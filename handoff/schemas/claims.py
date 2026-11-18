"""Claims: estado canonico interno + os contratos de handoff de A/B/C/D.

Distincao central do experimento:

* `CanonicalClaim` e o estado INTERNO, sempre completo. Nunca e o contrato de
  handoff -- ele existe para (a) receber a injecao de erro uma unica vez e
  (b) ser projetado nas 4 condicoes, garantindo que o estado incorreto seja
  literalmente o mesmo em A/B/C/D (passo 3 do protocolo).
* `ClaimB` / `ClaimC` / `ClaimD` sao os contratos de handoff. O conjunto de
  campos de cada um e exatamente o da secao 6 da proposta. A condicao A nao
  tem classe: seu payload e `str`.

Compatibilidade com Structured Outputs estrito da OpenAI: todo modelo usa
`extra="forbid"`, campos opcionais sao escritos como `X | None` e nao ha
default implicito em campo que o modelo precisa preencher.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from handoff import config
from handoff.conditions import CLAIM_ID_PREFIX, Condition, Stage

#: Unidades aceitas. Deliberadamente pequeno: unidade fora dessa lista e
#: violacao de contrato detectavel (ver serialization.validate_contract).
UNITS = ("USD_K", "USD_M", "USD_B", "PCT", "RATIO")

#: Tipo do campo `unit` nos contratos. Na rodada principal e `str`, e a lista
#: so aparece na descricao; com HANDOFF_STRICT_UNITS=1 vira Literal, e a
#: decodificacao restrita deixa de aceitar outra unidade.
Unit = Literal["USD_K", "USD_M", "USD_B", "PCT", "RATIO"] if config.STRICT_UNITS else str


# ==========================================================================
# Estado canonico (interno)
# ==========================================================================
class CanonicalClaim(BaseModel):
    """Menor unidade atomica de afirmacao factual que trafega no pipeline."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    metric: str
    value: float
    unit: str
    year: int
    period: str | None = None
    entity: str | None = None
    source_id: str
    page: int | None = None
    generated_by: Stage
    derived_from: list[str] = Field(default_factory=list)
    evidence: str | None = None


# ==========================================================================
# Contratos de handoff (secao 6 da proposta)
# ==========================================================================
class ClaimB(BaseModel):
    """B - typed. Estrutura, sem provenance e sem evidencia."""

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(description="Nome canonico da metrica, ex: revenue")
    value: float
    unit: Unit = Field(description=f"Uma de: {', '.join(UNITS)}")
    year: int


class ClaimE(ClaimB):
    """E - typed + evidence, sem lineage (condicao complementar)."""

    evidence: str = Field(description="Trecho literal do documento que sustenta o claim")


class ClaimC(ClaimB):
    """C - typed + lineage. source_id/page sao METADADOS: nao dereferenciaveis."""

    claim_id: str = Field(description="Id unico deste claim, ex: A01")
    source_id: str
    page: int | None
    generated_by: Stage
    derived_from: list[str] = Field(
        description="Ids dos claims de entrada que originaram este claim"
    )


class ClaimD(ClaimC):
    """D - typed + lineage + evidence."""

    evidence: str = Field(description="Trecho literal do documento que sustenta o claim")


CLAIM_SCHEMA: dict[Condition, type[BaseModel] | None] = {
    Condition.A: None,  # payload de A e str
    Condition.B: ClaimB,
    Condition.C: ClaimC,
    Condition.D: ClaimD,
    Condition.E: ClaimE,
    Condition.R: ClaimB,
    Condition.V: ClaimD,
}


# ==========================================================================
# Saidas por estagio
# ==========================================================================
class ExtractedClaim(BaseModel):
    """Saida bruta do Extrator.

    `claim_id`, `generated_by` e `derived_from` NAO sao pedidos ao modelo: sao
    atribuidos deterministicamente por nos (C01, C02, ...), o que evita
    colisao de ids e mantem o ground truth estavel entre execucoes.
    """

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(description="Nome canonico da metrica, ex: revenue")
    value: float = Field(description="Valor numerico exatamente como no documento")
    unit: str = Field(description=f"Uma de: {', '.join(UNITS)}")
    year: int = Field(description="Ano fiscal a que o valor se refere")
    period: str | None = Field(description="Ex: FY2023, Q3 2023; null se nao houver")
    entity: str | None = Field(description="Empresa a que o valor se refere")
    page: int | None = Field(description="Pagina do documento, null se desconhecida")
    evidence: str = Field(description="Trecho LITERAL do documento que sustenta o claim")


class ExtractorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ExtractedClaim]


def to_canonical(
    extracted: list[ExtractedClaim], source_id: str, stage: Stage = Stage.EXTRACTOR
) -> list[CanonicalClaim]:
    """Eleva a saida do Extrator ao estado canonico, atribuindo ids C01, C02..."""
    prefix = CLAIM_ID_PREFIX[stage]
    return [
        CanonicalClaim(
            claim_id=f"{prefix}{i:02d}",
            metric=c.metric,
            value=c.value,
            unit=c.unit,
            year=c.year,
            period=c.period,
            entity=c.entity,
            source_id=source_id,
            page=c.page,
            generated_by=stage,
            derived_from=[],
            evidence=c.evidence,
        )
        for i, c in enumerate(extracted, start=1)
    ]


class DerivedClaim(BaseModel):
    """Claim derivado, em forma canonica -- saida do Analista compartilhado.

    Usado quando a injecao acontece no estagio do Analista (subestudo de
    atribuicao de estagio da secao 7, e unico lugar onde existe claim em PCT,
    ja que o Extrator so extrai figuras brutas). Mesma logica do Extrator
    compartilhado: rodar uma vez em forma rica e projetar nas 4 condicoes.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(description="Id deste claim, no formato A01, A02, ...")
    metric: str
    value: float
    unit: str = Field(description=f"Uma de: {', '.join(UNITS)}")
    year: int
    period: str | None
    entity: str | None
    derived_from: list[str] = Field(description="Ids dos claims do extrator usados")
    evidence: str = Field(description="Evidencia herdada do claim de entrada usado")


class CanonicalAnalystOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[DerivedClaim]
    answer_claim_id: str = Field(description="Id do claim que responde a pergunta")


def derived_to_canonical(
    claims: list[DerivedClaim], source_id: str, page: int | None = None
) -> list[CanonicalClaim]:
    """Eleva a saida do Analista compartilhado ao estado canonico."""
    return [
        CanonicalClaim(
            claim_id=c.claim_id,
            metric=c.metric,
            value=c.value,
            unit=c.unit,
            year=c.year,
            period=c.period,
            entity=c.entity,
            source_id=source_id,
            page=page,
            generated_by=Stage.ANALYST,
            derived_from=c.derived_from,
            evidence=c.evidence,
        )
        for c in claims
    ]


class AnalystOutputB(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ClaimB]


class AnalystOutputE(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ClaimE]


class AnalystOutputR(BaseModel):
    """B com espaco para raciocinar antes dos claims (condicao R).

    `reasoning` vem PRIMEIRO de proposito: o modelo gera os campos na ordem do
    schema, entao o raciocinio precede os valores. So os `claims` seguem para
    o Redator, que recebe exatamente o mesmo handoff de B.
    """

    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(description="Raciocinio passo a passo antes dos claims")
    claims: list[ClaimB]


class AnalystOutputC(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ClaimC]
    answer_claim_id: str = Field(description="Id do claim que responde a pergunta")


class AnalystOutputD(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ClaimD]
    answer_claim_id: str = Field(description="Id do claim que responde a pergunta")


class WriterOutputB(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str = Field(description="Resposta final para o usuario, 1-3 frases")
    answer_claim: ClaimB


class WriterOutputE(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str = Field(description="Resposta final para o usuario, 1-3 frases")
    answer_claim: ClaimE


class WriterOutputC(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str = Field(description="Resposta final para o usuario, 1-3 frases")
    answer_claim: ClaimC


class WriterOutputD(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str = Field(description="Resposta final para o usuario, 1-3 frases")
    answer_claim: ClaimD


#: Schema de saida por (condicao, estagio). None => agente sem `output_schema`,
#: isto e, texto livre (condicao A).
STAGE_SCHEMA: dict[tuple[Condition, Stage], type[BaseModel] | None] = {
    (Condition.A, Stage.ANALYST): None,
    (Condition.B, Stage.ANALYST): AnalystOutputB,
    (Condition.C, Stage.ANALYST): AnalystOutputC,
    (Condition.D, Stage.ANALYST): AnalystOutputD,
    (Condition.A, Stage.WRITER): None,
    (Condition.B, Stage.WRITER): WriterOutputB,
    (Condition.C, Stage.WRITER): WriterOutputC,
    (Condition.D, Stage.WRITER): WriterOutputD,
    (Condition.E, Stage.ANALYST): AnalystOutputE,
    (Condition.E, Stage.WRITER): WriterOutputE,
    (Condition.R, Stage.ANALYST): AnalystOutputR,
    (Condition.R, Stage.WRITER): WriterOutputB,
    (Condition.V, Stage.ANALYST): AnalystOutputD,
    (Condition.V, Stage.WRITER): WriterOutputD,
}

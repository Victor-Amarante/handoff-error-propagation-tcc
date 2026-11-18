"""Condicoes experimentais e estagios do pipeline.

A unica variavel manipulada no experimento e o contrato de handoff:

    A - free text          (sem estrutura, sem lineage, sem evidencia)
    B - typed              (estrutura)
    C - typed + lineage    (estrutura + provenance, SEM acesso a fonte)
    D - typed + lineage + evidence

Condicoes complementares, pedidas no parecer do orientador e rodadas a parte
(logs em data/<modelo>/logs_parecer/), nunca misturadas as quatro principais:

    E - typed + evidence, SEM lineage  (fecha o fatorial lineage x evidencia)
    R - B com um campo `reasoning` no schema do Analista (so controle)
    V - D com instrucao explicita de conferir o valor contra a evidencia

Controle de validade interna (secao 8.4 da proposta): em C, `source_id` e
`page` sao apenas metadados -- o downstream nao pode dereferenciar a fonte.
Isso e garantido por construcao: nenhum estagio downstream recebe o documento
e nenhum agente tem tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Condition(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    R = "R"
    V = "V"


#: As quatro condicoes do desenho principal (RQ1-RQ3).
MAIN_CONDITIONS: tuple["Condition", ...] = (Condition.A, Condition.B, Condition.C, Condition.D)


class Stage(StrEnum):
    EXTRACTOR = "extractor"
    ANALYST = "analyst"
    WRITER = "writer"


#: Estagios executados por condicao. O Extrator roda uma unica vez por
#: (pergunta x seed) e o estado extraido e compartilhado pelas 4 condicoes,
#: de modo que o erro injetado seja literalmente o mesmo em A/B/C/D.
DOWNSTREAM_STAGES: tuple[Stage, ...] = (Stage.ANALYST, Stage.WRITER)

STAGE_INDEX: dict[Stage, int] = {
    Stage.EXTRACTOR: 0,
    Stage.ANALYST: 1,
    Stage.WRITER: 2,
}

#: Prefixo do claim_id por estagio. Torna o estagio de origem legivel no id
#: e evita colisao entre ids gerados por estagios diferentes.
CLAIM_ID_PREFIX: dict[Stage, str] = {
    Stage.EXTRACTOR: "C",
    Stage.ANALYST: "A",
    Stage.WRITER: "W",
}


@dataclass(frozen=True)
class Capabilities:
    """O que o contrato daquela condicao carrega no handoff."""

    structure: bool
    lineage: bool
    evidence: bool


CAPS: dict[Condition, Capabilities] = {
    Condition.A: Capabilities(structure=False, lineage=False, evidence=False),
    Condition.B: Capabilities(structure=True, lineage=False, evidence=False),
    Condition.C: Capabilities(structure=True, lineage=True, evidence=False),
    Condition.D: Capabilities(structure=True, lineage=True, evidence=True),
    Condition.E: Capabilities(structure=True, lineage=False, evidence=True),
    Condition.R: Capabilities(structure=True, lineage=False, evidence=False),
    Condition.V: Capabilities(structure=True, lineage=True, evidence=True),
}


def caps(condition: Condition) -> Capabilities:
    return CAPS[Condition(condition)]


def stage_from_claim_id(claim_id: str) -> Stage | None:
    """Inverte CLAIM_ID_PREFIX: 'C08' -> extractor, 'A02' -> analyst."""
    for stage, prefix in CLAIM_ID_PREFIX.items():
        if claim_id.upper().startswith(prefix):
            return stage
    return None

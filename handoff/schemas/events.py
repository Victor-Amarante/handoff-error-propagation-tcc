"""Schema do log JSONL -- um evento por estagio do pipeline.

O log e a unica fonte de dados da fase de analise. Regra de ouro: nada e
calculado aqui, tudo que qualquer metrica possa exigir e gravado cru.

Sequencia de eventos de uma celula experimental:

    run_start -> stage_output(extractor) -> injection
              -> stage_output(analyst) -> stage_output(writer)
              -> audit -> run_end

Cobertura das metricas (secao 9 da proposta):

| Metrica                     | Campos                                             |
|-----------------------------|----------------------------------------------------|
| Final Factual Accuracy      | run_end.output_raw + gold.answer                   |
| acuracia por tipo de erro   | error_type (em todo evento)                        |
| Correction Rate             | injection.original_value vs resposta final         |
| ESR                         | injection.corrupted_value vs writer.output_raw     |
| Propagation Depth           | claims/output_raw/derived_from por stage_output    |
| Error Amplification         | claims por estagio + derived_from                  |
| RCCA / FESA                 | audit_report x injection (target_claim_id, stage)  |
| Schema Validity             | schema_valid, schema_errors, contract_checks       |
| Custo                       | usage por evento; auditor isolado em event_type    |
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from handoff.conditions import Condition, Stage

EventType = Literal["run_start", "stage_output", "injection", "audit", "run_end"]
ErrorType = Literal["value", "percentage", "metadata"]


class Usage(BaseModel):
    """Custo operacional de uma chamada ao modelo."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: float | None = None
    n_calls: int = 1
    raw: dict = Field(default_factory=dict, description="RunMetrics.to_dict() verbatim")


class InjectionRecord(BaseModel):
    """Ground truth da perturbacao. Nunca e mostrado a nenhum agente."""

    error_type: ErrorType
    error_subtype: str
    rule: str = Field(description="Descricao textual da regra deterministica aplicada")
    selection_rule: str = Field(description="Como o claim-alvo foi escolhido")
    stage_injected: Stage
    target_claim_id: str
    field: str
    original_value: float | int | str
    corrupted_value: float | int | str
    original_claim: dict
    corrupted_claim: dict


class GoldRecord(BaseModel):
    """Verdade do benchmark. Nunca e mostrada ao pipeline nem ao auditor."""

    question_id: str
    question: str
    answer: str
    evidence: str
    doc_id: str


class LogEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    run_id: str
    event_id: str
    ts: str = Field(description="UTC ISO-8601")

    # --- identidade da celula experimental -------------------------------
    condition: Condition
    seed: int
    question_id: str
    doc_id: str
    error_type: ErrorType | None = None
    injection_stage: Stage | None = None

    # --- evento -----------------------------------------------------------
    event_type: EventType
    stage: Stage | None = None
    stage_index: int | None = None

    # --- conteudo ---------------------------------------------------------
    input_payload: dict | list | str | None = None
    handoff_payload: dict | list | str | None = None
    output_raw: str | None = Field(
        default=None, description="Texto bruto do modelo, gravado em toda condicao"
    )
    output_parsed: dict | None = None
    claims: list[dict] = Field(default_factory=list)

    # --- validade estrutural ---------------------------------------------
    schema_name: str | None = None
    schema_valid: bool | None = Field(
        default=None, description="None na condicao A (nao ha contrato estrutural)"
    )
    schema_errors: list[str] = Field(default_factory=list)
    parse_retries: int = 0
    contract_checks: dict = Field(
        default_factory=dict,
        description="Violacoes que nenhum JSON Schema pega (derived_from pendente etc)",
    )

    # --- custo -------------------------------------------------------------
    model: str
    model_params: dict = Field(default_factory=dict)
    usage: Usage | None = None

    # --- ground truth e avaliacao ----------------------------------------
    injection: InjectionRecord | None = None
    gold: GoldRecord | None = None
    audit_report: dict | None = None
    notes: dict[str, Any] = Field(default_factory=dict)

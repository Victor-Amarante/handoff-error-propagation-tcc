"""Instrumento de medida de root-cause observability.

`RootCauseReport` e o UNICO schema constante nas 4 condicoes. Ele nao e um
contrato de handoff -- e o instrumento. O que varia entre A/B/C/D e a ENTRADA
do auditor (o que o contrato daquela condicao preservou), nunca o formato da
resposta. Isso e o que torna RCCA e FESA comparaveis entre condicoes.

`reported_metric` / `reported_value` existem para permitir matching automatico
em A e B, onde nao ha `claim_id` para comparar com o ground truth.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RootCauseReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_error_stage: Literal["extractor", "analyst", "writer", "none"] = Field(
        description="Estagio em que o primeiro erro apareceu; 'none' se nao ha erro"
    )
    root_cause_claim_id: str | None = Field(
        description="Id do claim que iniciou a cadeia de erro; null se nao houver ids"
    )
    root_cause_claim_text: str = Field(
        description="Descricao em linguagem natural do claim que iniciou o erro"
    )
    reported_metric: str | None = Field(description="Metrica do claim de origem")
    reported_value: float | None = Field(description="Valor incorreto do claim de origem")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="Justificativa curta da atribuicao")

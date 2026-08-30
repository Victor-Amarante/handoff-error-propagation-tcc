"""Configuracao unica do experimento.

Tudo que precisa permanecer CONSTANTE entre as 4 condicoes mora aqui, para
que o desenho experimental seja auditavel a partir de um unico arquivo.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SUBSET_PATH = DATA_DIR / "financebench" / "subset.jsonl"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"


def ensure_dirs() -> None:
    for d in (SUBSET_PATH.parent, CACHE_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Modelo -- constante nas 4 condicoes (exigencia do desenho experimental)
# --------------------------------------------------------------------------
MODEL_ID = os.getenv("HANDOFF_MODEL", "gpt-5.6-luna")

#: Temperatura. Alguns modelos de reasoning rejeitam o parametro; nesse caso
#: defina HANDOFF_TEMPERATURE="" para omiti-lo da requisicao.
_temp_raw = os.getenv("HANDOFF_TEMPERATURE", "0.0")
TEMPERATURE: float | None = float(_temp_raw) if _temp_raw.strip() != "" else None

#: Envia `seed` a API (best-effort do lado da OpenAI). Se o modelo rejeitar,
#: defina HANDOFF_SEND_SEED=0 -- a seed continua identificando a replica no log.
SEND_SEED = os.getenv("HANDOFF_SEND_SEED", "1") == "1"

#: Esforco de raciocinio. Como tudo que nao e o contrato de handoff, precisa
#: ser CONSTANTE nas 4 condicoes -- e um confundidor de primeira ordem: mais
#: esforco significa mais chance de o estagio detectar o erro injetado por
#: conta propria, o que comprimiria as diferencas entre A/B/C/D. Tambem entra
#: direto no custo, porque reasoning tokens sao cobrados como output.
REASONING_EFFORT = os.getenv("HANDOFF_REASONING_EFFORT", "medium") or None

#: True  -> structured outputs nativo (decodificacao restrita): Schema Validity
#:          de B/C/D e ~1.0 por construcao.
#: False -> JSON mode sem restricao de gramatica: Schema Validity vira uma
#:          medida nao-trivial, ao custo de nao seguir o CONTEXT.md secao 11.
#: Em qualquer modo, as checagens de contrato de `serialization.validate_contract`
#: (derived_from pendente, ids duplicados, evidencia nao-literal) continuam
#: valendo -- sao violacoes que nenhum JSON Schema pega.
STRICT_OUTPUT = os.getenv("HANDOFF_STRICT_OUTPUT", "1") == "1"

#: Replicas do experimento. Tambem viram o `seed` enviado a API.
SEEDS: tuple[int, ...] = (1, 2, 3)

PIPELINE_VERSION = "1.0.0"
LOG_SCHEMA_VERSION = "1"


def model_params() -> dict:
    """Snapshot dos parametros do modelo, gravado em todo evento do log."""
    return {
        "model_id": MODEL_ID,
        "temperature": TEMPERATURE,
        "reasoning_effort": REASONING_EFFORT,
        "strict_output": STRICT_OUTPUT,
        "send_seed": SEND_SEED,
        "pipeline_version": PIPELINE_VERSION,
    }


# --------------------------------------------------------------------------
# Custo
# --------------------------------------------------------------------------
#: USD por 1 milhao de tokens, da tabela oficial da OpenAI. Modelo fora desta
#: tabela faz `estimate_cost` devolver None -- a analise ainda funciona, so
#: perde a dimensao monetaria (tokens sao sempre registrados).
PRICE_PER_MTOK: dict[str, dict[str, float]] = {
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float | None:
    """Custo em USD, ou None se o modelo nao esta na tabela de precos."""
    price = PRICE_PER_MTOK.get(model)
    if price is None:
        return None
    uncached = max(input_tokens - cached_tokens, 0)
    return (
        uncached * price["input"]
        + cached_tokens * price.get("cached_input", price["input"])
        + output_tokens * price["output"]
    ) / 1_000_000

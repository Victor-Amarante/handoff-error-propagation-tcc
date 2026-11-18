"""Configuracao unica do experimento.

Tudo que precisa permanecer CONSTANTE entre as 4 condicoes mora aqui, para
que o desenho experimental seja auditavel a partir de um unico arquivo.

Cada execucao usa UM modelo (um dos tres experimentos: GPT/Luna, Claude/Haiku,
SLM local/Qwen via Ollama). O modelo nao e uma variavel manipulada dentro de
um experimento -- e o eixo que separa os tres experimentos entre si. Por isso
os artefatos de cada um (cache do Extrator/Analista, logs de celula) vivem em
`data/<slug-do-modelo>/`, nunca misturados.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

#: Compartilhado pelos tres experimentos: as perguntas sao as mesmas, so o
#: modelo muda. Nunca fica dentro da pasta de um modelo especifico.
SUBSET_PATH = DATA_DIR / "financebench" / "subset.jsonl"


def _slugify(model_id: str) -> str:
    """'claude-haiku-4-5-20251001' -> mesmo nome; 'qwen3.5:9b-mlx' -> 'qwen3.5-9b-mlx'.

    So troca caracteres que nao servem em nome de pasta (':', '/'); mantem o
    resto do model_id reconhecivel, para que a pasta aponte sem ambiguidade
    para o mesmo nome gravado em `model_params.model_id` de cada evento.
    """
    return re.sub(r"[:/\\]+", "-", model_id)


# --------------------------------------------------------------------------
# Provedor e modelo -- constantes DENTRO de um experimento
# --------------------------------------------------------------------------
#: "openai" | "anthropic" | "ollama". Seleciona o client Agno em handoff/stages.py.
PROVIDER = os.getenv("HANDOFF_PROVIDER", "openai")

MODEL_ID = os.getenv("HANDOFF_MODEL", "gpt-5.6-luna")

#: Nome de pasta derivado do model_id -- pode ser sobrescrito explicitamente
#: (HANDOFF_MODEL_SLUG) se dois experimentos usassem o mesmo model_id com
#: configuracoes diferentes, o que nao e o caso aqui.
MODEL_SLUG = os.getenv("HANDOFF_MODEL_SLUG") or _slugify(MODEL_ID)

MODEL_DIR = DATA_DIR / MODEL_SLUG
CACHE_DIR = MODEL_DIR / "cache"
#: Rodadas complementares (parecer do orientador) gravam numa subpasta propria,
#: ex. HANDOFF_LOG_SUBDIR=logs_parecer, mas reaproveitam o MESMO cache do
#: Extrator: o estado corrompido continua identico ao da rodada principal.
LOG_DIR = MODEL_DIR / (os.getenv("HANDOFF_LOG_SUBDIR") or "logs")


def ensure_dirs() -> None:
    for d in (SUBSET_PATH.parent, CACHE_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Parametros de geracao -- o que cada provedor aceita difere, entao cada um
# tem seu proprio bloco. O principio continua o mesmo do desenho original:
# tudo aqui e constante nas 4 condicoes (A/B/C/D) DENTRO do experimento do
# provedor ativo.
# --------------------------------------------------------------------------

#: Temperatura. gpt-5.6-luna rejeita temperature=0 (so aceita o default, 1),
#: entao o valor default aqui e None -- omitido da requisicao. Vale para os
#: tres provedores: None sempre significa "nao enviar o parametro".
_temp_raw = os.getenv("HANDOFF_TEMPERATURE", "")
TEMPERATURE: float | None = float(_temp_raw) if _temp_raw.strip() != "" else None

# ---- OpenAI (gpt-5.6-luna) ------------------------------------------------
#: Envia `seed` a API (best-effort). Omitido para Anthropic (a API nao aceita
#: o parametro); usado em Ollama via `options.seed` (tambem best-effort).
SEND_SEED = os.getenv("HANDOFF_SEND_SEED", "1") == "1"

#: Esforco de raciocinio da OpenAI. Confundidor de primeira ordem (CONTEXT.md
#: 11.4): mais esforco aumenta a chance do proprio estagio corrigir o erro
#: sozinho, o que comprimiria as diferencas entre A/B/C/D. So se aplica ao
#: provedor "openai" -- Claude e Ollama tem seus proprios mecanismos abaixo.
REASONING_EFFORT = os.getenv("HANDOFF_REASONING_EFFORT", "medium") or None

#: True -> structured outputs nativo (Schema Validity de B/C/D ~1.0 por
#: construcao). So se aplica a "openai"; Claude/Ollama usam saida estruturada
#: nativa sempre que o modelo suporta (Agno decide isso sozinho).
STRICT_OUTPUT = os.getenv("HANDOFF_STRICT_OUTPUT", "1") == "1"

# ---- Anthropic (Claude Haiku 4.5) -----------------------------------------
#: Extended thinking do Claude. None (desligado) por padrao: mantem o
#: experimento Claude no mesmo espirito de "esforco moderado, constante nas 4
#: condicoes" do reasoning_effort="medium" da OpenAI, e Haiku 4.5 e vendido
#: como o modelo RAPIDO da familia -- ligar thinking native descaracterizaria
#: essa escolha. Para ligar: HANDOFF_CLAUDE_THINKING_BUDGET=<int tokens>.
_claude_budget = os.getenv("HANDOFF_CLAUDE_THINKING_BUDGET", "")
CLAUDE_THINKING: dict | None = (
    {"type": "enabled", "budget_tokens": int(_claude_budget)}
    if _claude_budget.strip()
    else None
)
CLAUDE_MAX_TOKENS = int(os.getenv("HANDOFF_CLAUDE_MAX_TOKENS", "4096"))

# ---- Ollama (SLM local, qwen3.5:9b -- NAO a tag "-mlx", ver nota abaixo) --
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
#: Qwen3 e hibrido (pensa ou nao, por chamada). Mantido desligado pelo mesmo
#: motivo do Claude acima -- constante e comparavel aos outros dois
#: experimentos, sem introduzir um eixo de "esforco" que eles nao tem.
OLLAMA_THINK = os.getenv("HANDOFF_OLLAMA_THINK", "0") == "1"
#: Penalidade de presenca enviada ao Ollama. Vazio = nao enviar, e vale o
#: padrao da tag (1.5 em qwen3.5:9b, ver `ollama show --parameters`). A rodada
#: principal nao enviou o parametro.
_pp_raw = os.getenv("HANDOFF_OLLAMA_PRESENCE_PENALTY", "")
OLLAMA_PRESENCE_PENALTY: float | None = float(_pp_raw) if _pp_raw.strip() else None

#: 1 = campo `unit` como Literal no schema, e a decodificacao restrita passa a
#: impedir unidade fora da lista. A rodada principal usou texto livre (0).
STRICT_UNITS = os.getenv("HANDOFF_STRICT_UNITS", "0") == "1"


def model_params() -> dict:
    """Snapshot dos parametros do modelo, gravado em todo evento do log.

    O conjunto de chaves muda por provedor -- gravar `reasoning_effort` para
    uma rodada Claude seria mentir sobre um parametro que nao existe ali.
    """
    base = {
        "provider": PROVIDER,
        "model_id": MODEL_ID,
        "temperature": TEMPERATURE,
        "pipeline_version": PIPELINE_VERSION,
    }
    if PROVIDER == "openai":
        base.update(
            {
                "reasoning_effort": REASONING_EFFORT,
                "strict_output": STRICT_OUTPUT,
                "send_seed": SEND_SEED,
            }
        )
    elif PROVIDER == "anthropic":
        base.update({"thinking": CLAUDE_THINKING, "max_tokens": CLAUDE_MAX_TOKENS})
    elif PROVIDER == "ollama":
        base.update({"think": OLLAMA_THINK, "send_seed": SEND_SEED, "host": OLLAMA_HOST,
                     "presence_penalty": OLLAMA_PRESENCE_PENALTY})
    base["strict_units"] = STRICT_UNITS
    return base


PIPELINE_VERSION = "1.0.0"
LOG_SCHEMA_VERSION = "1"

#: Replicas do experimento. Tambem viram o `seed` enviado a API quando
#: SEND_SEED=1 (OpenAI/Ollama; Anthropic nao aceita o parametro).
SEEDS: tuple[int, ...] = (1, 2, 3)


# --------------------------------------------------------------------------
# Custo
# --------------------------------------------------------------------------
#: USD por 1 milhao de tokens. Modelo fora desta tabela faz `estimate_cost`
#: devolver None -- a analise ainda funciona, so perde a dimensao monetaria
#: (tokens sao sempre registrados). Qwen local fica a zero: sem custo de API,
#: mas os tokens continuam contados para comparar overhead operacional.
PRICE_PER_MTOK: dict[str, dict[str, float]] = {
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    # qwen3.5:9b -- NAO a tag "-mlx": essa usa quantizacao nvfp4, que o motor
    # de JSON Schema do Ollama ignora silenciosamente (medido no piloto,
    # ver README). A tag padrao (Q4_K_M) respeita o schema corretamente.
    "qwen3.5:9b": {"input": 0.0, "cached_input": 0.0, "output": 0.0},
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

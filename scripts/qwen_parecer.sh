#!/usr/bin/env bash
# Rodadas do Qwen pedidas no parecer (itens A5 e B7). De preferencia na mesma
# maquina da rodada principal (Ollama + qwen3.5:9b, RTX 3090). O cache do
# Extrator e refeito a partir dos logs, entao o estado corrompido e o mesmo.
#
#   bash scripts/qwen_parecer.sh
#
# Custo: zero (local). Tempo estimado na RTX 3090: cerca de 1 hora (~11 s por celula).
set -euo pipefail
cd "$(dirname "$0")/.."
export HANDOFF_PROVIDER=ollama HANDOFF_MODEL=qwen3.5:9b
uv run python scripts/cache_from_logs.py qwen3.5-9b

# A5: condicao B' (campo `reasoning` no Analista), so controles. Compara a
# acuracia do controle de B' com a de A e B da rodada principal.
HANDOFF_LOG_SUBDIR=logs_parecer \
  uv run python scripts/run_experiment.py --conditions R --error-types "" --include-clean --cache-only

# B7: unidade como Literal no schema e penalidade de presenca zerada, nas
# condicoes B e C, com controle e os dois bracos de erro, 30 perguntas.
HANDOFF_LOG_SUBDIR=logs_strict_units HANDOFF_STRICT_UNITS=1 HANDOFF_OLLAMA_PRESENCE_PENALTY=0 \
  uv run python scripts/run_experiment.py --conditions B,C --include-clean --cache-only --questions 30

echo "pronto. Rode: uv run python scripts/build_complementares.py"

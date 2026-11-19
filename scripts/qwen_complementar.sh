#!/usr/bin/env bash
# Rodadas do Qwen que faltavam para igualar os modelos de API (parecer A2, A3
# e insight 1). Mesma maquina da rodada principal (Ollama + qwen3.5:9b, RTX
# 3090). O cache do Extrator e refeito a partir dos logs, entao o estado
# corrompido e o mesmo da rodada principal.
#
#   bash scripts/qwen_complementar.sh 2>&1 | tee qwen_complementar.log
#
# Custo: zero (local). Tempo estimado na RTX 3090: cerca de 3 horas
# (~10 s por celula). Se parar no meio, rode de novo: celulas completas
# sao puladas.
set -euo pipefail
cd "$(dirname "$0")/.."
export HANDOFF_PROVIDER=ollama HANDOFF_MODEL=qwen3.5:9b
uv run python scripts/cache_from_logs.py qwen3.5-9b

# A2: teste A/A, replica dos controles de A-D em 50 perguntas (~35 min).
# Vem primeiro por ser o que fecha a lacuna da RQ1 no Qwen.
HANDOFF_LOG_SUBDIR=logs_aa \
  uv run python scripts/run_experiment.py --conditions A,B,C,D --error-types "" --include-clean --cache-only --questions 50

# A3 e insight 1: condicoes E (tipado + evidencia, sem lineage) e V (D com
# instrucao de conferencia), com controle e os dois bracos de erro (~2h30).
HANDOFF_LOG_SUBDIR=logs_parecer \
  uv run python scripts/run_experiment.py --conditions E,V --include-clean --cache-only

echo "pronto. Confira: ls data/qwen3.5-9b/logs_aa | wc -l  (esperado 200)"
echo "                 ls data/qwen3.5-9b/logs_parecer | wc -l  (esperado 1044: 150 de R + 894 de E e V)"

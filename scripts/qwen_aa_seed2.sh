#!/usr/bin/env bash
# Teste A/A do Qwen com outra seed (parecer A2). No Ollama, a replica com a
# mesma seed da rodada principal (data/qwen3.5-9b/logs_aa) saiu identica byte
# a byte ao controle, entao nao mede ruido de amostragem. Aqui o Extrator usa o
# estado da seed 1 (cache) e Analista, Redator e auditor sorteiam com a seed 2.
#
#   bash scripts/qwen_aa_seed2.sh 2>&1 | tee qwen_aa_seed2.log
#
# Custo: zero (local). Tempo na RTX 3090: cerca de 50 min (200 celulas).
set -euo pipefail
cd "$(dirname "$0")/.."
export HANDOFF_PROVIDER=ollama HANDOFF_MODEL=qwen3.5:9b
uv run python scripts/cache_from_logs.py qwen3.5-9b
HANDOFF_LOG_SUBDIR=logs_aa_seed2 \
  uv run python scripts/run_experiment.py --conditions A,B,C,D --error-types "" --include-clean --cache-only --questions 50 --stage-seed 2
echo "pronto. Confira: ls data/qwen3.5-9b/logs_aa_seed2 | wc -l  (esperado 200)"

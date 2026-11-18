"""Reconstroi o cache do Extrator a partir dos logs de uma rodada.

O evento `stage_output` do Extrator grava o estado canonico completo, entao o
cache pode ser refeito em outra maquina sem chamar o modelo de novo, e o estado
corrompido das rodadas complementares continua identico ao da principal.

Uso: uv run python scripts/cache_from_logs.py qwen3.5-9b
"""
import json
import sys
from pathlib import Path

slug = sys.argv[1]
logs = Path("data") / slug / "logs"
cache = Path("data") / slug / "cache"
cache.mkdir(parents=True, exist_ok=True)
done = 0
for path in sorted(logs.glob("run_*_clean_A_seed*.jsonl")):
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["event_type"] == "stage_output" and e.get("stage") == "extractor":
            out = cache / f"extract_{e['question_id'].replace('/', '_')}_seed{e['seed']}.json"
            if not out.exists():
                usage = e.get("usage") or (e.get("notes") or {}).get("usage_when_cached")
                out.write_text(json.dumps({"question_id": e["question_id"], "seed": e["seed"],
                                           "claims": e["claims"], "output_raw": e.get("output_raw"),
                                           "usage": usage}, ensure_ascii=False, indent=2), encoding="utf-8")
                done += 1
            break
print(f"{done} estados gravados em {cache}")

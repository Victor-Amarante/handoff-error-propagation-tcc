"""Reauditoria cruzada (item B2 do parecer): o auditor de UM modelo le os
traces ja gravados de OUTRO pipeline.

Nada do pipeline roda de novo. O trace e reconstruido dos logs exatamente
como `run.run_cell` o montou para o auditor original -- handoff do Extrator
(o corrompido, se houve injecao), handoff do Analista e handoff do Redator --
e entregue ao auditor do provedor ativo (HANDOFF_PROVIDER/HANDOFF_MODEL).

Uso (auditor GPT sobre os traces do Haiku):
    HANDOFF_PROVIDER=openai HANDOFF_MODEL=gpt-5.6-luna \\
        uv run python scripts/reaudit.py --pipeline claude-haiku-4-5-20251001

Saida: data/<pipeline>/reaudit_<auditor>/<nome-do-log>.json, uma por celula.
Retoma por padrao: celulas ja reauditadas sao puladas.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handoff import config  # noqa: E402
from handoff.auditor import build_trace  # noqa: E402
from handoff.conditions import MAIN_CONDITIONS, Condition, Stage  # noqa: E402
from handoff.logger import is_complete  # noqa: E402
from handoff.schemas.claims import CanonicalClaim  # noqa: E402
from handoff.serialization import to_handoff  # noqa: E402
from handoff.stages import run_auditor  # noqa: E402


def reconstruct(path: Path) -> dict:
    """(pergunta, trace, resposta final) de uma celula do estudo principal."""
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    head = events[0]
    condition = Condition(head["condition"])
    by_type = {}
    for e in events:
        key = (e["event_type"], e.get("stage"))
        by_type[key] = e
    extractor = by_type[("stage_output", "extractor")]
    injection = by_type.get(("injection", "extractor"))
    if injection is not None:
        first = injection["handoff_payload"]
    else:
        claims = [CanonicalClaim.model_validate(c) for c in extractor["claims"]]
        first = to_handoff(claims, condition)
    handoffs = [
        (Stage.EXTRACTOR, first),
        (Stage.ANALYST, by_type[("stage_output", "analyst")]["handoff_payload"]),
        (Stage.WRITER, by_type[("stage_output", "writer")]["handoff_payload"]),
    ]
    end = by_type[("run_end", None)]
    original = by_type[("audit", None)]
    return {
        "question": head["gold"]["question"] if head.get("gold") else end["gold"]["question"],
        "trace": build_trace(handoffs),
        "final_answer": end.get("output_raw") or "",
        "seed": head["seed"],
        "original_audit_usage": original.get("usage"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipeline", required=True, help="slug do modelo cujos traces serao lidos")
    parser.add_argument("--shard", default="0/1")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logs = config.DATA_DIR / args.pipeline / "logs"
    out = config.DATA_DIR / args.pipeline / f"reaudit_{config.MODEL_SLUG}"
    out.mkdir(parents=True, exist_ok=True)
    conds = {str(c) for c in MAIN_CONDITIONS}
    paths = [
        p for p in sorted(logs.glob("run_*.jsonl"))
        if "_atanalyst_" not in p.name and p.stem.rsplit("_", 2)[-2] in conds and is_complete(p)
    ]
    k, n = (int(x) for x in args.shard.split("/"))
    pending = [p for p in paths if not (out / f"{p.stem}.json").exists()][k::n][: args.limit]
    print(f"auditor={config.MODEL_ID} pipeline={args.pipeline}: {len(pending)} pendentes de {len(paths)}")

    cost = 0.0
    for i, path in enumerate(pending, 1):
        try:
            cell = reconstruct(path)
            result = run_auditor(cell["question"], cell["trace"], cell["final_answer"], cell["seed"])
        except Exception as exc:  # noqa: BLE001 -- celula fica pendente e a retomada refaz
            print(f"  ERRO {path.name}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        report = result.content.model_dump(mode="json") if hasattr(result.content, "model_dump") else None
        usage = result.usage.model_dump() if result.usage else None
        cost += (usage or {}).get("cost_usd") or 0.0
        (out / f"{path.stem}.json").write_text(json.dumps({
            "log": path.name,
            "auditor_model": config.MODEL_ID,
            "audit_report": report,
            "schema_valid": result.schema_valid,
            "usage": usage,
            "original_audit_usage": cell["original_audit_usage"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if i % 50 == 0:
            print(f"  ... {i}/{len(pending)}  US$ {cost:.3f}")
    print(f"fim: US$ {cost:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

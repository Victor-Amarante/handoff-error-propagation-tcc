"""Piloto: poucas perguntas x 4 condicoes, para validar o end-to-end.

    uv run python scripts/run_pilot.py --questions 2 --error-type value

O Extrator roda uma vez por (pergunta x seed) e o resultado e cacheado, de
modo que as 4 condicoes partam do mesmo estado antes da injecao.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handoff import config  # noqa: E402
from handoff.conditions import Condition, Stage  # noqa: E402
from handoff.injector import ERROR_TYPES, InjectionError  # noqa: E402
from handoff.run import analyze_state, extract_state, run_cell  # noqa: E402


def load_subset(limit: int) -> list[dict]:
    if not config.SUBSET_PATH.exists():
        raise SystemExit(
            f"{config.SUBSET_PATH} nao existe. Rode scripts/build_subset.py primeiro."
        )
    rows = [
        json.loads(line)
        for line in config.SUBSET_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return rows[:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=int, default=2)
    parser.add_argument(
        "--error-type",
        default="value",
        choices=[*ERROR_TYPES, "none"],
        help="'none' roda o braco de controle: mesmo estado, sem injecao",
    )
    parser.add_argument("--seed", type=int, default=config.SEEDS[0])
    parser.add_argument(
        "--conditions", default="A,B,C,D", help="lista separada por virgula"
    )
    parser.add_argument(
        "--injection-stage", default="extractor", choices=["extractor", "analyst"]
    )
    parser.add_argument(
        "--metadata-subtype", default="year_shift", choices=["year_shift", "unit_shift"]
    )
    args = parser.parse_args()
    stage = Stage(args.injection_stage)

    conditions = [Condition(c.strip()) for c in args.conditions.split(",")]
    error_type = None if args.error_type == "none" else args.error_type
    rows = load_subset(args.questions)
    print(f"modelo={config.MODEL_ID} seed={args.seed} erro={args.error_type}")

    for row in rows:
        extraction = extract_state(row, args.seed)
        analysis = (
            analyze_state(row, args.seed, extraction) if stage is Stage.ANALYST else None
        )
        alvo = analysis or extraction
        print(
            f"\n[{row['question_id']}] {len(alvo.claims)} claims em {alvo.stage} "
            f"(cache={alvo.from_cache})"
        )
        for condition in conditions:
            try:
                out = run_cell(
                    row,
                    args.seed,
                    error_type,  # type: ignore[arg-type]
                    condition,
                    extraction=extraction,
                    analysis=analysis,
                    injection_stage=stage,
                    metadata_subtype=args.metadata_subtype,
                )
            except InjectionError as exc:
                # Pergunta inutilizavel para este tipo de erro: reportar e
                # seguir. Excluir a pergunta e decisao de analise, nao um crash.
                print(f"  {condition}: PULADA -- {exc}")
                continue

            report = out["audit_report"] or {}
            gt = out["injection"]
            gt_text = (
                f"(gt: stage={gt['stage_injected']} claim={gt['target_claim_id']})"
                if gt
                else "(controle, sem injecao)"
            )
            print(
                f"  {condition}: {out['path'].name}\n"
                f"     final: {(out['final_answer'] or '')[:110]}\n"
                f"     audit: stage={report.get('first_error_stage')} "
                f"claim={report.get('root_cause_claim_id')} {gt_text}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

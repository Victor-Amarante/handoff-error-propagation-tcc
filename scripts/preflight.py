"""Valida o subset ANTES de rodar a matriz completa.

Roda so o Extrator (cacheado, entao o custo e reaproveitado pelo experimento) e
responde offline, por pergunta:

* a extracao funcionou e produziu claims?
* quantos claims tem valor literal na evidencia (elegiveis para injecao)?
* cada classe de erro consegue um alvo?

    uv run python scripts/preflight.py
    uv run python scripts/preflight.py --with-analyst   # +1 chamada/pergunta,
                                                        # valida o subestudo
Perguntas sem alvo para uma classe de erro nao sao um bug: sao perguntas a
excluir daquele braco, e e melhor descobrir isso agora que em 480 celulas.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handoff import config  # noqa: E402
from handoff.conditions import Stage  # noqa: E402
from handoff.injector import ERROR_TYPES, InjectionError, inject  # noqa: E402
from handoff.run import PipelineError, analyze_state, extract_state  # noqa: E402
from handoff.serialization import verify_extraction  # noqa: E402


def probe(claims, eligible_ids, gold_answer: str) -> dict[str, str]:
    """Cada classe de erro consegue um alvo neste estado?"""
    out = {}
    for error_type in ERROR_TYPES:
        try:
            _, record = inject(
                claims, error_type, gold_answer=gold_answer, eligible_ids=eligible_ids
            )
            out[error_type] = f"{record.target_claim_id} {record.original_value}->{record.corrupted_value}"
        except InjectionError:
            out[error_type] = "-"
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=config.SEEDS[0])
    parser.add_argument("--questions", type=int, default=None)
    parser.add_argument("--with-analyst", action="store_true")
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in config.SUBSET_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.questions:
        rows = rows[: args.questions]

    tally: Counter = Counter()
    print(f"{'pergunta':<24} {'claims':>7} {'verif':>6} | {'value':<22} {'percentage':<22} {'metadata'}")
    print("-" * 118)
    for row in rows:
        qid = row["question_id"].replace("financebench_id_", "")
        try:
            state = extract_state(row, args.seed)
        except PipelineError as exc:
            print(f"{qid:<24} FALHA NA EXTRACAO: {exc}")
            tally["extracao_falhou"] += 1
            continue

        eligible, _ = verify_extraction(state.claims)
        tally["ok"] += 1
        tally["claims"] += len(state.claims)
        tally["verificados"] += len(eligible)

        res = probe(state.claims, eligible, row["answer"])
        for error_type, value in res.items():
            if value != "-":
                tally[f"alvo_{error_type}"] += 1
        print(
            f"{qid:<24} {len(state.claims):>7} {len(eligible):>6} | "
            f"{res['value']:<22} {res['percentage']:<22} {res['metadata']}"
        )

        if args.with_analyst:
            try:
                analysis = analyze_state(row, args.seed, state)
            except PipelineError as exc:
                print(f"{'':<24} analista: FALHA {exc}")
                continue
            ids = {c.claim_id for c in analysis.claims}
            res_a = probe(analysis.claims, ids, row["answer"])
            for error_type, value in res_a.items():
                if value != "-":
                    tally[f"analista_{error_type}"] += 1
            print(
                f"{'':<24} {len(analysis.claims):>7} {'(an)':>6} | "
                f"{res_a['value']:<22} {res_a['percentage']:<22} {res_a['metadata']}"
            )

    n = tally["ok"]
    print(f"\n{n}/{len(rows)} perguntas extraidas ({tally['extracao_falhou']} falhas)")
    if n:
        print(
            f"claims: {tally['claims']} total, {tally['verificados']} verificados "
            f"({tally['verificados'] / max(tally['claims'], 1):.0%})"
        )
        print("perguntas com alvo, injecao no EXTRATOR:")
        for error_type in ERROR_TYPES:
            print(f"   {error_type:<12} {tally['alvo_' + error_type]:>3}/{n}")
        if args.with_analyst:
            print("perguntas com alvo, injecao no ANALISTA:")
            for error_type in ERROR_TYPES:
                print(f"   {error_type:<12} {tally['analista_' + error_type]:>3}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

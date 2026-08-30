"""Constroi data/financebench/subset.jsonl a partir do FinanceBench.

Documento-fonte do experimento = os trechos de evidencia do proprio benchmark
(o split aberto traz pergunta, resposta e evidence). Isso evita parsing de PDF
e mantem o contexto curto; a evidencia da condicao D ja vem alinhada com o
ground truth.

Uso:
    uv run python scripts/build_subset.py --n 20
    uv run python scripts/build_subset.py --from-file financebench_open_source.jsonl

Se o download automatico nao estiver disponivel, baixe o jsonl aberto de
https://github.com/patronus-ai/financebench e use --from-file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handoff import config  # noqa: E402

FIELD_ALIASES = {
    "question_id": ("financebench_id", "id", "question_id"),
    "question": ("question",),
    "answer": ("answer",),
    "doc_id": ("doc_name", "doc_id", "docname"),
}


def _first(row: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if row.get(key):
            return str(row[key])
    return None


def _evidence(row: dict) -> str:
    """FinanceBench guarda a evidencia como lista de trechos."""
    ev = row.get("evidence") or row.get("evidence_text") or []
    if isinstance(ev, str):
        return ev
    parts = []
    for item in ev:
        if isinstance(item, dict):
            text = item.get("evidence_text") or item.get("text")
        else:
            text = str(item)
        if text:
            parts.append(text.strip())
    return "\n\n".join(parts)


def normalize(row: dict) -> dict | None:
    out = {
        key: _first(row, aliases) for key, aliases in FIELD_ALIASES.items()
    }
    out["evidence"] = _evidence(row)
    out["question_type"] = row.get("question_type", "")
    if not all(out[k] for k in FIELD_ALIASES):
        return None
    if not out["evidence"]:
        return None
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20, help="tamanho do subconjunto")
    parser.add_argument("--from-file", type=Path, help="jsonl bruto do FinanceBench")
    parser.add_argument(
        "--question-type",
        default="metrics-generated",
        help=(
            "filtro do FinanceBench; 'all' desliga. O default sao as perguntas com "
            "resposta numerica limpa extraivel de tabela -- as unicas em que a "
            "selecao do claim-alvo por gold matching funciona de forma confiavel"
        ),
    )
    parser.add_argument(
        "--ensure-percentage",
        type=int,
        default=0,
        help=(
            "reserva N vagas para perguntas de resposta percentual. O braço de erro "
            "percentual so existe quando o Analista produz claim em PCT, o que depende "
            "de a pergunta pedir um percentual; sem a cota, a amostra por id deixa esse "
            "braco magro"
        ),
    )
    args = parser.parse_args()

    config.ensure_dirs()

    if args.from_file:
        raw = [json.loads(line) for line in args.from_file.read_text().splitlines() if line.strip()]
    else:
        try:
            from datasets import load_dataset  # type: ignore
        except ImportError:
            print(
                "instale `datasets` (uv add --dev datasets) ou use --from-file",
                file=sys.stderr,
            )
            return 1
        ds = load_dataset("PatronusAI/financebench", split="train")
        raw = [dict(r) for r in ds]

    rows = [r for r in (normalize(r) for r in raw) if r]
    if args.question_type != "all":
        rows = [r for r in rows if r["question_type"] == args.question_type]
    # Ordenacao estavel por id: o subconjunto e reprodutivel.
    rows = sorted(rows, key=lambda r: r["question_id"])
    if args.ensure_percentage:
        with_pct = [r for r in rows if "%" in r["answer"]]
        without = [r for r in rows if "%" not in r["answer"]]
        chosen = with_pct[: args.ensure_percentage]
        chosen += without[: max(args.n - len(chosen), 0)]
        rows = sorted(chosen, key=lambda r: r["question_id"])
        print(
            f"cota percentual: {len([r for r in rows if '%' in r['answer']])} "
            f"de {len(with_pct)} disponiveis"
        )
    rows = rows[: args.n]

    with config.SUBSET_PATH.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"{len(rows)} perguntas -> {config.SUBSET_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

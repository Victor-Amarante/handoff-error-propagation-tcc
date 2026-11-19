"""Pagina local para a rotulagem manual (parecer, B8).

Gera analysis/rotulagem_manual.html a partir de analysis/rotulagem_manual.csv,
com a resposta do benchmark ao lado. O rotulo do instrumento nao entra na pagina.

    uv run python scripts/build_rotulagem_html.py
    open analysis/rotulagem_manual.html
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "analysis" / "rotulagem_manual.csv"
SUBSET = ROOT / "data" / "financebench" / "subset.jsonl"
OUT = ROOT / "analysis" / "rotulagem_manual.html"


def parse_stage(text):
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"text": text}
    if isinstance(obj, dict) and isinstance(obj.get("claims"), list):
        return {"claims": obj["claims"], "answer_claim_id": obj.get("answer_claim_id")}
    return {"text": json.dumps(obj, indent=2, ensure_ascii=False)}


with CSV.open(newline="") as f:
    reader = csv.DictReader(f)
    columns = reader.fieldnames
    rows = list(reader)
answers = {}
with SUBSET.open() as f:
    for line in f:
        q = json.loads(line)
        answers[q["question_id"]] = q["answer"]

data = [
    {
        "raw": r,
        "benchmark": answers.get(r["pergunta_id"], ""),
        "analista_controle": parse_stage(r["analista_controle"]),
        "analista_injetado": parse_stage(r["analista_injetado"]),
    }
    for r in rows
]
payload = json.dumps({"columns": columns, "rows": data}, ensure_ascii=False).replace("</", "<\\/")
OUT.write_text((Path(__file__).with_name("rotulagem_template.html")).read_text().replace("__DATA__", payload))
print(f"{len(rows)} linhas -> {OUT.relative_to(ROOT)}")

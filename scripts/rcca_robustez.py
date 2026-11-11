"""Robustez da RCCA: mesmo criterio de acerto nas quatro condicoes.

`measure.rcca` aceita dois caminhos de acerto: o `claim_id` (so existe em C/D)
ou a tupla (metrica, valor corrompido), que existe em todas as condicoes. Este
script recalcula a RCCA so pelo segundo caminho, para comparar A/B/C/D com o
mesmo criterio, e mostra quanto da RCCA de C/D depende so do identificador.

Uso: uv run python scripts/rcca_robustez.py   (a partir da raiz do repositorio)
"""
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from handoff.logger import is_complete
from handoff.measure import Number, load_cells, same_number

MODELS = ["gpt-5.6-luna", "claude-haiku-4-5-20251001", "qwen3.5-9b"]


def value_route(c) -> bool:
    a, i = c.audit, c.injection
    if not a:
        return False
    rv, cv = a.get("reported_value"), i.get("corrupted_value")
    if rv is None or not isinstance(cv, (int, float)):
        return False
    if not same_number(Number(float(rv), False), Number(float(cv), False)):
        return False
    rm = (a.get("reported_metric") or "").lower()
    tm = (i.get("original_claim") or {}).get("metric", "").lower()
    if not rm or not tm:
        return True
    return bool(set(re.findall(r"[a-z]+", tm)) & set(re.findall(r"[a-z]+", rm)))


def id_route(c) -> bool:
    return bool(c.audit) and c.audit.get("root_cause_claim_id") == c.injection.get("target_claim_id")


def ic(v):
    v = pd.Series(v).dropna().to_numpy(float)
    m = np.random.default_rng(0).choice(v, size=(5000, len(v))).mean(1)
    return np.quantile(m, [0.025, 0.975])


for slug in MODELS:
    cells = [
        c for c in load_cells(Path("data") / slug / "logs")
        if is_complete(c.path) and not c.is_control and c.injection_stage == "extractor"
    ]
    df = pd.DataFrame([
        {"q": c.question_id, "cond": str(c.condition), "et": c.error_type,
         "valor": float(value_route(c)), "id": float(id_route(c))}
        for c in cells
    ])
    df = df[df.groupby(["et", "q"]).cond.transform("nunique") == 4]
    p = df.groupby(["cond", "q"])[["valor", "id"]].mean()
    linha = " ".join(f"{c}:{p.loc[c].valor.mean():.2f}" for c in "ABCD")
    print(f"{slug}  RCCA por metrica+valor  {linha}")
    for a, b in [("B", "C"), ("C", "D")]:
        d = p.loc[b].valor - p.loc[a].valor
        lo, hi = ic(d)
        print(f"   {a}->{b}: {d.mean():+.2f} [{lo:+.2f}; {hi:+.2f}]")

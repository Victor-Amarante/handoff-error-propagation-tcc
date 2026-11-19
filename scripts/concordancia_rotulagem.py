"""Concordancia entre o instrumento textual e a rotulagem humana (parecer, B8).

1. Rotule em analysis/rotulagem_manual.html (gerada por scripts/build_rotulagem_html.py),
   sem olhar o gabarito, e clique em "Baixar CSV".
2. mv ~/Downloads/rotulagem_manual.csv analysis/
3. uv run python scripts/concordancia_rotulagem.py
"""
import pandas as pd

lab = pd.read_csv("analysis/rotulagem_manual.csv")
gab = pd.read_csv("analysis/rotulagem_manual_gabarito.csv")
df = lab.merge(gab, on=["log", "modelo"]).dropna(subset=["destino_humano"])
df = df[df.destino_humano.str.strip() != ""]
if df.empty:
    raise SystemExit("nenhuma linha rotulada ainda")
h, m = df.destino_humano.str.strip().str.lower(), df.destino_instrumento
po = (h == m).mean()
cats = sorted(set(h) | set(m))
pe = sum((h == c).mean() * (m == c).mean() for c in cats)
print(f"{len(df)} execucoes rotuladas: concordancia {po:.2f}, kappa de Cohen {(po - pe) / (1 - pe):.2f}")
print(pd.crosstab(h, m, rownames=["humano"], colnames=["instrumento"]))

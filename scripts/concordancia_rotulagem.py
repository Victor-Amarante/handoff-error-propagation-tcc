"""Concordancia entre o instrumento textual e a rotulagem humana (parecer, B8).

1. Preencha a coluna `destino_humano` de analysis/rotulagem_manual.csv com um de:
   preservado, transformado, amplificado, corrigido, contido, sem_efeito
   (definicoes na Secao III-G do artigo), sem olhar o gabarito.
2. uv run python scripts/concordancia_rotulagem.py
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

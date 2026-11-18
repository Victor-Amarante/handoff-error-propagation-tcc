"""Experimentos complementares pedidos no parecer do orientador.

* A3 -- condicao E (tipado + evidencia, sem lineage): fecha o fatorial
  lineage x evidencia com B, C e D da rodada principal.
* Insight 1 -- condicao V (D + instrucao de conferencia).
* A5 -- condicao R (B com campo `reasoning` no Analista), so controles.
* A2 -- teste A/A: replica dos controles de A-D, comparada com o controle
  original pelo mesmo instrumento (piso de ruido da ESR e da profundidade).
* B2 -- auditor GPT relendo os traces de Haiku e Qwen (scripts/reaudit.py).

Uso: uv run python scripts/build_complementares.py
Gera src/tables/resultados-complementares.tex e analysis/complementares.json.
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import numpy as np
import pandas as pd

from build_tables import load, ic
from handoff.logger import is_complete
from handoff.measure import (
    esr, final_correct, load_cell, load_cells, placebo_attribution, propagation_depth,
    rcca, rcca_conteudo, fesa,
)

API = [("gpt-5.6-luna", "GPT-5.6 Luna"), ("claude-haiku-4-5-20251001", "Claude Haiku 4.5")]
OUT = {}
TAB = Path("TCC___Contratos_de_Handoff_em_sistemas_de_IA_Generativa/src/tables")


def f(x, dec=2):
    return "--" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{dec}f}".replace(".", ",")


def fd(d):
    mu, (lo, hi) = d.mean(), ic(d)
    s = f"{mu:+.2f} [{lo:+.2f}; {hi:+.2f}]".replace(".", ",").replace("-", "$-$")
    return (r"\textbf{" + s + "}" if (lo > 0 or hi < 0) else s), (mu, lo, hi)


MET = ["final_correct", "retention", "esr", "esr_literal_valor", "propagation_depth", "rcca_conteudo", "fesa_liq", "pipeline_tokens"]


def per_q(df):
    d = df.copy()
    # sobrevivencia literal so no braco de valor: no de metadado o "valor" e o
    # ano, que a propria pergunta costuma trazer (Secao V-C)
    d["esr_literal_valor"] = np.where(d.error_type == "value", pd.to_numeric(d.esr_literal, errors="coerce"), np.nan)
    for m in MET:
        d[m] = pd.to_numeric(d[m], errors="coerce")
    return d.groupby(["condition", "question_id"])[MET].mean()


# --------------------------------------------------------------------------
# A3 + insight 1: E e V contra B, C, D (mesmas perguntas, mesmo estado)
# --------------------------------------------------------------------------
def factorial(slug):
    main, ctr_main, _ = load(slug, "extractor")
    extra, ctr_extra, _ = load_extra(slug)
    df = pd.concat([main, extra])
    # so perguntas com as seis condicoes completas, por braco
    n = df.groupby(["error_type", "question_id"]).condition.transform("nunique")
    df = df[n == 6]
    # retencao com o conjunto comum das SEIS condicoes
    ctr = ctr_main + ctr_extra
    cd = pd.DataFrame([{"q": c.question_id, "c": str(c.condition), "ok": final_correct(c)} for c in ctr]).dropna()
    pv = cd.pivot_table(index="q", columns="c", values="ok", aggfunc="first")
    common = set(pv[(pv.reindex(columns=list("ABCDEV")) == True).all(axis=1)].index)  # noqa: E712
    df["retention"] = np.where(df.question_id.isin(common), pd.to_numeric(df.final_correct, errors="coerce"), np.nan)
    return df, len(common)


def load_extra(slug):
    """Como build_tables.load, mas para logs_parecer (condicoes E e V)."""
    df, ctr, n = load(slug, "extractor", subdir="logs_parecer", nconds=2)
    return df[df.condition.isin(["E", "V"])], ctr, n


# --------------------------------------------------------------------------
# A2: teste A/A
# --------------------------------------------------------------------------
def aa(slug):
    rep = {(c.question_id, str(c.condition)): c for c in load_cells(Path("data") / slug / "logs_aa")
           if is_complete(c.path) and c.is_control}
    rows = []
    for c in load_cells(Path("data") / slug / "logs"):
        if not (c.is_control and c.injection_stage == "extractor"):
            continue
        r = rep.get((c.question_id, str(c.condition)))
        if r is None or not is_complete(c.path):
            continue
        rows.append({"q": c.question_id, "cond": str(c.condition),
                     "esr0": float(esr(r, c)), "depth0": float(propagation_depth(r, c)),
                     "acc_igual": float(final_correct(r) == final_correct(c))})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# A5: condicao R (so controles) contra A e B
# --------------------------------------------------------------------------
def reasoning(slug):
    rows = []
    for d, conds in (("logs", "AB"), ("logs_parecer", "R")):
        for c in load_cells(Path("data") / slug / d):
            if c.is_control and c.injection_stage == "extractor" and str(c.condition) in conds and is_complete(c.path):
                out = sum((e.get("usage") or {}).get("output_tokens", 0)
                          for e in map(json.loads, open(c.path))
                          if e["event_type"] == "stage_output" and e.get("stage") in ("analyst", "writer"))
                rows.append({"q": c.question_id, "cond": str(c.condition), "acc": final_correct(c), "out": out})
    df = pd.DataFrame(rows).dropna(subset=["acc"])
    df["acc"] = df.acc.astype(float)
    n = df.groupby("q").cond.transform("nunique")
    return df[n == 3]


# --------------------------------------------------------------------------
# B2: auditor GPT sobre os traces de Haiku e Qwen
# --------------------------------------------------------------------------
def cross_audit(slug):
    d = Path("data") / slug / "reaudit_gpt-5.6-luna"
    logs = Path("data") / slug / "logs"
    cells = {}
    for p in sorted(d.glob("*.json")):
        r = json.loads(p.read_text())
        c = load_cell(logs / r["log"])
        cells[r["log"]] = (c, r["audit_report"])
    rows, ctrl = [], {}
    for name, (c, rep) in cells.items():
        if c.is_control:
            ctrl[(c.question_id, str(c.condition))] = (c, rep)
    for name, (c, rep) in cells.items():
        if c.is_control:
            continue
        own = {"rcca": rcca_conteudo(c), "fesa": fesa(c)}
        orig_audit = c.audit
        c.audit = rep
        gpt = {"rcca": rcca_conteudo(c) if rep else False, "fesa": fesa(c) if rep else False}
        c.audit = orig_audit
        row = {"q": c.question_id, "cond": str(c.condition), "et": c.error_type,
               "rcca_own": float(bool(own["rcca"])), "fesa_own": float(bool(own["fesa"])),
               "rcca_gpt": float(bool(gpt["rcca"])), "fesa_gpt": float(bool(gpt["fesa"]))}
        cc = ctrl.get((c.question_id, str(c.condition)))
        if cc is not None:
            ctl, crep = cc
            row["pl_rcca_own"] = placebo_attribution(ctl, c.injection)["rcca"] if ctl.audit else np.nan
            ctl_audit = ctl.audit
            ctl.audit = crep or {}
            row["pl_rcca_gpt"] = placebo_attribution(ctl, c.injection)["rcca"]
            ctl.audit = ctl_audit
            row["fp_own"] = float((ctl.audit or {}).get("first_error_stage", "none") != "none")
            row["fp_gpt"] = float((crep or {}).get("first_error_stage", "none") != "none")
        rows.append(row)
    df = pd.DataFrame(rows)
    n = df.groupby(["et", "q"]).cond.transform("nunique")
    return df[n == 4]


def fdelta(v):
    mu, lo, hi = v
    s = f"{mu:+.2f} [{lo:+.2f}; {hi:+.2f}]".replace(".", ",").replace("-", "$-$")
    return r"\textbf{" + s + "}" if (lo > 0 or hi < 0) else s


ROWS = [("Acurácia factual final", "final_correct", 2), ("Retenção", "retention", 2), ("ESR", "esr", 2),
        ("Sobrevivência literal$^{a}$", "esr_literal_valor", 2), ("RCCA", "rcca_conteudo", 2),
        ("FESA líquida", "fesa_liq", 2), ("Tokens por execução", "pipeline_tokens", 0)]


def fi(x):
    return f"{x:,.0f}".replace(",", ".")


def noise_adjusted(slug):
    """Diferencas de ESR e profundidade descontada a diferenca dos pisos (A2):
    bootstrap independente das perguntas do estudo e das da replica."""
    df, _, _ = load(slug, "extractor")
    for m in ("esr", "propagation_depth", "esr_literal"):
        df[m] = pd.to_numeric(df[m], errors="coerce")
    p = df.groupby(["condition", "question_id"])[["esr", "propagation_depth", "esr_literal"]].mean()
    a = aa(slug)
    pa = a.groupby(["cond", "q"])[["esr0", "depth0"]].mean()
    rng = np.random.default_rng(0)
    boot = lambda v: rng.choice(v, size=(5000, len(v))).mean(1)  # noqa: E731
    out = {}
    for x, y in (("A", "B"), ("B", "C"), ("C", "D")):
        for m, m0 in (("esr", "esr0"), ("propagation_depth", "depth0")):
            d = (p.loc[y][m] - p.loc[x][m]).dropna().to_numpy()
            d0 = (pa.loc[y][m0] - pa.loc[x][m0]).dropna().to_numpy()
            bd = boot(d) - boot(d0)
            lo, hi = np.quantile(bd, [0.025, 0.975])
            out[f"{x}{y}:{m}"] = [d.mean(), d0.mean(), d.mean() - d0.mean(), lo, hi]
        d = (p.loc[y].esr_literal - p.loc[x].esr_literal).dropna()
        out[f"{x}{y}:esr_literal"] = [d.mean(), *ic(d)]
    return out


def write_tables():
    names = [n for _, n in API]
    L = [r"\begin{table*}[t]", r"\caption{Fatorial entre lineage e evidência e efeito da instrução de conferência (estudo principal, modelos de API)}",
         r"\label{tab:fatorial}", r"\centering", r"\footnotesize", r"\setlength{\tabcolsep}{3.2pt}",
         r"\begin{tabular}{|l|ccccc|ccccc|}", r"\hline",
         " & " + " & ".join(r"\multicolumn{5}{c|}{\textbf{" + n + "}}" for n in names) + r" \\",
         r"\textbf{Métrica} & " + " & ".join(["B & C & E & D & D$'$"] * 2) + r" \\",
         r"\multicolumn{1}{|l|}{} & " + " & ".join([r"\scriptsize --/-- & \scriptsize L/-- & \scriptsize --/E & \scriptsize L/E & \scriptsize L/E+i"] * 2) + r" \\", r"\hline"]
    for lab, m, dec in ROWS:
        cells = []
        for n in names:
            for c in "BCEDV":
                v = OUT[n]["means"][c][m]
                cells.append(fi(v) if dec == 0 else f(v))
        L.append(lab + " & " + " & ".join(cells) + r" \\")
    L += [r"\hline", r"\end{tabular}", r"\\[4pt]", r"{\scriptsize\setlength{\tabcolsep}{2pt}", r"\begin{tabular}{|l|ccc|ccc|}", r"\hline",
          " & " + " & ".join(r"\multicolumn{3}{c|}{\textbf{" + n + "}}" for n in names) + r" \\",
          r"\textbf{Diferença pareada} & " + " & ".join([r"B $\to$ E & E $\to$ D & D $\to$ D$'$"] * 2) + r" \\", r"\hline"]
    for lab, m, dec in ROWS:
        cells = []
        for n in names:
            for k in ("BE", "ED", "DV"):
                v = OUT[n]["deltas"][k][m]
                cells.append(f"{v[0]:+,.0f}".replace(",", ".") if dec == 0 else fdelta(v))
        L.append(lab + " & " + " & ".join(cells) + r" \\")
    L += [r"\hline", r"\end{tabular}}"]
    nq = ", ".join(f"{OUT[n]['factorial_n']}" for n in names)
    L += [r"\\[2pt]{\scriptsize\raggedright L: lineage; E: evidência; i: instrução de conferência. Médias e diferenças por pergunta sobre as mesmas "
          + nq + r" perguntas, com IC95\% bootstrap; em negrito, intervalo que não inclui zero. A retenção usa as perguntas cujo controle acerta nas cinco condições. "
          r"$^{a}$Fração das execuções do erro de valor em que o valor corrompido aparece literalmente na resposta final; não depende da comparação com o controle.\par}",
          r"\end{table*}"]
    (TAB / "resultados-fatorial.tex").write_text("\n".join(L) + "\n", encoding="utf-8")

    M3 = [("GPT-5.6 Luna", None), ("Claude Haiku 4.5", "Claude Haiku 4.5"), ("Qwen3.5 9B", "Qwen3.5 9B")]
    L = [r"\begin{table*}[t]", r"\caption{Verificações do instrumento: piso de ruído (teste A/A) e auditoria cruzada}", r"\label{tab:verificacoes}",
         r"\centering", r"\footnotesize", r"\setlength{\tabcolsep}{3.2pt}", r"\begin{tabular}{|l|cccc|cccc|cccc|}", r"\hline",
         " & " + " & ".join(r"\multicolumn{4}{c|}{\textbf{" + n + "}}" for n, _ in M3) + r" \\",
         r"\textbf{Métrica} & " + " & ".join(["A & B & C & D"] * 3) + r" \\", r"\hline",
         r"\multicolumn{13}{|l|}{\textit{Piso de ruído: réplica do controle contra o controle original}} \\"]
    for lab, k in (("ESR nula", "esr0"), ("Profundidade nula", "depth0"), ("Mesmo acerto da réplica", "acc_igual")):
        cells = []
        for n, _ in M3:
            for c in "ABCD":
                aa_ = OUT.get(n, {}).get("aa")
                cells.append(f(aa_[k][c]) if aa_ else "--")
        L.append(lab + " & " + " & ".join(cells) + r" \\")
    L.append(r"\multicolumn{13}{|l|}{\textit{Auditoria cruzada: traces do pipeline lidos pelo auditor do GPT}} \\")
    for lab, k in (("RCCA, auditor do próprio modelo", "rcca_own"), ("RCCA, auditor do GPT", "rcca_gpt"),
                   ("\\quad placebo, auditor do GPT", "pl_rcca_gpt"), ("FESA, auditor do GPT", "fesa_gpt"),
                   ("Falso positivo, auditor do GPT", "fp_gpt")):
        cells = []
        for n, key in M3:
            for c in "ABCD":
                cr = OUT.get(key, {}).get("cross") if key else None
                cells.append(f(cr[c][k]) if cr else "--")
        L.append(lab + " & " + " & ".join(cells) + r" \\")
    naa = ", ".join(str(OUT[n].get("aa_n", "--")) for _, n in API)
    ncr = ", ".join(str(OUT[n].get("cross_n", "--")) for n in ("Claude Haiku 4.5", "Qwen3.5 9B"))
    L += [r"\hline", r"\end{tabular}",
          r"\\[2pt]{\scriptsize\raggedright Piso de ruído: as métricas de contenção calculadas entre duas execuções limpas da mesma pergunta e condição ("
          + naa + r" perguntas no GPT e no Haiku); o Qwen não foi replicado. Auditoria cruzada: estudo principal, "
          + ncr + r" perguntas no Haiku e no Qwen; no GPT o auditor é o próprio, e os valores estão na Tabela~\ref{tab:principal}.\par}",
          r"\end{table*}"]
    (TAB / "resultados-verificacoes.tex").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    L = []
    for slug, name in API:
        R = OUT[name] = {}
        print(f"\n========== {name} ==========")
        df, ncommon = factorial(slug)
        p = per_q(df)
        nq = df.question_id.nunique()
        R["factorial_n"] = nq
        R["factorial_ncommon"] = ncommon
        R["means"] = {c: p.loc[c].mean().round(4).to_dict() for c in "BCDEV" if c in p.index.get_level_values(0)}
        print(f"fatorial: {nq} perguntas, retencao sobre {ncommon}")
        for c in "BCDEV":
            print("  ", c, {k: round(v, 2) for k, v in R["means"][c].items()})
        R["deltas"] = {}
        for a, b in [("B", "E"), ("C", "D"), ("B", "C"), ("E", "D"), ("D", "V")]:
            R["deltas"][a + b] = {}
            for m in MET:
                s, (mu, lo, hi) = fd(p.loc[b][m] - p.loc[a][m])
                R["deltas"][a + b][m] = [mu, lo, hi]
            print(f"  {a}->{b}:", {m: [round(x, 2) for x in v] for m, v in R["deltas"][a + b].items()})
        # por braco: ESR e RCCA de E e V
        for et in ("value", "metadata"):
            q = df[df.error_type == et].copy()
            for m in ("esr", "rcca_conteudo", "final_correct"):
                q[m] = pd.to_numeric(q[m], errors="coerce")
            R[f"braco_{et}"] = q.groupby("condition")[["esr", "rcca_conteudo", "final_correct"]].mean().round(4).to_dict()
            print(f"   braco {et}:", q.groupby("condition")[["esr", "rcca_conteudo", "final_correct"]].mean().round(2).to_dict())

        a = aa(slug)
        if len(a):
            g = a.groupby("cond")[["esr0", "depth0", "acc_igual"]].mean()
            R["aa"] = g.round(4).to_dict()
            R["aa_n"] = a.q.nunique()
            print(f"A/A ({a.q.nunique()} perguntas):", g.round(2).to_dict())

        if len(a):
            R["aa_ajustado"] = noise_adjusted(slug)
            for k, v in R["aa_ajustado"].items():
                print("   ajustado", k, [round(x, 2) for x in v])

        r = reasoning(slug)
        if len(r):
            g = r.groupby("cond")[["acc", "out"]].mean()
            R["reasoning"] = g.round(4).to_dict()
            R["reasoning_n"] = r.q.nunique()
            pv = r.pivot_table(index="q", columns="cond", values="acc")
            R["reasoning_delta"] = {}
            for x, y in [("B", "R"), ("A", "R"), ("A", "B")]:
                s, v = fd(pv[y] - pv[x])
                R["reasoning_delta"][x + y] = list(v)
            print(f"R ({r.q.nunique()} perguntas):", g.round(2).to_dict(), R["reasoning_delta"])

    for slug, name in [("claude-haiku-4-5-20251001", "Claude Haiku 4.5"), ("qwen3.5-9b", "Qwen3.5 9B")]:
        x = cross_audit(slug)
        R = OUT.setdefault(name, {})
        if not len(x):
            continue
        g = x.groupby(["cond", "q"]).mean(numeric_only=True)
        R["cross"] = {c: g.loc[c].mean().round(4).to_dict() for c in "ABCD"}
        R["cross_n"] = x.q.nunique()
        print(f"\nB2 {name} ({x.q.nunique()} perguntas):")
        for c in "ABCD":
            print("  ", c, {k: round(v, 2) for k, v in R["cross"][c].items()})
        R["cross_delta"] = {}
        for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
            R["cross_delta"][a + b] = {}
            for m in ("rcca_own", "rcca_gpt"):
                s, v = fd(g.loc[b][m] - g.loc[a][m])
                R["cross_delta"][a + b][m] = list(v)
            print(f"   {a}->{b}", {k: [round(z, 2) for z in v] for k, v in R["cross_delta"][a + b].items()})

    write_tables()
    json.dump(OUT, open("analysis/complementares.json", "w"), indent=1, default=float)
    print("ok -> analysis/complementares.json")

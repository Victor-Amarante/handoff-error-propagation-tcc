"""Reanalise dos logs pedida no parecer do orientador (itens A1, A4, A6, B1,
B3, B5, B6, A5 e o custo por ganho). Nenhuma chamada de API.

Uso: uv run python scripts/parecer_reanalise.py   (a partir da raiz)

Imprime um relatorio por item e grava os numeros em
analysis/parecer_reanalise.json, de onde sai o texto do artigo.
"""
import json
import re
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from handoff.logger import is_complete
from handoff.measure import (
    DOWNSTREAM, Number, contains_number, difference, extract_numbers,
    final_correct, load_cells, pair_with_control, same_number, to_records,
)

MODELS = [("gpt-5.6-luna", "GPT"), ("claude-haiku-4-5-20251001", "Haiku"), ("qwen3.5-9b", "Qwen")]
OUT = {}


def ic(v):
    v = pd.Series(v).dropna().to_numpy(float)
    if len(v) < 2:
        return (np.nan, np.nan)
    m = np.random.default_rng(0).choice(v, size=(5000, len(v))).mean(1)
    return tuple(np.quantile(m, [0.025, 0.975]))


def boot_p(v):
    """p bilateral do bootstrap percentilico (para Holm)."""
    v = pd.Series(v).dropna().to_numpy(float)
    m = np.random.default_rng(0).choice(v, size=(5000, len(v))).mean(1)
    return min(1.0, 2 * min((m <= 0).mean(), (m >= 0).mean()))


def fmt(mu, lo, hi):
    return f"{mu:+.2f} [{lo:+.2f}; {hi:+.2f}]" + (" *" if lo > 0 or hi < 0 else "")


def value_route(audit, value, metric):
    """Criterio comum da RCCA: metrica e valor informados pelo auditor."""
    if not audit or audit.get("reported_value") is None or not isinstance(value, (int, float)):
        return False
    if not same_number(Number(float(audit["reported_value"]), False), Number(float(value), False)):
        return False
    rm = (audit.get("reported_metric") or "").lower()
    tm = (metric or "").lower()
    if not rm or not tm:
        return True
    return bool(set(re.findall(r"[a-z]+", tm)) & set(re.findall(r"[a-z]+", rm)))


def numbers_ex_corrupted(text, corrupted):
    nums = extract_numbers(text)
    if corrupted is None:
        return nums
    return [n for n in nums if not same_number(n, Number(corrupted, False))]


def load(slug):
    cells = [c for c in load_cells(Path("data") / slug / "logs") if is_complete(c.path)]
    cells = [c for c in cells if c.injection_stage == "extractor"]
    rows = []
    for inj, ctr in pair_with_control(cells):
        if ctr is None:
            continue
        rec = inj.injection or {}
        corrupted = rec.get("corrupted_value")
        corrupted = float(corrupted) if isinstance(corrupted, (int, float)) else None
        metric = (rec.get("original_claim") or {}).get("metric")
        # B1: o que mudou no Analista e no Redator -- so a repeticao do valor
        # corrompido, ou numeros novos (derivacao)?
        lit, der, n_emit = [], [], 0
        for s in DOWNSTREAM:
            got = extract_numbers(inj.stage_text.get(s.value, ""))
            want = extract_numbers(ctr.stage_text.get(s.value, ""))
            n_emit += len(got)
            has_corr = corrupted is not None and contains_number(got, corrupted)
            new_other = difference(numbers_ex_corrupted(inj.stage_text.get(s.value, ""), corrupted), want)
            lit.append(has_corr and not new_other)
            der.append(bool(new_other))
        final = extract_numbers(inj.final_answer)
        fc = final_correct(inj)
        rows.append({
            "q": inj.question_id, "cond": str(inj.condition), "et": inj.error_type,
            "target": rec.get("target_claim_id"),
            "rcca_comum": float(value_route(inj.audit, corrupted, metric)) if inj.audit else 0.0,
            # Criterio de conteudo: metrica + valor do claim-alvo TAL COMO APARECE
            # no trace. No erro de valor e o valor corrompido; no de metadado, o
            # valor do claim (intacto), ja que o errado e o ano.
            "rcca_conteudo": float(value_route(
                inj.audit, corrupted if inj.error_type == "value" else (rec.get("original_claim") or {}).get("value"),
                metric)) if inj.audit else 0.0,
            "out_tokens": inj.pipeline_output_tokens, "in_tokens": inj.pipeline_input_tokens,
            "n_emit": n_emit,
            "depth_literal": sum(lit), "depth_deriv": sum(der),
            "analyst_literal": float(lit[0]), "analyst_deriv": float(der[0]),
            "acc_estrita": (None if fc is None else float(fc and not (corrupted is not None and contains_number(final, corrupted)))),
        })
    extra = pd.DataFrame(rows)
    df = pd.DataFrame(to_records(cells))
    df = df.rename(columns={"question_id": "q", "condition": "cond", "error_type": "et"})
    # auditor sem relatorio valido conta como erro de atribuicao (como nas tabelas)
    for m in ("rcca", "fesa"):
        df[m] = pd.to_numeric(df[m], errors="coerce").fillna(0.0)
    df = df.drop(columns=[c for c in extra.columns if c in df.columns and c not in ("q", "cond", "et")])
    df = df.merge(extra, on=["q", "cond", "et"])
    n = df.groupby(["et", "q"]).cond.transform("nunique")
    df = df[n == 4].copy()
    controls = [c for c in cells if c.is_control]
    return df, controls, cells


for slug, name in MODELS:
    df, controls, cells = load(slug)
    R = OUT[name] = {}
    print(f"\n==================== {name} ====================")
    df["sem_efeito"] = (df.fate == "sem_efeito").astype(float)

    # ---------------- A1: fora do caminho x absorvido -----------------
    g = df.pivot_table(index=["q", "et"], columns="cond", values="sem_efeito", aggfunc="first")
    off = g.min(axis=1) == 1  # sem efeito nas quatro condicoes
    df["off_path"] = df.set_index(["q", "et"]).index.map(off).astype(float)
    df["absorvido"] = ((df.sem_efeito == 1) & (df.off_path == 0)).astype(float)
    t = df.groupby("cond")[["sem_efeito", "off_path", "absorvido"]].mean()
    print("A1 sem efeito / fora do caminho / absorvido (fracao das execucoes)")
    print(t.round(3).to_string())
    R["A1"] = t.round(4).to_dict()
    # destino reclassificado: absorvido = corrigido no primeiro estagio
    fate2 = df.fate.where(df.absorvido == 0, "corrigido_1o")
    fate2 = fate2.where(df.off_path == 0, "fora_caminho")
    R["destino_reclass"] = (pd.crosstab(fate2, df.cond, normalize="columns") * 100).round(1).to_dict()
    print((pd.crosstab(fate2, df.cond, normalize="columns") * 100).round(0).to_string())

    # ---------------- A1/A4: retencao com denominador comum -----------
    ctr_ok = pd.DataFrame([{"q": c.question_id, "cond": str(c.condition), "ok": final_correct(c)} for c in controls])
    ctr_ok = ctr_ok.dropna()
    piv = ctr_ok.pivot_table(index="q", columns="cond", values="ok", aggfunc="first")
    common = set(piv[(piv[list("ABCD")] == True).all(axis=1)].index)  # noqa: E712
    df["final_correct"] = pd.to_numeric(df.final_correct, errors="coerce")
    ret = df[df.q.isin(common)].groupby(["cond", "q"]).final_correct.mean()
    for et in ("value", "metadata"):
        r2 = df[df.q.isin(common) & (df.et == et)].groupby("cond").final_correct.mean()
        R[f"retencao_{et}"] = r2.round(4).to_dict()
        print(f"   retencao braco {et}:", r2.round(2).to_dict())
    R["retencao"] = {c: round(ret.loc[c].mean(), 4) for c in "ABCD"}
    R["retencao_n"] = len(common)
    print(f"A1 retencao (controle correto nas 4 condicoes, n={len(common)} perguntas):",
          {c: round(ret.loc[c].mean(), 2) for c in "ABCD"})
    R["retencao_delta"] = {}
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        d = ret.loc[b] - ret.loc[a]
        R["retencao_delta"][a + b] = [d.mean(), *ic(d)]
        print(f"   {a}->{b}: {fmt(d.mean(), *ic(d))}")

    # ---------------- A4: n elegivel da taxa de correcao ---------------
    df["corrected"] = pd.to_numeric(df.corrected, errors="coerce")
    pq = df.groupby(["cond", "q"]).corrected.mean()
    R["correcao_n"] = {c: int(pq.loc[c].notna().sum()) for c in "ABCD"}
    print("A4 n de perguntas elegiveis para a taxa de correcao:", R["correcao_n"])
    R["correcao_intersec"] = {}
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        both = pq.loc[a].notna() & pq.loc[b].notna()
        ma, mb = pq.loc[a][both].mean(), pq.loc[b][both].mean()
        R["correcao_intersec"][a + b] = [int(both.sum()), ma, mb]
        print(f"   {a}->{b}: n={both.sum()}  medias na intersecao {ma:.2f} -> {mb:.2f} (dif {mb - ma:+.2f})")

    # ---------------- A6: placebo do auditor ----------------------------
    targets = df[["q", "cond", "et", "target"]].drop_duplicates()
    inj_by = {(c.question_id, str(c.condition), c.error_type): c for c in cells if not c.is_control}
    pl = []
    for c in controls:
        for et in ("value", "metadata"):
            inj = inj_by.get((c.question_id, str(c.condition), et))
            if inj is None or not inj.injection or not c.audit:
                continue
            if not ((targets.q == c.question_id) & (targets.et == et)).any():
                continue
            rec = inj.injection
            metric = (rec.get("original_claim") or {}).get("metric")
            pl.append({
                "q": c.question_id, "cond": str(c.condition), "et": et,
                "rcca_id": float(c.audit.get("root_cause_claim_id") == rec.get("target_claim_id")),
                "rcca_comum": float(value_route(c.audit, rec.get("original_value"), metric)),
                "rcca_conteudo": float(value_route(c.audit, (rec.get("original_claim") or {}).get("value"), metric)),
                "fesa": float(c.audit.get("first_error_stage") == "extractor"),
            })
    pl = pd.DataFrame(pl)
    plq = pl.groupby(["cond", "q"])[["rcca_id", "rcca_comum", "rcca_conteudo", "fesa"]].mean()
    iq = df.groupby(["cond", "q"])[["rcca", "rcca_comum", "rcca_conteudo", "fesa"]].mean()
    R["placebo"] = {c: plq.loc[c].mean().round(4).to_dict() for c in "ABCD"}
    R["observado"] = {c: iq.loc[c].mean().round(4).to_dict() for c in "ABCD"}
    print("A6 observado (injetadas) x placebo (controles):")
    for c in "ABCD":
        o, p = iq.loc[c].mean(), plq.loc[c].mean()
        print(f"   {c}: RCCA {o.rcca:.2f} (placebo id {p.rcca_id:.2f})  RCCA comum {o.rcca_comum:.2f} "
              f"(placebo {p.rcca_comum:.2f})  FESA {o.fesa:.2f} (placebo {p.fesa:.2f}) "
              f"-> FESA liquida {o.fesa - p.fesa:+.2f}")
    for c in "ABCD":
        print(f"   {c}: RCCA conteudo {iq.loc[c].rcca_conteudo.mean():.2f} (placebo {plq.loc[c].rcca_conteudo.mean():.2f})")
    R["rcca_conteudo_delta"] = {}
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        d = iq.loc[b].rcca_conteudo - iq.loc[a].rcca_conteudo
        R["rcca_conteudo_delta"][a + b] = [d.mean(), *ic(d)]
        print(f"   RCCA conteudo {a}->{b}: {fmt(d.mean(), *ic(d))}")
    R["rcca_conteudo_por_tipo"] = df.groupby(["et", "cond"]).rcca_conteudo.mean().round(4).unstack().to_dict(orient="index")
    R["placebo_por_tipo"] = {
        f"{et}:{c}": v for (et, c), v in
        pl.groupby(["et", "cond"])[["rcca_id", "rcca_conteudo", "fesa"]].mean().round(4).to_dict(orient="index").items()}
    R["rcca_id_por_tipo"] = df.groupby(["et", "cond"]).rcca.mean().round(4).unstack().to_dict(orient="index")
    print("   RCCA conteudo por tipo:", {k: {c: round(v, 2) for c, v in d.items()} for k, d in R["rcca_conteudo_por_tipo"].items()})
    print("   RCCA id-ou-valor por tipo:", {k: {c: round(v, 2) for c, v in d.items()} for k, d in R["rcca_id_por_tipo"].items()})
    print("   placebo por tipo:", R["placebo_por_tipo"])
    R["rcca_comum_delta"] = {}
    R["fesa_liq_delta"] = {}
    net_fesa = iq.fesa - plq.fesa.reindex(iq.index)
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        d = iq.loc[b].rcca_comum - iq.loc[a].rcca_comum
        R["rcca_comum_delta"][a + b] = [d.mean(), *ic(d)]
        e = net_fesa.loc[b] - net_fesa.loc[a]
        R["fesa_liq_delta"][a + b] = [e.mean(), *ic(e)]
        print(f"   RCCA comum {a}->{b}: {fmt(d.mean(), *ic(d))}   FESA liquida {a}->{b}: {fmt(e.mean(), *ic(e))}")
    # por tipo de erro (Fig. 2 com criterio comum)
    R["rcca_comum_por_tipo"] = df.groupby(["et", "cond"]).rcca_comum.mean().round(4).unstack().to_dict(orient="index")
    R["esr_por_tipo"] = df.groupby(["et", "cond"]).esr.apply(lambda s: pd.to_numeric(s).mean()).round(4).unstack().to_dict(orient="index")
    print("   RCCA comum por tipo:", {k: {c: round(v, 2) for c, v in d.items()} for k, d in R["rcca_comum_por_tipo"].items()})
    print("   ESR por tipo:", {k: {c: round(v, 2) for c, v in d.items()} for k, d in R["esr_por_tipo"].items()})

    # ---------------- B1: profundidade literal x derivacao --------------
    b1 = df.groupby(["cond", "q"])[["propagation_depth", "depth_literal", "depth_deriv", "analyst_literal", "analyst_deriv"]].apply(
        lambda x: x.apply(pd.to_numeric).mean())
    R["B1"] = {c: b1.loc[c].mean().round(4).to_dict() for c in "ABCD"}
    print("B1 profundidade total / so repeticao literal / com numeros novos:")
    for c in "ABCD":
        m = b1.loc[c].mean()
        print(f"   {c}: {m.propagation_depth:.2f} = literal {m.depth_literal:.2f} + derivacao {m.depth_deriv:.2f} "
              f"| Analista so-literal {m.analyst_literal:.2f}, com derivacao {m.analyst_deriv:.2f}")
    R["B1_delta"] = {}
    for col in ("depth_literal", "depth_deriv"):
        d = b1.loc["B"][col] - b1.loc["A"][col]
        R["B1_delta"][col] = [d.mean(), *ic(d)]
        print(f"   A->B {col}: {fmt(d.mean(), *ic(d))}")
    for et in ("value", "metadata"):
        x = df[df.et == et].groupby("cond")[["depth_literal", "depth_deriv"]].mean()
        R[f"B1_{et}"] = x.round(4).to_dict()
        print(f"   braco {et}:", x.round(2).to_dict())

    # ---------------- B3: acuracia estrita ------------------------------
    df["acc_estrita"] = pd.to_numeric(df.acc_estrita, errors="coerce")
    acc = df.groupby(["cond", "q"])[["final_correct", "acc_estrita"]].mean()
    R["B3"] = {c: acc.loc[c].mean().round(4).to_dict() for c in "ABCD"}
    print("B3 acuracia permissiva x estrita:", {c: (round(acc.loc[c].final_correct.mean(), 2), round(acc.loc[c].acc_estrita.mean(), 2)) for c in "ABCD"})
    R["B3_delta"] = {}
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        d = acc.loc[b].acc_estrita - acc.loc[a].acc_estrita
        R["B3_delta"][a + b] = [d.mean(), *ic(d)]
        print(f"   estrita {a}->{b}: {fmt(d.mean(), *ic(d))}")

    # ---------------- A5 (parte R): tokens de saida e amplificacao normalizada
    df["amplification"] = pd.to_numeric(df.amplification)
    df["amp_norm"] = df.amplification / df.n_emit.replace(0, np.nan)
    tok = df.groupby("cond")[["in_tokens", "out_tokens", "n_emit", "amplification", "amp_norm"]].mean()
    R["A5"] = tok.round(3).to_dict()
    print("A5 tokens de entrada/saida, numeros emitidos, amplificacao bruta e normalizada:")
    print(tok.round(2).to_string())
    def stage_tokens(c):
        out = inp = reas = 0
        for e in map(json.loads, open(c.path)):
            if e["event_type"] == "stage_output" and e.get("stage") in ("analyst", "writer") and e.get("usage"):
                out += e["usage"].get("output_tokens", 0); inp += e["usage"].get("input_tokens", 0)
                reas += e["usage"].get("reasoning_tokens", 0) or 0
        return {"cond": str(c.condition), "out": out, "inp": inp, "reasoning": reas}
    ctr_tok = pd.DataFrame([stage_tokens(c) for c in controls])
    R["A5_ctrl"] = ctr_tok.groupby("cond").mean().round(1).to_dict()
    print("   controles:", ctr_tok.groupby("cond").mean().round(0).to_dict())

    # ---------------- Holm sobre os 21 testes do modelo ----------------
    M = ["final_correct", "corrected", "esr", "propagation_depth", "amplification", "rcca", "fesa"]
    for m in M:
        df[m] = pd.to_numeric(df[m], errors="coerce")
    p = df.groupby(["cond", "q"])[M].mean()
    tests = []
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        for m in M:
            d = p.loc[b][m] - p.loc[a][m]
            lo, hi = ic(d)
            tests.append((f"{a}{b}:{m}", boot_p(d), lo > 0 or hi < 0))
    order = sorted(range(len(tests)), key=lambda i: tests[i][1])
    surv, k = set(), len(tests)
    for rank, i in enumerate(order):
        if tests[i][1] <= 0.05 / (k - rank):
            surv.add(tests[i][0])
        else:
            break
    sig = [t[0] for t in tests if t[2]]
    R["holm"] = {"significativos_ic": sig, "sobrevivem_holm": sorted(surv)}
    print(f"Holm: {len(sig)} significativos pelo IC, {len(surv)} sobrevivem; perdem:", sorted(set(sig) - surv))

    # ---------------- custo por ganho ----------------------------------
    tk = df.groupby(["cond", "q"]).pipeline_tokens.mean()
    R["custo_ganho"] = {}
    for a, b in [("B", "C"), ("C", "D")]:
        dt = (tk.loc[b] - tk.loc[a]).mean()
        dr = (iq.loc[b].rcca_comum - iq.loc[a].rcca_comum).mean()
        de = (p.loc[b].esr - p.loc[a].esr).mean()
        R["custo_ganho"][a + b] = {"tokens": dt, "rcca_comum": dr, "esr": de,
                                   "rcca_por_mil": 1000 * dr / dt, "esr_por_mil": 1000 * de / dt}
        print(f"custo {a}->{b}: +{dt:.0f} tokens, RCCA comum {dr:+.2f} ({1000 * dr / dt:+.3f}/mil), ESR {de:+.2f} ({1000 * de / dt:+.3f}/mil)")

    # ---------------- B5: vazamentos do erro de metadado ---------------
    meta = [c for c in cells if not c.is_control and c.error_type == "metadata" and str(c.condition) == "D"
            and c.question_id in set(df[df.et == "metadata"].q)]
    b5 = Counter()
    for c in meta:
        rec = c.injection
        orig, corr = int(rec["original_value"]), int(rec["corrupted_value"])
        oc = rec.get("original_claim") or {}
        ext = next(e for e in map(json.loads, open(c.path)) if e["event_type"] == "stage_output" and e["stage"] == "extractor")
        claims = ext["claims"]
        yr = re.compile(rf"(?<!\d){orig}(?!\d)|FY\s?'?{str(orig)[2:]}(?!\d)")
        b5["n"] += 1
        b5["source_id"] += str(orig) in (oc.get("source_id") or c.gold.get("doc_id", ""))
        b5["pergunta"] += bool(yr.search(c.gold.get("question", "")))
        b5["colisao_mesma_metrica"] += any(
            x["claim_id"] != rec["target_claim_id"] and x["metric"] == oc.get("metric") and x["year"] == corr for x in claims)
        b5["colisao_qualquer"] += any(x["claim_id"] != rec["target_claim_id"] and x["year"] == corr for x in claims)
        b5["evidencia_alvo"] += bool(yr.search(oc.get("evidence") or ""))
        b5["evidencia_qualquer"] += any(yr.search(x.get("evidence") or "") for x in claims)
    R["B5"] = dict(b5)
    print("B5 vazamentos no braco de metadado:", {k: f"{v}/{b5['n']}" for k, v in b5.items()})

    # ---------------- B6: execucoes completas ---------------------------
    allc = [c for c in load_cells(Path("data") / slug / "logs") if is_complete(c.path)]
    cnt = Counter((c.injection_stage, c.error_type or "controle") for c in allc)
    R["B6"] = {f"{k[0]}:{k[1]}": v for k, v in cnt.items()}
    print("B6 execucoes completas por braco:", dict(cnt), "total", len(allc))

    # ---------------- ordem de execucao (latencia) ----------------------
    ts = []
    for c in allc[:400]:
        first = json.loads(open(c.path).readline())
        ts.append((first["ts"], str(c.condition), c.question_id))
    ts.sort()
    switches = sum(1 for x, y in zip(ts, ts[1:]) if x[1] != y[1])
    R["intercalado"] = switches / max(len(ts) - 1, 1)
    print(f"ordem: {R['intercalado']:.2f} das execucoes consecutivas mudam de condicao (1 = intercalado)")

json.dump(OUT, open("analysis/parecer_reanalise.json", "w"), indent=1, default=float)
print("\nok -> analysis/parecer_reanalise.json")

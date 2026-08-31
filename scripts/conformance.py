"""Preflight de conformidade: o codigo implementa o que a proposta especifica?

Cada checagem cita a secao da proposta que a origina e verifica o CODIGO, nao
a documentacao. Nao faz chamada de API -- e para rodar antes do experimento,
quantas vezes for preciso.

    uv run python scripts/conformance.py

Sai com codigo 1 se alguma checagem obrigatoria falhar.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handoff import config, measure, prompts, stages  # noqa: E402
from handoff.conditions import CAPS, Condition, Stage, caps  # noqa: E402
from handoff.injector import (  # noqa: E402
    ERROR_TYPES,
    escalate_unit,
    inject,
    shift_percentage_points,
    shift_year,
    transpose_digits,
)
from handoff.run import run_cell  # noqa: E402
from handoff.schemas.claims import (  # noqa: E402
    STAGE_SCHEMA,
    CanonicalClaim,
    ClaimB,
    ClaimC,
    ClaimD,
)
from handoff.serialization import render_claim_text, to_handoff  # noqa: E402

RESULTS: list[tuple[str, str, str, str]] = []  # (secao, item, status, detalhe)


def check(section: str, item: str, ok: bool, detail: str = "", warn: bool = False):
    status = "OK" if ok else ("AVISO" if warn else "FALHA")
    RESULTS.append((section, item, status, detail))


CLAIM = CanonicalClaim(
    claim_id="C17", metric="revenue", value=14.2, unit="USD_M", year=2026,
    period="FY2026", entity="ACME", source_id="annual_report_2026.pdf", page=14,
    generated_by=Stage.EXTRACTOR, derived_from=["C08"],
    evidence="Revenue for fiscal 2026 was $12.4 million...",
)


# ==========================================================================
def s4_hipoteses():
    """Secao 4: cada hipotese precisa de colunas que a testem."""
    fonte = inspect.getsource(measure.to_records)
    hipoteses = {
        "H1 texto livre transforma o erro e perde a origem (AxB)":
            ["fate", "rcca"],
        "H2 estrutura melhora validade, nao correcao (AxB)":
            ["schema_validity", "final_correct"],
        "H3 lineage melhora atribuicao de causa raiz (BxC)":
            ["rcca", "fesa"],
        "H4 evidencia produz re-grounding: correcao e contencao (CxD)":
            ["corrected", "fate", "propagation_depth"],
    }
    for nome, campos in hipoteses.items():
        faltando = [c for c in campos if f'"{c}"' not in fonte]
        check("4", nome, not faltando, ", ".join(campos) if not faltando
              else f"faltando: {faltando}")

    # H2 so e mensuravel onde ha contrato estrutural -- e o que a proposta diz.
    check("4", "Schema Validity aplicavel a B/C/D, nula em A",
          "None na condicao A" in inspect.getsource(measure.schema_validity)
          or "flags else None" in inspect.getsource(measure.schema_validity),
          "secao 9: 'aplicavel a B, C e D'")


def s5_escopo():
    """Secao 5: pipeline fixo, 4 condicoes, controle de validade interna."""
    check("5", "pipeline Extrator -> Analista -> Redator",
          [s.value for s in Stage] == ["extractor", "analyst", "writer"])

    check("5", "quatro condicoes A/B/C/D", [c.value for c in Condition] == list("ABCD"))

    esperado = {
        Condition.A: (False, False, False), Condition.B: (True, False, False),
        Condition.C: (True, True, False), Condition.D: (True, True, True),
    }
    ok = all(
        (caps(c).structure, caps(c).lineage, caps(c).evidence) == v
        for c, v in esperado.items()
    )
    check("5", "tabela estrutura/lineage/evidencia", ok, str(len(CAPS)) + " condicoes")

    # Controle de validade interna: C nao pode dereferenciar a fonte.
    src = inspect.getsource(stages._build_agent)
    check("5", "C nao dereferencia a fonte: agentes sem tools",
          "tools=None" in src, "nenhum estagio tem ferramenta de busca")

    # O documento so entra no prompt do Extrator.
    downstream_src = inspect.getsource(prompts.stage_prompt)
    check("5", "documento nao chega aos estagios downstream",
          "evidence" not in downstream_src and "document" not in downstream_src,
          "stage_prompt so recebe pergunta + payload de handoff")


def s6_handoffs():
    """Secao 6: o conjunto EXATO de campos de cada condicao."""
    b = {"metric", "value", "unit", "year"}
    c = b | {"claim_id", "source_id", "page", "generated_by", "derived_from"}
    d = c | {"evidence"}

    check("6", "B = metric/value/unit/year", set(ClaimB.model_fields) == b,
          sorted(ClaimB.model_fields))
    check("6", "C = B + claim_id/source_id/page/generated_by/derived_from",
          set(ClaimC.model_fields) == c)
    check("6", "D = C + evidence", set(ClaimD.model_fields) == d)

    # A e prosa sem estrutura, sem provenance e sem evidencia. A pagina do
    # fixture e 99 de proposito: com page=14 a checagem colidiria com o "14"
    # de "$14.2M" e acusaria vazamento onde nao ha.
    marcado = CLAIM.model_copy(update={"page": 99, "claim_id": "CXX"})
    texto = render_claim_text(marcado)
    vazou = [
        x for x in ("CXX", "annual_report_2026.pdf", "99", "page", "derived_from", "C08")
        if x in texto
    ]
    check("6", "A e prosa sem provenance", not vazou, texto)
    check("6", "A nao vaza a evidencia", "12.4 million" not in texto)
    check("6", "A nao usa LLM para serializar",
          "Agent" not in inspect.getsource(render_claim_text),
          "template deterministico: A nao ganha variavel extra")

    check("6", "A sem output_schema (texto livre)",
          STAGE_SCHEMA[(Condition.A, Stage.ANALYST)] is None
          and STAGE_SCHEMA[(Condition.A, Stage.WRITER)] is None)
    check("6", "B/C/D com output_schema",
          all(STAGE_SCHEMA[(c, s)] is not None
              for c in (Condition.B, Condition.C, Condition.D)
              for s in (Stage.ANALYST, Stage.WRITER)))


def s7_erros():
    """Secao 7: as tres classes, deterministicas, com ground truth."""
    check("7", "value error 12.4 -> 14.2", transpose_digits(12.4)[0] == 14.2)
    check("7", "percentage error 8.1 -> 11.1", shift_percentage_points(8.1)[0] == 11.1)
    check("7", "metadata error 2025 -> 2026", shift_year(2025)[0] == 2026)
    check("7", "metadata error USD_M -> USD_B", escalate_unit("USD_M")[0] == "USD_B")
    check("7", "tres classes de erro", set(ERROR_TYPES) ==
          {"value", "percentage", "metadata"})

    # Determinismo: duas chamadas identicas.
    claims = [CLAIM.model_copy(update={"value": 12.4})]
    a, ra = inject(claims, "value")
    b, rb = inject(claims, "value")
    check("7", "perturbacao deterministica (sem RNG)",
          ra.model_dump() == rb.model_dump()
          and [x.model_dump() for x in a] == [x.model_dump() for x in b])

    campos = set(ra.model_dump())
    check("7", "ground truth registrado",
          {"original_value", "corrupted_value", "target_claim_id",
           "stage_injected", "rule"} <= campos)

    # Injecao cedo (Extrator) e subestudo em outros estagios.
    sig = inspect.signature(run_cell).parameters
    check("7", "injecao cedo, apos saida correta do Extrator",
          sig["injection_stage"].default is Stage.EXTRACTOR)
    check("7", "subestudo com falhas em estagios diferentes",
          "injection_stage" in sig, "run_cell(injection_stage=Stage.ANALYST)")


def s8_protocolo():
    """Secao 8: os 7 passos do protocolo minimo."""
    subset = config.SUBSET_PATH
    n = len(subset.read_text().splitlines()) if subset.exists() else 0
    check("8.1", "benchmark com respostas e evidencias", n > 0,
          f"FinanceBench, {n} perguntas em {subset.name}")

    check("8.2", "estado correto -> Error Injector deterministico",
          "extract_state" in dir(__import__("handoff.run", fromlist=["x"])))

    # Passo 3: o MESMO estado incorreto nas 4 condicoes.
    corrompido, rec = inject([CLAIM.model_copy(update={"value": 12.4})], "value")
    payloads = {c: to_handoff(corrompido, c) for c in Condition}
    mesmo = (
        str(rec.corrupted_value) in payloads[Condition.A]
        and all(payloads[c][0]["value"] == rec.corrupted_value
                for c in (Condition.B, Condition.C, Condition.D))
    )
    check("8.3", "mesmo estado incorreto serializado em A/B/C/D", mesmo,
          f"valor {rec.corrupted_value} presente nas 4")

    check("8.4", "C bloqueia recuperacao da fonte / D inclui evidencia",
          "evidence" not in ClaimC.model_fields and "evidence" in ClaimD.model_fields)

    check("8.5", "mesma config de modelo nos estagios",
          "config.MODEL_ID" in inspect.getsource(stages._build_agent),
          f"modelo unico: {config.MODEL_ID}")

    destinos = {"preservado", "transformado", "amplificado", "corrigido", "contido"}
    fonte = inspect.getsource(measure.fate)
    check("8.6", "classificacao do destino do erro",
          all(d in fonte for d in destinos),
          "+ sem_efeito (claim fora do caminho da resposta)")

    check("8.7", "seeds para intervalo de confianca", len(config.SEEDS) >= 2,
          f"seeds={config.SEEDS}")


def s9_metricas():
    """Secao 9: as 4 dimensoes + Schema Validity + Operational Overhead."""
    campos = {
        "Final Factual Accuracy": "final_correct",
        "acuracia por tipo de erro": "error_type",
        "Correction Rate": "corrected",
        "Error Survival Rate": "esr",
        "Propagation Depth": "propagation_depth",
        "Error Amplification": "amplification",
        "RCCA": "rcca",
        "FESA": "fesa",
        "Schema Validity": "schema_validity",
        "Overhead: tokens": "pipeline_tokens",
        "Overhead: latencia": "latency_ms",
        "Overhead: chamadas": "n_calls",
        "Overhead: custo": "pipeline_cost_usd",
    }
    fonte = inspect.getsource(measure.to_records)
    for nome, campo in campos.items():
        check("9", nome, f'"{campo}"' in fonte, campo)

    check("9", "custo monetario configurado",
          config.MODEL_ID in config.PRICE_PER_MTOK,
          f"{config.MODEL_ID}: {config.PRICE_PER_MTOK.get(config.MODEL_ID, 'AUSENTE')}")

    # O instrumento de containment NAO pode tocar em `claims`/`derived_from`:
    # A nao tem claims e B nao tem lineage, entao usa-los faria D parecer mais
    # amplificadora so por emitir mais campos. Tudo vem de `output_raw`, via
    # `stage_text`, que existe nas 4 condicoes.
    check("9", "containment sai de output_raw",
          'event.get("output_raw")' in inspect.getsource(measure.load_cell))
    contaminadas = [
        fn.__name__
        for fn in (measure.stage_affected, measure.esr, measure.propagation_depth,
                   measure.amplification, measure.fate)
        if "stage_claims" in inspect.getsource(fn)
        or "derived_from" in inspect.getsource(fn)
    ]
    check("9", "instrumento identico nas 4 condicoes", not contaminadas,
          "nenhuma metrica de containment usa claims/derived_from"
          if not contaminadas else f"contaminadas: {contaminadas}")
    # No subestudo o Analista e compartilhado (canonico, igual nas 4
    # condicoes). Contar o schema_valid dele daria Schema Validity 1.0 para a
    # condicao A, que nao tem contrato estrutural.
    check("9", "estagio compartilhado fora da Schema Validity",
          "shared_across_conditions" in inspect.getsource(measure.load_cell),
          "so estagios que rodam por condicao contam")

    check("9", "lineage e sinal secundario, nao metrica primaria",
          "derived_from" in inspect.getsource(measure.lineage_agreement),
          "lineage_agreement valida o instrumento onde ha proveniencia")

    check("9", "traceability avaliada por atribuicao, nao por presenca de campos",
          "target_claim_id" in inspect.getsource(measure.rcca),
          "RCCA compara com o ground truth da injecao")


def s10_causa_raiz():
    """Secao 10: cadeia Writer -> Analyst -> Extractor reconstruivel."""
    from handoff.conditions import CLAIM_ID_PREFIX, stage_from_claim_id

    check("10", "cadeia derived_from nos tres estagios",
          set(CLAIM_ID_PREFIX) == {Stage.EXTRACTOR, Stage.ANALYST, Stage.WRITER},
          f"prefixos {dict((k.value, v) for k, v in CLAIM_ID_PREFIX.items())}")
    check("10", "estagio de origem legivel no claim_id",
          stage_from_claim_id("C08") is Stage.EXTRACTOR
          and stage_from_claim_id("A01") is Stage.ANALYST
          and stage_from_claim_id("W01") is Stage.WRITER)
    # Controle de primeira ordem: se o auditor visse a injecao ou a resposta
    # do benchmark, RCCA e FESA nao mediriam nada.
    from handoff import auditor

    src = (inspect.getsource(auditor.audit) + inspect.getsource(auditor.build_trace)
           + inspect.getsource(stages.run_auditor))
    vazou = [t for t in ("injection", "InjectionRecord", "gold", "original_value",
                         "corrupted_value", "target_claim_id") if t in src]
    check("10", "auditor nao ve o ground truth da injecao", not vazou,
          f"parametros: {list(inspect.signature(auditor.audit).parameters)}"
          if not vazou else f"vazou: {vazou}")
    check("10", "auditor nao ve a resposta do benchmark", "gold" not in src)
    check("10", "auditor nao ve o documento-fonte",
          "evidence" not in inspect.getsource(auditor.build_trace),
          "so recebe o que o contrato da condicao preservou")

    check("10", "atribuicao errada e detectada como erro",
          "target_claim_id" in inspect.getsource(measure.rcca)
          and "stage_injected" in inspect.getsource(measure.fesa))


def s11_rqs():
    """Secao 11: as comparacoes A x B, B x C, C x D."""
    for rq, (x, y), o_que in (
        ("RQ1", (Condition.A, Condition.B), "estrutura"),
        ("RQ2", (Condition.B, Condition.C), "lineage"),
        ("RQ3", (Condition.C, Condition.D), "evidencia"),
    ):
        cx, cy = caps(x), caps(y)
        difs = [
            n for n in ("structure", "lineage", "evidence")
            if getattr(cx, n) != getattr(cy, n)
        ]
        check("11", f"{rq} ({x}x{y}) isola exatamente '{o_que}'",
              difs == [o_que.replace("evidencia", "evidence")
                       .replace("estrutura", "structure")],
              f"difere em: {difs}")


def s13_fora_de_escopo():
    """Secao 13: o que NAO pode estar no pipeline."""
    src = inspect.getsource(stages._build_agent)
    check("13", "sem retries (nao repara handoff invalido em silencio)",
          "retries=0" in src)
    check("13", "sem parser_model / reflection", "parser_model=None" in src)
    check("13", "sem RAG / ferramentas de busca", "tools=None" in src)
    check("13", "sem majority voting: uma chamada por estagio",
          inspect.getsource(stages._run).count("agent.run") == 1)
    check("13", "topologia linear, sem DAG/ciclo",
          "for stage, upstream in remaining" in inspect.getsource(run_cell))


def s14_reprodutibilidade():
    """Secao 14: protocolo controlado e reproduzivel."""
    params = config.model_params()
    check("14", "config do modelo gravada em todo evento",
          {"model_id", "temperature", "reasoning_effort", "strict_output"} <= set(params),
          json.dumps(params))
    check("14", "braco de controle disponivel",
          inspect.signature(run_cell).parameters["error_type"].annotation is not None,
          "error_type=None roda sem injecao")
    check("14", "log append-only, um arquivo por celula",
          'open("w"' in inspect.getsource(
              __import__("handoff.logger", fromlist=["x"]).JsonlLogger.__init__))


def main() -> int:
    for fn in (s4_hipoteses, s5_escopo, s6_handoffs, s7_erros, s8_protocolo, s9_metricas,
               s10_causa_raiz, s11_rqs, s13_fora_de_escopo, s14_reprodutibilidade):
        fn()

    largura = max(len(i) for _, i, _, _ in RESULTS) + 2
    atual = None
    for secao, item, status, detalhe in RESULTS:
        if secao != atual:
            print(f"\n--- secao {secao} " + "-" * 60)
            atual = secao
        marca = {"OK": "  ok ", "AVISO": " AVISO", "FALHA": " FALHA"}[status]
        print(f"{marca} {item:<{largura}} {detalhe[:60]}")

    falhas = [r for r in RESULTS if r[2] == "FALHA"]
    avisos = [r for r in RESULTS if r[2] == "AVISO"]
    print(f"\n{len(RESULTS)} checagens: {len(RESULTS) - len(falhas) - len(avisos)} ok, "
          f"{len(avisos)} avisos, {len(falhas)} falhas")
    for _, item, _, detalhe in falhas:
        print(f"  FALHA: {item} -- {detalhe}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())

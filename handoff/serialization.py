"""Projecao do estado canonico para o contrato de cada condicao.

Este modulo e o coracao da validade interna do experimento: o MESMO
`CanonicalClaim` corrompido e projetado em A/B/C/D, de modo que a unica
diferenca entre as execucoes seja o contrato de handoff.

A serializacao da condicao A e um template deterministico, NAO uma chamada ao
modelo -- se um LLM parafraseasse o estado, a condicao A carregaria uma
variavel extra (a parafrase) alem da ausencia de estrutura.
"""

from __future__ import annotations

import json
import re

from handoff.conditions import Condition, Stage, caps
from handoff.schemas.claims import (
    CLAIM_SCHEMA,
    UNITS,
    CanonicalClaim,
    ClaimB,
    ClaimC,
    ClaimD,
)

# ==========================================================================
# Renderizacao de valores e da condicao A
# ==========================================================================
_UNIT_SUFFIX = {"USD_K": "K", "USD_M": "M", "USD_B": "B"}


def format_value(value: float, unit: str) -> str:
    """14.2 + USD_M -> '$14.2M'; 11.1 + PCT -> '11.1%'."""
    num = f"{value:g}"
    if unit in _UNIT_SUFFIX:
        return f"${num}{_UNIT_SUFFIX[unit]}"
    if unit == "PCT":
        return f"{num}%"
    return num


def render_claim_text(claim: CanonicalClaim) -> str:
    """Renderiza um claim como prosa, no formato da secao 6 da proposta.

    A condicao A nao tem provenance: o template menciona 'the report'
    generico e NUNCA `source_id`, `page` ou `claim_id`.
    """
    subject = claim.metric.replace("_", " ")
    if claim.entity:
        subject = f"{subject} for {claim.entity}"
    when = claim.period or str(claim.year)
    return f"According to the report, {subject} in {when} was {format_value(claim.value, claim.unit)}."


def render_free_text(claims: list[CanonicalClaim]) -> str:
    return " ".join(render_claim_text(c) for c in claims)


# ==========================================================================
# Projecao canonical -> contrato da condicao
# ==========================================================================
def project_claim(claim: CanonicalClaim, condition: Condition) -> ClaimB | ClaimC | ClaimD:
    """Projeta um claim canonico no contrato tipado de B, C ou D.

    A projecao e uma restricao de campos: o contrato so recebe o que a
    condicao preve. Campos canonicos a mais sao descartados, e nao ignorados
    silenciosamente pelo modelo (todos usam extra="forbid").
    """
    condition = Condition(condition)
    if caps(condition).evidence and not claim.evidence:
        raise ValueError(f"condicao {condition} exige evidence em {claim.claim_id}")

    model = CLAIM_SCHEMA[condition]
    if model is None:
        raise ValueError(f"condicao {condition} nao tem contrato tipado")

    data = claim.model_dump()
    return model.model_validate({k: v for k, v in data.items() if k in model.model_fields})


def to_handoff(claims: list[CanonicalClaim], condition: Condition) -> str | list[dict]:
    """Payload de handoff exatamente como ele segue para o proximo estagio."""
    condition = Condition(condition)
    if condition is Condition.A:
        return render_free_text(claims)
    return [project_claim(c, condition).model_dump() for c in claims]


def render_payload(payload: str | list[dict] | dict) -> str:
    """Payload -> bloco de texto embutivel no prompt do estagio seguinte."""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ==========================================================================
# Controle de vazamento (secao 8.4 da proposta)
# ==========================================================================
_WS = re.compile(r"\s+")


def _shingles(text: str, n: int = 12) -> set[str]:
    words = _WS.sub(" ", text.strip().lower()).split()
    return {" ".join(words[i : i + n]) for i in range(max(len(words) - n + 1, 0))}


def check_evidence_leak(prompt: str, source_text: str, condition: Condition) -> dict:
    """Confere que o documento-fonte nao vazou para um estagio downstream.

    Em A/B/C nenhum trecho do documento pode aparecer no prompt. Em D a
    evidencia esta la de proposito, entao a checagem e apenas informativa.
    """
    condition = Condition(condition)
    overlap = _shingles(prompt) & _shingles(source_text)
    expected = caps(condition).evidence
    return {
        "condition": str(condition),
        "evidence_expected": expected,
        "overlapping_shingles": len(overlap),
        "leaked": bool(overlap) and not expected,
        "sample": sorted(overlap)[0] if overlap else None,
    }


# ==========================================================================
# Verificacao do estado extraido
# ==========================================================================
def value_in_evidence(value: float, evidence: str | None) -> bool:
    """O valor do claim aparece literalmente na evidencia que o sustenta?

    Guarda deterministica contra o Extrator computar metricas em vez de
    extrai-las: no piloto ele produziu `operating income margin = 18.4 PCT`
    anexando como evidencia `"Operatingincome 1,306"` -- um numero derivado
    (e errado) com a evidencia de um numero bruto. Prompt sozinho nao segura
    isso; esta checagem segura.

    Um claim que nao passa continua no estado (foi o pipeline que o produziu)
    mas nao pode ser alvo de injecao: corromper um valor ja fabricado tornaria
    o ground truth da perturbacao sem sentido.
    """
    # Demonstracoes financeiras escrevem negativo entre parenteses: capex de
    # -1577 aparece como "(1,577)". Sem converter, todo claim de capex seria
    # marcado como nao-verificado e sairia do conjunto injetavel.
    text = re.sub(r"\((\d[\d,.\s]*)\)", r"-\1", evidence or "")
    haystack = re.sub(r"[,\s]", "", text)
    if not haystack:
        return False
    candidates = {f"{value:g}", f"{value:.1f}", f"{value:.2f}"}
    if value == int(value):
        candidates.add(str(int(value)))
    return any(c in haystack for c in candidates)


def verify_extraction(claims: list) -> tuple[set[str], list[dict]]:
    """(ids elegiveis para injecao, relatorio por claim) do estado extraido."""
    report = []
    eligible = set()
    for claim in claims:
        ok = value_in_evidence(claim.value, claim.evidence)
        if ok:
            eligible.add(claim.claim_id)
        report.append(
            {
                "claim_id": claim.claim_id,
                "metric": claim.metric,
                "value": claim.value,
                "unit": claim.unit,
                "value_in_evidence": ok,
            }
        )
    return eligible, report


# ==========================================================================
# Checagens de contrato que nenhum JSON Schema pega
# ==========================================================================
def validate_contract(
    claims: list[dict],
    condition: Condition,
    stage: Stage,
    known_ids: set[str],
    source_text: str | None = None,
) -> dict:
    """Violacoes semanticas do contrato, para complementar Schema Validity.

    Com structured outputs nativo, a validade de JSON Schema e ~1.0 por
    construcao. Estas checagens continuam sendo medidas nao-triviais: um
    `derived_from` apontando para id inexistente e uma quebra real da cadeia
    de proveniencia, invisivel para o schema.
    """
    condition = Condition(condition)
    cap = caps(condition)
    checks: dict = {
        "unknown_units": [],
        "duplicate_claim_ids": [],
        "dangling_derived_from": [],
        "empty_derived_from": 0,
        "generated_by_mismatch": 0,
        "evidence_not_literal": 0,
    }
    if not cap.structure:
        return {"applicable": False}
    checks["applicable"] = True

    seen: set[str] = set()
    for claim in claims:
        unit = claim.get("unit")
        if unit not in UNITS:
            checks["unknown_units"].append(unit)

        if cap.lineage:
            cid = claim.get("claim_id")
            if cid in seen or cid in known_ids:
                checks["duplicate_claim_ids"].append(cid)
            if cid:
                seen.add(cid)

            parents = claim.get("derived_from") or []
            if not parents:
                checks["empty_derived_from"] += 1
            for parent in parents:
                if parent not in known_ids and parent not in seen:
                    checks["dangling_derived_from"].append(parent)

            if claim.get("generated_by") != str(stage):
                checks["generated_by_mismatch"] += 1

        if cap.evidence and source_text is not None:
            evidence = _WS.sub(" ", (claim.get("evidence") or "").strip().lower())
            if evidence and evidence not in _WS.sub(" ", source_text.lower()):
                checks["evidence_not_literal"] += 1

    checks["contract_valid"] = (
        not checks["unknown_units"]
        and not checks["duplicate_claim_ids"]
        and not checks["dangling_derived_from"]
        and checks["generated_by_mismatch"] == 0
    )
    return checks

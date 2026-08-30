"""A projecao A/B/C/D e o ponto de validade interna do experimento."""

from __future__ import annotations

import pytest

from handoff.conditions import Condition, Stage
from handoff.injector import inject
from handoff.schemas.claims import CanonicalClaim
from handoff.serialization import (
    check_evidence_leak,
    format_value,
    project_claim,
    render_claim_text,
    to_handoff,
    validate_contract,
)

CLAIM = CanonicalClaim(
    claim_id="C17",
    metric="revenue",
    value=14.2,
    unit="USD_M",
    year=2026,
    period="FY2026",
    entity="ACME",
    source_id="annual_report_2026.pdf",
    page=14,
    generated_by=Stage.EXTRACTOR,
    derived_from=["C08"],
    evidence="Revenue for fiscal 2026 was $12.4 million...",
)


# --- campos exatos da secao 6 da proposta --------------------------------
def test_field_sets_por_condicao():
    assert set(project_claim(CLAIM, Condition.B).model_dump()) == {
        "metric",
        "value",
        "unit",
        "year",
    }
    assert set(project_claim(CLAIM, Condition.C).model_dump()) == {
        "metric",
        "value",
        "unit",
        "year",
        "claim_id",
        "source_id",
        "page",
        "generated_by",
        "derived_from",
    }
    assert set(project_claim(CLAIM, Condition.D).model_dump()) == set(
        project_claim(CLAIM, Condition.C).model_dump()
    ) | {"evidence"}


def test_b_nao_carrega_provenance_e_c_nao_carrega_evidencia():
    b = project_claim(CLAIM, Condition.B).model_dump()
    c = project_claim(CLAIM, Condition.C).model_dump()
    assert "claim_id" not in b and "source_id" not in b
    assert "evidence" not in c


def test_a_e_prosa_sem_provenance():
    text = render_claim_text(CLAIM)
    assert "$14.2M" in text
    assert "annual_report_2026.pdf" not in text
    assert "C17" not in text


def test_format_value():
    assert format_value(14.2, "USD_M") == "$14.2M"
    assert format_value(11.1, "PCT") == "11.1%"


# --- o MESMO estado incorreto nas 4 condicoes ----------------------------
def test_mesmo_valor_corrompido_nas_quatro_condicoes():
    corrupted, record = inject([CLAIM.model_copy(update={"value": 12.4})], "value")
    payloads = {c: to_handoff(corrupted, c) for c in Condition}

    assert str(record.corrupted_value) in payloads[Condition.A]
    for condition in (Condition.B, Condition.C, Condition.D):
        assert payloads[condition][0]["value"] == record.corrupted_value


def test_d_exige_evidencia():
    sem_evidencia = CLAIM.model_copy(update={"evidence": None})
    with pytest.raises(ValueError):
        project_claim(sem_evidencia, Condition.D)


# --- controle de vazamento (secao 8.4) -----------------------------------
def test_vazamento_do_documento_e_detectado_em_c():
    doc = " ".join(f"palavra{i}" for i in range(40))
    leak = check_evidence_leak(f"INPUT:\n{doc}", doc, Condition.C)
    assert leak["leaked"] is True

    limpo = check_evidence_leak("INPUT:\n[{'metric': 'revenue'}]", doc, Condition.C)
    assert limpo["leaked"] is False


def test_em_d_a_evidencia_nao_conta_como_vazamento():
    doc = " ".join(f"palavra{i}" for i in range(40))
    leak = check_evidence_leak(f"INPUT:\n{doc}", doc, Condition.D)
    assert leak["leaked"] is False
    assert leak["evidence_expected"] is True


# --- checagens de contrato ------------------------------------------------
def test_derived_from_pendente_e_flagrado():
    claims = [
        {
            "metric": "growth",
            "value": 8.1,
            "unit": "PCT",
            "year": 2026,
            "claim_id": "A01",
            "source_id": "x",
            "page": 1,
            "generated_by": "analyst",
            "derived_from": ["C99"],
        }
    ]
    checks = validate_contract(claims, Condition.C, Stage.ANALYST, known_ids={"C17"})
    assert checks["dangling_derived_from"] == ["C99"]
    assert checks["contract_valid"] is False


def test_contrato_valido_passa():
    claims = [
        {
            "metric": "growth",
            "value": 8.1,
            "unit": "PCT",
            "year": 2026,
            "claim_id": "A01",
            "source_id": "x",
            "page": 1,
            "generated_by": "analyst",
            "derived_from": ["C17"],
        }
    ]
    checks = validate_contract(claims, Condition.C, Stage.ANALYST, known_ids={"C17"})
    assert checks["contract_valid"] is True


def test_condicao_a_nao_tem_contrato_estrutural():
    assert validate_contract([], Condition.A, Stage.ANALYST, set()) == {
        "applicable": False
    }

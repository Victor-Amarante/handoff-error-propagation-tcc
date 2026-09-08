"""O injector precisa reproduzir a tabela da secao 7 e ser deterministico."""

from __future__ import annotations

import pytest

from handoff.conditions import Stage
from handoff.injector import (
    MIN_RELATIVE_CHANGE,
    escalate_unit,
    inject,
    shift_percentage_points,
    shift_period,
    shift_year,
    transpose_digits,
)
from handoff.schemas.claims import CanonicalClaim


def claim(**over) -> CanonicalClaim:
    base = dict(
        claim_id="C01",
        metric="revenue",
        value=12.4,
        unit="USD_M",
        year=2025,
        period="FY2025",
        entity="ACME",
        source_id="acme_2025_10K",
        page=14,
        generated_by=Stage.EXTRACTOR,
        derived_from=[],
        evidence="Revenue for fiscal 2025 was $12.4 million.",
    )
    base.update(over)
    return CanonicalClaim(**base)


# --- tabela da secao 7 da proposta ---------------------------------------
def test_value_error_reproduz_o_exemplo_da_proposta():
    assert transpose_digits(12.4)[0] == 14.2


def test_percentage_error_reproduz_o_exemplo_da_proposta():
    assert shift_percentage_points(8.1)[0] == 11.1


def test_metadata_error_reproduz_o_exemplo_da_proposta():
    assert shift_year(2025)[0] == 2026
    assert escalate_unit("USD_M")[0] == "USD_B"


# --- determinismo ---------------------------------------------------------
@pytest.mark.parametrize("error_type", ["value", "percentage", "metadata"])
def test_injecao_e_deterministica(error_type):
    claims = [claim(), claim(claim_id="C02", metric="growth", value=8.1, unit="PCT")]
    first, rec_a = inject(claims, error_type, gold_answer="")
    second, rec_b = inject(claims, error_type, gold_answer="")
    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]
    assert rec_a.model_dump() == rec_b.model_dump()


def test_transposicao_idempotente_cai_no_fallback():
    value, rule = transpose_digits(11.1)
    assert value != 11.1
    assert "fallback" in rule


@pytest.mark.parametrize("value", [12.4, 39403.0, 1577.0, 0.81, 5058.0, -1228.0, 100.5])
def test_perturbacao_e_sempre_material(value):
    """Um erro menor que o arredondamento downstream faria o ESR medir ruido."""
    corrupted, _ = transpose_digits(value)
    assert abs(corrupted - value) / abs(value) >= MIN_RELATIVE_CHANGE


def test_transposicao_em_numero_grande_pega_digito_significativo():
    # os pares a direita mudariam 39403 em menos de 10% (39430, 39043)
    assert transpose_digits(39403.0)[0] == 34903.0


def test_troca_com_zero_a_esquerda_e_rejeitada():
    """302578 -> 032578 perderia uma ordem de grandeza (-89%)."""
    corrupted, rule = transpose_digits(302578.0)
    assert corrupted != 32578.0
    assert abs(corrupted - 302578.0) / 302578.0 < 0.5
    assert corrupted == int(corrupted)


@pytest.mark.parametrize("value", [5466312.0, 1486843.0, 2912853.0, 39403.0])
def test_figuras_de_7_digitos_recebem_transposicao(value):
    """`f"{5466312.0:g}"` vira '5.46631e+06' e desviava tudo para o fallback.

    O fallback x1.15 produzia valores como 6286258.8 -- decimais quebrados que
    um balanco nunca teria, tornando o erro trivialmente detectavel.
    """
    corrupted, rule = transpose_digits(value)
    assert "fallback" not in rule
    assert corrupted == int(corrupted), "figura inteira deve continuar inteira"
    assert abs(corrupted - value) / value >= MIN_RELATIVE_CHANGE


def test_percentage_escolhe_claim_em_pct():
    claims = [claim(), claim(claim_id="C02", metric="growth", value=8.1, unit="PCT")]
    _, record = inject(claims, "percentage")
    assert record.target_claim_id == "C02"
    assert record.corrupted_value == 11.1


def test_gold_answer_direciona_o_alvo():
    claims = [
        claim(claim_id="C01", value=99.0),
        claim(claim_id="C02", value=12.4),
    ]
    _, record = inject(claims, "value", gold_answer="Revenue was $12.4 million")
    assert record.target_claim_id == "C02"
    assert "gold" in record.selection_rule


# --- ground truth ---------------------------------------------------------
def test_record_guarda_estado_antes_e_depois():
    claims = [claim()]
    corrupted, record = inject(claims, "value")
    assert record.original_value == 12.4
    assert record.corrupted_value == 14.2
    assert record.field == "value"
    assert record.stage_injected == Stage.EXTRACTOR
    assert record.original_claim["value"] == 12.4
    assert record.corrupted_claim["value"] == 14.2
    # o claim original nao e mutado
    assert claims[0].value == 12.4
    assert corrupted[0].value == 14.2


def test_evidencia_permanece_correta_apos_a_injecao():
    """Em D e a contradicao evidencia x valor que da a chance de re-grounding."""
    corrupted, _ = inject([claim()], "value")
    assert "12.4" in (corrupted[0].evidence or "")
    assert corrupted[0].value == 14.2


# --- periodo acompanha o ano (visibilidade do erro na condicao A) ---------
def test_shift_period_reescreve_o_ano_no_rotulo():
    assert shift_period("FY2025", 2025, 2026) == "FY2026"
    assert shift_period("Q3 2025", 2025, 2026) == "Q3 2026"


def test_shift_period_descarta_rotulo_que_nao_menciona_o_ano():
    """Sem o ano no rotulo nao ha o que reescrever; manter o antigo esconderia
    a perturbacao na prosa de A. Com None, render_claim_text cai no `year` ja
    corrompido."""
    assert shift_period("primeiro semestre", 2025, 2026) is None
    assert shift_period(None, 2025, 2026) is None
    assert shift_period("", 2025, 2026) == ""


def test_injecao_de_ano_corrompe_year_e_period_juntos():
    corrompido, record = inject([claim()], "metadata", metadata_subtype="year_shift")
    assert (corrompido[0].year, corrompido[0].period) == (2026, "FY2026")
    assert "periodo reescrito" in record.rule

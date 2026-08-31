"""O instrumento de medida precisa ser identico nas 4 condicoes."""

from __future__ import annotations

import json

import pytest

from handoff.conditions import Condition, Stage
from handoff.logger import JsonlLogger
from handoff.measure import (
    Number,
    amplification,
    answer_matches_gold,
    correction,
    esr,
    extract_numbers,
    final_correct,
    fate,
    fesa,
    load_cell,
    pair_with_control,
    propagation_depth,
    rcca,
    same_number,
)
from handoff.schemas.events import GoldRecord, InjectionRecord, Usage

GOLD = GoldRecord(
    question_id="q1",
    question="What was the margin?",
    answer="2.8%",
    evidence="Revenue 39,403",
    doc_id="doc",
)

RECORD = InjectionRecord(
    error_type="value",
    error_subtype="digit_transposition",
    rule="transposicao",
    selection_rule="teste",
    stage_injected=Stage.EXTRACTOR,
    target_claim_id="C01",
    field="value",
    original_value=39403.0,
    corrupted_value=34903.0,
    original_claim={"metric": "revenue", "value": 39403.0},
    corrupted_claim={"metric": "revenue", "value": 34903.0},
)


# ==========================================================================
# Extracao numerica
# ==========================================================================
def test_formatos_financeiros():
    nums = extract_numbers("Revenue was $39,403 million, margin 2.8%, up from 12.4M")
    assert any(n.value == 39403 for n in nums)
    assert any(n.value == 2.8 and n.is_pct for n in nums)
    assert any(n.value == 12.4 and n.scale == 1e6 for n in nums)


def test_ids_de_claim_nao_viram_numeros():
    """O JSON de C/D carrega "claim_id": "A01" -- nao e uma assercao numerica."""
    nums = extract_numbers('{"claim_id": "A01", "derived_from": ["C08"], "value": 3.1}')
    assert {n.value for n in nums} == {3.1}


def test_deduplicacao():
    """O JSON de C/D repete page/year em cada claim; sem dedup, infla a amplificacao."""
    assert len(extract_numbers("14 14 14")) == 1


def test_dedup_e_tolerante_a_formato():
    """9.6 e 9.6% no mesmo texto sao a mesma afirmacao, nao duas."""
    assert len(extract_numbers("the margin 9.6 equals 9.6%")) == 1


def test_evidencia_citada_nao_conta_como_assercao():
    """Em D o claim carrega texto literal da fonte.

    Contar os numeros da evidencia faria D parecer sistematicamente mais
    amplificadora so por carregar evidencia -- o confundidor que o modulo
    existe para evitar.
    """
    d = ('{"value":9.3,"unit":"PCT","year":2019,'
         '"evidence":"Operating income  2,112  509  1,306"}')
    valores = {n.value for n in extract_numbers(d)}
    assert 9.3 in valores
    assert not ({2112.0, 509.0, 1306.0} & valores)


def test_tolerancia_de_arredondamento():
    assert same_number(Number(2.8, True), Number(2.8, True))
    assert not same_number(Number(2.8, True), Number(3.1, True))


def test_answer_matches_gold():
    assert answer_matches_gold("The margin was 2.8%.", "2.8%") is True
    assert answer_matches_gold("The margin was 4.4%.", "2.8%") is False
    assert answer_matches_gold("qualquer coisa", "sem numero") is None


# ==========================================================================
# Celulas sinteticas
# ==========================================================================
def _write(tmp_path, name, *, error_type, analyst, writer, final, audit=None,
           stage=Stage.EXTRACTOR):
    path = tmp_path / f"{name}.jsonl"
    logger = JsonlLogger(
        path,
        run_id="r",
        condition=Condition.C,
        seed=1,
        question_id="q1",
        doc_id="doc",
        error_type=error_type,
        injection_stage=stage,
        gold=GOLD,
    )
    with logger:
        logger.emit("run_start", gold=GOLD)
        if error_type:
            logger.emit("injection", stage=Stage.EXTRACTOR, injection=RECORD)
        for stage, text in ((Stage.ANALYST, analyst), (Stage.WRITER, writer)):
            logger.emit(
                "stage_output",
                stage=stage,
                stage_index=1 if stage is Stage.ANALYST else 2,
                output_raw=text,
                schema_valid=True,
                usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15,
                            cost_usd=0.001, latency_ms=100.0),
            )
        logger.emit("audit", audit_report=audit, injection=RECORD if error_type else None)
        logger.emit("run_end", output_raw=final, gold=GOLD,
                    injection=RECORD if error_type else None)
    return load_cell(path)


@pytest.fixture
def control(tmp_path):
    return _write(
        tmp_path, "clean", error_type=None,
        analyst="margins 3.1, 2.3, 3.1", writer="average 2.8%", final="The average was 2.8%.",
    )


def test_erro_preservado_literalmente(tmp_path, control):
    injected = _write(
        tmp_path, "inj", error_type="value",
        analyst="revenue 34903 gives margin 3.5",
        writer="average 34903", final="The figure is 34903.",
    )
    assert esr(injected, control) is True
    assert fate(injected, control) == "preservado"


def test_erro_transformado_sem_valor_literal(tmp_path, control):
    """O valor corrompido some na aritmetica, mas a saida difere da limpa.

    Sem o contrafactual limpo esse caso seria contado como contido.
    """
    injected = _write(
        tmp_path, "inj", error_type="value",
        analyst="margins 3.1, 2.3, 3.1", writer="average 3.5%", final="The average was 3.5%.",
    )
    assert esr(injected, control) is True
    assert fate(injected, control) in ("transformado", "amplificado")


def test_erro_contido_antes_da_saida(tmp_path, control):
    injected = _write(
        tmp_path, "inj", error_type="value",
        analyst="margins 9.9, 2.3, 3.1", writer="average 2.8%", final="The average was 2.8%.",
    )
    assert esr(injected, control) is False
    assert propagation_depth(injected, control) == 1
    assert fate(injected, control) == "contido"


def test_erro_corrigido_quando_valor_original_reaparece(tmp_path, control):
    injected = _write(
        tmp_path, "inj", error_type="value",
        analyst="input said 34903 but the evidence shows 39403; using 39403",
        writer="average 2.8%", final="The average was 2.8%.",
    )
    assert fate(injected, control) == "corrigido"


def test_sem_efeito_nao_e_contencao(tmp_path, control):
    """Claim fora do caminho da resposta: o contrato nunca foi testado."""
    injected = _write(
        tmp_path, "inj", error_type="value",
        analyst="margins 3.1, 2.3, 3.1", writer="average 2.8%", final="The average was 2.8%.",
    )
    assert propagation_depth(injected, control) == 0
    assert fate(injected, control) == "sem_efeito"


def test_correction_rate_nao_conta_erro_fora_do_caminho(tmp_path, control):
    """`sem_efeito` com resposta certa nao e correcao: nada foi corrigido.

    Contar como sucesso premiaria a condicao que por acaso recebeu mais
    injecoes irrelevantes.
    """
    injected = _write(
        tmp_path, "inj", error_type="value",
        analyst="margins 3.1, 2.3, 3.1", writer="average 2.8%", final="The average was 2.8%.",
    )
    assert fate(injected, control) == "sem_efeito"
    assert correction(injected, control) is None


def test_correction_rate_conta_erro_que_entrou_e_foi_corrigido(tmp_path, control):
    injected = _write(
        tmp_path, "inj", error_type="value",
        analyst="input said 34903 but evidence shows 39403; using 39403",
        writer="average 2.8%", final="The average was 2.8%.",
    )
    assert fate(injected, control) == "corrigido"
    assert correction(injected, control) is True


def test_correction_rate_nula_quando_a_linha_de_base_ja_errava(tmp_path):
    """Resposta final errada nao diz nada sobre a injecao se o limpo ja errava."""
    ctl = _write(
        tmp_path, "clean_bad", error_type=None,
        analyst="margins 9, 9, 9", writer="average 9.9%", final="The average was 9.9%.",
    )
    injected = _write(
        tmp_path, "inj_bad", error_type="value",
        analyst="margins 8, 8, 8", writer="average 8.8%", final="The average was 8.8%.",
    )
    assert final_correct(ctl) is False
    assert correction(injected, ctl) is None


def test_amplificacao_conta_so_numeros_novos_e_errados(tmp_path, control):
    injected = _write(
        tmp_path, "inj", error_type="value",
        analyst="margins 3.1, 2.3, 3.1 and extra 7.7 and 8.8",
        writer="average 2.8%", final="The average was 2.8%.",
    )
    # 7.7 e 8.8 sao novos e nao batem com o gold; 3.1/2.3 estao na execucao limpa
    assert amplification(injected, control) == 2


def test_valor_corrompido_nao_conta_como_amplificacao(tmp_path, control):
    injected = _write(
        tmp_path, "inj", error_type="value",
        analyst="revenue 34903", writer="average 2.8%", final="The average was 2.8%.",
    )
    assert amplification(injected, control) == 0


# ==========================================================================
# Root-cause
# ==========================================================================
def test_fesa(tmp_path):
    cell = _write(
        tmp_path, "a", error_type="value", analyst="x", writer="y", final="z",
        audit={"first_error_stage": "extractor", "root_cause_claim_id": "C01",
               "reported_metric": "revenue", "reported_value": 34903.0},
    )
    assert fesa(cell) is True

    errado = _write(
        tmp_path, "b", error_type="value", analyst="x", writer="y", final="z",
        audit={"first_error_stage": "analyst", "root_cause_claim_id": None,
               "reported_metric": None, "reported_value": None},
    )
    assert fesa(errado) is False


def test_rcca_por_id_e_por_tupla(tmp_path):
    por_id = _write(
        tmp_path, "a", error_type="value", analyst="x", writer="y", final="z",
        audit={"first_error_stage": "extractor", "root_cause_claim_id": "C01",
               "reported_metric": None, "reported_value": None},
    )
    assert rcca(por_id) is True

    # A e B nao tem ids: o matching precisa funcionar pela tupla metrica+valor
    por_tupla = _write(
        tmp_path, "b", error_type="value", analyst="x", writer="y", final="z",
        audit={"first_error_stage": "extractor", "root_cause_claim_id": None,
               "reported_metric": "revenue", "reported_value": 34903.0},
    )
    assert rcca(por_tupla) is True


def test_rcca_rejeita_id_alucinado(tmp_path):
    """No piloto o auditor devolveu "c1" na condicao B, que nao tem ids."""
    cell = _write(
        tmp_path, "a", error_type="value", analyst="x", writer="y", final="z",
        audit={"first_error_stage": "analyst", "root_cause_claim_id": "c1",
               "reported_metric": "average margin", "reported_value": 3.2},
    )
    assert rcca(cell) is False


# ==========================================================================
# Pareamento
# ==========================================================================
def test_controle_do_subestudo_pareia_com_a_celula_injetada_no_analista(tmp_path):
    """O controle precisa carregar o braco (`injection_stage`), nao None.

    Sem isso o controle do subestudo era lido como 'extractor' e nunca pareava
    com a celula injetada no Analista -- o braco percentual inteiro ficaria
    sem contrafactual.
    """
    limpo = _write(
        tmp_path, "clean_an", error_type=None, stage=Stage.ANALYST,
        analyst="a", writer="b", final="2.8%",
    )
    injetado = _write(
        tmp_path, "inj_an", error_type="percentage", stage=Stage.ANALYST,
        analyst="a", writer="b", final="5.8%",
    )
    assert limpo.injection_stage == "analyst"
    pares = pair_with_control([limpo, injetado])
    assert pares == [(injetado, limpo)]


def test_pareamento_com_o_controle_da_mesma_celula(tmp_path, control):
    injected = _write(
        tmp_path, "inj", error_type="value", analyst="a", writer="b", final="c"
    )
    pares = pair_with_control([control, injected])
    assert len(pares) == 1
    assert pares[0][1] is control


def test_celula_sem_controle_fica_com_containment_nulo(tmp_path):
    from handoff.measure import to_records

    injected = _write(
        tmp_path, "inj", error_type="value", analyst="a", writer="b", final="c"
    )
    (row,) = to_records([injected])
    assert row["has_control"] is False
    assert row["esr"] is None and row["fate"] is None

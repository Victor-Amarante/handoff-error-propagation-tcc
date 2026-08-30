"""Fiacao do run_cell: nomes de arquivo, retomada e escrita nao-duplicante."""

from __future__ import annotations

import json

from handoff.conditions import Condition, Stage
from handoff.logger import JsonlLogger, is_complete, log_path
from handoff.schemas.events import GoldRecord

GOLD = GoldRecord(
    question_id="q1", question="q?", answer="1", evidence="e", doc_id="d"
)


def _logger(path, error_type="value", stage=Stage.EXTRACTOR) -> JsonlLogger:
    return JsonlLogger(
        path,
        run_id="r1",
        condition=Condition.C,
        seed=1,
        question_id="q1",
        doc_id="d",
        error_type=error_type,
        injection_stage=stage,
        gold=GOLD,
    )


def test_nome_do_arquivo_separa_o_subestudo_de_estagio(tmp_path, monkeypatch):
    from handoff import config

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    principal = log_path("q1", "value", Condition.C, 1, Stage.EXTRACTOR)
    subestudo = log_path("q1", "percentage", Condition.C, 1, Stage.ANALYST)
    controle = log_path("q1", None, Condition.C, 1, Stage.EXTRACTOR)

    assert principal.name == "run_q1_value_C_seed1.jsonl"
    assert subestudo.name == "run_q1_percentage_atanalyst_C_seed1.jsonl"
    assert controle.name == "run_q1_clean_C_seed1.jsonl"


def test_subtipos_de_metadata_nao_colidem(tmp_path, monkeypatch):
    """Sem isso, unit_shift gravaria por cima de year_shift e a retomada o pularia."""
    from handoff import config

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    ano = log_path("q1", "metadata", Condition.C, 1, Stage.EXTRACTOR, "year_shift")
    unidade = log_path("q1", "metadata", Condition.C, 1, Stage.EXTRACTOR, "unit_shift")

    assert ano != unidade
    assert ano.name == "run_q1_metadata-year_shift_C_seed1.jsonl"
    # variant nao afeta o braco de controle, que nao tem tipo de erro
    assert (
        log_path("q1", None, Condition.C, 1, Stage.EXTRACTOR, "year_shift").name
        == "run_q1_clean_C_seed1.jsonl"
    )


def test_re_rodar_a_celula_nao_duplica_eventos(tmp_path):
    """Em modo append, duas execucoes se somariam no mesmo arquivo em silencio."""
    path = tmp_path / "run.jsonl"
    for _ in range(2):
        with _logger(path) as logger:
            logger.emit("run_start", gold=GOLD)
            logger.emit("run_end", output_raw="fim")

    lines = [x for x in path.read_text().splitlines() if x.strip()]
    assert len(lines) == 2
    assert [json.loads(x)["event_type"] for x in lines] == ["run_start", "run_end"]


def test_is_complete_reconhece_celula_terminada(tmp_path):
    path = tmp_path / "run.jsonl"
    assert is_complete(path) is False  # inexistente

    with _logger(path) as logger:
        logger.emit("run_start", gold=GOLD)
    assert is_complete(path) is False  # interrompida antes do fim

    with _logger(path) as logger:
        logger.emit("run_start", gold=GOLD)
        logger.emit("run_end", output_raw="fim")
    assert is_complete(path) is True

"""O log precisa conter tudo que as metricas da secao 9 exigem."""

from __future__ import annotations

import json

from handoff.conditions import Condition, Stage
from handoff.injector import inject
from handoff.logger import JsonlLogger
from handoff.schemas.events import GoldRecord, LogEvent, Usage
from tests.test_serialization import CLAIM

GOLD = GoldRecord(
    question_id="q1",
    question="What was revenue?",
    answer="$12.4 million",
    evidence="Revenue for fiscal 2026 was $12.4 million.",
    doc_id="annual_report_2026.pdf",
)


def _logger(tmp_path, condition=Condition.C) -> JsonlLogger:
    return JsonlLogger(
        tmp_path / "run.jsonl",
        run_id="r1",
        condition=condition,
        seed=1,
        question_id="q1",
        doc_id="annual_report_2026.pdf",
        error_type="value",
        injection_stage=Stage.EXTRACTOR,
        gold=GOLD,
    )


def test_uma_linha_por_evento_e_json_valido(tmp_path):
    with _logger(tmp_path) as logger:
        logger.emit("run_start", gold=GOLD)
        logger.emit("stage_output", stage=Stage.ANALYST, stage_index=1)
        logger.emit("run_end", output_raw="final")

    lines = (tmp_path / "run.jsonl").read_text().splitlines()
    assert len(lines) == 3
    events = [LogEvent.model_validate(json.loads(line)) for line in lines]
    assert [e.event_type for e in events] == ["run_start", "stage_output", "run_end"]
    assert all(e.run_id == "r1" and e.condition == Condition.C for e in events)


def test_evento_carrega_ground_truth_da_injecao(tmp_path):
    _, record = inject([CLAIM.model_copy(update={"value": 12.4})], "value")
    with _logger(tmp_path) as logger:
        event = logger.emit("injection", stage=Stage.EXTRACTOR, injection=record)

    assert event.injection is not None
    assert event.injection.target_claim_id == "C17"
    assert event.injection.original_value == 12.4
    assert event.injection.corrupted_value == 14.2


def test_schema_valid_e_none_em_a_e_bool_em_bcd(tmp_path):
    with _logger(tmp_path, Condition.A) as logger:
        livre = logger.emit("stage_output", stage=Stage.ANALYST, schema_valid=None)
    with _logger(tmp_path, Condition.B) as logger:
        tipado = logger.emit("stage_output", stage=Stage.ANALYST, schema_valid=True)

    assert livre.schema_valid is None
    assert tipado.schema_valid is True


def test_custo_por_evento(tmp_path):
    with _logger(tmp_path) as logger:
        event = logger.emit(
            "stage_output",
            stage=Stage.WRITER,
            usage=Usage(input_tokens=100, output_tokens=20, total_tokens=120,
                        latency_ms=812.5, raw={"duration": 0.81}),
        )
    assert event.usage is not None
    assert event.usage.total_tokens == 120
    assert event.usage.latency_ms == 812.5
    assert event.model_params["model_id"]

"""Log estruturado em JSONL -- uma linha por evento, append-only.

Escrita com flush a cada evento: uma execucao interrompida no meio preserva
tudo que ja rodou (chamadas de LLM sao caras para se perder).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from handoff import config
from handoff.conditions import Condition, Stage
from handoff.schemas.events import EventType, GoldRecord, LogEvent


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_path(
    question_id: str,
    error_type: str | None,
    condition: Condition,
    seed: int,
    injection_stage: Stage | None = None,
    variant: str | None = None,
) -> Path:
    """Um arquivo por celula experimental.

    `variant` distingue subtipos do mesmo tipo de erro (year_shift x
    unit_shift). Sem ele os dois gravariam no mesmo arquivo, e a retomada
    pularia o segundo achando que ja rodou.
    """
    safe = question_id.replace("/", "_")
    arm = error_type or "clean"
    if error_type and variant:
        arm = f"{arm}-{variant}"
    at = (
        f"_at{injection_stage}"
        if injection_stage and injection_stage is not Stage.EXTRACTOR
        else ""
    )
    return config.LOG_DIR / f"run_{safe}_{arm}{at}_{condition}_seed{seed}.jsonl"


def is_complete(path: Path) -> bool:
    """A celula ja rodou ate o fim? Usado para retomar o experimento."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        return any(
            json.loads(line).get("event_type") == "run_end"
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except (json.JSONDecodeError, OSError):
        return False


class JsonlLogger:
    """Escreve os eventos de UMA celula experimental."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        condition: Condition,
        seed: int,
        question_id: str,
        doc_id: str,
        error_type: str | None,
        injection_stage: Stage | None,
        gold: GoldRecord | None = None,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self._fixed = {
            "condition": condition,
            "seed": seed,
            "question_id": question_id,
            "doc_id": doc_id,
            "error_type": error_type,
            "injection_stage": injection_stage,
        }
        self.gold = gold
        # Trunca: um arquivo = uma execucao daquela celula. Em modo append,
        # re-rodar a celula misturaria duas execucoes no mesmo arquivo e a
        # analise contaria os eventos duas vezes, sem erro visivel.
        self._fh = self.path.open("w", encoding="utf-8")

    def emit(self, event_type: EventType, **fields: Any) -> LogEvent:
        event = LogEvent(
            schema_version=config.LOG_SCHEMA_VERSION,
            run_id=self.run_id,
            event_id=uuid.uuid4().hex[:12],
            ts=utc_now(),
            event_type=event_type,
            model=config.MODEL_ID,
            model_params=config.model_params(),
            **self._fixed,
            **fields,
        )
        self._fh.write(event.model_dump_json() + "\n")
        self._fh.flush()
        return event

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "JsonlLogger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

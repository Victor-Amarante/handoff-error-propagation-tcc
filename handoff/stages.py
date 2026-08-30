"""Execucao dos estagios do pipeline com Agno.

Camada fina de proposito: tres funcoes, nenhuma classe de agente. O ponto de
controle importante e que NENHUM agente recebe tools, db ou historico -- cada
estagio ve exclusivamente o payload de handoff que lhe foi entregue. E isso
que garante, por construcao, que a condicao C nao consegue dereferenciar
`source_id`/`page`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel

from handoff import config
from handoff.conditions import Condition, Stage
from handoff.prompts import (
    ANALYST_CANONICAL_FORMAT,
    ANALYST_TASK,
    AUDITOR_INSTRUCTIONS,
    EXTRACTOR_INSTRUCTIONS,
    auditor_prompt,
    extractor_prompt,
    stage_instructions,
    stage_prompt,
)
from handoff.schemas.audit import RootCauseReport
from handoff.schemas.claims import (
    STAGE_SCHEMA,
    CanonicalAnalystOutput,
    ExtractorOutput,
)
from handoff.schemas.events import Usage


@dataclass
class StageResult:
    """Resultado de uma chamada ao modelo, ja pronto para virar LogEvent."""

    content: Any
    output_raw: str | None
    schema_name: str | None
    schema_valid: bool | None
    schema_errors: list[str] = field(default_factory=list)
    usage: Usage | None = None


def _build_agent(
    name: str,
    instructions: str,
    output_schema: type[BaseModel] | None,
    seed: int,
) -> Agent:
    model = OpenAIChat(
        id=config.MODEL_ID,
        temperature=config.TEMPERATURE,
        reasoning_effort=config.REASONING_EFFORT,
        seed=seed if config.SEND_SEED else None,
        strict_output=config.STRICT_OUTPUT,
    )
    return Agent(
        name=name,
        model=model,
        instructions=instructions,
        output_schema=output_schema,
        # Sem tools, sem db, sem historico: cada estagio ve so o handoff.
        tools=None,
        db=None,
        markdown=False,
        # Sem retry silencioso: um handoff invalido precisa aparecer como
        # invalido no log, e nao ser reparado por baixo dos panos.
        retries=0,
        parser_model=None,
        telemetry=False,
    )


def _usage_from(run_output: Any, latency_ms: float) -> Usage:
    metrics = getattr(run_output, "metrics", None)
    raw = metrics.to_dict() if metrics is not None else {}
    input_tokens = getattr(metrics, "input_tokens", 0) or 0
    output_tokens = getattr(metrics, "output_tokens", 0) or 0
    cached = getattr(metrics, "cache_read_tokens", 0) or 0
    cost = getattr(metrics, "cost", None)
    if cost is None:
        cost = config.estimate_cost(config.MODEL_ID, input_tokens, output_tokens, cached)
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=getattr(metrics, "total_tokens", 0) or 0,
        cached_tokens=cached,
        reasoning_tokens=getattr(metrics, "reasoning_tokens", 0) or 0,
        cost_usd=cost,
        latency_ms=latency_ms,
        n_calls=1,
        raw=raw,
    )


def _raw_text(run_output: Any) -> str | None:
    """Texto bruto devolvido pelo modelo, gravado em toda condicao.

    Com `output_schema`, `run_output.content` ja e um objeto Pydantic; o texto
    original fica na ultima mensagem do assistente. E ele que sustenta as
    metricas de containment na condicao A, onde nao ha claims estruturados.
    """
    for message in reversed(getattr(run_output, "messages", None) or []):
        if getattr(message, "role", None) == "assistant" and message.content:
            return message.content
    content = getattr(run_output, "content", None)
    return content if isinstance(content, str) else None


def _run(agent: Agent, prompt: str, expected: type[BaseModel] | None) -> StageResult:
    started = time.perf_counter()
    run_output = agent.run(prompt)
    latency_ms = (time.perf_counter() - started) * 1000

    content = run_output.content
    errors: list[str] = []
    if expected is None:
        schema_valid = None  # condicao A: nao ha contrato estrutural
    else:
        schema_valid = isinstance(content, expected)
        if not schema_valid:
            errors.append(
                f"esperado {expected.__name__}, recebido {type(content).__name__}"
            )
    status = getattr(run_output, "status", None)
    if status is not None and str(status).lower().endswith("error"):
        errors.append(f"run status={status}")

    return StageResult(
        content=content,
        output_raw=_raw_text(run_output),
        schema_name=expected.__name__ if expected else None,
        schema_valid=schema_valid,
        schema_errors=errors,
        usage=_usage_from(run_output, latency_ms),
    )


# ==========================================================================
# Estagios
# ==========================================================================
def run_extractor(question: str, document: str, seed: int) -> StageResult:
    """Roda UMA vez por (pergunta x seed); o estado extraido serve as 4 condicoes."""
    agent = _build_agent("Extractor", EXTRACTOR_INSTRUCTIONS, ExtractorOutput, seed)
    return _run(agent, extractor_prompt(question, document), ExtractorOutput)


def run_canonical_analyst(question: str, payload_text: str, seed: int) -> StageResult:
    """Analista compartilhado, em forma canonica rica.

    So e usado quando a injecao acontece no estagio do Analista: como no
    Extrator, roda UMA vez e o estado e projetado nas 4 condicoes, para que o
    erro injetado seja literalmente o mesmo em A/B/C/D.
    """
    instructions = f"{ANALYST_TASK}\n\n{ANALYST_CANONICAL_FORMAT}"
    agent = _build_agent("Analyst", instructions, CanonicalAnalystOutput, seed)
    return _run(
        agent,
        stage_prompt(question, payload_text, "extractor"),
        CanonicalAnalystOutput,
    )


def run_downstream_stage(
    stage: Stage,
    condition: Condition,
    question: str,
    payload_text: str,
    upstream: str,
    seed: int,
) -> StageResult:
    """Executa Analista ou Redator sob o contrato da condicao."""
    schema = STAGE_SCHEMA[(Condition(condition), stage)]
    agent = _build_agent(
        stage.capitalize(), stage_instructions(stage, condition), schema, seed
    )
    return _run(agent, stage_prompt(question, payload_text, upstream), schema)


def run_auditor(question: str, trace: str, final_answer: str, seed: int) -> StageResult:
    """Instrumento de medida de RCCA/FESA. Custo logado separado do pipeline."""
    agent = _build_agent("Auditor", AUDITOR_INSTRUCTIONS, RootCauseReport, seed)
    return _run(agent, auditor_prompt(question, trace, final_answer), RootCauseReport)

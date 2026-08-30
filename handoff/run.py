"""Execucao de uma celula experimental = (pergunta x seed x tipo de erro x condicao).

Ordem dos eventos:

    run_start
    stage_output(extractor)   <- estado canonico, reaproveitado pelas 4 condicoes
    injection                 <- ground truth deterministico
    stage_output(analyst)
    stage_output(writer)
    audit                     <- instrumento de RCCA/FESA, custo isolado
    run_end
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from handoff import config
from handoff.auditor import audit
from handoff.conditions import STAGE_INDEX, Condition, Stage, caps
from handoff.injector import ErrorType, inject
from handoff.logger import JsonlLogger, log_path
from handoff.schemas.claims import (
    CanonicalAnalystOutput,
    CanonicalClaim,
    ExtractorOutput,
    derived_to_canonical,
    to_canonical,
)
from handoff.schemas.events import GoldRecord
from handoff.serialization import (
    check_evidence_leak,
    render_payload,
    to_handoff,
    validate_contract,
    verify_extraction,
)
from handoff.stages import (
    StageResult,
    run_canonical_analyst,
    run_downstream_stage,
    run_extractor,
)


class PipelineError(RuntimeError):
    pass


@dataclass
class SharedState:
    """Estado canonico de um estagio, compartilhado pelas 4 condicoes.

    Todo estagio ATE o ponto de injecao roda uma unica vez por (pergunta x
    seed) e e projetado em A/B/C/D. E o que garante que o erro injetado seja
    literalmente o mesmo nas 4 condicoes (passo 3 do protocolo).
    """

    claims: list[CanonicalClaim]
    output_raw: str | None
    usage: dict | None
    from_cache: bool
    stage: Stage = Stage.EXTRACTOR


#: Nome antigo, mantido porque `extract_state` e usado nos scripts.
Extraction = SharedState


# ==========================================================================
# Estagios compartilhados: rodam uma unica vez por (pergunta x seed)
# ==========================================================================
def _cache_path(question_id: str, seed: int, prefix: str = "extract"):
    return config.CACHE_DIR / f"{prefix}_{question_id.replace('/', '_')}_seed{seed}.json"


def _write_cache(path, question_id: str, seed: int, claims, result) -> dict | None:
    usage = result.usage.model_dump() if result.usage else None
    path.write_text(
        json.dumps(
            {
                "question_id": question_id,
                "seed": seed,
                "claims": [c.model_dump(mode="json") for c in claims],
                "output_raw": result.output_raw,
                "usage": usage,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return usage


def extract_state(row: dict, seed: int, *, use_cache: bool = True) -> Extraction:
    """Extrai (ou recupera do cache) o estado canonico correto da pergunta.

    O cache nao e otimizacao apenas: e o que garante que A/B/C/D partam
    literalmente do mesmo estado antes da injecao.
    """
    config.ensure_dirs()
    path = _cache_path(row["question_id"], seed)
    if use_cache and path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        return Extraction(
            claims=[CanonicalClaim.model_validate(c) for c in cached["claims"]],
            output_raw=cached.get("output_raw"),
            usage=cached.get("usage"),
            from_cache=True,
        )

    result = run_extractor(row["question"], row["evidence"], seed)
    if not isinstance(result.content, ExtractorOutput):
        raise PipelineError(
            f"extrator nao devolveu ExtractorOutput em {row['question_id']}: "
            f"{result.schema_errors}"
        )
    claims = to_canonical(result.content.claims, source_id=row["doc_id"])
    if not claims:
        raise PipelineError(f"extrator nao produziu claims em {row['question_id']}")

    usage = _write_cache(path, row["question_id"], seed, claims, result)
    return SharedState(claims, result.output_raw, usage, False, Stage.EXTRACTOR)


def analyze_state(
    row: dict,
    seed: int,
    extraction: SharedState,
    *,
    use_cache: bool = True,
) -> SharedState:
    """Analista COMPARTILHADO, em forma canonica.

    So roda quando a injecao acontece no estagio do Analista. Consequencia
    metodologica: nesse braco, apenas o Redator e medido por condicao, e a
    Propagation Depth maxima e 1 -- o proposito do subestudo e atribuicao de
    estagio (FESA), nao profundidade de propagacao.
    """
    config.ensure_dirs()
    path = _cache_path(row["question_id"], seed, prefix="analysis")
    if use_cache and path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        return SharedState(
            claims=[CanonicalClaim.model_validate(c) for c in cached["claims"]],
            output_raw=cached.get("output_raw"),
            usage=cached.get("usage"),
            from_cache=True,
            stage=Stage.ANALYST,
        )

    payload_text = render_payload(
        [c.model_dump(mode="json") for c in extraction.claims]
    )
    result = run_canonical_analyst(row["question"], payload_text, seed)
    if not isinstance(result.content, CanonicalAnalystOutput):
        raise PipelineError(
            f"analista canonico falhou em {row['question_id']}: {result.schema_errors}"
        )
    claims = derived_to_canonical(result.content.claims, source_id=row["doc_id"])
    if not claims:
        raise PipelineError(f"analista nao produziu claims em {row['question_id']}")

    usage = _write_cache(path, row["question_id"], seed, claims, result)
    return SharedState(claims, result.output_raw, usage, False, Stage.ANALYST)


# ==========================================================================
# Leitura da saida de um estagio
# ==========================================================================
def _stage_payload(
    result: StageResult, condition: Condition, stage: Stage
) -> tuple[list[dict], str | list[dict] | dict, str | None]:
    """Devolve (claims, payload de handoff, texto final se for o Redator).

    Em A nao ha claims estruturados: o payload e o proprio texto, e as
    metricas de containment sao reconstruidas na analise a partir dele.
    """
    condition = Condition(condition)
    content = result.content

    if not caps(condition).structure:
        text = content if isinstance(content, str) else (result.output_raw or "")
        return [], text, text if stage is Stage.WRITER else None

    if result.schema_valid is False or isinstance(content, str):
        # handoff estruturado invalido: preserva o texto cru para a analise
        return [], result.output_raw or "", result.output_raw

    if stage is Stage.ANALYST:
        claims = [c.model_dump(mode="json") for c in content.claims]
        return claims, claims, None

    claim = content.answer_claim.model_dump(mode="json")
    payload = {"answer_text": content.answer_text, "answer_claim": claim}
    return [claim], payload, content.answer_text


# ==========================================================================
# Celula experimental
# ==========================================================================
def run_cell(
    row: dict,
    seed: int,
    error_type: ErrorType | None,
    condition: Condition,
    *,
    extraction: SharedState | None = None,
    analysis: SharedState | None = None,
    injection_stage: Stage = Stage.EXTRACTOR,
    metadata_subtype: str = "year_shift",
) -> dict:
    """Executa uma celula completa e grava o .jsonl correspondente.

    `error_type=None` executa o BRACO DE CONTROLE: mesmo estado extraido, sem
    injecao. Ele e necessario para as metricas significarem alguma coisa -- o
    pipeline erra algumas perguntas por conta propria, e sem a linha de base
    limpa nao se distingue erro injetado de erro nativo, nem 'erro contido' de
    'erro propagado que por acaso coincidiu com a resposta certa'.

    `injection_stage` escolhe o estudo (secao 7 da proposta):

    * `EXTRACTOR` -- estudo principal de propagacao. Analista e Redator rodam
      por condicao.
    * `ANALYST` -- subestudo de atribuicao de estagio. O Analista tambem roda
      compartilhado, em forma canonica, e so o Redator roda por condicao. E o
      unico ponto do pipeline onde existem claims em PCT, entao e onde a classe
      de erro `percentage` pode ser injetada.
    """
    condition = Condition(condition)
    config.ensure_dirs()

    gold = GoldRecord(
        question_id=row["question_id"],
        question=row["question"],
        answer=row["answer"],
        evidence=row["evidence"],
        doc_id=row["doc_id"],
    )
    extraction = extraction or extract_state(row, seed)
    if injection_stage is Stage.ANALYST:
        analysis = analysis or analyze_state(row, seed, extraction)

    path = log_path(
        row["question_id"],
        error_type,
        condition,
        seed,
        injection_stage,
        variant=metadata_subtype if error_type == "metadata" else None,
    )
    logger = JsonlLogger(
        path,
        run_id=uuid.uuid4().hex[:12],
        condition=condition,
        seed=seed,
        question_id=row["question_id"],
        doc_id=row["doc_id"],
        error_type=error_type,
        # Sempre gravado, inclusive no controle: identifica o BRACO do
        # experimento, nao a existencia de injecao (`error_type=None` ja diz
        # isso). Sem ele o controle do subestudo nao pareia com a celula
        # injetada no Analista, e o braco inteiro perde o contrafactual.
        injection_stage=injection_stage,
        gold=gold,
    )

    with logger:
        logger.emit("run_start", gold=gold, notes={"seeds": list(config.SEEDS)})

        # --- Extrator (estado compartilhado) -----------------------------
        eligible_ids, verification = verify_extraction(extraction.claims)
        logger.emit(
            "stage_output",
            stage=Stage.EXTRACTOR,
            stage_index=STAGE_INDEX[Stage.EXTRACTOR],
            input_payload=row["evidence"],
            output_raw=extraction.output_raw,
            claims=[c.model_dump(mode="json") for c in extraction.claims],
            schema_name="ExtractorOutput",
            schema_valid=True,
            usage=None if extraction.from_cache else extraction.usage,
            contract_checks={
                "verified_claims": len(eligible_ids),
                "total_claims": len(extraction.claims),
                "per_claim": verification,
            },
            notes={
                "shared_across_conditions": True,
                "from_cache": extraction.from_cache,
                "usage_when_cached": extraction.usage if extraction.from_cache else None,
            },
        )

        # --- Analista compartilhado (so no subestudo de estagio) -----------
        handoffs: list[tuple[Stage, Any]] = []
        target_state = extraction
        if injection_stage is Stage.ANALYST:
            assert analysis is not None
            handoffs.append((Stage.EXTRACTOR, to_handoff(extraction.claims, condition)))
            eligible_ids, verification = verify_extraction(analysis.claims)
            logger.emit(
                "stage_output",
                stage=Stage.ANALYST,
                stage_index=STAGE_INDEX[Stage.ANALYST],
                input_payload=handoffs[0][1],
                output_raw=analysis.output_raw,
                claims=[c.model_dump(mode="json") for c in analysis.claims],
                schema_name="CanonicalAnalystOutput",
                schema_valid=True,
                usage=None if analysis.from_cache else analysis.usage,
                contract_checks={
                    "verified_claims": len(eligible_ids),
                    "total_claims": len(analysis.claims),
                    "per_claim": verification,
                },
                notes={
                    "shared_across_conditions": True,
                    "from_cache": analysis.from_cache,
                    "usage_when_cached": analysis.usage if analysis.from_cache else None,
                },
            )
            target_state = analysis
            # claims derivados sao computados, nao copiados: exigir o valor
            # literal na evidencia invalidaria todos eles.
            eligible_ids = {c.claim_id for c in analysis.claims}

        # --- Injecao (ausente no braco de controle) ------------------------
        record = None
        corrupted = target_state.claims
        if error_type is not None:
            corrupted, record = inject(
                target_state.claims,
                error_type,
                stage=injection_stage,
                gold_answer=row["answer"],
                metadata_subtype=metadata_subtype,  # type: ignore[arg-type]
                eligible_ids=eligible_ids,
            )
        handoff: str | list[dict] | dict = to_handoff(corrupted, condition)
        if record is not None:
            logger.emit(
                "injection",
                stage=injection_stage,
                stage_index=STAGE_INDEX[injection_stage],
                claims=[c.model_dump(mode="json") for c in corrupted],
                handoff_payload=handoff,
                injection=record,
            )

        known_ids = {c.claim_id for c in corrupted}
        known_ids |= {c.claim_id for c in extraction.claims}
        handoffs.append((injection_stage, handoff))
        final_answer: str | None = None

        # --- Estagios que rodam POR CONDICAO -------------------------------
        remaining = (
            ((Stage.ANALYST, "extractor"), (Stage.WRITER, "analyst"))
            if injection_stage is Stage.EXTRACTOR
            else ((Stage.WRITER, "analyst"),)
        )
        for stage, upstream in remaining:
            payload_text = render_payload(handoff)
            leak = check_evidence_leak(payload_text, row["evidence"], condition)
            result = run_downstream_stage(
                stage, condition, row["question"], payload_text, upstream, seed
            )
            claims, next_payload, text = _stage_payload(result, condition, stage)
            checks = validate_contract(
                claims, condition, stage, known_ids, source_text=row["evidence"]
            )
            known_ids |= {c["claim_id"] for c in claims if c.get("claim_id")}

            logger.emit(
                "stage_output",
                stage=stage,
                stage_index=STAGE_INDEX[stage],
                input_payload=handoff,
                handoff_payload=next_payload,
                output_raw=result.output_raw,
                output_parsed=(
                    result.content.model_dump(mode="json")
                    if hasattr(result.content, "model_dump")
                    else None
                ),
                claims=claims,
                schema_name=result.schema_name,
                schema_valid=result.schema_valid,
                schema_errors=result.schema_errors,
                contract_checks=checks,
                usage=result.usage,
                notes={"evidence_leak_check": leak},
            )
            handoff = next_payload
            handoffs.append((stage, next_payload))
            if stage is Stage.WRITER:
                final_answer = text or result.output_raw or ""

        # --- Auditor (instrumento, custo isolado) --------------------------
        audit_result = audit(
            row["question"], handoffs, final_answer or "", seed, condition
        )
        report = (
            audit_result.content.model_dump(mode="json")
            if hasattr(audit_result.content, "model_dump")
            else None
        )
        logger.emit(
            "audit",
            output_raw=audit_result.output_raw,
            audit_report=report,
            schema_name=audit_result.schema_name,
            schema_valid=audit_result.schema_valid,
            schema_errors=audit_result.schema_errors,
            usage=audit_result.usage,
            injection=record,
            notes={"instrument": True, "excluded_from_pipeline_cost": True},
        )

        logger.emit(
            "run_end",
            output_raw=final_answer,
            gold=gold,
            injection=record,
            audit_report=report,
        )

    return {
        "path": path,
        "final_answer": final_answer,
        "injection": record.model_dump(mode="json") if record else None,
        "audit_report": report,
    }

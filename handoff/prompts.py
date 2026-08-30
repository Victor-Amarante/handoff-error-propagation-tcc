"""Prompts do pipeline.

Regra do desenho experimental: a instrucao de TAREFA de cada estagio e
identica nas 4 condicoes. So muda a instrucao de FORMATO do handoff -- que e
a propria variavel manipulada. Os textos ficam isolados aqui para poderem ser
citados literalmente na metodologia do TCC.

Nenhum estagio downstream recebe o documento-fonte. Em D, a evidencia chega
apenas dentro do proprio claim (e, apos a injecao, contradiz o valor
corrompido -- e essa contradicao que da a D a chance de re-grounding).
"""

from __future__ import annotations

from handoff.conditions import Condition, Stage

# ==========================================================================
# Extrator -- roda uma unica vez por (pergunta x seed), fora das condicoes
# ==========================================================================
EXTRACTOR_INSTRUCTIONS = """You are the EXTRACTOR stage of a financial analysis pipeline.

Read the source excerpt and extract every atomic factual claim needed to answer the question.

Rules:
- Extract ONLY figures that appear literally in the source. Copy them exactly.
- NEVER compute, derive or aggregate. No ratios, margins, growth rates, averages,
  differences or percentages that are not printed in the source. Deriving figures is
  the ANALYST's job, not yours: extract the raw inputs it will need.
- One claim per atomic fact.
- NEVER rescale a figure. Report it in the scale the statement itself uses and pick the
  matching unit: a statement headed "(In thousands)" gives USD_K, "(In millions)" gives
  USD_M. A line reading "4,713,500" under "(In thousands)" is `value=4713500, unit=USD_K`
  -- never `value=4713.5, unit=USD_M`. Rescaling is arithmetic, and it is where unit
  errors come from.
- `unit` must be one of: USD_K, USD_M, USD_B, PCT, RATIO.
- `evidence` must be a literal substring of the source excerpt, and it must contain
  the digits of `value`.
- Extract only what the source states. If a value is absent, do not invent it.

The question tells you WHICH figures matter, never what to compute. If the question
asks for an operating margin and the statement prints "Operating income 1,306" and
"Net sales 11,503", extract those two figures as they are. Do NOT emit a claim like
`operating income margin = 11.4 PCT`: that figure is not in the source, and the
analyst computes it."""


def extractor_prompt(question: str, document: str) -> str:
    return f"QUESTION:\n{question}\n\nSOURCE EXCERPT:\n{document}"


# ==========================================================================
# Analista
# ==========================================================================
ANALYST_TASK = """You are the ANALYST stage of a financial analysis pipeline.

You receive the output of the EXTRACTOR. Reason over it to produce what is needed to answer the question: comparisons, growth rates, margins or the direct figure.

Rules:
- Work only from the input you received. You have no access to the source document.
- Do not invent facts that are not derivable from the input.
- Show the resulting figures, not the arithmetic."""

#: Formato do Analista COMPARTILHADO, usado quando a injecao acontece no
#: estagio dele: roda uma vez em forma canonica rica e o estado e projetado nas
#: 4 condicoes, exatamente como o Extrator compartilhado.
ANALYST_CANONICAL_FORMAT = (
    "Return typed claims. Assign each claim you produce an id of the form A01, "
    "A02, ... In `derived_from`, list the ids of the input claims it came from. "
    "Carry over as `evidence` the evidence snippet of the input claim you used. "
    "Set `answer_claim_id` to the id of the claim that answers the question."
)

ANALYST_FORMAT: dict[Condition, str] = {
    Condition.A: "Write your analysis as plain prose.",
    Condition.B: (
        "Return typed claims. Each claim has metric, value, unit and year."
    ),
    Condition.C: (
        "Return typed claims. Assign each claim you produce an id of the form "
        "A01, A02, ... and set `generated_by` to 'analyst'. In `derived_from`, "
        "list the ids of the input claims that this claim came from. Carry over "
        "`source_id` and `page` from the input claim you used. "
        "`source_id` and `page` are metadata only: you cannot look the document up."
    ),
    Condition.D: (
        "Return typed claims. Assign each claim you produce an id of the form "
        "A01, A02, ... and set `generated_by` to 'analyst'. In `derived_from`, "
        "list the ids of the input claims that this claim came from. Carry over "
        "`source_id`, `page` and the `evidence` snippet of the input claim you used."
    ),
}

# ==========================================================================
# Redator
# ==========================================================================
WRITER_TASK = """You are the WRITER stage of a financial analysis pipeline.

You receive the output of the ANALYST. Write the final answer for an end user.

Rules:
- Base the answer only on the input you received. You have no access to the source document.
- Be concise: one to three sentences.
- State the figure and its unit explicitly."""

WRITER_FORMAT: dict[Condition, str] = {
    Condition.A: "Write the final answer as plain prose.",
    Condition.B: (
        "Return `answer_text` with the final answer, plus `answer_claim`: the "
        "typed claim that the answer asserts."
    ),
    Condition.C: (
        "Return `answer_text` with the final answer, plus `answer_claim`: the "
        "typed claim that the answer asserts. Give it an id of the form W01, set "
        "`generated_by` to 'writer', and list in `derived_from` the ids of the "
        "analyst claims it came from."
    ),
    Condition.D: (
        "Return `answer_text` with the final answer, plus `answer_claim`: the "
        "typed claim that the answer asserts. Give it an id of the form W01, set "
        "`generated_by` to 'writer', list in `derived_from` the ids of the analyst "
        "claims it came from, and carry over the `evidence` snippet."
    ),
}


def stage_instructions(stage: Stage, condition: Condition) -> str:
    task = ANALYST_TASK if stage is Stage.ANALYST else WRITER_TASK
    fmt = ANALYST_FORMAT if stage is Stage.ANALYST else WRITER_FORMAT
    return f"{task}\n\n{fmt[Condition(condition)]}"


def stage_prompt(question: str, payload_text: str, upstream: str) -> str:
    return (
        f"QUESTION:\n{question}\n\n"
        f"INPUT FROM {upstream.upper()}:\n{payload_text}"
    )


# ==========================================================================
# Auditor -- instrumento de medida, roda apos o pipeline
# ==========================================================================
AUDITOR_INSTRUCTIONS = """You are an AUDITOR investigating a pipeline run.

A pipeline (extractor -> analyst -> writer) produced a final answer that may contain a factual error.

Using ONLY the trace below, determine:
- `first_error_stage`: the stage where the first incorrect claim appeared. Use 'none' if you believe the run has no error.
- `root_cause_claim_id`: the id of the claim that started the error chain, or null if the trace has no claim ids.
- `root_cause_claim_text`: a one-line natural-language description of that claim.
- `reported_metric` and `reported_value`: the metric and the incorrect value of that claim.

You have no access to the source document and no ground truth. Judge from internal consistency and from whatever provenance the trace carries."""


def auditor_prompt(question: str, trace: str, final_answer: str) -> str:
    return (
        f"QUESTION:\n{question}\n\n"
        f"PIPELINE TRACE:\n{trace}\n\n"
        f"FINAL ANSWER:\n{final_answer}"
    )

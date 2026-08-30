"""Probe de root-cause: mede RCCA e FESA.

Roda DEPOIS do pipeline, como instrumento de medida, e nunca como parte dele.
Duas consequencias de desenho:

* Extrator, Analista e Redator ficam identicos entre as condicoes -- nenhum
  deles carrega a tarefa extra de se autodiagnosticar.
* O auditor ve exclusivamente o que o contrato daquela condicao preservou.
  E essa assimetria de ENTRADA (nao de formato de saida) que a comparacao
  A x B x C x D esta medindo.

O auditor nunca ve o `InjectionRecord`, a resposta gold, nem o documento.
"""

from __future__ import annotations

from handoff.conditions import Condition, Stage
from handoff.serialization import render_payload
from handoff.stages import StageResult, run_auditor


def build_trace(
    handoffs: list[tuple[Stage, str | list[dict] | dict]],
) -> str:
    """Monta o trace na forma em que o contrato da condicao o preservou.

    Em A o trace e a prosa produzida por cada estagio; em B, os claims tipados
    sem ids; em C/D, os claims com a cadeia de proveniencia. Nenhuma
    informacao e adicionada aqui -- so concatenacao rotulada por estagio.
    """
    blocks = []
    for stage, payload in handoffs:
        blocks.append(f"--- {str(stage).upper()} OUTPUT ---\n{render_payload(payload)}")
    return "\n\n".join(blocks)


def audit(
    question: str,
    handoffs: list[tuple[Stage, str | list[dict] | dict]],
    final_answer: str,
    seed: int,
    condition: Condition,
) -> StageResult:
    del condition  # a condicao ja esta refletida no conteudo de `handoffs`
    return run_auditor(question, build_trace(handoffs), final_answer, seed)

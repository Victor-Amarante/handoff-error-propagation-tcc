"""Error Injector deterministico (secao 7 da proposta).

Tres classes de erro, todas SEM RNG -- dada a mesma entrada, a saida e sempre
a mesma, e a perturbacao e registrada como ground truth do experimento:

    value error       $12.4M -> $14.2M   transposicao de digitos adjacentes
    percentage error  8.1%   -> 11.1%    deslocamento fixo de +3.0 p.p.
    metadata error    2025   -> 2026     year_shift (+1, e `period` junto)
                      USD_M  -> USD_B    unit_shift (uma ordem de grandeza acima)

Toda perturbacao precisa ser DETECTAVEL na saida final: um erro menor que o
arredondamento do estagio seguinte faria as metricas de containment medirem
ruido em vez de propagacao (ver MIN_RELATIVE_CHANGE).

A injecao acontece sobre o estado canonico, uma unica vez por (pergunta x
seed x tipo de erro). O estado corrompido resultante e depois projetado nas 4
condicoes -- e por isso que A/B/C/D veem literalmente o mesmo erro.
"""

from __future__ import annotations

import re
from typing import Literal

from handoff.conditions import Stage
from handoff.schemas.claims import CanonicalClaim
from handoff.schemas.events import InjectionRecord

ErrorType = Literal["value", "percentage", "metadata"]
ERROR_TYPES: tuple[ErrorType, ...] = ("value", "percentage", "metadata")

PP_SHIFT = 3.0
UNIT_ESCALATION = {
    "USD_K": "USD_M",
    "USD_M": "USD_B",
    "USD_B": "USD_M",
    "PCT": "RATIO",
    "RATIO": "PCT",
}

#: Unidades que cada tipo de erro prefere no claim-alvo. Aplicar +3 p.p. a um
#: valor em USD_M seria uma perturbacao sem sentido economico.
PREFERRED_UNITS: dict[ErrorType, tuple[str, ...]] = {
    "value": ("USD_K", "USD_M", "USD_B"),
    "percentage": ("PCT",),
    "metadata": (),
}


class InjectionError(RuntimeError):
    """Nenhum claim elegivel para o tipo de erro pedido."""


# ==========================================================================
# Perturbacoes
# ==========================================================================
#: Mudanca relativa minima para a perturbacao ser detectavel na saida final.
#: Sem esse piso, transpor os dois ultimos digitos de 39403 (-> 39430) produz
#: um erro de 0.07% que desaparece no arredondamento do estagio seguinte, e as
#: metricas de containment passariam a medir ruido.
MIN_RELATIVE_CHANGE = 0.10


def _plain(value: float) -> str:
    """Decimal sem notacao cientifica.

    `f"{5466312.0:g}"` devolve '5.46631e+06', e figuras financeiras com 7+
    digitos sao comuns no FinanceBench. Sem isso elas nunca recebiam
    transposicao e caiam no fallback x1.15, que produz valores com decimais
    quebrados (6286258.8) -- implausiveis num balanco e por isso trivialmente
    detectaveis, o que confundiria o experimento.
    """
    if value == int(value):
        return str(int(value))
    text = repr(float(value))
    if "e" in text or "E" in text:
        text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text


def transpose_digits(value: float) -> tuple[float, str]:
    """Troca o par de digitos adjacentes MAIS A DIREITA que muda o valor em >=10%.

    Reproduz o exemplo canonico da proposta -- 12.4 -> 14.2, o par (2,4) -- e
    ao mesmo tempo garante perturbacao material em numeros de qualquer ordem
    de grandeza: 39403 -> 34903, o par (9,4), ja que os pares a direita dele
    alterariam o valor em menos de 10%.

    Sem nenhum par elegivel (11.1, 200.0, digito unico), cai no fallback x1.15.
    """
    text = _plain(value)
    sign = "-" if text.startswith("-") else ""
    body = text.lstrip("-")

    digits = [ch for ch in body if ch.isdigit()]
    if len(digits) < 2:
        return _scale_fallback(value)

    floor = max(abs(value), 1e-12) * MIN_RELATIVE_CHANGE
    for i in range(len(digits) - 2, -1, -1):
        swapped = list(digits)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        out, k = [], 0
        for ch in body:
            if ch.isdigit():
                out.append(swapped[k])
                k += 1
            else:
                out.append(ch)
        new_body = "".join(out)
        # Troca que joga um zero para a frente (302578 -> 032578) faz o numero
        # perder uma ordem de grandeza: -89%, conspicuo demais e heterogeneo
        # em relacao as demais perturbacoes (~10-20%).
        if body[0] != "0" and new_body[0] == "0":
            continue
        candidate = float(sign + new_body)
        if abs(candidate - value) >= floor:
            return candidate, (
                "transposicao do par de digitos adjacentes mais a direita que "
                f"altera o valor em >= {MIN_RELATIVE_CHANGE:.0%}"
            )
    return _scale_fallback(value)


def _scale_fallback(value: float) -> tuple[float, str]:
    """x1.15, preservando a forma do numero.

    Figura inteira continua inteira: 347964.7 num balanco denuncia a injecao
    so pelo formato, o que tornaria o erro detectavel pelo motivo errado.
    """
    rule = "fallback x1.15 (sem par de digitos elegivel)"
    if value == int(value):
        return float(round(value * 1.15)), rule
    decimals = len(_plain(value).partition(".")[2])
    return round(value * 1.15, max(decimals, 1)), rule


def shift_percentage_points(value: float) -> tuple[float, str]:
    """8.1 -> 11.1: soma fixa de +3.0 pontos percentuais."""
    decimals = len(_plain(value).partition(".")[2])
    return round(value + PP_SHIFT, max(decimals, 1)), f"deslocamento de +{PP_SHIFT} p.p."


def shift_year(year: int) -> tuple[int, str]:
    return year + 1, "ano deslocado em +1"


#: `period` ("FY2017", "Q3 2017") repete o ano em forma textual. A condicao A e
#: renderizada a partir de `period or year` (serialization.render_claim_text),
#: entao deslocar so o campo `year` deixaria o handoff de A IDENTICO ao limpo:
#: o erro de metadata nunca chegaria a condicao A, e o braco inteiro mediria
#: contencao artificial em vez do efeito do contrato. Corrigir o `period` junto
#: mantem o estado canonico internamente consistente e o mesmo erro visivel nas
#: 4 condicoes (passo 3 do protocolo). B/C/D nao carregam `period`, entao para
#: elas nada muda.
def shift_period(period: str | None, original_year: int, new_year: int) -> str | None:
    """Reescreve o ano dentro do rotulo de periodo: 'FY2017' -> 'FY2018'.

    Devolve None quando o periodo existe mas nao menciona o ano original: sem
    o ano ali, nao ha o que reescrever, e manter o rotulo antigo esconderia a
    perturbacao na condicao A. Com `period=None`, `render_claim_text` cai no
    proprio `year` -- ja corrompido -- e o erro volta a ser visivel.
    """
    if not period:
        return period
    if str(original_year) not in period:
        return None
    return period.replace(str(original_year), str(new_year))


def escalate_unit(unit: str) -> tuple[str, str]:
    if unit not in UNIT_ESCALATION:
        raise InjectionError(f"unidade sem regra de escalonamento: {unit}")
    return UNIT_ESCALATION[unit], "unidade escalonada uma ordem de grandeza"


# ==========================================================================
# Selecao deterministica do claim-alvo
# ==========================================================================
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _gold_numbers(gold_answer: str) -> set[float]:
    out: set[float] = set()
    for match in _NUM.findall(gold_answer or ""):
        try:
            out.add(float(match.replace(",", "")))
        except ValueError:
            continue
    return out


def _matches_gold(value: float, gold: set[float]) -> bool:
    return any(abs(value - g) <= max(abs(g), 1.0) * 1e-6 for g in gold)


def select_target_claim(
    claims: list[CanonicalClaim],
    error_type: ErrorType,
    gold_answer: str = "",
    eligible_ids: set[str] | None = None,
) -> tuple[CanonicalClaim, str]:
    """Escolhe o claim a corromper, sem qualquer aleatoriedade.

    Ordem de preferencia:
      1. claim com unidade compativel com o tipo de erro E valor presente na
         resposta gold (o erro atinge o caminho que responde a pergunta);
      2. claim com unidade compativel;
      3. primeiro claim na ordenacao por claim_id.

    `eligible_ids` restringe os candidatos aos claims verificados contra a
    evidencia (ver serialization.verify_extraction): corromper um valor que o
    Extrator ja fabricou tornaria o ground truth da perturbacao sem sentido.
    """
    if not claims:
        raise InjectionError("nenhum claim para corromper")

    ordered = sorted(claims, key=lambda c: c.claim_id)
    if eligible_ids is not None:
        ordered = [c for c in ordered if c.claim_id in eligible_ids]
        if not ordered:
            raise InjectionError("nenhum claim verificado contra a evidencia")

    preferred = PREFERRED_UNITS[error_type]
    eligible = [c for c in ordered if not preferred or c.unit in preferred]
    if not eligible:
        extra = (
            " -- o Extrator so extrai figuras brutas; erro percentual precisa de"
            " injection_stage=analyst"
            if error_type == "percentage"
            else ""
        )
        raise InjectionError(
            f"nenhum claim com unidade em {preferred} para erro '{error_type}'{extra}"
        )

    gold = _gold_numbers(gold_answer)
    for claim in eligible:
        if _matches_gold(claim.value, gold):
            return claim, "unidade compativel + valor presente na resposta gold"
    return eligible[0], "unidade compativel, primeiro na ordenacao por claim_id"


# ==========================================================================
# API principal
# ==========================================================================
def inject(
    claims: list[CanonicalClaim],
    error_type: ErrorType,
    stage: Stage = Stage.EXTRACTOR,
    gold_answer: str = "",
    metadata_subtype: Literal["year_shift", "unit_shift"] = "year_shift",
    eligible_ids: set[str] | None = None,
) -> tuple[list[CanonicalClaim], InjectionRecord]:
    """Corrompe exatamente um claim e devolve o ground truth da perturbacao."""
    target, selection_rule = select_target_claim(
        claims, error_type, gold_answer, eligible_ids
    )

    #: Campos corrompidos alem do campo primario. So o `year_shift` usa: o
    #: rotulo `period` precisa acompanhar o ano para que a perturbacao apareca
    #: tambem na prosa da condicao A (ver shift_period).
    extra: dict = {}

    if error_type == "value":
        field, subtype = "value", "digit_transposition"
        corrupted, rule = transpose_digits(target.value)
        original: float | int | str = target.value
    elif error_type == "percentage":
        field, subtype = "value", "pp_shift"
        corrupted, rule = shift_percentage_points(target.value)
        original = target.value
    elif error_type == "metadata" and metadata_subtype == "year_shift":
        field, subtype = "year", "year_shift"
        corrupted, rule = shift_year(target.year)
        original = target.year
        new_period = shift_period(target.period, target.year, corrupted)
        if new_period != target.period:
            extra["period"] = new_period
            rule += (
                f" (periodo reescrito: {target.period!r} -> {new_period!r})"
                if new_period
                else f" (periodo {target.period!r} descartado: nao menciona o ano)"
            )
    elif error_type == "metadata":
        field, subtype = "unit", "unit_shift"
        corrupted, rule = escalate_unit(target.unit)
        original = target.unit
    else:
        raise InjectionError(f"tipo de erro desconhecido: {error_type}")

    corrupted_claim = target.model_copy(update={field: corrupted, **extra})
    new_claims = [corrupted_claim if c.claim_id == target.claim_id else c for c in claims]

    record = InjectionRecord(
        error_type=error_type,
        error_subtype=subtype,
        rule=rule,
        selection_rule=selection_rule,
        stage_injected=stage,
        target_claim_id=target.claim_id,
        field=field,
        original_value=original,
        corrupted_value=corrupted,
        original_claim=target.model_dump(mode="json"),
        corrupted_claim=corrupted_claim.model_dump(mode="json"),
    )
    return new_claims, record

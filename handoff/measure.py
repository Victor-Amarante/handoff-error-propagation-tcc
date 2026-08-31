"""Instrumento de medida das metricas da secao 9 da proposta.

Principio de desenho, e a razao de este modulo existir: o instrumento precisa
ser IDENTICO nas 4 condicoes. Calcular containment a partir de `claims` e
`derived_from` seria impossivel em A (texto livre, zero claims), parcial em B
(claims sem lineage) e completo em C/D -- e D apareceria com "mais
amplificacao" so por emitir mais claims para contar. Isso mediria o formato do
contrato, nao o comportamento do erro.

Entao tudo aqui opera sobre `output_raw`, a unica coisa presente nas 4
condicoes, e sempre comparando uma celula injetada com a celula de CONTROLE da
MESMA condicao, pergunta e seed. A comparacao nunca cruza condicoes, entao o
fato de C/D produzirem JSON e A produzir prosa nao distorce nada: o ruido
estrutural aparece nos dois lados e se cancela na diferenca.

`derived_from` continua util, mas como sinal SECUNDARIO -- para validar o
instrumento textual onde ha lineage (`lineage_agreement`), o que e um resultado
por si so, e nao como metrica primaria.

Nada aqui chama a API: opera sobre os `.jsonl` ja gravados.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

from handoff.conditions import Condition, Stage

# ==========================================================================
# Extracao numerica uniforme
# ==========================================================================
_SCALE = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "million": 1e6, "mm": 1e6,
    "b": 1e9, "billion": 1e9,
}

#: O lookbehind evita capturar o "01" de identificadores como "A01"/"C08", que
#: aparecem no JSON de C/D e nao sao asserçoes numericas.
_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<num>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"\s*(?P<suffix>%|percent|million|billion|thousand|mm|[MBK])?(?![A-Za-z])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Number:
    value: float
    is_pct: bool
    scale: float = 1.0

    @property
    def scaled(self) -> float:
        return self.value * self.scale


#: `evidence` carrega texto LITERAL do documento. Os numeros dentro dele sao
#: citacao da fonte, nao afirmacoes do estagio -- conta-los faria a condicao D
#: parecer sistematicamente mais "amplificadora" so por carregar evidencia, que
#: e exatamente o confundidor que este modulo existe para evitar. A regra ("nao
#: contar fonte citada") vale para as 4 condicoes; so tem efeito onde ha
#: evidencia, porque so D a carrega.
_EVIDENCE_RE = re.compile(r'"evidence"\s*:\s*"(?:[^"\\]|\\.)*"')


def extract_numbers(text: str | None) -> list[Number]:
    """Asserçoes numericas de um texto, deduplicadas com tolerancia.

    A deduplicacao usa `same_number`, nao igualdade exata: `9.6` e `9.6%`
    aparecem no mesmo texto e sao a mesma afirmacao. Deduplicar importa
    tambem porque o JSON de C/D repete `page` e `year` em cada claim.
    """
    stripped = _EVIDENCE_RE.sub('"evidence":""', text or "")
    out: list[Number] = []
    for m in _NUM_RE.finditer(stripped):
        try:
            value = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        suffix = (m.group("suffix") or "").lower()
        number = Number(
            value=value,
            is_pct=suffix in ("%", "percent"),
            scale=_SCALE.get(suffix, 1.0),
        )
        if not any(same_number(number, seen) for seen in out):
            out.append(number)
    return out


def same_number(a: Number, b: Number, tol: float = 0.005) -> bool:
    """Iguais a menos de arredondamento (0,5% relativo, ou 1e-9 absoluto)."""
    for x, y in ((a.value, b.value), (a.scaled, b.scaled)):
        if abs(x - y) <= max(abs(x), abs(y), 1e-9) * tol:
            return True
    return False


def contains_number(haystack: Iterable[Number], needle: float) -> bool:
    probe = Number(needle, is_pct=False)
    return any(same_number(n, probe) for n in haystack)


def difference(a: Iterable[Number], b: Iterable[Number]) -> list[Number]:
    """Numeros de `a` sem equivalente em `b` (tolerante a arredondamento).

    Devolve lista, e nao set: a igualdade de `Number` e exata, e usar operacoes
    de conjunto aqui reintroduziria a dedup errada que `extract_numbers` evita.
    """
    b = list(b)
    return [x for x in a if not any(same_number(x, y) for y in b)]


def answer_matches_gold(text: str | None, gold: str) -> bool | None:
    """A resposta final bate com a do benchmark?

    None quando o gold nao tem numero para comparar -- melhor ficar sem dado
    do que fabricar um acerto ou um erro.
    """
    gold_nums = extract_numbers(gold)
    if not gold_nums:
        return None
    found = extract_numbers(text)
    return any(any(same_number(g, f) for f in found) for g in gold_nums)


# ==========================================================================
# Celula experimental carregada do log
# ==========================================================================
DOWNSTREAM = (Stage.ANALYST, Stage.WRITER)


@dataclass
class Cell:
    path: Path
    condition: Condition
    seed: int
    question_id: str
    error_type: str | None
    injection_stage: str | None
    metadata_subtype: str | None
    gold: dict
    injection: dict | None
    audit: dict | None
    final_answer: str
    stage_text: dict[str, str]
    stage_claims: dict[str, list[dict]]
    schema_flags: list[bool | None] = field(default_factory=list)
    contract_flags: list[bool | None] = field(default_factory=list)
    pipeline_tokens: int = 0
    pipeline_input_tokens: int = 0
    pipeline_output_tokens: int = 0
    auditor_tokens: int = 0
    pipeline_cost: float | None = None
    auditor_cost: float | None = None
    latency_ms: float = 0.0
    n_calls: int = 0

    @property
    def key(self) -> tuple:
        """Identidade para parear injetado com controle."""
        return (self.question_id, str(self.condition), self.seed, self.injection_stage)

    @property
    def is_control(self) -> bool:
        return self.error_type is None


def load_cell(path: str | Path) -> Cell:
    path = Path(path)
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not events:
        raise ValueError(f"log vazio: {path}")

    head = events[0]
    cell = Cell(
        path=path,
        condition=Condition(head["condition"]),
        seed=head["seed"],
        question_id=head["question_id"],
        error_type=head.get("error_type"),
        injection_stage=head.get("injection_stage") or "extractor",
        metadata_subtype=None,
        gold={},
        injection=None,
        audit=None,
        final_answer="",
        stage_text={},
        stage_claims={},
    )

    for event in events:
        etype = event["event_type"]
        if event.get("gold"):
            cell.gold = event["gold"]
        if event.get("injection"):
            cell.injection = event["injection"]
            cell.metadata_subtype = event["injection"].get("error_subtype")

        usage = event.get("usage")
        if usage:
            cell.n_calls += usage.get("n_calls", 1)
            cell.latency_ms += usage.get("latency_ms") or 0.0
            cost = usage.get("cost_usd")
            if etype == "audit":
                cell.auditor_tokens += usage.get("total_tokens", 0)
                if cost is not None:
                    cell.auditor_cost = (cell.auditor_cost or 0.0) + cost
            else:
                cell.pipeline_tokens += usage.get("total_tokens", 0)
                cell.pipeline_input_tokens += usage.get("input_tokens", 0)
                cell.pipeline_output_tokens += usage.get("output_tokens", 0)
                if cost is not None:
                    cell.pipeline_cost = (cell.pipeline_cost or 0.0) + cost

        if etype == "stage_output" and event.get("stage") in (s.value for s in DOWNSTREAM):
            stage = event["stage"]
            cell.stage_text[stage] = event.get("output_raw") or ""
            cell.stage_claims[stage] = event.get("claims") or []
            # Estagio COMPARTILHADO nao mede o contrato desta condicao: ele roda
            # uma vez, em forma canonica, e serve as quatro. No subestudo o
            # Analista e compartilhado, e contar o `schema_valid=True` dele
            # daria Schema Validity 1.0 para a condicao A -- que por definicao
            # nao tem contrato estrutural (secao 9: "aplicavel a B, C e D").
            if not (event.get("notes") or {}).get("shared_across_conditions"):
                cell.schema_flags.append(event.get("schema_valid"))
                checks = event.get("contract_checks") or {}
                cell.contract_flags.append(checks.get("contract_valid"))
        elif etype == "audit":
            cell.audit = event.get("audit_report")
        elif etype == "run_end":
            cell.final_answer = event.get("output_raw") or ""

    return cell


def load_cells(log_dir: str | Path) -> list[Cell]:
    return [load_cell(p) for p in sorted(Path(log_dir).glob("*.jsonl"))]


def pair_with_control(cells: Iterable[Cell]) -> list[tuple[Cell, Cell | None]]:
    """Pareia cada celula injetada com o controle da MESMA condicao/pergunta/seed."""
    controls = {c.key: c for c in cells if c.is_control}
    return [(c, controls.get(c.key)) for c in cells if not c.is_control]


# ==========================================================================
# Containment -- tudo depende do contrafactual limpo
# ==========================================================================
def _corrupted_value(cell: Cell) -> float | None:
    if not cell.injection:
        return None
    value = cell.injection.get("corrupted_value")
    return float(value) if isinstance(value, (int, float)) else None


def _original_value(cell: Cell) -> float | None:
    if not cell.injection:
        return None
    value = cell.injection.get("original_value")
    return float(value) if isinstance(value, (int, float)) else None


def stage_affected(injected: Cell, control: Cell, stage: str) -> bool:
    """O estagio mudou em relacao ao mesmo estagio da execucao limpa?

    Cobre tanto o erro preservado literalmente quanto o TRANSFORMADO: se o
    Analista dividiu o valor corrompido por outro numero, o valor original da
    injecao nao aparece em lugar nenhum, mas a saida difere da limpa.
    """
    got = extract_numbers(injected.stage_text.get(stage, ""))
    want = extract_numbers(control.stage_text.get(stage, ""))
    corrupted = _corrupted_value(injected)
    if corrupted is not None and contains_number(got, corrupted):
        return True
    return bool(difference(got, want))


def esr(injected: Cell, control: Cell) -> bool:
    """O erro permanece presente ou influencia a resposta final?

    Duas vias: o valor corrompido aparece literalmente, ou a resposta final
    difere da execucao limpa (influencia sem preservacao literal).
    """
    final = extract_numbers(injected.final_answer)
    corrupted = _corrupted_value(injected)
    if corrupted is not None and contains_number(final, corrupted):
        return True
    return bool(difference(final, extract_numbers(control.final_answer)))


def propagation_depth(injected: Cell, control: Cell) -> int:
    """Quantos estagios downstream o erro afetou."""
    return sum(
        1 for stage in DOWNSTREAM if stage_affected(injected, control, stage.value)
    )


def amplification(injected: Cell, control: Cell) -> int:
    """Novos numeros incorretos derivados do erro inicial.

    Novo  = nao aparece na execucao limpa do mesmo estagio.
    Incorreto = nao bate com a resposta do benchmark.
    O proprio valor corrompido nao conta: ele e o erro inicial, nao um derivado.
    """
    gold = extract_numbers(injected.gold.get("answer", ""))
    corrupted = _corrupted_value(injected)
    total = 0
    for stage in DOWNSTREAM:
        novos = difference(
            extract_numbers(injected.stage_text.get(stage.value, "")),
            extract_numbers(control.stage_text.get(stage.value, "")),
        )
        for n in novos:
            if corrupted is not None and same_number(n, Number(corrupted, False)):
                continue
            if any(same_number(n, g) for g in gold):
                continue
            total += 1
    return total


Fate = Literal[
    "preservado", "transformado", "amplificado", "corrigido", "contido", "sem_efeito"
]


def correction(injected: Cell, control: Cell) -> bool | None:
    """Correction Rate: o pipeline chegou na resposta certa apesar do erro?

    Devolve None -- nao mensuravel -- em dois casos, e isso importa mais do que
    parece:

    * `sem_efeito`: o claim corrompido estava fora do caminho da resposta, entao
      o pipeline nunca teve o que corrigir. Contar como sucesso premiaria a
      condicao que por acaso recebeu mais injecoes irrelevantes.
    * linha de base ja errada: se a execucao limpa erra a pergunta, a resposta
      final errada nao diz nada sobre a injecao.

    Sem esses dois cortes a metrica infla: no piloto, 2 de 16 celulas eram
    `sem_efeito` com resposta correta e seriam contadas como correcao.
    """
    if fate(injected, control) == "sem_efeito":
        return None
    if final_correct(control) is not True:
        return None
    return final_correct(injected) is True


def fate(injected: Cell, control: Cell) -> Fate:
    """Destino do erro -- passo 6 do protocolo (secao 8 da proposta).

    `sem_efeito` nao esta na lista da proposta e e deliberado: quando nada muda
    em nenhum estagio, o claim corrompido provavelmente estava fora do caminho
    da resposta. Somar esses casos a `contido` inflaria a contencao com casos
    em que o contrato nunca foi testado.
    """
    final = extract_numbers(injected.final_answer)
    corrupted = _corrupted_value(injected)
    original = _original_value(injected)
    depth = propagation_depth(injected, control)

    if corrupted is not None and contains_number(final, corrupted):
        return "preservado"
    if difference(final, extract_numbers(control.final_answer)):
        return "amplificado" if amplification(injected, control) > 0 else "transformado"
    if depth == 0:
        return "sem_efeito"
    restaurou = original is not None and any(
        contains_number(extract_numbers(injected.stage_text.get(s.value, "")), original)
        for s in DOWNSTREAM
    )
    return "corrigido" if restaurou else "contido"


# ==========================================================================
# Root-cause observability
# ==========================================================================
def fesa(cell: Cell) -> bool | None:
    """O auditor acertou o estagio de origem?"""
    if not (cell.audit and cell.injection):
        return None
    return cell.audit.get("first_error_stage") == cell.injection.get("stage_injected")


def rcca(cell: Cell) -> bool | None:
    """O auditor acertou o CLAIM de origem.

    Em A e B nao ha `claim_id` -- o auditor chegou a alucinar um no piloto --
    entao o matching e pela tupla (metrica, valor) do RootCauseReport contra o
    InjectionRecord. Em C/D o id e aceito como acerto adicional.
    """
    if not (cell.audit and cell.injection):
        return None

    reported_id = cell.audit.get("root_cause_claim_id")
    if reported_id and reported_id == cell.injection.get("target_claim_id"):
        return True

    reported_value = cell.audit.get("reported_value")
    if reported_value is None:
        return False
    corrupted = cell.injection.get("corrupted_value")
    if not isinstance(corrupted, (int, float)):
        return False
    if not same_number(Number(float(reported_value), False), Number(float(corrupted), False)):
        return False

    reported_metric = (cell.audit.get("reported_metric") or "").lower()
    target_metric = (cell.injection.get("original_claim") or {}).get("metric", "").lower()
    if not reported_metric or not target_metric:
        return True
    tokens = set(re.findall(r"[a-z]+", target_metric))
    return bool(tokens & set(re.findall(r"[a-z]+", reported_metric)))


# ==========================================================================
# Correctness, Schema Validity e custo
# ==========================================================================
def final_correct(cell: Cell) -> bool | None:
    return answer_matches_gold(cell.final_answer, cell.gold.get("answer", ""))


def schema_validity(cell: Cell) -> float | None:
    """Fracao de handoffs estruturalmente validos. None em A (sem contrato)."""
    flags = [f for f in cell.schema_flags if f is not None]
    return sum(flags) / len(flags) if flags else None


def contract_validity(cell: Cell) -> float | None:
    """Validade que nenhum JSON Schema pega (lineage pendente, id duplicado)."""
    flags = [f for f in cell.contract_flags if f is not None]
    return sum(flags) / len(flags) if flags else None


def lineage_agreement(cell: Cell) -> bool | None:
    """Sinal SECUNDARIO: em C/D, o lineage aponta para o claim injetado?

    Serve para validar o instrumento textual onde ha proveniencia -- nao e
    metrica primaria, porque nao existe em A e B.
    """
    if not cell.injection:
        return None
    target = cell.injection.get("target_claim_id")
    parents = {
        parent
        for claims in cell.stage_claims.values()
        for c in claims
        for parent in (c.get("derived_from") or [])
    }
    return target in parents if parents else None


# ==========================================================================
# Tabela para o notebook
# ==========================================================================
def to_records(cells: Iterable[Cell]) -> list[dict]:
    """Uma linha por celula injetada, pronta para `pd.DataFrame`.

    Celulas sem controle correspondente entram com as metricas de containment
    em None: sem contrafactual elas nao sao mensuraveis, e descartar em
    silencio esconderia buraco na matriz.
    """
    records = []
    for injected, control in pair_with_control(cells):
        row = {
            "question_id": injected.question_id,
            "condition": str(injected.condition),
            "seed": injected.seed,
            "error_type": injected.error_type,
            "error_subtype": injected.metadata_subtype,
            "injection_stage": injected.injection_stage,
            "target_claim_id": (injected.injection or {}).get("target_claim_id"),
            # Correctness
            "final_correct": final_correct(injected),
            "control_correct": final_correct(control) if control else None,
            # Root-cause observability
            "fesa": fesa(injected),
            "rcca": rcca(injected),
            "lineage_agreement": lineage_agreement(injected),
            # Schema
            "schema_validity": schema_validity(injected),
            "contract_validity": contract_validity(injected),
            # Custo
            "pipeline_tokens": injected.pipeline_tokens,
            "pipeline_input_tokens": injected.pipeline_input_tokens,
            "pipeline_output_tokens": injected.pipeline_output_tokens,
            "auditor_tokens": injected.auditor_tokens,
            "pipeline_cost_usd": injected.pipeline_cost,
            "auditor_cost_usd": injected.auditor_cost,
            "latency_ms": injected.latency_ms,
            "n_calls": injected.n_calls,
            "has_control": control is not None,
        }
        row.update(
            {
                "esr": esr(injected, control) if control else None,
                "propagation_depth": propagation_depth(injected, control) if control else None,
                "amplification": amplification(injected, control) if control else None,
                "fate": fate(injected, control) if control else None,
                # Correction Rate. None = nao mensuravel; ver `correction`.
                "corrected": correction(injected, control) if control else None,
            }
        )
        records.append(row)
    return records

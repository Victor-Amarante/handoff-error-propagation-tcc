"""Executa a matriz do experimento: perguntas x seeds x tipos de erro x condicoes.

    # ver o tamanho da matriz antes de gastar API
    uv run python scripts/run_experiment.py --dry-run

    # estudo principal (injecao no Extrator), com braco de controle
    uv run python scripts/run_experiment.py --error-types value,metadata --include-clean

    # subestudo de atribuicao de estagio (unico onde cabe erro percentual)
    uv run python scripts/run_experiment.py --injection-stage analyst \\
        --error-types percentage --questions 8

Retoma por padrao: celulas que ja chegaram ao `run_end` sao puladas, entao o
comando pode ser re-executado apos uma interrupcao sem refazer nem re-cobrar
o que ja rodou. `--force` refaz tudo.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handoff import config  # noqa: E402
from handoff.conditions import Condition, Stage  # noqa: E402
from handoff.injector import ERROR_TYPES, InjectionError  # noqa: E402
from handoff.logger import is_complete, log_path  # noqa: E402
from handoff.run import (  # noqa: E402
    PipelineError,
    _cache_path,
    analyze_state,
    extract_state,
    run_cell,
)


def load_subset(limit: int | None) -> list[dict]:
    if not config.SUBSET_PATH.exists():
        raise SystemExit(
            f"{config.SUBSET_PATH} nao existe. Rode scripts/build_subset.py primeiro."
        )
    rows = [
        json.loads(line)
        for line in config.SUBSET_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return rows[:limit] if limit else rows


def summarize_cost() -> None:
    """Tokens e custo acumulados a partir dos proprios logs."""
    pipeline = auditor = 0
    cost = 0.0
    has_cost = False
    for path in config.LOG_DIR.glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            usage = event.get("usage")
            if not usage:
                continue
            if event["event_type"] == "audit":
                auditor += usage.get("total_tokens", 0)
            else:
                pipeline += usage.get("total_tokens", 0)
            if usage.get("cost_usd") is not None:
                cost += usage["cost_usd"]
                has_cost = True
    print(f"\ntokens: pipeline={pipeline:,} auditor={auditor:,} total={pipeline + auditor:,}")
    print(
        f"custo: US$ {cost:.4f}"
        if has_cost
        else "custo: indisponivel (preencha config.PRICE_PER_MTOK)"
    )


#: Espera entre tentativas, em segundos. Duas tentativas extras cobrem o
#: rate limit tipico sem transformar uma quota esgotada em espera longa.
BACKOFF = (15, 60)


def _com_retomada_de_falha_transitoria(func, *args, **kwargs):
    """Refaz a celula quando a API falha por motivo transitorio.

    NAO e retry de schema: um handoff invalido continua sendo gravado como
    invalido (`stages._build_agent` mantem `retries=0`, e a conformidade checa
    isso). Aqui o alvo e rate limit / rede / 5xx numa execucao de horas, em que
    perder a celula significa uma lacuna na matriz ate a proxima retomada.
    """
    ultima: Exception | None = None
    for espera in (*BACKOFF, None):
        try:
            return func(*args, **kwargs)
        except (InjectionError, PipelineError, KeyboardInterrupt):
            raise
        except Exception as exc:  # noqa: BLE001
            ultima = exc
            if espera is None:
                raise
            print(f"    ...{type(exc).__name__}, nova tentativa em {espera}s")
            time.sleep(espera)
    raise ultima  # pragma: no cover -- inalcancavel, o laco sempre sai antes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=int, default=None, help="padrao: todas")
    parser.add_argument(
        "--seeds",
        default=str(config.SEEDS[0]),
        help=(
            "padrao: uma seed so. As replicas nao geram variancia neste modelo "
            f"(CONTEXT.md 11.4) e a unidade de analise e a pergunta; passe "
            f"--seeds {','.join(str(x) for x in config.SEEDS)} para rodar as "
            "replicas declaradas em config.SEEDS"
        ),
    )
    parser.add_argument("--conditions", default="A,B,C,D")
    parser.add_argument(
        "--error-types",
        default="value,metadata",
        help=f"lista separada por virgula, de {ERROR_TYPES}",
    )
    parser.add_argument(
        "--injection-stage",
        default="extractor",
        choices=["extractor", "analyst"],
        help="'analyst' e o subestudo de atribuicao de estagio (secao 7)",
    )
    parser.add_argument("--metadata-subtype", default="year_shift",
                        choices=["year_shift", "unit_shift"])
    parser.add_argument("--include-clean", action="store_true",
                        help="tambem roda o braco de controle, sem injecao")
    parser.add_argument("--force", action="store_true", help="refaz celulas completas")
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help=(
            "so roda perguntas com estado do Extrator ja em cache. Usado nas "
            "rodadas complementares: reextrair criaria um estado que a rodada "
            "principal nunca viu"
        ),
    )
    parser.add_argument(
        "--shard",
        default="0/1",
        help="k/n: roda so a k-esima de n fatias das celulas pendentes (paralelismo)",
    )
    parser.add_argument(
        "--stage-seed",
        type=int,
        default=None,
        help=(
            "seed de Analista, Redator e auditor, com o estado do Extrator da "
            "seed de --seeds. Usado no teste A/A do Qwen: no Ollama a mesma "
            "seed reproduz a execucao byte a byte, e a replica precisa de outro sorteio"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = load_subset(args.questions)
    seeds = [int(s) for s in args.seeds.split(",")]
    conditions = [Condition(c.strip()) for c in args.conditions.split(",")]
    stage = Stage(args.injection_stage)
    arms: list[str | None] = [t.strip() for t in args.error_types.split(",") if t.strip()]
    if args.include_clean:
        arms = [None, *arms]

    cells = [
        (row, seed, arm, cond)
        for row in rows
        for seed in seeds
        for arm in arms
        for cond in conditions
    ]
    def cell_path(cell):
        row, seed, arm, cond = cell
        return log_path(
            row["question_id"],
            arm,
            cond,
            args.stage_seed or seed,
            stage,
            variant=args.metadata_subtype if arm == "metadata" else None,
        )

    if args.cache_only:
        cells = [c for c in cells if _cache_path(c[0]["question_id"], c[1]).exists()]
    pending = [c for c in cells if args.force or not is_complete(cell_path(c))]
    k, n = (int(x) for x in args.shard.split("/"))
    pending = pending[k::n]

    print(
        f"modelo={config.MODEL_ID} injecao_em={stage}\n"
        f"{len(rows)} perguntas x {len(seeds)} seeds x {len(arms)} bracos "
        f"x {len(conditions)} condicoes = {len(cells)} celulas "
        f"({len(pending)} pendentes)"
    )
    if args.dry_run:
        calls_per_cell = 2 if stage is Stage.EXTRACTOR else 1
        shared = len(rows) * len(seeds) * (2 if stage is Stage.ANALYST else 1)
        print(
            f"chamadas estimadas: {len(pending) * (calls_per_cell + 1)} "
            f"(estagios+auditor) + ate {shared} compartilhadas nao cacheadas"
        )
        return 0

    started = time.perf_counter()
    done = skipped = failed = 0
    #: Perguntas cuja extracao ja falhou nesta execucao. Sem isso, uma pergunta
    #: sem claims extraiveis (comuns entre as de resposta qualitativa) seria
    #: reextraida em TODAS as suas celulas -- 12 chamadas cobradas por seed para
    #: falhar 12 vezes, porque a falha nao gera cache.
    extracao_falhou: set[tuple[str, int]] = set()

    for row, seed, arm, condition in pending:
        if (row["question_id"], seed) in extracao_falhou:
            skipped += 1
            continue
        try:
            extraction = extract_state(row, seed)
            analysis = (
                analyze_state(row, seed, extraction) if stage is Stage.ANALYST else None
            )
            _com_retomada_de_falha_transitoria(
                run_cell,
                row,
                args.stage_seed or seed,
                arm,  # type: ignore[arg-type]
                condition,
                extraction=extraction,
                analysis=analysis,
                injection_stage=stage,
                metadata_subtype=args.metadata_subtype,
            )
            done += 1
        except InjectionError as exc:
            print(f"  PULADA {row['question_id']} {arm} {condition}: {exc}")
            skipped += 1
        except PipelineError as exc:
            print(f"  FALHOU {row['question_id']} {arm} {condition}: {exc}")
            extracao_falhou.add((row["question_id"], seed))
            failed += 1
        except KeyboardInterrupt:
            print("\ninterrompido -- as celulas concluidas estao gravadas; "
                  "rode de novo para retomar de onde parou")
            break
        except Exception as exc:  # noqa: BLE001
            # Erro de API que sobreviveu ao retry: registrar e seguir. Numa
            # matriz de centenas de celulas, deixar a excecao subir jogaria
            # fora horas de execucao por uma falha transitoria de uma celula.
            # A celula fica sem `run_end`, entao a retomada a refaz sozinha.
            print(f"  ERRO   {row['question_id']} {arm} {condition}: "
                  f"{type(exc).__name__}: {str(exc)[:120]}")
            failed += 1
        if (done + skipped + failed) % 10 == 0:
            print(f"  ... {done + skipped + failed}/{len(pending)}")

    print(
        f"\n{done} celulas concluidas, {skipped} puladas, {failed} falhas "
        f"em {(time.perf_counter() - started) / 60:.1f} min"
    )
    summarize_cost()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

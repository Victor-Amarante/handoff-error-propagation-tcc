# Contratos de Handoff em Pipelines de IA Generativa

Infraestrutura experimental do TCC. O desenho completo esta em [CONTEXT.md](CONTEXT.md)
e na [proposta](docs/PropostaTCC.pdf); este README cobre so como rodar.

Pipeline fixo `Extrator -> Analista -> Redator`, com uma unica variavel
manipulada: o **contrato de handoff** entre os estagios (condicoes A/B/C/D).

## Setup

```bash
uv sync
cp .env.example .env      # preencha OPENAI_API_KEY
```

## Uso

```bash
# 1. conjunto de perguntas. O experimento roda o FinanceBench aberto INTEIRO
#    (150 perguntas, os 3 question_types); o jsonl bruto vem do repositorio
#    do benchmark e fica em data/financebench/
curl -sL -o data/financebench/financebench_open_source.jsonl \
  https://raw.githubusercontent.com/patronus-ai/financebench/main/data/financebench_open_source.jsonl
uv run python scripts/build_subset.py --n 150 --question-type all \
  --from-file data/financebench/financebench_open_source.jsonl

#    (variante enxuta, se algum dia for preciso reduzir: 25 perguntas de
#     resposta numerica limpa, com cota para o braco percentual)
#    uv run python scripts/build_subset.py --n 25 --ensure-percentage 15

# 2. preflight de conformidade: o codigo implementa a proposta? (sem API)
uv run python scripts/conformance.py

# 3. preflight de dados: valida o subset antes de gastar a matriz inteira
#    (so o Extrator, cacheado -- o custo e reaproveitado pelo experimento)
uv run python scripts/preflight.py --with-analyst

# 4. piloto: 2 perguntas x 4 condicoes, saida legivel
uv run python scripts/run_pilot.py --questions 2 --error-type none    # controle
uv run python scripts/run_pilot.py --questions 2 --error-type value

# 5. matriz completa (dry-run primeiro: mostra o tamanho antes de gastar API)
uv run python scripts/run_experiment.py --dry-run
uv run python scripts/run_experiment.py --error-types value,metadata --include-clean

# 6. subestudo de atribuicao de estagio (unico lugar onde cabe erro percentual)
uv run python scripts/run_experiment.py --injection-stage analyst \
    --error-types percentage --include-clean

# 7. testes deterministicos (nao gastam API)
uv run pytest

# 8. analise: agrega os .jsonl, calcula as metricas e gera a tabela do artigo
uv sync --group analysis        # pandas, matplotlib, ipykernel
#    abra analysis/metrics.ipynb
```

24 das 150 perguntas tem resposta qualitativa ("Yes, ...", "There are none"):
nelas a dimensao **Correctness** sai `None` de proposito (`answer_matches_gold`
nao inventa acerto sem numero no gold), enquanto containment, RCCA/FESA e custo
continuam mensuraveis, porque comparam com o **controle** e nao com o gold.

`run_experiment.py` retoma por padrao: celulas que chegaram ao `run_end` sao
puladas, entao da para interromper e re-executar sem refazer nem re-cobrar.

Cada celula experimental gera um `.jsonl` em `data/logs/`:
`run_<question_id>_<error_type>_<condicao>_seed<seed>.jsonl`. `clean` no lugar do
tipo de erro identifica o braco de controle; `_atanalyst` marca o subestudo de
atribuicao de estagio.

## Os dois estudos (secao 7 da proposta)

| | injecao em | roda por condicao | classes de erro | mede |
|---|---|---|---|---|
| principal | Extrator | Analista + Redator | value, metadata | propagacao, contencao, atribuicao |
| subestudo | Analista | Redator | percentage | atribuicao de estagio |

O Extrator so extrai figuras brutas, entao claims em `PCT` so existem na saida
do Analista -- e por isso que a classe `percentage` vive no subestudo. No
subestudo o Analista tambem roda compartilhado (forma canonica, projetado nas 4
condicoes), o que limita a Propagation Depth a 1: o proposito dele e FESA.

O controle nao e opcional: o pipeline erra algumas perguntas sozinho, e sem a linha
de base limpa nao da para separar erro injetado de erro nativo -- nem "erro contido"
de "erro propagado que coincidiu com a resposta certa".

## Como o experimento se mantem controlado

| Controle | Onde |
|---|---|
| O mesmo estado incorreto nas 4 condicoes | Extrator roda 1x por (pergunta x seed), cacheado em `data/cache/`; a injecao acontece sobre o estado canonico e so depois e projetada em A/B/C/D |
| Perturbacao deterministica | [`handoff/injector.py`](handoff/injector.py) -- sem RNG; regra e claim-alvo registrados no ground truth |
| Extrator nao computa metricas | `verify_extraction` confere que o valor aparece literal na evidencia; so claims verificados podem ser alvo de injecao |
| C nao dereferencia a fonte | Nenhum estagio downstream recebe o documento e nenhum agente tem tools; `check_evidence_leak` confere e grava o resultado no log |
| A nao ganha uma variavel extra | A serializacao de A e um template fixo, nao uma parafrase de LLM |
| Prompts constantes | [`handoff/prompts.py`](handoff/prompts.py) -- so a instrucao de FORMATO muda entre condicoes |
| Auditor nao contamina o pipeline | Roda depois, como instrumento; custo isolado em `event_type="audit"` |

## Estrutura

```
handoff/
  config.py          modelo, seeds, paths, tabela de precos
  conditions.py      Condition (A/B/C/D), Stage, capabilities
  schemas/
    claims.py        CanonicalClaim (interno) + ClaimB/C/D (contratos) + saidas por estagio
    audit.py         RootCauseReport -- unico schema constante entre condicoes
    events.py        LogEvent, Usage, InjectionRecord, GoldRecord
  prompts.py         prompts citaveis na metodologia
  serialization.py   projecao canonical -> contrato, template de A, checagens de contrato
  stages.py          Extrator / Analista / Redator sobre Agno
  injector.py        as 3 classes de erro da secao 7
  auditor.py         probe de root-cause (RCCA/FESA)
  logger.py          JSONL, um arquivo por celula
  run.py             uma celula experimental completa
  measure.py         instrumento de medida, uniforme nas 4 condicoes
scripts/             build_subset, conformance, preflight, run_pilot, run_experiment
data/                financebench/, cache/, logs/
analysis/            metrics.ipynb -- agrega os logs, calcula IC e gera a tabela do artigo
tests/               injector, serializacao, logging, guarda de extracao, fiacao
```

## O que o log sustenta

Nada e calculado durante a execucao: o `.jsonl` guarda o estado cru e o ground
truth, e as metricas saem na analise.

| Metrica | Campos |
|---|---|
| Final Factual Accuracy | `run_end.output_raw` + `gold.answer` |
| acuracia por tipo de erro | `error_type` |
| Correction Rate | `injection.original_value` vs resposta final |
| Error Survival Rate | `injection.corrupted_value` vs `output_raw` do writer |
| Propagation Depth | `output_raw` por `stage_output`, contra o mesmo estagio no controle |
| Error Amplification | idem: numeros novos, ausentes no controle e diferentes do gold |
| destino do erro | `fate`: preservado/transformado/amplificado/corrigido/contido |
| RCCA / FESA | `audit_report` x `injection` |
| Schema Validity | `schema_valid`, `schema_errors`, `contract_checks` |
| Custo operacional | `usage` por evento (tokens, latencia, custo, nº de chamadas) |

Containment sai de `output_raw` nas 4 condicoes, nunca de `claims`/`derived_from`:
A nao tem claims e B nao tem lineage, entao usa-los faria D parecer mais
amplificadora so por emitir mais campos -- mediria o formato do contrato, nao o
comportamento do erro. `derived_from` vira sinal secundario (`lineage_agreement`).

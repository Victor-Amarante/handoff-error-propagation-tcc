# CONTEXT.md — Contratos de Handoff em Pipelines de IA Generativa

> Este documento é a fonte da verdade do desenho experimental do TCC. Qualquer decisão de implementação deve ser consistente com o que está aqui. Se algo mudar durante o desenvolvimento, atualize este arquivo.

## 1. Tema e pergunta central

**Tema:** Investigar experimentalmente como o contrato de comunicação entre componentes probabilísticos determina o ciclo de vida de um erro já introduzido no sistema: se ele é preservado, transformado, amplificado, corrigido ou atribuível à sua origem.

**Pergunta central:** Dado que um componente probabilístico introduziu um erro, como o design da interface de comunicação entre componentes influencia sua propagação, contenção, correção e atribuição de origem em um pipeline de IA generativa?

O foco **não** é abrir a caixa-preta do modelo. É observabilidade e atribuição de falhas no nível do sistema/harness.

## 2. Pipeline lógico (fixo)

```
Documento-fonte → Extrator → Analista → Redator → Resposta final
```

Modelo, prompts, documentos, perguntas e lógica das etapas devem permanecer **constantes** entre condições. A única variável experimental é o **contrato de handoff** entre os estágios.

## 3. As 4 condições experimentais

| Condição | Estrutura | Provenance/lineage | Evidência |
|---|---|---|---|
| A — Free text | não | não | não |
| B — Typed | sim | não | não |
| C — Typed + lineage | sim | sim | não |
| D — Typed + lineage + evidence | sim | sim | sim |

**Controle de validade interna (crítico):** na condição C, `source_id` e `page` são apenas metadados — o componente downstream **não pode** dereferenciar a fonte nem recuperar o conteúdo original. Somente D recebe o trecho de evidência.

### Exemplo do mesmo handoff nas 4 condições

**A — Free text:**
```
"According to the report, revenue in 2026 was $14.2M."
```

**B — Typed:**
```json
{
  "metric": "revenue",
  "value": 14.2,
  "unit": "USD_M",
  "year": 2026
}
```

**C — Typed + lineage:**
```json
{
  "claim_id": "C17",
  "metric": "revenue",
  "value": 14.2,
  "unit": "USD_M",
  "year": 2026,
  "source_id": "annual_report_2026.pdf",
  "page": 14,
  "generated_by": "extractor",
  "derived_from": ["C08"]
}
```

**D — Typed + lineage + evidence:**
```json
{
  "claim_id": "C17",
  "metric": "revenue",
  "value": 14.2,
  "unit": "USD_M",
  "year": 2026,
  "source_id": "annual_report_2026.pdf",
  "page": 14,
  "generated_by": "extractor",
  "derived_from": ["C08"],
  "evidence": "Revenue for fiscal 2026 was $12.4 million..."
}
```

**Comparações isoladas:**
- A × B → isola o efeito da estrutura
- B × C → isola o efeito de lineage/provenance
- C × D → isola o efeito adicional do grounding documental (evidência)

## 4. Conceito-chave: "claim"

Um **claim** é a menor unidade atômica de afirmação factual que trafega entre os componentes (ex: "receita em 2026 = $14.2M"). Cada claim tem:
- `claim_id` único
- `derived_from`: lista de claim_ids que o originaram (forma a cadeia de proveniência)

Exemplo de cadeia:
```
C31 (Writer) → derived_from → C17 (Analyst) → derived_from → C08 (Extractor)
```

A avaliação de causa raiz compara a origem **reconstruída pelo sistema** com o **ground truth da injeção** — não basta existir uma cadeia de provenance, ela precisa apontar para o claim correto.

## 5. Tipos de erro controlados (3 classes)

| Tipo de erro | Exemplo correto | Perturbação controlada |
|---|---|---|
| Value error | $12.4M | $14.2M |
| Percentage error | 8.1% | 11.1% |
| Metadata error | 2025 / USD M | 2026 / USD B |

- Perturbações são **determinísticas** e registradas como ground truth.
- Estudo principal de propagação: erro injetado **cedo** no pipeline (após saída correta do Extrator, antes do handoff).
- Subconjunto menor: falhas injetadas em estágios diferentes, para avaliar atribuição do estágio de origem sem trivializar a tarefa.

## 6. Protocolo experimental mínimo

1. Benchmark candidato: **FinanceBench** (perguntas financeiras + respostas + evidências verificáveis). Usar um **subconjunto** (~15-25 perguntas) — não o benchmark inteiro.
2. Executar o estágio alvo até obter estado correto → aplicar **Error Injector** determinístico → gerar uma das 3 classes de erro.
3. Serializar exatamente o mesmo estado incorreto nas 4 condições (A/B/C/D). A diferença deve estar **apenas** no contrato de handoff.
4. Em C: bloquear qualquer recuperação da fonte via source_id/page. Em D: incluir o trecho de evidência correto.
5. Executar estágios downstream com mesma config de modelo/prompts equivalentes, registrando estados intermediários e dependências entre claims.
6. Classificar destino de cada erro: **preservado / transformado / amplificado / corrigido / contido antes da saída final**.
7. Repetir com execuções/seeds suficientes para análise estatística simples (intervalos de confiança).

## 7. Métricas (4 dimensões)

| Dimensão | Pergunta | Métricas |
|---|---|---|
| Correctness | O resultado final está correto? | Final Factual Accuracy; acurácia por tipo de erro; Correction Rate |
| Containment | Até onde o erro contamina o pipeline? | Error Survival Rate (ESR); Propagation Depth; Error Amplification |
| Root-Cause Observability | Conseguimos atribuir a origem corretamente? | Root Cause Claim Accuracy (RCCA); First Error Stage Accuracy (FESA) |
| Operational Cost | Quanto custa cada condição? | Tokens; latência; nº de chamadas; custo monetário |

Também medir **Schema Validity** (aplicável a B/C/D) — validade estrutural do handoff, sem confundir com correção semântica.

### Definições rápidas
- **ESR**: % de erros injetados que permanecem/influenciam a resposta final
- **Propagation Depth**: nº de estágios downstream afetados antes de correção/contenção
- **Error Amplification**: quantidade de novos claims incorretos derivados do erro inicial
- **RCCA**: % de falhas finais para as quais o sistema identifica corretamente o claim de origem
- **FESA**: % de casos em que o sistema identifica corretamente o estágio onde surgiu o primeiro erro

RCCA e FESA podem ser **automatizados por comparação**: como o erro é injetado por nós, sabemos o ground truth, então basta comparar com o que o pipeline aponta como origem.

## 8. Perguntas de pesquisa (RQs)

- **RQ1**: Efeito da estruturação do handoff sobre propagação e correção. Comparação: A × B.
- **RQ2**: Efeito da preservação de lineage/provenance sobre containment e atribuição de causa raiz. Comparação: B × C.
- **RQ3**: Efeito adicional de disponibilizar evidência original ao downstream. Comparação: C × D.

Custo operacional é reportado transversalmente às três RQs.

## 9. Fora de escopo (explicitamente)

- Fine-tuning, distillation, treinamento de novos modelos
- Comparação ampla entre muitos LLMs/SLMs
- RAG, retries, reflection, majority voting, múltiplos verifiers
- Topologias complexas (DAGs, ciclos, dezenas de agentes)
- Múltiplos domínios de aplicação / taxonomias extensas de erro

Extensão opcional (só depois do experimento principal): repetir subconjunto com um SLM para checar se efeitos se mantêm.

## 10. Critério de sucesso

Não é preciso provar que D é sempre superior. O valor está em decompor causalmente o efeito de cada mecanismo (estrutura, lineage, evidência). Resultados negativos são úteis (ex: B tem alta schema validity sem melhorar correctness; C melhora RCCA sem reduzir ESR; D contém mais erros mas com mais overhead).

---

## 11. Decisões de implementação (stack)

**Objetivo:** implementação rápida e enxuta — o foco do trabalho é a análise das métricas, não a engenharia do pipeline.

- **Linguagem:** Python
- **Orquestração:** Agno (preferência sobre LangGraph — pipeline é linear e fixo, sem ciclos/branches complexos, então Agno exige menos boilerplate e dá controle mais fino sobre o ponto exato de injeção de erro e captura do payload de handoff)
- **Structured outputs:** Pydantic (define os schemas de B/C/D; resolve Schema Validity automaticamente via validação, sem parser manual)
- **Modelo:** API da OpenAI (modelo específico a definir — ex: gpt-4o, gpt-4o-mini — deve permanecer **constante entre as 4 condições**, conforme exigido pelo desenho experimental)
- **Structured outputs:** usar o suporte nativo da OpenAI a Structured Outputs (`response_format` com JSON Schema, ou `.parse()` do SDK com Pydantic direto) para as condições B/C/D — reforça Schema Validity sem depender de prompting solto
- **Prompt caching:** ~~a OpenAI aplica caching automático em prompts longos repetidos, o que já cobre o reuso do documento-fonte~~ — **medido e falso neste desenho.** `cached_tokens = 0` em todas as células do piloto. O caching automático exige prefixo longo e idêntico entre chamadas; aqui o documento-fonte só aparece no prompt do Extrator (que já é cacheado em disco por nós, então não se repete), e os prompts downstream são curtos e variam por condição. Não contar com isso na análise de custo
- **Armazenamento:** **JSONL** (um JSON por linha), não CSV puro e não MySQL
  - Motivo: dados são naturalmente aninhados (`derived_from` é lista; payloads de C/D têm campos estruturados). CSV forçaria achatamento/serialização manual. JSONL carrega direto em Pandas (`pd.read_json(lines=True)`) e não exige setup de banco.
  - Um arquivo `.jsonl` por execução completa, ex: `run_condicaoB_seed3.jsonl`
  - Cada linha = um evento/estado que saiu de um estágio do pipeline, contendo: timestamp, condição, seed, claim_id, payload do estágio, erro ground truth (quando aplicável)
- **Análise:** Pandas + Jupyter Notebook — concatenar todos os `.jsonl`, calcular ESR, Propagation Depth, RCCA, FESA, Schema Validity, custo operacional

### Estrutura de pastas (implementada)

```
handoff-error-propagation-tcc/
├── CONTEXT.md · README.md · pyproject.toml · .env.example
├── docs/PropostaTCC.pdf
├── handoff/                 # pacote único (evita hack de sys.path entre pastas)
│   ├── config.py            # modelo, seeds, paths, tabela de preços
│   ├── conditions.py        # Condition (A/B/C/D), Stage, capabilities
│   ├── schemas/
│   │   ├── claims.py        # CanonicalClaim (interno) + ClaimB/C/D (contratos)
│   │   ├── audit.py         # RootCauseReport
│   │   └── events.py        # LogEvent, Usage, InjectionRecord, GoldRecord
│   ├── prompts.py           # prompts citáveis na metodologia
│   ├── serialization.py     # projeção canonical → contrato + checagens
│   ├── stages.py            # Extrator/Analista/Redator sobre Agno
│   ├── injector.py          # as 3 classes de erro da seção 5
│   ├── auditor.py           # probe de root-cause (RCCA/FESA)
│   ├── logger.py            # JSONL append-only
│   └── run.py               # uma célula experimental completa
├── scripts/                 # build_subset.py, run_pilot.py
├── data/                    # financebench/, cache/, logs/
├── analysis/                # metrics.ipynb (fase seguinte)
└── tests/                   # injector, serialização, logging
```

### Decisões congeladas na fase de engenharia (29 ago 2026)

1. **Extrator roda 1× por (pergunta × seed)**, em schema canônico rico, e o estado é
   compartilhado pelas 4 condições. É o passo 3 do protocolo levado a sério: o erro
   injetado é *literalmente* o mesmo em A/B/C/D. **Consequência para a metodologia:**
   Schema Validity e custo variável são medidos em Analista + Redator; o Extrator entra
   como custo fixo comum às condições.
2. **Atribuição de causa raiz por auditor separado**, rodado após o pipeline. Recebe
   somente o que o contrato daquela condição preservou; o schema de saída
   (`RootCauseReport`) é constante nas 4 condições — o que varia é a *entrada*. Mantém
   Extrator/Analista/Redator idênticos entre condições. Custo isolado no log
   (`event_type="audit"`), fora do custo operacional do pipeline.
3. **Documento-fonte = evidence snippets do FinanceBench**, sem parsing de PDF. Contexto
   curto, evidência de D já alinhada com o ground truth, e sem erros de extração não
   controlados competindo com o erro injetado.
4. **Modelo:** `gpt-5.6-luna` via Agno/`OpenAIChat` (Chat Completions expõe `seed`; a
   Responses API não expõe). Constante nas 4 condições. Preços: input US$ 0,20 / cached
   US$ 0,02 / output US$ 1,20 por 1M tokens.
   **O modelo rejeita `temperature=0`** ("only the default (1) value is supported"), então
   o parâmetro é omitido da requisição (`HANDOFF_TEMPERATURE=`) e o pipeline roda em
   temperatura 1. A injeção de erro continua determinística: o ground truth não depende
   do modelo.
   **Réplicas por seed não geram variância neste desenho — medido.** Apesar da temperatura
   1, seed 1 e seed 2 produziram respostas finais numericamente idênticas em 8/8 células
   limpas e 8/8 injetadas (2 perguntas × 4 condições). O modelo converge na aritmética
   mesmo variando a prosa. **Não tratar seeds como observações independentes**: com
   respostas idênticas, o intervalo de confiança sairia artificialmente estreito por
   triplicar o n com dado duplicado. A unidade de análise deve ser a **pergunta**
   (n = 25). Antes da rodada principal, medir a taxa de discordância entre duas seeds no
   conjunto inteiro; se continuar ~0, rodar uma seed só. Refazer essa medição sempre que
   modelo ou `reasoning_effort` mudarem — com `gpt-5.4-mini` as seeds variavam
   (3,1% / 4,4% / 3,1% na mesma célula).
   **`reasoning_effort = "medium"`**, constante nas 4 condições. É um confundidor de
   primeira ordem, não um detalhe de performance: mais esforço aumenta a chance de o
   próprio estágio detectar a inconsistência do erro injetado, o que comprimiria as
   diferenças entre A/B/C/D — no limite, um modelo que sempre corrige o erro daria ESR≈0
   em todas as condições e o experimento não mediria nada. Também entra direto no custo,
   porque reasoning tokens são cobrados como output. Medido numa chamada real do Extrator:
   86 reasoning tokens em `low`, 208 em `medium`, 311 em `high` (as três produziram os
   mesmos 6 claims válidos). O valor usado fica gravado em `model_params` de todo evento.
5. **Serialização de A é um template determinístico**, não uma paráfrase de LLM — caso
   contrário a condição A carregaria uma variável extra além da ausência de estrutura.
6. **A perturbação precisa ser detectável na saída final.** A regra literal da seção 5
   ("transpor os dois últimos dígitos") reproduz `12.4 → 14.2` (+15%), mas em `39403`
   produz `39430` (+0,07%) — um erro menor que o arredondamento do estágio seguinte, que
   faria ESR e Correction Rate medirem ruído. A regra implementada transpõe **o par de
   dígitos adjacentes mais à direita que altera o valor em ≥10%**: reproduz o exemplo
   canônico da proposta e garante perturbação material em qualquer ordem de grandeza
   (`39403 → 34903`). Constante em `injector.MIN_RELATIVE_CHANGE`.
7. **Todo experimento tem braço de controle limpo** (`error_type=None`, arquivos
   `run_*_clean_*.jsonl`): mesmo estado extraído, sem injeção. O pipeline erra algumas
   perguntas por conta própria — no piloto, a `financebench_id_02981` dá 11.5% contra
   gold 10.3% *sem injeção nenhuma*. Sem a linha de base limpa não se distingue erro
   injetado de erro nativo, nem "erro contido" de "erro propagado que coincidiu com a
   resposta certa". O controle também mede a taxa de falso-positivo do auditor.
8. **O Extrator não pode computar métricas — e isso é garantido por checagem, não por
   prompt.** No piloto ele emitiu `operating income margin = 18.4 PCT` anexando como
   evidência `"Operatingincome 1,306"`: um número derivado (e errado) com a evidência de
   um número bruto. Dois danos: o Analista vira pass-through, o que comprime
   artificialmente Propagation Depth e Error Amplification; e a injeção pode cair num
   claim que ninguém usa, produzindo falsa contenção. Além do prompt, `verify_extraction`
   confere deterministicamente que o valor do claim aparece literalmente na sua evidência,
   e só claims verificados podem ser alvo de injeção — corromper um valor já fabricado
   tornaria o ground truth da perturbação sem sentido. O resultado por claim vai para o log.
   Pelo mesmo motivo o Extrator **não converte escala**: reporta a figura na unidade em que
   a demonstração a publica (`(In thousands)` → `USD_K`). Reescalar é aritmética, e era de
   onde vinham os erros de unidade — numa pergunta ele leu `24,576` de uma demonstração
   "em milhões" e emitiu `24.576 USD_M`, errado por um fator de 1000. Com a regra, a taxa
   de claims verificados subiu de 89% para 100% e as 20 perguntas do subset ficaram
   utilizáveis (eram 18).
9. **A classe de erro `percentage` vive no subestudo de estágio.** Como o Extrator só
   extrai figuras brutas (decisão 8), não existem claims em `PCT` na saída dele — a
   perturbação `8.1% → 11.1%` só faz sentido sobre um claim derivado. Então `percentage`
   é injetada no **Analista**, que é exatamente o subestudo de atribuição de estágio que
   a seção 5 já pedia. Nesse braço o Analista também roda compartilhado (forma canônica,
   projetado nas 4 condições) e só o Redator roda por condição — logo a Propagation Depth
   máxima é 1, e o propósito do braço é FESA, não profundidade.
10. **O instrumento de medida é idêntico nas 4 condições** (`handoff/measure.py`). Calcular
    containment a partir de `claims`/`derived_from` seria impossível em A (texto livre,
    zero claims), parcial em B (claims sem lineage) e completo em C/D — e D apareceria
    com "mais amplificação" só por emitir mais claims para contar, medindo o formato do
    contrato em vez do comportamento do erro. Então tudo opera sobre `output_raw`, a única
    coisa presente nas quatro, sempre comparando a célula injetada com o **controle da
    mesma condição, pergunta e seed**; a comparação nunca cruza condições. Duas regras
    saíram de artefatos observados: números dentro do campo `evidence` não contam (são
    citação da fonte, e contá-los inflava a amplificação de D em ~3×), e a deduplicação é
    tolerante (`9.6` e `9.6%` são a mesma afirmação). `derived_from` vira sinal
    **secundário** (`lineage_agreement`), para validar o instrumento textual onde há
    proveniência — não métrica primária.
11. **Schema Validity com structured outputs nativo é ~1.0 por construção.** Para que a
   métrica não seja trivial, o log também grava `contract_checks`: violações que nenhum
   JSON Schema pega (`derived_from` apontando para id inexistente, `claim_id` duplicado,
   `generated_by` incoerente, evidência não-literal em D). O flag `HANDOFF_STRICT_OUTPUT=0`
   permite rodar um braço em JSON mode sem gramática restrita, se quisermos medir
   validade estrutural bruta.

12. **A perturbação precisa chegar às quatro condições, não só ao estado canônico.**
   O `year_shift` corrompia apenas o campo `year`, mas a prosa da condição A é renderizada
   a partir de `period or year` (`render_claim_text`) e **todos os 82 claims do subset têm
   `period` preenchido** (`FY2017`, ...). O handoff de A saía literalmente idêntico ao do
   braço de controle: o erro de metadata nunca chegava à condição A, que teria medido
   ESR = 0 e `fate="sem_efeito"` em 100% das células por construção — quebrando o passo 3
   do protocolo e invalidando a comparação RQ1 (A×B) nesse braço. O injetor agora reescreve
   `period` junto com `year` (`FY2017 → FY2018`), e descarta o rótulo (`period=None`) quando
   ele não menciona o ano original, caso em que a prosa cai no `year` já corrompido. B/C/D
   não carregam `period`, então nada muda nelas; o ground truth continua ancorado no campo
   primário (`field="year"`), com a reescrita registrada em `rule` e visível em
   `corrupted_claim`. A invariante virou checagem permanente: `conformance.py` §8.3 testa as
   **quatro** combinações de classe/subtipo contra o payload de A, e não só a classe `value`
   — que era o único caso que a checagem antiga exercia, e por isso o defeito passou.


13. **Correção e contenção terminam iguais no log; o que as separa é a resposta ter voltado
   à da execução limpa.** A regra antiga chamava de correção qualquer célula em que o *valor
   original reaparecesse* em algum estágio downstream. Na classe `metadata`/`year_shift` isso
   é falso-positivo sistemático: o ano original aparece na própria pergunta (que o Redator
   reafirma), nos claims irmãos não corrompidos e no `answer_claim` — observado numa célula
   real (`financebench_id_02608`, condição B) em que o Redator **recusou responder** e ainda
   assim era classificada como correção. `fate` agora exige também que a resposta final não
   tenha *perdido* a figura que a execução limpa entregava (`difference` é assimétrico, então
   a checagem é feita nos dois sentidos). Recusa e omissão passam a cair em `contido`, que é
   o que são. Só afeta a classificação de `fate` e o `corrected`; ESR, Propagation Depth e
   Amplification não usavam essa regra.


## 12. Cronograma

| Período | Entrega |
|---|---|
| 25 ago – 7 set | Fechar RQs, benchmark, modelo, schemas A/B/C/D e ground truth das perturbações |
| 8 – 27 set | Implementar pipeline, Error Injector, logging/lineage e executar piloto pequeno |
| 28 set – 31 out | Executar experimento principal A/B/C/D e subconjunto de root-cause attribution |
| 1 – 15 nov | Análise estatística, gráficos, revisão dos casos de erro e trade-offs de custo |
| 16 – 29 nov | Redação final, revisão com orientador, preparação da apresentação |
| Início de dez | Apresentação/defesa |

## 13. Bibliografia prioritária

- [4] Singh, P.; Pawar, B. (2026). *The Hallucination Snowball: Modeling Error Propagation as State Transitions in Multi-Agent LLM Pipelines.* arXiv:2608.14588 — referência mais próxima do problema
- [5] Barrak, A. (2025). *Traceability and Accountability in Role-Specialized Multi-Agent LLM Pipelines.* arXiv:2510.07614
- [6] Geng, S. et al. (2025). *Generating Structured Outputs from Language Models: Benchmark and Studies.* arXiv:2501.10868
- [7] Ray, J. (2026). *The Constraint Tax: Measuring Validity-Correctness Tradeoffs in Structured Outputs for Small Language Models.* arXiv:2605.26128
- [9] Zhong, H.; Zhu, S. (2026). *AI Harness Engineering: A Runtime Substrate for Foundation-Model Software Agents.* arXiv:2605.13357
- [10] Chen, M. et al. (2026). *From Failed Trajectories to Reliable LLM Agents: Diagnosing and Repairing Harness Flaws.* arXiv:2606.06324
- [11] Islam, P. et al. (2023). *FinanceBench: A New Benchmark for Financial Question Answering.* arXiv:2311.11944 — dataset candidato

---

## Próximo passo imediato

Congelar o schema exato de B/C/D, selecionar subconjunto inicial do FinanceBench, e implementar um piloto de ponta a ponta antes de ampliar o número de execuções.
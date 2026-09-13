# Proposta de TCC
## Contratos de Handoff, Propagação e Atribuição de Erros em Pipelines de IA Generativa

*Versão revisada após validação do orientador — agosto de 2026*
*Notas de implementação alinhadas ao pipeline experimental — setembro de 2026*

---

## 1. Tema em uma frase

Investigar experimentalmente como o contrato de comunicação entre componentes probabilísticos determina o ciclo de vida de um erro já introduzido no sistema: se ele é preservado, transformado, amplificado, corrigido ou atribuível à sua origem.

## 2. Pergunta central

Dado que um componente probabilístico introduziu um erro, como o design da interface de comunicação entre componentes influencia sua propagação, contenção, correção e atribuição de origem em um pipeline de IA generativa?

## 3. Motivação

Sistemas modernos com LLMs raramente consistem em uma única chamada ao modelo. Eles combinam extração, raciocínio, síntese, ferramentas, memória e outros componentes, fazendo com que a saída de uma etapa se torne entrada ou premissa para a etapa seguinte. Nesse cenário, um erro local pode sobreviver, gerar novos erros derivados e tornar-se progressivamente mais difícil de diagnosticar.

O foco deste trabalho não é explicar internamente a "caixa-preta" do modelo. O objetivo é investigar observabilidade e atribuição de falhas no nível do sistema: quando uma saída final está errada, conseguir determinar em que estágio a falha começou, qual claim a originou e como ela se propagou. Dois sistemas podem ter a mesma accuracy final e, ainda assim, serem arquiteturalmente muito diferentes se apenas um permitir reconstruir a origem de uma falha.

The Hallucination Snowball [4] demonstra propagação de erros em pipelines sequenciais e aponta structured handoffs, passagem de citações e provenance-preserving state como direções futuras. Trabalhos sobre structured outputs também indicam que validade estrutural não implica correção semântica [6,7]. A proposta explora essa lacuna por meio de ablações controladas do contrato de handoff.

## 4. Hipóteses de trabalho

- **H1** — Texto livre tende a facilitar a transformação do erro e a perda de informações sobre sua origem.
- **H2** — Estrutura tipada melhora consistência estrutural e parseabilidade, mas não necessariamente reduz erros semânticos.
- **H3** — Lineage/provenance, sem reexpor a evidência correta, melhora a atribuição de causa raiz e a observabilidade do erro.
- **H4** — Disponibilizar a evidência original ao downstream produz um efeito adicional de re-grounding, aumentando a chance de correção e contenção do erro.

## 5. Escopo experimental

Pipeline lógico fixo: **Documento-fonte → Extrator → Analista → Redator → Resposta final**.

A variável experimental principal será o contrato usado nos handoffs. Modelo, prompts, documentos, perguntas e lógica das etapas devem permanecer constantes sempre que possível. A comparação será feita em quatro condições:

| Condição | Estrutura | Provenance / lineage | Evidência |
|---|---|---|---|
| A — Free text | não | não | não |
| B — Typed | sim | não | não |
| C — Typed + lineage | sim | sim | não |
| D — Typed + lineage + evidence | sim | sim | sim |

**Controle de validade interna:** na condição C, `source_id` e `page` são apenas metadados. O componente downstream não poderá dereferenciar a fonte, recuperar o documento ou obter novamente o conteúdo original. Somente D recebe o trecho de evidência.

**Nota de implementação:** por "Documento-fonte" o experimento usa o trecho de evidência (*evidence snippet*) já recortado pelo FinanceBench, não o PDF completo — não há etapa de parsing de PDF no pipeline. Isso evita que erros de extração de documento não controlados competam com o erro injetado, mas restringe o "Documento-fonte" do diagrama da seção 5 a um contexto curto por pergunta. O conjunto de perguntas usado é o FinanceBench aberto **inteiro** (150 perguntas, os três `question_type`), e não um subconjunto de 15–25 perguntas como cogitado inicialmente.

## 6. O mesmo handoff em A, B, C e D

**A — Free text**

```
"According to the report, revenue in 2026 was $14.2M."
```

**B — Typed structured output**

```json
{
  "metric": "revenue",
  "value": 14.2,
  "unit": "USD_M",
  "year": 2026
}
```

**C — Typed + lineage, sem conteúdo da fonte**

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

**D — Typed + lineage + evidence**

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

A × B isola o efeito da estrutura; B × C isola o efeito de lineage/provenance; C × D isola o efeito adicional de fornecer grounding documental.

## 7. Tipos de erro controlados

O estudo será restringido a três classes de falha, suficientes para gerar análise sem inflar o escopo:

| Tipo de erro | Exemplo correto | Perturbação controlada |
|---|---|---|
| Value error | $12.4M | $14.2M |
| Percentage error | 8.1% | 11.1% |
| Metadata error | 2025 / USD M | 2026 / USD B |

As perturbações serão determinísticas e registradas como ground truth do experimento. Para o estudo principal de propagação, o erro será introduzido cedo no pipeline, após uma saída correta do Extrator e antes do handoff. Para avaliar atribuição do estágio de origem sem tornar a tarefa trivial, um subconjunto menor incluirá falhas introduzidas em estágios diferentes.

**Nota de implementação — os dois estudos:** o Extrator só extrai figuras brutas (não computa razões), então não existem claims de percentual na sua saída. Por isso o experimento se divide em dois estudos, e não um só com uma variação de estágio:

| | Injeção em | Roda por condição | Classes de erro | Mede |
|---|---|---|---|---|
| Estudo principal | Extrator | Analista + Redator | value, metadata | propagação, contenção, atribuição |
| Subestudo de estágio | Analista | Redator | percentage | atribuição de estágio (FESA) |

No subestudo, o Analista também roda de forma compartilhada (uma execução canônica projetada nas 4 condições), o que limita a Propagation Depth desse braço a 1 — seu propósito é FESA, não profundidade de propagação. Todo experimento (ambos os estudos) inclui um braço de controle sem injeção (`error_type=None`), necessário porque o pipeline erra algumas perguntas por conta própria, mesmo sem erro injetado; sem essa linha de base não é possível separar erro injetado de erro nativo, nem "erro contido" de "erro propagado que coincidiu com a resposta certa".

Um guard determinístico (`verify_extraction`) confere que o valor de cada claim do Extrator aparece literalmente na evidência associada antes de o claim poder ser alvo de injeção — isso impede que a perturbação caia sobre um número já fabricado pelo modelo, o que invalidaria o ground truth da injeção.

## 8. Protocolo experimental mínimo

Os sete passos abaixo são o protocolo da proposta. Cada um traz a nota de implementação correspondente, de modo que o que foi efetivamente construído possa ser auditado contra o que foi proposto. A subseção 8.8 fecha com a matriz de execução resultante.

**1. Selecionar um benchmark com documentos, respostas e evidências verificáveis.** FinanceBench [11] foi o escolhido por possuir perguntas financeiras, respostas e trechos de evidência; o experimento roda o conjunto aberto inteiro (150 perguntas, três `question_type`), usando o evidence snippet de cada pergunta como "documento-fonte" (sem parsing de PDF).

> **Nota de implementação — quantas perguntas entram de fato.** Das 150 perguntas, **138 produzem estado extraído**. As 12 restantes são qualitativas ("There are none", descrição de litígios, descrição de linha de negócio) e o Extrator devolve zero claims, porque não há figura numérica literal na evidência: sem claim numérico não existe o que corromper, e elas ficam fora do experimento por construção. Nas 138 restantes o Extrator produziu **548 claims, dos quais 545 (99%) passam no guard de verificação literal** descrito na seção 7. Esses números foram medidos com um preflight que roda apenas o Extrator (cacheado em disco, de modo que o custo é reaproveitado pela rodada principal).

**2. Executar o componente responsável pelo estágio alvo e obter um estado correto; em seguida, aplicar um Error Injector determinístico para criar uma das três classes de erro.**

> **Nota de implementação — estado compartilhado e as regras exatas de perturbação.** O Extrator roda **uma única vez por (pergunta × seed)** e o estado canônico resultante é cacheado e compartilhado pelas quatro condições. Isso é o passo 3 levado a sério — o erro injetado é literalmente o mesmo em A/B/C/D — e tem uma consequência metodológica que precisa ser declarada: Schema Validity e custo variável são medidos em **Analista + Redator**, com o Extrator entrando como custo fixo comum às condições.
>
> As três perturbações são determinísticas (sem RNG) e registradas como ground truth:
>
> | Classe | Regra implementada |
> |---|---|
> | `value` | transposição do par de dígitos adjacentes **mais à direita que altere o valor em ≥ 10%**. Reproduz o exemplo canônico da seção 7 (`12.4 → 14.2`) e garante perturbação material em qualquer ordem de grandeza (`39403 → 34903`). A regra literal "transpor os dois últimos dígitos" produziria `39403 → 39430`, isto é, +0,07% — um erro menor que o arredondamento do estágio seguinte, o que faria ESR e Correction Rate medirem ruído. Sem par elegível, cai num fallback ×1,15 que preserva a forma do número. |
> | `percentage` | deslocamento fixo de **+3,0 pontos percentuais** (`8.1 → 11.1`). |
> | `metadata` | `year + 1` (`2017 → 2018`) reescrevendo **simultaneamente o rótulo `period`** (`FY2017 → FY2018`); subtipo alternativo `unit_shift` escalona a unidade uma ordem de grandeza (`USD_M → USD_B`). |
>
> A reescrita do `period` junto com o `year` não é cosmética: a serialização da condição A renderiza `period or year`, e **todos os claims do conjunto têm `period` preenchido**. Corrompendo só o campo `year`, o handoff de A sairia idêntico ao do braço de controle — o erro de metadata nunca chegaria à condição A, que mediria contenção artificial em 100% das células e invalidaria a comparação RQ1 nesse braço.
>
> A escolha do claim-alvo também é determinística, por ordem de preferência: (i) claim com unidade compatível com a classe de erro **e** valor presente na resposta gold, de modo que o erro atinja o caminho que responde à pergunta; (ii) claim com unidade compatível; (iii) primeiro claim na ordenação por `claim_id`. Só claims aprovados pelo guard de verificação literal são candidatos.
>
> **Consequência direta:** o `n` varia por classe de erro, porque cada perturbação exige uma unidade. O censo dos 548 claims extraídos é `USD_M` 378, `PCT` 82, `USD_K` 34, `USD_B` 31, `RATIO` 23.
>
> | Braço | `n` de perguntas | Restrição |
> |---|---|---|
> | `metadata` (Extrator) | **138 / 138** | todo claim tem ano |
> | `value` (Extrator) | **115 / 138** | exige cifra monetária; as 23 excluídas só têm claims em `PCT`/`RATIO` |
> | `percentage` (Analista) | **55 / 138** | exige claim derivado em `PCT` na saída do Analista |
>
> As 23 perguntas sem alvo para `value` não são falha de execução: sua evidência só imprime percentuais ou razões, e transpor dígitos de `8.1%` seria a classe `percentage`, não `value`. Misturá-las tornaria a métrica "acurácia por tipo de erro" ininterpretável.

**3. Serializar exatamente o mesmo estado incorreto nas condições A, B, C e D.** A diferença entre as execuções deve estar apenas no contrato de handoff.

> **Nota de implementação.** O estado canônico é corrompido **uma vez** e só então projetado nos quatro contratos; a projeção é uma restrição de campos (B recebe `metric/value/unit/year`; C acrescenta `claim_id/source_id/page/generated_by/derived_from`; D acrescenta `evidence`). A serialização da condição A é um **template determinístico, não uma paráfrase gerada por LLM** — caso contrário A carregaria uma variável extra (a paráfrase) além da ausência de estrutura, e a comparação A × B deixaria de isolar o efeito da estrutura. Uma checagem automatizada de conformidade verifica que **cada uma das classes de erro é visível na prosa de A**, e não apenas a classe `value`; era justamente a ausência dessa verificação para as demais classes que deixava passar o problema do `period` descrito no passo 2.

**4. Na condição C, impedir qualquer recuperação da fonte a partir de `source_id`/`page`. Na condição D, incluir explicitamente o trecho de evidência correto.**

> **Nota de implementação.** O bloqueio é **por construção, não por instrução no prompt**: nenhum estágio downstream recebe o documento-fonte, e nenhum agente tem ferramentas, banco ou histórico de conversa — cada estágio vê exclusivamente o payload de handoff que lhe foi entregue. Como reforço auditável, cada célula grava no log o resultado de uma checagem de vazamento por sobreposição de n-gramas (janelas de 12 palavras) entre o prompt do estágio e o documento-fonte; em A/B/C qualquer sobreposição é marcada como vazamento, e em D a checagem é informativa, já que ali a evidência está presente de propósito.

**5. Executar os estágios downstream com a mesma configuração de modelo e prompts equivalentes, registrando estados intermediários e dependências entre claims.**

> **Nota de implementação — o que é mantido constante.** Modelo, temperatura, `reasoning_effort` e modo de structured output são idênticos nas quatro condições e ficam gravados em `model_params` de **todo evento do log**, de modo que a constância seja verificável a posteriori e não apenas afirmada. A instrução de **tarefa** de cada estágio é idêntica entre condições; só muda a instrução de **formato** do handoff, que é a própria variável manipulada.
>
> Dois parâmetros merecem registro explícito por serem confundidores de primeira ordem:
>
> - **`reasoning_effort` fixo em `medium`.** Mais esforço de raciocínio aumenta a chance de o próprio estágio detectar a inconsistência do erro injetado; no limite, um modelo que sempre corrige daria ESR ≈ 0 nas quatro condições e o experimento não mediria nada. O parâmetro também entra direto no custo, porque reasoning tokens são cobrados como output.
> - **Temperatura 1.** O modelo usado rejeita `temperature=0` ("only the default (1) value is supported"), então o parâmetro é omitido da requisição. O determinismo do experimento não depende disso: a injeção e seu ground truth são calculados fora do modelo.
>
> Não há retries, `parser_model`, reflection nem majority voting: **um handoff inválido precisa aparecer como inválido no log**, e não ser reparado por baixo dos panos — caso contrário Schema Validity mediria o mecanismo de reparo, não o contrato. É uma chamada por estágio.

**6. Classificar o destino de cada erro: preservado, transformado, amplificado, corrigido ou contido antes da saída final.**

> **Nota de implementação — o instrumento de medida.** Nada é calculado durante a execução: o log guarda o estado cru e o ground truth, e todas as métricas são derivadas offline por um instrumento único, **idêntico nas quatro condições**. Isso obriga a uma decisão que precisa ficar explícita: as métricas de containment operam sobre o **texto de saída de cada estágio** (`output_raw`), nunca sobre `claims`/`derived_from`. Calcular containment a partir dos claims seria impossível em A (texto livre, zero claims), parcial em B (claims sem lineage) e completo em C/D — e D apareceria como "mais amplificadora" apenas por emitir mais campos para contar, medindo o formato do contrato em vez do comportamento do erro. `derived_from` é usado como sinal **secundário** (`lineage_agreement`), para validar o instrumento textual onde há proveniência.
>
> Toda comparação é feita contra o **braço de controle da mesma condição, mesma pergunta e mesma seed** — a comparação nunca cruza condições, de modo que o ruído estrutural (JSON em C/D, prosa em A) apareça nos dois lados e se cancele na diferença. Duas regras de contagem saíram de artefatos observados no piloto: números dentro do campo `evidence` não contam como afirmação do estágio (são citação da fonte, e contá-los inflava a amplificação de D em ~3×), e a deduplicação é tolerante a arredondamento (`9.6` e `9.6%` são a mesma afirmação). A sexta categoria de destino (`sem_efeito`) e o critério que separa "corrigido" de "contido" estão detalhados na nota da seção 10.

**7. Repetir as condições com execuções/seeds suficientes para análise estatística simples e intervalos de confiança.**

> **Nota de implementação — por que uma seed e qual é a unidade de análise.** Uma medição piloto com o modelo usado mostrou respostas finais numericamente idênticas entre seeds em 16/16 células (2 perguntas × 4 condições, limpas e injetadas) — réplicas por seed **não geraram variância neste desenho**. A unidade de análise passa a ser a **pergunta**, e não seed × pergunta, para não inflar artificialmente o `n` com dados duplicados; pelo mesmo motivo as quatro condições de uma mesma pergunta não são tratadas como observações independentes, já que partem do mesmo estado extraído. A taxa de discordância entre seeds é remedida no conjunto inteiro antes da rodada principal, e refeita sempre que o modelo ou o `reasoning_effort` mudarem.
>
> Os intervalos de confiança são calculados por **bootstrap percentílico** (5.000 reamostragens com reposição sobre as perguntas, percentis 2,5 e 97,5), e não pela aproximação normal: as métricas aqui são binárias (ESR, RCCA, FESA) ou contagens pequenas e enviesadas (Propagation Depth varia de 0 a 2), e com proporções próximas de 0 ou 1 o intervalo normal produziria limites fora de `[0,1]`.

### 8.8 A matriz de execução resultante

Com 1 seed e as quatro condições, a matriz a executar é:

| Estudo principal (injeção no Extrator) | perguntas | × condições | células |
|---|---|---|---|
| controle limpo (sem injeção) | 138 | 4 | 552 |
| braço `value` | 115 | 4 | 460 |
| braço `metadata` | 138 | 4 | 552 |
| **subtotal** | | | **1.564** (4.692 chamadas ao modelo) |

| Subestudo de estágio (injeção no Analista) | perguntas | × condições | células |
|---|---|---|---|
| controle limpo | 138 | 4 | 552 |
| braço `percentage` | 55 | 4 | 220 |
| **subtotal** | | | **772** (1.544 chamadas ao modelo) |

**Total: 2.336 células e 6.236 chamadas**, estimadas em ~5 h de execução sequencial e ~US$ 3 a partir da latência e do custo médios medidos no piloto. Uma **célula** é uma execução completa do pipeline para uma combinação (pergunta × seed × braço × condição) e gera um arquivo `.jsonl` próprio, com todos os eventos daquela execução: saída crua e parseada de cada estágio, payload de handoff, o `InjectionRecord` com o ground truth da perturbação, o relatório do auditor, as checagens de contrato e o consumo de tokens/latência/custo por chamada. No estudo principal cada célula custa 3 chamadas (Analista → Redator → Auditor) e no subestudo 2 (Redator → Auditor), já que os estágios até o ponto de injeção rodam de forma compartilhada.

Duas limitações decorrem diretamente desse desenho e são reportadas junto dos resultados: a Propagation Depth máxima é **2** no estudo principal e **1** no subestudo (onde o Analista também roda compartilhado); e o custo do auditor é registrado em separado (`event_type="audit"`), fora do custo operacional do pipeline, porque ele é instrumento de medida e não estágio.

## 9. Dimensões e métricas principais

A avaliação não será limitada à accuracy final. O experimento observará quatro dimensões complementares:

- **Error Survival Rate (ESR):** percentual de erros injetados que permanecem presentes ou influenciam a resposta final.
- **Propagation Depth:** número de estágios downstream afetados pelo erro antes de ele ser corrigido, contido ou chegar à saída final.
- **Error Amplification:** quantidade de novos claims incorretos derivados do erro inicial.
- **Root Cause Claim Accuracy (RCCA):** percentual de falhas finais para as quais o sistema identifica corretamente o claim que iniciou a cadeia de erro.
- **First Error Stage Accuracy (FESA):** percentual de casos em que o sistema identifica corretamente o estágio onde surgiu o primeiro erro.
- **Schema Validity:** aplicável a B, C e D; mede se o handoff respeita o contrato estrutural, sem confundi-lo com correção semântica.
- **Operational Overhead:** tokens, latência, chamadas e custo adicional de cada condição.

**Nota de implementação:** com structured outputs nativo (validação via Pydantic/JSON Schema), Schema Validity tende a ~1.0 por construção — o modelo raramente produz JSON inválido quando a geração é restringida por gramática. Para que a métrica não seja trivial, o log também registra `contract_checks`: violações semânticas que nenhum JSON Schema captura (`derived_from` apontando para um `claim_id` inexistente, `claim_id` duplicado, `generated_by` incoerente, evidência em D que não é literal da fonte). Um sinal secundário adicional, `lineage_agreement`, verifica em C/D se o `derived_from` aponta de fato para o claim onde o erro foi injetado — serve para validar o instrumento de medida textual onde há proveniência, não é métrica primária de nenhuma RQ.

Traceability deixa de ser avaliada apenas pela presença de campos de provenance. O critério forte será se esses dados permitem atribuir corretamente a causa raiz de uma falha observada na saída final.

| Dimensão | Pergunta | Métricas principais |
|---|---|---|
| Correctness | O resultado final está correto? | Final Factual Accuracy; acurácia por tipo de erro; Correction Rate. |
| Containment | Quando surge um erro, até onde ele contamina o pipeline? | Error Survival Rate; Propagation Depth; Error Amplification. |
| Root-Cause Observability | Dado um erro final, conseguimos atribuir corretamente sua origem? | Root Cause Claim Accuracy (RCCA); First Error Stage Accuracy (FESA). |
| Operational Cost | Quanto custa obter as propriedades adicionais? | Tokens; latência; número de chamadas; custo monetário quando aplicável. |

## 10. Exemplo de atribuição de causa raiz

```
Resposta final incorreta
  ↓
claim C31 — Writer
  ↓ derived_from
claim C17 — Analyst
  ↓ derived_from
claim C08 — Extractor ← primeiro claim incorreto
  ↓
source_id / page / estágio de origem
```

A avaliação não pergunta apenas "há lineage?". Ela compara a origem reconstruída com o ground truth da injeção. Se o primeiro erro foi introduzido em C08 pelo Extrator e o mecanismo atribui a causa a C17 no Analista, a atribuição está incorreta mesmo que exista uma cadeia de provenance.

**Nota de implementação — sexta categoria de destino:** além de preservado/transformado/amplificado/corrigido/contido (seção 8, item 6), a classificação usa uma sexta categoria, `sem_efeito`, para os casos em que nenhum estágio downstream muda em relação ao controle — sinal de que o claim corrompido estava fora do caminho da resposta e o pipeline nunca teve o que corrigir ou conter. Somar esses casos a "contido" infla artificialmente a contenção com células em que o contrato nunca foi de fato testado; por isso `sem_efeito` também é excluído do denominador da Correction Rate. A distinção entre "corrigido" e "contido" exige ainda que a resposta final tenha *voltado* a coincidir com a da execução limpa — apenas o valor original reaparecer em algum estágio downstream não basta, porque isso gera falso-positivo sistemático em erros de metadata (o ano original volta a aparecer na própria pergunta ou em claims irmãos não corrompidos mesmo quando o Redator se recusa a responder); recusa e omissão contam como "contido", não como correção.

## 11. Perguntas de pesquisa

- **RQ1** — Qual é o efeito da estruturação do handoff sobre a propagação e a correção do erro? Comparação principal: A × B.
- **RQ2** — Qual é o efeito da preservação de lineage/provenance sobre containment e atribuição correta da causa raiz? Comparação principal: B × C.
- **RQ3** — Qual é o efeito adicional de disponibilizar a evidência original ao componente downstream, separadamente da provenance? Comparação principal: C × D.

Custo operacional será reportado transversalmente às três RQs, permitindo observar o trade-off entre confiabilidade adicional e overhead.

## 12. Contribuição esperada

- Uma ablação controlada que separa três mecanismos frequentemente combinados na prática: estrutura, lineage/provenance e re-grounding por evidência.
- Evidência sobre como o contrato de comunicação altera o ciclo de vida de uma falha já existente, em vez de tratar apenas a capacidade do LLM de evitar alucinações.
- Métricas de root-cause attribution que avaliam se a observabilidade do harness permite reconstruir corretamente claim e estágio de origem, e não apenas armazenar metadados.
- Um protocolo reproduzível para acompanhar erros entre estados intermediários e recomendações práticas sobre o trade-off entre correctness, containment, observability e custo.

## 13. O que ficará fora do escopo inicial

Para manter o TCC executável até o início de dezembro de 2026, não farão parte da contribuição principal:

- fine-tuning, distillation ou treinamento de novos modelos;
- comparação ampla entre muitos LLMs e SLMs;
- RAG, retries, reflection, majority voting ou múltiplos tipos de verifier;
- pipelines com topologias complexas, como DAGs, ciclos ou dezenas de agentes;
- múltiplos domínios de aplicação e taxonomias extensas de erros.

**Extensão opcional:** somente após concluir o experimento principal, repetir um subconjunto com um segundo modelo menor (SLM) para verificar se os efeitos se mantêm em outra faixa de capacidade.

## 14. Critério de sucesso do TCC

O trabalho não precisa demonstrar que D é sempre superior. O resultado relevante é decompor de forma causal o que muda ao adicionar estrutura, lineage e evidência. Resultados negativos também são úteis: por exemplo, B pode atingir alta schema validity sem melhorar correctness; C pode aumentar root-cause attribution sem reduzir Error Survival Rate; D pode conter mais erros, porém com maior overhead. O sucesso depende de um protocolo controlado, reproduzível e capaz de atribuir os efeitos ao mecanismo correto.

## 15. Cronograma enxuto

| Período | Entrega |
|---|---|
| 25 ago – 7 set | Fechar RQs, benchmark, modelo, schemas A/B/C/D e ground truth das perturbações. |
| 8 – 27 set | Implementar pipeline, Error Injector, logging/lineage e executar piloto pequeno. |
| 28 set – 31 out | Executar experimento principal A/B/C/D e o subconjunto de root-cause attribution. |
| 1 – 15 nov | Análise estatística, gráficos, revisão dos casos de erro e trade-offs de custo. |
| 16 – 29 nov | Redação final, revisão com o orientador e preparação da apresentação. |
| Início de dez | Apresentação/defesa. |

## 16. Bibliografia inicial

Prioridade de leitura: [4], [5], [6], [7], [9], [10] e [11]. Os três papers que motivaram a ideia permanecem como referências de contexto arquitetural [1–3]. A lista continua intencionalmente curta.

1. Park, J. S. et al. (2023). *Generative Agents: Interactive Simulacra of Human Behavior*. arXiv:2304.03442.
2. Altera.AL et al. (2024). *Project Sid: Many-agent simulations toward AI civilization*. arXiv:2411.00114.
3. Park, J. S. et al. (2024; rev. 2026). *LLM Agents Grounded in Self-Reports Enable General-Purpose Simulation of Individuals*. arXiv:2411.10109.
4. Singh, P.; Pawar, B. (2026). *The Hallucination Snowball: Modeling Error Propagation as State Transitions in Multi-Agent LLM Pipelines*. arXiv:2608.14588. — Referência mais próxima do problema; explicita structured handoffs como direção futura.
5. Barrak, A. (2025). *Traceability and Accountability in Role-Specialized Multi-Agent LLM Pipelines*. arXiv:2510.07614. — Relaciona handoffs estruturados, rastreabilidade e falhas entre etapas.
6. Geng, S. et al. (2025). *Generating Structured Outputs from Language Models: Benchmark and Studies*. arXiv:2501.10868. — Base para structured outputs, JSON Schema e constrained decoding.
7. Ray, J. (2026). *The Constraint Tax: Measuring Validity-Correctness Tradeoffs in Structured Outputs for Small Language Models*. arXiv:2605.26128. — Separa validade estrutural de correção semântica.
8. Ran, M. et al. (2026). *CaveAgent: Transforming LLMs into Stateful Runtime Operators*. arXiv:2601.01569. — Alternativa a handoffs textuais/JSON baseada em estado persistente e programático.
9. Zhong, H.; Zhu, S. (2026). *AI Harness Engineering: A Runtime Substrate for Foundation-Model Software Agents*. arXiv:2605.13357. — Fundamenta o harness como camada de execução, verificação, observabilidade e controle.
10. Chen, M. et al. (2026). *From Failed Trajectories to Reliable LLM Agents: Diagnosing and Repairing Harness Flaws*. arXiv:2606.06324. — Relaciona traces, provenance, atribuição de falhas e reparos no harness.
11. Islam, P. et al. (2023). *FinanceBench: A New Benchmark for Financial Question Answering*. arXiv:2311.11944. — Dataset candidato por possuir perguntas, respostas e evidências verificáveis.

**Próximo passo imediato:** congelar o schema exato de B/C/D, selecionar um subconjunto inicial do FinanceBench e implementar um piloto de ponta a ponta antes de ampliar o número de execuções.
# Parecer — TCC "Contratos de Handoff, Propagação e Atribuição de Erros em Pipelines de IA Generativa"

**Autor:** Victor Amarante F. da Silva · **Orientador:** Cleber Zanchettin · CIn/UFPE · 15 páginas, formato IEEE
**Base do parecer:** leitura integral do PDF, conferência por código das Tabelas IV, VII, VIII, IX e X, inspeção da Fig. 2 e da marcação em negrito da Tabela VIII, consulta das 16 referências arXiv na API do arXiv, e busca na web dos dois modelos de 2026.

**Legenda de custo:** **T** = só edição de texto · **R** = reanálise dos logs já existentes, sem novas chamadas · **E** = experimento novo (custo estimado a partir da Tabela IV: a rodada completa custou US$ 3,32 no GPT e US$ 13,50 no Haiku).

---

## 1. Veredito

Trabalho bem acima do padrão de TCC. A pergunta é clara, o desenho isola a variável manipulada, existe braço de controle, a análise é pareada por pergunta com bootstrap, e a seção de ameaças aponta por conta própria os dois problemas mais sérios da RQ2 (vazamento do ano pelo `source_id` e critério de acerto assimétrico). As referências existem e os números citados batem com os resumos que consegui conferir.

Os problemas que restam são de **medida**, não de execução. Três categorias do instrumento ("sem efeito", profundidade e taxa de correção) dependem do formato do contrato, embora o texto afirme o contrário. A frase de fechamento ("conteúdo verificável, e não formato nem ponteiros") vai além do que uma ablação aninhada permite concluir. Quase tudo se resolve com reanálise dos logs (R) ou com experimentos de poucos dólares (E). Nenhum dos pontos invalida os achados centrais sobre a evidência (RQ3) nos dois modelos de API.

**Recomendação:** apto para defesa. Antes do depósito final, tratar os itens A1–A6 (T ou R, exceto A2 e A5, que pedem experimentos baratos).

---

## 2. O que conferi e o resultado

| Verificação | Resultado |
|---|---|
| Execuções injetadas da Tabela IV = 4 × (valor + metadado + percentual) | Fecha nos três modelos (1.264, 1.212, 1.104) |
| Tabela IX: colunas somam 100% | Fecha (99–101) |
| ESR (Tab. VII) ≈ preservado + transformado + amplificado (Tab. IX) | Fecha em todas as 12 células, diferença ≤ 0,02 |
| Diferenças pareadas (Tab. VIII) vs. diferença das médias (Tab. VII) | Fecha em 6 das 7 métricas; **não fecha na taxa de correção** (item A4) |
| Tokens: +972/+1.375/+966 (B→C), +357/+293/+259 (C→D), razões 3,9×/3,7×/2,2× | Fecham |
| "63 comparações" na Tabela VIII | Fecha (3 × 7 × 3); 34 intervalos excluem zero, 4 encostam em zero e estão corretamente sem negrito |
| 16 referências arXiv | Todas resolvem para o título e os autores citados |
| Números citados de terceiros presentes nos resumos | Conferidos para [3] (58,4; 16,2; 75,4; 346), [9], [12], [6], [10], [14], [16], [5], [4]. Não conferi os que só aparecem no corpo dos artigos (p. ex. "1.642 execuções", "140 perguntas") |
| GPT-5.6 Luna e Qwen3.5 9B | Existem; o preço de tabela do Luna (0,20/1,20) confere |
| Execuções completas da Tabela IV | **Não consegui fechar** para Haiku e Qwen (item B6) |

---

## 3. Pontos fortes

1. **Isolamento da variável.** O Extrator roda uma vez, o estado corrompido é literalmente o mesmo nas quatro condições, e a prosa de A vem de template fixo (Seção III-A e III-C). Isso elimina a fonte de ruído mais óbvia.
2. **Controle limpo e falso positivo do auditor como linha de base.** A Tabela VII mostra que, sem essa linha, Haiku e Qwen pareceriam bons em localizar o estágio. É uma contribuição metodológica real e reutilizável.
3. **Honestidade analítica.** O vazamento pelo `source_id` (128 de 142 perguntas) e a recontagem da RCCA com critério comum são reportados no resumo, nos resultados, na discussão e nas ameaças. O autor enfraquece o próprio resultado mais vistoso em vez de escondê-lo.
4. **Replicação em três famílias de modelo**, com um resultado negativo informativo (Qwen).
5. **Unidade de análise correta** (pergunta, não execução) e recusa explícita de inflar n com seeds.
6. **Custo reportado por mecanismo**, com o achado prático de que o lineage custa cerca de mil tokens e a evidência cerca de 300.
7. **Redação** clara e econômica; tabelas e a Fig. 2 legíveis.

---

## 4. Novidade

- **Posicionamento:** execução direta de um item de trabalho futuro de Singh e Pawar [3] (agosto de 2026), com dois acréscimos próprios: a origem do erro como variável de saída e o controle sem injeção. A ablação aninhada A→B→C→D do contrato com erro injetado não apareceu na minha busca.
- **Alcance da busca:** seis consultas por palavras-chave na API do arXiv (13 resultados). É uma varredura limitada; ausência nela não é prova de ineditismo.
- **Trabalhos que deveriam entrar em Trabalhos Relacionados:**
  - *Routed Graph Handoff* (Banerjee e Chadha, arXiv:2608.25277, ago. 2026): manipula o formato do handoff (grafo tipado × linguagem natural) e relata regressão quando só o formato estruturado é usado. Qualifica a frase da Seção I "O formato do handoff aparece pouco como variável controlada" e reforça a RQ1.
  - *MetaGPT* (Hong et al., arXiv:2308.00352): é a origem da tese de que artefatos estruturados entre papéis reduzem alucinação em cascata. A RQ1 testa essa tese de forma isolada e deveria dizer isso.
  - *Agent Behavioral Contracts II* (Bhardwaj et al., arXiv:2608.12895): duas instâncias do mesmo modelo falham juntas com alta frequência. Sustenta a ameaça "auditor é o mesmo modelo do pipeline".
  - *Chain-of-Verification* (Dhuliawala et al., arXiv:2309.11495): verificação explícita contra a fonte, relevante para a discussão da Seção VI-C.

---

## 5. Problemas prioritários (A = alta prioridade)

### A1. A categoria "sem efeito" depende do contrato, e isso contamina a taxa de correção — custo R

- **Onde:** Seção III-G (último parágrafo), Seção IV-C ("Taxa de correção"), Tabela IX.
- **Trecho:** "Quase sempre ela indica que o claim corrompido estava fora do caminho da resposta, e somá-la à contenção inflaria a métrica com execuções em que o contrato nunca foi posto à prova."
- **Problema:** o estado corrompido é idêntico nas quatro condições. Se "sem efeito" fosse propriedade do claim (fora do caminho da resposta), a fração seria a mesma em A, B, C e D. Não é.
- **Meu cálculo (a partir da Tabela IX):**

| "Sem efeito" (%) | A | B | C | D |
|---|---|---|---|---|
| GPT-5.6 Luna | 27 | 3 | 2 | 9 |
| Claude Haiku 4.5 | 16 | 6 | 2 | 10 |
| Qwen3.5 9B | 13 | 6 | 4 | 5 |

  O piso entre condições (2%, 2%, 4%) é o teto do que pode ser "claim fora do caminho". O excedente é efeito do contrato: 25 pontos em A no GPT e 7 a 8 pontos em D nos modelos de API.
- **Interpretação provável (hipótese, não verificada nos logs):** em D, o Analista lê a evidência, usa o valor certo e produz a mesma saída do controle. Pela ordem de decisão da Seção III-G, isso cai em "sem efeito" antes de chegar a "corrigido". É a melhor correção possível, classificada como execução em que "o contrato nunca foi posto à prova". Em A, a prosa do Analista não reescreve o campo corrompido (p. ex. o ano), e a mesma execução que em B vira "contido" ou "corrigido" fica como "sem efeito".
- **Consequência:** a taxa de correção exclui do denominador exatamente esses casos, com exclusão diferente por condição. Isso explica o sinal trocado no GPT de A para B: acurácia final cai (0,34 → 0,28) e taxa de correção sobe (0,31 → 0,38). A fração "corrigido" de D (23%, 17%) está subestimada, e a leitura da Seção V-B ("Em B, esses casos passam a se dividir entre correção e contenção") descreve uma reclassificação do instrumento, não uma mudança de comportamento. A ESR não é afetada.
- **Como corrigir:**
  1. Definir "fora do caminho" por pergunta: sem efeito nas quatro condições ao mesmo tempo.
  2. Reportar, além da taxa atual, a **retenção**: P(injetada correta | controle correto), sem o corte "erro com efeito".
  3. Reclassificar como "corrigido no primeiro estágio" as execuções sem efeito em uma condição cujo par em outra condição teve efeito.
- **Esboço (nomes de colunas hipotéticos):**
```python
g = runs[runs.injected].pivot_table(index=["model","qid","err"], columns="cond", values="no_effect", aggfunc="first")
off_path = g.all(axis=1)                      # sem efeito em A, B, C e D
runs["off_path"] = runs.set_index(["model","qid","err"]).index.map(off_path)
ret = runs[runs.injected & runs.ctrl_correct].groupby(["model","cond"]).correct.mean()   # retenção
```
- **Texto sugerido (III-G):** "A fração sem efeito varia entre condições (Tabela IX), embora o estado corrompido seja o mesmo. Por isso, só tratamos como fora do caminho da resposta as execuções sem efeito nas quatro condições; as demais são contadas como correção no primeiro estágio."
- **Critério de aceite:** a fração "fora do caminho" é igual nas quatro colunas de cada modelo, e a tabela traz a retenção ao lado da taxa de correção.
- **Versão curta:** "sem efeito" não é só amostra ruim; em D é correção silenciosa e em A é absorção pela prosa.

### A2. Falta o piso de ruído: controle contra réplica do controle — custo E (≈ US$ 2 no total)

- **Onde:** Seção IV-B ("Cada execução rodou com uma única seed"), Eq. 1, Seção VII-A.
- **Trecho:** "Essa variação aleatória afeta igualmente as quatro condições, então tende a alargar os intervalos, e não a criar diferenças entre elas."
- **Problema:** ESR, profundidade, amplificação e "sem efeito" são definidas por diferença de conjuntos de números contra **uma** execução de controle, gerada com temperatura padrão e, no Haiku, sem seed. Duas execuções limpas do mesmo estado podem diferir sozinhas. A afirmação de que o ruído é igual entre condições não foi medida, e é plausível que prosa e JSON variem de forma diferente de uma execução para outra. O piloto citado (16 de 16 respostas idênticas) cobre só o GPT e só a resposta final, enquanto a profundidade depende da saída do Analista.
- **Consequência:** parte do termo "F \ Fc ≠ ∅" da ESR e parte da profundidade podem ser ruído de amostragem. Sem o piso por condição, o aumento de profundidade de A para B (+0,43; +0,26; +0,31), que é o único efeito consistente da RQ1, não pode ser atribuído inteiramente ao erro.
- **Como corrigir:** repetir o controle em uma subamostra (p. ex. 40 perguntas × 4 condições × 3 modelos), aplicar o mesmo instrumento ao par controle–controle e reportar "ESR nula" e "profundidade nula" por modelo e condição.
- **Critério de aceite:** uma linha nova na Tabela VII com o piso de ruído; os efeitos da Tabela VIII continuam fora de zero depois de descontado o piso da condição correspondente.
- **Versão curta:** rodar um teste A/A antes de interpretar diferenças contra o controle.

### A3. A frase de fechamento afirma mais do que a ablação aninhada identifica — custo T (ou E ≈ US$ 1–5 para sustentar a frase)

- **Onde:** Seção VIII, penúltimo parágrafo; também o fim do Resumo.
- **Trecho:** "o que torna um handoff mais confiável é o conteúdo verificável que ele carrega, e não o seu formato nem os seus ponteiros."
- **Problema:** a evidência só foi testada **em cima** de estrutura e lineage (D = C + evidência). O desenho mede o efeito marginal de cada camada dadas as anteriores. Ele não mostra que as camadas anteriores são dispensáveis: a RCCA de 0,8 em D pode depender de o auditor ter identificadores para apontar. O próprio texto reconhece isso na Seção VI-C ("não dá para saber se a evidência sozinha teria o mesmo efeito").
- **Como corrigir (duas opções):**
  1. **T:** reescrever para o que foi medido.
  2. **E:** rodar a condição "tipado + evidência, sem lineage" (e, se possível, "prosa + citação da evidência"). Isso fecha um fatorial 2×2 lineage × evidência e transforma o trabalho futuro nº 1 em resultado. O custo é da ordem de uma fração da rodada original.
- **Texto sugerido:** "Dado um handoff já tipado e com proveniência, o que reduziu a sobrevivência do erro foi acrescentar conteúdo verificável. O desenho aninhado não permite dizer se a evidência teria o mesmo efeito sem estrutura ou sem lineage."
- **Critério de aceite:** nenhuma frase do Resumo ou da Conclusão atribui irrelevância a formato ou ponteiros sem a condição fatorial correspondente.

### A4. Taxa de correção: Tabela VIII não bate com a Tabela VII — custo T/R

- **Onde:** Tabelas VII e VIII, linhas "Taxa de correção".
- **Meu cálculo (diferença das médias da Tab. VII × diferença pareada da Tab. VIII):**

| Comparação | Modelo | Tab. VII | Tab. VIII |
|---|---|---|---|
| A→B | GPT | +0,07 | +0,04 |
| A→B | Haiku | +0,12 | +0,03 |
| A→B | Qwen | +0,08 | +0,01 |
| B→C | Haiku | +0,11 | +0,18 |
| B→C | Qwen | −0,06 | +0,00 |
| C→D | GPT | +0,20 | +0,16 |

  Nas outras seis métricas a discrepância é de no máximo 0,02 (arredondamento).
- **Causa provável:** a taxa de correção é condicional ("controle correto e erro com efeito"), e o conjunto de perguntas elegíveis muda de condição para condição. A Tabela VII faz a média sobre conjuntos diferentes; a VIII, presumivelmente, sobre a interseção.
- **Como corrigir:** informar o n elegível por célula, declarar em nota qual conjunto cada tabela usa, e preferir a retenção do item A1, que tem denominador comum.
- **Critério de aceite:** o leitor consegue reproduzir a linha da Tabela VIII a partir de uma tabela de médias sobre o mesmo conjunto.

### A5. De A para B mudam duas coisas: o formato da entrada e a supressão do raciocínio na saída — custo R + E (≈ US$ 1–2)

- **Onde:** Seção V-A (queda da acurácia do controle), Seção VI-A, Tabela VII (tokens, latência, custo).
- **Trecho:** "o formato estruturado custa acurácia mesmo sem erro nenhum: o Haiku cai de 0,72 em A para 0,59 em B, e o Qwen, de 0,63 para 0,44".
- **Meu cálculo (separado do texto do aluno):** resolvi tokens de entrada e de saída a partir de "Tokens por execução" e "US$ por mil execuções", usando os preços da Tabela V. Premissas: preço de tabela, sem desconto de cache.

| Modelo | Cond. | Entrada (est.) | Saída (est.) | Acurácia do controle |
|---|---|---|---|---|
| GPT (raciocínio ligado) | A | 439 | 252 | 0,71 |
| | B | 864 | 473 | 0,68 |
| | C | 1.571 | 738 | 0,66 |
| | D | 1.759 | 907 | 0,70 |
| Haiku (raciocínio desligado) | A | 616 | 291 | 0,72 |
| | B | 1.498 | 156 | 0,59 |
| | C | 2.679 | 350 | 0,61 |
| | D | 2.872 | 450 | 0,74 |

  No Qwen não há custo, mas o total de tokens **cai** de A para B (974 → 946) apesar de a entrada crescer, e a latência cai de 3,2 s para 2,4 s. A saída, portanto, encolheu.
- **Leitura:** nos dois modelos sem raciocínio, a saída em B é bem mais curta que em A. Em prosa, o modelo calcula "em voz alta"; no JSON imposto, não há onde fazer isso. O GPT, que raciocina em tokens ocultos, não perde acurácia no controle. É o mecanismo de Tam et al. [11]. Assim, a perda de acurácia de A para B pode vir do modo de decodificação, e não do contrato de handoff. A amplificação do Haiku acompanha o volume de saída de A a C (1,93 → 1,26 → 1,86 para 291 → 156 → 350 tokens), o que sugere que a contagem absoluta de "valores novos" também mede verbosidade.
- **Como corrigir:**
  1. **R:** reportar tokens de saída por condição e normalizar a amplificação pelo número de valores emitidos.
  2. **E:** condição B′ com um campo `reasoning: str` como primeiro campo do schema do Analista, só nas execuções de controle de Haiku e Qwen. Alternativa: Haiku com raciocínio estendido ligado.
- **Critério de aceite:** se a acurácia do controle em B′ voltar ao nível de A, o texto atribui a perda ao modo de saída; se não voltar, a conclusão atual da RQ1 fica mais forte.
- **Versão curta:** separar "handoff tipado" de "saída sem espaço para raciocinar".

### A6. RCCA por identificador não é imune a palpite; falta o placebo — custo R

- **Onde:** Seção V-A.
- **Trecho:** "A RCCA é bem menos sensível a esse viés, já que exige apontar o claim corrompido ou o seu valor exato."
- **Problema:** isso vale para o critério de métrica e valor, não para o de identificador. O claim-alvo é escolhido de forma determinística entre os que estão no caminho da resposta (Seção III-D). Um auditor que culpa alguém com frequência e segue o `derived_from` da resposta até a raiz chega a esse claim sem detectar nada.
- **Meu cálculo:** claims por pergunta = 3,9 (GPT), 3,5 (Haiku) e 6,1 (Qwen), ou seja, acerto por sorteio uniforme de 0,26, 0,28 e 0,17 quando o auditor culpa alguém. Em C, o auditor culpa alguém em 65% (Haiku) e 74% (Qwen) das execuções **limpas**; a RCCA em C é 0,41 e 0,44. FESA menos falso positivo dá −0,14 e −0,16 no Haiku em B e C, e é negativa nas quatro condições do Qwen (no GPT: +0,12, +0,10, +0,23, +0,68).
- **Como corrigir:** como o injetor é determinístico, o claim que **seria** corrompido é conhecido também nas execuções de controle. Calcular a "RCCA placebo" (fração dos controles em que o auditor aponta esse claim) e a "FESA placebo" (fração em que aponta o Extrator), e reportar RCCA e FESA líquidas.
```python
ctrl = runs[~runs.injected & runs.cond.isin(["C","D"])]
placebo_rcca = (ctrl.auditor_claim_id == ctrl.would_be_target_id).groupby([ctrl.model, ctrl.cond]).mean()
placebo_fesa = (ctrl.auditor_stage == "extractor").groupby([ctrl.model, ctrl.cond]).mean()
```
- **Recomendação de apresentação:** tornar o critério comum (métrica e valor) a RCCA principal e deixar a variante por identificador como secundária. O próprio texto já mostra que, pelo critério comum, o ganho de B para C é +0,03, 0,00 e +0,04.
- **Critério de aceite:** Tabela VII com a linha de placebo; a frase citada é reescrita.

---

## 6. Problemas de prioridade média (B)

### B1. Profundidade conta repetição passiva — custo R
- **Onde:** Seção V-B e VI-A. **Trecho:** "com claims tipados, o erro passou a alterar mais estágios".
- **Problema:** um schema que obriga a reemitir `value` e `year` de cada claim altera a saída do Analista mesmo quando o valor não é usado. O dado do próprio autor aponta nessa direção: repetição literal em 52% (B) contra 30% (A) no GPT. A ESR não muda de A para B (−0,03; −0,05; −0,02).
- **Correção:** decompor a profundidade em "repetição literal" e "uso em derivação" (o `derived_from` permite isso em C e D; em A e B, usar presença do valor em número derivado). No Resumo, acompanhar "aumentou a profundidade" de "sem alterar a sobrevivência".

### B2. Auditor fixo para os três pipelines — custo E (≈ US$ 2)
- **Onde:** Seção VII-B, já reconhecido. **Ação:** reauditar os traces de Haiku e Qwen com o auditor GPT. Forma um 2×2 (modelo do pipeline × modelo do auditor) e responde diretamente se a RCCA de 0,47 do Qwen em D vem do trace quebrado ou do auditor fraco. Não exige rodar o pipeline de novo.

### B3. Acurácia final é permissiva — custo R
- **Onde:** Seção IV-C. **Trecho:** "fração de execuções cuja resposta final contém um número igual ao da resposta do benchmark".
- **Problema:** uma resposta que traz o valor certo e o corrompido conta como correta. No Qwen, de C para D, a acurácia sobe 0,10 enquanto a ESR não muda e "amplificado" fica em 48%. Isso é compatível com respostas que passam a citar números da evidência sem abandonar o erro.
- **Correção:** acurácia estrita = contém o número do benchmark **e** não contém o valor corrompido. Especificar também qual texto é a "resposta final" em B, C e D (o campo de resposta ou o JSON inteiro, com `page`, identificadores e ano do `source_id`).

### B4. Comparação com Singh e Pawar mistura métricas — custo T
- **Onde:** Seção VI-C. **Trecho:** "A evidência no contrato é, portanto, mais barata e bem menos eficaz que um portão explícito".
- **Problema:** os 16,2% de [3] são sobrevivência após verificação com ferramenta de recuperação, em outro pipeline, com outros modelos e outra perturbação. A ESR daqui inclui influência indireta, como a própria Seção IV-C explica.
- **Texto sugerido:** "Os números não são diretamente comparáveis (métrica, pipeline e perturbação diferentes), mas a ordem de grandeza sugere que a evidência no contrato, sem instrução de conferência, fica longe do que um portão dedicado alcança."

### B5. Erro de metadado: quatro vazamentos possíveis, só um quantificado — custo R
- **Onde:** Seções III-D, V-C, VII-A.
- **Problema:** o texto quantifica o ano no `source_id` (128 de 142, só no GPT). Faltam: (i) a mesma contagem para Haiku e Qwen; (ii) a fração de perguntas cujo enunciado traz o ano original (afeta as quatro condições); (iii) a fração de injeções em que o ano deslocado colide com outro claim da mesma métrica, comum em demonstrativos com anos consecutivos, o que gera um erro autoevidente; (iv) a fração dos trechos de evidência de D que contêm o ano. O item (iv) explicaria por que a evidência quase não ajuda no braço de metadado (Fig. 2).
- **Correção:** uma tabela pequena com as quatro frações por modelo.

### B6. Tabela IV: execuções completas não fecham — custo T
- **Meu cálculo:** execuções completas menos injetadas = 1.144, 1.128 e 1.200, isto é, 8 × 143, 8 × 141 e 8 × 150. As "perguntas com estado extraído" são 143, 138 e 149. Bate no GPT; sobram 3 perguntas no Haiku e 1 no Qwen. A decomposição "8 ×" é hipótese minha.
- **Correção:** nota de rodapé com a fórmula do total de execuções.

### B7. Configuração do Qwen subespecificada — custo T + E pequeno
- **Onde:** Seção IV-B ("foi usada a versão padrão do modelo no Ollama") e V-F.
- **Problemas:**
  1. Não há tag, digest nem quantização. A biblioteca do Ollama lista várias variantes do 9B.
  2. Não há o tamanho de contexto efetivo (`num_ctx`). Se o padrão for menor que o prompt do auditor em C e D, o Ollama trunca sem erro. Isso é uma hipótese a verificar com `prompt_eval_count` nos logs, não um fato.
  3. A temperatura e as penalidades não foram enviadas. Conferir com `ollama show --parameters` se há penalidade de presença no padrão da tag usada; uma penalidade desse tipo desestimula repetir o mesmo rótulo de unidade em vários claims, o que seria uma explicação para as 1.210 unidades fora da lista.
  4. "Como o schema aceita qualquer texto no campo de unidade": basta declarar o campo como `Literal[...]` no Pydantic para a decodificação restrita impedir essa violação. Do jeito atual, a "validade de contrato" de 0,51 do Qwen mede em boa parte uma omissão do schema.
- **Correção:** reportar a configuração; repetir 30 perguntas do Qwen com unidade em `Literal` e penalidade zerada.

### B8. Instrumento textual sem validação humana — custo R (1 a 2 horas)
- **Onde:** Seção III-G. A "concordância de lineage" compara o instrumento com a cadeia declarada pelo modelo, não com um julgamento humano.
- **Correção:** rotular à mão 50 execuções estratificadas por condição e destino, e reportar a concordância com o instrumento.

### B9. Reprodutibilidade — custo T
- Não há link para repositório, prompts dos estágios e do auditor, schemas, nem identificadores exatos dos modelos (snapshot com data). Duas das três contribuições declaradas são "protocolo" e "instrumento"; sem o artefato, elas não são reaplicáveis. Incluir apêndice com prompts e schemas e o link do código.

---

## 7. Insights que os dados sustentam e o texto não explora

1. **O gargalo em D é a instrução, não a informação.** No erro de valor, o auditor aponta o claim corrompido em 97% (GPT) e 88% (Haiku) dos casos, mas a ESR desse braço cai só 0,25 e 0,20 e fica em torno de 0,7 (leitura aproximada da Fig. 2). O mesmo modelo, com a mesma evidência, detecta quando é perguntado e deixa passar quando não é. Experimento barato: condição D com uma frase no prompt do Analista ("confira cada valor contra o trecho de evidência antes de usar"). Isso quebra a regra de prompt de tarefa idêntico, então deve entrar como condição extra, não como substituta. É a ponte direta para o trabalho futuro nº 3.
2. **O subestudo contradiz parte da H1 e reforça a tese central.** No GPT, RCCA e FESA são 0,96 a 0,98 em todas as condições, inclusive em texto livre. Um percentual derivado pode ser recalculado a partir dos claims que estão no trace; a atribuição não dependeu de proveniência, e sim de o erro ser conferível. A Seção VI-E diz que "o texto livre teve a pior atribuição de origem, com RCCA de no máximo 0,05", o que vale só para o estudo principal.
3. **A evidência não reduz a sobrevivência do erro de ano.** Na Fig. 2, a ESR do braço de metadado fica praticamente plana de A a D nos três modelos. O ganho agregado de C para D vem todo do braço de valor. O resumo deveria dizer "erro de valor" onde diz "erro".
4. **Correções silenciosas em D** (item A1): o salto de "sem efeito" de C para D (2% → 9% e 2% → 10%) é provavelmente o melhor resultado do contrato D e está fora da métrica de correção.
5. **Custo por ganho.** Pelo critério comum de RCCA, o lineage custa cerca de mil tokens por execução para um ganho de 0,00 a 0,04; a evidência custa cerca de 300 tokens para um ganho de 0,31 a 0,33 nos modelos de API. Uma tabela de "ganho por mil tokens" tornaria a implicação prática da Seção VI-F quantitativa.
6. **Sem acesso à fonte, o erro de valor é praticamente indetectável.** A ESR do braço de valor fica acima de 0,8 em A, B e C nos dois modelos de API (leitura aproximada da Fig. 2). É o resultado que melhor justifica a tese, e hoje aparece só no gráfico.

---

## 8. Ajustes pontuais de texto (custo T)

| Onde | Trecho | Ajuste |
|---|---|---|
| Resumo; V-B | "de menos de 0,09"; "RCCA abaixo de 0,09 em A e em B" | Qwen em B é 0,09 na Tabela VII. Usar "até 0,09". |
| V-E | "a FESA, entre 0,70 e 0,82" (Haiku, subestudo) | A Tabela X traz 0,70 a 0,81. |
| VIII | "quase quatro vezes mais tokens" | 3,9× e 3,7× são "quase quatro vezes os tokens"; "vezes mais" sugere 4,9×. |
| VI-E | "A H2 se confirma." | A H2 ("não reduz necessariamente") é difícil de refutar. Dizer que os dados são compatíveis com ela. |
| III-C × VI-A | "essa prosa vem de um template fixo" × "Em prosa, o Analista resume, reorganiza" | Explicitar que o template vale para o handoff Extrator→Analista e que o handoff Analista→Redator em A é texto do modelo. |
| IV-B | Latência do GPT maior em C (13,2 s) que em D (11,3 s) | Dizer se as condições rodaram intercaladas ou em blocos; em blocos, a latência mede a hora do dia. |
| I | Hipóteses H1–H4 | Informar se foram fixadas antes da rodada final. |
| VII-D | "sem correção para comparações múltiplas" | Opcional: aplicar Holm aos 21 testes por modelo e marcar o que sobrevive. |

---

## 9. Ordem sugerida de trabalho

1. **Só logs (um a dois dias):** A1, A4, A6, B1, B3, B5, B6 e a tabela de custo por ganho.
2. **Só texto:** A3 (versão T), B4, B9, seção 8 e as quatro referências novas.
3. **Experimentos de poucos dólares:** A2 (teste A/A), A5 (B′ com campo de raciocínio), B2 (auditor fixo), A3 (condição evidência sem lineage), insight 1 (D com instrução de conferência).

---

## 10. Perguntas para a banca

1. A fração "sem efeito" vai de 2% a 27% no GPT com o mesmo estado corrompido. O que acontece nessas execuções em A e em D?
2. Se o auditor do GPT auditar os traces do Qwen, a RCCA em D sobe?
3. Por que a evidência não reduz a ESR no erro de ano? O trecho de evidência contém o ano?
4. Quantas execuções de controle repetidas dariam "erro sobrevivente" pelo critério da Eq. 1?
5. A afirmação "não o formato nem os ponteiros" se sustenta sem uma condição com evidência e sem lineage?

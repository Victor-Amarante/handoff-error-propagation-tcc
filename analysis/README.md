# Analise

O calculo das metricas ja esta implementado e testado em
[`handoff/measure.py`](../handoff/measure.py). O notebook aqui so agrega,
faz estatistica e plota:

```python
import pandas as pd
from handoff.measure import load_cells, to_records

df = pd.DataFrame(to_records(load_cells("../data/logs")))
df.groupby("condition")[["esr", "propagation_depth", "amplification",
                         "fesa", "rcca", "pipeline_tokens"]].mean()
```

Uma linha por celula injetada, ja pareada com o seu controle. `has_control=False`
marca celula sem contrafactual: as metricas de containment vem `None` de
proposito, porque sem a execucao limpa elas nao sao mensuraveis.

## O que measure.py ja resolve

| Metrica | Funcao |
|---|---|
| Final Factual Accuracy | `final_correct` |
| Correction Rate | coluna `corrected` |
| Error Survival Rate | `esr` |
| Propagation Depth | `propagation_depth` |
| Error Amplification | `amplification` |
| destino do erro (passo 6 do protocolo) | `fate` |
| RCCA / FESA | `rcca`, `fesa` |
| Schema Validity | `schema_validity`, `contract_validity` |
| custo | colunas `*_tokens`, `*_cost_usd`, `latency_ms`, `n_calls` |

## Quatro coisas a nao esquecer

**A unidade de analise e a PERGUNTA, nao a celula.** Seeds nao geram variancia
neste desenho: medido, seed 1 e seed 2 dao respostas finais identicas em 8/8
celulas limpas e 8/8 injetadas. Agrupar por `seed` e tratar as replicas como
observacoes independentes triplicaria o n com dado duplicado e estreitaria o
intervalo de confianca artificialmente. Calcule os intervalos sobre as 25
perguntas, com `groupby(["condition", "question_id"])` antes de agregar.
Confira a premissa nos seus proprios dados:

```python
# taxa de discordancia entre replicas: deve ser ~0 neste modelo
piv = df.pivot_table(index=["question_id", "condition", "error_type"],
                     columns="seed", values="esr")
(piv[1] != piv[2]).mean()
```

**Toda metrica de containment se compara ao braco de controle da MESMA
condicao, pergunta e seed.** O pipeline erra algumas perguntas sozinho; sem o
contrafactual, "erro sobreviveu" e "pipeline ja errava" ficam indistinguiveis.
O pareamento e automatico em `pair_with_control`.

**`corrigido` x `contido`:** as duas terminam com o erro fora da resposta final. O
que separa e a resposta ter voltado a ser a da execucao limpa (correcao) ou a
figura ter sumido -- recusa, omissao (contencao). Recusa e comum no braco
`metadata`: o estagio percebe a inconsistencia de ano e se nega a calcular.

**`fate == "sem_efeito"` nao e contencao.** Significa que nada mudou em estagio
nenhum -- quase sempre porque o claim corrompido estava fora do caminho da
resposta. Somar esses casos a `contido` inflaria a contencao com celulas em que
o contrato nunca foi testado. Considere reportar a taxa de `sem_efeito` como
qualidade da amostra, nao como resultado.

**Reporte a taxa de falso-positivo do auditor junto com RCCA/FESA.** Um auditor
enviesado a sempre culpar algum estagio pontuaria alto em FESA sem saber de
nada, entao a metrica so se interpreta contra a linha de base do controle:
quantas celulas SEM erro injetado receberam um culpado. Calcule sobre as
celulas `is_control` (`audit.first_error_stage != "none"`).

Medido no piloto com `gpt-5.6-luna` / effort medium: **0/16**, todas com
confianca 0.99 -- o instrumento esta bem calibrado e RCCA/FESA podem ser lidos
de forma direta. Vale refazer a conta na matriz completa, e refazer sempre que
o modelo ou o `reasoning_effort` mudar: com `gpt-5.4-mini` o mesmo auditor
apontava culpado em quase toda execucao limpa.

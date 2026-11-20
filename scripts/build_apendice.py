"""Gera o apendice do artigo (prompts e schemas) direto de handoff/prompts.py e
handoff/schemas, para que o texto publicado seja literalmente o que rodou.

Uso: uv run python scripts/build_apendice.py
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from handoff.conditions import MAIN_CONDITIONS, Condition, Stage  # noqa: E402
from handoff.prompts import (  # noqa: E402
    ANALYST_FORMAT, ANALYST_TASK, AUDITOR_INSTRUCTIONS, EXTRACTOR_INSTRUCTIONS,
    VERIFY_SENTENCE, WRITER_FORMAT, WRITER_TASK,
)


def block(title, text):
    return f"\\noindent\\textit{{{title}}}\n\\begin{{lstlisting}}\n{text.strip()}\n\\end{{lstlisting}}\n"


parts = [
    "% !TEX root = ../tcc.tex",
    "% Gerado por scripts/build_apendice.py a partir de handoff/prompts.py. Nao edite a mao.",
    "\\section{Prompts e schemas}\\label{sec:apendice}",
    "",
    "Os prompts abaixo são os que rodaram no experimento, em inglês. A instrução de cada estágio é a de tarefa seguida da de formato da condição. "
    "A mensagem do usuário traz a pergunta e o handoff do estágio anterior, sob os rótulos \\texttt{QUESTION} e \\texttt{INPUT FROM <ESTÁGIO>}, e a do auditor traz a pergunta, o trace e a resposta final.",
    "",
    block("Extrator", EXTRACTOR_INSTRUCTIONS),
    block("Analista: instrução de tarefa", ANALYST_TASK),
]
for c in MAIN_CONDITIONS:
    parts.append(block(f"Analista: formato da condição {c}", ANALYST_FORMAT[c]))
parts.append(block("Redator: instrução de tarefa", WRITER_TASK))
for c in MAIN_CONDITIONS:
    parts.append(block(f"Redator: formato da condição {c}", WRITER_FORMAT[c]))
parts += [
    block("Condição E (Analista e Redator): como B, acrescida de", "Carry over the `evidence` snippet of the input claim you used."),
    block("Condição B' (Analista): como B, acrescida de", "Use `reasoning` to work through the computation before writing the claims."),
    block("Condição D' (Analista e Redator): como D, acrescida de", VERIFY_SENTENCE),
    block("Auditor", AUDITOR_INSTRUCTIONS),
    "Os schemas são modelos Pydantic com \\texttt{extra=\"forbid\"}. Os campos de cada claim por condição estão na Tabela~\\ref{tab:condicoes}: "
    "\\texttt{metric} (texto), \\texttt{value} (número), \\texttt{unit} (texto, com a lista USD\\_K, USD\\_M, USD\\_B, PCT e RATIO só na descrição), "
    "\\texttt{year} (inteiro), \\texttt{claim\\_id}, \\texttt{source\\_id}, \\texttt{page}, \\texttt{generated\\_by}, \\texttt{derived\\_from} (lista de identificadores) e \\texttt{evidence} (texto). "
    "O Analista devolve uma lista de claims e, em C e D, o identificador do claim que responde à pergunta. O Redator devolve \\texttt{answer\\_text} e o claim que a resposta afirma. "
    "O relatório do auditor, igual nas quatro condições, tem \\texttt{first\\_error\\_stage} (extractor, analyst, writer ou none), \\texttt{root\\_cause\\_claim\\_id}, "
    "\\texttt{root\\_cause\\_claim\\_text}, \\texttt{reported\\_metric}, \\texttt{reported\\_value}, \\texttt{confidence} (entre 0 e 1) e \\texttt{rationale}.",
    "",
]
out = Path("TCC___Contratos_de_Handoff_em_sistemas_de_IA_Generativa/src/sections/apendice.tex")
out.write_text("\n".join(parts), encoding="utf-8")
print(out)

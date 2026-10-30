"""Gera as tabelas de resultados do artigo (src/tables/*.tex) a partir dos logs.

Uso: uv run python scripts/build_tables.py   (a partir da raiz do repositorio)
"""
import sys, json, warnings; warnings.filterwarnings('ignore')
from pathlib import Path
sys.path.insert(0,'.')
import pandas as pd, numpy as np
from handoff.measure import load_cells, to_records, final_correct
from handoff.logger import is_complete
MODELS=[('gpt-5.6-luna','GPT-5.6 Luna'),('claude-haiku-4-5-20251001','Claude Haiku 4.5'),('qwen3.5-9b','Qwen3.5 9B')]
def ic(v):
    v=pd.Series(v).dropna().to_numpy(float)
    if len(v)<2: return (np.nan,np.nan)
    r=np.random.default_rng(0); m=r.choice(v,size=(5000,len(v))).mean(1); return tuple(np.quantile(m,[.025,.975]))
def pipe_usage(path):
    L=C=0.0
    for l in open(path):
        e=json.loads(l)
        if e['event_type']=='stage_output' and e.get('stage') in('analyst','writer') and e.get('usage'):
            u=e['usage']; L+=(u.get('latency_ms') or 0)/1000; C+=u.get('cost_usd') or 0
    return L,C
def load(slug,stage):
    cells=[c for c in load_cells(Path('data')/slug/'logs') if is_complete(c.path)]
    inj={(c.question_id,str(c.condition),c.error_type,c.injection_stage):c for c in cells if not c.is_control}
    df=pd.DataFrame(to_records(cells))
    KEY=['question_id','condition','error_type','injection_stage']
    keys=df[KEY].apply(tuple,axis=1)
    sa={k for k,c in inj.items() if c.audit is None}
    mk=keys.isin(sa); df[['rcca','fesa']]=df[['rcca','fesa']].astype(object); df.loc[mk,['rcca','fesa']]=False
    us=[pipe_usage(inj[k].path) for k in keys]
    df['lat_s']=[u[0] for u in us]; df['cost_k']=[u[1]*1000 for u in us]
    n=df.groupby(['injection_stage','error_type','question_id']).condition.transform('nunique')
    df=df[(n==4)&(df.injection_stage==stage)].copy()
    ctr=[c for c in cells if c.is_control and c.injection_stage==stage]
    return df,ctr
M=['final_correct','corrected','esr','propagation_depth','amplification','rcca','fesa','contract_validity','lineage_agreement','pipeline_tokens','lat_s','cost_k']
def pq(d):
    d=d.copy()
    for m in M: d[m]=pd.to_numeric(d[m],errors='coerce')
    return d.groupby(['condition','question_id'])[M].mean()
def f(x,dec=2):
    if x is None or (isinstance(x,float) and np.isnan(x)): return '--'
    return f'{x:.{dec}f}'.replace('.',',')
def fi(x): return f'{x:,.0f}'.replace(',','.')
data={}
for slug,name in MODELS:
    for stage in ['extractor','analyst']:
        df,ctr=load(slug,stage); p=pq(df)
        cd=pd.DataFrame([{'c':str(c.condition),'acc':final_correct(c),'fp':(c.audit.get('first_error_stage')!='none') if c.audit else None} for c in ctr])
        fate=df.groupby('condition').fate.value_counts(normalize=True).unstack().fillna(0).to_dict(orient='index')
        data[(slug,stage)]=dict(p=p,cd=cd,n=df.question_id.nunique(),fate=fate)
# ---------- Tabela principal (por condicao) ----------
rows=[('Correção',None),('Acurácia factual final','final_correct',2),('Taxa de correção','corrected',2),
      ('Contenção',None),('ESR','esr',2),('Profundidade de propagação','propagation_depth',2),('Amplificação','amplification',2),
      ('Observabilidade',None),('RCCA','rcca',2),('FESA','fesa',2),('Falso positivo do auditor$^{a}$','FP',2),('Concordância de lineage','lineage_agreement',2),
      ('Validade e linha de base',None),('Validade de contrato','contract_validity',2),('Acurácia do controle$^{a}$','ACC',2),
      ('Custo (Analista + Redator)',None),('Tokens por execução','pipeline_tokens',0),('Latência (s)','lat_s',1),('US\\$ por mil execuções','cost_k',2)]
def table_main(stage,label,caption):
    L=[r'\begin{table*}[t]',r'\caption{'+caption+'}',r'\label{'+label+'}',r'\centering',r'\footnotesize',r'\setlength{\tabcolsep}{3.2pt}',
       r'\begin{tabular}{|l|cccc|cccc|cccc|}',r'\hline']
    L.append(' & '+' & '.join(r'\multicolumn{4}{c|}{\textbf{'+n+'}}' for _,n in MODELS)+r' \\')
    L.append(r'\textbf{Métrica} & '+' & '.join(['A & B & C & D']*3)+r' \\'); L.append(r'\hline')
    for r in rows:
        if r[1] is None:
            L.append(r'\multicolumn{13}{|l|}{\textit{'+r[0]+r'}} \\'); continue
        lab,m,dec=r; cells=[]
        for slug,_ in MODELS:
            D=data[(slug,stage)]
            for c in 'ABCD':
                if m=='FP': v=pd.to_numeric(D['cd'][D['cd'].c==c].fp,errors='coerce').mean()
                elif m=='ACC': v=pd.to_numeric(D['cd'][D['cd'].c==c].acc,errors='coerce').mean()
                else: v=D['p'].loc[c][m].mean()
                if m=='cost_k' and slug=='qwen3.5-9b': cells.append('--'); continue
                if m=='lineage_agreement' and c in 'AB': cells.append('--'); continue
                cells.append(fi(v) if dec==0 and not np.isnan(v) else f(v,dec))
        L.append(lab+' & '+' & '.join(cells)+r' \\')
    L+= [r'\hline', r'\end{tabular}',
         r'\\[2pt]{\scriptsize $^{a}$Calculados sobre as execuções de controle (sem injeção). Demais métricas: média por pergunta sobre as execuções injetadas.}',
         r'\end{table*}']
    return '\n'.join(L)
# ---------- Tabela de deltas pareados ----------
DM=[('Acurácia factual final','final_correct'),('Taxa de correção','corrected'),('ESR','esr'),('Profundidade','propagation_depth'),('Amplificação','amplification'),('RCCA','rcca'),('FESA','fesa')]
def table_delta(stage,label,caption,comps):
    L=[r'\begin{table*}[t]',r'\caption{'+caption+'}',r'\label{'+label+'}',r'\centering',r'\footnotesize',r'\setlength{\tabcolsep}{4pt}',
       r'\begin{tabular}{|l|l|c|c|c|}',r'\hline',
       r'\textbf{Comparação} & \textbf{Métrica} & '+' & '.join(r'\textbf{'+n+'}' for _,n in MODELS)+r' \\',r'\hline']
    for a,b,rq in comps:
        first=True
        for lab,m in DM:
            cells=[]
            for slug,_ in MODELS:
                p=data[(slug,stage)]['p']; d=(p.loc[b][m]-p.loc[a][m]); mu=d.mean(); lo,hi=ic(d)
                s=f'{mu:+.2f} [{lo:+.2f}; {hi:+.2f}]'.replace('.',',').replace('-','$-$')
                sig=(lo>0 or hi<0)
                cells.append(r'\textbf{'+s+'}' if sig else s)
            L.append((rq if first else '')+' & '+lab+' & '+' & '.join(cells)+r' \\'); first=False
        L.append(r'\hline')
    L+=[r'\end{tabular}',
        r'\\[2pt]{\scriptsize Diferença média pareada por pergunta (segunda condição menos a primeira) e IC95\% bootstrap. Em negrito: intervalo que não inclui zero.}',
        r'\end{table*}']
    return '\n'.join(L)
FATES=[('preservado','Preservado'),('transformado','Transformado'),('amplificado','Amplificado'),('corrigido','Corrigido'),('contido','Contido'),('sem_efeito','Sem efeito')]
def table_fate(stage,label,caption):
    L=[r'\begin{table*}[t]',r'\caption{'+caption+'}',r'\label{'+label+'}',r'\centering',r'\footnotesize',r'\setlength{\tabcolsep}{3.2pt}',
       r'\begin{tabular}{|l|cccc|cccc|cccc|}',r'\hline']
    L.append(' & '+' & '.join(r'\multicolumn{4}{c|}{\textbf{'+n+'}}' for _,n in MODELS)+r' \\')
    L.append(r'\textbf{Destino} & '+' & '.join(['A & B & C & D']*3)+r' \\'); L.append(r'\hline')
    for key,lab in FATES:
        cells=[]
        for slug,_ in MODELS:
            fr=data[(slug,stage)]['fate']
            for c in 'ABCD':
                cells.append(f"{100*fr.get(c,{}).get(key,0):.0f}")
        L.append(lab+' & '+' & '.join(cells)+r' \\')
    L+=[r'\hline',r'\end{tabular}',
        r'\\[2pt]{\scriptsize Percentual das execuções injetadas de cada condição. As colunas somam 100\% a menos de arredondamento.}',
        r'\end{table*}']
    return '\n'.join(L)
out=Path('TCC___Contratos_de_Handoff_em_sistemas_de_IA_Generativa/src/tables'); out.mkdir(exist_ok=True)
(out/'resultados-principal.tex').write_text(table_main('extractor','tab:principal','Resultados do estudo principal por modelo e condição (injeção no Extrator)')+'\n')
(out/'resultados-deltas.tex').write_text(table_delta('extractor','tab:deltas','Efeito de cada mecanismo no estudo principal: diferenças pareadas entre condições vizinhas',
   [('A','B','RQ1: A $\\to$ B'),('B','C','RQ2: B $\\to$ C'),('C','D','RQ3: C $\\to$ D')])+'\n')
(out/'resultados-subestudo.tex').write_text(table_main('analyst','tab:subestudo','Resultados do subestudo de estágio por modelo e condição (injeção no Analista)')+'\n')
(out/'resultados-destino.tex').write_text(table_fate('extractor','tab:destino','Destino do erro no estudo principal (\\% das execuções)')+'\n')
print('ok', {k:v['n'] for k,v in data.items()})

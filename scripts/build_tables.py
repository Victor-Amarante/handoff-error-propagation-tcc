"""Gera as tabelas de resultados do artigo (src/tables/*.tex) a partir dos logs.

Uso: uv run python scripts/build_tables.py   (a partir da raiz do repositorio)

Revisao do parecer: a RCCA principal passou a ser o criterio de conteudo
(measure.rcca_conteudo), com o criterio antigo como linha secundaria; entraram
a retencao (denominador comum), a acuracia estrita, a profundidade decomposta,
os placebos do auditor e a marcacao de Holm na tabela de diferencas.
"""
import sys, json, warnings; warnings.filterwarnings('ignore')
from pathlib import Path
sys.path.insert(0,'.')
import pandas as pd, numpy as np
from handoff.measure import load_cells, to_records, final_correct, placebo_attribution
from handoff.logger import is_complete
MODELS=[('gpt-5.6-luna','GPT-5.6 Luna'),('claude-haiku-4-5-20251001','Claude Haiku 4.5'),('qwen3.5-9b','Qwen3.5 9B')]
def ic(v):
    v=pd.Series(v).dropna().to_numpy(float)
    if len(v)<2: return (np.nan,np.nan)
    r=np.random.default_rng(0); m=r.choice(v,size=(5000,len(v))).mean(1); return tuple(np.quantile(m,[.025,.975]))
def boot_p(v):
    v=pd.Series(v).dropna().to_numpy(float)
    m=np.random.default_rng(0).choice(v,size=(5000,len(v))).mean(1)
    return min(1.0,2*min((m<=0).mean(),(m>=0).mean()))
def stage_usage(path):
    L=C=O=0.0
    for l in open(path):
        e=json.loads(l)
        if e['event_type']=='stage_output' and e.get('stage') in('analyst','writer') and e.get('usage') and not (e.get('notes') or {}).get('shared_across_conditions'):
            u=e['usage']; L+=(u.get('latency_ms') or 0)/1000; C+=u.get('cost_usd') or 0; O+=u.get('output_tokens') or 0
    return L,C,O
KEY=['question_id','condition','error_type','injection_stage']
def load(slug,stage,subdir='logs',nconds=4):
    cells=[c for c in load_cells(Path('data')/slug/subdir) if is_complete(c.path)]
    inj={(c.question_id,str(c.condition),c.error_type,c.injection_stage):c for c in cells if not c.is_control}
    df=pd.DataFrame(to_records(cells))
    keys=df[KEY].apply(tuple,axis=1)
    # auditor sem relatorio valido conta como erro de atribuicao, nao como dado faltante
    sa={k for k,c in inj.items() if c.audit is None}
    mk=keys.isin(sa)
    for m in ('rcca','rcca_conteudo','fesa'):
        df[m]=df[m].astype(object); df.loc[mk,m]=False
    us=[stage_usage(inj[k].path) for k in keys]
    df['lat_s']=[u[0] for u in us]; df['cost_k']=[u[1]*1000 for u in us]; df['out_tokens']=[u[2] for u in us]
    df['amp_norm']=pd.to_numeric(df.amplification)/pd.to_numeric(df.n_emitted).replace(0,np.nan)
    # placebo: o auditor do controle aponta o claim que o injetor corromperia?
    ctrl={(c.question_id,str(c.condition),c.injection_stage):c for c in cells if c.is_control}
    pl=[]
    for k,c in inj.items():
        cc=ctrl.get((k[0],k[1],k[3]))
        if cc is None or cc.audit is None or c.injection is None: continue
        p=placebo_attribution(cc,c.injection); pl.append({'question_id':k[0],'condition':k[1],'error_type':k[2],'injection_stage':k[3],
            'rcca_placebo':p['rcca'],'rcca_id_placebo':p['rcca_id'],'fesa_placebo':p['fesa']})
    df=df.merge(pd.DataFrame(pl),on=KEY,how='left')
    df['fesa_liq']=pd.to_numeric(df.fesa)-df.fesa_placebo
    df['sem_efeito']=(df.fate=='sem_efeito').astype(float)
    n=df.groupby(['injection_stage','error_type','question_id']).condition.transform('nunique')
    df=df[(n==nconds)&(df.injection_stage==stage)].copy()
    # A1: "fora do caminho" e propriedade da pergunta, nao da condicao: sem efeito nas quatro
    off=df.groupby(['error_type','question_id']).sem_efeito.transform('min')
    df['fate2']=np.where(df.fate=='sem_efeito',np.where(off==1,'fora_caminho','corrigido_1o'),df.fate)
    ctr=[c for c in cells if c.is_control and c.injection_stage==stage]
    # retencao: P(injetada correta | controle correto), sobre as perguntas cujo
    # controle acerta nas QUATRO condicoes -- denominador comum (A1/A4)
    cd=pd.DataFrame([{'q':c.question_id,'c':str(c.condition),'ok':final_correct(c)} for c in ctr]).dropna()
    pv=cd.pivot_table(index='q',columns='c',values='ok',aggfunc='first')
    common=set(pv[(pv.reindex(columns=list('ABCD'))==True).all(axis=1)].index)
    df['retention']=np.where(df.question_id.isin(common),pd.to_numeric(df.final_correct,errors='coerce'),np.nan)
    return df,ctr,len(common)
M=['final_correct','final_correct_strict','corrected','retention','esr','propagation_depth','depth_literal','depth_derived','amplification','amp_norm',
   'rcca_conteudo','rcca','rcca_placebo','fesa','fesa_placebo','fesa_liq','contract_validity','lineage_agreement','pipeline_tokens','out_tokens','lat_s','cost_k']
def pq(d):
    d=d.copy()
    for m in M: d[m]=pd.to_numeric(d[m],errors='coerce')
    return d.groupby(['condition','question_id'])[M].mean()
def f(x,dec=2):
    if x is None or (isinstance(x,float) and np.isnan(x)): return '--'
    return f'{x:.{dec}f}'.replace('.',',')
def fi(x): return f'{x:,.0f}'.replace(',','.')
data={}
if __name__=='__main__':
  for slug,name in MODELS:
    for stage in ['extractor','analyst']:
        df,ctr,ncommon=load(slug,stage); p=pq(df)
        cd=pd.DataFrame([{'c':str(c.condition),'acc':final_correct(c),'fp':(c.audit.get('first_error_stage')!='none') if c.audit else None} for c in ctr])
        fate=df.groupby('condition').fate2.value_counts(normalize=True).unstack().fillna(0).to_dict(orient='index')
        ncor={c:int(p.loc[c].corrected.notna().sum()) for c in 'ABCD'}
        data[(slug,stage)]=dict(p=p,cd=cd,n=df.question_id.nunique(),fate=fate,ncommon=ncommon,ncor=ncor)
# ---------- Tabela principal (por condicao) ----------
rows=[('Correção',None),('Acurácia factual final','final_correct',2),('Acurácia estrita$^{b}$','final_correct_strict',2),
      ('Taxa de correção$^{c}$','corrected',2),('Retenção$^{d}$','retention',2),
      ('Contenção',None),('ESR','esr',2),('Profundidade de propagação','propagation_depth',2),
      ('\\quad só repetição literal$^{e}$','depth_literal',2),('\\quad com valores novos$^{e}$','depth_derived',2),
      ('Amplificação','amplification',2),('\\quad por valor emitido','amp_norm',2),
      ('Observabilidade',None),('RCCA$^{f}$','rcca_conteudo',2),('\\quad placebo$^{a}$','rcca_placebo',2),
      ('RCCA, critério original$^{g}$','rcca',2),('FESA','fesa',2),('\\quad placebo$^{a}$','fesa_placebo',2),
      ('Falso positivo do auditor$^{a}$','FP',2),('Concordância de lineage','lineage_agreement',2),
      ('Validade e linha de base',None),('Validade de contrato','contract_validity',2),('Acurácia do controle$^{a}$','ACC',2),
      ('Custo (Analista + Redator)',None),('Tokens por execução','pipeline_tokens',0),('\\quad de saída','out_tokens',0),('Latência (s)','lat_s',1),('US\\$ por mil execuções','cost_k',2)]
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
    nc=[D['ncor'][c] for slug,_ in MODELS for D in [data[(slug,stage)]] for c in 'ABCD']
    nr=', '.join(str(data[(slug,stage)]['ncommon']) for slug,_ in MODELS)
    L+= [r'\hline', r'\end{tabular}',
         r'\\[2pt]{\scriptsize\raggedright $^{a}$Calculados sobre as execuções de controle (sem injeção); os placebos medem com que frequência o auditor do controle aponta o claim (ou o estágio) que o injetor corromperia. Demais métricas: média por pergunta sobre as execuções injetadas. '
         r'$^{b}$Contém o número do benchmark e não contém o valor corrompido. '
         r'$^{c}$Entre as execuções com controle correto e erro com efeito; o conjunto elegível muda com a condição ('+f'{min(nc)} a {max(nc)}'+r' perguntas). '
         r'$^{d}$Fração de acertos nas perguntas cujo controle acerta nas quatro condições ('+nr+r' perguntas), sem o corte de erro com efeito. '
         r'$^{e}$Estágios alterados apenas porque repetem o valor corrompido, e estágios com números novos em relação ao controle. '
         r'$^{f}$Critério de conteúdo, comum às quatro condições: o auditor informa a métrica e o valor do claim-alvo como aparecem no trace. '
         r'$^{g}$Critério original: identificador do claim (só em C e D) ou métrica e valor corrompido.\par}',
         r'\end{table*}']
    return '\n'.join(L)
# ---------- Tabela de deltas pareados ----------
DM=[('Acurácia factual final','final_correct'),('Retenção','retention'),('Taxa de correção$^{a}$','corrected'),('ESR','esr'),('Profundidade','propagation_depth'),
    ('Amplificação','amplification'),('RCCA','rcca_conteudo'),('FESA líquida$^{b}$','fesa_liq')]
def table_delta(stage,label,caption,comps):
    L=[r'\begin{table*}[t]',r'\caption{'+caption+'}',r'\label{'+label+'}',r'\centering',r'\footnotesize',r'\setlength{\tabcolsep}{4pt}',
       r'\begin{tabular}{|l|l|c|c|c|}',r'\hline',
       r'\textbf{Comparação} & \textbf{Métrica} & '+' & '.join(r'\textbf{'+n+'}' for _,n in MODELS)+r' \\',r'\hline']
    res={}
    for slug,_ in MODELS:
        p=data[(slug,stage)]['p']; tests={}
        for a,b,rq in comps:
            for lab,m in DM:
                d=(p.loc[b][m]-p.loc[a][m]); lo,hi=ic(d); tests[(a,b,m)]=(d.mean(),lo,hi,boot_p(d))
        order=sorted(tests,key=lambda k:tests[k][3]); holm=set(); K=len(order)
        for r,k in enumerate(order):
            if tests[k][3]<=0.05/(K-r): holm.add(k)
            else: break
        res[slug]=(tests,holm)
    for a,b,rq in comps:
        first=True
        for lab,m in DM:
            cells=[]
            for slug,_ in MODELS:
                tests,holm=res[slug]; mu,lo,hi,_p=tests[(a,b,m)]
                s=f'{mu:+.2f} [{lo:+.2f}; {hi:+.2f}]'.replace('.',',').replace('-','$-$')
                sig=(lo>0 or hi<0)
                if sig: s=r'\textbf{'+s+'}'+('' if (a,b,m) in holm else r'$^{\dagger}$')
                cells.append(s)
            L.append((rq if first else '')+' & '+lab+' & '+' & '.join(cells)+r' \\'); first=False
        L.append(r'\hline')
    L+=[r'\end{tabular}',
        r'\\[2pt]{\scriptsize\raggedright Diferença média pareada por pergunta (segunda condição menos a primeira) e IC95\% bootstrap. Em negrito: intervalo que não inclui zero; $^{\dagger}$: não sobrevive à correção de Holm sobre as 24 comparações do modelo. '
        r'$^{a}$Calculada só sobre as perguntas elegíveis nas duas condições comparadas, por isso não é a diferença das médias da Tabela~\ref{tab:principal}. '
        r'$^{b}$FESA menos o placebo da mesma pergunta e condição.\par}',
        r'\end{table*}']
    return '\n'.join(L)
FATES=[('preservado','Preservado'),('transformado','Transformado'),('amplificado','Amplificado'),('corrigido','Corrigido'),
       ('corrigido_1o','Neutralizado no Analista$^{a}$'),('contido','Contido'),('fora_caminho','Fora do caminho$^{b}$')]
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
        r'\\[2pt]{\scriptsize\raggedright Percentual das execuções injetadas de cada condição. As colunas somam 100\% a menos de arredondamento. '
        r'$^{a}$Nenhum estágio difere do controle nesta condição, mas o mesmo erro altera algum estágio em outra condição: o erro foi neutralizado já no primeiro estágio, sem deixar marca nos números do Analista nem do Redator. '
        r'$^{b}$Sem efeito nas quatro condições, o que caracteriza o claim corrompido como fora do caminho da resposta.\par}',
        r'\end{table*}']
    return '\n'.join(L)
if __name__=='__main__':
    out=Path('TCC___Contratos_de_Handoff_em_sistemas_de_IA_Generativa/src/tables'); out.mkdir(exist_ok=True)
    (out/'resultados-principal.tex').write_text(table_main('extractor','tab:principal','Resultados do estudo principal por modelo e condição (injeção no Extrator)')+'\n')
    (out/'resultados-deltas.tex').write_text(table_delta('extractor','tab:deltas','Efeito de cada mecanismo no estudo principal: diferenças pareadas entre condições vizinhas',
       [('A','B','RQ1: A $\\to$ B'),('B','C','RQ2: B $\\to$ C'),('C','D','RQ3: C $\\to$ D')])+'\n')
    (out/'resultados-subestudo.tex').write_text(table_main('analyst','tab:subestudo','Resultados do subestudo de estágio por modelo e condição (injeção no Analista)')+'\n')
    (out/'resultados-destino.tex').write_text(table_fate('extractor','tab:destino','Destino do erro no estudo principal (\\% das execuções)')+'\n')
    print('ok', {k:v['n'] for k,v in data.items()}, {k:v['ncommon'] for k,v in data.items()})

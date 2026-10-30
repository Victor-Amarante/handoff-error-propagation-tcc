"""Gera a Fig. 2 do artigo (ESR e RCCA por tipo de erro) a partir dos logs.

Uso: uv run --group analysis python scripts/build_figures.py
"""
import sys, warnings; warnings.filterwarnings('ignore')
from pathlib import Path
sys.path.insert(0,'.')
import pandas as pd, numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker
from handoff.measure import load_cells, to_records
from handoff.logger import is_complete
plt.rcParams.update({'font.family':'serif','font.serif':['Times New Roman','Times','DejaVu Serif'],'font.size':8,
  'axes.edgecolor':'#8a8a85','axes.linewidth':0.6,'xtick.color':'#555','ytick.color':'#555','axes.labelcolor':'#222'})
def ic(v):
    v=pd.Series(v).dropna().to_numpy(float); r=np.random.default_rng(0)
    m=r.choice(v,size=(5000,len(v))).mean(1); return np.quantile(m,[.025,.975])
models=[('gpt-5.6-luna','GPT-5.6 Luna'),('claude-haiku-4-5-20251001','Claude Haiku 4.5'),('qwen3.5-9b','Qwen3.5 9B')]
mets=[('esr','ESR (menor é melhor)'),('rcca','RCCA (maior é melhor)')]
ser=[('value','valor','#2a78d6','o','-'),('metadata','metadado','#eb6834','s','--')]
fig,axs=plt.subplots(2,3,figsize=(7.16,3.6),sharex=True,sharey='row')
for j,(slug,name) in enumerate(models):
    cells=[c for c in load_cells(Path('data')/slug/'logs') if is_complete(c.path)]
    df=pd.DataFrame(to_records(cells))
    KEY=['question_id','condition','error_type','injection_stage']
    sa={(c.question_id,str(c.condition),c.error_type,c.injection_stage) for c in cells if not c.is_control and c.audit is None}
    mk=df[KEY].apply(tuple,axis=1).isin(sa); df[['rcca','fesa']]=df[['rcca','fesa']].astype(object); df.loc[mk,['rcca','fesa']]=False
    n=df.groupby(['injection_stage','error_type','question_id']).condition.transform('nunique'); df=df[(n==4)&(df.injection_stage=='extractor')].copy()
    for m,_ in mets: df[m]=pd.to_numeric(df[m],errors='coerce')
    for i,(m,lab) in enumerate(mets):
        ax=axs[i,j]
        for et,etl,col,mkr,ls in ser:
            p=df[df.error_type==et].groupby(['condition','question_id'])[m].mean()
            mu=[p.loc[c].mean() for c in 'ABCD']; lo,hi=zip(*[ic(p.loc[c]) for c in 'ABCD'])
            x=np.arange(4)
            ax.fill_between(x,lo,hi,color=col,alpha=0.12,linewidth=0)
            ax.plot(x,mu,ls,color=col,lw=1.6,marker=mkr,ms=4.5,mec='white',mew=0.8,label=etl)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v,_: f'{v:.2f}'.replace('.',',')))
        ax.set_ylim(0,1.02); ax.set_xticks(range(4)); ax.set_xticklabels(list('ABCD'))
        ax.grid(axis='y',color='#e6e5e0',lw=0.5); ax.set_axisbelow(True)
        for s in ('top','right'): ax.spines[s].set_visible(False)
        if i==0: ax.set_title(name,fontsize=9,color='#222')
        if j==0: ax.set_ylabel(lab)
        if i==1: ax.set_xlabel('condição')
h,l=axs[0,0].get_legend_handles_labels()
fig.legend(h,['erro de valor','erro de metadado'],loc='upper center',ncol=2,frameon=False,bbox_to_anchor=(0.5,1.02),fontsize=8)
fig.tight_layout(rect=(0,0,1,0.95))
out=Path('TCC___Contratos_de_Handoff_em_sistemas_de_IA_Generativa/images/fig2_tipo_erro.pdf')
fig.savefig(out); print(out)

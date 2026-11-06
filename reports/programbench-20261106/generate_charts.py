"""Regenerate the paper comparison from the bundled, frozen data."""
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault('MPLCONFIGDIR',str(Path(tempfile.gettempdir())/'procontract-report-mpl'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parent
data=json.loads((ROOT/'data/paper-aligned.json').read_text())
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,
                     'svg.hashsalt':'procontract-paper-comparison-20261106'})
BLUE='#2563eb';GRAY='#a3acbb';AMBER='#d48a22'


def save(fig,name):
    fig.savefig(ROOT/'assets'/(name+'.png'),dpi=190,bbox_inches='tight')
    fig.savefig(ROOT/'assets'/(name+'.svg'),bbox_inches='tight',metadata={'Date':None})
    vector=ROOT/'assets'/(name+'.svg')
    vector.write_text('\n'.join(line.rstrip() for line in vector.read_text().splitlines())+'\n')
    plt.close(fig)


fig,axes=plt.subplots(2,1,figsize=(9,8),layout='constrained')
for ax,view,title in zip(axes,['same_instance_numeric','same_instance_paper_valid'],
    ['Same instances: paper numeric results vs. current valid runs',
     'Subset: also require the paper\'s historical valid flag']):
    rows=[data[key][view] for key in ['luna','sol']];x=np.arange(2);w=.32
    paper=ax.bar(x-w/2,[r['paper_mean'] for r in rows],w,color=GRAY,label='Paper snapshot')
    current=ax.bar(x+w/2,[r['current_mean'] for r in rows],w,color=BLUE,label='Current snapshot')
    ax.bar_label(paper,labels=[f"{r['paper_mean']:.2f}%" for r in rows],padding=4,fontsize=11)
    ax.bar_label(current,labels=[f"{r['current_mean']:.2f}%" for r in rows],padding=4,fontsize=11)
    ax.set_xticks(x,[f"Luna 5.6 / max → 5.6 / max\nn = {rows[0]['n']}",
                    f"Sol 5.6 / xhigh → 6.1 / max\nn = {rows[1]['n']}"])
    for i,row in enumerate(rows):
        ax.text(i,106,f"Δ {row['delta']:+.2f} pp",ha='center',weight='bold',color=BLUE)
    ax.set_ylim(0,114);ax.set_yticks([0,25,50,75,100]);ax.set_ylabel('Mean task score (%)')
    ax.set_title(title,fontsize=12,pad=14);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    ax.spines[['top','right']].set_visible(False)
axes[0].legend(loc='lower right',frameon=False,ncol=2,fontsize=10)
fig.suptitle('Paper → current ProContract: align the tasks before comparing',fontsize=15)
save(fig,'paper-aligned')

fig,ax=plt.subplots(figsize=(9,3.8),layout='constrained')
for index,key in enumerate(['sol','luna']):
    groups=data[key]['by_paper_valid_flag'];a=groups['True']['contribution_pp'];b=groups['False']['contribution_pp']
    ax.barh(index,a,color=BLUE,height=.46,label='Paper valid flag = true' if index==0 else None)
    ax.barh(index,b,left=a,color=AMBER,height=.46,label='Other paper numeric scores' if index==0 else None)
    if a>.2:ax.text(a/2,index,f'+{a:.2f}',ha='center',va='center',color='white',weight='bold')
    if b>1:ax.text(a+b/2,index,f'+{b:.2f}',ha='center',va='center',color='white',weight='bold')
    else:ax.annotate(f'+{b:.2f}',(a+b/2,index),xytext=(0,19),textcoords='offset points',ha='center',fontsize=10,color='#915b0b')
    ax.text(a+b+.2,index,f'total +{a+b:.2f}',va='center',weight='bold',fontsize=11)
ax.set_yticks([0,1],['Sol 5.6 → 6.1\n175 paired instances','Luna 5.6 → 5.6\n196 paired instances'])
ax.set_xlim(0,17.2);ax.set_ylim(-.6,1.8);ax.set_xlabel('Contribution to paired mean-score change (percentage points)')
ax.set_title('Where the observed gain is concentrated',fontsize=14)
ax.legend(loc='upper right',frameon=False,fontsize=9);ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
ax.spines[['top','right','left']].set_visible(False)
save(fig,'paper-gain-groups')

fig,axes=plt.subplots(1,2,figsize=(11,5.4),layout='constrained')
for ax,key in zip(axes,['luna','sol']):
    rows=data[key]['same_instance_numeric']['rows']
    for flag,color,label in [(True,BLUE,'Paper valid flag = true'),(False,AMBER,'Other numeric score')]:
        selected=[r for r in rows if r['paper_valid']==flag]
        ax.scatter([r['paper'] for r in selected],[r['current'] for r in selected],s=23,alpha=.7,c=color,edgecolor='white',linewidth=.3,label=label)
    ax.plot([0,100],[0,100],color='#64748b',linestyle='--',linewidth=1)
    ax.set(xlim=(-3,103),ylim=(-3,103),xlabel='Paper task score (%)',ylabel='Current task score (%)',
           title=f"{key.title()} · {len(rows)} matched instances")
    ax.set_aspect('equal');ax.grid(alpha=.12);ax.spines[['top','right']].set_visible(False)
axes[0].legend(loc='lower right',frameon=False,fontsize=8)
fig.suptitle('Per-instance paper/current comparison',fontsize=14)
save(fig,'paper-scatter')

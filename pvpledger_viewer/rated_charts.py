"""One axis per compatible rated cohort; no missing-value interpolation."""
from datetime import datetime
from matplotlib.figure import Figure
from .chart_style import apply_chart_palette


def figure(series, *, palette=None):
    f=Figure(figsize=(10,max(3,2.8*len(series))),dpi=100,facecolor='#0b1420')
    for index,s in enumerate(series or [{'label':'Rated progression','points':[]}],1):
        ax=f.add_subplot(max(1,len(series)),1,index);ax.set_facecolor('#142131')
        pts=s['points']
        if pts:
            ax.plot([datetime.fromisoformat(p['time']) for p in pts],[p['rating'] for p in pts],marker='o',linestyle='None',color='#d5b76d')
            ax.tick_params(axis='x',labelrotation=15)
        else:ax.text(.5,.5,'No compatible, dated rating observations.\nReview missing game version / season / bracket / specialization.',transform=ax.transAxes,ha='center',va='center',color='#e7edf5',wrap=True)
        ax.set_title(s['label'],color='#e7edf5',fontsize=9);ax.set_ylabel('Personal rating',color='#e7edf5');ax.tick_params(colors='#e7edf5',labelsize=8);ax.grid(alpha=.18)
    apply_chart_palette(f, palette)
    f.tight_layout(pad=2)
    return f

import json
import tkinter as tk
from tkinter import ttk
from .widgets import Table, page_heading
from ..metric_registry import METRICS
from ..rankings import SCOPES
from .theme import palette


class RankingWindow(tk.Toplevel):
    def __init__(self, app, key=None, reference=None):
        super().__init__(app.root); self.app,self.key,self.reference=app,key,reference
        self.title('Match rankings' if key else 'Historical archive rankings');self.geometry('1120x660')
        controls=ttk.Frame(self,padding=12);controls.pack(fill='x')
        self.metric=ttk.Combobox(controls,values=list(METRICS),state='readonly',width=24);self.metric.set('Damage');self.metric.pack(side='left')
        self.scope=ttk.Combobox(controls,values=SCOPES,state='readonly',width=26);self.scope.set('All recorded participants');self.scope.pack(side='left',padx=5)
        self.mode=ttk.Combobox(controls,values=['Individual Encounters','Player averages','Player medians'],state='readonly',width=23);self.mode.set('Individual Encounters')
        if not key:self.mode.pack(side='left')
        self.minimum=tk.Spinbox(controls,from_=1,to=100000,width=4);self.minimum.pack(side='left',padx=4)
        ttk.Button(controls,text='Rank',command=self.load).pack(side='left')
        self.note=ttk.Label(self,wraplength=1050,padding=10);self.note.pack(fill='x')
        self.table=Table(self,[(k,k,w) for k,w in [('Rank',55),('Player',140),('Realm',130),('Value',110),('Eligible',70),('Excluded',75),('Percentile',90),('Difference from mean',155),('Difference from median',155),('Samples',70),('Coverage',240),('Date',105),('Time',65),('Map',160),('source',100),('event_id',140),('realm_certainty',120),('quality',250)]])
        self.table.pack(fill='both',expand=True,padx=10,pady=10)
        self.serial=0;self.load()
    def load(self):
        try:minimum=int(self.minimum.get());assert minimum>0
        except (ValueError,AssertionError):self.note.configure(text='Minimum samples must be positive');return
        self.serial+=1;serial=self.serial
        metric,scope,mode=self.metric.get(),self.scope.get(),self.mode.get()
        self.note.configure(text='Loading archived cohort…')
        def done(model):
            if not self.winfo_exists() or serial!=self.serial:return
            self.metric.configure(values=list(METRICS))
            definition=model['metric']
            self.note.configure(text=f"{model['cohort']} · {model['eligible']} eligible · {model['excluded']} excluded · "+('Verified complete' if model['complete'] else 'Rank among observed eligible players')+'\n'+definition['unit']+' · '+('Higher' if definition['higher_is_better'] else 'Lower')+' is preferable · '+definition['formula']+'\n'+('No compatible data. ' if not model['rows'] else '')+model['note']+' Separate events may be unresolved duplicate candidates; review Duplicate Review. Scroll right for date, source and event IDs.')
            self.table.set_rows(model['rows'])
        def failed(exc):
            if self.winfo_exists():self.note.configure(text='Ranking failed: '+str(exc))
        filters = self.app.filters if not self.key else None
        self.app.run_job('Preparing rankings…',lambda:self.app.service.ranking(self.key,metric,scope,self.reference,mode,minimum,filters),done,failed)


class PlayersView(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.page=0;self.serial=0
        page_heading(self,'All Players','Every decodable archived sighting · inferred realms are not verified identities · archived encounters only')
        bar=ttk.Frame(self);bar.pack(fill='x')
        self.query=ttk.Entry(bar,width=24);self.query.pack(side='left');self.query.bind('<Return>',lambda e:self.load(reset=True))
        self.query.bind('<KeyRelease>',self.search_later);self.pending=None
        ttk.Label(bar,text='Class').pack(side='left',padx=5);self.class_name=ttk.Entry(bar,width=12);self.class_name.pack(side='left')
        ttk.Label(bar,text='Spec').pack(side='left',padx=5);self.spec=ttk.Entry(bar,width=14);self.spec.pack(side='left')
        ttk.Button(bar,text='Search',command=lambda:self.load(True)).pack(side='left',padx=5)
        ttk.Button(bar,text='Historical rankings',command=lambda:RankingWindow(app,reference=self.table.selected())).pack(side='right')
        self.note=ttk.Label(self,style='Muted.TLabel');self.note.pack(fill='x',pady=5)
        self.table=Table(self,[(k,k,w) for k,w in [('Player',145),('Realm',135),('Realm certainty',110),('Class',115),('Spec',130),('Person',100),('Relationship',130),('Encounters',90),('First',100),('Last',100),('Available statistics',250),('Quality',240)]],on_open=self.open_player)
        bottom=ttk.Frame(self);bottom.pack(side='bottom',fill='x');self.pager=bottom
        ttk.Button(bottom,text='Previous',command=lambda:self.move(-1)).pack(side='left');ttk.Button(bottom,text='Next',command=lambda:self.move(1)).pack(side='left',padx=5)
        ttk.Button(bottom,text='Unresolved records',command=self.unresolved).pack(side='right')
        self.table.pack(fill='both',expand=True)
    def search_later(self,event=None):
        if self.pending:self.after_cancel(self.pending)
        self.pending=self.after(350,lambda:self.load(True))
    def render(self,payload):self.load()
    def move(self,delta):self.page=max(0,self.page+delta);self.load()
    def load(self,reset=False):
        self.pending=None
        if reset:self.page=0
        self.serial+=1;serial=self.serial
        query,cls,spec,page=self.query.get(),self.class_name.get(),self.spec.get(),self.page
        def done(model):
            if serial!=self.serial:return
            self.note.configure(text=f"{model['total']} matching players · page {page+1} · double-click for encounter history")
            self.table.set_rows(model['rows'])
        self.app.run_job('Searching archived players…',lambda:self.app.service.players(query,cls,spec,page),done)
    def open_player(self,player):
        dialog=tk.Toplevel(self);dialog.title('Player encounters — '+player['Player']);dialog.geometry('1120x660')
        ttk.Label(dialog,text=player['Player']+'-'+player['Realm']+' · Realm '+player['Realm certainty']+' · archived encounters, not a complete career',padding=10).pack(fill='x')
        ttk.Button(dialog,text='Rated PvP career…',command=lambda:self.app.open_rated(player=player['player_key'],others=True)).pack(anchor='w',padx=10)
        table=Table(dialog,[(k,k,w) for k,w in [('Date',105),('Time',65),('Map',150),('Type',140),('relationship',100),('Class',110),('Spec',120),('Result',65),('Damage',110),('Healing',110),('KB',55),('HK',55),('Deaths',60),('Honor',70),('Rating change',100),('Minutes played',110),('Objectives',220),('source',95),('quality',220),('recording_perspectives',240)]],on_open=lambda row:self.app.open_scoreboard(row['canonical_key']))
        table.pack(fill='both',expand=True,padx=10,pady=5)
        ttk.Button(dialog,text='Rank selected encounter',command=lambda:RankingWindow(self.app,table.selected()['canonical_key'],table.selected()) if table.selected() else None).pack(pady=5)
        def evidence():
            row=table.selected()
            if not row:return
            def work():
                return self.app.service.player_evidence(row['event_id'],row['player_key'])
            def show(records):
                child=tk.Toplevel(dialog);child.title('All source sightings and available fields');child.geometry('1000x600')
                text=tk.Text(child,wrap='word');scroll=ttk.Scrollbar(child,command=text.yview);scroll.pack(side='right',fill='y');text.configure(yscrollcommand=scroll.set);text.pack(fill='both',expand=True)
                text.insert('end',json.dumps(records,ensure_ascii=False,indent=2));text.configure(state='disabled')
            self.app.run_job('Reading every source revision for this encounter…',work,show)
        ttk.Button(dialog,text='All source sightings / fields / conflicts',command=evidence).pack(pady=3)
        def done(rows):
            if dialog.winfo_exists():table.set_rows(rows)
        self.app.run_job('Loading all player encounters…',lambda:self.app.service.player_history(player['player_key']),done)
        return dialog
    def unresolved(self):
        def done(rows):
            dialog=tk.Toplevel(self);dialog.title('Unresolved captured records');dialog.geometry('1000x600')
            text=tk.Text(dialog,wrap='word');scroll=ttk.Scrollbar(dialog,command=text.yview);scroll.pack(side='right',fill='y');text.configure(yscrollcommand=scroll.set);text.pack(fill='both',expand=True)
            text.insert('end',json.dumps(rows,ensure_ascii=False,indent=2));text.configure(state='disabled')
        def work():
            return self.app.service.unresolved_records()
        self.app.run_job('Reading unresolved records…',work,done)

    def destroy(self):
        if self.pending:self.after_cancel(self.pending)
        super().destroy()


class ArchiveStatusView(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app
        page_heading(self,'Archive Status','Automatic checks every 300 seconds · WoW writes SavedVariables on logout or /reload')
        bar=ttk.Frame(self);bar.pack(fill='x')
        ttk.Button(bar,text='Sync Now',command=app.refresh).pack(side='left')
        ttk.Button(bar,text='Refresh status',command=lambda:self.render(None)).pack(side='left',padx=8)
        self.next=ttk.Label(bar);self.next.pack(side='right')
        self.text=tk.Text(self,wrap='word',bg=palette(self)['FIELD'],fg=palette(self)['TEXT']);scroll=ttk.Scrollbar(self,command=self.text.yview);scroll.pack(side='right',fill='y');self.text.configure(yscrollcommand=scroll.set);self.text.pack(fill='both',expand=True,pady=10)
    def render(self,payload):
        schedule=getattr(self.app,'sync_schedule',None)
        if schedule:self.next.configure(text=f'Next check in {max(0,int(schedule.next_due-schedule.clock()))} seconds')
        def done(data):
            self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('end',json.dumps(data,ensure_ascii=False,indent=2));self.text.configure(state='disabled')
        self.app.run_job('Inspecting archive storage and integrity…',self.app.service.archive_status,done)

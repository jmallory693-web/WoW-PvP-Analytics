"""Rated career interface. All data/recovery work uses the application worker."""
import json
from datetime import datetime,timezone
import tkinter as tk
from tkinter import ttk,filedialog
from .widgets import Table,ScrollFrame,page_heading
from ..career_sources import BRACKETS


class RatingForm(tk.Toplevel):
    def __init__(self,view,record=None,previous=None):
        super().__init__(view.app.root);self.view=view;self.previous=previous;self.record=record or {};self.title('Rated PvP — manual observation / correction');self.geometry('990x710');self.minsize(850,600)
        shell=ttk.Frame(self,padding=12);shell.pack(fill='both',expand=True)
        bottom=ttk.Frame(shell);bottom.pack(side='bottom',fill='x')
        self.approved=tk.BooleanVar(value=False);ttk.Checkbutton(bottom,text='I approve this user-entered observation or correction.',variable=self.approved).pack(anchor='w')
        self.error=ttk.Label(bottom,wraplength=930);self.error.pack(fill='x',pady=4)
        self.save_button=ttk.Button(bottom,text='Save manual observation',command=self.save);self.save_button.pack(side='right')
        ttk.Button(bottom,text='Close',command=self.destroy).pack(side='left')
        scroll=ScrollFrame(shell);scroll.pack(fill='both',expand=True);body=scroll.body
        ttk.Label(body,text='Manual evidence remains separate from addon facts. Date/time needs an explicit UTC offset.\nA source citation can be user-attested; no external leaderboard has been fetched.',wraplength=900).grid(row=0,column=0,columnspan=2,sticky='w',pady=8)
        selected=view.character_info();defaults=dict(selected or {})|{'observed_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'source':'Manual'}|self.record
        fields=[('character','Character'),('realm','Realm'),('realm_certainty','Realm certainty'),('identity_context','Recording realm (uncertain identity only)'),('spec','Specialization'),('game_version','Game version / build (do not guess)'),('season','Season (explicit ID or name)'),('bracket','Rated bracket'),('rating','Personal rating'),('leaderboard_position','Optional leaderboard position'),('ranking_region','Ranking region'),('observed_at','Date/time observed (with UTC offset)'),('source','Source (manual / screenshot / official leaderboard)'),('source_reference','Source reference / URL / screenshot citation'),('notes','Notes'),('correction_reason','Reason for correction')]
        self.vars={}
        for n,(key,label) in enumerate(fields,1):
            ttk.Label(body,text=label).grid(row=n,column=0,sticky='w',pady=4,padx=3)
            v=tk.StringVar(value='' if defaults.get(key) is None else str(defaults.get(key,'')));self.vars[key]=v
            options={'bracket':BRACKETS,'realm_certainty':('observed','inferred','unknown'),'ranking_region':('','US','EU','KR','TW','CN')}.get(key)
            widget=ttk.Combobox(body,textvariable=v,values=options,state='readonly') if options else ttk.Entry(body,textvariable=v)
            widget.grid(row=n,column=1,sticky='ew',padx=5)
        body.columnconfigure(1,weight=1)
        self.attested=tk.BooleanVar(value=bool(defaults.get('ranking_verified_by_user')))
        ttk.Checkbutton(body,text='I verified the cited rank for this character, region, bracket, spec and season. (User attestation)',variable=self.attested).grid(row=len(fields)+1,column=0,columnspan=2,sticky='w',pady=10)
        self.protocol('WM_DELETE_WINDOW',self.destroy)

    def save(self):
        if not self.approved.get():self.error.configure(text='Explicit approval is required before saving.');return
        values={k:v.get() for k,v in self.vars.items()};reason=values.pop('correction_reason') or 'Manual rating observation'
        values.update(ranking_verified_by_user=self.attested.get(),own=self.record.get('own',(self.view.character_info() or {}).get('own',True)))
        if self.record and not self.record.get('manual'):values['linked_source_observation']=self.record.get('id')
        # Validate synchronously so invalid fields remain visible in the form.
        from ..career import validate_manual
        try:validate_manual(values)
        except (ValueError,TypeError,OverflowError) as exc:self.error.configure(text=str(exc));return
        self.save_button.configure(state='disabled')
        def done(result):
            self.view.load();self.destroy()
        def failed(exc):
            if self.winfo_exists():self.error.configure(text=str(exc));self.save_button.configure(state='normal')
        self.view.app.run_job('Saving append-only manual rated evidence…',lambda:self.view.app.service.rated_manual(values,self.previous,reason,True),done,failed)

    def destroy(self):
        super().destroy()
        self.vars.clear();self.approved=None;self.attested=None


class RatedChart(tk.Toplevel):
    def __init__(self,app,series):
        super().__init__(app.root);self.title('Rated rating progression');self.geometry('1060x690');self.minsize(800,550);self.figure=None;self.canvas=None
        bar=ttk.Frame(self,padding=10);bar.pack(fill='x')
        ttk.Button(bar,text='Export PNG…',command=self.export).pack(side='right')
        self.status=ttk.Label(bar,text='Observed values only; gaps are not imputed. Cohorts have separate axes.');self.status.pack(side='left')
        self.scroll=ScrollFrame(self);self.scroll.pack(fill='both',expand=True)
        try:
            from ..rated_charts import figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            self.figure=figure(series);self.canvas=FigureCanvasTkAgg(self.figure,master=self.scroll.body);widget=self.canvas.get_tk_widget();widget.configure(height=max(330,len(series)*280));widget.pack(fill='both',expand=True);self.canvas.draw()
            self.scroll.canvas.bind('<Configure>',self.resize,add='+')
        except Exception as exc:self.status.configure(text='Chart failed: '+str(exc))
        self.protocol('WM_DELETE_WINDOW',self.close)
    def resize(self,event):
        if self.figure and self.canvas:
            self.figure.set_size_inches(max(4,(event.width-25)/100),max(3.3,len(self.figure.axes)*2.8),forward=False);self.canvas.draw_idle()
    def export(self):
        if self.figure is None:self.status.configure(text='Export unavailable: no chart initialized');return
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.png',filetypes=[('PNG','*.png')])
        if not path:return
        try:
            from ..archive import safe_destination
            self.figure.savefig(safe_destination(path),dpi=150,facecolor=self.figure.get_facecolor());self.status.configure(text='PNG saved: '+path)
        except Exception as exc:self.status.configure(text='PNG export failed: '+str(exc))
    def close(self):
        self.destroy()
    def destroy(self):
        # Tk images and callbacks must be released on the UI thread even when
        # the parent is closed directly or cyclic GC runs in a worker later.
        canvas=self.canvas
        if canvas is not None:
            widget=canvas.get_tk_widget()
            for timer in ('_idle_draw_id','_event_loop_id'):
                ticket=getattr(canvas,timer,None)
                if ticket:widget.after_cancel(ticket);setattr(canvas,timer,None)
            widget.destroy();canvas._tkphoto=None;canvas.figure.set_canvas(None)
            self.canvas=None
        # Detaching Figure.canvas already breaks the Figure/canvas cycle.
        # Figure.clear() expects a live canvas and must not run after detach.
        self.figure=None
        super().destroy()


class RatedView(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.data=None;self.serial=0;self.target=None
        page_heading(self,'Rated PvP career','Personal rating, MMR and ladder position are separate. This screen uses its own filters; unknown dimensions are never guessed.')
        bar=ttk.Frame(self);bar.pack(fill='x');self.character=ttk.Combobox(bar,state='readonly',width=43);self.character.pack(side='left',fill='x',expand=True);self.character.bind('<<ComboboxSelected>>',lambda e:self.load(reset=True))
        self.others=tk.BooleanVar(value=False);ttk.Checkbutton(bar,text='Include other captured characters',variable=self.others,command=lambda:self.load(reset=True)).pack(side='left',padx=6)
        self.refresh_button=ttk.Button(bar,text='Refresh career',command=self.load);self.refresh_button.pack(side='right')
        filters=ttk.Frame(self);filters.pack(fill='x',pady=6);self.filters={}
        for key,label,width in [('season','Season',10),('bracket','Bracket',21),('spec','Spec',16),('start','From (UTC)',11),('end','To (UTC)',11)]:
            frame=ttk.Frame(filters);frame.pack(side='left',fill='x',expand=True,padx=(0,5));ttk.Label(frame,text=label).pack(anchor='w')
            w=ttk.Combobox(frame,state='readonly',width=width) if key in ('season','bracket','spec') else ttk.Entry(frame,width=width)
            if key in ('season','bracket','spec'):w.set('All')
            w.pack(fill='x');self.filters[key]=w
        ttk.Button(filters,text='Apply',command=self.load).pack(side='right',anchor='s')
        self.note=ttk.Label(self,wraplength=1020,style='Muted.TLabel');self.note.pack(fill='x',pady=4)
        footer=ttk.Frame(self);footer.pack(side='bottom',fill='x',pady=5);self.footer=footer
        self.add=ttk.Button(footer,text='Manual observation…',command=lambda:RatingForm(self));self.add.pack(side='left')
        ttk.Button(footer,text='Progression chart…',command=self.chart).pack(side='left',padx=5)
        ttk.Button(footer,text='Source / definitions',command=self.details).pack(side='left')
        ttk.Button(footer,text='Open linked match',command=self.open_match).pack(side='right')
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True)
        summary=ttk.Frame(self.tabs);observed=ttk.Frame(self.tabs);manual=ttk.Frame(self.tabs)
        self.tabs.add(summary,text='Career by season');self.tabs.add(observed,text='All rating observations');self.tabs.add(manual,text='Manual revisions')
        self.summary=Table(summary,[(k,label,w) for k,label,w in [('bracket','Bracket',180),('current','Latest known rating',150),('season_peak','Season recorded peak',165),('season','Season',80),('spec','Specialization',135),('game_version','Game version',115),('highest_recorded','Date-window peak',145),('first','First rating',95),('games','Rated games',105),('wins','Wins',65),('losses','Losses',65),('unknown_results','Unknown W/L',105),('gains','Gained points',105),('loss_points','Lost points',100),('delta_samples','Delta samples',110),('leaderboard','Ladder position',130),('rank_verification','Rank verification',265),('ranking_region','Rank region',100),('rank_source','Rank source',230),('rank_observed_at','Rank observed UTC',190),('latest_observed','Latest rating UTC',190),('conflicted_events','Conflicted events',125)]]);self.summary.pack(fill='both',expand=True)
        obsbar=ttk.Frame(observed);obsbar.pack(side='bottom',fill='x');ttk.Button(obsbar,text='New manual observation from selected evidence…',command=self.new_from_source).pack(side='left')
        self.observed=Table(observed,[(k,k,w) for k,w in [('observed_at',190),('bracket',170),('rating_before',110),('rating_after',110),('rating_change',115),('rating',100),('source',105),('season',70),('game_version',110),('spec',125),('mmr_before',110),('mmr_after',100),('result',60),('realm_certainty',110),('rating_semantics',340),('id',170)]]);self.observed.pack(fill='both',expand=True)
        manualbar=ttk.Frame(manual);manualbar.pack(side='bottom',fill='x');self.reverse_approval=tk.BooleanVar(value=False)
        ttk.Button(manualbar,text='Correct selected…',command=self.correct).pack(side='left')
        ttk.Checkbutton(manualbar,text='I approve reversal',variable=self.reverse_approval).pack(side='left',padx=5)
        ttk.Button(manualbar,text='Reverse latest selected',command=self.reverse).pack(side='right')
        self.history=Table(manual,[(k,k,w) for k,w in [('id',55),('action',80),('character',115),('realm',125),('rating',85),('bracket',170),('season',80),('reason',240),('created',190)]]);self.history.pack(fill='both',expand=True)
    def render(self,payload):self.load()
    def character_info(self):
        if not self.data or self.character.current()<0:return None
        chars=self.data['characters'];index=self.character.current()
        return chars[index] if index<len(chars) else None
    def open_character(self,name=None,realm=None,player=None,others=False):
        self.target=(name,realm,player);self.others.set(others);self.load(reset=True)
    def load(self,reset=False):
        self.serial+=1;serial=self.serial;selected=self.character_info();player=selected['player_key'] if selected else None
        target=self.target;self.target=None
        filters={k:w.get().strip() for k,w in self.filters.items()};filters={k:v for k,v in filters.items() if v and v!='All'}
        if reset:
            for k,w in self.filters.items():
                if k in ('season','bracket','spec'):w.set('All')
                else:w.delete(0,'end')
            filters={}
        others=self.others.get();self.note.configure(text='Reading permanent source observations…')
        def work():
            data=self.app.service.rated_career(player=player,include_others=others,**filters)
            if target:
                name,realm,wanted=target
                choice=next((r for r in data['characters'] if r['player_key']==wanted or wanted is None and r['character']==name and r['realm']==realm and r['realm_certainty']=='observed'),None)
                if choice:data=self.app.service.rated_career(player=choice['player_key'],include_others=others,**filters)
                elif name:
                    from ..career_sources import player_id
                    certainty='observed' if realm else 'unknown';pid=player_id(name,realm or '',certainty)
                    data=self.app.service.rated_career(player=pid,include_others=others,**filters)
                    data['characters'].append({'player_key':pid,'character':name,'realm':realm or '', 'realm_certainty':certainty,'identity_context':'','own':True})
            return data
        def done(data):
            if serial!=self.serial or not self.winfo_exists():return
            self.data=data;self.character.configure(values=[f"{c['character']}-{c['realm']} · {c['realm_certainty']}" for c in data['characters']])
            index=next((i for i,c in enumerate(data['characters']) if c['player_key']==data['player']),None)
            if index is not None:self.character.current(index)
            for k in ('season','bracket','spec'):self.filters[k].configure(values=['All']+data['choices'][k])
            self.summary.set_rows(data['summaries']);self.observed.set_rows(data['observations'])
            if data['observations'] and not data['summaries']:self.tabs.select(1)
            self.history.set_rows([r|{k:r['data'].get(k) for k in ('character','realm','rating','bracket','season')} for r in data['manual_history'] if r['data'].get('player_key')==data['player']])
            self.note.configure(text=f"{len(data['observations'])} observations · {data['unclassified']} lack cohort metadata (see All rating observations). Peaks are recorded samples, not official season best. Leaderboard provider: Not Available. Manual citations are labeled.")
        def failed(exc):
            if self.winfo_exists():self.note.configure(text='Career failed: '+str(exc))
        self.app.run_job('Loading rated career…',work,done,failed)
    def new_from_source(self):
        selected=self.observed.selected()
        if selected:RatingForm(self,selected)
    def chart(self):
        if self.data:RatedChart(self.app,self.data['series'])
    def details(self):
        selected=self.observed.selected();payload={'definitions':self.data['definitions'] if self.data else {},'selected':selected}
        def show(evidence):
            dialog=tk.Toplevel(self);dialog.title('Rated source evidence and definitions');dialog.geometry('1000x650')
            text=tk.Text(dialog,wrap='word');s=ttk.Scrollbar(dialog,command=text.yview);s.pack(side='right',fill='y');text.configure(yscrollcommand=s.set);text.pack(fill='both',expand=True);text.insert('end',json.dumps(payload|{'evidence':evidence},ensure_ascii=False,indent=2));text.configure(state='disabled')
        if selected and not selected.get('manual'):self.app.run_job('Reading original rated evidence…',lambda:self.app.service.rated_evidence(selected['id']),show)
        else:show([])
    def open_match(self):
        r=self.observed.selected()
        if r and (r.get('canonical_match_key') or r.get('match_key')):self.app.open_scoreboard(r.get('canonical_match_key') or r['match_key'])
        else:self.note.configure(text='Select an addon observation with a match link. A standalone manual rating is not a match.')
    def correct(self):
        r=self.history.selected()
        if r:RatingForm(self,r['data']|{'manual':True},r['id'])
    def reverse(self):
        r=self.history.selected()
        if not r:return
        if not self.reverse_approval.get():self.note.configure(text='Explicit reversal approval is required.');return
        def done(result):self.reverse_approval.set(False);self.load()
        self.app.run_job('Appending manual reversal…',lambda:self.app.service.rated_reverse(r['id'],True),done,lambda e:self.note.configure(text=str(e)))

    def destroy(self):
        self.serial+=1
        super().destroy()
        self.others=None;self.reverse_approval=None

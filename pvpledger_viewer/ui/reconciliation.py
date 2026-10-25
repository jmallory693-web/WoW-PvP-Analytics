"""Review first; only the explicit approval/commit action persists Excel data."""
import json
import tkinter as tk
from tkinter import ttk,filedialog
from .widgets import Table
from ..reconcile import EXACT,PROBABLE,AMBIGUOUS,MISSING
from ..identity import character_key


class ReconciliationWindow(tk.Toplevel):
    def __init__(self,app,path=None):
        super().__init__(app.root);self.app=app;self.title('Excel match log reconciliation');self.geometry('1260x780');self.minsize(1100,650)
        self.report=None;self.staged={};self.current=None;self.candidate=None;self.busy=False;self.serial=0
        self.path=tk.StringVar(value=path or '');self.zone=tk.StringVar(value=app.config['source_timezone'])
        body=ttk.Frame(self,padding=12);body.pack(fill='both',expand=True)
        toolbar=ttk.Frame(body);toolbar.pack(fill='x')
        ttk.Button(toolbar,text='Choose workbook…',command=self.choose).pack(side='left')
        ttk.Entry(toolbar,textvariable=self.path).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Label(toolbar,text='Excel timezone').pack(side='left');ttk.Entry(toolbar,textvariable=self.zone,width=22).pack(side='left',padx=5)
        ttk.Button(toolbar,text='Audit (read only)',command=self.audit).pack(side='left')
        ttk.Button(toolbar,text='Export report…',command=self.export_report).pack(side='left',padx=6)
        self.status=ttk.Label(body,text='Choose a workbook. Audit does not write archive records.',wraplength=1200);self.status.pack(fill='x',pady=6)
        bottom=ttk.Frame(body);bottom.pack(side='bottom',fill='x',pady=(8,0));self.approval=tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom,text='I approve only the staged decisions and selected supplemental fields. Original addon values and identity mappings stay unchanged.',variable=self.approval,command=self.update_commit).pack(anchor='w')
        self.commit_button=ttk.Button(bottom,text='Commit approved decisions',command=self.commit,state='disabled');self.commit_button.pack(side='right',pady=4)
        self.staged_label=ttk.Label(bottom,text='0 staged decisions');self.staged_label.pack(side='left')
        ttk.Button(bottom,text='Clear staged',command=self.clear_staged).pack(side='left',padx=6)
        self.tabs=ttk.Notebook(body);self.tabs.pack(fill='both',expand=True)
        review=ttk.Frame(self.tabs);self.tabs.add(review,text='Reconcile matches')
        filters=ttk.Frame(review);filters.pack(fill='x',pady=4)
        self.category=ttk.Combobox(filters,values=['All',EXACT,PROBABLE,AMBIGUOUS,MISSING,'FIELD CONFLICT','SPREADSHEET-ONLY DATA'],state='readonly',width=26);self.category.set('All');self.category.pack(side='left');self.category.bind('<<ComboboxSelected>>',lambda e:self.render_rows())
        self.show_all=tk.BooleanVar(value=False);ttk.Checkbutton(filters,text='Show all same-character archive records for manual selection',variable=self.show_all,command=self.select_row).pack(side='left',padx=8)
        panes=ttk.Panedwindow(review,orient='vertical');panes.pack(fill='both',expand=True)
        top=ttk.Panedwindow(panes,orient='horizontal');panes.add(top,weight=1)
        left=ttk.Frame(top);right=ttk.Frame(top);top.add(left,weight=1);top.add(right,weight=1)
        self.rows=Table(left,[(k,k,w) for k,w in [('sheet',145),('row',45),('character',110),('classification',145),('field_conflict',90),('Staged',100)]],height=6);self.rows.pack(fill='both',expand=True)
        self.rows.tree.bind('<<TreeviewSelect>>',lambda e:self.select_row())
        self.candidates=Table(right,[(k,k,w) for k,w in [('Record',260),('Source',120),('Date',105),('Time',70),('Map',150),('Result',60)]],height=6);self.candidates.pack(fill='both',expand=True)
        self.candidates.tree.bind('<<TreeviewSelect>>',lambda e:self.select_candidate())
        detail=ttk.Frame(panes);panes.add(detail,weight=1)
        controls=ttk.Frame(detail);controls.pack(side='bottom',fill='x',pady=4)
        self.reason=tk.StringVar();self.realm=tk.StringVar();self.include_roster=tk.BooleanVar(value=False)
        ttk.Label(controls,text='Reason').grid(row=0,column=0,sticky='w');ttk.Entry(controls,textvariable=self.reason).grid(row=0,column=1,columnspan=3,sticky='ew',padx=4)
        ttk.Label(controls,text='Owner realm').grid(row=0,column=4);ttk.Entry(controls,textvariable=self.realm,width=17).grid(row=0,column=5,padx=4)
        ttk.Checkbutton(controls,text='Include workbook roster (incomplete / manually transcribed)',variable=self.include_roster).grid(row=1,column=0,columnspan=3,sticky='w')
        ttk.Button(controls,text='Stage link',command=lambda:self.stage('link')).grid(row=1,column=3,padx=4)
        ttk.Button(controls,text='Stage separate historical event',command=lambda:self.stage('historical')).grid(row=1,column=4,padx=4)
        ttk.Button(controls,text='Stage reject',command=lambda:self.stage('reject')).grid(row=1,column=5,padx=4)
        controls.columnconfigure(1,weight=1)
        fields=ttk.Panedwindow(detail,orient='horizontal');fields.pack(fill='both',expand=True)
        source=ttk.Frame(fields);approved=ttk.Frame(fields);fields.add(source,weight=2);fields.add(approved,weight=1)
        ttk.Label(source,text='Original row and selected candidate: source values, conflicts, units and cell references').pack(anchor='w')
        self.details=tk.Text(source,wrap='word',height=6);scroll=ttk.Scrollbar(source,command=self.details.yview);scroll.pack(side='right',fill='y');self.details.configure(yscrollcommand=scroll.set);self.details.pack(fill='both',expand=True)
        ttk.Label(approved,text='Approve fields (Ctrl-click). Conflicts stay separate.').pack(anchor='w')
        self.field_list=tk.Listbox(approved,selectmode='extended',exportselection=False,height=6);scroll=ttk.Scrollbar(approved,command=self.field_list.yview);scroll.pack(side='right',fill='y');self.field_list.configure(yscrollcommand=scroll.set);self.field_list.pack(fill='both',expand=True);self.field_names=[]
        context=ttk.Frame(self.tabs);self.tabs.add(context,text='All workbook sheets and notes')
        ttk.Label(context,text='Original evidence from every sheet is retained with any approved import. Known-player mappings here are evidence only; they never edit People.').pack(anchor='w')
        self.sheet_choice=ttk.Combobox(context,state='readonly');self.sheet_choice.pack(fill='x',pady=4);self.sheet_choice.bind('<<ComboboxSelected>>',lambda e:self.show_sheet())
        self.context=tk.Text(context,wrap='word');scroll=ttk.Scrollbar(context,command=self.context.yview);scroll.pack(side='right',fill='y');self.context.configure(yscrollcommand=scroll.set);self.context.pack(fill='both',expand=True)
        historical=ttk.Frame(self.tabs);self.tabs.add(historical,text='Imported decisions and reversals')
        history_bar=ttk.Frame(historical);history_bar.pack(side='bottom',fill='x')
        ttk.Button(history_bar,text='Refresh history',command=self.load_history).pack(side='left')
        ttk.Button(history_bar,text='Reverse selected (approval checkbox required)',command=self.reverse).pack(side='right')
        self.history=Table(historical,[(k,k,w) for k,w in [('id',50),('sheet',150),('row_number',60),('action',100),('classification',145),('reason',270),('created',220)]],height=8);self.history.pack(fill='both',expand=True)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.load_history()
        if path:self.after(50,self.audit)

    def close(self):
        if self.busy:self.status.configure(text='A background operation is running. Wait for it to finish before closing.');return
        self.destroy()

    def destroy(self):
        super().destroy()
        # Release Tcl-backed variables on the UI thread, even if queued worker
        # closures or Python cycles retain the destroyed window for longer.
        for name in ('path','zone','approval','show_all','reason','realm','include_roster'):
            setattr(self,name,None)
        self.report=None;self.staged.clear()

    def choose(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self,title='Select Excel match log (original remains unchanged)',filetypes=[('Excel workbook','*.xlsx')])
        if path:self.path.set(path);self.audit()

    def audit(self):
        if self.busy or not self.path.get():return
        path,zone=self.path.get(),self.zone.get();self.busy=True;self.serial+=1;serial=self.serial
        self.status.configure(text='Reading every sheet and comparing retained addon evidence. No import is being committed.');self.update_commit()
        def done(report):
            if not self.winfo_exists() or serial!=self.serial:return
            self.busy=False;self.report=report;self.staged.clear();self.approval.set(False)
            self.status.configure(text=' · '.join(f'{k}: {v}' for k,v in report['counts'].items() if k in (EXACT,PROBABLE,AMBIGUOUS,MISSING,'FIELD CONFLICT','ARCHIVE ONLY')))
            self.sheet_choice.configure(values=[s['name'] for s in report['workbook']['sheets']]);self.sheet_choice.current(0);self.show_sheet();self.render_rows();self.update_commit()
        self.app.run_job('Auditing Excel without archive writes…',lambda:self.app.service.reconcile_excel(path,zone),done,self.failed)

    def failed(self,error):
        self.busy=False
        if self.winfo_exists():self.status.configure(text='Operation failed: '+str(error));self.update_commit()

    def render_rows(self):
        if not self.report:return
        category=self.category.get()
        rows=[r|{'Staged':self.staged.get(r['row_id'],{}).get('action','')} for r in self.report['results'] if category=='All' or r['classification']==category or category=='FIELD CONFLICT' and r['field_conflict'] or category=='SPREADSHEET-ONLY DATA' and r['spreadsheet_only_fields']]
        self.rows.set_rows(rows);self.current=None;self.candidate=None

    def select_row(self):
        if not self.report:return
        selected=self.rows.selected()
        if not selected:return
        self.current=selected;self.candidate=None;row=next(r for r in self.report['workbook']['matches'] if r['id']==selected['row_id'])
        self.realm.set(row['normalized'].get('Realm') or '');self.reason.set('');self.include_roster.set(False)
        candidates=selected['candidates']
        if self.show_all.get():
            candidates=[{'key':c['key'],'match':c['match'],'source':c['match'].get('Source'),'fields':[],'manual_selection':True} for c in self.report['archive_catalogue'] if character_key(c['match']['Character'])[0]==character_key(row['owner'] or '')[0]]
        self.candidates.set_rows([c|{'Record':' / '.join(str(x) for x in c['key']),'Source':c['source'],**{k:c['match'].get(k) for k in ('Date','Time','Map','Result')}} for c in candidates])
        self.show_fields(row,None)

    def select_candidate(self):
        if not self.current:return
        self.candidate=self.candidates.selected()
        row=next(r for r in self.report['workbook']['matches'] if r['id']==self.current['row_id']);self.show_fields(row,self.candidate)

    def show_fields(self,row,candidate):
        self.details.delete('1.0','end');self.details.insert('end',json.dumps({'original_spreadsheet_row':row,'candidate':candidate},ensure_ascii=False,indent=2))
        statuses={f['field']:f['status'] for f in candidate.get('fields',[])} if candidate else {}
        self.field_names=list(row['fields']);self.field_list.delete(0,'end')
        for label in self.field_names:self.field_list.insert('end',label+' — '+statuses.get(label,'original spreadsheet evidence'))
        # Approval is explicit: no cells are selected automatically.

    def stage(self,action):
        if self.busy or not self.report or not self.current:return
        if action=='link' and not self.candidate:self.status.configure(text='Select an archived candidate to inspect before staging a link.');return
        selection={'row_id':self.current['row_id'],'action':action,'target':self.candidate['key'] if action=='link' else None,
            'fields':[self.field_names[i] for i in self.field_list.curselection()],'include_roster':self.include_roster.get(),
            'realm':self.realm.get().strip(),'reason':self.reason.get()}
        self.staged[self.current['row_id']]=selection;self.status.configure(text='Decision staged only. Nothing has been imported. Review fields, then use the approval checkbox and Commit.');self.update_commit()

    def update_commit(self):
        self.staged_label.configure(text=f'{len(self.staged)} staged decisions')
        self.commit_button.configure(state='normal' if self.approval.get() and self.staged and not self.busy else 'disabled')

    def clear_staged(self):self.staged.clear();self.approval.set(False);self.update_commit()

    def commit(self):
        if not self.approval.get() or not self.staged or self.busy:self.status.configure(text='Explicit approval and staged decisions are required.');return
        report=self.report;choices=list(self.staged.values());self.busy=True;self.update_commit()
        def done(result):
            self.busy=False
            if not self.winfo_exists():return
            self.clear_staged();self.status.configure(text=f"Committed {result['decisions_added']} reviewed decisions. Original addon records and mappings remain unchanged. Run Audit again before staging more.")
            self.report=None;self.rows.set_rows([]);self.candidates.set_rows([]);self.load_history();self.app.reload('Excel supplemental decisions applied; original addon records preserved.')
        self.app.run_job('Committing only explicitly approved Excel evidence…',lambda:self.app.service.commit_excel(report,choices,approved=True),done,self.failed)

    def show_sheet(self):
        if not self.report:return
        sheet=next((s for s in self.report['workbook']['sheets'] if s['name']==self.sheet_choice.get()),None)
        self.context.delete('1.0','end');self.context.insert('end',json.dumps(sheet,ensure_ascii=False,indent=2))

    def export_report(self):
        if not self.report or self.busy:return
        destination=filedialog.askdirectory(parent=self,title='Save reconciliation report and all field comparisons')
        if not destination:return
        report=self.report;self.app.run_job('Exporting read-only reconciliation report…',lambda:self.app.service.export_reconciliation(report,destination),lambda p:self.status.configure(text='Report saved: '+p),self.failed)

    def load_history(self):
        def done(rows):
            if self.winfo_exists():self.history.set_rows(rows)
        self.app.run_job('Reading supplemental decision history…',self.app.service.excel_history,done,self.failed)

    def reverse(self):
        selected=self.history.selected()
        if not selected:return
        if not self.approval.get():self.status.configure(text='Select the approval checkbox before reversing this supplemental decision.');return
        self.busy=True;self.update_commit()
        def done(result):
            self.busy=False;self.approval.set(False);self.update_commit();self.status.configure(text='Supplemental decision reversed. Historical evidence retained; addon records untouched.');self.load_history();self.app.reload()
        self.app.run_job('Reversing only supplemental projections…',lambda:self.app.service.reverse_excel(selected['row_id'],approved=True),done,self.failed)

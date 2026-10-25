import queue
import threading
import tkinter as tk
from tkinter import ttk,filedialog


class AIDumpDialog(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app.root);self.app=app;self.title('Complete AI Dump');self.geometry('800x610')
        body=ttk.Frame(self,padding=20);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Complete AI Dump',style='Heading.TLabel').pack(anchor='w')
        ttk.Label(body,text='One file. No upload. Full Archive needs no player selection.\nFull source context includes original snapshots and may contain out-of-filter records.',wraplength=740).pack(fill='x',pady=10)
        self.scope=ttk.Combobox(body,values=['Full Archive','My Characters','Individual Character','Selected Players','Current Filters'],state='readonly');self.scope.set('Full Archive');self.scope.pack(fill='x')
        self.format=ttk.Combobox(body,values=['Compressed JSON (.json.gz)','JSON (.json)'],state='readonly');self.format.current(0);self.format.pack(fill='x',pady=8)
        search=ttk.Frame(body);search.pack(fill='x')
        self.query=ttk.Entry(search);self.query.pack(side='left',fill='x',expand=True)
        ttk.Button(search,text='Find players',command=self.search).pack(side='right')
        ttk.Label(body,text='Optional: search and Ctrl-click participants for filtered scopes. Full Archive ignores this list.').pack(anchor='w',pady=4)
        self.players=tk.Listbox(body,height=8,selectmode='extended',exportselection=False,bg='#0e1928',fg='#e7edf5');self.players.pack(fill='both',expand=True)
        self.entries=[];self.stop=threading.Event();self.messages=queue.Queue();self.busy=False
        self.cancel_event=self.stop
        self.status=ttk.Label(body,wraplength=740);self.status.pack(fill='x',pady=10)
        buttons=ttk.Frame(body);buttons.pack(fill='x')
        self.save=ttk.Button(buttons,text='Export one file…',command=self.export);self.save.pack(side='right')
        ttk.Button(buttons,text='Cancel export',command=self.stop.set).pack(side='left')
        self.protocol('WM_DELETE_WINDOW',self.close);self.after(100,self.poll)
    def search(self):
        query=self.query.get()
        def done(data):
            if not self.winfo_exists():return
            self.entries=data['rows'];self.players.delete(0,'end')
            for r in self.entries:self.players.insert('end',r['Player']+'-'+r['Realm']+' · '+r['Realm certainty'])
            self.status.configure(text=f"Showing {len(self.entries)} of {data['total']} matches. Narrow the search if needed.")
        self.app.run_job('Searching export participants…',lambda:self.app.service.players(query),done)
    def poll(self):
        if not self.winfo_exists():return
        while not self.messages.empty():self.status.configure(text=self.messages.get_nowait())
        self.after(100,self.poll)
    def close(self):
        if self.busy:self.stop.set();self.status.configure(text='Cancelling safely; waiting for the worker…')
        else:self.destroy()
    def export(self):
        selected=[self.entries[i] for i in self.players.curselection()];scope=self.scope.get()
        if scope in ('Individual Character','Selected Players') and not selected:
            self.status.configure(text='Search and select the character/player first.');return
        if scope=='Individual Character' and len(selected)!=1:
            self.status.configure(text='Select exactly one character.');return
        compressed=self.format.current()==0
        path=filedialog.asksaveasfilename(parent=self,initialdir=self.app.config['export_dir'] or None,initialfile='WoWApp-archive.json.gz' if compressed else 'WoWApp-archive.json',defaultextension='.json.gz' if compressed else '.json',filetypes=[('Compressed JSON','*.json.gz'),('JSON','*.json')])
        if not path:return
        self.stop.clear();self.busy=True;self.save.configure(state='disabled');self.status.configure(text='Preparing consistent archive export…')
        filters=self.app.filters;service=self.app.service
        ids=[r['player_key'] for r in selected]
        def work():
            return service.complete_export(path,scope,filters,ids,selected[0]['Player']+'-'+selected[0]['Realm'] if selected else None,self.messages.put,self.stop.is_set)
        def done(result):
            self.busy=False
            if self.winfo_exists():self.save.configure(state='normal');self.status.configure(text=f"Validated one-file export: {result['path']} ({result['bytes']:,} bytes)")
        def failed(error):
            self.busy=False
            if self.winfo_exists():self.save.configure(state='normal');self.status.configure(text='Export failed or cancelled: '+str(error))
        self.app.run_job('Creating Complete AI Dump…',work,done,failed)

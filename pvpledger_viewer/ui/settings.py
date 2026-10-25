import tkinter as tk
from tkinter import ttk, filedialog
from .theme import BG


class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.master_app = app
        self.title('PvP Ledger — Settings'); self.configure(bg=BG)
        self.transient(app.root); self.grab_set(); self.resizable(False, False)
        body = ttk.Frame(self, padding=25); body.pack(fill='both', expand=True)
        ttk.Label(body, text='Settings', style='Title.TLabel').grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 18))
        self.paths = {}
        for index, (key, label) in enumerate([('wow_root', 'World of Warcraft installation'), ('export_dir', 'Default export folder')], 1):
            ttk.Label(body, text=label).grid(row=index * 2 - 1, column=0, columnspan=3, sticky='w', pady=(9, 4))
            variable = tk.StringVar(value=app.config[key]); self.paths[key] = variable
            ttk.Entry(body, textvariable=variable, width=61).grid(row=index * 2, column=0, columnspan=2, sticky='ew')
            def browse(v=variable, title=label):
                chosen = filedialog.askdirectory(parent=self, title=title, initialdir=v.get() or None)
                if chosen:
                    v.set(chosen)
            ttk.Button(body, text='Browse…', command=browse).grid(row=index * 2, column=2, padx=(10, 0))
        ttk.Label(body, text='Default Copy for Claude match count').grid(row=5, column=0, sticky='w', pady=(18, 5))
        self.limit = tk.StringVar(value=str(app.config['report_limit']))
        ttk.Spinbox(body, textvariable=self.limit, from_=1, to=100000, width=8).grid(row=5, column=1, sticky='e')
        ttk.Label(body, text='Recording PC timezone (IANA)').grid(row=6, column=0, sticky='w', pady=(12, 5))
        self.zone = tk.StringVar(value=app.config['source_timezone'])
        ttk.Entry(body, textvariable=self.zone, width=30).grid(row=6, column=1, columnspan=2, sticky='e')
        ttk.Label(body, text='Archive: ' + str(app.service.home / 'archive.sqlite'), style='Muted.TLabel', wraplength=580).grid(row=7, column=0, columnspan=3, sticky='w', pady=(18, 8))
        ttk.Label(body, text='WoW files are read-only. New matches appear after logout or /reload.\nBoth addons are scanned at launch and Refresh. Set the timezone used by the recording PC.', style='Muted.TLabel', wraplength=580).grid(row=8, column=0, columnspan=3, sticky='w', pady=(0, 12))
        self.enabled = tk.BooleanVar(value=app.config['sync_enabled'])
        self.interval = tk.StringVar(value=str(app.config['sync_interval']))
        ttk.Checkbutton(body,text='Automatic synchronization',variable=self.enabled).grid(row=12,column=0,sticky='w')
        ttk.Entry(body,textvariable=self.interval,width=8).grid(row=12,column=1,sticky='e')
        ttk.Label(body,text='Interval (seconds, minimum 30)').grid(row=13,column=0,sticky='w')
        self.error = ttk.Label(body, foreground='#f28b94', wraplength=580)
        self.error.grid(row=9, column=0, columnspan=3, sticky='w')
        def save():
            try:
                count = int(self.limit.get())
                if count < 1:
                    raise ValueError('Match count must be positive')
                config = app.config | {key: value.get().strip() for key, value in self.paths.items()} | {'report_limit': count, 'source_timezone': self.zone.get().strip(), 'sync_enabled':self.enabled.get(), 'sync_interval':int(self.interval.get())}
                if hasattr(self,'selected_sources'):
                    config.update(source_locations=self.selected_sources,source_selection_explicit=True)
                elif config['wow_root'] != app.config['wow_root']:
                    config.update(source_locations=[],source_selection_explicit=False)
                from ..settings import validate_settings
                validate_settings(config)
                from pathlib import Path
                if config['wow_root'] and not Path(config['wow_root']).is_dir():
                    raise ValueError('The selected WoW folder does not exist')
            except ValueError as exc:
                self.error.configure(text=str(exc)); return
            button.configure(state='disabled')
            def done(saved):
                app.config = saved
                app.sync_schedule.interval = saved['sync_interval']
                app.sync_schedule.next_due = app.sync_schedule.clock() + saved['sync_interval']
                self.destroy()
                if saved['wow_root']:
                    app.refresh()
                else:
                    app.reload('Settings saved.')
            def failed(exc):
                if self.winfo_exists():
                    self.error.configure(text=str(exc)); button.configure(state='normal')
            def work():
                if config['export_dir']:
                    app.service._guard_export(config['export_dir'], config['wow_root'])
                return app.settings.save(config)
            app.run_job('Saving settings…', work, done, failed)
        button = ttk.Button(body, text='Save settings', style='Accent.TButton', command=save)
        button.grid(row=10, column=2, sticky='e', pady=(15, 0))
        ttk.Button(body, text='Cancel', command=self.destroy).grid(row=10, column=0, sticky='w', pady=(15, 0))
        ttk.Button(body, text='Copy / change archive location…', command=self.relocate).grid(row=11, column=0, columnspan=3, sticky='w', pady=8)
        ttk.Button(body, text='Select account / character source files…', command=self.select_sources).grid(row=14, column=0, columnspan=3, sticky='w', pady=8)
        self.bind('<Escape>', lambda e: self.destroy())
        self.after_idle(self.focus_set)

    def select_sources(self):
        from ..setup import locations
        window=tk.Toplevel(self);window.title('SavedVariables source selection');window.geometry('900x420')
        frame=ttk.Frame(window,padding=15);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Select files from the WoW folder entered in Settings. Ctrl-click multiple. No selection explicitly disables all sources.').pack(anchor='w')
        box=tk.Listbox(frame,selectmode='extended',exportselection=False);box.pack(fill='both',expand=True,pady=10)
        note=ttk.Label(frame,wraplength=850);note.pack(fill='x')
        found=[]
        try:
            found=locations(self.paths['wow_root'].get())
            for i,path in enumerate(found):
                from .setup import SetupDialog
                box.insert('end',SetupDialog.source_label(path))
                if str(path) in self.master_app.config['source_locations']:box.selection_set(i)
            if not found:note.configure(text='No addon files found. Browse to the correct WoW installation or import a file manually.')
        except (OSError,ValueError) as exc:note.configure(text=str(exc))
        def apply():
            self.selected_sources=[str(found[i]) for i in box.curselection()]
            window.destroy()
        ttk.Button(frame,text='Use selection (then Save settings)',command=apply).pack(anchor='e')

    def relocate(self):
        destination = filedialog.askdirectory(parent=self, title='Choose an empty destination; original archive is retained')
        if not destination:
            return
        def work():
            from ..profile import relocate
            from ..sync import home_lock
            with home_lock(self.master_app.service.home):
                return relocate(self.master_app.service.home, destination)
        app = self.master_app
        def done(path):
            from ..service import DesktopService
            from ..settings import SettingsStore
            app.service = DesktopService(path)
            app.settings = SettingsStore(app.service.home / 'settings.json')
            app.generation += 1
            if not app.explicit_home:
                from ..archive import set_default_home
                set_default_home(path)
            self.destroy();app.reload('Verified archive copy selected. Original data remains at its previous location.')
        app.run_job('Copying and verifying archive…', work, done, lambda exc:self.error.configure(text=str(exc)))

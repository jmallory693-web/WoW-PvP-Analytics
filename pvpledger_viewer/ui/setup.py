"""Optional, local-only first-run setup; never applied to an existing profile."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog
from .. import setup
from .widgets import ScrollFrame


class SetupDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root); self.app = app
        self.title('Welcome — local profile setup'); self.transient(app.root)
        self.geometry('900x600'); self.minsize(760,560); self.grab_set()
        self.variables = {}
        for key, value in {'display_name':'', 'wow_root':'', 'home':str(app.service.home), 'zone':'UTC',
                           'interval':'300', 'character':'', 'realm':'', 'friend':''}.items():
            self.variables[key] = tk.StringVar(value=value)
        self.sync = tk.BooleanVar(value=True); self.do_import = tk.BooleanVar(value=False)
        self.own = []; self.friends = []; self.paths = []; self.source_files = []
        footer = ttk.Frame(self,padding=12); footer.pack(side='bottom',fill='x')
        self.error = ttk.Label(footer,wraplength=650,foreground='#f28b94'); self.error.pack(fill='x')
        ttk.Button(footer,text='Start',style='Accent.TButton',command=self.finish).pack(side='right')
        ttk.Button(footer,text='Skip optional setup',command=self.skip).pack(side='left')
        book = ttk.Notebook(self); book.pack(fill='both',expand=True,padx=16,pady=12)
        source = ttk.Frame(book,padding=16); people_page = ttk.Frame(book,padding=16)
        self.people_scroll = ScrollFrame(people_page)
        self.people_scroll.pack(fill='both',expand=True)
        people = self.people_scroll.body
        storage = ttk.Frame(book,padding=16)
        self.book = book
        book.add(source,text='1. Addon sources'); book.add(people_page,text='2. My characters and friends'); book.add(storage,text='3. Private storage')
        ttk.Label(source,text='No name, email, online account, or upload is required. All setup fields are optional.',wraplength=790).pack(anchor='w',pady=(0,12))
        self.entry(source,'Optional display name','display_name')
        self.entry(source,'WoW installation or SavedVariables directory','wow_root',lambda:self.browse('wow_root'))
        row=ttk.Frame(source);row.pack(fill='x',pady=7)
        ttk.Button(row,text='Discover installations',command=self.discover_install).pack(side='left')
        ttk.Button(row,text='Find addon files',command=self.find).pack(side='left',padx=8)
        ttk.Button(row,text='Add file…',command=self.add_file).pack(side='left')
        ttk.Label(source,text='Select the account/character files to synchronize (Ctrl-click for multiple).').pack(anchor='w')
        frame=ttk.Frame(source);frame.pack(fill='both',expand=True)
        self.sources=tk.Listbox(frame,selectmode='extended',exportselection=False,height=6)
        self.sources.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(frame,command=self.sources.yview);scroll.pack(side='right',fill='y');self.sources.configure(yscrollcommand=scroll.set)
        self.source_note=ttk.Label(source,text='Choose a folder, discover files, or start empty.',wraplength=790);self.source_note.pack(fill='x',pady=8)
        ttk.Button(source,text='Use selected sources and list characters',command=self.choose_sources).pack(anchor='w')
        ttk.Label(people,text='Select discovered characters or enter exact character + realm below. Account-wide files may need manual identification.',wraplength=780).pack(anchor='w')
        self.characters=ttk.Combobox(people,state='readonly',width=60);self.characters.pack(fill='x',pady=8)
        ttk.Button(people,text='Add selected character to Me',command=self.add_discovered).pack(anchor='w')
        self.entry(people,'Character','character');self.entry(people,'Realm','realm');self.entry(people,'Friend label (optional; blank assigns to Me)','friend')
        ttk.Button(people,text='Add association',command=self.add_identity).pack(anchor='w',pady=5)
        self.associations=tk.Listbox(people,height=4,exportselection=False);self.associations.pack(fill='both',expand=True)
        ttk.Button(people,text='Remove selected association',command=self.remove_identity).pack(anchor='w',pady=4)
        self.entry(storage,'Private archive folder (outside the application and WoW)','home',lambda:self.browse('home'))
        self.entry(storage,'Recording PC timezone (IANA; choose explicitly if not UTC)','zone')
        ttk.Checkbutton(storage,text='Enable automatic archival synchronization',variable=self.sync).pack(anchor='w',pady=12)
        self.entry(storage,'Synchronization interval in seconds (default 300)','interval')
        ttk.Checkbutton(storage,text='Import selected addon history on Start (otherwise start empty)',variable=self.do_import).pack(anchor='w',pady=14)
        ttk.Label(storage,text='Existing profiles are never replaced by this setup. Settings and Edit people remain available later. Source addon files are read-only.',wraplength=770).pack(anchor='w',pady=12)
        self.protocol('WM_DELETE_WINDOW',self.skip)

    def entry(self,parent,label,key,browse=None):
        ttk.Label(parent,text=label).pack(anchor='w',pady=(7,2))
        row=ttk.Frame(parent);row.pack(fill='x')
        ttk.Entry(row,textvariable=self.variables[key]).pack(side='left',fill='x',expand=True)
        if browse:ttk.Button(row,text='Browse…',command=browse).pack(side='right',padx=(8,0))

    def browse(self,key):
        value=filedialog.askdirectory(parent=self,title='Choose folder')
        if value:self.variables[key].set(value)

    def discover_install(self):
        candidates=setup.installation_candidates()
        if candidates:self.variables['wow_root'].set(str(candidates[0]));self.find()
        else:self.source_note.configure(text='No standard installation found. Browse to your installation or add a SavedVariables file.')

    def add_file(self):
        value=filedialog.askopenfilename(parent=self,title='Choose addon SavedVariables',filetypes=[('Lua SavedVariables','*.lua')])
        if value:
            if Path(value).name not in ('PvPLedger.lua','REFlex.lua'):
                self.error.configure(text='Choose PvPLedger.lua or REFlex.lua, not a backup.');return
            self.source_files.append(value)
            self.sources.insert('end',self.source_label(value));self.sources.selection_set('end')

    @staticmethod
    def source_label(value):
        path=Path(value)
        parts=path.parts
        if 'Account' in parts:
            context=' / '.join(parts[parts.index('Account')+1:-1])
        else:context=str(path.parent)
        return path.name+' — '+context

    def find(self):
        try:
            paths=setup.locations(self.variables['wow_root'].get());self.sources.delete(0,'end')
            self.source_files=list(map(str,paths))
            for path in paths:self.sources.insert('end',self.source_label(path))
            self.source_note.configure(text=f'{len(paths)} addon files found. Select only the locations you want to read.' if paths else 'No addon files found. The addons may not be installed or have not saved data; you can start empty.')
        except (ValueError,OSError) as exc:self.error.configure(text=str(exc))

    def choose_sources(self):
        self.paths=[self.source_files[i] for i in self.sources.curselection()]
        values=setup.discovered_characters(self.paths)
        self.characters.configure(values=values)
        if values:self.characters.set(values[0])
        self.source_note.configure(text=f'{len(self.paths)} source files selected; {len(values)} character-specific identities discovered.')

    def add_discovered(self):
        if self.characters.get():self.add_association('',self.characters.get())

    def add_identity(self):
        name,realm=(self.variables[k].get().strip() for k in ('character','realm'))
        if not name or not realm:self.error.configure(text='Enter a character and realm.');return
        self.add_association(self.variables['friend'].get().strip(),name+'-'+realm)

    def add_association(self,person,character):
        self.friends.append((person,character)) if person else self.own.append(character)
        self.render_associations()

    def render_associations(self):
        self.associations.delete(0,'end')
        for person,character in [*[("Me",c) for c in self.own],*self.friends]:self.associations.insert('end',f'{person}: {character}')

    def remove_identity(self):
        selected=self.associations.curselection()
        if selected:
            i=selected[0]
            self.own.pop(i) if i<len(self.own) else self.friends.pop(i-len(self.own))
            self.render_associations()

    def skip(self):
        self.finish(empty=True)

    def finish(self,empty=False):
        try:
            self.choose_sources()
            home=self.app.service.home if empty else Path(self.variables['home'].get()).resolve()
            import sys
            installation=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
            if home == installation or home.is_relative_to(installation):
                raise ValueError('Select a private archive outside the application/source folder')
            config=setup.configure(home,**({} if empty else {
                'display_name':self.variables['display_name'].get(),'wow_root':self.variables['wow_root'].get().strip(),
                'sources':self.paths,'own':self.own,'friends':self.friends,'sync_enabled':self.sync.get(),
                'interval':int(self.variables['interval'].get()),'zone':self.variables['zone'].get().strip()}))
            from ..service import DesktopService
            from ..settings import SettingsStore
            from ..sync import SyncSchedule
            if not self.app.explicit_home:
                from ..archive import set_default_home
                set_default_home(home)
            self.app.service=DesktopService(home);self.app.settings=SettingsStore(home/'settings.json');self.app.config=config
            self.app.sync_schedule=SyncSchedule(interval=config['sync_interval'])
            do_import=not empty and self.do_import.get() and bool(self.paths)
            self.app.auto_sync=not empty
            if not do_import:
                self.app.sync_schedule.next_due=self.app.sync_schedule.clock()+config['sync_interval']
            self.destroy()
            if do_import:self.app.refresh()
            else:self.app.reload('Local profile ready. No characters or records are required to start.')
        except (ValueError,OSError) as exc:self.error.configure(text=str(exc))

    def destroy(self):
        super().destroy();self.variables.clear();self.sync=self.do_import=None

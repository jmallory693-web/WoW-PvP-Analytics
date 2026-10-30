import tkinter as tk
from tkinter import ttk, simpledialog
from .theme import palette


class PeopleDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root); self.app = app
        self.title('Edit people and exact character identities'); self.transient(app.root)
        body = ttk.Frame(self, padding=20); body.pack(fill='both', expand=True)
        ttk.Label(body, text='Edit people', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(body, text='Display names do not change person IDs. Associations apply retroactively; source records stay unchanged.', wraplength=620).pack(anchor='w', pady=8)
        self.payload = app.payload
        self.labels = self.payload['person_labels']
        self.person = ttk.Combobox(body, values=list(self.labels.values()), state='readonly', width=45); self.person.pack(fill='x')
        self.person.bind('<<ComboboxSelected>>', self.load_person)
        self.name, self.nick = tk.StringVar(), tk.StringVar()
        for label, var in [('Display name', self.name), ('Nickname (optional)', self.nick)]:
            ttk.Label(body, text=label).pack(anchor='w', pady=(7, 0)); ttk.Entry(body, textvariable=var).pack(fill='x')
        ttk.Button(body, text='Save person name', command=self.save_person).pack(anchor='e', pady=8)
        ttk.Button(body, text='Add person / friend…', command=self.add_person).pack(anchor='w')
        self.entries = tk.Listbox(body, height=7, exportselection=False, bg=palette(self)['FIELD'], fg=palette(self)['TEXT'], selectbackground=palette(self)['LIST_SELECTION_BG']); self.entries.pack(fill='both', expand=True)
        self.entries.bind('<<ListboxSelect>>', self.select_character)
        row = ttk.Frame(body); row.pack(fill='x', pady=8)
        self.character, self.realm = tk.StringVar(), tk.StringVar()
        ttk.Label(row, text='Character').grid(row=0, column=0, sticky='w'); ttk.Entry(row, textvariable=self.character, width=25).grid(row=1, column=0)
        ttk.Label(row, text='Realm (required for new associations)').grid(row=0, column=1, sticky='w'); ttk.Entry(row, textvariable=self.realm, width=27).grid(row=1, column=1, padx=8)
        buttons = ttk.Frame(body); buttons.pack(fill='x')
        ttk.Button(buttons, text='Assign / reassign to person', command=self.assign).pack(side='left')
        ttk.Button(buttons, text='Unassign selected', command=lambda: self.change('unassign')).pack(side='left', padx=5)
        ttk.Button(buttons, text='Remove association', command=lambda: self.change('remove')).pack(side='left')
        self.message = ttk.Label(body, wraplength=610, foreground=palette(self)['RED']); self.message.pack(fill='x', pady=8)
        ttk.Button(body, text='Close', command=self.destroy).pack(anchor='e')
        self.person.set(next(iter(self.labels.values()))); self.load_person()
        self.bind('<Escape>', lambda e: self.destroy()); self.after_idle(self.focus_set)

    def key(self):
        return next(k for k, v in self.labels.items() if v == self.person.get())

    def add_person(self):
        value = simpledialog.askstring('Add person', 'Optional friend/person label:', parent=self)
        if value and value.strip():
            def work():
                from ..identity import IdentityMap, normalized
                identities = IdentityMap(self.app.service.home/'people.json')
                name = value.strip()
                if any(normalized(name) in (normalized(p),normalized(identities.label(p))) for p in identities.people):
                    raise ValueError('That person already exists')
                identities.people[name] = []
                identities.save()
            self.run(work)

    def load_person(self, event=None):
        self.old_association = None
        p = self.key(); profile = self.payload['person_profiles'].get(p, {})
        self.name.set(profile.get('display_name', p)); self.nick.set(profile.get('nickname', ''))
        self.entries.delete(0, 'end')
        for entry in self.payload['people'][p]:
            self.entries.insert('end', entry)

    def select_character(self, event=None):
        values = self.entries.curselection()
        if values:
            self.old_association = self.entries.get(values[0])
            name, _, realm = self.old_association.partition('-')
            self.character.set(name); self.realm.set(realm)

    def run(self, work):
        def done(result):
            self.app.reload('People updated across archived history.'); self.destroy()
        self.app.run_job('Updating people…', work, done, lambda exc: self.message.configure(text=str(exc)))

    def save_person(self):
        p, name, nick = self.key(), self.name.get(), self.nick.get()
        self.run(lambda: self.app.service.edit_person(p, name, nick))

    def assign(self):
        name, realm, p = self.character.get().strip(), self.realm.get().strip(), self.key()
        if not name or not realm:
            self.message.configure(text='Enter both character and realm; names alone do not confirm an exact identity.'); return
        service, old = self.app.service, self.old_association
        self.run(lambda: service.edit_association(old, name + '-' + realm, p) if old else service.edit_identity(name + '-' + realm, p))

    def change(self, action):
        selected = self.entries.curselection()
        if not selected:
            self.message.configure(text='Select an existing association first.'); return
        entry = self.entries.get(selected[0])
        self.run(lambda: self.app.service.edit_identity(entry, action=action))

    def destroy(self):
        super().destroy()
        self.name = self.nick = self.character = self.realm = None

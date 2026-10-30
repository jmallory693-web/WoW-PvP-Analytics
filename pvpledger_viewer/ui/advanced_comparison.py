import tkinter as tk
from tkinter import ttk, filedialog
from .character_search import CharacterSearch
from .widgets import ScrollFrame
from ..comparisons import METRICS, QUICK, paired_text
from ..viewmodels import display
from ..charts import RENDER_LOCK
from .theme import palette, chart_palette


class AdvancedComparison(ttk.Frame):
    def __init__(self, parent, app, initial='Character vs Character'):
        super().__init__(parent); self.app, self.model, self.serial = app, None, 0
        saved = app.config.get('advanced_comparison', {}).get(initial, {})
        self.initial = initial
        self.mode = tk.StringVar(value=saved.get('mode', initial))
        self.scope = tk.StringVar(value=saved.get('scope', 'All Recorded Matches'))
        row = ttk.Frame(self); row.pack(fill='x', pady=3)
        mode = ttk.Combobox(row, textvariable=self.mode, values=['Character vs Character', 'Me vs Friends', 'My Characters'], state='readonly', width=23); mode.pack(side='left')
        mode.bind('<<ComboboxSelected>>', lambda e: self.layout())
        ttk.Combobox(row, textvariable=self.scope, values=['All Recorded Matches', 'Played Together', 'Only Shared Matches'], state='readonly', width=23).pack(side='left', padx=5)
        ttk.Button(row, text='Compare', style='Accent.TButton', command=self.request).pack(side='left')
        ttk.Button(row, text='Samples / paired data', command=self.details).pack(side='right')
        self.selectors = ttk.Frame(self); self.selectors.pack(fill='x')
        self.a = CharacterSearch(self.selectors, 'Character A / my character (blank = All My Characters)')
        self.b = CharacterSearch(self.selectors, 'Character B / optional friend character')
        self.selectors.columnconfigure(0, weight=1); self.selectors.columnconfigure(1, weight=1)
        self.a.grid(row=0, column=0, sticky='ew', padx=(0, 5)); self.b.grid(row=0, column=1, sticky='ew')
        self.mine = tk.Listbox(self.selectors, height=4, selectmode='extended', exportselection=False, bg=palette(self)['FIELD'], fg=palette(self)['TEXT'], selectbackground=palette(self)['LIST_SELECTION_BG'])
        options = ttk.Frame(self); options.pack(fill='x', pady=4)
        ttk.Label(options, text='Friend').pack(side='left')
        self.friend = ttk.Combobox(options, state='readonly', width=18); self.friend.pack(side='left', padx=4)
        self.friend.bind('<<ComboboxSelected>>', lambda e: self.layout())
        self.metric = ttk.Combobox(options, values=list(QUICK), state='readonly', width=23); self.metric.set(saved.get('quick', 'Damage performance')); self.metric.pack(side='left', padx=4)
        self.metric.bind('<<ComboboxSelected>>', self.quick)
        ttk.Label(options, text='Gear min / max').pack(side='left')
        self.low, self.high = tk.StringVar(value=saved.get('low', '')), tk.StringVar(value=saved.get('high', ''))
        ttk.Entry(options, textvariable=self.low, width=5).pack(side='left', padx=3); ttk.Entry(options, textvariable=self.high, width=5).pack(side='left')
        ttk.Button(options, text='Charts / metrics…', command=self.charts).pack(side='right')
        self.note = ttk.Label(self, wraplength=1000, style='Muted.TLabel'); self.note.pack(fill='x', pady=3)
        self.holder = ttk.Frame(self); self.holder.pack(fill='both', expand=True)
        self.owner_person = 'Me'
        self.canvas = None; self.entries = []; self.people = {}; self.my_entries = []
        self.saved = saved; self.restored = False
        self.metrics = list(saved.get('metrics', [QUICK[self.metric.get()]]))

    def destroy(self):
        super().destroy()
        self.mode = self.scope = self.low = self.high = self.metric = None

    def render(self, payload):
        self.owner_person = payload['owner_person']
        self.entries, self.people = payload['catalogue'], payload['person_labels']
        self.ownership = {tuple(e['key']): e['person'] for e in self.entries}
        selected_mine = [self.my_entries[i]['key'] for i in self.mine.curselection()] if self.my_entries else self.saved.get('mine', [])
        self.my_entries = [e for e in self.entries if e['person'] == self.owner_person]
        self.mine.delete(0, 'end')
        for i, e in enumerate(self.my_entries):
            self.mine.insert('end', e['label'])
            if e['key'] in selected_mine:
                self.mine.selection_set(i)
        values = [label for p, label in self.people.items() if p not in (self.owner_person, 'Unassigned')]
        self.friend.configure(values=values)
        key = self.saved.get('friend')
        if key in self.people:
            self.friend.set(self.people[key])
        elif self.friend.get() not in values:
            self.friend.set(values[0] if values else '')
        self.layout()
        if not self.restored:
            self.a.restore(self.saved.get('a')); self.b.restore(self.saved.get('b')); self.restored = True
        if self.model:
            self.request()

    def friend_key(self):
        return next((p for p, label in self.people.items() if label == self.friend.get()), None)

    def layout(self):
        mode = self.mode.get()
        self.a.label.configure(text='My character (blank = All My Characters)' if mode == 'Me vs Friends' else 'Character A · choose a suggestion to confirm')
        self.b.label.configure(text='Friend character (optional; blank = whole person)' if mode == 'Me vs Friends' else 'Character B · choose a suggestion to confirm')
        if mode == 'My Characters':
            self.a.grid_remove(); self.b.grid_remove(); self.mine.grid(row=0, column=0, columnspan=2, sticky='ew')
        else:
            self.mine.grid_remove(); self.a.grid(); self.b.grid()
        self.a.set_entries([e for e in self.entries if mode != 'Me vs Friends' or e['person'] == self.owner_person])
        self.b.set_entries([e for e in self.entries if mode != 'Me vs Friends' or e['person'] == self.friend_key()])
        self.friend.configure(state='readonly' if mode == 'Me vs Friends' else 'disabled')

    def selections(self):
        def character(e):
            return {'kind': 'character', 'character': e['key'], 'label': e['label']}
        if self.mode.get() == 'My Characters':
            selected = [self.my_entries[i] for i in self.mine.curselection()]
            if len(selected) < 2:
                raise ValueError('Ctrl-click two or more of your characters.')
            return [character(e) for e in selected]
        if self.mode.get() == 'Me vs Friends':
            p = self.friend_key()
            if not p:
                raise ValueError('Select a friend.')
            if self.a.text.get() and not self.a.selected or self.b.text.get() and not self.b.selected:
                raise ValueError('Confirm each typed character using a suggestion, or clear it to select the whole person.')
            if self.a.selected and self.a.selected['person'] != self.owner_person or self.b.selected and self.b.selected['person'] != p:
                raise ValueError('Choose a character assigned to the selected person.')
            return [{'kind': 'person', 'person': self.owner_person, 'character': self.a.selected['key'] if self.a.selected else None, 'label': self.a.selected['label'] if self.a.selected else 'All My Characters (' + self.people.get(self.owner_person, self.owner_person) + ')'},
                    {'kind': 'person', 'person': p, 'character': self.b.selected['key'] if self.b.selected else None, 'label': self.b.selected['label'] if self.b.selected else self.people[p]}]
        if not self.a.selected or not self.b.selected:
            raise ValueError('Confirm Character A and B from their suggestions; fuzzy matches are never selected automatically.')
        if self.a.selected['key'] == self.b.selected['key']:
            raise ValueError('Select two different characters.')
        return [character(self.a.selected), character(self.b.selected)]

    def request(self):
        try:
            selections = self.selections()
            low, high = (float(v.get()) if v.get().strip() else None for v in (self.low, self.high))
        except ValueError as exc:
            self.app.feedback(str(exc), error=True); return
        self.serial += 1; serial = self.serial
        self.persist()
        scope, filters, window = self.scope.get(), self.app.filters, self.app.config['trend_window']
        def done(model):
            if serial == self.serial and self.winfo_exists():
                self.model = model; self.preview()
        service = self.app.service
        self.app.run_job('Comparing archived participants…', lambda: service.compare(selections, scope, filters, window, low, high), done)

    def persist(self):
        self.app.config['advanced_comparison'][self.initial] = {'mode': self.mode.get(), 'scope': self.scope.get(), 'friend': self.friend_key(),
            'a': self.a.selected['key'] if self.a.selected else None, 'b': self.b.selected['key'] if self.b.selected else None,
            'mine': [self.my_entries[i]['key'] for i in self.mine.curselection()], 'low': self.low.get(), 'high': self.high.get(),
            'metrics': self.metrics, 'quick': self.metric.get()}
        self.saved = self.app.config['advanced_comparison'][self.initial]

    def quick(self, event=None):
        self.metrics = [QUICK[self.metric.get()]]
        self.persist()
        self.preview()

    def preview(self):
        if not self.model:
            return
        self.note.configure(text=self.model['scope'] + ' · ' + ' | '.join(f"{s['label']}: {s['summary']['games']} games, {s['summary']['wins']}W/{s['summary']['losses']}L; known n={s['summary']['known_results']}" for s in self.model['series'])
                            + ('\nIndependent samples can contain different matches and match types. ' if self.model['scope'] == 'All Recorded Matches' else '\nOnly jointly observed matches are included. ')
                            + 'Roles, gear and teams differ. Samples shows coverage; Charts opens separate metric scales.')
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from ..comparison_charts import draw
        if self.canvas is None:
            self.figure = Figure(figsize=(9, 2.3), dpi=100)
            self.canvas = FigureCanvasTkAgg(self.figure, master=self.holder); self.canvas.get_tk_widget().pack(fill='both', expand=True)
        with RENDER_LOCK:
            draw(self.figure, self.model, self.metrics[:1], palette=chart_palette(self)); self.canvas.draw_idle()

    def details(self):
        if not self.model:
            self.app.feedback('Choose participants and click Compare first.'); return
        dialog = tk.Toplevel(self); dialog.title('Comparison samples, coverage and paired matches'); dialog.geometry('1000x650')
        text = tk.Text(dialog, wrap='word', bg=palette(self)['FIELD'], fg=palette(self)['TEXT']); scrollbar = ttk.Scrollbar(dialog, command=text.yview); scrollbar.pack(side='right', fill='y')
        text.configure(yscrollcommand=scrollbar.set); text.pack(fill='both', expand=True)
        text.insert('end', self.model['scope'] + '\n' + self.model['note'] + '\n\nMean / median, supported n / games\n')
        for s in self.model['series']:
            text.insert('end', '\n' + s['label'] + '\n')
            for kind, summary in [('ALL TYPES (explicit aggregate)', s['summary']), *s['by_type'].items()]:
                context = '; '.join(' / '.join(c) for c in summary['contexts']) or 'No observations'
                text.insert('end', f"{kind}: {summary['games']} games; {summary['wins']}W/{summary['losses']}L; win rate {display(summary['win_rate'])}% (known n={summary['known_results']})\nContext: {context}\n")
                for field, stat in summary['metrics'].items():
                    text.insert('end', f"  {field}: {display(stat['mean'])} / {display(stat['median'])}; n={stat['count']}/{summary['games']}\n")
        text.insert('end', '\n' + paired_text(self.model))
        text.configure(state='disabled'); dialog.bind('<Escape>', lambda e: dialog.destroy()); dialog.focus_set()

    def charts(self):
        from .comparison_dialog import ComparisonChartDialog
        return ComparisonChartDialog(self)

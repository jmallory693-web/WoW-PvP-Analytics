import tkinter as tk
from tkinter import ttk
from .widgets import Table
from .theme import palette
from ..service import EDITABLE_FIELDS, MATCH_TYPES
from ..viewmodels import display, premade_description

COLUMNS = [('Identity', '', 85), ('Player/realm', 'Player / realm', 210), ('Person', 'Person', 95),
           ('Class', 'Class', 110), ('Spec', 'Specialization', 125), ('KB', 'KB', 65), ('HK', 'HK', 65),
           ('Deaths', 'Deaths', 70), ('Damage', 'Damage', 115), ('Healing', 'Healing', 115),
           ('Honor', 'Honor', 80), ('Objectives', 'Objectives', 260), ('Attendance', 'Attendance', 140)]


class ScoreboardWindow(tk.Toplevel):
    def __init__(self, app, key, model):
        super().__init__(app.root)
        self.app, self.key, self.model = app, tuple(key), model
        self.configure(bg=palette(self)['BG'])
        self.title('PvP Ledger — Match Scoreboard')
        self.geometry('1180x700'); self.minsize(960, 560)
        self.transient(app.root)
        self.bind('<Escape>', lambda e: self.destroy())
        container = ttk.Frame(self, padding=22); container.pack(fill='both', expand=True)
        header = ttk.Frame(container); header.pack(fill='x')
        self.heading = ttk.Label(header, style='Title.TLabel'); self.heading.pack(side='left')
        ttk.Button(header, text='Copy Scoreboard', style='Accent.TButton', command=self.copy).pack(side='right')
        self.edit_button = ttk.Button(header, text='Edit partial metadata', command=self.edit)
        self.edit_button.pack(side='right', padx=10)
        ttk.Button(container, text='Sources and field conflicts…', command=self.sources).pack(anchor='w', pady=(6, 0))
        from .players import RankingWindow
        ttk.Button(container, text='Rank players by statistic…', command=lambda: RankingWindow(app, self.key, next((table.selected() for table in self.teams.values() if table.selected()), None))).pack(anchor='w', pady=3)
        self.status = ttk.Label(container, style='Gold.TLabel', wraplength=1100)
        self.status.pack(fill='x', pady=(5, 12))
        self.metadata = ttk.Label(container, justify='left', wraplength=1110, style='Muted.TLabel')
        self.metadata.pack(fill='x', pady=(0, 14))
        self.tabs = ttk.Notebook(container)
        self.teams = {}
        ttk.Label(container, text=f"YOU = {palette(self)['SELF_LABEL']}   ·   PREMADE / known ALLY = {palette(self)['ALLY_LABEL']}   ·   Select a column to sort   ·   Scroll horizontally for objectives and attendance", style='Muted.TLabel', wraplength=1100).pack(side='bottom', anchor='w', pady=(12, 0))
        self.tabs.pack(fill='both', expand=True)
        self.render(model)
        self.after_idle(self.focus_set)

    def render(self, model):
        self.model = model
        m = model['match']; meta = model['metadata']
        self.heading.configure(text=m.get('Map') or (f"Map ID {m['Map ID']}" if m.get('Map ID') is not None else 'Unknown map'))
        self.status.configure(text=('PARTIAL MATCH · Unknown metadata has not been inferred.  ' if model['partial'] else '')
                              + f"{m['Character']}-{m['Realm']}  ·  {m['Match ID']}  ·  {m.get('Type') or 'Unknown type'}  ·  {m.get('Display source',m.get('Source', 'PvP Ledger'))}"
                              + (' · Incomplete scoreboard; retained players only' if m.get('_scoreboard_incomplete') else '')
                              + (f" · {len(m.get('_conflicts', []))} field conflicts; inspect sources" if m.get('_conflicts') else ''))
        self.edit_button.configure(state='normal' if model['partial'] and not m.get('_excel_historical') else 'disabled')
        lines = [f"Result  {display(meta['Result'])}     Duration  {display(meta['Duration (s)'])} s     Minutes played  {display(meta['Minutes played'])}     Win margin  {display(meta['Win margin'])}",
                 f"Scores (your team / enemy)  {display(meta['My team score'])} / {display(meta['Enemy team score'])}     Alliance / Horde  {display(meta['Alliance score'])} / {display(meta['Horde score'])}",
                 f"Team damage  {display(meta['Team damage'])} / {display(meta['Enemy damage'])}     Team healing  {display(meta['Team healing'])} / {display(meta['Enemy healing'])}     Deaths  {display(meta['Team deaths'])} / {display(meta['Enemy deaths'])}",
                 'Premade members  ' + premade_description(m)]
        if model['partial'] and m.get('_map_suggestion'):
            lines.append('Unconfirmed map suggestion: ' + m['_map_suggestion'])
        self.metadata.configure(text='\n'.join(lines))
        for team, rows in model['teams'].items():
            if team == 'Unknown' and not rows:
                continue
            if team not in self.teams:
                table = Table(self.tabs, COLUMNS)
                self.tabs.add(table, text=team)
                self.teams[team] = table
            table = self.teams[team]
            self.tabs.tab(table, text=f"{'Friendly team' if team == 'Mine' else 'Enemy team' if team == 'Enemy' else team}  ·  {len(rows)} players")
            table.set_rows(rows)

    def copy(self):
        self.app.run_job('Copying scoreboard…', lambda: self.app.service.copy_report(key=self.key),
                         lambda r: self.app.feedback(f"Scoreboard copied ({r['characters']:,} characters)."))

    def sources(self):
        import json
        dialog = tk.Toplevel(self); dialog.title('Match sources and provenance'); dialog.geometry('1000x650')
        box = tk.Text(dialog, wrap='word', bg=palette(self)['BG'], fg=palette(self)['TEXT'])
        scroll = ttk.Scrollbar(dialog, command=box.yview); scroll.pack(side='right', fill='y')
        box.configure(yscrollcommand=scroll.set); box.pack(fill='both', expand=True)
        m = self.model['match']
        box.insert('end', 'FIELD PROVENANCE\n')
        for field, sources in m.get('_provenance', {}).items():
            box.insert('end', f"{field}: {display(m.get(field))} — {', '.join(sources)}\n")
        box.insert('end', '\nCONFLICTING SOURCE VALUES (all retained)\n' + json.dumps(m.get('_conflicts', []), ensure_ascii=False, indent=2))
        box.insert('end', '\n\nOBSERVATIONS AND IMMUTABLE SNAPSHOTS\n' + json.dumps(m.get('_observations', []), ensure_ascii=False, indent=2))
        box.insert('end', '\n\nAPPROVED EXCEL EVIDENCE (separate, reversible; addon values preserved)\n'+json.dumps(m.get('_excel_supplements',[]),ensure_ascii=False,indent=2))
        box.insert('end', '\n\nROSTER FIELD PROVENANCE\n')
        for rows in self.model['teams'].values():
            for row in rows:
                box.insert('end', f"\n{row.get('Player')}-{row.get('Realm')}\n" + json.dumps(row.get('_provenance', {}), ensure_ascii=False, indent=2))
        box.configure(state='disabled'); dialog.bind('<Escape>', lambda e: dialog.destroy()); dialog.focus_set()

    def edit(self):
        dialog = tk.Toplevel(self); dialog.title('Edit partial-match metadata')
        dialog.configure(bg=palette(self)['BG']); dialog.transient(self); dialog.grab_set()
        body = ttk.Frame(dialog, padding=22); body.pack(fill='both', expand=True)
        ttk.Label(body, text='Correct the record', style='Heading.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Label(body, text='Leave unknown values blank. Edits are overrides; raw data stays unchanged.', style='Muted.TLabel', wraplength=480).grid(row=1, column=0, columnspan=2, sticky='w', pady=(6, 15))
        entries = {}
        for index, field in enumerate(EDITABLE_FIELDS, 2):
            ttk.Label(body, text=field).grid(row=index, column=0, sticky='w', pady=4, padx=(0, 20))
            value = self.model['match'].get(field)
            variable = tk.StringVar(value='' if value is None else str(value))
            if field in ('Result', 'Type'):
                widget = ttk.Combobox(body, textvariable=variable, values=[''] + (['W', 'L'] if field == 'Result' else list(MATCH_TYPES)), state='readonly', width=26)
            else:
                widget = ttk.Entry(body, textvariable=variable, width=29)
            widget.grid(row=index, column=1, sticky='ew', pady=4)
            entries[field] = variable
        error = ttk.Label(body, text='', foreground=palette(self)['RED'], wraplength=480)
        error.grid(row=12, column=0, columnspan=2, sticky='w', pady=8)
        def save():
            values = {field: var.get() for field, var in entries.items()}
            from ..service import validate_overrides
            try:
                validate_overrides(values)
            except ValueError as exc:
                error.configure(text=str(exc)); return
            button.configure(state='disabled')
            def done(model):
                if self.winfo_exists():
                    self.render(model)
                if dialog.winfo_exists():
                    dialog.destroy()
                self.app.reload('Partial metadata saved. Original data is unchanged.')
            def failed(exc):
                if dialog.winfo_exists():
                    error.configure(text=str(exc)); button.configure(state='normal')
            self.app.run_job('Saving metadata override…', lambda: self.app.service.edit_partial(self.key, values), done, failed)
        button = ttk.Button(body, text='Save overrides', style='Accent.TButton', command=save)
        button.grid(row=13, column=1, sticky='e')
        ttk.Button(body, text='Cancel', command=dialog.destroy).grid(row=13, column=0, sticky='w')
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        dialog.after_idle(dialog.focus_set)

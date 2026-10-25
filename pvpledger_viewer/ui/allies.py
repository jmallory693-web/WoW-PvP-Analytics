import tkinter as tk
from tkinter import ttk
from .widgets import Table, page_heading
from ..identity import normalized
from ..viewmodels import percent


def ally_rows(allies):
    result = []
    for person, kinds in allies.items():
        for kind, data in kinds.items():
            together, without = data['together'], data['without']
            row = {'Person': person, 'Type': kind, 'Games': together['games'],
                   'Record': f"{together['wins']}–{together['losses']} (n={together['result_count']})",
                   'Together': percent(together['win_rate']),
                   'Without': f"{percent(without['win_rate'])} (n={without['result_count']})"}
            for field, values in data['ally_statistics'].items():
                row[field] = values['mean']; row[field + ' median'] = values['median']; row[field + ' n'] = values['count']
            result.append(row)
    return result


class AlliesView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        page_heading(self, 'Your allies', 'People, not just characters. Records are split by match type; identity edits apply to all archived history.')
        from .people import PeopleDialog
        ttk.Button(self, text='Edit People…', command=lambda: PeopleDialog(app)).pack(anchor='w', pady=(0, 6))
        editor = ttk.Frame(self); editor.pack(fill='x', pady=(0, 12))
        ttk.Label(editor, text='Character / realm').grid(row=0, column=0, sticky='w')
        ttk.Label(editor, text='Person (or a new name)').grid(row=0, column=1, sticky='w', padx=8)
        self.character = ttk.Combobox(editor, width=28)
        self.character.grid(row=1, column=0, sticky='ew')
        self.person = ttk.Combobox(editor, width=18)
        self.person.grid(row=1, column=1, sticky='ew', padx=8)
        ttk.Button(editor, text='Assign', style='Accent.TButton', command=lambda: self.edit('assign')).grid(row=1, column=2, padx=4)
        ttk.Button(editor, text='Unassign', command=lambda: self.edit('unassign')).grid(row=1, column=3, padx=4)
        ttk.Button(editor, text='Export selected ally', command=self.export).grid(row=1, column=4, padx=4)
        self.assignments = ttk.Label(self, style='Muted.TLabel', wraplength=980, justify='left')
        self.assignments.pack(fill='x', pady=(0, 8))
        self.unassigned = ttk.Label(self, style='Gold.TLabel', wraplength=980)
        self.unassigned.pack(fill='x', pady=(0, 10))
        columns = [('Person', 'Person', 90), ('Type', 'Match type', 130), ('Games', 'Together', 80),
                   ('Record', 'W–L / sample', 120), ('Together', 'Win rate with', 110), ('Without', 'Without / sample', 145)]
        for field in ('Damage', 'Healing', 'Deaths', 'Damage rank', 'Healing rank'):
            columns += [(field, field + ' mean', 125), (field + ' median', 'Median', 100), (field + ' n', 'n', 50)]
        self.table = Table(self, columns)
        self.table.pack(fill='both', expand=True)

    def edit(self, action):
        character, person = self.character.get().strip(), self.person.get().strip()
        if not character or (action == 'assign' and not person):
            self.app.feedback('Enter a character and choose or enter a person.', error=True)
            return
        self.app.run_job('Updating identities…', lambda: self.app.service.edit_identity(character, person, action),
                         lambda result: self.app.reload('Identity updated across all history.'))

    def export(self):
        row = self.table.selected()
        person = row['Person'] if row else self.person.get().strip()
        if not person:
            self.app.feedback('Select an ally row or enter a person to export.', error=True)
        else:
            self.app.export_data(ally=person)

    def render(self, payload):
        people = payload['people']
        labels = payload.get('person_labels', {p: p for p in people})
        self.person.configure(values=list(labels.values()))
        self.character.configure(values=sorted({e for entries in people.values() for e in entries}))
        self.assignments.configure(text='   |   '.join(labels[p] + ': ' + (', '.join(entries) or 'No confirmed characters') for p, entries in people.items() if normalized(p) not in (normalized(payload['owner_person']), 'unassigned')))
        unknown = payload['diagnostics']['unassigned']
        self.unassigned.configure(text='UNASSIGNED   ' + (', '.join(unknown) or 'No unassigned premade characters'))
        self.table.set_rows([r | {'Person': labels.get(r['Person'], r['Person'])} for r in ally_rows(payload['allies'])])

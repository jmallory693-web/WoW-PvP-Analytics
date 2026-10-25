import json
import tkinter as tk
from tkinter import ttk
from .widgets import Table, page_heading
from ..viewmodels import display, history_row


class DuplicateReviewView(ttk.Frame):
    def destroy(self):
        super().destroy()
        self.left=self.right=None

    def __init__(self, parent, app):
        super().__init__(parent); self.app = app
        page_heading(self, 'Duplicate review', 'Ambiguous observations count separately until linked. Linking changes the logical archive; original files and observations stay intact.')
        choices = ttk.Frame(self); choices.pack(fill='x', pady=(0, 8))
        self.left, self.right = tk.StringVar(), tk.StringVar()
        ttk.Label(choices, text='Observation IDs').pack(side='left')
        self.a = ttk.Combobox(choices, textvariable=self.left, state='readonly', width=35); self.a.pack(side='left', padx=6)
        self.b = ttk.Combobox(choices, textvariable=self.right, state='readonly', width=35); self.b.pack(side='left', padx=6)
        buttons = ttk.Frame(self); buttons.pack(fill='x', pady=(0, 8))
        for label, decision in [('Link as one match', 'confirmed'), ('Keep separate', 'separate'), ('Unlink left observation', 'unlink')]:
            ttk.Button(buttons, text=label, command=lambda d=decision: self.decide(d)).pack(side='left', padx=(0, 8))
        ttk.Button(buttons, text='Inspect selected evidence', command=self.inspect).pack(side='left')
        self.count = ttk.Label(self, style='Muted.TLabel'); self.count.pack(anchor='w', pady=5)
        self.table = Table(self, [('Decision', 'Decision', 115), ('Owner', 'Character / realm', 175),
                                 ('Left', 'PvP / left observation', 260), ('Right', 'REFlex / right observation', 260),
                                 ('Manual', 'User decision', 105)], on_open=lambda row: self.inspect())
        self.table.pack(fill='both', expand=True)
        self.table.tree.bind('<<TreeviewSelect>>', self.select)

    def render(self, payload):
        self.observations = {o['id']: o for o in payload['observations']}
        values = [f"{o['id']} · {o['addon']} · {o['character']}-{o['realm']}" for o in self.observations.values()]
        self.a.configure(values=values); self.b.configure(values=values)
        self.values = {int(v.split(' · ')[0]): v for v in values}
        def label(m):
            row = history_row(m)
            return f"{row['Date/time'] or 'Unknown time'} · {row['Map display'] or 'Unknown map'} · {m.get('Result') or 'Unknown result'}"
        rows = [r | {'Decision': r['decision'], 'Owner': r['left']['Character'] + '-' + r['left']['Realm'],
                     'Left': str(r['left_id']) + ' · ' + label(r['left']),
                     'Right': str(r['right_id']) + ' · ' + label(r['right']), 'Manual': 'Yes' if r['manual'] else 'No'} for r in payload['review']]
        rows.sort(key=lambda r: (r['decision'] != 'ambiguous', r['left_id'], r['right_id']))
        self.table.set_rows(rows)
        self.count.configure(text=f"{sum(r['decision'] == 'ambiguous' for r in rows)} ambiguous pairs · {len(rows)} recorded decisions. Select a row, inspect evidence, then choose Link or Keep separate.")

    def select(self, event=None):
        row = self.table.selected()
        if row:
            self.left.set(self.values[row['left_id']]); self.right.set(self.values[row['right_id']])

    def decide(self, decision):
        try:
            a, b = int(self.left.get().split(' · ')[0]), int(self.right.get().split(' · ')[0])
            if a == b:
                raise ValueError('Select two different observations')
        except ValueError:
            self.app.feedback('Select two different observation IDs, or select a review row.', error=True); return
        self.app.run_job('Saving duplicate decision…', lambda: self.app.service.decide_link(a, b, decision),
                         lambda r: self.app.reload('Decision saved. All archive statistics now use the updated logical matches.'))

    def inspect(self):
        row = self.table.selected()
        if not row:
            self.app.feedback('Select a review row first.', error=True); return
        dialog = tk.Toplevel(self); dialog.title('Duplicate evidence'); dialog.geometry('1000x650')
        text = tk.Text(dialog, wrap='word', bg='#0e1928', fg='#e7edf5')
        scrollbar = ttk.Scrollbar(dialog, command=text.yview); scrollbar.pack(side='right', fill='y')
        text.configure(yscrollcommand=scrollbar.set); text.pack(fill='both', expand=True)
        text.insert('end', f"Decision: {row['decision']} · User decision: {bool(row['manual'])}\nReason: {row['reason']}\n")
        for name in ('left', 'right'):
            text.insert('end', '\n' + name.upper() + '\n')
            for key, value in row[name].items():
                if not key.startswith('_'):
                    text.insert('end', f'{key}: {display(value)}\n')
        text.configure(state='disabled'); dialog.bind('<Escape>', lambda e: dialog.destroy()); dialog.focus_set()

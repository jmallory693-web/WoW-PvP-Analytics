import json
import tkinter as tk
from tkinter import ttk
from .theme import FIELD, TEXT
from .widgets import page_heading


def diagnostic_text(data):
    lines = [f"Archive: {data['archive']}", f"WoW folder: {data['wow_root'] or 'Not selected'}",
             f"Last import (UTC): {data['last_import'] or 'No imports yet'}",
             f"Archive totals: {json.dumps(data['totals'], ensure_ascii=False)}", '',
             f"Source totals: {json.dumps(data.get('sources', {}), ensure_ascii=False)}", '',
             'DISCOVERED SAVEDVARIABLES FILES', *(data['files'] or ['None found; choose WoW folder or import a file.']), '',
             'UNASSIGNED PREMADE CHARACTERS', *(data['unassigned'] or ['None']), '',
             f"IMPORT HISTORY — latest {len(data['recent_imports'])} of {data['imports_total']} imports"]
    for record in reversed(data['recent_imports']):
        issues = record['diagnostics']
        malformed = sum(i['code'] in ('invalid_csv', 'extra_columns', 'invalid_number', 'missing_match_identity', 'missing_roster_identity', 'ambiguous_roster_owner') for i in issues)
        lines += [f"\nImport #{record['id']}  {record['started']}  [{record['status']}]",
                  record['source'], f"Added {record['matches_added']} matches / {record['roster_added']} rosters; malformed/ambiguous issues: {malformed}",
                  f"Snapshot: {record.get('snapshot') or 'Unavailable'}"]
        lines.extend('  ' + json.dumps(issue, ensure_ascii=False) for issue in issues)
    lines += ['', 'ADDON TRACE — latest up to 500 archived messages']
    lines.extend(f"{r['started']}  {r['raw']}" for r in reversed(data['trace']))
    lines += ['', 'WoW writes SavedVariables only on logout or /reload. Refresh reads saved data; it cannot read unsaved in-game matches.']
    return '\n'.join(lines)


class DiagnosticsView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        page_heading(self, 'Diagnostics', 'Import recovery, source snapshots and errors in one place. Your WoW files are read-only.')
        ttk.Button(self, text='Copy diagnostic information', command=lambda: app.run_job('Copying diagnostics…', lambda: app.service.copy_diagnostics(app.config['wow_root']), lambda r: app.feedback('Diagnostic information copied.'))).pack(anchor='w', pady=(0, 10))
        box = ttk.Frame(self); box.pack(fill='both', expand=True)
        self.text = tk.Text(box, bg=FIELD, fg=TEXT, insertbackground=TEXT, font=('Consolas', 10), wrap='word', relief='flat', padx=15, pady=15)
        scrollbar = ttk.Scrollbar(box, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side='left', fill='both', expand=True); scrollbar.pack(side='right', fill='y')

    def render(self, payload):
        self.text.configure(state='normal'); self.text.delete('1.0', 'end')
        self.text.insert('end', diagnostic_text(payload['diagnostics']))
        self.text.configure(state='disabled')

from tkinter import ttk
from .widgets import Table, page_heading
from .theme import palette
from ..metrics import match_key

COLUMNS = [('Date/time', 'Date / time', 150), ('Character', 'Character', 110), ('Source', 'Source', 100), ('Map display', 'Map / ID', 160),
           ('Type', 'Match type', 130), ('Status', 'Result / status', 135), ('Duration', 'Duration (s)', 100),
           ('KB', 'KB', 65), ('HK', 'HK', 65), ('Deaths', 'Deaths', 70), ('Damage', 'Damage', 110),
           ('Healing', 'Healing', 110), ('Premade present', 'Premade', 80)]


class HistoryView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        page_heading(self, 'Match history', f"Double-click a match to open its scoreboard. {palette(self)['PARTIAL_LABEL']} rows are partial; unknown results never count as losses.")
        controls = ttk.Frame(self); controls.pack(fill='x', pady=(0, 10))
        self.count = ttk.Label(controls, style='Muted.TLabel'); self.count.pack(side='left')
        ttk.Button(controls, text='Previous', command=lambda: app.change_page(-1)).pack(side='right')
        ttk.Button(controls, text='Next', command=lambda: app.change_page(1)).pack(side='right', padx=8)
        self.table = Table(self, COLUMNS, on_open=lambda row: app.open_scoreboard(match_key(row)) if row else None, on_sort=app.sort_history)
        self.table.pack(fill='both', expand=True)
        self.empty = ttk.Label(self, style='Muted.TLabel'); self.empty.pack(anchor='w', pady=8)

    def render(self, payload):
        self.table.set_rows(payload['history'])
        self.count.configure(text=f"{payload['history_count']:,} matches · Page {payload['page'] + 1} of {payload['pages']} · Up to 100 rows per page")
        self.empty.configure(text='' if payload['history'] else 'No archived matches match the current filters. Try Reset filters or Import file.')

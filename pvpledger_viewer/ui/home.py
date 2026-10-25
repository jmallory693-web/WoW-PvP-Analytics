from tkinter import ttk
from .widgets import ScrollFrame, page_heading, stat_panel
from ..viewmodels import display, percent


class HomeView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

    def render(self, payload):
        for child in self.winfo_children():
            child.destroy()
        page_heading(self, 'Your PvP ledger', 'A permanent record of every fight. Current filters apply across the dashboard.')
        summary = payload['home']['summary']
        stats = ttk.Frame(self); stats.pack(fill='x', pady=(0, 16))
        stat_panel(stats, 'ARCHIVED MATCHES', display(summary['games']), f"{summary['partial_games']} partial · current selection", 0)
        stat_panel(stats, 'RECORD', f"{summary['wins']} W  /  {summary['losses']} L", f"{summary['result_count']} known results", 1)
        stat_panel(stats, 'WIN RATE', percent(summary['win_rate']), 'All selected types combined', 2)
        scroll = ScrollFrame(self); scroll.pack(fill='both', expand=True)
        for index, card in enumerate(payload['home']['cards']):
            frame = ttk.Frame(scroll.body, style='Panel.TFrame', padding=16)
            frame.grid(row=index // 2, column=index % 2, sticky='nsew', padx=(0, 12), pady=(0, 12))
            scroll.body.columnconfigure(index % 2, weight=1, uniform='cards')
            ttk.Label(frame, text=card['character'], style='CardTitle.TLabel').pack(anchor='w')
            ttk.Label(frame, text=f"{card['realm'] or 'Realm unconfirmed'} · {card['spec'] or 'Spec unknown'} {card['class'] or ''}", style='CardMuted.TLabel').pack(anchor='w', pady=(2, 12))
            s = card['summary']; fields = s['statistics']
            if s['games']:
                ttk.Label(frame, text=f"{s['wins']} W  ·  {s['losses']} L     {percent(s['win_rate'])}", style='CardRecord.TLabel').pack(anchor='w')
                text = (f"PvP item level  {display(card['item_level'])}     Games  {s['games']}\n"
                        f"Deaths / match  {display(fields['Deaths']['mean'])}  (n={fields['Deaths']['count']})\n"
                        f"Avg team rank   Damage {display(fields['Damage rank']['mean'])} / Healing {display(fields['Healing rank']['mean'])}\n"
                        f"Last played  {card['last_played'] or 'Unknown'}")
            else:
                text = 'No matches in this selection.\nImport a SavedVariables file or widen the filters.'
            ttk.Label(frame, text=text, style='CardMuted.TLabel', justify='left', wraplength=400).pack(anchor='w', pady=(6, 8))
            actions = ttk.Frame(frame, style='Panel.TFrame'); actions.pack(fill='x')
            ttk.Button(actions, text='View history →', command=lambda c=card: self.app.select_character(c['character'], c['realm'])).pack(side='left')
            ttk.Button(actions, text='Export character…', command=lambda c=card: self.app.export_data(character=c['character'] + ('-' + c['realm'] if c['realm'] else ''))).pack(side='left', padx=8)
            ttk.Button(actions,text='Rated PvP…',command=lambda c=card:self.app.open_rated(c['character'],c['realm'])).pack(side='left')
            select = lambda event, c=card: self.app.select_character(c['character'], c['realm'])
            frame.bind('<Button-1>', select)
            for child in frame.winfo_children():
                if isinstance(child, ttk.Label):
                    child.bind('<Button-1>', select)
        if not summary['games']:
            ttk.Label(scroll.body, text='Import a file, or choose your WoW folder in Settings. WoW saves on logout or /reload.', style='Muted.TLabel', wraplength=900).grid(row=4, column=0, columnspan=2, sticky='w')

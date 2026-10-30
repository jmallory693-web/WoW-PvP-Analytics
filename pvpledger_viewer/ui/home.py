import tkinter as tk
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
            frame = ttk.Frame(scroll.body, style='Panel.TFrame', padding=18)
            frame.grid(row=index // 2, column=index % 2, sticky='nsew', padx=(0, 14), pady=(0, 16))
            scroll.body.columnconfigure(index % 2, weight=1, uniform='cards')
            heading = ttk.Frame(frame, style='Panel.TFrame'); heading.pack(fill='x')
            more = ttk.Menubutton(heading, text='⋯', width=3, takefocus=True, style='CardOverflow.TMenubutton')
            more.pack(side='right', anchor='n', padx=(8, 0))
            menu = tk.Menu(more, tearoff=False)
            menu.add_command(label='Export character…', command=lambda c=card: self.app.export_data(character=c['character'] + ('-' + c['realm'] if c['realm'] else '')))
            menu.add_command(label='Rated PvP…', command=lambda c=card: self.app.open_rated(c['character'], c['realm']))
            more.configure(menu=menu)
            name = ttk.Label(heading, text=card['character'], style='CardTitle.TLabel', wraplength=400)
            name.pack(side='left', fill='x', expand=True)
            name.bind('<Configure>', lambda event, label=name: label.configure(wraplength=max(1, event.width)))
            ttk.Label(frame, text=f"{card['realm'] or 'Realm unconfirmed'} · {card['spec'] or 'Spec unknown'} {card['class'] or ''}",
                      style='CardMuted.TLabel', wraplength=400).pack(anchor='w', pady=(3, 10))
            s = card['summary']; fields = s['statistics']
            record = ttk.Frame(frame, style='Panel.TFrame'); record.pack(fill='x')
            ttk.Label(record, text=f"{s['wins']} W  ·  {s['losses']} L", style='CardRecord.TLabel').pack(side='left')
            rate = ttk.Frame(record, style='Panel.TFrame'); rate.pack(side='right', padx=(12, 0))
            ttk.Label(rate, text='Win rate', style='CardMuted.TLabel').pack(anchor='e')
            ttk.Label(rate, text=percent(s['win_rate']), style='HomeWinRate.TLabel').pack(anchor='e')
            actions = ttk.Frame(frame, style='Panel.TFrame'); actions.pack(fill='x', pady=(8, 10))
            ttk.Button(actions, text='View history →', style='Accent.TButton',
                       command=lambda c=card: self.app.select_character(c['character'], c['realm'])).pack(side='left')
            if not s['games']:
                ttk.Label(frame, text='No matches in this selection.\nImport a SavedVariables file or widen the filters.',
                          style='CardMuted.TLabel', wraplength=400).pack(anchor='w', pady=(0, 8))
            rows = ttk.Frame(frame, style='Panel.TFrame'); rows.pack(fill='x')
            rows.columnconfigure(1, weight=1)
            for row, (label, value) in enumerate((
                ('Games', str(s['games'])),
                ('Deaths / match', f"{display(fields['Deaths']['mean'])}  (n={fields['Deaths']['count']})"),
                ('Avg damage rank', display(fields['Damage rank']['mean'])),
                ('Avg healing rank', display(fields['Healing rank']['mean'])),
                ('PvP item level', display(card['item_level'])),
                ('Last played', card['last_played'] or 'Unknown'),
            )):
                ttk.Label(rows, text=label, style='CardMuted.TLabel').grid(row=row, column=0, sticky='nw', padx=(0, 16), pady=2)
                ttk.Label(rows, text=value, style='Card.TLabel', wraplength=250).grid(row=row, column=1, sticky='nw', pady=2)
            select = lambda event, c=card: self.app.select_character(c['character'], c['realm'])
            def bind_card(widget):
                if isinstance(widget, (ttk.Label, ttk.Frame)):
                    widget.bind('<Button-1>', select)
                    for child in widget.winfo_children():
                        bind_card(child)
            bind_card(frame)
        if not summary['games']:
            ttk.Label(scroll.body, text='Import a file, or choose your WoW folder in Settings. WoW saves on logout or /reload.', style='Muted.TLabel', wraplength=900).grid(row=4, column=0, columnspan=2, sticky='w')

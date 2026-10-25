from tkinter import ttk
from .widgets import Table, page_heading
from ..viewmodels import display, percent

FIELDS = ('Damage', 'Healing', 'KB', 'HK', 'Deaths', 'Deaths per 10 minutes', 'Damage rank', 'Healing rank', 'PvP item level')


def comparison_rows(comparisons):
    rows = []
    for item in comparisons:
        # A dedicated mode row avoids implicit comparisons across arenas/BGs.
        for kind, summary in item['by_type'].items() or [('No matches', item['overall_explicitly_combined'])]:
            row = {'Character': item['character'], 'Realm': item['realm'], 'Type': kind, 'Games': summary['games'],
                   'Record': f"{summary['wins']}–{summary['losses']} (n={summary['result_count']})", 'Win rate': summary['win_rate'],
                   'Latest ilvl': item['latest_pvp_item_level']}
            for field in FIELDS:
                stats = summary['statistics'][field]
                row[field] = stats['mean']
                row[field + ' median'] = stats['median']
                row[field + ' n'] = stats['count']
            rows.append(row)
    return rows


class ComparisonView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        page_heading(self, 'Character comparison', 'Characters side by side, one match type at a time. Values show mean / median (n). Roles are not ranked against each other.')
        self.app = app; self.show_advanced = bool(app.config.get('advanced_comparison', {}).get('overview_advanced'))
        ttk.Button(self, text='Switch overview ↔ Character vs Character / My Characters', command=self.toggle).pack(anchor='w', pady=(0, 5))
        from .advanced_comparison import AdvancedComparison
        self.advanced = AdvancedComparison(self, app)
        self.tabs = ttk.Notebook(self)
        ttk.Label(self, text='Unknown values are excluded. Small samples are descriptive, not conclusive. Scroll to see every metric and character.', style='Muted.TLabel', wraplength=950).pack(side='bottom', anchor='w', pady=8)
        self.tabs.pack(fill='both', expand=True)

    def toggle(self):
        self.show_advanced = not self.show_advanced
        self.app.config['advanced_comparison']['overview_advanced'] = self.show_advanced
        self.layout()

    def layout(self):
        if self.show_advanced:
            self.tabs.pack_forget(); self.advanced.pack(fill='both', expand=True)
        else:
            self.advanced.pack_forget(); self.tabs.pack(fill='both', expand=True)

    def render(self, payload):
        self.advanced.render(payload); self.layout()
        previous = self.tabs.tab(self.tabs.select(), 'text') if self.tabs.tabs() else None
        for child in self.tabs.winfo_children():
            child.destroy()
        comparisons = payload['comparison']
        kinds = sorted({kind for c in comparisons for kind in c['by_type']}) or ['No matches']
        for kind in kinds:
            columns = [('Metric', 'Metric', 190)] + [(str(i), c['character'], 200) for i, c in enumerate(comparisons)]
            table = Table(self.tabs, columns)
            self.tabs.add(table, text=kind)
            labels = ['Realm', 'Class / specialization', 'Games', 'Wins / losses (known n)', 'Win rate', 'Latest PvP item level', *FIELDS]
            rows = [{'Metric': label} for label in labels]
            for index, character in enumerate(comparisons):
                summary = character['by_type'].get(kind)
                latest = character['recent_matches'][-1] if character['recent_matches'] else {}
                values = [character['realm'] or 'Unconfirmed', ' / '.join(filter(None, [latest.get('Class'), latest.get('Spec')])) or 'Unknown',
                          summary['games'] if summary else 0,
                          f"{summary['wins']} / {summary['losses']} (n={summary['result_count']})" if summary else '0 / 0 (n=0)',
                          percent(summary['win_rate']) if summary else 'Unknown', display(character['latest_pvp_item_level'])]
                for field in FIELDS:
                    stat = summary['statistics'][field] if summary else None
                    values.append(f"{display(stat['mean'])} / {display(stat['median'])} (n={stat['count']})" if stat else 'Unknown (n=0)')
                for row, value in zip(rows, values):
                    row[str(index)] = value
            table.set_rows(rows)
            if kind == previous:
                self.tabs.select(table)

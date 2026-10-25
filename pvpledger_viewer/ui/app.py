"""Desktop shell. All database/import/analytics/export work runs through DesktopService."""
import argparse
from dataclasses import asdict, replace
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog
from ..archive import default_home
from ..background import BackgroundTasks
from ..metrics import Filters
from ..service import DesktopService, MATCH_TYPES
from ..settings import SettingsStore, VIEWS
from .theme import apply_theme, BG, GOLD, MUTED, RED
from .home import HomeView
from .history import HistoryView
from .comparison import ComparisonView
from .allies import AlliesView
from .diagnostics import DiagnosticsView
from .scoreboard import ScoreboardWindow
from .settings import SettingsDialog
from .trends import TrendsView
from .duplicates import DuplicateReviewView


class LedgerApp:
    def __init__(self, root, home=None, autostart=True):
        # A host may reopen the viewer in the same process. Retired Tk widget
        # cycles must be finalized on this UI thread before a new worker starts.
        import gc
        gc.collect()
        self.root = root
        self.service = DesktopService(home)
        from ..setup import existing_profile
        self.needs_setup = autostart and not existing_profile(self.service.home)
        self.settings = SettingsStore(self.service.home / 'settings.json')
        self.config = self.settings.load()
        if self.config['date_mode'] in ('Last 7 Days', 'Last 30 Days', 'This Month'):
            from ..calendar_core import preset
            start, end = preset(self.config['date_mode'], zone=self.config['source_timezone'])
            self.config['filters'].update(start=start, end=end)
        self.filters = Filters(**self.config['filters'])
        self.tasks = BackgroundTasks()
        self.generation = 0; self.page = 0
        self.sort_field, self.descending = 'Date/time', True
        self.payload = None; self.closing = False; self.settings_window = None
        from ..sync import SyncSchedule
        self.sync_schedule = SyncSchedule(interval=self.config['sync_interval'])
        self.auto_sync = autostart and not self.needs_setup
        self.explicit_home = home is not None
        self.view_name = self.config['view']
        root.title('PvP Ledger Viewer')
        root.geometry(self.config['geometry']); root.minsize(1100, 650)
        apply_theme(root)
        self._build()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<F5>', lambda e: self.refresh())
        root.bind('<Control-o>', lambda e: self.import_file())
        root.bind('<Control-e>', lambda e: self.export_data())
        root.bind('<Control-comma>', lambda e: self.open_settings())
        root.report_callback_exception = self.callback_error
        root.bind('<Destroy>',self._release_variables,add='+')
        self.show_view(self.view_name)
        self.root.after(50, self.poll)
        if autostart:
            self.root.after(100, self.startup)

    def _build(self):
        sidebar = ttk.Frame(self.root, padding=(12, 18)); sidebar.pack(side='left', fill='y')
        sidebar.configure(width=190); sidebar.pack_propagate(False)
        ttk.Label(sidebar, text='PVP  LEDGER', style='Gold.TLabel').pack(anchor='w', padx=14)
        ttk.Label(sidebar, text='YOUR MATCHES.\nYOUR HISTORY.', style='Muted.TLabel', justify='left').pack(anchor='w', padx=14, pady=(8, 16))
        self.nav = {}
        for title in VIEWS:
            button = ttk.Button(sidebar, text=title, style='Nav.TButton', command=lambda name=title: self.show_view(name))
            button.pack(fill='x', pady=1); self.nav[title] = button
        ttk.Button(sidebar, text='Settings', command=self.open_settings).pack(side='bottom', fill='x', pady=(10, 0))
        self.archive_label = ttk.Label(sidebar, text='LOCAL ARCHIVE\nLoading…', style='Muted.TLabel', wraplength=165)
        self.archive_label.pack(side='bottom', anchor='w', padx=12, pady=10)
        main = ttk.Frame(self.root, padding=(22, 18)); main.pack(side='left', fill='both', expand=True)
        header = ttk.Frame(main); header.pack(fill='x', pady=(0, 14))
        ttk.Label(header, text='PvP Ledger Viewer', style='Heading.TLabel').pack(side='left')
        self.refresh_button = ttk.Button(header, text='Refresh', command=self.refresh); self.refresh_button.pack(side='right')
        export_menu = ttk.Menubutton(header, text='Export…', style='Accent.TButton')
        menu = tk.Menu(export_menu, tearoff=False)
        menu.add_command(label='Complete AI Dump', command=self.complete_ai_dump)
        menu.add_command(label='Existing CSV exports', command=self.export_data)
        menu.add_separator();menu.add_command(label='Excel reconciliation…',command=self.reconcile_excel)
        export_menu.configure(menu=menu); export_menu.pack(side='right', padx=8)
        self.import_button = ttk.Button(header, text='Import file…', command=self.import_file); self.import_button.pack(side='right')
        bar = ttk.Frame(main); bar.pack(fill='x', pady=(0, 8))
        self.variables, self.combos = {}, {}
        for index, (key, label, width, values) in enumerate([
            ('character', 'Character', 24, ['All characters']), ('match_type', 'Match type', 18, ['All types', *MATCH_TYPES, 'Unknown']),
            ('map_name', 'Map', 23, ['All maps']), ('premade', 'Queue', 12, ['Any queue', 'Solo', 'Premade']),
            ('ally', 'Ally', 14, ['Any ally'])]):
            frame = ttk.Frame(bar); frame.grid(row=0, column=index, sticky='ew', padx=(0, 8)); bar.columnconfigure(index, weight=1)
            ttk.Label(frame, text=label, style='Muted.TLabel').pack(anchor='w', pady=(0, 3))
            initial = getattr(self.filters, key)
            text = ('Premade' if initial is True else 'Solo' if initial is False else values[0]) if key == 'premade' else initial or values[0]
            variable = tk.StringVar(value=text); self.variables[key] = variable
            combo = ttk.Combobox(frame, textvariable=variable, values=values, state='readonly', width=width)
            combo.pack(fill='x'); combo.bind('<<ComboboxSelected>>', lambda e: self.apply_filters())
            self.combos[key] = combo
        dates = ttk.Frame(main); dates.pack(fill='x', pady=(0, 16))
        for key in ('start', 'end'):
            self.variables[key] = tk.StringVar(value=getattr(self.filters, key) or '')
        from .calendar import CalendarDialog
        ttk.Button(dates, text='Calendar / dates…', command=lambda: CalendarDialog(self)).pack(side='left')
        self.date_label = ttk.Label(dates, style='Muted.TLabel'); self.date_label.pack(side='left', padx=8)
        ttk.Button(dates, text='Reset filters', command=self.reset_filters).pack(side='left', padx=8)
        ttk.Button(dates, text='Copy for Claude…', command=self.copy_for_claude).pack(side='right')
        self.content = ttk.Frame(main)
        from .players import PlayersView, ArchiveStatusView
        from .rated import RatedView
        self.views = {name: cls(self.content, self) for name, cls in zip(VIEWS, (HomeView, HistoryView, ComparisonView, AlliesView, DiagnosticsView, TrendsView, DuplicateReviewView, PlayersView, ArchiveStatusView, RatedView))}
        footer = ttk.Frame(main); footer.pack(side='bottom', fill='x', pady=(10, 0))
        self.progress = ttk.Progressbar(footer, mode='indeterminate', length=110)
        self.progress.pack(side='right', padx=(12, 0))
        self.status = ttk.Label(footer, text='Opening local archive…', style='Muted.TLabel', wraplength=850)
        self.status.pack(side='left', fill='x', expand=True)
        self.content.pack(fill='both', expand=True)

    def _release_variables(self,event):
        if event.widget is self.root:
            # Destroy can also be invoked directly by a host. Release Tcl
            # variables here instead of deferring their finalizers to worker GC.
            self.variables.clear()

    def startup(self):
        if self.needs_setup:
            from .setup import SetupDialog
            self.setup_window = SetupDialog(self)
            return
        if self.config['wow_root'] or self.config['source_locations']:
            self.refresh()
        else:
            message = 'Choose the WoW installation in Settings, or use Import file. Saved matches remain available offline.'
            if self.settings.error:
                message = 'Preferences could not be loaded: ' + self.settings.error + '. ' + message
            self.reload(message)
            from ..career import recover
            self.run_job('Recovering permanent rated history…',lambda:recover(self.service.home),lambda r:None)

    def poll(self):
        if not self.root.winfo_exists():
            return
        try:
            self.tasks.drain()
        except Exception as exc:
            import sys
            self.callback_error(*sys.exc_info())
        busy = self.tasks.pending > 0
        if self.auto_sync and self.config['sync_enabled'] and not self.closing and not busy and (self.config['wow_root'] or self.config['source_locations']) and self.sync_schedule.clock() >= self.sync_schedule.next_due:
            self.refresh()
            busy = self.tasks.pending > 0
        self.refresh_button.configure(state='disabled' if busy or self.closing else 'normal')
        self.import_button.configure(state='disabled' if busy or self.closing else 'normal')
        if not busy:
            self.progress.stop()
            self.progress.pack_forget()
        if self.closing and not busy:
            self._finish_close()
            return
        self.root.after(50, self.poll)

    def run_job(self, message, work, done=None, failed=None):
        if self.closing:
            return
        self.feedback(message)
        self.progress.pack(before=self.status, side='right', padx=(12, 0))
        self.progress.start(12)
        self.tasks.submit(work, done or (lambda result: self.feedback('Done.')), failed or self.job_error)

    def feedback(self, message, error=False):
        self.status.configure(text=message, foreground=RED if error else MUTED)

    def job_error(self, error):
        self.feedback(str(error) + ' — Open Diagnostics for import details.', error=True)

    def callback_error(self, kind, value, traceback):
        import traceback as tb
        tb.print_exception(kind, value, traceback)
        self.feedback('Interface error: ' + str(value), error=True)

    def reload(self, message=None):
        self.generation += 1; generation = self.generation
        filters, page, field, descending, wow_root = self.filters, self.page, self.sort_field, self.descending, self.config['wow_root']
        def work():
            if generation != self.generation:
                return None
            return self.service.snapshot(filters, field, descending, page, wow_root=wow_root)
        def done(payload):
            if generation != self.generation or payload is None:
                return
            self.payload = payload; self.page = payload['page']
            self.date_label.configure(text=(f"{self.filters.start or 'Beginning'} → {self.filters.end or 'Latest'}" if self.filters.start or self.filters.end else 'All history') + f" · {payload['history_count']} matches")
            self.combos['character'].configure(values=['All characters'] + payload['characters'])
            self.combos['map_name'].configure(values=['All maps'] + payload['maps'])
            labels = payload.get('person_labels', {})
            self.combos['ally'].configure(values=['Any ally'] + [labels.get(p,p) for p in payload['people'] if p not in (payload['owner_person'], 'Unassigned')])
            if self.filters.ally in labels:
                self.variables['ally'].set(labels[self.filters.ally])
            for name, view in self.views.items():
                if name == self.view_name:
                    view.render(payload)
            self.archive_label.configure(text=f"LOCAL ARCHIVE\n{payload['totals']['total']:,} matches\n{payload['totals']['rosters']:,} roster rows")
            self.feedback(message or f"{payload['history_count']:,} matches in current selection. WoW saves on logout or /reload.")
        self.run_job('Updating dashboard…', work, done)

    def show_view(self, name):
        for view in self.views.values():
            view.pack_forget()
        self.view_name = name
        for title, button in self.nav.items():
            button.configure(style='Active.Nav.TButton' if title == name else 'Nav.TButton')
        view = self.views[name]; view.pack(fill='both', expand=True)
        if self.payload:
            view.render(self.payload)

    def apply_filters(self):
        values = {key: variable.get().strip() for key, variable in self.variables.items()}
        for key, placeholder in [('character', 'All characters'), ('match_type', 'All types'), ('map_name', 'All maps'), ('ally', 'Any ally')]:
            if values[key] == placeholder:
                values[key] = None
        values['premade'] = {'Any queue': None, 'Solo': False, 'Premade': True}[values['premade']]
        values['start'], values['end'] = values['start'] or None, values['end'] or None
        from ..settings import validate_settings
        try:
            validate_settings(self.config | {'filters': values})
        except ValueError as exc:
            self.feedback(str(exc), error=True); return
        self.filters = Filters(**values); self.page = 0; self.reload()

    def reset_filters(self):
        self.config['date_mode'] = 'All Time'
        for key, variable in self.variables.items():
            variable.set({'character': 'All characters', 'match_type': 'All types', 'map_name': 'All maps', 'premade': 'Any queue', 'ally': 'Any ally'}.get(key, ''))
        self.apply_filters()

    def select_character(self, name, realm=None):
        self.variables['character'].set(name + ('-' + realm if realm else ''))
        self.apply_filters(); self.show_view('Match History')

    def change_page(self, delta):
        if self.payload:
            self.page = max(0, min(self.page + delta, self.payload['pages'] - 1)); self.reload()

    def sort_history(self, field, descending):
        self.sort_field, self.descending, self.page = field, descending, 0
        self.reload()

    def open_scoreboard(self, key):
        self.run_job('Opening scoreboard…', lambda: self.service.scoreboard(key), lambda model: (ScoreboardWindow(self, key, model), self.feedback('Scoreboard opened.')))

    def open_rated(self,name=None,realm=None,player=None,others=False):
        self.show_view('Rated PvP');self.views['Rated PvP'].open_character(name,realm,player,others)

    def open_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift(); return
        self.settings_window = SettingsDialog(self)

    def refresh(self):
        if self.closing or not self.sync_schedule.claim(manual=True):
            return
        if not (self.config['wow_root'] or self.config['source_locations']):
            self.sync_schedule.finish()
            self.open_settings(); return
        root = self.config['wow_root']
        def done(report):
            self.sync_schedule.finish()
            message = f"Read {report['files']} files; added {report['matches_added']} matches and {report['rosters_added']} roster rows."
            message += f" Recognized {report['recognized']} observations; consolidated {report['consolidated']}; ambiguous pairs {report['ambiguous']}."
            if report['failures']:
                message += f" {report['failures']} import errors — see Diagnostics."
            elif not report['files']:
                message += ' No PvPLedger.lua or REFlex.lua files found; check the selected WoW folder.'
            self.reload(message)
        def failed(error):
            self.sync_schedule.finish(); self.job_error(error)
        self.run_job('Reading saved addon data…', lambda: self.service.refresh(root), done, failed)

    def complete_ai_dump(self):
        from .ai_export import AIDumpDialog
        return AIDumpDialog(self)

    def import_file(self):
        path = filedialog.askopenfilename(parent=self.root, title='Import addon data or reconcile Excel (originals read-only)', filetypes=[('Addon or Excel files','*.lua *.xlsx'),('Addon SavedVariables', '*.lua'),('Excel match log','*.xlsx')])
        if not path:
            return
        if path.lower().endswith('.xlsx'):
            self.reconcile_excel(path);return
        def done(report):
            self.reload(f"Added {report['matches_added']} matches / {report['rosters_added']} roster rows. Recognized {report['recognized']}; consolidated {report['consolidated']}; ambiguous pairs {report['ambiguous']}; {report['failures']} errors.")
        self.run_job('Snapshotting and importing source…', lambda: self.service.refresh(files=[path]), done)

    def reconcile_excel(self,path=None):
        from .reconciliation import ReconciliationWindow
        return ReconciliationWindow(self,path)

    def export_data(self, ally=None, character=None):
        destination = filedialog.askdirectory(parent=self.root, title='Export filtered CSVs outside WoW', initialdir=self.config['export_dir'] or None)
        if not destination:
            return
        self.config['export_dir'] = destination
        filters, wow_root = self.filters, self.config['wow_root']
        self.run_job('Exporting CSVs…', lambda: self.service.export(destination, filters, character=character, ally=ally, wow_root=wow_root),
                     lambda manifest: self.feedback(f"Exported {len(manifest)} character/person folders to {destination}"))

    def copy_for_claude(self):
        count = simpledialog.askinteger('Copy for Claude', 'Latest matching matches to include:', initialvalue=self.config['report_limit'], minvalue=1, parent=self.root)
        if count is None:
            return
        self.config['report_limit'] = count
        filters = self.filters
        self.run_job('Preparing and copying CSV report…', lambda: self.service.copy_report(filters, count),
                     lambda r: self.feedback(f"Copied complete report ({r['characters']:,} characters)."))

    def close(self):
        if self.closing:
            return
        self.closing = True
        for child in self.root.winfo_children():
            event = getattr(child, 'cancel_event', None)
            if event is not None:event.set()
        self.feedback('Finishing archive work and saving preferences…')
        # Drain outstanding worker results before saving preferences and exiting.

    def _finish_close(self):
        config = self.config | {'geometry': self.root.geometry(), 'filters': asdict(self.filters), 'view': self.view_name}
        self.closing = False
        def end(result):
            self.tasks.close(); self.root.destroy()
        self.tasks.submit(lambda: self.settings.save(config), end, lambda exc: (print('Settings save failed:', exc), end(None)))
        self.closing = True
        self.root.after(50, self._close_poll)

    def _close_poll(self):
        self.tasks.drain()
        if not self.tasks.closed:
            self.root.after(50, self._close_poll)


def main(argv=None):
    parser = argparse.ArgumentParser(description='PvP Ledger Viewer desktop')
    parser.add_argument('--archive-dir', help='Default: %%APPDATA%%/PvPLedgerViewer')
    args = parser.parse_args(argv)
    root = tk.Tk()
    try:
        import ctypes
        if hasattr(ctypes, 'windll'):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('PvPLedgerViewer.Desktop')
        LedgerApp(root, args.archive_dir)
        root.mainloop()
    except Exception:
        root.destroy()
        raise


if __name__ == '__main__':
    main()

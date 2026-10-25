import tkinter as tk
from tkinter import ttk
from datetime import date
import calendar
from ..calendar_core import month_days, shift_month, preset


class CalendarDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title('Archive dates'); self.transient(app.root)
        self.resizable(False, False)
        self.counts = (app.payload or {}).get('calendar', {})
        initial = app.filters.start or (max(self.counts) if self.counts else date.today().isoformat())
        stamp = date.fromisoformat(initial); self.year, self.month = stamp.year, stamp.month
        self.mode = tk.StringVar(value=app.config.get('date_mode', 'All Time'))
        self.start, self.end = app.filters.start, app.filters.end
        self.picking_end = False
        body = ttk.Frame(self, padding=18); body.pack(fill='both', expand=True)
        ttk.Label(body, text='Archive calendar', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(body, text='* marks archived matches under the other shared filters. Empty days can be selected.', wraplength=510).pack(anchor='w', pady=6)
        modes = ttk.Frame(body); modes.pack(fill='x')
        for mode in ('Single Day', 'Date Range'):
            ttk.Radiobutton(modes, text=mode, value=mode, variable=self.mode, command=self.reset_pick).pack(side='left', padx=8)
        quick = ttk.Frame(body); quick.pack(fill='x', pady=8)
        for name in ('Last 7 Days', 'Last 30 Days', 'This Month', 'All Time'):
            ttk.Button(quick, text=name, command=lambda n=name: self.quick(n)).pack(side='left', padx=2)
        nav = ttk.Frame(body); nav.pack(fill='x', pady=6)
        for label, offset in [('« Year', -12), ('‹ Month', -1)]:
            ttk.Button(nav, text=label, command=lambda o=offset: self.move(o)).pack(side='left')
        self.title_label = ttk.Label(nav, width=19, anchor='center'); self.title_label.pack(side='left')
        for label, offset in [('Month ›', 1), ('Year »', 12)]:
            ttk.Button(nav, text=label, command=lambda o=offset: self.move(o)).pack(side='left')
        self.grid_body = ttk.Frame(body); self.grid_body.pack(fill='both')
        self.selection = ttk.Label(body, wraplength=540); self.selection.pack(fill='x', pady=10)
        buttons = ttk.Frame(body); buttons.pack(fill='x')
        ttk.Button(buttons, text='Cancel', command=self.destroy).pack(side='left')
        ttk.Button(buttons, text='Apply dates', style='Accent.TButton', command=self.apply).pack(side='right')
        self.render(); self.bind('<Escape>', lambda e: self.destroy()); self.after_idle(self.focus_set)

    def reset_pick(self):
        self.picking_end = False

    def move(self, offset):
        try:
            self.year, self.month = shift_month(self.year, self.month, offset)
            self.render()
        except ValueError:
            pass

    def pick(self, stamp):
        if self.mode.get() != 'Date Range':
            self.mode.set('Single Day'); self.start = self.end = stamp
        elif not self.picking_end:
            self.start = self.end = stamp; self.picking_end = True
        else:
            self.start, self.end = sorted((self.start, stamp)); self.picking_end = False
        self.render()

    def quick(self, name):
        self.mode.set(name)
        self.start, self.end = preset(name, zone=self.app.config['source_timezone'])
        self.picking_end = False
        if self.start:
            d = date.fromisoformat(self.start); self.year, self.month = d.year, d.month
        self.render()

    def render(self):
        self.title_label.configure(text=f'{calendar.month_name[self.month]} {self.year}')
        for child in self.grid_body.winfo_children():
            child.destroy()
        for i, day in enumerate(('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')):
            ttk.Label(self.grid_body, text=day, anchor='center').grid(row=0, column=i, sticky='ew')
        for w, week in enumerate(month_days(self.year, self.month), 1):
            for c, day in enumerate(week):
                stamp = day.isoformat(); count = self.counts.get(stamp, 0)
                selected = self.start and self.end and self.start <= stamp <= self.end
                text = f'{day.day}' + (f' *{count}' if count else '')
                button = ttk.Button(self.grid_body, text=text, width=9, style='Accent.TButton' if selected else 'TButton', command=lambda s=stamp: self.pick(s))
                button.grid(row=w, column=c, padx=1, pady=2, sticky='ew')
                if day.month != self.month:
                    button.configure(text='(' + text + ')')
        count = sum(n for d, n in self.counts.items() if (not self.start or self.start <= d) and (not self.end or d <= self.end))
        self.selection.configure(text=f"{self.mode.get()}: {self.start or 'Beginning'} → {self.end or 'Today / latest'} · {count} archived matches" + (' · Choose the range end.' if self.picking_end else ''))

    def apply(self):
        if self.mode.get() in ('Single Day', 'Date Range') and not self.start:
            self.selection.configure(text='Select a date first.'); return
        self.app.variables['start'].set(self.start or ''); self.app.variables['end'].set(self.end or '')
        self.app.config['date_mode'] = self.mode.get()
        self.app.apply_filters(); self.destroy()

    def destroy(self):
        super().destroy()
        self.mode = None  # Release Tcl variables on Tk's thread, not cyclic GC in a worker.

import tkinter as tk
from tkinter import ttk, filedialog
from ..trends import METRICS
from ..charts import draw_chart, export_png, RENDER_LOCK
from .widgets import page_heading
from .theme import CHART_ANNOTATION_FONT_SIZE, TEXT as CHART_ANNOTATION_TEXT, palette, chart_palette


class TrendsView(ttk.Frame):
    def destroy(self):
        canvas=self.canvas
        if canvas is not None:
            widget=canvas.get_tk_widget()
            for name in ('_idle_draw_id','_event_loop_id'):
                timer=getattr(canvas,name,None)
                if timer:widget.after_cancel(timer);setattr(canvas,name,None)
            widget.destroy();canvas._tkphoto=None;canvas.figure.set_canvas(None)
            self.canvas=None
        super().destroy()
        self.mode=self.metric=self.window=self.threshold=self.teammate=None

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.model, self.serial = app, None, 0
        page_heading(self, 'Performance trends', 'Archive history · shared filters above · teammate comparisons show your performance when playing together.')
        toolbar = ttk.Frame(self); toolbar.pack(fill='x', pady=(0, 5))
        ttk.Label(toolbar, text='Mode').pack(side='left')
        self.mode = tk.StringVar(value=app.config.get('trend_comparison_mode', 'Dashboard'))
        selector = ttk.Combobox(toolbar, values=['Dashboard', 'Me vs Friends', 'My Characters'], textvariable=self.mode, state='readonly', width=25); selector.pack(side='left', padx=6)
        selector.bind('<<ComboboxSelected>>', lambda e: self.switch_mode())
        from .advanced_comparison import AdvancedComparison
        self.advanced = AdvancedComparison(self, app, 'Me vs Friends')
        self.standard = ttk.Frame(self); self.standard.pack(fill='both', expand=True)
        controls = ttk.Frame(self.standard); controls.pack(fill='x')
        self.metric = tk.StringVar(value=app.config['trend_metric'])
        self.window = tk.StringVar(value=str(app.config['trend_window']))
        self.threshold = tk.StringVar(value=str(app.config['trend_threshold']))
        self.teammate = tk.BooleanVar(value=False)
        ttk.Label(controls, text='Metric').pack(side='left')
        combo = ttk.Combobox(controls, values=METRICS, textvariable=self.metric, state='readonly', width=23)
        combo.pack(side='left', padx=6); combo.bind('<<ComboboxSelected>>', lambda e: self.redraw())
        ttk.Label(controls, text='Window').pack(side='left')
        ttk.Spinbox(controls, from_=1, to=10000, textvariable=self.window, width=5).pack(side='left', padx=6)
        ttk.Label(controls, text='Gear threshold').pack(side='left')
        ttk.Entry(controls, textvariable=self.threshold, width=6).pack(side='left', padx=6)
        ttk.Button(controls, text='Apply', command=self.request).pack(side='left')
        ttk.Button(controls, text='Export PNG…', command=self.export).pack(side='right')
        row = ttk.Frame(self.standard); row.pack(fill='x', pady=6)
        ttk.Label(row, text='Teammates\nCtrl-click multiple').pack(side='left')
        self.people = tk.Listbox(row, height=3, selectmode='extended', exportselection=False,
                                 bg=palette(self)['FIELD'], fg=palette(self)['TEXT'], selectbackground=palette(self)['LIST_SELECTION_BG'], width=25)
        self.people.pack(side='left', padx=10)
        ttk.Checkbutton(row, text='Plot teammate comparisons', variable=self.teammate, command=self.redraw).pack(side='left')
        ttk.Button(row, text='Samples and gear groups…', command=self.show_details).pack(side='right')
        self.detail = ttk.Label(self.standard, style='Muted.TLabel', wraplength=1000)
        self.detail.pack(side='bottom', fill='x', pady=5)
        self.holder = ttk.Frame(self.standard); self.holder.pack(fill='both', expand=True)
        self.canvas = None

    def render(self, payload):
        self.payload = payload
        self.advanced.render(payload)
        self.switch_mode(render=False)
        if self.mode.get() != 'Dashboard':
            return
        previous_labels = getattr(self, 'person_labels', {})
        selected = [next((p for p,l in previous_labels.items() if l == self.people.get(i)), self.people.get(i)) for i in self.people.curselection()] or self.app.config['trend_teammates']
        self.person_labels = payload.get('person_labels', {p:p for p in payload['people']})
        self.people.delete(0, 'end')
        for person in payload['people']:
            if person not in (payload['owner_person'], 'Unassigned'):
                index = self.people.size(); self.people.insert('end', self.person_labels.get(person, person))
                if person in selected:
                    self.people.selection_set(index)
        self.request()

    def switch_mode(self, render=True):
        mode = self.mode.get(); self.app.config['trend_comparison_mode'] = mode
        if mode == 'Dashboard':
            self.advanced.pack_forget(); self.standard.pack(fill='both', expand=True)
            if render and hasattr(self, 'payload'):
                self.render(self.payload)
        else:
            self.standard.pack_forget(); self.advanced.pack(fill='both', expand=True)
            self.advanced.mode.set(mode); self.advanced.layout()

    def request(self):
        try:
            window, threshold = int(self.window.get()), float(self.threshold.get())
            from ..settings import validate_settings
            labels = getattr(self, 'person_labels', {})
            people = [next((p for p,l in labels.items() if l == self.people.get(i)), self.people.get(i)) for i in self.people.curselection()]
            config = validate_settings(self.app.config | {'trend_window': window, 'trend_threshold': threshold,
                                      'trend_metric': self.metric.get(), 'trend_teammates': people})
        except ValueError as exc:
            self.app.feedback(str(exc), error=True); return
        self.app.config.update(config)
        self.serial += 1; serial = self.serial
        filters = self.app.filters
        def done(model):
            if serial == self.serial and self.winfo_exists():
                self.model = model; self.redraw()
                self.app.feedback(f'Trends ready: {model["matches"]} matches. Full windows require {window} known results per character/type.')
        self.app.run_job('Preparing archive trends…', lambda: self.app.service.trends(filters, window, threshold, people), done)

    def redraw(self):
        if self.model is None or not self.winfo_ismapped():
            return
        self.app.config['trend_metric'] = self.metric.get()
        if self.canvas is None:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            class LockedCanvas(FigureCanvasTkAgg):
                def draw(self):
                    with RENDER_LOCK:
                        super().draw()
            self.figure = Figure(figsize=(10, 4), dpi=100)
            self.canvas = LockedCanvas(self.figure, master=self.holder)
            self.canvas.get_tk_widget().pack(fill='both', expand=True)
            self.canvas.mpl_connect('motion_notify_event', self.hover)
        colors = chart_palette(self)
        self.axis, self.lines = draw_chart(self.figure, self.model, self.metric.get(), self.teammate.get(), palette=colors)
        self.annotation = self.axis.annotate('', xy=(0, 0), xytext=(10, 12), textcoords='offset points',
                                             bbox={'boxstyle': 'round', 'fc': CHART_ANNOTATION_TEXT}, fontsize=CHART_ANNOTATION_FONT_SIZE)
        self.annotation.set_visible(False)
        from ..chart_style import style_annotation
        style_annotation(self.annotation, colors)
        gear = []
        for group in self.model['series']:
            g = group['gear']; low, high = g['below'], g['at_or_above']
            def rate(v):
                return f'{v["win_rate"]:.1f}%' if v['win_rate'] is not None else 'Unknown'
            gear.append(f'{group["label"]}: below {self.model["threshold"]:g} n={low["matches"]}, W% {rate(low)} (known n={low["known_results"]}); at/above n={high["matches"]}, W% {rate(high)} (known n={high["known_results"]}); unknown gear n={g["unknown_item_level"]}')
        # Keep all group metrics available in a scrollable detail dialog.
        self.summary_text = self.model['note'] + '\n\n' + '\n'.join(gear)
        self.detail.configure(text=f'{self.model["matches"]} matches · full {self.model["window"]}-result windows · threshold {self.model["threshold"]:g}. Gear associations are not causal. Double-click here for all sample/gear/teammate statistics.')
        self.detail.bind('<Double-1>', lambda e: self.show_details())
        with RENDER_LOCK:
            self.canvas.draw_idle()

    def hover(self, event):
        if not self.canvas or event.inaxes != self.axis:
            return
        for line, points in self.lines:
            hit, info = line.contains(event)
            if hit and info['ind'].size:
                i = int(info['ind'][0]); point = points[i]
                self.annotation.xy = (i + 1, point['value'])
                self.annotation.set_text(f'{point["date"]} · {point["key"][2]}\n{point["value"]:,.2f} · n={point["count"]}')
                self.annotation.set_visible(True); self.canvas.draw_idle(); return
        if self.annotation.get_visible():
            self.annotation.set_visible(False); self.canvas.draw_idle()

    def show_details(self):
        if self.model is None:
            return
        dialog = tk.Toplevel(self); dialog.title('Trend samples and comparisons'); dialog.geometry('1000x650')
        text = tk.Text(dialog, wrap='word', bg=palette(self)['FIELD'], fg=palette(self)['TEXT'])
        scroll = ttk.Scrollbar(dialog, command=text.yview); scroll.pack(side='right', fill='y')
        text.configure(yscrollcommand=scroll.set); text.pack(fill='both', expand=True)
        text.insert('end', self.summary_text + '\n\nOWNER PERFORMANCE WITH/WITHOUT TEAMMATES\nSelected owner characters combined within each labeled match type. A match appears once in the union.\n')
        def summary(label, data):
            rate = f'{data["win_rate"]:.1f}%' if data['win_rate'] is not None else 'Unknown'
            text.insert('end', f'  {label}: {data["matches"]} matches; win rate {rate} (known results n={data["known_results"]})\n')
            for metric, values in data['metrics'].items():
                def number(value):
                    return f'{value:,.2f}' if value is not None else 'Unknown'
                text.insert('end', f'    {metric}: mean {number(values["mean"])}, median {number(values["median"])}, n={values["count"]}\n')
        for group in self.model['teammates']:
            text.insert('end', f'\n{group["label"]} · {group["mode"]}\n')
            summary('Together', group['with']); summary('Without', group['without'])
        text.insert('end', '\n\nGEAR PERFORMANCE GROUPS\n')
        for group in self.model['series']:
            text.insert('end', '\n' + group['label'] + '\n')
            summary(f'Below {self.model["threshold"]:g}', group['gear']['below'])
            summary(f'At or above {self.model["threshold"]:g}', group['gear']['at_or_above'])
        text.configure(state='disabled'); dialog.bind('<Escape>', lambda e: dialog.destroy()); dialog.focus_set()

    def export(self):
        if self.model is None:
            return
        path = filedialog.asksaveasfilename(parent=self.app.root, title='Export trend PNG outside WoW',
                                           initialdir=self.app.config['export_dir'] or None,
                                           initialfile='PvPLedger-trend.png', defaultextension='.png', filetypes=[('PNG image', '*.png')])
        if not path:
            return
        model, metric, teammate = self.model, self.metric.get(), self.teammate.get()
        colors = chart_palette(self)
        def work():
            self.app.service._guard_export(path, self.app.config['wow_root'])
            return export_png(path, model, metric, teammate, palette=colors)
        self.app.run_job('Exporting chart…', work, lambda p: self.app.feedback(f'Chart saved to {p}'))

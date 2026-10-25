"""Chart workflow with dialog-local loading, validation and error feedback."""
from copy import deepcopy
import logging
import tkinter as tk
from tkinter import ttk, filedialog
from .widgets import ScrollFrame
from .theme import MUTED, RED
from ..comparisons import METRICS
from ..charts import RENDER_LOCK


class ComparisonChartDialog(tk.Toplevel):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel, self.app = panel, panel.app
        self.title('Comparison metrics and charts')
        self.geometry('1100x700'); self.minsize(720, 420)
        self.serial = 0
        self.chart_canvas = self.displayed_model = None
        self.displayed_metrics = []
        top = ttk.Frame(self, padding=10); top.pack(fill='x')
        ttk.Label(top, text='Ctrl-click metrics; each uses a separate scale.').pack(side='left')
        selection = ttk.Frame(top); selection.pack(side='left', padx=10)
        self.chosen = tk.Listbox(selection, selectmode='extended', exportselection=False,
                                 height=3, bg='#0e1928', fg='#e7edf5', selectbackground='#304460')
        self.chosen.pack(side='left')
        scrollbar = ttk.Scrollbar(selection, command=self.chosen.yview)
        scrollbar.pack(side='right', fill='y'); self.chosen.configure(yscrollcommand=scrollbar.set)
        for i, metric in enumerate(METRICS):
            self.chosen.insert('end', metric)
            if metric in panel.metrics:
                self.chosen.selection_set(i)
        self.draw_button = ttk.Button(top, text='Draw metrics', command=self.render)
        self.draw_button.pack(side='left')
        self.export_button = ttk.Button(top, text='Export PNG…', command=self.export, state='disabled')
        self.export_button.pack(side='left', padx=6)
        self.status = ttk.Label(self, padding=(10, 5), wraplength=1000)
        self.status.pack(fill='x')
        self.holder = ScrollFrame(self); self.holder.pack(fill='both', expand=True)
        self.message = ttk.Label(self.holder.body, padding=30, wraplength=650)
        self.message.pack(fill='x')
        self.bind('<Configure>', self.resize_message)
        self.bind('<Escape>', lambda e: self.destroy())
        self.after_idle(self.render)

    def resize_message(self, event):
        if event.widget is self:
            self.status.configure(wraplength=max(300, event.width - 30))

    def say(self, message, error=False):
        self.status.configure(text=message, foreground=RED if error else MUTED)

    def clear_chart(self, message):
        self.dispose_canvas()
        for child in self.holder.body.winfo_children():
            child.destroy()
        self.chart_canvas = self.displayed_model = None
        self.displayed_metrics = []
        self.export_button.configure(state='disabled')
        self.message = ttk.Label(self.holder.body, text=message, padding=30, wraplength=650)
        self.message.pack(fill='x')

    def dispose_canvas(self):
        canvas = self.chart_canvas
        if canvas is not None:
            widget = canvas.get_tk_widget()
            for timer in ('_idle_draw_id', '_event_loop_id'):
                ticket = getattr(canvas, timer, None)
                if ticket:
                    widget.after_cancel(ticket)
                    setattr(canvas, timer, None)
            widget.destroy()
            # Matplotlib canvases contain cycles. Release the Tk image on the
            # GUI thread now, before a database worker can trigger cyclic GC.
            canvas._tkphoto = None
            canvas.figure.set_canvas(None)
            self.chart_canvas = None

    def destroy(self):
        self.serial += 1
        self.dispose_canvas()
        super().destroy()

    def failure(self, error):
        if not self.winfo_exists():
            return
        self.draw_button.configure(state='normal')
        self.clear_chart('Unable to draw this comparison. ' + str(error))
        self.say('Chart error: ' + str(error) + '. Adjust the selection and click Draw metrics to retry.', True)
        # Windowed EXEs have no visible stderr; retain the traceback for diagnosis.
        try:
            import traceback
            with (self.app.service.home / 'chart_errors.log').open('a', encoding='utf8') as stream:
                traceback.print_exception(type(error), error, error.__traceback__, file=stream)
        except OSError:
            logging.getLogger(__name__).exception('Unable to record chart error')

    def render(self):
        self.serial += 1; serial = self.serial
        try:
            selected = [self.chosen.get(i) for i in self.chosen.curselection()]
            if not selected:
                raise ValueError('Select at least one metric from the list.')
            selections = deepcopy(self.panel.selections())
            low, high = (float(v.get()) if v.get().strip() else None for v in (self.panel.low, self.panel.high))
            scope, filters = self.panel.scope.get(), deepcopy(self.app.filters)
            window = self.app.config['trend_window']
            self.panel.metrics = selected
            self.panel.persist()
        except ValueError as exc:
            self.clear_chart('Choose comparison participants on the main screen, then open Charts / metrics.\n' + str(exc))
            self.say(str(exc), True)
            return
        self.clear_chart('Loading comparison from the permanent archive…')
        self.say('Loading selected participants, scope and shared filters…')
        self.draw_button.configure(state='disabled')
        service = self.app.service
        def done(model):
            if not self.winfo_exists() or serial != self.serial:
                return
            self.draw_button.configure(state='normal')
            try:
                self.draw_model(model, selected)
            except Exception as exc:
                self.failure(exc)
        def failed(error):
            if self.winfo_exists() and serial == self.serial:
                self.failure(error)
        self.app.run_job('Preparing comparison charts…',
                         lambda: service.compare(selections, scope, filters, window, low, high), done, failed)

    def draw_model(self, model, selected):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from ..comparison_charts import draw
        self.dispose_canvas()
        for child in self.holder.body.winfo_children():
            child.destroy()
        figure = Figure(figsize=(10, 3.5 * len(selected)), dpi=100)
        canvas = FigureCanvasTkAgg(figure, master=self.holder.body)
        self.chart_canvas = canvas
        canvas.get_tk_widget().configure(height=350 * len(selected))
        canvas.get_tk_widget().pack(fill='x', expand=True)
        with RENDER_LOCK:
            draw(figure, model, selected); canvas.draw()
        self.chart_canvas = canvas
        self.displayed_model, self.displayed_metrics = deepcopy(model), list(selected)
        self.export_button.configure(state='normal')
        counts = ' | '.join(f"{s['label']}: {s['summary']['games']} games" for s in model['series'])
        compatible = any(axis.lines for axis in figure.axes)
        self.say((model['scope'] + ' · ' + counts) if compatible else
                 'No data for this comparison with the selected metrics. Change participants, filters or metrics. ' + counts)

    def export(self):
        if self.displayed_model is None:
            self.say('Draw a comparison successfully before exporting.', True); return
        try:
            path = filedialog.asksaveasfilename(parent=self, initialdir=self.app.config['export_dir'] or None,
                                                initialfile='PvPLedger-comparison.png', defaultextension='.png',
                                                filetypes=[('PNG', '*.png')])
            if not path:
                return
            # Export the displayed snapshot, even if the list selection changed afterward.
            model, selected = deepcopy(self.displayed_model), list(self.displayed_metrics)
            service, wow_root = self.app.service, self.app.config['wow_root']
            def work():
                from ..comparison_charts import export_png
                service._guard_export(path, wow_root)
                return export_png(path, model, selected)
            def saved(path):
                if self.winfo_exists():
                    self.say('PNG saved: ' + str(path))
            def failed(error):
                if self.winfo_exists():
                    self.say('PNG export failed: ' + str(error), True)
            self.say('Exporting the displayed chart…')
            self.app.run_job('Exporting comparison charts…', work, saved, failed)
        except Exception as exc:
            self.say('PNG export failed: ' + str(exc), True)

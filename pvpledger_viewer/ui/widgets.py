import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from ..viewmodels import display, sort_records
from .theme import palette


class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=palette(self)['BG'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas)
        self.item = self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.body.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.item, width=e.width))
        self.top = self.winfo_toplevel()
        self.wheel_binding = self.top.bind('<MouseWheel>', self._wheel, add='+')

    def _wheel(self, event):
        if str(event.widget).startswith(str(self)):
            self.canvas.yview_scroll(-int(event.delta / 120), 'units')

    def destroy(self):
        self.top.unbind('<MouseWheel>', self.wheel_binding)
        super().destroy()


class Table(ttk.Frame):
    def __init__(self, parent, columns, height=12, on_open=None, on_sort=None):
        super().__init__(parent)
        self.columns, self.rows, self.sort_state = columns, [], None
        self.on_sort = on_sort
        self.on_open = on_open
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show='headings', height=height, selectmode='browse')
        for field, label, width in columns:
            self.tree.heading(field, text=label, command=lambda f=field: self.sort(f))
            self.tree.column(field, width=width, minwidth=width, stretch=True, anchor='w')
        vertical = ttk.Scrollbar(self, orient='vertical', command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)
        self.tree.tag_configure('win', foreground=palette(self)['TEAL'])
        self.tree.tag_configure('loss', foreground=palette(self)['RED'])
        self.tree.tag_configure('partial', foreground=palette(self)['GOLD'])
        self.tree.tag_configure('self', foreground=palette(self)['GOLD'], background=palette(self)['SELF_ROW_BG'])
        self.tree.tag_configure('premade', foreground=palette(self)['TEAL'])
        if on_open:
            self.tree.bind('<Double-1>', self._open_row)
            self.tree.bind('<Return>', lambda e: self.open_selected())

    def _open_row(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.open_selected()

    def open_selected(self):
        selected = self.selected()
        if selected and self.on_open:
            self.on_open(selected)

    def selected(self):
        selection = self.tree.selection()
        return self.rows[int(selection[0])] if selection else None

    def set_rows(self, rows):
        self.rows = rows
        # Keep complete values readable after a resize; overflow uses the scrollbar.
        font = tkfont.nametofont('TkDefaultFont')
        heading_font = tkfont.Font(self, font=ttk.Style(self).lookup('Treeview.Heading', 'font') or font)
        for field, label, width in self.columns:
            minimum = max(width, heading_font.measure(label + ' ▼') + 24,
                          max((font.measure(display(row.get(field))) + 18 for row in rows), default=0))
            self.tree.column(field, minwidth=minimum, width=max(minimum, self.tree.column(field, 'width')))
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(rows):
            tag = row.get('Highlight') or ('partial' if row.get('_partial') else ('win' if row.get('Result') == 'W' else ('loss' if row.get('Result') == 'L' else '')))
            self.tree.insert('', 'end', iid=str(index), values=[display(row.get(c[0])) for c in self.columns], tags=(tag,))

    def sort(self, field):
        descending = not self.sort_state[1] if self.sort_state and self.sort_state[0] == field else True
        self.sort_state = (field, descending)
        for f, label, _ in self.columns:
            self.tree.heading(f, text=label + (' ▼' if descending else ' ▲') if f == field else label)
        if self.on_sort:
            self.on_sort(field, descending)
        else:
            self.set_rows(sort_records(self.rows, field, descending))


def page_heading(parent, title, subtitle):
    ttk.Label(parent, text=title, style='Title.TLabel').pack(anchor='w')
    ttk.Label(parent, text=subtitle, style='Muted.TLabel', wraplength=950).pack(anchor='w', pady=(3, 15))


def stat_panel(parent, title, value, detail='', column=0):
    panel = ttk.Frame(parent, style='Panel.TFrame', padding=12)
    panel.grid(row=0, column=column, sticky='nsew', padx=(0, 10))
    parent.columnconfigure(column, weight=1, uniform='stats')
    ttk.Label(panel, text=title, style='CardMuted.TLabel').pack(anchor='w')
    ttk.Label(panel, text=value, style='Value.TLabel').pack(anchor='w', pady=(2, 0))
    ttk.Label(panel, text=detail, style='CardMuted.TLabel').pack(anchor='w')
    return panel

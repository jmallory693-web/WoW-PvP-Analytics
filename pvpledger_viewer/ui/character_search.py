import tkinter as tk
from tkinter import ttk
from ..comparisons import suggestions
from .theme import palette


class CharacterSearch(ttk.Frame):
    """Typing only suggests; Enter or a mouse choice explicitly confirms identity."""
    def __init__(self, parent, label):
        super().__init__(parent)
        self.label = ttk.Label(self, text=label); self.label.pack(anchor='w')
        self.text = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.text); self.entry.pack(fill='x')
        self.list = tk.Listbox(self, height=3, exportselection=False, bg=palette(self)['FIELD'], fg=palette(self)['TEXT'], selectbackground=palette(self)['LIST_SELECTION_BG'])
        self.list.pack(fill='x')
        self.entries, self.hits, self.selected = [], [], None
        self.trace_id = self.text.trace_add('write', self.changed)
        self.entry.bind('<Down>', self.down)
        self.entry.bind('<Return>', self.confirm)
        self.list.bind('<Return>', self.confirm)
        self.list.bind('<ButtonRelease-1>', self.confirm)

    def set_entries(self, entries):
        self.entries = entries
        if self.selected:
            current = next((e for e in entries if e['key'] == self.selected['key']), None)
            self.selected = current
            if current:
                self.text.set(current['label'])
        self.changed()

    def changed(self, *args):
        if self.selected and self.text.get() != self.selected['label']:
            self.selected = None
        self.hits = [self.selected] if self.selected else suggestions(self.entries, self.text.get())
        self.list.delete(0, 'end')
        for hit in self.hits:
            self.list.insert('end', hit['label'])

    def down(self, event=None):
        if self.hits:
            self.list.focus_set(); self.list.selection_clear(0, 'end'); self.list.selection_set(0); self.list.activate(0)
        return 'break'

    def confirm(self, event=None):
        chosen = self.list.curselection()
        if not chosen and self.hits and event is not None and getattr(event, 'keysym', '') == 'Return':
            chosen = (0,)
        if chosen:
            self.selected = self.hits[chosen[0]]
            self.text.set(self.selected['label'])
            self.entry.focus_set()
        return 'break'

    def restore(self, key):
        found = next((e for e in self.entries if e['key'] == key), None)
        if found:
            self.selected = found; self.text.set(found['label'])

    def destroy(self):
        if self.text is not None:
            self.text.trace_remove('write', self.trace_id)
        super().destroy()
        self.text = None

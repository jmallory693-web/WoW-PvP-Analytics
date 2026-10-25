from tkinter import ttk
from tkinter import font as tkfont

BG = '#0c1420'
PANEL = '#142131'
FIELD = '#0e1928'
TEXT = '#e7edf5'
MUTED = '#a3b2c5'
GOLD = '#d8b56c'
TEAL = '#6cd4b0'
RED = '#f28b94'


def apply_theme(root):
    root.configure(bg=BG)
    tkfont.nametofont('TkDefaultFont').configure(family='Segoe UI', size=10)
    root.option_add('*TCombobox*Listbox.background', FIELD)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground', '#304460')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=BG, foreground=TEXT, font=('Segoe UI', 10))
    style.configure('TFrame', background=BG)
    style.configure('Panel.TFrame', background=PANEL)
    style.configure('TLabel', background=BG, foreground=TEXT)
    style.configure('TCheckbutton',background=BG,foreground=TEXT)
    style.map('TCheckbutton',background=[('active',BG),('focus',BG)],foreground=[('disabled',MUTED),('active',TEXT),('focus',TEXT)])
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('Title.TLabel', font=('Segoe UI Semibold', 24))
    style.configure('Heading.TLabel', font=('Segoe UI Semibold', 15))
    style.configure('Gold.TLabel', foreground=GOLD, font=('Segoe UI Semibold', 11))
    style.configure('Card.TLabel', background=PANEL)
    style.configure('CardTitle.TLabel', background=PANEL, font=('Segoe UI Semibold', 17))
    style.configure('CardMuted.TLabel', background=PANEL, foreground=MUTED)
    style.configure('Value.TLabel', background=PANEL, foreground=GOLD, font=('Segoe UI Semibold', 25))
    style.configure('CardRecord.TLabel', background=PANEL, foreground=GOLD, font=('Segoe UI Semibold', 20))
    style.configure('TButton', background='#24364b', foreground=TEXT, borderwidth=0, padding=(12, 8))
    style.map('TButton', background=[('active', '#344d67'), ('disabled', PANEL)], foreground=[('disabled', '#77869a')])
    style.configure('Accent.TButton', background=GOLD, foreground='#101620', font=('Segoe UI Semibold', 10))
    style.map('Accent.TButton', background=[('active', '#eccd89'), ('disabled', '#625b48')])
    style.configure('Nav.TButton', anchor='w', padding=(18, 13), background=BG)
    style.configure('Active.Nav.TButton', anchor='w', padding=(18, 13), background=PANEL, foreground=GOLD)
    style.configure('TEntry', fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, padding=6)
    style.configure('TCombobox', fieldbackground=FIELD, background=PANEL, foreground=TEXT, padding=5, arrowsize=14)
    style.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', TEXT)], selectbackground=[('readonly', FIELD)], selectforeground=[('readonly', TEXT)])
    style.configure('TSpinbox', fieldbackground=FIELD, foreground=TEXT, padding=6, arrowsize=14)
    style.configure('Treeview', background=FIELD, fieldbackground=FIELD, foreground=TEXT, rowheight=29, borderwidth=0)
    style.configure('Treeview.Heading', background=PANEL, foreground=MUTED, relief='flat', padding=(8, 9), font=('Segoe UI Semibold', 10))
    style.map('Treeview', background=[('selected', '#304660')], foreground=[('selected', '#ffffff')])
    style.map('Treeview.Heading', background=[('active', '#2b3b50')])
    style.configure('TNotebook', background=BG, borderwidth=0)
    style.configure('TNotebook.Tab', background=PANEL, padding=(18, 10))
    style.map('TNotebook.Tab', background=[('selected', '#2b4057')], foreground=[('selected', GOLD)])
    style.configure('Horizontal.TProgressbar', background=GOLD, troughcolor=PANEL, borderwidth=0)
    style.configure('TScrollbar', background='#2c4157', troughcolor=FIELD, borderwidth=0, arrowsize=12)

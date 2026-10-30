from tkinter import ttk
from tkinter import font as tkfont
from types import MappingProxyType
from ..settings import THEME_NAMES

BG = '#0c1420'
PANEL = '#142131'
FIELD = '#0e1928'
TEXT = '#e7edf5'
MUTED = '#a3b2c5'
GOLD = '#d8b56c'
TEAL = '#6cd4b0'
RED = '#f28b94'



# Classic palette roles; keep distinct roles even where current values coincide.
LIST_SELECTION_BG = '#304460'
BUTTON_BG = '#24364b'
BUTTON_ACTIVE_BG = '#344d67'
DISABLED_TEXT = '#77869a'
ACCENT_TEXT = '#101620'
ACCENT_ACTIVE_BG = '#eccd89'
ACCENT_DISABLED_BG = '#625b48'
TABLE_SELECTION_BG = '#304660'
TABLE_SELECTION_TEXT = '#ffffff'
TABLE_HEADING_ACTIVE_BG = '#2b3b50'
TAB_SELECTED_BG = '#2b4057'
SCROLLBAR_BG = '#2c4157'
SELF_ROW_BG = '#2d2c26'

UI_FONT_FAMILY = 'Segoe UI'
UI_FONT_SIZE = 10
DEFAULT_FONT = (UI_FONT_FAMILY, UI_FONT_SIZE)
TITLE_FONT = ('Segoe UI Semibold', 24)
HEADING_FONT = ('Segoe UI Semibold', 15)
GOLD_FONT = ('Segoe UI Semibold', 11)
CARD_TITLE_FONT = ('Segoe UI Semibold', 17)
VALUE_FONT = ('Segoe UI Semibold', 25)
CARD_RECORD_FONT = ('Segoe UI Semibold', 20)
EMPHASIS_FONT = ('Segoe UI Semibold', 10)
MONOSPACE_FONT = ('Consolas', 10)
CHART_ANNOTATION_FONT_SIZE = 8


_CLASSIC_KEYS = (
    'BG', 'PANEL', 'FIELD', 'TEXT', 'MUTED', 'GOLD', 'TEAL', 'RED',
    'LIST_SELECTION_BG', 'BUTTON_BG', 'BUTTON_ACTIVE_BG', 'DISABLED_TEXT',
    'ACCENT_TEXT', 'ACCENT_ACTIVE_BG', 'ACCENT_DISABLED_BG', 'TABLE_SELECTION_BG',
    'TABLE_SELECTION_TEXT', 'TABLE_HEADING_ACTIVE_BG', 'TAB_SELECTED_BG',
    'SCROLLBAR_BG', 'SELF_ROW_BG', 'UI_FONT_FAMILY', 'UI_FONT_SIZE', 'DEFAULT_FONT',
    'TITLE_FONT', 'HEADING_FONT', 'GOLD_FONT', 'CARD_TITLE_FONT', 'VALUE_FONT',
    'CARD_RECORD_FONT', 'EMPHASIS_FONT', 'MONOSPACE_FONT',
)
CLASSIC = MappingProxyType({key: globals()[key] for key in _CLASSIC_KEYS} | {
    'SIDEBAR_TITLE_FONT': GOLD_FONT,
    'PARTIAL_LABEL': 'Gold', 'SELF_LABEL': 'gold', 'ALLY_LABEL': 'teal',
    'SIDEBAR': BG, 'BORDER': PANEL, 'ACCENT': GOLD, 'ACCENT_HOVER': ACCENT_ACTIVE_BG,
    'ON_ACCENT': ACCENT_TEXT, 'BUTTON': BUTTON_BG, 'BUTTON_HOVER': BUTTON_ACTIVE_BG,
    'SELECTED': TABLE_SELECTION_BG, 'DISABLED': DISABLED_TEXT,
    'POSITIVE': TEAL, 'NEGATIVE': RED,
})
_WARBAND_VALUES = {
    'BG': '#121111', 'SIDEBAR': '#0d0c0c', 'PANEL': '#1c1a1a', 'FIELD': '#161414',
    'BORDER': '#4a2a27', 'ACCENT': '#c8463d', 'ACCENT_HOVER': '#d65a50',
    'ON_ACCENT': '#121111', 'BUTTON': '#2a2424', 'BUTTON_HOVER': '#3a3030',
    'SELECTED': '#3a2523', 'TEXT': '#e9dfcf', 'MUTED': '#9a8f84',
    'DISABLED': '#6b625a', 'POSITIVE': '#8fbf6a', 'NEGATIVE': '#e08a6e',
}
_WARBAND_VALUES.update({
    'MONOSPACE_FONT': DEFAULT_FONT,
    'PARTIAL_LABEL': 'Crimson', 'SELF_LABEL': 'crimson', 'ALLY_LABEL': 'green',
    'GOLD': _WARBAND_VALUES['ACCENT'], 'TEAL': _WARBAND_VALUES['POSITIVE'],
    'RED': _WARBAND_VALUES['NEGATIVE'],
    'LIST_SELECTION_BG': _WARBAND_VALUES['SELECTED'],
    'BUTTON_BG': _WARBAND_VALUES['BUTTON'], 'BUTTON_ACTIVE_BG': _WARBAND_VALUES['BUTTON_HOVER'],
    'DISABLED_TEXT': _WARBAND_VALUES['DISABLED'], 'ACCENT_TEXT': _WARBAND_VALUES['ON_ACCENT'],
    'ACCENT_ACTIVE_BG': _WARBAND_VALUES['ACCENT_HOVER'], 'ACCENT_DISABLED_BG': _WARBAND_VALUES['BUTTON'],
    'TABLE_SELECTION_BG': _WARBAND_VALUES['SELECTED'], 'TABLE_SELECTION_TEXT': _WARBAND_VALUES['TEXT'],
    'TABLE_HEADING_ACTIVE_BG': _WARBAND_VALUES['BUTTON_HOVER'], 'TAB_SELECTED_BG': _WARBAND_VALUES['SELECTED'],
    'SCROLLBAR_BG': _WARBAND_VALUES['BUTTON'], 'SELF_ROW_BG': _WARBAND_VALUES['SELECTED'],
})
WARBAND = MappingProxyType(dict(CLASSIC) | _WARBAND_VALUES)
PALETTES = MappingProxyType({'Warband': WARBAND, 'Classic': CLASSIC})


def palette(widget):
    """Resolve the palette of this widget's application, never mutable imports."""
    root = getattr(widget, 'root', widget)
    return getattr(root._root(), '_ledger_palette', WARBAND)


def chart_palette(widget):
    """Resolve once on the UI thread; None preserves the original Classic charts."""
    root = getattr(widget, 'root', widget)._root()
    return palette(widget) if getattr(root, '_ledger_theme', 'Warband') == 'Warband' else None


def apply_theme(root, name='Warband'):
    """Apply once before constructing widgets. Saved changes require a restart."""
    name = name if isinstance(name, str) and name in THEME_NAMES else 'Warband'
    p = dict(PALETTES[name])
    root._ledger_font_available = False
    if name == 'Warband':
        from .fonts import register_cinzel
        root._ledger_font_available = register_cinzel(root)
        family = 'Cinzel' if root._ledger_font_available else 'Georgia'
        for key in ('TITLE_FONT', 'HEADING_FONT', 'SIDEBAR_TITLE_FONT', 'CARD_TITLE_FONT'):
            p[key] = (family, CLASSIC[key][1])
    root._ledger_theme = name
    root._ledger_palette = MappingProxyType(p)

    root.configure(bg=p['BG'])
    tkfont.nametofont('TkDefaultFont').configure(family=p['UI_FONT_FAMILY'], size=p['UI_FONT_SIZE'])
    root.option_add('*TCombobox*Listbox.background', p['FIELD'])
    root.option_add('*TCombobox*Listbox.foreground', p['TEXT'])
    root.option_add('*TCombobox*Listbox.selectBackground', p['LIST_SELECTION_BG'])
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=p['BG'], foreground=p['TEXT'], font=p['DEFAULT_FONT'])
    style.configure('TFrame', background=p['BG'])
    style.configure('Panel.TFrame', background=p['PANEL'])
    style.configure('TLabel', background=p['BG'], foreground=p['TEXT'])
    style.configure('TCheckbutton',background=p['BG'],foreground=p['TEXT'])
    style.map('TCheckbutton',background=[('active',p['BG']),('focus',p['BG'])],foreground=[('disabled',p['MUTED']),('active',p['TEXT']),('focus',p['TEXT'])])
    style.configure('Muted.TLabel', foreground=p['MUTED'])
    style.configure('Title.TLabel', font=p['TITLE_FONT'])
    style.configure('Heading.TLabel', font=p['HEADING_FONT'])
    style.configure('Gold.TLabel', foreground=p['GOLD'], font=p['GOLD_FONT'])
    style.configure('Card.TLabel', background=p['PANEL'])
    style.configure('CardTitle.TLabel', background=p['PANEL'], font=p['CARD_TITLE_FONT'])
    if name == 'Warband':
        style.configure('CardTitle.TLabel', foreground=p['ACCENT'])
    style.configure('CardMuted.TLabel', background=p['PANEL'], foreground=p['MUTED'])
    style.configure('Value.TLabel', background=p['PANEL'], foreground=p['GOLD'], font=p['VALUE_FONT'])
    style.configure('CardRecord.TLabel', background=p['PANEL'], foreground=p['GOLD'], font=p['CARD_RECORD_FONT'])
    style.configure('TButton', background=p['BUTTON_BG'], foreground=p['TEXT'], borderwidth=0, padding=(12, 8))
    style.map('TButton', background=[('active', p['BUTTON_ACTIVE_BG']), ('disabled', p['PANEL'])], foreground=[('disabled', p['DISABLED_TEXT'])])
    style.configure('Accent.TButton', background=p['GOLD'], foreground=p['ACCENT_TEXT'], font=p['EMPHASIS_FONT'])
    style.map('Accent.TButton', background=[('active', p['ACCENT_ACTIVE_BG']), ('disabled', p['ACCENT_DISABLED_BG'])])
    style.configure('Nav.TButton', anchor='w', padding=(18, 13), background=p['BG'])
    style.configure('Active.Nav.TButton', anchor='w', padding=(18, 13), background=p['PANEL'], foreground=p['GOLD'])
    style.configure('TEntry', fieldbackground=p['FIELD'], foreground=p['TEXT'], insertcolor=p['TEXT'], padding=6)
    style.configure('TCombobox', fieldbackground=p['FIELD'], background=p['PANEL'], foreground=p['TEXT'], padding=5, arrowsize=14)
    style.map('TCombobox', fieldbackground=[('readonly', p['FIELD'])], foreground=[('readonly', p['TEXT'])], selectbackground=[('readonly', p['FIELD'])], selectforeground=[('readonly', p['TEXT'])])
    style.configure('TSpinbox', fieldbackground=p['FIELD'], foreground=p['TEXT'], padding=6, arrowsize=14)
    style.configure('Treeview', background=p['FIELD'], fieldbackground=p['FIELD'], foreground=p['TEXT'], rowheight=29, borderwidth=0)
    style.configure('Treeview.Heading', background=p['PANEL'], foreground=p['MUTED'], relief='flat', padding=(8, 9), font=p['EMPHASIS_FONT'])
    style.map('Treeview', background=[('selected', p['TABLE_SELECTION_BG'])], foreground=[('selected', p['TABLE_SELECTION_TEXT'])])
    style.map('Treeview.Heading', background=[('active', p['TABLE_HEADING_ACTIVE_BG'])])
    style.configure('TNotebook', background=p['BG'], borderwidth=0)
    style.configure('TNotebook.Tab', background=p['PANEL'], padding=(18, 10))
    style.map('TNotebook.Tab', background=[('selected', p['TAB_SELECTED_BG'])], foreground=[('selected', p['GOLD'])])
    style.configure('Horizontal.TProgressbar', background=p['GOLD'], troughcolor=p['PANEL'], borderwidth=0)
    style.configure('TScrollbar', background=p['SCROLLBAR_BG'], troughcolor=p['FIELD'], borderwidth=0, arrowsize=12)

    # Sidebar styles preserve Classic values without changing layout.
    style.configure('Sidebar.TFrame', background=p['SIDEBAR'])
    style.configure('SidebarGold.TLabel', background=p['SIDEBAR'], foreground=p['GOLD'], font=p['SIDEBAR_TITLE_FONT'])
    style.configure('SidebarMuted.TLabel', background=p['SIDEBAR'], foreground=p['MUTED'])
    style.configure('Nav.TButton', background=p['SIDEBAR'])
    if name == 'Warband':
        style.configure('Active.Nav.TButton', background=p['SELECTED'], foreground=p['ACCENT'])
        # Combined W/L summaries are neutral; individual loss/error tags use NEGATIVE.
        style.configure('Value.TLabel', foreground=p['TEXT'])
        style.configure('CardRecord.TLabel', foreground=p['TEXT'])
        style.configure('.', bordercolor=p['BORDER'], lightcolor=p['BORDER'], darkcolor=p['BORDER'])
        style.configure('TEntry', selectbackground=p['SELECTED'], selectforeground=p['TEXT'])
        style.configure('TSpinbox', background=p['BUTTON'], insertcolor=p['TEXT'], arrowcolor=p['TEXT'])
        style.configure('TCombobox', arrowcolor=p['TEXT'])
        style.configure('TNotebook', bordercolor=p['BORDER'], lightcolor=p['BORDER'], darkcolor=p['BORDER'])
        style.configure('TNotebook.Tab', bordercolor=p['BORDER'], lightcolor=p['BORDER'], darkcolor=p['BORDER'])
        style.configure('TScrollbar', arrowcolor=p['TEXT'])
        style.map('TScrollbar', background=[('disabled', p['PANEL']),
                                            ('pressed', p['BUTTON_HOVER']), ('active', p['BUTTON_HOVER'])])
        style.configure('TCheckbutton', indicatorbackground=p['FIELD'], indicatorforeground=p['TEXT'],
                        upperbordercolor=p['BORDER'], lowerbordercolor=p['BORDER'])
        style.map('TCheckbutton', indicatorbackground=[('disabled', p['PANEL']), ('active', p['BUTTON_HOVER'])])
        style.map('TEntry', foreground=[('disabled', p['DISABLED'])])
        style.map('TSpinbox', foreground=[('disabled', p['DISABLED'])])
        style.map('TCombobox', foreground=[('disabled', p['DISABLED']), ('readonly', p['TEXT'])])
        style.map('TNotebook.Tab', background=[('selected', p['SELECTED']), ('active', p['BUTTON_HOVER'])],
                  foreground=[('disabled', p['DISABLED']), ('selected', p['ACCENT'])],
                  lightcolor=[('', p['BORDER'])], darkcolor=[('', p['BORDER'])],
                  bordercolor=[('', p['BORDER'])])
        # Theme native Tk widgets, including dialogs with no explicit colors.
        for kind in ('Toplevel', 'Canvas', 'Menu'):
            root.option_add(f'*{kind}.background', p['BG'])
        # tkinter's built-in input prompts use native Tk controls rather than ttk.
        for kind in ('Frame', 'Label', 'Button', 'Entry'):
            root.option_add(f'*{kind}.background', p['BG'])
        for kind in ('Label', 'Button', 'Entry'):
            root.option_add(f'*{kind}.foreground', p['TEXT'])
            root.option_add(f'*{kind}.font', p['DEFAULT_FONT'])
        for option, value in {'background': p['FIELD'], 'insertBackground': p['TEXT'],
                              'selectBackground': p['SELECTED'], 'selectForeground': p['TEXT'],
                              'disabledBackground': p['PANEL'], 'disabledForeground': p['DISABLED'],
                              'readonlyBackground': p['FIELD'], 'highlightBackground': p['BORDER'],
                              'highlightColor': p['ACCENT']}.items():
            root.option_add(f'*Entry.{option}', value)
        for option, value in {'background': p['BUTTON'], 'activeBackground': p['BUTTON_HOVER'],
                              'activeForeground': p['TEXT'], 'disabledForeground': p['DISABLED'],
                              'highlightBackground': p['BORDER']}.items():
            root.option_add(f'*Button.{option}', value)
        for kind in ('Listbox', 'Text', 'Spinbox', 'Menu'):
            for option, value in {'background': p['FIELD'], 'foreground': p['TEXT'],
                                  'selectBackground': p['SELECTED'], 'selectForeground': p['TEXT'],
                                  'highlightBackground': p['BORDER'], 'highlightColor': p['ACCENT'],
                                  'font': p['DEFAULT_FONT']}.items():
                root.option_add(f'*{kind}.{option}', value)
        for kind in ('Text', 'Spinbox'):
            root.option_add(f'*{kind}.insertBackground', p['TEXT'])
        root.option_add('*Spinbox.buttonBackground', p['BUTTON'])
        root.option_add('*Spinbox.disabledForeground', p['DISABLED'])
        root.option_add('*Listbox.disabledForeground', p['DISABLED'])
        root.option_add('*Menu.activeBackground', p['SELECTED'])
        root.option_add('*Menu.activeForeground', p['TEXT'])
        root.option_add('*TCombobox*Listbox.selectForeground', p['TEXT'])
    # Layout-specific styles do not change other screens' shared typography.
    style.configure('Sidebar.Nav.TButton', padding=(14, 8))
    style.configure('Active.Sidebar.Nav.TButton', padding=(14, 8),
                    background=style.lookup('Active.Nav.TButton', 'background'), foreground=p['GOLD'])
    style.configure('HomeWinRate.TLabel', background=p['PANEL'], foreground=p['POSITIVE'], font=p['VALUE_FONT'])
    style.configure('CardOverflow.TMenubutton', background=p['PANEL'], foreground=p['TEXT'], padding=(6, 2))
    style.map('CardOverflow.TMenubutton', background=[('active', p['BUTTON_ACTIVE_BG'])],
              foreground=[('disabled', p['DISABLED_TEXT'])])
    return root._ledger_palette

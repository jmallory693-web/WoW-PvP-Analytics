"""Theme preference and startup behavior; no visual-value assertions."""
import time
import tkinter as tk
from tkinter import ttk
import pytest
from pvpledger_viewer.settings import SettingsStore, validate_settings
from pvpledger_viewer.ui.app import LedgerApp
from pvpledger_viewer.ui.theme import apply_theme, palette
from pvpledger_viewer.ui import fonts


@pytest.mark.parametrize('value', ['unknown', '', None, 42, [], {}])
def test_invalid_theme_falls_back_without_losing_preferences(value):
    saved = validate_settings({'theme': value, 'view': 'Match History', 'trend_window': 7})
    assert saved['theme'] == 'Warband'
    assert saved['view'] == 'Match History' and saved['trend_window'] == 7


def test_settings_without_theme_use_warband(tmp_path):
    store = SettingsStore(tmp_path / 'settings.json')
    assert store.load()['theme'] == 'Warband'
    store.path.write_text('{"view":"Match History","trend_window":7}', encoding='utf8')
    assert store.load()['theme'] == 'Warband'
    assert store.load()['view'] == 'Match History'


@pytest.mark.parametrize('name', ['Classic', 'Warband'])
def test_settings_dialog_saves_theme_for_next_startup(tmp_path, name):
    # A restart is a new process, with its own Tcl interpreter and private fonts.
    import subprocess
    import sys
    from pathlib import Path
    script = ("import runpy,sys; "
              "runpy.run_path(sys.argv[1])['_theme_session'](sys.argv[2],sys.argv[3],sys.argv[4])")
    for mode in ('save', 'restart'):
        result = subprocess.run([sys.executable, '-c', script, str(Path(__file__).resolve()),
                                 str(tmp_path), name, mode], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr


def _theme_session(home, name, mode):
    from pathlib import Path
    home = Path(home)
    old = 'Classic' if name == 'Warband' else 'Warband'
    store = SettingsStore(home / 'settings.json')
    if mode == 'save':
        store.save({'theme': old, 'view': 'Match History', 'trend_window': 7, 'sync_enabled': False})
    root = tk.Tk(); root.withdraw()
    app = LedgerApp(root, home, autostart=False)
    try:
        assert root._ledger_theme == (old if mode == 'save' else name)
        assert palette(app.views['Match History']) is root._ledger_palette
        if mode == 'save':
            app.open_settings(); dialog = app.settings_window
            dialog.theme.set(name)
            body = dialog.winfo_children()[0]
            button = next(w for w in body.winfo_children()
                          if isinstance(w, ttk.Button) and w.cget('text') == 'Save settings')
            button.invoke()
            until = time.monotonic() + 15
            while app.tasks.pending and time.monotonic() < until:
                root.update(); time.sleep(.01)
            assert not app.tasks.pending and not dialog.winfo_exists()
            assert store.load()['theme'] == name
            assert root._ledger_theme == old  # No partial live-theme changes.
        assert store.load()['view'] == 'Match History' and store.load()['trend_window'] == 7
    finally:
        app.close()
        until = time.monotonic() + 10
        while not app.tasks.closed and time.monotonic() < until:
            root.update(); time.sleep(.01)
        assert app.tasks.closed


@pytest.mark.parametrize('failure', ['missing', 'error'])
def test_font_failure_does_not_prevent_theme_startup(tmp_path, failure):
    import subprocess
    import sys
    from pathlib import Path
    script = ("import runpy,sys; "
              "runpy.run_path(sys.argv[1])['_font_failure_session'](sys.argv[2],sys.argv[3])")
    result = subprocess.run([sys.executable, '-c', script, str(Path(__file__).resolve()),
                             str(tmp_path), failure], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def _font_failure_session(home, failure):
    from pathlib import Path
    if failure == 'missing':
        fonts.resource_path = lambda relative: Path(home) / 'missing.ttf'
    else:
        def unavailable(path):
            raise OSError('Font registration unavailable')
        fonts._register_private = unavailable
    root = tk.Tk(); root.withdraw()
    try:
        apply_theme(root, 'Warband')
        assert root._ledger_theme == 'Warband'
        assert not root._ledger_font_available
        assert ttk.Label(root, text='Still running').winfo_exists()
    finally:
        root.destroy()

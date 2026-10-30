"""Navigation and character-card commands, in fresh native Windows sessions."""
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.parametrize('theme', ['Warband', 'Classic'])
def test_sidebar_and_home_commands(tmp_path, theme):
    script = "import runpy,sys; runpy.run_path(sys.argv[1])['_session'](sys.argv[2],sys.argv[3])"
    result = subprocess.run([sys.executable, '-c', script, str(Path(__file__).resolve()),
                             str(tmp_path), theme], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def _session(folder, theme):
    from copy import deepcopy
    import time
    import tkinter as tk
    from tkinter import ttk
    from pvpledger_viewer.service import DesktopService
    from pvpledger_viewer.settings import SettingsStore, VIEWS
    from pvpledger_viewer.ui.app import LedgerApp
    from pvpledger_viewer.ui.widgets import ScrollFrame
    from pvpledger_viewer.viewmodels import display, percent
    home = Path(folder)
    DesktopService(home).refresh(files=[Path(__file__).parent / 'fixtures/PvPLedger.lua'])
    SettingsStore(home / 'settings.json').save({'theme': theme, 'sync_enabled': False})
    root = tk.Tk(); root.geometry('1280x720')
    app = LedgerApp(root, home, autostart=False); errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    def pump():
        deadline = time.monotonic() + 30
        for _ in range(3):
            root.update()
            while app.tasks.pending and time.monotonic() < deadline:
                root.update(); time.sleep(.01)
        assert not errors and not app.tasks.pending, errors
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    try:
        app.reload(); pump()
        expected = ['Home', 'Match History', 'Rated PvP', 'Trends', 'Allies', 'All Players',
                    'Character Comparison', 'Archive Status', 'Diagnostics', 'Duplicate Review']
        assert list(app.nav) == expected and set(app.nav) == set(VIEWS)
        groups = [app.nav[name].master for name in ('Home', 'Allies', 'Archive Status')]
        assert [next(w.cget('text') for w in group.winfo_children() if isinstance(w, ttk.Label))
                for group in groups] == ['Play', 'People', 'Archive']
        for name in expected:
            app.nav[name].invoke(); pump()
            assert app.view_name == name and app.views[name].winfo_viewable()
            assert app.nav[name].winfo_viewable()
            assert app.nav[name].winfo_rooty() + app.nav[name].winfo_height() <= root.winfo_rooty() + root.winfo_height()
        app.nav['Home'].invoke(); pump()
        payload = deepcopy(app.payload)
        first = payload['home']['cards'][0]
        missing = deepcopy(first)
        missing.update(character='A deliberately long fictional character name for wrapping', realm=None,
                       item_level=None, last_played=None)
        missing['summary'].update(games=0, wins=0, losses=0, win_rate=None)
        for field in ('Deaths', 'Damage rank', 'Healing rank'):
            missing['summary']['statistics'][field].update(mean=None, count=0)
        payload['home']['cards'] = [first, missing]
        view = app.views['Home']; view.render(payload); root.update()
        scroll = next(w for w in view.winfo_children() if isinstance(w, ScrollFrame))
        cards = list(scroll.body.winfo_children())
        history, exports, rated = [], [], []
        app.select_character = lambda name, realm: history.append((name, realm))
        app.export_data = lambda **kw: exports.append(kw['character'])
        app.open_rated = lambda name, realm: rated.append((name, realm))
        for frame, model in zip(cards, payload['home']['cards']):
            children = list(descendants(frame))
            button = next(w for w in children if isinstance(w, ttk.Button))
            assert button.cget('text') == 'View history →'
            button.invoke()
            trigger = next(w for w in children if isinstance(w, ttk.Menubutton))
            menu = trigger.nametowidget(str(trigger.cget('menu')))
            assert [menu.entrycget(i, 'label') for i in (0, 1)] == ['Export character…', 'Rated PvP…']
            menu.invoke(0); menu.invoke(1)
            assert history[-1] == rated[-1] == (model['character'], model['realm'])
            assert exports[-1] == model['character'] + ('-' + model['realm'] if model['realm'] else '')
            labels = [w for w in children if isinstance(w, ttk.Label)]
            for label in ('Games', 'Deaths / match', 'Avg damage rank', 'Avg healing rank', 'PvP item level', 'Last played'):
                assert any(w.cget('text') == label for w in labels)
            assert any(w.cget('text') == percent(model['summary']['win_rate']) for w in labels)
            labels[0].event_generate('<Button-1>')
            assert history[-1] == (model['character'], model['realm'])
        values = [w.cget('text') for w in descendants(cards[0]) if isinstance(w, ttk.Label)]
        assert display(first['summary']['statistics']['Damage rank']['mean']) in values
        assert display(first['summary']['statistics']['Healing rank']['mean']) in values
        assert display(first['item_level']) in values and first['last_played'] in values
        assert f"{display(first['summary']['statistics']['Deaths']['mean'])}  (n={first['summary']['statistics']['Deaths']['count']})" in values
        missing_values = [w.cget('text') for w in descendants(cards[1]) if isinstance(w, ttk.Label)]
        assert 'Unknown' in missing_values and '0' in missing_values
        assert any('No matches in this selection.' in value for value in missing_values)
        for size in ('1600x900', '1280x720'):
            root.geometry(size); root.update()
            assert all(button.winfo_viewable() for button in app.nav.values())
    finally:
        app.close(); deadline = time.monotonic() + 10
        while not app.tasks.closed and time.monotonic() < deadline:
            root.update(); time.sleep(.01)
        assert app.tasks.closed

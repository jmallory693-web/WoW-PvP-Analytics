import hashlib
from pathlib import Path
import pytest
from pvpledger_viewer.archive import Archive, default_home
from pvpledger_viewer.identity import IdentityMap
from pvpledger_viewer.metrics import Filters, performance
from pvpledger_viewer.service import DesktopService
from pvpledger_viewer.settings import SettingsStore, validate_settings
from pvpledger_viewer.trends import (rolling_results, threshold_groups, prepare_trends, metric_value)
from pvpledger_viewer.charts import chart_series, export_png
from pvpledger_viewer.runtime import resource_path
from test_core import FIXTURE


def record(i, result='W', **values):
    return {'Character': 'Asterknight', 'Realm': 'ExampleRealm', 'Match ID': f'20261022-{i:06d}',
            'Type': 'Battleground', 'Result': result, **values}


def test_full_valid_result_rolling_windows():
    rows = [record(1), record(2, None, _partial=True), record(3, 'L'), record(4)]
    points = rolling_results(rows, 2)
    assert [p['value'] for p in points] == [50, 50]
    assert [p['key'][2] for p in points] == ['20261022-000003', '20261022-000004']
    assert all(p['count'] == 2 for p in points)
    assert not rolling_results(rows, 20)
    assert rolling_results([record(1, 'L')], 1)[0]['value'] == 0


@pytest.mark.parametrize('window', [0, -1, True, 1.5, 10001])
def test_invalid_windows(window):
    with pytest.raises(ValueError):
        rolling_results([], window)


def test_threshold_boundary_missing_and_samples():
    rows = [record(1, 'W', **{'PvP item level': 343, 'Damage': 100}),
            record(2, 'L', **{'PvP item level': 344, 'Damage': 200}),
            record(3, None, **{'PvP item level': 345, 'Damage': None}), record(4)]
    groups = threshold_groups(rows)
    assert groups['below']['matches'] == 1
    assert groups['at_or_above']['matches'] == 2
    assert groups['at_or_above']['known_results'] == 1
    assert groups['at_or_above']['win_rate'] == 0
    assert groups['at_or_above']['metrics']['Damage']['mean'] == 200
    assert groups['at_or_above']['metrics']['Damage']['count'] == 1
    assert groups['unknown_item_level'] == 1


@pytest.mark.parametrize('threshold', [0, -1, float('nan'), float('inf'), True, '344'])
def test_invalid_thresholds(threshold):
    with pytest.raises(ValueError):
        threshold_groups([], threshold)


def test_missing_zero_and_minutes_definitions():
    assert metric_value({'Damage': 0, 'Minutes played': 2}, 'Damage per minute') == 0
    assert metric_value({'Damage': 100, 'Minutes played': 2}, 'Damage per minute') == 50
    for duration in (None, 0, -1):
        assert metric_value({'Healing': 100, 'Minutes played': duration}, 'Healing per minute') is None
    row = performance(record(1, **{'Deaths': 2, 'Minutes played': 5}), [])
    assert metric_value(row, 'Deaths per 10 minutes') == 4
    assert metric_value(record(1), 'Damage rank') is None


def test_types_characters_dedup_and_teammate_union(tmp_path):
    identities = IdentityMap(tmp_path / 'people.json')
    rows = [record(1, Damage=10), record(2, 'L', Damage=20), record(3, Type='Brawl', Damage=30)]
    roster = [{'Owner character': 'Asterknight', 'Owner realm': 'ExampleRealm', 'Match ID': m['Match ID'],
               'Player': p, 'Realm': 'SandboxRealm', 'Team': 'Mine', 'Is me': 'No'}
              for m in rows[:2] for p in ('Emberguard', 'Pebblebrew')]
    model = prepare_trends(rows + [rows[0]], roster, identities, window=2, teammates=['Buddy A', 'Buddy B', 'Buddy A'])
    assert model['matches'] == 3 and len(model['series']) == 2
    union = next(g for g in model['teammates'] if g['label'].endswith('(union)') and g['mode'] == 'Battleground')
    assert union['with']['matches'] == 2 and union['with']['win_rate'] == 50
    assert union['with']['metrics']['Damage']['mean'] == 15
    assert union['without']['matches'] == 0
    assert len(chart_series(model, 'Damage', True)) == 6
    filtered = prepare_trends(rows, roster, identities, Filters(match_type='Brawl'))
    assert filtered['matches'] == 1


def test_chart_data_nulls_and_sparse_history(tmp_path):
    model = prepare_trends([record(1, Damage=None), record(2, Damage=0)], [], IdentityMap(tmp_path / 'people.json'))
    data = chart_series(model, 'Damage')[0]
    assert [p['value'] for p in data['points']] == [None, 0]
    assert data['count'] == 1 and data['mean'] == 0
    assert chart_series(model, 'Win rate')[0]['points'] == []
    assert prepare_trends([], [], IdentityMap(tmp_path / 'people.json'))['series'] == []


def test_real_fixture_metric_regression_and_png(tmp_path):
    service = DesktopService(tmp_path / 'archive')
    service.refresh(files=[FIXTURE])
    model = service.trends(window=2, teammates=['Buddy A', 'Buddy B'])
    assert model['matches'] == 10
    assert sum(g['summary']['known_results'] for g in model['series']) == 7
    assert sum(g['summary']['metrics']['Deaths per 10 minutes']['count'] for g in model['series']) == 5
    for metric in ('Win rate', 'Damage per minute', 'Healing rank', 'Deaths per 10 minutes', 'PvP item level'):
        path = export_png(tmp_path / f'{metric}.png', model, metric)
        assert path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
        from PIL import Image
        with Image.open(path) as image:
            assert image.size == (1560, 840)
    with pytest.raises(ValueError):
        chart_series(model, 'Invented metric')


def test_chart_export_rejects_wow(tmp_path):
    with pytest.raises(ValueError):
        export_png(tmp_path / 'World of Warcraft' / 'chart.png', {}, 'Damage')


def test_small_chart_labels_and_teammate_legend_fit(tmp_path):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from pvpledger_viewer.charts import draw_chart
    service = DesktopService(tmp_path / 'archive'); service.refresh(files=[FIXTURE])
    model = service.trends(window=2, teammates=['Buddy A', 'Buddy B', 'Buddy C'])
    figure = Figure(figsize=(10, 2.7), dpi=100)
    canvas = FigureCanvasAgg(figure)
    axis, _ = draw_chart(figure, model, 'Damage per minute', True)
    canvas.draw(); renderer = canvas.get_renderer()
    for artist in (axis.xaxis.label, axis.get_legend()):
        bounds = artist.get_window_extent(renderer)
        assert bounds.x0 >= 0 and bounds.y0 >= 0
        assert bounds.x1 <= figure.bbox.width and bounds.y1 <= figure.bbox.height


def test_settings_upgrade_persists_trends_and_original_preferences(tmp_path):
    store = SettingsStore(tmp_path / 'settings.json')
    store.path.write_text('{"wow_root":"C:/Games/WoW","report_limit":42}')
    old = store.load()
    assert old['trend_window'] == 20 and old['trend_threshold'] == 344
    store.save(old | {'trend_window': 5, 'trend_threshold': 350, 'trend_teammates': ['Buddy A'], 'trend_metric': 'Healing'})
    loaded = store.load()
    assert loaded['wow_root'] == 'C:/Games/WoW' and loaded['report_limit'] == 42
    assert (loaded['trend_window'], loaded['trend_metric'], loaded['trend_teammates']) == (5, 'Healing', ['Buddy A'])


def test_frozen_resources_never_redirect_user_data(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'bundle'), raising=False)
    monkeypatch.setenv('APPDATA', str(tmp_path / 'profile'))
    assert resource_path('matplotlib/mpl-data') == tmp_path / 'bundle/matplotlib/mpl-data'
    assert default_home() == tmp_path / 'profile/PvPLedgerViewer'
    with pytest.raises(ValueError):
        resource_path('../archive.sqlite')


def test_tk_hover_reports_match_date_and_window_sample(tmp_path, monkeypatch):
    import tkinter as tk
    from matplotlib.backend_bases import MouseEvent
    from pvpledger_viewer.ui.app import LedgerApp
    home = tmp_path / 'archive'; service = DesktopService(home); service.refresh(files=[FIXTURE])
    root = tk.Tk(); root.withdraw()
    app = LedgerApp(root, home, autostart=False)
    try:
        view = app.views['Trends']
        view.model = service.trends(window=2)
        # Construct the real canvas without showing a test window.
        monkeypatch.setattr(view, 'winfo_ismapped', lambda: True)
        view.redraw(); view.canvas.draw()
        line, points = next((line, points) for line, points in view.lines if points)
        point = points[0]
        x, y = view.axis.transData.transform((1, point['value']))
        event = MouseEvent('motion_notify_event', view.canvas, x, y)
        view.canvas.callbacks.process('motion_notify_event', event)
        assert view.annotation.get_visible()
        assert point['date'] in view.annotation.get_text()
        assert 'n=2' in view.annotation.get_text()
    finally:
        app.tasks.close(); root.destroy()


def test_archive_mappings_snapshots_overrides_survive_upgrade(tmp_path):
    home = tmp_path / 'existing'
    service = DesktopService(home); service.refresh(files=[FIXTURE])
    key = ('Asterknight', 'ExampleRealm', '20301022-180118')
    service.edit_partial(key, {'Map': 'User map'})
    service.edit_identity('Customalt', 'Buddy A')
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (home / 'snapshots').iterdir()}
    data = DesktopService(home).trends()
    assert data['matches'] == 10
    assert 'Customalt' in IdentityMap(home / 'people.json').people['Buddy A']
    assert DesktopService(home).scoreboard(key)['match']['Map'] == 'User map'
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (home / 'snapshots').iterdir()}
    result = DesktopService(home).refresh(files=[FIXTURE])
    assert result['matches_added'] == result['rosters_added'] == 0

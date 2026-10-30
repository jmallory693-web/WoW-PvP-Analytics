"""Theme routing, unchanged chart data and successful PNG export."""
from pathlib import Path
import pytest


def chart_models():
    """Fictional prepared models, including multiple series and null gaps."""
    groups, comparisons = [], []
    for index in range(6):
        name = f'Example {index + 1}'
        records = [{'Character': name, 'Realm': 'ExampleRealm', 'Match ID': f'2030010{day}-120000',
                    'Date': f'2030-01-0{day}', 'Time': '12:00', 'Type': 'Battleground',
                    'Damage': value, 'Damage per minute': value, 'Deaths': day,
                    'Deaths per 10 minutes': day, 'Damage rank': day, 'Minutes played': 1}
                   for day, value in enumerate([1000 + index * 200, None, 1600 + index * 250], 1)]
        points = [{'key': (name, 'ExampleRealm', row['Match ID']), 'date': row['Date'],
                   'value': value, 'count': 2}
                  for row, value in zip(records, [50 + index * 4, 75 - index * 3, 100 - index * 4])]
        summary = {'games': 3, 'wins': 2, 'losses': 1, 'known_results': 3}
        gear_sample = {'matches': 3, 'win_rate': 66.7, 'known_results': 3}
        groups.append({'label': name, 'mode': 'Battleground', 'records': records, 'rolling': points,
                       'gear': {'below': gear_sample, 'at_or_above': gear_sample, 'unknown_item_level': 0}})
        comparisons.append({'label': name, 'records': records, 'summary': summary,
                            'by_type': {'Battleground': summary}, 'rolling_by_type': {'Battleground': points}})
    trends = {'series': groups, 'teammates': groups, 'window': 2, 'threshold': 344,
              'matches': 18, 'note': 'Fictional chart verification'}
    comparison = {'series': comparisons, 'scope': 'All Recorded Matches', 'window': 2,
                  'note': 'Fictional chart verification'}
    rated = [{'label': f'Example rated cohort {index + 1}',
              'points': [{'time': f'2030-01-0{day}T12:00:00+00:00', 'rating': value}
                         for day, value in enumerate([1500 + index * 100, 1480 + index * 100, 1540 + index * 100], 1)]}
             for index in range(2)]
    return trends, comparison, rated


@pytest.mark.parametrize('theme', ['Classic', 'Warband'])
def test_chart_data_exports_and_render_isolation(tmp_path, theme):
    from copy import deepcopy
    import matplotlib
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib._pylab_helpers import Gcf
    from PIL import Image
    from pvpledger_viewer import charts, comparison_charts, rated_charts
    from pvpledger_viewer.ui.theme import WARBAND
    colors = None if theme == 'Classic' else WARBAND
    trend, comparison, rated = chart_models(); before = deepcopy((trend, comparison, rated))
    settings = dict(matplotlib.rcParams); managers = list(Gcf.get_all_fig_managers())
    def snapshot(f):
        return [(a.get_title(), a.get_xlabel(), a.get_ylabel(), a.get_xlim(), a.get_ylim(),
                 a.get_yscale(), [line.get_xydata().copy() for line in a.lines],
                 [t.get_text() for t in a.get_legend().get_texts()] if a.get_legend() else [],
                 [line.get_linestyle() for line in a.lines]) for a in f.axes]
    def same_data(a, b):
        assert len(a) == len(b)
        for left, right in zip(a, b):
            assert left[:6] == right[:6] and left[7:] == right[7:]
            assert len(left[6]) == len(right[6])
            for x, y in zip(left[6], right[6]):
                np.testing.assert_equal(x, y)
    for kind in ('trends', 'comparison', 'rated'):
        reference = rated_charts.figure(rated) if kind == 'rated' else Figure()
        f = rated_charts.figure(rated, palette=colors) if kind == 'rated' else Figure()
        FigureCanvasAgg(reference); FigureCanvasAgg(f)
        if kind == 'trends':
            charts.draw_chart(reference, trend, 'Win rate')
            charts.draw_chart(f, trend, 'Win rate', palette=colors)
            path = charts.export_png(tmp_path / 'trends.png', trend, 'Win rate', palette=colors)
            expected = (1560, 840)
        elif kind == 'comparison':
            metrics = ['Win rate', 'Damage per minute']
            comparison_charts.draw(reference, comparison, metrics)
            comparison_charts.draw(f, comparison, metrics, palette=colors)
            path = comparison_charts.export_png(tmp_path / 'comparison.png', comparison, metrics, palette=colors)
            expected = (1560, 960)
        else:
            path = tmp_path / 'rated.png'; f.savefig(path, dpi=150, facecolor=f.get_facecolor())
            expected = (1500, 840)
        same_data(snapshot(reference), snapshot(f))
        with Image.open(path) as image:
            assert image.format == 'PNG' and image.size == expected
            assert image.convert('RGBA').getextrema()[3] == (255, 255)
        reference.clear(); f.clear()
    f = Figure(); FigureCanvasAgg(f)
    for _ in range(3):
        charts.draw_chart(f, trend, 'Deaths', palette=colors)
        assert len(f.axes) == 1 and len(f.axes[0].lines) == 6
        comparison_charts.draw(f, comparison, ['Damage rank', 'Win rate'], palette=colors)
        assert len(f.axes) == 2 and f.axes[0].yaxis_inverted()
    empty = dict(comparison, series=[])
    comparison_charts.draw(f, empty, ['Win rate'], palette=colors)
    assert not f.axes[0].lines and f.axes[0].texts
    assert rated_charts.figure([], palette=colors).axes[0].texts
    assert (trend, comparison, rated) == before
    assert dict(matplotlib.rcParams) == settings and Gcf.get_all_fig_managers() == managers


@pytest.mark.parametrize('theme', ['Classic', 'Warband'])
def test_application_routes_active_chart_palette_and_exports(tmp_path, theme):
    import subprocess
    import sys
    script = "import runpy,sys; runpy.run_path(sys.argv[1])['_ui_session'](sys.argv[2],sys.argv[3])"
    result = subprocess.run([sys.executable, '-c', script, str(Path(__file__).resolve()),
                             str(tmp_path), theme], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def _ui_session(folder, theme):
    import time
    import tkinter as tk
    from pvpledger_viewer.service import DesktopService
    from pvpledger_viewer.settings import SettingsStore
    from pvpledger_viewer.ui.app import LedgerApp
    from pvpledger_viewer.ui.theme import chart_palette
    from pvpledger_viewer import charts, comparison_charts, rated_charts
    from pvpledger_viewer.ui.comparison_dialog import ComparisonChartDialog
    from pvpledger_viewer.ui.rated import RatedChart
    from tkinter import filedialog
    home = Path(folder); service = DesktopService(home)
    service.refresh(files=[Path(__file__).parent / 'fixtures/PvPLedger.lua'])
    SettingsStore(home / 'settings.json').save({'theme': theme, 'trend_window': 2, 'sync_enabled': False})
    root = tk.Tk(); app = LedgerApp(root, home, autostart=False); errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    def pump():
        deadline = time.monotonic() + 25
        for _ in range(3):
            root.update()
            while app.tasks.pending and time.monotonic() < deadline:
                root.update(); time.sleep(.01)
        assert not app.tasks.pending and not errors, errors
    received = []
    for module in (charts, comparison_charts, rated_charts):
        original = module.apply_chart_palette
        def track(figure, colors, original=original):
            received.append(colors); return original(figure, colors)
        module.apply_chart_palette = track
    destination = [home / 'trend.png']
    filedialog.asksaveasfilename = lambda **kw: str(destination[0])
    try:
        app.reload(); pump(); app.show_view('Trends'); pump()
        view = app.views['Trends']; assert view.figure.axes
        view.export(); pump(); assert destination[0].is_file()
        t, comparison, ratings = chart_models()
        app.show_view('Character Comparison'); pump()
        panel = app.views['Character Comparison'].advanced
        panel.model = comparison; panel.metrics = ['Damage']; panel.preview(); pump()
        assert panel.figure.axes[0].lines
        dialog = ComparisonChartDialog(panel); pump()
        dialog.draw_model(comparison, ['Win rate', 'Damage per minute']); pump()
        assert len(dialog.chart_canvas.figure.axes) == 2
        destination[0] = home / 'comparison.png'; dialog.export(); pump()
        assert destination[0].is_file(); dialog.destroy(); pump()
        window = RatedChart(app, ratings); pump()
        assert len(window.figure.axes) == 2
        destination[0] = home / 'rated.png'; window.export(); assert destination[0].is_file()
        window.close(); pump()
        expected = chart_palette(root)
        assert (expected is None) == (theme == 'Classic')
        assert len(received) >= 6 and all(value is expected for value in received)
    finally:
        for child in list(root.winfo_children()):
            if isinstance(child, tk.Toplevel): child.destroy()
        app.close(); deadline = time.monotonic() + 10
        while not app.tasks.closed and time.monotonic() < deadline:
            root.update(); time.sleep(.01)
        assert app.tasks.closed

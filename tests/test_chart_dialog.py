import time
import tkinter as tk
from pathlib import Path
import pytest
from pvpledger_viewer.service import DesktopService
from pvpledger_viewer.ui.app import LedgerApp
from test_core import FIXTURE


@pytest.fixture(scope='module')
def chart_base(tmp_path_factory):
    tmp_path=tmp_path_factory.mktemp('chart-data')
    home=tmp_path/'archive'
    alternate=tmp_path/'alternate.lua'
    alternate.write_text(FIXTURE.read_text(encoding='utf8').replace('Asterknight','Mossweaver'),encoding='utf8')
    DesktopService(home).refresh(files=[FIXTURE,alternate])
    root=tk.Tk(); root.withdraw()
    app=LedgerApp(root,home,autostart=False)
    errors=[]; root.report_callback_exception=lambda *args: errors.append(args)
    def pump():
        end=time.monotonic()+20
        for _ in range(3):
            root.update()
            while app.tasks.pending and time.monotonic()<end:
                root.update(); time.sleep(.01)
        assert app.tasks.pending==0
        assert not errors, errors
    app.reload(); pump()
    panel=app.views['Character Comparison'].advanced
    panel.render(app.payload)
    yield app,panel,pump
    for child in list(root.winfo_children()):
        if isinstance(child,tk.Toplevel): child.destroy()
    app.tasks.close()
    for timer in root.tk.call('after','info'):
        root.after_cancel(timer)
    root.destroy()


@pytest.fixture
def chart_app(chart_base):
    from pvpledger_viewer.metrics import Filters
    app,panel,pump=chart_base
    app.filters=Filters();panel.model=None;panel.mode.set('Character vs Character');panel.layout()
    panel.a.text.set('');panel.b.text.set('');panel.metrics=['Damage']
    panel.mine.selection_clear(0,'end')
    return app,panel,pump


def setup(panel,mode):
    panel.mode.set(mode); panel.layout()
    if mode=='My Characters':
        panel.mine.selection_set(0,1)
    elif mode=='Character vs Character':
        entries=panel.entries
        panel.a.restore(next(e['key'] for e in entries if e['name']=='Asterknight'))
        panel.b.restore(next(e['key'] for e in entries if e['name']=='Emberguard'))
    else:
        panel.a.text.set('');panel.b.text.set('');panel.friend.set('Buddy A');panel.layout()
    panel.metrics=['Damage']


def test_chart_open_before_compare_explains_missing_participants(chart_app):
    app,panel,pump=chart_app
    assert panel.model is None
    dialog=panel.charts(); pump()
    assert 'Confirm Character A and B' in dialog.status.cget('text')
    assert 'Choose comparison participants' in dialog.message.cget('text')
    assert dialog.chart_canvas is None and dialog.export_button.instate(['disabled'])
    dialog.draw_button.invoke();pump()
    assert dialog.status.cget('text')
    dialog.destroy()


@pytest.mark.parametrize('mode',['My Characters','Character vs Character','Me vs Friends'])
def test_chart_auto_loads_without_compare_and_draw_updates(chart_app,mode):
    app,panel,pump=chart_app;setup(panel,mode)
    assert panel.model is None
    dialog=panel.charts();pump()
    assert dialog.displayed_model is not None
    assert dialog.chart_canvas.figure.axes[0].lines
    assert dialog.chart_canvas.get_tk_widget().winfo_height()>100
    assert dialog.export_button.instate(['!disabled'])
    dialog.chosen.selection_clear(0,'end');dialog.chosen.selection_set(0,2)
    dialog.draw_button.invoke();pump()
    assert len(dialog.chart_canvas.figure.axes)==3
    assert dialog.displayed_metrics==['Win rate','Damage per minute','Healing per minute']
    for size in ('800x500','1100x700'):
        dialog.geometry(size);pump()
        assert dialog.draw_button.winfo_viewable() and dialog.export_button.winfo_viewable()
        assert dialog.holder.canvas.cget('scrollregion')
    dialog.holder.canvas.yview_moveto(1);pump()
    assert dialog.holder.canvas.yview()[1]==1
    dialog.destroy()


def test_chart_empty_metric_coverage_is_visible(chart_app):
    app,panel,pump=chart_app;setup(panel,'Me vs Friends')
    panel.friend.set('Buddy D');panel.layout()
    from pvpledger_viewer.metrics import Filters
    app.filters=Filters(start='1900-01-01',end='1900-01-01')
    dialog=panel.charts();pump()
    assert 'No data for this comparison' in dialog.status.cget('text')
    assert all(not axis.lines for axis in dialog.chart_canvas.figure.axes)
    assert any('No data for this comparison' in t.get_text() for axis in dialog.chart_canvas.figure.axes for t in axis.texts)
    dialog.destroy()


def test_chart_no_metric_selected_and_retry(chart_app):
    app,panel,pump=chart_app;setup(panel,'My Characters')
    dialog=panel.charts();pump()
    dialog.chosen.selection_clear(0,'end');dialog.draw_button.invoke();pump()
    assert 'Select at least one metric' in dialog.status.cget('text')
    assert dialog.export_button.instate(['disabled'])
    dialog.chosen.selection_set(0);dialog.draw_button.invoke();pump()
    assert dialog.chart_canvas is not None
    dialog.destroy()


@pytest.mark.parametrize('stage',['worker','drawing'])
def test_chart_exceptions_visible_and_retryable(chart_app,monkeypatch,stage):
    app,panel,pump=chart_app;setup(panel,'My Characters')
    import pvpledger_viewer.comparison_charts as charts
    target,name=(app.service,'compare') if stage=='worker' else (charts,'draw')
    original=getattr(target,name)
    def fail(*a,**kw):raise RuntimeError('plot failure evidence')
    monkeypatch.setattr(target,name,fail)
    dialog=panel.charts();pump()
    assert 'plot failure evidence' in dialog.status.cget('text')
    assert dialog.draw_button.instate(['!disabled']) and dialog.export_button.instate(['disabled'])
    assert 'plot failure evidence' in (app.service.home/'chart_errors.log').read_text()
    monkeypatch.setattr(target,name,original);dialog.draw_button.invoke();pump()
    assert dialog.chart_canvas is not None
    dialog.destroy()


def test_chart_exports_displayed_snapshot_and_reports_export_errors(chart_app,monkeypatch,tmp_path):
    app,panel,pump=chart_app;setup(panel,'My Characters')
    dialog=panel.charts();pump()
    path=tmp_path/'real-chart.png'
    monkeypatch.setattr('pvpledger_viewer.ui.comparison_dialog.filedialog.asksaveasfilename',lambda **kw:str(path))
    dialog.chosen.selection_clear(0,'end');dialog.chosen.selection_set(0,2)
    dialog.export_button.invoke();pump()
    from PIL import Image
    with Image.open(path) as image:
        assert image.size==(1560,480) # displayed one metric, not newly selected three
        image.verify()
    assert 'PNG saved:' in dialog.status.cget('text')
    def fail(*a,**kw):raise OSError('cannot write PNG')
    monkeypatch.setattr('pvpledger_viewer.comparison_charts.export_png',fail)
    dialog.export_button.invoke();pump()
    assert 'PNG export failed: cannot write PNG' in dialog.status.cget('text')
    dialog.destroy()


def test_chart_closing_while_computing_has_no_callback_error(chart_app):
    app,panel,pump=chart_app;setup(panel,'My Characters')
    dialog=panel.charts();dialog.render();dialog.destroy();pump()


def test_trends_restored_mode_matches_actual_comparison(chart_app):
    app,panel,pump=chart_app
    trends=app.views['Trends'];trends.mode.set('My Characters');trends.render(app.payload)
    assert trends.advanced.mode.get()=='My Characters'
    assert trends.advanced.mine.winfo_manager()=='grid'

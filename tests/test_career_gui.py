import time
import tkinter as tk
from pathlib import Path
import pytest
from pvpledger_viewer.ui.app import LedgerApp
from pvpledger_viewer.ui.rated import RatingForm,RatedChart
from test_career import imported,raw_record,manual
from pvpledger_viewer.career import save_manual


@pytest.fixture(scope='module')
def gui(tmp_path_factory):
    folder=tmp_path_factory.mktemp('rated-gui');home,source=imported(folder,[raw_record()]);root=tk.Tk();app=LedgerApp(root,home,autostart=False);errors=[]
    root.report_callback_exception=lambda *args:errors.append(args)
    def pump():
        deadline=time.monotonic()+40
        for _ in range(3):
            root.update()
            while app.tasks.pending and time.monotonic()<deadline:root.update();time.sleep(.01)
        assert not errors and not app.tasks.pending,errors
    app.reload();pump();app.open_rated('Me','Realm');pump()
    yield app,root,pump,folder
    for child in list(root.winfo_children()):
        if isinstance(child,tk.Toplevel):child.destroy()
    app.close();deadline=time.monotonic()+5
    while not app.tasks.closed and time.monotonic()<deadline:root.update();time.sleep(.01)
    assert app.tasks.closed


def test_rated_navigation_footer_filters_and_1280_layout(gui):
    app,root,pump,folder=gui;view=app.views['Rated PvP']
    assert view.character_info()['character']=='Me' and view.summary.rows[0]['current']==1520
    for geometry in ('1280x720','1600x900','1280x720'):
        root.geometry(geometry);pump()
        for button in (view.add,view.refresh_button,app.nav['Rated PvP']):
            assert button.winfo_viewable() and button.winfo_height()>=25
            assert button.winfo_rooty()+button.winfo_height()<=root.winfo_rooty()+root.winfo_height()
    view.filters['season'].set('999');view.load();pump();assert not view.summary.rows and not view.observed.rows
    view.load(reset=True);pump();assert view.observed.rows
    app.open_rated('Skyarrow',None);pump();assert view.character_info()['character']=='Skyarrow' and not view.observed.rows
    app.open_rated('Me','Realm');pump()


def test_manual_form_gating_correction_and_reversal_callbacks(gui):
    app,root,pump,folder=gui;view=app.views['Rated PvP'];original=(app.service.home/'archive.sqlite').read_bytes()
    form=RatingForm(view)
    for key,value in manual(rating=1900).items():
        if key in form.vars:form.vars[key].set(str(value))
    form.save();assert 'approval' in form.error.cget('text').lower()
    form.approved.set(True);form.save();pump();assert not form.winfo_exists()
    row=view.history.rows[0];assert row['rating']==1900
    form=RatingForm(view,row['data']|{'manual':True},row['id']);form.vars['rating'].set('1800');form.vars['correction_reason'].set('Corrected manual test rating');form.approved.set(True);form.save();pump()
    assert view.summary.rows[0]['current']==1800 and len(view.history.rows)==2
    view.history.tree.selection_set('0');view.reverse();assert 'approval' in view.note.cget('text').lower()
    view.reverse_approval.set(True);view.reverse();pump();assert view.summary.rows[0]['current']==1520
    assert (app.service.home/'archive.sqlite').read_bytes()==original and len(view.history.rows)==3


def test_rating_chart_initial_draw_png_and_resize_are_real(gui):
    app,root,pump,folder=gui;view=app.views['Rated PvP'];window=RatedChart(app,view.data['series']);pump()
    assert window.canvas and window.figure.axes[0].lines and not window.figure.axes[0].lines[0].get_linestyle()=='-'
    for geometry in ('1280x720','900x600'):
        window.geometry(geometry);pump();assert window.canvas.get_tk_widget().winfo_width()>500
    path=folder/'rating.png';window.figure.savefig(path)
    from PIL import Image,ImageStat
    with Image.open(path) as image:
        assert image.width>500 and sum(ImageStat.Stat(image.convert('RGB')).var)>50
    window.close();pump()
    empty=RatedChart(app,[]);pump();assert any('No compatible' in t.get_text() for t in empty.figure.axes[0].texts)
    empty.close();pump()


def test_direct_parent_chart_destroy_releases_tk_resources_before_worker_gc(gui):
    app,root,pump,folder=gui
    window=RatedChart(app,app.views['Rated PvP'].data['series']);pump();canvas=window.canvas
    window.destroy();pump()
    assert canvas._tkphoto is None and canvas.figure.canvas is None
    # Retaining Python references after closing a window must not retain live
    # Tcl variables that could be finalized by a subsequent worker collection.
    frame=app.views['Rated PvP']
    assert frame.others is not None


def test_closed_application_does_not_retain_tcl_variables_for_worker_finalization(gui):
    app,root,pump,folder=gui
    extra=tk.Toplevel(root);retained=LedgerApp(extra,app.service.home,autostart=False)
    retained.tasks.close();extra.destroy()
    assert retained.variables=={}
    assert retained.views['Trends'].mode is None
    assert retained.views['Character Comparison'].advanced.metric is None
    assert retained.views['Rated PvP'].others is None

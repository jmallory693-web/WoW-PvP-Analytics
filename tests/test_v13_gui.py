import time
import tkinter as tk
import pytest
from pvpledger_viewer.service import DesktopService
from pvpledger_viewer.ui.app import LedgerApp
from pvpledger_viewer.ui.players import RankingWindow
from pvpledger_viewer.full_export import validate
from pvpledger_viewer.sync import SyncSchedule
from test_core import FIXTURE


@pytest.fixture(scope='module')
def gui(tmp_path_factory):
    home=tmp_path_factory.mktemp('v13-native')/'archive'
    DesktopService(home).refresh(files=[FIXTURE])
    root=tk.Tk();app=LedgerApp(root,home,autostart=False);errors=[]
    root.report_callback_exception=lambda *args:errors.append(args)
    def pump():
        end=time.monotonic()+25
        for _ in range(3):
            root.update()
            while app.tasks.pending and time.monotonic()<end:
                root.update();time.sleep(.01)
        assert not app.tasks.pending and not errors, errors
    app.reload();pump()
    yield app,root,pump
    for child in list(root.winfo_children()):
        if isinstance(child,tk.Toplevel):child.destroy()
    app.close()
    end=time.monotonic()+5
    while not app.tasks.closed and time.monotonic()<end:
        root.update();time.sleep(.01)
    assert app.tasks.closed


def test_all_players_search_encounters_rankings_status_and_resize(gui):
    app,root,pump=gui
    app.show_view('All Players');pump()
    view=app.views['All Players'];assert len(view.table.rows)>0
    view.query.insert(0,'Emberg');view.load(True);pump()
    assert view.table.rows[0]['Player']=='Emberguard'
    dialog=view.open_player(view.table.rows[0]);pump()
    assert dialog.winfo_exists();dialog.destroy()
    ranking=RankingWindow(app,reference=view.table.rows[0]);pump()
    assert ranking.table.rows and 'observed eligible' in ranking.note.cget('text')
    ranking.metric.set('Healing');ranking.scope.set('Same class');ranking.load();pump()
    assert ranking.note.cget('text');ranking.destroy()
    for size in ('1280x720','1600x900'):
        root.geometry(size);pump()
        assert view.table.tree.winfo_width()>100 and app.nav['Archive Status'].winfo_viewable()
        assert view.pager.winfo_height()>=25 and view.pager.winfo_viewable()
    app.show_view('Archive Status');pump()
    text=app.views['Archive Status'].text.get('1.0','end')
    assert 'used_bytes' in text and 'sync_history' in text and 'integrity_errors' in text


def test_native_complete_dump_progress_success_and_visible_error(gui,tmp_path,monkeypatch):
    app,root,pump=gui;path=tmp_path/'gui.json.gz'
    monkeypatch.setattr('pvpledger_viewer.ui.ai_export.filedialog.asksaveasfilename',lambda **kw:str(path))
    dialog=app.complete_ai_dump();dialog.export();pump()
    assert path.exists() and 'Validated one-file export' in dialog.status.cget('text')
    assert validate(path)['logical_matches']==10
    def failure(*args,**kw):raise OSError('injected export failure')
    monkeypatch.setattr(app.service,'complete_export',failure)
    dialog.export();pump()
    assert 'injected export failure' in dialog.status.cget('text');dialog.destroy()


def test_native_scheduler_and_manual_refresh_coordinate(gui,tmp_path,monkeypatch):
    app,root,pump=gui;app.config['wow_root']=str(tmp_path)
    now=[0];app.sync_schedule=SyncSchedule(lambda:now[0]);app.auto_sync=True
    calls=[];original=app.service.refresh
    def refresh(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(app.service,'refresh',refresh)
    now[0]=300;root.after(0,app.poll);pump()
    assert len(calls)==1 and not app.sync_schedule.running
    now[0]=599;root.update();assert len(calls)==1
    app.refresh();app.refresh();pump();assert len(calls)==2
    app.auto_sync=False;app.config['wow_root']=''


def test_archive_location_copy_gui_retains_original(gui,tmp_path,monkeypatch):
    app,root,pump=gui;old=app.service.home;destination=tmp_path/'copied'
    monkeypatch.setattr('pvpledger_viewer.ui.settings.filedialog.askdirectory',lambda **kw:str(destination))
    app.open_settings();app.settings_window.relocate();pump()
    assert app.service.home==destination and (old/'archive.sqlite').exists()
    assert (destination/'archive.sqlite').exists() and not (destination/'COPY_INCOMPLETE').exists()
    assert app.service.snapshot()['totals']['total']==10

import time
import tkinter as tk
from pathlib import Path
import pytest
from pvpledger_viewer.ui.app import LedgerApp
from pvpledger_viewer.excel_reader import read_workbook
from pvpledger_viewer.reconcile import EXACT,MISSING
from test_excel import BOOK,make_home,sha


@pytest.fixture(scope='module')
def gui(tmp_path_factory):
    folder=tmp_path_factory.mktemp('excel-gui');home=make_home(folder,read_workbook(BOOK))
    root=tk.Tk();app=LedgerApp(root,home,autostart=False);errors=[];root.report_callback_exception=lambda *args:errors.append(args)
    def pump():
        deadline=time.monotonic()+40
        for _ in range(3):
            root.update()
            while app.tasks.pending and time.monotonic()<deadline:root.update();time.sleep(.01)
        assert not app.tasks.pending and not errors,errors
    app.reload();pump();yield app,root,pump
    for child in list(root.winfo_children()):
        if isinstance(child,tk.Toplevel):child.destroy()
    app.close();deadline=time.monotonic()+5
    while not app.tasks.closed and time.monotonic()<deadline:root.update();time.sleep(.01)
    assert app.tasks.closed


def select(dialog,classification):
    index=next(i for i,r in enumerate(dialog.rows.rows) if r['classification']==classification)
    dialog.rows.tree.selection_set(str(index));dialog.select_row()


def test_review_staging_requires_explicit_approval_and_resizes(gui):
    app,root,pump=gui;main=sha(app.service.home/'archive.sqlite');people=sha(app.service.home/'people.json')
    dialog=app.reconcile_excel(str(BOOK));dialog.audit();pump()
    assert dialog.report['counts']['MATCH ROWS']==200 and dialog.rows.rows
    assert not (app.service.home/'supplemental.sqlite').exists()
    for geometry in ('1280x720','1600x900'):
        dialog.geometry(geometry);pump()
        assert dialog.commit_button.winfo_viewable() and dialog.commit_button.winfo_height()>=25
        assert dialog.commit_button.winfo_rooty()+dialog.commit_button.winfo_height()<=dialog.winfo_rooty()+dialog.winfo_height()
    select(dialog,EXACT);dialog.candidates.tree.selection_set('0');dialog.select_candidate()
    i=dialog.field_names.index('Data source');dialog.field_list.selection_set(i);dialog.stage('link')
    assert len(dialog.staged)==1 and str(dialog.commit_button.cget('state'))=='disabled'
    dialog.commit();assert not (app.service.home/'supplemental.sqlite').exists()
    dialog.approval.set(True);dialog.update_commit();dialog.commit();pump()
    assert 'Committed 1 reviewed decisions' in dialog.status.cget('text')
    assert len(app.service.excel_history())==1 and app.service.snapshot()['history_count']==1
    assert sha(app.service.home/'archive.sqlite')==main and sha(app.service.home/'people.json')==people
    dialog.destroy()


def test_historical_event_and_reviewable_reversal_in_gui(gui):
    app,root,pump=gui;main=sha(app.service.home/'archive.sqlite');dialog=app.reconcile_excel(str(BOOK));dialog.audit();pump()
    select(dialog,MISSING);dialog.field_list.selection_set(0,'end');dialog.reason.set('Isolated explicit historical import test');dialog.stage('historical')
    dialog.approval.set(True);dialog.update_commit();dialog.commit();pump()
    assert app.service.snapshot()['history_count']==2
    assert dialog.history.rows[0]['action']=='historical'
    dialog.history.tree.selection_set('0');dialog.reverse();assert 'approval checkbox' in dialog.status.cget('text')
    dialog.approval.set(True);dialog.reverse();pump()
    assert app.service.snapshot()['history_count']==1 and len(app.service.excel_history())==3
    assert sha(app.service.home/'archive.sqlite')==main;dialog.destroy()

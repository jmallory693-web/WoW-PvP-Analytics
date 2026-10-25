from dataclasses import asdict
import json
from pathlib import Path
import threading
import time
import pytest
from pvpledger_viewer.archive import Archive
from pvpledger_viewer.background import BackgroundTasks
from pvpledger_viewer.identity import IdentityMap
from pvpledger_viewer.metrics import Filters, match_key
from pvpledger_viewer.service import DesktopService, validate_overrides
from pvpledger_viewer.settings import SettingsStore, validate_settings
from pvpledger_viewer.viewmodels import display, history_row, home_model, percent, scoreboard_model, sort_records
from test_core import FIXTURE, write_source, match


@pytest.fixture
def desktop(tmp_path):
    home = tmp_path / 'archive'
    a = Archive(home); a.import_file(FIXTURE); a.close()
    copied = []
    service = DesktopService(home, clipboard=copied.append)
    return service, copied


def test_view_snapshot_filtering_paging_and_counts(desktop):
    service, _ = desktop
    data = service.snapshot(page_size=3)
    assert data['history_count'] == 10 and len(data['history']) == 3 and data['pages'] == 4
    last = service.snapshot(page=100, page_size=3)
    assert last['page'] == 3 and len(last['history']) == 1
    eye = service.snapshot(Filters(map_name='Eye of the Storm'))
    assert eye['history_count'] == 1 and eye['home']['summary']['losses'] == 1
    assert len(service.snapshot(Filters(match_type='Arena skirmish'))['history']) == 2
    assert service.snapshot(Filters(premade=False))['history_count'] == 1
    with pytest.raises(ValueError):
        service.snapshot(page_size=0)


def test_home_cards_class_spec_and_empty_states(desktop):
    service, _ = desktop
    home = service.snapshot()['home']
    pal = next(c for c in home['cards'] if c['character'] == 'Asterknight')
    assert (pal['summary']['wins'], pal['summary']['losses']) == (4, 3)
    assert pal['spec'] == 'Retribution' and pal['class'] == 'Paladin'
    assert pal['item_level'] == 343.4 and pal['last_played'].startswith('2030-10-22')
    absent = next(c for c in home['cards'] if c['character'] == 'Mossweaver')
    assert absent['realm'] is None and absent['summary']['games'] == 0


def test_home_detects_new_owner_without_inventing_identity(desktop, tmp_path):
    service, _ = desktop
    source = write_source(tmp_path / 'new-owner.lua', [match(character='NewOwner')])
    service.refresh(files=[source])
    payload = service.snapshot()
    assert next(c for c in payload['home']['cards'] if c['character'] == 'NewOwner')['summary']['games'] == 1
    assert 'NewOwner' not in payload['people']['Me']


def test_large_history_page_is_bounded(desktop, tmp_path):
    service, _ = desktop
    source = write_source(tmp_path / 'many.lua', [match(mid=f'20261023-{i:06}') for i in range(501)])
    service.refresh(files=[source])
    payload = service.snapshot()
    assert payload['history_count'] == 511 and len(payload['history']) == 100


@pytest.mark.parametrize('descending,expected', [(False, [2, 10, 100, None]), (True, [100, 10, 2, None])])
def test_numeric_sort_and_unknowns_last(descending, expected):
    assert [r['Damage'] for r in sort_records([{'Damage': v} for v in [10, None, 2, 100]], 'Damage', descending)] == expected


def test_unicode_text_sort_and_formats():
    assert [r['Name'] for r in sort_records([{'Name': 'Fayë'}, {'Name': 'snowflare'}], 'Name')] == ['Fayë', 'snowflare']
    assert display(None) == 'Unknown' and display(1234567) == '1,234,567'
    assert percent(4 / 7) == '57.1%'


def test_scoreboard_teams_highlights_and_margin(desktop):
    service, _ = desktop
    model = service.scoreboard(('Asterknight', 'ExampleRealm', '20301022-190143'))
    assert model['metadata']['Win margin'] == -52 and not model['partial']
    assert sum(len(rows) for rows in model['teams'].values()) == 32
    mine = model['teams']['Mine']
    assert next(r for r in mine if r['Player'] == 'Asterknight')['Highlight'] == 'self'
    assert {r['Person'] for r in mine if r['Highlight'] == 'premade'} >= {'Buddy A', 'Buddy B', 'Buddy C'}
    assert next(r for r in mine if r['Player'] == 'Emberguard')['Identity'] == 'PREMADE'
    assert all(r['Team'] == 'Enemy' for r in model['teams']['Enemy'])


def test_partial_metadata_edit_and_raw_preservation(desktop):
    service, _ = desktop
    key = ('Asterknight', 'ExampleRealm', '20301022-173450')
    before = service.scoreboard(key)
    assert before['partial'] and before['metadata']['Map'] is None and before['metadata']['Result'] is None
    with service.archive() as a:
        before_raw = a.db.execute('SELECT data FROM matches WHERE match_id=?', (key[2],)).fetchone()[0]
    model = service.edit_partial(key, {'Map': 'Confirmed map', 'Result': 'W', 'Duration (s)': '600', 'My team score': '', 'Minutes played': '8.5'})
    assert model['partial'] and model['metadata']['Map'] == 'Confirmed map'
    assert model['metadata']['Result'] == 'W' and model['metadata']['My team score'] is None
    with service.archive() as a:
        assert a.db.execute('SELECT data FROM matches WHERE match_id=?', (key[2],)).fetchone()[0] == before_raw
    with pytest.raises(ValueError):
        service.edit_partial(('Asterknight', 'ExampleRealm', '20301022-190143'), {'Result': 'W'})


@pytest.mark.parametrize('values', [{'Result': 'Maybe'}, {'Duration (s)': '-1'}, {'Duration (s)': '2.5'}, {'Minutes played': 'nan'}, {'Type': 'Mystery'}, {'Match ID': 'bad'}, {'Minutes played': True}])
def test_partial_edit_validation(values):
    with pytest.raises(ValueError):
        validate_overrides(values)


def test_partial_attendance_and_unknown_display():
    from test_phase2 import sample, player
    class Identity:
        owner_person = "Me"
        def resolve(self, name, realm):
            return 'Buddy A'
    model = scoreboard_model(sample(_partial=True, Result=None), [player(**{'Joined late': 1, 'Left early': 1})], Identity())
    assert model['partial'] and model['teams']['Mine'][0]['Attendance'] == 'Late join · Left early'
    assert history_row(sample(_partial=True, Result=None))['Status'] == 'PARTIAL · Unknown'


def test_identity_edit_recomputes_history(desktop):
    service, _ = desktop
    before = service.snapshot()
    assert sum(k['together']['games'] for k in before['allies']['Buddy D'].values()) == 0
    service.edit_identity('Unboundleaf', 'Buddy D')
    assert sum(k['together']['games'] for k in service.snapshot()['allies']['Buddy D'].values()) > 0
    service.edit_identity('Unboundleaf', action='unassign')
    assert 'Unboundleaf' in service.snapshot()['diagnostics']['unassigned']
    service.edit_identity('SomeNewCharacter', 'New ally')
    assert 'New ally' in service.snapshot()['allies']


def test_clipboard_report_scoreboard_and_diagnostics_integration(desktop):
    service, copied = desktop
    assert service.copy_report(Filters(map_name='Eye of the Storm'), limit=1)['characters'] > 1000
    assert '1448' in copied[-1] and 'Emberguard' in copied[-1] and 'Pebblebrew' in copied[-1] and 'Snowflare' in copied[-1]
    service.copy_report(key=('Asterknight', 'ExampleRealm', '20301022-173450'))
    assert 'True' in copied[-1] and 'Unknown map' not in copied[-1]  # Unknown raw cells stay blank CSV fields.
    service.copy_diagnostics()
    assert json.loads(copied[-1])['totals']['total'] == 10


def test_clipboard_failure_propagates(desktop):
    service, _ = desktop
    def busy(text):
        raise OSError('Clipboard is busy')
    service.clipboard = busy
    with pytest.raises(OSError, match='busy'):
        service.copy_report()


def test_refresh_scan_idempotence_and_bak(desktop, tmp_path):
    service, _ = desktop
    source = tmp_path / 'WoW/_retail_/WTF/Account/A/Realm/Me/SavedVariables/PvPLedger.lua'
    source.parent.mkdir(parents=True); source.write_bytes(FIXTURE.read_bytes())
    source.with_suffix('.lua.bak').write_text('bad')
    original = source.read_bytes()
    report = service.refresh(tmp_path / 'WoW')
    assert report['files'] == 1 and report['matches_added'] == report['rosters_added'] == report['failures'] == 0
    assert source.read_bytes() == original and service.snapshot()['totals']['total'] == 10


def test_refresh_malformed_file_does_not_lose_archive(desktop, tmp_path):
    service, _ = desktop
    bad = tmp_path / 'bad.lua'; bad.write_text('PvPLedgerDB={')
    assert service.refresh(files=[bad])['failures'] == 1
    assert service.snapshot()['diagnostics']['recent_imports'][-1]['status'] == 'failed'
    assert service.snapshot()['totals']['total'] == 10
    with pytest.raises(ValueError):
        service.refresh('missing-folder')


def test_export_selected_ally_and_filters(desktop, tmp_path):
    service, _ = desktop
    manifest = service.export(tmp_path / 'exports', Filters(map_name='Eye of the Storm'), ally='Buddy A')
    assert next(r for r in manifest if r['label'] == 'Buddy A')['matches'] == 1
    with pytest.raises(ValueError):
        service.export(tmp_path / 'CustomGame' / 'exports', wow_root=str(tmp_path / 'CustomGame'))


def test_export_protects_previously_imported_custom_game_root(desktop, tmp_path):
    service, _ = desktop
    source = tmp_path / 'CustomGame/_retail_/WTF/Account/A/ExampleRealm/Asterknight/SavedVariables/PvPLedger.lua'
    source.parent.mkdir(parents=True); source.write_bytes(FIXTURE.read_bytes())
    service.refresh(files=[source])
    with pytest.raises(ValueError, match='imported WoW'):
        service.export(tmp_path / 'CustomGame' / 'exports')


def test_settings_roundtrip_filters_and_window(tmp_path):
    store = SettingsStore(tmp_path / 'settings.json')
    values = store.load() | {'geometry': '1600x900+25+40', 'wow_root': 'C:/Games/WoW', 'report_limit': 30,
                             'view': 'Allies', 'filters': asdict(Filters(character='Asterknight', map_name='Fayë', premade=False))}
    store.save(values)
    assert SettingsStore(store.path).load() == values
    assert 'Fayë' in store.path.read_text(encoding='utf8')


def test_corrupt_settings_recovery_preserves_original(tmp_path):
    path = tmp_path / 'settings.json'; path.write_text('invalid JSON')
    store = SettingsStore(path); data = store.load()
    assert store.error and data['report_limit'] == 20
    store.save(data)
    assert path.with_name('settings.invalid.json').read_text() == 'invalid JSON'


@pytest.mark.parametrize('values', [{'geometry': 'bad'}, {'report_limit': 0}, {'report_limit': True}, {'filters': {'start': 'bad'}}, {'filters': {'premade': 'Yes'}}])
def test_invalid_settings(values):
    with pytest.raises(ValueError):
        validate_settings(values)


def wait_worker(worker):
    end = time.monotonic() + 3
    while worker.results.empty() and time.monotonic() < end:
        time.sleep(.01)
    assert not worker.results.empty()


def test_background_never_calls_tk_callbacks_from_worker():
    worker = BackgroundTasks(); main_thread = threading.get_ident()
    callbacks = []
    future = worker.submit(lambda: threading.get_ident(), lambda thread: callbacks.append((thread, threading.get_ident())), pytest.fail)
    future.result(timeout=3); wait_worker(worker)
    assert callbacks == []
    worker.drain()
    assert callbacks[0][0] != main_thread and callbacks[0][1] == main_thread
    assert worker.pending == 0
    worker.close()


def test_background_errors_and_close_suppress_callbacks():
    worker = BackgroundTasks(); errors = []
    def bad():
        raise ValueError('Malformed data')
    worker.submit(bad, pytest.fail, errors.append)
    wait_worker(worker); worker.drain()
    assert str(errors[0]) == 'Malformed data'
    worker.submit(lambda: 1, pytest.fail, pytest.fail).result(timeout=3)
    worker.close(); worker.drain()
    with pytest.raises(RuntimeError):
        worker.submit(lambda: 2, print, print)


def test_service_opens_sqlite_in_worker_thread(desktop):
    service, _ = desktop
    worker = BackgroundTasks(); results = []
    worker.submit(service.snapshot, results.append, pytest.fail)
    wait_worker(worker); worker.drain(); worker.close()
    assert results[0]['history_count'] == 10


def test_trace_api_and_diagnostics_sources(desktop, tmp_path):
    service, _ = desktop
    file = tmp_path / 'trace.lua'
    file.write_text('PvPLedgerDB={trace={"capture ready", "last test line"}}')
    service.refresh(files=[file])
    diagnostics = service.snapshot()['diagnostics']
    assert diagnostics['trace'][0]['raw'] == 'last test line'
    assert diagnostics['last_import'] and diagnostics['imports_total'] == 2


def test_tk_views_worker_delivery_navigation_and_shutdown(desktop):
    # Runs when a full Python/Tk installation is available; no display mocks.
    pytest.importorskip('tkinter')
    import tkinter as tk
    from pvpledger_viewer.ui.app import LedgerApp
    from pvpledger_viewer.ui.scoreboard import ScoreboardWindow
    from pvpledger_viewer.ui.comparison import comparison_rows
    from pvpledger_viewer.ui.allies import ally_rows
    from pvpledger_viewer.ui.diagnostics import diagnostic_text
    service, copied = desktop
    root = tk.Tk(); root.withdraw()
    app = LedgerApp(root, service.home, autostart=False)
    app.service.clipboard = copied.append
    def pump(predicate):
        until = time.monotonic() + 10
        while not predicate() and time.monotonic() < until:
            root.update(); time.sleep(.01)
        assert predicate()
    try:
        app.reload(); pump(lambda: app.tasks.pending == 0)
        assert app.payload['history_count'] == 10
        for view in app.views:
            app.show_view(view); root.update()
        heartbeats = []
        def heartbeat():
            heartbeats.append(threading.get_ident())
            if len(heartbeats) < 10:
                root.after(10, heartbeat)
        root.after(10, heartbeat)
        app.run_job('Responsiveness check', lambda: time.sleep(.2))
        pump(lambda: app.tasks.pending == 0)
        assert len(heartbeats) >= 5 and set(heartbeats) == {threading.get_ident()}
        assert len(comparison_rows(app.payload['comparison'])) >= 5
        assert any(r['Person'] == 'Buddy A' for r in ally_rows(app.payload['allies']))
        assert 'archive.sqlite' in diagnostic_text(app.payload['diagnostics'])
        app.select_character('Asterknight', 'ExampleRealm'); pump(lambda: app.tasks.pending == 0)
        assert app.view_name == 'Match History' and app.filters.character == 'Asterknight-ExampleRealm'
        assert len(app.views['Match History'].table.tree.get_children()) == 10
        app.sort_history('Damage', True); pump(lambda: app.tasks.pending == 0)
        assert app.payload['history'][0]['Damage'] == 20211075
        key = ('Asterknight', 'ExampleRealm', '20301022-190143')
        board = ScoreboardWindow(app, key, service.scoreboard(key)); board.withdraw()
        assert 'Win margin  -52' in board.metadata.cget('text')
        board.copy(); pump(lambda: app.tasks.pending == 0)
        assert 'Emberguard' in copied[-1] and 'MATCHES CSV' in copied[-1]
        board.destroy()
        app.close(); pump(lambda: app.tasks.closed)
        persisted = SettingsStore(service.home / 'settings.json').load()
        assert persisted['view'] == 'Match History' and persisted['filters']['character'] == 'Asterknight-ExampleRealm'
    finally:
        if not app.tasks.closed:
            app.tasks.close(); root.destroy()

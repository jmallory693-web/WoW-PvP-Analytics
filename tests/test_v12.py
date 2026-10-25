from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import time
import pytest
from pvpledger_viewer.calendar_core import availability, localize, preset, shift_month, month_days
from pvpledger_viewer.comparisons import catalogue, suggestions, compare, participant_records, same_event
from pvpledger_viewer.identity import IdentityMap, character_key
from pvpledger_viewer.metrics import Filters, filter_matches
from pvpledger_viewer.service import DesktopService
from pvpledger_viewer.archive import Archive
from pvpledger_viewer.settings import SettingsStore, validate_settings
from test_core import FIXTURE


def match(i=1, owner='Asterknight', **extra):
    return {'Match ID': f'20261023-12000{i}', 'Character': owner, 'Realm': 'ExampleRealm',
            'Date': '2026-10-23', 'Time': '12:00', 'Type': 'Battleground', 'Map': 'Map',
            'Duration (s)': 300, 'Minutes played': 5, 'Damage': 1000, 'Healing': 200,
            'KB': 1, 'HK': 10, 'Deaths': 2, 'Result': 'W', 'PvP item level': 340,
            '_timestamp_utc': 1792782000 + i * 1000, '_partial': False} | extra


def roster(m, name, damage=1000, team='Mine', **extra):
    return {'Owner character': m['Character'], 'Owner realm': m['Realm'], 'Match ID': m['Match ID'],
            'Player': name, 'Realm': 'ExampleRealm', 'Team': team, 'Damage': damage, 'Healing': 200,
            'KB': 2, 'HK': 20, 'Deaths': 3, 'Class': 'Mage', 'Spec': 'Frost',
            'Is me': 'Yes' if name == m['Character'] else 'No', '_scoreboard_incomplete': False} | extra


@pytest.fixture
def identities(tmp_path):
    return IdentityMap(tmp_path / 'people.json')


def selection(name, realm='ExampleRealm'):
    return {'kind': 'character', 'character': list(character_key(name, realm)), 'label': name + '-' + realm}


def test_calendar_local_timezone_boundaries_and_inclusive_days():
    stamps = [datetime(2026, 10, 23, 6, 59, 59, tzinfo=timezone.utc), datetime(2026, 10, 23, 7, tzinfo=timezone.utc), datetime(2026, 10, 24, 6, 59, 59, tzinfo=timezone.utc), datetime(2026, 10, 24, 7, tzinfo=timezone.utc)]
    matches = localize([match(i + 1, _timestamp_utc=s.timestamp()) for i, s in enumerate(stamps)], 'America/Los_Angeles')
    assert [m['Date'] for m in matches] == ['2026-10-22', '2026-10-23', '2026-10-23', '2026-10-24']
    assert len(filter_matches(matches, [], Filters(start='2026-10-23', end='2026-10-23'))) == 2
    assert availability(matches) == {'2026-10-22': 1, '2026-10-23': 2, '2026-10-24': 1}
    assert len(filter_matches(matches, [], Filters(start='2026-11-01', end='2026-11-01'))) == 0


def test_calendar_dst_and_non_mutation():
    source = [match(_timestamp_utc=datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc).timestamp()), match(2, _timestamp_utc=datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc).timestamp())]
    original = deepcopy(source)
    result = localize(source, 'America/Los_Angeles')
    assert source == original
    assert availability(result) == {'2026-11-01': 2}
    assert all(m['Time'] == '01:30' for m in result)


@pytest.mark.parametrize('name,expected', [('Last 7 Days', ('2026-10-17','2026-10-23')), ('Last 30 Days', ('2026-09-24','2026-10-23')), ('This Month', ('2026-10-01','2026-10-23')), ('All Time', (None,None))])
def test_date_presets(name, expected):
    assert preset(name, date(2026, 10, 23)) == expected


@pytest.mark.parametrize('args,expected', [((2026,1,-1),(2025,12)), ((2026,12,1),(2027,1)), ((2026,2,-12),(2025,2)), ((2026,2,12),(2027,2))])
def test_month_year_navigation(args, expected):
    assert shift_month(*args) == expected
    days = [d for w in month_days(2024, 2) for d in w]
    assert date(2024, 2, 29) in days and len(days) % 7 == 0


def test_identity_rename_keeps_keys_aliases_settings_and_backup(identities):
    old = identities.path.read_bytes()
    settings = SettingsStore(identities.path.parent / 'settings.json'); settings.save({'trend_teammates':['Buddy A']})
    identities.edit_person('Buddy A', 'David', 'Buddy A')
    again = IdentityMap(identities.path)
    assert set(again.people) == set(identities.people) and 'David' not in again.people
    assert again.label('Buddy A') == 'David (Buddy A)'
    assert again.person_name('david (buddy a)') == 'Buddy A' and again.person_name('buddy a') == 'Buddy A'
    assert again.resolve('Emberguard','SandboxRealm') == 'Buddy A'
    assert settings.load()['trend_teammates'] == ['Buddy A']
    assert any(p.read_bytes() == old for p in identities.path.parent.glob('backups/*/people.json'))
    with pytest.raises(ValueError):
        again.edit_person('Buddy B', 'David', 'Buddy A')


def test_exact_realm_reassignment_and_similar_names(identities):
    identities.assign('Skárö-ExampleWorld104', 'Buddy A'); identities.assign('Skárö-ExampleWorld017','Buddy B')
    assert identities.resolve('SKÁRÖ','ExampleWorld104') == 'Buddy A'
    assert identities.resolve('Ska\u0301ro\u0308', 'ExampleWorld017') == 'Buddy B'
    assert identities.resolve('Emberg','ExampleWorld104') == 'Unassigned'
    identities.assign('Skárö-ExampleWorld104','Buddy C')
    assert identities.resolve('Skárö','ExampleWorld104') == 'Buddy C'
    identities.unassign('Skárö-ExampleWorld104'); assert identities.resolve('Skárö','ExampleWorld104') == 'Unassigned'
    assert identities.resolve('Unboundleaf','ExampleRealm') == 'Unassigned'


def test_character_search_rank_unicode_realm_and_fuzzy(identities):
    m = match(); rows = [roster(m,n,Realm=r) for n,r in [('Emberguard','ExampleWorld104'),('Emberguard','SandboxRealm'),('Emberg','ExampleWorld017'),('Pebblebrew','ExampleRealm'),('Pebblepaw','ExampleRealm'),('Árwen','ExampleWorld017')]]
    entries = catalogue([m], rows, identities)
    assert suggestions(entries,'eMbErG')[0]['name'] == 'Emberg'
    assert [e['name'] for e in suggestions(entries,'Pebble')][:2] == ['Pebblebrew','Pebblepaw']
    assert suggestions(entries,'mberguard')[0]['name'] == 'Emberguard'
    assert suggestions(entries,'Embergurad')[0]['name'] == 'Emberguard'
    assert len([e for e in suggestions(entries,'Emberguard') if e['name']=='Emberguard']) == 2
    assert suggestions(entries,'A\u0301rw')[0]['name'] == 'Árwen'


def test_together_paired_friend_stats_unknown_attendance(identities):
    m = match(); rows = [roster(m,'Asterknight',1000), roster(m,'Emberguard',500)]
    selections = [selection('Asterknight'), {'kind':'person','person':'Buddy A','label':'Buddy A'}]
    result = compare([m], rows, identities, selections, 'Played Together', window=1)
    assert [s['summary']['games'] for s in result['series']] == [1,1]
    assert result['paired'][0]['differences']['Damage'] == 500
    assert result['series'][1]['summary']['metrics']['Damage per minute']['count'] == 0
    assert result['series'][0]['summary']['metrics']['Damage per minute']['mean'] == 200
    assert result['series'][1]['summary']['metrics']['Damage rank']['mean'] == 2
    assert result['series'][1]['summary']['known_results'] == 1
    from pvpledger_viewer.comparisons import paired_text
    report=paired_text(result)
    assert 'PAIRED MATCHES' in report and 'Damage: 500' in report and 'Unknown' in report
    assert '_owner_key' not in report and '_event' not in report


def test_independent_characters_include_roster_history_and_enemy_results(identities):
    a, b = match(), match(2, owner='Mossweaver', Result='L')
    rows = [roster(a,'Emberguard',500,team='Enemy'),roster(a,'Asterknight'),roster(b,'Pebblebrew',900),roster(b,'Mossweaver')]
    values = [selection('Emberguard'), selection('Pebblebrew')]
    together = compare([a,b],rows,identities,values,'Only Shared Matches')
    assert all(s['summary']['games']==0 for s in together['series'])
    independent = compare([a,b],rows,identities,values)
    assert [s['summary']['losses'] for s in independent['series']] == [1,1]
    assert 'Independent samples' in independent['note']


def test_cross_owner_same_event_not_double_counted(identities):
    a = match(); b = match(2, owner='Mossweaver', _timestamp_utc=a['_timestamp_utc']+1)
    names = ['Asterknight','Mossweaver','Emberguard']
    rows_a = [roster(a,n,500+i*100) for i,n in enumerate(names)]
    rows_b = [roster(b,n,500+i*100) for i,n in enumerate(names)]
    assert same_event(a,b,rows_a,rows_b)
    result = compare([a,b],rows_a+rows_b,identities,[{'kind':'person','person':'Me','label':'Me'},{'kind':'person','person':'Buddy A','label':'Buddy A'}])
    assert [s['summary']['games'] for s in result['series']] == [1,1]
    assert result['series'][0]['summary']['metrics']['Damage']['count'] == 0 # two actual Me characters; no fictional sum
    assert result['series'][1]['summary']['metrics']['Damage']['count'] == 1
    assert len(participant_records([a,b],rows_a+rows_b)) == 3
    assert not same_event(a,b,[],[]) # timestamp/map alone never sufficient


def test_my_characters_keeps_types_separate_and_gear_filter(identities):
    a,b,c = match(),match(2,owner='Mossweaver',Type='Rated arena'),match(3,owner='Dawnstalker',**{'PvP item level':None})
    result = compare([a,b,c],[],identities,[selection('Asterknight'),selection('Mossweaver'),selection('Dawnstalker')],window=1)
    assert [s['summary']['games'] for s in result['series']] == [1,1,1]
    assert set(result['series'][0]['by_type']) == {'Battleground'}
    assert set(result['series'][1]['rolling_by_type']) == {'Rated arena'}
    filtered = compare([a,b,c],[],identities,[selection('Asterknight'),selection('Dawnstalker')],item_min=330,item_max=350)
    assert [s['summary']['games'] for s in filtered['series']] == [1,0]


def test_partial_scoreboard_cannot_invent_ranks_or_unknown_zero(identities):
    m=match(_scoreboard_incomplete=True,**{'Minutes played':None,'Damage':None})
    rows=[roster(m,'Asterknight',damage=None,_scoreboard_incomplete=True),roster(m,'Emberguard',damage=0,_scoreboard_incomplete=True)]
    result=compare([m],rows,identities,[selection('Asterknight'),selection('Emberguard')])
    me,friend=[s['summary']['metrics'] for s in result['series']]
    assert me['Damage']['count']==0 and friend['Damage']['mean']==0
    assert friend['Damage rank']['count']==0 and friend['Deaths per 10 minutes']['count']==0


def test_identity_edit_retroactive_without_archive_mutation(identities):
    m=match(); rows=[roster(m,'Unmapped',500),roster(m,'Asterknight')]; before=deepcopy((m,rows))
    selections=[selection('Asterknight'),{'kind':'person','person':'Buddy B','label':'Buddy B'}]
    assert compare([m],rows,identities,selections)['series'][1]['summary']['games']==0
    identities.assign('Unmapped-ExampleRealm','Buddy B')
    assert compare([m],rows,identities,selections)['series'][1]['summary']['games']==1
    identities.assign('Unmapped-ExampleRealm','Buddy C')
    assert compare([m],rows,identities,selections)['series'][1]['summary']['games']==0
    assert (m,rows)==before


def test_real_archive_calendar_reflex_and_combined_counts(tmp_path):
    home=tmp_path/'archive'; a=Archive(home)
    data=Path(__file__).parent/'fixtures/v1_1'
    for name in ('PvPLedger.lua','REFlex.lua'):
        a.import_file(data/name,'Asterknight','ExampleRealm')
    a.close(); service=DesktopService(home)
    payload=service.snapshot()
    assert sum(payload['calendar'].values())==94
    assert any(d<'2030-10-21' for d in payload['calendar'])
    result=service.compare([selection('Asterknight'),selection('Emberguard','SandboxRealm')])
    assert result['series'][0]['summary']['games']==94
    before=(home/'archive.sqlite').read_bytes()
    service.edit_person('Buddy A','David','Buddy A')
    assert (home/'archive.sqlite').read_bytes()==before
    assert service.snapshot()['person_labels']['Buddy A']=='David (Buddy A)'


def test_comparison_multi_metric_png(tmp_path,identities):
    from pvpledger_viewer.comparison_charts import export_png
    from PIL import Image
    model=compare([match(),match(2,owner='Mossweaver')],[],identities,[selection('Asterknight'),selection('Mossweaver')],window=1)
    path=tmp_path/'comparison.png'; export_png(path,model,['Win rate','Damage per minute','PvP item level'])
    with Image.open(path) as image:
        assert image.width==1560 and image.height==1440


def test_gui_calendar_search_people_comparisons_and_persistence(tmp_path):
    import tkinter as tk
    from pvpledger_viewer.ui.app import LedgerApp
    from pvpledger_viewer.ui.calendar import CalendarDialog
    from pvpledger_viewer.ui.people import PeopleDialog
    home=tmp_path/'archive'; service=DesktopService(home); service.refresh(files=[FIXTURE])
    root=tk.Tk(); root.withdraw(); app=LedgerApp(root,home,autostart=False)
    def pump():
        until=time.monotonic()+15
        while (app.tasks.pending or app.closing and not app.tasks.closed) and time.monotonic()<until:
            root.update(); time.sleep(.01)
        assert app.tasks.pending==0
    try:
        app.reload(); pump()
        dialog=CalendarDialog(app); dialog.mode.set('Single Day'); dialog.pick('2026-10-22'); dialog.apply(); pump()
        assert app.filters.start==app.filters.end=='2026-10-22'
        dialog=CalendarDialog(app); dialog.move(-12); assert dialog.year==2025; dialog.destroy()
        app.reset_filters(); pump()
        panel=app.views['Character Comparison'].advanced
        panel.render(app.payload); panel.a.text.set('Emberg')
        assert panel.a.selected is None and panel.a.hits[0]['name']=='Emberguard'
        panel.a.list.selection_set(0); panel.a.confirm(); assert panel.a.selected['name']=='Emberguard'
        panel.b.restore(next(e['key'] for e in app.payload['catalogue'] if e['name']=='Asterknight'))
        panel.request(); pump(); assert panel.model['series'][0]['summary']['games']>0
        panel.mode.set('Me vs Friends'); panel.a.text.set(''); panel.b.text.set(''); panel.friend.set('Buddy D'); panel.layout(); panel.request(); pump()
        assert panel.model['series'][1]['summary']['games']==0
        people=PeopleDialog(app); people.person.set('Buddy A'); people.load_person(); people.name.set('David'); people.nick.set('Buddy A'); people.save_person(); pump()
        assert app.payload['person_labels']['Buddy A']=='David (Buddy A)'
        root.deiconify(); root.update()
        for width,height in ((1280,720),(1600,900)):
            root.geometry(f'{width}x{height}')
            until=time.monotonic()+2
            while root.winfo_width()!=width and time.monotonic()<until:
                root.update(); time.sleep(.01)
            assert root.winfo_width()==width
        app.config['date_mode']='Date Range'
        app.close(); pump()
        saved=SettingsStore(home/'settings.json').load()
        assert saved['date_mode']=='Date Range' and saved['advanced_comparison']['Character vs Character']['mode']=='Me vs Friends'
    finally:
        if not app.tasks.closed:
            app.tasks.close(); root.destroy()


def test_worker_releases_gui_callbacks_on_caller_thread():
    import gc, threading
    from pvpledger_viewer.background import BackgroundTasks
    caller=threading.get_ident(); released=[]
    class Callback:
        def __call__(self, result):
            assert result==42
        def __del__(self):
            released.append(threading.get_ident())
    worker=BackgroundTasks(); callback=Callback()
    future=worker.submit(lambda:42,callback,pytest.fail)
    del callback
    assert future.result(timeout=3)==42
    until=time.monotonic()+3
    while worker.results.empty() and time.monotonic()<until:
        time.sleep(.01)
    worker.drain(); gc.collect()
    assert released==[caller]
    worker.close()


def test_existing_v11_profile_backup_precedes_identity_edits(tmp_path):
    from pvpledger_viewer.upgrade import ensure_profile_backup
    home=tmp_path/'legacy'; home.mkdir()
    import sqlite3
    db=sqlite3.connect(home/'archive.sqlite'); db.execute('CREATE TABLE preserved(value)'); db.execute("INSERT INTO preserved VALUES ('keep')"); db.commit(); db.close()
    old={'people':{'Me':['Asterknight'],'Buddy A':['Emberguard'],'Unassigned':['Unboundleaf']}}
    (home/'people.json').write_text(json.dumps(old),encoding='utf8')
    (home/'settings.json').write_text('{"trend_teammates":["Buddy A"]}',encoding='utf8')
    before=(home/'archive.sqlite').read_bytes()
    ensure_profile_backup(home)
    backup=Path(json.loads((home/'upgrade-1.2.json').read_text())['backup'])
    check=sqlite3.connect(backup/'archive.sqlite')
    assert check.execute('SELECT value FROM preserved').fetchall()==[('keep',)]
    assert check.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    check.close()
    assert json.loads((backup/'people.json').read_text())==old
    identity=IdentityMap(home/'people.json'); identity.edit_person('Buddy A','David','Buddy A')
    assert (home/'archive.sqlite').read_bytes()==before
    assert json.loads((backup/'people.json').read_text())==old
    identity.replace_association('Emberguard','Emberguard-SandboxRealm','Buddy A')
    assert identity.resolve('Emberguard','SandboxRealm')=='Buddy A'
    assert identity.resolve('Emberguard','ExampleWorld104')=='Unassigned'
    assert identity.people['Buddy A']==['Emberguard-SandboxRealm']


def test_comparison_exact_realm_choices(identities):
    m=match(); rows=[roster(m,'Twin',100,Realm='ExampleWorld104'),roster(m,'Twin',500,Realm='ExampleWorld017')]
    result=compare([m],rows,identities,[selection('Twin','ExampleWorld104'),selection('Twin','ExampleWorld017')],'Only Shared Matches')
    assert [s['summary']['metrics']['Damage']['mean'] for s in result['series']]==[100,500]

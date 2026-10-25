import base64
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import pytest
from pvpledger_viewer.archive import Archive
from pvpledger_viewer.service import DesktopService
from pvpledger_viewer.schema import parse_row
from pvpledger_viewer.lua_reader import loads, sequence
from pvpledger_viewer.sync import stable_read, SyncSchedule, sidecar
from pvpledger_viewer.player_index import rebuild, directory, encounters
from pvpledger_viewer.rankings import rank, historical, SCOPES
from pvpledger_viewer.metric_registry import METRICS, values
from pvpledger_viewer.full_export import export_dump, validate, Cancelled
from pvpledger_viewer.identity import IdentityMap
from test_core import match, roster, write_source, FIXTURE
from test_dual_archive import lua

V5=Path(__file__).parent/'fixtures/v1_3/PvPLedger.lua'


@pytest.fixture
def profile(tmp_path):
    home=tmp_path/'archive';a=Archive(home);a.import_file(FIXTURE);a.close()
    IdentityMap(home/'people.json')
    return home


def test_verified_real_schema5_epoch_and_retained_trailing_fields():
    doc=loads(V5.read_text(encoding='utf8'))['PvPLedgerDB']
    raw=sequence(doc['matchCSV'])[0];issues=[];m=parse_row(raw,'match',issues)
    assert m['Schema version']==5 and isinstance(m['Epoch'],int)
    assert m['Damage'] is not None and m['PvP item level'] is not None and m['_raw']==raw
    assert not any(i['code'] in ('extra_columns','unknown_schema') for i in issues)
    future=parse_row(raw+',unknown,new','match',[])
    assert future['_unknown_trailing_fields']==['unknown','new']
    r=parse_row(sequence(doc['rosterCSV'])[0],'roster',issues)
    assert r['Schema version']==5
    assert not any(i['code']=='unknown_schema' for i in issues)
    import re
    source=(Path(__file__).parents[1]/'reference/addon_v5/PvPLedger.lua').read_text(encoding='utf8')
    header=re.search(r'local MATCH_HEADER = \{(.*?)\}',source,re.S)[1]
    assert re.findall(r'"([^"]+)"',header)[-2:]==['Attendance ticks','Epoch']


def test_schema5_import_reimport_and_legacy_main_schema(tmp_path):
    a=Archive(tmp_path/'archive');before=hashlib.sha256(V5.read_bytes()).hexdigest()
    first=a.import_file(V5);totals=a.totals();second=a.import_file(V5)
    assert first['status']=='ok' and totals['total']==41 and totals['rosters']==835
    assert totals==a.totals() and second['matches_added']==second['roster_added']==0
    assert a.db.execute('pragma user_version').fetchone()[0]==2
    assert any(m.get('Epoch') for m in a.read_matches())
    assert len(list((a.home/'snapshots').glob('*.lua')))==1
    assert hashlib.sha256(V5.read_bytes()).hexdigest()==before;a.close()


def test_schema5_historical_recovery_does_not_change_archive(tmp_path):
    h=tmp_path/'archive';a=Archive(h);a.import_file(V5)
    # Emulate an earlier limited structured fallback; raw history stays intact.
    for row in a.db.execute('SELECT character,realm,match_id,data FROM matches').fetchall():
        m=json.loads(row['data']);m['PvP item level']=None;m['Minutes played']=None;m['Epoch']=None
        a.db.execute('UPDATE matches SET data=? WHERE character=? AND realm=? AND match_id=?',(json.dumps(m),*tuple(row)[:3]))
    a.db.commit();a.close();original=(h/'archive.sqlite').read_bytes()
    result=rebuild(h)
    assert result['recovery']['records']==38 and result['recovery']['fields']>0
    assert any(r.get('Minutes played') for r in encounters(h))
    assert (h/'archive.sqlite').read_bytes()==original


def test_sync_unchanged_changed_shrunk_and_removed(tmp_path):
    game=tmp_path/'Game';source=game/'_retail_/WTF/Account/A/Realm/Me/SavedVariables/PvPLedger.lua';source.parent.mkdir(parents=True)
    write_source(source,[match(),match('20261022-120100')]);service=DesktopService(tmp_path/'archive')
    a=service.refresh(game);b=service.refresh(game)
    assert a['changed']==1 and b['skipped']==1 and b['changed']==b['matches_added']==0
    write_source(source,[match()]);c=service.refresh(game)
    assert c['changed']==1 and c['matches_added']==0
    archive=Archive(service.home);assert archive.totals()['total']==2;archive.close()
    source.unlink();d=service.refresh(game)
    assert d['removed']==[str(source.resolve())] and d['failures']==0
    archive=Archive(service.home);assert archive.totals()['total']==2;archive.close()
    db=sidecar(service.home);assert [r[0] for r in db.execute('SELECT status FROM sync_runs')]==['ok']*4;db.close()


def test_sync_bad_files_retry_and_retain_history(tmp_path,profile):
    source=tmp_path/'bad.lua';source.write_text('PvPLedgerDB={')
    service=DesktopService(profile);a=service.refresh(files=[source]);b=service.refresh(files=[source])
    assert a['failures']==b['failures']==1
    archive=Archive(profile);assert archive.totals()['total']==10
    assert all(r['status']=='failed' for r in archive.diagnostics()[-2:]);archive.close()
    assert len(list((profile/'snapshots').glob('*.lua')))==3 # original + two first failed attempts; later retries reuse


def test_stable_reader_rejects_changed_bytes_and_retries_locks(tmp_path,monkeypatch):
    p=tmp_path/'file.lua';p.write_bytes(b'original');original=Path.read_bytes;calls=[]
    def changing(self):
        if self==p:
            calls.append(1);return b'a' if len(calls)%2 else b'b'
        return original(self)
    monkeypatch.setattr(Path,'read_bytes',changing)
    with pytest.raises(OSError,match='changed during reading'):stable_read(p,pause=0)
    calls.clear()
    def locked(self):
        if self==p and not calls:calls.append(1);raise PermissionError('locked')
        return original(self)
    monkeypatch.setattr(Path,'read_bytes',locked)
    assert stable_read(p,pause=0)[0]==b'original'


def test_five_minute_startup_manual_schedule_no_overlap():
    now=[0];schedule=SyncSchedule(lambda:now[0])
    assert schedule.interval==300 and schedule.claim(manual=True)
    assert not schedule.claim(manual=True)
    schedule.finish();now[0]=299;assert not schedule.claim()
    now[0]=300;assert schedule.claim();assert not schedule.claim(manual=True)
    schedule.finish();assert schedule.next_due==600


def test_concurrent_sync_only_one_job(profile,monkeypatch):
    import pvpledger_viewer.sync as module
    entered=threading.Event();release=threading.Event();original=module.stable_read
    def blocking(path,*a,**kw):entered.set();release.wait(4);return original(path,*a,**kw)
    monkeypatch.setattr(module,'stable_read',blocking)
    service=DesktopService(profile);results=[]
    thread=threading.Thread(target=lambda:results.append(service.refresh(files=[FIXTURE])));thread.start();assert entered.wait(2)
    second=service.refresh(files=[FIXTURE]);assert second['busy']
    release.set();thread.join(5);assert len(results)==1 and not results[0]['failures']


def test_index_includes_superseded_snapshot_players_and_unknown_realms(tmp_path):
    p=tmp_path/'PvPLedger.lua';home=tmp_path/'archive'
    early=[roster('20261022-120000','EarlierOnly',realm='')]
    later=[roster('20261022-120020',name) for name in ('Later','Other')]
    write_source(p,(),early+later);a=Archive(home);a.import_file(p,'Me','Realm');a.close()
    result=rebuild(home);found=directory(home,'EarlierOnly')['rows']
    assert found and found[0]['Realm certainty']=='unknown'
    assert result['players']>=4
    assert len(encounters(home,found[0]['player_key']))==1


def test_unresolved_records_and_auxiliary_data_retained(tmp_path):
    path=tmp_path/'PvPLedger.lua';home=tmp_path/'archive'
    write_source(path,[match(character='A'),match('20261022-120100',character='B')],[roster('unknown','Unresolved')])
    a=Archive(home);a.import_file(path);a.close()
    assert rebuild(home)['unresolved']>0


def test_reflex_realms_observed_inferred_and_unicode(tmp_path):
    h=tmp_path/'archive';p=tmp_path/'REFlex.lua'
    players=[['Asterknight',1,2,3,4,0,'Human','Paladin','PALADIN',100,200,0,1,0,0,'Retribution'],
             ['Árwen',1,2,3,4,1,'Elf','Mage','MAGE',500,100,0,1,0,0,'Frost'],
             ['Árwen-ExampleWorld104',1,2,3,4,1,'Elf','Mage','MAGE',500,100,0,1,0,0,'Frost']]
    p.write_text('REFlexDatabase='+lua([{'Version':3501,'Time':1792780000,'Map':1,'Duration':300,'isArena':False,'PlayerSide':0,'Winner':0,'PlayerNum':1,'PlayersNum':3,'Players':players}]),encoding='utf8')
    a=Archive(h);a.import_file(p,'Asterknight','ExampleRealm');a.close();rebuild(h)
    found=directory(h,'árw')['rows'];assert len(found)==2
    assert {r['Realm certainty'] for r in found}=={'inferred','observed'}
    assert directory(h,'arwen')['total']>=0 # fuzzy only, no identity merging


@pytest.mark.parametrize('metric',list(METRICS))
def test_every_metric_rank_direction_zero_null(metric):
    rows=[{'Player':'A','Team':'Mine',metric:10,'Minutes played':1},
          {'Player':'B','Team':'Mine',metric:0,'Minutes played':1},
          {'Player':'C','Team':'Mine',metric:None,'Minutes played':1}]
    if metric.endswith(' per minute'):rows[0][METRICS[metric]['source_field']]=10;rows[1][METRICS[metric]['source_field']]=0
    if metric=='Deaths per 10 minutes':rows[0]['Deaths']=1;rows[1]['Deaths']=0
    result=rank(rows,metric)
    assert result['eligible']==2 and result['excluded']==1
    assert result['rows'][0]['Player']==('A' if METRICS[metric]['higher_is_better'] else 'B')
    assert not result['complete']


@pytest.mark.parametrize('scope',SCOPES)
def test_ranking_cohorts_ties_and_quality(scope):
    rows=[{'Player':n,'Damage':v,'Team':t,'Class':'Mage','Spec':s,'_cohort_verified_complete':True} for n,v,t,s in [('A',100,'Mine','Frost'),('B',100,'Mine','Frost'),('C',20,'Enemy','Fire')]]
    result=rank(rows,'Damage',scope,rows[0])
    expected={'My team':2,'Opposing team':1,'All recorded participants':3,'Same class':3,'Same specialization':2,'Class in my team':2,'Spec in my team':2,'Class in opposing team':1,'Spec in opposing team':0}[scope]
    assert result['eligible']==expected and result['complete']==bool(expected)
    assert [r['Rank'] for r in rank(rows)['rows']]==[1,1,3]
    rows[0]['_cohort_verified_complete']=False
    assert not rank(rows,'Damage',scope,rows[0])['complete']
    assert all('observed eligible' in r['Coverage'] for r in rank(rows)['rows'])


def test_historical_mean_median_and_known_attendance():
    rows=[{'Player':'A','player_key':'a','Damage':v,'Minutes played':2} for v in (0,20,100)]
    rows.append({'Player':'B','player_key':'b','Damage':None})
    assert historical(rows,'Damage','Player averages')['rows'][0]['Value']==40
    assert historical(rows,'Damage','Player medians')['rows'][0]['Value']==20
    assert historical(rows,'Damage per minute','Player averages')['rows'][0]['Value']==20
    assert historical(rows,'Damage','Player averages',minimum=4)['eligible']==0
    assert values({'Damage':100,'Duration (s)':60})['Damage per minute'] is None


def test_objective_registry_is_map_specific_and_preserves_unknowns():
    row={'Map':'Arathi Basin','Objectives':'Bases Assaulted=0; Bases Defended=3; Unverified Thing=99'}
    result=values(row);name='Objective · Arathi Basin · Bases Defended'
    assert result[name]==3 and result['Objective · Arathi Basin · Bases Assaulted']==0
    assert not any('Unverified Thing' in k for k in METRICS)


@pytest.mark.parametrize('compressed',[False,True])
def test_complete_export_all_tables_blobs_raw_keys_and_source_bytes(profile,tmp_path,compressed):
    rebuild(profile);p=profile/'auxiliary.lua';p.write_text('Extra={[1]="numeric",["1"]="string",name="Árwen"}',encoding='utf8')
    db=sqlite3.connect(profile/'archive.sqlite');db.execute('CREATE TABLE future_records(id INTEGER,unexpected TEXT,blob BLOB)');db.execute('INSERT INTO future_records VALUES (?,?,?)',(1,'Unicode 雪',b'\x00\xff'));db.commit();db.close()
    before=(profile/'archive.sqlite').read_bytes();path=tmp_path/('dump.json.gz' if compressed else 'dump.json')
    result=export_dump(profile,path);assert result['validation']['table_counts']['future_records']==1
    with (gzip.open(path,'rt',encoding='utf8') if compressed else path.open(encoding='utf8')) as f:data=json.load(f)
    assert data['manifest']['full_archive'] and len(data['logical_matches'])==10
    assert data['database']['future_records']['rows'][0]['unexpected']=='Unicode 雪'
    assert base64.b64decode(data['database']['future_records']['rows'][0]['blob']['base64'])==b'\x00\xff'
    artifacts={r['path']:r for r in data['profile_artifacts']}
    assert base64.b64decode(artifacts['auxiliary.lua']['bytes'])==p.read_bytes()
    assert loads(base64.b64decode(artifacts['auxiliary.lua']['bytes']).decode())['Extra'][1]=='numeric'
    assert len([r for r in artifacts if r.startswith('snapshots')])==1
    assert data['analytical_indexes']['sightings']['rows']
    assert (profile/'archive.sqlite').read_bytes()==before


def test_filtered_dump_dependency_context_and_selected_player(profile,tmp_path):
    rebuild(profile);player=directory(profile,'Emberguard')['rows'][0]
    path=tmp_path/'filtered.json';export_dump(profile,path,'Selected Players',players=[player['player_key']])
    data=json.loads(path.read_text(encoding='utf8'))
    assert not data['manifest']['full_archive'] and data['manifest']['include_full_source_context']
    assert len(data['logical_matches'])>0
    assert any(r['path'].startswith('snapshots') for r in data['profile_artifacts'])


def test_export_missing_snapshot_corruption_cancel_and_atomicity(profile,tmp_path):
    destination=tmp_path/'dump.json';destination.write_text('existing')
    with pytest.raises(Cancelled):export_dump(profile,destination,cancel=lambda:True)
    assert destination.read_text()=='existing' and not list(tmp_path.glob('ai-dump-*'))
    snapshot=next((profile/'snapshots').glob('*.lua'));original=snapshot.read_bytes();snapshot.write_bytes(b'changed')
    with pytest.raises(ValueError,match='hash mismatch'):export_dump(profile,destination)
    assert destination.read_text()=='existing'
    snapshot.write_bytes(original);snapshot.unlink()
    with pytest.raises(OSError):export_dump(profile,destination)


def test_export_finished_hash_validation(profile,tmp_path):
    path=tmp_path/'dump.json';export_dump(profile,path)
    raw=path.read_bytes();path.write_bytes(raw.replace(b'Full Archive',b'Fool Archive',1))
    with pytest.raises(ValueError,match='integrity mismatch'):validate(path)


def test_verified_copy_preserves_original_and_rewrites_snapshot_paths(profile,tmp_path):
    from pvpledger_viewer.profile import relocate
    before=(profile/'archive.sqlite').read_bytes();destination=tmp_path/'moved'
    relocate(profile,destination)
    assert (profile/'archive.sqlite').read_bytes()==before
    db=sqlite3.connect(destination/'archive.sqlite');assert db.execute('pragma user_version').fetchone()[0]==2
    assert all(Path(r[0]).is_relative_to(destination) for r in db.execute('SELECT snapshot FROM imports'));db.close()
    assert not (destination/'COPY_INCOMPLETE').exists()
    with pytest.raises(ValueError):relocate(profile,destination)


def test_full_dump_disk_full_is_not_published(profile,tmp_path,monkeypatch):
    import pvpledger_viewer.full_export as module
    def failed(*a,**kw):raise OSError('disk full')
    monkeypatch.setattr(module,'validate',failed)
    path=tmp_path/'dump.json'
    with pytest.raises(OSError,match='disk full'):export_dump(profile,path)
    assert not path.exists() and not list(tmp_path.glob('ai-dump-*'))


def test_historical_complete_scoreboard_is_still_observed_population():
    row={'Player':'A','Realm':'R','player_key':'a','Damage':12,'_cohort_verified_complete':True}
    assert not historical([row],'Damage')['complete']
    with pytest.raises(ValueError):historical([row],'Damage',minimum=0)


def test_large_artifact_streaming_and_cancel_during_write(profile,tmp_path):
    artifact=profile/'large.bin';artifact.write_bytes(b'0123456789abcdef'*655360)
    path=tmp_path/'large.json.gz';result=export_dump(profile,path)
    assert result['validation']['artifacts']>=2
    with gzip.open(path,'rt',encoding='utf8') as stream:data=json.load(stream)
    embedded=next(r for r in data['profile_artifacts'] if r['path']=='large.bin')
    assert embedded['size']==10485760 and hashlib.sha256(base64.b64decode(embedded['bytes'])).hexdigest()==hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert data['completeness']['participant_metric_coverage']['Damage']['known']>0
    calls=[0]
    def cancel():calls[0]+=1;return calls[0]>350
    previous=path.read_bytes()
    with pytest.raises(Cancelled):export_dump(profile,path,cancel=cancel)
    assert path.read_bytes()==previous and not list(tmp_path.glob('ai-dump-*'))


def test_export_serializes_import_and_keeps_consistent_counts(profile,tmp_path):
    started=threading.Event();finished=threading.Event();worker=[];reports=[]
    def import_again():
        started.set();reports.append(DesktopService(profile).refresh(files=[FIXTURE]));finished.set()
    def progress(message):
        if not worker:
            t=threading.Thread(target=import_again);worker.append(t);t.start();assert started.wait(2)
            assert finished.wait(2) and reports[0]['busy'] is True
    path=tmp_path/'coherent.json';export_dump(profile,path,progress=progress)
    worker[0].join(10);assert finished.is_set()
    data=json.loads(path.read_text(encoding='utf8'))
    assert len(data['database']['imports']['rows'])==1
    assert len(data['logical_matches'])==10
    assert not DesktopService(profile).refresh(files=[FIXTURE]).get('busy')


def test_missing_snapshot_participants_retained_via_observation_versions(profile):
    original=directory(profile)['total']
    next((profile/'snapshots').glob('*.lua')).unlink()
    result=rebuild(profile,force=True)
    assert result['unresolved']>0 and directory(profile)['total']==original


def test_directory_handles_metrics_discovered_on_later_maps(profile,monkeypatch):
    import pvpledger_viewer.player_index as module
    rows=encounters(profile)
    player=rows[0]['player_key'];older=deepcopy(rows[0]);newer=deepcopy(rows[0])
    newer['metrics']['Objective · Later Map · Bases Defended']=3
    monkeypatch.setattr(module,'encounters',lambda home:[older,newer])
    result=directory(profile)
    assert result['total']==1 and result['rows'][0]['player_key']==player
    assert 'Later Map' in result['rows'][0]['Available statistics']


def test_source_count_equality_does_not_prove_complete_team(tmp_path):
    p=tmp_path/'REFlex.lua';h=tmp_path/'archive'
    players=[['Asterknight',1,2,3,4,0,'Human','Paladin','PALADIN',100,200,0,1,0,0,'Retribution']]
    p.write_text('REFlexDatabase='+lua([{'Version':3501,'Time':1792780000,'Map':1,'Duration':300,'isArena':True,'PlayerSide':0,'Winner':0,'PlayerNum':1,'PlayersNum':1,'Players':players}]),encoding='utf8')
    a=Archive(h);a.import_file(p,'Asterknight','ExampleRealm');a.close()
    rows=encounters(h)
    assert rows and all(not r['_cohort_verified_complete'] for r in rows)
    assert not rank(rows,'Damage')['complete']

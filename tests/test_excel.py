import base64
from copy import deepcopy
import gzip,hashlib,json,sqlite3,zipfile
from pathlib import Path
import pytest
from pvpledger_viewer.archive import Archive
from pvpledger_viewer.excel_reader import read_workbook,duration,clock,day
from pvpledger_viewer.reconcile import reconcile,candidate,compare_fields,EXACT,PROBABLE,AMBIGUOUS,MISSING
from pvpledger_viewer.supplemental import commit,reverse,history,read_db,SOURCE
from pvpledger_viewer.service import DesktopService
from pvpledger_viewer.player_index import directory,encounters
from pvpledger_viewer.full_export import export_dump
from pvpledger_viewer.identity import IdentityMap
from test_core import match,roster,write_source

BOOK=Path(__file__).parent/'fixtures/excel/WoW_Match_Log.xlsx'


@pytest.fixture(scope='module')
def workbook():return read_workbook(BOOK)


@pytest.fixture
def home(tmp_path,workbook):
    return make_home(tmp_path,workbook)


def make_home(tmp_path,workbook):
    row=workbook['matches'][0]['normalized'];home=tmp_path/'archive';a=Archive(home)
    fields={k:v for k,v in row.items() if k not in ('Character','Realm','Objectives','Notes','Role') and v is not None};fields['Time']='10:59'
    p=write_source(tmp_path/'source.lua',[match('20301016-113600','Asterknight','ExampleRealm',**fields)],
        [roster('20301016-113600','Asterknight','ExampleRealm',**{'Is me':'Yes','Damage':row['Damage'],'Healing':row['Healing'],'KB':2,'HK':22})])
    a.import_file(p);a.close();IdentityMap(home/'people.json');return home


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def approved(report,classification=EXACT,action='link',fields=None):
    review=next(r for r in report['results'] if r['classification']==classification)
    row=next(r for r in report['workbook']['matches'] if r['id']==review['row_id'])
    choice={'row_id':row['id'],'action':action,'fields':fields if fields is not None else list(row['fields']),
            'realm':row['normalized']['Realm'],'reason':'Reviewed source evidence explicitly'}
    if action=='link':choice['target']=review['candidates'][0]['key']
    return choice,row


def test_real_workbook_all_sheets_cells_formulas_and_units(workbook):
    assert len(workbook['sheets'])==13 and len(workbook['matches'])==200 and len(workbook['rosters'])==413
    assert workbook['row_count']==796
    row=workbook['matches'][0]
    assert row['normalized']['Damage']==4226227 and row['normalized']['Duration (s)']==840
    assert row['normalized']['Honor (scoreboard)']==430
    assert row['fields']['Damage (M)']['original']==4.226227
    assert row['fields']['Damage / min (M)']['formula'].startswith('=IF(')
    assert any(s['name']=='Known Players' for s in workbook['sheets'])
    assert len(next(s for s in workbook['sheets'] if s['name']=='Guide')['cells'])==32
    assert workbook['sha256']==sha(BOOK)


@pytest.mark.parametrize('value,expected',[('1:17',77),('0:14:00',840),('',None),(5,None)])
def test_duration_units_are_not_guessed(value,expected):assert duration(value)==expected


def test_audit_readonly_exact_and_time_representation(home):
    before=sha(home/'archive.sqlite');book_hash=sha(BOOK);identities=sha(home/'people.json')
    r=reconcile(home,BOOK);first=r['results'][0]
    assert first['classification']==EXACT and not first['field_conflict']
    fields=first['candidates'][0]['fields'];assert next(f for f in fields if f['field']=='Time')['status']=='Identical'
    assert sha(home/'archive.sqlite')==before and sha(home/'people.json')==identities and sha(BOOK)==book_hash
    assert not (home/'supplemental.sqlite').exists()


def fake_audit(monkeypatch,workbook,variants):
    import pvpledger_viewer.reconcile as module
    rows=deepcopy(workbook);rows['matches']=rows['matches'][:1]
    evidence={tuple((m['Character'],m['Realm'],m['Match ID'])):[{'match':m,'roster':[],'provenance':{'test_source':'verified observation'}}] for m in variants}
    monkeypatch.setattr(module,'archive_evidence',lambda h:(variants,evidence,'generation',[]))
    return reconcile('.',BOOK,document=rows)


def sample_match(workbook):
    return deepcopy(workbook['matches'][0]['normalized'])|{'Realm':'ExampleRealm','Match ID':'known','Source':'PvP Ledger','_observation_ids':[1]}


def test_probable_when_timestamp_missing_and_no_false_exact(monkeypatch,workbook):
    m=sample_match(workbook);m['Time']=None
    result=fake_audit(monkeypatch,workbook,[m]);assert result['results'][0]['classification']==PROBABLE


def test_ambiguous_distinct_events_same_date_result_and_stats(monkeypatch,workbook):
    a=sample_match(workbook);b=a|{'Match ID':'different'}
    result=fake_audit(monkeypatch,workbook,[a,b]);assert result['results'][0]['classification']==AMBIGUOUS
    assert len(result['results'][0]['candidates'])==2


def test_same_date_result_alone_never_proves_a_match(monkeypatch,workbook):
    m=sample_match(workbook)
    for f in ('Time','Damage','Healing','Duration (s)','KB','HK','Honor (scoreboard)'):m[f]=None
    assert fake_audit(monkeypatch,workbook,[m])['results'][0]['classification']==MISSING


def test_other_character_perspective_is_not_owner_statistic(monkeypatch,workbook):
    m=sample_match(workbook);m['Character']='Mossweaver'
    assert fake_audit(monkeypatch,workbook,[m])['results'][0]['classification']==MISSING


def test_utc_local_and_dst_ambiguity(workbook):
    row=deepcopy(workbook['matches'][0]);row['timezone']='UTC';row['normalized']['Time']='17:59:00'
    m=sample_match(workbook);m['Time']='10:59';m['_source_timezone']='America/Los_Angeles'
    c=candidate(row,m,[{'match':m,'roster':[],'provenance':{}}],'UTC')
    assert c['exact_supported'] and c['time_difference_seconds']==0
    assert next(f for f in compare_fields(row,m,[{'match':m,'provenance':{}}]) if f['field']=='Time')['status']=='Identical'
    from pvpledger_viewer.reconcile import timestamps
    assert len(timestamps({'Date':'2026-11-01','Time':'01:30'},'America/Los_Angeles'))==2
    assert timestamps({'Date':'2026-03-08','Time':'02:30'},'America/Los_Angeles')==[]


def test_raw_addon_field_is_distinguished_from_excel_only(workbook):
    row=deepcopy(workbook['matches'][0]);m=sample_match(workbook);m['Damage']=None
    original=m|{'Damage':1510000};fields=compare_fields(row,m,[{'match':original,'provenance':{'snapshot_sha256':'raw'}}])
    damage=next(f for f in fields if f['field']=='Damage (M)')
    assert damage['status']=='Present in raw addon data but not normalized'
    assert damage['retained_addon_evidence'][0]['value']==1510000


def test_explicit_approval_link_idempotence_and_immutable_addons(home):
    r=reconcile(home,BOOK);choice,row=approved(r,fields=['Data source']);before=sha(home/'archive.sqlite');people=sha(home/'people.json')
    with pytest.raises(PermissionError):commit(home,r,[choice])
    assert not (home/'supplemental.sqlite').exists()
    first=commit(home,r,[choice],approved=True);second=commit(home,r,[choice],approved=True)
    assert first['decisions_added']==1 and second['decisions_added']==0
    assert len(history(home))==1 and sha(home/'archive.sqlite')==before and sha(home/'people.json')==people
    db=read_db(home);assert db.execute('select count(*) from workbooks').fetchone()[0]==1
    raw=db.execute('select original_bytes from workbooks').fetchone()[0];db.close();assert raw==BOOK.read_bytes()
    assert sqlite3.connect(home/'archive.sqlite').execute('pragma user_version').fetchone()[0]==2


def test_conflicting_excel_value_retained_without_replacing_addon(home):
    source=write_source(home.parent/'corrected.lua',[match('20301016-113600','Asterknight','ExampleRealm',**{'Date':'2030-10-16','Time':'10:59','Map':'The Battle for Gilneas','Type':'Battleground','Result':'L','Damage':2510000,'Healing':436000,'Duration (s)':840})])
    a=Archive(home);a.import_file(source);a.close()
    r=reconcile(home,BOOK);choice,row=approved(r,fields=['Damage (M)']);before=sha(home/'archive.sqlite')
    assert r['results'][0]['field_conflict']
    commit(home,r,[choice],approved=True)
    model=DesktopService(home).snapshot();m=model['history'][0]
    assert m['Damage']==2510000 and 'Excel supplement' in m['Source']
    assert m['_excel_supplements'][0]['original_values']['Damage (M)']['original']==4.226227
    assert sha(home/'archive.sqlite')==before


def test_approved_workbook_roster_is_searchable_without_identity_edits(home):
    r=reconcile(home,BOOK)
    row=next(row for row in r['workbook']['matches'] if row['sheet']=='PG Matches' and row['game']==48)
    choice={'row_id':row['id'],'action':'historical','fields':list(row['fields']),'include_roster':True,'realm':'ExampleRealm','reason':'Reviewed unmatched historical scoreboard'}
    people=sha(home/'people.json');main=sha(home/'archive.sqlite');commit(home,r,[choice],approved=True)
    service=DesktopService(home);model=service.snapshot();m=next(m for m in model['history'] if m.get('_excel_historical'))
    board=service.scoreboard(('Asterknight','ExampleRealm',m['Match ID']))
    assert sum(len(rows) for rows in board['teams'].values())>=len(row['roster'])
    player=row['roster'][0]['normalized']['Player'];found=directory(home,player)
    assert any(p['Player']==player for p in found['rows'])
    assert any(p['quality'].startswith('Excel;') for p in encounters(home) if p['Player']==player)
    assert sha(home/'archive.sqlite')==main and sha(home/'people.json')==people


def test_duplicate_approved_event_fingerprint_is_blocked_across_workbook_versions(home,tmp_path):
    r=reconcile(home,BOOK);choice,row=approved(r,MISSING,'historical');commit(home,r,[choice],approved=True)
    version=tmp_path/'same_cells_new_package.xlsx';version.write_bytes(BOOK.read_bytes())
    # Change only the temporary ZIP package comment, leaving every original
    # worksheet cell intact. A different workbook hash must not duplicate an event.
    with zipfile.ZipFile(version,'a') as z:z.comment=b'Regression fixture: revised package metadata'
    fresh=reconcile(home,version)
    new_row=next(x for x in fresh['workbook']['matches'] if x['sheet']==row['sheet'] and x['row']==row['row'])
    new_choice=choice|{'row_id':new_row['id']}
    assert fresh['workbook']['sha256']!=r['workbook']['sha256'] and new_row['fingerprint']==row['fingerprint']
    with pytest.raises(ValueError,match='already approved'):commit(home,fresh,[new_choice],approved=True)
    assert len(history(home))==1


def test_historical_event_browsing_rankings_and_reversal(home):
    r=reconcile(home,BOOK);choice,row=approved(r,MISSING,'historical');before=sha(home/'archive.sqlite');people=sha(home/'people.json')
    result=commit(home,r,[choice],approved=True);assert result['historical_events_added']==1
    service=DesktopService(home);model=service.snapshot();assert model['history_count']==2
    excel=next(m for m in model['history'] if m.get('_excel_historical'))
    assert excel['Source']==SOURCE and excel['_partial'] and excel['_scoreboard_incomplete'] and excel['Minutes played'] is None
    players=directory(home,'Asterknight');assert players['total']>=1
    sightings=encounters(home,perspective=('Asterknight','ExampleRealm',excel['Match ID']))
    assert len(sightings)==1 and sightings[0]['source']==SOURCE
    ranked=service.ranking(('Asterknight','ExampleRealm',excel['Match ID']));assert ranked['eligible']==1 and not ranked['complete']
    assert service.ranking(('Asterknight','ExampleRealm',excel['Match ID']),'Damage per minute')['eligible']==0
    with pytest.raises(PermissionError):reverse(home,row['id'])
    reverse(home,row['id'],approved=True);assert DesktopService(home).snapshot()['history_count']==1
    assert len(history(home))==2 and sha(home/'archive.sqlite')==before and sha(home/'people.json')==people
    assert not any(r['source']==SOURCE for r in encounters(home))


def test_tampered_workbook_evidence_and_stale_archive_rejected(home,tmp_path):
    r=reconcile(home,BOOK);choice,row=approved(r)
    changed=deepcopy(r);changed['workbook']['matches'][0]['normalized']['Damage']=999999
    with pytest.raises(ValueError,match='evidence changed'):commit(home,changed,[choice],approved=True)
    a=Archive(home);a.set_override(('Asterknight','ExampleRealm','20301016-113600'),'Map','Manual map');a.close()
    with pytest.raises(ValueError,match='Archive changed'):commit(home,r,[choice],approved=True)
    assert not (home/'supplemental.sqlite').exists()


@pytest.mark.parametrize('compressed',[False,True])
def test_full_ai_dump_includes_lossless_workbook_all_fields_decisions(home,tmp_path,compressed):
    r=reconcile(home,BOOK);choice,row=approved(r,MISSING,'historical');commit(home,r,[choice],approved=True)
    before=sha(home/'archive.sqlite');path=tmp_path/('full.json.gz' if compressed else 'full.json');export_dump(home,path)
    opener=gzip.open if compressed else open
    with opener(path,'rt',encoding='utf8') as f:data=json.load(f)
    supplemental=data['supplemental_archive'];assert len(supplemental['decisions']['rows'])==1
    w=supplemental['workbooks']['rows'][0];assert base64.b64decode(w['original_bytes']['base64'])==BOOK.read_bytes()
    source=json.loads(w['document']);assert len(source['sheets'])==13 and len(source['matches'])==200
    assert data['supplemental_dictionary'] and len(data['logical_matches'])==2
    assert sha(home/'archive.sqlite')==before


def test_workbook_changed_after_review_refused(home,tmp_path):
    copy=tmp_path/'book.xlsx';copy.write_bytes(BOOK.read_bytes());r=reconcile(home,copy);choice,_=approved(r)
    copy.write_bytes(copy.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='Workbook changed'):commit(home,r,[choice],approved=True)


def test_rejected_decision_has_no_projection_and_can_be_revised(home):
    r=reconcile(home,BOOK);choice,row=approved(r,action='reject',fields=[])
    commit(home,r,[choice],approved=True);assert DesktopService(home).snapshot()['history_count']==1
    fresh=reconcile(home,BOOK);choice,_=approved(fresh,fields=['Data source']);commit(home,fresh,[choice],approved=True)
    assert len(history(home))==2 and history(home)[0]['action']=='link'


def test_cli_read_only_audit_does_not_seed_profiles(home,tmp_path,capsys):
    from pvpledger_viewer.cli import main
    before=sha(home/'archive.sqlite');assert main(['--archive-dir',str(home),'reconcile',str(BOOK),'--output',str(tmp_path/'report')])==0
    data=json.loads(capsys.readouterr().out);assert data['counts']['MATCH ROWS']==200
    assert sha(home/'archive.sqlite')==before and not (home/'supplemental.sqlite').exists()


def test_exact_counterpart_cannot_be_imported_as_another_historical_match(home):
    r=reconcile(home,BOOK);choice,_=approved(r,EXACT,'historical')
    with pytest.raises(ValueError,match='exact identified counterpart'):commit(home,r,[choice],approved=True)
    assert not (home/'supplemental.sqlite').exists()


def test_unknown_realm_and_different_owner_manual_links_are_rejected(home):
    r=reconcile(home,BOOK);row=next(x for x in r['workbook']['matches'] if x['owner']=='Mossweaver')
    choice={'row_id':row['id'],'action':'historical','fields':list(row['fields'])}
    with pytest.raises(ValueError,match='realm must be supplied'):commit(home,r,[choice],approved=True)
    choice.update(action='link',target=r['results'][0]['candidates'][0]['key'],realm='ExampleRealm',reason='Manual cross-perspective test')
    with pytest.raises(ValueError,match='different character perspective'):commit(home,r,[choice],approved=True)


def test_duplicate_spreadsheet_rows_require_review_even_with_one_archive_candidate(monkeypatch,workbook):
    import pvpledger_viewer.reconcile as module
    from pvpledger_viewer.excel_reader import mark_duplicates
    document=deepcopy(workbook);first=deepcopy(document['matches'][0]);second=deepcopy(first);second.update(id='another-row',row=200,game=999)
    document['matches']=[first,second];mark_duplicates(document['matches']);m=sample_match(workbook)
    monkeypatch.setattr(module,'archive_evidence',lambda h:([m],{('Asterknight','ExampleRealm','known'):[{'match':m,'roster':[],'provenance':{}}]},'generation',[]))
    r=reconcile('.',BOOK,document=document)
    assert r['counts']['AMBIGUOUS MATCH']==2 and len(r['results'])==2
    assert first['duplicate_rows']==['another-row']


def test_zero_scoreboard_with_rating_and_timestamp_is_probable_not_discarded(workbook):
    row=deepcopy(workbook['matches'][0]);row['normalized'].update(Damage=0,Healing=0,**{'Duration (s)':0,'Rating change':96})
    m=sample_match(workbook);m.update(row['normalized']);m['Realm']='ExampleRealm'
    result=candidate(row,m,[{'match':m,'roster':[],'provenance':{}}],'America/Los_Angeles')
    assert result and not result['exact_supported'] and 'Rating change' in result['anchors']


def test_arena_local_game_numbers_do_not_attach_battleground_rosters(workbook):
    arenas=[r for r in workbook['matches'] if 'Arena' in r['fields']]
    assert arenas and all(not r['roster'] for r in arenas)
    assert any(r['roster'] for r in workbook['matches'] if 'Battleground' in r['fields'])


def test_workbook_objectives_and_notes_are_approved_with_source_units(home):
    r=reconcile(home,BOOK)
    row=next(row for row in r['workbook']['matches'] if row['owner']=='Mossweaver' and row['normalized'].get('Notes') and any(k.startswith('Objective: ') and v is not None for k,v in row['normalized'].items()))
    labels=[k for k,v in row['field_map'].items() if v.startswith('Objective: ')]+['Notes']
    commit(home,r,[{'row_id':row['id'],'action':'historical','fields':labels,'realm':'ExampleRealm','reason':'Explicit review of separate historical objectives and notes'}],approved=True)
    m=next(m for m in DesktopService(home).snapshot()['history'] if m.get('_excel_historical'))
    assert m['Notes']==row['normalized']['Notes'] and m['My objectives']
    for label in labels:
        assert m['_excel_supplements'][0]['original_values'][label]==row['fields'][label]
    assert m['Damage'] is None if 'Damage' in m else True

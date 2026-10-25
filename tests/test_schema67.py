"""Schema 6/7 regression data is fictional; live addon files are never fixtures."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import pytest
from pvpledger_viewer.archive import Archive
from pvpledger_viewer.lua_reader import loads, sequence
from pvpledger_viewer.normalize import normalize
from pvpledger_viewer.schema import CURRENT_MATCH_HEADER, MATCH_HEADER, ROSTER_HEADER, parse_row
from test_core import match, roster, write_source

FIXTURE = Path(__file__).parent/'fixtures/v1_3_4/PvPLedger.lua'


def document():
    return loads(FIXTURE.read_text(encoding='utf8'))


def lines():
    return sequence(document()['PvPLedgerDB']['matchCSV'])


def csvline(values):
    out=io.StringIO();csv.writer(out,lineterminator='').writerow(values);return out.getvalue()


@pytest.mark.parametrize('index,schema,date,clock,change,queue',[
    (0,6,'2030-01-01','12:00',27,'ARENA'),
    (1,7,'2030-01-02','18:30',-11,'BATTLEGROUND')])
def test_schema67_populates_fields_instead_of_structured_fallback(index,schema,date,clock,change,queue):
    raw=lines()[index];issues=[];row=parse_row(raw,'match',issues)
    assert len(next(csv.reader([raw])))==48
    assert row['Schema version']==schema and row['Addon version']==('1.3.2' if schema==6 else '1.3.4')
    assert (row['Date'],row['Time'],row['Rated'],row['Rating change'])==(date,clock,'Yes',change)
    assert isinstance(row['Epoch'],int) and row['Queue type']==queue
    assert row['Premade members']=='Fayë, Example'
    assert row['_raw']==raw and row['_unknown_trailing_fields']==[] and not issues


def test_verified_reference_header_and_fixed_column_positions():
    source=(Path(__file__).parents[1]/'reference/addon/PvPLedger/PvPLedger.lua').read_text(encoding='utf8')
    for key,expected in [('MATCH_HEADER',CURRENT_MATCH_HEADER),('ROSTER_HEADER',ROSTER_HEADER)]:
        header=re.search(r'local '+key+r' = \{(.*?)\}',source,re.S)[1]
        assert re.findall(r'"([^"]+)"',header)==expected
    assert CURRENT_MATCH_HEADER[:46]==MATCH_HEADER
    assert [CURRENT_MATCH_HEADER.index(name)+1 for name in ('Date','Time','Rated','Rating change','Schema version','Epoch','Queue type')]==[2,3,12,23,45,47,48]


@pytest.mark.parametrize('version,width',[(1,37),(2,44),(3,46),(4,46),(5,47),(6,48),(7,48)])
def test_schema1_through7_still_use_the_verified_shared_prefix(version,width):
    values=next(csv.reader([lines()[0]]))
    values[44]=str(version)
    issues=[];row=parse_row(csvline(values[:width]),'match',issues)
    assert row['Schema version']==version
    assert (row['Date'],row['Time'],row['Rated'],row['Rating change'])==('2030-01-01','12:00','Yes',27)
    assert not any(d['code'] in ('unknown_schema','extra_columns') for d in issues)
    if version>=5:assert row['Epoch']==1893499200


@pytest.mark.parametrize('version',[6,7])
def test_schema67_unknown_match_fields_and_raw_quotes_are_retained(version):
    values=next(csv.reader([lines()[0]]));values[44]=str(version)
    unknown=['future, quoted','Fayë|nraw','']
    raw=csvline(values+unknown);issues=[];row=parse_row(raw,'match',issues)
    assert row['_unknown_trailing_fields']==unknown and row['_raw']==raw
    assert row['Epoch']==1893499200 and row['Queue type']=='ARENA' and not issues


@pytest.mark.parametrize('version',[6,7])
def test_schema67_roster_version_and_unknown_extensions(version):
    values=next(csv.reader([sequence(document()['PvPLedgerDB']['rosterCSV'])[0]]));values[20]=str(version)
    raw=csvline(values+['future, field','']);issues=[];row=parse_row(raw,'roster',issues)
    assert row['Schema version']==version and row['Rating change']==27
    assert row['_unknown_trailing_fields']==['future, field',''] and row['_raw']==raw and not issues


@pytest.mark.parametrize('value,expected',[('',None),('0',0),('-9',-9)])
def test_schema67_missing_rating_is_null_and_zero_is_observed(value,expected):
    values=next(csv.reader([lines()[1]]));values[22]=value;values[11]='No'
    row=parse_row(csvline(values),'match',[])
    assert row['Rating change']==expected and row['Rated']=='No'


@pytest.mark.parametrize('epoch',['','bad','1.5'])
def test_schema67_missing_or_invalid_epoch_never_replaces_csv_fields(epoch):
    values=next(csv.reader([lines()[1]]));values[46]=epoch;issues=[]
    row=parse_row(csvline(values),'match',issues)
    assert row['Epoch'] is None and row['Date']=='2030-01-02' and row['Time']=='18:30' and row['Rating change']==-11
    assert any(d['code']=='invalid_number' and d.get('field')=='Epoch' for d in issues)==bool(epoch)


@pytest.mark.parametrize('index',[0,1])
def test_schema67_incomplete_extension_is_diagnosed_without_inventing_values(index):
    values=next(csv.reader([lines()[index]]));issues=[];row=parse_row(csvline(values[:46]),'match',issues)
    assert row['Epoch'] is None and row['Queue type'] is None
    assert row['Date'] and row['Time'] and row['Rated']=='Yes'
    assert any(d['code']=='short_row' for d in issues)


def test_schema67_mixed_versions_normalize_rich_csv_once():
    matches,rosters,aliases,issues=normalize(document(),'Asterknight','ExampleRealm')
    assert len(matches)==2 and sum(map(len,rosters.values()))==4 and not aliases
    assert all(m['Date'] and m['Time'] and m['Rated']=='Yes' and m['Rating change'] is not None for m in matches.values())
    assert not any(d['code'] in ('structured_fallback','extra_columns','unknown_schema') for d in issues)


def test_schema67_import_reimport_keeps_source_bytes_and_stable_identities(tmp_path):
    before=hashlib.sha256(FIXTURE.read_bytes()).hexdigest();a=Archive(tmp_path/'profile')
    try:
        first=a.import_file(FIXTURE,'Asterknight','ExampleRealm');assert first['status']=='ok'
        assert (first['matches_added'],first['roster_added'])==(2,4)
        ids=a.db.execute('select id,original_id from observations order by id').fetchall()
        versions=a.db.execute('select count(*) from observation_versions').fetchone()[0]
        again=a.import_file(FIXTURE,'Asterknight','ExampleRealm')
        assert (again['matches_added'],again['roster_added'])==(0,0)
        assert a.totals()['total']==2 and a.totals()['rosters']==4
        assert a.db.execute('select id,original_id from observations order by id').fetchall()==ids
        assert a.db.execute('select count(*) from observation_versions').fetchone()[0]==versions
        assert a.db.execute('pragma user_version').fetchone()[0]==2
        assert all(m['Date'] and m['Time'] and m['Rated']=='Yes' for m in a.read_matches())
        assert len(list((a.home/'snapshots').glob('*.lua')))==1
        assert next((a.home/'snapshots').glob('*.lua')).read_bytes()==FIXTURE.read_bytes()
    finally:a.close()
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest()==before


def test_retained_raw_snapshot_repairs_old_fallback_without_history_loss(tmp_path,monkeypatch):
    source=tmp_path/'PvPLedger.lua';source.write_bytes(FIXTURE.read_bytes())
    archive=Archive(tmp_path/'profile')
    legacy=write_source(tmp_path/'legacy.lua',[match('20290101-120000','Asterknight','ExampleRealm')],[roster('20290101-120000','Asterknight','ExampleRealm')])
    archive.import_file(legacy)
    legacy_row=archive.db.execute("select data,raw_csv from matches where match_id='20290101-120000'").fetchone()
    def old_fallback(doc,character=None,realm=None):
        # Reproduce the old reader rejecting extended matchCSV while retaining
        # the complete snapshot and using its limited structured entries.
        db=dict(doc['PvPLedgerDB']);db['matchCSV']=[]
        return normalize({'PvPLedgerDB':db},character,realm)
    try:
        with monkeypatch.context() as patch:
            patch.setattr('pvpledger_viewer.archive.normalize',old_fallback)
            old=archive.import_file(source,'Asterknight','ExampleRealm');assert old['status']=='ok'
        key=('Asterknight','ExampleRealm','20300102-183000')
        old_match=next(m for m in archive.read_matches() if m['Match ID']==key[2])
        assert all(old_match[f] is None for f in ('Date','Time','Rated','Rating change'))
        archive.set_override(key,'Map','User reviewed map')
        retained=Path(archive.diagnostics(old['import_id'])[0]['snapshot'])
        snapshot_hash=hashlib.sha256(retained.read_bytes()).hexdigest()
        ids=set(tuple(r) for r in archive.db.execute('select id,original_id from observations'))
        raw_before=set(tuple(r) for r in archive.db.execute('select * from raw_rows'))
        versions_before=set(tuple(r) for r in archive.db.execute('select * from observation_versions'))
        overrides=set(tuple(r) for r in archive.db.execute('select * from overrides'))
        # Rolling history no longer contains either match. Recover from the
        # retained file through the existing explicit import path, not a new UI.
        write_source(source);archive.import_file(source,'Asterknight','ExampleRealm')
        repaired=archive.import_file(retained,'Asterknight','ExampleRealm')
        assert repaired['status']=='ok' and (repaired['matches_added'],repaired['roster_added'])==(0,0)
        assert archive.totals()['total']==3 and archive.totals()['rosters']==5
        assert set(tuple(r) for r in archive.db.execute('select id,original_id from observations'))==ids
        recovered=next(m for m in archive.read_matches() if m['Match ID']==key[2])
        assert (recovered['Date'],recovered['Time'],recovered['Rated'],recovered['Rating change'])==('2030-01-02','18:30','Yes',-11)
        assert recovered['Map']=='User reviewed map' and recovered['Epoch']==1893609000
        assert raw_before<=set(tuple(r) for r in archive.db.execute('select * from raw_rows'))
        assert versions_before<=set(tuple(r) for r in archive.db.execute('select * from observation_versions'))
        assert set(tuple(r) for r in archive.db.execute('select * from overrides'))==overrides
        assert archive.db.execute("select data,raw_csv from matches where match_id='20290101-120000'").fetchone()==legacy_row
        assert hashlib.sha256(retained.read_bytes()).hexdigest()==snapshot_hash
        counts=archive.totals();archive.import_file(retained,'Asterknight','ExampleRealm');assert archive.totals()==counts
    finally:archive.close()

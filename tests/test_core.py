import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import stat
import pytest
from pvpledger_viewer.archive import Archive
from pvpledger_viewer.cli import main
from pvpledger_viewer.discovery import discover
from pvpledger_viewer.lua_reader import LuaError, loads, sequence
from pvpledger_viewer.normalize import normalize
from pvpledger_viewer.schema import MATCH_HEADER, ROSTER_HEADER, parse_row

FIXTURE = Path(__file__).parent / 'fixtures/PvPLedger.lua'


def csv_line(header, values, length=None):
    out = io.StringIO()
    csv.writer(out, lineterminator='').writerow([values.get(h, '') for h in header[:length]])
    return out.getvalue()


def match(mid='20261022-120000', character='Me', realm='Realm', **fields):
    values = {'Match ID': mid, 'Character': character, 'Realm': realm, 'Map': 'Map', 'Result': 'W', 'Duration (s)': 600}
    return csv_line(MATCH_HEADER, values | fields)


def roster(mid='20261022-120000', player='Me', realm='Realm', **fields):
    return csv_line(ROSTER_HEADER, {'Match ID': mid, 'Player': player, 'Realm': realm, 'Team': 'Mine'} | fields)


def write_source(path, matches=(), rosters=()):
    # JSON quoted strings use the same escapes needed by these fixtures.
    path.write_text('PvPLedgerDB={matchCSV={' + ','.join(json.dumps(x, ensure_ascii=False) for x in matches) + '},rosterCSV={' + ','.join(json.dumps(x, ensure_ascii=False) for x in rosters) + '}}', encoding='utf8')
    return path


@pytest.fixture
def archive(tmp_path):
    a = Archive(tmp_path / 'archive')
    yield a
    a.close()


def test_real_acceptance_and_idempotence(archive):
    before = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    first = archive.import_file(FIXTURE)
    assert first['status'] == 'ok'
    assert (first['matches_added'], first['roster_added']) == (10, 211)
    assert archive.totals() == {'total': 10, 'complete': 7, 'partial': 3, 'rosters': 211, 'wins': 4, 'losses': 3}
    counts = archive.db.execute('SELECT m.partial,count(r.player) n FROM matches m JOIN rosters r USING(character,realm,match_id) GROUP BY character,realm,match_id ORDER BY m.partial,n').fetchall()
    assert sorted(r['n'] for r in counts if not r['partial']) == [4, 4, 20, 20, 20, 31, 32]
    assert sorted(r['n'] for r in counts if r['partial']) == [20, 30, 30]
    second = archive.import_file(FIXTURE)
    assert (second['matches_added'], second['roster_added']) == (0, 0)
    assert archive.db.execute("SELECT count(*) FROM raw_rows WHERE import_id=1 AND kind='rosterCSV'").fetchone()[0] == 451
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == before
    for record in archive.diagnostics():
        assert Path(record['snapshot']).read_bytes() == FIXTURE.read_bytes()
    arena = next(m for m in archive.read_matches() if m['Match ID'] == '20301021-191143')
    assert 'Rounds Won=0' in arena['My objectives'] and '|n' not in arena['My objectives']
    assert arena['Type'] == 'Arena skirmish' and arena['Rated'] == 'No'
    assert any(d['code'] == 'duplicate_roster' for d in first['diagnostics'])


def test_persistence_rolling_and_overrides(tmp_path):
    home = tmp_path / 'archive'
    a = Archive(home)
    a.import_file(FIXTURE)
    key = ('Asterknight', 'ExampleRealm', '20301022-173450')
    a.set_override(key, 'Result', 'W')
    original = a.db.execute('SELECT data FROM matches WHERE character=? AND realm=? AND match_id=?', key).fetchone()[0]
    a.close()
    a = Archive(home)
    source = write_source(tmp_path / 'empty.lua')
    assert a.import_file(source)['matches_added'] == 0
    assert a.totals()['total'] == 10
    a.import_file(FIXTURE)
    assert next(m for m in a.read_matches() if m['Match ID'] == key[2])['Result'] == 'W'
    assert a.db.execute('SELECT data FROM matches WHERE character=? AND realm=? AND match_id=?', key).fetchone()[0] == original
    with pytest.raises(ValueError):
        a.set_override(key, 'Match ID', 'bad')
    a.close()


@pytest.mark.parametrize('text', ['x={a=os.execute("bad")}', 'x={a=1', 'x={} os.execute("bad")', 'x={a=1+2}', 'x={"unterminated}', 'x={a=function() end}'])
def test_parser_rejects_executable_and_truncated(text):
    with pytest.raises(LuaError):
        loads(text)


def test_parser_tables_escapes_comments_unicode():
    d = loads('-- comment\nx={ ["names"]={"Môônlet", "Fayë", "Silverhålo"}, n=2.5, yes=true, no=false, empty=nil, str="a\\n\\\"\\\\b", long=[=[player0343]=] }; y={} ')
    assert sequence(d['x']['names']) == ['Môônlet', 'Fayë', 'Silverhålo']
    assert d['x']['str'] == 'a\n"\\b' and d['x']['n'] == 2.5
    assert d['x']['long'] == 'player0343' and d['y'] == {}


@pytest.mark.parametrize('length,version', [(37, 1), (44, 2), (46, 3)])
def test_schema_versions(length, version):
    raw = csv_line(MATCH_HEADER, {'Match ID': 'id', 'Schema version': 3}, length)
    diagnostics = []
    m = parse_row(raw, 'match', diagnostics)
    assert m['Schema version'] == version
    assert m['Damage'] is None and m['Honor awarded'] is None
    assert m['_raw'] == raw


def test_csv_quotes_extra_fields_bad_numeric_and_codes():
    raw = match(**{'Map': 'Map, with comma', 'Damage': 'not a number', 'My objectives': '|cffff0000Rounds|nWon=0|r; Test=1'})
    diagnostics = []
    m = parse_row(raw, 'match', diagnostics)
    assert m['Map'] == 'Map, with comma' and m['Damage'] is None
    assert m['My objectives'] == 'Rounds Won=0; Test=1'
    assert diagnostics[0]['code'] == 'invalid_number'
    assert parse_row(raw + ',extra', 'match', diagnostics) is None
    assert diagnostics[-1]['code'] == 'extra_columns'
    assert parse_row('"unclosed', 'match', diagnostics) is None


def test_last_roster_duplicate_kept():
    doc = {'PvPLedgerDB': {'matchCSV': [match()], 'rosterCSV': [roster(**{'Damage': 1}), roster(**{'Damage': 2})]}}
    _, rows, _, issues = normalize(doc)
    assert next(iter(rows.values()))[0]['Damage'] == 2
    assert any(i['code'] == 'duplicate_roster' for i in issues)


def test_orphans_latest_complete_and_no_invented_fields():
    ids = ['20261022-120000', '20261022-120010', '20261022-120020', '20261022-120121']
    rows = [roster(ids[0], 'A'), roster(ids[0], 'B'), roster(ids[1], 'A', Damage=7), roster(ids[1], 'B'), roster(ids[2], 'A'), roster(ids[3], 'C')]
    matches, rosters, aliases, _ = normalize({'PvPLedgerDB': {'rosterCSV': rows}}, 'Me', 'Realm')
    assert len(matches) == 2
    m = matches['Me', 'Realm', ids[0]]
    assert m['_snapshot'] == ids[1] and m['_partial']
    assert all(m[k] is None for k in ('Result', 'Map', 'Type', 'Duration (s)', 'My team score'))
    assert len(rosters['Me', 'Realm', ids[0]]) == 2
    assert aliases['Me', 'Realm', ids[2]] == ('Me', 'Realm', ids[0])


def test_new_snapshot_across_imports_and_stale_snapshot(archive, tmp_path):
    src = tmp_path / 'source.lua'
    write_source(src, rosters=[roster('20261022-120010', 'A', Damage=8), roster('20261022-120010', 'B')])
    archive.import_file(src, 'Me', 'Realm')
    write_source(src, rosters=[roster('20261022-120020', 'A', Damage=9), roster('20261022-120020', 'B')])
    result = archive.import_file(src, 'Me', 'Realm')
    assert result['matches_added'] == 0 and archive.totals()['total'] == 1
    write_source(src, rosters=[roster('20261022-120000', 'A', Damage=1)])
    archive.import_file(src, 'Me', 'Realm')
    assert json.loads(archive.db.execute("SELECT data FROM rosters WHERE player='A'").fetchone()[0])['Damage'] == 9


def test_discovery_layouts_and_bak(tmp_path):
    root = tmp_path / 'Game'
    paths = [root / '_retail_/WTF/Account/A/SavedVariables/PvPLedger.lua', root / '_retail_/WTF/Account/A/Realm/Me/SavedVariables/PvPLedger.lua', root / '_retail_/WTF/Account/B/Other/Alt/SavedVariables/PvPLedger.lua']
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text('')
        p.with_suffix('.lua.bak').write_text('')
    assert discover(root) == sorted(p.resolve() for p in paths)
    assert discover(root / '_retail_') == discover(root)


def test_same_timestamp_different_characters(archive, tmp_path):
    for character in ('One', 'Two'):
        src = write_source(tmp_path / f'{character}.lua', [match(character=character)], [roster(player=character)])
        assert archive.import_file(src)['matches_added'] == 1
    assert archive.totals()['total'] == 2


def test_failed_import_diagnostics_and_snapshot(archive, tmp_path):
    source = tmp_path / 'bad.lua'; source.write_text('PvPLedgerDB={')
    result = archive.import_file(source)
    assert result['status'] == 'failed' and archive.totals()['total'] == 0
    assert len(result['diagnostics']) == 2
    assert len(list((archive.home / 'snapshots').glob('*.lua'))) == 2
    assert archive.diagnostics()[0]['status'] == 'failed'


def test_invalid_rows_preserved_and_incomplete(archive, tmp_path):
    source = write_source(tmp_path / 'short.lua', ['bad,short'], ['bad,short'])
    result = archive.import_file(source)
    assert result['diagnostics']
    assert archive.db.execute('SELECT count(*) FROM raw_rows').fetchone()[0] == 2
    m, _, _, _ = normalize({'PvPLedgerDB': {'matchCSV': [match(**{'Duration (s)': ''})]}})
    assert next(iter(m.values()))['_partial']


def test_structured_fallback_and_account_only(archive, tmp_path):
    source = tmp_path / 'structured.lua'
    source.write_text('PvPLedgerDB={matches={{id="20261022-120000",character="Me",map="Map",kb=2}}}')
    assert archive.import_file(source, 'Me', 'Realm')['matches_added'] == 1
    m = archive.read_matches()[0]
    assert m['_partial'] and m['KB'] == 2 and m['Result'] is None
    source.write_text('PvPLedgerAccountDB={friends={Me=true}}')
    assert archive.import_file(source)['status'] == 'ok'


def test_protected_destination(tmp_path):
    with pytest.raises(ValueError):
        Archive(tmp_path / 'World of Warcraft' / 'viewer')
    with pytest.raises(ValueError):
        Archive(tmp_path / '_retail_' / 'viewer')


def test_cli(tmp_path, capsys):
    args = ['--archive-dir', str(tmp_path / 'archive')]
    assert main(args + ['import', str(FIXTURE)]) == 0
    assert json.loads(capsys.readouterr().out)['matches_added'] == 10
    assert main(args + ['totals']) == 0
    assert json.loads(capsys.readouterr().out)['total'] == 10
    assert main(args + ['diagnostics', '--import-id', '1']) == 0
    assert json.loads(capsys.readouterr().out)[0]['status'] == 'ok'


def test_arena_deaths_and_attendance():
    raw = csv_line(MATCH_HEADER, {'Match ID': 'id', 'Character': 'Me', 'Realm': 'Realm', 'Type': 'Rated arena', 'Rated': 'Yes', 'Team deaths': 0, 'Enemy deaths': 0}, 37)
    doc = {'PvPLedgerDB': {'matchCSV': [raw], 'rosterCSV': [roster('id', 'A', KB=2, **{'Joined late': 1, 'Left early': 1}), roster('id', 'B', Team='Enemy', KB=3)]}}
    matches, rows, _, _ = normalize(doc)
    m = next(iter(matches.values()))
    assert (m['Team deaths'], m['Enemy deaths'], m['Deaths']) == (3, 2, None)
    r = next(iter(rows.values()))[0]
    assert r['Joined late'] == r['Left early'] == 1 and r['Deaths'] is None


def test_read_only_source(archive, tmp_path):
    source = tmp_path / 'readonly.lua'
    source.write_bytes(FIXTURE.read_bytes())
    source.chmod(stat.S_IREAD)
    try:
        assert archive.import_file(source)['matches_added'] == 10
        assert source.read_bytes() == FIXTURE.read_bytes()
    finally:
        source.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_unknown_schema_and_numeric_zero():
    issues = []
    row = parse_row(match(**{'Schema version': 99, 'Damage': 0}), 'match', issues)
    assert row['Damage'] == 0 and row['Healing'] is None
    assert any(d['code'] == 'unknown_schema' for d in issues)


def test_partial_upgrades_without_changing_identity(archive, tmp_path):
    source = tmp_path / 'data.lua'
    write_source(source, rosters=[roster()])
    archive.import_file(source, 'Me', 'Realm')
    write_source(source, matches=[match()], rosters=[roster()])
    result = archive.import_file(source)
    assert result['matches_added'] == result['roster_added'] == 0
    assert archive.totals()['complete'] == 1 and archive.totals()['partial'] == 0


def test_raw_headers_match_authoritative_addon():
    import re
    source = Path('reference/addon/PvPLedger/PvPLedger.lua').read_text(encoding='utf8')
    for name, expected in [('MATCH_HEADER', MATCH_HEADER), ('ROSTER_HEADER', ROSTER_HEADER)]:
        block = source.split('local ' + name + ' = {', 1)[1].split('}', 1)[0]
        assert re.findall(r'"([^"\n]+)"', block) == expected


def test_account_and_character_copies_deduplicate(archive, tmp_path):
    root = tmp_path / 'Game'
    paths = [root / '_retail_/WTF/Account/A/SavedVariables/PvPLedger.lua', root / '_retail_/WTF/Account/A/Realm/Me/SavedVariables/PvPLedger.lua']
    for source in paths:
        source.parent.mkdir(parents=True, exist_ok=True)
        write_source(source, [match()], [roster()])
    for source in discover(root):
        assert archive.import_file(source)['status'] == 'ok'
    assert archive.totals()['total'] == archive.totals()['rosters'] == 1


def test_scan_cli(tmp_path, capsys):
    root = tmp_path / 'Game'
    source = root / '_retail_/WTF/Account/A/Realm/Me/SavedVariables/PvPLedger.lua'
    source.parent.mkdir(parents=True)
    write_source(source, rosters=[roster()])
    assert main(['--archive-dir', str(tmp_path / 'archive'), 'scan', str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result) == 1 and result[0]['matches_added'] == 1


def test_unreadable_source_and_bak_rejection(archive, tmp_path):
    assert archive.import_file(tmp_path / 'missing.lua')['status'] == 'failed'
    with pytest.raises(ValueError):
        archive.import_file(tmp_path / 'PvPLedger.lua.bak')


def test_orphan_map_suggestions_are_not_facts():
    for objectives, suggestion in [('Carts Controlled=1', 'Silvershard Mines'), ('Carts Captures=1; Mines Assaulted=1', 'Deepwind Gorge'), ('Flag Captures=1', None)]:
        matches, _, _, _ = normalize({'PvPLedgerDB': {'rosterCSV': [roster(Objectives=objectives)]}}, 'Me', 'Realm')
        m = next(iter(matches.values()))
        assert m['Map'] is None and m['_map_suggestion'] == suggestion

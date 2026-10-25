from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest
from pvpledger_viewer.archive import Archive
from pvpledger_viewer.discovery import discover
from pvpledger_viewer.dual_archive import comparison, records
from pvpledger_viewer.identity import IdentityMap
from pvpledger_viewer.lua_reader import loads, sequence
from pvpledger_viewer.metrics import Filters, character_comparison, ally_comparisons, performance, match_key
from pvpledger_viewer.reflex_reader import parse_reflex, capture_time, pvp_time, at
from pvpledger_viewer.service import DesktopService
from pvpledger_viewer.settings import SettingsStore, validate_settings
from pvpledger_viewer.trends import prepare_trends
from pvpledger_viewer.export import ai_report
from test_core import FIXTURE

DATA = Path(__file__).parent / 'fixtures/v1_1'
PVP, REF = DATA / 'PvPLedger.lua', DATA / 'REFlex.lua'


def reflex_records():
    return sequence(loads(REF.read_text(encoding='utf8'))['REFlexDatabase'])


def lua(value):
    if value is None:
        return 'nil'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, dict):
        return '{' + ','.join('[' + lua(k) + ']=' + lua(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '{' + ','.join(lua(v) for v in value) + '}'
    return json.dumps(value, ensure_ascii=False)


def write_ref(path, rows):
    path.write_text('REFlexDatabase=' + lua(rows), encoding='utf8')
    return path


@pytest.fixture
def dual(tmp_path):
    a = Archive(tmp_path / 'archive')
    a.import_file(PVP, 'Asterknight', 'ExampleRealm')
    a.import_file(REF, 'Asterknight', 'ExampleRealm')
    yield a
    a.close()


def test_real_reflex_positional_fields_and_owner():
    m, rows, _, diagnostics = parse_reflex(loads(REF.read_text(encoding='utf8')), 'Asterknight', 'ExampleRealm')
    assert len(m) == 91
    first = next(iter(m.values()))
    assert (first['KB'], first['HK'], first['Deaths'], first['Damage'], first['Healing']) == (7, 1, 7, 4222764, 1285484)
    assert first['Character'] == 'Asterknight' and first['Realm'] == 'ExampleRealm'
    assert first['Map ID'] == 761 and first['Map'] is None
    assert first['Player count'] == 20 and len(rows[match_key(first)]) == 1
    assert first['Minutes played'] is None and first['Premade present'] is None
    assert first['_raw_reflex']['PlayersNum'] == 20
    assert first['_scoreboard_incomplete']
    assert any(d['code'] == 'reflex_incomplete_scoreboard' for d in diagnostics)


def test_unknown_reflex_premade_is_not_rendered_as_none():
    from pvpledger_viewer.viewmodels import premade_description
    match = next(iter(parse_reflex(loads(REF.read_text(encoding='utf8')), 'Asterknight', 'ExampleRealm')[0].values()))
    assert premade_description(match) == 'Unknown'
    assert premade_description({'Premade present': 0}) == 'None recorded'
    assert premade_description({'Premade present': 1}) == 'Unknown — see highlighted allied roster'
    assert premade_description({'Premade members': 'Emberguard'}) == 'Emberguard'


def test_real_winner_player_perspective_and_shuffle():
    matches = list(parse_reflex(loads(REF.read_text(encoding='utf8')), 'Asterknight', 'ExampleRealm')[0].values())
    assert matches[0]['Result'] == 'L'  # Winner=1, PlayerSide=0
    assert matches[1]['Result'] == 'W'  # Winner=0, PlayerSide=0
    assert any(m['Result'] == 'W' and m['_raw_reflex']['Winner'] == 1 for m in matches)
    shuffle = [m for m in matches if m['_raw_reflex'].get('isSoloShuffle')]
    assert shuffle and all(m['Result'] is None and m['Type'] == 'Solo Shuffle' for m in shuffle)


@pytest.mark.parametrize('side,winner,result', [(0, 0, 'W'), (1, 1, 'W'), (0, 1, 'L'), (1, 0, 'L'), (None, 0, None), (0, 2, None), (False, True, None)])
def test_result_missing_draw_invalid(side, winner, result):
    raw = deepcopy(reflex_records()[0]); raw.update(PlayerSide=side, Winner=winner)
    parsed = next(iter(parse_reflex({'REFlexDatabase': [raw]}, 'Asterknight', 'ExampleRealm')[0].values()))
    assert parsed['Result'] == result


def test_timestamp_decodes_addon_local_utc_encoding():
    raw = next(r for r in reflex_records() if r['Time'] == 1919026114)
    utc = capture_time(raw['Time'])
    assert utc == datetime(2030, 10, 23, 15, 48, 34, tzinfo=timezone.utc)
    pvp = {'Match ID': '20301023-084833'}
    assert utc.timestamp() - pvp_time(pvp) == 1
    assert pvp_time({'Match ID': '20261101-013000'}) is None  # ambiguous Pacific DST fold
    assert capture_time(0, 'UTC') == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_old_unknown_versions_and_missing_fields_keep_raw():
    raw = deepcopy(reflex_records()[0]); raw['Version'] = 9999
    raw['MysteryMetadata'] = {'unknown': [3, None, 7]}
    m, _, _, diagnostics = parse_reflex({'REFlexDatabase': [raw]}, 'Asterknight', 'ExampleRealm')
    match = next(iter(m.values()))
    assert match['Damage'] is None and match['_raw_reflex']['MysteryMetadata'] == raw['MysteryMetadata']
    assert any(i['code'] == 'unverified_reflex_version' for i in diagnostics)
    raw.pop('Time'); raw.pop('Winner'); raw['Hidden'] = True
    match = next(iter(parse_reflex({'REFlexDatabase': [raw]}, 'Asterknight', 'ExampleRealm')[0].values()))
    assert match['Date'] is None and match['Result'] is None
    assert match['_raw_reflex']['Hidden']


def test_real_overlap_counts_and_schema4(dual):
    assert dual.source_totals() | {} == {'PvP Ledger-only': 3, 'REFlex-only': 67, 'Both': 24,
                                        'ambiguous_pairs': 3, 'observations': 118, 'conflicting_matches': 11}
    assert dual.totals()['total'] == 27 + 91 - 24 == 94
    assert dual.totals()['rosters'] == 575
    assert not any(d['code'] == 'unknown_schema' for i in dual.diagnostics() for d in i['diagnostics'])
    assert len([r for r in dual.duplicate_review() if r['decision'] == 'confirmed']) == 24
    for r in dual.duplicate_review():
        if r['decision'] == 'confirmed':
            evidence = json.loads(r['reason'])
            assert evidence['seconds_apart'] <= 5 and evidence['duration_agrees'] and evidence['type_agrees']


def test_duration_correction_updates_observation_and_missing_times_stay_distinct(tmp_path):
    a = Archive(tmp_path / 'archive')
    try:
        raw = deepcopy(reflex_records()[0])
        path = write_ref(tmp_path / 'REFlex.lua', [raw])
        a.import_file(path, 'Asterknight', 'ExampleRealm')
        raw['Duration'] += 1
        write_ref(path, [raw])
        update = a.import_file(path, 'Asterknight', 'ExampleRealm')
        assert update['observations_added'] == 0 and a.totals()['total'] == 1
        assert a.read_matches()[0]['Duration (s)'] == raw['Duration']
        assert a.db.execute('SELECT count(*) FROM observation_versions').fetchone()[0] == 2
        raw.pop('Time')
        write_ref(path, [raw]); a.import_file(path, 'Asterknight', 'ExampleRealm')
        raw['Duration'] += 2
        write_ref(path, [raw]); a.import_file(path, 'Asterknight', 'ExampleRealm')
        assert a.totals()['total'] == 3
    finally:
        a.close()


def test_repeat_reordered_pruned_imports_are_permanent(dual, tmp_path):
    before = dual.totals(); versions = dual.db.execute('SELECT count(*) FROM observation_versions').fetchone()[0]
    for p in (PVP, REF):
        report = dual.import_file(p, 'Asterknight', 'ExampleRealm')
        assert report['matches_added'] == report['roster_added'] == report['observations_added'] == 0
    assert dual.db.execute('SELECT count(*) FROM observation_versions').fetchone()[0] == versions
    reordered = write_ref(tmp_path / 'reordered.lua', list(reversed(reflex_records())))
    assert dual.import_file(reordered, 'Asterknight', 'ExampleRealm')['observations_added'] == 0
    empty = write_ref(tmp_path / 'empty.lua', [])
    dual.import_file(empty, 'Asterknight', 'ExampleRealm')
    old = tmp_path / 'empty_pvp.lua'; old.write_text('PvPLedgerDB={matchCSV={},rosterCSV={}}')
    dual.import_file(old)
    assert dual.totals() == before


def test_reflex_first_later_full_scoreboards(dual, tmp_path):
    a = Archive(tmp_path / 'reverse')
    try:
        assert a.import_file(REF, 'Asterknight', 'ExampleRealm')['matches_added'] == 91
        assert a.source_totals()['REFlex-only'] == 91
        a.import_file(PVP, 'Asterknight', 'ExampleRealm')
        assert a.totals() == dual.totals()
        assert a.source_totals() == dual.source_totals()
        board = next(m for m in a.read_matches() if m['Match ID'] == '20301022-190143')
        rows = [r for r in a.read_rosters() if r['Match ID'] == board['Match ID']]
        assert board['Source'] == 'Both' and len(rows) == 32
        assert not board['_scoreboard_incomplete']
    finally:
        a.close()


def test_complement_conflicts_and_overrides_preserved(dual):
    key = ('Asterknight', 'ExampleRealm', '20301023-094901')
    m = next(m for m in dual.read_matches() if match_key(m) == key)
    assert m['Damage'] == 13900337  # PvP Ledger's observed value remains preferred.
    assert any(c['field'] == 'Damage' and c['other'] == 13918884 for c in m['_conflicts'])
    assert m['Map ID'] == 617 and m['_provenance']['Map ID'] == ['REFlex']
    assert set(m['_provenance']['Healing']) == {'PvP Ledger', 'REFlex'}
    dual.set_override(key, 'Damage', 123)
    dual.import_file(REF, 'Asterknight', 'ExampleRealm')
    m = next(m for m in dual.read_matches() if match_key(m) == key)
    assert m['Damage'] == 123 and m['_provenance']['Damage'] == ['User override']
    assert len(m['_observations']) == 2
    assert dual.db.execute('SELECT count(*) FROM observation_versions').fetchone()[0] == 118


def test_only_self_is_not_fabricated_team_rank(tmp_path):
    a = Archive(tmp_path / 'a')
    try:
        path = write_ref(tmp_path / 'one.lua', reflex_records()[:1])
        a.import_file(path, 'Asterknight', 'ExampleRealm')
        m, rows = a.read_matches()[0], a.read_rosters()
        assert len(rows) == 1
        assert performance(m, rows)['Damage rank'] is None
        assert performance(m, rows)['Deaths per 10 minutes'] is None
    finally:
        a.close()


def test_time_and_duration_alone_never_confirm(dual):
    source = records(dual)
    pair = next(r for r in dual.duplicate_review() if r['decision'] == 'confirmed')
    a, b = deepcopy(source[pair['left_id']]), deepcopy(source[pair['right_id']])
    # Derived real record with conflicting combat statistics and no shared roster.
    b['rows'] = []
    for field in ('Damage', 'Healing', 'KB', 'HK', 'Deaths'):
        b['match'][field] = 987654321
    assert comparison(a, b)[0] == 'ambiguous'
    b['match']['_timestamp_utc'] += 180
    assert comparison(a, b) is None


def test_manual_link_keep_separate_unlink_survive_restart(dual):
    candidate = next(r for r in dual.duplicate_review() if r['decision'] == 'ambiguous')
    left, right = candidate['left_id'], candidate['right_id']
    original = dual.totals()['total']
    dual.decide_link(left, right, 'confirmed')
    assert dual.totals()['total'] == original - 1
    dual.import_file(REF, 'Asterknight', 'ExampleRealm')
    assert dual.totals()['total'] == original - 1
    dual.decide_link(left, right, 'unlink')
    assert dual.totals()['total'] == original
    dual.import_file(PVP, 'Asterknight', 'ExampleRealm')
    reopened = Archive(dual.home)
    try:
        pair = next(r for r in reopened.duplicate_review() if (r['left_id'], r['right_id']) == (left, right))
        assert pair['manual'] and pair['decision'] == 'separate'
        assert reopened.totals()['total'] == original
    finally:
        reopened.close()


def test_cannot_link_different_characters(dual, tmp_path):
    dual.import_file(write_ref(tmp_path / 'other.lua', reflex_records()[:1]), 'Asterknight', 'OtherRealm')
    values = list(records(dual).values())
    other = next(r for r in values if r['realm'] == 'OtherRealm')
    first = next(r for r in values if r['realm'] == 'ExampleRealm')
    with pytest.raises(ValueError):
        dual.decide_link(other['id'], first['id'], 'confirmed')


def test_sources_stats_exports_and_trends_use_one_projection(dual, tmp_path):
    identities = IdentityMap(dual.home / 'people.json')
    matches, rows = dual.read_matches(), dual.read_rosters()
    comparison_rows = character_comparison(matches, rows, identities)
    example_character = next(c for c in comparison_rows if c['character'] == 'Asterknight')
    assert example_character['overall_explicitly_combined']['games'] == 94
    trends = prepare_trends(matches, rows, identities, teammates=['Buddy A'])
    assert trends['matches'] == 94
    assert sum(g['summary']['matches'] for g in trends['series']) == 94
    report = ai_report(matches, rows, identities, limit=1000)
    assert 'Field provenance' in report and 'REFlex' in report
    allies = ally_comparisons(matches, rows, identities)
    assert allies
    service = DesktopService(dual.home)
    assert service.snapshot()['history_count'] == 94


def downgrade_to_v1(home):
    db = sqlite3.connect(home / 'archive.sqlite')
    for name in ('link_history', 'match_links', 'observation_files', 'observation_versions', 'observations', 'source_files'):
        db.execute(f'DROP TABLE {name}')
    db.execute('PRAGMA user_version=1'); db.commit(); db.close()


def test_migration_backup_existing_data_and_settings(tmp_path):
    home = tmp_path / 'old'
    a = Archive(home); a.import_file(FIXTURE)
    key = ('Asterknight', 'ExampleRealm', '20301022-180118'); a.set_override(key, 'Map', 'User map')
    before = a.totals(); a.close()
    people = IdentityMap(home / 'people.json'); people.assign('Oldalt', 'Me')
    SettingsStore(home / 'settings.json').save({'trend_window': 7, 'wow_root': 'C:/Games/WoW'})
    downgrade_to_v1(home)
    config = {p.name: p.read_bytes() for p in (home / 'people.json', home / 'settings.json')}
    a = Archive(home)
    try:
        assert a.db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert a.totals() == before
        assert next(m for m in a.read_matches() if match_key(m) == key)['Map'] == 'User map'
        folder = next((home / 'backups').iterdir())
        backup = sqlite3.connect(folder / 'archive.sqlite')
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 1
        assert backup.execute('SELECT count(*) FROM matches').fetchone()[0] == 10
        backup.close()
        for name, raw in config.items():
            assert (folder / name).read_bytes() == (home / name).read_bytes() == raw
        assert json.loads((folder / 'manifest.json').read_text())['schema_before'] == 1
    finally:
        a.close()


def test_migration_rolls_back_on_error(tmp_path, monkeypatch):
    home = tmp_path / 'old'; a = Archive(home); a.import_file(FIXTURE); a.close(); downgrade_to_v1(home)
    import pvpledger_viewer.dual_archive as module
    def fail(*args, **kwargs):
        raise RuntimeError('simulated migration failure')
    monkeypatch.setattr(module, 'observe', fail)
    with pytest.raises(RuntimeError):
        Archive(home)
    db = sqlite3.connect(home / 'archive.sqlite')
    assert db.execute('PRAGMA user_version').fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='observations'").fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM matches').fetchone()[0] == 10
    db.close()


def test_missing_owner_diagnostics_and_immutable_source(tmp_path):
    a = Archive(tmp_path / 'a')
    try:
        original = REF.read_bytes(); pvp = PVP.read_bytes()
        report = a.import_file(REF)
        assert report['status'] == 'ok' and report['matches_added'] == 0
        assert any(d['code'] == 'missing_or_conflicting_reflex_owner' for d in report['diagnostics'])
        assert a.db.execute("SELECT count(*) FROM raw_rows WHERE kind='REFlex'").fetchone()[0] == 91
        a.import_file(PVP, 'Asterknight', 'ExampleRealm')
        assert a.import_file(REF)['observations_added'] == 91  # uniquely archived realm context
        assert REF.read_bytes() == original and PVP.read_bytes() == pvp
        for item in a.diagnostics():
            raw = Path(item['snapshot']).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == item['sha256']
    finally:
        a.close()


def test_discovery_two_addons_account_character_and_backups(tmp_path):
    base = tmp_path / '_retail_/WTF/Account'
    files = []
    for addon in ('PvPLedger', 'REFlex'):
        for layout in ('A/SavedVariables', 'A/Realm/One/SavedVariables', 'B/Other/Two/SavedVariables'):
            path = base / layout / f'{addon}.lua'; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('')
            path.with_suffix('.lua.bak').write_text(''); files.append(path.resolve())
    assert discover(tmp_path) == sorted(files)


def test_timezone_setting_validation_and_chronological_recent(dual):
    assert validate_settings({'source_timezone': 'UTC'})['source_timezone'] == 'UTC'
    with pytest.raises(ValueError):
        validate_settings({'source_timezone': 'Not/AZone'})
    identities = IdentityMap(dual.home / 'people.json')
    result = character_comparison(dual.read_matches(), dual.read_rosters(), identities, recent=1)
    example_character = next(c for c in result if c['character'] == 'Asterknight')
    assert example_character['recent_matches'][0]['Match ID'] == '20301023-110707'

import csv
import ctypes
import io
import json
from pathlib import Path
import pytest
from pvpledger_viewer.archive import Archive
from pvpledger_viewer.identity import IdentityMap, character_key
from pvpledger_viewer.metrics import (Filters, ally_comparisons, by_type, character_comparison,
    distribution, filter_matches, performance, player_rank, summarize)
from pvpledger_viewer.export import (MATCH_EXPORT_HEADER, ROSTER_EXPORT_HEADER, ai_report,
    copy_to_clipboard, export_folders)
from pvpledger_viewer.cli import main
from test_core import FIXTURE


@pytest.fixture
def real(tmp_path):
    archive = Archive(tmp_path / 'archive')
    archive.import_file(FIXTURE)
    identities = IdentityMap(archive.home / 'people.json')
    matches, rows = archive.read_matches(), archive.read_rosters()
    identities.discover_unassigned(rows)
    yield archive, identities, matches, rows
    archive.close()


def sample(mid='20261022-120000', **fields):
    return {'Character': 'Asterknight', 'Realm': 'ExampleRealm', 'Match ID': mid,
            'Type': 'Battleground', 'Map': 'Map', 'Result': 'W', 'Premade present': 1,
            'Damage': 100, 'Healing': 20, 'Deaths': 2, 'KB': 3, 'HK': 8,
            'Minutes played': 5, 'Duration (s)': 600, '_partial': False} | fields


def player(name='Emberguard', mid='20261022-120000', **fields):
    return {'Owner character': 'Asterknight', 'Owner realm': 'ExampleRealm', 'Match ID': mid,
            'Player': name, 'Realm': 'SandboxRealm', 'Team': 'Mine', 'Is me': 'No',
            'Is premade': 'Yes', 'Damage': 100, 'Healing': 20, 'Deaths': 2, 'KB': 3, 'HK': 8} | fields


def test_identity_seeds_no_assumed_realms(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    assert ids.resolve('Emberguard', 'Any Realm') == 'Buddy A'
    assert ids.resolve('Pebblebrew') == 'Buddy B'
    assert ids.resolve('Snowflare') == 'Buddy C'
    assert ids.resolve('Unboundleaf') == 'Unassigned'
    assert ids.people['Buddy D'] == []
    assert all('-' not in name for names in ids.people.values() for name in names)
    assert IdentityMap(ids.path).people == ids.people


def test_identity_unicode_specific_realm_overrides_and_edits(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    ids.assign('Faye\u0308', 'New Person')
    assert ids.resolve('FAYË', 'Practice Realm') == 'New Person'
    ids.assign('Fayë-PracticeRealm', 'Buddy D')
    assert ids.resolve('Fayë', 'Practice Realm') == 'Buddy D'
    assert ids.resolve('Fayë', 'Other') == 'New Person'
    ids.unassign('Fayë-PracticeRealm')
    assert ids.resolve('Fayë', 'Practice Realm') == 'Unassigned'
    ids.remove('Fayë-PracticeRealm')
    assert ids.resolve('Fayë', 'Practice Realm') == 'New Person'
    ids.assign('Fayë', 'Buddy C')
    assert ids.resolve('fayë') == 'Buddy C'
    ids.remove('fayë')
    assert ids.resolve('Fayë') == 'Unassigned'
    assert 'Fayë' not in ids.path.read_text(encoding='utf8')


def test_unknown_premades_persist_without_enemies_or_self_guesses(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    rows = [player('Môônlet'), player('Enemy', Team='Enemy'), player('Solo', **{'Is premade': 'No'}), player('Môônlet')]
    assert ids.discover_unassigned(rows) == ['Môônlet-SandboxRealm']
    assert ids.discover_unassigned(rows) == []
    assert 'Môônlet' in ids.path.read_text(encoding='utf8')
    assert ids.resolve('Enemy') == 'Unassigned'
    assert not any('Enemy' in e for e in ids.people['Unassigned'])


@pytest.mark.parametrize('document', [{'people': []}, {'people': {'A': ['X'], 'B': ['x']}}, {'people': {'A': 'X'}}, {'people': {'A': ['']}}])
def test_bad_mapping_not_overwritten(tmp_path, document):
    path = tmp_path / 'people.json'
    original = json.dumps(document)
    path.write_text(original)
    with pytest.raises(ValueError):
        IdentityMap(path)
    assert path.read_text() == original


def test_real_record_unknown_partials_and_identity(real):
    _, ids, matches, rows = real
    summary = summarize(matches, rows)
    assert (summary['games'], summary['wins'], summary['losses'], summary['result_count']) == (10, 4, 3, 7)
    assert summary['win_rate'] == pytest.approx(4 / 7)
    assert summarize([m for m in matches if not m['_partial']], rows)['win_rate'] == summary['win_rate']
    assert ids.resolve('Unboundleaf', 'SandboxRealm') == 'Unassigned'
    for name, person in [('Emberguard', 'Buddy A'), ('Pebblebrew', 'Buddy B'), ('Snowflare', 'Buddy C')]:
        assert ids.resolve(name) == person
    eye = next(m for m in matches if m['Map'] == 'Eye of the Storm')
    own = [r for r in rows if r['Match ID'] == eye['Match ID']]
    assert performance(eye, own)['Win margin'] == -52
    assert {r['Player'] for r in own if r['Is premade'] == 'Yes'} >= {'Emberguard', 'Pebblebrew', 'Snowflare'}


def test_retroactive_assignment_never_rewrites_archive(real):
    archive, ids, matches, rows = real
    original = archive.db.execute('SELECT data FROM rosters ORDER BY character,realm,match_id,player').fetchall()
    before = ally_comparisons(matches, rows, ids)
    ids.assign('Unboundleaf', 'Buddy D')
    after = ally_comparisons(archive.read_matches(), archive.read_rosters(), IdentityMap(ids.path))
    assert sum(v['together']['games'] for v in before['Buddy D'].values()) == 0
    assert sum(v['together']['games'] for v in after['Buddy D'].values()) > 0
    assert archive.db.execute('SELECT data FROM rosters ORDER BY character,realm,match_id,player').fetchall() == original


def test_distribution_null_zero_and_counts():
    assert distribution([None, 0, 10, float('nan')]) == {'count': 2, 'total': 10, 'mean': 5, 'median': 5}
    assert distribution([None]) == {'count': 0, 'total': None, 'mean': None, 'median': None}


def test_deaths_per10_uses_minutes_and_never_duration():
    assert performance(sample(), [])['Deaths per 10 minutes'] == 4
    for value in (None, 0, -1):
        assert performance(sample(**{'Minutes played': value}), [])['Deaths per 10 minutes'] is None
    assert performance(sample(Deaths=None), [])['Deaths per 10 minutes'] is None
    assert performance(sample(Deaths=0), [])['Deaths per 10 minutes'] == 0


def test_rank_only_own_team_ties_missing_stats():
    row = player('A')
    rows = [row, player('B'), player('C', Damage=200), player('Opponent', Team='Enemy', Damage=99999)]
    assert player_rank(row, rows, 'Damage') == 2
    assert player_rank(rows[2], rows, 'Damage') == 1
    assert player_rank(row, rows + [player('Missing', Damage=None)], 'Damage') is None
    assert player_rank(row | {'Damage': None}, rows, 'Damage') is None


def test_performance_rank_self_and_win_margin_modes():
    me = player('Asterknight', Realm='ExampleRealm', **{'Is me': 'Yes'})
    rows = [me, player('A', Damage=200, Healing=10), player('Enemy', Team='Enemy', Damage=10000)]
    out = performance(sample(**{'My team score': 1448, 'Enemy team score': 1500}), rows)
    assert (out['Damage rank'], out['Healing rank'], out['Win margin']) == (2, 1, -52)
    assert performance(sample(Type='Arena skirmish', **{'My team score': 2, 'Enemy team score': 1}), rows)['Win margin'] is None


def test_summary_fields_and_deduplicated_matches():
    m = sample()
    s = summarize([m, m, sample('20261022-120100', Result='L', Damage=None, Healing=0)], [])
    assert (s['games'], s['wins'], s['losses']) == (2, 1, 1)
    assert s['statistics']['Damage']['count'] == 1
    assert s['statistics']['Healing']['mean'] == s['statistics']['Healing']['median'] == 10
    assert s['statistics']['KB']['total'] == 6
    assert s['statistics']['HK']['count'] == 2
    assert s['statistics']['Deaths']['mean'] == 2
    assert 'total' not in s['statistics']['Deaths per 10 minutes']
    assert 'total' not in s['statistics']['Damage rank']


def test_partial_known_result_can_count_without_guessing():
    s = summarize([sample(Result=None, _partial=True), sample('20261022-130000', Result='L', _partial=True)], [])
    assert s['result_count'] == 1 and s['win_rate'] == 0


def test_match_types_explicitly_separate():
    matches = [sample(str(i), Type=t) for i, t in enumerate(['Battleground', 'Brawl', 'Rated arena', 'Arena skirmish'])]
    assert len(by_type(matches, [])) == 4
    assert summarize(matches, [])['mixed_types']


def test_filters_all_dimensions_and_date_boundaries(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    matches = [sample(), sample('20261023-120000', Type='Brawl', Map='Other', **{'Premade present': 0}), sample('20261024-120000', Result=None, Type=None, Map=None, _partial=True, **{'Premade present': None})]
    rows = [player()]
    for filters in [Filters(start='2026-10-22', end='2026-10-22'), Filters(character='asterknight-examplerealm', match_type='battleground'), Filters(map_name='map'), Filters(premade=True), Filters(ally='buddy a')]:
        assert filter_matches(matches, rows, filters, ids) == [matches[0]]
    assert filter_matches(matches, rows, Filters(premade=False)) == [matches[1]]
    assert filter_matches(matches, rows, Filters(character='Asterknight-Other')) == []
    with pytest.raises(ValueError):
        filter_matches(matches, rows, Filters(start='2026-10-24', end='2026-10-22'))
    with pytest.raises(ValueError):
        filter_matches(matches, rows, Filters(ally='Buddy A'))


def test_enemy_and_owner_do_not_count_as_ally(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    rows = [player(Team='Enemy'), player('Asterknight', Realm='ExampleRealm', **{'Is me': 'Yes'})]
    assert filter_matches([sample()], rows, Filters(ally='Buddy A'), ids) == []
    assert filter_matches([sample()], rows, Filters(ally='Me'), ids) == []


def test_character_comparison_all_seed_characters_and_recent(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    matches = [sample('20261022-120000', Result='L', **{'PvP item level': 300}), sample('20261022-130000', **{'PvP item level': 333})]
    result = character_comparison(matches, [], ids, recent=1)
    assert len(result) == 5
    pal = next(r for r in result if r['character'] == 'Asterknight')
    assert pal['latest_pvp_item_level'] == 333
    assert pal['overall_explicitly_combined']['win_rate'] == 0.5
    assert pal['recent_by_type']['Battleground']['win_rate'] == 1
    assert next(r for r in result if r['character'] == 'Mossweaver')['realm'] is None


def test_ally_multiple_characters_and_duplicate_rows_count_once(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    rows = [player(Damage=100), player(Damage=100), player('Emberblade', Damage=200, Deaths=None)]
    matches = [sample(), sample('20261022-130000', Result='L')]
    result = ally_comparisons(matches, rows, ids)['Buddy A']['Battleground']
    assert result['together']['games'] == result['together']['result_count'] == 1
    assert result['together']['win_rate'] == 1 and result['without']['win_rate'] == 0
    assert result['ally_statistics']['Damage'] == {'count': 1, 'total': 300, 'mean': 300, 'median': 300}
    assert result['ally_statistics']['Deaths']['count'] == 0
    assert result['ally_statistics']['Damage rank']['mean'] == 1


def test_ally_unknown_results_and_missing_allies(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    result = ally_comparisons([sample(Result=None, _partial=True)], [player()], ids)
    assert result['Buddy A']['Battleground']['together']['games'] == 1
    assert result['Buddy A']['Battleground']['together']['win_rate'] is None
    assert result['Buddy D']['Battleground']['ally_statistics']['Damage']['count'] == 0


def parse_ai(text):
    matches, roster = text.split('MATCHES CSV\r\n', 1)[1].split('\r\nROSTER CSV\r\n')
    return list(csv.DictReader(io.StringIO(matches))), list(csv.DictReader(io.StringIO(roster)))


def test_export_headers_bom_unicode_and_context(real, tmp_path):
    _, ids, matches, rows = real
    manifest = export_folders(matches, rows, ids, tmp_path / 'exports')
    pal = next(m for m in manifest if m['label'] == 'Asterknight-ExampleRealm')
    assert pal['matches'] == 10 and pal['rosters'] == 211
    for item in manifest:
        for filename, header in [('matches.csv', MATCH_EXPORT_HEADER), ('roster.csv', ROSTER_EXPORT_HEADER)]:
            path = Path(item['folder']) / filename
            assert path.read_bytes().startswith(b'\xef\xbb\xbf')
            with path.open(encoding='utf-8-sig', newline='') as f:
                assert next(csv.reader(f)) == header
    with (Path(pal['folder']) / 'roster.csv').open(encoding='utf-8-sig', newline='') as f:
        exported = list(csv.DictReader(f))
    assert {r['Player'] for r in exported} == {r['Player'] for r in rows}
    assert any(any(ord(ch) > 127 for ch in r['Player']) for r in exported)
    assert all(r['Owner realm'] == 'ExampleRealm' for r in exported)
    assert sum(r['Partial'] == 'True' for r in exported) == 80


def test_export_filters_and_collision_safe_names(real, tmp_path):
    _, ids, matches, rows = real
    ids.assign('Nobody', '../Buddy C')
    manifest = export_folders(matches, rows, ids, tmp_path / 'exports', Filters(map_name='Eye of the Storm'))
    assert len({m['folder'] for m in manifest}) == len(manifest)
    assert all(Path(m['folder']).is_relative_to(tmp_path / 'exports') for m in manifest)
    pal = next(m for m in manifest if m['label'] == 'Asterknight-ExampleRealm')
    assert pal['matches'] == 1 and pal['rosters'] == 32
    with pytest.raises(ValueError):
        export_folders(matches, rows, ids, tmp_path / 'World of Warcraft')


def test_ai_report_default_limit_filters_and_partials(real):
    _, ids, matches, rows = real
    text = ai_report(matches, rows, ids)
    exported, roster = parse_ai(text)
    assert len(exported) == 10 and len(roster) == 211
    assert sum(r['Partial'] == 'True' for r in exported) == 3
    exported, roster = parse_ai(ai_report(matches, rows, ids, Filters(match_type='Battleground'), limit=2))
    assert len(exported) == 2 and all(r['Type'] == 'Battleground' for r in exported)
    assert {r['Match ID'] for r in roster} == {m['Match ID'] for m in exported}
    assert exported[-1]['Match ID'] == '20301022-192339'


def test_large_report_never_truncates_and_exact_default_limit(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    matches = [sample(f'20261022-{i:06}') for i in range(100)]
    rows = [player('Môônlet', m['Match ID'], Objectives='x' * 10000) for m in matches]
    exported, roster = parse_ai(ai_report(matches, rows, ids))
    assert len(exported) == len(roster) == 20
    text = ai_report(matches, rows, ids, limit=100)
    exported, roster = parse_ai(text)
    assert len(text) > 1_000_000 and len(exported) == len(roster) == 100
    assert all(len(r['Objectives']) == 10000 for r in roster)


@pytest.mark.parametrize('limit', [0, -1, 1.5, True])
def test_invalid_report_limit(tmp_path, limit):
    with pytest.raises(ValueError):
        ai_report([], [], IdentityMap(tmp_path / 'people.json'), limit=limit)


def test_cli_people_metrics_export_and_report(real, tmp_path, capsys, monkeypatch):
    archive, _, _, _ = real
    args = ['--archive-dir', str(archive.home)]
    assert main(args + ['people', 'list']) == 0
    assert json.loads(capsys.readouterr().out)['people']['Unassigned'] == ['Unboundleaf']
    assert main(args + ['people', 'assign', 'Unboundleaf', 'Buddy D']) == 0
    capsys.readouterr()
    assert main(args + ['people', 'unassign', 'Unboundleaf']) == 0
    capsys.readouterr()
    assert main(args + ['characters', '--character', 'Asterknight', '--recent', '2']) == 0
    data = json.loads(capsys.readouterr().out)
    assert next(r for r in data if r['character'] == 'Asterknight')['overall_explicitly_combined']['wins'] == 4
    assert main(args + ['allies', '--type', 'Battleground']) == 0
    assert 'Buddy A' in json.loads(capsys.readouterr().out)
    assert main(args + ['export', str(tmp_path / 'exports'), '--map', 'Eye of the Storm']) == 0
    assert json.loads(capsys.readouterr().out)
    captured = []
    monkeypatch.setattr('pvpledger_viewer.cli.copy_to_clipboard', captured.append)
    output = tmp_path / 'report.txt'
    assert main(args + ['report', '--limit', '1', '--copy', '--output', str(output)]) == 0
    assert json.loads(capsys.readouterr().out)['copied']
    assert len(parse_ai(captured[0])[0]) == 1
    assert output.read_bytes()[3:].decode('utf8') == captured[0]


def test_phase2_only_uses_archive_and_preserves_sources(real, tmp_path, monkeypatch):
    archive, ids, matches, rows = real
    before = FIXTURE.read_bytes()
    def no_import(*args, **kwargs):
        raise AssertionError('Phase 2 must never import or read game files')
    monkeypatch.setattr(archive, 'import_file', no_import)
    before_totals = archive.totals()
    character_comparison(archive.read_matches(), archive.read_rosters(), ids)
    ally_comparisons(matches, rows, ids)
    export_folders(matches, rows, ids, tmp_path / 'exports')
    ai_report(matches, rows, ids)
    assert archive.totals() == before_totals and FIXTURE.read_bytes() == before


@pytest.mark.parametrize('busy', [False, True])
def test_native_clipboard_unicode_large_text_and_failure_cleanup(monkeypatch, busy):
    from types import SimpleNamespace
    import pvpledger_viewer.export as module
    state = {'freed': False, 'closed': False, 'destroyed': False}
    class Function:
        def __init__(self, call):
            self.call = call
        def __call__(self, *args):
            return self.call(*args)
    def allocate(flags, size):
        state['buffer'] = ctypes.create_string_buffer(size)
        state['size'] = size
        return 123
    def capture(format_id, handle):
        state['copied'] = state['buffer'].raw
        return handle
    def mark(key):
        def call(*args):
            state[key] = True
            return 1
        return call
    kernel = SimpleNamespace(GlobalAlloc=Function(allocate), GlobalLock=Function(lambda h: ctypes.addressof(state['buffer'])),
        GlobalUnlock=Function(lambda h: 1), GlobalFree=Function(mark('freed')))
    user = SimpleNamespace(CreateWindowExW=Function(lambda *args: 42), DestroyWindow=Function(mark('destroyed')),
        OpenClipboard=Function(lambda h: 0 if busy else 1), CloseClipboard=Function(mark('closed')),
        EmptyClipboard=Function(lambda: 1), SetClipboardData=Function(capture))
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name, **kw: user if name == 'user32' else kernel, raising=False)
    monkeypatch.setattr(ctypes, 'WinError', lambda code: OSError(code, 'Clipboard busy'), raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 5, raising=False)
    text = 'Môônlet Fayë 🐻\r\n' * 100000
    if busy:
        with pytest.raises(OSError):
            copy_to_clipboard(text)
        assert state['freed'] and state['destroyed'] and not state['closed']
    else:
        copy_to_clipboard(text)
        assert state['copied'] == text.encode('utf-16-le') + b'\x00\x00'
        assert state['closed'] and state['destroyed'] and not state['freed']
    with pytest.raises(ValueError):
        copy_to_clipboard('embedded\x00NUL')


def test_lowercase_person_labels_remain_consistent(tmp_path):
    path = tmp_path / 'people.json'
    path.write_text(json.dumps({'people': {'me': ['Asterknight'], 'buddy a': ['Emberguard'], 'unassigned': []}}))
    ids = IdentityMap(path)
    assert len(character_comparison([sample()], [], ids)) == 1
    assert ally_comparisons([sample()], [player()], ids)['buddy a']['Battleground']['together']['games'] == 1


def test_date_filter_invalid_unknown_ids():
    assert filter_matches([sample('unknown')], [], Filters(start='2026-01-01')) == []
    assert filter_matches([sample(Date='2026-10-21')], [], Filters(end='2026-10-21'))


def test_same_name_different_realms_export_separate(tmp_path):
    ids = IdentityMap(tmp_path / 'people.json')
    matches = [sample(), sample(Realm='Other')]
    comparisons = character_comparison(matches, [], ids)
    pal = [r for r in comparisons if r['character'] == 'Asterknight']
    assert len(pal) == 2 and all(r['overall_explicitly_combined']['games'] == 1 for r in pal)
    groups = export_folders(matches, [], ids, tmp_path / 'exports')
    assert len({r['folder'] for r in groups}) == len(groups)


def test_opening_existing_archive_does_not_rewrite_database(real):
    archive, _, _, _ = real
    path = archive.home / 'archive.sqlite'
    before = path.read_bytes()
    another = Archive(archive.home)
    assert another.totals()['total'] == 10
    another.read_rosters()
    another.close()
    assert path.read_bytes() == before

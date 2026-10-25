"""Immutable source observations, reversible links and a deduplicated read model.

Base match/roster/override rows are never deleted by linking. Every analytics and
export reader receives this single logical projection, so links affect all views.
"""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import shutil
import uuid
from .identity import character_key
from .metrics import numeric
from .reflex_reader import DEFAULT_ZONE, pvp_time


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def migrate(archive):
    db = archive.db
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > 2:
        raise ValueError(f'Archive schema {version} is newer than supported schema 2')
    if version == 2:
        return
    exists = archive._existing_database
    if exists:
        import sqlite3
        folder = archive.home / 'backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        target = sqlite3.connect(folder / 'archive.sqlite')
        try:
            db.backup(target)
        finally:
            target.close()
        for name in ('people.json', 'settings.json'):
            if (archive.home / name).exists():
                shutil.copyfile(archive.home / name, folder / name)
        (folder / 'manifest.json').write_text(encode({'schema_before': version, 'schema_after': 2,
             'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}}), encoding='utf8')
    statements = [
        '''CREATE TABLE source_files(id INTEGER PRIMARY KEY, addon TEXT NOT NULL, path TEXT NOT NULL UNIQUE)''',
        '''CREATE TABLE observations(id INTEGER PRIMARY KEY, addon TEXT NOT NULL, character TEXT NOT NULL,
            realm TEXT NOT NULL, original_id TEXT NOT NULL, match_id TEXT NOT NULL,
            first_import INTEGER REFERENCES imports(id), last_import INTEGER REFERENCES imports(id),
            UNIQUE(addon,character,realm,original_id))''',
        '''CREATE TABLE observation_versions(observation_id INTEGER NOT NULL REFERENCES observations(id),
            digest TEXT NOT NULL, import_id INTEGER REFERENCES imports(id), payload TEXT NOT NULL,
            roster TEXT NOT NULL, raw_record TEXT, PRIMARY KEY(observation_id,digest))''',
        '''CREATE TABLE observation_files(observation_id INTEGER REFERENCES observations(id),
            file_id INTEGER REFERENCES source_files(id), first_import INTEGER REFERENCES imports(id),
            last_import INTEGER REFERENCES imports(id), PRIMARY KEY(observation_id,file_id))''',
        '''CREATE TABLE match_links(left_id INTEGER REFERENCES observations(id), right_id INTEGER REFERENCES observations(id),
            decision TEXT NOT NULL CHECK(decision IN ('confirmed','separate','ambiguous')), manual INTEGER NOT NULL,
            reason TEXT NOT NULL, updated TEXT NOT NULL, PRIMARY KEY(left_id,right_id), CHECK(left_id<right_id))''',
        '''CREATE TABLE link_history(id INTEGER PRIMARY KEY, left_id INTEGER, right_id INTEGER,
            decision TEXT, reason TEXT, updated TEXT)''',
    ]
    with db:
        db.execute('BEGIN IMMEDIATE')
        for statement in statements:
            db.execute(statement)
        for row in db.execute('SELECT * FROM matches').fetchall():
            m = json.loads(row['data'])
            rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM rosters WHERE character=? AND realm=? AND match_id=?', (row['character'], row['realm'], row['match_id']))]
            imp = db.execute('SELECT source FROM imports WHERE id=?', (row['import_id'],)).fetchone()
            observe(archive, 'PvP Ledger', (row['character'], row['realm'], row['match_id']), m, rows,
                    m.get('_raw'), row['import_id'], imp[0] if imp else 'legacy:unknown')
        db.execute('PRAGMA user_version=2')


def observe(archive, addon, key, match, rows, raw, import_id, source):
    db = archive.db
    original = match.get('_original_id') or key[2]
    found = db.execute('SELECT id FROM observations WHERE addon=? AND character=? AND realm=? AND original_id=?', (addon, *key[:2], original)).fetchone()
    if found:
        obs_id = found[0]
        db.execute('UPDATE observations SET last_import=? WHERE id=?', (import_id, obs_id))
    else:
        obs_id = db.execute('INSERT INTO observations(addon,character,realm,original_id,match_id,first_import,last_import) VALUES (?,?,?,?,?,?,?)',
                            (addon, *key[:2], original, key[2], import_id, import_id)).lastrowid
    payload, roster, raw_text = encode(match), encode(rows), encode(raw)
    digest = hashlib.sha256((payload + roster + raw_text).encode()).hexdigest()
    fresh = db.execute('INSERT OR IGNORE INTO observation_versions VALUES (?,?,?,?,?,?)', (obs_id, digest, import_id, payload, roster, raw_text)).rowcount
    normalized_path = str(source).casefold()
    db.execute('INSERT OR IGNORE INTO source_files(addon,path) VALUES (?,?)', (addon, normalized_path))
    file_id = db.execute('SELECT id FROM source_files WHERE path=?', (normalized_path,)).fetchone()[0]
    db.execute('INSERT INTO observation_files VALUES (?,?,?,?) ON CONFLICT(observation_id,file_id) DO UPDATE SET last_import=excluded.last_import',
               (obs_id, file_id, import_id, import_id))
    return obs_id, not bool(found), bool(fresh)


def records(archive):
    db = archive.db
    result = {}
    for row in db.execute('SELECT o.*,m.data,m.partial FROM observations o JOIN matches m ON m.character=o.character AND m.realm=o.realm AND m.match_id=o.match_id'):
        item = dict(row); item['match'] = json.loads(item.pop('data'))
        item['rows'] = [json.loads(r[0]) for r in db.execute('SELECT data FROM rosters WHERE character=? AND realm=? AND match_id=?',
                                                          (row['character'], row['realm'], row['match_id']))]
        result[row['id']] = item
    return result


def link(archive, left, right, decision, reason, manual=False, _values=None):
    if left == right or decision not in ('confirmed', 'separate', 'ambiguous'):
        raise ValueError('Choose two distinct observations and a known decision')
    left, right = sorted((int(left), int(right)))
    found = _values if _values is not None else records(archive)
    if left not in found or right not in found:
        raise ValueError('Observation no longer exists')
    a, b = found[left], found[right]
    if character_key(a['character'], a['realm']) != character_key(b['character'], b['realm']):
        raise ValueError('Cannot link observations owned by different characters/realms')
    prior = archive.db.execute('SELECT * FROM match_links WHERE left_id=? AND right_id=?', (left, right)).fetchone()
    if prior and prior['manual'] and not manual:
        return
    stamp = datetime.now(timezone.utc).isoformat()
    archive.db.execute('INSERT INTO match_links VALUES (?,?,?,?,?,?) ON CONFLICT(left_id,right_id) DO UPDATE SET decision=excluded.decision,manual=excluded.manual,reason=excluded.reason,updated=excluded.updated',
                       (left, right, decision, int(manual), reason, stamp))
    if not prior or (prior['decision'], prior['manual'], prior['reason']) != (decision, int(manual), reason):
        archive.db.execute('INSERT INTO link_history(left_id,right_id,decision,reason,updated) VALUES (?,?,?,?,?)', (left, right, decision, reason, stamp))


def comparison(a, b, zone=DEFAULT_ZONE):
    """5-second confirmation window; <=120 seconds is only a review candidate.

    Time, owner, duration and type alone are never enough. Confirmation additionally
    requires high-information equal player statistics or multiple named opponents.
    """
    x, y = a['match'], b['match']
    if character_key(a['character'], a['realm']) != character_key(b['character'], b['realm']):
        return None
    tx = x.get('_timestamp_utc') if x.get('_timestamp_utc') is not None else pvp_time(x, x.get('_source_timezone', zone)) if a['addon'] == 'PvP Ledger' else None
    ty = y.get('_timestamp_utc') if y.get('_timestamp_utc') is not None else pvp_time(y, y.get('_source_timezone', zone)) if b['addon'] == 'PvP Ledger' else None
    if tx is None or ty is None:
        return None
    delta = abs(tx - ty)
    if delta > 120:
        return None
    duration = numeric(x.get('Duration (s)')) and numeric(y.get('Duration (s)')) and abs(x['Duration (s)'] - y['Duration (s)']) <= 3
    mode = bool(x.get('Type')) and x.get('Type') == y.get('Type')
    known_map_conflict = (x.get('Map ID') is not None and y.get('Map ID') is not None and x['Map ID'] != y['Map ID']) or (x.get('Map') and y.get('Map') and x['Map'] != y['Map'])
    result_conflict = x.get('Result') and y.get('Result') and x['Result'] != y['Result']
    def own(item):
        return next((r for r in item['rows'] if r.get('Is me') == 'Yes'), {})
    sx = {k: x.get(k) if x.get(k) is not None else own(a).get(k) for k in ('Damage', 'Healing', 'KB', 'HK', 'Deaths')}
    sy = {k: y.get(k) if y.get(k) is not None else own(b).get(k) for k in sx}
    equal = [f for f in ('Damage', 'Healing', 'KB', 'HK', 'Deaths') if numeric(sx.get(f)) and sx[f] > 0 and sx[f] == sy.get(f)]
    names_a = {character_key(r['Player'], r.get('Realm')) for r in a['rows'] if r.get('Is me') != 'Yes'}
    names_b = {character_key(r['Player'], r.get('Realm')) for r in b['rows'] if r.get('Is me') != 'Yes'}
    shared = len(names_a & names_b)
    stats = ('Damage' in equal and 'Healing' in equal) or (len(equal) >= 3 and bool({'Damage', 'Healing'} & set(equal))) or (shared >= 2 and bool({'Damage', 'Healing'} & set(equal)))
    confirmed = delta <= 5 and duration and mode and stats and not known_map_conflict and not result_conflict
    reason = encode({'seconds_apart': delta, 'duration_agrees': bool(duration), 'type_agrees': mode,
                     'equal_nonzero_player_fields': equal, 'shared_other_players': shared,
                     'map_conflict': bool(known_map_conflict), 'result_conflict': bool(result_conflict),
                     'map_note': 'Unmapped REFlex instance IDs are retained, not guessed from time or name.'})
    return ('confirmed' if confirmed else 'ambiguous'), reason


def correlate(archive, zone=DEFAULT_ZONE):
    mapping = records(archive)
    values = list(mapping.values())
    pvp = [r for r in values if r['addon'] == 'PvP Ledger']
    reflex = [r for r in values if r['addon'] == 'REFlex']
    proposals = []
    for a in pvp:
        for b in reflex:
            result = comparison(a, b, zone)
            if result:
                proposals.append((a['id'], b['id'], *result))
    confirmed_counts = defaultdict(int)
    for a, b, decision, _ in proposals:
        if decision == 'confirmed':
            confirmed_counts[a] += 1; confirmed_counts[b] += 1
    for a, b, decision, reason in proposals:
        if confirmed_counts[a] > 1 or confirmed_counts[b] > 1:
            decision = 'ambiguous'; reason = 'Multiple candidates; manual review required. ' + reason
        link(archive, a, b, decision, reason, _values=mapping)
    proposed = {tuple(sorted((a, b))) for a, b, _, _ in proposals}
    for row in archive.db.execute('SELECT * FROM match_links WHERE manual=0').fetchall():
        if (row['left_id'], row['right_id']) not in proposed:
            link(archive, row['left_id'], row['right_id'], 'ambiguous', 'Updated evidence no longer meets the candidate rules; review required.', _values=mapping)


def components(archive, values):
    parent = {i: i for i in values}
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    decisions = list(archive.db.execute('SELECT * FROM match_links ORDER BY manual DESC,left_id,right_id'))
    separate = [(r['left_id'], r['right_id']) for r in decisions if r['decision'] == 'separate']
    for row in decisions:
        if row['decision'] != 'confirmed' or row['left_id'] not in parent or row['right_id'] not in parent:
            continue
        a, b = find(row['left_id']), find(row['right_id'])
        if a != b and not any(u in parent and v in parent and {find(u), find(v)} == {a, b} for u, v in separate):
            parent[b] = a
    groups = defaultdict(list)
    for i in values:
        groups[find(i)].append(values[i])
    return list(groups.values())


def project(archive):
    from pathlib import Path
    from . import supplemental
    location=archive.db.execute('PRAGMA database_list').fetchone()[2]
    home=getattr(archive,'home',None) or (Path(location).parent if location else None)
    include_supplemental=home is not None and not getattr(archive,'_exclude_supplemental',False)
    cache_key = (archive.db.total_changes, archive.db.execute('PRAGMA data_version').fetchone()[0],supplemental.generation(home) if include_supplemental else 0)
    if getattr(archive, '_projection_key', None) == cache_key:
        return archive._projection_data
    output, rosters = [], []
    for group in components(archive, records(archive)):
        group.sort(key=lambda r: (r['addon'] != 'PvP Ledger', bool(r['match'].get('_partial')), r['id']))
        canonical = group[0]; key = (canonical['character'], canonical['realm'], canonical['match_id'])
        merged, provenance, conflicts = {}, {}, []
        for observation in group:
            addon = observation['addon']
            for field, value in observation['match'].items():
                if field.startswith('_') or value is None:
                    continue
                if field in ('Match ID', 'Character', 'Realm'):
                    continue
                if merged.get(field) is None:
                    merged[field] = value; provenance[field] = [addon]
                elif merged[field] == value:
                    if addon not in provenance[field]:
                        provenance[field].append(addon)
                else:
                    conflicts.append({'field': field, 'chosen': merged[field], 'other': value, 'source': addon, 'observation_id': observation['id']})
        data = canonical['match'].copy(); data.update(merged)
        data.update({'Character': key[0], 'Realm': key[1], 'Match ID': key[2], '_observation_ids': [r['id'] for r in group],
                     'Source': 'Both' if len({r['addon'] for r in group}) > 1 else canonical['addon'],
                     '_provenance': provenance, '_conflicts': conflicts})
        if data.get('_timestamp_utc') is None:
            data['_timestamp_utc'] = next((r['match'].get('_timestamp_utc') for r in group if r['match'].get('_timestamp_utc') is not None), pvp_time(data))
        # Keep raw/partial semantics of a PvP Ledger record unless its missing
        # result, map and duration were actually supplied by the other source.
        if canonical['addon'] == 'PvP Ledger':
            data['_partial'] = bool(data.get('_partial')) and any(data.get(f) is None for f in ('Map', 'Result', 'Duration (s)'))
        source_refs = []
        override_values = {}
        for observation in reversed(group):
            for row in archive.db.execute('SELECT field,value FROM overrides WHERE character=? AND realm=? AND match_id=?', (observation['character'], observation['realm'], observation['match_id'])):
                override_values[row['field']] = json.loads(row['value'])
            refs = [dict(r) for r in archive.db.execute('''SELECT f.path,i.started,i.snapshot,i.sha256 FROM observation_files ofi
                JOIN source_files f ON f.id=ofi.file_id LEFT JOIN imports i ON i.id=ofi.last_import WHERE ofi.observation_id=?''', (observation['id'],))]
            source_refs.append({'id': observation['id'], 'addon': observation['addon'], 'original_id': observation['original_id'], 'files': refs})
        for field, value in override_values.items():
            data[field] = value; provenance[field] = ['User override']
        data['_observations'] = source_refs
        # Prefer the complete PvP Ledger scoreboard. Fill only missing values;
        # never delete any source roster from underlying storage.
        ordered = sorted(group, key=lambda r: (r['addon'] != 'PvP Ledger', bool(r['match'].get('_scoreboard_incomplete')), -len(r['rows'])))
        roster = {}
        complete = any(not r['match'].get('_scoreboard_incomplete') and len(r['rows']) > 1 for r in ordered)
        for observation in ordered:
            for row in observation['rows']:
                player = character_key(row['Player'], row.get('Realm'))
                if player not in roster:
                    roster[player] = row.copy()
                    roster[player]['_provenance'] = {f: [observation['addon']] for f, v in row.items() if not f.startswith('_') and v is not None}
                else:
                    existing = roster[player]
                    for field, value in row.items():
                        if not field.startswith('_') and existing.get(field) is None and value is not None:
                            existing[field] = value
                            existing['_provenance'][field] = [observation['addon']]
                        elif not field.startswith('_') and value is not None and existing.get(field) == value:
                            sources = existing['_provenance'].setdefault(field, [])
                            if observation['addon'] not in sources:
                                sources.append(observation['addon'])
                        elif not field.startswith('_') and field != 'Match ID' and value is not None and existing.get(field) is not None and existing[field] != value:
                            conflicts.append({'player': row['Player'], 'field': field, 'chosen': existing[field], 'other': value, 'source': observation['addon']})
        for row in roster.values():
            row.update({'Owner character': key[0], 'Owner realm': key[1], 'Match ID': key[2]})
            if complete:
                row['_scoreboard_incomplete'] = False
            rosters.append(row)
        data['_scoreboard_incomplete'] = not complete
        output.append(data)
    if include_supplemental:output,rosters=supplemental.project(home,output,rosters)
    archive._projection_key, archive._projection_data = cache_key, (output, rosters)
    return output, rosters


def review(archive):
    values = records(archive)
    return [dict(row) | {'left': values[row['left_id']]['match'], 'right': values[row['right_id']]['match']}
            for row in archive.db.execute('SELECT * FROM match_links ORDER BY manual DESC,decision,left_id,right_id')
            if row['left_id'] in values and row['right_id'] in values]

"""Pure normalization; original lines and snapshot IDs remain available."""
from collections import defaultdict
from datetime import datetime
import re
from .lua_reader import sequence
from .schema import MATCH_HEADER, parse_row


def normalize(document, character=None, realm=None):
    diagnostics, matches, rosters = [], {}, defaultdict(list)
    db = document.get('PvPLedgerDB', {})
    if not isinstance(db, dict):
        raise ValueError('PvPLedgerDB must be a table')
    for raw in sequence(db.get('matchCSV')):
        m = parse_row(raw, 'match', diagnostics)
        if m and m['Match ID'] and m['Character'] and m['Realm']:
            key = (m['Character'], m['Realm'], m['Match ID'])
            if key in matches:
                diagnostics.append({'code': 'duplicate_match', 'id': key[2]})
            m['_partial'] = any(m[f] is None for f in ('Map', 'Result', 'Duration (s)'))
            if m['_partial']:
                diagnostics.append({'code': 'incomplete_match', 'id': key[2]})
            matches[key] = m
        else:
            diagnostics.append({'code': 'missing_match_identity', 'raw': raw})
    owners = {(k[0], k[1]) for k in matches}
    for raw in sequence(db.get('rosterCSV')):
        r = parse_row(raw, 'roster', diagnostics)
        if not r or not r['Match ID'] or not r['Player']:
            diagnostics.append({'code': 'missing_roster_identity', 'raw': raw}); continue
        candidates = [(k[0], k[1]) for k in matches if k[2] == r['Match ID']]
        if not candidates:
            candidates = list(owners) if len(owners) == 1 else []
        if not candidates and character and realm:
            candidates = [(character, realm)]
        if len(set(candidates)) != 1:
            diagnostics.append({'code': 'ambiguous_roster_owner', 'raw': raw}); continue
        c, world = candidates[0]
        rosters[c, world, r['Match ID']].append(r)
    # Structured entries are a fallback, never overwrite the richer CSV record.
    for entry in sequence(db.get('matches')):
        if not isinstance(entry, dict):
            diagnostics.append({'code': 'invalid_structured_match', 'entry': entry}); continue
        # CSV is authoritative. A copied character file can have a different
        # directory name; that must not create a second structured fallback.
        if any(k[2] == entry.get('id') and (not entry.get('character') or k[0] == entry['character']) for k in matches):
            continue
        c = entry.get('character') or character or (next(iter(owners))[0] if len(owners) == 1 else None)
        world = entry.get('realm') or realm or (next(iter(owners))[1] if len(owners) == 1 else None)
        key = (c, world, entry.get('id'))
        if not all(key):
            diagnostics.append({'code': 'missing_structured_identity', 'entry': entry}); continue
        if key not in matches:
            m = dict.fromkeys(MATCH_HEADER)
            mapping = {'id': 'Match ID', 'character': 'Character', 'map': 'Map', 'type': 'Type', 'result': 'Result', 'kb': 'KB', 'hk': 'HK', 'deaths': 'Deaths', 'damage': 'Damage', 'healing': 'Healing', 'duration': 'Duration (s)'}
            for src, dst in mapping.items():
                m[dst] = entry.get(src)
            m.update({'Character': c, 'Realm': world, '_partial': True, '_raw': None})
            matches[key] = m
            diagnostics.append({'code': 'structured_fallback', 'id': key[2]})
    orphan_groups = defaultdict(list)
    for key in rosters:
        if key not in matches:
            try:
                timestamp = datetime.strptime(key[2], '%Y%m%d-%H%M%S')
                orphan_groups[key[:2]].append((timestamp, key))
            except ValueError:
                orphan_groups[key[:2]].append((datetime.min, key))
                diagnostics.append({'code': 'invalid_snapshot_id', 'id': key[2]})
    aliases = {}
    # Diagnose duplicates even in snapshots that will be superseded.
    for key, rows in rosters.items():
        seen = set()
        for row in rows:
            identity = (row['Player'], row['Realm'] or '')
            if identity in seen:
                diagnostics.append({'code': 'duplicate_roster', 'id': key[2], 'player': identity})
            seen.add(identity)
    for owner, entries in orphan_groups.items():
        clusters = []
        for timestamp, key in sorted(entries):
            if not clusters or timestamp == datetime.min or (timestamp - clusters[-1][0][0]).total_seconds() > 60:
                clusters.append([])
            clusters[-1].append((timestamp, key))
        for cluster in clusters:
            # Prefer latest full-sized snapshot over a later truncated scoreboard.
            sizes = {key: len({(r['Player'], r['Realm']) for r in rosters[key]}) for _, key in cluster}
            selected = max(cluster, key=lambda item: (sizes[item[1]], item[0]))[1]
            canonical = cluster[0][1]
            m = dict.fromkeys(MATCH_HEADER)
            m.update({'Character': owner[0], 'Realm': owner[1], 'Match ID': canonical[2], '_partial': True, '_raw': None, '_snapshot': selected[2], '_snapshot_count': sizes[selected]})
            matches[canonical] = m
            for _, key in cluster:
                aliases[key] = canonical
            diagnostics.append({'code': 'orphan_cluster', 'id': canonical[2], 'snapshots': [k[2] for _, k in cluster], 'selected': selected[2]})
            rosters[canonical] = rosters[selected]
    output = {}
    for key, m in matches.items():
        dedup = {}
        for r in rosters.get(key, []):
            identity = (r['Player'], r['Realm'] or '')
            dedup[identity] = r
        rows = list(dedup.values())
        if not m['Addon version'] and m['Type'] and 'arena' in m['Type'].lower():
            if m['Rated'] == 'Yes' and all(m[f] in (0, None) for f in ('Rating change', 'MMR before', 'MMR after')):
                m['Rated'], m['Type'] = 'No', 'Arena skirmish'
                diagnostics.append({'code': 'arena_classification_repaired', 'id': key[2]})
            if rows and m['Team deaths'] in (0, None) and m['Enemy deaths'] in (0, None):
                for team, field in [('Enemy', 'Team deaths'), ('Mine', 'Enemy deaths')]:
                    values = [r['KB'] for r in rows if r['Team'] == team]
                    m[field] = sum(values) if values and all(v is not None for v in values) else None
                m['Deaths'] = None
                for r in rows:
                    r['Deaths'] = None
        pair = re.fullmatch(r'(\d+)\s*/\s*(\d+)', m['Score detail'] or '')
        if pair and 'arena' not in (m['Type'] or '').lower():
            for field, value in zip(('Alliance score', 'Horde score'), pair.groups()):
                if m[field] is None:
                    m[field] = int(value)
        if m['_partial']:
            objectives = ' '.join(r['Objectives'] or '' for r in rows)
            m['_map_suggestion'] = 'Silvershard Mines' if 'Carts Controlled' in objectives else ('Deepwind Gorge' if 'Carts Captures' in objectives and 'Mines Assaulted' in objectives else None)
        output[key] = rows
    return matches, output, aliases, diagnostics

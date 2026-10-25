"""Participant comparisons from logical archive records, with conservative event identity."""
from collections import defaultdict
from difflib import SequenceMatcher
from .identity import character_key, normalized
from .metrics import (Filters, filter_matches, group_rosters, match_key, numeric,
                      player_rank, distribution, chronological_key)
from .trends import rolling_results

METRICS = ('Win rate', 'Damage per minute', 'Healing per minute', 'KB', 'HK',
           'Deaths per 10 minutes', 'Damage rank', 'Healing rank', 'Damage', 'Healing', 'PvP item level')
QUICK = {'Win rate': 'Win rate', 'Survivability': 'Deaths per 10 minutes',
         'Damage performance': 'Damage per minute', 'Healing performance': 'Healing per minute',
         'Team-relative rankings': 'Damage rank', 'Gear progression': 'PvP item level'}


def catalogue(matches, rows, identities):
    found = {}
    for m in matches:
        found.setdefault(character_key(m['Character'], m.get('Realm')), (m['Character'], m.get('Realm') or ''))
    for r in rows:
        found.setdefault(character_key(r['Player'], r.get('Realm')), (r['Player'], r.get('Realm') or ''))
    return [{'key': list(key), 'name': n, 'realm': realm, 'person': identities.resolve(n, realm),
             'label': f"{n}-{realm or '[unknown realm]'} · {identities.label(identities.resolve(n, realm))}"}
            for key, (n, realm) in sorted(found.items())]


def suggestions(entries, query, limit=12):
    q = normalized(query)
    def rank(item):
        name = normalized(item['name'])
        full = normalized(item['name'] + '-' + item['realm'])
        if not q or q in (name, full):
            return 0, 0, full
        if name.startswith(q):
            return 1, 0, full
        if q in name or q in full:
            return 2, 0, full
        similarity = SequenceMatcher(None, q, name).ratio()
        return (3 if similarity >= .6 else 4), -similarity, full
    return sorted((e for e in entries if rank(e)[0] < 4), key=rank)[:limit]


def same_event(a, b, rows_a, rows_b):
    # Owner-specific v1.1 keys must not be collapsed by time alone.
    if match_key(a) == match_key(b):
        return True
    if a.get('_excel_historical') or b.get('_excel_historical'):
        return False # Explicitly approved separate historical events stay separate.
    if character_key(a['Character'], a.get('Realm')) == character_key(b['Character'], b.get('Realm')):
        return False
    if not all(numeric(m.get('_timestamp_utc')) and numeric(m.get('Duration (s)')) for m in (a, b)):
        return False
    if abs(a['_timestamp_utc'] - b['_timestamp_utc']) > 5 or abs(a['Duration (s)'] - b['Duration (s)']) > 3:
        return False
    if not a.get('Type') or a.get('Type') != b.get('Type'):
        return False
    map_equal = (a.get('Map') and a.get('Map') == b.get('Map')) or (a.get('Map ID') is not None and a.get('Map ID') == b.get('Map ID'))
    if not map_equal:
        return False
    other = {character_key(r['Player'], r.get('Realm')): r for r in rows_b}
    evidence = 0
    for r in rows_a:
        s = other.get(character_key(r['Player'], r.get('Realm')))
        if s and all(numeric(r.get(f)) and r[f] == s.get(f) for f in ('Damage', 'Healing')) and (r['Damage'] > 0 or r['Healing'] > 0):
            evidence += 1
    return evidence >= 2


def participant_records(matches, rows):
    """One record per actual character/event; no attendance inferred from match duration."""
    grouped = group_rosters(rows)
    events, prepared = [], []
    for m in sorted(matches, key=chronological_key):
        roster = grouped.get(match_key(m), [])
        candidates = [i for i, group in enumerate(events) if all(same_event(m, other, roster, grouped.get(match_key(other), [])) for other in group)]
        event = candidates[0] if len(candidates) == 1 else len(events)
        if event == len(events):
            events.append([])
        events[event].append(m)
        owner = character_key(m['Character'], m.get('Realm'))
        present = {character_key(r['Player'], r.get('Realm')): r for r in roster}
        if owner not in present:
            present[owner] = {'Player': m['Character'], 'Realm': m.get('Realm'), 'Is me': 'Yes', 'Team': 'Mine'}
        for key, row in present.items():
            own = key == owner
            record = {f: m.get(f) for f in ('Date', 'Time', 'Type', 'Map', 'Map ID', '_timestamp_utc', '_partial', 'Source')}
            record.update({'Character': row['Player'], 'Realm': row.get('Realm') or '', 'Match ID': m['Match ID'],
                           '_event': event, '_owner_key': match_key(m), '_own': own,
                           '_complete_roster': not m.get('_scoreboard_incomplete') and len(roster) > 1,
                           'Class': m.get('Class') if own else row.get('Class'), 'Spec': m.get('Spec') if own else row.get('Spec'),
                           'Minutes played': m.get('Minutes played') if own else None,
                           'PvP item level': m.get('PvP item level') if own else None})
            for f in ('Damage', 'Healing', 'KB', 'HK', 'Deaths'):
                record[f] = m.get(f) if own and m.get(f) is not None else row.get(f)
            outcome = m.get('Result')
            record['Result'] = outcome if own or row.get('Team') == 'Mine' else ({'W': 'L', 'L': 'W'}.get(outcome) if row.get('Team') == 'Enemy' else None)
            for field in ('Damage', 'Healing'):
                record[field + ' rank'] = player_rank(row, roster, field)
                minutes = record['Minutes played']
                record[field + ' per minute'] = record[field] / minutes if numeric(record[field]) and numeric(minutes) and minutes > 0 else None
            minutes, deaths = record['Minutes played'], record['Deaths']
            record['Deaths per 10 minutes'] = deaths / minutes * 10 if numeric(deaths) and numeric(minutes) and minutes > 0 else None
            prepared.append(record)
    best = {}
    for r in prepared:
        key = (r['_event'], character_key(r['Character'], r['Realm']))
        priority = (r['_own'], r['_complete_roster'], sum(r.get(f) is not None for f in METRICS))
        if key not in best or priority > best[key][0]:
            best[key] = priority, r
    return [r for _, r in best.values()]


def summarize(records):
    wins, losses = sum(r.get('Result') == 'W' for r in records), sum(r.get('Result') == 'L' for r in records)
    return {'games': len(records), 'wins': wins, 'losses': losses, 'known_results': wins + losses,
            'win_rate': wins / (wins + losses) * 100 if wins + losses else None,
            'metrics': {f: distribution(r.get(f) for r in records) for f in METRICS if f != 'Win rate'},
            'contexts': sorted({(r.get('Type') or 'Unknown', r.get('Class') or 'Unknown', r.get('Spec') or 'Unknown') for r in records})}


def paired_text(model):
    from .viewmodels import display
    lines = ['PAIRED MATCHES', 'Differences are the first selection minus the second. Unknown values are not zero.']
    if not model['paired']:
        lines.append('No jointly observed matches in this selection.')
    for pair in model['paired']:
        first = pair['players'][0]
        location = first.get('Map') or (f"Map ID {first['Map ID']}" if first.get('Map ID') is not None else 'Unknown map')
        lines.append(f"\n{first.get('Date') or 'Unknown date'} {first.get('Time') or ''} · {first.get('Type') or 'Unknown type'} · {location}")
        for player in pair['players']:
            names = ', '.join(player.get('_represented_characters', [])) or player['Character'] + '-' + player['Realm']
            lines.append(f"  {names} · Result {player.get('Result') or 'Unknown'}")
            for metric in METRICS[1:]:
                lines.append(f'    {metric}: {display(player.get(metric))}')
        lines.append('  Paired differences: ' + '; '.join(f'{field}: {display(value)}' for field, value in pair['differences'].items()))
    return '\n'.join(lines)


def compare(matches, rows, identities, selections, scope='All Recorded Matches', filters=None, window=20,
            item_min=None, item_max=None):
    if scope not in ('All Recorded Matches', 'Played Together', 'Only Shared Matches'):
        raise ValueError('Unknown comparison scope')
    if len(selections) < 2:
        raise ValueError('Select at least two characters or people')
    rolling_results([], window)
    for v in (item_min, item_max):
        if v is not None and (not numeric(v) or v < 0):
            raise ValueError('Item-level bounds must be nonnegative numbers')
    if item_min is not None and item_max is not None and item_min > item_max:
        raise ValueError('Item-level minimum exceeds maximum')
    selected = filter_matches(matches, rows, filters or Filters(), identities)
    records = participant_records(selected, rows)
    series = []
    for selection in selections:
        if selection['kind'] == 'person':
            person = identities.person_name(selection['person'])
            chosen = [r for r in records if identities.resolve(r['Character'], r['Realm']) == person
                      and (not selection.get('character') or character_key(r['Character'], r['Realm']) == tuple(selection['character']))]
        elif selection['kind'] == 'character':
            chosen = [r for r in records if character_key(r['Character'], r['Realm']) == tuple(selection['character'])]
        else:
            raise ValueError('Unknown comparison selection')
        if item_min is not None or item_max is not None:
            chosen = [r for r in chosen if numeric(r.get('PvP item level')) and (item_min is None or r['PvP item level'] >= item_min) and (item_max is None or r['PvP item level'] <= item_max)]
        by_event = defaultdict(list)
        for r in chosen:
            by_event[r['_event']].append(r)
        collapsed = []
        for event_rows in by_event.values():
            r = event_rows[0].copy()
            r['_represented_characters'] = [x['Character'] + '-' + x['Realm'] for x in event_rows]
            if len(event_rows) > 1:
                for field in METRICS:
                    r[field] = None
                results = {x.get('Result') for x in event_rows}
                r['Result'] = results.pop() if len(results) == 1 else None
            collapsed.append(r)
        series.append({'label': selection['label'], 'records': sorted(collapsed, key=chronological_key)})
    shared = set.intersection(*(set(r['_event'] for r in s['records']) for s in series))
    if scope != 'All Recorded Matches':
        for s in series:
            s['records'] = [r for r in s['records'] if r['_event'] in shared]
    for s in series:
        s['summary'] = summarize(s['records'])
        s['by_type'] = {t: summarize([r for r in s['records'] if (r.get('Type') or 'Unknown') == t]) for t in sorted({r.get('Type') or 'Unknown' for r in s['records']})}
        s['rolling_by_type'] = {t: rolling_results([r for r in s['records'] if (r.get('Type') or 'Unknown') == t], window) for t in s['by_type']}
    paired = []
    for event in sorted(shared):
        pair = [next(r for r in s['records'] if r['_event'] == event) for s in series]
        paired.append({'event': event, 'players': pair,
                       'differences': {f: pair[0].get(f) - pair[1].get(f) if all(numeric(r.get(f)) for r in pair[:2]) else None for f in METRICS if f != 'Win rate'}})
    return {'scope': scope, 'series': series, 'paired': paired, 'window': window,
            'note': ('Independent samples: these can be different matches and match types. ' if scope == 'All Recorded Matches' else 'Paired samples: only events where every selection is actually observed. ')
                    + 'Roles, gear and teams differ; these are descriptive comparisons. Unknown statistics are excluded per metric. Roster-only attendance and gear are unknown. Multiple characters of one person count once per event; ambiguous person metrics are withheld. Cross-owner events require strong scoreboard evidence; uncertain events stay separate.'}

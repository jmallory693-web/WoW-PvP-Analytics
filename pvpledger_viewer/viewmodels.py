"""Toolkit-free presentation models and stable, numeric sorting for desktop views."""
from .identity import character_key, normalized
from .metrics import (character_comparison, match_date, match_key, numeric, performance,
                      summarize, chronological_key)


def display(value, digits=1):
    if value is None:
        return 'Unknown'
    if isinstance(value, float):
        return f'{value:,.{digits}f}'
    if isinstance(value, int):
        return f'{value:,}'
    return str(value)


def percent(value):
    return f'{value * 100:.1f}%' if value is not None else 'Unknown'


def premade_description(match):
    if match.get('Premade members'):
        return match['Premade members']
    if match.get('Premade present') in (0, 'No'):
        return 'None recorded'
    return 'Unknown — see highlighted allied roster' if match.get('_partial') or match.get('Premade present') else 'Unknown'


def sort_records(records, field, descending=False):
    """Unknowns stay last in both directions; never lexicographically sort numbers."""
    known = [r for r in records if r.get(field) is not None]
    unknown = [r for r in records if r.get(field) is None]
    def value(row):
        v = row[field]
        return (0, v) if numeric(v) else (1, normalized(str(v)))
    return sorted(known, key=value, reverse=descending) + unknown


def history_row(match):
    stamp = match_date(match)
    time = match.get('Time') or (match['Match ID'][9:11] + ':' + match['Match ID'][11:13] if len(match['Match ID']) == 15 else '')
    return match | {'Source':match.get('Display source',match.get('Source')),'Date/time': (stamp.isoformat() + ' ' + time).strip() if stamp else None,
                    'Map display': match.get('Map') or (f"Map ID {match['Map ID']}" if match.get('Map ID') is not None else None),
                    'Status': ('PARTIAL · ' if match.get('_partial') else '') + (match.get('Result') or 'Unknown'),
                    'Duration': match.get('Duration (s)')}


def home_model(matches, rosters, identities):
    cards = []
    comparisons = character_comparison(matches, rosters, identities)
    known = {(c['character'], c['realm']) for c in comparisons}
    for name, realm in sorted({(m['Character'], m.get('Realm')) for m in matches} - known):
        selected = sorted([m for m in matches if (m['Character'], m.get('Realm')) == (name, realm)], key=chronological_key)
        ilvl = next((m['PvP item level'] for m in reversed(selected) if m.get('PvP item level') is not None), None)
        comparisons.append({'character': name, 'realm': realm, 'latest_pvp_item_level': ilvl,
                            'overall_explicitly_combined': summarize(selected, rosters)})
    for comparison in comparisons:
        name, realm = comparison['character'], comparison['realm']
        selected = sorted([m for m in matches if (m['Character'], m.get('Realm')) == (name, realm)], key=chronological_key)
        latest = selected[-1] if selected else {}
        last_known = lambda field: next((m[field] for m in reversed(selected) if m.get(field) is not None), None)
        cards.append({'character': name, 'realm': realm, 'class': last_known('Class'), 'spec': last_known('Spec'),
                      'item_level': comparison['latest_pvp_item_level'], 'summary': comparison['overall_explicitly_combined'],
                      'last_played': history_row(latest)['Date/time'] if latest else None})
    return {'summary': summarize(matches, rosters), 'cards': cards}


def scoreboard_model(match, rows, identities):
    teams = {'Mine': [], 'Enemy': [], 'Unknown': []}
    owner = character_key(match['Character'], match.get('Realm'))
    for row in rows:
        person = identities.resolve(row['Player'], row.get('Realm'))
        is_me = row.get('Is me') == 'Yes' or character_key(row['Player'], row.get('Realm')) == owner
        known = row.get('Team') == 'Mine' and person not in ('Unassigned', identities.owner_person)
        premade = row.get('Team') == 'Mine' and row.get('Is premade') == 'Yes'
        marker = 'YOU' if is_me else ('PREMADE' if premade else 'ALLY' if known else '')
        attendance = []
        if row.get('Joined late') == 1:
            attendance.append('Late join')
        if row.get('Left early') == 1:
            attendance.append('Left early')
        item = row | {'Person': getattr(identities, 'label', lambda p:p)(person), 'Highlight': 'self' if is_me else ('premade' if premade or known else ''),
                      'Identity': marker, 'Attendance': ' · '.join(attendance) or '—',
                      'Player/realm': row['Player'] + ('-' + row['Realm'] if row.get('Realm') else '')}
        teams.setdefault(row.get('Team') or 'Unknown', []).append(item)
    for team in teams:
        teams[team] = sort_records(teams[team], 'Damage', True)
    enriched = performance(match, rows)
    return {'match': enriched, 'teams': teams, 'partial': bool(match.get('_partial')),
            'raw_match_available': bool(match.get('_raw')),
            'metadata': {field: match.get(field) for field in ('Map', 'Result', 'Type', 'Duration (s)', 'Minutes played',
                'My team score', 'Enemy team score', 'Alliance score', 'Horde score', 'Team damage', 'Enemy damage',
                'Team healing', 'Enemy healing', 'Team deaths', 'Enemy deaths', 'Premade members')} | {'Win margin': enriched['Win margin']}}

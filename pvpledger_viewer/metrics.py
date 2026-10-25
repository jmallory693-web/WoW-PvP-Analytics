"""Pure archive-record analytics. Unknowns stay unknown; each key counts once."""
from dataclasses import dataclass
from datetime import date
from statistics import mean, median
import math
from .identity import character_key, normalized


def match_key(match):
    return match.get('Character'), match.get('Realm'), match['Match ID']


def roster_key(row):
    return row['Owner character'], row['Owner realm'], row['Match ID']


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def distribution(values):
    values = [v for v in values if numeric(v)]
    return {'count': len(values), 'total': sum(values) if values else None, 'mean': mean(values) if values else None,
            'median': median(values) if values else None}


def statistic(field, values):
    result = distribution(values)
    if field not in ('Damage', 'Healing', 'KB', 'HK', 'Deaths'):
        result.pop('total')
    return result


def match_date(match):
    value = match.get('Date')
    if value:
        return date.fromisoformat(value)
    # IDs encode a known local capture date even for orphan scoreboards.
    stamp = match['Match ID'][:8]
    try:
        return date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
    except ValueError:
        return None


def chronological_key(match):
    stamp = match_date(match)
    return (str(stamp or ''), match.get('Time') or '',
            match.get('_timestamp_utc') or 0, match['Match ID'], match['Character'], match.get('Realm') or '')


def own_rows(match, rosters):
    return [r for r in rosters if roster_key(r) == match_key(match)]


def player_rank(player, rows, field):
    """Competition rank: tied leaders both rank 1; next rank is 3."""
    value, team = player.get(field), player.get('Team')
    if not numeric(value) or team not in ('Mine', 'Enemy') or any(r.get('_scoreboard_incomplete') for r in rows):
        return None
    unique = {character_key(r['Player'], r.get('Realm')): r for r in rows if r.get('Team') == team}
    if any(not numeric(r.get(field)) for r in unique.values()):
        return None
    return 1 + sum(numeric(r.get(field)) and r[field] > value for r in unique.values())


def performance(match, rows):
    me = next((r for r in rows if r.get('Is me') == 'Yes'), None)
    if me is None:
        me = next((r for r in rows if character_key(r['Player'], r.get('Realm')) == character_key(match['Character'], match.get('Realm'))), None)
    minutes, deaths = match.get('Minutes played'), match.get('Deaths')
    margin = None
    if normalized(match.get('Type') or '') in ('battleground', 'brawl'):
        a, b = match.get('My team score'), match.get('Enemy team score')
        if numeric(a) and numeric(b):
            margin = a - b
    return match | {
        'Deaths per 10 minutes': deaths / minutes * 10 if numeric(deaths) and numeric(minutes) and minutes > 0 else None,
        'Damage rank': player_rank(me, rows, 'Damage') if me else None,
        'Healing rank': player_rank(me, rows, 'Healing') if me else None,
        'Win margin': margin,
    }


@dataclass(frozen=True)
class Filters:
    start: str | None = None
    end: str | None = None
    character: str | None = None
    match_type: str | None = None
    map_name: str | None = None
    premade: bool | None = None
    ally: str | None = None


def has_person(match, rows, identities, person):
    person = normalized(identities.person_name(person))
    owner = character_key(match['Character'], match.get('Realm'))
    return any(r.get('Team') == 'Mine' and r.get('Is me') != 'Yes'
               and character_key(r['Player'], r.get('Realm')) != owner
               and normalized(identities.resolve(r['Player'], r.get('Realm'))) == person for r in rows)


def filter_matches(matches, rosters, filters=None, identities=None):
    filters = filters or Filters()
    start = date.fromisoformat(filters.start) if filters.start else None
    end = date.fromisoformat(filters.end) if filters.end else None
    if start and end and start > end:
        raise ValueError('Start date must not follow end date')
    if filters.ally and identities is None:
        raise ValueError('Ally filtering requires identity mappings')
    selected = {}
    grouped = group_rosters(rosters)
    for m in matches:
        stamp = match_date(m)
        if (start and (stamp is None or stamp < start)) or (end and (stamp is None or stamp > end)):
            continue
        if filters.character:
            name, realm = character_key(filters.character)
            actual = character_key(m['Character'], m.get('Realm'))
            if actual[0] != name or (realm and actual[1] != realm):
                continue
        if filters.match_type and normalized(m.get('Type') or 'Unknown') != normalized(filters.match_type):
            continue
        if filters.map_name and normalized(m.get('Map') or (f"Map ID {m['Map ID']}" if m.get('Map ID') is not None else '')) != normalized(filters.map_name):
            continue
        count = m.get('Premade present')
        if filters.premade is not None and (not numeric(count) or (count >= 1) != filters.premade):
            continue
        if filters.ally and not has_person(m, grouped.get(match_key(m), []), identities, filters.ally):
            continue
        selected[match_key(m)] = m
    return sorted(selected.values(), key=chronological_key)


def group_rosters(rosters):
    grouped = {}
    for row in rosters:
        grouped.setdefault(roster_key(row), []).append(row)
    return grouped


PERFORMANCE_FIELDS = ('Damage', 'Healing', 'KB', 'HK', 'Deaths', 'Deaths per 10 minutes',
                      'Damage rank', 'Healing rank', 'Win margin', 'PvP item level')


def summarize(matches, rosters):
    grouped = group_rosters(rosters)
    unique = {match_key(m): m for m in matches}
    enriched = [performance(m, grouped.get(k, [])) for k, m in unique.items()]
    wins = sum(m.get('Result') == 'W' for m in enriched)
    losses = sum(m.get('Result') == 'L' for m in enriched)
    types = sorted({m.get('Type') or 'Unknown' for m in enriched})
    return {'games': len(enriched), 'partial_games': sum(bool(m.get('_partial')) for m in enriched),
            'wins': wins, 'losses': losses, 'result_count': wins + losses,
            'win_rate': wins / (wins + losses) if wins + losses else None,
            'match_types': types, 'mixed_types': len(types) > 1,
            'statistics': {field: statistic(field, (m.get(field) for m in enriched)) for field in PERFORMANCE_FIELDS}}


def by_type(matches, rosters):
    types = sorted({m.get('Type') or 'Unknown' for m in matches})
    return {t: summarize([m for m in matches if (m.get('Type') or 'Unknown') == t], rosters) for t in types}


def character_comparison(matches, rosters, identities, recent=20):
    if recent < 1:
        raise ValueError('Recent match count must be positive')
    result = []
    characters = sorted({(m['Character'], m.get('Realm')) for m in matches if normalized(identities.resolve(m['Character'], m.get('Realm'))) == normalized(identities.owner_person)})
    for entry in identities.people.get(identities.owner_person, []):
        name, _, realm = entry.partition('-')
        if not any(character_key(c, r)[0] == character_key(name)[0] and (not realm or character_key(c, r)[1] == character_key(name, realm)[1]) for c, r in characters):
            characters.append((name, realm or None))
    grouped = group_rosters(rosters)
    for name, realm in characters:
        selected = sorted([m for m in matches if (m['Character'], m.get('Realm')) == (name, realm)], key=chronological_key)
        ilvls = [m.get('PvP item level') for m in selected if numeric(m.get('PvP item level'))]
        result.append({'character': name, 'realm': realm, 'overall_explicitly_combined': summarize(selected, rosters),
                       'by_type': by_type(selected, rosters), 'latest_pvp_item_level': ilvls[-1] if ilvls else None,
                       'recent_limit': recent, 'recent_by_type': by_type(selected[-recent:], rosters),
                       'recent_matches': [performance(m, grouped.get(match_key(m), [])) for m in selected[-recent:]]})
    return result


def ally_comparisons(matches, rosters, identities):
    """Ally statistics use one observation per person per logical owner match.

    If multiple characters of a person occur, their numeric stats are summed
    only when all are known; rank is the best actual character rank, never the
    rank of a fictitious combined player. No attendance duration is invented.
    """
    matches = filter_matches([m for m in matches if normalized(identities.resolve(m['Character'], m.get('Realm'))) == normalized(identities.owner_person)], rosters)
    grouped = group_rosters(rosters)
    result = {}
    for person in identities.people:
        if normalized(person) in (normalized(identities.owner_person), 'unassigned'):
            continue
        breakdown = {}
        for kind in sorted({m.get('Type') or 'Unknown' for m in matches}):
            pool = [m for m in matches if (m.get('Type') or 'Unknown') == kind]
            together, without, observations = [], [], []
            for m in pool:
                rows = grouped.get(match_key(m), [])
                if not has_person(m, rows, identities, person):
                    without.append(m); continue
                together.append(m)
                owner = character_key(m['Character'], m.get('Realm'))
                players = {character_key(r['Player'], r.get('Realm')): r for r in rows
                           if r.get('Team') == 'Mine' and r.get('Is me') != 'Yes'
                           and character_key(r['Player'], r.get('Realm')) != owner
                           and identities.resolve(r['Player'], r.get('Realm')) == person}
                observation = {}
                for field in ('Damage', 'Healing', 'Deaths', 'KB', 'HK'):
                    values = [r.get(field) for r in players.values()]
                    observation[field] = sum(values) if values and all(numeric(v) for v in values) else None
                for field in ('Damage', 'Healing'):
                    ranks = [player_rank(r, rows, field) for r in players.values()]
                    observation[field + ' rank'] = min(ranks) if ranks and all(r is not None for r in ranks) else None
                observations.append(observation)
            breakdown[kind] = {'together': summarize(together, rosters), 'without': summarize(without, rosters),
                               'ally_statistics': {f: statistic(f, (o.get(f) for o in observations)) for f in ('Damage', 'Healing', 'Deaths', 'KB', 'HK', 'Damage rank', 'Healing rank')}}
        result[person] = breakdown
    return result

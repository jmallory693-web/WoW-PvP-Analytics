"""Pure trend preparation using the established archive/Phase 2 definitions."""
from collections import defaultdict
from .metrics import (Filters, filter_matches, group_rosters, match_key, match_date,
                      performance, numeric, distribution, has_person, chronological_key)

METRICS = ('Win rate', 'Damage', 'Damage per minute', 'Damage rank', 'Healing',
           'Healing per minute', 'Healing rank', 'Deaths', 'Deaths per 10 minutes', 'PvP item level')


def rolling_results(records, window=20):
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 10000:
        raise ValueError('Rolling window must be an integer from 1 to 10000')
    valid = [r for r in records if r.get('Result') in ('W', 'L')]
    points = []
    wins = 0
    for index, record in enumerate(valid):
        wins += record['Result'] == 'W'
        if index >= window:
            wins -= valid[index - window]['Result'] == 'W'
        if index + 1 >= window:
            points.append({'key': match_key(record), 'date': str(match_date(record) or 'Unknown'),
                           'value': wins / window * 100, 'count': window})
    return points


def metric_value(record, metric):
    if metric.endswith(' per minute'):
        value, minutes = record.get(metric.removesuffix(' per minute')), record.get('Minutes played')
        return value / minutes if numeric(value) and numeric(minutes) and minutes > 0 else None
    value = record.get(metric)
    return value if numeric(value) else None


def sample_summary(records):
    known = [m for m in records if m.get('Result') in ('W', 'L')]
    return {'matches': len(records), 'known_results': len(known),
            'win_rate': sum(m['Result'] == 'W' for m in known) / len(known) * 100 if known else None,
            'metrics': {metric: distribution(metric_value(m, metric) for m in records) for metric in METRICS[1:]}}


def threshold_groups(records, threshold=344):
    if not numeric(threshold) or threshold <= 0:
        raise ValueError('Item-level threshold must be a positive finite number')
    known = [r for r in records if numeric(r.get('PvP item level'))]
    return {'below': sample_summary([r for r in known if r['PvP item level'] < threshold]),
            'at_or_above': sample_summary([r for r in known if r['PvP item level'] >= threshold]),
            'unknown_item_level': len(records) - len(known)}


def prepare_trends(matches, rosters, identities, filters=None, window=20, threshold=344, teammates=()):
    # Validate even when there are no records.
    rolling_results([], window); threshold_groups([], threshold)
    selected = filter_matches(matches, rosters, filters or Filters(), identities)
    grouped = group_rosters(rosters)
    records = [performance(m, grouped.get(match_key(m), [])) for m in selected]
    records.sort(key=chronological_key)
    groups = defaultdict(list)
    for record in records:
        groups[(record['Character'], record['Realm'], record.get('Type') or 'Unknown')].append(record)
    series = []
    for (character, realm, mode), rows in sorted(groups.items()):
        series.append({'label': f'{character}-{realm} · {mode}', 'mode': mode,
                       'records': rows, 'rolling': rolling_results(rows, window),
                       'summary': sample_summary(rows), 'gear': threshold_groups(rows, threshold)})
    names = sorted(set(teammates))
    if any(p not in identities.people or p in (identities.owner_person, 'Unassigned') for p in names):
        raise ValueError('Select known teammates')
    teammates_by_type = []
    for mode in sorted({r.get('Type') or 'Unknown' for r in records}):
        rows = [r for r in records if (r.get('Type') or 'Unknown') == mode]
        def together(row, people):
            return any(has_person(row, grouped.get(match_key(row), []), identities, p) for p in people)
        for label, people in [(p, [p]) for p in names] + ([('Selected teammates (union)', names)] if names else []):
            with_rows = [r for r in rows if together(r, people)]
            without_rows = [r for r in rows if not together(r, people)]
            teammates_by_type.append({'label': label, 'mode': mode, 'records': with_rows,
                                      'rolling': rolling_results(with_rows, window),
                                      'with': sample_summary(with_rows), 'without': sample_summary(without_rows)})
    return {'series': series, 'teammates': teammates_by_type, 'window': window,
            'threshold': threshold, 'matches': len(records),
            'note': 'Types and owner characters stay separate. Full valid-result windows only. Missing values are excluded. Gear groups are associations, not causal estimates.'}

"""Observed-cohort competition ranks, never population-wide WoW rankings."""
from statistics import mean, median
from .metrics import numeric
from .metric_registry import METRICS, VERSION, values

SCOPES = ('My team', 'Opposing team', 'All recorded participants', 'Same class', 'Same specialization', 'Class in my team', 'Spec in my team', 'Class in opposing team', 'Spec in opposing team')


def cohort(rows, scope, reference=None):
    reference = reference or next((r for r in rows if r.get('Is me') == 'Yes'), {})
    pool = []
    for r in rows:
        if scope in ('My team', 'Class in my team', 'Spec in my team') and r.get('Team') != 'Mine': continue
        if scope in ('Opposing team', 'Class in opposing team', 'Spec in opposing team') and r.get('Team') != 'Enemy': continue
        if scope in ('Same class', 'Class in my team', 'Class in opposing team') and (not reference.get('Class') or r.get('Class') != reference.get('Class')): continue
        if scope in ('Same specialization', 'Spec in my team', 'Spec in opposing team') and (not reference.get('Spec') or r.get('Spec') != reference.get('Spec') or r.get('Class') != reference.get('Class')): continue
        pool.append(r)
    return pool


def rank(rows, metric='Damage', scope='All recorded participants', reference=None, ascending=None):
    if metric not in METRICS or scope not in SCOPES:
        raise ValueError('Choose a supported metric and cohort')
    pool = cohort(rows, scope, reference)
    def identity_eligible(r):
        return not (r.get('realm_certainty') == 'inferred' and any(
            other.get('realm_certainty') == 'observed' and other.get('Player','').casefold() == r.get('Player','').casefold()
            and other.get('event_id') == r.get('event_id') for other in pool))
    eligible = [(r, r.get(metric) if r.get('_aggregate_metric') == metric else values(r).get(metric)) for r in pool
                if identity_eligible(r) and numeric(r.get(metric) if r.get('_aggregate_metric') == metric else values(r).get(metric))]
    ascending = not METRICS[metric]['higher_is_better'] if ascending is None else ascending
    samples = [v for _, v in eligible]
    complete = bool(pool) and all(r.get('_cohort_verified_complete') is True for r in rows) and len(samples) == len(pool)
    result = []
    for r, v in eligible:
        better = sum(x < v if ascending else x > v for x in samples)
        worse = sum(x > v if ascending else x < v for x in samples)
        ties = samples.count(v)
        result.append(r | {'Metric': metric, 'Value': v, 'Rank': 1 + better,
             'Eligible': len(samples), 'Excluded': len(pool)-len(samples), 'Cohort': scope,
             'Coverage': 'Verified complete' if complete else 'Rank among observed eligible players',
             'Difference from mean': v - mean(samples), 'Difference from median': v - median(samples),
             'Percentile': 100 * (worse + (ties - 1) / 2) / (len(samples) - 1) if len(samples) > 1 else None})
    return {'metric': METRICS[metric], 'registry_version': VERSION, 'cohort': scope, 'eligible': len(samples),
            'excluded': len(pool)-len(samples), 'unobserved_count': None if not complete else 0,
            'complete': complete, 'rows': sorted(result, key=lambda r: (r['Rank'], str(r.get('Player', '')))),
            'note': 'Archived encounters only. Unknown cohort members cannot be counted; source totals may describe a different snapshot.'}


def historical(rows, metric, mode='Individual Encounters', minimum=1, scope='All recorded participants', reference=None):
    if scope not in SCOPES or minimum < 1: raise ValueError('Choose a supported cohort and positive minimum sample size')
    # A complete individual scoreboard cannot prove a complete historical population.
    rows = [r | {'_cohort_verified_complete': False} for r in cohort(rows, scope, reference)]
    if mode == 'Individual Encounters':
        result = rank(rows, metric)
    else:
        if mode not in ('Player averages', 'Player medians'): raise ValueError('Unknown historical mode')
        grouped = {}
        for r in rows:
            grouped.setdefault(r['player_key'], []).append(r)
        combined = []
        for key, sightings in grouped.items():
            known = [values(r)[metric] for r in sightings if numeric(values(r)[metric])]
            if len(known) < minimum: continue
            combined.append(sightings[0] | {metric: mean(known) if mode == 'Player averages' else median(known), '_aggregate_metric':metric,
                                           'Samples': len(known), 'Encounters': len(sightings)})
        # Aggregated derived rates already have their final units.
        result = rank(combined, metric)
    result.update(mode=mode, minimum=minimum, cohort=scope)
    return result

"""Versioned participant statistics; structural numbers never become rankings."""
from .metrics import numeric

VERSION = '1.3.2'
METRICS = {name: {'name': name, 'source_field': name, 'formula': 'observed value', 'unit': unit,
                  'higher_is_better': higher, 'entity': 'participant', 'required': [name],
                  'match_types': 'verified source applicability', 'missing': 'exclude, never substitute zero'}
           for name, unit, higher in [('Damage', 'damage', True), ('Healing', 'healing', True),
               ('KB', 'kills', True), ('HK', 'kills', True), ('Deaths', 'deaths', False),
               ('Honor', 'honor', True), ('Rating change', 'rating points', True)]}
for name, source, scale in [('Damage per minute', 'Damage', 1), ('Healing per minute', 'Healing', 1), ('Deaths per 10 minutes', 'Deaths', 10)]:
    METRICS[name] = {'name': name, 'source_field': source, 'formula': f'{source} / individual Minutes played * {scale}',
                     'unit': 'per minute' if scale == 1 else 'per 10 minutes', 'higher_is_better': source != 'Deaths',
                     'entity': 'participant', 'required': [source, 'Minutes played > 0'], 'match_types': 'known individual attendance only',
                     'missing': 'withhold without measured attendance'}


def values(row):
    import re
    # These source labels explicitly describe count objectives. Unknown labels
    # remain raw text, rather than guessing their unit or preferred direction.
    labels = {'Bases Assaulted','Bases Defended','Flags Captured','Flags Returned','Carts Controlled','Mines Assaulted','Mines Defended','Rounds Won','Orb Possessions','Victory Points'}
    if row.get('Map') or row.get('Map ID') is not None:
        location = row.get('Map') or 'Map ID '+str(row['Map ID'])
        for segment in str(row.get('Objectives') or '').split(';'):
            label,separator,value = segment.strip().partition('=')
            if label in labels and separator and re.fullmatch(r'\d+',value.strip()):
                name = 'Objective · '+str(location)+' · '+label
                METRICS.setdefault(name, {'name':name,'source_field':'Objectives','formula':'verified source count label '+label,
                                          'unit':'points' if label=='Victory Points' else 'count','higher_is_better':True,'entity':'participant','required':['matching map',label],
                                          'match_types':'map-specific objective','missing':'unknown labels remain raw, absent labels are NULL'})
                row[name] = int(value)
    result = {name: row.get(name) if numeric(row.get(name)) else None for name in METRICS}
    minutes = row.get('Minutes played')
    for name, source, scale in [('Damage per minute', 'Damage', 1), ('Healing per minute', 'Healing', 1), ('Deaths per 10 minutes', 'Deaths', 10)]:
        result[name] = row[source] / minutes * scale if numeric(row.get(source)) and numeric(minutes) and minutes > 0 else None
    return result

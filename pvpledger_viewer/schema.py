MATCH_HEADER = ['Match ID', 'Date', 'Time', 'Character', 'Realm', 'Class', 'Spec', 'PvP item level', 'Equipped item level', 'Map', 'Type', 'Rated', 'Result', 'Duration (s)', 'Minutes played', 'Late join', 'KB', 'HK', 'Deaths', 'Damage', 'Healing', 'Honor (scoreboard)', 'Rating change', 'MMR before', 'MMR after', 'Team deaths', 'Enemy deaths', 'Team damage', 'Enemy damage', 'Team healing', 'Enemy healing', 'Team healers', 'Enemy healers', 'Premade present', 'Premade members', 'My objectives', 'Score detail', 'Alliance score', 'Horde score', 'My team score', 'Enemy team score', 'Honor awarded', 'Conquest awarded', 'Addon version', 'Schema version', 'Attendance ticks']
ROSTER_HEADER = ['Match ID', 'Player', 'Realm', 'Team', 'Class', 'Spec', 'KB', 'HK', 'Deaths', 'Damage', 'Healing', 'Honor', 'Rating change', 'Is me', 'Is premade', 'Objectives', 'Ticks present', 'Ticks total', 'Joined late', 'Left early', 'Schema version']
import csv
import io
import math
import re

MATCH_NUMBERS = set(range(7, 9)) | set(range(13, 15)) | set(range(16, 34)) | set(range(37, 43)) | {44, 45}
ROSTER_NUMBERS = set(range(6, 13)) | set(range(16, 21))


def clean(text):
    return re.sub(r'\s+', ' ', re.sub(r'\|c[0-9a-fA-F]{8}|\|r', '', text.replace('|n', ' '))).strip()


def parse_row(raw, kind, diagnostics):
    header = MATCH_HEADER if kind == 'match' else ROSTER_HEADER
    numbers = MATCH_NUMBERS if kind == 'match' else ROSTER_NUMBERS
    try:
        rows = list(csv.reader(io.StringIO(raw), strict=True))
        if len(rows) != 1:
            raise ValueError('Expected one CSV record')
        values = rows[0]
    except (csv.Error, ValueError, TypeError) as exc:
        diagnostics.append({'code': 'invalid_csv', 'kind': kind, 'raw': raw, 'detail': str(exc)})
        return None
    schema5 = kind == 'match' and len(values) >= 47 and values[44].strip() == '5'
    trailing = values[47:] if schema5 else []
    epoch = values[46] if schema5 else None
    if schema5:
        values = values[:46]
    if len(values) > len(header):
        diagnostics.append({'code': 'extra_columns', 'kind': kind, 'raw': raw, 'count': len(values)})
        return None
    original = len(values)
    if original not in ((37, 44, 46) if kind == 'match' else (16, 21)):
        diagnostics.append({'code': 'short_row', 'kind': kind, 'raw': raw, 'count': original})
    values += [''] * (len(header) - len(values))
    data = {}
    for i, (key, value) in enumerate(zip(header, values)):
        value = clean(value)
        if i in numbers and value:
            try:
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError('Non-finite number')
                value = int(number) if number.is_integer() else number
            except ValueError:
                diagnostics.append({'code': 'invalid_number', 'field': key, 'raw': raw})
                value = None
        data[key] = value if value != '' else None
    if data['Schema version'] is None:
        data['Schema version'] = (1 if original <= 37 else 2) if kind == 'match' else 1
    if data['Schema version'] not in (1, 2, 3, 4, 5):
        diagnostics.append({'code': 'unknown_schema', 'raw': raw, 'version': data['Schema version']})
    data['_raw'] = raw
    if schema5:
        try:
            data['Epoch'] = int(epoch) if epoch else None
        except ValueError:
            data['Epoch'] = None
            diagnostics.append({'code': 'invalid_number', 'field': 'Epoch', 'raw': raw})
        data['_unknown_trailing_fields'] = trailing
    return data

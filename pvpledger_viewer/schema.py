MATCH_HEADER = ['Match ID', 'Date', 'Time', 'Character', 'Realm', 'Class', 'Spec', 'PvP item level', 'Equipped item level', 'Map', 'Type', 'Rated', 'Result', 'Duration (s)', 'Minutes played', 'Late join', 'KB', 'HK', 'Deaths', 'Damage', 'Healing', 'Honor (scoreboard)', 'Rating change', 'MMR before', 'MMR after', 'Team deaths', 'Enemy deaths', 'Team damage', 'Enemy damage', 'Team healing', 'Enemy healing', 'Team healers', 'Enemy healers', 'Premade present', 'Premade members', 'My objectives', 'Score detail', 'Alliance score', 'Horde score', 'My team score', 'Enemy team score', 'Honor awarded', 'Conquest awarded', 'Addon version', 'Schema version', 'Attendance ticks']
ROSTER_HEADER = ['Match ID', 'Player', 'Realm', 'Team', 'Class', 'Spec', 'KB', 'HK', 'Deaths', 'Damage', 'Healing', 'Honor', 'Rating change', 'Is me', 'Is premade', 'Objectives', 'Ticks present', 'Ticks total', 'Joined late', 'Left early', 'Schema version']
# Verified PvP Ledger 1.3.4 header; schemas 6 and 7 share this layout.
CURRENT_MATCH_HEADER = MATCH_HEADER + ['Epoch', 'Queue type']

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
    # The schema marker remains in column 45 in the verified 1.3.1 through 1.3.4
    # sources. Epoch is column 47; schema 6 adds Queue type in column 48.
    # Select extensions by the explicit marker, never by row length alone.
    version = values[44].strip() if kind == 'match' and len(values) > 44 else None
    extended = version in ('5', '6', '7')
    width = 47 if version == '5' else 48
    original_count = len(values)
    trailing = values[width:] if extended else []
    epoch = values[46] if extended and len(values) > 46 else None
    queue_type = values[47] if extended and len(values) > 47 else None
    if extended:
        values = values[:46]
        if original_count < width:
            diagnostics.append({'code': 'short_row', 'kind': kind, 'raw': raw, 'count': original_count})
    elif kind == 'roster' and len(values) >= 21 and values[20].strip() in ('6', '7'):
        trailing = values[21:]
        values = values[:21]
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
    if data['Schema version'] not in (1, 2, 3, 4, 5, 6, 7):
        diagnostics.append({'code': 'unknown_schema', 'raw': raw, 'version': data['Schema version']})
    data['_raw'] = raw
    if extended:
        try:
            data['Epoch'] = int(epoch) if epoch else None
        except ValueError:
            data['Epoch'] = None
            diagnostics.append({'code': 'invalid_number', 'field': 'Epoch', 'raw': raw})
        if version in ('6', '7'):
            data['Queue type'] = clean(queue_type) if queue_type else None
        data['_unknown_trailing_fields'] = trailing
    elif trailing:
        data['_unknown_trailing_fields'] = trailing
    return data

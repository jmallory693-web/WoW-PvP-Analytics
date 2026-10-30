"""Validated, atomic desktop preferences, separate from source and archive data."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import tempfile
from .archive import default_home, safe_destination
from .metrics import Filters

THEME_NAMES = ('Warband', 'Classic')

DEFAULTS = {'geometry': '1280x720', 'wow_root': '', 'export_dir': '', 'report_limit': 20,
            'theme': 'Warband',
            'view': 'Home', 'filters': asdict(Filters()), 'trend_window': 20, 'trend_threshold': 344,
            'trend_metric': 'Win rate', 'trend_teammates': [], 'source_timezone': 'UTC',
            'source_locations': [], 'source_selection_explicit': False,
            'sync_enabled': True, 'sync_interval': 300, 'setup_complete': False,
            'date_mode': 'All Time', 'advanced_comparison': {}, 'trend_comparison_mode': 'Dashboard'}
VIEWS = ('Home', 'Match History', 'Character Comparison', 'Allies', 'Diagnostics', 'Trends', 'Duplicate Review', 'All Players', 'Archive Status', 'Rated PvP')


def validate_settings(data):
    from copy import deepcopy
    result = deepcopy(DEFAULTS) | data
    if not isinstance(result['theme'], str) or result['theme'] not in THEME_NAMES:
        result['theme'] = 'Warband'
    if not isinstance(result['sync_enabled'], bool):
        raise ValueError('Automatic synchronization must be enabled or disabled')
    if type(result['sync_interval']) is not int or result['sync_interval'] < 30:
        raise ValueError('Synchronization interval must be at least 30 seconds')
    if not isinstance(result['source_locations'], list) or any(not isinstance(p,str) or not p.strip() for p in result['source_locations']):
        raise ValueError('SavedVariables locations must be a list of nonempty paths')
    if result['date_mode'] not in ('All Time', 'Single Day', 'Date Range', 'Last 7 Days', 'Last 30 Days', 'This Month'):
        raise ValueError('Unknown date mode')
    if not isinstance(result['advanced_comparison'], dict):
        raise ValueError('Comparison preferences must be an object')
    if result['trend_comparison_mode'] not in ('Dashboard', 'Me vs Friends', 'My Characters'):
        raise ValueError('Unknown Trends comparison mode')
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(result['source_timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise ValueError('Source timezone must be a valid IANA timezone, e.g. America/Los_Angeles') from exc
    from .trends import METRICS, rolling_results, threshold_groups
    rolling_results([], result['trend_window'])
    threshold_groups([], result['trend_threshold'])
    if result['trend_metric'] not in METRICS:
        raise ValueError('Invalid saved trend metric')
    if not isinstance(result['trend_teammates'], list) or any(not isinstance(p, str) for p in result['trend_teammates']):
        raise ValueError('Trend teammates must be a list of names')
    if not re.fullmatch(r'\d{3,5}x\d{3,5}(?:[+-]\d+[+-]\d+)?', str(result['geometry'])):
        raise ValueError('Invalid saved window geometry')
    if not isinstance(result['report_limit'], int) or isinstance(result['report_limit'], bool) or result['report_limit'] < 1:
        raise ValueError('Report match count must be a positive integer')
    for field in ('wow_root', 'export_dir'):
        if not isinstance(result[field], str):
            raise ValueError(f'{field} must be a path string')
    if result['view'] not in VIEWS:
        result['view'] = 'Home'
    raw = result.get('filters', {})
    if not isinstance(raw, dict):
        raise ValueError('Saved filters must be an object')
    filters = asdict(Filters(**{k: raw.get(k) for k in Filters.__dataclass_fields__}))
    for key, value in filters.items():
        if key == 'premade':
            if value is not None and not isinstance(value, bool):
                raise ValueError('Premade filter must be true, false, or null')
        elif value is not None and not isinstance(value, str):
            raise ValueError(f'{key} filter must be text')
    from datetime import date
    start, end = filters['start'], filters['end']
    if start:
        date.fromisoformat(start)
    if end:
        date.fromisoformat(end)
    if start and end and start > end:
        raise ValueError('Start date must not follow end date')
    result['filters'] = filters
    if 'date_mode' not in data and (start or end):
        result['date_mode'] = 'Date Range'
    return result


class SettingsStore:
    def __init__(self, path=None):
        self.path = safe_destination(path or default_home() / 'settings.json')
        self.error = None

    def load(self):
        if not self.path.exists():
            # Older archives used this recording-time assumption before a
            # preference was stored. Preserve their chronology on reopen.
            legacy = (self.path.parent/'archive.sqlite').exists()
            return validate_settings({'source_timezone':'America/Los_Angeles'} if legacy else {})
        try:
            document = json.loads(self.path.read_text(encoding='utf-8-sig'))
            if 'source_timezone' not in document:
                document = {'source_timezone':'America/Los_Angeles'} | document
            return validate_settings(document)
        except (ValueError, TypeError, OSError) as exc:
            self.error = str(exc)
            return validate_settings({})

    def save(self, data):
        data = validate_settings(data)
        from .profile import backup
        backup(self.path.parent)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.error and self.path.exists():
            # Keep invalid user preferences available for troubleshooting.
            backup = self.path.with_name('settings.invalid.json')
            if not backup.exists():
                backup.write_bytes(self.path.read_bytes())
        descriptor, temporary = tempfile.mkstemp(prefix='settings-', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf8') as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.flush(); os.fsync(output.fileno())
            os.replace(temporary, safe_destination(self.path))
            self.error = None
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
        return data

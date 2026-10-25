"""Archive calendar calculations, independent of Tk and system timezone."""
import calendar
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .metrics import match_date


def localize(matches, zone):
    tz = ZoneInfo(zone)
    result = []
    for match in matches:
        m = match.copy()
        if m.get('_timestamp_utc') is not None:
            local = datetime.fromtimestamp(m['_timestamp_utc'], timezone.utc).astimezone(tz)
            m.update(Date=local.date().isoformat(), Time=local.strftime('%H:%M'))
        result.append(m)
    return result


def availability(matches):
    return dict(sorted(Counter(str(d) for m in matches if (d := match_date(m)) is not None).items()))


def shift_month(year, month, offset):
    absolute = year * 12 + month - 1 + offset
    y, m = divmod(absolute, 12)
    if not 1 <= y <= 9999:
        raise ValueError('Calendar year must be from 1 to 9999')
    return y, m + 1


def month_days(year, month):
    return calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)


def preset(name, today=None, zone='America/Los_Angeles'):
    today = today or datetime.now(ZoneInfo(zone)).date()
    if name == 'All Time':
        return None, None
    if name == 'Last 7 Days':
        first = today - timedelta(days=6)
    elif name == 'Last 30 Days':
        first = today - timedelta(days=29)
    elif name == 'This Month':
        first = today.replace(day=1)
    else:
        raise ValueError('Unknown date preset')
    return first.isoformat(), today.isoformat()

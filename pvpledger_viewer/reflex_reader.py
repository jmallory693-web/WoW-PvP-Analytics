"""REFlex 3501 table adapter. Semantics verified against the installed addon source.

Positional indexes below come from REFlexFunctions.lua DumpCSV/GetPlayerData,
GetBGComposition and GetPlayerWin; unknown positions stay in the raw record.
"""
from datetime import datetime, timezone
import hashlib
import json
from zoneinfo import ZoneInfo
from .schema import MATCH_HEADER, ROSTER_HEADER, clean
from .lua_reader import sequence
from .metrics import numeric

DEFAULT_ZONE = 'America/Los_Angeles'


def at(table, index):
    if isinstance(table, dict):
        return table.get(index)
    return table[index - 1] if isinstance(table, list) and len(table) >= index else None


def number(value):
    return value if numeric(value) else None


def capture_time(value, zone=DEFAULT_ZONE, version=3501):
    """REFlex >=260 encodes UTC wall time through Lua's *local* time(table).

    Undo that local encoding, then interpret the recovered wall time as UTC.
    The timezone must be that of the computer that wrote the SavedVariables.
    """
    if not numeric(value):
        return None
    local = datetime.fromtimestamp(value, ZoneInfo(zone))
    return local.replace(tzinfo=timezone.utc) if version >= 260 else datetime.fromtimestamp(value, timezone.utc)


def pvp_time(match, zone=DEFAULT_ZONE):
    try:
        stamp = datetime.strptime(match['Match ID'], '%Y%m%d-%H%M%S')
        first = stamp.replace(tzinfo=ZoneInfo(zone), fold=0)
        if first.utcoffset() != stamp.replace(tzinfo=ZoneInfo(zone), fold=1).utcoffset():
            return None  # DST fold/gap is not a unique instant: review instead.
        return first.timestamp()
    except (ValueError, KeyError):
        return None


def parse_reflex(document, character=None, realm=None, zone=DEFAULT_ZONE):
    if not isinstance(document.get('REFlexDatabase'), (dict, list)):
        raise ValueError('REFlexDatabase must be a Lua table')
    ZoneInfo(zone)
    matches, rosters, issues, raw_records = {}, {}, [], {}
    for position, raw in enumerate(sequence(document['REFlexDatabase']), 1):
        if not isinstance(raw, dict):
            issues.append({'code': 'invalid_reflex_record', 'position': position}); continue
        players = raw.get('Players', {})
        me = at(players, raw.get('PlayerNum')) if isinstance(raw.get('PlayerNum'), int) else None
        if not isinstance(me, (dict, list)):
            issues.append({'code': 'missing_reflex_player', 'position': position}); me = {}
        owner_name = clean(str(at(me, 1) or '')).partition('-')[0]
        owner = character or owner_name
        owner_realm = realm or (str(at(me, 1)).partition('-')[2] or None)
        if not owner or not owner_realm or (owner_name and character and owner_name.casefold() != character.casefold()):
            issues.append({'code': 'missing_or_conflicting_reflex_owner', 'position': position,
                           'detail': 'Import with character/realm context; raw record retained in source snapshot.'}); continue
        version = number(raw.get('Version'))
        known_version = version in (3500, 3501)
        if not known_version:
            issues.append({'code': 'unverified_reflex_version', 'position': position, 'version': version,
                           'detail': 'Positional statistics withheld; raw table retained.'})
        try:
            utc = capture_time(raw.get('Time'), zone, version or 3501)
        except (ValueError, OverflowError, OSError):
            utc = None
        if utc is None:
            issues.append({'code': 'invalid_reflex_timestamp', 'position': position})
        local = utc.astimezone(ZoneInfo(zone)) if utc else None
        # Stable across array reordering/pruning; collisions with differing payloads
        # in one file get distinct suffixes and a diagnostic, never discarded.
        identity = [raw.get(k) for k in ('Time', 'Map', 'isArena', 'isSoloShuffle', 'isRated')]
        if utc is None:
            # Without a usable capture instant, distinct incomplete records
            # cannot safely share an identity across separate imports.
            identity.append(raw)
        original_id = 'REFlex-' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
        key = (owner, owner_realm, original_id)
        serialized = json.dumps(raw, ensure_ascii=False, sort_keys=True)
        if key in matches:
            if raw_records[key] == raw:
                issues.append({'code': 'duplicate_reflex_record', 'position': position}); continue
            original_id += '-' + hashlib.sha256(serialized.encode()).hexdigest()[:12]
            key = (owner, owner_realm, original_id)
            issues.append({'code': 'reflex_identity_collision', 'position': position})
        arena = raw.get('isArena')
        shuffle = raw.get('isSoloShuffle') is True
        mode = ('Solo Shuffle' if shuffle else ('Rated arena' if raw.get('isRated') is True else 'Arena skirmish')) if arena is True else ('Brawl' if raw.get('isBrawl') is True else 'Battleground') if arena is False else None
        side, winner = number(raw.get('PlayerSide')), number(raw.get('Winner'))
        outcome = ('W' if winner == side else 'L') if not shuffle and side in (0, 1) and winner in (0, 1) else None
        m = dict.fromkeys(MATCH_HEADER)
        m.update({'Match ID': original_id, 'Character': owner, 'Realm': owner_realm,
                  'Date': local.strftime('%Y-%m-%d') if local else None,
                  'Time': local.strftime('%H:%M') if local else None,
                  'Type': mode, 'Rated': 'Yes' if raw.get('isRated') is True else 'No' if raw.get('isRated') is False else None,
                  'Result': outcome, 'Duration (s)': number(raw.get('Duration')),
                  'Map ID': number(raw.get('Map')), 'Player count': number(raw.get('PlayersNum')),
                  '_timestamp_utc': utc.timestamp() if utc else None, '_source_timezone': zone,
                  '_raw': None, '_partial': outcome is None or utc is None or raw.get('Duration') is None,
                  '_addon': 'REFlex', '_original_id': original_id, '_reflex_version': version,
                  '_raw_reflex': raw, '_is_arena': arena, '_is_solo_shuffle': shuffle})
        rows = []
        for index, player in enumerate(sequence(players), 1):
            if not isinstance(player, (dict, list)) or not at(player, 1):
                issues.append({'code': 'invalid_reflex_player_row', 'position': position, 'player': index}); continue
            name, _, world = clean(str(at(player, 1))).partition('-')
            world = world or owner_realm
            row = dict.fromkeys(ROSTER_HEADER)
            faction = at(player, 6)
            row.update({'Match ID': original_id, 'Player': name, 'Realm': world,
                        'Team': ('Mine' if faction == side else 'Enemy') if faction in (0, 1) and side in (0, 1) and not shuffle else None,
                        'Class': at(player, 8) if known_version else None, 'Spec': at(player, 16) if known_version else None,
                        'Is me': 'Yes' if index == raw.get('PlayerNum') else 'No', 'Is premade': None,
                        '_raw': None, '_raw_reflex_player': player, '_addon': 'REFlex'})
            if known_version:
                for field, slot in [('KB', 2), ('HK', 3), ('Deaths', 4), ('Honor', 5), ('Damage', 10), ('Healing', 11), ('Rating change', 13)]:
                    row[field] = number(at(player, slot))
                # Arena deaths are not reliable in the legacy scoreboard API;
                # retain its raw zeros without changing established death metrics.
                if arena:
                    row['Deaths'] = None
            rows.append(row)
            if index == raw.get('PlayerNum'):
                for field in ('Class', 'Spec', 'KB', 'HK', 'Deaths', 'Damage', 'Healing', 'Rating change'):
                    m[field] = row.get(field)
                m['Honor (scoreboard)'] = row.get('Honor')
        m['_scoreboard_incomplete'] = not numeric(m['Player count']) or len(rows) != m['Player count'] or shuffle
        for row in rows:
            row['_scoreboard_incomplete'] = m['_scoreboard_incomplete']
        if m['_scoreboard_incomplete']:
            issues.append({'code': 'reflex_incomplete_scoreboard', 'id': original_id, 'retained_players': len(rows), 'reported_players': m['Player count']})
        if raw.get('Hidden'):
            issues.append({'code': 'reflex_hidden_record_preserved', 'id': original_id})
        if any(k not in raw for k in ('PlayerSide', 'Winner', 'isArena')):
            issues.append({'code': 'incomplete_reflex_metadata', 'id': original_id})
        matches[key], rosters[key], raw_records[key] = m, rows, raw
    return matches, rosters, {}, issues

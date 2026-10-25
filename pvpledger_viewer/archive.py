"""Transactional, append-preserving SQLite archive and immutable snapshots."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from copy import deepcopy
from .lua_reader import loads, sequence
from .normalize import normalize


def default_home():
    original = Path(os.environ.get('APPDATA', Path.home() / 'AppData/Roaming')) / 'PvPLedgerViewer'
    pointer = original / 'archive-location.json'
    if pointer.exists():
        selected = safe_destination(json.loads(pointer.read_text(encoding='utf8'))['path'])
        if not (selected / 'archive.sqlite').is_file() or (selected / 'COPY_INCOMPLETE').exists():
            raise ValueError('Configured archive is unavailable; original archive remains at ' + str(original))
        return selected
    return original


def set_default_home(path):
    original = Path(os.environ.get('APPDATA', Path.home() / 'AppData/Roaming')) / 'PvPLedgerViewer'
    from .profile import backup
    backup(original)
    selected = safe_destination(path)
    if not (selected / 'archive.sqlite').exists() or (selected / 'COPY_INCOMPLETE').exists():
        raise ValueError('Archive destination has not been verified')
    safe_destination(original).mkdir(parents=True, exist_ok=True)
    temporary = original / 'archive-location.tmp'
    temporary.write_text(json.dumps({'path':str(selected)}),encoding='utf8')
    temporary.replace(original / 'archive-location.json')


def safe_destination(path):
    path = Path(path).resolve()
    if any(part.lower() in ('world of warcraft', '_retail_', 'wtf') for part in path.parts):
        raise ValueError('Archive and snapshots must be outside the WoW directory')
    return path


class Archive:
    def __init__(self, home=None):
        self.home = safe_destination(home or default_home())
        self._existing_database = (self.home / 'archive.sqlite').exists()
        self.home.mkdir(parents=True, exist_ok=True)
        from .profile import backup
        backup(self.home)
        from .upgrade import ensure_profile_backup
        ensure_profile_backup(self.home)
        safe_destination(self.home / 'snapshots').mkdir(exist_ok=True)
        self.db = sqlite3.connect(safe_destination(self.home / 'archive.sqlite'))
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY, source TEXT NOT NULL, started TEXT NOT NULL,
            sha256 TEXT, snapshot TEXT, status TEXT NOT NULL, db_version TEXT,
            diagnostics TEXT NOT NULL DEFAULT '[]', matches_added INTEGER DEFAULT 0,
            roster_added INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS matches (
            character TEXT NOT NULL, realm TEXT NOT NULL, match_id TEXT NOT NULL,
            partial INTEGER NOT NULL, data TEXT NOT NULL, raw_csv TEXT,
            import_id INTEGER REFERENCES imports(id),
            PRIMARY KEY(character, realm, match_id));
        CREATE TABLE IF NOT EXISTS rosters (
            character TEXT NOT NULL, realm TEXT NOT NULL, match_id TEXT NOT NULL,
            player TEXT NOT NULL, player_realm TEXT NOT NULL,
            data TEXT NOT NULL, raw_csv TEXT, import_id INTEGER REFERENCES imports(id),
            PRIMARY KEY(character, realm, match_id, player, player_realm),
            FOREIGN KEY(character, realm, match_id) REFERENCES matches(character, realm, match_id));
        CREATE TABLE IF NOT EXISTS overrides (
            character TEXT NOT NULL, realm TEXT NOT NULL, match_id TEXT NOT NULL,
            field TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY(character, realm, match_id, field),
            FOREIGN KEY(character, realm, match_id) REFERENCES matches(character, realm, match_id));
        CREATE TABLE IF NOT EXISTS snapshot_aliases (
            character TEXT NOT NULL, realm TEXT NOT NULL, snapshot_id TEXT NOT NULL,
            match_id TEXT NOT NULL, PRIMARY KEY(character, realm, snapshot_id));
        CREATE TABLE IF NOT EXISTS raw_rows (
            import_id INTEGER REFERENCES imports(id), kind TEXT, position INTEGER, raw TEXT,
            PRIMARY KEY(import_id, kind, position));
        ''')
        # Opening an existing archive for analytics must not rewrite its header.
        if self.db.execute('PRAGMA user_version').fetchone()[0] == 0:
            self.db.execute('PRAGMA user_version=1')
        from .dual_archive import migrate
        migrate(self)

    def close(self):
        self.db.close()

    def totals(self):
        from .dual_archive import project
        matches, rows = project(self)
        partial = sum(bool(m['_partial']) for m in matches)
        result = {'total': len(matches), 'complete': len(matches) - partial, 'partial': partial, 'rosters': len(rows)}
        results = [m.get('Result') for m in matches if not m['_partial']]
        result.update(wins=results.count('W'), losses=results.count('L'))
        return result

    def read_matches(self):
        from .dual_archive import project
        return deepcopy(project(self)[0])

    def set_override(self, key, field, value):
        from .schema import MATCH_HEADER
        if field not in MATCH_HEADER or field in ('Character', 'Realm', 'Match ID'):
            raise ValueError('Only non-identity match fields may be overridden')
        with self.db:
            self.db.execute('INSERT INTO overrides VALUES (?,?,?,?,?) ON CONFLICT(character,realm,match_id,field) DO UPDATE SET value=excluded.value', (*key, field, json.dumps(value, ensure_ascii=False)))

    def read_rosters(self):
        """Return normalized roster payloads with canonical archive ownership.

        Snapshot IDs in raw CSV remain unchanged; joins use the logical match ID.
        """
        from .dual_archive import project
        return deepcopy(project(self)[1])

    def source_totals(self):
        from .dual_archive import project, review
        matches, _ = project(self)
        result = {'PvP Ledger-only': sum(m['Source'] == 'PvP Ledger' for m in matches),
                'REFlex-only': sum(m['Source'] == 'REFlex' for m in matches),
                'Both': sum(m['Source'] == 'Both' for m in matches),
                'ambiguous_pairs': sum(r['decision'] == 'ambiguous' for r in review(self)),
                'observations': self.db.execute('SELECT count(*) FROM observations').fetchone()[0],
                'conflicting_matches': sum(bool(m['_conflicts']) for m in matches)}
        excel=sum(m['Source']=='Excel historical import' for m in matches)
        if excel:result['Excel historical import']=excel
        supplemented=sum(bool(m.get('_excel_supplements')) and not m.get('_excel_historical') for m in matches)
        if supplemented:result['Manually supplemented matches']=supplemented
        return result

    def duplicate_review(self):
        from .dual_archive import review
        return review(self)

    def decide_link(self, left, right, decision):
        from .dual_archive import link, components, records
        with self.db:
            if decision == 'unlink':
                groups = components(self, records(self))
                group = next((g for g in groups if int(left) in [r['id'] for r in g]), [])
                for item in group:
                    if item['id'] != int(left):
                        link(self, int(left), item['id'], 'separate', 'User unlinked observation', True)
                return
            link(self, left, right, decision, 'User decision', True)

    def diagnostics(self, import_id=None):
        sql = 'SELECT * FROM imports' + (' WHERE id=?' if import_id is not None else '') + ' ORDER BY id'
        return [dict(r) | {'diagnostics': json.loads(r['diagnostics'])} for r in self.db.execute(sql, (import_id,) if import_id is not None else ())]

    def set_overrides(self, key, values):
        """Validate identities/fields, then save a metadata edit atomically."""
        from .schema import MATCH_HEADER
        if any(f not in MATCH_HEADER or f in ('Character', 'Realm', 'Match ID') for f in values):
            raise ValueError('Only non-identity match fields may be overridden')
        with self.db:
            for field, value in values.items():
                self.db.execute('INSERT INTO overrides VALUES (?,?,?,?,?) ON CONFLICT(character,realm,match_id,field) DO UPDATE SET value=excluded.value', (*key, field, json.dumps(value, ensure_ascii=False)))

    def read_traces(self, limit=500):
        rows = self.db.execute('''SELECT r.raw, i.source, i.started FROM raw_rows r
            JOIN imports i ON i.id=r.import_id WHERE r.kind='trace'
            AND i.id=(SELECT max(j.id) FROM imports j WHERE j.source=i.source AND j.status='ok')
            ORDER BY i.id DESC,r.position DESC LIMIT ?''', (limit,))
        return [dict(r) for r in rows]

    def source_game_roots(self):
        """Recognize custom installation names from previously imported WTF paths."""
        roots = set()
        for row in self.db.execute('SELECT DISTINCT source FROM imports'):
            for parent in Path(row[0]).parents:
                if parent.name.lower() == 'wtf':
                    branch = parent.parent
                    roots.add(branch.parent if branch.name.startswith('_') else branch)
                    break
        return sorted(roots)

    def import_file(self, source, character=None, realm=None, source_timezone=None, raw_bytes=None):
        source = Path(source).resolve()
        if source.suffix.lower() == '.bak':
            raise ValueError('Backup files are not import sources')
        started = datetime.now(timezone.utc).isoformat()
        with self.db:
            import_id = self.db.execute('INSERT INTO imports(source,started,status) VALUES (?,?,?)', (str(source), started, 'started')).lastrowid
        diagnostics = []
        document = None
        for attempt in range(2):
            try:
                from .sync import stable_read
                raw = raw_bytes if raw_bytes is not None else stable_read(source)[0]
                snapshot = safe_destination(self.home / 'snapshots' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex + '.lua'))
                digest = hashlib.sha256(raw).hexdigest()
                prior = self.db.execute('SELECT snapshot FROM imports WHERE sha256=? AND id<>? AND snapshot IS NOT NULL ORDER BY id DESC', (digest, import_id)).fetchall()
                reused = next((Path(r[0]) for r in prior if Path(r[0]).is_file() and hashlib.sha256(Path(r[0]).read_bytes()).hexdigest() == digest), None)
                if reused:
                    snapshot = reused
                else:
                    temporary = snapshot.with_suffix('.tmp')
                    with temporary.open('xb') as out:
                        out.write(raw); out.flush(); os.fsync(out.fileno())
                    temporary.replace(snapshot)
                with self.db:
                    self.db.execute('UPDATE imports SET sha256=?,snapshot=? WHERE id=?', (digest, str(snapshot), import_id))
                document = loads(snapshot.read_text(encoding='utf-8-sig'))
                break
            except (OSError, ValueError, RecursionError) as exc:
                diagnostics.append({'code': 'read_or_parse_error', 'attempt': attempt + 1, 'detail': str(exc)})
        if document is None:
            with self.db:
                self.db.execute('UPDATE imports SET status=?,diagnostics=? WHERE id=?', ('failed', json.dumps(diagnostics), import_id))
            return {'import_id': import_id, 'status': 'failed', 'matches_added': 0, 'roster_added': 0, 'diagnostics': diagnostics}
        if source.parent.name == 'SavedVariables' and source.parent.parent.parent.name != 'Account':
            # Only infer character context from the actual WTF layout.
            if any(p.lower() == 'account' for p in source.parts):
                character = character or source.parent.parent.name
                realm = realm or source.parent.parent.parent.name
        try:
            from .dual_archive import observe, correlate
            from .reflex_reader import parse_reflex, DEFAULT_ZONE, at
            source_timezone = source_timezone or DEFAULT_ZONE
            addon = 'REFlex' if 'REFlexDatabase' in document else 'PvP Ledger'
            if addon == 'REFlex':
                # A loose export can safely reuse one uniquely archived realm.
                owners = {(r[0], r[1]) for r in self.db.execute('SELECT DISTINCT character,realm FROM matches')}
                if not realm:
                    names = {str(at(at(r.get('Players', {}), r.get('PlayerNum')), 1) or '').partition('-')[0]
                             for r in sequence(document['REFlexDatabase']) if isinstance(r, dict) and isinstance(r.get('PlayerNum'), int)}
                    candidates = {(c, w) for c, w in owners if c in names and (not character or c == character)}
                    if len(candidates) == 1:
                        character, realm = next(iter(candidates))
                        diagnostics.append({'code': 'reflex_owner_from_unique_archive', 'character': character, 'realm': realm})
                matches, rosters, aliases, issues = parse_reflex(document, character, realm, source_timezone)
            else:
                matches, rosters, aliases, issues = normalize(document, character, realm)
                from .reflex_reader import pvp_time
                for match in matches.values():
                    match['_source_timezone'] = source_timezone
                    match['_timestamp_utc'] = match.get('Epoch') if isinstance(match.get('Epoch'), (int, float)) and match['Epoch'] > 0 else pvp_time(match, source_timezone)
            diagnostics.extend(issues)
            db = document.get('PvPLedgerDB', {})
            if not document.keys() & {'PvPLedgerDB', 'PvPLedgerAccountDB', 'REFlexDatabase'}:
                raise ValueError('No recognized PvP Ledger or REFlex database assignment')
            before = self.totals()
            sources_before = self.source_totals()
            recognized = observations_added = 0
            with self.db:
                if addon == 'REFlex':
                    for position, raw_record in enumerate(sequence(document['REFlexDatabase'])):
                        self.db.execute('INSERT INTO raw_rows VALUES (?,?,?,?)', (import_id, 'REFlex', position, json.dumps(raw_record, ensure_ascii=False)))
                for kind in ('matchCSV', 'rosterCSV', 'trace'):
                    for position, line in enumerate(sequence(db.get(kind))):
                        self.db.execute('INSERT INTO raw_rows VALUES (?,?,?,?)', (import_id, kind, position, line if isinstance(line, str) else json.dumps(line)))
                for key, m in matches.items():
                    related = [k for k, v in aliases.items() if v == key] or [key]
                    existing = {r[0] for k in related for r in self.db.execute('SELECT match_id FROM snapshot_aliases WHERE character=? AND realm=? AND snapshot_id=?', k)}
                    if not existing and m['_partial']:
                        # A later import can contain only a previously unseen ID
                        # from the same scoreboard burst.
                        try:
                            stamp = datetime.strptime(key[2], '%Y%m%d-%H%M%S')
                            for archived in self.db.execute('SELECT match_id FROM matches WHERE character=? AND realm=? AND partial=1', key[:2]):
                                try:
                                    delta = abs((stamp - datetime.strptime(archived[0], '%Y%m%d-%H%M%S')).total_seconds())
                                    if delta <= 60:
                                        existing.add(archived[0])
                                except ValueError:
                                    pass
                        except ValueError:
                            pass
                    if len(existing) > 1:
                        raise ValueError('Conflicting archived snapshot groups; review required')
                    target = (*key[:2], next(iter(existing))) if existing else key
                    previous = self.db.execute('SELECT partial,data FROM matches WHERE character=? AND realm=? AND match_id=?', target).fetchone()
                    stale = False
                    if previous and previous['partial'] and m['_partial']:
                        old = json.loads(previous['data'])
                        stale = (m.get('_snapshot_count', 0), m.get('_snapshot', '')) < (old.get('_snapshot_count', 0), old.get('_snapshot', ''))
                    # A later partial import must never degrade an archived complete record.
                    if not stale and (not previous or previous['partial'] or not m['_partial']):
                        m['Match ID'] = target[2]
                        self.db.execute('INSERT INTO matches VALUES (?,?,?,?,?,?,?) ON CONFLICT(character,realm,match_id) DO UPDATE SET partial=excluded.partial,data=excluded.data,raw_csv=excluded.raw_csv,import_id=excluded.import_id', (*target, int(m['_partial']), json.dumps(m, ensure_ascii=False), m['_raw'], import_id))
                        for r in rosters[key]:
                            self.db.execute('INSERT INTO rosters VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(character,realm,match_id,player,player_realm) DO UPDATE SET data=excluded.data,raw_csv=excluded.raw_csv,import_id=excluded.import_id', (*target, r['Player'], r['Realm'] or '', json.dumps(r, ensure_ascii=False), r['_raw'], import_id))
                    for alias in related:
                        self.db.execute('INSERT INTO snapshot_aliases VALUES (?,?,?,?) ON CONFLICT(character,realm,snapshot_id) DO UPDATE SET match_id=excluded.match_id', (*alias, target[2]))
                    # Store immutable incoming observations even when an older
                    # snapshot cannot replace the richer current base record.
                    _, fresh, _ = observe(self, addon, target, m, rosters[key], m.get('_raw_reflex', m.get('_raw')), import_id, source)
                    observations_added += int(fresh)
                    recognized += int(not fresh)
                correlate(self, source_timezone)
                after = self.totals()
                added, roster_added = max(0, after['total'] - before['total']), max(0, after['rosters'] - before['rosters'])
                source_after = self.source_totals()
                self.db.execute('UPDATE imports SET status=?,db_version=?,diagnostics=?,matches_added=?,roster_added=? WHERE id=?', ('ok', str(db.get('version')), json.dumps(diagnostics, ensure_ascii=False), added, roster_added, import_id))
        except (ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            diagnostics.append({'code': 'import_error', 'detail': str(exc)})
            with self.db:
                self.db.execute('UPDATE imports SET status=?,diagnostics=? WHERE id=?', ('failed', json.dumps(diagnostics), import_id))
            return {'import_id': import_id, 'status': 'failed', 'matches_added': 0, 'roster_added': 0, 'diagnostics': diagnostics}
        return {'import_id': import_id, 'status': 'ok', 'matches_added': added, 'roster_added': roster_added, 'diagnostics': diagnostics,
                'observations_added': observations_added, 'observations_recognized': recognized,
                'consolidated': max(0, source_after['Both'] - sources_before['Both']),
                'ambiguous': source_after['ambiguous_pairs'], 'source_addon': addon}

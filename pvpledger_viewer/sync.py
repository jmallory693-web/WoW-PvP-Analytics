"""Non-overlapping, content-addressed, stable-file synchronization."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from .discovery import discover

INTERVAL = 300
_locks = {}
_guard = threading.Lock()


def home_lock(home):
    with _guard:
        return _locks.setdefault(str(Path(home).resolve()).casefold(), threading.RLock())


def stable_read(path, attempts=3, pause=.03):
    path = Path(path)
    for attempt in range(attempts):
        try:
            before = path.stat()
            raw = path.read_bytes()
            time.sleep(pause)
            second = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and raw == second and len(raw) == after.st_size:
                return raw, {'size': after.st_size, 'mtime_ns': after.st_mtime_ns, 'sha256': hashlib.sha256(raw).hexdigest()}
        except OSError:
            if attempt == attempts - 1:
                raise
    raise OSError('Source changed during reading; retry on next synchronization: ' + str(path))


def sidecar(home):
    db = sqlite3.connect(Path(home) / 'intelligence.sqlite')
    db.execute('PRAGMA busy_timeout=30000')
    db.executescript('''CREATE TABLE IF NOT EXISTS sync_files(path TEXT PRIMARY KEY,digest TEXT,metadata TEXT,present INTEGER);
    CREATE TABLE IF NOT EXISTS sync_runs(id INTEGER PRIMARY KEY,started TEXT,finished TEXT,status TEXT,report TEXT);
    CREATE TABLE IF NOT EXISTS sightings(id TEXT PRIMARY KEY,player_key TEXT,event_id TEXT,data TEXT);
    CREATE INDEX IF NOT EXISTS player_sightings ON sightings(player_key,event_id);
    CREATE TABLE IF NOT EXISTS unresolved(id TEXT PRIMARY KEY,data TEXT);
    CREATE TABLE IF NOT EXISTS index_meta(key TEXT PRIMARY KEY,value TEXT);
    PRAGMA user_version=1;''')
    return db


def synchronize(service, wow_root='', files=None):
    lock = home_lock(service.home)
    if not lock.acquire(blocking=False):
        return {'busy': True, 'files': 0, 'matches_added': 0, 'rosters_added': 0, 'recognized': 0, 'consolidated': 0, 'ambiguous': 0, 'failures': 0}
    try:
        from .profile import backup
        backup(service.home)
        from .archive import Archive
        from .settings import SettingsStore
        started = datetime.now(timezone.utc).isoformat()
        service.home.mkdir(parents=True, exist_ok=True)
        db = sidecar(service.home)
        ticket = db.execute('INSERT INTO sync_runs(started,status,report) VALUES (?, ?, ?)', (started, 'running', '{}')).lastrowid
        db.commit()
        report = {'files': 0, 'changed': 0, 'skipped': 0, 'removed': [], 'matches_added': 0, 'rosters_added': 0,
                  'recognized': 0, 'consolidated': 0, 'ambiguous': 0, 'failures': 0, 'observations_added': 0, 'imports': [], 'warnings': []}
        archive = None
        try:
            if files is None and (not wow_root or not Path(wow_root).is_dir()):
                raise ValueError('Choose a valid WoW installation folder in Settings')
            paths = [Path(p).resolve() for p in (files if files is not None else discover(wow_root))]
            report['files'] = len(paths)
            archive = Archive(service.home)
            before = archive.totals()
            zone = SettingsStore(service.home / 'settings.json').load()['source_timezone']
            for path in paths:
                try:
                    raw, metadata = stable_read(path)
                    previous = db.execute('SELECT digest FROM sync_files WHERE path=?', (str(path),)).fetchone()
                    if previous and previous[0] == metadata['sha256']:
                        report['skipped'] += 1
                        db.execute('UPDATE sync_files SET present=1 WHERE path=?', (str(path),))
                        continue
                    report['changed'] += 1
                    item = archive.import_file(path, source_timezone=zone, raw_bytes=raw)
                    report['imports'].append(item)
                    if item['status'] != 'ok':
                        raise ValueError('Import failed: ' + json.dumps(item['diagnostics'], ensure_ascii=False))
                    for key, source in [('recognized', 'observations_recognized'), ('observations_added', 'observations_added'), ('consolidated', 'consolidated')]:
                        report[key] += item.get(source, 0)
                    db.execute('INSERT OR REPLACE INTO sync_files VALUES (?,?,?,1)', (str(path), metadata['sha256'], json.dumps(metadata)))
                except (OSError, ValueError) as exc:
                    report['failures'] += 1; report['warnings'].append(str(path) + ': ' + str(exc))
            if files is None:
                present = {str(p) for p in paths}
                for path, in db.execute('SELECT path FROM sync_files WHERE present=1').fetchall():
                    if path not in present:
                        report['removed'].append(path)
                        db.execute('UPDATE sync_files SET present=0 WHERE path=?', (path,))
            after = archive.totals()
            report['matches_added'] = max(0, after['total'] - before['total'])
            report['rosters_added'] = max(0, after['rosters'] - before['rosters'])
            report['ambiguous'] = archive.source_totals()['ambiguous_pairs']
            from .career import recover
            report['rated_career'] = recover(service.home)
        except Exception as exc:
            report['failures'] += 1; report['warnings'].append(str(exc))
        finally:
            if archive:
                archive.close()
            status = 'ok' if not report['failures'] else 'failed'
            db.execute('UPDATE sync_runs SET finished=?,status=?,report=? WHERE id=?', (datetime.now(timezone.utc).isoformat(), status, json.dumps(report), ticket))
            db.commit(); db.close()
        return report
    finally:
        lock.release()


class SyncSchedule:
    def __init__(self, clock=time.monotonic, interval=INTERVAL):
        self.clock, self.interval = clock, interval
        self.next_due = clock() + interval
        self.running = False

    def claim(self, manual=False):
        if self.running or not manual and self.clock() < self.next_due:
            return False
        self.running = True
        return True

    def finish(self):
        self.running = False
        self.next_due = self.clock() + self.interval

"""Verified pre-write backups and non-destructive profile relocation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid
from .archive import safe_destination


def backup(home):
    home = Path(home)
    marker = home / 'upgrade-1.3.json'
    if marker.exists() or not (home / 'archive.sqlite').exists():
        return
    folder = safe_destination(home / 'backups' / ('v1_3_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]))
    folder.mkdir(parents=True)
    source = sqlite3.connect((home / 'archive.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
    target = sqlite3.connect(folder / 'archive.sqlite')
    try:
        source.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        counts = {r[0]: source.execute('SELECT count(*) FROM "' + r[0].replace('"', '""') + '"').fetchone()[0]
                  for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    finally:
        source.close(); target.close()
    for name in ('people.json', 'settings.json'):
        if (home / name).exists():
            shutil.copyfile(home / name, folder / name)
    manifest = {'created': datetime.now(timezone.utc).isoformat(), 'counts': counts,
                'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()},
                'snapshots': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (home / 'snapshots').glob('*') if p.is_file()}}
    for name, digest in manifest['files'].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise OSError('Backup verification failed: ' + name)
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps({'backup': str(folder), 'created': manifest['created']}), encoding='utf8')
    temporary.replace(marker)


def relocate(home, destination):
    home, destination = Path(home).resolve(), safe_destination(destination)
    if destination == home or destination.is_relative_to(home) or home.is_relative_to(destination):
        raise ValueError('Choose a separate archive folder outside the current profile')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Destination must be an empty folder')
    backup(home)
    destination.mkdir(parents=True, exist_ok=True)
    # No original is removed. A failure leaves an explicitly unverified copy.
    marker = destination / 'COPY_INCOMPLETE'
    marker.write_text('Do not use until verification finishes', encoding='utf8')
    for source in home.iterdir():
        if source.name.endswith(('-wal', '-shm', '-journal')) or source.name == 'archive.sqlite':
            continue
        if source.is_dir():
            shutil.copytree(source, destination / source.name)
        else:
            shutil.copy2(source, destination / source.name)
    source_db = sqlite3.connect((home / 'archive.sqlite').as_uri() + '?mode=ro', uri=True)
    target_db = sqlite3.connect(destination / 'archive.sqlite')
    try:
        source_db.backup(target_db)
        assert target_db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        # Imported snapshot paths must point inside the verified new copy.
        for row in target_db.execute('SELECT id,snapshot FROM imports WHERE snapshot IS NOT NULL').fetchall():
            old = Path(row[1])
            new = destination / 'snapshots' / old.name
            if not old.exists() or not new.exists() or hashlib.sha256(old.read_bytes()).digest() != hashlib.sha256(new.read_bytes()).digest():
                raise OSError('Missing or changed snapshot during copy: ' + str(old))
            target_db.execute('UPDATE imports SET snapshot=? WHERE id=?', (str(new), row[0]))
        target_db.commit()
    finally:
        source_db.close(); target_db.close()
    for source in home.rglob('*'):
        if source.is_file() and source.name != 'archive.sqlite' and not source.name.endswith(('-wal', '-shm', '-journal')):
            other = destination / source.relative_to(home)
            if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(other.read_bytes()).digest():
                raise OSError('Profile changed during copy: ' + str(source))
    marker.unlink()
    return str(destination)

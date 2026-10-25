"""One-time, pre-write profile backup for the 1.2 upgrade; no archive reset."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid


def ensure_profile_backup(home):
    home = Path(home)
    marker = home / 'upgrade-1.2.json'
    if marker.exists():
        return
    home.mkdir(parents=True, exist_ok=True)
    existing = [home / n for n in ('archive.sqlite', 'people.json', 'settings.json') if (home / n).exists()]
    folder = None
    if existing:
        folder = home / 'backups' / ('v1_2_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        for path in existing:
            if path.name == 'archive.sqlite':
                source = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
                target = sqlite3.connect(folder / path.name)
                try:
                    source.backup(target)
                    assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                finally:
                    target.close(); source.close()
            else:
                shutil.copyfile(path, folder / path.name)
        (folder / 'manifest.json').write_text(json.dumps({'version': '1.2', 'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}}, indent=2), encoding='utf8')
    temporary = marker.with_name(marker.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps({'version': '1.2', 'backup': str(folder) if folder else None}), encoding='utf8')
    temporary.replace(marker)

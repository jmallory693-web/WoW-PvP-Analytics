"""UTF-8 CSV exports and independently testable AI report/Windows clipboard."""
import csv
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
from .archive import safe_destination
from .identity import normalized
from .metrics import (Filters, character_comparison, filter_matches, group_rosters,
                      has_person, match_key, performance, roster_key)
from .schema import MATCH_HEADER, ROSTER_HEADER

MATCH_EXPORT_HEADER = MATCH_HEADER + ['Partial', 'Map suggestion', 'Deaths per 10 minutes', 'Damage rank', 'Healing rank', 'Win margin', 'Source', 'Map ID', 'Player count', 'Field provenance', 'Conflicts']
ROSTER_EXPORT_HEADER = ['Owner character', 'Owner realm', 'Owner person', 'Partial'] + ROSTER_HEADER + ['Person', 'Field provenance', 'Owner person display', 'Person display']


def export_records(matches, rosters, identities):
    grouped = group_rosters(rosters)
    match_rows, roster_rows = [], []
    for m in matches:
        rows = grouped.get(match_key(m), [])
        enriched = performance(m, rows)
        match_rows.append(enriched | {'Partial': bool(m.get('_partial')), 'Map suggestion': m.get('_map_suggestion'),
                                     'Field provenance': json.dumps(m.get('_provenance', {}), ensure_ascii=False),
                                     'Conflicts': json.dumps(m.get('_conflicts', []), ensure_ascii=False)})
        for row in rows:
            roster_rows.append(row | {'Owner person': identities.resolve(m['Character'], m.get('Realm')),
                                     'Owner person display': identities.label(identities.resolve(m['Character'], m.get('Realm'))),
                                     'Person display': identities.label(identities.resolve(row['Player'], row.get('Realm'))),
                                     'Partial': bool(m.get('_partial')),
                                     'Field provenance': json.dumps(row.get('_provenance', {}), ensure_ascii=False),
                                     'Person': identities.resolve(row['Player'], row.get('Realm'))})
    return match_rows, roster_rows


def csv_text(header, records):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=header, extrasaction='ignore', lineterminator='\r\n')
    writer.writeheader()
    for record in records:
        writer.writerow({key: record.get(key) for key in header})
    return out.getvalue()


def _folder(label):
    # Prefix and digest prevent Windows reserved names and sanitization collisions.
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', label).strip(' .')[:80] or 'unnamed'
    return 'entry_' + slug + '_' + hashlib.sha256(label.encode('utf8')).hexdigest()[:10]


def _write_csv(path, header, rows):
    path = safe_destination(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='export-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8-sig', newline='') as out:
            writer = csv.DictWriter(out, fieldnames=header, extrasaction='ignore', lineterminator='\r\n')
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in header})
            out.flush(); os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def export_folders(matches, rosters, identities, destination, filters=None):
    """Each character/person folder gets selected matches and whole scoreboards."""
    destination = safe_destination(destination)
    selected = filter_matches(matches, rosters, filters, identities)
    grouped = group_rosters(rosters)
    groups = []
    for character in character_comparison(matches, rosters, identities):
        name, realm = character['character'], character['realm']
        label = name + ('-' + realm if realm else '')
        subset = [m for m in selected if m['Character'] == name and m.get('Realm') == realm]
        groups.append(('characters', label, subset))
    for person in identities.people:
        if normalized(person) == normalized(identities.owner_person):
            continue
        subset = [m for m in selected if normalized(identities.resolve(m['Character'], m.get('Realm'))) == normalized(identities.owner_person)
                  and has_person(m, grouped.get(match_key(m), []), identities, person)]
        groups.append(('people', person, subset))
    manifest = []
    for category, label, subset in groups:
        match_rows, roster_rows = export_records(subset, rosters, identities)
        folder = safe_destination(destination / category / _folder(label))
        _write_csv(folder / 'matches.csv', MATCH_EXPORT_HEADER, match_rows)
        _write_csv(folder / 'roster.csv', ROSTER_EXPORT_HEADER, roster_rows)
        manifest.append({'category': category, 'label': label, 'folder': str(folder),
                         'matches': len(match_rows), 'rosters': len(roster_rows)})
    return manifest


def ai_report(matches, rosters, identities, filters=None, limit=20):
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError('Match limit must be a positive integer')
    selected = filter_matches(matches, rosters, filters, identities)[-limit:]
    match_rows, roster_rows = export_records(selected, rosters, identities)
    # Two complete CSV sections keep match and roster schemas unambiguous.
    metadata = {'selected_matches': len(selected), 'requested_limit': limit,
                'roster_rows': len(roster_rows), 'filters': vars(filters or Filters()),
                'notes': 'Partial=True means incomplete source. Blank numeric fields are unknown. Map suggestions are unconfirmed. Match types are separate categories; combine explicitly.'}
    return ('PvP Ledger archive report\r\n' + json.dumps(metadata, ensure_ascii=False) + '\r\n\r\nMATCHES CSV\r\n'
            + csv_text(MATCH_EXPORT_HEADER, match_rows) + '\r\nROSTER CSV\r\n'
            + csv_text(ROSTER_EXPORT_HEADER, roster_rows))


def copy_to_clipboard(text):
    """Set CF_UNICODETEXT without Tk, a shell, encoding loss, or size limits."""
    if os.name != 'nt':
        raise OSError('Clipboard access requires Windows; use ai_report() for text')
    if '\x00' in text:
        raise ValueError('Clipboard text cannot contain NUL characters')
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.OpenClipboard.argtypes = [wintypes.HWND]; user.OpenClipboard.restype = wintypes.BOOL
    user.EmptyClipboard.argtypes = []; user.EmptyClipboard.restype = wintypes.BOOL
    user.CloseClipboard.argtypes = []; user.CloseClipboard.restype = wintypes.BOOL
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]; user.SetClipboardData.restype = wintypes.HANDLE
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = wintypes.HWND
    user.DestroyWindow.argtypes = [wintypes.HWND]; user.DestroyWindow.restype = wintypes.BOOL
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]; kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]; kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]; kernel.GlobalUnlock.restype = wintypes.BOOL
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]; kernel.GlobalFree.restype = wintypes.HGLOBAL
    encoded = text.encode('utf-16-le') + b'\x00\x00'
    handle = kernel.GlobalAlloc(0x0002, len(encoded))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    opened = False
    window = None
    try:
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(pointer, encoded, len(encoded))
        finally:
            kernel.GlobalUnlock(handle)
        # A private, invisible message-only owner avoids NULL clipboard ownership.
        window = user.CreateWindowExW(0, 'STATIC', 'PvP Ledger clipboard', 0, 0, 0, 0, 0, wintypes.HWND(-3), None, None, None)
        if not window:
            raise ctypes.WinError(ctypes.get_last_error())
        if not user.OpenClipboard(window):
            raise ctypes.WinError(ctypes.get_last_error())
        opened = True
        if not user.EmptyClipboard() or not user.SetClipboardData(13, handle):
            raise ctypes.WinError(ctypes.get_last_error())
        handle = None  # Windows owns the allocation after SetClipboardData.
    finally:
        if opened:
            user.CloseClipboard()
        if window:
            user.DestroyWindow(window)
        if handle:
            kernel.GlobalFree(handle)

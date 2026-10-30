"""Desktop application service. Owns connections inside the calling worker thread."""
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
from .archive import Archive, default_home, safe_destination
from .discovery import discover
from .identity import IdentityMap, normalized
from .metrics import (Filters, ally_comparisons, character_comparison, filter_matches,
                      group_rosters, match_key, own_rows)
from .export import ai_report, copy_to_clipboard, export_folders
from .viewmodels import history_row, home_model, scoreboard_model, sort_records

EDITABLE_FIELDS = {'Map': str, 'Result': str, 'Type': str, 'Duration (s)': int,
                   'Minutes played': float, 'My team score': int, 'Enemy team score': int,
                   'Alliance score': int, 'Horde score': int}
MATCH_TYPES = ('Battleground', 'Brawl', 'Rated arena', 'Arena skirmish', 'Solo Shuffle')


def validate_overrides(values):
    cleaned = {}
    for field, value in values.items():
        if field not in EDITABLE_FIELDS:
            raise ValueError(f'{field} is not supported by the metadata editor')
        if value is None or (isinstance(value, str) and not value.strip()):
            cleaned[field] = None
            continue
        if field == 'Result' and value not in ('W', 'L'):
            raise ValueError('Result must be W, L, or blank for unknown')
        if field == 'Type' and value not in MATCH_TYPES:
            raise ValueError('Choose a known match type or leave it unknown')
        try:
            converted = EDITABLE_FIELDS[field](value)
        except (ValueError, TypeError):
            raise ValueError(f'{field} requires a valid {EDITABLE_FIELDS[field].__name__}') from None
        if isinstance(converted, (int, float)):
            import math
            if isinstance(value, bool) or not math.isfinite(converted) or converted < 0 or (EDITABLE_FIELDS[field] is int and float(value) != converted):
                raise ValueError(f'{field} must be a nonnegative finite number' + (' without decimals' if EDITABLE_FIELDS[field] is int else ''))
        cleaned[field] = converted.strip() if isinstance(converted, str) else converted
    return cleaned


class DesktopService:
    def rated_career(self,**filters):
        from .career import recover,model
        recover(self.home)
        return model(self.home,**filters)

    def rated_manual(self,values,previous=None,reason='Manual rating observation',approved=False):
        from .career import save_manual
        return save_manual(self.home,values,previous,reason,approved)

    def rated_reverse(self,revision,approved=False):
        from .career import reverse_manual
        return reverse_manual(self.home,revision,approved)

    def rated_rebuild(self):
        from .career import recover
        return recover(self.home,force=True)

    def rated_evidence(self,observation_id):
        from .career import connect
        db=connect(self.home)
        if db is None:return []
        try:return [json.loads(r[0]) for r in db.execute('select provenance from evidence where observation_id=?',(observation_id,))]
        finally:db.close()

    def trends(self, filters=None, window=20, threshold=344, teammates=()):
        from .trends import prepare_trends
        with self.archive() as archive:
            matches, rows, identities = self._records(archive)
            return prepare_trends(matches, rows, identities, filters, window, threshold, teammates)

    def __init__(self, home=None, clipboard=copy_to_clipboard):
        self.home = safe_destination(home or default_home())
        self.clipboard = clipboard

    @contextmanager
    def archive(self):
        archive = Archive(self.home)
        try:
            yield archive
        finally:
            archive.close()

    def _records(self, archive):
        identities = IdentityMap(self.home / 'people.json')
        from .settings import SettingsStore
        from .calendar_core import localize
        matches, rosters = localize(archive.read_matches(), SettingsStore(self.home / 'settings.json').load()['source_timezone']), archive.read_rosters()
        identities.discover_unassigned([r for r in rosters if not r.get('_excel_historical')])
        return matches, rosters, identities

    def snapshot(self, filters=None, sort_field='Date/time', descending=True, page=0, page_size=100, wow_root=''):
        from .calendar_core import availability
        from .comparisons import catalogue
        if page_size < 1 or page_size > 500:
            raise ValueError('History page size must be between 1 and 500')
        filters = filters or Filters()
        with self.archive() as archive:
            matches, rosters, identities = self._records(archive)
            selected = filter_matches(matches, rosters, filters, identities)
            history = sort_records([history_row(m) for m in selected], sort_field, descending)
            pages = max(1, (len(history) + page_size - 1) // page_size)
            page = max(0, min(page, pages - 1))
            return {'home': home_model(selected, rosters, identities),
                    'calendar': availability(filter_matches(matches, rosters, replace(filters, start=None, end=None), identities)),
                    'catalogue': catalogue(matches, rosters, identities),
                    'person_labels': {p: identities.label(p) for p in identities.people},
                    'person_profiles': identities.profiles,
                    'history': history[page * page_size:(page + 1) * page_size],
                    'page': page, 'pages': pages, 'history_count': len(history),
                    'comparison': character_comparison(selected, rosters, identities),
                    'allies': ally_comparisons(selected, rosters, identities),
                    'people': identities.people,
                    'owner_person': identities.owner_person,
                    'characters': sorted({m['Character'] + '-' + m['Realm'] for m in matches}),
                    'maps': sorted({m.get('Map') or f"Map ID {m['Map ID']}" for m in matches if m.get('Map') or m.get('Map ID') is not None}),
                    'diagnostics': self._diagnostics(archive, identities, wow_root),
                    'review': archive.duplicate_review(),
                    'observations': [dict(r) for r in archive.db.execute('SELECT id,addon,character,realm,original_id FROM observations ORDER BY id')],
                    'totals': archive.totals()}

    def _diagnostics(self, archive, identities, wow_root):
        imports = archive.diagnostics()
        return {'archive': str(self.home / 'archive.sqlite'), 'wow_root': wow_root,
                'files': [str(p) for p in discover(wow_root)] if wow_root and Path(wow_root).is_dir() else [],
                'last_import': imports[-1]['started'] if imports else None,
                'totals': archive.totals(), 'recent_imports': imports[-20:],
                'sources': archive.source_totals(),
                'imports_total': len(imports), 'unassigned': identities.people.get(identities.person_name('Unassigned'), []),
                'trace': archive.read_traces(500)}

    def refresh(self, wow_root='', files=None):
        if files is None:
            from .settings import SettingsStore
            from .setup import selected_sources
            preferences = SettingsStore(self.home / 'settings.json').load()
            selected = preferences['source_locations']
            if selected or preferences['source_selection_explicit']:
                files = selected_sources(selected)
        if files is None and (not wow_root or not Path(wow_root).is_dir()):
            raise ValueError('Choose a valid WoW installation folder in Settings, or import a file')
        from .sync import synchronize
        return synchronize(self, wow_root, files)

    def players(self, query='', class_name='', spec='', page=0):
        from .player_index import directory
        return directory(self.home, query, class_name, spec, page)

    def reconcile_excel(self,path,zone='America/Los_Angeles'):
        from .reconcile import reconcile
        from .sync import home_lock
        with home_lock(self.home):return reconcile(self.home,path,zone)

    def commit_excel(self,report,selections,*,approved=False):
        from .supplemental import commit
        return commit(self.home,report,selections,approved=approved)

    def reverse_excel(self,row_id,*,approved=False):
        from .supplemental import reverse
        return reverse(self.home,row_id,approved=approved)

    def excel_history(self):
        from .supplemental import history
        return history(self.home)

    def export_reconciliation(self,report,destination):
        from .reconcile import write_report
        return write_report(report,destination)

    def player_history(self, key=None):
        from .player_index import encounters
        return encounters(self.home, key)

    def player_evidence(self, event_id, player_key):
        """Return every retained source sighting for this player encounter."""
        from .sync import sidecar
        db = sidecar(self.home)
        try:
            return [json.loads(r[0]) for r in db.execute(
                'SELECT data FROM sightings WHERE event_id=? AND player_key=?',
                (event_id, player_key))]
        finally:
            db.close()

    def unresolved_records(self):
        """Return captured records that could not be resolved by the index."""
        from .sync import sidecar
        db = sidecar(self.home)
        try:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM unresolved')]
        finally:
            db.close()

    def ranking(self, key=None, metric='Damage', scope='All recorded participants', reference=None,
                historical_mode='Individual Encounters', minimum=1, filters=None):
        from .rankings import rank, historical
        from .player_index import encounters
        rows = encounters(self.home, perspective=key)
        if filters is not None and key is None:
            from .player_index import read_archive, read_identities
            from .dual_archive import project
            from types import SimpleNamespace
            db = read_archive(self.home)
            try:
                matches, rosters = project(SimpleNamespace(db=db))
                selected = {match_key(m) for m in filter_matches(matches, rosters, filters, read_identities(self.home))}
                rows = [r for r in rows if tuple(r['canonical_key']) in selected]
            finally:db.close()
        identities = IdentityMap(self.home / 'people.json')
        for row in rows:
            row['Highlight'] = 'self' if identities.resolve(row['Player'], row.get('Realm')) == identities.owner_person else ''
            row['Person'] = identities.label(identities.resolve(row['Player'], row.get('Realm')))
        return rank(rows, metric, scope, reference) if key else historical(rows, metric, historical_mode, minimum, scope, reference)

    def archive_status(self):
        from .sync import sidecar
        from .player_index import rebuild
        import hashlib
        indexed = rebuild(self.home)
        db = sidecar(self.home)
        try:
            runs = [dict(zip(('started','finished','status','report'), r)) for r in db.execute('SELECT started,finished,status,report FROM sync_runs ORDER BY id DESC LIMIT 30')]
        finally:
            db.close()
        with self.archive() as archive:
            missing = []
            for row in archive.db.execute('SELECT DISTINCT snapshot,sha256 FROM imports WHERE snapshot IS NOT NULL'):
                path = Path(row[0])
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != row[1]:
                    missing.append(str(path))
            totals = archive.totals()
        files = [p for p in self.home.rglob('*') if p.is_file()]
        marker = self.home / 'upgrade-1.3.json'
        return {'archive': str(self.home), 'database': str(self.home / 'archive.sqlite'),
                'snapshots': str(self.home / 'snapshots'), 'used_bytes': sum(p.stat().st_size for p in files),
                'snapshot_count': sum(p.is_file() for p in (self.home / 'snapshots').glob('*')),
                'index': indexed, 'totals': totals, 'sync_history': runs, 'integrity_errors': missing,
                'backup': json.loads(marker.read_text(encoding='utf8')) if marker.exists() else None}

    def complete_export(self, destination, scope='Full Archive', filters=None, players=(), character=None, progress=None, cancel=None):
        from .full_export import export_dump
        destination = safe_destination(destination)
        from .player_index import read_archive
        db = read_archive(self.home)
        try:
            for row in db.execute('SELECT DISTINCT source FROM imports'):
                for parent in Path(row[0]).parents:
                    if parent.name.casefold() == 'wtf':
                        branch = parent.parent
                        root = branch.parent if branch.name.startswith('_') else branch
                        if destination.is_relative_to(root.resolve()):
                            raise ValueError('Export destination must be outside imported WoW installations')
        finally:
            db.close()
        return export_dump(self.home, destination, scope, filters, players, character, progress, cancel)

    def decide_link(self, left, right, decision):
        with self.archive() as archive:
            archive.decide_link(left, right, decision)
            return archive.source_totals()

    def scoreboard(self, key):
        with self.archive() as archive:
            matches, rosters, identities = self._records(archive)
            match = next((m for m in matches if match_key(m) == tuple(key)), None)
            if match is None:
                raise ValueError('This archived match could not be found')
            return scoreboard_model(match, own_rows(match, rosters), identities)

    def edit_partial(self, key, values):
        values = validate_overrides(values)
        with self.archive() as archive:
            match = next((m for m in archive.read_matches() if match_key(m) == tuple(key)), None)
            if match and match.get('_excel_historical'):
                raise ValueError('Use Excel reconciliation to correct or reverse spreadsheet-sourced historical records')
            if not match or not match.get('_partial'):
                raise ValueError('Only partial-match metadata can be edited here')
            archive.set_overrides(tuple(key), values)
        return self.scoreboard(key)

    def edit_identity(self, character, person=None, action='assign'):
        identities = IdentityMap(self.home / 'people.json')
        if action == 'assign':
            identities.assign(character, person or '')
        elif action == 'unassign':
            identities.unassign(character)
        elif action == 'remove':
            identities.remove(character)
        else:
            raise ValueError('Unknown identity action')
        return identities.people

    def edit_person(self, person, display_name, nickname=''):
        identities = IdentityMap(self.home / 'people.json')
        identities.edit_person(person, display_name, nickname)
        return identities.label(identities.person_name(person))

    def edit_association(self, old, new, person):
        identities = IdentityMap(self.home / 'people.json')
        identities.replace_association(old, new, person)
        return identities.people

    def compare(self, selections, scope='All Recorded Matches', filters=None, window=20, item_min=None, item_max=None):
        from .comparisons import compare
        with self.archive() as archive:
            matches, rows, identities = self._records(archive)
            return compare(matches, rows, identities, selections, scope, filters, window, item_min, item_max)

    def _guard_export(self, destination, wow_root):
        destination = safe_destination(destination)
        if wow_root and destination.is_relative_to(Path(wow_root).resolve()):
            raise ValueError('Export destination must be outside the selected WoW installation')
        with self.archive() as archive:
            if any(destination.is_relative_to(root.resolve()) for root in archive.source_game_roots()):
                raise ValueError('Export destination must be outside imported WoW installations')
        return destination

    def export(self, destination, filters=None, character=None, ally=None, wow_root=''):
        destination = self._guard_export(destination, wow_root)
        filters = filters or Filters()
        if character:
            filters = replace(filters, character=character)
        if ally:
            filters = replace(filters, ally=ally)
        with self.archive() as archive:
            matches, rows, identities = self._records(archive)
            return export_folders(matches, rows, identities, destination, filters)

    def copy_report(self, filters=None, limit=20, key=None):
        with self.archive() as archive:
            matches, rows, identities = self._records(archive)
            if key is not None:
                matches = [m for m in matches if match_key(m) == tuple(key)]
                if not matches:
                    raise ValueError('Match not found')
            text = ai_report(matches, rows, identities, filters, 1 if key else limit)
        self.clipboard(text)
        return {'characters': len(text)}

    def copy_diagnostics(self, wow_root=''):
        with self.archive() as archive:
            identities = IdentityMap(self.home / 'people.json')
            text = json.dumps(self._diagnostics(archive, identities, wow_root), ensure_ascii=False, indent=2)
        self.clipboard(text)
        return {'characters': len(text)}

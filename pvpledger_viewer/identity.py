"""Editable person mappings, resolved at query time against all archived history."""
import json
import os
from pathlib import Path
import tempfile
import unicodedata
from .archive import default_home, safe_destination

SEED = {'Me': [], 'Unassigned': []}


def owner_id(document):
    people = document['people']
    explicit = document.get('owner_person')
    if explicit is not None:
        if explicit not in people or explicit == 'Unassigned':
            raise ValueError('Invalid owner person ID')
        return explicit
    # Legacy version-2 documents stored the owner first. Infer without rewriting
    # any person ID, association, alias, or the original document.
    return next((p for p in people if p != 'Unassigned'), 'Me')


def normalized(value):
    return unicodedata.normalize('NFC', value.strip()).casefold()


def character_key(name, realm=None):
    if realm is None:
        name, _, realm = name.partition('-')
    return normalized(name), ''.join(normalized(realm or '').split())


class IdentityMap:
    def __init__(self, path=None):
        self.path = safe_destination(path or default_home() / 'people.json')
        if self.path.exists():
            document = json.loads(self.path.read_text(encoding='utf-8-sig'))
            self.people = document['people']
            self.profiles = document.get('profiles', {})
            self.owner_person = owner_id(document)
            self._validate()
        else:
            self.people = {p: list(names) for p, names in SEED.items()}
            self.profiles = {}
            self.owner_person = owner_id({'people': self.people})
            self.save()

    def _validate(self):
        if not isinstance(self.people, dict):
            raise ValueError('people must be an object of person names and character lists')
        seen, people_seen = set(), set()
        for person, entries in self.people.items():
            if not isinstance(person, str) or not person.strip() or normalized(person) in people_seen:
                raise ValueError('Person names must be nonempty and unique, ignoring case')
            people_seen.add(normalized(person))
            if not isinstance(entries, list):
                raise ValueError('Each person must have a list of character mappings')
            for entry in entries:
                if not isinstance(entry, str) or not character_key(entry)[0]:
                    raise ValueError('Character mappings must be nonempty strings')
                key = character_key(entry)
                if key in seen:
                    raise ValueError(f'Duplicate character mapping: {entry}')
                seen.add(key)

    def save(self):
        self._validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from .upgrade import ensure_profile_backup
        ensure_profile_backup(self.path.parent)
        path = safe_destination(self.path)
        if path.exists():
            from datetime import datetime, timezone
            import shutil, uuid
            folder = path.parent / 'backups' / ('identity_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
            folder.mkdir(parents=True)
            shutil.copyfile(path, folder / path.name)
        handle, temporary = tempfile.mkstemp(prefix='people-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(handle, 'w', encoding='utf8', newline='\n') as out:
                json.dump({'version': 2, 'people': self.people, 'profiles': self.profiles, 'owner_person': self.owner_person}, out, ensure_ascii=False, indent=2)
                out.write('\n'); out.flush(); os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()

    def person_name(self, person):
        return next((p for p in self.people if normalized(p) == normalized(person) or normalized(self.label(p)) == normalized(person)), person.strip())

    def label(self, person):
        profile = self.profiles.get(person, {})
        name, nick = profile.get('display_name', person), profile.get('nickname', '')
        return f'{name} ({nick})' if nick else name

    def edit_person(self, person, display_name, nickname=''):
        person = self.person_name(person)
        if person not in self.people:
            raise ValueError('Choose an existing person')
        display_name, nickname = display_name.strip(), nickname.strip()
        if not display_name:
            raise ValueError('Display name cannot be empty')
        if person == 'Unassigned' and display_name != person:
            raise ValueError('Unassigned retains its reserved name')
        label = f'{display_name} ({nickname})' if nickname else display_name
        if any(p != person and normalized(label) in (normalized(p), normalized(self.label(p))) for p in self.people):
            raise ValueError('That person label already exists')
        self.profiles[person] = {'display_name': display_name, 'nickname': nickname}
        self.save()

    def _lookup(self, name, realm=None):
        name_key, realm_key = character_key(name, realm)
        wildcard = None
        for person, entries in self.people.items():
            for entry in entries:
                n, r = character_key(entry)
                if n == name_key:
                    if r and realm_key and r == realm_key:
                        return person
                    if not r:
                        wildcard = person
        return wildcard

    def resolve(self, name, realm=None):
        return self._lookup(name, realm) or 'Unassigned'

    def assign(self, character, person):
        person = self.person_name(person)
        if not person:
            raise ValueError('Person name cannot be empty')
        key = character_key(character)
        if not key[0]:
            raise ValueError('Character name cannot be empty')
        for entries in self.people.values():
            entries[:] = [e for e in entries if character_key(e) != key]
        self.people.setdefault(person, []).append(unicodedata.normalize('NFC', character.strip()))
        self.save()

    def unassign(self, character):
        self.assign(character, 'Unassigned')

    def replace_association(self, old, new, person):
        from copy import deepcopy
        before = deepcopy(self.people)
        person = self.person_name(person)
        if person not in self.people or not character_key(new)[0] or not character_key(new)[1]:
            raise ValueError('Choose an existing person and an exact character/realm')
        try:
            for entries in self.people.values():
                entries[:] = [e for e in entries if character_key(e) not in (character_key(old), character_key(new))]
            self.people[person].append(unicodedata.normalize('NFC', new.strip()))
            self.save()
        except Exception:
            self.people = before
            raise

    def remove(self, character):
        """Delete an explicit mapping; a remaining wildcard can still apply."""
        key = character_key(character)
        for entries in self.people.values():
            entries[:] = [e for e in entries if character_key(e) != key]
        self.save()

    def discover_unassigned(self, rosters):
        """Persist unknown premade allies only, never opponents or inferred people."""
        added = []
        for row in rosters:
            if row.get('Team') != 'Mine' or row.get('Is premade') != 'Yes':
                continue
            name, realm = row['Player'], row.get('Realm')
            if self._lookup(name, realm) is None:
                entry = name + ('-' + realm if realm else '')
                self.people.setdefault('Unassigned', []).append(entry)
                added.append(entry)
        if added:
            self.save()
        return added

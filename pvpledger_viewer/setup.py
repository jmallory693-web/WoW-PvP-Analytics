"""Local-only onboarding. Existing profiles are detected without rewriting them."""
import os
from pathlib import Path
from .archive import safe_destination
from .discovery import discover


def existing_profile(home):
    return any((Path(home)/name).exists() for name in ('archive.sqlite', 'people.json', 'settings.json'))


def installation_candidates():
    candidates = []
    for variable in ('ProgramFiles(x86)', 'ProgramFiles'):
        if os.environ.get(variable):
            path = Path(os.environ[variable])/'World of Warcraft'
            if path.is_dir() and path not in candidates:
                candidates.append(path)
    return candidates


def locations(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('Choose an existing WoW installation or SavedVariables folder')
    paths = discover(root)
    # A user may choose one exact SavedVariables directory.
    paths.extend(p for name in ('PvPLedger.lua', 'REFlex.lua') if (p := root/name).is_file())
    return sorted(set(paths))


def selected_sources(values):
    found = set()
    for value in values:
        path = Path(value)
        if path.is_dir():
            found.update(locations(path))
        elif path.name in ('PvPLedger.lua', 'REFlex.lua') and path.is_file():
            found.add(path.resolve())
        else:
            raise ValueError('SavedVariables location is unavailable: ' + str(path))
    return sorted(found)


def discovered_characters(paths):
    """Character-specific paths are exact identities; account-wide files stay unassigned."""
    result = set()
    for path in map(Path, paths):
        parts = path.parts
        if 'Account' in parts:
            suffix = parts[parts.index('Account')+1:]
            if len(suffix) == 5 and suffix[-2] == 'SavedVariables':
                result.add(suffix[2] + '-' + suffix[1])
    return sorted(result)


def configure(home, *, display_name='', wow_root='', sources=(), own=(), friends=(),
              sync_enabled=True, interval=300, zone='UTC'):
    """Create a fresh profile only. Validate all inputs before any profile write."""
    from .identity import IdentityMap, character_key, normalized
    from .settings import SettingsStore, validate_settings
    from .archive import Archive
    home = safe_destination(home)
    if existing_profile(home):
        raise ValueError('An existing profile is present; use Settings and Edit people to preserve it')
    if wow_root and not Path(wow_root).is_dir():
        raise ValueError('The WoW folder does not exist')
    config = validate_settings({'wow_root': str(wow_root), 'source_locations': list(map(str,sources)),
                                'sync_enabled': sync_enabled, 'sync_interval': interval,
                                'source_timezone': zone, 'setup_complete': True, 'source_selection_explicit': True})
    selected_sources(sources)
    people = {'Me': list(own), 'Unassigned': []}
    for person, character in friends:
        person = person.strip()
        if normalized(person) in ('me', 'unassigned') or not person:
            raise ValueError('Choose a unique friend name other than Me or Unassigned')
        key = next((p for p in people if normalized(p) == normalized(person)), person)
        people.setdefault(key, []).append(character)
    for entries in people.values():
        for entry in entries:
            if not all(character_key(entry)):
                raise ValueError('Enter both character and realm for each association')
    identities = object.__new__(IdentityMap)
    identities.path = home/'people.json'; identities.people = people
    identities.owner_person = 'Me'
    identities.profiles = {'Me': {'display_name': display_name.strip(), 'nickname': ''}} if display_name.strip() else {}
    identities._validate()
    home.mkdir(parents=True, exist_ok=True)
    identities.save()
    SettingsStore(home/'settings.json').save(config)
    archive = Archive(home); archive.close()
    return config

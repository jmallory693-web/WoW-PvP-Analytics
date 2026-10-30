# Approved Warband source release

Date: October 30, 2026. Application: PvP Ledger Viewer 1.4.0.

The user inspected the installed Windows interface and approved its appearance
before authorizing this source publication. No new design or functionality was
implemented during release preparation.

## Included development work

The application, tests, packaging metadata and font assets match approved
development commit `1bdc82c8729de42897c95a037ddab449e29f6569` exactly.
That commit contains all four completed steps:

1. Centralized Classic styling and UI-to-service evidence reads (`5a8ce60`).
2. Persistent Warband and Classic selection, bundled process-private Cinzel,
   and Georgia fallback (`3f255e7`). Missing/invalid preferences use Warband.
3. Play/People/Archive sidebar groups and revised Home character cards,
   retaining all ten navigation view names and existing actions (`ebcc228`).
4. Theme-aware Trends, comparison and rated progression charts and PNG
   exports, preserving Classic rendering and chart data (`1bdc82c`).

Only publication inventory and verification documents differ from that approved
source snapshot. The existing source spec includes the Cinzel font and its full
SIL Open Font License; font provenance is recorded beside the asset. The font
is unchanged and is not installed system-wide.

## History and merge safety

Release preparation used a fresh clone of the published repository at
`5df039719929240b00fc2b155ccb8b4f8fbc1a2f`, on
`release/warband-1.4.0-20261030`. Approved file blobs were copied explicitly;
no private local repository, index, branches or development history was imported.
The release is a source snapshot on top of the published history.

The initial release and schema 6/7 hotfix `80f95fd` remain in ancestry. All six
hotfix implementation, fixture and regression-test files are byte-identical to
that hotfix. README and publication documents include the approved newer notes.
Publication requires an unchanged base, a clean merge, passing tests and a clear
privacy audit; no force-push or uncertain conflict resolution is authorized.

## Final Windows tests

Command: `python -m pytest -q`, run from the clean publishing clone with the
native Windows Python 3.12.10/Tcl/Tk runtime and existing dependencies.

Result: **373 passed, zero failures, skips, errors or warnings**, 151.73 seconds.
One full suite was run during this publication task. The earlier nonfatal
cache-permission warning did not occur in this fresh clone.

The suite covers original archive/import behavior and schema 6/7 regressions,
theme preferences and restart persistence, missing-font startup, all navigation
views and Home actions, theme routing, unchanged chart data and all PNG exports.
See `CHART_THEME_VERIFICATION.md` for the completed Step 4 visual evidence.

## Privacy and preservation

The current explicit publication set is recorded in `PUBLICATION_INVENTORY.json`,
including every new source/test file, the Cinzel font, its license and provenance.
SHA-256 hashes describe exact published content bytes; the inventory excludes
its own recursive hash.

Every candidate file was scanned for configured private identity values,
personal account identifiers, absolute Windows user paths, email addresses and
credential signatures. Workbook members and font name metadata were inspected
separately. No private-data or credential findings occurred. Public GitHub
noreply commit identities are allowed metadata. Tests and addon-format fixtures
remain fictional protocol examples.

No personal archives, databases, identities, settings, SavedVariables, addon
data, screenshots, recordings, exports, builds, executable packages, private
logs, verification copies or old private Git history are publication candidates.
The local Step 5 build-only spec and private installation report are excluded.

Fresh preservation hashes cover the complete installed Windows package,
desktop shortcut, real profile and relevant addon/SavedVariables files. Release
preparation made no changes to them. No executable rebuild or installation,
application launch, profile migration, import or archive write is part of this
publication task. The separate working development checkout remains unchanged.

## Retained limitations

The existing Trends tooltip may extend past the final chart edge. Rated
observations lacking compatible cohort metadata remain unplotted with an
explanation; missing metadata is not guessed. These approved limitations were
not changed during publication. No further features or redesign work is included.

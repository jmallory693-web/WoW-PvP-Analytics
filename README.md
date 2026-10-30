# PvP Ledger Viewer

A local Windows desktop application for permanently archiving PvP Ledger and REFlex SavedVariables. It provides match history, realm-aware identities, encounter comparisons, captured-player rankings, rated career observations, CSV exports, and complete single-file AI exports. The viewer reads game files without executing Lua or writing to the WoW installation. No online account or upload is required.

## Schema 6/7 import hotfix

PvP Ledger 1.3.2/1.3.3 (schema 6) and 1.3.4 (schema 7) write 48 match columns. The reader now accepts their Date, Time, Rated and Rating change fields, the trailing Epoch and Queue type, and the unchanged 21-column roster layout. Schemas 1 through 5 remain supported. Original CSV lines and unknown trailing fields are retained.

Some records imported by the older reader may contain only a structured fallback. Refresh deliberately skips unchanged files by content hash. To repair these records, explicitly import the original file or its retained snapshot through the existing import command, using the original recording context and timezone:

```powershell
pvpledger-viewer --archive-dir "D:\Private PvP Profile" import "D:\Private PvP Profile\snapshots\retained-source.lua" --character Examplehero --realm ExampleRealm --timezone UTC
```

Use your actual recording timezone instead of UTC where applicable. Reimport updates the same match/participant identities, retains raw evidence and observation history, and preserves user overrides; it does not duplicate matches. No archive schema migration, live profile rewrite, executable rebuild, or combat-log feature is part of this hotfix. The reference addon file contains only the protocol headers verified against 1.3.4 source, not its implementation or player data.

## Install and run

Use Windows and Python 3.12 for source development:

```powershell
python -m pip install -e ".[test,build]"
python -m pvpledger_viewer.ui.app
```

For a packaged release, open `PvPLedgerViewer.exe` in its application folder. Keep the entire `_internal` directory beside it. A Windows shortcut should target that EXE, use its folder as the working directory, and have no console launcher.

## Appearance

Warband is the default appearance. Choose Warband or Classic in Settings,
save, then restart the viewer. Classic preserves the original colors and fonts.
Missing or invalid theme preferences use Warband without resetting other settings.
Warband uses bundled Cinzel for titles/headings and Segoe UI for body text;
if its private Windows font registration is unavailable, headings use Georgia.
No font is installed system-wide. The font and its SIL Open Font License are
in `pvpledger_viewer/assets/fonts/`. Classic charts retain their original
appearance; Warband charts follow the active palette.

## First run

New profiles open optional local setup. You may enter a display name, discover a standard WoW installation, browse to a custom installation or SavedVariables directory, and select account/character addon files. Ctrl-click multiple source files. Choose **Use selected sources and list characters** to identify character-specific locations. Account-wide captures may require manual character identification.

Add your own characters using exact character and realm names. Add a friend label plus their character and realm to associate teammates. No sample identities or game history are installed. All optional fields may be skipped and an empty archive is useful offline.

Choose a private archive folder outside the application and WoW directories. The default is `%APPDATA%\PvPLedgerViewer`. Automatic archival defaults to 300 seconds and can be disabled or changed (minimum 30 seconds). Choose the recording PC's IANA timezone explicitly; fresh setup defaults to UTC. Check **Import selected addon history on Start** to import immediately; otherwise setup starts empty. Only selected files are synchronized after fresh setup; selecting no sources does not silently select every account.

Existing profiles reopen directly. Their stable person IDs, labels, character mappings, settings, snapshots, sidecars, and history are preserved. Old archives without a saved timezone retain the legacy recording-time assumption instead of having historical dates silently reinterpreted. Change it in Settings if needed.

**Settings** lets you change WoW/export paths, timezone, synchronization preference and interval, and selected source files. After choosing source files, save Settings. Changing the WoW folder without an explicit file selection restores installation-wide discovery. **Allies ? Edit people** adds people and edits labels, nicknames, and exact character/realm associations. Stable IDs remain unchanged when labels change.

## Permanent archive and privacy

SavedVariables are normally written by WoW on logout or `/reload`. Refresh (F5) and configured background synchronization read both addons. Account-wide and character-specific files are supported; `.bak` files are ignored. Every import retains an immutable source snapshot outside WoW. Content hashes skip unchanged files, and rolling-history removal never deletes archived records.

Back up the entire profile directory, not just `archive.sqlite`. It contains identities, settings, source snapshots, overrides, duplicate decisions, encounter indexes, rated observations, Excel supplements, and backups. The main archive remains schema 2. Settings can create and verify a copy at a separate empty archive location; the original remains intact. An explicit `--archive-dir` selects an isolated profile.

Private game data, screenshots, recordings, exports, and verification outputs do not belong in a source repository. `.gitignore` helps prevent accidental additions but cannot remove existing index or history objects. Inspect the proposed source inventory and Git-history findings in [privacy verification](GITHUB_PRIVACY_VERIFICATION.md) before publication. This phase performs no staging, commit, push, or history rewrite.

## Match history, comparisons and players

Use shared character, type, map, queue, ally and calendar filters to select records. Full Match Scoreboard retains player/team relationships, incomplete-scoreboard indicators and unknown values. User overrides change interpretations while raw observations remain available.

Character Comparison supports Character vs Character, My Characters, and Me vs Friends. Confirm search suggestions before comparing. My Characters uses characters associated with your configured owner. Played Together compares jointly observed encounters; All Recorded Matches compares independent histories. Select multiple metrics with Ctrl-click in Charts, then Draw metrics. Different metrics use separate axes. Export PNG saves the last displayed chart. Missing data and plotting errors appear visibly.

All Players includes teammates, opponents, unassigned participants and older retained sightings. Search names or Name-Realm, inspect encounter history and attendance, and view same-match numeric ranks for selected teams or class/spec groups. Historical comparisons describe archived encounters only, never population-wide WoW rankings. Unknown duration, team membership and incomplete scoreboards limit derived metrics and are shown explicitly.

Duplicate Review preserves source observations and records explicit link/unlink decisions. Confirmed duplicates contribute once to analytics; ambiguous observations stay separate for review. Archive Status and Diagnostics show storage, imports, integrity, synchronization results and unresolved evidence.

## Rated careers (v1.4 Phase 1)

Rated PvP separates character/realm certainty, game version, season, bracket and specialization. REFlex 3500/3501 can retain personal pre-rating and change; after-rating is calculated as their sum. PvP Ledger CSV can retain rating change and MMR, but not personal rating or season. Missing classifications remain unknown. Complete balanced arena rosters are required to infer 2v2/3v3; battleground size alone does not establish a rated bracket.

Career charts plot observed compatible samples. Current rating means the latest dated observation, not a live API value. Recorded peaks do not claim official season bests. Manual observations require explicit approval, timestamp offsets and documented rank citations where applicable. Corrections and reversals retain their revision history. The append-preserving `rated.sqlite` sidecar retains source evidence and can regenerate derived rows. No online leaderboard provider is configured. Later rated analytics phases are not implemented.

## Excel reconciliation

Import an `.xlsx` match log to audit source evidence without executing formulas or changing the workbook. Review exact, probable, ambiguous and missing candidates. Every supplemental link or historical import requires explicit selections and approval; it never silently overwrites addon values. Original workbook bytes, cells, formulas, cached values and decisions are retained in `supplemental.sqlite`.

Workbook character ownership is inferred from named Summary, Battleground or Arena titles sharing a sheet prefix. No particular character or prefix is built into the reader. The Python `read_workbook(..., owners={"AA": "Examplehero"})` API accepts an explicit prefix mapping for other layouts. Unsupported or unnamed layouts may require the user to clarify ownership before import.

## Exports

CSV exports include match and roster records with Unicode. Copy for Claude uses local clipboard data. Complete AI Dump exports every available local archive record, raw source observation and provenance, source bytes, relationships, identity mappings, overrides, duplicate decisions, rating information and Excel evidence. JSON and JSON.gz each produce a single file. Exporting does not upload data. Full exports intentionally retain the user's real names and statistics: store and share them deliberately outside the repository.

## Command line

```powershell
pvpledger-viewer --help
pvpledger-viewer --archive-dir "D:\Private PvP Profile" import "D:\Addon Data\PvPLedger.lua"
pvpledger-viewer --archive-dir "D:\Private PvP Profile" scan "D:\Games\World of Warcraft"
pvpledger-viewer --archive-dir "D:\Private PvP Profile" totals
pvpledger-viewer --archive-dir "D:\Private PvP Profile" diagnostics
```

Consult command help for timezone, character/realm, export and reconciliation options. Source paths containing spaces and Unicode are supported.

## Tests and build

```powershell
python -m pytest -q -W error::pytest.PytestUnraisableExceptionWarning
python -m PyInstaller --noconfirm --clean PvPLedgerViewer.spec
```

Native Tk and chart tests need an accessible desktop and a complete Tcl/Tk installation. Tests use fictional identities and synthetic fixture copies, including mixed schemas, roster anomalies, incomplete observations, Unicode, ratings, and workbook reconciliation. Test-only identity seeds are provided by `tests/conftest.py`; production defaults are empty. Protocol header references contain schema field names only.

The PyInstaller spec includes application and plotting/timezone resources, not private profiles, fixtures, archives, snapshots, exports or recordings. Review the verification report for actual test/build evidence and remaining publication blockers.

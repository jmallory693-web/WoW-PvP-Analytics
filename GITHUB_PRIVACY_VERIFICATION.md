# GitHub privacy verification

Date: October 25, 2026. Scope: verification and publication inventory only.

**READY FOR GITHUB REVIEW — the explicit source allowlist only.** No known
personal-data or code-regression blocker remains in that set. This does not
clear the existing repository directory, Git index, history, build folders,
or private development outputs for publication.

## Automated verification

One complete suite was run during this verification task:

```powershell
python -m pytest -q --basetemp=.test-tmp-privacy-verification-only -W error::pytest.PytestUnraisableExceptionWarning
```

Result: **330 passed in 105.18 seconds**, with no failures or skips. This
retains the 304 original cases and 26 previously added privacy/setup cases.
The suite includes the final fictional fixture dates, statistics and ratings,
schema handling, deduplication, native Tk/chart workflows, first-run setup,
legacy identity preservation, Unicode paths, and JSON/gzip exports.

The prior interrupted command had not executed its proposed final test edits.
The actual current files were tested as found. No application code, fixtures,
tests, configuration, or executable was changed during this verification task.
No regression fix or additional full-suite run was necessary.

## Private-data preservation

The older preservation evidence remains useful, but its hashes are not all
current. Compared with that older baseline, the profile now has 184 files
instead of 179. The archive, encounter index and settings differ; four source
snapshots and the rating-history sidecar were added. Two of 15 live addon files
also differ from that older baseline. These differences are not attributed to
the privacy cleanup or this verification task.

Read-only checks established:

| Item | Evidence |
| --- | --- |
| Current local profile | Fresh SHA-256, size and modification-time baseline: all 184 files unchanged on the subsequent check; file set unchanged. |
| Live addon files | All 15 files unchanged against the fresh hash/size/time baseline. Thirteen also match the older baseline. No game files were written or restored. |
| Main archive | Schema 2; SQLite integrity check returned `ok`. All 332 older match identities, 2,433 older roster identities and 332 older observation identities remain present. Current totals are 346, 2,505 and 346 respectively. |
| Historical evidence | All 175 older import rows, 24,847 raw rows and 450 observation-version rows remain byte-for-byte equivalent as SQL row values. Current totals are 179, 27,982 and 533 respectively. Updated projections do not imply deleted raw history. |
| Identity mappings | The original `people.json` hash still matches the older baseline. |
| Settings | Changed since the older baseline in filters, current view and setup/synchronization preferences. Unchanged against the fresh baseline. No settings were saved by this task. |
| Source snapshots | All 160 snapshots in the older baseline still exist with matching hashes. Current profile snapshots are also covered by the fresh baseline. |
| Rating history | `rated.sqlite` now exists; its integrity check returned `ok` and sidecar schema is 1. It is included in the unchanged fresh profile baseline. No rating entries or revisions were written. |
| Excel evidence | No `supplemental.sqlite` existed in the older real-profile backup or current real profile. There were no main-profile supplemental rows to migrate or remove. The original downloaded workbook still matches the pre-cleanup workbook copy by SHA-256. |

Earlier isolated-copy evidence confirmed schema-2 compatibility, an unchanged
copied primary archive and identity document, and readable complete JSON and
gzip exports containing the exact identity artifact. Fixture-only changes
after those checks do not change that application behavior. All database
inspection in this task used immutable read-only connections; no live import,
refresh, setup, recovery or export operation was invoked.

## Current source privacy audit

The audit covered the publication candidates, rather than recursively treating
private runtime folders as shareable source. It checked application code,
setup/settings defaults, tests, fixture data, documentation, packaging metadata,
and schema-only addon references. Workbook XML and document properties were
examined inside the XLSX container; binary packaging alone was not treated as
proof of privacy.

No candidate matched the checked original private names, configured identity
IDs/character mappings/display labels, account identifier, private realms,
absolute Windows user paths, email addresses, or high-confidence credential
signatures. Fixture participant fields were checked separately: captured names
are fictional named examples or generated player identifiers, including all
365 REFlex participant entries. No screenshots, recordings, private profiles,
source snapshots, databases or AI exports are candidates.

Production identity defaults are empty `Me` and `Unassigned` groups. Personal
ownership comes from local configuration. Legacy IDs and labels are retained;
first-run configuration is optional and is not forced onto existing profiles.
Test-only identities remain confined to the tests. Common fictional display
names and accented Unicode test examples are not live identity mappings.
WoW classes, specifications, map vocabulary, addon field names and IANA
timezone identifiers are legitimate format/test content, not private findings.

The Lua and workbook fixtures contain fictional identities, shifted chronology
and regenerated gameplay values while retaining required schema/anomaly
relationships. See `tests/fixtures/SYNTHETIC_DATA.md`. Original source copies
and detailed private verification evidence remain outside the publication set.
Full runtime AI exports intentionally retain the requesting user's actual data;
the export implementation is shareable, generated exports are excluded.

## Publication inventory and exclusions

`PUBLICATION_INVENTORY.json` contains the exact **91 content files**, their
sizes and SHA-256 digests. Include those files plus the inventory itself:
**92 files total**. Its self-entry deliberately has no recursive self-digest.
Use these explicit paths when preparing a separate clean repository. Do not
copy the entire working directory or reuse the existing staging index.

| Included category | Files |
| --- | ---: |
| Application Python modules | 61 |
| Packaging launcher | 1 |
| Tests and fictional fixtures, including fixture documentation | 22 |
| Schema-only Lua reference fixtures | 2 |
| README, project metadata, build spec, ignore rules | 4 |
| This verification report | 1 |
| Publication inventory | 1 |

Everything not explicitly listed is excluded. In particular:

- Existing `.git` history, index, configuration and remote metadata.
- All local application profiles, databases, journals, identities and settings.
- Original addon archives, SavedVariables, source snapshots and real workbooks.
- AI/CSV exports, personal reports, screenshots, recordings and backups.
- Build outputs, executable packages, dependency environments and caches.
- Local logs, detailed verification results and private workspace pointers.
- All test-output directories, including the 16 permission-protected folders.
- One-time migration, backup, deployment and historical-audit scripts in
  `tools/`; they are not required by the application or the tests.
- Credentials and local environment files.

The protected test-output folders may remain on disk. No permission changes,
moves, deletion or cleanup of those folders were attempted during this task.
Ignore rules are supplementary; the publication allowlist is authoritative.

## Packaging and prior GUI evidence

The installed EXE still matches the previously recorded final package hash:

`ed1a6d25f2bae84b5109af7807ac804ea0a17ad4949aaacebb9ababe4326497d`

Previous evidence records a 2,568-file windowed package, optional setup with
Unicode owner/friend entry, empty-state rendering, selected addon-file import,
zero additions on repeated Refresh, setup scrolling at 1280-by-720 client
geometry, and a validated compressed complete AI export. These are historical
GUI checks, not desktop actions repeated during this verification-only task.
No executable rebuild, shortcut launch or other deployment change was made.

## Remaining scope boundaries

There are **no known blockers for review of the listed source files**. The old
repository's private history is explicitly excluded. The user reports deleting
the old GitHub repository; remote state was not checked. Git history was not
inspected again, rewritten or copied into the inventory during this task.

A later, separately authorized step must create a new repository using only
the allowlist. Existing private outputs on disk and the old Git directory are
not cleared for publication. No repository was created, no files were staged
or committed, and no upload, push or publication occurred. No later analytics
phase or unrelated feature work was started.

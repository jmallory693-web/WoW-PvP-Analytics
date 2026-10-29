# Source synchronization verification

Date: October 29, 2026.

## Source comparison

The local application identifies as PvP Ledger Viewer 1.4.0. All 92 approved
local publication files match published main at 2200af6, allowing only Git
checkout line-ending conversion. No additional application, packaging,
reference, test or fixture files were found outside the local allowlist.

The newer published hotfix at 80f95fd adds schema 6/7 CSV handling, retained raw
fields, fictional regression fixtures and 25 regression cases. Its eight-file
change is retained in full. Older local files were not copied over it.
The synchronization branch descends from the published hotfix and contains
no commits from the private local repository.

## Privacy verification

Reviewed PUBLICATION_INVENTORY.json and GITHUB_PRIVACY_VERIFICATION.md.
Used a fresh clone of the published repository. Its 94 tracked files exactly
matched the hotfix allowlist before adding this report. All inventory hashes
matched after accounting for LF/CRLF conversion.

Scanned all 124 reachable Git objects, including both published commits and
source blobs, for configured private identity values, Windows user paths,
email addresses and credential signatures. No private identity, path or
credential findings occurred. Commit email matches were existing GitHub
noreply identities. A raw compressed XLSX byte match was checked separately:
all decompressed workbook members, including XML and document metadata, were
clear. The schema 6/7 fixture contains only fictional protocol examples.

No personal archives, SQLite databases, SavedVariables, account identities,
character mappings, recordings, screenshots, exports, private logs, local
Git history or executable/build output are in the publication set. No local
working source, installed executable, live profile or game files were changed.
The newly committed report contains no private audit detail. New commit
metadata uses the existing public GitHub noreply identity.

## Validation

The first sandbox run could not access pytest temporary directories:
162 passed and 193 setup errors. This was an environment permission issue.
The full command was rerun with Python 3.12.10 outside that restriction,
using existing dependencies and importing application code from the fresh clone.
Result: **355 passed, 0 failed, 0 skipped in 103.78 seconds**. One nonfatal
pytest cache-write warning remained; no test failed. The command was
`python -m pytest -q`.

No redesign, application behavior change, archive migration or executable
rebuild was performed. Only this report and the inventory were added or
updated on top of the existing schema 6/7 hotfix.

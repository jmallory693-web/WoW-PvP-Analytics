# Fictional parser and archive scenarios

These files are test data, not a user's game archive. Identities and realms are
fictional. Event dates have been shifted, and combat totals, counts, equipment,
ratings, scores, honor, and source metadata values have been regenerated.
Free-form source notes, traces, addon settings, and unrelated private tables
were removed. Original developer records are retained only in a private backup
outside the proposed source set.

The scenarios retain addon schema shapes and structural anomalies needed by
the existing regression cases: duplicate roster sightings, multiple snapshots,
orphan recovery, missing fields, Unicode, ambiguous links, and incomplete
scoreboards. Structural participant counts and attendance relationships remain
deliberate test inputs. Results and map/class/spec vocabulary are fictional
scenario inputs using legitimate addon values.

Expected scenarios include:

- Legacy PvP Ledger: 7 complete and 3 partial logical matches, 211 deduplicated
  roster rows, 4 wins and 3 losses. Reimport adds zero records.
- Dual-addon set: 118 raw observations, 94 canonical matches under the fixture's
  recording timezone, 24 confirmed overlaps, 3 ambiguous pairs, and 11 matches
  with deliberately conflicting source fields.
- Schema 5: 41 matches and 835 normalized roster rows.
- Rated REFlex sample: 30 participant observations. Fictional own Shuffle
  ratings progress from 0 to 891 to 1083, with a retained zero-change sample.
- Workbook: 13 sheets, 200 match rows, 413 roster rows, and 796 nonempty rows.
  It preserves formula text and unavailable caches without executing formulas.

The application does not install or load these fixtures for new users. The
test-only comparison profile is supplied by `tests/conftest.py`; production
identity defaults contain only empty Me and Unassigned groups. Some test
function names retain historical wording to preserve regression case identity.

The `v1_3_4` fixture contains one schema-6 and one schema-7 match, with
four fictional roster entries. It follows the verified 48-column match and
21-column roster headers, including signed rating changes, Epoch, Queue type,
Unicode and quoted CSV fields. No live SavedVariables rows were copied.

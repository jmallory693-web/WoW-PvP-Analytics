# Chart appearance and verification

Baseline: Step 3 commit `ebcc228`, recorded before Step 4 changes.

## Existing Classic rendering

| Renderer | Original appearance and sizing |
| --- | --- |
| `pvpledger_viewer/charts.py`: `draw_chart`, `export_png` | Trends: figure `#0c1420`, plot `#0e1928`, title/axis labels `#e7edf5`, ticks/grid `#a3b2c5`, spines `#304460`. Grid alpha .15. Six categorical colors: gold, teal, blue, rose, lavender, orange. Circle markers, existing solid/downsampled line behavior. Legend panel `#142131`, text `#e7edf5`, size 7. PNG 13 by 7 inches at 120 dpi. |
| `pvpledger_viewer/comparison_charts.py`: `draw`, `export_png` | Same figure/plot and six-series colors as Trends; size-3 circle markers. Metric titles size 10, muted axis/tick labels size 8, grid alpha .12. Legend size 7, original matplotlib spine/grid defaults. One axis per metric, tight layout padding 2. PNG 13 by 4 inches per metric at 120 dpi. |
| `pvpledger_viewer/rated_charts.py`: `figure` | Rated progression: figure `#0b1420`, plot `#142131`, observed points `#d5b76d`, no connecting lines. Title/text/ticks `#e7edf5`; title size 9, ticks size 8, grid alpha .18 and original matplotlib grid/spine defaults. One axis per cohort, original date labels/rotation, tight layout padding 2. Figure 10 by max(3, 2.8 per cohort) inches at 100 dpi. Existing dialog export uses 150 dpi and the resized displayed figure. |

All three retain matplotlib's original font configuration. Trends hover labels
use the original light rounded box, black default text, and size 8.
No bar-chart renderer is present in the application.

## Chart consumers

- `ui/trends.py`: embedded Trends dashboard, hover details, and trend PNG export.
- `ui/advanced_comparison.py`: embedded single-metric advanced comparison preview.
- `ui/comparison_dialog.py`: Character Comparison and Trends comparison dialogs,
  multiple metric axes, and export of the displayed model/metric snapshot.
- `ui/rated.py`: Rated PvP progression dialog and its PNG export.

Window layouts, figure sizes, export resolution, metrics, date interpretation,
labels, legends, filtering, null gaps, downsampling, rank-axis inversion, and
rating observations are outside the styling change.

## Step 4 implementation

The UI resolves its already-applied startup palette on the UI thread and passes
that read-only mapping to chart rendering and export. Classic passes `None`,
which leaves the original plotting configuration intact. The standalone Python
render/export APIs also retain Classic as their backward-compatible default.
Saving a new preference does not change charts until the existing restart flow.

`chart_style.py` changes only local figure/artist properties. It imports no Tk,
sets no rcParams/backend/global style, changes no model values, and creates no
new figures. Warband uses the existing BG/PANEL/TEXT/MUTED/BORDER tokens for
surfaces, labels, spines, grids and legends. Existing fonts and sizes remain.
Series use existing palette roles plus different marker shapes. The primary
win-rate series uses POSITIVE; death metrics use NEGATIVE and neutral roles,
not crimson. Rating observations remain neutral categorical points, not new
gain/loss calculations. Hover boxes use SELECTED with TEXT and BORDER.

The legacy Classic literals intentionally remain in their original renderers;
no new hexadecimal color literals were introduced into chart functions.

## Verification, October 30, 2026

- Full Windows command `python -m pytest -q`: **373 passed, zero failures,
  skips or errors**, one known pytest cache-permission warning, 140.69 seconds.
- Four focused cases cover both themes: identical plotted data, null gaps,
  titles/labels/legends, scales, original line-joining behavior, PNG generation,
  export sizes and opaque backgrounds, repeated draws and empty states,
  unchanged rcParams, and no pyplot figure-manager growth.
- Native UI checks cover routing the actual startup palette through embedded
  Trends, advanced comparison preview, multi-metric comparison dialogs, rated
  progression dialogs, and all three UI PNG-export workflows.
- Original Classic baseline PNGs were generated before renderer edits, then
  visually compared with Step 4 Classic outputs. Original fonts, colors,
  categorical distinctions and dimensions were retained. There are no
  pixel-perfect/color-value assertions in the regression tests.
- Warband and Classic were inspected in Windows at 1280 by 720 and 1600 by
  900 across the chart views/dialogs. Trends was also switched from Warband to
  Classic through Settings and a real process restart; no stale styling remained.
- Multi-series/multi-metric PNGs were inspected in both themes. A Warband PNG
  was opened in Windows Paint; its backgrounds and labels remained readable.
  Trends PNGs remain 1560 by 840, two-metric comparison PNGs 1560 by 960,
  and the original rated export dpi/resizing behavior remains unchanged.
- Only fictional fixtures and separate disposable profiles/exports were used.
  The installed executable's SHA-256 still matches the pre-existing baseline.
  No executable was rebuilt, no private profile/addon file was changed, and
  no branch was pushed or merged.

## Retained limitations

The existing fixed-offset Trends hover box can extend beyond the right edge
when hovering the final point. Its positioning and interactions were preserved.
Compact previews and long multi-metric dialogs keep their original layouts and
scrolling behavior. There is no bar-chart implementation to verify.

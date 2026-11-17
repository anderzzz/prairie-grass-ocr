# Volume II: tables, conventions and checks

Volume II (`rawdata/PGrassVolumeII.pdf`, 222 pages, one 1-bit 300 dpi image per
page like Volume I) holds no concentration data. Its tables are meteorological;
the inventory is `config/volume2_pages.yaml`. The harmo.org reference covers
none of them, so quality control is by internal consistency (below), not by an
answer key.

Pipeline: `make volume2` = Mistral OCR per page (cached, same preprocessing as
Volume I; 11.3 is rotated upright) -> per-table parsers (`src/volume2/`) ->
`output/volume2/extracted/table_<id>.csv` (one row per printed cell) ->
`output/volume2/checks/suspects.csv`.

## Printed conventions (kept as printed, never "corrected")

| Token | Meaning | Status |
|---|---|---|
| `--` | missing ("missing data due to instrument failure", Table 10.1 legend) | `missing` |
| blank | nothing printed (e.g. rawinsonde height between standard levels) | `not_printed` |
| `(x)` | estimated value (Table 10.1 legend) | `value`, `estimated=True` |
| `x*` | value with a footnote; footnote text kept per page | `value`, `footnote=True` |
| `>100` | relative humidity above 100 % (Table 13.1) | `value`, kind `above` |
| `a to b` | a range (Table 11.1) | `value`, `value_lo`/`value_hi` |
| `MB` | rawinsonde humidity "motorboating" (too dry to measure) | `text` |
| words (`rain`, `Calm`, `No Data`) | printed notes in value cells | `text` |
| `#` column, 13.1 | two-figure trace code (legend, printed p.177); a code, not a number | `code` |

Other facts established while parsing:

* Table 8.1/8.2 CST values marked `*` belong to the date in the page footnote
  (the next day).
* The precipitation row is printed below the table frame; it is read from its
  own strip (Mistral). 37 of 42 pages read as all `--`; 5 are `unread`.
* Table 9.1's last column ("R_n + Σq_i") equals **−(R_n + Σq)** as printed, in
  every release; the check uses that relation.
* Table 9.2 = 0.06 × Table 9.1 (q_c, q_e, q_s, R_n): Table 9.1 is in
  10⁻³ cal cm⁻² s⁻¹ although headed "Kcal/cm² sec"; the unit is recorded as printed.
* Table 13.1 field-test numbers follow the releases, but the flights were not
  made at release times; they are not used as release keys.
* Table 13.1 field tests 23–24 and 31–36 are not printed (all 61 printed blocks
  are parsed).

## Checks (`src/volume2/checks.py`)

Tolerances come from the printed precision or from the measured spread of the
residuals (the 99.5th percentile), not from the data being "right":

| Check | Relation |
|---|---|
| format | every value has its column's printed shape (e.g. radiation `.0183`, wind `321`) |
| 9.1-sum | Σq = q_c + q_e + q_s; last column = −(R_n + Σq) |
| 9.1-9.2 | Table 9.2 = 0.06 × Table 9.1; the 9.1 sum decides which side is suspect |
| 13.1-humidity | e = e_s(Td) (within 0.5 mb; 90 % agree within 0.13) and RH = e/e_s(T) (4.5 points) |
| 13.1-hypso | pressure and height may not contradict (climb with rising pressure, factor > 2) |
| 12.1-hypso / order | standard-level heights from P and virtual T (25 m or 3 %); P decreasing, wind heights increasing |
| 8.x-profile / time | air profiles smooth in ln z (0.5 °C, 0.5 mb, 20 % wind); hourly continuity; soil by time only |
| 8.x-radiation | reflected/insolation in 0.03–0.45; net ≤ insolation |
| keys | the same release has the same date/time (±3 h) in 8.1, 10.1 and 12.1 |

Mistral's word confidence barely predicts check failures in this volume
(cells below 0.99 fail a check at 0.8 % against 0.65 % for the rest), so only
cells below 0.95 are flagged for it; the confidence is kept in the output.

A failed check lists the cells involved; it never proposes a value. Suspects
go to a second reading and to the owner, as in Volume I.

## Second reading, review and errata

Rows holding a cell involved in a failed check (235 rows on 70 pages) were cut
from the page and read again by Sonnet (`src/volume2/second_read.py`, 88 calls,
$0.36, cached in `cache/reader_llm`; Sonnet is not shown Mistral's reading).
Of 513 involved cells, 413 read the same, 95 differ, 5 got no usable strip.
The owner's review pack (`make volume2-review` -> `review/volume2/index.html`)
holds the 95 differences (group A, with whether the failed checks pass under
Sonnet's reading), the cells nobody re-read (B: strips that missed, five
precipitation rows, two structural problems) and the failures where both
readers agree (C, default "printed as such").

Owner decisions on smudged header keys, and errata (a printed value the owner
reads as a typing error in the original: the token is kept, the
interpretation is stored next to it), are in `config/volume2_keys.yaml`.

Dataset: `DATE=yyyy-mm-dd make volume2-dataset` converts the exported verdicts
to `config/review/volume2_verdicts.csv` and writes
`output/volume2/dataset/table_<id>.csv`; until then the build marks open cells
`pending`. Table 13.1 remarks are kept as read by Mistral and flagged
"unverified transcription" (owner decision).

Review of 2026-11-16: the owner ruled on 49 of the 95 differences and left 46
open ("choose whichever"). Open ones are settled by a fixed rule that only
ever picks one of the two readings: the reading under which the failed checks
pass, if exactly one does and it is well formed (24 cells, `quality=rule`);
otherwise Mistral's, marked `doubtful` (22). On the 47 differences the owner
did rule between the two readers, this rule agrees with the owner 40 times. One cell the
owner marked illegible (`status=illegible`, no value).

Every dataset cell carries `quality`: `owner`, `two_readers`, `single_reader`
(no check involved it), `printed_inconsistent` (owner: printed as such, still
fails a check), `context` (Table 8.1 follow-up, below), `rule`, `doubtful`,
`illegible`, `unread`.

## Follow-up: full second reading of Tables 8.1 and 8.2 (2026-11-17)

Data users found Table 8.1's 1 m direction for release 40 (106) 74 deg off
Table 6.1 and the plume. The print says 166, and only Mistral had read that cell.
In this print 0, 6, 8 and 9 are easily confused when worn. So every row of Tables 8.1
and 8.2 was then read by Sonnet as well (`second_read.py`, `FULL_TABLES`; 224 new
calls, $1.38). These calls are separate from the check-row calls, so the earlier
readings stayed cached. Where Mistral's grid has empty trailing columns, Sonnet's
shorter rows are padded instead of being dropped.

Disagreements are settled by `volume2.followup` into
`config/review/volume2_followup.csv`, which `volume2.dataset` applies after the
review verdicts:

* Cells already ruled in the 2026-11-16 owner review are left alone.
* Strip shifts: where Sonnet's strip straddled rows, its row reproduces Mistral's
  row above or below (all of page 100's lower soil rows, much of page 96).
  These cells get no second reading (`single_reader`, Mistral kept), and that
  includes cells that "agreed" only by coincidence.
* Decimal point only: the column's printed format decides (a zero is printed
  `00`).
* Otherwise context decides (`quality = context`). Each candidate is compared with
  the interpolation between the levels above and below (ln z for air, depth for
  soil) and, in 8.2, with the mean of the neighbouring hours. A residual counts
  only in units of that quantity's typical scatter. The other reading has to be off
  by more than 4 units while the chosen one is at most half as far off, and no
  axis may fit neither reading.
* If nothing decides, Mistral's reading is kept with `quality = doubtful`.
* Decisions made by hand on Table 8.1 (`config/review/volume2_followup_hand.csv`)
  are kept.

Third readings were tried and are not used to decide. Each disputed cell was
cropped and shown with only the two candidates, in random order, to Sonnet
(`volume2.adjudicate`, 409 calls, $1.87) and, on the 96 cells where context is
unambiguous, to Opus ($1.10). Both contradicted the profile about as often as they
agreed: Sonnet 22 agree to 42 contradict, Opus 30 to 43. Both called worn 9s and 6s
"clean 0s", e.g. 408 for 498 between 540 and 452. The scan is bilevel, so a worn 9 or 6
loses its inner stroke and becomes an oval. "It looks like a 0" is therefore no
evidence, while a hook or tail that is present is. Their verdicts are kept in
`value_source` as information (`output/volume2/second_read/adjudication*.csv`).
For the same reason, three hand decisions on Table 8.1 that rested only on an
"oval" were downgraded to doubtful.

Result:

* Table 8.1 (2,982 cells): 2,775 `two_readers`, 45 `context`, 59 `doubtful`,
  61 `single_reader`.
* Table 8.2 (7,428 cells, before this almost all `single_reader`): 6,818
  `two_readers`, 114 `context`, 188 `doubtful`, 222 `single_reader`.
* Values changed from the previous release: 17 in 8.1 (9 of them `.00` to `00`) and 10 in 8.2,
  e.g. 409 to 489 (8 m wind) and 22.40 to 23.40 (soil temperature at -0.12 m; the
  neighbouring hours read 23.4).

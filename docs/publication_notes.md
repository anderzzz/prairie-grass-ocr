# Publication notes: issues and judgment calls

Working notes for the Hugging Face blog post and the machine-readable notes file that
will ship with the data. Compiled 2026-11-19 from `REPORT.md`, `docs/volume1s.md`,
`docs/volume2.md`, `config/suspect_values.yaml`, `config/volume2_keys.yaml`,
`config/review/*` and the built datasets. Counts are from the current build.

Guiding principle, to state up front: **every value is what the page prints.** Nothing is
interpolated, smoothed or corrected. Where we think the print is wrong, the printed token
stays and our interpretation sits beside it in a separate column.

---

## 1. Errors in the reference transcription (harmo.org, J. S. Irwin)

**Provenance of what we compared against.** Fetched once on 2026-11-13 16:24 UTC by
`scripts/fetch_reference.py`; checksums in `scoring/reference_checksums.json`:

| File | URL | Bytes | SHA-256 | Internal dating |
|---|---|---|---|---|
| `PGARCS.txt` (Table 5.2, arcs) | https://www.harmo.org/jsirwin/PGARCS.txt | 388,856 | `36a12bc9…0147c8` | none; header line "Project Prairie Grass" only |
| `PGVertConc.txt` (Table 5.3, towers) | https://www.harmo.org/jsirwin/PGVertConc.txt | 46,036 | `7d7f6f61…e571b` | "August 9, 2010" |
| `D6589_UGDesign2_Table_2.pdf` (format description) | https://www.harmo.org/jsirwin/D6589_UGDesign2_Table_2.pdf | 48,047 | `0b2a1c7c…7123a1` | PDF metadata: author "jirwin", created 2009-12-31 |

These are John S. Irwin's files hosted under `/jsirwin/` on harmo.org (the Initiative on
Harmonisation within Atmospheric Dispersion Modelling). The PDF name refers to ASTM
D6589, the standard guide for statistical evaluation of dispersion models. The files
themselves don't say how the values were keyed; we only know what's in them. The towers
file states its own conventions: -9 = missing, 0.0 = no measurable concentration, runs 70
and 71 = 35S and 48S. Only Volume I Tables 5.2 and 5.3 have a reference; nothing was
compared for Tables 5.1, 5.4, 6.1 or Volume II.

These files were used only to find cells worth a second look. The build never reads them (enforced by
`tests/test_isolation.py`).

- **Overall:** 159 cells in Volume I where our reading and the reference disagreed were
  reviewed by the owner against the scan. In about 119 the reference is wrong; it was right
  in 40 (where Mistral misread).
- **Column copy, run 7, 100 m arc (PDF 106, posts 46+):** the reference repeats the 200 m
  column in the 100 m slot (22 of 27 values identical). The print shows different values.
- **×10 slips:** scattered order-of-magnitude differences (e.g. 2.69 vs 0.269, 0.090 vs
  0.900) where the print is clear.
- **Blank coded as missing:** the report says blank = "no measurable concentration" and
  M = missing (Vol. I pp. 79, 193). The reference codes some printed blanks as -9 (missing):
  42 cells in Volume I.
- **Blank vs printed zero:** the reference stores 0 for blank, so it cannot distinguish
  the two printed explicit zeros (run 1, 800 m post 31 `0.000`; run 30, 800 m post 98 `0`).
- **Unit label:** the arcs-file header suggests µg m⁻³, but the values are in the printed
  mg m⁻³ (median ratio 1.000 over 1,270 pairs).
- **Same 0/6 confusion as the OCR:** several reference errors look like OCR or hurried
  keying of the same worn glyphs.
- **Ambiguous, not proven wrong: run 61, 800 m arc (PDF 196).** The printed values drift
  off the post grid, many sitting between two post numbers. Our one-to-one assignment is
  self-consistent (38 values for posts 95–132); the reference assigns some differently. The
  owner sided with our assignment in 24 of 25 cells.

> **Note (2026-11-19):** this is *not* the Aarhus University Excel workbook
> (`PrairieGrass.xls`, envs.au.dk "excelprairie" page, linked to Olesen, Berkowicz &
> Løfstrøm 2007, "Evaluation of OML and AERMOD"). That workbook was never downloaded or
> used in this project; the repo history has no trace of it. Every reference comparison
> above is against harmo.org only. The errors listed here should not be attributed to the
> Aarhus workbook unless we check it separately.

## 2. Suspected errors in the original 1958 report ("fat finger")

Print is clear and all readers agree, but the value contradicts its neighbours or another
table. Kept as printed; flagged with `suspect = True` and a `suspect_alternative` (Vol. I),
or as an `erratum` (Vol. II).

| Where | Printed | Likely intended | Evidence |
|---|---|---|---|
| Table 5.2, run 44, 800 m, post 69 | 9.565 | 0.565 | 18× neighbours (0.505, 0.575); only four-figure value in the column; would make the 800 m peak 3× the 400 m peak |
| Table 5.2, run 10, 800 m, post 127 | 0.90 | 0.090 | 12× neighbours; only two-decimal value in a three-decimal column |
| Table 6.1, release 60, time | 0135 | 0025 | Table 8.1 0035; Table 5.2 header 0030–0040; every other release is 10 min before 8.1 |
| Table 6.1, release 61, date | blank (= 26 Aug.) | 27 Aug. | Table 8.1 and Table 5.2 header |
| Table 6.1, release 62, date | 26 Aug. | 27 Aug. | as above; date probably printed one column too far right |
| Table 10.1, release 45, time | 1200 | 1700 | Table 8.1 (1705), Table 12.1 sounding (1658) |
| Table 9.1 heading | "Kcal/cm² sec" | 10⁻³ cal cm⁻² s⁻¹ | Table 9.2 = 0.06 × Table 9.1 throughout. Unit recorded as printed |
| Table 9.1, last column | headed "R_n + Σq_i" | −(R_n + Σq) | holds for every release |

Beyond these, **cells the owner confirmed are printed as such but still fail a consistency
check** carry `quality = printed_inconsistent`: 25 (8.1), 54 (8.2), 152 (13.1), 17 (12.1),
11 (6.1), plus single cells in 9.1, 9.2 and 10.1.

**Not an error, though it looks like one:** runs 14, 39 and 40 have a Table 6.1 source
wind speed 36–48 % above Table 8.1's 2 m speed (every other run within 12 %). All three
are light-wind nights with smooth profiles; we read this as an instrument difference.
Kept as printed, `printed_inconsistent`.

**Excluded table:** Table 11.3 (Δ(∂T/∂z) at 12 cm) carries hand corrections in the
original. Left out of the dataset; the raw parse is in `output/volume2/extracted/`.

## 3. Smudged or unreadable print: honest N/A and inferred keys

- **Illegible value:** one cell, Table 13.1 (field test 38, 12 Aug., relative humidity),
  `status = illegible`, no value.
- **Doubtful values:** readers disagree and nothing (owner, context, checks) decides;
  Mistral's reading kept with `quality = doubtful`. One cell left after the owner
  reviews of 2026-11-23 (was 265): Table 13.1 field test 38, 12 Aug., 630 ft, vapour
  pressure, faded in the print (Mistral 20.7, Sonnet 26.7).
- **Second owner review (2026-11-23):** 388 items (265 doubtful readings, 123 outliers).
  357 verdicts applied (`config/review/round2_verdicts.csv`, export kept as
  `round2_export.csv`): 237 doubtful readings settled (103 values changed), 119 outliers
  confirmed as printed, 4 outliers found to be misreadings (e.g. Table 13.1 field test 67
  dew point 1.2 -> 7.2, which also clears that row's humidity check). Not applied: 22
  undecided (19 "can't tell", 3 blank), 7 where the review image boxed or showed the
  wrong cell (`HOLD` in `src/publish/round2.py`), 2 open questions (`ASK`: release 16
  insolation `0183`, Table 8.2 7 Aug. 1105 net radiation `0130`).
- **Third owner review (2026-11-23):** the 31 items round 2 left open, shown afresh by
  `src/publish/review_round3.py`: no drawn box; column heading and ~3 rows either side,
  the row marked only where its printed label was read, crops straightened where the
  page is typed at a slant (PDF 94 about 1 line, PDF 96 about 1.8 lines across the
  table, the cause of the round-2 misplacements). 30 verdicts applied
  (`config/review/round3_verdicts.csv`, export `round3_export.csv`): 27 doubtful
  readings confirmed as Mistral read them (no value changed), the PDF 100 soil outlier
  `.12` confirmed as printed, and the two decimal-point questions ruled as misreadings
  (the point is printed, faintly): release 16 insolation `.0183` (previously recorded as
  a printed `0183`, a suspected missing decimal point) and Table 8.2 7 Aug. 1105 net
  radiation `.0130`. Both now pass every check, and so does the 7 Aug. insolation `.0192`
  beside it. One "can't tell" remains doubtful.
- **Inferred run key, run 66 (PDF 200):** header unreadable (Mistral read "86"). Keyed by
  page order (half B of run 66 is PDF 201). Independently supported: 269 of 270 cells
  then match the reference. `key_source` says "inferred".
- **Smudged date headers, Volume II:** Table 8.2 PDF 97 date set to 8 Aug. (read
  "August 9"; page sits between two 8 Aug. pages). Table 8.1 release 29 date set to
  3 Aug. (read "5"; Tables 10.1, 12.1 and release order give 3 Aug.).
  > **Settled (2026-11-23):** the owner confirmed 3 Aug. against the scan.
- **Table 13.1 free-text remarks:** kept as Mistral read them, marked "unverified
  transcription", not reviewed cell by cell.
- **Faint column rules (Vol. I):** seven pages needed a column template to place cells;
  those cells carry a "column bound inferred" flag.

## 4. The 0/6 problem (and 3/8/9)

- The typeface prints 6 with a weak or broken top loop. The scan is bilevel (1-bit,
  300 dpi native; no better pixels exist), so a worn 6 or 9 loses its inner stroke and
  becomes an oval that reads as 0. 3, 8 and 9 blur together the same way.
- Every reader we tried makes this mistake: Tesseract, EasyOCR, Mistral OCR, Claude
  Sonnet and Opus. Examples: 161 read as 16; 6.68 as 0.68; Table 8.1 release 40 wind
  direction 106 for a printed 166 (found by data users, 74° off the plume); 8.2 8 m wind
  409 for 489; soil temperature 22.40 for 23.40.
- **LLMs as glyph judges do not help.** Shown only the crop and the two candidates, Sonnet
  contradicted an unambiguous profile 42 times vs 22 agreements; Opus 43 vs 30. Both
  confidently call worn 6s and 9s "clean 0s". Those verdicts are kept as information only.
- **What we did:**
  - Volume I concentrations: every cell where Mistral and the reference disagree went to
    a Sonnet reading and then the owner (159 cells; 25 values changed).
  - Volume I Tables 5.1, 5.4, 6.1: every cell read independently by Mistral and Sonnet;
    1,428 of 1,438 agreed, the rest ruled by the owner.
  - Volume II Tables 8.1, 8.2: every row read by both. Disagreements settled by context
    (height profile in ln z, neighbouring hours, other tables): `quality = context`
    (45 + 114), otherwise `doubtful`. Context decisions were made by Claude under the
    owner's method, not by the owner.
- **What remains (the caveat to state plainly):**
  - In Volume I, a cell that Mistral **and** the reference misread the same way was never
    surfaced. Plausible precisely for 0/6.
  - In Volume II, all tables other than 8.1/8.2 are mostly `single_reader`: only cells
    involved in a failed consistency check got a second reading. A 0/6 slip that breaks no
    check is invisible.
  - Many such slips are small next to the measurement uncertainty; a 0/6 in a leading
    digit is not.
  - Estimated rate of unflagged real misreads in Volume I: below 1 in 600 cells.

## 5. Judgment calls (conventions we chose)

- **Blank ≠ missing ≠ zero.** `status` is derived only from the printed token, following
  each table's own legend (Table 5.4 uses the opposite convention: blank = missing).
  Printed zeros stay as 0.0.
- **Nothing corrected.** Suspected errors, errata and printed inconsistencies keep the
  printed token; our reading sits in separate columns.
- **Evaporation correction factors (Table 5.4) not applied** to the concentrations; shipped
  separately.
- **Units as printed,** even when the heading is wrong (Table 9.1).
- **Table 6.1 dates:** a blank date cell repeats the date to its left (carried forward,
  printed token kept). Join on `release`, not date.
- **Run labels are strings:** 35S and 48S are distinct from 35 and 48.
- **Undecided owner verdicts default to Sonnet's reading** (Volume I; in all 39 such cells
  Sonnet and Mistral agreed).
- **Open Volume II differences settled by rule:** 46 cells the owner left open; the reading
  under which the failed checks pass (`rule`, 24) or Mistral (`doubtful`, 22). On 47 cells
  the owner did rule, this rule matched the owner 40 times.
- **Strip shifts:** where Sonnet's row strip straddled rows, its reading is discarded (no
  second reader), even where it "agreed" by coincidence.
- **Pipeline flags are not cleared by review.** About 8 % of arc cells and 18 % of tower
  cells carry a flag; they are doubts, not errors.
- **Outlier screen marks, never removes** (Volume II: 125 cells flagged).
- **Analysis-side choices live in `notebooks/pgdata.py`, never in the data** (e.g.
  radiation above the solar constant dropped, Ri_b fallback to 4 m).
- **Mistral OCR as primary reader** (98.2 % vs 83 % for the best offline reader on dev
  pages); offline readers kept as a cross-check. Model pinned, all raw responses
  committed, so the dataset rebuilds without any API.

## 6. Quality labels in brief (for the data card)

| Quality | Volume I concentrations | Volume I small tables | Volume II |
|---|---|---|---|
| owner-reviewed | 162 | 9 | 459 |
| two independent readers | n/a (offline cross-check) | 1,350 | 9,689 |
| context-decided | | | 157 |
| rule-decided | | | 24 |
| doubtful | | | 1 |
| printed_inconsistent | | 11 | 245 |
| illegible | | | 1 |

## Next steps

- ~~Settle the release 29 date~~ (settled 2026-11-23: 3 Aug.).
- Re-check the LLM glyph-judge experiment (section 4) before citing it: its crops came
  from `volume2.adjudicate.cell_images`, the locator that misplaced round-2 boxes on
  sloped pages, so some judged crops may have shown the wrong cell.
- Decide whether to compare against the Aarhus `PrairieGrass.xls` as well (see the note
  in section 1).
- Machine-readable companions (built 2026-11-19):
  - `output/publish/annotations.jsonl` (`make annotations`): 452 statements (724 before the owner reviews of 2026-11-23) on our data,
    one per line, keyed by file + `cell_id` (or a row selector / whole table), with
    category, printed token, alternative, evidence, decided_by, date. Category glossary in
    `output/publish/annotation_categories.json`. `tests/test_annotations.py` checks it
    agrees with the dataset columns.
  - `output/publish/reference_comparison.csv` (`make reference-comparison`): the 201
    Volume I cells where the dataset and the harmo.org files differ or differed before
    review, with the difference type and who was right.
- Worth a line in the post: for run 44, 800 m, post 69, the reference holds 0.565, the
  value we suspect was intended, where the print clearly says 9.565. Irwin's keying
  either silently corrected the misprint or came from another source.

# {{title}}

Version {{version}} ({{date}}) · {{creators}} · Licence: CC BY 4.0

This dataset is a cell-by-cell transcription of the data tables in **Project Prairie Grass, A Field
Program in Diffusion** (M. L. Barad, ed., 1958; Geophysical Research Papers No. 59, Volumes I and II,
Air Force Cambridge Research Center). In July and August 1956, sulfur dioxide was released near the
ground near O'Neill, Nebraska, and sampled on arcs 50 to 800 m downwind. The micrometeorology was
measured at the same time. The experiment is one of the standard data sets of near-field dispersion
modelling.

It was transcribed afresh from the scanned report. It is not derived from earlier transcriptions;
it was compared against one of them (see [Differences from earlier transcriptions](#differences-from-earlier-transcriptions)).

**The guiding rule: every value is what the page prints.** Nothing is interpolated, smoothed or
corrected. Where we think the print is wrong, the printed token stays and our interpretation sits in
a separate column, with its evidence.

## Contents

{{file_table}}

Plus:

- `datapackage.json`: a [Frictionless Data Package](https://datapackage.org/) that describes every
  file and column, with types, units, the allowed values of `status`, `quality` and similar columns,
  and the primary keys.
- `annotations/annotations.jsonl`: {{n_annotations}} statements about specific cells, rows or tables
  (see [Annotations](#annotations)).
- `annotations/annotation_categories.json`: what each annotation category means.

## How to read the files

Each table is in **long format, one row per printed cell**, including blank cells, because a blank
means something in these tables. Two rules matter:

1. **Treat only an empty field as missing, and use `status` for meaning.** An empty `value` only says
   that there is no number. Whether the cell was blank, printed as missing, or text is in `status`.
   Tokens such as `NA` or `M` are data, not missing markers (`datapackage.json` declares
   `missingValues: [""]`).
2. **Read `run` and `release` as strings.** Runs `35S` and `48S` are distinct from 35 and 48.

```python
import pandas as pd
arcs = pd.read_csv("volume1/arcs.csv", dtype={"run": str, "token": str}, keep_default_na=False)
measured = arcs[arcs.status == "value"].astype({"concentration_mg_m3": float})
wide = measured[measured.run == "33"].pivot(index="bearing_deg", columns="arc_m", values="concentration_mg_m3")
```

With the Frictionless tools: `frictionless validate datapackage.json`, or in R,
`frictionless::read_resource(frictionless::read_package("datapackage.json"), "volume1-arcs")`.

### What a cell holds: `status`

`status` is derived **only from the printed token**. A blank is never stored as 0 or as missing.

| `status` | Printed as | Meaning |
|---|---|---|
| `value` | a number | the number is in the value column |
| `not_measurable` | blank (Tables 5.2, 5.3) | "no measurable concentration" (Vol. I pp. 79, 193) |
| `missing` | `M` (Vol. I), `--` (Vol. II), blank in Table 5.4 | missing data or instrument failure, per each table's legend |
| `not_printed` | blank (Vol. II) | nothing printed, e.g. a sounding level without that quantity |
| `text` | words | e.g. `rain`, `Calm`, `MB` (motorboating), remarks |
| `code` | Table 13.1 `#` column | a two-figure trace code, not a number |
| `illegible` | | the print could not be read by the project owner (1 cell) |

Printed zeros (`0.000`, `0`) are `value` 0.0, which is distinct from a blank. In Tables 5.2/5.3:
{{v1_status}}.

### How well supported a value is: `quality`

{{quality_table}}

In Volume I, Tables 5.2/5.3 have no `quality` column. They carry `reviewed`, `flagged` and
`value_source` instead (see [Method](#method)), and Tables 5.1, 5.4 and 6.1 use the labels above.
For maximum certainty, drop `doubtful`, `rule` and `illegible` cells. For an audit, start from
`printed_inconsistent` and the annotations.

### Provenance on every row

| Column | Meaning |
|---|---|
| `token` | the printed token, exactly as read (`.0183`, `(2.4)`, `>100`, `--`) |
| `value_source` | how the token was established: OCR, OCR confirmed by a second reader, or a review decision with its basis, decider and date |
| `reviewed` | the cell went through review by the project owner |
| `pdf_index`, `printed_page` | where the cell is: page index in the scanned volume (see [Source](#source)) and the printed page number |
| `cell_id` | stable identifier; joins to `annotations.jsonl` |

### Units and time

Units are those printed in each table heading. They are recorded **as printed**, either in the column
name (`concentration_mg_m3`) or in a `unit` column, even where the heading is known to be wrong
(Table 9.1). Times are Central Standard Time, `hhmm`. All dates are 1956. In Tables 8.1/8.2, CST
values marked `*` belong to the next day, per the page footnote; `date` already reflects this.

## Corrections we did not make

Each of these is a deliberate choice and is recorded in the data:

- **Suspected errors in the 1958 original are marked, not fixed** (`suspect`, `suspect_alternative`,
  `suspect_note`; Table 10.1 `erratum`):

  | Where | Printed | Likely intended | Evidence |
  |---|---|---|---|
  | Table 5.2, run 44, 800 m, post 69 | 9.565 | 0.565 | 18× its neighbours; the only four-figure value in the column |
  | Table 5.2, run 10, 800 m, post 127 | 0.90 | 0.090 | 12× its neighbours; the only two-decimal value in a three-decimal column |
  | Table 6.1, release 60, time | 0135 | 0025 | Table 8.1 has 0035, Table 5.2 header 0030-0040 |
  | Table 6.1, release 61, date | blank (= 26 Aug.) | 27 Aug. | Table 8.1 and the Table 5.2 header |
  | Table 6.1, release 62, date | 26 Aug. | 27 Aug. | as above |
  | Table 10.1, release 45, time | 1200 | 1700 | Table 8.1 (1705), Table 12.1 sounding (1658) |

- **Units kept as printed.** Table 9.1 is headed "Kcal/cm² sec" but is in fact 10⁻³ cal cm⁻² s⁻¹
  (Table 9.2 = 0.06 × Table 9.1 throughout). Its last column, headed R_n + Σq, holds −(R_n + Σq).
- **Evaporation not applied.** The Table 5.2/5.3 concentrations are as printed. The Table 5.4 factors
  are shipped separately; towers take the 100 m factor.
- **Legend caveats kept.** The Table 6.1 legend says the 450 m vane reads about 8° too high; values
  are as printed. In runs 14, 39 and 40, the Table 6.1 source wind speed is 36-48 % above Table 8.1's
  2 m speed. They are kept as printed (`printed_inconsistent`); this is most likely an instrument
  difference on light-wind nights.
- **Consistency failures are reported, not resolved.** `check_failures` lists the checks a printed
  value still fails, and `outlier` marks statistical outliers. Neither removes anything.
- **Table 11.3 is excluded.** The printed table (Δ(∂T/∂z) at 12 cm) carries hand corrections.

## Annotations

`annotations/annotations.jsonl` holds one statement per line about the data beyond the printed token.
Categories include:

- suspected errors in the original;
- printed inconsistencies;
- doubtful readings, and readings decided by context or by rule;
- keys set by a person;
- units kept as printed;
- the excluded table.

Each statement has `file` + `cell_id` (or a row selector `match`, or a whole table), the printed
token, an alternative where there is one, the evidence, who decided (`project owner`,
`Claude (owner-approved method)` or `rule`) and the date. These are the same facts as the columns
in the tables, gathered in one place for review.

## Differences from earlier transcriptions

The concentrations (Tables 5.2, 5.3) were compared with J. S. Irwin's transcription on harmo.org
(`PGARCS.txt`, `PGVertConc.txt`). The comparison was used only to find cells worth a second look;
the build never reads those files. The owner reviewed all 159 cells where the two disagreed against
the scan. In about 119 the earlier transcription differs from the print, and in 40 our first reading
was wrong. The most common kinds of difference are:

- single-digit differences;
- one column of run 7 repeated in the next slot;
- ×10 slips;
- printed blanks ("no measurable concentration") coded as missing (42 cells);
- explicit printed zeros not distinguishable from blanks.

Every case is listed in `annotations/reference_comparison.csv`, with the type of difference and who
was right. One case is notable: for run 44, 800 m, post 69, the earlier file holds 0.565, the value we
suspect was intended, while the print clearly says 9.565.

That transcription is the work of the late John S. Irwin, who kept the Prairie Grass data and the
scanned report available on harmo.org for many years. This dataset would not exist without that
service. The differences listed here are offered in the same spirit: to help users of either file.

Not yet compared: Irwin's files for Tables 5.1 and 5.4 and his micrometeorological wind and
temperature file. To our knowledge, Table 6.1, the rawinsonde soundings (12.1), the aircraft
observations (13.1), the hourly Table 8.2 and the heat-budget tables have not been published in
machine-readable form before.

## Method

- **Reading.** The primary reader is Mistral OCR (`mistral-ocr-4-1`, pinned). It read 98.2 % of
  cells correctly on development pages, against 83 % for the best offline OCR. All raw responses are
  kept with the code (see [Code](#code)).
- **Volume I, Tables 5.2/5.3.** Every cell was cross-checked by offline OCR (Tesseract, EasyOCR).
  Every cell where our reading and the earlier transcription disagreed was read again by Claude
  Sonnet (`claude-sonnet-5-5`) and decided by the project owner from the scan (159 cells, 25 values
  changed). Pipeline doubts are kept in `flagged`/`flag_notes`.
- **Volume I, Tables 5.1, 5.4, 6.1.** Every cell was read independently by Mistral and Sonnet; 1,428
  of 1,438 agreed and the owner ruled on the rest. The cells were also checked for format, range,
  internal consistency and against Table 8.1.
- **Volume II.** Every cell was checked for internal consistency: arithmetic, physics, height
  profiles, neighbouring hours, keys shared between tables. Tables 8.1 and 8.2 were read in full by a
  second reader, Sonnet.
  - Cells that fail a check, and cells where the two readers differ, were reviewed. A reading that
    fits its height profile or neighbouring hours and whose alternative does not was kept as
    `context`: decided by Claude under rules set by the project owner, not by the owner.
  - The project owner then ruled from the scan on the remaining doubtful readings and on the
    statistical outliers, in three review rounds (2026-11-15 to 2026-11-23).
- **The hardest problem is the typeface.** In this print 0, 6, 8 and 9 are easily confused, because
  a worn 6 or 9 loses its inner stroke. Every reader tried makes this mistake, including human ones.
  Single-reader cells that pass every check can still hold such a slip.

### Use of AI tools

Two AI systems read the printed tables: Mistral OCR (primary reader) and Claude Sonnet (independent
second reader). Claude also decided between disagreeing readings by context (`quality = context`,
157 cells), under rules set by the project owner. The project owner made every review ruling
(`quality = owner`) and every suspected-error judgement. The processing code was written with an AI
coding assistant (Claude Code) under the owner's direction. Every value records which of these
established it (`value_source`, and `decided_by` in the annotations).

## Known limitations

- **Unseen misreads.** In Volume I, a cell that our OCR and the earlier transcription misread *the
  same way* was never surfaced. We estimate fewer than 1 in 600 cells. In Volume II, tables other than
  8.1/8.2 are mostly `single_reader`: a 0/6 slip that breaks no check is invisible.
- **Table 13.1 remarks** are machine-transcribed and not reviewed cell by cell (flagged "unverified
  transcription").
- **One doubtful and one illegible cell** remain in Volume II (both in Table 13.1).

## Source

The transcription was made from scans of the report kept on harmo.org by J. S. Irwin, with byte
counts and checksums as below. The scans are **not included** in this version. `pdf_index` refers to
pages of these exact files.

{{scan_table}}

The report: Barad, M. L. (ed.), 1958: *Project Prairie Grass, A Field Program in Diffusion*, Vols. I
and II. Geophysical Research Papers No. 59, AFCRC-TR-58-235(I) and (II), Air Force Cambridge
Research Center.

## Code

The extraction and review pipeline, all raw OCR and second-reader responses, and every review
decision are in the project repository. The dataset can be rebuilt from them without any API access.

## Citation

{{citation}}

Please also cite the original report (above).

## Licence

The data and this documentation: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
The underlying measurements are those of the 1958 report.

## Versions

- **1.0.0**: first release.

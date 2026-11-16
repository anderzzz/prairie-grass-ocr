# prairie-grass-ocr

Machine-readable transcriptions of the data tables in the **Project Prairie Grass**
reports (Barad, ed., 1958), digitised from the scanned PDFs in `rawdata/`:

- **Volume I**: Chapter 5 SO₂ concentration tables. Table 5.2 covers the five horizontal arcs
  and Table 5.3 covers the six towers. Also the source strengths Q (Table 5.1), the evaporation
  correction factors (Table 5.4), the slow-response 2 m wind and σ_θ (Table 6.1) and the per-run
  remarks.
- **Volume II**: the meteorological tables in Chapters 7–13. These are micrometeorology,
  heat budget, soil, optical ΔT/Δz, rawinsonde and aircraft data.

Every value comes from the printed page and nothing else. The primary reader is Mistral OCR,
cross-checked by offline OCR (Volume I) or by internal consistency checks (Volume II).
Cells in doubt were read a second time by Claude Sonnet, and conflicts were reviewed by the
project owner. Nothing is interpolated, smoothed or "corrected". Each cell keeps its printed
token next to the parsed number, along with where the number came from.

---

## Where the data is

**The final datasets are these two folders:**

| Path | Content | Rows |
|---|---|---|
| `output/volume1/dataset/arcs.csv` | Table 5.2: arc samplers at 1.5 m, 68 runs | 30,510 |
| `output/volume1/dataset/towers.csv` | Table 5.3: tower samplers, 52 runs | 2,808 |
| `output/volume1/dataset/source_strength.csv` | Table 5.1: release rate Q (g/s), 68 runs | 68 |
| `output/volume1/dataset/evaporation_correction.csv` | Table 5.4: correction factors per run and arc | 350 |
| `output/volume1/dataset/slow_response_wind.csv` | Table 6.1: 2 m wind speed, direction, σ_θ (source and 450 m; 10 and 20 min) | 952 |
| `output/volume1/dataset/run_remarks.csv` | Per-run remarks printed with Table 5.2 and the Table 6.1 legend | 23 |
| `output/volume2/dataset/table_<id>.csv` | One file per Volume II table (catalogue below) | 31 – 7,767 |

Each file is **long format, one row per printed cell**. That includes blank cells, because a
blank means something in these tables (see [Status](#status-what-a-cell-holds)).

Everything else under `output/` is an intermediate or a working file. You do not need it
to use the data:

| Path | What it is |
|---|---|
| `output/volume1/extracted/p<pdf>.csv` + `.meta.json` | Per-page pipeline output: every reader's raw token, confidences, flags, cell boxes. Input to `make dataset`. |
| `output/volume2/extracted/table_<id>.csv` | Parsed Volume II tables before review. Table 11.3 exists only here (see below). |
| `output/volume2/checks/suspects.csv` | Cells that failed a consistency check |
| `output/volume2/mistral/`, `output/volume2/locate/` | Mistral page transcriptions (Markdown) and table locations |
| `output/volume1/triage/`, `output/volume2/second_read/` | Sonnet second readings and API spend |
| `output/volume1/dashboard/` | Summary JSON for the Volume I overview page |
| `output/extracted/`, `output/pages/`, `output/crops/` | The 10-page pilot (frozen at tag `extraction-frozen`; see `REPORT.md`) |

The two PDF volumes and all raw OCR responses (`cache/reader_mistral_page/`,
`cache/reader_llm/`) are committed, so the datasets can be rebuilt without API keys.

## Quick start

```python
import pandas as pd

arcs = pd.read_csv("output/volume1/dataset/arcs.csv",
                   dtype={"run": str, "token": str}, keep_default_na=False)
measured = arcs[arcs.status == "value"].astype({"concentration_mg_m3": float})

# Wide table for one run: posts × arcs
run = measured[measured.run == "33"].pivot(index="bearing_deg", columns="arc_m",
                                           values="concentration_mg_m3")
```

Two rules apply when reading these files:

- **Read `run` as a string.** Runs `35S` and `48S` exist, and they are distinct from 35 and 48.
- **Read with `keep_default_na=False`.** Otherwise pandas turns empty strings, and tokens such
  as `NA`, into NaN, and you lose the difference between "nothing printed" and "missing".

`notebooks/pgdata.py` has ready-made loaders (`arcs()`, `towers()`) that apply these rules,
convert booleans and add a printed run order. `make notebooks` opens the exploration
notebooks.

---

## Conventions shared by both volumes

### Status: what a cell holds

`status` is derived **only from the printed token**. A blank is never written as 0 or as
missing.

| `status` | Printed as | Meaning | Volume |
|---|---|---|---|
| `value` | a number | the number is in the value column | both |
| `not_measurable` | blank | "no measurable concentration" (Vol. I pp. 79, 193) | I |
| `missing` | `M` (Vol. I), `--` (Vol. II) | missing data / instrument failure | both |
| `not_printed` | blank | nothing printed, e.g. a rawinsonde height between standard levels | II |
| `text` | words (`rain`, `Calm`, `MB`, remarks) | kept as text, no number | II |
| `code` | Table 13.1 `#` column | two-figure trace code: a code, not a number | II |
| `illegible` | | the owner could not read the print (1 cell) | II |
| `unread` | | token not interpretable as any of the above | both |

Printed zeros (`0.000`, `0`) are kept as `value` 0.0. They are distinct from a blank.

### Provenance columns

| Column | Meaning |
|---|---|
| `token` | The printed token the value was parsed from, exactly as read (`.0183`, `(2.4)`, `>100`) |
| `value_source` | How the token was established: `mistral`, `mistral, confirmed by sonnet`, or an owner/rule decision with its basis and date |
| `reviewed` | The cell went through owner review |
| `estimated` | Printed as estimated: `*` in Vol. I Table 5.3, `(x)` in Vol. II |
| `flags` / `flagged`, `flag_notes` | Pipeline doubts (reader disagreement, low confidence, structure). Not cleared by review. |
| `key_source` | How the row key (run, release) was established: `pipeline`, or `manual (...)` with who decided and on what basis |
| `pdf_index` | 0-based page index in the PDF |
| `printed_page` | Page number printed in the report (Vol. I: `pdf_index − 13`) |
| `cell_id` | Stable cell identifier. It joins to the per-page extraction, the review verdicts in `config/review/` and the suspect list. |

### Units and time

Units are those printed in the table heading. They are recorded in the column name (Vol. I)
or in a `unit` column (Vol. II), **as printed**, even where the heading is known to be
wrong (see Table 9.1). Times are Central Standard Time, `hhmm`. All dates are 1956.

---

## Volume I: `arcs.csv` and `towers.csv`

Ten-minute mean SO₂ concentrations, **mg m⁻³ as printed**, from Tables 5.2 and 5.3.

### Keys

**arcs.csv**: one row per (`run`, `arc_m`, `post`). Rows are sorted in printed run order
(…, 35S, 35, …, 48S, 48, …).

| Column | Type | Meaning |
|---|---|---|
| `run` | str | Release number: 1–62, 65–68, plus `35S`, `48S` |
| `arc_m` | int | Arc radius: 50, 100, 200, 400, 800 m |
| `post` | int | Post number on the arc: 1–91 on inner arcs, 1–181 on the 800 m arc |
| `bearing_deg` | int | Post bearing. Post 1 is due west (270°); spacing is 2° on 50–400 m arcs, 1° at 800 m (printed p. 79) |

**towers.csv**: one row per (`run`, `tower`, `height_m`).

| Column | Type | Meaning |
|---|---|---|
| `run` | str | As above; tower data begin at run 13 |
| `tower` | int | 1–6. Towers stand on the 100 m arc between posts 28–29, 35–36, 42–43, 49–50, 56–57, 63–64. |
| `height_m` | float | 0.5, 1.0, 1.5, 2.5, 4.5, 7.5, 10.5, 13.5, 17.5 |

### Value and quality columns

| Column | Meaning |
|---|---|
| `status` | `value`, `not_measurable`, `missing`, `unread` |
| `concentration_mg_m3` | Filled **only** when `status = value` |
| `estimated` | Printed with `*` ("estimated value"); one tower cell |
| `token`, `value_source`, `reviewed` | See provenance above. 159 cells were reviewed: every cell where Mistral and the [harmo.org](https://www.harmo.org) reference transcription disagreed. |
| `flagged`, `flag_notes` | Pipeline flags: about 8% of arc cells, 18% of tower cells |
| `suspect`, `suspect_alternative`, `suspect_note` | The owner suspects an error **in the original report** (`config/suspect_values.yaml`). The printed value is kept; the alternative is only carried alongside it. |
| `key_source`, `pdf_index`, `printed_page`, `cell_id` | Provenance |

`cell_id` has the form `p<pdf>_<table>_r<run>_<arc>_<post>` (arcs) or
`p<pdf>_<table>_r<run>_<tower>_<height>` (towers).

Status counts:

| | value | not_measurable | missing |
|---|---|---|---|
| arcs | 8,173 | 22,306 | 31 |
| towers | 1,096 | 1,700 | 12 |

The dataset is built from the scan readings and owner verdicts only. **The reference
transcription is never read by the build**, and `tests/test_isolation.py` checks this. The
reference was used to find cells worth a second look, and it turned out to contain real
errors. See `REPORT.md` for details.

### Tables 5.1, 5.4, 6.1 and the run remarks

Smaller Volume I tables, built by `src/volume1s/` (`make volume1s`, `make volume1s-dataset`).
Every cell was read by Mistral **and** independently by Sonnet (13 calls, $0.25), then checked
for keys, printed format, ranges, internal consistency and against Table 8.1. The columns
follow Volume II: `token`, `value`, `status`, `quality`, `value_source`, `check_failures`,
`review_note` and the provenance columns.

- `source_strength.csv`: `run`, `value` = Q in g/s as printed.
- `evaporation_correction.csv`: `run`, `arc_m`, `value` = factor to multiply concentrations by.
  A blank is printed as "missing data" (`status = missing`); runs 30, 31, 63 and 64 are blank
  throughout. Towers take the 100 m factor (legend). **The Table 5.2/5.3 values are not
  corrected**; the factors are kept separately.
- `slow_response_wind.csv`: `release`, `quantity` (`wind_speed` m/s, `wind_direction` deg,
  `sigma_theta` deg = standard deviation of azimuth wind direction), `location` (`source` = 2 m
  on the base line, `450m`), `period_min` (10 or 20; the 10 min source period coincides with
  the release). `estimated` = printed with `*` (estimate from an incomplete record). The legend
  says the 450 m vane reads about 8° too high; values are as printed. A blank `Date` cell repeats
  the date to its left: `date_token` is printed, `date` is carried forward. Rows with
  `quantity = key:date` / `key:time_cst` hold the printed keys and their checks.
- `run_remarks.csv`: one row per run and remark (e.g. run 4 released for 9.5 min; run 47's rate
  varied ±50 % in the first 90 s; vacuum-line faults in runs 50, 51, 57; missing slow-response
  records).

`suspect`, `suspect_alternative`, `suspect_note` mark printed values that disagree with
other tables (release 60 time, 61/62 date, 40 speed; `config/suspect_values.yaml`). They are
never corrected. See `docs/volume1s.md` for the checks and the review.

---

## Volume II: `table_<id>.csv`

Meteorological tables. No concentration data. No reference transcription exists, so quality
control relies on internal consistency checks (arithmetic, physics, cross-table keys; see
`docs/volume2.md`).

### Table catalogue

| File | Table | Content | Key columns | Rows |
|---|---|---|---|---|
| `table_7.1.csv` | 7.1 | Standard error of mean potential temperature | panel/block/row_key | 30 |
| `table_7.2.csv` | 7.2 | Statistical measures of temperature | panel/block/row_key | 64 |
| `table_8.1.csv` | 8.1 | Micrometeorology at gas-release times | `release`, `date`, `cst`, `section`, `quantity`, `height_m` | 2,982 |
| `table_8.2.csv` | 8.2 | Micrometeorology at other times (hourly) | `date`, `cst`, `section`, `quantity`, `height_m` | 7,428 |
| `table_8.3.csv` | 8.3 | Soil moisture and density | panel/block/row_key | 80 |
| `table_9.1.csv` | 9.1 | Heat budget, Texas A&M (as printed "Kcal/cm² sec") | `release`, `quantity` | 432 |
| `table_9.2.csv` | 9.2 | Heat budget, Texas A&M (cal/cm² min) | `release`, `quantity` | 192 |
| `table_9.3.csv` | 9.3 | % of double-level values within 10% of profile values | panel/block/row_key | 84 |
| `table_9.4.csv` | 9.4 | Heat-budget balance statistics (text only) | panel/block/row_key | 18 |
| `table_10.1.csv` | 10.1 | Heat budget, Univ. of Wisconsin (langley/min) | `release`, `quantity` | 230 |
| `table_11.1.csv` | 11.1 | Δ(∂T/∂z), optical method, 10–12 July | panel/block/row_key | 98 |
| `table_11.2.csv` | 11.2 | Δ(∂T/∂z), optical method, 21/23/31 July | panel/block/row_key | 58 |
| `table_12.1.csv` | 12.1 | Rawinsonde soundings and winds | `release`, `date`, `part`, `level`, `quantity` | 5,801 |
| `table_13.1.csv` | 13.1 | Aircraft observations | `field_test`, `date`, `time_cst`, `block`, `level`, `quantity` | 7,767 |

Table 11.3 (time series of Δ(∂T/∂z) at 12 cm) is **not in the dataset**. The owner left it
out on 2026-11-16 because the printed table carries hand corrections. The raw parse is in
`output/volume2/extracted/table_11.3.csv`.

### Columns common to every table

| Column | Meaning |
|---|---|
| `cell_id` | `T<table>\|p<pdf>\|<key parts>…`, unique within the table |
| `table`, `pdf_index`, `printed_page` | Provenance |
| `quantity`, `unit` | What the cell measures and its printed unit. Small tables have no `unit` column; there, `quantity` is the printed column heading, units included. |
| `token` | Printed token |
| `value` | Parsed number. Filled when `status = value` and `kind` is `number` or `above`. |
| `value_lo`, `value_hi` | Bounds of a printed range `a to b` (Table 11.1 only) |
| `status` | See [Status](#status-what-a-cell-holds) |
| `kind` | Token shape: `number`, `missing`, `blank`, `range`, `above` (`>100`), `text`, `unread` |
| `estimated` | Printed in parentheses `(x)` |
| `footnote` | Printed with `*`. The footnote text is kept per page (`page_footnotes`, Tables 8.x). |
| `conf` | Mistral word confidence (0–1) |
| `flags` | Parser and reader doubts, `;`-separated |
| `quality` | Overall standing of the cell (next table) |
| `value_source`, `reviewed` | See provenance above |
| `pending` | A review decision is still open. All `False` in the current build. |
| `check_failures` | Consistency checks the final token still fails, e.g. a printed inconsistency |
| `review_note` | Owner's note, where one was made |
| `outlier` | Outlier screen result: `spike (±n scales)` or `global (±n scales)`. Empty = not an outlier. **Marks only, removes nothing.** |
| `grid_ti`, `grid_row` | Table/row index on the page, used to cut review images |

**`quality`**, from strongest to weakest:

| `quality` | Meaning |
|---|---|
| `owner` | The owner read the cell from the scan |
| `two_readers` | Mistral and Sonnet read the same token independently |
| `single_reader` | Mistral only, and no consistency check involved the cell (the large majority) |
| `printed_inconsistent` | The owner confirmed it is printed this way, yet it still fails a check |
| `rule` | Not ruled by the owner. The reading under which the failed checks pass was taken. |
| `doubtful` | Not ruled by the owner, and neither reading passes. Mistral's reading is kept. |
| `illegible` / `unread` | No usable value |

### Table-specific columns

**Tables 8.1 and 8.2** (micrometeorology profiles):

- `release` / `release_token`: gas release number (= Volume I `run`; 8.1 only).
- `date` (ISO), `cst` (hhmm). `cst_token` and `date_read` hold what was printed. CST values
  marked `*` belong to the next day, per the page footnote.
- `section`: one of `radiation`, `temperature`, `vapor_pressure`, `wind_speed`,
  `wind_direction`, `soil_temperature_change`, `precipitation`.
- `height_m`: measurement height. **Negative = depth below the surface** (soil, −0.03 to
  −1.0 m). Air levels are 0.12 to 16 m. Empty for whole-column quantities.
- Units: radiation in cal cm⁻² s⁻¹, temperature in °C, vapour pressure in mb, wind speed in
  cm/s, direction in degrees.
- `read_by`: set where the precipitation row was read from its own strip.

**Tables 9.1, 9.2, 10.1** (heat budget): `release`, `row`, `quantity`.

- Table 9.1 `quantity` takes the values `du`, `dtheta`, `de`, `q_c`, `q_e`, `q_s`, `sum_q`,
  `R_n`, `R_n_plus_sum_q`.
- **Table 9.1 is printed "Kcal/cm² sec" but is in fact 10⁻³ cal cm⁻² s⁻¹.** Table 9.2 equals
  0.06 × Table 9.1. The unit is recorded as printed. The last column of 9.1 equals
  −(R_n + Σq) as printed.
- Table 10.1 has `I`, `R_N`, `L`, `E`, `G` in langley/min, plus `date_token`, `time_cst` and
  `time_cst_interpreted`. `erratum` holds the owner's reading where the printed value is
  judged a typing error in the original. The token is kept unchanged.

**Table 12.1** (rawinsonde):

- `release`, `date`, `time_token` (as printed, e.g. `1050C`).
- `panel`, `part`: `sounding` or `winds`.
- `level` and `level_label` (`SFC` for the surface).
- `quantity`: `pressure` (mb), `height` (m), `temperature` (°C), `relative_humidity` (%),
  `wind_direction` (deg), `wind_speed` (m/s), or `note`.
- `MB` (motorboating: too dry to measure) is `text`.

**Table 13.1** (aircraft):

- `field_test`, `date`, `time_cst`, `block`, `level`. `header_token` and `field_test_token`
  hold the block header as printed.
- `quantity`: `pressure_altitude` (ft), `pressure` (mb), `temperature` (°C),
  `relative_humidity` (%), `vapor_pressure` (mb), `dew_point` (°C), `trace_code` (`code`),
  `remarks` (text).
- Field-test numbers are **not** release keys: the flights were not made at release times.
- Field tests 23–24 and 31–36 are not printed.
- Remarks are transcribed by Mistral and flagged "unverified transcription".

**Small tables** (7.1, 7.2, 8.3, 9.3, 9.4, 11.1, 11.2): a generic grid.

- `panel`, `block`, `row`, `col`. `row_key` holds the printed row labels joined with ` | `.
- `quantity` is the printed column heading, units included (LaTeX where Mistral wrote it).
- Table 9.4 is entirely text (fitted equations, error terms).

### Reshaping

```python
t = pd.read_csv("output/volume2/dataset/table_8.1.csv", dtype=str, keep_default_na=False)
temp = (t[(t.section == "temperature") & (t.status == "value")]
        .astype({"value": float, "height_m": float})
        .pivot_table(index=["release", "date", "cst"], columns="height_m", values="value"))
```

---

## Rebuilding

Python 3.11 with [uv](https://docs.astral.sh/uv/). Every step reads committed caches, so no
API keys are needed unless you add pages.

```
make dataset            # Volume I dataset from output/volume1/extracted + config/review
make volume2            # Volume II: OCR (cached) -> parsed tables -> consistency checks
make volume2-dataset    # Volume II dataset + outlier screen
make volume1s           # Vol I Tables 5.1, 5.4, 6.1: OCR + second reading (cached), checks, review pack
make volume1s-dataset   # their dataset (after review: DATE=yyyy-mm-dd make volume1s-dataset)
make test
make notebooks          # JupyterLab with the exploration notebooks
```

Full re-extraction of Volume I is `make volume`. The pilot (`make pilot`, `make score-holdout`)
also downloads the reference transcription into the gitignored `reference/`. The `Makefile`
lists every target with a one-line description.

## Repository layout

```
rawdata/          the two scanned volumes (1-bit, 300 dpi)
src/extract/      Volume I pipeline: structure detection, readers, flags
src/dataset/      Volume I dataset build
src/volume2/      Volume II parsers, checks, second reading, dataset, outliers
src/volume1s/     Volume I Tables 5.1, 5.4, 6.1 and run remarks
scoring/          pilot scoring against the reference, triage, verdict resolution
config/           manual keys, page inventories, owner verdicts, suspect values
docs/             table layouts, page maps, Volume II conventions
notebooks/        exploration notebooks and loaders (pgdata.py)
cache/            raw Mistral and Sonnet responses (committed)
output/           extractions and the datasets
```

## Further reading

- `docs/table_layouts.md`: how the Volume I tables are laid out on the page
- `docs/volume2.md`: Volume II conventions, checks, review and outlier rules
- `REPORT.md`: pilot method and accuracy, the full Volume I run, and the owner review
- `docs/recon_discrepancies.md`, `docs/page_map.csv`: page-level reconciliation

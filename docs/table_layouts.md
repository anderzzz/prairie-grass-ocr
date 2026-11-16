# Table layouts in Chapter 5 (Volume I)

Derived from the scan itself (`rawdata/PGrassVolumeI.pdf`). Printed page =
PDF page index − 13 throughout the body of the report (115 footer page
numbers read by OCR agree; see `docs/page_map.csv`). All page images are 1-bit
CCITT G4 scans at 300 dpi.

| Table | Content | PDF index | Printed pages |
|---|---|---|---|
| 5.1 | Source strengths Q (g sec⁻¹) per run | 91 | 78 |
| 5.2 | 10-min mean SO₂ concentration on the five horizontal arcs | intro text 92–93, tables 94–205 | 79–80, 81–192 |
| 5.3 | 10-min mean SO₂ concentration on the six towers | intro text 206, tables 207–212 | 193, 194–199 |
| 5.4 | Correction factors for evaporative loss of impinger solution | 213–214 | 200–201 |
| 6.1 | Slow-response 2 m wind speed, direction, σ_θ (MIT); legend + 5 pages | 222–227 | 209–214 |
| 6.2 | Frequency distributions of wind direction (not transcribed) | 228– | 215– |

The text above Table 5.1 refers to "Tables 5.4 and 5.5" for slow-response
meteorological data. There is no Table 5.5; the slow-response data are Table 6.1.

The brief placed Chapter 5 at printed pages 57–201; the data tables sit at
printed 78–201. The table numbers in the brief are right.

## Table 5.1 — source strengths

* One page, three side-by-side column pairs `Run No. | Q (g sec⁻¹)`.
* Rows: runs 1–62, 65–68 plus runs **35S** and **48S** (68 entries; runs 63 and
  64 absent). 35S is listed before 35, and 48S before 48.
* Values printed with one decimal (e.g. `81.5`, `101.4`).
* Not part of the pilot: no reference file covers it.

## Table 5.2 — horizontal arcs ("Ten-minute average gas concentrations measured … at a height of 1.5 m")

* Units as printed: `CONCENTRATION (mg m⁻³)`.
* Page header: `Table 5.2 (Continued)`, `DATE <d Month 1956>`, `TIME hhmm-hhmm CST`,
  `RUN NO. <n>`; S-runs are printed `RUN NO. 35-S`, `RUN NO. 48-S`.
* Each page has **two side-by-side panels**, each with the columns
  `POST NO.: Inner Arcs | 800m arc ‖ ARC: 50m | 100m | 200m | 400m | 800m`.
  Column boundaries are ruled; the post/arc separators are double rules.
* Rows are 800 m posts. Inner-arc post *n* shares a row with 800 m post
  *2n − 1*; the inner-arc cells are ruled every two 800 m rows and their values
  are printed on the upper (odd 800 m post) line. The 800 m column has a value
  slot on every row.
* A run takes up to two pages:
  * half **A**: left panel 800 m posts 1–45 (inner 1–23), right panel 46–90 (inner 24–45);
  * half **B**: left panel 91–135 (inner 46–68), right panel 136–181 (inner 69–91).
  Geometry check: inner arcs 91 posts at 2° over 180°, 800 m arc 181 posts at 1°.
* Not every run has both halves: by the automatic run labels in
  `docs/page_inventory.csv`, about 20-25 runs have a single Table 5.2 page (the
  exact count depends on a few labels settled by order; see
  `docs/recon_discrepancies.md`). For example run 46 has only half A and run 47
  only half B. A half that would be empty appears to have been omitted. **The
  report does not say so** (the intro, printed pp. 79–80, only says blanks mean
  "no measurable concentration"); it is our inference. The data support it: on
  all 120 run/arc pairs with one half printed, the printed half is below 5 % of
  the arc maximum at the seam (checked 2026-11-16).
* Order of runs: 1 … 34, 35S, 35, 36 … 47, 48S, 48, 49 … 62, 65 … 68.
* Values: three significant figures as a rule — `0.ddd` below 1, `d.dd` from 1 to 10,
  `dd.d` from 10 to 100, integers from 100 (e.g. `2200`). Decimal points often print
  as or merge into commas against the underline.
* Special values (Table 5.2 intro, printed page 79):
  * **blank** = no measurable concentration (verbatim: "the letter "M" indicates
    missing data and the blank spaces denote no measurable concentration");
  * **`M`** = missing data.
  * A few cells print an explicit zero (`0.000`, `0`), distinct from a blank.
  * Run-specific remarks (printed page 79–80): run 4 adjusted to a 10-min release;
    run 25 gnat-affected samplers marked missing; runs 30/31 low background
    resistance; run 45 post 38 of 50 m arc adjusted; runs 47, 50, 51, 57 sampler
    and release irregularities.
* Footnote markers: none seen in 5.2 so far.

## Table 5.3 — towers ("Ten-minute average gas concentrations measured along the vertical")

* Units as printed: `CONCENTRATION (mg m⁻³)`.
* Columns: `Tower No. | Height (m) | Run No.: r1 … r9` — up to nine runs per page,
  run numbers printed in a header row (not consecutive: runs without tower data
  are skipped, e.g. 22, 24, 25 …; `48S` appears as its own column).
* Rows: 6 towers × 9 heights, printed top to bottom as
  `17.5, 13.5, 10.5, 7.5, 4.5, 2.5, 1.5, 1.0, 0.5` m, tower number printed on
  the 17.5 m row. Tower groups are separated by a spacer whose height varies
  (≈0.75–1.05 row pitches), so groups must be located individually.
* Towers stand between 100 m arc posts 28–29, 35–36, 42–43, 49–50, 56–57, 63–64
  (towers 1–6).
* Specials (Table 5.3 intro, printed page 193): blank = no measurable concentration; `M` = missing; `*` after a value
  = estimated (footnote `*ESTIMATED VALUE`; run 13, tower 4, 0.5 m: `2200*`).
* Tower data begin with run 13; no data for runs 23, 28, 35, 53, 63, 64.
* Value formats as in 5.2.

## Table 5.4 — evaporation correction factors

* Columns: `RUN NO. | ARC (m): 50 | 100 | 200 | 400 | 800`. Two pages.
* Factors with two decimals (`0.97`). Blank = missing data. Tower data take the
  100 m factor. Runs 30 and 31 blank throughout.
* Not part of the pilot: no reference file covers it.

## Table 6.1 — slow-response meteorological measurements (MIT)

* Legend page (PDF 222): units, the asterisk convention (estimate from an
  incomplete record), the 450 m vane offset (~8° too high) and a list of
  incomplete or missing records per run.
* Data pages 223–227: two blocks per page, seven release columns per block,
  ten blocks; the slots of runs 63 and 64 are printed empty.
* Rows per block: Gas release No., Date (printed once per day), Time (CST,
  the release start; 10 min before Table 8.1's observation time for 62 of 68
  releases), then wind speed, wind direction and standard deviation of wind
  direction, each for Source (10 min), 450 m (10 min), Source (20 min),
  450 m (20 min).

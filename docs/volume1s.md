# Volume I supplementary tables: 5.1, 5.4, 6.1 and run remarks

Added 2026-11-16 because the release rate Q (Table 5.1) is needed to
normalise the concentrations, and σ_θ (Table 6.1) is needed as a per-run
model input. Code: `src/volume1s/`; inventory: `config/volume1s_pages.yaml`.

## Pipeline

1. `volume1s.ocr`: Mistral OCR of PDF pages 91 (5.1), 92–93 (remarks),
   213–214 (5.4), 222–227 (6.1). Cached in `cache/reader_mistral_page`,
   markdown in `output/volume1s/mistral/`.
2. `volume1s.second_read`: Sonnet reads **every** data page independently
   (not only suspects, as in Volume II, because the tables are small): 5.1 in one
   call, 5.4 in two, 6.1 in two overlapping halves per page. 13 calls, $0.25,
   cached in `cache/reader_llm`.
3. `volume1s.compare`: cell-by-cell comparison. 6.1 is aligned by position
   (page, block, column), so a misread release header is compared like a value.
   Result: 1,438 cells, 1,428 agree. All 68 Q values and all 350 factors agree.
4. `volume1s.checks` (see the module docstring for tolerances): keys, printed
   format, ranges, 10 vs 20 min and source vs 450 m agreement, and date, time
   and 2 m speed against Table 8.1.
5. `volume1s.review`: owner review pack, `review/volume1s/index.html`
   (gitignored). `DATE=yyyy-mm-dd make volume1s-dataset` reads the exported
   verdicts into `config/review/volume1s_verdicts.csv`.

## Owner review (2026-11-16)

All 19 items ruled (`config/review/volume1s_verdicts.csv`).

Group A, readers differed (10): Mistral's reading kept for releases 1, 8
(σ 19.1), 21 (5.76; the dash is a print mark), 26 direction, 27, 32, 42 and
the release header 61; Sonnet's for 26 speed 450 m 20 min (6.29) and
33 speed 450 m 20 min (7.99). `quality = owner`.

Group C, readers agree but a check fails (9 cells): all "printed as such",
`quality = printed_inconsistent`. Run 35's direction (source 132 vs 450 m
105) is an internal difference and is not suspected.

Suspected errors in the original (`config/suspect_values.yaml`, section
`volume1s`; the cell gets `suspect = True`, the printed value is kept):

| Cell | Printed | Alternative | Against |
|---|---|---|---|
| release 60 time | 0135 | 0025 | Table 8.1 0035; Table 5.2 header 0030–0040 |
| release 61 date | blank (= 26 Aug.) | 1956-08-27 | Table 8.1; Table 5.2 header |
| release 62 date | 26 Aug. | 27 Aug. | Table 8.1; Table 5.2 header |
| release 40 speed, source 10 min | 3.08 | none | Table 8.1 2 m speed 2.08 m/s; which table is off is unclear |

The derived `date` column follows the print (26 Aug. for 61 and 62). Join on
`release`, not on date.

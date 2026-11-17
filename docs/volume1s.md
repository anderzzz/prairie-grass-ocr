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

The derived `date` column follows the print (26 Aug. for 61 and 62). Join on
`release`, not on date.

## Follow-up (2026-11-17, from data users' remarks)

Release 40's 10-min source speed (3.08 against Table 8.1's 2.08 m/s at 2 m) was
listed as suspect. Runs 14 (1.91 vs 1.39) and 39 (3.12 vs 2.29) show the same
gap: in all three Table 6.1 is 36-48 % higher, against a median ratio of 1.00
and at most 1.12 for every other release, all on light-wind nights with smooth
Table 8.1 profiles. The check had passed 14 and 39 because it measured the gap
against the larger speed (27 %); it now tests the ratio either way (factor 1.3),
so all three fail it. They are kept as printed (`quality = printed_inconsistent`,
`config/review/volume1s_followup.csv`) and read as a difference between the
instruments rather than a misprint; the suspect entry for 40 was removed.

A direction test was added: the 10-min source direction within 45 deg of
Table 8.1's 1 m direction. Before the Table 8.1 re-read it failed only release
40 (180 vs 106), which was a misreading of Table 8.1 (printed 166; see
`docs/volume2.md`).

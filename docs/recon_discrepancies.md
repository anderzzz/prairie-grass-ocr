# Reconnaissance discrepancies for manual review

Everything below is a *key* (which run / which page), not a data value. The
pipeline never takes a data value from a human. If you settle a key by eye,
it goes into `config/manual_keys.yaml` with your initials and date, and every
cell under it is marked `key source: manual` in the output.

PDF index → printed page = index − 13.

## A. Affects pilot pages (please check first)

| PDF | Printed | Table | What | Pipeline's reading | Readers |
|---|---|---|---|---|---|
| 211 | 198 | 5.3 holdout | run header, column 5 | **unresolved** (between 54 and 56) | disagree |
| 211 | 198 | 5.3 holdout | run headers, columns 2, 6, 8 | 51, 56, 58, chosen by run order | tesseract/easyocr disagree |
| 210 | 197 | 5.3 dev | run header, column 5 | 46, chosen by run order | tesseract 46 / easyocr 40 |

Cells under unresolved or order-chosen headers are flagged `structural`.

## B. Run labels on Table 5.2 pages outside the pilot

| PDF | Printed | Header as printed (by eye) | Pipeline | Note |
|---|---|---|---|---|
| 155 | 142 | RUN NO. 35-S | **36S** (wrong) | both readers misread (38S / 36S); the run-order rule then picked 36S. A real error, kept here as an example of a confident wrong key |
| 156 | 143 | RUN NO. 35 | unresolved | tesseract 95 / easyocr 36 |
| 157 | 144 | RUN NO. 36 | 36 | ok after both readers |
| 200 | 187 | ? | page not detected as a table page | needs a look: header OCR failed and the rule-count fallback did not fire |

13 more pages were settled by the run-order rule or by pairing with the adjacent
page (see `run_source` in `docs/page_inventory.csv`). I have not checked these
by eye.

## C. Table 5.3 run headers outside the pilot

| PDF | Printed | Column | Pipeline |
|---|---|---|---|
| 207 | 194 | 4 | unresolved (16 by sequence?) |
| 209 | 196 | 3 | unresolved (35 or 35S?) |
| 212 | 199 | 2, 6 | unresolved (61?, 67?) |
| 212 | 199 | 8, 9 | blank headers; treated as unused columns |

## D. Other

* Table 5.4 page 2 (PDF 214): the run range in the inventory (`34-97`) is OCR
  noise; it should be 40–68. Not part of the pilot.
* Structure: seven Table 5.2 pages (PDF 98, 117, 121, 159, 196, 197, 198) have
  one or two column rules too faint to detect. Their positions are now inferred
  from the printed form's template, and the affected cells are flagged. PDF 98
  is a holdout page.

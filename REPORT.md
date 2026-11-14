# Prairie Grass OCR pilot: report

*Project Prairie Grass, Vol. I (Barad, ed., 1958), Tables 5.2 (arc concentrations) and 5.3
(tower concentrations). Ten pilot pages: five dev pages, five holdout pages. Extraction
frozen at tag `extraction-frozen` (commit `c2c637a`); holdout scored once, on
2026-11-13 at 18:19 UTC.*

## Read this first: how the plan changed

The brief anticipated offline OCR as the backbone. On dev pages the two offline readers
(Tesseract 5, EasyOCR) read only 83% and 78% of cells with values correctly. After a
documented comparison on dev pages (section 3), the **primary reader became Mistral OCR
4.1** (`mistral-ocr-4-1`, a cloud page-level OCR model). The two offline readers stay as an
independent cross-check, so the brief's "at least two readers, one offline" still holds. The
switch was made, tuned and frozen **before** any holdout page was extracted or scored.

**Nothing in the extraction code changed after the holdout results were seen.** Disclosures
about what was seen before the freeze are in section 7.

## 1. Headline numbers (holdout)

| | Holdout | Dev |
|---|---|---|
| Cells scored | 1,571 | 1,576 |
| **Disagreement rate with the reference** (all cells) | **1.15%** (18) | 0.76% (12) |
| Disagreement rate, cells non-blank on either side | 2.75% | 1.87% |
| **Self-flag recall** (disagreements the pipeline flagged) | **22%** (4 of 18) | 67% (8 of 12) |
| Flag rate (cells flagged) | 13.4% | 8.6% |
| Flag precision (flagged cells that disagree) | 1.9% | 5.9% |

On the holdout set, **13 of the 18 disagreements are one convention difference, not
misreadings**. Where the printed table is blank, the reference records "missing" (-9):
12 cells on PDF page 182 (800 m arc, run 52) and 1 on PDF page 98. The crops show empty
cells, with no "M" printed. The table's own convention is blank = no measurable
concentration and M = missing. The scoring does not decide which side is right. Counting
value disagreements only:

| Value disagreements only (blank-vs-missing excluded) | Holdout | Dev |
|---|---|---|
| Disagreement rate | 0.32% (5) | 0.76% (12) |
| Self-flag recall | 40% (2 of 5) | 67% (8 of 12) |

### Per page

| Set | PDF page (printed) | Table | Stratum | Disagree | Non-blank | Flag rate | Recall | Unflagged |
|---|---|---|---|---|---|---|---|---|
| holdout | 182 (169) | 5.2 | 2nd best | 5.19% | 7.14% | 14.4% | 14% | 12 (blank-vs-missing) |
| holdout | 98 (85) | 5.2 | near median | 0.73% | 0.85% | 46.9% | 100% | 0 |
| holdout | 144 (131) | 5.2 | near median | 0 | 0 | 3.3% | n/a | 0 |
| holdout | 107 (94) | 5.2 | 2nd worst | 0 | 0 | 10.4% | n/a | 0 |
| holdout | 211 (198) | 5.3 | tower (random) | 0.41% | 1.57% | 1.2% | 0% | 2 |
| dev | 146 (133) | 5.2 | best | 0 | 0 | 3.6% | n/a | 0 |
| dev | 111 (98) | 5.2 | near median | 0.36% | 0.65% | 6.2% | 0% | 1 |
| dev | 162 (149) | 5.2 | near median | 0.74% | 2.53% | 1.5% | 50% | 1 |
| dev | 124 (111) | 5.2 | worst | 0 | 0 | 4.8% | n/a | 0 |
| dev | 210 (197) | 5.3 | tower (random) | 1.85% | 3.80% | 18.7% | 78% | 2 |

### Per table type

| Table | Set | Cells | Disagree | Non-blank | Flag rate | Recall |
|---|---|---|---|---|---|---|
| 5.2 arcs | holdout | 1,085 | 1.47% | 3.03% | 18.9% | 25% |
| 5.2 arcs | dev | 1,090 | 0.28% | 0.74% | 4.0% | 33% |
| 5.3 towers | holdout | 486 | 0.41% | 1.57% | 1.2% | 0% |
| 5.3 towers | dev | 486 | 1.85% | 3.80% | 18.7% | 78% |

Structure: every extracted cell aligned with a reference key on all ten pages. There were no
row shifts, and no reference value fell outside the extracted grid. Units agree: the median
ratio over 1,270 numeric pairs is 1.000, in mg m⁻³. The arcs file's header multiplier (1.0
"to µg/m³" per its format document) is misleading; its values are in the printed mg m⁻³.

The holdout pages are easier than PDF page 210 (dev), which has badly degraded print in tower
6. Their flag rates differ for a structural reason: on PDF page 98 a column rule is too faint
to detect, so 91 cells carry "column bound inferred from template", and the offline readers
struggle on that page.

## 2. Which flags caught which disagreements

| Flag | Dev catches (of 12) | Holdout catches (of 18) |
|---|---|---|
| readers disagree: neither offline reader gives Mistral's token | 6 | 2 |
| low confidence: Mistral word confidence < 0.999 | 7 | 0 |
| token unexpected: breaks the three-significant-figure format | 1 | 0 |
| structural: row/column/key doubts | 0 | 3 |
| implausible: > ×4 from the neighbours' log-interpolation | 1 | 0 |

**What the unflagged disagreements have in common.** In each one, Mistral is backed by at
least one offline reader, so no disagreement signal fired:

1. **Blank in print, "missing" in the reference.** This is 12 of the 14 unflagged holdout
   disagreements. It is a convention difference, not a reading error.
2. **A clean print that every reader reads the same way, but the reference differs.**
   Dev, by PDF page:
   - page 111: 0.165 vs 0.166;
   - page 162: 98.4 vs 98.6;
   - page 210: 25.1 vs 24.1.

   Holdout:
   - page 182: 27.9 vs 27.0;
   - page 211: 13.8 vs 13.6.

   The project owner is reviewing these against the PDF. Several look like differences in
   the reference or in the print rather than in the reading.
3. **Single-digit confusions in fair print that one offline reader shares:**
   - holdout page 211, run 57, tower 4, 1.5 m: Mistral and EasyOCR read 27.8; Tesseract and
     the reference read 27.6;
   - dev page 210: Mistral and EasyOCR read 115; the reference reads 113.

   The flag rule needs *both* offline readers to disagree, so these went unflagged.

The flags reliably catch degraded print (dev PDF page 210, tower 6) and magnitude errors.
They cannot catch an error that every reader makes the same way.

## 3. What earned its place

### Readers (dev pages, the 649 cells where the offline readers found ink)

| Reader | Correct | Hard cells (317 flagged by the offline pipeline) |
|---|---|---|
| Tesseract 5 (psm 7, whitelist) | 82.7% | 66.6% |
| EasyOCR 1.7 | 77.3% | 55.5% |
| Offline consensus | 84.4% | 70.0% |
| Claude Haiku 5.5 (per cell, with format rules) | 92.0% | 87.1% |
| Claude Sonnet 5.5 (per cell, with format rules) | 94.0% | 90.5% |
| **Mistral OCR 4.1 (page level)** | **98.2%** | **96.8%** |

Costs on dev:

| Reader | Calls | Cost |
|---|---|---|
| Mistral | 5 pages | $0.02 |
| Haiku | 2,244 calls | $0.15 |
| Sonnet | 966 calls | $2.19 |

Projected per-run cost for Volume I's ~118 table pages: Mistral about $0.50; Sonnet on every
cell about $30–35.

The vision-LLM readers are coded (`src/extract/llm.py`) and capped, but **not used in the
frozen pipeline**. The project owner decided to reserve Sonnet for targeted review cases.

- **Mistral OCR 4.1** earned the primary role.
  - Most accurate reader by far, and the cheapest of the cloud options.
  - On the pilot pages it never invented a value in an empty cell and never left a printed
    value blank.
  - Its post numbers matched our grid on every row, which checks our structure independently.
  - Its word confidence separates errors well: cells at ≥ 0.999 had 0.9% errors on dev,
    against 6–11% below.
  - The model is pinned, and raw responses are committed under `cache/reader_mistral_page/`,
    so results can be rebuilt without the service.
- **The offline readers** earned a supporting role only. They are free, local and
  independent, and their joint disagreement is a useful flag. On their own they are too
  weak for the job.
- **Our own structure detection is still essential.** It defines every cell's key, checks
  Mistral's table row by row, and produces the crops for review. Mistral's own column
  headers on tower pages are unreliable (it read "48S 49 49" for "48S 48 49"), so tower
  columns are matched by position.

### Preprocessing (dev, with Mistral as the primary reader)

| Preset | Disagreement | Flag rate | Recall |
|---|---|---|---|
| raw page | 0.63% | 9.1% | 60% (6 of 10) |
| deskew + despeckle (kept) | 0.76% | 8.6% | 67% (8 of 12) |
| + stroke repair | 0.70% | 12.9% | 64% (7 of 11) |

The differences are 1–2 cells, which is noise. Deskew is kept because structure detection
was built on it. Stroke repair does not help. For the offline readers, careful glyph
isolation helped a lot (tesseract 54% to 83%); global preprocessing did not.

Other measures that earned their place:

| Measure | What it does |
|---|---|
| Template fit for faint column rules | Seven pages would otherwise have failed structure detection |
| Manual run keys | Settled by the owner from the scan, keys only, recorded with provenance |
| Mistral's reading of the page header | Third independent check of the run number; confirmed run 29 on PDF page 146, which the offline readers had only settled by run order |
| Neighbour-interpolation check | Simulation over real profiles: catches every lost decimal point (×10 to ×1000) while flagging about 1% of correct cells; flagged the "16" for 161 on dev |

## 4. Human review effort for the full volume

Volume I has about 112 Table 5.2 pages (×~272 cells) and 6 Table 5.3 pages (×486), so
about **33,400 cells**.

| Flag rate | Cells to review |
|---|---|
| Dev, 8.6% | about 2,900 |
| Holdout, 13.4% | about 4,500 |

At 5–10 seconds per cell, with crop, readers and page context in the review pack, that is
roughly **4–12 hours** of focused review. Add:

- about 1 hour of page-level checks: run keys, the seven template-repaired pages, PDF page 200
  (not detected; see section 6);
- the blank-vs-missing question, settled once as a convention rather than per cell.

**What review will not catch:** errors that every reader makes the same way. On the pilot
this is 0.3–0.8% of cells under the value-only measure, and the inspected examples look
largely like reference-side differences. Comparing against the reference afterwards, with the
owner judging the conflicts, covers this, as planned.

## 5. What I would change before scaling up

1. **Run Mistral on the whole volume first**, then compare with the reference per page,
   before any targeted Sonnet use. This is the next step agreed with the owner.
2. **Settle the blank-vs-missing convention in scoring.** Report it as its own category
   so it doesn't swamp real disagreements.
3. **Tighten the cross-check rule.** Flag when *either* offline reader agrees with neither
   Mistral nor the other reader, and the cell is in fair print. That would have caught the
   27.8/27.6 case. Tune it on more pages, not on the holdout.
4. **Add the checks the data supports:**
   - page seams (half A and half B of the same run join at post 90/91);
   - towers against the 100 m arc samplers at neighbouring bearings;
   - centreline consistency across arcs within a run.
5. **Fix page detection.** PDF page 200 (printed 187) is a Table 5.2 page that recon misses.
6. **Make review faster.** Record verdicts in the review pack itself rather than on paper.
   Prioritise by a combined score of flags, Mistral confidence and residual.

## 6. What in the brief turned out to be wrong or incomplete

- **The reference is not a clean answer key.** It encodes printed blanks as "missing" in
  places. Several cells where every reader agrees on a clean print differ from it. Its
  arcs-file header suggests µg m⁻³ while its values are in mg m⁻³. "Disagreement with the
  reference" is therefore an upper bound on reading error, not the error rate.
- **Offline OCR is not good enough here** to be the backbone at a reasonable review cost.
  A cheap cloud OCR reader changes the economics. The "at least one offline reader" rule is
  still met, as a cross-check.
- **"Physically implausible against neighbours"** needed a sharper definition than "10× from
  both neighbours". Interpolation between neighbours at ×4 is what catches decimal errors.

## 7. Disclosures (what was seen before the freeze)

- **Holdout pages seen during structure development:** PDF pages 98 and 211, structure only
  (rules, rows, headers). No values were read by me and no reference values were looked at.
- **Holdout tower page 211:** the project owner read the run-number headers from the scan,
  recorded in `config/manual_keys.yaml`. Keys only.
- **The ×4 neighbour threshold** was informed by an exploratory analysis of natural scatter
  across **all** reference arc profiles, including runs on holdout pages. It used aggregate
  statistics only; no holdout cell was looked at. I disclose it because the analysis
  touched holdout-run data before the freeze.
- **All reader comparisons were on dev pages only:** Haiku, Sonnet, Mistral and the flag
  tuning. Holdout pages were extracted once, after the tag, and scored once. Dev pages were
  re-scored after the freeze to rebuild the review pack; dev scoring is not part of the freeze.
- **The pilot selection was regenerated once,** after the column-template fix and before
  any extraction. The rule and seed are in `config/pilot_pages.yaml`.

## Reproducing

```
make pilot   # recon, selection, extraction, tests, reference fetch, scoring (dev), review pack
make score-holdout   # holdout scoring; refuses to run without the extraction-frozen tag
```

The Mistral responses for pilot pages are committed, so `make pilot` needs no Mistral key.
The reference is downloaded into the gitignored `reference/`, with SHA-256 checksums in
`scoring/reference_checksums.json`. The review pack (`review/index.html`) and scores contain
reference values and are therefore not committed; `make pilot` regenerates them.

---

## Addendum (post-pilot): all of Volume I

*Written after the pilot was complete (tag `pilot-v1`). It uses code changed after the
holdout scoring and is **not** part of the pilot's holdout result.*

**Run.** The frozen pipeline ran over all 118 Table 5.2 / 5.3 pages, including PDF page 200,
which recon misses. Mistral cost was about $0.50. Sonnet was not used. Run with
`make volume`; outputs are in `output/volume1/`.

**One post-pilot code change.** On PDF pages 97 and 103, Mistral returned the column-heading
row as a data row, which shifted all their rows. The flags caught every affected cell (116
conflicts, all flagged). `extract.mistral.drop_header_rows` now skips such rows. Only these
two responses are affected, and re-parsing them needed no new API calls.

**Result: 158 conflicts with the reference in 33,048 keyed cells (0.48%; 1.7% of cells with
a number).** The pipeline flags 7.95% of cells.

| What | Cells | Notes |
|---|---|---|
| Blank in print, "missing" in reference | 42 | convention difference; not counted as conflicts |
| PDF page 196 (run 61, 800 m arc) | 26 | **ambiguous layout, not a proven reference error** (corrected 2026-11-14): the 800 m values drift off the post grid on this page, many sitting between two post numbers. Posts 95–132 hold 38 printed values for 38 posts, so our one-to-one assignment is self-consistent, but the reference assigns some differently; a person decides |
| PDF page 106 (run 7, 100 m arc, posts 46+) | 25 | the **reference** repeats the 200 m column in the 100 m slot (22 of 27 identical); the print shows different values (checked at posts 51–53) |
| Other conflicts, all three readers agree | 38 | 11 flagged; 18 differ by < 12%, 7 by ×10 or more (e.g. 2.69 vs 0.269, 0.090 vs 0.900), so reference errors or ambiguous print |
| Other conflicts, readers differ | 69 | 43 flagged; mostly Mistral misreads of a single digit (34 within 12%) |
| PDF page 200 | 270 cells | first run unkeyed (Mistral read the header as "86"). Now keyed as run 66 by the owner, **inferred from page order** (half B of run 66 is PDF 201), recorded as such in `config/manual_keys.yaml`. With that key 269 of 270 cells match the reference, an independent confirmation |

**What this means for the dataset.**
- Reading quality is high. Systematic problems are rare and visible: whole-page row shifts
  show up as clusters of flagged conflicts.
- The reference contains real errors: whole-column copy and shift errors, plus scattered
  ×10 differences. That supports building the dataset from the scan, with the reference
  used only to find cells worth a second look.
- **Unflagged real misreads** are at most the 26 unflagged "readers differ" conflicts plus
  any of the 27 unflagged "all agree" cells that turn out to be misreads. Either way, fewer
  than 1 in 600 cells.
- **Owner's triage design:** sending reference conflicts to Sonnet and then to a person
  means about 158 cells. Sonnet would cost under $0.50. About 1–2 hours of human review.

### Update 2026-11-14: blank vs missing, run 66, triage

**What a blank means.** Both table introductions say it explicitly:
- Table 5.2, printed p. 79 (PDF 92): *"the letter "M" indicates missing data and the blank
  spaces denote no measurable concentration."*
- Table 5.3, printed p. 193 (PDF 206): *"The letter "M" indicates missing data, and blank
  spaces in the table signify no measurable concentration."*
- Table 5.4 (printed p. 200) uses the opposite: *"Blank spaces signify missing data."*

Every extracted cell now carries `status`, derived only from the printed token:
`value`, `not_measurable` (printed blank), `missing` (printed M) or `unread` (token not
interpretable; 2 cells). A blank is never written as 0 or as missing. `no_station`
cannot occur, because the grid creates cells only where a sampler stood; a test checks
this. Volume I: 9,267 value, 24,006 not_measurable, 43 missing, 2 unread.

**Printed zeros.** Two cells print an explicit zero: run 1, 800 m post 31 (`0.000`, PDF 94),
and run 30, 800 m post 98 (`0`, PDF 148). They are kept as printed (status `value`, 0.0).
The reference stores 0 for blank, so it cannot tell them apart. Both are in the conflict
list.

**Code changes (post-pilot).**
- A manual key can carry its own method, e.g. "inferred from page order".
- On a page keyed by a person, Mistral's disagreeing header reading becomes an `info:`
  note rather than a structural flag on every cell.
- Re-running Volume I from the Mistral cache made no new API calls. It changed only
  PDF 200 (keyed now) and added the status column.

**Totals.** 159 conflicts in 33,318 keyed cells (0.48%).

**Triage.** `scoring/triage.py` sends only the conflict cells to Claude Sonnet (mode
`context`: the cell outlined in a strip of its column, pixels only, no reference and no
other readings). It halts before any call if more than 250 cells would go. Raw responses
go to `cache/reader_llm/` (committed) and `output/volume1/triage/sonnet_reads.csv`; spend
goes to `output/volume1/triage/spend.json`. The review pack is `review/volume1/index.html`
(local only). It groups the conflicts as follows:
- A: ambiguous layout, PDF 196 (25 cells);
- B: suspected reference column copy, PDF 106 (23);
- C: Mistral, Tesseract and EasyOCR give the same token (42);
- D: readers differ (69).

Verdicts are entered in the page and saved to `review/volume1/verdicts.csv`.

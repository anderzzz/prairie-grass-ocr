"""Reconnaissance: page-number map and table-page inventory.

Everything here is derived from the scan with our own OCR (tesseract). The
PDF's embedded text layer is someone else's OCR and is deliberately not used.

Outputs
  docs/page_map.csv      pdf_index -> printed page number
  docs/page_inventory.csv  one row per table page (written by `inventory`)
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .pdfio import REPO, page_count, page_image
from .tess import ocr_words

DOCS = REPO / "docs"


def _band_text(words: list[dict]) -> str:
    lines: dict = {}
    for w in words:
        lines.setdefault(tuple(w["line"]), []).append(w)
    out = []
    for key in sorted(lines, key=lambda k: min(w["top"] for w in lines[k])):
        out.append(" ".join(w["text"] for w in sorted(lines[key], key=lambda w: w["left"])))
    return "\n".join(out)


def scan_page(idx: int) -> dict:
    img = page_image(idx)
    h, w = img.shape
    top = img[: int(h * 0.40), :]
    bottom = img[int(h * 0.86):, :]
    top_words = ocr_words(top, psm=6, namespace="recon_top")
    bot_words = ocr_words(bottom, psm=11, namespace="recon_bottom")
    # printed page number: a bare integer near the horizontal centre of the footer
    nums = []
    for wd in bot_words:
        cx = wd["left"] + wd["width"] / 2
        if re.fullmatch(r"\d{1,3}", wd["text"]) and 0.35 * w < cx < 0.65 * w:
            nums.append((wd["conf"], int(wd["text"])))
    ocr_page = max(nums)[1] if nums else None
    return {"pdf_index": idx, "ocr_page": ocr_page, "top_text": _band_text(top_words)}


def scan_all(workers: int = 6) -> list[dict]:
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(scan_page, range(page_count())))


def fit_page_offset(rows: list[dict]) -> int:
    diffs = Counter(r["pdf_index"] - r["ocr_page"] for r in rows if r["ocr_page"])
    return diffs.most_common(1)[0][0]


RUN_RE = re.compile(r"RUN\s*N[O0o][.,]?\s*(\d{1,2})\s*(-?\s*[S8$]\b)?", re.I)


def classify(top_text: str) -> str | None:
    """Table type from the page's own header text (OCR variants tolerated)."""
    t = top_text
    if re.search(r"Table\s*5\s*[.,]\s*1\s*[.,]?\s*Source\s+strengths", t, re.I):
        return "5.1"
    if re.search(r"Correction\s+factors", t, re.I) or re.search(r"T\w{3,4}\s*[5S§68]\s*[.,]\s*4\b", t):
        return "5.4"
    if not re.search(r"CONCENTRATION\s*\(", t):
        return None  # narrative pages that merely mention a table
    if re.search(r"Tower|Height|Run\s*No\.?\s*$", t, re.M):
        return "5.3"
    if RUN_RE.search(t):
        return "5.2"
    return None


def header_run(top_text: str) -> str | None:
    m = RUN_RE.search(top_text)
    return None if not m else m.group(1) + ("S" if m.group(2) else "")  # '35-S' -> '35S'


def write_page_map(rows: list[dict], offset: int) -> Path:
    DOCS.mkdir(exist_ok=True)
    path = DOCS / "page_map.csv"
    with path.open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["pdf_index", "printed_page_fitted", "printed_page_ocr", "agrees"])
        for r in rows:
            fitted = r["pdf_index"] - offset
            fitted_s = fitted if fitted >= 1 else ""
            agrees = "" if r["ocr_page"] is None else str(r["ocr_page"] == fitted).lower()
            wr.writerow([r["pdf_index"], fitted_s, r["ocr_page"] or "", agrees])
    return path


# --------------------------------------------------------------------------
# inventory of table pages

def _inventory_row(args: tuple[int, str, str]) -> dict:
    from .preprocess import PreprocessConfig, glyph_metrics, preprocess
    from . import structure as S
    idx, table, top_text = args
    img, info = preprocess(page_image(idx), PreprocessConfig())
    row = {"pdf_index": idx, "table": table, "skew_deg": info.get("skew_deg")}
    if table == "5.2":
        st = S.analyse_arc_page(img)
        row["run_header_ocr"] = header_run(top_text) or ""
        row["run_header_easyocr"] = header_run_easyocr(idx)
        row["half"] = st.meta.get("half") or ""
        row["anomalies"] = len(st.anomalies)
        box = st.table_box
    elif table == "5.3":
        st = S.analyse_tower_page(img)
        row["runs"] = " ".join(tower_header_runs(img, st))
        row["anomalies"] = len(st.anomalies)
        box = st.table_box
    else:
        xs, (y0, y1) = S.vertical_boundaries(img)
        h, w = img.shape
        box = (int(0.08 * w), int(0.15 * h), int(0.92 * w), int(0.85 * h))
        words = ocr_words(img[box[1]:box[3], box[0]:int(box[0] + 0.2 * w)], psm=6, namespace="recon_runs")
        nums = sorted(int(m) for wd in words for m in re.findall(r"^(\d{1,2})S?$", wd["text"]))
        row["runs"] = f"{nums[0]}-{nums[-1]}" if nums else ""
    if box:
        row.update(glyph_metrics(img, box))
    return row


def tower_header_runs(img, st) -> list[str]:
    """Run labels of a Table 5.3 page's columns ('?' where readers disagree)."""
    from .keys import read_tower_runs
    return [c["run"] or "?" for c in read_tower_runs(img, st)]


def header_run_easyocr(idx: int) -> str:
    """Second, independent reading of the 'RUN NO.' label (EasyOCR detector +
    recogniser on the header strip). Cached."""
    from .cache import cached
    from .readers import _easyocr
    img = page_image(idx)
    h = img.shape[0]
    strip = img[int(h * 0.08): int(h * 0.24), :]

    def run():
        res = _easyocr().readtext(strip, detail=0, paragraph=False)
        return {"texts": res}

    texts = cached("recon_header_easyocr", {"v": 1}, strip, run)["texts"]
    m = RUN_RE.search(" ".join(texts))
    return "" if not m else m.group(1) + ("S" if m.group(2) else "")


def run_order(run: str) -> float | None:
    """Sort key for run labels. 'nS' runs (printed '35-S', '48-S') precede
    run n in Table 5.2 (they were made earlier; see the DATE/TIME headers)."""
    m = re.fullmatch(r"(\d{1,2})(S?)", run or "")
    if not m:
        return None
    return int(m.group(1)) - (0.5 if m.group(2) else 0.0)


def resolve_arc_runs(rows: list[dict]) -> None:
    """Resolve the run label of every Table 5.2 page.

    Each page's own header reading is accepted when it is consistent with
    the run order: not before the previous readable page, not after the next
    one, and not a second page for the same (run, half). Otherwise the page is
    attached to an adjacent page of the other half (A followed by B), or left
    unresolved. Not every run has both halves (e.g. run 46 has only posts
    1-90, run 47 only 91-181), so pairing is never assumed when the page's
    own reading is acceptable. `run_source` records the basis.
    """
    arc = [r for r in rows if r["table"] == "5.2"]
    for p in arc:
        a, b = p.get("run_header_ocr") or "", p.get("run_header_easyocr") or ""
        p["run_reads"] = f"tesseract={a or '-'} easyocr={b or '-'}"
    # readers agreeing, else whichever single reading exists; conflicts are
    # left to the order test below (each candidate tried in turn)
    reads = []
    for p in arc:
        a, b = p.get("run_header_ocr") or "", p.get("run_header_easyocr") or ""
        reads.append(a if a == b else (a or b) if not (a and b) else "")
    alts = [[x for x in (p.get("run_header_ocr"), p.get("run_header_easyocr")) if x] for p in arc]
    keys = [run_order(x) for x in reads]
    n = len(arc)
    ok = [False] * n
    for i in range(n):
        if keys[i] is None:
            continue
        prev = next((keys[j] for j in range(i - 1, -1, -1) if keys[j] is not None), None)
        nxt = next((keys[j] for j in range(i + 1, n) if keys[j] is not None), None)
        ok[i] = (prev is None or keys[i] >= prev) and (nxt is None or keys[i] <= nxt)
    # a reading that breaks order against an outlier neighbour: re-test
    # against the nearest *accepted* neighbours
    for i in range(n):
        if keys[i] is None or ok[i]:
            continue
        prev = next((keys[j] for j in range(i - 1, -1, -1) if ok[j]), None)
        nxt = next((keys[j] for j in range(i + 1, n) if ok[j]), None)
        ok[i] = (prev is None or keys[i] >= prev) and (nxt is None or keys[i] <= nxt)
    seen: set = set()
    for i, p in enumerate(arc):
        if ok[i] and (reads[i], p.get("half")) not in seen:
            p["run"], p["run_source"] = reads[i], "header" if "-" not in p["run_reads"] else "header (one reader)"
            seen.add((reads[i], p.get("half")))
    for i, p in enumerate(arc):
        if str(p.get("run_source", "")).startswith("header"):
            continue
        cand = None
        if p.get("half") == "B" and i > 0 and arc[i - 1].get("half") == "A" and str(arc[i - 1].get("run_source", "")).startswith("header"):
            cand = arc[i - 1]["run"]
        elif p.get("half") == "A" and i + 1 < n and arc[i + 1].get("half") == "B" and str(arc[i + 1].get("run_source", "")).startswith("header"):
            cand = arc[i + 1]["run"]
        if not cand:
            # conflicting readers: take the candidate that fits the run order
            prev = next((run_order(arc[j]["run"]) for j in range(i - 1, -1, -1)
                         if str(arc[j].get("run_source", "")).startswith("header")), None)
            nxt = next((run_order(arc[j]["run"]) for j in range(i + 1, n)
                        if str(arc[j].get("run_source", "")).startswith("header")), None)
            fit = [x for x in alts[i] if run_order(x) is not None
                   and (prev is None or run_order(x) >= prev) and (nxt is None or run_order(x) <= nxt)
                   and (x, p.get("half")) not in seen]
            if len(set(fit)) == 1:
                p["run"], p["run_source"] = fit[0], f"readers disagree ({p['run_reads']}); chosen by run order"
                seen.add((fit[0], p.get("half")))
                continue
        if cand and (cand, p.get("half")) not in seen:
            p["run"], p["run_source"] = cand, f"header read '{reads[i]}' rejected; paired with adjacent page"
            seen.add((cand, p.get("half")))
        else:
            p["run"], p["run_source"] = "", f"unresolved (header read '{reads[i]}')"


def classify_by_rules(idx: int, top_text: str) -> str | None:
    """Fallback when the header text is unreadable: a Table 5.2 page has
    exactly 15 long vertical rules (2 panels x 7 columns + outer rule) and a
    concentration header; this layout occurs nowhere else in the volume."""
    from . import structure as S
    from .preprocess import PreprocessConfig, preprocess
    if not re.search(r"CONCENTRATION|RUN|Table|DATE|TIME", top_text, re.I):
        return None
    img, _ = preprocess(page_image(idx), PreprocessConfig())
    xs, _ = S.vertical_boundaries(img)
    return "5.2" if len(xs) == 15 else None


INVENTORY_FIELDS = ["pdf_index", "printed_page", "table", "runs", "half", "posts_800m",
                    "stroke_px", "intact_frac", "legibility", "char_components",
                    "skew_deg", "structure_anomalies", "run_reads", "run_source"]


def build_inventory(scan_rows: list[dict], offset: int, workers: int = 6) -> list[dict]:
    jobs = []
    for r in scan_rows:
        t = classify(r["top_text"]) or classify_by_rules(r["pdf_index"], r["top_text"])
        if t:
            jobs.append((r["pdf_index"], t, r["top_text"]))
    with ProcessPoolExecutor(workers) as ex:
        inv = list(ex.map(_inventory_row, jobs))
    resolve_arc_runs(inv)
    for r in inv:
        r["printed_page"] = r["pdf_index"] - offset
        if r["table"] == "5.2":
            r["runs"] = r.get("run", "")
            r["posts_800m"] = {"A": "1-90", "B": "91-181"}.get(r.get("half", ""), "")
        r["structure_anomalies"] = r.pop("anomalies", "")
    return inv


def write_inventory(inv: list[dict]) -> Path:
    path = DOCS / "page_inventory.csv"
    with path.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=INVENTORY_FIELDS, extrasaction="ignore")
        wr.writeheader()
        for r in inv:
            wr.writerow(r)
    return path


def main() -> None:
    rows = scan_all()
    offset = fit_page_offset(rows)
    write_page_map(rows, offset)
    inv = build_inventory(rows, offset)
    write_inventory(inv)
    print(f"page offset {offset}; {len(inv)} table pages")


if __name__ == "__main__":
    main()

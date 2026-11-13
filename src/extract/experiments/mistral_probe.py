"""Probe Mistral OCR (page-level document OCR) as a reader on dev pages.

    uv run python -m extract.experiments.mistral_probe [--model mistral-ocr-4-1]

Sends each dev page image (after deskew, as the pipeline sees it) once,
asks for HTML tables with word confidences, caches the raw response, and
maps the table cells onto the pipeline's cells (output/extracted/p<idx>.csv):

* Table 5.2: the HTML grid has 14 cells per row (two panels of inner post,
  800 m post, five arcs). Data row i is the pipeline's row i; Mistral's own
  800 m post number in that row is checked against the expected one and a
  mismatch is recorded (`key_ok`). Inner-arc values are taken from rows that
  carry an inner post number.
* Table 5.3: rows carry tower (rowspan) and height; the run columns are
  matched by position to the pipeline's column keys, because Mistral's
  header reading is not reliable.

Writes output/experiments/mistral_<model>.csv. No reference data is read.
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import os
import re

import cv2

from ..cache import cached
from ..pdfio import REPO, page_image
from ..pipeline import PRESETS
from ..preprocess import preprocess
from ..select_pages import load_or_create

OUT = REPO / "output" / "experiments"
PRICE_PER_PAGE = {"mistral-ocr-4-1": 4 / 1000, "mistral-ocr-3": 2 / 1000}

CELL_RE = re.compile(r"<t([dh])([^>]*)>(.*?)</t[dh]>", re.S)
ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)


def call(idx: int, model: str) -> dict:
    img, _ = preprocess(page_image(idx), PRESETS["default"])

    def run():
        from mistralai.client import Mistral
        ok, buf = cv2.imencode(".png", img)
        uri = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()
        c = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        r = c.ocr.process(model=model, document={"type": "image_url", "image_url": uri},
                          table_format="html", confidence_scores_granularity="word")
        return r.model_dump()

    return cached("reader_mistral_page", {"model": model, "table_format": "html",
                                          "conf": "word"}, img, run)


def parse_rows(table: dict) -> list[list[dict]]:
    """Rows of <td> cells with text, rowspan and min word confidence."""
    content = table["content"]
    words = table.get("word_confidence_scores") or []
    rows = []
    for rm in ROW_RE.finditer(content):
        cells = []
        for cm in CELL_RE.finditer(rm.group(1)):
            if cm.group(1) != "d":
                continue
            a, b = rm.start(1) + cm.start(3), rm.start(1) + cm.end(3)
            confs = [w["confidence"] for w in words if a <= w["start_index"] < b]
            txt = html.unescape(re.sub(r"<[^>]+>", " ", cm.group(3))).strip()
            span = re.search(r'rowspan="(\d+)"', cm.group(2))
            cells.append({"text": txt, "conf": min(confs) if confs else None,
                          "rowspan": int(span.group(1)) if span else 1})
        if cells:
            rows.append(cells)
    return rows


def map_arc(idx: int, rows: list[list[dict]], cells: list[dict]) -> list[dict]:
    by_key = {(c["arc_m"], c["post"]): c["cell_id"] for c in cells}
    posts800 = sorted({int(c["post"]) for c in cells if c["arc_m"] == "800"})
    # pipeline panels: first half of the 800 m posts left, the rest right
    half = (len(posts800) + 1) // 2 if len(posts800) % 2 else len(posts800) // 2
    left, right = posts800[:45], posts800[45:]
    out = []
    for i, r in enumerate(rows):
        if len(r) != 14:
            out.append({"row": i, "problem": f"{len(r)} cells in row"})
            continue
        for pidx, (exp_posts, off) in enumerate(((left, 0), (right, 7))):
            if i >= len(exp_posts):
                continue
            p800 = exp_posts[i]
            got = r[off + 1]["text"]
            key_ok = got == str(p800)
            vals = [c["text"] for c in r[off + 2: off + 7]]
            confs = [c["conf"] for c in r[off + 2: off + 7]]
            out.append({"cell_id": by_key.get(("800", str(p800))), "text": vals[4],
                        "conf": confs[4], "key_read": got, "key_ok": key_ok})
            if p800 % 2 == 1:
                inner = (p800 + 1) // 2
                for d, v, cf in zip(("50", "100", "200", "400"), vals[:4], confs[:4]):
                    out.append({"cell_id": by_key.get((d, str(inner))), "text": v, "conf": cf,
                                "key_read": r[off]["text"], "key_ok": r[off]["text"] == str(inner)})
            else:
                # an inner-arc value printed on the even row is recorded, not dropped
                for d, v in zip(("50", "100", "200", "400"), vals[:4]):
                    if v:
                        out.append({"row": i, "problem": f"value '{v}' on even row, arc {d}"})
    return out


def map_tower(idx: int, rows: list[list[dict]], cells: list[dict], meta: dict) -> list[dict]:
    col_runs = [c for c in meta["tower_column_runs"]]
    by_key = {(c["tower"], c["height_m"], c["run"]): c["cell_id"] for c in cells}
    out, tower = [], 0
    heights = ["17.5", "13.5", "10.5", "7.5", "4.5", "2.5", "1.5", "1.0", "0.5"]
    for r in rows:
        if r[0]["rowspan"] > 1 or len(r) == len(col_runs) + 2:
            tower += 1
            r = r[1:]
        if len(r) != len(col_runs) + 1:
            out.append({"problem": f"tower {tower}: {len(r)} cells in row"})
            continue
        h = r[0]["text"]
        if h not in heights:
            out.append({"problem": f"tower {tower}: height '{h}'"})
            continue
        for c, cell in zip(col_runs, r[1:]):
            if not c.get("run"):
                continue
            out.append({"cell_id": by_key.get((str(tower), h, c["run"])), "text": cell["text"],
                        "conf": cell["conf"], "key_read": h, "key_ok": True})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="mistral-ocr-4-1")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    allrows, problems, pages = [], [], 0
    for e in load_or_create()["dev"]:
        idx = e["pdf_index"]
        cells = list(csv.DictReader((REPO / "output" / "extracted" / f"p{idx}.csv").open()))
        meta = json.loads((REPO / "output" / "extracted" / f"p{idx}.meta.json").read_text())
        d = call(idx, a.model)
        pages += d["usage_info"]["pages_processed"]
        tables = d["pages"][0].get("tables") or []
        if len(tables) != 1:
            problems.append(f"p{idx}: {len(tables)} tables")
            continue
        rows = parse_rows(tables[0])
        mapped = (map_arc(idx, rows, cells) if e["table"] == "5.2"
                  else map_tower(idx, rows, cells, meta))
        for m in mapped:
            if "problem" in m:
                problems.append(f"p{idx}: {m['problem']}")
            elif m["cell_id"]:
                allrows.append(m)
        n = sum(1 for m in mapped if m.get("cell_id"))
        print(f"p{idx}: {len(rows)} table rows, {n} of {len(cells)} pipeline cells mapped, "
              f"{sum(1 for m in mapped if m.get('cell_id') and not m['key_ok'])} row-key mismatches")
    path = OUT / f"mistral_{a.model}.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cell_id", "text", "conf", "key_read", "key_ok"])
        w.writeheader()
        w.writerows(allrows)
    print(f"wrote {path}; {pages} pages processed (~${pages * PRICE_PER_PAGE.get(a.model, 0):.3f})")
    for p in problems[:30]:
        print("  problem:", p)


if __name__ == "__main__":
    main()

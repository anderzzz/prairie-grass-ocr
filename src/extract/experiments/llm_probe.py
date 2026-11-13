"""Probe a vision LLM as a cell reader on dev pages (experiment).

    PGOCR_LLM_MAX_CALLS=... uv run python -m extract.experiments.llm_probe \
        --model claude-haiku-5-5 --modes glyphs,cell,cell_rules,context [--limit N]

Reads the dev pages' cells (boxes from output/extracted/p<idx>.csv, so the
pipeline must have run) in each requested mode and writes the raw responses
to output/experiments/llm_probe_<model>.csv. Cells: every cell in which the
offline readers found glyph ink; the `context` mode only on cells the
pipeline flagged at cell level (readers disagree, low confidence or
unexpected token), which is where an extra reader would be consulted.
No reference data is read here; evaluation happens outside src/extract.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .. import structure as S
from ..llm import LLMReader, cost_usd, spend
from ..pdfio import REPO, page_image
from ..pipeline import MARGIN, PRESETS, remove_vertical_rules
from ..preprocess import preprocess
from ..select_pages import load_or_create

OUT = REPO / "output" / "experiments"


def cell_flagged(r: dict) -> bool:
    return any(r[k] == "True" for k in ("flag_readers_disagree", "flag_low_confidence",
                                        "flag_token_unexpected"))


def jobs_for_page(idx: int, modes: list[str]) -> list[tuple]:
    rows = list(csv.DictReader((REPO / "output" / "extracted" / f"p{idx}.csv").open()))
    img, _ = preprocess(page_image(idx), PRESETS["default"])
    img_r = remove_vertical_rules(img)
    H, W = img.shape
    out = []
    for r in rows:
        if r["raw_tesseract"] == "" and r["raw_easyocr"] == "" and int(r["ink_components"]) == 0:
            continue
        if not (r["raw_tesseract"] or r["raw_easyocr"]):
            continue  # readers were skipped: no glyph-height ink
        x0, y0, x1, y1 = map(int, r["box"].split(","))
        ex0, ex1 = max(0, x0 - MARGIN), min(W, x1 + MARGIN)
        glyphs, _ = S.isolate_glyphs(img_r[y0:y1, ex0:ex1], interior=(x0 - ex0, x1 - ex0))
        raw = img[y0:y1, ex0:ex1]
        for m in modes:
            if m == "context":
                if not cell_flagged(r):
                    continue
                h = y1 - y0
                sy0, sy1 = max(0, y0 - 2 * h), min(H, y1 + 2 * h)
                strip = cv2.cvtColor(img[sy0:sy1, ex0:ex1], cv2.COLOR_GRAY2BGR)
                cv2.rectangle(strip, (x0 - ex0, y0 - sy0), (x1 - ex0 - 1, y1 - sy0 - 1), (0, 0, 255), 2)
                out.append((r["cell_id"], m, glyphs, strip))
            else:
                out.append((r["cell_id"], m, glyphs, raw))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--modes", default="glyphs,cell,cell_rules,context")
    ap.add_argument("--limit", type=int, default=0, help="max cells per mode (smoke test)")
    ap.add_argument("--effort", default="low")
    a = ap.parse_args()
    modes = a.modes.split(",")
    jobs = []
    for e in load_or_create()["dev"]:
        jobs += jobs_for_page(e["pdf_index"], modes)
    if a.limit:
        per = {}
        kept = []
        for j in jobs:
            per[j[1]] = per.get(j[1], 0) + 1
            if per[j[1]] <= a.limit:
                kept.append(j)
        jobs = kept
    print(f"{len(jobs)} reads: " + ", ".join(f"{m} {sum(j[1] == m for j in jobs)}" for m in modes))
    readers = {m: LLMReader(model=a.model, mode=m, effort=a.effort) for m in modes}

    def run(j):
        cid, m, glyphs, raw = j
        return cid, m, readers[m].read(glyphs, raw)

    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(run, jobs))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"llm_probe_{a.model}.csv"
    tot_in = tot_out = 0
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cell_id", "mode", "text", "uncertain", "note", "raw_response",
                    "input_tokens", "output_tokens", "stop_reason"])
        for cid, m, r in res:
            tot_in += r["usage"]["input_tokens"]
            tot_out += r["usage"]["output_tokens"]
            w.writerow([cid, m, r["text"], r["uncertain"], r["note"], r["raw_response"],
                        r["usage"]["input_tokens"], r["usage"]["output_tokens"], r["stop_reason"]])
    s = spend()
    print(f"wrote {path}")
    print(f"all reads (incl. cached): {tot_in} in / {tot_out} out tokens = "
          f"${cost_usd(a.model, tot_in, tot_out):.4f}")
    print(f"new calls this run: {s['calls']}, {s['input_tokens']} in / {s['output_tokens']} out "
          f"= ${cost_usd(a.model, s['input_tokens'], s['output_tokens']):.4f}")


if __name__ == "__main__":
    main()

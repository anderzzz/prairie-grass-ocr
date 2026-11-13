"""End-to-end extraction for pilot pages.

    uv run python -m extract.pipeline [--set dev|holdout|all] [--preprocess raw|default|repair]

For each page: preprocess -> structure -> keyed cells -> ink check -> readers
-> consensus -> flags. Writes output/extracted/p<idx>.csv (one row per cell)
and output/crops/p<idx>/<cell_id>.png. Values are never filled, smoothed or
corrected: a cell's consensus is one of the readers' tokens, verbatim apart
from the documented normalisation (comma read as decimal point, spaces
dropped), and plausibility checks only raise flags.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from . import structure as S
from .cells import CellSpec, arc_cells, ink_stats, tower_cells
from . import manual_keys
from .keys import read_tower_runs
from .pdfio import REPO, page_image
from .preprocess import PreprocessConfig, preprocess
from .readers import default_readers
from .select_pages import load_or_create

OUT = REPO / "output"
PRESETS = {
    "raw": PreprocessConfig(deskew=False, despeckle=False, repair=False),
    "default": PreprocessConfig(),
    "repair": PreprocessConfig(repair=True),
}

# thresholds (tuned on dev pages only; see REPORT.md)
CONF_MIN = {"tesseract": 0.80, "easyocr": 0.80}
IMPLAUSIBLE_LOG10 = 1.0   # >10x away from both same-arc neighbours
MARGIN = 16               # px read beyond a cell's rules (digits can overlap them)
V_RULE_MIN = 90           # vertical ink runs this long are rules, not glyphs


def remove_vertical_rules(img: np.ndarray) -> np.ndarray:
    """Whiten vertical ink runs >= V_RULE_MIN px (the column rules) and a
    2 px fringe, so digits overlapping a rule are not fused with it."""
    ink = (img < 128).astype(np.uint8)
    v = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, V_RULE_MIN)))
    v = cv2.dilate(v, np.ones((1, 5), np.uint8))  # the rules' ragged fringe
    return np.where(v > 0, 255, img).astype(np.uint8)

VALUE_RE = re.compile(r"^(\d+(?:\.\d+)?)(\*?)$")


def normalise(tok: str) -> str:
    """Documented normalisation only: drop spaces, read ',' as '.'."""
    return (tok or "").replace(" ", "").replace(",", ".")


def parse(tok: str) -> dict:
    """Interpret a normalised token. Never alters digits."""
    if tok == "":
        return {"kind": "blank", "value": None, "estimated": False, "format_ok": True}
    if tok == "M":
        return {"kind": "missing", "value": None, "estimated": False, "format_ok": True}
    m = VALUE_RE.match(tok)
    if not m:
        return {"kind": "unparseable", "value": None, "estimated": False, "format_ok": False}
    s, star = m.group(1), m.group(2) == "*"
    v = float(s)
    return {"kind": "number", "value": v, "estimated": star, "format_ok": format_ok(s, v)}


def format_ok(s: str, v: float) -> bool:
    """Printed convention: 3 significant figures - 0.ddd below 1, d.dd below
    10, dd.d below 100, integers from 100."""
    if v < 1:
        return bool(re.fullmatch(r"0\.\d{3}", s))
    if v < 10:
        return bool(re.fullmatch(r"\d\.\d{2}", s))
    if v < 100:
        return bool(re.fullmatch(r"\d{2}\.\d", s))
    return bool(re.fullmatch(r"\d{3,4}", s))


def text_lines(glyph_img: np.ndarray) -> int:
    ink = (glyph_img < 128).sum(axis=1) > 0
    n, prev = 0, False
    gap = 0
    for on in ink:
        if on and not prev and gap >= 4:
            n += 1
        if on and n == 0:
            n = 1
        gap = 0 if on else gap + 1
        prev = on
    return n


def read_page(idx: int, table: str, run_label: str, run_note: str, cfg: PreprocessConfig,
              readers, crops_dir: Path | None) -> tuple[list[dict], dict]:
    img, info = preprocess(page_image(idx), cfg)
    if table == "5.2":
        st = S.analyse_arc_page(img)
        auto = run_label
        run_label, ksrc, mnote = manual_keys.arc_run(idx, auto)
        if ksrc != "pipeline":
            run_note = ""  # settled by a person; pipeline reading kept in run_auto
        cells = arc_cells(idx, st, run_label, run_note, ksrc, auto)
        col_runs = None
    else:
        st = S.analyse_tower_page(img)
        col_runs = manual_keys.apply_tower(idx, read_tower_runs(img, st))
        cells = tower_cells(idx, st, col_runs)
    page_meta = {"pdf_index": idx, "table": table, "run": run_label, "run_note": run_note,
                 "preprocess": info, "structure_anomalies": st.anomalies,
                 "half": st.meta.get("half"), "n_cells": len(cells),
                 "tower_column_runs": col_runs}
    if crops_dir:
        crops_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    img_r = remove_vertical_rules(img)
    W = img.shape[1]
    for c in cells:
        x0, y0, x1, y1 = c.box
        ex0, ex1 = max(0, x0 - MARGIN), min(W, x1 + MARGIN)
        crop = img_r[y0:y1, ex0:ex1]
        glyphs, ist = S.isolate_glyphs(crop, interior=(x0 - ex0, x1 - ex0))
        rec = {"cell_id": c.cell_id, "pdf_index": idx, "printed_page": idx - 13, "table": table,
               "run": c.run, "arc_m" if table == "5.2" else "tower": c.group,
               "post" if table == "5.2" else "height_m": c.position,
               "key_source": c.key_source, "run_auto": c.run_auto,
               "box": f"{x0},{y0},{x1},{y1}", "ink_px": ist["ink"],
               "ink_components": ist["components"]}
        if crops_dir:
            cv2.imwrite(str(crops_dir / f"{c.cell_id}.png"), img[y0:y1, ex0:ex1])
        # readers run only when a glyph-height component exists; fragments
        # alone are recorded (ink_components) and flagged, not read
        no_ink = ist["tall_components"] == 0
        for r in readers:
            if no_ink:
                res = {"text": "", "conf": None, "skipped": "no glyph-height ink"}
            else:
                res = r.read(glyphs)  # readers see only the isolated glyphs
            rec[f"raw_{r.name}"] = res["text"]
            rec[f"conf_{r.name}"] = res.get("conf")
        notes = list(c.structural)
        # glyph geometry checks
        if ist["components"] and not ist["tall_components"]:
            notes.append("only small ink fragments, not read (faint or broken print?)")
        if ist["bbox"] is not None:
            if text_lines(glyphs) > 1:
                notes.append("more than one line of text in cell")
            if c.table == "5.2" and c.group != "800":
                # inner-arc value should sit on the upper (odd-post) line
                cy = (ist["bbox"][1] + ist["bbox"][3]) / 2
                if cy > 0.62 * crop.shape[0]:
                    notes.append("inner-arc value sits on the even-post line")
        rec["_structural"] = notes
        rows.append(rec)
    consensus(rows, [r.name for r in readers])
    implausibility(rows, table)
    finalise(rows)
    return rows, page_meta


def consensus(rows: list[dict], names: list[str]) -> None:
    for rec in rows:
        toks = {n: normalise(rec[f"raw_{n}"]) for n in names}
        parsed = {n: parse(t) for n, t in toks.items()}
        distinct = set(toks.values())
        rec["flag_readers_disagree"] = len(distinct) > 1
        low = [n for n in names if rec[f"conf_{n}"] is not None and n in CONF_MIN
               and rec[f"conf_{n}"] < CONF_MIN[n]]
        rec["flag_low_confidence"] = bool(low)
        rec["_low"] = low
        if len(distinct) == 1:
            choice, src = names[0], "all readers agree"
        else:
            # prefer a token that parses and fits the printed format; among
            # those the higher reader confidence. Never construct a new token.
            def score(n):
                p = parsed[n]
                return (p["kind"] in ("number", "missing") and p["format_ok"],
                        p["kind"] != "unparseable", rec[f"conf_{n}"] or 0.0)
            choice = max(names, key=score)
            src = f"readers disagree; took {choice}"
        tok = toks[choice]
        p = parsed[choice]
        rec["consensus_token"] = tok
        rec["consensus_source"] = src
        rec["value_kind"] = p["kind"]
        rec["value"] = p["value"]
        rec["estimated_mark"] = p["estimated"]
        rec["flag_token_unexpected"] = (p["kind"] == "unparseable" or not p["format_ok"]
                                        or any(not parsed[n]["format_ok"] for n in names))


def implausibility(rows: list[dict], table: str) -> None:
    """Flag (never change) values >10x away from both neighbours on the same
    arc (Table 5.2) or the same tower (Table 5.3), when both neighbours have
    numbers; also values bordered by blanks on both sides on the 800 m arc
    are left alone (plume edges are legitimately abrupt)."""
    gkey = "arc_m" if table == "5.2" else "tower"
    pkey = "post" if table == "5.2" else "height_m"
    groups: dict = {}
    for rec in rows:
        groups.setdefault((rec["run"], rec[gkey]), []).append(rec)
    for recs in groups.values():
        if table == "5.2":
            recs.sort(key=lambda r: int(r[pkey]))
        for i, rec in enumerate(recs):
            rec["flag_implausible"] = False
            if rec["value_kind"] != "number" or not rec["value"]:
                continue
            nb = [recs[j] for j in (i - 1, i + 1) if 0 <= j < len(recs)]
            vals = [n["value"] for n in nb if n["value_kind"] == "number" and n["value"]]
            if len(vals) == 2:
                d = [abs(math.log10(rec["value"] / v)) for v in vals]
                if min(d) > IMPLAUSIBLE_LOG10:
                    rec["flag_implausible"] = True
                    rec["_structural"].append(
                        f"implausible: {rec['value']} vs neighbours {vals[0]}, {vals[1]}")


def finalise(rows: list[dict]) -> None:
    for rec in rows:
        notes = rec.pop("_structural")
        low = rec.pop("_low")
        rec["flag_structural"] = any(not n.startswith("implausible") for n in notes)
        if low:
            notes.append("low confidence: " + ", ".join(low))
        rec["flags_any"] = any(rec[k] for k in FLAG_COLS)
        rec["flag_notes"] = " | ".join(notes)


FLAG_COLS = ["flag_readers_disagree", "flag_low_confidence", "flag_token_unexpected",
             "flag_structural", "flag_implausible"]


def page_run_label(entry: dict) -> tuple[str, str]:
    """Run label from page selection; if recon did not get it from both
    readers agreeing on the header, every cell carries that doubt."""
    run = str(entry.get("runs") or "")
    if not run:
        return "", "run label unresolved"
    inv = REPO / "docs" / "page_inventory.csv"
    for r in csv.DictReader(inv.open()):
        if int(r["pdf_index"]) == entry["pdf_index"] and r["run_source"] != "header":
            return run, f"run label: {r['run_source']}"
    return run, ""


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def run(which: str = "all", preset: str = "default", out: Path = OUT, save_crops: bool = True) -> list[Path]:
    sel = load_or_create()
    pages = []
    for k in ("dev", "holdout"):
        if which in (k, "all"):
            pages += [(k, p) for p in sel[k]]
    readers = default_readers()
    written = []
    for subset, entry in pages:
        idx = entry["pdf_index"]
        run_label, note = page_run_label(entry) if entry["table"] == "5.2" else ("", "")
        crops = out / "crops" / f"p{idx}" if save_crops else None
        rows, meta = read_page(idx, entry["table"], run_label, note, PRESETS[preset], readers, crops)
        meta.update({"subset": subset, "readers": {r.name: r.describe() for r in readers},
                     "preprocess_preset": preset})
        path = out / "extracted" / f"p{idx}.csv"
        write_rows(path, rows)
        (out / "extracted" / f"p{idx}.meta.json").write_text(json.dumps(meta, indent=1, default=str))
        n_flag = sum(r["flags_any"] for r in rows)
        print(f"[{subset}] p{idx}: {len(rows)} cells, {n_flag} flagged")
        written.append(path)
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="all", choices=["dev", "holdout", "all"])
    ap.add_argument("--preprocess", default="default", choices=list(PRESETS))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    run(a.set, a.preprocess, Path(a.out))

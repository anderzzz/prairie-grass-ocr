"""Second reading of the rows involved in failed checks (Sonnet), and comparison.

    cd src && uv run python -m volume2.second_read [--no-llm] [--max-calls N] [--full 8.1 ...]

For every page with suspect cells, the involved rows are cut from the page
(row strips located by volume2.locate), stacked under the table's column
heading line, labelled A, B, C ... in a white margin, and sent to Sonnet in
one image (at most ROWS_PER_CALL rows). Sonnet is not shown Mistral's reading.
It transcribes every cell of each labelled row; the result is compared cell
by cell with Mistral's row. Responses are cached (cache/reader_llm) and the
spend is written to output/volume2/second_read/spend.json.

--full TABLE also re-reads every other row of that table (check "full_read"),
in calls of their own, so the readings of the check-involved rows stay as cached.

Output: output/volume2/second_read/reads.csv, one row per involved cell:
mistral token, sonnet token, agree, and the checks that involved it.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
from collections import defaultdict

import cv2
import numpy as np

from extract.cache import cached
from extract.llm import PRICES

from .common import norm, page_tables, txt
from .locate import locate_page, row_y
from .pages import OUT, image
from .run import parse_all

MODEL = "claude-sonnet-5-5"
EFFORT = "low"
ROWS_PER_CALL = 8
HALT_ABOVE = 150          # refuse to start if more calls than this would be needed
SECOND = OUT / "second_read"

PROMPT = """This image is cut from a printed 1950s table of meteorological observations.
The top strip (labelled H) shows the table's column headings. Below it are rows of the
same table, each labelled with a number in the left margin ({labels}).{extra}

For each labelled row, transcribe every cell from left to right, one entry per column of
the table as laid out under the headings, exactly as printed: digits, signs, decimal
points, asterisks, parentheses, '--' for a printed dash pair, words if a word is printed.
Use "" for a column that is blank in that row. Include the row's label column (the first
column) as the first entry when the table has one. Do not correct, complete or infer
anything; if a character is unclear, give your best reading and list the row label in
"unclear". The strips may cut the tops or bottoms of neighbouring rows: ignore those."""

SCHEMA = {"type": "object", "properties": {
    "rows": {"type": "array", "items": {"type": "object", "properties": {
        "label": {"type": "string"}, "cells": {"type": "array", "items": {"type": "string"}}},
        "required": ["label", "cells"], "additionalProperties": False}},
    "unclear": {"type": "array", "items": {"type": "string"}},
    "note": {"type": "string"}},
    "required": ["rows", "unclear", "note"], "additionalProperties": False}

EXTRA = {
    "13.1": " Transcribe only the first seven columns (Zp, P, T, #, RH, e, Td); skip Remarks.",
    "8.1": " The first column holds the row label (a height in metres or a quantity name).",
    "8.2": " The first column holds the row label (a height in metres or a quantity name).",
}


def heading_row(table: str, grid: list, k: int) -> int | None:
    """Grid index of the column-heading line that applies to grid row k."""
    def is_head(r):
        cells = [txt(c) for c in r]
        if table in ("8.1", "8.2"):
            return cells[0].upper().startswith(("CST", "CET"))
        if table == "12.1":
            return any(c.startswith(("P /", "Z /")) for c in cells if c)
        if table == "13.1":
            return len(cells) > 1 and cells[1].upper().startswith("P")
        return not any(re.fullmatch(r"[-+(.\d]+[\d)]", c or "") for c in cells[1:3])
    for j in range(k - 1, -1, -1):
        if is_head(grid[j]):
            return j
    return None


def refine_y(img: np.ndarray, y: float, h: float, x0: int, x1: int) -> float:
    """Centre of the band of text ink nearest to y (ruling lines removed)."""
    a, b = max(0, int(y - 1.3 * h)), int(y + 1.3 * h)
    ink = (img[a:b, x0:x1] < 128).astype(np.uint8)
    prof = ink.sum(1).astype(float)
    prof[prof > 0.5 * (x1 - x0)] = 0                     # horizontal rules
    vert = ink.sum(0) > 0.8 * (b - a)                    # vertical rules
    prof -= ink[:, vert].sum(1)
    on = prof > max(3.0, 0.15 * prof.max()) if prof.max() > 0 else prof > 1e9
    bands, start = [], None
    for i, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= 0.4 * h:
                bands.append((start + i) / 2)
            start = None
    if not bands:
        return y
    c = min(bands, key=lambda m: abs(a + m - y))
    return a + c if abs(a + c - y) < 0.9 * h else y


def strip(img: np.ndarray, y: float, h: float, x0: int, x1: int, rows: float = 1.0) -> np.ndarray:
    y = refine_y(img, y, h, x0, x1)
    a, b = int(y - 0.8 * h * rows), int(y + 0.8 * h * rows)
    return img[max(0, a): b, x0:x1]


def label_strip(s: np.ndarray, lab: str) -> np.ndarray:
    m = np.full((s.shape[0], 70), 255, np.uint8)
    cv2.putText(m, lab, (12, min(s.shape[0] - 6, s.shape[0] // 2 + 12)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    sep = np.full((6, s.shape[1] + 70), 255, np.uint8)
    sep[2:4] = 160
    return np.vstack([np.hstack([m, s]), sep])


def build_image(idx: int, table: str, ti: int, rows: list[int]) -> tuple[np.ndarray, list[str]]:
    img = image(idx)
    loc = locate_page(idx)
    grid = page_tables(idx)[ti]
    x0, x1 = loc["x_extent"].get(str(ti), [0, img.shape[1]])
    x0, x1 = max(0, int(x0) - 40), min(img.shape[1], int(x1) + 40)
    parts, labels = [], []
    heads = sorted({heading_row(table, grid, k) for k in rows} - {None})
    for hk in heads[:2]:
        y, h, _ = row_y(idx, ti, hk)
        if y is not None:
            if table in ("12.1", "13.1", "9.1", "9.2", "10.1"):
                # headings span two or three printed lines; the matched line is the lowest one
                a, b = int(y - 2.6 * h), int(y + 0.8 * h)
                parts.append(label_strip(img[max(0, a): b, x0:x1], "H"))
            else:
                parts.append(label_strip(strip(img, y, h, x0, x1), "H"))
    for n, k in enumerate(rows):
        y, h, _ = row_y(idx, ti, k)
        lab = str(n + 1)
        parts.append(label_strip(strip(img, y, h, x0, x1), lab))
        labels.append(lab)
    w = max(p.shape[1] for p in parts)
    parts = [np.hstack([p, np.full((p.shape[0], w - p.shape[1]), 255, np.uint8)]) for p in parts]
    return np.vstack(parts), labels


def call(img: np.ndarray, prompt: str, budget: dict) -> dict:
    params = {"model": MODEL, "effort": EFFORT, "prompt": prompt, "schema": "rows-v1"}

    def run():
        if budget["left"] <= 0:
            raise SystemExit("call budget exhausted")
        budget["left"] -= 1
        import anthropic
        ok, buf = cv2.imencode(".png", img)
        msg = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=4000,
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.b64encode(buf.tobytes()).decode()}},
                {"type": "text", "text": prompt}]}])
        raw = "".join(b.text for b in msg.content if b.type == "text")
        u = msg.usage
        budget["in"] += u.input_tokens
        budget["out"] += u.output_tokens
        budget["calls"] += 1
        return {"raw_response": raw, "model": msg.model, "stop_reason": msg.stop_reason,
                "request_id": getattr(msg, "_request_id", None),
                "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}}
    return cached("reader_llm", params, img, run)


FULL_TABLES = ("8.1", "8.2")    # tables read completely by Sonnet (0/6 confusion in smudged print)


def units(full: tuple[str, ...] = ()) -> tuple[dict, dict, dict, dict]:
    """(page, table, ti) -> sorted grid rows involved in checks; the same for the remaining rows
    of the fully re-read tables; cell_id -> checks; cell_id -> cell."""
    T, _ = parse_all()
    cells = {c["cell_id"]: c for rows in T.values() for c in rows}
    checks = defaultdict(set)
    for r in csv.DictReader((OUT / "checks" / "suspects.csv").open()):
        if r["cell_id"]:
            checks[r["cell_id"]].add(r["check"])
    for c in cells.values():          # unparseable tokens also get a second reading
        if c["status"] == "unread" and c.get("grid_row") not in (None, ""):
            checks[c["cell_id"]].add("unread")
    u = defaultdict(set)
    for cid in checks:
        c = cells.get(cid)
        if c is None or c.get("grid_row") in (None, "") or c["quantity"] in ("remarks", "note"):
            continue
        u[(c["pdf_index"], c["table"], c["grid_ti"])].add(c["grid_row"])
    f = defaultdict(set)
    for cid, c in cells.items():
        if c["table"] in full and c.get("grid_row") not in (None, "") and c["quantity"] not in ("remarks", "note"):
            checks[cid].add("full_read")
            k = (c["pdf_index"], c["table"], c["grid_ti"])
            if c["grid_row"] not in u.get(k, ()):
                f[k].add(c["grid_row"])
    return ({k: sorted(v) for k, v in u.items()}, {k: sorted(v) for k, v in f.items()}, checks, cells)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="build the images only")
    ap.add_argument("--max-calls", type=int, default=HALT_ABOVE)
    ap.add_argument("--full", nargs="*", default=list(FULL_TABLES), help="tables to re-read completely")
    a = ap.parse_args()
    U, F, checks, cells = units(tuple(a.full))
    jobs = []
    for group in (U, F):
        for (idx, table, ti), rows in sorted(group.items()):
            for s in range(0, len(rows), ROWS_PER_CALL):
                jobs.append((idx, table, ti, rows[s: s + ROWS_PER_CALL]))
    print(f"{sum(len(v) for v in U.values())} check rows + {sum(len(v) for v in F.values())} full-read rows "
          f"on {len({k[0] for k in U} | {k[0] for k in F})} pages -> {len(jobs)} calls")
    if len(jobs) > a.max_calls:
        raise SystemExit(f"{len(jobs)} calls > {a.max_calls}: halting before any call")
    SECOND.mkdir(parents=True, exist_ok=True)
    (SECOND / "images").mkdir(exist_ok=True)
    if not a.no_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set")
    budget = {"left": a.max_calls, "in": 0, "out": 0, "calls": 0}
    reads: dict[tuple, list[str]] = {}
    unclear: set = set()
    for idx, table, ti, rows in jobs:
        img, labels = build_image(idx, table, ti, rows)
        cv2.imwrite(str(SECOND / "images" / f"p{idx}_t{ti}_{rows[0]}.png"), img)
        if a.no_llm:
            continue
        prompt = PROMPT.format(labels=", ".join(labels), extra=EXTRA.get(table, ""))
        resp = call(img, prompt, budget)
        try:
            d = json.loads(resp["raw_response"])
        except ValueError:
            print(f"p{idx}: unparseable response")
            continue
        got = {r["label"]: r["cells"] for r in d["rows"]}
        for lab, k in zip(labels, rows):
            if lab in got:
                cells_ = got[lab]
                if not any(x.strip() for x in cells_):
                    continue            # the strip missed its line: no second reading
                if cells_ and cells_[0].strip() == lab:
                    cells_ = cells_[1:]  # the strip's own number copied as a first cell
                reads[(idx, ti, k)] = cells_
            if lab in d.get("unclear", []):
                unclear.add((idx, ti, k))
    if a.no_llm:
        print(f"images written to {SECOND / 'images'}")
        return
    cost = budget["in"] / 1e6 * PRICES[MODEL][0] + budget["out"] / 1e6 * PRICES[MODEL][1]
    prev = json.loads((SECOND / "spend.json").read_text()) if (SECOND / "spend.json").exists() else {}
    tot = {"calls": prev.get("calls", 0) + budget["calls"], "usd": round(prev.get("usd", 0) + cost, 4),
           "input_tokens": prev.get("input_tokens", 0) + budget["in"],
           "output_tokens": prev.get("output_tokens", 0) + budget["out"], "model": MODEL}
    (SECOND / "spend.json").write_text(json.dumps(tot, indent=1))
    print(f"new calls {budget['calls']} (${cost:.2f}); total {tot}")
    compare(checks, cells, reads, unclear)


def _cmp(t: str) -> str:
    import html
    t = html.unescape(t or "").replace("•", "*").replace("·", ".")
    t = norm(t).replace(" ", "").replace("−", "-")
    t = re.sub(r"^-{2,}$", "--", t)
    return t


def compare(checks: dict, cells: dict, reads: dict, unclear: set) -> None:
    out = []
    for cid, chk in checks.items():
        c = cells.get(cid)
        if c is None or c.get("grid_row") in (None, "") or c["quantity"] in ("remarks", "note"):
            continue
        key = (c["pdf_index"], c["grid_ti"], c["grid_row"])
        mrow = [txt(x) for x in page_tables(c["pdf_index"])[c["grid_ti"]][c["grid_row"]]]
        srow = reads.get(key)
        col = _col_of(c, mrow)
        s_tok, how = None, ""
        if srow is None:
            how = "no second reading"
        else:
            m_len = len(mrow) if c["table"] != "13.1" else 7
            s_cells = srow[:m_len] if c["table"] == "13.1" else srow
            if len(s_cells) < m_len and not any(x for x in mrow[len(s_cells):m_len]):
                # Mistral's grid has empty trailing columns (unused page columns) that Sonnet leaves out
                s_cells = list(s_cells) + [""] * (m_len - len(s_cells))
                how = "padded: Mistral's trailing columns are empty"
            if len(s_cells) == m_len:
                s_tok = s_cells[col]
            elif len([x for x in s_cells if x != ""]) == len([x for x in mrow[:m_len] if x]):
                # Sonnet dropped or added blanks: align the non-blank cells in order
                nb = [i for i, x in enumerate(mrow[:m_len]) if x]
                sb = [x for x in s_cells if x != ""]
                s_tok = sb[nb.index(col)] if col in nb else ""
                how = "aligned by non-blank cells"
            else:
                how = f"row lengths differ (Mistral {m_len}, Sonnet {len(s_cells)})"
        agree = s_tok is not None and _cmp(s_tok) == _cmp(c["token"])
        out.append({"cell_id": cid, "table": c["table"], "pdf_index": c["pdf_index"],
                    "grid_ti": c["grid_ti"], "grid_row": c["grid_row"], "grid_col": col,
                    "quantity": c["quantity"], "mistral_token": c["token"],
                    "sonnet_token": "" if s_tok is None else s_tok,
                    "agree": agree, "compared": s_tok is not None, "alignment": how,
                    "sonnet_unclear": key in unclear, "checks": ";".join(sorted(chk))})
    with (SECOND / "reads.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    n = len(out)
    print(f"{n} involved cells: compared {sum(o['compared'] for o in out)}, "
          f"agree {sum(o['agree'] for o in out)}, disagree {sum(o['compared'] and not o['agree'] for o in out)}, "
          f"not compared {sum(not o['compared'] for o in out)}")


def _col_of(c: dict, mrow: list[str]) -> int:
    """Column of the cell in Mistral's grid row."""
    if c.get("grid_col") not in (None, ""):
        return int(c["grid_col"])
    t = c["table"]
    if t == "12.1":
        q = c["quantity"]
        names = (["pressure", "height", "temperature", "relative_humidity"] if c.get("part") == "sounding"
                 else ["_label", "height", "wind_direction", "wind_speed"])
        return 4 * int(c["panel"]) + names.index(q)
    if t == "13.1":
        return ["pressure_altitude", "pressure", "temperature", "trace_code", "relative_humidity",
                "vapor_pressure", "dew_point"].index(c["quantity"])
    from .lists import MAIN
    _, _, keys, vals = MAIN[t]
    return len(keys) + [v[0] for v in vals].index(c["quantity"])


if __name__ == "__main__":
    main()

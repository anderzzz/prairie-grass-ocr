"""Reading of page- and column-level keys (run numbers).

A wrong run number mis-keys every cell under it, so keys are read by both
local readers and checked against ordering constraints. Disagreement is
reported, never silently resolved.
"""
from __future__ import annotations

import re

import numpy as np

from .readers import EasyOCRReader, TesseractReader
from .structure import text_bands

_RUN = re.compile(r"(\d{1,2})(?:-?S)?$")


def _norm_run(t: str) -> str | None:
    t = (t or "").replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(-?S)?", t)
    return None if not m else m.group(1) + ("S" if m.group(2) else "")


def read_tower_runs(img: np.ndarray, st) -> list[dict]:
    """Run number above each data column of a Table 5.3 page.

    Returns one dict per data column: column name, x-range, each reader's raw
    token, the agreed run (or None) and notes. The header cell is the band of
    ~1.1 row pitches directly above the first data row.
    """
    out = []
    if not st.panels or not st.panels[0].rows:
        return out
    p = st.panels[0]
    yc0 = p.rows[0].yc
    ry0, ry1 = max(0, int(yc0 - 2.6 * p.pitch)), int(yc0 - 0.3 * p.pitch)
    readers = [TesseractReader(whitelist="0123456789S-"), EasyOCRReader(allowlist="0123456789S-")]
    for name, (x0, x1) in p.cols.items():
        if not re.fullmatch(r"c\d+", name):
            continue
        # the run number is the lowest text band above the first data row
        bands = [b for b in text_bands(img, x0, x1, ry0, ry1) if b.h >= 12]
        if not bands:
            out.append({"col": name, "x": (x0, x1), "raw": {r.name: "" for r in readers},
                        "run": None, "note": ""})
            continue
        b = bands[-1]
        crop = img[b.y0 - 3: b.y1 + 3, x0:x1]
        raw = {r.name: r.read(crop)["text"] for r in readers}
        norm = {k: _norm_run(v) for k, v in raw.items()}
        vals = {v for v in norm.values() if v}
        run = vals.pop() if len(vals) == 1 and all(norm.values()) else None
        out.append({"col": name, "x": (x0, x1), "raw": raw, "run": run,
                    "note": "" if run else f"run header readers disagree or unreadable: {raw}"})
    # resolve disagreements by order: runs increase left to right, so a
    # candidate must lie strictly between the nearest agreed neighbours
    def order(r: str) -> float:
        return int(re.match(r"\d+", r).group()) - (0.5 if r.endswith("S") else 0)

    for i, c in enumerate(out):
        if c["run"] is not None:
            c["source"] = "both readers agree"
            continue
        if not any(c["raw"].values()):
            c["source"] = "blank header"
            c["note"] = "blank run header (unused column)"
            continue
        prev = next((order(out[j]["run"]) for j in range(i - 1, -1, -1) if out[j].get("source") == "both readers agree"), None)
        nxt = next((order(out[j]["run"]) for j in range(i + 1, len(out)) if out[j]["run"] is not None
                    and all(_norm_run(v) == out[j]["run"] for v in out[j]["raw"].values())), None)
        cands = {v for v in (_norm_run(x) for x in c["raw"].values()) if v}
        fit = [v for v in cands if (prev is None or order(v) > prev) and (nxt is None or order(v) < nxt)]
        if len(fit) == 1:
            c["run"], c["source"] = fit[0], "readers disagree; chosen by run order"
        else:
            c["source"] = "unresolved"
    return out

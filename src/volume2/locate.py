"""Where is a parsed row on the page? (Mistral returns no positions.)

Tesseract finds the printed text lines (word boxes grouped by height); each
Mistral grid row is matched to a line by the tokens they share, with rows kept
in order (dynamic programming). Rows that match nothing are placed by linear
interpolation between matched neighbours. Used only to cut images for the
second reader and the owner's review pack, never to produce a value.
"""
from __future__ import annotations

import json
import re

import numpy as np

from extract.tess import ocr_words

from .common import page_tables, txt
from .pages import OUT, image

CACHE = OUT / "locate"


def _norm(t: str) -> str:
    return re.sub(r"[^0-9A-Za-z.\-]", "", t).lstrip("-").lower()


def text_lines(img: np.ndarray) -> list[dict]:
    words = [w for w in ocr_words(img, psm=11) if w["text"].strip()]
    if not words:
        return []
    hmed = float(np.median([w["height"] for w in words]))
    words.sort(key=lambda w: w["top"] + w["height"] / 2)
    lines: list[dict] = []
    for w in words:
        yc = w["top"] + w["height"] / 2
        if lines and abs(yc - lines[-1]["yc"]) < 0.6 * hmed:
            ln = lines[-1]
            ln["words"].append(w)
            ln["yc"] = float(np.mean([x["top"] + x["height"] / 2 for x in ln["words"]]))
        else:
            lines.append({"yc": yc, "words": [w]})
    for ln in lines:
        ln["tokens"] = [_norm(w["text"]) for w in ln["words"] if _norm(w["text"])]
    return [{"yc": ln["yc"], "tokens": ln["tokens"], "x0": min(w["left"] for w in ln["words"]),
             "x1": max(w["left"] + w["width"] for w in ln["words"])} for ln in lines], hmed


def _score(row_tokens: list[str], line_tokens: list[str]) -> float:
    s, pool = 0.0, list(line_tokens)
    for t in row_tokens:
        if t in pool:
            s += 1 if len(t) >= 2 else 0.3
            pool.remove(t)
    return s


def locate_page(idx: int) -> dict:
    """{'rows': [[table index, row index, y_center, matched_score]], 'line_h': px}"""
    path = CACHE / f"p{idx}.json"
    if path.exists():
        return json.loads(path.read_text())
    img = image(idx)
    lines, hmed = text_lines(img)
    rows = []
    for ti, g in enumerate(page_tables(idx)):
        for k, r in enumerate(g):
            toks = [_norm(p) for c in r if c for p in txt(c).replace("/", " ").split() if _norm(p)]
            rows.append((ti, k, toks))
    R, L = len(rows), len(lines)
    sc = np.array([[_score(rows[i][2], lines[j]["tokens"]) for j in range(L)] for i in range(R)])
    # monotone alignment: best[i][j] = best score using rows[:i], lines[:j]
    best = np.zeros((R + 1, L + 1))
    for i in range(1, R + 1):
        for j in range(1, L + 1):
            best[i, j] = max(best[i - 1, j], best[i, j - 1], best[i - 1, j - 1] + sc[i - 1, j - 1])
    match = {}
    i, j = R, L
    while i > 0 and j > 0:
        if best[i, j] == best[i - 1, j]:
            i -= 1
        elif best[i, j] == best[i, j - 1]:
            j -= 1
        else:
            if sc[i - 1, j - 1] >= 1:
                match[i - 1] = j - 1
            i, j = i - 1, j - 1
    known = sorted(match)
    xr: dict[int, list] = {}
    for i, j in match.items():
        xr.setdefault(rows[i][0], []).append((lines[j]["x0"], lines[j]["x1"]))
    xext = {ti: [float(np.percentile([a for a, _ in v], 5)), float(np.percentile([b for _, b in v], 95))]
            for ti, v in xr.items()}
    out = []
    for i, (ti, k, toks) in enumerate(rows):
        if i in match:
            y, s = lines[match[i]]["yc"], float(sc[i, match[i]])
        else:
            lo = max([m for m in known if m < i], default=None)
            hi = min([m for m in known if m > i], default=None)
            if lo is not None and hi is not None:
                ylo, yhi = lines[match[lo]]["yc"], lines[match[hi]]["yc"]
                y = ylo + (yhi - ylo) * (i - lo) / (hi - lo)
            elif lo is not None:
                y = lines[match[lo]]["yc"] + (i - lo) * 1.6 * hmed
            elif hi is not None:
                y = lines[match[hi]]["yc"] - (hi - i) * 1.6 * hmed
            else:
                y = None
            s = 0.0
        out.append([ti, k, y, s])
    res = {"rows": out, "line_h": hmed, "matched": len(match), "total": R,
           "x_extent": {str(k): v for k, v in xext.items()}}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res))
    return res


def row_y(idx: int, ti: int, k: int) -> tuple[float | None, float, bool]:
    loc = locate_page(idx)
    for t, kk, y, s in loc["rows"]:
        if t == ti and kk == k:
            return y, loc["line_h"], s >= 1
    return None, loc["line_h"], False

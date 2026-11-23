"""Third owner review pack: what round 2 left open -> review/round3/index.html

    cd src && uv run python -m publish.review_round3      (make review-round3)

Items: the round-2 verdicts not applied (src/publish/round2.py): HOLD (the
round-2 image showed the wrong cell), ASK (a question to the owner), and the
undecided ones (can't tell, blank), read from config/review/round2_export.csv.

No box is drawn: the round-2 boxes came from counting ruling lines
(volume2.adjudicate.cell_images) and were sometimes a column or a row off, and
neither ink profiles nor Tesseract locate columns reliably in this print. Each
item instead shows the column heading and ~3 printed rows either side of the
cell, and names the row label and column heading to read. The row is marked
only when Tesseract reads that row's printed label exactly (label column only,
nearest the old estimate); the marked row is also shown enlarged.
Verdicts are exported as review/round3/verdicts.csv, the same format as round 2.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from extract.tess import ocr_words
from volume2.common import page_tables, txt
from volume2.locate import locate_page, row_y
from volume2.pages import image
from volume2.second_read import heading_row

from .review_pack import write_html
from .round2 import ASK, HOLD

REPO = Path(__file__).resolve().parents[2]
EXPORT2 = REPO / "config" / "review" / "round2_export.csv"
ITEMS2 = REPO / "review" / "round2" / "items.json"
X2 = REPO / "output" / "volume2" / "extracted"
V2 = REPO / "output" / "volume2" / "dataset"
PACK = REPO / "review" / "round3"
HEAD_13_1 = ["Zp (ft)", "P (mb)", "T (°C)", "#", "RH (%)", "e (mb)", "Td (°C)"]
COL_13_1 = {"pressure_altitude": 0, "pressure": 1, "temperature": 2, "trace_code": 3,
            "relative_humidity": 4, "vapor_pressure": 5, "dew_point": 6}


def norm(t: str) -> str:
    return re.sub(r"[^0-9a-z.]", "", t.lower().replace("*", ""))


def _words(img: np.ndarray, y0: int, y1: int, xa: int, xb: int, wl: str | None) -> list[dict]:
    y0 = max(0, y0)
    crop = cv2.copyMakeBorder(img[y0:y1, xa:xb], 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return [dict(w, yc=y0 - 20 + w["top"] + w["height"] / 2, x1=xa - 20 + w["left"] + w["width"])
            for w in ocr_words(crop, psm=11, whitelist=wl)]


def locate(g: dict) -> dict:
    """The row by its printed label; None if the label is not read exactly."""
    idx, ti, k = int(g["pdf_index"]), int(g["grid_ti"]), int(g["grid_row"])
    img = image(idx)
    loc = locate_page(idx)
    h = loc["line_h"]
    x0, x1 = (int(v) for v in loc["x_extent"].get(str(ti), [0, img.shape[1]]))
    G = page_tables(idx)[ti]
    lab = txt(G[k][0])
    col = int(g["grid_col"]) if g.get("grid_col", "") != "" else COL_13_1[g["quantity"]]
    hk = heading_row(g["table"], G, k)
    head = (txt(G[hk][col]) if g["table"] != "13.1" else HEAD_13_1[col]) if hk is not None else ""
    y_est, _, _ = row_y(idx, ti, k)
    num = bool(re.fullmatch(r"[-.\d]+", lab))
    xa, xl = max(0, x0 - 60), x0 + int(0.22 * (x1 - x0))          # the label column
    ws = _words(img, int(y_est - 6 * h), int(y_est + 6 * h), xa, xl, "0123456789.-" if num else None)
    if num:
        hits = [w for w in ws if w["text"] == lab or (re.sub(r"\D", "", w["text"]) == re.sub(r"\D", "", lab)
                and w["text"].startswith("-") == lab.startswith("-") and len(w["text"]) == len(lab))]
    else:
        hits = [w for w in ws if w["text"].lower()[:5] == lab.lower()[:5]]
    hit = min(hits, key=lambda w: abs(w["yc"] - y_est)) if hits else None
    return {"idx": idx, "ti": ti, "hk": hk, "h": h, "x": (x0, x1), "y_est": y_est,
            "y_row": hit["yc"] if hit else None, "label": lab, "head": head,
            "label_x1": hit["x1"] if hit else None}


def slope(img: np.ndarray, y0: int, y1: int, xa: int, xb: int) -> float:
    """Slope of the typed lines (dy/dx) in a table region: the shear under which the row
    profile (rules removed) is sharpest. This print is sometimes typed at a slant."""
    ink = (img[max(0, y0):y1, xa:xb] < 128).astype(np.float32)
    ink[:, ink.mean(0) > 0.3] = 0                               # vertical rules
    ink[ink.mean(1) > 0.3, :] = 0                               # horizontal rules
    n = 24
    edges = np.linspace(0, ink.shape[1], n + 1).astype(int)
    prof = [ink[:, a:b].sum(1) for a, b in zip(edges[:-1], edges[1:])]
    mid = (edges[:-1] + edges[1:]) / 2
    best, s_best = -1.0, 0.0
    for s in np.linspace(-0.05, 0.05, 101):
        acc = np.zeros(ink.shape[0] + 200)
        for p, m in zip(prof, mid):
            sh = int(round(100 - s * m))
            acc[sh: sh + len(p)] += p
        sc = float((acc ** 2).sum())
        if sc > best:
            best, s_best = sc, float(s)
    return s_best


def straighten(img: np.ndarray, s: float, x_ref: float) -> np.ndarray:
    """Shear so that a line typed with slope s runs level; rows keep their height at x_ref."""
    M = np.float32([[1, 0, 0], [s, 1, -s * x_ref]])
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderValue=255)


def images(g: dict, L: dict, name: str) -> tuple[str, str | None]:
    img = image(L["idx"])
    H, W = img.shape
    h, (x0, x1) = L["h"], L["x"]
    xa, xb = max(0, x0 - 60), min(W, x1 + 60)
    yc = L["y_row"] if L["y_row"] is not None else L["y_est"]
    L["slope"] = slope(img, int(yc - 8 * h), int(yc + 8 * h), xa, xb)
    img = straighten(img, L["slope"], x0)
    ya, yb = max(0, int(yc - 3.6 * h)), min(H, int(yc + 3.6 * h))
    parts = []
    if L["hk"] is not None:
        yh, _, _ = row_y(L["idx"], L["ti"], L["hk"])
        up = 2.8 if g["table"] in ("12.1", "13.1") else 2.0
        if yh is not None and yh + 1.2 * h < ya:                  # heading above the window: its own strip
            parts.append(cv2.cvtColor(img[max(0, int(yh - up * h)): int(yh + 1.0 * h), xa:xb], cv2.COLOR_GRAY2BGR))
            sep = np.full((14, xb - xa, 3), 255, np.uint8)
            sep[6:8] = 150
            parts.append(sep)
        elif yh is not None:
            ya = max(0, int(yh - up * h))
    ctx = cv2.cvtColor(img[ya:yb, xa:xb], cv2.COLOR_GRAY2BGR)
    ctx = cv2.copyMakeBorder(ctx, 0, 0, 46, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    zoom = None
    if L["y_row"] is not None:                                   # mark the row found by its label
        y = int(L["y_row"] - ya)
        cv2.fillPoly(ctx, [np.array([[6, y - 12], [6, y + 12], [36, y]])], (0, 0, 230))
        r0, r1 = max(0, int(L["y_row"] - 0.95 * h)), int(L["y_row"] + 0.95 * h)
        zoom = cv2.resize(img[r0:r1, xa:xb], None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
    full = np.vstack([np.hstack([np.full((p.shape[0], 46, 3), 255, np.uint8), p]) for p in parts] + [ctx])
    (PACK / "img").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(PACK / "img" / f"{name}.png"), full)
    if zoom is not None:
        cv2.imwrite(str(PACK / "img" / f"{name}_row.png"), zoom)
        return f"img/{name}.png", f"img/{name}_row.png"
    return f"img/{name}.png", None


def main() -> None:
    old = {i["cell_id"]: i for i in json.loads(ITEMS2.read_text())}
    grid = {r["cell_id"]: r for p in X2.glob("table_*.csv") for r in csv.DictReader(p.open())}
    data = {r["cell_id"]: r for p in V2.glob("table_*.csv") for r in csv.DictReader(p.open())}
    exp = list(csv.DictReader(EXPORT2.open()))
    items = []
    for v in exp:
        cid = v["cell_id"]
        if not (cid in HOLD or cid in ASK or v["verdict"].strip() in ("", "cant_tell")):
            continue
        it, g, d = dict(old[cid]), grid[cid], data[cid]
        L = locate(g)
        name = "r3_" + cid.replace("|", "_").replace("/", "-")
        it["img"], it["cell"] = images(g, L, name)
        it["token"] = d["token"]
        it["anchor"] = (f"Read the cell in the row labelled <b>{L['label']}</b>, under the column headed "
                        f"<b>{L['head']}</b>. "
                        + ("The red mark points at that row (found by its printed label); the strip below "
                           "is the same row enlarged." if L["y_row"] is not None else
                           "Row not marked (its label could not be read automatically); it is within the "
                           "rows shown."))
        drift = L["slope"] * (L["x"][1] - L["x"][0])
        if abs(drift) > 0.5 * L["h"]:
            it["anchor"] += (f" This page is typed at a slant (about {abs(drift) / L['h']:.1f} lines across the "
                             f"table); the image has been straightened so the rows run level.")
        it["locator"] = {"row_found": L["y_row"] is not None, "y_row": L["y_row"], "y_est": L["y_est"],
                         "slope": L["slope"], "drift_lines": round(drift / L["h"], 2)}
        why2 = {"": "left open in round 2", "cant_tell": "round 2: can't tell"}.get(v["verdict"].strip(), "")
        if cid in HOLD:
            why2 = f"round 2 image was wrong: {HOLD[cid]}; you typed {v['typed']!r}"
        if cid in ASK:
            it["group"] = "Q"
            why2 = f"round 2: you marked it misread, typed {v['typed']!r}. {ASK[cid]}"
        if v["note"]:
            why2 += f" (your note: {v['note']})"
        it["why"] = why2
        items.append(it)
    order = {"D": 0, "Q": 1, "O": 2}
    items.sort(key=lambda i: (order[i["group"]], i["file"], i["cell_id"]))
    PACK.mkdir(parents=True, exist_ok=True)
    (PACK / "items.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    write_html(items, pack=PACK, title="Round 3", key="pg-round3-verdicts")
    n = defaultdict(int)
    for it in items:
        n[it["group"]] += 1
    print(f"review pack: {PACK / 'index.html'}  {dict(n)}; row marked by label: "
          f"{sum(i['locator']['row_found'] for i in items)} of {len(items)}")


if __name__ == "__main__":
    main()

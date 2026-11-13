"""Table structure: columns from ruling lines, rows anchored on the printed keys.

* Columns: long vertical rules (broken rules are clustered; double rules are
  merged into one boundary with an x-extent so cell interiors exclude both
  strokes).
* Rows: text bands of the key column (800 m post numbers on Table 5.2 pages,
  heights on Table 5.3 pages). Ruling lines are unreliable on faded pages but
  the key is printed on every row. The key values are OCR'd and *vote* for
  the row-lattice offset, so a stray header fragment cannot shift every row
  by one; rows are then fitted as an evenly pitched lattice so that faint,
  unreadable keys still get a position. Rows whose position was inferred,
  and rows whose printed key disagrees with the geometry, are reported so
  their cells can be flagged as structural anomalies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from .preprocess import ink_mask, line_masks, long_vertical_rules
from .tess import ocr_words

# Table 5.2: per panel  [inner post | 800m post || 50 100 200 400 800]
ARC_PANEL_COLS = ["inner_post", "post800", "50", "100", "200", "400", "800"]
ARC_DISTANCES = ["50", "100", "200", "400", "800"]
# first 800 m post of each panel, by page half; inner post n sits on 800 m row 2n-1
ARC_HALVES = {"A": (1, 46), "B": (91, 136)}
ARC_ROWS = {("A", 0): 45, ("A", 1): 45, ("B", 0): 45, ("B", 1): 46}
# Table 5.3: rows are tower x height, top to bottom as printed
TOWER_HEIGHTS = ["17.5", "13.5", "10.5", "7.5", "4.5", "2.5", "1.5", "1.0", "0.5"]
N_TOWERS = 6


@dataclass
class Band:
    y0: int
    y1: int
    ink: int

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> int:
        return self.y1 - self.y0


@dataclass
class Row:
    index: int
    yc: float
    key_expected: str
    key_read: str | None      # OCR of the printed key (None if no band)
    inferred: bool            # no text band found; position from lattice


@dataclass
class Panel:
    cols: dict[str, tuple[int, int]]
    rows: list[Row]
    pitch: float
    edges: list[tuple[int, int]]
    meta: dict = field(default_factory=dict)


@dataclass
class PageStructure:
    table: str
    col_bounds: list[tuple[float, float]]   # (x_left, x_right) of each rule
    panels: list[Panel]
    anomalies: list[str] = field(default_factory=list)
    table_box: tuple[int, int, int, int] | None = None
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# columns

def vertical_boundaries(img: np.ndarray, min_frac: float = 0.35
                        ) -> tuple[list[tuple[float, float]], tuple[int, int]]:
    """(x_left, x_right) extents of long vertical rules, and the table's y-span."""
    ink = ink_mask(img)
    H, W = ink.shape
    segs = []
    for pts in long_vertical_rules(ink, min_h=150):
        x = float(pts[:, 1].mean())
        top, bot = int(pts[:, 0].min()), int(pts[:, 0].max())
        if x < 0.02 * W or x > 0.98 * W or top <= 2 or bot >= H - 3:
            continue  # page-edge artefacts
        segs.append((x, top, bot))
    if not segs:
        return [], (0, 0)
    segs.sort()
    clusters: list[list[tuple]] = []
    for s in segs:
        if clusters and s[0] - np.mean([c[0] for c in clusters[-1]]) <= 22:
            clusters[-1].append(s)
        else:
            clusters.append([s])
    totals = [sum(b - t for _, t, b in c) for c in clusters]
    tmax = max(totals)
    keep = [c for c, t in zip(clusters, totals) if t >= min_frac * tmax]
    y0 = int(np.median([min(t for _, t, _ in c) for c in keep]))
    y1 = int(max(max(b for _, _, b in c) for c in keep))
    ext = [(min(x for x, _, _ in c) - 3, max(x for x, _, _ in c) + 3) for c in keep]
    return ext, (y0, y1)


def fill_regular_gaps(xs: list[tuple[float, float]], first_regular: int
                      ) -> tuple[list[tuple[float, float]], list[str]]:
    """Insert boundaries where a gap among equal-width columns spans k>=2 pitches."""
    notes: list[str] = []
    reg = xs[first_regular:]
    if len(reg) < 3:
        return xs, notes
    centres = [(l + r) / 2 for l, r in reg]
    pitch = float(np.median(np.diff(centres)))
    out = list(xs[: first_regular + 1])
    for (a, b), eb in zip(zip(centres[:-1], centres[1:]), reg[1:]):
        k = int(round((b - a) / pitch))
        if k >= 2 and abs((b - a) / k - pitch) < 0.15 * pitch:
            for j in range(1, k):
                c = a + j * (b - a) / k
                out.append((c - 4, c + 4))
            notes.append(f"inferred {k - 1} column boundary(ies) between x={a:.0f} and x={b:.0f}")
        out.append(eb)
    return out, notes


def _interior(a: tuple[float, float], b: tuple[float, float], pad: int = 3) -> tuple[int, int]:
    return int(round(a[1] + pad)), int(round(b[0] - pad))


# --------------------------------------------------------------------------
# text bands

def glyph_ink(crop: np.ndarray) -> np.ndarray:
    """Ink mask of a column/cell crop with ruling lines (and their fringes) removed."""
    ink = ink_mask(crop)
    w = crop.shape[1]
    h, v = line_masks(ink, h_len=max(15, int(w * 0.5)), v_len=30)
    h = cv2.dilate(h, np.ones((5, 1), np.uint8))
    v = cv2.dilate(v, np.ones((1, 5), np.uint8))
    glyph = cv2.subtract(ink, cv2.bitwise_or(h, v))
    glyph[:, :2] = 0
    glyph[:, -2:] = 0
    return glyph


def clean_for_ocr(crop: np.ndarray, edge: int = 4) -> np.ndarray:
    """Gentle rule removal for reading: whiten only long horizontal ink runs
    (ruling lines) and a thin margin at the crop edges. Unlike `glyph_ink`,
    nothing is grown, so digits standing on an underline keep their strokes."""
    ink = ink_mask(crop)
    w = crop.shape[1]
    h, _ = line_masks(ink, h_len=max(30, int(w * 0.45)), v_len=10_000)
    ink = cv2.subtract(ink, h)
    ink[:, :edge] = 0
    ink[:, -edge:] = 0
    return np.where(ink > 0, 0, 255).astype(np.uint8)


def isolate_glyphs(crop: np.ndarray) -> tuple[np.ndarray, dict]:
    """Keep only character-like ink in a cell crop.

    After gentle rule removal, connected components are classified:
      * flat strokes (height <= 4 px and width >= 2.5 x height) are rule
        fragments or dashes and are dropped;
      * specks under 6 px are dropped;
      * everything else is kept, including small near-square blobs which are
        decimal points or the asterisk.
    Returns the cleaned crop (same size, 0 = ink) and stats: kept ink pixels,
    component count, and the bounding box of kept ink (or None).
    """
    clean = clean_for_ocr(crop)
    ink = np.where(clean < 128, 255, 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    keep = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < 6:
            continue
        if h <= 4 and w >= 2.5 * h:
            continue
        keep.append(i)
    tall = [i for i in keep if stats[i, cv2.CC_STAT_HEIGHT] >= 12]
    if tall:
        # small blobs (decimal points, asterisks) must sit on the text line
        # and within its horizontal span; other specks are scanner dust
        ty0 = min(stats[i, cv2.CC_STAT_TOP] for i in tall)
        ty1 = max(stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] for i in tall)
        tx0 = min(stats[i, cv2.CC_STAT_LEFT] for i in tall)
        tx1 = max(stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] for i in tall)
        small_ok = []
        for i in keep:
            if i in tall:
                continue
            x, y, w, h, a = stats[i]
            cy, cx = y + h / 2, x + w / 2
            if ty0 - 2 <= cy <= ty1 + 3 and tx0 - 10 <= cx <= tx1 + 10:
                small_ok.append(i)
        keep = tall + small_ok
    mask = np.isin(lab, keep)
    out = np.where(mask, 0, 255).astype(np.uint8)
    if keep:
        ys, xs = np.where(mask)
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    else:
        bbox = None
    return out, {"ink": int(mask.sum()), "components": len(keep), "tall_components": len(tall),
                 "bbox": bbox}


def text_bands(img: np.ndarray, x0: int, x1: int, y0: int, y1: int,
               min_ink: int = 12, merge_gap: int = 3, min_row_px: int = 1) -> list[Band]:
    glyph = glyph_ink(img[y0:y1, x0:x1])
    prof = (glyph > 0).sum(axis=1)
    on = prof >= min_row_px
    bands: list[Band] = []
    y, n = 0, len(prof)
    while y < n:
        if on[y]:
            s = y
            while y < n and on[y]:
                y += 1
            if bands and (s + y0) - bands[-1].y1 <= merge_gap:
                b = bands[-1]
                bands[-1] = Band(b.y0, y + y0, b.ink + int(prof[s:y].sum()))
            else:
                bands.append(Band(s + y0, y + y0, int(prof[s:y].sum())))
        y += 1
    return [b for b in bands if b.ink >= min_ink and b.h >= 6]


def _normal(bands: list[Band]) -> list[Band]:
    if not bands:
        return []
    med_h = float(np.median([b.h for b in bands]))
    return [b for b in bands if 0.35 * med_h <= b.h <= 1.8 * med_h]


def _pitch(bands: list[Band]) -> float:
    d = np.diff([b.yc for b in bands])
    if len(d) == 0:
        return float("nan")
    p = float(np.median(d))
    for _ in range(3):
        sel = d[(d > 0.7 * p) & (d < 1.35 * p)]
        if len(sel):
            p = float(np.median(sel))
    return p


def read_key(img: np.ndarray, band: Band, x0: int, x1: int) -> str:
    pad = 4
    crop, st = isolate_glyphs(img[max(0, band.y0 - pad): band.y1 + pad, x0:x1])
    if st["bbox"] is None:
        return ""
    bx0, by0, bx1, by1 = st["bbox"]
    crop = cv2.copyMakeBorder(crop[by0:by1, bx0:bx1], 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    words = ocr_words(crop, psm=7, whitelist="0123456789.", namespace="keycol")
    return "".join(w["text"] for w in words)


def row_edges(rows: list[Row], pitch: float) -> list[tuple[int, int]]:
    yc = [r.yc for r in rows]
    edges = []
    for i, c in enumerate(yc):
        top = (yc[i - 1] + c) / 2 if i > 0 and yc[i] - yc[i - 1] < 1.5 * pitch else c - pitch / 2
        bot = (c + yc[i + 1]) / 2 if i + 1 < len(yc) and yc[i + 1] - c < 1.5 * pitch else c + pitch / 2
        edges.append((int(round(top)), int(round(bot))))
    return edges


def _snap(bands: list[Band], lat: np.ndarray, tol: float) -> tuple[list[int | None], np.ndarray]:
    """Assign each lattice point the nearest unused band within tol."""
    yc = np.array([b.yc for b in bands]) if bands else np.zeros(0)
    assign: list[int | None] = [None] * len(lat)
    if len(yc) == 0:
        return assign, lat
    pairs = sorted((abs(yc[j] - lat[i]), i, j) for i in range(len(lat)) for j in range(len(yc))
                   if abs(yc[j] - lat[i]) <= tol)
    used_i, used_j = set(), set()
    for _, i, j in pairs:
        if i in used_i or j in used_j:
            continue
        assign[i] = j
        used_i.add(i)
        used_j.add(j)
    return assign, lat


# --------------------------------------------------------------------------
# Table 5.2

def _fit_arc_panel(img, bands, kx0, kx1, panel_idx):
    """Choose page half and row offset by key-value votes, then fit the lattice."""
    notes: list[str] = []
    cand = _normal(bands)
    pitch = _pitch(cand)
    if len(cand) < 5 or not np.isfinite(pitch):
        return None, [f"only {len(cand)} text bands in key column"]
    tol = 0.3 * pitch
    vals = []
    for b in cand:
        t = read_key(img, b, kx0, kx1)
        vals.append(int(t) if re.fullmatch(r"\d{1,3}", t) else None)
    best = None
    for half, starts in ARC_HALVES.items():
        start = starts[panel_idx]
        n = ARC_ROWS[(half, panel_idx)]
        implied = [b.yc - (v - start) * pitch for b, v in zip(cand, vals)
                   if v is not None and start <= v < start + n]
        if not implied:
            continue
        implied = np.array(implied)
        # densest cluster of implied y0
        support = [(np.abs(implied - y) <= tol).sum() for y in implied]
        i = int(np.argmax(support))
        y0 = float(np.median(implied[np.abs(implied - implied[i]) <= tol]))
        if best is None or support[i] > best[0]:
            best = (support[i], half, start, n, y0)
    if best is None:
        return None, ["no readable post numbers in key column; cannot anchor rows"]
    support, half, start, n, y0 = best
    if support < 5:
        notes.append(f"row alignment weakly supported ({support} key readings)")
    k = np.arange(n)
    lat = y0 + k * pitch
    for _ in range(2):
        assign, _ = _snap(cand, lat, tol)
        ks = [i for i, j in enumerate(assign) if j is not None]
        if len(ks) >= 3:
            A = np.column_stack([np.ones(len(ks)), k[ks]])
            (y0, pitch), *_ = np.linalg.lstsq(A, np.array([cand[assign[i]].yc for i in ks]), rcond=None)
            lat = y0 + k * pitch
    assign, _ = _snap(cand, lat, 0.3 * pitch)
    rows = []
    mism = 0
    for i in range(n):
        j = assign[i]
        expected = str(start + i)
        if j is None:
            rows.append(Row(i, float(lat[i]), expected, None, True))
        else:
            read = "" if vals[j] is None else str(vals[j])
            rows.append(Row(i, cand[j].yc, expected, read, False))
            if read and read != expected:
                mism += 1
    inferred = sum(r.inferred for r in rows)
    if inferred:
        notes.append(f"{inferred} of {n} rows had no text band in the key column; positions inferred")
    if mism:
        notes.append(f"{mism} printed post numbers read differently from the expected sequence")
    return {"rows": rows, "pitch": float(pitch), "half": half, "support": int(support)}, notes


def analyse_arc_page(img: np.ndarray) -> PageStructure:
    """Table 5.2 page: two panels, each [inner post | 800m post || 50 100 200 400 800]."""
    xs, (ty0, ty1) = vertical_boundaries(img)
    anomalies: list[str] = []
    if len(xs) != 15:
        anomalies.append(f"found {len(xs)} vertical boundaries, expected 15")
    panels: list[Panel] = []
    halves = []
    for p in range(2):
        b = xs[7 * p: 7 * p + 8]
        if len(b) < 8:
            anomalies.append(f"panel {p}: incomplete column boundaries")
            continue
        cols = {name: _interior(b[i], b[i + 1]) for i, name in enumerate(ARC_PANEL_COLS)}
        kx0, kx1 = cols["post800"]
        bands = text_bands(img, kx0, kx1, max(0, ty0 - 50), min(img.shape[0], ty1 + 80))
        fit, notes = _fit_arc_panel(img, bands, kx0, kx1, p)
        anomalies += [f"panel {p}: {n}" for n in notes]
        if fit is None:
            panels.append(Panel(cols, [], float("nan"), [], {"panel": p}))
            continue
        halves.append(fit["half"])
        panels.append(Panel(cols, fit["rows"], fit["pitch"], row_edges(fit["rows"], fit["pitch"]),
                            {"panel": p, "half": fit["half"], "support": fit["support"]}))
    half = halves[0] if halves and all(h == halves[0] for h in halves) else None
    if halves and half is None:
        anomalies.append(f"panels disagree on page half: {halves}")
    box = (int(xs[0][0]), ty0, int(xs[-1][1]), ty1) if xs else None
    return PageStructure("5.2", xs, panels, anomalies, box, {"half": half})


# --------------------------------------------------------------------------
# Table 5.3

def _norm_height(t: str) -> str | None:
    m = re.fullmatch(r"(\d{1,2})\.?(\d)", t)
    if not m:
        return None
    return f"{int(m.group(1))}.{m.group(2)}"


def analyse_tower_page(img: np.ndarray) -> PageStructure:
    """Table 5.3 page: [tower | height | run columns], 6 towers x 9 heights.

    The spacer between tower groups is not uniform, so each group of nine
    rows is fitted separately, anchored on its printed 17.5 m label.
    """
    xs, (ty0, ty1) = vertical_boundaries(img)
    xs, notes = fill_regular_gaps(xs, first_regular=2)
    anomalies = list(notes)
    if len(xs) < 4:
        anomalies.append(f"found only {len(xs)} vertical boundaries")
        return PageStructure("5.3", xs, [], anomalies)
    cols = {"tower": _interior(xs[0], xs[1]), "height": _interior(xs[1], xs[2])}
    for j in range(2, len(xs) - 1):
        cols[f"c{j - 1}"] = _interior(xs[j], xs[j + 1])
    kx0, kx1 = cols["height"]
    bands = _normal(text_bands(img, kx0, kx1, max(0, ty0 - 20), min(img.shape[0], ty1 + 40)))
    vals = [_norm_height(read_key(img, b, kx0, kx1)) for b in bands]
    d = np.diff([b.yc for b in bands])
    pitch = _pitch(bands)
    tol = 0.3 * pitch
    rows: list[Row] = []
    n_h = len(TOWER_HEIGHTS)
    starts, gnotes = _tower_group_starts(bands, vals, pitch, tol)
    anomalies += gnotes
    if not starts:
        return PageStructure("5.3", xs, [], anomalies, (int(xs[0][0]), ty0, int(xs[-1][1]), ty1))
    for g, group_y in enumerate(starts):
        lat = group_y + np.arange(n_h) * pitch
        assign, _ = _snap(bands, lat, tol)
        ks = [i for i, j in enumerate(assign) if j is not None]
        if len(ks) >= 3:
            A = np.column_stack([np.ones(len(ks)), np.array(ks, float)])
            (y0g, pg), *_ = np.linalg.lstsq(A, np.array([bands[assign[i]].yc for i in ks]), rcond=None)
            if 0.85 * pitch < pg < 1.15 * pitch:
                lat = y0g + np.arange(n_h) * pg
            assign, _ = _snap(bands, lat, tol)
        for i in range(n_h):
            j = assign[i]
            exp = TOWER_HEIGHTS[i]
            idx = g * n_h + i
            if j is None:
                rows.append(Row(idx, float(lat[i]), exp, None, True))
            else:
                rows.append(Row(idx, bands[j].yc, exp, vals[j] or "", False))
    inferred = sum(r.inferred for r in rows)
    mism = sum(1 for r in rows if r.key_read and r.key_read != r.key_expected)
    if inferred:
        anomalies.append(f"{inferred} of {len(rows)} rows had no text band in the height column; positions inferred")
    if mism:
        anomalies.append(f"{mism} printed heights read differently from the expected sequence")
    panel = Panel(cols, rows, pitch, row_edges(rows, pitch), {"panel": 0})
    return PageStructure("5.3", xs, [panel], anomalies, (int(xs[0][0]), ty0, int(xs[-1][1]), ty1))


def _tower_group_starts(bands: list[Band], vals: list[str | None], pitch: float, tol: float
                        ) -> tuple[list[float], list[str]]:
    """y of the 17.5 m row of each of the six tower groups.

    Every band whose height label was read votes for its group's start
    (y - index * pitch). The best-supported starts at least 9.5 pitches apart
    are taken, top to bottom; groups without support are inferred from the
    typical group spacing and the extent of the bands, and reported.
    (Anchoring on the first '17.5' read instead silently shifts every tower
    by one group when the top label is unreadable - seen on PDF page 208.)
    """
    notes: list[str] = []
    n_h = len(TOWER_HEIGHTS)
    implied = np.array([b.yc - TOWER_HEIGHTS.index(v) * pitch
                        for b, v in zip(bands, vals) if v in TOWER_HEIGHTS])
    if len(implied) == 0:
        return [], ["no tower height labels readable; rows not anchored"]
    clusters: list[list[float]] = []
    for y in sorted(implied):
        if clusters and y - clusters[-1][-1] <= tol:
            clusters[-1].append(y)
        else:
            clusters.append([y])
    clusters.sort(key=len, reverse=True)
    chosen: list[tuple[float, int]] = []
    for c in clusters:
        y = float(np.median(c))
        if len(c) >= 2 and all(abs(y - z) >= 9.5 * pitch for z, _ in chosen):
            chosen.append((y, len(c)))
        if len(chosen) == N_TOWERS:
            break
    if not chosen:
        return [], ["tower height labels too sparse to anchor rows"]
    chosen.sort()
    starts = [y for y, _ in chosen]
    nominal = 10.9 * pitch
    if len(starts) >= 2:
        steps = [g / max(1, round(g / nominal)) for g in np.diff(starts)]
        step = float(np.median(steps))
    else:
        step = nominal
    filled = [starts[0]]
    for y in starts[1:]:
        k = int(round((y - filled[-1]) / step))
        for _ in range(1, k):
            filled.append(filled[-1] + step)
            notes.append(f"tower group start inferred at y={filled[-1]:.0f} (between labelled groups)")
        filled.append(y)
    top_band = min(b.yc for b in bands)
    while len(filled) < N_TOWERS and filled[0] - step >= top_band - tol:
        filled.insert(0, filled[0] - step)
        notes.append(f"tower group start inferred at y={filled[0]:.0f} (above first labelled group)")
    bot_band = max(b.yc for b in bands)
    while len(filled) < N_TOWERS and filled[-1] + step <= bot_band:
        filled.append(filled[-1] + step)
        notes.append(f"tower group start inferred at y={filled[-1]:.0f} (below last labelled group)")
    if len(filled) != N_TOWERS:
        notes.append(f"found {len(filled)} tower groups, expected {N_TOWERS}")
    support = {round(y): n for y, n in chosen}
    weak = [i + 1 for i, y in enumerate(filled) if support.get(round(y), 0) < 3]
    if weak:
        notes.append(f"tower group(s) {weak} anchored on fewer than 3 readable height labels")
    return filled[:N_TOWERS], notes

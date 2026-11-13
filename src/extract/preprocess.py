"""Image preprocessing for 1-bit scans.

The scan is already bilevel (CCITT G4), so "contrast" enhancement in the
grey-level sense has nothing to work on. The operations that can matter are:

* deskew   - rotate so ruling lines are axis-aligned (estimated from long
             horizontal line segments);
* despeckle - drop isolated tiny ink components (scanner dust);
* repair   - morphological closing to reconnect broken strokes on faded pages.

Each step is optional and controlled by a PreprocessConfig so that the
pipeline can be run with and without it and the effect measured, instead of
assumed (see `extract.experiments`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class PreprocessConfig:
    deskew: bool = True
    despeckle: bool = True
    repair: bool = False
    speck_max_area: int = 4
    repair_kernel: int = 2

    def as_dict(self) -> dict:
        return asdict(self)


RAW = PreprocessConfig(deskew=False, despeckle=False, repair=False)


def ink_mask(img: np.ndarray) -> np.ndarray:
    """uint8 mask, 255 where ink."""
    return np.where(img < 128, 255, 0).astype(np.uint8)


def line_masks(ink: np.ndarray, h_len: int = 80, v_len: int = 60) -> tuple[np.ndarray, np.ndarray]:
    """Masks of long horizontal and vertical strokes (ruling lines)."""
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    h = cv2.morphologyEx(ink, cv2.MORPH_OPEN, hk)
    v = cv2.morphologyEx(ink, cv2.MORPH_OPEN, vk)
    return h, v


def long_vertical_rules(ink: np.ndarray, min_h: int = 300) -> list[np.ndarray]:
    """Pixel coordinate arrays (y, x) of long, thin vertical rule components."""
    _, v = line_masks(ink, v_len=40)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(v, connectivity=8)
    out = []
    for i in range(1, n):
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if h >= min_h and h / max(w, 1) >= 25:
            out.append(i)
    return [np.column_stack(np.where(lab == i)) for i in out]


def estimate_skew_deg(img: np.ndarray) -> float:
    """Skew angle in degrees.

    Table pages: from the slope of long vertical rules (the horizontal rules
    on Table 5.2 pages are short per-cell segments). Text pages: fall back to
    long horizontal segments.
    """
    ink = ink_mask(img)
    rules = long_vertical_rules(ink)
    if len(rules) >= 4:
        slopes, weights = [], []
        for pts in rules:
            ys, xs = pts[:, 0].astype(float), pts[:, 1].astype(float)
            a = np.polyfit(ys, xs, 1)[0]   # dx/dy
            slopes.append(a)
            weights.append(len(pts))
        order = np.argsort(slopes)
        s, w = np.array(slopes)[order], np.array(weights)[order]
        cw = np.cumsum(w)
        a = s[np.searchsorted(cw, cw[-1] / 2)]
        # rotating by +deg (counter-clockwise) moves a rule leaning right
        # (dx/dy > 0) back to vertical
        return float(-np.degrees(np.arctan(a)))
    h, _ = line_masks(ink, h_len=120)
    lines = cv2.HoughLinesP(h, 1, np.pi / 3600, threshold=200,
                            minLineLength=400, maxLineGap=20)
    if lines is None:
        return 0.0
    angles, weights = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        length = np.hypot(x2 - x1, y2 - y1)
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(ang) < 3:
            angles.append(ang)
            weights.append(length)
    if not angles:
        return 0.0
    order = np.argsort(angles)
    a, w = np.array(angles)[order], np.array(weights)[order]
    cw = np.cumsum(w)
    return float(a[np.searchsorted(cw, cw[-1] / 2)])  # weighted median


def rotate(img: np.ndarray, deg: float) -> np.ndarray:
    hgt, wid = img.shape
    m = cv2.getRotationMatrix2D((wid / 2, hgt / 2), deg, 1.0)
    return cv2.warpAffine(img, m, (wid, hgt), flags=cv2.INTER_NEAREST,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def despeckle(img: np.ndarray, max_area: int) -> np.ndarray:
    ink = ink_mask(img)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    small = np.where(stats[:, cv2.CC_STAT_AREA] <= max_area)[0]
    small = small[small != 0]
    out = img.copy()
    out[np.isin(lab, small)] = 255
    return out


def repair(img: np.ndarray, k: int) -> np.ndarray:
    ink = ink_mask(img)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k + 1, k + 1))
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, ker)
    return np.where(ink > 0, 0, 255).astype(np.uint8)


def preprocess(img: np.ndarray, cfg: PreprocessConfig) -> tuple[np.ndarray, dict]:
    info: dict = {"config": cfg.as_dict()}
    out = img
    if cfg.deskew:
        ang = estimate_skew_deg(out)
        info["skew_deg"] = round(ang, 4)
        if abs(ang) > 0.02:
            out = rotate(out, ang)
    if cfg.despeckle:
        out = despeckle(out, cfg.speck_max_area)
    if cfg.repair:
        out = repair(out, cfg.repair_kernel)
    return out, info


def glyph_metrics(img: np.ndarray, region: tuple[int, int, int, int] | None = None) -> dict:
    """Objective legibility measures of the character ink in a region (x0,y0,x1,y1).

    Ruling lines are removed (long horizontal and vertical runs), then ink
    components are split into
      * characters: height 15-45 px and width <= 45 px (a digit at 300 dpi
        is ~25-30 px tall);
      * pieces: everything else of area >= 6 px that is not a flat rule
        fragment.
    stroke_px   - mean stroke width of character components
                  (2 x mean distance-transform value on their medial ridge);
                  faded print has thinner strokes.
    intact_frac - characters / (characters + pieces); faded print breaks
                  glyphs into pieces.
    legibility  - stroke_px x intact_frac (higher is more legible).
    """
    if region is not None:
        x0, y0, x1, y1 = region
        img = img[y0:y1, x0:x1]
    ink = ink_mask(img)
    h, v = line_masks(ink, h_len=60, v_len=60)
    ink = cv2.subtract(ink, cv2.bitwise_or(h, v))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    chars, pieces = [], 0
    for i in range(1, n):
        x, y, w, hh, a = stats[i]
        if a < 6 or (hh <= 4 and w >= 2.5 * hh):
            continue
        if 15 <= hh <= 45 and w <= 45:
            chars.append(i)
        else:
            pieces += 1
    if len(chars) < 20:
        return {"stroke_px": float("nan"), "intact_frac": float("nan"),
                "legibility": float("nan"), "char_components": len(chars)}
    mask = np.isin(lab, chars).astype(np.uint8) * 255
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    dil = cv2.dilate(dist, np.ones((3, 3), np.uint8))
    ridge = (dist > 0) & (dist >= dil - 1e-6)
    stroke = 2.0 * float(dist[ridge].mean())
    intact = len(chars) / (len(chars) + pieces)
    return {"stroke_px": round(stroke, 3), "intact_frac": round(intact, 4),
            "legibility": round(stroke * intact, 4), "char_components": len(chars)}

"""Debug overlay: draw detected structure (and optionally cell boxes) on a page."""
from __future__ import annotations

import cv2
import numpy as np


def draw(img: np.ndarray, st, cells=None) -> np.ndarray:
    out = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for xl, xr in st.col_bounds:
        cv2.line(out, (int(xl), 0), (int(xl), out.shape[0]), (255, 0, 0), 1)
        cv2.line(out, (int(xr), 0), (int(xr), out.shape[0]), (255, 0, 0), 1)
    for p in st.panels:
        x0 = min(a for a, _ in p.cols.values())
        x1 = max(b for _, b in p.cols.values())
        for (t, b) in p.edges:
            cv2.line(out, (x0, t), (x1, t), (0, 160, 0), 1)
        for r in p.rows:
            colr = (0, 140, 255) if r.inferred else ((0, 0, 255) if r.key_read == r.key_expected else (255, 0, 255))
            cv2.circle(out, (x0 - 10, int(r.yc)), 5, colr, -1)
            cv2.putText(out, r.key_expected, (max(0, x0 - 75), int(r.yc) + 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, colr, 2)
    if cells:
        for c in cells:
            x0, y0, x1, y1 = c["box"]
            cv2.rectangle(out, (x0, y0), (x1, y1), (0, 0, 255), 1)
    return out

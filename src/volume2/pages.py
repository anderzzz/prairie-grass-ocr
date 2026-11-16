"""Volume II page inventory and page images (same preprocessing as Volume I)."""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np
import yaml

from extract.pdfio import REPO, page_image
from extract.preprocess import PreprocessConfig, preprocess

PDF = REPO / "rawdata" / "PGrassVolumeII.pdf"
CONFIG = REPO / "config" / "volume2_pages.yaml"
OUT = REPO / "output" / "volume2"


@lru_cache(maxsize=1)
def inventory() -> dict:
    return yaml.safe_load(CONFIG.read_text())["tables"]


def pages_of(table: str) -> list[int]:
    p = inventory()[table]["pages"]
    return list(range(p[0], p[-1] + 1))


def all_pages() -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for t in inventory():
        for i in pages_of(t):
            out.setdefault(i, []).append(t)
    return dict(sorted(out.items()))


def image(idx: int) -> np.ndarray:
    """Deskewed, despeckled page, rotated upright where the inventory says so."""
    img, _ = preprocess(page_image(idx, PDF), PreprocessConfig())
    rot = {inventory()[t].get("rotate", 0) for t in all_pages()[idx]} - {0}
    if rot == {90}:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif rot:
        raise ValueError(f"page {idx}: unsupported rotation {rot}")
    return img

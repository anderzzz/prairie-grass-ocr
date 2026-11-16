"""Page inventory, page images and cached Mistral responses for the Volume I
supplementary tables. Preprocessing as in Volumes I and II."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import yaml

from extract.mistral import ocr_page
from extract.pdfio import PDF_PATH, REPO, page_image
from extract.preprocess import PreprocessConfig, preprocess
from volume2.htmlgrid import grid

CONFIG = REPO / "config" / "volume1s_pages.yaml"
OUT = REPO / "output" / "volume1s"


@lru_cache(maxsize=1)
def inventory() -> dict:
    return yaml.safe_load(CONFIG.read_text())["tables"]


def pages_of(table: str) -> list[int]:
    p = inventory()[table]["pages"]
    return list(range(p[0], p[-1] + 1))


def printed(idx: int) -> int:
    return idx - 13


@lru_cache(maxsize=None)
def image(idx: int) -> np.ndarray:
    img, _ = preprocess(page_image(idx, PDF_PATH), PreprocessConfig())
    return img


@lru_cache(maxsize=None)
def response(idx: int) -> dict:
    return ocr_page(image(idx))


def page_tables(idx: int) -> list[list[list]]:
    """Tables on the page as grids of (text, min word confidence)."""
    out = []
    for p in response(idx).get("pages") or []:
        for t in p.get("tables") or []:
            out.append(grid(t["content"], t.get("word_confidence_scores"), with_conf=True))
    return out


def page_markdown(idx: int) -> str:
    md = "\n\n".join(p.get("markdown") or "" for p in response(idx).get("pages") or [])
    for p in response(idx).get("pages") or []:
        for t in p.get("tables") or []:
            md = md.replace(f"[{t['id']}]({t['id']})", t["content"])
    return md

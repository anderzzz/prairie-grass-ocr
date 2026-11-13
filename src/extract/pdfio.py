"""Access to the scanned PDF.

Every page of PGrassVolumeI.pdf is a single 1-bit CCITT G4 image placed at
300 dpi with no rotation (verified for all 300 pages in recon). We therefore
decode the embedded image directly instead of rendering the page: that gives
the scanner's native pixels with no resampling. Rendering at a higher dpi adds
no information to a bilevel scan; rendering lower throws strokes away.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import fitz
import numpy as np

REPO = Path(__file__).resolve().parents[2]
PDF_PATH = REPO / "rawdata" / "PGrassVolumeI.pdf"
NATIVE_DPI = 300


@lru_cache(maxsize=1)
def _doc(path: str = str(PDF_PATH)) -> fitz.Document:
    return fitz.open(path)


def page_count() -> int:
    return _doc().page_count


def page_image(pdf_index: int) -> np.ndarray:
    """Return the page as a uint8 array, 0 = ink, 255 = paper, native resolution."""
    doc = _doc()
    page = doc[pdf_index]
    infos = page.get_image_info(xrefs=True)
    if len(infos) != 1:
        raise ValueError(f"page {pdf_index}: expected 1 image, found {len(infos)}")
    pix = fitz.Pixmap(doc, infos[0]["xref"])
    if pix.n != 1:
        pix = fitz.Pixmap(fitz.csGRAY, pix)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return arr.copy()

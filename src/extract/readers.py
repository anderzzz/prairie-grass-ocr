"""Independent cell readers.

Each reader takes a cell crop (uint8, 0 = ink) and returns
    {"text": raw string as read, "conf": float in [0, 1] or None, ...}
Raw responses are cached on disk keyed by crop pixels and reader settings.

* tesseract  - Tesseract 5 LSTM, local and offline.
* easyocr    - EasyOCR CRNN recogniser (PyTorch), local and offline after a
               one-time model download.
* claude     - optional vision-LLM reader; used only when ANTHROPIC_API_KEY is
               set, skipped cleanly otherwise.

The two local readers are independent implementations (different networks,
training data and decoding). They share the crop and the gentle line removal
in `prepare`, which is the price of reading the same cell.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from .cache import cached
from .structure import isolate_glyphs
from .tess import ocr_words, tesseract_version

ALLOW = "0123456789.M*"


def prepare(crop: np.ndarray, scale: float = 1.0, border: int = 12) -> np.ndarray:
    """Isolated glyphs, cropped tightly with a white border, optionally scaled."""
    img, st = isolate_glyphs(crop)
    if st["bbox"] is not None:
        x0, y0, x1, y1 = st["bbox"]
        img = img[y0:y1, x0:x1]
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        img = np.where(img < 128, 0, 255).astype(np.uint8)
    return cv2.copyMakeBorder(img, border, border, border, border, cv2.BORDER_CONSTANT, value=255)


@dataclass(frozen=True)
class TesseractReader:
    name: str = "tesseract"
    psm: int = 7
    scale: float = 1.0
    whitelist: str = ALLOW

    def read(self, crop: np.ndarray) -> dict:
        img = prepare(crop, self.scale)
        words = ocr_words(img, psm=self.psm, whitelist=self.whitelist, namespace="reader_tesseract")
        if not words:
            return {"text": "", "conf": None}
        text = "".join(w["text"] for w in words)
        confs = [w["conf"] for w in words if w["conf"] >= 0]
        return {"text": text, "conf": round(min(confs) / 100.0, 4) if confs else None,
                "n_words": len(words)}

    def describe(self) -> dict:
        return {"engine": tesseract_version(), "psm": self.psm, "scale": self.scale,
                "whitelist": self.whitelist}


@lru_cache(maxsize=1)
def _easyocr():
    import easyocr  # heavy import, deferred
    return easyocr.Reader(["en"], gpu=False, verbose=False)


@dataclass(frozen=True)
class EasyOCRReader:
    name: str = "easyocr"
    scale: float = 1.0
    allowlist: str = ALLOW

    def read(self, crop: np.ndarray) -> dict:
        img = prepare(crop, self.scale)
        params = {"scale": self.scale, "allow": self.allowlist, "v": "1.7.2-g2"}

        def run():
            h, w = img.shape
            res = _easyocr().recognize(img, horizontal_list=[[0, w, 0, h]], free_list=[],
                                       allowlist=self.allowlist, detail=1, decoder="greedy")
            if not res:
                return {"text": "", "conf": None}
            _, text, conf = res[0]
            return {"text": text.replace(" ", ""), "conf": round(float(conf), 4)}

        return cached("reader_easyocr", params, img, run)

    def describe(self) -> dict:
        return {"engine": "easyocr 1.7.2 english_g2", "scale": self.scale, "allowlist": self.allowlist}


def default_readers() -> list:
    """Offline readers always; the vision-LLM reader only when explicitly
    enabled with PGOCR_LLM=<model id> (and an API key) - never implicitly."""
    rs: list = [TesseractReader(), EasyOCRReader()]
    model = os.environ.get("PGOCR_LLM")
    if model:
        from .llm import LLMReader
        if LLMReader.available():
            rs.append(LLMReader(model=model))
    return rs

"""Content-addressed on-disk cache for slow or non-deterministic steps.

Keys are SHA-256 of (namespace, parameters, image bytes). Values are JSON.
Reader caches for pilot pages are committed so a fresh clone reproduces the
exact reader outputs even if a local OCR engine version differs; delete
`cache/` (or run `make clean-cache`) to recompute from scratch.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .pdfio import REPO

CACHE_DIR = Path(os.environ.get("PGOCR_CACHE", REPO / "cache"))


def key_for(namespace: str, params: dict, img: np.ndarray | None = None) -> str:
    h = hashlib.sha256()
    h.update(namespace.encode())
    h.update(json.dumps(params, sort_keys=True).encode())
    if img is not None:
        h.update(str(img.shape).encode())
        h.update(np.ascontiguousarray(img).tobytes())
    return h.hexdigest()


def cached(namespace: str, params: dict, img: np.ndarray | None, fn: Callable[[], Any]) -> Any:
    k = key_for(namespace, params, img)
    path = CACHE_DIR / namespace / k[:2] / f"{k}.json"
    if path.exists():
        return json.loads(path.read_text())
    value = fn()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(value))
    tmp.replace(path)
    return value

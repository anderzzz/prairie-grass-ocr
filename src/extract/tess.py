"""Thin, cached wrapper around the tesseract CLI (local, offline)."""
from __future__ import annotations

import csv
import io
import subprocess
from functools import lru_cache

import cv2
import numpy as np

from .cache import cached


@lru_cache(maxsize=1)
def tesseract_version() -> str:
    out = subprocess.run(["tesseract", "--version"], capture_output=True, text=True)
    return (out.stdout or out.stderr).splitlines()[0].strip()


def ocr_words(img: np.ndarray, psm: int = 6, whitelist: str | None = None,
              namespace: str = "tesseract") -> list[dict]:
    """Run tesseract on a uint8 image; return word dicts with text, conf, bbox."""
    params = {"psm": psm, "whitelist": whitelist, "version": tesseract_version()}

    def run() -> list[dict]:
        ok, png = cv2.imencode(".png", img)
        assert ok
        cmd = ["tesseract", "stdin", "stdout", "--psm", str(psm), "-l", "eng",
               "--dpi", "300"]
        if whitelist is not None:
            cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
        cmd += ["tsv"]
        res = subprocess.run(cmd, input=png.tobytes(), capture_output=True, check=True)
        words = []
        reader = csv.DictReader(io.StringIO(res.stdout.decode("utf-8", "replace")),
                                delimiter="\t", quoting=csv.QUOTE_NONE)
        for r in reader:
            txt = (r.get("text") or "").strip()
            if r.get("level") != "5" or not txt:
                continue
            words.append({
                "text": txt,
                "conf": float(r["conf"]),
                "left": int(r["left"]), "top": int(r["top"]),
                "width": int(r["width"]), "height": int(r["height"]),
                "line": (int(r["block_num"]), int(r["par_num"]), int(r["line_num"])),
            })
        return words

    return cached(namespace, params, img, run)

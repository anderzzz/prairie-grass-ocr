"""Precipitation row of Tables 8.1/8.2 (printed below the table frame).

Mistral's page read drops this line on most pages. The line is located with
Tesseract (the word "Precipitation"; fallback: just under the lowest long
horizontal rule), cropped across the full width, and sent to Mistral on its
own (cached, ~$0.004 per page). Tokens are assigned to the page's columns
only when their count equals the number of columns; otherwise the cells stay
"unread". Nothing is inferred from neighbouring pages.
"""
from __future__ import annotations

import re

import numpy as np

from .common import cached_response
from extract.preprocess import ink_mask, line_masks
from extract.tess import ocr_words

from .pages import image

LABEL = re.compile(r"^pr\w{0,3}[ci]\w*", re.I)


def strip(idx: int) -> tuple[np.ndarray, str]:
    img = image(idx)
    h, w = img.shape
    y0 = int(h * 0.62)
    ws = [x for x in ocr_words(img[y0:int(h * 0.95)], psm=11)
          if LABEL.match(x["text"]) and len(x["text"]) >= 9]
    if ws:
        x = ws[0]
        top = x["top"] + y0
        return img[top - 20: top + x["height"] + 20], "located by Tesseract label"
    ys = np.where((line_masks(ink_mask(img))[0] > 0).sum(1) > 300)[0]
    bottom = int(ys.max())
    return img[bottom + 5: bottom + 110], "located under the table's bottom rule"


def read(idx: int, ncols: int) -> tuple[list[str] | None, str]:
    howbox = {}

    def make():
        s, howbox["how"] = strip(idx)
        return s
    resp = cached_response(f"precip {idx}", make)
    how = howbox.get("how", "strip located earlier (see index)")
    md = " ".join(p.get("markdown") or "" for p in resp.get("pages") or [])
    for p in resp.get("pages") or []:
        for t in p.get("tables") or []:
            md = md.replace(f"[{t['id']}]({t['id']})", t["content"])
    md = re.sub(r"<[^>]+>", " ", md)
    if not re.search(r"precip", md, re.I):
        return None, f"{how}; the strip does not contain the 'Precipitation' label"
    m = re.search(r"\(\s*c\s*m\s*\)(.*)", md, re.S)
    tail = re.split(r"[*•]|[A-Za-z]", (m.group(1) if m else md))[0]   # footnote text follows
    toks = re.findall(r"-{2,}|[+-]?\d*\.?\d+", tail)
    if len(toks) != ncols:
        return None, f"{how}; Mistral gave {len(toks)} tokens for {ncols} columns: {tail.strip()[:60]!r}"
    return toks, f"{how}; Mistral strip read"

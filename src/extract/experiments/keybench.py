"""Reader tuning on key-column crops.

The printed keys (800 m post numbers, tower heights) are set in the same type
as the data values, and their true values follow from the known geometry, so
they form a labelled tuning set that needs no reference data. Only rows whose
position came from a real text band are used. Run on dev pages only.

    uv run python -m extract.experiments.keybench <pdf_index> ...
"""
from __future__ import annotations

import sys
from collections import Counter

import numpy as np

from extract import structure as S
from extract.pdfio import page_image
from extract.preprocess import PreprocessConfig, preprocess
from extract.readers import EasyOCRReader, TesseractReader


def collect(pages: list[int], cfg: PreprocessConfig = PreprocessConfig()) -> list[tuple[np.ndarray, str]]:
    out = []
    for i in pages:
        img, _ = preprocess(page_image(i), cfg)
        st = S.analyse_tower_page(img) if i >= 206 else S.analyse_arc_page(img)
        for p in st.panels:
            key = "height" if st.table == "5.3" else "post800"
            x0, x1 = p.cols[key]
            for r, (t, b) in zip(p.rows, p.edges):
                if not r.inferred:
                    out.append((img[t:b, x0:x1].copy(), r.key_expected))
    return out


def evaluate(reader, data) -> tuple[float, Counter]:
    errs: Counter = Counter()
    ok = 0
    for crop, truth in data:
        t = reader.read(crop)["text"]
        if t == truth:
            ok += 1
        else:
            errs[(truth, t)] += 1
    return ok / max(1, len(data)), errs


if __name__ == "__main__":
    pages = [int(x) for x in sys.argv[1:]]
    data = collect(pages)
    print(f"{len(data)} key crops")
    variants = [TesseractReader(psm=7), TesseractReader(psm=7, scale=2.0), TesseractReader(psm=8, scale=2.0),
                TesseractReader(psm=13, scale=2.0), EasyOCRReader(), EasyOCRReader(scale=2.0)]
    for v in variants:
        acc, errs = evaluate(v, data)
        print(f"{v.name:10s} {v.describe()}  acc={acc:.3f}  top errors={errs.most_common(6)}")

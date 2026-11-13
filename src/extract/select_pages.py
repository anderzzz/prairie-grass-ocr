"""Rule-based pilot page selection -> config/pilot_pages.yaml.

If config/pilot_pages.yaml already exists it is used as is (never rewritten).

Rule (also recorded in the YAML):
  Eligible Table 5.2 pages: run label resolved, page half resolved, all 15
  column boundaries found (structure detection did not fail), and at least
  MIN_INKED value cells containing ink (pages that are almost all blank say
  little about reading accuracy).
  Rank eligible pages by legibility (docs/page_inventory.csv).
    dev:     best, worst, and 2 of the 6 pages nearest the median
    holdout: 2nd best, 2nd worst, and 2 other pages near the median
  Near-median: take the 6 eligible pages closest to the median legibility,
  shuffle them with random.Random(SEED); dev gets positions 0-1, holdout 2-3.
  Table 5.3: shuffle the tower pages with random.Random(SEED); dev gets the
  first, holdout the second.
"""
from __future__ import annotations

import csv
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import yaml

from .pdfio import REPO

CONFIG = REPO / "config" / "pilot_pages.yaml"
SEED = 1956
MIN_INKED = 25


def _inked_cells(idx: int) -> int:
    from . import structure as S
    from .cells import arc_cells, ink_stats
    from .pdfio import page_image
    from .preprocess import PreprocessConfig, preprocess
    img, _ = preprocess(page_image(idx), PreprocessConfig())
    st = S.analyse_arc_page(img)
    if len(st.col_bounds) != 15:
        return -1  # structure failed
    cells = arc_cells(idx, st, run="?")
    return sum(1 for c in cells if ink_stats(img, c.box)["tall_components"] > 0)


def select(inventory: Path = REPO / "docs" / "page_inventory.csv") -> dict:
    rows = list(csv.DictReader(inventory.open()))
    arc = [r for r in rows if r["table"] == "5.2" and r["runs"] and r["half"] and r["legibility"]]
    with ProcessPoolExecutor(6) as ex:
        inked = list(ex.map(_inked_cells, [int(r["pdf_index"]) for r in arc]))
    for r, n in zip(arc, inked):
        r["inked_cells"] = n
    eligible = [r for r in arc if r["inked_cells"] >= MIN_INKED]
    excluded = {r["pdf_index"]: ("structure failed" if r["inked_cells"] < 0 else f"{r['inked_cells']} inked cells")
                for r in arc if r["inked_cells"] < MIN_INKED}
    eligible.sort(key=lambda r: float(r["legibility"]), reverse=True)
    leg = [float(r["legibility"]) for r in eligible]
    med = sorted(leg)[len(leg) // 2]
    taken = {eligible[0]["pdf_index"], eligible[1]["pdf_index"],
             eligible[-1]["pdf_index"], eligible[-2]["pdf_index"]}
    mid = sorted((r for r in eligible if r["pdf_index"] not in taken),
                 key=lambda r: abs(float(r["legibility"]) - med))[:6]
    rng = random.Random(SEED)
    rng.shuffle(mid)
    towers = [r for r in rows if r["table"] == "5.3"]
    rng_t = random.Random(SEED)
    rng_t.shuffle(towers)

    def desc(r, stratum):
        return {"pdf_index": int(r["pdf_index"]), "printed_page": int(r["printed_page"]),
                "table": r["table"], "runs": r["runs"], "half": r.get("half") or None,
                "legibility": float(r["legibility"]), "stratum": stratum,
                **({"inked_cells": r["inked_cells"]} if "inked_cells" in r else {})}

    dev = [desc(eligible[0], "best"), desc(mid[0], "near-median"), desc(mid[1], "near-median"),
           desc(eligible[-1], "worst"), desc(towers[0], "tower (random)")]
    hold = [desc(eligible[1], "2nd best"), desc(mid[2], "near-median"), desc(mid[3], "near-median"),
            desc(eligible[-2], "2nd worst"), desc(towers[1], "tower (random)")]
    return {
        "rule": (__doc__ or "").strip(),
        "seed": SEED,
        "min_inked_cells": MIN_INKED,
        "eligible_arc_pages": len(eligible),
        "median_legibility": med,
        "excluded_arc_pages": excluded,
        "unresolved_arc_pages": [r["pdf_index"] for r in rows if r["table"] == "5.2" and not r["runs"]],
        "dev": dev,
        "holdout": hold,
    }


def load_or_create() -> dict:
    if CONFIG.exists():
        return yaml.safe_load(CONFIG.read_text())
    sel = select()
    CONFIG.parent.mkdir(exist_ok=True)
    CONFIG.write_text(yaml.safe_dump(sel, sort_keys=False, width=100))
    return sel


if __name__ == "__main__":
    s = load_or_create()
    for k in ("dev", "holdout"):
        print(k, [(p["pdf_index"], p["runs"], p.get("half"), p["stratum"]) for p in s[k]])

"""Turn a PageStructure into keyed cells with page-pixel boxes.

Row and column keys come from the known geometry plus the page's resolved
keys (page half / run for Table 5.2; tower group / height and column run
headers for Table 5.3). Structural doubts attach to the cells they affect.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .structure import ARC_DISTANCES, ARC_HALVES, PageStructure, isolate_glyphs


@dataclass
class CellSpec:
    page: int
    table: str
    run: str                   # run label ('' if unresolved)
    group: str                 # arc distance (m) or tower number
    position: str              # post number or height (m)
    box: tuple[int, int, int, int]
    structural: list[str] = field(default_factory=list)

    @property
    def cell_id(self) -> str:
        return f"p{self.page}_{self.table}_r{self.run or 'X'}_{self.group}_{self.position}"


def arc_cells(page: int, st: PageStructure, run: str, run_note: str = "") -> list[CellSpec]:
    half = st.meta.get("half")
    out: list[CellSpec] = []
    page_notes = [run_note] if run_note else []
    if half is None:
        page_notes.append("page half (posts 1-90 vs 91-181) undetermined")
    for p in st.panels:
        pidx = p.meta.get("panel", 0)
        if not p.rows or half is None:
            continue
        start = ARC_HALVES[half][pidx]
        n = len(p.rows)
        for i, (row, (t, b)) in enumerate(zip(p.rows, p.edges)):
            post800 = start + i
            rnotes = list(page_notes)
            if row.inferred:
                rnotes.append("row position inferred (800 m post number not found)")
            elif row.key_read and row.key_read != row.key_expected:
                rnotes.append(f"800 m post printed as '{row.key_read}', expected {row.key_expected}")
            x0, x1 = p.cols["800"]
            out.append(CellSpec(page, "5.2", run, "800", str(post800), (x0, t, x1, b), list(rnotes)))
            if post800 % 2 == 1:
                inner = (post800 + 1) // 2
                # inner-arc cell spans this row and the next (even) 800 m row
                b2 = p.edges[i + 1][1] if i + 1 < n else b
                for d in ARC_DISTANCES[:-1]:
                    x0, x1 = p.cols[d]
                    out.append(CellSpec(page, "5.2", run, d, str(inner), (x0, t, x1, b2), list(rnotes)))
    return out


def tower_cells(page: int, st: PageStructure, col_runs: list[dict]) -> list[CellSpec]:
    out: list[CellSpec] = []
    if not st.panels:
        return out
    p = st.panels[0]
    by_col = {c["col"]: c for c in col_runs}
    for i, (row, (t, b)) in enumerate(zip(p.rows, p.edges)):
        tower = str(i // 9 + 1)
        rnotes = []
        if row.inferred:
            rnotes.append("row position inferred (height label not found)")
        elif row.key_read and row.key_read != row.key_expected:
            rnotes.append(f"height printed as '{row.key_read}', expected {row.key_expected}")
        for name, (x0, x1) in p.cols.items():
            if not name.startswith("c"):
                continue
            c = by_col.get(name, {})
            run = c.get("run") or ""
            notes = list(rnotes)
            if c.get("source") == "blank header":
                continue  # unused column
            if not run:
                notes.append(f"column run header unresolved: {c.get('raw')}")
            elif c.get("source") != "both readers agree":
                notes.append(f"column run header: {c.get('source')} {c.get('raw')}")
            out.append(CellSpec(page, "5.3", run, tower, row.key_expected, (x0, t, x1, b), notes))
    return out


def ink_stats(img: np.ndarray, box: tuple[int, int, int, int]) -> dict:
    x0, y0, x1, y1 = box
    _, st = isolate_glyphs(img[y0:y1, x0:x1])
    return st

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
    key_source: str = "pipeline"
    run_auto: str = ""

    @property
    def cell_id(self) -> str:
        return f"p{self.page}_{self.table}_r{self.run or 'X'}_{self.group}_{self.position}"


def _key_note(rows, i: int, what: str) -> str:
    """A printed row key that reads as a *neighbouring* row's key (within two
    rows) is evidence the row lattice is locally shifted -> structural note.
    Any other misreading is key-OCR noise against a lattice fitted by voting
    over all rows, and is not flagged."""
    row = rows[i]
    if row.inferred:
        return f"row position inferred ({what} not found)"
    if not row.key_read or row.key_read == row.key_expected:
        return ""
    near = {rows[j].key_expected for j in range(max(0, i - 2), min(len(rows), i + 3)) if j != i}
    if row.key_read in near:
        return f"{what} printed as '{row.key_read}', expected {row.key_expected} (row shift?)"
    return ""


def arc_cells(page: int, st: PageStructure, run: str, run_note: str = "",
              key_source: str = "pipeline", run_auto: str = "") -> list[CellSpec]:
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
        inferred_cols = set(p.meta.get("inferred_cols", []))
        n = len(p.rows)
        for i, (row, (t, b)) in enumerate(zip(p.rows, p.edges)):
            post800 = start + i
            rnotes = list(page_notes)
            kn = _key_note(p.rows, i, "800 m post number")
            if kn:
                rnotes.append(kn)
            x0, x1 = p.cols["800"]
            cn = rnotes + (["column bound inferred from template (rule not visible)"] if "800" in inferred_cols else [])
            out.append(CellSpec(page, "5.2", run, "800", str(post800), (x0, t, x1, b), cn, key_source, run_auto))
            if post800 % 2 == 1:
                inner = (post800 + 1) // 2
                # inner-arc cell spans this row and the next (even) 800 m row
                b2 = p.edges[i + 1][1] if i + 1 < n else b
                for d in ARC_DISTANCES[:-1]:
                    x0, x1 = p.cols[d]
                    cn = rnotes + (["column bound inferred from template (rule not visible)"] if d in inferred_cols else [])
                    out.append(CellSpec(page, "5.2", run, d, str(inner), (x0, t, x1, b2), cn, key_source, run_auto))
    return out


def tower_cells(page: int, st: PageStructure, col_runs: list[dict]) -> list[CellSpec]:
    out: list[CellSpec] = []
    if not st.panels:
        return out
    p = st.panels[0]
    by_col = {c["col"]: c for c in col_runs}
    for i, (row, (t, b)) in enumerate(zip(p.rows, p.edges)):
        tower = str(i // 9 + 1)
        kn = _key_note(p.rows, i, "height label")
        rnotes = [kn] if kn else []
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
            elif c.get("source") not in ("both readers agree", "manual"):
                notes.append(f"column run header: {c.get('source')} {c.get('raw')}")
            out.append(CellSpec(page, "5.3", run, tower, row.key_expected, (x0, t, x1, b), notes,
                                c.get("key_source", "pipeline"), c.get("run_auto") or ""))
    return out


def ink_stats(img: np.ndarray, box: tuple[int, int, int, int]) -> dict:
    x0, y0, x1, y1 = box
    _, st = isolate_glyphs(img[y0:y1, x0:x1])
    return st

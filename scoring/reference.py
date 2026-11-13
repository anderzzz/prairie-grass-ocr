"""Parsers for the reference transcription (answer key; scoring only).

Arcs (PGARCS.txt, format in D6589_UGDesign2_Table_2.pdf): per run and arc a
two-line header then one record per receptor: bearing (deg), bearing - 268,
arc radius (m), concentration. Receptors absent from a block are posts with
no measurable concentration (printed blank); -9 means missing (printed M).

Towers (PGVertConc.txt): per run a 9 x 6 grid, heights x tower bearings;
0.000 = no measurable concentration, -9 = missing.

Run numbers 70 and 71 in both files are runs 35-S and 48-S.

Post <-> bearing (Barad 1958, Vol. I, sec. 5.3): post 1 of every arc is at
270 deg; posts are 2 deg apart on the 50-400 m arcs and 1 deg apart at 800 m.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REF = REPO / "reference"
SPECIAL_RUNS = {70: "35S", 71: "48S"}
TOWER_BEARINGS = [325, 339, 353, 7, 21, 35]   # towers 1-6 along the 100 m arc
HEIGHTS = ["17.5", "13.5", "10.5", "7.5", "4.5", "2.5", "1.5", "1.0", "0.5"]


def run_label(n: int) -> str:
    return SPECIAL_RUNS.get(n, str(n))


def post_bearing(arc_m: int, post: int) -> int:
    step = 1 if arc_m == 800 else 2
    return (270 + step * (post - 1)) % 360


def load_arcs(path: Path = REF / "PGARCS.txt") -> dict:
    """-> {(run, arc_m): {bearing: value_str}}"""
    lines = path.read_text().splitlines()[1:]
    out, i = {}, 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        h2 = [x.strip() for x in lines[i].split(",")]
        h3 = [x.strip() for x in lines[i + 1].split(",")]
        run, arc = run_label(int(h2[0])), int(float(h2[4]))
        n = int(h3[0])
        rec = {}
        for ln in lines[i + 2: i + 2 + n]:
            b, _, _, v = ln.split()
            rec[int(float(b)) % 360] = v
        out[(run, arc)] = rec
        i += 2 + n
    return out


def load_towers(path: Path = REF / "PGVertConc.txt") -> dict:
    """-> {(run, tower): {height: value_str}}; also checks bearings."""
    lines = path.read_text().splitlines()
    out = {}
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("Run No."):
            run = run_label(int(ln.split()[2]))
            bearings = [int(x) for x in lines[i + 1].split()[1:]]
            if bearings != TOWER_BEARINGS:
                raise ValueError(f"unexpected tower bearings for run {run}: {bearings}")
            for ln2 in lines[i + 2: i + 11]:
                parts = ln2.split()
                h = parts[0]
                for t, v in enumerate(parts[1:7], start=1):
                    out.setdefault((run, str(t)), {})[h] = v
            i += 11
        else:
            i += 1
    return out

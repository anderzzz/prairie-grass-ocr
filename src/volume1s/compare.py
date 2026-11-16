"""Compare Mistral's and Sonnet's readings cell by cell.

    cd src && uv run python -m volume1s.compare

Output: output/volume1s/second_read/reads.csv, one row per parsed cell:
mistral token, sonnet token ("<none>" if Sonnet gave no reading), agree.
"""
from __future__ import annotations

import csv
import json
import re

from volume2.common import norm

from .parse import norm_run, parse_all
from .second_read import SECOND

QUANT = {"speed": "wind_speed", "direction": "wind_direction", "sigma": "sigma_theta"}


def tok(s: str) -> str:
    return re.sub(r"\s+", " ", norm(s or "")).strip()


def sonnet_cells() -> dict[str, str]:
    """cell_id-like key -> Sonnet token. Keys: (table, run[, arc|quantity...])."""
    out: dict[tuple, str] = {}
    for t in ("5.1", "5.4"):
        for name, v in json.loads((SECOND / f"{t}.json").read_text()).items():
            for row in v["raw"]["rows"]:
                run = norm_run(row["label"])
                if t == "5.1":
                    out[("5.1", run)] = row["cells"][0] if row["cells"] else ""
                else:
                    cells = row["cells"][-5:] if len(row["cells"]) >= 5 else row["cells"] + [""] * (5 - len(row["cells"]))
                    for arc, c in zip((50, 100, 200, 400, 800), cells):
                        out[("5.4", run, arc)] = c
    # 6.1: aligned by position (page, block, column), not by the printed release number,
    # so that a misread header is compared like any other cell.
    for name, v in json.loads((SECOND / "6.1.json").read_text()).items():
        page, half = re.fullmatch(r"p(\d+)-(top|bottom)", name).groups()
        rows = v["raw"]["rows"]
        heads = [k for k, row in enumerate(rows) if row["label"].startswith("Gas release")]
        if len(heads) != 1:
            raise SystemExit(f"{name}: expected one block, Sonnet gave {len(heads)}")
        pos = ("6.1", int(page), 0 if half == "top" else 1)
        for sub in rows[heads[0]: heads[0] + 15]:
            lab = sub["label"]
            for j, c in enumerate(sub["cells"], start=1):
                if lab.startswith("Gas release"):
                    out[pos + (j, "key:release")] = c
                elif lab.startswith("Date"):
                    out[pos + (j, "key:date")] = c
                elif lab.startswith("Time"):
                    out[pos + (j, "key:time_cst")] = c
                else:
                    m = re.match(r"(speed|direction|sigma) (Source|450 m) \((10|20) min\)", lab)
                    if m:
                        out[pos + (j, QUANT[m.group(1)], "source" if m.group(2) == "Source" else "450m",
                                   int(m.group(3)))] = c
    return out


def key(c: dict) -> tuple:
    if c["table"] == "5.1":
        return ("5.1", c["run"])
    if c["table"] == "5.4":
        return ("5.4", c["run"], c["arc_m"])
    pos = ("6.1", c["pdf_index"], c["block"], c["grid_col"])
    if c["quantity"].startswith("key"):
        return pos + (c["quantity"],)
    return pos + (c["quantity"], c["location"], c["period_min"])


def compare() -> list[dict]:
    T = parse_all()
    s = sonnet_cells()
    out = []
    for t in ("5.1", "5.4", "6.1"):
        for c in T[t]:
            k = key(c)
            st = tok(s[k]) if k in s else "<none>"
            mt = tok(c["token"])
            if c["quantity"] == "key:release":
                mt, st = norm_run(mt), norm_run(st) if st != "<none>" else st
            out.append({"cell_id": c["cell_id"], "table": t, "mistral": mt, "sonnet": st,
                        "agree": mt == st})
    return out


def main() -> None:
    rows = compare()
    with (SECOND / "reads.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    dis = [r for r in rows if not r["agree"]]
    print(f"{len(rows)} cells, {len(rows) - len(dis)} agree, {len(dis)} differ")
    for r in dis:
        print(f"  {r['cell_id']:45s} mistral={r['mistral']!r:10s} sonnet={r['sonnet']!r}")


if __name__ == "__main__":
    main()

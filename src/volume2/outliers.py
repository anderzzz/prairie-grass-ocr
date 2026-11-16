"""Outlier screen for the Volume II dataset: flags, never removes or alters.

    cd src && uv run python -m volume2.outliers

Adds a column `outlier` to output/volume2/dataset/table_<id>.csv:

  spike   the value departs from the mean of its two neighbours in the same series
          (8.2 hourly in time, 12.1 up the sounding, 13.1 along the flight) by more than
          K robust scales of such departures in that series family, and both neighbours
          lie on the same side (a spike, not a step). This is what a digit misread looks like.
  global  the value lies more than K robust scales (1.4826 MAD) from the median of its
          variable (same table, quantity, height/level). Real extremes (inversions, calms)
          also land here; the flag is for the user to judge, not a verdict.

A cleaned view can be had by filtering on `outlier` and `quality`; the printed token
and value stay as they are.
"""
from __future__ import annotations

import csv
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime

from .dataset import DATASET

K_SPIKE, K_GLOBAL = 6.0, 6.0
NOT_PHYSICAL = {"initial_time", "run_time", "wind_direction", "trace_code"}   # clock, circular, code


def _num(c):
    try:
        return float(c["value"]) if c["status"] == "value" and c["value"] not in ("", None) else None
    except ValueError:
        return None


def _scale(xs):
    if len(xs) < 8:
        return None
    m = st.median(xs)
    s = 1.4826 * st.median(abs(x - m) for x in xs)
    return (m, s) if s > 0 else None


def _when(c):
    try:
        return datetime.strptime(f"{c['date']} {c['cst'][:4]}", "%Y-%m-%d %H%M")
    except (ValueError, KeyError, TypeError):
        return None


def series(table, rows):
    """{family: [ordered series of cells]} for the spike test."""
    S = defaultdict(list)
    if table == "8.2":
        g = defaultdict(list)
        for c in rows:
            if _when(c) and c["quantity"] not in NOT_PHYSICAL:
                g[(c["section"], c["quantity"], c["height_m"])].append(c)
        for k, cs in g.items():
            cs.sort(key=_when)
            run = [cs[0]]
            for a, b in zip(cs, cs[1:]):           # break the series at gaps over 2 h
                if (_when(b) - _when(a)).total_seconds() > 7200:
                    S[k[:2]].append(run)
                    run = []
                run.append(b)
            S[k[:2]].append(run)
    elif table == "12.1":
        g = defaultdict(list)
        for c in rows:
            if c["part"] == "sounding":
                g[(c["release"], c["date"], c["panel"], c["quantity"])].append(c)
        for k, cs in g.items():
            S[("sounding", k[3])].append(sorted(cs, key=lambda c: int(c["level"])))
    elif table == "13.1":
        # rows follow the flight (climb, then descent); neighbours are taken in pressure instead
        g, p = defaultdict(list), {}
        for c in rows:
            if c["quantity"] == "pressure" and _num(c) is not None:
                p[(c["field_test"], c["date"], c["block"], c["level"])] = _num(c)
        for c in rows:
            k = (c["field_test"], c["date"], c["block"], c["level"])
            if k in p and c["quantity"] in ("temperature", "dew_point", "vapor_pressure", "relative_humidity"):
                g[k[:3] + (c["quantity"],)].append(c)
        for k, cs in g.items():
            S[k[3]].append(sorted(cs, key=lambda c: -p[(c["field_test"], c["date"], c["block"], c["level"])]))
    return S


def spikes(table, rows):
    out = {}
    for fam, runs in series(table, rows).items():
        trip = []
        for run in runs:
            v = [(c, _num(c)) for c in run]
            v = [(c, x) for c, x in v if x is not None]
            for (a, xa), (b, xb), (n, xn) in zip(v, v[1:], v[2:]):
                trip.append((b, xb - (xa + xn) / 2, (xb - xa) * (xb - xn) > 0))
        sc = _scale([r for _, r, _ in trip])
        if not sc:
            continue
        m, s = sc
        for c, r, same_side in trip:
            if same_side and abs(r - m) > K_SPIKE * s:
                out[c["cell_id"]] = f"spike ({(r - m) / s:+.0f} scales)"
    if table == "8.2":
        # a misread hits one cell; a jump seen at several heights at once is weather, not a misread
        n = Counter((c["section"], c["quantity"], c["date"], c["cst"]) for c in rows if c["cell_id"] in out)
        out = {c["cell_id"]: out[c["cell_id"]] for c in rows
               if c["cell_id"] in out and n[(c["section"], c["quantity"], c["date"], c["cst"])] == 1}
    return out


def global_key(table, c):
    if c["quantity"] in NOT_PHYSICAL:
        return None
    if table in ("8.1", "8.2"):
        if c["section"] == "radiation":
            return None                          # diurnal: one median is meaningless (8.x-radiation checks it)
        return (c["section"], c["quantity"], c["height_m"])
    if table == "12.1":
        return (c["part"], c["quantity"], c.get("level_label") if c["part"] == "sounding" else "")
    if table == "13.1":
        return (c["quantity"],) if c["quantity"] in ("temperature", "dew_point", "relative_humidity") else None
    return (c["quantity"], c.get("row_key", c.get("row", "")) if table.startswith(("7", "11")) else "")


def globals_(table, rows):
    g = defaultdict(list)
    for c in rows:
        k = global_key(table, c)
        if k is not None and _num(c) is not None:
            g[k].append(c)
    out = {}
    for cs in g.values():
        sc = _scale([_num(c) for c in cs])
        if not sc:
            continue
        m, s = sc
        for c in cs:
            z = (_num(c) - m) / s
            if abs(z) > K_GLOBAL:
                out[c["cell_id"]] = f"global ({z:+.0f} scales)"
    return out


def main() -> None:
    tally = Counter()
    for f in sorted(DATASET.glob("table_*.csv")):
        table = f.stem.split("_", 1)[1]
        rows = list(csv.DictReader(f.open()))
        flags = globals_(table, rows)
        flags.update(spikes(table, rows))        # a spike says more than a global flag
        for c in rows:
            c["outlier"] = flags.get(c["cell_id"], "")
            if c["outlier"]:
                tally[(table, c["outlier"].split()[0], c["quality"])] += 1
        cols = list(rows[0])
        with f.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    for k, n in sorted(tally.items()):
        print(*k, n, sep="\t")
    print("total flagged", sum(tally.values()))


if __name__ == "__main__":
    main()

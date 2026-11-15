"""Summaries of the reviewed Volume I dataset for the overview page.

    uv run python scripts/dashboard_data.py

Reads output/volume1/dataset/{arcs,towers}.csv only (no reference data) and
writes output/volume1/dashboard/{layout,coverage,arc_values,tower_values}.json,
each {rows, meta} with this script's own text in meta.
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DS = REPO / "output" / "volume1" / "dataset"
OUT = REPO / "output" / "volume1" / "dashboard"
CODE = Path(__file__).read_text()


def run_key(r):
    n = int("".join(c for c in r if c.isdigit()))
    return n + (0 if r.endswith("S") else 0.5)


def load(name):
    with (DS / f"{name}.csv").open() as f:
        return list(csv.DictReader(f))


def changed(r):
    return r["reviewed"] == "True" and not r["value_source"].startswith("owner review (Sonnet")


def write(name, rows, inputs):
    meta = [{"label": "dashboard_data.py", "value": CODE, "type": "code", "lang": "python"},
            {"label": "Input", "value": inputs}]
    (OUT / f"{name}.json").write_text(json.dumps({"rows": rows, "meta": meta}, separators=(",", ":")))
    print(name, len(rows))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    arcs, towers = load("arcs"), load("towers")
    # layout: one row per arc and one for the towers
    layout = []
    groups = defaultdict(list)
    for r in arcs:
        groups[f"{r['arc_m']} m arc"].append(r)
    groups["Towers"] = towers
    for name, rs in groups.items():
        st = Counter(r["status"] for r in rs)
        is_arc = name != "Towers"
        posts = sorted({int(r["post"]) for r in rs}) if is_arc else []
        layout.append({
            "group": name,
            "arc_m": int(name.split()[0]) if is_arc else None,
            "positions": len(posts) if is_arc else len({(r["tower"], r["height_m"]) for r in rs}),
            "first_post": posts[0] if is_arc else None,
            "last_post": posts[-1] if is_arc else None,
            "spacing_deg": (1 if name.startswith("800") else 2) if is_arc else None,
            "runs": len({r["run"] for r in rs}),
            "pages": len({r["pdf_index"] for r in rs}),
            "cells": len(rs), "values": st["value"], "not_measurable": st["not_measurable"],
            "missing": st["missing"], "flagged": sum(r["flagged"] == "True" for r in rs),
            "reviewed": sum(r["reviewed"] == "True" for r in rs),
            "changed_by_review": sum(changed(r) for r in rs)})
    layout.sort(key=lambda x: (x["arc_m"] is None, x["arc_m"] or 0))
    write("layout", layout, "arcs.csv, towers.csv")
    # coverage: run x group -> values and peak
    cov = defaultdict(lambda: {"values": 0, "cells": 0, "peak": 0.0})
    for r in arcs:
        c = cov[(r["run"], f"{r['arc_m']} m")]
        c["cells"] += 1
    for r in towers:
        cov[(r["run"], "Towers")]["cells"] += 1
    for r in arcs + towers:
        if r["status"] == "value":
            g = f"{r['arc_m']} m" if "arc_m" in r else "Towers"
            c = cov[(r["run"], g)]
            c["values"] += 1
            c["peak"] = max(c["peak"], float(r["concentration_mg_m3"]))
    rows = [{"run": k[0], "run_order": run_key(k[0]), "group": k[1], **v} for k, v in cov.items()]
    rows.sort(key=lambda x: (x["run_order"], x["group"]))
    write("coverage", rows, "arcs.csv, towers.csv")
    # value cells
    av = [{"run": r["run"], "arc_m": int(r["arc_m"]), "post": int(r["post"]),
           "bearing_deg": int(r["bearing_deg"]), "conc": float(r["concentration_mg_m3"]),
           "reviewed": r["reviewed"] == "True"} for r in arcs if r["status"] == "value"]
    write("arc_values", av, "arcs.csv")
    tv = [{"run": r["run"], "tower": int(r["tower"]), "height_m": float(r["height_m"]),
           "conc": float(r["concentration_mg_m3"]), "estimated": r["estimated"] == "True"}
          for r in towers if r["status"] == "value"]
    write("tower_values", tv, "towers.csv")


if __name__ == "__main__":
    main()

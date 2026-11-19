"""Where the published Volume I concentrations and the harmo.org reference differ.

    uv run python -m scoring.reference_comparison      (make reference-comparison)

Writes output/publish/reference_comparison.csv: one row per cell of Tables
5.2/5.3 where the dataset and J. S. Irwin's transcription (PGARCS.txt,
PGVertConc.txt; see scoring/reference_checksums.json) say different things,
plus the cells where they disagreed before review and the review sided with
the reference (our misreads, now fixed).

This is a statement about the reference, not about our data, so it lives
apart from annotations.jsonl and is built here in scoring/, the only code
allowed to read the reference. It needs reference/ (make reference) and runs
scoring.volume_compare first to align the cells.

Columns:
  cell_id ... printed_page   keys and provenance, as in arcs.csv / towers.csv
  printed_token, dataset_status, dataset_value   what the dataset holds
  reference_file, reference_entry   the reference record as written
                                    (blank = no record, i.e. no measurable concentration)
  reference_reading     value | not_measurable | missing, by the reference's own conventions
  reference_agrees_with_print   True only where review found the reference right
  difference            printed_blank_coded_missing | printed_zero_coded_blank |
                        value_missing_from_reference | reference_value_where_print_blank |
                        magnitude (x5 or more) | digit | none (agrees after review) |
                        column_copy (run 7, 100 m: the reference repeats its 200 m values) |
                        post_assignment (run 61, 800 m: values printed between posts, assigned
                        differently)
  reference_matches_suspected_alternative   the reference holds the value the curators
                        suspect was intended (annotations.jsonl, suspected_original_error)
  ratio                 reference / dataset, where both are numbers
  review_group          A-D as in the owner review (REPORT.md); BM = blank vs missing, not reviewed
  review_note           the group's description and the owner's basis
  reviewed_by, review_date
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from . import volume_compare
from .triage import GROUP_TITLES

REPO = Path(__file__).resolve().parents[1]
CELLS = REPO / "output" / "scores" / "volume1" / "cells.csv"
VERDICTS = REPO / "config" / "review" / "volume1_verdicts.csv"
DATA = REPO / "output" / "volume1" / "dataset"
CHECKSUMS = REPO / "scoring" / "reference_checksums.json"
OUT = REPO / "output" / "publish" / "reference_comparison.csv"

REF_FILE = {"5.2": "PGARCS.txt", "5.3": "PGVertConc.txt"}
GROUP_TITLES = dict(GROUP_TITLES, BM="Printed blank (no measurable concentration); the reference "
                                     "records -9 (missing). Not reviewed cell by cell: the table "
                                     "legend decides.")
# groups whose cause is known at page level (REPORT.md, owner review 2026-11-15)
PAGE_DIFFERENCE = {"A": "post_assignment", "B": "column_copy"}


def _rows(p: Path) -> list[dict]:
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def _num(s: str) -> float | None:
    try:
        return float(s.rstrip("*"))
    except (ValueError, AttributeError):
        return None


def _reference_reading(c: dict) -> str:
    return {"number": "value", "blank": "not_measurable", "missing": "missing"}.get(c["ref_kind"], c["ref_kind"])


def _difference(d: dict, ref_reading: str, ref_val: float | None) -> tuple[str, str]:
    """-> (difference, ratio)"""
    status, val = d["status"], _num(d["concentration_mg_m3"])
    if status == "value" and ref_reading == "value":
        if math.isclose(val, ref_val, abs_tol=1e-9):
            return "none", "1"
        if val == 0 or ref_val == 0:
            return "printed_zero_coded_blank" if val == 0 else "reference_value_where_print_blank", ""
        r = ref_val / val
        return ("magnitude" if max(r, 1 / r) >= 5 else "digit"), f"{r:.4g}"
    if status == "not_measurable" and ref_reading == "missing":
        return "printed_blank_coded_missing", ""
    if status == "value" and ref_reading == "not_measurable":
        return ("printed_zero_coded_blank" if val == 0 else "value_missing_from_reference"), ""
    if status == "not_measurable" and ref_reading == "value":
        return "reference_value_where_print_blank", ""
    if status == ref_reading:
        return "none", ""
    return f"{status}_vs_{ref_reading}", ""


def main() -> None:
    volume_compare.main()                       # aligns every cell with the reference -> CELLS
    data = {r["cell_id"]: (r, "volume1/arcs.csv") for r in _rows(DATA / "arcs.csv")}
    data |= {r["cell_id"]: (r, "volume1/towers.csv") for r in _rows(DATA / "towers.csv")}
    verdicts = {v["cell_id"]: v for v in _rows(VERDICTS)}
    sums = json.loads(CHECKSUMS.read_text())
    out = []
    for c in _rows(CELLS):
        if c["outcome"] in ("match", "no_reference") and c["cell_id"] not in verdicts:
            continue
        d, file = data[c["cell_id"]]
        reading = _reference_reading(c)
        ref_val = _num(c["ref_value"]) if reading == "value" else None
        diff, ratio = _difference(d, reading, ref_val)
        v = verdicts.get(c["cell_id"])
        group = v["group"] if v else ("BM" if c["outcome"] == "blank_vs_missing" else "")
        assert group, c["cell_id"]
        if diff != "none" and group in PAGE_DIFFERENCE:   # the page-level explanation outranks the size
            diff = PAGE_DIFFERENCE[group]
        alt = d.get("suspect_alternative", "")
        out.append({
            "cell_id": c["cell_id"], "file": file, "table": c["table"], "run": d["run"],
            "arc_m": d.get("arc_m", ""), "post": d.get("post", ""), "bearing_deg": d.get("bearing_deg", ""),
            "tower": d.get("tower", ""), "height_m": d.get("height_m", ""),
            "pdf_index": d["pdf_index"], "printed_page": d["printed_page"],
            "printed_token": d["token"], "dataset_status": d["status"],
            "dataset_value": d["concentration_mg_m3"],
            "reference_file": REF_FILE[c["table"]], "reference_entry": c["ref_value"],
            "reference_reading": reading,
            "reference_agrees_with_print": diff == "none",
            "difference": diff, "ratio": ratio,
            "reference_matches_suspected_alternative":
                bool(alt) and ref_val is not None and math.isclose(_num(alt), ref_val, abs_tol=1e-9), "review_group": group,
            "review_note": GROUP_TITLES[group] + (f" Owner: {v['basis']}." if v else ""),
            "reviewed_by": v["reviewer"] if v else "", "review_date": v["date"] if v else "",
            "reference_sha256": sums[REF_FILE[c["table"]]]["sha256"],
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print(f"{len(out)} cells -> {OUT.relative_to(REPO)}")
    for k, n in Counter((r["difference"]) for r in out).most_common():
        print(f"  {k}: {n}")
    print("  by group:", dict(Counter((r["review_group"], r["reference_agrees_with_print"]) for r in out)))


if __name__ == "__main__":
    main()

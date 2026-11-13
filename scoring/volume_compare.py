"""Compare the Volume I extraction with the reference (assessment, not a score).

    uv run python -m scoring.volume_compare

Reads output/volume1/extracted/p<idx>.csv and aligns every cell with the
reference exactly as scoring.score does. Writes output/scores/volume1/:
cells.csv (every cell with its outcome), conflicts.csv (cells where the
value and the reference differ, largest first), pages.csv and summary.md.

Categories (no adjudication):
  match            same number, both blank, or both missing
  blank_vs_missing printed table read as blank, reference says missing (-9)
  value_mismatch   both numbers, different (split by size below)
  false_blank      read blank, reference has a number
  spurious_value   read a number, reference blank / not listed
  other_mark       M on one side only, other cases
  unparseable      value token not interpretable
  no_reference     run/arc or run/tower not in the reference at all
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .reference import load_arcs, load_towers, post_bearing
from .score import SCORES, score_page

REPO = Path(__file__).resolve().parents[1]
VOL = REPO / "output" / "volume1" / "extracted"
OUT = SCORES / "volume1"


def size_class(a: float, r: float) -> str:
    if a <= 0 or r <= 0:
        return "n/a"
    d = abs(math.log10(a / r))
    if d >= 0.9:
        return "x10+ (decimal point / magnitude)"
    if d >= 0.3:
        return "x2-x10 (leading digit)"
    if d >= 0.05:
        return "12-100%"
    return "<12% (trailing digit)"


def main() -> str:
    arcs, towers = load_arcs(), load_towers()
    OUT.mkdir(parents=True, exist_ok=True)
    allc, pages = [], []
    covered_blocks = set()
    for path in sorted(VOL.glob("p*.csv"), key=lambda p: int(p.stem[1:])):
        idx = int(path.stem[1:])
        meta = json.loads((VOL / f"p{idx}.meta.json").read_text())
        rows = list(csv.DictReader(path.open()))
        sc, unc = score_page(rows, meta["table"], arcs, towers)
        for c in sc:
            if c["outcome"] == "mark_mismatch" and c["value_kind"] == "blank" and c["ref_kind"] == "missing":
                c["outcome"] = "blank_vs_missing"
            elif c["outcome"] == "mark_mismatch":
                c["outcome"] = "other_mark"
            if c["outcome"] == "value_mismatch":
                c["size"] = size_class(float(c["value"]), float(c["ref_value"]))
            else:
                c["size"] = ""
            gk = "arc_m" if meta["table"] == "5.2" else "tower"
            covered_blocks.add((meta["table"], c["run"], c[gk]))
        allc += sc
        oc = Counter(c["outcome"] for c in sc)
        wrong = [c for c in sc if c["outcome"] not in ("match", "blank_vs_missing", "no_reference")]
        m = meta["mistral"]
        pages.append({
            "pdf_index": idx, "printed_page": idx - 13, "table": meta["table"], "run": meta.get("run"),
            "half": meta.get("half"), "cells": len(sc),
            "mistral_mapped": m["cells_mapped"], "mistral_problems": " | ".join(m["problems"]),
            "mistral_header_run": m.get("header_run", ""),
            "structure_anomalies": len(meta.get("structure_anomalies") or []),
            "match": oc["match"], "conflicts": len(wrong), "blank_vs_missing": oc["blank_vs_missing"],
            "no_reference": oc["no_reference"], "uncovered_ref_values": unc,
            "shift_candidates": sum(bool(c["shift_candidate"]) for c in sc),
            "flagged": sum(c["flagged"] for c in sc),
            "conflicts_flagged": sum(c["flagged"] for c in wrong),
        })
    # reference blocks with no extracted page
    missing_arc = sorted({(r, a) for (r, a) in arcs if ("5.2", r, str(a)) not in covered_blocks},
                         key=lambda x: (x[0], x[1]))
    missing_tower = sorted({r for (r, t) in towers if ("5.3", r, t) not in covered_blocks})

    keys = list(dict.fromkeys(k for c in allc for k in c))
    with (OUT / "cells.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(allc)
    conflicts = [c for c in allc if c["outcome"] not in ("match", "blank_vs_missing", "no_reference")]

    def mag(c):
        try:
            return abs(math.log10(float(c["value"]) / float(c["ref_value"])))
        except (ValueError, ZeroDivisionError, TypeError):
            return 9.0
    conflicts.sort(key=mag, reverse=True)
    ck = ["cell_id", "pdf_index", "printed_page", "table", "run", "arc_m", "post", "tower", "height_m",
          "raw_mistral", "conf_mistral", "raw_tesseract", "raw_easyocr", "consensus_token",
          "ref_value", "ref_kind", "outcome", "size", "flagged", "flag_notes"]
    with (OUT / "conflicts.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ck, extrasaction="ignore")
        w.writeheader()
        w.writerows(conflicts)
    with (OUT / "pages.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pages[0]))
        w.writeheader()
        w.writerows(pages)

    oc = Counter(c["outcome"] for c in allc)
    scored = [c for c in allc if c["outcome"] != "no_reference"]
    numeric = [c for c in scored if c["value_kind"] == "number" or c["ref_kind"] == "number"]
    sizes = Counter(c["size"] for c in conflicts if c["outcome"] == "value_mismatch")
    flagged = [c for c in scored if c["flagged"]]
    L = ["# Volume I: Mistral extraction vs reference", "",
         f"{len(pages)} pages, {len(allc)} cells ({len(scored)} with a reference key; "
         f"{len(numeric)} with a number on either side).", "",
         "| outcome | cells |", "|---|---|"]
    for k in ("match", "blank_vs_missing", "value_mismatch", "false_blank", "spurious_value",
              "other_mark", "unparseable", "no_reference"):
        L.append(f"| {k} | {oc.get(k, 0)} |")
    L += ["", f"Conflicts (excluding blank_vs_missing and no_reference): **{len(conflicts)}** = "
          f"{len(conflicts) / max(1, len(scored)):.2%} of keyed cells, "
          f"{len(conflicts) / max(1, len(numeric)):.2%} of cells with a number.",
          f"Of these, flagged by the pipeline: {sum(c['flagged'] for c in conflicts)}.",
          f"Pipeline flag rate: {len(flagged) / max(1, len(scored)):.2%} ({len(flagged)} cells).", "",
          "Value mismatches by size: " + ", ".join(f"{k}: {v}" for k, v in sizes.most_common()), ""]
    L += ["## Pages with structural trouble", "",
          "| PDF | printed | table | run | cells | Mistral mapped | conflicts | no-ref | shift? | problems |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    trouble = [p for p in pages if p["mistral_problems"] or p["mistral_mapped"] < p["cells"]
               or p["no_reference"] or p["shift_candidates"] or p["conflicts"] >= 5]
    for p in sorted(trouble, key=lambda p: -p["conflicts"]):
        L.append(f"| {p['pdf_index']} | {p['printed_page']} | {p['table']} | {p['run']} | {p['cells']} | "
                 f"{p['mistral_mapped']} | {p['conflicts']} | {p['no_reference']} | {p['shift_candidates']} | "
                 f"{p['mistral_problems'][:120]} |")
    L += ["", "## Coverage", "",
          f"Reference arc blocks (run, arc) with no extracted page: {len(missing_arc)}"
          + (": " + ", ".join(f"{r}/{a}" for r, a in missing_arc[:40]) if missing_arc else ""),
          f"Reference tower runs with no extracted column: {missing_tower or 'none'}",
          f"Reference values inside page scope but outside the extracted grid: "
          f"{sum(p['uncovered_ref_values'] for p in pages)}", "",
          "## Conflicts per page (top 20)", "", "| PDF | run | conflicts | flagged |", "|---|---|---|---|"]
    for p in sorted(pages, key=lambda p: -p["conflicts"])[:20]:
        L.append(f"| {p['pdf_index']} | {p['run']} | {p['conflicts']} | {p['conflicts_flagged']} |")
    by_run = defaultdict(int)
    for c in conflicts:
        by_run[c["run"]] += 1
    L += ["", "Conflicts per run (top 15): " + ", ".join(f"{r}: {n}" for r, n in
                                                         sorted(by_run.items(), key=lambda x: -x[1])[:15])]
    text = "\n".join(L) + "\n"
    (OUT / "summary.md").write_text(text)
    return text


if __name__ == "__main__":
    print(main())

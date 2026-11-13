"""Score extracted cells against the reference transcription.

    uv run python -m scoring.score [--set dev|holdout]

Aligns each extracted cell with the reference by run, arc (or tower) and
post bearing (or height); never adjudicates which side is right. Writes
output/scores/<set>/cells.csv, summary.json and summary.md.

Outcomes per cell:
  match              consensus equals the reference (number, blank or M)
  value_mismatch     both numbers, different
  false_blank        extracted blank, reference has a number
  spurious_value     extracted number, reference blank / no measurable conc.
  mark_mismatch      M (missing) on one side only
  unparseable        consensus token not interpretable
  no_reference       key not present in the reference (structural)
Value mismatches whose extracted number equals the reference at an adjacent
post / height of the same arc / tower are also marked `shift_candidate`
(possible structural misalignment rather than misreading). Reference cells in
a page's scope with no extracted cell are counted as `uncovered`.

Holdout pages may only be scored once the tag `extraction-frozen` exists and
the extraction code is unchanged since it.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .reference import HEIGHTS, REF, load_arcs, load_towers, post_bearing

REPO = Path(__file__).resolve().parents[1]
EXTRACTED = REPO / "output" / "extracted"
SCORES = REPO / "output" / "scores"
FLAG_COLS = ["flag_readers_disagree", "flag_low_confidence", "flag_token_unexpected",
             "flag_structural", "flag_implausible"]
READERS = ["tesseract", "easyocr", "claude"]
PAGE_KEY_NOTES = ("run label", "column run header")
FROZEN_TAG = "extraction-frozen"
FROZEN_PATHS = ["src/extract", "config/manual_keys.yaml", "config/pilot_pages.yaml"]


# ---------------------------------------------------------------- helpers
def b(x) -> bool:
    return str(x) == "True"


def ref_kind(v: str | None) -> tuple[str, float | None]:
    if v is None:
        return "blank", None
    f = float(v)
    if f == -9:
        return "missing", None
    if f == 0:
        return "blank", None
    return "number", f


def tok_kind(tok: str) -> tuple[str, float | None]:
    """Interpret a token the same way the pipeline does (no correction)."""
    from extract.pipeline import normalise, parse
    p = parse(normalise(tok))
    return p["kind"], p["value"]


def same(a: float, b_: float) -> bool:
    """Equal at the reference's 3 decimals (printed values have <= 3)."""
    return abs(a - b_) < 5e-4


def compare(kind, val, rkind, rval) -> str:
    if kind == "unparseable":
        return "unparseable"
    if kind == rkind == "number":
        return "match" if same(val, rval) else "value_mismatch"
    if kind == rkind:
        return "match"
    if "missing" in (kind, rkind):
        return "mark_mismatch"
    if kind == "blank":
        return "false_blank"
    return "spurious_value"


def cell_level_flag(r: dict) -> bool:
    """Flags raised by the cell itself, ignoring page-level key doubts that
    mark every cell of a page or column."""
    if any(b(r[k]) for k in FLAG_COLS if k != "flag_structural"):
        return True
    notes = [n for n in r["flag_notes"].split(" | ") if n and not n.startswith("implausible")
             and not n.startswith("low confidence") and not n.startswith("info:")]
    return any(not n.startswith(PAGE_KEY_NOTES) for n in notes)


# ---------------------------------------------------------------- guard
def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def holdout_guard() -> str:
    if git("rev-parse", "-q", "--verify", f"refs/tags/{FROZEN_TAG}").returncode != 0:
        raise SystemExit(f"refusing to score holdout: tag '{FROZEN_TAG}' does not exist")
    diff = git("diff", "--stat", FROZEN_TAG, "--", *FROZEN_PATHS).stdout.strip()
    if diff:
        raise SystemExit("refusing to score holdout: extraction code changed since "
                         f"'{FROZEN_TAG}':\n{diff}")
    return git("rev-parse", FROZEN_TAG).stdout.strip()


# ---------------------------------------------------------------- scoring
def score_page(rows: list[dict], table: str, arcs: dict, towers: dict) -> tuple[list[dict], int]:
    out = []
    ref_neigh = {}
    if table == "5.2":
        for r in rows:
            arc, post = int(r["arc_m"]), int(r["post"])
            ref_block = arcs.get((r["run"], arc))
            bearing = post_bearing(arc, post)
            r["ref_key"] = f"run {r['run']} arc {arc} bearing {bearing}"
            if ref_block is None:
                out.append({**r, "ref_value": "", "ref_kind": "", "outcome": "no_reference"})
                continue
            rv = ref_block.get(bearing)
            rk, rval = ref_kind(rv)
            ref_neigh[r["cell_id"]] = [ref_kind(ref_block.get(post_bearing(arc, p)))
                                       for p in (post - 1, post + 1)]
            out.append({**r, "ref_value": rv or "", "ref_kind": rk, "_rval": rval})
        # reference cells in this page's scope that no extracted cell covers
        covered = defaultdict(set)
        for r in rows:
            covered[(r["run"], int(r["arc_m"]))].add(post_bearing(int(r["arc_m"]), int(r["post"])))
        uncovered = 0
        for (run, arc), bs in covered.items():
            lo, hi = min(int(r["post"]) for r in rows if r["run"] == run and int(r["arc_m"]) == arc), \
                max(int(r["post"]) for r in rows if r["run"] == run and int(r["arc_m"]) == arc)
            scope = {post_bearing(arc, p) for p in range(lo, hi + 1)}
            for bear, v in arcs.get((run, arc), {}).items():
                if bear in scope and bear not in bs and ref_kind(v)[0] != "blank":
                    uncovered += 1
    else:
        uncovered = 0
        for r in rows:
            blk = towers.get((r["run"], r["tower"]))
            r["ref_key"] = f"run {r['run']} tower {r['tower']} height {r['height_m']}"
            if blk is None:
                out.append({**r, "ref_value": "", "ref_kind": "", "outcome": "no_reference"})
                continue
            rv = blk.get(r["height_m"])
            rk, rval = ref_kind(rv)
            i = HEIGHTS.index(r["height_m"])
            ref_neigh[r["cell_id"]] = [ref_kind(blk.get(HEIGHTS[j])) for j in (i - 1, i + 1)
                                       if 0 <= j < len(HEIGHTS)]
            out.append({**r, "ref_value": rv or "", "ref_kind": rk, "_rval": rval})
    for r in out:
        rval = r.pop("_rval", None)
        if r.get("outcome") == "no_reference":
            r["shift_candidate"] = False
        else:
            kind = r["value_kind"]
            val = float(r["value"]) if r["value"] not in ("", "None") else None
            r["outcome"] = compare(kind, val, r["ref_kind"], rval)
            r["shift_candidate"] = (r["outcome"] == "value_mismatch" and any(
                k == "number" and same(val, v) for k, v in ref_neigh.get(r["cell_id"], [])))
        for rd in READERS:
            if f"raw_{rd}" in r:
                if r.get("outcome") == "no_reference":
                    r[f"ok_{rd}"] = ""
                    continue
                k, v = tok_kind(r[f"raw_{rd}"])
                r[f"ok_{rd}"] = compare(k, v, r["ref_kind"], rval) == "match"
        r["flagged"] = b(r["flags_any"])
        r["flagged_cell_level"] = cell_level_flag(r)
    return out, uncovered


def rate(n, d):
    return None if not d else round(n / d, 4)


def summarise(cells: list[dict], uncovered: dict) -> dict:
    scored = [c for c in cells if c["outcome"] != "no_reference"]
    wrong = [c for c in scored if c["outcome"] != "match"]
    inked = [c for c in scored if c["value_kind"] != "blank" or c["ref_kind"] != "blank"]
    wrong_inked = [c for c in inked if c["outcome"] != "match"]
    flagged = [c for c in scored if c["flagged"]]
    s = {
        "cells_extracted": len(cells),
        "cells_scored": len(scored),
        "structural": {
            "no_reference": sum(c["outcome"] == "no_reference" for c in cells),
            "uncovered_reference_values": sum(uncovered.values()),
            "shift_candidates": sum(bool(c["shift_candidate"]) for c in scored),
        },
        "outcomes": dict(Counter(c["outcome"] for c in cells)),
        "disagreement_rate": rate(len(wrong), len(scored)),
        "disagreement_rate_nonblank": rate(len(wrong_inked), len(inked)),
        "nonblank_cells": len(inked),
        "flag_rate": rate(len(flagged), len(scored)),
        "self_flag_recall": rate(sum(c["flagged"] for c in wrong), len(wrong)),
        "self_flag_precision": rate(sum(c["outcome"] != "match" for c in flagged), len(flagged)),
        "cell_level": {
            "flag_rate": rate(sum(c["flagged_cell_level"] for c in scored), len(scored)),
            "recall": rate(sum(c["flagged_cell_level"] for c in wrong), len(wrong)),
        },
        "unflagged_errors": len([c for c in wrong if not c["flagged"]]),
        "recall_by_flag": {k: rate(sum(b(c[k]) for c in wrong), len(wrong)) for k in FLAG_COLS},
        "rate_by_flag": {k: rate(sum(b(c[k]) for c in scored), len(scored)) for k in FLAG_COLS},
        "reader_accuracy": {},
        "units": units_check(scored),
    }
    for rd in READERS:
        vals = [c[f"ok_{rd}"] for c in scored if f"ok_{rd}" in c and c[f"ok_{rd}"] != ""]
        if vals:
            s["reader_accuracy"][rd] = {
                "all": rate(sum(vals), len(vals)),
                "nonblank": rate(sum(c[f"ok_{rd}"] for c in inked), len(inked))}
    return s


def units_check(scored: list[dict]) -> dict:
    pairs = [(float(c["value"]), float(c["ref_value"])) for c in scored
             if c["value_kind"] == "number" and c["ref_kind"] == "number"]
    if not pairs:
        return {"pairs": 0}
    ratios = [math.log10(a / r) for a, r in pairs if a > 0 and r > 0]
    med = statistics.median(ratios)
    return {"pairs": len(pairs), "median_log10_ratio": round(med, 4),
            "median_ratio": round(10 ** med, 4),
            "printed_units": "mg m^-3 (Tables 5.2, 5.3 column headings)",
            "reference_units": "PGVertConc.txt states mg/m^3; PGARCS.txt header multiplier 1.0 "
                               "(format doc: converts user units to ug/m^3)",
            "verdict": "same scale" if abs(med) < 0.05 else "SCALE DIFFERS - check units"}


# ---------------------------------------------------------------- report
def write(out_dir: Path, cells: list[dict], summary: dict, by_page: dict, meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for c in cells for k in c))
    with (out_dir / "cells.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(cells)
    (out_dir / "summary.json").write_text(json.dumps(
        {"meta": meta, "overall": summary, "by_page": by_page}, indent=1) + "\n")
    L = [f"# Scores: {meta['set']} pages", "",
         f"Scored {meta['scored_at']} at commit `{meta['commit']}`"
         + (f", frozen tag `{meta['frozen']}`" if meta.get("frozen") else "") + ".", "",
         "| page | table | cells | disagreement | (non-blank) | flag rate | recall | "
         "cell-level flag rate | cell-level recall | unflagged errors | structural |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p, s in list(by_page.items()) + [("all", summary)]:
        st = s["structural"]
        L.append(f"| {p} | {s.get('table', '')} | {s['cells_scored']} | {s['disagreement_rate']} | "
                 f"{s['disagreement_rate_nonblank']} | {s['flag_rate']} | {s['self_flag_recall']} | "
                 f"{s['cell_level']['flag_rate']} | {s['cell_level']['recall']} | "
                 f"{s['unflagged_errors']} | no-ref {st['no_reference']}, uncovered "
                 f"{st['uncovered_reference_values']}, shift? {st['shift_candidates']} |")
    L += ["", "Outcomes: " + json.dumps(summary["outcomes"]),
          "", "Reader accuracy: " + json.dumps(summary["reader_accuracy"]),
          "", "Units: " + json.dumps(summary["units"]), ""]
    (out_dir / "summary.md").write_text("\n".join(L))


def main(which: str = "dev", extracted: Path = EXTRACTED, label: str | None = None) -> dict:
    sel = yaml.safe_load((REPO / "config" / "pilot_pages.yaml").read_text())
    frozen = holdout_guard() if which == "holdout" else None
    if not (REF / "PGARCS.txt").exists():
        raise SystemExit("reference not fetched: run scripts/fetch_reference.py")
    arcs, towers = load_arcs(), load_towers()
    cells, uncovered, by_page = [], {}, {}
    for e in sel[which]:
        idx = e["pdf_index"]
        path = extracted / f"p{idx}.csv"
        if not path.exists():
            raise SystemExit(f"missing {path}; run the pipeline first")
        rows = list(csv.DictReader(path.open()))
        sc, unc = score_page(rows, e["table"], arcs, towers)
        for c in sc:
            c["subset"] = which
        cells += sc
        uncovered[idx] = unc
        by_page[idx] = {"table": e["table"], "stratum": e["stratum"], **summarise(sc, {idx: unc})}
    summary = summarise(cells, uncovered)
    meta = {"set": which, "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "commit": git("rev-parse", "--short", "HEAD").stdout.strip(),
            "dirty_extraction_code": bool(git("status", "--porcelain", "--", *FROZEN_PATHS).stdout.strip()),
            "frozen": frozen,
            "reference_sha256": json.loads((REPO / "scoring" / "reference_checksums.json").read_text())}
    out_dir = SCORES / (label or which)
    if which == "holdout" and (out_dir / "summary.json").exists():
        prev = json.loads((out_dir / "summary.json").read_text())["meta"]
        meta["previous_holdout_scoring"] = prev.get("scored_at")
    write(out_dir, cells, summary, by_page, meta)
    print((out_dir / "summary.md").read_text())
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="dev", choices=["dev", "holdout"])
    ap.add_argument("--extracted", default=str(EXTRACTED))
    ap.add_argument("--label", default=None, help="output folder name under output/scores")
    a = ap.parse_args()
    main(a.set, Path(a.extracted), a.label)

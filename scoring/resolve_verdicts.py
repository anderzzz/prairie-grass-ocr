"""Turn the owner's review verdicts into explicit printed values.

    uv run python -m scoring.resolve_verdicts

Input: review/volume1/verdicts.csv, exported from the review pack. The owner
confirmed (2026-11-15) what the buttons meant:
  ours       the Sonnet reading shown in the pack is what is printed
  reference  the reference value is what is printed
  other      neither; the printed value is typed in (value_as_printed, or the
             note field, which is where the owner typed it). In all four
             cases the typed value equals Mistral's reading.
Cells the owner left undecided count as "ours" (owner's instruction). In groups
A-C Sonnet's reading equals Mistral's in every such cell, which is checked
here.

Output: config/review/volume1_verdicts.csv. Every row carries the printed value
itself, recorded as the owner's reading, so the dataset build
(src/dataset) never needs the reference. This module lives in scoring/
because resolving "reference" verdicts reads the reference value once.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from extract.pipeline import normalise, parse  # noqa: E402

from .score import SCORES  # noqa: E402
from .triage import group_of, page_rows  # noqa: E402

VERDICTS = REPO / "review" / "volume1" / "verdicts.csv"
SONNET = REPO / "output" / "volume1" / "triage" / "sonnet_reads.csv"
OUT = REPO / "config" / "review" / "volume1_verdicts.csv"
REVIEWER, DATE = "project owner", "2026-11-15"


def printed_form(v: float) -> str:
    """The table's own convention: three significant figures."""
    if v < 1:
        return f"{v:.3f}"
    if v < 10:
        return f"{v:.2f}"
    if v < 100:
        return f"{v:.1f}"
    return f"{v:.0f}"


def main() -> None:
    verd = {r["cell_id"]: r for r in csv.DictReader(VERDICTS.open()) if r["cell_id"]}
    son = {r["cell_id"]: normalise(r["text"]) for r in csv.DictReader(SONNET.open())}
    conflicts = list(csv.DictReader((SCORES / "volume1" / "conflicts.csv").open()))
    rows, pages, problems = [], {}, []
    for c in conflicts:
        cid = c["cell_id"]
        idx = int(c["pdf_index"])
        pr = pages.setdefault(idx, page_rows(idx))[cid]
        mi = normalise(pr["raw_mistral"] or "")
        v = verd.get(cid)
        given = v["verdict"] if v else "ours"
        decided = "explicit" if v else "default (undecided = ours)"
        if given == "ours":
            tok, basis = son[cid], "Sonnet's reading confirmed by the owner"
            if not v and tok != mi:
                problems.append(f"{cid}: undecided but Sonnet {tok!r} != Mistral {mi!r}")
        elif given == "reference":
            if c["ref_kind"] != "number":
                problems.append(f"{cid}: verdict reference but reference is {c['ref_kind']}")
                continue
            tok, basis = printed_form(float(c["ref_value"])), "owner reading (agrees with the reference value)"
        elif given == "other":
            tok = normalise(v["value_as_printed"] or v["note"])
            basis = "owner reading (typed)"
        else:
            problems.append(f"{cid}: unknown verdict {given!r}")
            continue
        p = parse(tok)
        if p["kind"] not in ("number", "blank", "missing"):
            problems.append(f"{cid}: resolved token {tok!r} does not parse")
        rows.append({"cell_id": cid, "pdf_index": idx, "group": group_of(c, pr),
                     "token_as_printed": tok, "basis": basis, "verdict_given": given,
                     "decided": decided, "mistral_token": mi, "sonnet_token": son[cid],
                     "mistral_right": tok == mi, "sonnet_right": tok == son[cid],
                     "reviewer": REVIEWER, "date": DATE})
    if problems:
        raise SystemExit("not written:\n" + "\n".join(problems))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}: {len(rows)} cells")


if __name__ == "__main__":
    main()

"""Dataset for the Volume I supplementary tables.

    cd src && uv run python -m volume1s.dataset [--resolve yyyy-mm-dd]

--resolve converts the verdicts exported from the review pack
(review/volume1s/verdicts.csv) into config/review/volume1s_verdicts.csv, which
is the only owner input the build reads.

Output, next to arcs.csv / towers.csv:
  output/volume1/dataset/source_strength.csv      Table 5.1
  output/volume1/dataset/evaporation_correction.csv  Table 5.4
  output/volume1/dataset/slow_response_wind.csv   Table 6.1
  output/volume1/dataset/run_remarks.csv          remarks with Table 5.2 and the Table 6.1 legend

Every table cell was read by Mistral and, independently, by Sonnet.
quality: two_readers (both agree, no check fails), printed_inconsistent
(both agree, a check fails, the owner confirmed the print), owner (the
owner read it), pending (readers differ or a check fails, not yet reviewed).
suspect / suspect_alternative / suspect_note: the owner suspects an error in
the ORIGINAL report (config/suspect_values.yaml, section volume1s); the
printed value is kept.
"""
from __future__ import annotations

import argparse
import csv
import json

import yaml

from extract.pdfio import REPO

from .checks import run_on
from .parse import parse_all
from .second_read import SECOND
from volume2.common import parse as parse_token

REVIEW = REPO / "review" / "volume1s"
VERDICTS = REPO / "config" / "review" / "volume1s_verdicts.csv"
SUSPECTS = REPO / "config" / "suspect_values.yaml"
DATASET = REPO / "output" / "volume1" / "dataset"
FILES = {"5.1": "source_strength.csv", "5.4": "evaporation_correction.csv", "6.1": "slow_response_wind.csv"}
LEAD = {"5.1": ["run", "quantity", "unit", "value", "token", "status"],
        "5.4": ["run", "arc_m", "quantity", "value", "token", "status"],
        "6.1": ["release", "date", "date_token", "time_cst", "quantity", "location", "period_min", "unit",
                "value", "token", "status", "estimated"]}
TAIL = ["quality", "value_source", "reviewed", "check_failures", "review_note",
        "suspect", "suspect_alternative", "suspect_note", "conf", "flags",
        "table", "pdf_index", "printed_page", "cell_id"]
REVIEWER = "project owner"


def resolve(date: str) -> None:
    items = {it["cell_id"]: it for it in json.loads((REVIEW / "items.json").read_text())}
    out = []
    for v in csv.DictReader((REVIEW / "verdicts.csv").open()):
        it, verdict, typed = items[v["cell_id"]], v["verdict"].strip(), v["typed"].strip()
        if not verdict:
            continue
        if it["group"] == "C":
            out.append({"cell_id": it["cell_id"], "group": "C", "token_as_printed": it["mistral"],
                        "basis": "owner: printed as such" if verdict == "printed" else f"owner note: {typed}",
                        "verdict": verdict, "reviewer": REVIEWER, "date": date})
            continue
        tok = {"mistral": it["mistral"], "sonnet": it["sonnet"]}.get(verdict, typed)
        if verdict == "other" and not typed:
            raise SystemExit(f"{it['cell_id']}: 'other' without a typed value")
        basis = {"mistral": "owner confirmed Mistral's reading", "sonnet": "owner confirmed Sonnet's reading",
                 "other": "owner reading (typed)"}[verdict]
        out.append({"cell_id": it["cell_id"], "group": "A", "token_as_printed": tok, "basis": basis,
                    "verdict": verdict, "reviewer": REVIEWER, "date": date})
    VERDICTS.parent.mkdir(parents=True, exist_ok=True)
    with VERDICTS.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cell_id", "group", "token_as_printed", "basis", "verdict",
                                          "reviewer", "date"])
        w.writeheader()
        w.writerows(out)
    print(f"wrote {VERDICTS}: {len(out)} rows")


def build() -> None:
    T = parse_all()
    cells = {c["cell_id"]: c for t in FILES for c in T[t]}
    reads = {r["cell_id"]: r for r in csv.DictReader((SECOND / "reads.csv").open())}
    owner = {v["cell_id"]: v for v in csv.DictReader(VERDICTS.open())} if VERDICTS.exists() else {}
    for cid, c in cells.items():
        r = reads[cid]
        c["reviewed"], c["review_note"] = False, ""
        if r["agree"] == "True":
            c["value_source"], c["quality"] = "mistral, confirmed by sonnet", "two_readers"
        else:
            c["value_source"] = f"mistral {r['mistral']!r}, sonnet {r['sonnet']!r}: readers differ"
            c["quality"] = "pending"
        v = owner.get(cid)
        if v and v["group"] == "A":
            p = parse_token(v["token_as_printed"])
            c.update(token=p["token"], value=p["value"], estimated=p["estimated"] or p["footnote"],
                     status="value" if p["kind"] == "number" else "missing" if p["kind"] == "blank" else c["status"],
                     value_source=f"{v['basis']} ({v['reviewer']}, {v['date']})", reviewed=True, quality="owner")
    fails: dict[str, set] = {}
    for f in run_on(T):
        if f["cell_id"] in cells:
            fails.setdefault(f["cell_id"], set()).add(f["check"])
    for cid, c in cells.items():
        c["check_failures"] = ";".join(sorted(fails.get(cid, ())))
        v = owner.get(cid)
        if v and v["group"] == "C":
            c["reviewed"], c["review_note"] = True, f"{v['basis']} ({v['reviewer']}, {v['date']})"
            c["quality"] = "printed_inconsistent" if v["verdict"] == "printed" else "doubtful"
        elif c["check_failures"] and c["quality"] == "two_readers":
            c["quality"] = "pending"
    # Suspected errors in the original report: the cell is marked, never changed.
    sus = (yaml.safe_load(SUSPECTS.read_text()) or {}).get("volume1s", [])
    for c in cells.values():
        c.update(suspect=False, suspect_alternative="", suspect_note="")
    for s in sus:
        c = cells.get(s["cell_id"])
        if c is None:
            raise SystemExit(f"suspect list: unknown cell {s['cell_id']}")
        if c["token"] != s["printed"]:
            raise SystemExit(f"suspect list: {s['cell_id']} printed {s['printed']!r}, dataset has {c['token']!r}")
        c.update(suspect=True, suspect_alternative=s["suspect_alternative"],
                 suspect_note=" ".join(s["basis"].split()) + f" ({s['reviewer']}, {s['date']})")
    DATASET.mkdir(parents=True, exist_ok=True)
    for t, name in FILES.items():
        rows = [r for r in T[t] if not (t == "6.1" and r["quantity"] == "key:release")]
        cols = LEAD[t] + TAIL
        with (DATASET / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    with (DATASET / "run_remarks.csv").open("w", newline="") as f:
        cols = ["run", "table", "remark", "applies_to", "pdf_index", "printed_page", "cell_id"]
        w = csv.DictWriter(f, fieldnames=cols + ["value_source"], extrasaction="ignore")
        w.writeheader()
        for r in T["remarks"]:
            w.writerow(r | {"value_source": "mistral (prose; checked against the page image by Claude, 2026-11-16)"})
    from collections import Counter
    print("quality:", dict(Counter(c["quality"] for c in cells.values())))
    print("written:", ", ".join(list(FILES.values()) + ["run_remarks.csv"]), "->", DATASET)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolve", metavar="DATE")
    a = ap.parse_args()
    if a.resolve:
        resolve(a.resolve)
    build()


if __name__ == "__main__":
    main()

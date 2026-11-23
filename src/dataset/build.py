"""Build the reviewed Volume I dataset from the scan readings.

    uv run python -m dataset.build        (from src/, or via `make dataset`)

Inputs, and nothing else:
  output/volume1/extracted/p<idx>.csv   the pipeline's readings (Mistral token
                                        per cell, flags, keys)
  config/review/volume1_verdicts.csv    the owner's verdicts, as printed
                                        values (resolved once, at review time)
  config/suspect_values.yaml            cells the owner suspects are wrong in
                                        the original (marked, never changed)
The reference transcription is never read (tests/test_isolation.py).

Outputs (output/volume1/dataset/):
  arcs.csv    Table 5.2: run, arc_m, post, bearing_deg, ...
  towers.csv  Table 5.3: run, tower, height_m, ...
Common columns:
  status            value | not_measurable | missing | unread
  concentration_mg_m3  only when status = value; never filled otherwise
  estimated         printed with an asterisk ("estimated value")
  token             the printed token the value comes from
  value_source      mistral | owner review (<basis>)
  reviewed          the cell went through owner review
  flagged, flag_notes  the pipeline's flags (not cleared by review)
  suspect, suspect_alternative, suspect_note
                    owner suspects an error in the ORIGINAL report
                    (config/suspect_values.yaml); the printed value is kept,
                    the alternative is only carried alongside
  pdf_index, printed_page, cell_id  provenance

Meaning of a blank (Vol. I printed pp. 79, 193): "the letter "M" indicates
missing data and the blank spaces denote no measurable concentration".
Bearing (printed p. 79): Post 1 due west (270 deg); 2 deg spacing on the
50-400 m arcs, 1 deg at 800 m.
"""
from __future__ import annotations

import csv
from pathlib import Path

import yaml

from extract.pipeline import STATUS, normalise, parse

REPO = Path(__file__).resolve().parents[2]
VOL = REPO / "output" / "volume1"
VERDICTS = REPO / "config" / "review" / "volume1_verdicts.csv"
SUSPECTS = REPO / "config" / "suspect_values.yaml"
ROUNDS = [REPO / "config" / "review" / f"round{n}_verdicts.csv" for n in (2, 3)]   # src/publish/round2.py
OUT = VOL / "dataset"

COMMON = ["status", "concentration_mg_m3", "estimated", "token", "value_source", "reviewed",
          "flagged", "flag_notes", "suspect", "suspect_alternative", "suspect_note", "key_source", "pdf_index", "printed_page", "cell_id"]
ARC = ["run", "arc_m", "post", "bearing_deg"] + COMMON
TOWER = ["run", "tower", "height_m"] + COMMON


def bearing(arc_m: int, post: int) -> int:
    return (270 + (1 if arc_m == 800 else 2) * (post - 1)) % 360


def run_order(run: str) -> tuple:
    n = int("".join(ch for ch in run if ch.isdigit()) or 0)
    return (n, 0 if run.endswith("S") else 1)


def main() -> dict:
    verd = {r["cell_id"]: r for r in csv.DictReader(VERDICTS.open())} if VERDICTS.exists() else {}
    for path in (p for p in ROUNDS if p.exists()):     # later owner reviews: outliers confirmed as printed
        for r in csv.DictReader(path.open()):
            if r["file"].startswith("volume1/"):
                verd[r["cell_id"]] = {**r, "basis": f"{r['basis']}, {r['reviewer']}, {r['date']}"}
    sus = {s["cell_id"]: s for s in (yaml.safe_load(SUSPECTS.read_text()) or {}).get("volume1", [])} \
        if SUSPECTS.exists() else {}
    arcs, towers, used = [], [], set()
    for path in sorted((VOL / "extracted").glob("p*.csv"), key=lambda p: int(p.stem[1:])):
        for r in csv.DictReader(path.open()):
            if not r["run"] or r["run"] == "None":
                continue  # unused column (blank header) or unkeyed page
            v = verd.get(r["cell_id"])
            if v:
                tok, src = v["token_as_printed"], f"owner review ({v['basis']})"
                used.add(r["cell_id"])
            else:
                tok, src = normalise(r["consensus_token"] or ""), r["value_source"]
            p = parse(tok)
            status = STATUS.get(p["kind"], "unread")
            rec = {"status": status,
                   "concentration_mg_m3": p["value"] if status == "value" else "",
                   "estimated": p["estimated"], "token": tok, "value_source": src,
                   "reviewed": bool(v), "flagged": r["flags_any"], "flag_notes": r["flag_notes"],
                   "key_source": r["key_source"], "pdf_index": r["pdf_index"],
                   "printed_page": r["printed_page"], "cell_id": r["cell_id"], "run": r["run"]}
            s = sus.get(r["cell_id"])
            if s and s["printed"] != tok:
                raise SystemExit(f"suspect list: {r['cell_id']} printed {s['printed']!r}, dataset has {tok!r}")
            rec.update(suspect=bool(s), suspect_alternative=s["suspect_alternative"] if s else "",
                       suspect_note=" ".join(s["basis"].split()) + f" ({s['reviewer']}, {s['date']})" if s else "")
            if s:
                used.add(("suspect", r["cell_id"]))
            if r["table"] == "5.2":
                a, post = int(r["arc_m"]), int(r["post"])
                rec.update(arc_m=a, post=post, bearing_deg=bearing(a, post))
                arcs.append(rec)
            else:
                rec.update(tower=int(r["tower"]), height_m=float(r["height_m"]))
                towers.append(rec)
    missing = set(verd) - used
    missing |= {c for c in sus if ("suspect", c) not in used}
    if missing:
        raise SystemExit(f"verdicts for cells not in the extraction: {sorted(missing)[:5]}")
    arcs.sort(key=lambda x: (run_order(x["run"]), x["arc_m"], x["post"]))
    towers.sort(key=lambda x: (run_order(x["run"]), x["tower"], -x["height_m"]))
    for name, rows, cols in (("arcs", arcs, ARC), ("towers", towers, TOWER)):
        keys = [tuple(r[c] for c in cols[:3]) for r in rows]
        dup = len(keys) - len(set(keys))
        if dup:
            raise SystemExit(f"{name}: {dup} duplicate keys")
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / f"{name}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    stats = {"arcs": len(arcs), "towers": len(towers), "reviewed": len(used & set(verd)), "suspect": len(sus)}
    print(stats)
    return stats


if __name__ == "__main__":
    main()

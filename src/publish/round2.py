"""Owner review rounds 2 and 3: exported verdicts -> config/review/round<N>_verdicts.csv

    cd src && uv run python -m publish.round2 <verdicts.csv> <DATE> [ROUND]     (ROUND: 2 or 3, default 2)

Reads the export of review/round<N>/index.html (cell_id, file, group, verdict,
typed, note) and review/round<N>/items.json, and writes one row per applied
verdict. Both dataset builds read the round files after their earlier review
files, in round order, so a later row overrides earlier decisions for its cell:

  verdict    token_as_printed       effect in the dataset
  mistral    Mistral's reading      quality = owner
  sonnet     Sonnet's reading       quality = owner
  misread    the owner's reading    quality = owner (outlier was a misreading)
  printed    the current token      reviewed; quality = owner, or printed_inconsistent
                                    if the cell still fails a consistency check
  misread    (round 3, Q items: "the decimal point is printed") the token with its
             leading decimal point, e.g. 0183 -> .0183; quality = owner

Not applied (the cell stays as it is):
  - cant_tell and blank verdicts;
  - round 2 only, HOLD: verdicts given on a review image that boxed or showed the
    wrong cell (the column/row locator in volume2.adjudicate.cell_images misplaced it);
  - round 2 only, ASK: verdicts awaiting a question to the owner.
Both went to round 3 (src/publish/review_round3.py).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROUNDS = [REPO / "config" / "review" / f"round{n}_verdicts.csv" for n in (2, 3)]   # applied in this order
FIELDS = ["cell_id", "file", "group", "token_as_printed", "basis", "verdict", "reviewer", "date"]

_BOX = "review image boxed the neighbouring column; the typed value is that cell's"
HOLD = {
    "T8.2|p94|1956-08-08|0005|temperature|temperature|-0.06": _BOX,
    "T8.2|p94|1956-08-08|0005|temperature|temperature|-0.12": _BOX,
    "T8.2|p96|1956-08-08|1205|temperature|temperature|16.0": _BOX,
    "T8.2|p96|1956-08-08|1305|temperature|temperature|16.0": _BOX,
    "T8.2|p96|1956-08-08|1205|temperature|temperature|1.0": _BOX,
    "T8.2|p96|1956-08-08|1305|temperature|temperature|1.0": _BOX,
    "T8.2|p100|1956-08-09|0905|soil_temperature_change|soil_temperature_change|-1.0":
        "review image showed the -0.50 m row; the typed value is that row's",
}
ASK = {
    "T8.1|p66|16|1956-07-23|1005|radiation|insolation":
        "print shows 0183 without a decimal point: misreading, or printed typo (suspected original error)?",
    "T8.2|p93|1956-08-07|1105|radiation|net_radiation":
        "print shows 0130 without a decimal point: misreading, or printed typo (suspected original error)?",
}


def main(path: str, date: str, rnd: str = "2") -> None:
    items = {i["cell_id"]: i for i in json.loads((REPO / "review" / f"round{rnd}" / "items.json").read_text())}
    out_path = REPO / "config" / "review" / f"round{rnd}_verdicts.csv"
    hold, ask = (HOLD, ASK) if rnd == "2" else ({}, {})
    out, skipped = [], {"cant_tell": 0, "blank": 0, "hold": 0, "ask": 0}
    for v in csv.DictReader(open(path, newline="")):
        it = items[v["cell_id"]]
        verdict, typed = v["verdict"].strip(), v["typed"].strip()
        if v["cell_id"] in hold:
            skipped["hold"] += 1
            continue
        if v["cell_id"] in ask:
            skipped["ask"] += 1
            continue
        if verdict in ("", "cant_tell"):
            skipped["cant_tell" if verdict else "blank"] += 1
            continue
        if verdict in ("mistral", "sonnet"):
            tok, basis = it[verdict], f"owner confirmed {verdict.capitalize()}'s reading (round {rnd})"
        elif verdict == "printed_real":
            why = it.get("why", "") if rnd == "2" else f"round {rnd}"
            tok, basis, verdict = it["token"], f"owner: printed as such (outlier review: {why})", "printed"
        elif verdict == "misread" and v["group"] == "Q" and not typed:
            if not re.fullmatch(r"-?\d{4}", it["token"]):
                raise SystemExit(f"{v['cell_id']}: no decimal point to restore in {it['token']!r}")
            tok = it["token"].replace("-", "-.") if it["token"].startswith("-") else "." + it["token"]
            basis = (f"owner: the decimal point is printed (faint); {it['token']!r} was a misreading "
                     f"(round {rnd})")
        elif verdict == "misread":
            if not typed:
                raise SystemExit(f"{v['cell_id']}: misread without a typed value")
            tok, basis = typed, f"owner reading; outlier was a misreading of {it['token']!r} (round {rnd})"
        else:
            raise SystemExit(f"{v['cell_id']}: verdict {verdict!r} not handled")
        out.append({"cell_id": v["cell_id"], "file": v["file"], "group": v["group"], "token_as_printed": tok,
                    "basis": basis, "verdict": verdict, "reviewer": "project owner", "date": date})
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {out_path}: {len(out)} rows; not applied: {skipped}")


if __name__ == "__main__":
    main(*sys.argv[1:4])

"""Volume II dataset: extraction + second reading + owner verdicts.

    cd src && uv run python -m volume2.dataset [--resolve]

--resolve turns review/volume2/verdicts.csv (exported from the review pack)
into config/review/volume2_verdicts.csv: one row per cell with the printed
token the owner confirmed and its basis. The dataset build reads only that
file, the parsed tables and the second-reading results.

Output: output/volume2/dataset/table_<id>.csv. Columns added to the parsed
cells: value_source (how the printed token was established), reviewed,
check_failures (checks the final token still fails: expected for printed
inconsistencies), and pending (a decision is still open).
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict

import yaml

from .checks import run_on
from .common import parse
from .pages import OUT
from .run import KEYS, LEAD, parse_all
from .second_read import SECOND

ROOT = OUT.parents[1]
VERDICTS_IN = ROOT / "review" / "volume2" / "verdicts.csv"
ITEMS = ROOT / "review" / "volume2" / "items.json"
VERDICTS = ROOT / "config" / "review" / "volume2_verdicts.csv"
DATASET = OUT / "dataset"
REVIEWER, DATE = "project owner", None


def resolve(date: str) -> None:
    items = {it["cell_id"]: it for it in json.loads(ITEMS.read_text())}
    out, problems = [], []
    for v in csv.DictReader(VERDICTS_IN.open()):
        it = items.get(v["cell_id"])
        if it is None:
            problems.append(f"verdict for unknown item {v['cell_id']}")
            continue
        verdict, typed = v["verdict"].strip(), v["typed"].strip()
        if not verdict and it["group"] == "A":
            # The owner left this one open ("choose whichever"). A fixed rule picks between the two
            # readings, never a third value: the reading under which the failed checks pass, if exactly
            # one does and it is well formed; otherwise Mistral's, marked doubtful.
            ok = {r: it[f"pass_{r}"] and parse(it[r])["kind"] != "unread" for r in ("mistral", "sonnet")}
            pick = "sonnet" if ok["sonnet"] and not ok["mistral"] else "mistral"
            sure = ok[pick] and not (ok["mistral"] and ok["sonnet"])
            out.append({"cell_id": it["cell_id"], "group": "A", "token_as_printed": it[pick],
                        "basis": (f"not ruled by owner; rule: {pick} reading, under which the checks pass"
                                  if sure else
                                  f"not ruled by owner; neither reading passes the checks ({it['mistral']!r} "
                                  f"vs {it['sonnet']!r}); Mistral kept, doubtful"),
                        "verdict": "rule" if sure else "rule_doubtful", "reviewer": "rule", "date": date})
            continue
        if not verdict:
            continue                                     # undecided B item: stays as read, flagged
        if it["group"] == "C":
            out.append({"cell_id": ";".join(it["cells"]), "group": "C", "token_as_printed": "",
                        "basis": "owner: printed as such" if verdict != "flag" else f"owner flag: {typed}",
                        "verdict": verdict or "printed", "reviewer": REVIEWER, "date": date})
            continue
        if it["cell_id"].startswith("precip:"):
            toks = ["--"] * len(it["cells"]) if verdict == "all_dashes" else typed.split()
            if len(toks) != len(it["cells"]):
                problems.append(f"{it['cell_id']}: {len(toks)} tokens for {len(it['cells'])} columns")
                continue
            for cid, t in zip(it["cells"], toks):
                out.append({"cell_id": cid, "group": "B", "token_as_printed": t,
                            "basis": "owner reading", "verdict": verdict, "reviewer": REVIEWER, "date": date})
            continue
        if it["cell_id"].startswith("page:"):
            out.append({"cell_id": it["cell_id"], "group": "B", "token_as_printed": "",
                        "basis": f"owner note: {typed or verdict}", "verdict": verdict,
                        "reviewer": REVIEWER, "date": date})
            continue
        tok = {"mistral": it["mistral"], "sonnet": it["sonnet"]}.get(verdict, typed)
        if verdict == "other" and typed.lower() in ("unreadable", "illegible"):
            out.append({"cell_id": it["cell_id"], "group": it["group"], "token_as_printed": "",
                        "basis": "owner: illegible in the print", "verdict": "illegible",
                        "reviewer": REVIEWER, "date": date})
            continue
        if verdict == "other" and not typed:
            problems.append(f"{it['cell_id']}: 'other' without a typed value")
            continue
        basis = {"mistral": "owner confirmed Mistral's reading", "sonnet": "owner confirmed Sonnet's reading",
                 "other": "owner reading (typed)"}[verdict]
        out.append({"cell_id": it["cell_id"], "group": it["group"], "token_as_printed": tok, "basis": basis,
                    "verdict": verdict, "reviewer": REVIEWER, "date": date})
    if problems:
        raise SystemExit("not written:\n" + "\n".join(problems))
    VERDICTS.parent.mkdir(parents=True, exist_ok=True)
    with VERDICTS.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cell_id", "group", "token_as_printed", "basis", "verdict",
                                          "reviewer", "date"])
        w.writeheader()
        w.writerows(out)
    print(f"wrote {VERDICTS}: {len(out)} rows")


def excluded() -> set[str]:
    """Tables the owner left out of the dataset (config/volume2_keys.yaml, excluded_tables)."""
    return {e["table"] for e in yaml.safe_load(KEYS.read_text()).get("excluded_tables", [])}


def build() -> None:
    T, _ = parse_all()
    for t in excluded():
        T.pop(t, None)
        (DATASET / f"table_{t}.csv").unlink(missing_ok=True)
    cells = {c["cell_id"]: c for rows in T.values() for c in rows}
    for c in cells.values():
        c["value_source"], c["reviewed"], c["pending"] = "mistral", False, False
    reads = list(csv.DictReader((SECOND / "reads.csv").open())) if (SECOND / "reads.csv").exists() else []
    for r in reads:
        c = cells.get(r["cell_id"])
        if c is None:
            continue
        if r["agree"] == "True":
            c["value_source"] = "mistral, confirmed by sonnet"
        else:
            c["pending"] = True                       # until the owner decides
    for c in cells.values():
        if c["status"] == "unread":
            c["pending"] = True
    owner = list(csv.DictReader(VERDICTS.open())) if VERDICTS.exists() else []
    for v in owner:
        if v["group"] == "C":
            for cid in v["cell_id"].split(";"):
                if cid in cells:
                    cells[cid]["reviewed"] = True
                    cells[cid]["review_note"] = v["basis"]
            continue
        c = cells.get(v["cell_id"])
        if c is None:
            if not v["cell_id"].startswith("page:"):
                raise SystemExit(f"verdict for unknown cell {v['cell_id']}")
            continue
        if v["verdict"] == "illegible":
            c.update(token=c["token"], value=None, kind="unread", status="illegible", reviewed=True,
                     pending=False, quality="illegible",
                     value_source=f"{v['basis']} ({v['reviewer']}, {v['date']}); OCR read {c['token']!r}")
            continue
        p = parse(v["token_as_printed"])
        rule = v["verdict"].startswith("rule")
        c.update(token=p["token"], value=p["value"], kind=p["kind"], estimated=p["estimated"],
                 footnote=p["footnote"], status={"number": "value", "above": "value", "range": "value",
                                                 "blank": "not_printed", "missing": "missing",
                                                 "text": "text"}.get(p["kind"], "unread"),
                 value_source=f"{v['basis']} ({v['reviewer']}, {v['date']})", reviewed=not rule, pending=False,
                 quality={"rule": "rule", "rule_doubtful": "doubtful"}.get(v["verdict"], "owner"))
    fails = defaultdict(set)
    for r in run_on(T):
        if r["cell_id"]:
            fails[r["cell_id"]].add(r["check"])
    for c in cells.values():
        c["check_failures"] = ";".join(sorted(fails.get(c["cell_id"], ())))
        if "quality" not in c:
            c["quality"] = ("unread" if c["status"] == "unread" else
                            "doubtful" if c["pending"] else
                            "printed_inconsistent" if c["check_failures"] and c.get("review_note") else
                            "two_readers" if c["value_source"].startswith("mistral, confirmed") else
                            "single_reader")
        if c["pending"] and c["quality"] == "doubtful":
            c["pending"] = False                     # nothing left for the owner to decide; flagged instead
    DATASET.mkdir(parents=True, exist_ok=True)
    extra = ["quality", "value_source", "reviewed", "pending", "check_failures", "review_note"]
    for t, rows in T.items():
        cols = ["cell_id"] + [k for k in LEAD + extra + sorted({k for r in rows for k in r} - set(LEAD) - set(extra))
                              if any(k in r for r in rows) and k != "cell_id"]
        cols = [c for c in cols if not c.startswith("grid_")] + ["grid_ti", "grid_row"]
        with (DATASET / f"table_{t}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[c for c in cols if any(c in r for r in rows)],
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    n = len(cells)
    print(f"dataset: {n} cells in {len(T)} tables -> {DATASET}; "
          f"confirmed by two readers {sum(c['value_source'].startswith('mistral, confirmed') for c in cells.values())}, "
          f"owner-reviewed {sum(c['reviewed'] for c in cells.values())}, "
          f"pending {sum(c['pending'] for c in cells.values())}")
    print("quality:", dict(Counter(c["quality"] for c in cells.values()).most_common()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolve", metavar="DATE", help="convert the exported verdicts first (date of review)")
    a = ap.parse_args()
    if a.resolve:
        resolve(a.resolve)
    build()


if __name__ == "__main__":
    main()

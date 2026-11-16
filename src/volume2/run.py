"""Parse every Volume II table from the cached Mistral responses.

    cd src && uv run python -m volume2.run

Writes output/volume2/extracted/table_<id>.csv (one row per printed cell)
and output/volume2/extracted/problems.json (structural problems per page;
entries starting with "info:" are notes, not problems). No API calls are
made unless a page's response is missing from the cache.
"""
from __future__ import annotations

import csv
import json

import yaml

from . import aircraft, lists, raob, tables8
from .pages import OUT, pages_of

EXTRACTED = OUT / "extracted"
KEYS = OUT.parents[1] / "config" / "volume2_keys.yaml"
LEAD = ["table", "pdf_index", "printed_page", "release", "release_token", "field_test", "date", "cst",
        "time_cst", "time_token", "panel", "block", "part", "section", "row", "row_key", "level",
        "level_label", "observation", "quantity", "height_m", "unit", "token", "value", "value_lo",
        "value_hi", "status", "kind", "estimated", "footnote", "conf", "flags", "key_source", "erratum"]


def parse_all() -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    tables: dict[str, list[dict]] = {}
    problems: dict[str, list[str]] = {}

    def add(t, rows, pr, key):
        tables.setdefault(t, []).extend(rows)
        if pr:
            problems[key] = pr

    for t in ("8.1", "8.2"):
        for i in pages_of(t):
            rows, pr = tables8.parse_page(i, t)
            add(t, rows, pr, f"{t} p{i}")
    for t in lists.MAIN:
        rows, pr = lists.parse_main(t)
        add(t, rows, pr, t)
    for t in lists.MINOR:
        rows, pr = lists.parse_minor(t)
        add(t, rows, pr, t)
    for i in pages_of("12.1"):
        rows, pr = raob.parse_page(i)
        add("12.1", rows, pr, f"12.1 p{i}")
    for i in pages_of("13.1")[1:]:          # first page is the legend
        rows, pr = aircraft.parse_page(i)
        add("13.1", rows, pr, f"13.1 p{i}")
    apply_owner_decisions(tables)
    for t, rows in tables.items():
        for k, r in enumerate(rows):
            r["cell_id"] = cell_id(t, r, k)
    return tables, problems


def apply_owner_decisions(tables: dict[str, list[dict]]) -> None:
    """config/volume2_keys.yaml: header keys decided by the owner, errata, conventions.
    Printed tokens are never changed; key fields carry their source."""
    d = yaml.safe_load(KEYS.read_text())
    who = f"{d['reviewer']}, {d['date']}"
    for k in d.get("keys", []):
        hit = 0
        for r in tables.get(k["table"], []):
            if r["pdf_index"] != k["pdf_index"] or ("release" in k and r.get("release") != k["release"]):
                continue
            r[f"{k['field']}_read"] = r.get(k["field"], "")
            r[k["field"]] = k["value"]
            r["key_source"] = f"manual ({who}; {k['basis']})"
            hit += 1
        if not hit:
            raise SystemExit(f"owner key matches no cell: {k}")
    for e in d.get("errata", []):
        hit = 0
        for r in tables.get(e["table"], []):
            if r.get("release") == e["release"] and r.get(e["field"]) == e["printed"]:
                r[f"{e['field']}_interpreted"] = e["interpreted"]
                r["erratum"] = e["basis"]
                hit += 1
        if not hit:
            raise SystemExit(f"erratum matches no cell: {e}")
    for r in tables.get("13.1", []):
        if r["quantity"] == "remarks":
            r["flags"] = "; ".join(x for x in (r.get("flags"), "unverified transcription") if x)


def cell_id(t: str, r: dict, k: int) -> str:
    """Stable id: table, page, and the printed coordinates of the cell."""
    parts = [f"T{t}", f"p{r['pdf_index']}"]
    for f in ("release", "field_test", "date", "cst", "panel", "block", "part", "section", "row_key",
              "row", "level", "observation", "col", "quantity", "height_m"):
        v = r.get(f)
        if v not in (None, ""):
            parts.append(str(v))
    return "|".join(parts)


def write(tables: dict[str, list[dict]], problems: dict) -> None:
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    for t, rows in tables.items():
        cols = LEAD + sorted({k for r in rows for k in r} - set(LEAD) - {"cell_id"})
        cols = ["cell_id"] + [c for c in cols if any(c in r for r in rows)]
        with (EXTRACTED / f"table_{t}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    (EXTRACTED / "problems.json").write_text(json.dumps(problems, indent=1))


def main() -> None:
    tables, problems = parse_all()
    write(tables, problems)
    for t, rows in tables.items():
        ids = [r["cell_id"] for r in rows]
        dup = len(ids) - len(set(ids))
        st: dict[str, int] = {}
        for r in rows:
            st[r["status"]] = st.get(r["status"], 0) + 1
        nflag = sum(bool(r.get("flags")) for r in rows)
        print(f"{t:5s} {len(rows):6d} cells  {st}  flagged {nflag}" + (f"  DUPLICATE IDS {dup}" if dup else ""))
    real = {k: [p for p in v if not p.startswith("info")] for k, v in problems.items()}
    print("pages/tables with structural problems:", {k: len(v) for k, v in real.items() if v})


if __name__ == "__main__":
    main()

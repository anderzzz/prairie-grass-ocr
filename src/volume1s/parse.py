"""Parse the Mistral grids of the supplementary tables into long-format cells.

One record per printed cell, same conventions as Volume II (volume2.common):
the token is kept, the value is parsed from it only, blank cells are kept.

Table-specific conventions (from the printed legends):
  5.1   Q in g/s, one decimal.
  5.4   factor to multiply concentrations by; blank = missing data
        (status `missing`, since the legend says so). Towers take the 100 m factor.
  6.1   `*` = estimate based on an incomplete record (legend p. 209), so
        estimated=True; blank = missing data (legend), status `missing`.
        A blank Date cell repeats the date to its left (printed once per day);
        `date` is carried forward, `date_token` is what is printed.
"""
from __future__ import annotations

import re
from datetime import date

from volume2.common import parse as parse_token
from volume2.common import txt

from .pages import page_markdown, page_tables, pages_of, printed

MONTHS = {"July": 7, "Aug.": 8, "Aug": 8}
RUNS = ([str(i) for i in range(1, 35)] + ["35S", "35"] + [str(i) for i in range(36, 48)]
        + ["48S", "48"] + [str(i) for i in range(49, 63)] + [str(i) for i in range(65, 69)])
STATUS = {"number": "value", "above": "value", "blank": "missing", "missing": "missing",
          "unread": "unread", "text": "text"}


def norm_run(s: str) -> str:
    return re.sub(r"\s|-", "", s or "").upper()


def cell(base: dict, c, blank_status: str = "missing") -> dict:
    text, conf = c if isinstance(c, tuple) else (c or "", None)
    p = parse_token(text or "")
    r = dict(base)
    flags = []
    if p["kind"] == "unread":
        flags.append("token does not parse")
    if conf is not None and conf < 0.95 and p["kind"] != "blank":
        flags.append(f"low Mistral confidence {conf:.3f}")
    r.update(token=p["token"], value=p["value"],
             status=blank_status if p["kind"] == "blank" else STATUS[p["kind"]],
             kind=p["kind"], estimated=p["estimated"] or p["footnote"],
             conf=None if conf is None else round(conf, 4), flags="; ".join(flags))
    return r


def prov(table: str, idx: int, ti: int, row: int) -> dict:
    return {"table": table, "pdf_index": idx, "printed_page": printed(idx),
            "grid_ti": ti, "grid_row": row}


def table_5_1() -> list[dict]:
    out = []
    for idx in pages_of("5.1"):
        for ti, g in enumerate(page_tables(idx)):
            for k, row in enumerate(g):
                for j in range(0, len(row) - 1, 2):
                    run = norm_run(txt(row[j]))
                    if not run or not re.fullmatch(r"\d+S?", run):
                        continue
                    b = prov("5.1", idx, ti, k) | {"cell_id": f"T5.1|p{idx}|r{run}", "run": run,
                                                   "quantity": "Q", "unit": "g/s", "grid_col": j + 1}
                    out.append(cell(b, row[j + 1]))
    return sorted(out, key=lambda r: (r["pdf_index"], r["grid_col"], r["grid_row"]))  # printed order: down each pair


ARCS = [50, 100, 200, 400, 800]


def table_5_4() -> list[dict]:
    out = []
    for idx in pages_of("5.4"):
        for ti, g in enumerate(page_tables(idx)):
            for k, row in enumerate(g):
                run = norm_run(txt(row[0]))
                if not re.fullmatch(r"\d+S?", run) or len(row) < 6:
                    continue
                if all(txt(c) in ("50", "100", "200", "400", "800") for c in row[:5]):
                    continue                                   # heading line
                for j, arc in enumerate(ARCS):
                    b = prov("5.4", idx, ti, k) | {"cell_id": f"T5.4|p{idx}|r{run}|a{arc}", "run": run,
                                                   "arc_m": arc, "quantity": "evaporation_correction_factor",
                                                   "unit": "", "grid_col": j + 1}
                    out.append(cell(b, row[j + 1]))
    return out


SECTIONS = {"wind speed": ("wind_speed", "m/s"), "wind direction": ("wind_direction", "deg"),
            "standard deviation": ("sigma_theta", "deg")}
SUB = {"source (10 min)": ("source", 10), "450 m (10 min)": ("450m", 10),
       "source (20 min)": ("source", 20), "450 m (20 min)": ("450m", 20)}


def parse_date(tok: str) -> str | None:
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z.]+)", tok.strip())
    if not m or m.group(2) not in MONTHS:
        return None
    return date(1956, MONTHS[m.group(2)], int(m.group(1))).isoformat()


def table_6_1() -> list[dict]:
    out = []
    last_date = None
    for idx in pages_of("6.1"):
        for ti, g in enumerate(page_tables(idx)):
            if not g or not txt(g[0][0]).startswith("Gas release"):
                continue                                       # the legend table on p. 209
            k, block = 0, -1
            while k < len(g):
                head = g[k]
                if not txt(head[0]).startswith("Gas release"):
                    k += 1
                    continue
                block += 1
                cols = [norm_run(txt(c)) for c in head[1:]]
                dates, times = g[k + 1], g[k + 2]
                assert txt(dates[0]).startswith("Date") and txt(times[0]).startswith("Time"), (idx, k)
                keys = {}
                for j, run in enumerate(cols, start=1):
                    if not run:
                        continue                               # empty slot (runs 63, 64 not printed)
                    dt = txt(dates[j])
                    if dt:
                        last_date = parse_date(dt)
                    keys[j] = {"release": run, "date_token": dt, "date": last_date,
                               "time_cst": txt(times[j]), "block": block}
                    for kk, lab in ((k, "release"), (k + 1, "date"), (k + 2, "time_cst")):
                        r = g[kk][j]
                        out.append(prov("6.1", idx, ti, kk) | keys[j] | {
                            "cell_id": f"T6.1|p{idx}|r{run}|{lab}", "quantity": f"key:{lab}",
                            "location": "", "period_min": "", "unit": "",
                            "token": txt(r), "value": None, "status": "text", "kind": "key",
                            "estimated": False, "conf": None if not isinstance(r, tuple) or r[1] is None
                            else round(r[1], 4), "flags": "", "grid_col": j})
                section = None
                k += 3
                while k < len(g) and not txt(g[k][0]).startswith("Gas release"):
                    lab = txt(g[k][0]).lower()
                    for s, v in SECTIONS.items():
                        if lab.startswith(s):
                            section = v
                    if lab in SUB:
                        loc, per = SUB[lab]
                        for j, kv in keys.items():
                            b = prov("6.1", idx, ti, k) | kv | {
                                "cell_id": f"T6.1|p{idx}|r{kv['release']}|{section[0]}|{loc}|{per}",
                                "quantity": section[0], "location": loc, "period_min": per,
                                "unit": section[1], "grid_col": j}
                            out.append(cell(b, g[k][j] if j < len(g[k]) else ""))
                    k += 1
    return out


def remarks() -> list[dict]:
    """Per-run remarks printed with Table 5.2 (pp. 79-80) and the Table 6.1 legend (p. 209)."""
    out = []
    for idx in pages_of("5.2-remarks"):
        for m in re.finditer(r"Runs? No\. ([\d, and]+?) - (.+?)(?=\n\n|\n?\d{2,3}Run|\Z)",
                             page_markdown(idx), re.S):
            runs = re.findall(r"\d+S?", m.group(1))
            for run in runs:
                out.append({"cell_id": f"R5.2|p{idx}|r{run}", "table": "5.2", "pdf_index": idx,
                            "printed_page": printed(idx), "run": run,
                            "remark": " ".join(m.group(2).split()), "applies_to": "Tables 5.2/5.3 concentrations"})
    for idx in pages_of("6.1")[:1]:
        for g in page_tables(idx):
            if not g or not txt(g[0][0]).startswith("Experiment"):
                continue
            for row in g[1:]:
                for run in re.findall(r"\d+S?", txt(row[0])):
                    out.append({"cell_id": f"R6.1|p{idx}|r{run}", "table": "6.1", "pdf_index": idx,
                                "printed_page": printed(idx), "run": run, "remark": txt(row[1]),
                                "applies_to": "Table 6.1 slow-response wind data"})
    return out


def parse_all() -> dict[str, list[dict]]:
    return {"5.1": table_5_1(), "5.4": table_5_4(), "6.1": table_6_1(), "remarks": remarks()}


if __name__ == "__main__":
    for t, rows in parse_all().items():
        print(t, len(rows))

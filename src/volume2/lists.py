"""Row-list tables of Volume II (one record per printed row, fixed columns).

Main tables (named quantities): 9.1, 9.2 (Texas A&M heat budget), 10.1
(Wisconsin heat budget). Minor tables (7.1, 7.2, 8.3, 9.3, 9.4, 11.1, 11.2,
11.3) are transcribed generically: row key(s) + the printed column heading as
the quantity, so nothing is interpreted that the page does not say.
"""
from __future__ import annotations

import re

from .common import page_tables, printed_page, record, txt
from .tables8 import release_label

# table -> (pages, table index on page, key columns, value columns (name, unit))
MAIN = {
    "9.1": ([124], 0, ["release"], [("du", "cm/sec"), ("dtheta", "degC"), ("de", "mb"),
                                    ("q_c", "Kcal/cm2 sec (as printed)"), ("q_e", "Kcal/cm2 sec (as printed)"),
                                    ("q_s", "Kcal/cm2 sec (as printed)"), ("sum_q", "Kcal/cm2 sec (as printed)"),
                                    ("R_n", "Kcal/cm2 sec (as printed)"),
                                    ("R_n_plus_sum_q", "Kcal/cm2 sec (as printed)")]),
    "9.2": ([125], 0, ["release"], [("q_c", "cal/cm2 min"), ("q_e", "cal/cm2 min"), ("q_s", "cal/cm2 min"),
                                    ("R_n", "cal/cm2 min")]),
    "10.1": ([136, 137], 0, ["release", "date_token", "time_cst"],
             [("I", "langley/min"), ("R_N", "langley/min"), ("L", "langley/min"), ("E", "langley/min"),
              ("G", "langley/min")]),
}

RELEASE_RE = re.compile(r"^\d{1,2}\s*[sSaA]?$")


def parse_main(table: str) -> tuple[list[dict], list[str]]:
    pages, ti, keys, vals = MAIN[table]
    out, problems = [], []
    ncol = len(keys) + len(vals)
    for idx in pages:
        tabs = page_tables(idx)
        if len(tabs) <= ti:
            problems.append(f"p{idx}: table {ti} not found")
            continue
        pp = printed_page(idx)
        for k, r in enumerate(tabs[ti]):
            first = txt(r[0])
            if not RELEASE_RE.match(first):
                if any(re.search(r"\d", txt(c)) for c in r[1:]) and k > 1:
                    problems.append(f"p{idx} row {k}: row with numbers but no release label: "
                                    f"{[txt(c) for c in r]}")
                continue
            if len(r) != ncol:
                problems.append(f"p{idx} row {k}: {len(r)} cells, expected {ncol}: {[txt(c) for c in r]}")
                continue
            base = {"table": table, "pdf_index": idx, "printed_page": pp, "row": k, "grid_ti": ti, "grid_row": k,
                    "release_token": first, "release": release_label(first)}
            for j, kname in enumerate(keys[1:], start=1):
                base[kname] = txt(r[j])
            for (name, unit), cell in zip(vals, r[len(keys):]):
                out.append(record(base, cell, quantity=name, unit=unit))
    return out, problems


# minor tables: (page, table index, key columns, panel width or None, header rows)
MINOR = {
    "7.1": (41, 0, 3, None, 1),
    "7.2": (44, 0, 1, None, 1),
    "8.3": (106, None, 1, None, 2),  # two tables (two pairs of dates)
    "9.3": (132, 0, 1, 5, 1),        # two side-by-side panels of 5 columns
    "9.4": (132, 1, 1, None, 1),
    "11.1": (142, 0, 2, None, 2),
    "11.2": (143, 0, 3, None, 1),
    "11.3": (144, 0, 2, 3, 1),       # three panels: date, time, three observations
}


def _headers(rows: list[list], n: int) -> tuple[list[str], int]:
    """Column headings = the first n rows joined per column."""
    heads = []
    for j in range(max(len(r) for r in rows)):
        parts = []
        for r in rows[:n]:
            jj = j
            while 0 < jj < len(r) and r[jj] is None:   # colspan filler: heading of the spanning cell
                jj -= 1
            t = txt(r[jj]) if jj < len(r) else ""
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        heads.append(" | ".join(parts))
    return heads, n


def parse_minor(table: str) -> tuple[list[dict], list[str]]:
    idx, ti, nkey, panel, nhead = MINOR[table]
    tabs = page_tables(idx)
    grids = tabs if ti is None else tabs[ti:ti + 1]
    out, problems = [], []
    pp = printed_page(idx)
    for g_i, rows in enumerate(grids):
        heads, nh = _headers(rows, nhead)
        if panel:
            width = len(heads) // (len(heads) // panel) if len(heads) % panel == 0 else panel
            spans = [(s, s + width) for s in range(0, len(heads), width)]
        else:
            spans = [(0, len(heads))]
        carry: dict[int, str] = {}
        for k, r in enumerate(rows[nh:], start=nh):
            for p_i, (a, b) in enumerate(spans):
                cells = [r[j] if j < len(r) else ("", None) for j in range(a, b)]
                keyv = [txt(c) for c in cells[:nkey]]
                # a printed key (e.g. a date) applies to the rows below it until the next one
                for j, v in enumerate(keyv):
                    if v:
                        carry[(p_i, j)] = v
                    elif j == 0 and (p_i, j) in carry and any(txt(c) for c in cells[nkey:]):
                        keyv[j] = carry[(p_i, j)]
                if not any(txt(c) for c in cells[nkey:]):
                    continue
                base = {"table": table, "pdf_index": idx, "printed_page": pp, "block": g_i,
                        "panel": p_i, "row": k, "row_key": " | ".join(keyv)}
                for j, c in enumerate(cells[nkey:], start=a + nkey):
                    parts = [p.strip() for p in txt(c).split(",")] if table == "11.3" else []
                    if len(parts) > 1:
                        # Table 11.3 prints the observations of each time as "a, b, c"
                        conf = c[1] if isinstance(c, tuple) else None
                        for o, ptxt in enumerate(parts, start=1):
                            out.append(record(base, (ptxt, conf), quantity=heads[j], observation=o, col=j))
                        continue
                    rec = record(base, c if c is not None else ("", None), quantity=heads[j] if j < len(heads) else "",
                                 col=j)
                    if rec["kind"] == "unread":
                        rec["flags"] = ""          # free text (remarks, method names) kept as printed
                        rec["status"] = "text"
                    out.append(rec)
    return out, problems

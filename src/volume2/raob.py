"""Table 12.1: rawinsonde data, two gas releases per page (left/right panel).

Each panel: a sounding (P mb, Z m, T degC, RH %; Z printed only at standard
levels, so a blank Z is "not printed", not missing) and a wind profile below
a "Winds" heading (Z m, ddd deg, ff m/sec; the first wind row is labelled
SFC). Panel headers ("Gas Release No. 29 / 3 Aug 1956 0150C") are either in
the page text above the table or in the table's first row; both are read.
One output record per printed cell, with the level's row order kept.
"""
from __future__ import annotations

import re
from datetime import date

from .common import page_markdown, page_tables, printed_page, record, txt
from .tables8 import release_label

MONTHS = {"jul": 7, "aug": 8}
HDR_RE = re.compile(r"Gas\s+\S*\s*No[.,]?\s*(\d{1,2}\s*[sS]?)\s*(?:/|\s)*"
                    r"(\d{1,2})\s+(Jul\w*|Aug\w*)\s+(\d{4})\s+(\d{3,4})\s*(\w?)", re.I)
SOUND = [("pressure", "mb"), ("height", "m"), ("temperature", "degC"), ("relative_humidity", "%")]
WIND = [("height", "m"), ("wind_direction", "deg"), ("wind_speed", "m/sec")]


def headers(idx: int) -> list[dict]:
    md = re.sub(r"<[^>]+>", " ", page_markdown(idx))
    for t in page_tables(idx):
        for p in (0, 1):   # read header rows panel by panel (left block, then right block)
            md += " " + " ".join(txt(c) for r in t[:2] for c in r[4 * p: 4 * p + 4] if c)
    out = []
    for m in HDR_RE.finditer(md):
        h = {"release_token": m.group(1).strip(), "release": release_label(m.group(1)),
             "date_token": f"{m.group(2)} {m.group(3)} {m.group(4)}", "time_token": m.group(5) + m.group(6)}
        try:
            h["date"] = date(1956, MONTHS[m.group(3)[:3].lower()], int(m.group(2))).isoformat()
        except (KeyError, ValueError):
            h["date"] = ""
        h["year_ok"] = m.group(4) == "1956"
        out.append(h)
    return out


def parse_page(idx: int) -> tuple[list[dict], list[str]]:
    problems: list[str] = []
    tabs = page_tables(idx)
    if len(tabs) != 1:
        problems.append(f"{len(tabs)} tables on page")
    if not tabs:
        return [], problems
    rows = tabs[0]
    hd = headers(idx)
    if len(hd) != 2:
        problems.append(f"{len(hd)} release headers read (expected 2): {hd}")
        return [], problems
    for h in hd:
        if not h["year_ok"]:
            problems.append(f"info: release {h['release']}: year read as {h['date_token']}; 1956 assumed")
    pp = printed_page(idx)
    out: list[dict] = []
    part, level = None, [0, 0]
    for k, r in enumerate(rows):
        cells = [txt(c) for c in r]
        if any(c.startswith("Gas") for c in cells if c) or \
                (part is None and any(re.search(r"(Jul|Aug)\w*\s+19", c) for c in cells if c)):
            continue
        if any(c.startswith("P /") or c == "P" for c in cells if c):
            part, level = "sounding", [0, 0]
            continue
        if any(c == "Winds" for c in cells if c):
            part = "winds_heading"
            continue
        if part == "winds_heading":
            if any(c.startswith("Z") for c in cells if c):
                part, level = "winds", [0, 0]
                continue
        if part is None:
            problems.append(f"row {k} before any heading: {cells}")
            continue
        if len(r) == 7 and part == "winds":
            # one label cell dropped by the OCR table (rowspan end): right-align the row
            r = [("", None)] + list(r)
            problems.append(f"info: winds row {k} had 7 cells; aligned to the right panel")
        align_note = ""
        if len(r) == 3 and part == "winds" and any(o.get("note") for o in out):
            noted = {o["panel"] for o in out if o.get("note")}
            if len(noted) == 1:
                p_free = 1 - noted.pop()
                r = ([("", None)] + list(r) + [("", None)] * 4) if p_free == 0 else \
                    ([("", None)] * 5 + list(r))
                cells = [txt(c) for c in r]
                align_note = "wind row had 3 cells; placed in the panel without a note"
        elif len(r) == 6 and part == "winds":
            # a short wind row without label cells: place the three values in the half
            # whose other cells are empty; flagged, because the side is inferred
            if all(cells[3:]) is False and not any(cells[3:]):
                r = [("", None)] + list(r[:3]) + [("", None)] * 4
            elif not any(cells[:3]):
                r = [("", None)] * 4 + [("", None)] + list(r[3:])
            align_note = "wind row had 6 cells; panel inferred from the empty half"
        if len(r) != 8:
            # a panel replaced by a note (e.g. "Signal Failure / No Data")
            notes = [c for c in cells if c and re.search(r"[a-z]{3}", c)]
            if notes and part == "winds":
                problems.append(f"info: winds row {k}: note {notes} in one panel")
                for p, h in enumerate(hd):
                    seg = cells[4 * p: 4 * p + 4]
                    if any(re.search(r"[a-z]{3}", c or "") for c in seg):
                        continue
                    seg_cells = r[4 * p: 4 * p + 4]
                    if len(seg_cells) == 4 and any(txt(c) for c in seg_cells[1:]):
                        level[p] += 1
                        base = {"table": "12.1", "pdf_index": idx, "printed_page": pp, "panel": p,
                                "release_token": h["release_token"], "release": h["release"],
                                "date": h["date"], "time_token": h["time_token"], "grid_ti": 0, "grid_row": k}
                        for (q, u), c in zip(WIND, seg_cells[1:]):
                            out.append(record(base, c, part="winds", level=level[p],
                                              level_label="SFC" if level[p] == 1 else "", quantity=q, unit=u))
                for p, h in enumerate(hd):
                    if any(re.search(r"[a-z]{3}", c or "") for c in cells[4 * p: 4 * p + 4]) and \
                            not any(o.get("note") and o["release"] == h["release"] for o in out):
                        out.append({"table": "12.1", "pdf_index": idx, "printed_page": pp, "panel": p,
                                    "release_token": h["release_token"], "release": h["release"],
                                    "date": h["date"], "time_token": h["time_token"], "part": "winds",
                                    "quantity": "note", "token": notes[0], "status": "text", "kind": "text",
                                    "value": None, "note": True, "flags": ""})
                continue
            problems.append(f"{part} row {k}: {len(r)} cells, expected 8: {cells}")
            continue
        for p, h in enumerate(hd):
            seg = r[4 * p: 4 * p + 4]
            base = {"table": "12.1", "pdf_index": idx, "printed_page": pp, "panel": p,
                    "release_token": h["release_token"], "release": h["release"],
                    "date": h["date"], "time_token": h["time_token"], "grid_ti": 0, "grid_row": k}
            if part == "sounding":
                if not any(txt(c) for c in seg):
                    continue
                level[p] += 1
                for (q, u), c in zip(SOUND, seg):
                    out.append(record(base, c, part="sounding", level=level[p], quantity=q, unit=u))
            else:
                if not any(txt(c) for c in seg[1:]):
                    continue
                level[p] += 1
                lab = "SFC" if level[p] == 1 else ""
                if level[p] == 1 and txt(seg[0]) != "SFC":
                    problems.append(f"info: release {h['release']}: first wind row not labelled SFC")
                for (q, u), c in zip(WIND, seg[1:]):
                    rec = record(base, c, part="winds", level=level[p], level_label=lab, quantity=q, unit=u)
                    if align_note:
                        rec["flags"] = "; ".join(x for x in (rec["flags"], align_note) if x)
                    out.append(rec)
    return out, problems

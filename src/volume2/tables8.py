"""Tables 8.1 and 8.2: hourly micrometeorological observations, O'Neill.

Page layout (both tables): a header block (8.1: gas release no., day of month
under a month label, CST; 8.2: the date in the title row, then CST), then
fixed sections with fixed row labels. Columns are observation times; unused
columns are printed empty. One output row per (column, section, row label).
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from . import precip
from .common import page_tables, page_text, printed_page, record, txt

SECTIONS = {
    "RADIATION": ("radiation", ["Insolation", "Reflected", "Net Radiation"], "cal/cm2 sec"),
    "AIR AND SOIL TEMPERATURES": ("temperature", ["16.00", "8.00", "4.00", "2.00", "1.00", ".50", ".25",
                                                  ".12", "-.03", "-.06", "-.12", "-.25", "-.50", "-1.00"], "degC"),
    "VAPOR PRESSURE": ("vapor_pressure", ["16.00", "8.00", "4.00", "2.00", "1.00", ".50", ".25", ".12"], "mb"),
    "WIND SPEED": ("wind_speed", ["16.00", "8.00", "4.00", "2.00", "1.00", ".50", ".25"], "cm/sec"),
    "WIND DIRECTION": ("wind_direction", ["1.00"], "deg"),
    "SOIL TEMPERATURE CHANGE": ("soil_temperature_change", ["Initial Time", "Run Time (min)", "-.03", "-.06",
                                                            "-.12", "-.25", "-.50", "-1.00"], "degC"),
}
MONTHS = {"JULY": 7, "AUGUST": 8}
RAD_Q = {"Insolation": "insolation", "Reflected": "reflected", "Net Radiation": "net_radiation"}


def _section(label: str) -> str | None:
    u = re.sub(r"\s+", " ", label.upper())
    for k in SECTIONS:
        if u.startswith(k):
            return k
    return None


def _label_key(label: str) -> str:
    s = label.strip().replace(",", ".").replace(" ", "")
    for exp in [l for sec in SECTIONS.values() for l in sec[1]]:
        if s.lower() == exp.replace(" ", "").lower():
            return exp
    try:
        f = float(s)
        return {16.0: "16.00", 8.0: "8.00", 4.0: "4.00", 2.0: "2.00", 1.0: "1.00", 0.5: ".50", 0.25: ".25",
                0.12: ".12", -0.03: "-.03", -0.06: "-.06", -0.12: "-.12", -0.25: "-.25", -0.5: "-.50",
                -1.0: "-1.00"}.get(f, label)
    except ValueError:
        return label


def _header(rows, problems):
    """Header rows before the first section heading -> (hdr, title_date, body_start)."""
    hdr: dict = {}
    title_date = None
    for i, r in enumerate(rows):
        lab = txt(r[0]).upper()
        if _section(lab):
            return hdr, title_date, i
        joined = " ".join(txt(c) for c in r).upper()
        if "RELEASE" in lab and "CST" in lab and all(not txt(c) for c in r[1:]):
            # the whole header block merged into one cell (p75): split it
            problems.append("info: header block read as one cell; split by row")
            for part in lab.split(" / "):
                toks = part.split()
                if "RELEASE" in part:
                    hdr["release"] = [(part, None)] + [(v, None) for v in toks[3:]]
                elif re.match(r"(JULY|AUGUST)", part):
                    hdr["month"] = [(part, None)] + [(v, None) for v in toks[2:]]
                    hdr["month_name"] = toks[0]
                elif part.startswith("CST"):
                    hdr["cst"] = [(part, None)] + [(v, None) for v in toks[1:]]
            continue
        if lab.startswith("HOURLY") or ("NEBRASKA" in joined and "RELEASE" not in lab):
            m = re.search(r"(JULY|AUGUST)\s+(\d{1,2})\s*,?\s*19\s*\d\s*\d", joined)
            if m:
                title_date = date(1956, MONTHS[m.group(1)], int(m.group(2)))
                if "1956" not in joined:
                    problems.append(f"info: title year read as {joined!r}; 1956 assumed")
            continue
        if lab.startswith("GAS RELEASE"):
            hdr["release"] = r
        elif re.match(r"(JULY|AUGUST)", lab):
            hdr["month"] = r
            hdr["month_name"] = re.match(r"(JULY|AUGUST)", lab).group(1)
        elif re.match(r"C\W?[SE]\W?T\b", lab):
            if not lab.startswith("CST"):
                problems.append(f"info: CST label read as '{lab}'")
            hdr["cst"] = r
        else:
            problems.append(f"unrecognised header row {[txt(c) for c in r]}")
    return hdr, title_date, None


def release_label(tok: str) -> str:
    """'35s', '35a', '35 S' -> '35S' (the S releases); digits otherwise."""
    m = re.fullmatch(r"(\d{1,2})\s*([sSaA])?", tok.strip())
    if not m:
        return ""
    return m.group(1) + ("S" if m.group(2) else "")


def parse_page(idx: int, table: str) -> tuple[list[dict], list[str]]:
    problems: list[str] = []
    tabs = page_tables(idx)
    if len(tabs) != 1:
        problems.append(f"{len(tabs)} tables on page (expected 1); using the largest")
    if not tabs:
        return [], problems
    rows = max(tabs, key=len)
    grid_ti = tabs.index(rows)
    foot = page_text(idx)
    pp = printed_page(idx)
    hdr, title_date, body_start = _header(rows, problems)
    if body_start is None or "cst" not in hdr:
        problems.append("no CST row or no section heading found")
        return [], problems
    if table == "8.1" and ("release" not in hdr or "month" not in hdr):
        problems.append("Table 8.1 page without release-number or month row")
    if table == "8.2" and title_date is None:
        problems.append("Table 8.2 page without a readable date in the title row")

    # next-day footnote ("* July 11, 1956") for CST values marked *
    fm = re.search(r"\*\s*(July|August)\s+(\d{1,2})\s*,\s*19\s*5\s*\d", foot, re.I)
    star_date = date(1956, MONTHS[fm.group(1).upper()], int(fm.group(2))) if fm else None

    def hval(key, j):
        r = hdr.get(key) or []
        return txt(r[j]) if j < len(r) else ""

    cols = []
    for j in range(1, len(hdr["cst"])):
        cst = hval("cst", j)
        if not cst:
            continue
        col = {"col": j, "cst_token": cst, "cst": cst.rstrip("*").strip()}
        if table == "8.1":
            col["release_token"] = hval("release", j)
            col["release"] = release_label(col["release_token"])
            day = hval("month", j)
            col["day_token"] = day
            try:
                col["date"] = date(1956, MONTHS[hdr["month_name"]], int(day)).isoformat()
            except (ValueError, KeyError):
                col["date"] = ""
                problems.append(f"col {j}: unreadable day '{day}'")
        else:
            d = title_date
            if cst.endswith("*"):
                d = star_date or (title_date + timedelta(days=1) if title_date else None)
                if not star_date:
                    problems.append(f"col {j}: CST {cst} marked * but no footnote date found")
            col["date"] = d.isoformat() if d else ""
        cols.append(col)

    def base(c, section):
        return {"table": table, "pdf_index": idx, "printed_page": pp, "date": c["date"], "cst": c["cst"],
                "cst_token": c["cst_token"], "release_token": c.get("release_token", ""),
                "release": c.get("release", ""), "section": section}

    # --- body: rows assigned to the fixed labels by position ------------------
    body: dict[str, list] = {}
    sec = None
    for gk, r in enumerate(rows[body_start:], start=body_start):
        lab = txt(r[0])
        s = _section(lab)
        if s:
            sec = s
            body[sec] = []
            continue
        if lab.lower().startswith("height") and all(txt(c) in ("", "--") for c in r[1:]):
            if any(txt(c) for c in r[1:]):
                problems.append("info: 'Height (m)' row carried only '--'; treated as a heading")
            continue
        if sec is not None:
            body[sec].append((gk, r))
    out: list[dict] = []
    for sec, (name, labels, unit) in SECTIONS.items():
        got = body.get(sec, [])
        keys = [_label_key(txt(r[0])) for _, r in got]
        if len(got) == len(labels):
            pairs = list(zip(labels, got))
            for k, lab in zip(keys, labels):
                if k != lab:
                    problems.append(f"info: {sec}: row label read '{k}' where '{lab}' stands (position used)")
        else:
            problems.append(f"{sec}: {len(got)} rows {keys} != expected {len(labels)}; matched by label")
            pairs = [(k, r) for k, r in zip(keys, got) if k in labels]
        for key, (gk, r) in pairs:
            for c in cols:
                cell = r[c["col"]] if c["col"] < len(r) else ("", None)
                if name == "radiation":
                    q, h, u = RAD_Q[key], "", unit
                elif key == "Initial Time":
                    q, h, u = "initial_time", "", "CST"
                elif key == "Run Time (min)":
                    q, h, u = "run_time", "", "min"
                else:
                    q, h, u = name, float(key), unit
                out.append(record(base(c, name), cell if cell is not None else ("", None),
                                  quantity=q, height_m=h, unit=u, grid_ti=grid_ti, grid_row=gk,
                                  grid_col=c["col"]))

    # --- precipitation (printed below the table; read from its own strip) ---
    toks, how = precip.read(idx, len(cols))
    for k, c in enumerate(cols):
        if toks:
            rec = record(base(c, "precipitation"), (toks[k], None), quantity="precipitation",
                         height_m="", unit="cm")
        else:
            rec = record(base(c, "precipitation"), ("", None), quantity="precipitation", height_m="", unit="cm")
            rec.update(status="unread", kind="unread", flags=f"precipitation row not read ({how})")
        rec["read_by"] = "mistral (precipitation strip)"
        out.append(rec)
    notes = re.findall(r"\*[^\n]+", foot)
    for r in out:
        r["page_footnotes"] = " | ".join(n.strip() for n in notes)
    return out, problems

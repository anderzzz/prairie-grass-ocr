"""Table 13.1: aircraft observations, two field tests per page (stacked).

Each block: header (FIELD TEST NO. n, date, time CST), then rows of
Zp (ft), P (mb), T (degC), # (two-figure trace code, see the legend on the
first page: kept as a code token, never as a number), RH (%; ">100" kept as
printed), e (mb), Td (degC) and free-text Remarks (kept verbatim; the OCR
joins wrapped lines with " / "). Page 187 holds only the legend.
"""
from __future__ import annotations

import re
from datetime import date

from .common import page_tables, printed_page, record, txt
from .tables8 import release_label

MONTHS = {"JULY": 7, "AUGUST": 8}
COLS = [("pressure_altitude", "ft"), ("pressure", "mb"), ("temperature", "degC"), ("trace_code", ""),
        ("relative_humidity", "%"), ("vapor_pressure", "mb"), ("dew_point", "degC"), ("remarks", "")]
HDR = re.compile(r"(?:FIELD\s+)?T\w*\s*NO\.?\s*(\d{1,2}\s*S?)", re.I)


def header(rows) -> dict:
    t = " ".join(txt(c) for c in rows[0] if c).upper()
    m = HDR.search(t)
    d = re.search(r"(\d{1,2})\s+(JULY|AUGUST)\s+(\d{4})", t)
    tm = re.search(r"(\d{3,4})\s*C\s*S\s*T", t)
    h = {"header_token": t, "field_test_token": m.group(1).strip() if m else "",
         "field_test": release_label(m.group(1)) if m else "",
         "date": date(1956, MONTHS[d.group(2)], int(d.group(1))).isoformat() if d else "",
         "time_cst": tm.group(1) if tm else ""}
    return h


def parse_page(idx: int) -> tuple[list[dict], list[str]]:
    problems: list[str] = []
    out: list[dict] = []
    pp = printed_page(idx)
    tabs = page_tables(idx)
    if len(tabs) != 2:
        problems.append(f"{len(tabs)} tables on page (expected 2 field tests)")
    for b, rows in enumerate(tabs):
        h = header(rows)
        if not (h["field_test"] and h["date"] and h["time_cst"]):
            problems.append(f"block {b}: header not fully read: {h['header_token']!r}")
        start = next((k + 1 for k, r in enumerate(rows[:4])
                      if len(r) > 1 and txt(r[1]).upper().startswith("P")), None)
        if start is None:
            problems.append(f"block {b}: column heading row not found")
            continue
        level = 0
        for k, r in enumerate(rows[start:], start=start):
            if len(r) == 9:
                # remarks printed in two columns (e.g. observer initials at the right): join them
                extra = txt(r[8])
                r = list(r[:7]) + [((" / ".join(x for x in (txt(r[7]), extra) if x)),
                                    r[7][1] if isinstance(r[7], tuple) else None)]
            if len(r) != 8:
                problems.append(f"block {b} row {k}: {len(r)} cells: {[txt(c) for c in r]}")
                continue
            if not any(txt(c) for c in r[:7]):
                if txt(r[7]):
                    out.append({"table": "13.1", "pdf_index": idx, "printed_page": pp, "block": b, **h,
                                "level": level, "row": k, "quantity": "remarks", "unit": "", "token": txt(r[7]),
                                "status": "text", "kind": "text", "value": None, "flags": "remark on a row "
                                "without values (attached to the level above)"})
                continue
            level += 1
            base = {"table": "13.1", "pdf_index": idx, "printed_page": pp, "block": b, **h, "level": level,
                    "grid_ti": b, "grid_row": k}
            for (q, u), c in zip(COLS, r):
                if q in ("remarks", "trace_code"):
                    t = txt(c)
                    conf = c[1] if isinstance(c, tuple) else None
                    if q == "remarks" and not t:
                        continue
                    ok = q == "remarks" or re.fullmatch(r"\d{1,2}|-{1,2}|", t)
                    fl = [] if ok else ["trace code is not a 1-2 digit code or dash"]
                    if conf is not None and conf < 0.9:
                        fl.append(f"low Mistral confidence {conf:.3f}")
                    out.append({**base, "quantity": q, "unit": u, "token": t,
                                "status": "text" if q == "remarks" else ("code" if t else "not_printed"),
                                "kind": "text", "value": None, "conf": conf, "flags": "; ".join(fl)})
                else:
                    out.append(record(base, c, quantity=q, unit=u))
    return out, problems

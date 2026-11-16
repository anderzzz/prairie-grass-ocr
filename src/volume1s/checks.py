"""Consistency checks for the supplementary tables. A failed check names the
cells involved and never proposes a value.

    cd src && uv run python -m volume1s.checks

Tolerances are deliberately loose: they are there to catch misreadings
(a dropped digit, a shifted decimal point), not unusual weather.

  keys        5.1 lists RUNS in printed order; 5.4 lists RUNS + 63, 64; 6.1 lists RUNS
  format      printed shape: Q `dd.d`/`ddd.d`, factor `d.dd`, speed `d.dd`,
              direction `ddd`, sigma `d.d`/`dd.d`, time `hhmm`, date `d Month`
  range       Q 30-110 g/s; factor 0.80-1.00; speed 0.5-15 m/s; direction 0-360;
              sigma 0.5-60 deg
  6.1-period  10- vs 20-min mean at the same place: speed within 25 %,
              direction within 20 deg
  6.1-place   source vs 450 m, same period: speed within 40 %, direction within
              30 deg after the 8 deg vane offset stated on p. 209
  6.1-8.1     date and time within 30 min of Table 8.1's (6.1 prints the release
              start, 8.1 the observation time: usually 10 min apart), and the
              10-min source speed within 30 % of Table 8.1's 2 m speed
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta
from collections import defaultdict

from extract.pdfio import REPO

from .pages import OUT
from .parse import RUNS, parse_all

FORMAT = {("5.1", "Q"): r"\d{2,3}\.\d",
          ("5.4", "evaporation_correction_factor"): r"[01]\.\d\d",
          ("6.1", "wind_speed"): r"\d{1,2}\.\d\d\*?",
          ("6.1", "wind_direction"): r"\d{1,3}\*?",
          ("6.1", "sigma_theta"): r"\d{1,2}\.\d\*?",
          ("6.1", "key:time_cst"): r"\d{4}",
          ("6.1", "key:date"): r"(\d{1,2} (July|Aug\.))?"}
RANGE = {"Q": (30, 110), "evaporation_correction_factor": (0.80, 1.00), "wind_speed": (0.5, 15),
         "wind_direction": (0, 360), "sigma_theta": (0.5, 60)}


def adiff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def table_8_1() -> dict[str, dict]:
    """release -> {date, cst, u2 (m/s)} from the Volume II dataset."""
    p = REPO / "output" / "volume2" / "dataset" / "table_8.1.csv"
    out: dict[str, dict] = {}
    for r in csv.DictReader(p.open()):
        d = out.setdefault(r["release"], {"date": r["date"], "cst": r["cst"], "u2": None})
        if (r["section"] == "wind_speed" and r["status"] == "value" and r["height_m"]
                and float(r["height_m"]) == 2.0 and d["u2"] is None):
            d["u2"] = float(r["value"]) / 100
    return out


def minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[2:])


def run_on(T: dict[str, list[dict]]) -> list[dict]:
    fails = []

    def fail(check, cells, msg):
        for c in cells or [None]:
            fails.append({"check": check, "table": c["table"] if c else "", "cell_id": c["cell_id"] if c else "",
                          "token": c["token"] if c else "", "message": msg})

    # keys
    if [c["run"] for c in T["5.1"]] != RUNS:
        fail("keys", [], f"5.1 runs differ from the expected list: {[c['run'] for c in T['5.1']]}")
    r54 = sorted({c["run"] for c in T["5.4"]})
    if r54 != sorted(RUNS + ["63", "64"]):
        fail("keys", [], f"5.4 runs differ from the expected list: {r54}")
    r61 = sorted({c["release"] for c in T["6.1"]})
    if r61 != sorted(RUNS):
        fail("keys", [], f"6.1 releases differ from the expected list: {r61}")

    # format and range
    for t in ("5.1", "5.4", "6.1"):
        for c in T[t]:
            pat = FORMAT.get((t, c["quantity"]))
            if c["status"] == "missing" or pat is None:
                continue
            if not re.fullmatch(pat, c["token"]):
                fail("format", [c], f"{c['token']!r} does not have the printed shape {pat}")
            lo_hi = RANGE.get(c["quantity"])
            if lo_hi and c["value"] is not None and not lo_hi[0] <= c["value"] <= lo_hi[1]:
                fail("range", [c], f"{c['value']} outside {lo_hi}")

    # 6.1 internal
    v = defaultdict(dict)
    for c in T["6.1"]:
        if c["status"] == "value" and not c["quantity"].startswith("key"):
            v[c["release"]][(c["quantity"], c["location"], c["period_min"])] = c
    for rel, d in v.items():
        for q in ("wind_speed", "wind_direction"):
            for loc in ("source", "450m"):
                a, b = d.get((q, loc, 10)), d.get((q, loc, 20))
                if a and b:
                    bad = (abs(a["value"] - b["value"]) > 0.25 * max(a["value"], b["value"]) if q == "wind_speed"
                           else adiff(a["value"], b["value"]) > 20)
                    if bad:
                        fail("6.1-period", [a, b], f"release {rel} {q} {loc}: 10 min {a['token']} vs 20 min {b['token']}")
            for per in (10, 20):
                a, b = d.get((q, "source", per)), d.get((q, "450m", per))
                if a and b:
                    bad = (abs(a["value"] - b["value"]) > 0.4 * max(a["value"], b["value"]) if q == "wind_speed"
                           else adiff(a["value"], b["value"] - 8) > 30)
                    if bad:
                        fail("6.1-place", [a, b], f"release {rel} {q} {per} min: source {a['token']} vs 450 m {b['token']}")

    # 6.1 against Table 8.1 (Volume II)
    m = table_8_1()
    keys = {(c["release"], c["quantity"]): c for c in T["6.1"] if c["quantity"].startswith("key")}
    for rel in sorted({c["release"] for c in T["6.1"]}):
        e = m.get(rel)
        if e is None:
            fail("6.1-8.1", [keys[(rel, "key:release")]], f"release {rel} not in Table 8.1")
            continue
        kd, kt = keys[(rel, "key:date")], keys[(rel, "key:time_cst")]
        if re.fullmatch(r"\d{4}", kt["token"]) and re.fullmatch(r"\d{4}", e["cst"] or "") and kd["date"]:
            a = datetime.fromisoformat(kd["date"]) + timedelta(minutes=minutes(kt["token"]))
            b = datetime.fromisoformat(e["date"]) + timedelta(minutes=minutes(e["cst"]))
            if abs((a - b).total_seconds()) > 30 * 60:
                fail("6.1-8.1", [kd, kt], f"release {rel}: {kd['date']} {kt['token']} vs Table 8.1 "
                                          f"{e['date']} {e['cst']}")
        s = v[rel].get(("wind_speed", "source", 10))
        if s and e["u2"] and abs(s["value"] - e["u2"]) > 0.3 * max(s["value"], e["u2"]):
            fail("6.1-8.1", [s], f"release {rel}: 2 m speed {s['token']} m/s vs Table 8.1 {e['u2']:.2f} m/s")
    return fails


def main() -> None:
    fails = run_on(parse_all())
    d = OUT / "checks"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "suspects.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["check", "table", "cell_id", "token", "message"])
        w.writeheader()
        w.writerows(fails)
    for r in fails:
        print(r["check"], r["cell_id"], r["message"])
    print(len(fails), "failures")


if __name__ == "__main__":
    main()

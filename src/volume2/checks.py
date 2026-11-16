"""Internal consistency checks for Volume II (there is no answer key).

    cd src && uv run python -m volume2.checks

Each check points at printed cells that cannot all be right. A check never
proposes a value: it only lists suspects, which then go to a second reading
(Sonnet, on request) and to the owner. Output:
output/volume2/checks/suspects.csv with one row per (check, cell):

  check       name of the check
  cell_id     a cell involved
  role        "suspect" (the check localises the error to this cell) or
              "involved" (one of the cells in a failed relation; the check
              alone cannot say which)
  detail      the numbers behind the failure

Checks (tolerances follow the printed precision; see docs/volume2.md):
  9.1-sum         Sigma q = q_c + q_e + q_s;  R_n + Sigma q column = R_n + Sigma q
  9.1-9.2         Table 9.2 = 0.06 x Table 9.1 for q_c, q_e, q_s, R_n (unit change)
  13.1-humidity   e = e_s(Td) (Magnus) and RH = e / e_s(T); localised by which pair fails
  13.1-hypso      pressure vs height between consecutive levels (hypsometric)
  12.1-hypso      height of standard levels from pressure and temperature (hypsometric)
  12.1-order      pressure decreasing and heights increasing up the sounding
  8.x-profile     vertical smoothness of temperature, vapour pressure, wind speed (in ln z)
  8.x-time        continuity at a fixed height across consecutive hours (Table 8.2, 8.1 same day)
  8.x-radiation   reflected < insolation; net radiation <= insolation
  range           physically impossible values (RH < 0, direction > 360, ...)
  keys            the same release with different date/time in different tables
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict

from .pages import OUT
from .run import parse_all

CHECKS = OUT / "checks"


class Suspects:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, check: str, cells: list[dict], detail: str, suspect: dict | None = None) -> None:
        for c in cells:
            self.rows.append({"check": check, "cell_id": c["cell_id"], "table": c["table"],
                              "pdf_index": c["pdf_index"], "token": c["token"],
                              "role": "suspect" if suspect is c else ("involved" if suspect is None else "context"),
                              "detail": detail})


def num(c: dict | None) -> float | None:
    if c is None or c.get("status") != "value" or c.get("kind") != "number":
        return None
    return float(c["value"])


def decimals(tok: str) -> int:
    t = tok.strip().lstrip("+-(").rstrip(")*")
    return len(t.split(".")[1]) if "." in t else 0


def half_ulp(c: dict) -> float:
    return 0.5 * 10 ** -decimals(c["token"])


# --------------------------------------------------------------------------- 9.1 / 9.2
def check_heat_budget(T: dict, S: Suspects) -> None:
    def by_release(t):
        d = defaultdict(dict)
        for c in T[t]:
            d[c["release"]][c["quantity"]] = c
        return d

    a, b = by_release("9.1"), by_release("9.2")
    for rel, q in a.items():
        terms = [q.get(k) for k in ("q_c", "q_e", "q_s")]
        if all(num(x) is not None for x in terms) and num(q.get("sum_q")) is not None:
            s = sum(num(x) for x in terms)
            tol = sum(half_ulp(x) for x in terms) + half_ulp(q["sum_q"]) + 1e-9
            if abs(s - num(q["sum_q"])) > tol:
                S.add("9.1-sum", terms + [q["sum_q"]],
                      f"release {rel}: q_c+q_e+q_s = {s:.2f} but printed sum {q['sum_q']['token']}")
        # the last column is printed as -(R_n + Sigma q) in every release (sign convention of
        # the table; verified on all 48 rows), so that is the relation checked
        if all(num(q.get(k)) is not None for k in ("R_n", "sum_q", "R_n_plus_sum_q")):
            s = -(num(q["R_n"]) + num(q["sum_q"]))
            tol = half_ulp(q["R_n"]) + half_ulp(q["sum_q"]) + half_ulp(q["R_n_plus_sum_q"]) + 1e-9
            if abs(s - num(q["R_n_plus_sum_q"])) > tol:
                S.add("9.1-sum", [q["R_n"], q["sum_q"], q["R_n_plus_sum_q"]],
                      f"release {rel}: -(R_n + sum) = {s:.2f} but printed {q['R_n_plus_sum_q']['token']}")
        sum_ok = None
        if all(num(x) is not None for x in terms) and num(q.get("sum_q")) is not None:
            sum_ok = abs(sum(num(x) for x in terms) - num(q["sum_q"])) <= \
                sum(half_ulp(x) for x in terms) + half_ulp(q["sum_q"]) + 1e-9
        for k in ("q_c", "q_e", "q_s", "R_n"):
            x, y = q.get(k), b.get(rel, {}).get(k)
            if num(x) is None or num(y) is None:
                continue
            tol = 0.06 * half_ulp(x) + half_ulp(y) + 1e-9
            if abs(0.06 * num(x) - num(y)) > tol:
                # the 9.1 term also enters the 9.1 sum: if that sum holds, the 9.2 cell is the odd one out
                sus = (y if sum_ok else x) if (k != "R_n" and sum_ok is not None) else None
                S.add("9.1-9.2", [x, y], f"release {rel} {k}: 0.06 x {x['token']} = {0.06 * num(x):.4f} "
                                         f"but Table 9.2 prints {y['token']}"
                                         + ("" if sus is None else f" (9.1 sum {'holds' if sum_ok else 'fails'})"),
                      sus)
    missing = set(a) ^ set(b)
    if missing:
        S.rows.append({"check": "9.1-9.2", "cell_id": "", "table": "9.1/9.2", "pdf_index": "",
                       "token": "", "role": "involved", "detail": f"releases in only one table: {sorted(missing)}"})


# --------------------------------------------------------------------------- humidity
def es(t: float) -> float:
    """Saturation vapour pressure over water, mb (Bolton 1980)."""
    return 6.112 * math.exp(17.67 * t / (t + 243.5))


def check_aircraft(T: dict, S: Suspects) -> None:
    lv = defaultdict(dict)
    for c in T["13.1"]:
        if c.get("level") and c["quantity"] != "remarks":
            lv[(c["pdf_index"], c["block"], c["level"])][c["quantity"]] = c
    for key, q in lv.items():
        t, td, e, rh = (num(q.get(k)) for k in ("temperature", "dew_point", "vapor_pressure", "relative_humidity"))
        bad = {}
        if e is not None and td is not None:
            pred = es(td)
            bad["e-Td"] = abs(pred - e) > 0.5          # 90 % of rows agree within 0.13 mb
        if e is not None and t is not None and rh is not None:
            pred = 100 * e / es(t)
            bad["RH-e-T"] = abs(pred - rh) > 4.5 and q["relative_humidity"]["kind"] == "number"
        if td is not None and t is not None and rh is not None:
            pred = 100 * es(td) / es(t)
            bad["RH-Td-T"] = abs(pred - rh) > 4.5 and q["relative_humidity"]["kind"] == "number"
        if not any(bad.values()):
            continue
        cells = [q[k] for k in ("temperature", "dew_point", "vapor_pressure", "relative_humidity") if k in q]
        detail = (f"field test {q[next(iter(q))]['field_test']} level {key[2]}: T={_tok(q, 'temperature')} "
                  f"Td={_tok(q, 'dew_point')} e={_tok(q, 'vapor_pressure')} RH={_tok(q, 'relative_humidity')}; "
                  f"e_s(Td)={es(td):.1f} " if td is not None else "") + f"failed: {[k for k, v in bad.items() if v]}"
        # localise: the cell common to all failed relations and absent from the passing ones
        rel_cells = {"e-Td": {"vapor_pressure", "dew_point"}, "RH-e-T": {"relative_humidity", "vapor_pressure", "temperature"},
                     "RH-Td-T": {"relative_humidity", "dew_point", "temperature"}}
        cand = set.intersection(*[rel_cells[k] for k, v in bad.items() if v])
        for k, v in bad.items():
            if not v:
                cand -= rel_cells[k]
        sus = q.get(cand.pop()) if len(cand) == 1 else None
        S.add("13.1-humidity", cells, detail, sus)
    # hypsometric between consecutive levels of the same flight
    by_flight = defaultdict(list)
    for key, q in lv.items():
        by_flight[key[:2]].append((key[2], q))
    for fl, levels in by_flight.items():
        levels.sort(key=lambda x: x[0])
        for (l1, a), (l2, b) in zip(levels, levels[1:]):
            z1, z2, p1, p2 = num(a.get("pressure_altitude")), num(b.get("pressure_altitude")), \
                num(a.get("pressure")), num(b.get("pressure"))
            t1, t2 = num(a.get("temperature")), num(b.get("temperature"))
            if None in (z1, z2, p1, p2, t1, t2) or p1 <= 0 or p2 <= 0:
                continue
            tk = 273.15 + (t1 + t2) / 2
            dz_pred = 29.27 * tk * math.log(p1 / p2) / 0.3048       # ft
            # heights and pressures of the flights agree only loosely (different instruments and
            # times), so only contradictions are flagged: climbing while pressure rises (or the
            # reverse) by clearly more than the noise, or a thickness off by more than a factor 2
            dz = z2 - z1
            contra = (dz > 150 and dz_pred < -150) or (dz < -150 and dz_pred > 150)
            factor = abs(dz) > 300 and abs(dz_pred) > 300 and not 0.5 < dz_pred / dz < 2
            if contra or factor:
                S.add("13.1-hypso", [a["pressure_altitude"], b["pressure_altitude"], a["pressure"], b["pressure"]],
                      f"levels {l1}->{l2}: Zp {z1:.0f}->{z2:.0f} ft but P {p1}->{p2} mb implies "
                      f"dZ = {dz_pred:.0f} ft")


def _tok(q, k):
    return q[k]["token"] if k in q else "?"


# --------------------------------------------------------------------------- rawinsonde
def check_raob(T: dict, S: Suspects) -> None:
    snd = defaultdict(list)
    wnd = defaultdict(list)
    for c in T["12.1"]:
        if c.get("part") == "sounding":
            snd[c["release"]].append(c)
        elif c.get("part") == "winds" and c["quantity"] != "note":
            wnd[c["release"]].append(c)
    for rel, cells in snd.items():
        lv = defaultdict(dict)
        for c in cells:
            lv[c["level"]][c["quantity"]] = c
        levels = [lv[k] for k in sorted(lv)]
        # order
        ps = [(q.get("pressure"), num(q.get("pressure"))) for q in levels]
        for (c1, p1), (c2, p2) in zip(ps, ps[1:]):
            if p1 is not None and p2 is not None and p2 >= p1:
                S.add("12.1-order", [c1, c2], f"release {rel}: pressure {p1} then {p2} (must decrease)")
        # hypsometric between printed heights, integrating T (virtual) over all levels between
        zs = [(i, q) for i, q in enumerate(levels) if num(q.get("height")) is not None]
        for (i1, a), (i2, b) in zip(zs, zs[1:]):
            dz, ok, layer = 0.0, True, levels[i1:i2 + 1]
            for u, v in zip(layer, layer[1:]):
                pu, pv, tu, tv = (num(u.get("pressure")), num(v.get("pressure")),
                                  num(u.get("temperature")), num(v.get("temperature")))
                if None in (pu, pv, tu, tv) or pu <= 0 or pv <= 0:
                    ok = False
                    break
                rh = [num(x.get("relative_humidity")) for x in (u, v)]
                tvirt = []
                for t_, p_, r_ in ((tu, pu, rh[0]), (tv, pv, rh[1])):
                    e_ = (r_ or 0) / 100 * es(t_)
                    tvirt.append((273.15 + t_) / (1 - 0.378 * e_ / p_))
                dz += 29.27 * (sum(tvirt) / 2) * math.log(pu / pv)
            if not ok:
                continue
            obs = num(b["height"]) - num(a["height"])
            if abs(dz - obs) > max(25, 0.03 * obs):
                inv = [a["height"], b["height"]] + [x["temperature"] for x in layer if "temperature" in x]
                S.add("12.1-hypso", inv, f"release {rel}: Z {a['height']['token']} at {a['pressure']['token']} mb -> "
                                         f"{b['height']['token']} at {b['pressure']['token']} mb; thickness from P,T "
                                         f"= {dz:.0f} m, printed {obs:.0f} m")
        for q in levels:
            rh = num(q.get("relative_humidity"))
            if rh is not None and not 1 <= rh <= 100:
                S.add("range", [q["relative_humidity"]], f"release {rel}: RH {rh}", q["relative_humidity"])
    for rel, cells in wnd.items():
        lv = defaultdict(dict)
        for c in cells:
            lv[c["level"]][c["quantity"]] = c
        zs = [(q.get("height"), num(q.get("height"))) for _, q in sorted(lv.items())]
        for (c1, z1), (c2, z2) in zip(zs, zs[1:]):
            if z1 is not None and z2 is not None and z2 <= z1:
                S.add("12.1-order", [c1, c2], f"release {rel} winds: height {z1} then {z2}")
        for q in lv.values():
            d = num(q.get("wind_direction"))
            if d is not None and not (0 <= d <= 360):
                S.add("range", [q["wind_direction"]], f"release {rel}: direction {d}", q["wind_direction"])


# --------------------------------------------------------------------------- Tables 8.x
# ~99.5th percentile of the residuals over all columns (measured 2026-11-15); wind relative to speed
PROFILE_TOL = {"temperature": 0.5, "vapor_pressure": 0.5, "wind_speed": 0.2}
TIME_TOL = {"temperature": 1.5, "vapor_pressure": 1.0, "wind_speed": 0.35, "soil_temperature": 1.5}


def check_micromet(T: dict, S: Suspects) -> None:
    cols = defaultdict(dict)        # (table, date, cst) -> {(quantity, height): cell}
    for t in ("8.1", "8.2"):
        for c in T[t]:
            cols[(t, c["date"], c["cst"])][(c["quantity"], c["height_m"])] = c
    # vertical smoothness: residual of each level from the ln(z) interpolation of its neighbours
    vert: dict[str, float] = {}
    for key, col in cols.items():
        for q, tol in PROFILE_TOL.items():
            # air levels only: soil temperatures are strongly curved near the surface by day,
            # so they are checked over time only
            prof = sorted([(h, c) for (qq, h), c in col.items() if qq == q and h != "" and float(h) > 0
                           and num(c) is not None], key=lambda x: float(x[0]))
            for (h0, c0), (h1, c1), (h2, c2) in zip(prof, prof[1:], prof[2:]):
                x0, x1, x2 = (math.log(float(h)) for h in (h0, h1, h2))
                pred = num(c0) + (num(c2) - num(c0)) * (x1 - x0) / (x2 - x0)
                r = num(c1) - pred
                if q == "wind_speed":
                    r = r / max(100.0, abs(pred))
                vert[c1["cell_id"]] = max(vert.get(c1["cell_id"], 0), abs(r) / tol)
            # the end levels have one neighbour only: compare with the extrapolation of the next two
            for ends in ((prof[:3], 0), (prof[-3:][::-1], 0)) if len(prof) >= 3 else ():
                (h0, c0), (h1, c1), (h2, c2) = ends[0]
                x0, x1, x2 = (math.log(float(h)) for h in (h0, h1, h2))
                pred = num(c1) + (num(c2) - num(c1)) * (x0 - x1) / (x2 - x1)
                r = num(c0) - pred
                if q == "wind_speed":
                    r = r / max(100.0, abs(pred))
                vert[c0["cell_id"]] = max(vert.get(c0["cell_id"], 0), abs(r) / (2 * tol))
    # time continuity at fixed height: hourly columns of Table 8.2 in time order (and 8.1)
    seq = defaultdict(list)
    for (t, d, cst), col in cols.items():
        for (q, h), c in col.items():
            if q == "temperature" and h != "" and float(h) < 0:
                q = "soil_temperature"
            if q in TIME_TOL and num(c) is not None:
                try:
                    minutes = int(cst[:2]) * 60 + int(cst[2:])
                except ValueError:
                    continue
                seq[(t, q, h)].append((d, minutes, c))
    tim: dict[str, float] = {}
    for (t, q, h), xs in seq.items():
        xs.sort(key=lambda x: (x[0], x[1]))
        for a, b, c in zip(xs, xs[1:], xs[2:]):
            ta, tb, tc = (_abs_min(x) for x in (a, b, c))
            if tc - ta > 4 * 60 or tb == ta or tc == tb:
                continue
            pred = num(a[2]) + (num(c[2]) - num(a[2])) * (tb - ta) / (tc - ta)
            r = num(b[2]) - pred
            if q == "wind_speed":
                r = r / max(100.0, abs(pred))
            tim[b[2]["cell_id"]] = abs(r) / TIME_TOL[q]
    allcells = {c["cell_id"]: c for t in ("8.1", "8.2") for c in T[t]}
    for cid, tv in tim.items():
        c = allcells[cid]
        if c["quantity"] == "temperature" and float(c["height_m"]) < 0 and tv > 1:
            S.add("8.x-time", [c], f"{c['table']} {c['date']} {c['cst']} soil temperature {c['height_m']} m = "
                                   f"{c['token']}: off its hourly series by {tv:.1f}x tolerance", c)
    for cid, v in vert.items():
        tv = tim.get(cid)
        c = allcells[cid]
        # a vertical outlier counts when its hourly series (if any) does not explain it
        if v > 1 and (tv is None or tv > 0.5):
            S.add("8.x-profile+time" if tv is not None else "8.x-profile", [c],
                  f"{c['table']} {c['date']} {c['cst']} {c['quantity']} {c['height_m']} m = {c['token']}: "
                  f"off its vertical profile by {v:.1f}x tolerance" +
                  (f" and its time series by {tv:.1f}x" if tv is not None else " (no hourly neighbours)"), c)
    for key, col in cols.items():
        ins, ref, net = (col.get((k, "")) for k in ("insolation", "reflected", "net_radiation"))
        if num(ins) is not None and num(ref) is not None and num(ins) > 0.002:
            if not 0.03 <= num(ref) / num(ins) <= 0.45:
                S.add("8.x-radiation", [ins, ref], f"{key}: reflected/insolation = {num(ref) / num(ins):.2f}")
        if num(ins) is not None and num(net) is not None and num(net) > num(ins) + half_ulp(ins) + half_ulp(net):
            S.add("8.x-radiation", [ins, net], f"{key}: net radiation {net['token']} > insolation {ins['token']}")
        wd = col.get(("wind_direction", 1.0))
        if num(wd) is not None and not 0 <= num(wd) <= 360:
            S.add("range", [wd], f"{key}: wind direction {wd['token']}", wd)


def _abs_min(x) -> int:
    d, m, _ = x
    return int(d[5:7]) * 31 * 1440 + int(d[8:10]) * 1440 + m if d else m


# --------------------------------------------------------------------------- keys across tables
def check_keys(T: dict, S: Suspects) -> None:
    seen = defaultdict(dict)    # release -> table -> (date, time, cell)
    for c in T["8.1"]:
        if c["quantity"] == "insolation":
            seen[c["release"]]["8.1"] = (c["date"], c["cst"], c)
    for c in T["10.1"]:
        if c["quantity"] == "I":
            m, d = (c.get("date_token") or "0/0").split("/")[:2]
            seen[c["release"]]["10.1"] = (f"1956-{int(m):02d}-{int(d):02d}" if m.isdigit() and d.isdigit() else "",
                                          c.get("time_cst_interpreted") or c.get("time_cst", ""), c)
    for c in T["12.1"]:
        if c.get("part") == "sounding" and c["level"] == 1 and c["quantity"] == "pressure":
            seen[c["release"]]["12.1"] = (c["date"], c["time_token"], c)
    # Table 13.1 is not compared: field-test flights were not made at release times
    # (e.g. field test 3 flew at 1100, release 3 was at 2205)
    for rel, by in seen.items():
        when = {}
        for t, (d, tm, _) in by.items():
            hm = "".join(ch for ch in str(tm) if ch.isdigit())[:4]
            if d and len(hm) == 4:
                when[t] = _abs_min((d, int(hm[:2]) * 60 + int(hm[2:]), None))
        if when and max(when.values()) - min(when.values()) > 3 * 60:
            S.add("keys", [v[2] for v in by.values()],
                  f"release {rel}: date/time differ by more than 3 h between tables: "
                  f"{ {t: f'{v[0]} {v[1]}' for t, v in by.items()} }")
    rels = [c["release"] for c in T["8.1"] if c["quantity"] == "insolation"]
    dts = [(c["date"], c["cst"], c) for c in T["8.1"] if c["quantity"] == "insolation"]
    order = sorted(dts, key=lambda x: _relnum(x[2]["release"]))
    for a, b in zip(order, order[1:]):
        if (a[0], a[1]) > (b[0], b[1]):
            S.add("keys", [a[2], b[2]], f"8.1: release {a[2]['release']} at {a[0]} {a[1]} is after release "
                                        f"{b[2]['release']} at {b[0]} {b[1]}")
    _ = rels


def _relnum(r: str) -> float:
    try:
        return float(r.rstrip("S")) + (0.5 if r.endswith("S") else 0) - (1.0 if r.endswith("S") else 0)
    except ValueError:
        return 999


# printed format of each column (every value in the column is printed this way)
FORMATS = {
    ("8.x", "insolation"): r"-?\.\d{4,5}", ("8.x", "reflected"): r"-?\.\d{4,5}",
    ("8.x", "net_radiation"): r"-?\.\d{4,5}",
    ("8.x", "temperature"): r"-?\d{1,2}\.\d{2}", ("8.x", "vapor_pressure"): r"\d{1,2}\.\d{2}",
    ("8.x", "wind_speed"): r"\d{1,4}", ("8.x", "wind_direction"): r"\d{1,3}\*?",
    ("8.x", "initial_time"): r"\d{4}", ("8.x", "run_time"): r"\d{1,2}",
    ("8.x", "soil_temperature_change"): r"[-+]?(\d?\.\d{1,2}|0|00)",
    ("12.1", "pressure"): r"\d{3,4}", ("12.1", "temperature"): r"-?\d{1,2}\.\d",
    ("12.1", "relative_humidity"): r"\d{1,3}", ("12.1", "wind_direction"): r"\d{1,3}",
    ("12.1", "wind_speed"): r"\d{1,2}(\.\d)?",
    ("13.1", "pressure_altitude"): r"\d{1,5}", ("13.1", "pressure"): r"\d{3}(\.\d)?",
    ("13.1", "temperature"): r"-?\d{1,2}\.\d", ("13.1", "relative_humidity"): r"[<>]?\d{1,3}",
    ("13.1", "vapor_pressure"): r"\d{1,2}\.\d", ("13.1", "dew_point"): r"-?\d{1,2}\.\d",
    ("9.1", "*"): r"-?\d*\.\d{2}|\d{1,3}", ("9.2", "*"): r"-?\.\d{3}",
    ("10.1", "*"): r"\(?-?\d?\.\d{2}\)?|0|\(?-?0\)?",
}


def check_format(T: dict, S: Suspects) -> None:
    import re
    for t, rows in T.items():
        for c in rows:
            if c.get("status") != "value":
                continue
            fam = "8.x" if t in ("8.1", "8.2") else t
            pat = FORMATS.get((fam, c["quantity"])) or FORMATS.get((fam, "*"))
            if t == "9.1" and c["quantity"] == "du":
                pat = r"\d{1,3}"
            if not pat:
                continue
            tok = c["token"].replace(" ", "").rstrip("*")
            if tok.startswith("(") and tok.endswith(")"):     # (x) = estimated, a printed convention
                tok = tok[1:-1]
            if not re.fullmatch(pat, tok):
                S.add("format", [c], f"{t} {c['quantity']}: token {c['token']!r} is not in the column's printed "
                                    f"format ({pat})", c)


def run_on(T: dict) -> list[dict]:
    """All checks on parsed tables T (no file output)."""
    S = Suspects()
    check_format(T, S)
    check_heat_budget(T, S)
    check_aircraft(T, S)
    check_raob(T, S)
    check_micromet(T, S)
    check_keys(T, S)
    return S.rows


def run() -> list[dict]:
    T, _ = parse_all()
    S = Suspects()
    check_format(T, S)
    check_heat_budget(T, S)
    check_aircraft(T, S)
    check_raob(T, S)
    check_micromet(T, S)
    check_keys(T, S)
    CHECKS.mkdir(parents=True, exist_ok=True)
    with (CHECKS / "suspects.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["check", "role", "cell_id", "table", "pdf_index", "token", "detail"])
        w.writeheader()
        w.writerows(S.rows)
    return S.rows


def main() -> None:
    rows = run()
    by = defaultdict(lambda: [0, 0, set()])
    for r in rows:
        k = by[r["check"]]
        k[0] += r["role"] == "suspect"
        k[1] += 1
        k[2].add(r["detail"])
    for k, (s, n, d) in sorted(by.items()):
        print(f"{k:18s} failures {len(d):4d}   localised suspects {s:4d}   cells involved {n:4d}")


if __name__ == "__main__":
    main()

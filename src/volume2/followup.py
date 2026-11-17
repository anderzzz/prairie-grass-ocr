"""Settle Mistral/Sonnet disagreements in the fully re-read tables (8.1, 8.2).

    cd src && uv run python -m volume2.followup

Inputs
  output/volume2/second_read/reads.csv          the two readings (check "full_read")
  output/volume2/second_read/adjudication.csv   third, glyph-only reading (volume2.adjudicate)
  config/review/volume2_followup_hand.csv       decisions made by hand (glyph + context, 2026-11-17)
Output
  config/review/volume2_followup.csv            read by volume2.dataset after the review verdicts

Context score. Each candidate value is compared with what its neighbours predict:
  profile  linear interpolation between the levels above and below, in ln z for air
           levels and in depth for soil levels (same column)
  time     mean of the previous and next hour (Table 8.2; same row, same day)
A residual counts only against a noise level: the median absolute residual of that
quantity on that axis over the whole table. Context picks a candidate when the other
one is off by more than NOISE_K noise levels on some axis while the picked one is at
most half as far off there, and no axis says the opposite.

Decision. Context decides (verdict "context"); where it does not, the cell is
"context_doubtful" and keeps Mistral's reading. The third, glyph-only readings
(volume2.adjudicate, Sonnet and Opus) are recorded in the basis but never decide:
on the cells where the profile is unambiguous both models contradicted it about
as often as they agreed (Sonnet 22:42, Opus 30:43), reading worn 9s and 6s as
clean 0s. In this bilevel scan a worn 9 or 6 loses its inner stroke and becomes an
oval, so "it looks like a 0" is no evidence; a hook or a tail that is there is.

Strip shifts. Where Sonnet's strip straddled rows, its whole row reproduces
Mistral's row above or below. Such rows get no second reading (verdict
"single_reader", Mistral kept), including cells that agree only by coincidence.
Disagreements in the decimal point only follow the column's printed format (a zero
is printed "00", without a point).
Hand decisions are kept, except a hand "doubtful" that context now settles. Cells
already ruled in the owner review (config/review/volume2_verdicts.csv) are skipped.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from statistics import median

from .common import parse
from .pages import OUT
from .run import parse_all
from .second_read import SECOND

ROOT = OUT.parents[1]
HAND = ROOT / "config" / "review" / "volume2_followup_hand.csv"
FOLLOWUP = ROOT / "config" / "review" / "volume2_followup.csv"
ADJ = SECOND / "adjudication.csv"
NOISE_K = 4.0
DATE = "2026-11-17"
REVIEWER = "Claude (owner-approved method)"


def num(tok: str) -> float | None:
    p = parse(tok)
    return p["value"] if p["kind"] == "number" else None


def zcoord(h: str) -> float | None:
    if h in ("", None):
        return None
    z = float(h)
    return math.log(z) if z > 0 else z            # soil: depth (negative), linear


class Context:
    def __init__(self, cells: list[dict]):
        self.val = {c["cell_id"]: num(c["token"]) for c in cells}
        self.cell = {c["cell_id"]: c for c in cells}
        self.col = defaultdict(list)               # profile: same column, same section and kind of level
        self.row = defaultdict(list)               # time: same quantity and level, same day (8.2)
        for c in cells:
            z = zcoord(c.get("height_m", ""))
            if z is None:
                continue
            soil = float(c["height_m"]) < 0
            self.col[(c["table"], c["date"], c["cst"], c.get("release", ""), c["section"], soil)].append(c["cell_id"])
            if c["table"] == "8.2" and c["cst"]:
                self.row[(c["date"], c["section"], c["quantity"], c["height_m"])].append(c["cell_id"])
        for k in self.col:
            self.col[k].sort(key=lambda i: zcoord(self.cell[i]["height_m"]))
        for k in self.row:
            self.row[k].sort(key=lambda i: self.cell[i]["cst"])
        self.noise = {}
        for axis in ("profile", "time"):
            res = defaultdict(list)
            for cid, v in self.val.items():
                p = self.predict(cid, axis)
                if v is not None and p is not None:
                    res[self.kind(cid)].append(abs(v - p))
            self.noise[axis] = {q: max(median(r), 1e-9) for q, r in res.items() if len(r) >= 20}

    def kind(self, cid: str) -> tuple[str, bool]:
        """Noise class: section, and soil vs air (soil profiles curve near the surface)."""
        c = self.cell[cid]
        return c["section"], c.get("height_m", "") not in ("", None) and float(c["height_m"]) < 0

    def predict(self, cid: str, axis: str) -> float | None:
        c = self.cell[cid]
        z = zcoord(c.get("height_m", ""))
        if z is None:
            return None
        if axis == "profile":
            ids = self.col[(c["table"], c["date"], c["cst"], c.get("release", ""), c["section"],
                            float(c["height_m"]) < 0)]
            i = ids.index(cid)
            if 0 < i < len(ids) - 1:
                a, b = ids[i - 1], ids[i + 1]
                va, vb = self.val[a], self.val[b]
                if va is None or vb is None:
                    return None
                za, zb = zcoord(self.cell[a]["height_m"]), zcoord(self.cell[b]["height_m"])
                return va + (vb - va) * (z - za) / (zb - za)
            return None
        if c["table"] != "8.2":
            return None
        ids = self.row.get((c["date"], c["section"], c["quantity"], c["height_m"]), [])
        i = ids.index(cid)
        if 0 < i < len(ids) - 1:
            va, vb = self.val[ids[i - 1]], self.val[ids[i + 1]]
            if va is not None and vb is not None:
                return (va + vb) / 2
        return None

    def judge(self, cid: str, m: str, s: str) -> tuple[str | None, str]:
        """('mistral' | 'sonnet' | None, explanation)."""
        vm, vs = num(m), num(s)
        if vm is None and vs is None:
            return None, "neither reading is a number"
        if (vm is None) != (vs is None):
            return None, "only one reading is a number"
        q = self.kind(cid)
        votes, why = [], []
        for axis in ("profile", "time"):
            p = self.predict(cid, axis)
            n = self.noise[axis].get(q)
            if p is None or n is None:
                continue
            rm, rs = abs(vm - p) / n, abs(vs - p) / n
            why.append(f"{axis}: predicted {p:.4g}, residuals {rm:.1f} (Mistral) / {rs:.1f} (Sonnet) noise units")
            if rs > NOISE_K and rm <= rs / 2:
                votes.append("mistral")
            elif rm > NOISE_K and rs <= rm / 2:
                votes.append("sonnet")
            elif rm > NOISE_K or rs > NOISE_K:
                votes.append("?")
        decided = {v for v in votes if v != "?"}
        if len(decided) == 1 and "?" not in votes:      # an axis that fits neither reading vetoes
            return decided.pop(), "; ".join(why)
        return None, "; ".join(why) if why else "no neighbours to compare with"


def shifted(r: dict) -> bool:
    """Sonnet's token is Mistral's token from the row above or below: the strip straddled rows."""
    from .common import page_tables, txt
    grid = page_tables(int(r["pdf_index"]))[int(r["grid_ti"])]
    k, col, sv = int(r["grid_row"]), int(r["grid_col"]), r["sonnet_token"].replace(" ", "")
    for j in (k - 1, k + 1):
        if 0 <= j < len(grid) and col < len(grid[j]) and sv and txt(grid[j][col]).replace(" ", "") == sv:
            return True
    return False


def shifted_rows(rows: list[dict]) -> set[tuple]:
    """(pdf_index, grid_ti, grid_row) whose Sonnet reading reproduces Mistral's row above or below."""
    from .common import page_tables, txt
    by = defaultdict(list)
    for r in rows:
        if r["compared"] == "True":
            by[(r["pdf_index"], r["grid_ti"], r["grid_row"])].append(r)
    out = set()
    for (idx, ti, k), rr in by.items():
        grid = page_tables(int(idx))[int(ti)]
        k = int(k)
        own = sum(r["agree"] == "True" for r in rr)
        for j in (k - 1, k + 1):
            if not 0 <= j < len(grid):
                continue
            nb = sum(int(r["grid_col"]) < len(grid[j]) and r["sonnet_token"].replace(" ", "") != "" and
                     txt(grid[j][int(r["grid_col"])]).replace(" ", "") == r["sonnet_token"].replace(" ", "")
                     for r in rr)
            if nb >= max(2, (len(rr) + 1) // 2) and nb > own:
                out.add((idx, ti, str(k)))
    return out


def point_only(m: str, s: str) -> bool:
    """The readers agree on every digit and sign; only a decimal point or a space differs."""
    strip = lambda t: t.replace(".", "").replace(" ", "")
    return m != s and strip(m) == strip(s) and strip(m) != ""


def usual_format(cells: list[dict]) -> dict:
    """(table, quantity) -> share of printed numbers with a decimal point."""
    n, pt = defaultdict(int), defaultdict(int)
    for c in cells:
        if c["status"] == "value":
            n[(c["table"], c["quantity"])] += 1
            pt[(c["table"], c["quantity"])] += "." in c["token"]
    return {k: pt[k] / n[k] for k in n}


def main() -> None:
    T, _ = parse_all()
    cells = [c for t in ("8.1", "8.2") for c in T.get(t, [])]
    ctx = Context(cells)
    print("noise levels:", {a: {f"{q[0]}{' (soil)' if q[1] else ''}": round(v, 4) for q, v in d.items()}
                            for a, d in ctx.noise.items()})
    hand = {r["cell_id"]: r for r in csv.DictReader(HAND.open())} if HAND.exists() else {}
    from .dataset import VERDICTS
    ruled = {r["cell_id"] for r in csv.DictReader(VERDICTS.open())} if VERDICTS.exists() else set()
    adj = {r["cell_id"]: r for r in csv.DictReader(ADJ.open())} if ADJ.exists() else {}
    po = SECOND / "adjudication_claude-opus-5-5.csv"
    adj_opus = {r["cell_id"]: r for r in csv.DictReader(po.open())} if po.exists() else {}
    full = [r for r in csv.DictReader((SECOND / "reads.csv").open())
            if r["table"] in ("8.1", "8.2") and "full_read" in r["checks"].split(";")]
    srows = shifted_rows(full)
    reads = [r for r in full if r["compared"] == "True" and
             (r["agree"] == "False" or (r["pdf_index"], r["grid_ti"], r["grid_row"]) in srows)]
    fmt = usual_format(cells)
    cellmap = {c["cell_id"]: c for c in cells}
    out, tally, conflicts = [], defaultdict(int), []
    for r in reads:
        cid, m, s = r["cell_id"], r["mistral_token"], r["sonnet_token"]
        if cid in ruled:                                 # the 2026-11-16 review already decided it
            tally["already ruled in the review"] += 1
            continue
        if ((r["pdf_index"], r["grid_ti"], r["grid_row"]) in srows or shifted(r)) and \
                not (cid in hand and hand[cid]["verdict"] != "context_doubtful"):
            tally["Sonnet strip straddled rows"] += 1
            out.append({"cell_id": cid, "group": "A", "token_as_printed": m,
                        "basis": f"Sonnet's strip straddled rows (its row reproduces the neighbouring row; "
                                 f"here {s!r}): no usable second reading; Mistral's {m!r} kept, single reader",
                        "verdict": "single_reader", "reviewer": REVIEWER, "date": DATE})
            continue
        if point_only(m, s) and not (cid in hand and hand[cid]["verdict"] != "context_doubtful"):
            c = cellmap[cid]
            share = fmt.get((c["table"], c["quantity"]), 0.5)
            pick = m if (("." in m) == (share >= 0.5)) else s
            if set(m.replace(".", "").replace(" ", "").lstrip("+-")) == {"0"}:
                pick = m if "." not in m else s          # zero is printed "00", without a point
            tally["decimal point only, by column format"] += 1
            out.append({"cell_id": cid, "group": "A", "token_as_printed": pick,
                        "basis": f"0/6/8/9 re-read of Table {r['table']}: readers agree on the digits ({m!r} vs {s!r}); "
                                 f"decimal point as printed in the column ({share:.0%} of {c['quantity']} values "
                                 f"have one)",
                        "verdict": "context", "reviewer": REVIEWER, "date": DATE})
            continue
        h = hand.get(cid)
        if h and h["verdict"] != "context_doubtful":
            out.append(h)
            a = adj.get(cid)
            if a and a["choice"] in ("mistral", "sonnet") and {"mistral": m, "sonnet": s}[a["choice"]] != h["token_as_printed"]:
                conflicts.append(f"{cid}: hand {h['token_as_printed']!r}, third reading {a['choice']} "
                                 f"({ {'mistral': m, 'sonnet': s}[a['choice']]!r})")
            tally["hand"] += 1
            continue
        cpick, cwhy = ctx.judge(cid, m, s)
        a = adj.get(cid, {})
        o = adj_opus.get(cid, {})
        gnote = "; ".join(f"{who} glyph-only reading (information only): {x['choice']}"
                          + (f" {x['third_reading'][:40]!r}" if x.get("third_reading") else "")
                          for who, x in (("Sonnet", a), ("Opus", o)) if x) or "no third reading"
        tok = {"mistral": m, "sonnet": s}
        if cpick:
            ver, pick, how = "context", cpick, "the profile/time context decides"
        else:
            ver, pick, how = "context_doubtful", "mistral", "context does not decide"
        tally[how] += 1
        name = "Mistral" if pick == "mistral" else "Sonnet"
        kept = "kept, doubtful" if ver == "context_doubtful" else "kept"
        out.append({"cell_id": cid, "group": "A", "token_as_printed": tok[pick],
                    "basis": f"0/6/8/9 re-read of Table {r['table']}: {name} reading {kept} ({m!r} vs {s!r}); "
                             f"{how}. {gnote}. Context: {cwhy}",
                    "verdict": ver, "reviewer": REVIEWER, "date": DATE})
    with FOLLOWUP.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cell_id", "group", "token_as_printed", "basis", "verdict",
                                          "reviewer", "date"])
        w.writeheader()
        w.writerows(out)
    print(f"wrote {FOLLOWUP}: {len(out)} rows;", dict(tally))
    print(f"{sum(o['verdict'] == 'context' for o in out)} context, "
          f"{sum(o['verdict'] == 'context_doubtful' for o in out)} doubtful")
    if conflicts:
        print("hand decisions contradicted by the third reading:")
        print("\n".join("  " + c for c in conflicts))


if __name__ == "__main__":
    main()

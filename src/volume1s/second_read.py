"""Independent second reading of the supplementary tables by Sonnet.

    cd src && uv run python -m volume1s.second_read [--max-calls N]

The tables are small, so every data page is read in full (not only cells in
failed checks, as in Volume II): 5.1 one call, 5.4 two calls, 6.1 two
overlapping halves per page (the dense grid needs the resolution). Sonnet is
not shown Mistral's reading. Responses are cached in cache/reader_llm; the
spend is written to output/volume1s/second_read/spend.json and the parsed
readings to output/volume1s/second_read/<table>.json.
"""
from __future__ import annotations

import argparse
import json

from extract.llm import PRICES
from volume2.second_read import MODEL, call

from .pages import OUT, image, pages_of

SECOND = OUT / "second_read"
HALT_ABOVE = 20

COMMON = """Transcribe exactly as printed: digits, decimal points, signs, asterisks, letters.
Use "" for a blank cell. Do not correct, complete or infer anything; if a character is
unclear, give your best reading and list the row label in "unclear"."""

PROMPTS = {
    "5.1": """This image is a page of a printed 1950s report holding Table 5.1, source
strengths Q in g/sec for individual diffusion experiments. The table has three side-by-side
column pairs 'Run No. | Q (g sec-1)'. Output one row per printed run: label = the run number
exactly as printed (e.g. 12, 35S), cells = [the Q value]. Go down the first pair, then the
second, then the third. Skip the heading lines.
""" + COMMON,
    "5.4": """This image is a page of a printed 1950s report holding Table 5.4, correction
factors for evaporative loss, with columns RUN NO. | ARC (m) 50 | 100 | 200 | 400 | 800.
Output one row per printed run: label = the run number exactly as printed, cells = the five
arc columns in order (50, 100, 200, 400, 800), "" where blank. Skip the heading lines.
""" + COMMON,
    "6.1": """This image is cut from a page of Table 6.1 of a printed 1950s report
(slow-response meteorological measurements). The table is printed in blocks. Each block
starts with a row 'Gas release No.' and has up to seven release columns, followed by the rows
'Date', 'Time (CST)', then 'Wind speed (m/sec)', 'Wind direction (deg)' and 'Standard
deviation of wind direction (deg)', each with four sub-rows: Source (10 min), 450 m (10 min),
Source (20 min), 450 m (20 min).

Transcribe only blocks whose 'Gas release No.' row is fully visible in this image; ignore a
block whose top is cut off. For each such block output 15 rows, labelled exactly:
'Gas release No.', 'Date', 'Time (CST)', then 'speed Source (10 min)', 'speed 450 m (10 min)',
'speed Source (20 min)', 'speed 450 m (20 min)', 'direction Source (10 min)', ...,
'sigma Source (10 min)', ..., 'sigma 450 m (20 min)'. cells = one entry per release column,
left to right, the same number of entries in every row of the block ("" where blank).
""" + COMMON,
}


def crops(table: str) -> list[tuple[str, object]]:
    """(name, image) for every call of a table."""
    out = []
    for idx in pages_of(table):
        img = image(idx)
        if table == "6.1":
            if idx == 222:                                   # text page: the legend only
                continue
            h = img.shape[0]
            out += [(f"p{idx}-top", img[: int(0.6 * h)]), (f"p{idx}-bottom", img[int(0.4 * h):])]
        else:
            out.append((f"p{idx}", img))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=HALT_ABOVE)
    a = ap.parse_args()
    budget = {"left": a.max_calls, "in": 0, "out": 0, "calls": 0}
    SECOND.mkdir(parents=True, exist_ok=True)
    for table, prompt in PROMPTS.items():
        res = {}
        for name, img in crops(table):
            r = call(img, prompt, budget)
            res[name] = {"raw": json.loads(r["raw_response"]), "request_id": r.get("request_id"),
                         "usage": r.get("usage")}
        (SECOND / f"{table}.json").write_text(json.dumps(res, indent=1))
        print(table, len(res), "reads")
    pi, po = PRICES[MODEL]
    usd = budget["in"] / 1e6 * pi + budget["out"] / 1e6 * po
    spend = SECOND / "spend.json"
    prev = json.loads(spend.read_text()) if spend.exists() else {"calls": 0, "usd": 0.0}
    spend.write_text(json.dumps({"calls": prev["calls"] + budget["calls"],
                                 "usd": round(prev["usd"] + usd, 4), "model": MODEL}))
    print(f"new calls {budget['calls']}, ${usd:.3f}")


if __name__ == "__main__":
    main()

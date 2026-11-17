"""Third reading of the cells where Mistral and Sonnet differ in the fully re-read tables.

    cd src && uv run python -m volume2.adjudicate [--tables 8.1 8.2] [--max-calls N] [--no-llm]

For each disagreement in output/volume2/second_read/reads.csv (tables read in full,
check "full_read"), Sonnet is shown the row under its column headings with the cell
boxed, plus the cell enlarged, and the two candidate readings in an order fixed by a
hash of the cell id (so neither reader is always first). It is not told which reader
gave which reading, nor any neighbouring value: this is a glyph judgement only. The
context judgement (profile in height, neighbouring hours, other tables) is made
separately and the two are combined when the follow-up verdicts are written.

Output: output/volume2/second_read/adjudication.csv - cell_id, mistral, sonnet,
choice (mistral / sonnet / neither / unclear), third_reading, note.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os

import cv2
import numpy as np

from extract.cache import cached
from extract.llm import PRICES

from .second_read import SECOND, build_image

MODEL = "claude-sonnet-5-5"
EFFORT = "high"
OUT = SECOND / "adjudication.csv"
# Sonnet as the third reader repeats Sonnet's own misreadings (worn 6 and 9 read as 0): on cells
# where the profile decides clearly it sided against the profile in 42 of 64. --model claude-opus-5-5
# gives an independent third reading, written to adjudication_<model>.csv.

PROMPT = """These images are cut from a scanned, smudged 1950s printed table of meteorological
observations. Image 1 shows the column headings (H) and one table row; the cell in question
is boxed in red. Image 2 is that cell enlarged.

Two readers transcribed the boxed cell differently:
  reading A: {a}
  reading B: {b}

In this typeface the digits 0, 6, 8 and 9 are easily confused when the print is worn.
Compare each disputed character with clear examples of the same digits elsewhere in the
row (a 0 is a closed, symmetric oval; a 6 has a hooked or flat top stroke and its loop at
the bottom; a 9 has its loop at the top and a tail at the bottom; an 8 has two stacked
loops pinched in the middle).

Decide which reading matches the print. Answer "A" or "B"; "neither" if the print shows
something else (give it in third_reading); "unclear" if the print does not allow a
decision. Judge only from the ink, not from what value would be plausible."""

SCHEMA = {"type": "object", "properties": {
    "choice": {"type": "string", "enum": ["A", "B", "neither", "unclear"]},
    "third_reading": {"type": "string"},
    "note": {"type": "string"}},
    "required": ["choice", "third_reading", "note"], "additionalProperties": False}


def cell_images(r: dict) -> tuple[np.ndarray, np.ndarray]:
    """Row strip (headings + row, cell boxed) and the enlarged cell."""
    img, _ = build_image(int(r["pdf_index"]), r["table"], int(r["grid_ti"]), [int(r["grid_row"])])
    h = img.shape[0]
    row = img[h // 2:, 70:]                                  # the row strip, without its label margin
    vert = np.where((row < 128).sum(0) > 0.7 * row.shape[0])[0]
    rules: list[list[int]] = []
    for v in vert:
        if not rules or v - rules[-1][-1] > 3:
            rules.append([v])
        else:
            rules[-1].append(v)
    xs = [int(np.mean(g)) for g in rules]
    bounds = [0] + xs + [row.shape[1]]
    if xs and xs[0] > 40:                                    # no left border found
        bounds = [0] + bounds
    col = int(r["grid_col"])
    a, b = (bounds[col + 1], bounds[col + 2]) if col + 2 < len(bounds) else (0, row.shape[1])
    a, b = max(0, a - 6), min(row.shape[1], b + 6)
    cell = cv2.resize(row[:, a:b], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    full = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(full, (70 + a, h // 2), (70 + b, h - 1), (0, 0, 255), 2)
    return full, cell


def _png(a: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", a)
    return base64.b64encode(buf.tobytes()).decode()


def call(full: np.ndarray, cell: np.ndarray, prompt: str, budget: dict, model: str = MODEL) -> dict:
    params = {"model": model, "effort": EFFORT, "prompt": prompt, "schema": "adjudicate-v1"}

    def run():
        if budget["left"] <= 0:
            raise SystemExit("call budget exhausted")
        budget["left"] -= 1
        import anthropic
        msg = anthropic.Anthropic().messages.create(
            model=model, max_tokens=8000,
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _png(full)}},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _png(cell)}},
                {"type": "text", "text": prompt}]}])
        if msg.stop_reason == "refusal":
            return {"raw_response": json.dumps({"choice": "unclear", "third_reading": "", "note": "refused"}),
                    "model": msg.model, "stop_reason": msg.stop_reason}
        raw = "".join(b.text for b in msg.content if b.type == "text")
        u = msg.usage
        budget["in"] += u.input_tokens
        budget["out"] += u.output_tokens
        budget["calls"] += 1
        return {"raw_response": raw, "model": msg.model, "stop_reason": msg.stop_reason,
                "request_id": getattr(msg, "_request_id", None),
                "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}}
    return cached("reader_llm", params, cached_key_image(full, cell), run)


def cached_key_image(full: np.ndarray, cell: np.ndarray) -> np.ndarray:
    """One array that changes whenever either image changes (the cache key hashes it)."""
    f = full[:, :, 2].ravel()
    return np.concatenate([f, cell.ravel()]).reshape(1, -1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", nargs="*", default=["8.1", "8.2"])
    ap.add_argument("--max-calls", type=int, default=600)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--limit", type=int, help="only the first N disagreements (pilot)")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--cells", help="file with one cell_id per line: adjudicate only these")
    a = ap.parse_args()
    rows = [r for r in csv.DictReader((SECOND / "reads.csv").open())
            if r["table"] in a.tables and "full_read" in r["checks"].split(";")
            and r["compared"] == "True" and r["agree"] == "False"]
    if a.cells:
        keep = {ln.strip() for ln in open(a.cells) if ln.strip()}
        rows = [r for r in rows if r["cell_id"] in keep]
    rows = rows[: a.limit] if a.limit else rows
    out_path = OUT if a.model == MODEL else SECOND / f"adjudication_{a.model}.csv"
    print(f"{len(rows)} disagreements to adjudicate")
    if len(rows) > a.max_calls:
        raise SystemExit(f"{len(rows)} calls > {a.max_calls}: halting before any call")
    if not a.no_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set")
    (SECOND / "adjudicate").mkdir(exist_ok=True)
    budget = {"left": a.max_calls, "in": 0, "out": 0, "calls": 0}
    out = []
    for r in rows:
        full, cell = cell_images(r)
        tag = r["cell_id"].replace("|", "_")
        if a.no_llm:
            cv2.imwrite(str(SECOND / "adjudicate" / f"{tag}.png"), cell)
            continue
        swap = hashlib.sha256(r["cell_id"].encode()).digest()[0] % 2 == 1
        first, second = (("sonnet", "mistral") if swap else ("mistral", "sonnet"))
        tok = {"mistral": r["mistral_token"], "sonnet": r["sonnet_token"]}
        prompt = PROMPT.format(a=tok[first], b=tok[second])
        resp = call(full, cell, prompt, budget, a.model)
        try:
            d = json.loads(resp["raw_response"])
        except ValueError:
            d = {"choice": "unclear", "third_reading": "", "note": "unparseable response"}
        choice = {"A": first, "B": second}.get(d["choice"], d["choice"])
        out.append({"cell_id": r["cell_id"], "table": r["table"], "mistral": r["mistral_token"],
                    "sonnet": r["sonnet_token"], "choice": choice,
                    "third_reading": d.get("third_reading", ""), "note": d.get("note", "")})
    if a.no_llm:
        print(f"cell images written to {SECOND / 'adjudicate'}")
        return
    if out_path.exists() and a.cells:              # partial run: merge into what is there
        old = {r["cell_id"]: r for r in csv.DictReader(out_path.open())}
        old.update({o["cell_id"]: o for o in out})
        out = list(old.values())
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    pr = PRICES.get(a.model, (4.0, 20.0))
    cost = budget["in"] / 1e6 * pr[0] + budget["out"] / 1e6 * pr[1]
    sp = SECOND / "spend.json"
    prev = json.loads(sp.read_text()) if sp.exists() else {}
    key = "adjudication" if a.model == MODEL else f"adjudication_{a.model}"
    prev.setdefault(key, {"calls": 0, "usd": 0.0})
    prev[key]["calls"] += budget["calls"]
    prev[key]["usd"] = round(prev[key]["usd"] + cost, 4)
    sp.write_text(json.dumps(prev, indent=1))
    from collections import Counter
    print(f"new calls {budget['calls']} (${cost:.2f});", dict(Counter(o["choice"] for o in out)))


if __name__ == "__main__":
    main()

"""Static HTML review pack: one page per pilot page, plus an index.

    uv run python -m scoring.review

For every scored pilot page (output/scores/<set>/cells.csv) the page shows
  * every flagged cell,
  * every cell whose value disagrees with the reference,
  * a random sample (seeded) of 30 unflagged cells that agree with it,
each with the scanned crop, its key, every reader's raw token, the value,
flags and notes, and the reference value. Nothing is adjudicated; a column
is left for the reviewer's verdict.

review/ is gitignored because it reproduces reference values.
"""
from __future__ import annotations

import csv
import html
import json
import random
from pathlib import Path

from .score import SCORES

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "review"
SEED = 1956
SAMPLE = 30

CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mut:#6e6e73;--line:#d2d2d7;--flag:#b3261e;--ok:#1b6e3a;--hl:#fff4ce}
@media (prefers-color-scheme: dark){:root{--bg:#161617;--fg:#f5f5f7;--mut:#a1a1a6;--line:#3a3a3c;--flag:#ff8a80;--ok:#7ad69b;--hl:#3b3420}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:16px}
table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:middle}
th{position:sticky;top:0;background:var(--bg)}img.crop{background:#fff;max-height:70px;image-rendering:pixelated}
.mut{color:var(--mut)}.bad{color:var(--flag);font-weight:600}.good{color:var(--ok)}code{font-size:13px}
tr.wrong{background:var(--hl)}h2{margin-top:28px}.tok{font-family:ui-monospace,Menlo,monospace}
"""

READERS = ["mistral", "tesseract", "easyocr"]


def cell_row(c: dict) -> str:
    key = (f"run {c['run']} · {c['arc_m']} m · post {c['post']}" if c["table"] == "5.2"
           else f"run {c['run']} · tower {c['tower']} · {c['height_m']} m")
    toks = "<br>".join(f"<span class=mut>{r}</span> <span class=tok>{html.escape(c.get('raw_' + r, '') or '∅')}</span>"
                       for r in READERS if f"raw_{r}" in c)
    flags = ", ".join(k[5:] for k in ("flag_readers_disagree", "flag_low_confidence",
                                      "flag_token_unexpected", "flag_structural", "flag_implausible")
                      if c.get(k) == "True")
    ok = c["outcome"] == "match"
    ref = c["ref_value"] if c["ref_kind"] == "number" else (c["ref_kind"] or "no reference")
    return (f"<tr class='{'' if ok else 'wrong'}'><td><img class=crop loading=lazy "
            f"src='../output/crops/p{c['pdf_index']}/{c['cell_id']}.png'></td>"
            f"<td>{key}<br><code class=mut>{c['cell_id']}</code></td><td>{toks}</td>"
            f"<td class=tok><b>{html.escape(c['consensus_token'] or '∅')}</b></td>"
            f"<td class=tok>{html.escape(ref)}<br><span class='{'good' if ok else 'bad'}'>{c['outcome']}</span></td>"
            f"<td><span class=bad>{flags}</span><br><span class=mut>{html.escape(c['flag_notes'])}</span></td>"
            f"<td></td></tr>")


def page_html(idx: str, cells: list[dict], summ: dict, subset: str) -> str:
    flagged = [c for c in cells if c["flagged"] == "True"]
    wrong_unflagged = [c for c in cells if c["outcome"] != "match" and c["flagged"] != "True"]
    pool = [c for c in cells if c["flagged"] != "True" and c["outcome"] == "match"
            and c["value_kind"] != "blank"]
    sample = random.Random(f"{SEED}-{idx}").sample(pool, min(SAMPLE, len(pool)))
    head = ("<tr><th>crop</th><th>cell</th><th>readers (raw)</th><th>value</th>"
            "<th>reference</th><th>flags / notes</th><th>verdict</th></tr>")
    s = summ
    parts = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>Review p{idx}</title><style>{CSS}</style>",
             f"<p><a href=index.html>← index</a></p><h1>PDF page {idx} (printed {int(idx) - 13}) · "
             f"Table {cells[0]['table']} · {subset}</h1>",
             f"<p>{s['cells_scored']} cells · disagreement {s['disagreement_rate']} · flag rate "
             f"{s['flag_rate']} · self-flag recall {s['self_flag_recall']} · "
             f"<a href='../output/pages/p{idx}.png'>page image</a></p>"]
    for title, rows in ((f"Disagree with the reference, not flagged ({len(wrong_unflagged)})", wrong_unflagged),
                        (f"Flagged ({len(flagged)})", flagged),
                        (f"Sample of unflagged cells that agree with the reference ({len(sample)})", sample)):
        parts.append(f"<h2>{title}</h2>")
        if rows:
            parts.append(f"<table>{head}{''.join(cell_row(c) for c in rows)}</table>")
        else:
            parts.append("<p class=mut>none</p>")
    return "\n".join(parts)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    index = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>Pilot review pack</title><style>{CSS}</style><h1>Pilot review pack</h1>",
             "<p>Rows highlighted: value differs from the reference. Nothing is adjudicated.</p>"]
    for subset in ("dev", "holdout"):
        path = SCORES / subset / "cells.csv"
        if not path.exists():
            continue
        summary = json.loads((SCORES / subset / "summary.json").read_text())
        cells = list(csv.DictReader(path.open()))
        o = summary["overall"]
        index.append(f"<h2>{subset}</h2><p>{o['cells_scored']} cells · disagreement {o['disagreement_rate']}"
                     f" · flag rate {o['flag_rate']} · self-flag recall {o['self_flag_recall']}</p>")
        index.append("<table><tr><th>page</th><th>table</th><th>stratum</th><th>cells</th><th>disagree</th>"
                     "<th>flagged</th><th>unflagged errors</th></tr>")
        for idx, s in summary["by_page"].items():
            pc = [c for c in cells if c["pdf_index"] == str(idx)]
            (OUT / f"p{idx}.html").write_text(page_html(str(idx), pc, s, subset))
            index.append(f"<tr><td><a href=p{idx}.html>p{idx}</a></td><td>{s['table']}</td><td>{s['stratum']}</td>"
                         f"<td>{s['cells_scored']}</td><td>{sum(c['outcome'] != 'match' for c in pc)}</td>"
                         f"<td>{sum(c['flagged'] == 'True' for c in pc)}</td><td>{s['unflagged_errors']}</td></tr>")
        index.append("</table>")
    (OUT / "index.html").write_text("\n".join(index))
    print(f"wrote {OUT}/index.html")


if __name__ == "__main__":
    main()

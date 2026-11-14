"""Volume I triage: a fourth reader (Sonnet) on the reference conflicts, then a
review pack for the project owner.

    PGOCR_LLM_MAX_CALLS=250 uv run python -m scoring.triage [--no-llm]

Design agreed with the project owner (2026-11-14): Mistral is the reader for
every cell; only cells where its value conflicts with the reference
(output/scores/volume1/conflicts.csv, from scoring.volume_compare) go to
Claude Sonnet; a person decides. This module lives in scoring/ because the
*selection* uses the reference. Sonnet sees only pixels: the cell outlined in
a strip of its column (mode `context`) and the fixed prompt in
extract/llm.py. It never sees the reference value, Mistral's reading or the
other readers.

Outputs
  output/volume1/triage/sonnet_reads.csv  one row per cell: Sonnet's reading,
      uncertain flag, note, raw response, tokens, request id. No reference
      values; committed. Raw responses are also cached in cache/reader_llm/.
  output/volume1/triage/spend.json        calls and cost of this run.
  review/volume1/index.html + crops        the review pack (local only: it
      shows reference values). Verdicts are entered in the page and saved
      with its "Download verdicts" button to review/volume1/verdicts.csv.

Nothing is adjudicated here. The groups only sort the work.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from extract.llm import LLMReader, CallCapReached, cost_usd, spend  # noqa: E402
from extract.pdfio import page_image  # noqa: E402
from extract.pipeline import MARGIN, PRESETS, normalise  # noqa: E402
from extract.preprocess import preprocess  # noqa: E402

from .score import SCORES  # noqa: E402

CONFLICTS = SCORES / "volume1" / "conflicts.csv"
VOL = REPO / "output" / "volume1"
TRIAGE = VOL / "triage"
PACK = REPO / "review" / "volume1"
MODEL = "claude-sonnet-5-5"
MODE = "context"
HALT_ABOVE = 250  # refuse to start if more cells than this would go to Sonnet

# Page-level situations seen by eye on the scan (see REPORT.md addendum).
# They only sort the review; they decide nothing.
PAGE_GROUPS = {
    (196, "800"): ("A", "Ambiguous layout: run 61, 800 m values drift off the post grid "
                        "(PDF 196); post assignment needs a human decision"),
    (106, "100"): ("B", "Suspected reference column copy: run 7, 100 m (PDF 106); the "
                        "reference repeats its 200 m values"),
}
GROUP_TITLES = {
    "A": PAGE_GROUPS[(196, "800")][1],
    "B": PAGE_GROUPS[(106, "100")][1],
    "C": "Mistral, Tesseract and EasyOCR all give the same token; the reference differs",
    "D": "Readers differ among themselves",
}


def group_of(c: dict, row: dict) -> str:
    g = PAGE_GROUPS.get((int(c["pdf_index"]), c.get("arc_m") or ""))
    if g:
        return g[0]
    toks = {normalise(row.get(f"raw_{n}", "") or "") for n in ("mistral", "tesseract", "easyocr")}
    return "C" if len(toks) == 1 else "D"


def page_rows(idx: int) -> dict:
    with (VOL / "extracted" / f"p{idx}.csv").open() as f:
        return {r["cell_id"]: r for r in csv.DictReader(f)}


def images(idx: int, rows: list[dict]) -> dict:
    """cell_id -> (cell crop, context strip with the cell outlined), exactly
    as llm_probe cuts them."""
    img, _ = preprocess(page_image(idx), PRESETS["default"])
    H, W = img.shape
    out = {}
    for r in rows:
        x0, y0, x1, y1 = map(int, r["box"].split(","))
        ex0, ex1 = max(0, x0 - MARGIN), min(W, x1 + MARGIN)
        h = y1 - y0
        sy0, sy1 = max(0, y0 - 2 * h), min(H, y1 + 2 * h)
        strip = cv2.cvtColor(img[sy0:sy1, ex0:ex1], cv2.COLOR_GRAY2BGR)
        cv2.rectangle(strip, (x0 - ex0, y0 - sy0), (x1 - ex0 - 1, y1 - sy0 - 1), (0, 0, 255), 2)
        # a wider strip for the person: the whole row band across the table
        wide = img[max(0, y0 - 3 * h):min(H, y1 + 3 * h), :]
        out[r["cell_id"]] = (img[y0:y1, ex0:ex1], strip, wide, (y0 - max(0, y0 - 3 * h), h))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="build the pack from cached reads only")
    a = ap.parse_args()
    conflicts = list(csv.DictReader(CONFLICTS.open()))
    if len(conflicts) > HALT_ABOVE and not a.no_llm:
        raise SystemExit(f"{len(conflicts)} conflict cells > {HALT_ABOVE}: halting before any "
                         "Sonnet call (owner's instruction: stop if the call count is high)")
    by_page: dict[int, list[dict]] = {}
    for c in conflicts:
        by_page.setdefault(int(c["pdf_index"]), []).append(c)
    reader = LLMReader(model=MODEL, mode=MODE, effort="low")
    (PACK / "crops").mkdir(parents=True, exist_ok=True)
    TRIAGE.mkdir(parents=True, exist_ok=True)
    jobs, rows_by_id = [], {}
    for idx, cs in sorted(by_page.items()):
        prow = page_rows(idx)
        rows = [prow[c["cell_id"]] for c in cs]
        ims = images(idx, rows)
        for c in cs:
            cid = c["cell_id"]
            rows_by_id[cid] = prow[cid]
            crop, strip, wide, (yo, h) = ims[cid]
            cv2.imwrite(str(PACK / "crops" / f"{cid}.png"), crop)
            cv2.imwrite(str(PACK / "crops" / f"{cid}_ctx.png"), strip)
            wide = cv2.cvtColor(wide, cv2.COLOR_GRAY2BGR)
            x0, y0, x1, y1 = map(int, prow[cid]["box"].split(","))
            cv2.rectangle(wide, (x0, yo), (x1, yo + h), (0, 0, 255), 2)
            cv2.imwrite(str(PACK / "crops" / f"{cid}_row.png"),
                        cv2.resize(wide, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA))
            jobs.append((cid, strip))

    def read(j):
        cid, strip = j
        if a.no_llm:
            return cid, None
        try:
            return cid, reader.read(None, strip)
        except CallCapReached as e:
            return cid, {"error": str(e)}

    with ThreadPoolExecutor(6) as ex:
        reads = dict(ex.map(read, jobs))

    tot = Counter()
    with (TRIAGE / "sonnet_reads.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cell_id", "model", "mode", "text", "uncertain", "note", "raw_response",
                    "input_tokens", "output_tokens", "stop_reason", "request_id", "error"])
        for cid, _ in jobs:
            r = reads.get(cid)
            if r is None:
                continue
            if "error" in r:
                w.writerow([cid, MODEL, MODE] + [""] * 8 + [r["error"]])
                continue
            tot["in"] += r["usage"]["input_tokens"]
            tot["out"] += r["usage"]["output_tokens"]
            w.writerow([cid, MODEL, MODE, r["text"], r["uncertain"], r["note"], r["raw_response"],
                        r["usage"]["input_tokens"], r["usage"]["output_tokens"], r["stop_reason"],
                        r.get("request_id") or "", ""])
    s = spend()
    sp = {"model": MODEL, "mode": MODE, "cells": len(jobs),
          "new_calls_this_run": s["calls"],
          "new_cost_usd": round(cost_usd(MODEL, s["input_tokens"], s["output_tokens"]), 4),
          "all_reads_cost_usd_incl_cached": round(cost_usd(MODEL, tot["in"], tot["out"]), 4),
          "errors": sum(1 for r in reads.values() if r and "error" in r)}
    (TRIAGE / "spend.json").write_text(json.dumps(sp, indent=1) + "\n")
    print(json.dumps(sp))
    build_pack(conflicts, rows_by_id, reads)


CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mut:#6e6e73;--line:#d2d2d7;--bad:#b3261e;--ok:#1b6e3a;--hl:#fff4ce}
@media (prefers-color-scheme: dark){:root{--bg:#161617;--fg:#f5f5f7;--mut:#a1a1a6;--line:#3a3a3c;--bad:#ff8a80;--ok:#7ad69b;--hl:#3b3420}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,system-ui,sans-serif;margin:0 auto;max-width:1300px;padding:16px}
table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{position:sticky;top:0;background:var(--bg);z-index:1}img{background:#fff}
img.crop{max-height:60px}img.ctx{max-height:150px}img.row{max-width:520px;display:none;margin-top:6px}
tr.open img.row{display:block}.mut{color:var(--mut)}.tok{font-family:ui-monospace,Menlo,monospace;font-size:15px}
.same{color:var(--ok)}.diff{color:var(--bad)}button{font:inherit;padding:4px 10px;cursor:pointer}
.bar{position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:2;border-bottom:1px solid var(--line)}
td.v label{display:block;white-space:nowrap}input[type=text]{width:90px}
"""

JS = """
const KEY='pg-vol1-verdicts';
let V={};try{V=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(V))}catch(e){};count()}
function count(){document.getElementById('n').textContent=Object.values(V).filter(v=>v.verdict).length}
document.querySelectorAll('tr[data-id]').forEach(tr=>{
  const id=tr.dataset.id, v=V[id]||{};
  tr.querySelectorAll('input[type=radio]').forEach(r=>{r.checked=v.verdict===r.value;
    r.onchange=()=>{V[id]={...(V[id]||{}),verdict:r.value};save()}});
  const t=tr.querySelector('input[type=text]');t.value=v.value||'';
  t.oninput=()=>{V[id]={...(V[id]||{}),value:t.value};save()};
  const n=tr.querySelector('textarea');n.value=v.note||'';
  n.oninput=()=>{V[id]={...(V[id]||{}),note:n.value};save()};
  tr.querySelector('.ctxbtn').onclick=()=>tr.classList.toggle('open');
});
count();
document.getElementById('dl').onclick=()=>{
  const q=s=>'"'+String(s??'').replace(/"/g,'""')+'"';
  const rows=[['cell_id','verdict','value_as_printed','note']];
  for(const [id,v] of Object.entries(V)) rows.push([id,v.verdict,v.value,v.note]);
  const b=new Blob([rows.map(r=>r.map(q).join(',')).join('\\n')+'\\n'],{type:'text/csv'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='verdicts.csv';a.click();
};
"""


def build_pack(conflicts: list[dict], rows_by_id: dict, reads: dict) -> None:
    groups: dict[str, list] = {k: [] for k in GROUP_TITLES}
    for c in conflicts:
        groups[group_of(c, rows_by_id[c["cell_id"]])].append(c)
    n_sonnet_m = n_sonnet_r = n_read = 0
    out = []
    for g, cs in groups.items():
        trs = []
        for c in cs:
            r = rows_by_id[c["cell_id"]]
            s = reads.get(c["cell_id"]) or {}
            st = normalise(s.get("text", "")) if s and "error" not in s else None
            mi = normalise(r.get("raw_mistral", "") or "")
            ref = c["ref_value"] if c["ref_kind"] == "number" else (c["ref_kind"] or "not in reference")
            if st is not None:
                n_read += 1
                n_sonnet_m += st == mi
                n_sonnet_r += _num_eq(st, c["ref_value"]) if c["ref_kind"] == "number" else st == ""
            key = (f"run {c['run']} · {c['arc_m']} m · post {c['post']}" if c["table"] == "5.2"
                   else f"run {c['run']} · tower {c['tower']} · {c['height_m']} m")
            son = ("<span class=mut>not read</span>" if st is None else
                   f"<span class=tok>{html.escape(st or '∅')}</span>"
                   + (" <span class=diff>uncertain</span>" if s.get("uncertain") else "")
                   + f"<br><span class=mut>{html.escape(s.get('note', ''))}</span>")
            toks = "<br>".join(
                f"<span class=mut>{n}</span> <span class=tok>{html.escape(r.get('raw_' + n, '') or '∅')}</span>"
                for n in ("mistral", "tesseract", "easyocr"))
            cid = c["cell_id"]
            trs.append(
                f"<tr data-id='{cid}'><td><img class=crop src='crops/{cid}.png'><br>"
                f"<img class=ctx src='crops/{cid}_ctx.png'><br><button class=ctxbtn>row context</button>"
                f"<img class=row loading=lazy src='crops/{cid}_row.png'></td>"
                f"<td>{key}<br><span class=mut>PDF {c['pdf_index']} (printed {c['printed_page']})</span>"
                f"<br><code class=mut>{cid}</code></td>"
                f"<td>{toks}</td><td>{son}</td>"
                f"<td class=tok>{html.escape(ref)}</td>"
                f"<td class=mut>{html.escape(c['flag_notes'] or '')}<br>{'flagged' if c['flagged'] == 'True' else 'not flagged'}</td>"
                f"<td class=v><label><input type=radio name='{cid}' value=ours> ours</label>"
                f"<label><input type=radio name='{cid}' value=reference> reference</label>"
                f"<label><input type=radio name='{cid}' value=other> other:</label>"
                f"<input type=text placeholder='as printed'><br>"
                f"<textarea rows=1 placeholder=note></textarea></td></tr>")
        out.append(f"<h2>{g}. {html.escape(GROUP_TITLES[g])} ({len(cs)})</h2>")
        out.append("<table><tr><th>scan (cell · what Sonnet saw)</th><th>cell</th><th>readers</th>"
                   "<th>Sonnet</th><th>reference</th><th>flags</th><th>verdict</th></tr>"
                   + "".join(trs) + "</table>" if trs else "<p class=mut>none</p>")
    head = (f"<!doctype html><html lang=en><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Volume I conflicts</title><style>{CSS}</style>"
            f"<h1>Volume I: cells where our value and the reference differ</h1>"
            f"<p>{len(conflicts)} cells. Sonnet read {n_read} of them from pixels only "
            f"(it never saw the reference or the other readings): it gives Mistral's token in "
            f"{n_sonnet_m} and the reference value in {n_sonnet_r}. "
            f"Our value is Mistral's token. A verdict records what is printed: "
            f"<b>ours</b> = Mistral is right, <b>reference</b> = the reference is right, "
            f"<b>other</b> = neither (type what is printed). Verdicts are kept in this browser; "
            f"use the button to save them as <code>review/volume1/verdicts.csv</code>.</p>"
            f"<div class=bar><button id=dl>Download verdicts</button> "
            f"<span class=mut><span id=n>0</span> of {len(conflicts)} decided</span></div>")
    (PACK / "index.html").write_text(head + "\n".join(out) + f"<script>{JS}</script>")
    print(f"wrote {PACK / 'index.html'}")


def _num_eq(tok: str, ref: str) -> bool:
    try:
        return abs(float(tok.rstrip("*")) - float(ref)) < 1e-9
    except ValueError:
        return False


if __name__ == "__main__":
    main()

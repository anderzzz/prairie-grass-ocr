"""Second owner review (2026-11): doubtful readings and outliers -> review/round2/index.html

    cd src && uv run python -m publish.review_pack      (make review-round2)

Two groups, both read from the published datasets only:

  D  doubtful readings (quality = doubtful, Volume II): the readers disagree and
     nothing decided, or (Tables 8.1/8.2) the second reader returned nothing.
     Shown: the row under its headings with the cell boxed where the column can
     be located, the cell enlarged, both readings, and the context the follow-up
     used (height profile, neighbouring hours) as text.
  O  outliers not yet ruled by the owner: Volume II cells marked by the outlier
     screen, the release 16 insolation, and the Volume I arc spikes with measured
     neighbours that notebook 04 lists (cells already in suspect_values.yaml are
     left out). The question is whether the print says this, and if it does,
     whether it looks like a typing error in the original.

Verdicts stay in the browser (localStorage) and are exported with "Download
verdicts" as review/round2/verdicts.csv:
  cell_id, file, group, verdict, typed, note
  D verdicts: mistral | sonnet | other (typed = as printed) | cant_tell
  O verdicts: printed_real | printed_typo (typed = intended value) |
              misread (typed = as printed) | cant_tell

Nothing is applied here; a later step turns the verdicts into config/review/.
"""
from __future__ import annotations

import csv
import html
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import yaml

from extract.pdfio import page_image
from extract.pipeline import MARGIN, PRESETS
from extract.preprocess import preprocess
from volume2.adjudicate import cell_images
from volume2.pages import image as page_image_v2
from volume2.second_read import SECOND, build_image

REPO = Path(__file__).resolve().parents[2]
V1 = REPO / "output" / "volume1" / "dataset"
V2 = REPO / "output" / "volume2" / "dataset"
X1 = REPO / "output" / "volume1" / "extracted"
X2 = REPO / "output" / "volume2" / "extracted"
PACK = REPO / "review" / "round2"
SPIKE_FACTOR = 5.0           # as notebook 04: > 5x the larger measured neighbour


def _rows(p: Path) -> list[dict]:
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def _where(c: dict) -> str:
    t = c["table"]
    if t in ("8.1", "8.2"):
        h = f" at {c['height_m']} m" if c.get("height_m") else ""
        rel = f"release {c['release']}, " if c.get("release") else ""
        return f"Table {t}, {rel}{c['date']} {c['cst']} CST: {c['quantity']}{h} (printed p. {c['printed_page']})"
    if t == "12.1":
        return f"Table 12.1, release {c['release']}, {c['part']} level {c['level']}: {c['quantity']} " \
               f"(printed p. {c['printed_page']})"
    if t == "13.1":
        return f"Table 13.1, field test {c['field_test']}, {c['date']} {c['time_cst']}, block {c['block']} " \
               f"level {c['level']}: {c['quantity']} (printed p. {c['printed_page']})"
    return f"Table {t}, {c.get('release') and 'release ' + c['release'] + ', ' or ''}{c['quantity']} " \
           f"(printed p. {c['printed_page']})"


def _context(c: dict, by_table: dict) -> str:
    """The neighbours a reader would compare with, as text."""
    if c["table"] not in ("8.1", "8.2") or not c.get("height_m"):
        return ""
    rows = by_table[c["table"]]
    key = ("release", "date", "cst") if c["table"] == "8.1" else ("date", "cst")
    prof = [r for r in rows if r["quantity"] == c["quantity"] and all(r[k] == c[k] for k in key)]
    prof.sort(key=lambda r: float(r["height_m"]))
    out = "profile: " + ", ".join(
        (f"<b>{r['height_m']} m: {html.escape(r['token'])}</b>" if r["cell_id"] == c["cell_id"]
         else f"{r['height_m']} m: {html.escape(r['token'])}") for r in prof)
    if c["table"] == "8.2":
        series = sorted((r for r in rows if r["quantity"] == c["quantity"] and r["height_m"] == c["height_m"]),
                        key=lambda r: (r["date"], r["cst"]))
        i = next(k for k, r in enumerate(series) if r["cell_id"] == c["cell_id"])
        near = series[max(0, i - 2): i + 3]
        out += "<br>hours: " + ", ".join(
            (f"<b>{r['cst']}: {html.escape(r['token'])}</b>" if r["cell_id"] == c["cell_id"]
             else f"{r['cst']}: {html.escape(r['token'])}") for r in near)
    return out


def _v2_images(c: dict, grid: dict, name: str) -> tuple[str, str | None]:
    """Row strip (cell boxed if its column is known) and the enlarged cell."""
    full_p, cell_p = PACK / "img" / f"{name}.png", PACK / "img" / f"{name}_cell.png"
    g = grid.get(c["cell_id"], {})
    if not full_p.exists():
        if not c.get("grid_ti") and not g.get("grid_ti"):     # small tables: no row grid, show the page
            im = page_image_v2(int(c["pdf_index"]))
            cv2.imwrite(str(full_p), cv2.resize(im, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
            return f"img/{full_p.name}", None
        c = dict(c, grid_ti=c.get("grid_ti") or g["grid_ti"], grid_row=c.get("grid_row") or g["grid_row"])
        if g.get("grid_col", "") != "":
            full, cell = cell_images({"pdf_index": c["pdf_index"], "table": c["table"],
                                      "grid_ti": c["grid_ti"], "grid_row": c["grid_row"],
                                      "grid_col": g["grid_col"]})
            cv2.imwrite(str(cell_p), cell)
        else:
            full, _ = build_image(int(c["pdf_index"]), c["table"], int(c["grid_ti"]), [int(c["grid_row"])])
        cv2.imwrite(str(full_p), full)
    return f"img/{full_p.name}", (f"img/{cell_p.name}" if cell_p.exists() else None)


def _v1_images(r: dict, name: str) -> tuple[str, str]:
    """Volume I: the post's column strip with the cell outlined, and the cell enlarged."""
    full_p, cell_p = PACK / "img" / f"{name}.png", PACK / "img" / f"{name}_cell.png"
    if not full_p.exists():
        img, _ = preprocess(page_image(int(r["pdf_index"])), PRESETS["default"])
        H, W = img.shape
        x0, y0, x1, y1 = map(int, r["box"].split(","))
        h = y1 - y0
        wide = cv2.cvtColor(img[max(0, y0 - 4 * h):min(H, y1 + 4 * h), :], cv2.COLOR_GRAY2BGR)
        oy = max(0, y0 - 4 * h)
        cv2.rectangle(wide, (x0, y0 - oy), (x1, y1 - oy), (0, 0, 255), 2)
        cv2.imwrite(str(full_p), cv2.resize(wide, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA))
        cell = img[y0:y1, max(0, x0 - MARGIN):min(W, x1 + MARGIN)]
        cv2.imwrite(str(cell_p), cv2.resize(cell, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
    return f"img/{full_p.name}", f"img/{cell_p.name}"


def _readings() -> dict:
    return {r["cell_id"]: r for r in _rows(SECOND / "reads.csv")}


def volume2_items() -> list[dict]:
    reads = _readings()
    by_table = {p.stem.split("_", 1)[1]: _rows(p) for p in sorted(V2.glob("table_*.csv"))}
    grid = {r["cell_id"]: r for p in X2.glob("table_*.csv") for r in _rows(p)}
    items = []
    for t, rows in by_table.items():
        for c in rows:
            doubtful = c["quality"] == "doubtful"
            insolation16 = (t == "8.1" and c["quantity"] == "insolation" and c["release"] == "16")
            outlier = (c["outlier"] or insolation16) and c["quality"] not in ("owner", "illegible")
            if not (doubtful or outlier):
                continue
            name = c["cell_id"].replace("|", "_").replace("/", "-")
            full, cell = _v2_images(c, grid, name)
            rd = reads.get(c["cell_id"], {})
            it = {"group": "D" if doubtful else "O", "cell_id": c["cell_id"], "file": f"volume2/table_{t}.csv",
                  "where": _where(c), "img": full, "cell": cell, "token": c["token"],
                  "mistral": rd.get("mistral_token", c["token"]), "sonnet": rd.get("sonnet_token", ""),
                  "context": _context(c, by_table),
                  "why": c["outlier"] or ("printed without a decimal point; above the solar constant"
                                          if insolation16 else ""),
                  "evidence": c["value_source"], "quality": c["quality"]}
            if doubtful and not it["sonnet"]:
                it["why"] = "no usable second reading"
            items.append(it)
    return items


def volume1_items() -> list[dict]:
    suspects = {e["cell_id"] for e in yaml.safe_load((REPO / "config" / "suspect_values.yaml").read_text())["volume1"]}
    arcs = [r for r in _rows(V1 / "arcs.csv") if r["status"] in ("value", "not_measurable")]
    series = defaultdict(list)
    for r in arcs:
        series[(r["run"], r["arc_m"])].append(r)
    items, pages = [], {}
    for (run, arc), rs in series.items():
        rs.sort(key=lambda r: int(r["post"]))
        val = [float(r["concentration_mg_m3"] or 0) for r in rs]
        for i in range(1, len(rs) - 1):
            nb = max(val[i - 1], val[i + 1])
            if nb > 0 and val[i] > SPIKE_FACTOR * nb and rs[i]["cell_id"] not in suspects:
                r = rs[i]
                idx = r["pdf_index"]
                if idx not in pages:
                    pages[idx] = {x["cell_id"]: x for x in _rows(X1 / f"p{idx}.csv")}
                full, cell = _v1_images(pages[idx][r["cell_id"]], r["cell_id"])
                items.append({"group": "O", "cell_id": r["cell_id"], "file": "volume1/arcs.csv",
                              "where": f"Table 5.2, run {run}, {arc} m arc, post {r['post']} "
                                       f"({r['bearing_deg']}°, printed p. {r['printed_page']})",
                              "img": full, "cell": cell, "token": r["token"], "mistral": r["token"],
                              "sonnet": "", "quality": "single_reader",
                              "context": f"posts {rs[i-1]['post']}–{rs[i+1]['post']}: "
                                         f"{rs[i-1]['token'] or 'blank'}, <b>{r['token']}</b>, "
                                         f"{rs[i+1]['token'] or 'blank'}",
                              "why": f"{val[i] / nb:.0f}x the larger neighbour",
                              "evidence": r["value_source"] + (f"; flags: {r['flag_notes']}" if r["flag_notes"] else "")})
    return items


def write_html(items: list[dict]) -> None:
    blocks = []
    for k, it in enumerate(items):
        e = html.escape
        cell = f"<img class=cell src='{it['cell']}' loading=lazy>" if it["cell"] else \
            "<div class=ev>(column not located: find the value in the row)</div>"
        if it["group"] == "D" and it["sonnet"]:
            q = (f"<label><input type=radio name=v{k} value=mistral> <code>{e(it['mistral'])}</code></label>"
                 f"<label><input type=radio name=v{k} value=sonnet> <code>{e(it['sonnet'])}</code></label>")
        elif it["group"] == "D":
            q = f"<label><input type=radio name=v{k} value=mistral> <code>{e(it['mistral'])}</code> is right</label>"
        else:
            q = (f"<label><input type=radio name=v{k} value=printed_real> printed <code>{e(it['token'])}</code>, "
                 f"plausibly real</label>"
                 f"<label><input type=radio name=v{k} value=printed_typo> printed, but a typo; intended:</label>")
        q += (f"<label><input type=radio name=v{k} value={'other' if it['group'] == 'D' else 'misread'}> "
              f"{'other' if it['group'] == 'D' else 'misread'}; printed:</label>"
              f"<input class=t name=t{k} placeholder='value'>"
              f"<label><input type=radio name=v{k} value=cant_tell> can't tell</label>"
              f"<input class=n name=n{k} placeholder='note (optional)'>")
        blocks.append(
            f"<div class='it g{it['group']}' data-k={k} data-id=\"{e(it['cell_id'])}\" data-file='{it['file']}' "
            f"data-group={it['group']}><div class=h><span class=g>{it['group']}</span> {e(it['where'])}"
            f"{' &middot; <i>' + e(it['why']) + '</i>' if it['why'] else ''}</div>"
            f"<img src='{it['img']}' loading=lazy>{cell}"
            f"{'<div class=ctx>' + it['context'] + '</div>' if it['context'] else ''}"
            f"<details><summary>how it was settled so far ({e(it['quality'])})</summary>"
            f"<div class=ev>{e(it['evidence'])}</div></details><div class=c>{q}</div></div>")
    n = defaultdict(int)
    for it in items:
        n[it["group"]] += 1
    page = f"""<!doctype html><html><head><meta charset=utf-8><title>Doubtful and outlier review</title>
<meta name=viewport content="width=device-width, initial-scale=1">
<style>
:root{{--bg:#fff;--fg:#111;--mut:#666;--bd:#ddd;--d:#b45309;--o:#1d4ed8}}
@media (prefers-color-scheme: dark){{:root{{--bg:#111;--fg:#eee;--mut:#aaa;--bd:#333}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1150px;padding:16px}}
.it{{border:1px solid var(--bd);border-radius:8px;padding:10px;margin:12px 0}}
.it.done{{opacity:.55}}
.it img{{max-width:100%;background:#fff;display:block;margin:6px 0}} .it img.cell{{max-height:110px}}
.g{{display:inline-block;min-width:1.4em;text-align:center;border-radius:4px;color:#fff;font-weight:600;margin-right:4px}}
.gD .g{{background:var(--d)}} .gO .g{{background:var(--o)}}
.ev,.ctx{{color:var(--mut)}} .ctx{{margin:4px 0}} .c label{{margin-right:14px;white-space:nowrap}}
.t{{width:7em;margin-right:14px}} .n{{width:16em}} code{{font-size:16px}}
.bar{{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--bd);z-index:1}}
</style></head><body>
<div class=bar><b>Round 2</b> &middot; <span class=g style="background:var(--d)">D</span>{n['D']} doubtful readings
&middot; <span class=g style="background:var(--o)">O</span>{n['O']} outliers &nbsp;
<label><input type=checkbox id=hide> hide decided</label> &nbsp;
<button id=dl>Download verdicts</button> <span id=cnt></span>
<div class=ev>Judge from the ink. In this print a worn 6 or 9 loses its inner stroke and looks like a 0:
an oval alone is no evidence, a hook or tail is. Context (profile, hours) is shown to help, not to decide.</div></div>
{''.join(blocks)}
<script>
const KEY='pg-round2-verdicts';
let st={{}}; try{{st=JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{}}
function save(){{try{{localStorage.setItem(KEY,JSON.stringify(st))}}catch(e){{}};count()}}
function count(){{const all=[...document.querySelectorAll('.it')];
 let d=0; all.forEach(e=>{{const ok=!!(st[e.dataset.id]&&st[e.dataset.id].v); d+=ok;
  e.classList.toggle('done',ok); e.style.display=(ok&&document.getElementById('hide').checked)?'none':''}});
 document.getElementById('cnt').textContent=d+' / '+all.length+' decided'}}
document.querySelectorAll('.it').forEach(e=>{{const id=e.dataset.id,s=st[id]||{{}};
 e.querySelectorAll('input[type=radio]').forEach(r=>{{if(s.v===r.value)r.checked=true;
  r.onchange=()=>{{st[id]=Object.assign(st[id]||{{}},{{v:r.value}});save()}}}});
 for(const [cls,f] of [['t','t'],['n','n']]){{const i=e.querySelector('input.'+cls);
  i.value=s[f]||''; i.oninput=()=>{{st[id]=Object.assign(st[id]||{{}},{{[f]:i.value}});save()}}}}}});
document.getElementById('hide').onchange=count;
document.getElementById('dl').onclick=()=>{{
 const q=x=>'"'+String(x).replace(/"/g,'""')+'"';
 const lines=['cell_id,file,group,verdict,typed,note'];
 document.querySelectorAll('.it').forEach(e=>{{const s=st[e.dataset.id]||{{}};
  lines.push([e.dataset.id,e.dataset.file,e.dataset.group,s.v||'',s.t||'',s.n||''].map(q).join(','))}});
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([lines.join('\\n')],{{type:'text/csv'}}));
 a.download='verdicts.csv';a.click()}};
count();
</script></body></html>"""
    (PACK / "index.html").write_text(page)


def main() -> None:
    (PACK / "img").mkdir(parents=True, exist_ok=True)
    v2 = volume2_items()
    items = ([i for i in v2 if i["group"] == "D"]
             + volume1_items()
             + sorted((i for i in v2 if i["group"] == "O"), key=lambda i: i["file"]))
    (PACK / "items.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    write_html(items)
    n = defaultdict(int)
    for it in items:
        n[it["group"]] += 1
    print(f"review pack: {PACK / 'index.html'}  D={n['D']} O={n['O']} "
          f"(cell located: {sum(bool(i['cell']) for i in items)} of {len(items)})")


if __name__ == "__main__":
    main()

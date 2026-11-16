"""Owner review pack for Volume II (local HTML, gitignored like Volume I's).

    cd src && uv run python -m volume2.review

Groups:
  A  Mistral and Sonnet read the cell differently. Shown: the row strip under
     its column headings, both readings, and whether the failed checks pass
     with each reading (evidence only; the owner decides what is printed).
  B  cells without a second reading (strip missed, precipitation row, a row
     missing from the OCR) - the owner reads them.
  C  checks that fail although both readers agree on every cell involved:
     most likely printed that way. Default "printed as such"; the owner can
     flag one for a closer look.

Verdicts are kept in the browser (localStorage) and exported with
"Download verdicts" to review/volume2/verdicts.csv.
"""
from __future__ import annotations

import copy
import csv
import html
import json
from collections import defaultdict

import cv2

from .checks import run_on
from .common import parse
from .pages import OUT, image
from .run import parse_all
from .second_read import SECOND, build_image

REVIEW = OUT.parents[1] / "review" / "volume2"


def where(c: dict) -> str:
    t = c["table"]
    if t in ("8.1", "8.2"):
        h = f" at {c['height_m']} m" if c.get("height_m") not in ("", None) else ""
        rel = f"release {c['release']}, " if c.get("release") else ""
        return f"Table {t}, {rel}{c['date']} {c['cst']} CST: {c['quantity']}{h}"
    if t == "12.1":
        return f"Table 12.1, release {c['release']} ({'left' if str(c['panel']) == '0' else 'right'} panel), " \
               f"{c['part']} row {c['level']}: {c['quantity']}"
    if t == "13.1":
        return f"Table 13.1, field test {c['field_test']}, row {c['level']}: {c['quantity']}"
    return f"Table {t}, release {c.get('release', '')}: {c['quantity']}"


def main() -> None:
    T, problems = parse_all()
    cells = {c["cell_id"]: c for rows in T.values() for c in rows}
    reads = list(csv.DictReader((SECOND / "reads.csv").open()))
    base_fail = defaultdict(set)
    sus_rows = list(csv.DictReader((OUT / "checks" / "suspects.csv").open()))
    for r in sus_rows:
        base_fail[r["cell_id"]].add(r["check"])

    # evidence: the checks with every disagreeing cell replaced by Sonnet's reading
    T2 = copy.deepcopy(T)
    by_id2 = {c["cell_id"]: c for rows in T2.values() for c in rows}
    dis = [r for r in reads if r["compared"] == "True" and r["agree"] == "False"]
    for r in dis:
        c = by_id2[r["cell_id"]]
        p = parse(r["sonnet_token"])
        c.update(token=p["token"], value=p["value"], kind=p["kind"],
                 status={"number": "value", "above": "value", "range": "value", "blank": "not_printed",
                         "missing": "missing", "text": "text"}.get(p["kind"], "unread"))
    fail2 = defaultdict(set)
    for r in run_on(T2):
        fail2[r["cell_id"]].add(r["check"])

    REVIEW.mkdir(parents=True, exist_ok=True)
    (REVIEW / "img").mkdir(exist_ok=True)
    items = []

    def row_img(c) -> str:
        name = f"p{c['pdf_index']}_t{c['grid_ti']}_r{c['grid_row']}.png"
        path = REVIEW / "img" / name
        if not path.exists():
            img, _ = build_image(int(c["pdf_index"]), c["table"], int(c["grid_ti"]), [int(c["grid_row"])])
            cv2.imwrite(str(path), img)
        return f"img/{name}"

    for r in sorted(dis, key=lambda r: (r["table"], int(r["pdf_index"]))):
        c = cells[r["cell_id"]]
        items.append({"group": "A", "cell_id": r["cell_id"], "where": where(c), "img": row_img(c),
                      "mistral": r["mistral_token"], "sonnet": r["sonnet_token"],
                      "checks": r["checks"],
                      "pass_mistral": False,
                      "pass_sonnet": not (fail2.get(r["cell_id"], set()) & set(r["checks"].split(";"))),
                      "unclear": r["sonnet_unclear"] == "True"})
    for r in reads:
        if r["compared"] == "False":
            c = cells[r["cell_id"]]
            items.append({"group": "B", "cell_id": r["cell_id"], "where": where(c), "img": row_img(c),
                          "mistral": r["mistral_token"], "sonnet": "", "checks": r["checks"],
                          "why": "no second reading (" + (r["alignment"] or "strip missed its line") + ")"})
    pre = defaultdict(list)
    for c in cells.values():
        if c.get("section") == "precipitation" and c["status"] == "unread":
            pre[c["pdf_index"]].append(c)
    for idx, cs in sorted(pre.items()):
        name = f"precip_p{idx}.png"
        im = image(idx)            # lower part of the page: soil section + the precipitation line
        h = im.shape[0]
        cv2.imwrite(str(REVIEW / "img" / name), cv2.resize(im[int(0.68 * h): int(0.88 * h)], None, fx=0.6, fy=0.6,
                                                            interpolation=cv2.INTER_AREA))
        cs.sort(key=lambda c: (c["date"], c["cst"]))
        items.append({"group": "B", "cell_id": f"precip:p{idx}", "where":
                      f"Table {cs[0]['table']} p{idx}: precipitation row, columns "
                      + ", ".join(c["cst"] for c in cs), "img": f"img/{name}",
                      "mistral": "", "sonnet": "", "checks": "", "cells": [c["cell_id"] for c in cs],
                      "why": f"precipitation row not read. If every one of the {len(cs)} columns shows '--', "
                             "choose 'all --'; otherwise type the tokens left to right separated by spaces"})
    for key, pr in problems.items():
        real = [p for p in pr if not p.startswith("info")]
        if real:
            idx = int(key.split("p")[-1])
            name = f"page_p{idx}.png"
            im = image(idx)
            cv2.imwrite(str(REVIEW / "img" / name), cv2.resize(im, None, fx=0.45, fy=0.45, interpolation=cv2.INTER_AREA))
            items.append({"group": "B", "cell_id": f"page:{key}", "where": f"{key}: {'; '.join(real)}",
                          "img": f"img/{name}", "mistral": "", "sonnet": "", "checks": "structure",
                          "why": "structural problem: describe what is printed (or type 'ok')"})
    # C: failures where both readers agree on every involved cell
    agree = {r["cell_id"] for r in reads if r["agree"] == "True"}
    fails = defaultdict(list)
    for r in sus_rows:
        if r["cell_id"]:
            fails[(r["check"], r["detail"])].append(r["cell_id"])
    for (chk, det), ids in sorted(fails.items()):
        if chk == "format" and all(cells[i]["token"].endswith("*") for i in ids):
            continue
        if all(i in agree for i in ids):
            c = cells[ids[0]]
            items.append({"group": "C", "cell_id": "fail:" + chk + ":" + ids[0], "where": f"{chk}: {det}",
                          "img": row_img(c), "mistral": ", ".join(cells[i]["token"] for i in ids),
                          "sonnet": "(same)", "checks": chk, "cells": ids})
    (REVIEW / "items.json").write_text(json.dumps(items, indent=1))
    write_html(items)
    n = defaultdict(int)
    for it in items:
        n[it["group"]] += 1
    print(f"review pack: {REVIEW / 'index.html'}  A={n['A']} B={n['B']} C={n['C']}")


def write_html(items: list[dict]) -> None:
    rows = []
    for k, it in enumerate(items):
        cid = html.escape(it["cell_id"])
        ev = ""
        if it["group"] == "A":
            ev = (f"<div class=ev>checks ({html.escape(it['checks'])}) with Sonnet's reading: "
                  f"<b>{'pass' if it['pass_sonnet'] else 'still fail'}</b>"
                  f"{' &middot; Sonnet marked this row unclear' if it.get('unclear') else ''}</div>")
            choice = (f"<label><input type=radio name=v{k} value=mistral> Mistral <code>{html.escape(it['mistral'])}</code></label> "
                      f"<label><input type=radio name=v{k} value=sonnet> Sonnet <code>{html.escape(it['sonnet'])}</code></label> "
                      f"<label><input type=radio name=v{k} value=other> other</label> "
                      f"<input class=t name=t{k} placeholder='as printed'>")
        elif it["group"] == "B" and it["cell_id"].startswith("precip:"):
            ev = f"<div class=ev>{html.escape(it.get('why', ''))}</div>"
            choice = (f"<label><input type=radio name=v{k} value=all_dashes> all --</label> "
                      f"<label><input type=radio name=v{k} value=other> printed:</label> "
                      f"<input class=t name=t{k} placeholder='-- -- --'>")
        elif it["group"] == "B":
            ev = f"<div class=ev>{html.escape(it.get('why', ''))}</div>"
            choice = (f"Mistral read <code>{html.escape(it['mistral'])}</code> &nbsp; "
                      f"<label><input type=radio name=v{k} value=mistral> Mistral is right</label> "
                      f"<label><input type=radio name=v{k} value=other> printed:</label> "
                      f"<input class=t name=t{k} placeholder='as printed'>")
        else:
            choice = (f"<label><input type=radio name=v{k} value=printed checked> printed as such</label> "
                      f"<label><input type=radio name=v{k} value=flag> flag a cell</label> "
                      f"<input class=t name=t{k} placeholder='which cell / what is printed'>")
        rows.append(f"<div class='it g{it['group']}' data-k={k} data-id=\"{cid}\" data-group={it['group']}>"
                    f"<div class=h><span class=g>{it['group']}</span> {html.escape(it['where'])}</div>"
                    f"<img src='{it['img']}' loading=lazy>{ev}<div class=c>{choice}</div></div>")
    page = f"""<!doctype html><html><head><meta charset=utf-8><title>Volume II review</title>
<meta name=viewport content="width=device-width, initial-scale=1">
<style>
:root{{--bg:#fff;--fg:#111;--mut:#666;--bd:#ddd;--a:#b45309;--b:#1d4ed8;--c:#4b5563}}
@media (prefers-color-scheme: dark){{:root{{--bg:#111;--fg:#eee;--mut:#aaa;--bd:#333}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}}
.it{{border:1px solid var(--bd);border-radius:8px;padding:10px;margin:12px 0}}
.it img{{max-width:100%;background:#fff;display:block;margin:6px 0}}
.g{{display:inline-block;min-width:1.4em;text-align:center;border-radius:4px;color:#fff;font-weight:600}}
.gA .g{{background:var(--a)}} .gB .g{{background:var(--b)}} .gC .g{{background:var(--c)}}
.ev{{color:var(--mut)}} .t{{width:12em}} code{{font-size:15px}}
.bar{{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--bd)}}
</style></head><body>
<div class=bar><b>Volume II review</b> &middot; A: readers disagree &middot; B: no second reading &middot;
C: both agree, check fails &nbsp; <button id=dl>Download verdicts</button> <span id=n></span></div>
{''.join(rows)}
<script>
const KEY='pg-v2-verdicts';
let st={{}}; try{{st=JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{}}
function save(){{try{{localStorage.setItem(KEY,JSON.stringify(st))}}catch(e){{}};count()}}
function count(){{const n=document.querySelectorAll('.gA,.gB').length;
 const d=[...document.querySelectorAll('.gA,.gB')].filter(e=>st[e.dataset.id]&&st[e.dataset.id].v).length;
 document.getElementById('n').textContent=d+' / '+n+' A+B decided'}}
document.querySelectorAll('.it').forEach(e=>{{const k=e.dataset.k,id=e.dataset.id,s=st[id]||{{}};
 e.querySelectorAll('input[type=radio]').forEach(r=>{{if(s.v===r.value)r.checked=true;
  r.onchange=()=>{{st[id]=Object.assign(st[id]||{{}},{{v:r.value}});save()}}}});
 const t=e.querySelector('input.t'); if(t){{t.value=s.t||'';t.oninput=()=>{{st[id]=Object.assign(st[id]||{{}},{{t:t.value}});save()}}}}}});
document.getElementById('dl').onclick=()=>{{
 const lines=['cell_id,group,verdict,typed'];
 document.querySelectorAll('.it').forEach(e=>{{const s=st[e.dataset.id]||{{}};
  const dv=e.dataset.group==='C'?'printed':'';
  lines.push([e.dataset.id,e.dataset.group,s.v||dv,s.t||''].map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(','))}});
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([lines.join('\\n')],{{type:'text/csv'}}));
 a.download='verdicts.csv';a.click()}};
count();
</script></body></html>"""
    (REVIEW / "index.html").write_text(page)


if __name__ == "__main__":
    main()

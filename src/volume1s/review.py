"""Owner review pack for the supplementary tables (local HTML, gitignored).

    cd src && uv run python -m volume1s.review

Groups (as in Volume II):
  A  Mistral and Sonnet read the cell differently: pick one, or type the print.
  C  a check fails although both readers agree: default "printed as such";
     the owner can flag it instead.

Each item shows the cell's column (with the row-label column) cut from the
page; the target column is outlined. Verdicts stay in the browser and are
exported with "Download verdicts" to review/volume1s/verdicts.csv.
"""
from __future__ import annotations

import csv
import html
import json
from collections import defaultdict

import cv2
import numpy as np

from .checks import run_on
from .pages import OUT, image
from .parse import parse_all
from .second_read import SECOND

REVIEW = OUT.parents[1] / "review" / "volume1s"


def column_rules(idx: int) -> list[int]:
    """x of the label column's left rule and the 8 rules bounding 7 release columns."""
    img = image(idx)
    h = img.shape[0]
    ink = (img[int(.2 * h):int(.9 * h)] < 128).sum(0)
    xs = np.where(ink > 0.5 * ink.max())[0]
    groups: list[list[int]] = []
    for x in xs:
        if groups and x - groups[-1][-1] <= 8:
            groups[-1].append(int(x))
        else:
            groups.append([int(x)])
    g = [int(np.mean(v)) for v in groups]
    for i in range(len(g) - 8):
        sp = np.diff(g[i:i + 9])
        if sp[0] > 300 and all(140 < s < 240 for s in sp[1:]):
            return g[i:i + 9]
    raise RuntimeError(f"page {idx}: table rules not found ({g})")


def crop(c: dict) -> np.ndarray:
    img = cv2.cvtColor(image(c["pdf_index"]), cv2.COLOR_GRAY2BGR)
    h = img.shape[0]
    if c["table"] == "6.1":
        r = column_rules(c["pdf_index"])
        j = c["grid_col"]
        y0, y1 = (0.12, 0.6) if c["block"] == 0 else (0.45, 0.95)
        y0, y1 = int(y0 * h), int(y1 * h)
        cv2.rectangle(img, (r[j] - 4, y0 + 5), (r[j + 1] + 4, y1 - 5), (0, 0, 220), 4)
        lo, hi = max(0, r[j - 1] - 10) if j > 1 else r[1] - 10, min(img.shape[1], r[min(j + 2, 8)] + 10)
        label = img[y0:y1, r[0]:r[1]]
        return np.hstack([label, img[y0:y1, lo:hi]])
    return img                                            # 5.1 / 5.4: no items expected; whole page


def main() -> None:
    T = parse_all()
    cells = {c["cell_id"]: c for t in ("5.1", "5.4", "6.1") for c in T[t]}
    reads = {r["cell_id"]: r for r in csv.DictReader((SECOND / "reads.csv").open())}
    fails = defaultdict(list)
    for f in run_on(T):
        if f["cell_id"]:
            fails[f["cell_id"]].append(f"{f['check']}: {f['message']}")
    items = []
    for cid, r in reads.items():
        if r["agree"] != "True":
            items.append({"group": "A", "cell_id": cid, "mistral": r["mistral"], "sonnet": r["sonnet"],
                          "checks": fails.get(cid, [])})
    for cid, msgs in fails.items():
        if reads.get(cid, {}).get("agree") == "True":
            items.append({"group": "C", "cell_id": cid, "mistral": reads[cid]["mistral"],
                          "sonnet": reads[cid]["sonnet"], "checks": msgs})
    (REVIEW / "img").mkdir(parents=True, exist_ok=True)
    for n, it in enumerate(items):
        c = cells[it["cell_id"]]
        it["where"] = (f"Table 6.1, release {c['release']}, {c['quantity']}"
                       + (f" {c['location']} {c['period_min']} min" if c.get("location") else "")
                       + f" (PDF p. {c['pdf_index']}, printed p. {c['printed_page']})")
        it["img"] = f"img/{n:03d}.png"
        cv2.imwrite(str(REVIEW / it["img"]), crop(c))
    (REVIEW / "items.json").write_text(json.dumps(items, indent=1))
    write_html(items)
    print(f"{len(items)} items -> {REVIEW / 'index.html'}")


def write_html(items: list[dict]) -> None:
    blocks = []
    for n, it in enumerate(items):
        cid = html.escape(it["cell_id"])
        checks = "".join(f"<li>{html.escape(m)}</li>" for m in it["checks"]) or "<li>none</li>"
        if it["group"] == "A":
            choice = (f"<label><input type=radio name=v{n} value=mistral> Mistral <b>{html.escape(it['mistral'])}</b></label> "
                      f"<label><input type=radio name=v{n} value=sonnet> Sonnet <b>{html.escape(it['sonnet'])}</b></label> "
                      f"<label><input type=radio name=v{n} value=other> other: <input name=t{n} size=8></label>")
        else:
            choice = (f"Both read <b>{html.escape(it['mistral'])}</b>. "
                      f"<label><input type=radio name=v{n} value=printed checked> printed as such</label> "
                      f"<label><input type=radio name=v{n} value=other> other / flag: <input name=t{n} size=20></label>")
        blocks.append(f"<section data-n={n} data-cid='{cid}'><h3>{n + 1}. [{it['group']}] {html.escape(it['where'])}</h3>"
                      f"<img src='{it['img']}'><ul>{checks}</ul><p>{choice}</p></section>")
    page = f"""<!doctype html><meta charset=utf-8><title>Volume I supplementary review</title>
<style>body{{font:15px system-ui;margin:2em;max-width:1100px}}img{{max-width:100%;max-height:70vh;border:1px solid #ccc}}
section{{border-bottom:2px solid #ddd;padding:1em 0}}</style>
<h1>Volume I supplementary tables: owner review</h1>
<p>A = the two readers differ: say what is printed. C = both readers agree but a check fails.
The target column is outlined in red; the row labels are on the left.</p>
<button onclick=dl()>Download verdicts</button>
{''.join(blocks)}
<button onclick=dl()>Download verdicts</button>
<script>
const K='v1s-verdicts';
function save(){{const o={{}};document.querySelectorAll('section').forEach(s=>{{const n=s.dataset.n;
 const v=document.querySelector(`input[name=v${{n}}]:checked`);o[n]={{v:v?v.value:'',t:document.querySelector(`input[name=t${{n}}]`).value}}}});
 try{{localStorage.setItem(K,JSON.stringify(o))}}catch(e){{}}}}
function load(){{let o={{}};try{{o=JSON.parse(localStorage.getItem(K)||'{{}}')}}catch(e){{}}
 for(const [n,x] of Object.entries(o)){{if(x.v){{const r=document.querySelector(`input[name=v${{n}}][value=${{x.v}}]`);if(r)r.checked=true}}
 const t=document.querySelector(`input[name=t${{n}}]`);if(t)t.value=x.t||''}}}}
document.addEventListener('change',save);document.addEventListener('input',save);load();
function dl(){{const lines=['cell_id,verdict,typed'];document.querySelectorAll('section').forEach(s=>{{const n=s.dataset.n;
 const v=document.querySelector(`input[name=v${{n}}]:checked`);const t=document.querySelector(`input[name=t${{n}}]`).value.replace(/"/g,'""');
 lines.push(`${{s.dataset.cid}},${{v?v.value:''}},"${{t}}"`)}});
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([lines.join('\\n')],{{type:'text/csv'}}));
 a.download='verdicts.csv';a.click()}}
</script>"""
    (REVIEW / "index.html").write_text(page)


if __name__ == "__main__":
    main()

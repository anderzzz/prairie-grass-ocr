"""Mistral OCR as the primary reader (page-level document OCR).

Each page image (after deskew, exactly what the rest of the pipeline sees)
is sent once to a pinned model; the raw response is cached on disk (and the
pilot pages' responses are committed), so the dataset can be rebuilt without
the service. The HTML table in the response is mapped onto the pipeline's
own cell grid; the grid, not Mistral, decides which cell a value belongs to,
and every disagreement between the two is recorded:

* Table 5.2: 14 cells per row (two panels: inner post, 800 m post, five
  arcs). Data row i is the pipeline's row i of each panel. Mistral's 800 m
  and inner post numbers are compared with the expected keys.
* Table 5.3: rows carry tower (rowspan) and height; run columns are matched
  by position to the pipeline's columns, because Mistral's header reading is
  unreliable. Heights are compared with the expected ones.
"""
from __future__ import annotations

import base64
import html
import os
import re

import cv2
import numpy as np

from .cache import cached

MODEL = os.environ.get("PGOCR_MISTRAL_MODEL", "mistral-ocr-4-1")
PRICE_PER_PAGE = {"mistral-ocr-4-1": 4 / 1000}
HEIGHTS = ["17.5", "13.5", "10.5", "7.5", "4.5", "2.5", "1.5", "1.0", "0.5"]

CELL_RE = re.compile(r"<t([dh])([^>]*)>(.*?)</t[dh]>", re.S)
ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)


class MistralUnavailable(RuntimeError):
    pass


def ocr_page(img: np.ndarray, model: str = MODEL) -> dict:
    """Raw Mistral OCR response for a page image (cached)."""
    def run():
        if not os.environ.get("MISTRAL_API_KEY"):
            raise MistralUnavailable("no cached response and MISTRAL_API_KEY not set")
        from mistralai.client import Mistral
        ok, buf = cv2.imencode(".png", img)
        uri = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()
        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        r = client.ocr.process(model=model, document={"type": "image_url", "image_url": uri},
                               table_format="html", confidence_scores_granularity="word")
        return r.model_dump()

    return cached("reader_mistral_page", {"model": model, "table_format": "html",
                                          "conf": "word"}, img, run)


def table_rows(table: dict) -> list[list[dict]]:
    """<td> cells per row: text, rowspan and the minimum word confidence."""
    content = table["content"]
    words = table.get("word_confidence_scores") or []
    rows = []
    for rm in ROW_RE.finditer(content):
        cells = []
        for cm in CELL_RE.finditer(rm.group(1)):
            if cm.group(1) != "d":
                continue
            a, b = rm.start(1) + cm.start(3), rm.start(1) + cm.end(3)
            confs = [w["confidence"] for w in words if a <= w["start_index"] < b]
            txt = html.unescape(re.sub(r"<[^>]+>", " ", cm.group(3))).strip()
            span = re.search(r'rowspan="(\d+)"', cm.group(2))
            cells.append({"text": txt, "conf": min(confs) if confs else None,
                          "rowspan": int(span.group(1)) if span else 1})
        if cells:
            rows.append(cells)
    return rows


def header_run(resp: dict) -> str | None:
    """Run label from Mistral's page text ('RUN NO. 35-S' -> '35S')."""
    md = " ".join(p.get("markdown") or "" for p in resp.get("pages") or [])
    m = re.search(r"RUN\s+NO\.?\s*(\d{1,2})\s*(-\s*S)?\b", md, re.I)
    return None if not m else m.group(1) + ("S" if m.group(2) else "")


def _main_table(resp: dict) -> tuple[dict | None, list[str]]:
    pages = resp.get("pages") or []
    tables = [t for p in pages for t in (p.get("tables") or [])]
    if not tables:
        return None, ["Mistral returned no table"]
    if len(tables) > 1:
        tables.sort(key=lambda t: len(t["content"]), reverse=True)
        return tables[0], [f"Mistral returned {len(tables)} tables; used the largest"]
    return tables[0], []


DATA_TOKEN = re.compile(r"^(|M|\d[\d.,\s]*\*?|[.,]\d[\d.,\s]*\*?)$")


def drop_header_rows(rows: list[list[dict]], problems: list[str]) -> list[list[dict]]:
    """Mistral sometimes returns a column-heading row ('50m', 'POST NO.') as a
    <td> row. A row with any token that is not blank, M or numeric-looking is
    a heading, not data (post-pilot fix, see REPORT addendum)."""
    out = []
    for i, r in enumerate(rows):
        if any(not DATA_TOKEN.match(c["text"]) for c in r):
            problems.append(f"Mistral row {i}: heading row skipped: {[c['text'] for c in r][:7]}")
            continue
        out.append(r)
    return out


def map_arc(resp: dict, cells: list) -> tuple[dict, list[str]]:
    """cell_id -> {text, conf, key_read, key_ok}; plus page-level problems."""
    table, problems = _main_table(resp)
    if table is None:
        return {}, problems
    rows = drop_header_rows(table_rows(table), problems)
    by_key = {(c.group, c.position): c.cell_id for c in cells}
    posts800 = sorted({int(c.position) for c in cells if c.group == "800"})
    panels = (posts800[:45], posts800[45:])
    out: dict = {}
    for i, r in enumerate(rows):
        if len(r) != 14:
            problems.append(f"Mistral row {i}: {len(r)} cells instead of 14")
            continue
        for exp_posts, off in zip(panels, (0, 7)):
            if i >= len(exp_posts):
                if any(c["text"] for c in r[off: off + 7]):
                    problems.append(f"Mistral row {i}: values beyond the expected rows")
                continue
            p800 = exp_posts[i]
            vals, confs = [c["text"] for c in r[off + 2: off + 7]], [c["conf"] for c in r[off + 2: off + 7]]
            got = r[off + 1]["text"]
            cid = by_key.get(("800", str(p800)))
            if cid:
                out[cid] = {"text": vals[4], "conf": confs[4], "key_read": got,
                            "key_ok": got == str(p800)}
            if p800 % 2 == 1:
                inner = str((p800 + 1) // 2)
                got_i = r[off]["text"]
                for d, v, cf in zip(("50", "100", "200", "400"), vals[:4], confs[:4]):
                    cid = by_key.get((d, inner))
                    if cid:
                        out[cid] = {"text": v, "conf": cf, "key_read": got_i,
                                    "key_ok": got_i == inner and got == str(p800)}
            elif any(vals[:4]):
                problems.append(f"Mistral row {i} (800 m post {p800}): inner-arc value on an "
                                f"even row: {vals[:4]}")
    if len(rows) < max(len(p) for p in panels):
        problems.append(f"Mistral table has {len(rows)} data rows, expected {max(len(p) for p in panels)}")
    return out, problems


def map_tower(resp: dict, cells: list, col_runs: list[dict]) -> tuple[dict, list[str]]:
    table, problems = _main_table(resp)
    if table is None:
        return {}, problems
    rows = table_rows(table)
    by_key = {(c.group, c.position, c.run): c.cell_id for c in cells}
    used = [c for c in col_runs]
    nonblank = [c for c in col_runs if c.get("run")]
    out: dict = {}
    tower = 0
    for r in rows:
        if r[0]["rowspan"] > 1 or (r[0]["text"] not in HEIGHTS and len(r) > 1 and r[1]["text"] in HEIGHTS):
            tower += 1
            r = r[1:]
        if len(r) == len(used) + 1:
            cols = used
        elif len(r) == len(nonblank) + 1:
            cols = nonblank
        else:
            problems.append(f"Mistral tower {tower}: row with {len(r)} cells, expected {len(used) + 1}")
            continue
        h = r[0]["text"]
        if h not in HEIGHTS:
            problems.append(f"Mistral tower {tower}: unexpected height label '{h}'")
            continue
        for c, cell in zip(cols, r[1:]):
            if not c.get("run"):
                if cell["text"]:
                    problems.append(f"Mistral: value '{cell['text']}' under blank run header {c['col']}")
                continue
            cid = by_key.get((str(tower), h, c["run"]))
            if cid:
                out[cid] = {"text": cell["text"], "conf": cell["conf"], "key_read": h, "key_ok": True}
    if tower != 6:
        problems.append(f"Mistral table has {tower} tower groups, expected 6")
    return out, problems

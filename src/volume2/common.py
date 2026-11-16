"""Shared pieces for the Volume II table parsers.

Every parser emits one record per printed cell with the raw token, its parsed
value and a status. Values come from the token only; nothing is filled,
smoothed or corrected (same rules as Volume I).

Token conventions printed in Volume II:
  --        missing ("missing data due to instrument failure", Table 10.1 legend;
            used the same way in Tables 8.x, 12.1, 13.1)
  (x)       estimated value (Table 10.1 legend)
  x*        value carrying a footnote (footnote text kept per page)
  >100      relative humidity above 100 % (Table 13.1), kept as printed
  a to b    a range (Table 11.1)
  blank     nothing printed
"""
from __future__ import annotations

import re
from functools import lru_cache

import json

from extract.cache import CACHE_DIR, key_for
from extract.mistral import MODEL, ocr_page
from extract.pdfio import REPO

from .htmlgrid import grid, outside
from .pages import image

MISTRAL_CONF_MIN = 0.95  # Vol II: confidence barely predicts check failures (see docs/volume2.md)

NUM = r"[+-]?\s?(?:\d+\.?\d*|\.\d+)"
NUM_RE = re.compile(rf"^({NUM})$")


INDEX = REPO / "output" / "volume2" / "mistral" / "index.json"


def cached_response(name: str, make_img) -> dict:
    """Mistral response for a named image (page or strip). The image -> cache-key
    mapping is remembered in INDEX so later runs skip re-rendering the image."""
    idx_map = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    k = idx_map.get(name)
    if k:
        path = CACHE_DIR / "reader_mistral_page" / k[:2] / f"{k}.json"
        if path.exists():
            return json.loads(path.read_text())
    img = make_img()
    resp = ocr_page(img)
    idx_map[name] = key_for("reader_mistral_page", {"model": MODEL, "table_format": "html", "conf": "word"}, img)
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(idx_map, indent=0, sort_keys=True))
    return resp


@lru_cache(maxsize=None)
def response(idx: int) -> dict:
    return cached_response(f"page {idx}", lambda: image(idx))


def page_tables(idx: int) -> list[list[list]]:
    """Tables on the page as grids of (text, conf) (None for colspan filler)."""
    out = []
    for p in response(idx).get("pages") or []:
        for t in p.get("tables") or []:
            out.append(grid(t["content"], t.get("word_confidence_scores"), with_conf=True))
    return out


def page_markdown(idx: int) -> str:
    return "\n\n".join(p.get("markdown") or "" for p in response(idx).get("pages") or [])


def page_text(idx: int) -> str:
    return outside(page_markdown(idx))


def printed_page(idx: int) -> int | None:
    m = re.search(r"(?:^|\n)\s*(\d{1,3})\s*$", page_text(idx).strip())
    return int(m.group(1)) if m else None


def norm(tok: str) -> str:
    t = tok.strip().replace("−", "-").replace("–", "-").replace("—", "--")
    t = re.sub(r"(?<=[-+])\s+(?=[\d.])", "", t)       # "- .28" -> "-.28"
    t = re.sub(r"(?<=\d),(?=\d)", ".", t) if re.fullmatch(r"[+-]?\d+,\d+", t) else t
    return t


def parse(tok: str) -> dict:
    """{kind, value, estimated, footnote} from a printed token."""
    t = norm(tok)
    d = {"kind": "unread", "value": None, "estimated": False, "footnote": False, "token": t}
    if t == "":
        d["kind"] = "blank"
        return d
    if re.fullmatch(r"-{2,}|- -", t):
        d["kind"] = "missing"
        return d
    core = t
    if core.endswith("*"):
        d["footnote"], core = True, core.rstrip("*").strip()
    if re.fullmatch(rf"\(\s*{NUM}\s*\)", core):
        d["estimated"], core = True, core.strip("() ")
    if m := re.fullmatch(rf">\s*({NUM})", core):
        d.update(kind="above", value=float(m.group(1).replace(" ", "")))
        return d
    if m := re.fullmatch(rf"({NUM})\s+to\s+({NUM})", core):
        d.update(kind="range", value=None, lo=float(m.group(1).replace(" ", "")),
                 hi=float(m.group(2).replace(" ", "")))
        return d
    if NUM_RE.match(core):
        d.update(kind="number", value=float(core.replace(" ", "")))
    elif re.fullmatch(r"[A-Za-z][A-Za-z .'/]*", core):
        # a printed word in a value cell ("rain", "Calm", "MB" = motorboating, "No Data"): kept as text
        d["kind"] = "text"
    return d


STATUS = {"number": "value", "above": "value", "range": "value", "blank": "not_printed",
          "missing": "missing", "unread": "unread", "text": "text"}


def record(base: dict, cell, **extra) -> dict:
    """One output row from a (text, conf) cell."""
    text, conf = cell if isinstance(cell, tuple) else (cell or "", None)
    p = parse(text or "")
    flags = []
    if p["kind"] == "unread":
        flags.append("token does not parse")
    if conf is not None and conf < MISTRAL_CONF_MIN and p["kind"] not in ("blank", "missing"):
        flags.append(f"low Mistral confidence {conf:.3f}")
    r = dict(base)
    r.update(extra)
    r.update({"token": p["token"], "value": p["value"], "status": STATUS[p["kind"]],
              "kind": p["kind"], "estimated": p["estimated"], "footnote": p["footnote"],
              "conf": None if conf is None else round(conf, 4), "flags": "; ".join(flags)})
    if p["kind"] == "range":
        r["value_lo"], r["value_hi"] = p["lo"], p["hi"]
    return r


def txt(cell) -> str:
    if cell is None:
        return ""
    return cell[0] if isinstance(cell, tuple) else cell

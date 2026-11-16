"""Send every Volume II table page to Mistral OCR once (cached, like Volume I).

    cd src && uv run python -m volume2.ocr [--dry-run]

Writes output/volume2/mistral/p<idx>.md (page markdown with HTML tables) for
inspection; the raw responses live in cache/reader_mistral_page/.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from extract.cache import key_for, CACHE_DIR
from extract.mistral import MODEL, PRICE_PER_PAGE, ocr_page

from .pages import OUT, all_pages, image


def is_cached(img) -> bool:
    k = key_for("reader_mistral_page", {"model": MODEL, "table_format": "html", "conf": "word"}, img)
    return (CACHE_DIR / "reader_mistral_page" / k[:2] / f"{k}.json").exists()


def one(idx: int, dry: bool) -> tuple[int, bool, int]:
    img = image(idx)
    hit = is_cached(img)
    if dry:
        return idx, hit, 0
    for attempt in range(6):
        try:
            resp = ocr_page(img)
            break
        except Exception as e:  # noqa: BLE001 - 503 "high load" from the service
            if "503" not in str(e) and "429" not in str(e) or attempt == 5:
                raise
            time.sleep(10 * 2 ** attempt)
    md = "\n\n".join(p.get("markdown") or "" for p in resp.get("pages") or [])
    for p in resp.get("pages") or []:
        for t in p.get("tables") or []:
            md = md.replace(f"[{t['id']}]({t['id']})", t["content"])
    d = OUT / "mistral"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"p{idx}.md").write_text(md)
    return idx, hit, len(md)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    pages = list(all_pages())
    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(lambda i: one(i, a.dry_run), pages))
    new = sum(not h for _, h, _ in res)
    cost = new * PRICE_PER_PAGE[MODEL]
    print(f"{len(pages)} pages, {len(pages) - new} cached, {new} new calls "
          f"({'would cost' if a.dry_run else 'cost'} ~${cost:.2f})")
    if not a.dry_run:
        spend = OUT / "mistral_spend.json"
        prev = json.loads(spend.read_text()) if spend.exists() else {"calls": 0, "usd": 0.0}
        spend.write_text(json.dumps({"calls": prev["calls"] + new,
                                     "usd": round(prev["usd"] + cost, 4), "model": MODEL}))


if __name__ == "__main__":
    main()

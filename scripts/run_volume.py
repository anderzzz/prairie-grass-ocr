"""Run the frozen extraction over every Table 5.2 / 5.3 page of Volume I.

    uv run python scripts/run_volume.py [--workers 3] [--no-offline]

Uses the frozen pipeline (src/extract, tag extraction-frozen) unchanged; this
driver only chooses pages and where to write. Pages come from
docs/page_inventory.csv plus EXTRA_PAGES (table pages that recon misses,
confirmed by the project owner). Output: output/volume1/extracted/p<idx>.csv
and .meta.json; no crops (they are cut on demand for review).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "output" / "volume1"
# PDF 200 (printed 187): a Table 5.2 page that recon does not detect (owner confirmed)
EXTRA_PAGES = [{"pdf_index": 200, "table": "5.2", "runs": ""}]


def pages() -> list[dict]:
    rows = list(csv.DictReader((REPO / "docs" / "page_inventory.csv").open()))
    out = [{"pdf_index": int(r["pdf_index"]), "table": r["table"], "runs": r["runs"]}
           for r in rows if r["table"] in ("5.2", "5.3")]
    have = {p["pdf_index"] for p in out}
    out += [p for p in EXTRA_PAGES if p["pdf_index"] not in have]
    return sorted(out, key=lambda p: p["pdf_index"])


def one(entry: dict, offline: bool) -> tuple[int, str]:
    from extract import pipeline as P
    from extract.readers import default_readers
    idx = entry["pdf_index"]
    try:
        if entry["table"] == "5.2":
            run_label, note = P.page_run_label(entry)
        else:
            run_label, note = "", ""
        readers = default_readers() if offline else []
        rows, meta = P.read_page(idx, entry["table"], run_label, note, P.PRESETS["default"],
                                 readers, None)
        meta.update({"readers": {r.name: r.describe() for r in readers}, "offline": offline})
        P.write_rows(OUT / "extracted" / f"p{idx}.csv", rows)
        (OUT / "extracted" / f"p{idx}.meta.json").write_text(json.dumps(meta, indent=1, default=str))
        m = meta["mistral"]
        return idx, (f"{len(rows)} cells, {sum(r['flags_any'] for r in rows)} flagged, "
                     f"mistral mapped {m['cells_mapped']}, problems {len(m['problems'])}")
    except Exception as e:  # noqa: BLE001 - one bad page must not stop the volume
        return idx, f"FAILED: {type(e).__name__}: {e}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--no-offline", action="store_true")
    ap.add_argument("--pages", default="", help="comma-separated PDF indices (default: all)")
    a = ap.parse_args()
    ps = pages()
    if a.pages:
        want = {int(x) for x in a.pages.split(",")}
        ps = [p for p in ps if p["pdf_index"] in want]
    (OUT / "extracted").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = []
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(one, p, not a.no_offline) for p in ps]
        for f in as_completed(futs):
            idx, msg = f.result()
            line = f"p{idx}: {msg}"
            print(line, flush=True)
            log.append(line)
    (OUT / "run_log.txt").write_text("\n".join(sorted(log)) + f"\n{len(ps)} pages in {time.time() - t0:.0f}s\n")


if __name__ == "__main__":
    main()

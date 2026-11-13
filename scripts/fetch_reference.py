"""Download the independent reference transcription into reference/.

reference/ is gitignored and is read only by scoring/ (never by
src/extract/). SHA-256 checksums are written to reference/SHA256SUMS and to
scoring/reference_checksums.json (committed), so a later run can tell whether
the answer key changed. Files already present are not re-downloaded.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEST = REPO / "reference"
SOURCES = {
    "PGARCS.txt": "https://www.harmo.org/jsirwin/PGARCS.txt",
    "PGVertConc.txt": "https://www.harmo.org/jsirwin/PGVertConc.txt",
    "D6589_UGDesign2_Table_2.pdf": "https://www.harmo.org/jsirwin/D6589_UGDesign2_Table_2.pdf",
}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    DEST.mkdir(exist_ok=True)
    record, failed = {}, []
    for name, url in SOURCES.items():
        path = DEST / name
        if not path.exists():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "pg-ocr-pilot/0.1"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                path.write_bytes(data)
                fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
            except Exception as e:  # noqa: BLE001
                print(f"FAILED {url}: {e}", file=sys.stderr)
                failed.append(name)
                continue
        else:
            fetched = "already present"
        record[name] = {"url": url, "sha256": sha256(path), "bytes": path.stat().st_size,
                        "fetched": fetched}
        print(f"{record[name]['sha256']}  {name}")
    (DEST / "SHA256SUMS").write_text("".join(f"{v['sha256']}  {k}\n" for k, v in record.items()))
    out = REPO / "scoring" / "reference_checksums.json"
    old = json.loads(out.read_text()) if out.exists() else {}
    for k, v in record.items():
        if k in old and old[k]["sha256"] != v["sha256"]:
            print(f"WARNING: {k} checksum differs from the recorded one", file=sys.stderr)
        if k in old and v["fetched"] == "already present":
            v["fetched"] = old[k]["fetched"]
    out.write_text(json.dumps(record, indent=1) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Status of a cell follows the printed token only, and the grid never creates
a cell where no sampler stood (so "no_station" cannot be confused with a
printed blank)."""
import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from extract import manual_keys  # noqa: E402
from extract.pipeline import STATUS, parse  # noqa: E402

VOL = ROOT / "output" / "volume1" / "extracted"
PILOT = ROOT / "output" / "extracted"


def test_status_mapping_from_printed_token():
    assert STATUS[parse("")["kind"]] == "not_measurable"
    assert STATUS[parse("M")["kind"]] == "missing"
    assert STATUS[parse("0.045")["kind"]] == "value"
    assert STATUS[parse("2200*")["kind"]] == "value"


def test_inferred_manual_key_keeps_its_method():
    d = {"reviewer": "owner", "date": "d0", "arc_pages": {200: {"run": "66", "method": "inferred",
                                                                 "date": "d1"}}}
    run, src, _ = manual_keys.arc_run(200, "", d)
    assert run == "66" and "inferred" in src and "d1" in src


def _rows():
    paths = sorted(VOL.glob("p*.csv")) or sorted(PILOT.glob("p*.csv"))
    if not paths:
        pytest.skip("no extraction output yet")
    for p in paths:
        with p.open() as f:
            yield from csv.DictReader(f)


def test_no_cell_without_a_sampler():
    for r in _rows():
        if r["table"] != "5.2":
            continue
        post = int(r["post"])
        limit = 181 if r["arc_m"] == "800" else 91
        assert 1 <= post <= limit, (r["cell_id"], post)


def test_status_never_invents_a_value():
    for r in _rows():
        if "status" not in r:
            pytest.skip("output predates the status column")
        if r["status"] != "value":
            assert r["value"] in ("", "None"), r["cell_id"]
        else:
            # a printed zero ("0.000", "0") exists in a few cells and is kept
            # as printed; it is never produced from a blank
            assert float(r["value"]) >= 0 and r["consensus_token"].strip("0.") == "" or float(r["value"]) > 0, r["cell_id"]

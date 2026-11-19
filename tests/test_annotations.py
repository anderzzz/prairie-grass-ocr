"""The annotations file and the dataset columns must say the same thing."""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from publish.annotations import (CATEGORIES, OUT, QUALITY_CATEGORY, QUALITY_FILES, REPO, V1, V2,  # noqa: E402
                                 build)

DATASET_FILES = dict(QUALITY_FILES) | {"volume1/arcs.csv": V1 / "arcs.csv",
                                       "volume1/towers.csv": V1 / "towers.csv"}


@pytest.fixture(scope="module")
def anns():
    return build()


def _rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def test_every_marked_cell_is_annotated_and_nothing_else(anns):
    by_cell = {(a["file"], a["cell_id"], a["category"]) for a in anns if a["scope"] == "cell"}
    expected = set()
    for file, path in DATASET_FILES.items():
        for r in _rows(path):
            cat = QUALITY_CATEGORY.get(r.get("quality", ""))
            if cat:
                expected.add((file, r["cell_id"], cat))
            if r.get("suspect") == "True":
                expected.add((file, r["cell_id"], "suspected_original_error"))
    assert by_cell == expected


def test_every_annotated_cell_exists(anns):
    ids = {f: {r["cell_id"] for r in _rows(p)} for f, p in DATASET_FILES.items()}
    missing = [a for a in anns if a["scope"] == "cell" and a["cell_id"] not in ids[a["file"]]]
    assert not missing


def test_key_annotations_select_rows(anns):
    for a in anns:
        if a["scope"] != "key":
            continue
        rows = _rows(V1 / a["file"].split("/")[1] if a["file"].startswith("volume1")
                     else V2 / a["file"].split("/")[1])
        hit = [r for r in rows if all(r.get(k) == v for k, v in a["match"].items())]
        assert hit, a


def test_errata_match_erratum_column(anns):
    errata = {(a["match"]["release"]) for a in anns
              if a["category"] == "suspected_original_error" and a["scope"] == "key"}
    rows = _rows(V2 / "table_10.1.csv")
    assert errata == {r["release"] for r in rows if r["erratum"]}


def test_schema(anns):
    assert len({a["id"] for a in anns}) == len(anns)
    for a in anns:
        assert a["category"] in CATEGORIES
        assert a["statement"]
        assert (a["cell_id"] is not None) == (a["scope"] == "cell")
        assert (a["match"] is not None) == (a["scope"] == "key")


def test_written_file_is_current(anns):
    if not OUT.exists():
        pytest.skip("make annotations not run")
    written = [json.loads(line) for line in OUT.open()]
    assert written == anns, "output/publish/annotations.jsonl is stale: run make annotations"

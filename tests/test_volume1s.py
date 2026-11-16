"""Volume I supplementary tables (5.1, 5.4, 6.1): keys and printed shape, from the
committed Mistral cache and second readings."""
import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DS = ROOT / "output" / "volume1" / "dataset"

pytestmark = pytest.mark.skipif(not (DS / "source_strength.csv").exists(), reason="dataset not built")


def rows(name):
    return list(csv.DictReader((DS / name).open()))


def test_source_strength_covers_every_run_once():
    r = rows("source_strength.csv")
    runs = [x["run"] for x in r]
    assert len(runs) == 68 and len(set(runs)) == 68
    assert {x["run"] for x in rows("arcs.csv")} == set(runs) if (DS / "arcs.csv").exists() else True
    assert all(30 <= float(x["value"]) <= 110 for x in r)


def test_evaporation_factors_shape():
    r = rows("evaporation_correction.csv")
    assert len(r) == 70 * 5                       # 68 runs + printed rows 63, 64
    blank = {x["run"] for x in r if x["status"] == "missing"}
    assert {"30", "31", "63", "64"} <= blank
    assert all(0.8 <= float(x["value"]) <= 1.0 for x in r if x["status"] == "value")


def test_slow_response_wind_keys():
    r = rows("slow_response_wind.csv")
    rel = {x["release"] for x in r}
    assert len(rel) == 68 and "63" not in rel and "64" not in rel
    data = [x for x in r if not x["quantity"].startswith("key")]
    assert len(data) == 68 * 12
    assert {x["quantity"] for x in data} == {"wind_speed", "wind_direction", "sigma_theta"}
    # run 3: "no slow-response data" (legend p. 209)
    assert all(x["status"] == "missing" for x in data if x["release"] == "3")

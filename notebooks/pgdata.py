"""Load the reviewed Volume I dataset for exploration.

Reads output/volume1/dataset/{arcs,towers}.csv (built by `make dataset`).
No reference data is read here.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "output" / "volume1" / "dataset"
ARCS_M = [50, 100, 200, 400, 800]
TOWER_HEIGHTS_M = [0.5, 1.0, 1.5, 2.5, 4.5, 7.5, 10.5, 13.5, 17.5]


def run_order(run: str) -> float:
    """Printed order: 35S before 35, 48S before 48."""
    n = int("".join(c for c in str(run) if c.isdigit()))
    return n + (0.0 if str(run).endswith("S") else 0.5)


def _common(df: pd.DataFrame) -> pd.DataFrame:
    df["run"] = df["run"].astype(str)
    df["run_order"] = df["run"].map(run_order)
    df["concentration_mg_m3"] = pd.to_numeric(df["concentration_mg_m3"], errors="coerce")
    for c in ("estimated", "reviewed", "flagged"):
        df[c] = df[c].astype(str).eq("True")
    df["status"] = pd.Categorical(df["status"], ["value", "not_measurable", "missing", "unread"])
    return df


def arcs() -> pd.DataFrame:
    """One row per arc sampler cell (Table 5.2). bearing_unwrapped runs 270..450
    so that west -> north -> east is continuous."""
    df = _common(pd.read_csv(DATASET / "arcs.csv", dtype={"run": str, "token": str}, keep_default_na=False))
    df["bearing_unwrapped"] = df["bearing_deg"].where(df["bearing_deg"] >= 270, df["bearing_deg"] + 360)
    return df


def towers() -> pd.DataFrame:
    """One row per tower sampler cell (Table 5.3)."""
    return _common(pd.read_csv(DATASET / "towers.csv", dtype={"run": str, "token": str}, keep_default_na=False))


def runs_in_order(df: pd.DataFrame) -> list[str]:
    return df.drop_duplicates("run").sort_values("run_order")["run"].tolist()

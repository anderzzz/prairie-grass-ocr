"""Manual key overrides (config/manual_keys.yaml).

Only run labels can be set here, never cell values. The pipeline's own
reading is always kept next to the manual one.
"""
from __future__ import annotations

import yaml

from .pdfio import REPO

PATH = REPO / "config" / "manual_keys.yaml"


def load() -> dict:
    if not PATH.exists():
        return {"arc_pages": {}, "tower_pages": {}}
    d = yaml.safe_load(PATH.read_text()) or {}
    d.setdefault("arc_pages", {})
    d.setdefault("tower_pages", {})
    return d


def provenance(d: dict) -> str:
    return f"manual ({d.get('reviewer', '?')}, {d.get('date', '?')})"


def arc_run(idx: int, auto: str, d: dict | None = None) -> tuple[str, str, str]:
    """-> (run, key_source, note)."""
    d = d if d is not None else load()
    man = d["arc_pages"].get(idx)
    if man is None:
        return auto, "pipeline", ""
    src = provenance(d)
    if isinstance(man, dict):  # {run, method, date}: a key not read from the header
        src = f"manual ({d.get('reviewer', '?')}, {man.get('date', d.get('date', '?'))}; {man.get('method', '?')})"
        man = man["run"]
    man = str(man)
    note = "" if man == auto else f"pipeline read run '{auto or '?'}', manual key '{man}'"
    return man, src, note


def apply_tower(idx: int, col_runs: list[dict], d: dict | None = None) -> list[dict]:
    """Overwrite column runs from the manual file, keeping the auto reading."""
    d = d if d is not None else load()
    man = d["tower_pages"].get(idx)
    if man is None:
        for c in col_runs:
            c["key_source"], c["run_auto"] = "pipeline", c.get("run")
        return col_runs
    if isinstance(man, list):
        man = {f"c{i + 1}": v for i, v in enumerate(man)}
    for c in col_runs:
        c["run_auto"], c["source_auto"] = c.get("run"), c.get("source")
        if c["col"] in man:
            v = man[c["col"]]
            c["key_source"] = provenance(d)
            if v is None:
                c["run"], c["source"] = None, "blank header"
            else:
                c["run"], c["source"] = str(v), "manual"
        else:
            c["key_source"] = "pipeline"
    return col_runs

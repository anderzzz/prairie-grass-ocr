"""Curators' annotations on the published datasets -> output/publish/annotations.jsonl

    cd src && uv run python -m publish.annotations      (make annotations)

One JSON object per line, one statement per object. A statement is something
the curators say about the data beyond the printed token: a suspected error in
the 1958 original, a key decided by a person, a reading that is doubtful or was
settled by context or by rule, a unit kept as printed, an excluded table.

Sources (nothing new is decided here):
  config/suspect_values.yaml        suspected original errors (Volume I, Table 6.1)
  config/volume2_keys.yaml          Volume II keys, errata, conventions, exclusions
  config/manual_keys.yaml           Volume I run keys (only the inferred ones)
  output/*/dataset/*.csv            `quality` per cell (Volume II, Tables 5.1/5.4/6.1)
  output/volume2/second_read/reads.csv   the two readings of disputed cells

tests/test_annotations.py checks that every cell the datasets mark (suspect,
erratum, a quality other than owner/two_readers/single_reader) has exactly
the annotation it should, and that every annotated cell exists.

Like the dataset builds, this never reads the reference transcription.

Fields:
  id            stable hash of (category, file, target)
  scope         cell | key | table
  file          path inside the published dataset, e.g. volume2/table_8.1.csv
  cell_id       scope = cell: the row's cell_id
  match         scope = key: column values selecting the affected rows
  field         the column the statement is about, where it is not `token`/`value`
  category      see CATEGORIES
  printed       the printed token (as in the dataset)
  alternative   the other candidate reading or the suspected intended value, else null
  statement     one sentence for people
  evidence      the basis, as recorded by whoever decided
  checks_failed consistency checks the printed value fails (Volume II, 6.1)
  decided_by    project owner | Claude (owner-approved method) | rule
  date          ISO date of the decision
  source        the config or dataset file the statement comes from
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config"
V1 = REPO / "output" / "volume1" / "dataset"
V2 = REPO / "output" / "volume2" / "dataset"
READS = REPO / "output" / "volume2" / "second_read" / "reads.csv"
OUT = REPO / "output" / "publish" / "annotations.jsonl"

CATEGORIES = {
    "suspected_original_error": "Read correctly, but the curators suspect a typing error in the 1958 "
                                "report. The printed value is kept; `alternative` is the suspected "
                                "intended value.",
    "printed_inconsistent": "The owner confirmed the print, yet it fails a consistency check. No "
                            "correction is proposed.",
    "doubtful_reading": "The readers disagree and nothing decided between them; the first reader's "
                        "(Mistral's) token is kept, `alternative` is the other reading.",
    "reading_decided_by_context": "The readers disagreed; the kept reading fits the height profile or "
                                  "neighbouring hours and the alternative does not. Decided by "
                                  "Claude under the owner's method, not by the owner.",
    "reading_decided_by_rule": "The readers disagreed and the owner left it open; the reading under "
                               "which the failed checks pass was kept.",
    "illegible": "The owner could not read the print; no value.",
    "key_decided": "A row key (run, date) was smudged or unreadable and was set by a person.",
    "unit_as_printed": "The printed unit or heading is wrong; the dataset keeps it as printed.",
    "excluded_table": "A printed table left out of the dataset.",
    "unverified_transcription": "Kept as machine-read, not reviewed cell by cell.",
}

# quality label -> category, for cells settled in review or follow-up
QUALITY_CATEGORY = {
    "printed_inconsistent": "printed_inconsistent",
    "doubtful": "doubtful_reading",
    "context": "reading_decided_by_context",
    "rule": "reading_decided_by_rule",
    "illegible": "illegible",
}

# Volume I small tables use the same quality labels as Volume II
QUALITY_FILES = ([(f"volume1/{p.name}", p) for p in sorted(V1.glob("*.csv"))
                  if p.name not in ("arcs.csv", "towers.csv", "run_remarks.csv")]
                 + [(f"volume2/{p.name}", p) for p in sorted(V2.glob("table_*.csv"))])

DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")
PAIR_RE = re.compile(r"\('([^']*)' vs '([^']*)'\)")


def _id(category: str, file: str, target: str) -> str:
    return hashlib.sha1(f"{category}|{file}|{target}".encode()).hexdigest()[:12]


def _ann(category: str, file: str, *, scope: str = "cell", cell_id: str | None = None,
         match: dict | None = None, field: str | None = None, printed: str | None = None,
         alternative: str | None = None, statement: str, evidence: str = "",
         checks_failed: list[str] | None = None, decided_by: str, date: str | None,
         source: str) -> dict:
    target = {"cell": cell_id or "", "key": json.dumps(match, sort_keys=True) + (field or ""),
              "table": ""}[scope]
    assert category in CATEGORIES, category
    return {"id": _id(category, file, target), "scope": scope, "file": file, "cell_id": cell_id,
            "match": match, "field": field, "category": category, "printed": printed,
            "alternative": alternative, "statement": statement, "evidence": evidence,
            "checks_failed": checks_failed or [], "decided_by": decided_by, "date": date,
            "source": source}


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _second_readings() -> dict[str, tuple[str, str]]:
    """cell_id -> (mistral_token, sonnet_token), Volume II second readings."""
    return {r["cell_id"]: (r["mistral_token"], r["sonnet_token"]) for r in _rows(READS)}


def _alternative(row: dict, reads: dict) -> str | None:
    """The candidate reading that was not kept."""
    m = PAIR_RE.search(row.get("value_source", ""))
    if m:
        a, b = m.groups()
        return b if a == row["token"] else a
    pair = reads.get(row["cell_id"])
    if pair:
        other = [t for t in pair if t and t != row["token"]]
        if other:
            return other[0]
    return None


def _decider(q: str, row: dict) -> tuple[str, str | None]:
    text = row.get("value_source", "") + " " + row.get("review_note", "")
    d = DATE_RE.search(text)
    if q in ("context",) or "owner-approved method" in text:
        who = "Claude (owner-approved method)"
    elif q == "rule" or "(rule," in text:
        who = "rule"
    else:
        who = "project owner"
    return who, d.group(1) if d else None


STATEMENT = {
    "printed_inconsistent": "Printed as such (owner), but fails: {checks}.",
    "doubtful_reading": "Readers disagree ({token} vs {alt}); nothing decides; {token} kept.",
    "reading_decided_by_context": "Readers disagree ({token} vs {alt}); {token} kept because it fits "
                                  "the profile or neighbouring values.",
    "reading_decided_by_rule": "Readers disagree ({token} vs {alt}); {token} kept because the failed "
                               "checks pass with it.",
    "illegible": "Illegible in the scan; no value.",
}


def quality_annotations(reads: dict) -> list[dict]:
    out = []
    for file, path in QUALITY_FILES:
        for row in _rows(path):
            cat = QUALITY_CATEGORY.get(row.get("quality", ""))
            if not cat:
                continue
            checks = [c for c in row.get("check_failures", "").split(";") if c]
            alt = _alternative(row, reads) if cat not in ("printed_inconsistent", "illegible") else None
            who, date = _decider(row["quality"], row)
            statement = STATEMENT[cat].format(token=row["token"] or "blank", alt=alt or "?",
                                              checks=", ".join(checks) or "a check")
            if cat == "doubtful_reading" and alt is None and row["value_source"] == "mistral":
                # Tables 8.1/8.2: the second reader returned nothing usable for this cell
                who, statement = "rule", (f"No usable second reading (the second reader returned nothing "
                                          f"for this cell); marked doubtful; {row['token'] or 'blank'} kept.")
            out.append(_ann(
                cat, file, cell_id=row["cell_id"], printed=row["token"], alternative=alt,
                statement=statement,
                evidence="; ".join(x for x in (row.get("review_note"), row.get("value_source")) if x),
                checks_failed=checks, decided_by=who, date=date, source=file))
    return out


def suspect_annotations() -> list[dict]:
    cfg = yaml.safe_load((CONFIG / "suspect_values.yaml").read_text())
    out = []
    for section, file_of in (("volume1", lambda e: "volume1/arcs.csv" if e["table"] == "5.2"
                              else "volume1/towers.csv"),
                             ("volume1s", lambda e: "volume1/slow_response_wind.csv")):
        for e in cfg.get(section) or []:
            out.append(_ann(
                "suspected_original_error", file_of(e), cell_id=e["cell_id"],
                printed=e["printed"], alternative=e["suspect_alternative"],
                statement=f"Printed {e['printed'] or 'blank'!s}; probably {e['suspect_alternative']} "
                          f"in the original. Kept as printed.",
                evidence=" ".join(e["basis"].split()), decided_by=e["reviewer"], date=str(e["date"]),
                source="config/suspect_values.yaml"))
    return out


def volume2_key_annotations() -> list[dict]:
    cfg = yaml.safe_load((CONFIG / "volume2_keys.yaml").read_text())
    who, date = cfg["reviewer"], str(cfg["date"])
    src = "config/volume2_keys.yaml"
    out = []
    for k in cfg.get("keys") or []:
        match = {"pdf_index": str(k["pdf_index"])}
        if "release" in k:
            match["release"] = str(k["release"])
        out.append(_ann(
            "key_decided", f"volume2/table_{k['table']}.csv", scope="key", match=match,
            field=k["field"], alternative=None,
            statement=f"{k['field']} smudged in the print; set to {k['value']} by the owner."
                      + (f" Note: {k['note']}." if k.get("note") else ""),
            evidence=k["basis"], decided_by=who, date=date, source=src))
    for e in cfg.get("errata") or []:
        out.append(_ann(
            "suspected_original_error", f"volume2/table_{e['table']}.csv", scope="key",
            match={"release": str(e["release"])}, field=e["field"], printed=e["printed"],
            alternative=e["interpreted"],
            statement=f"{e['field']} printed {e['printed']}; probably {e['interpreted']} in the "
                      f"original. Kept as printed; the interpretation is in the `erratum` column.",
            evidence=e["basis"], decided_by=who, date=date, source=src))
    for c in cfg.get("conventions") or []:
        out.append(_ann(
            "unverified_transcription", f"volume2/table_{c['table']}.csv", scope="key",
            match={"quantity": c["field"]}, field=c["field"],
            statement=f"Table {c['table']} {c['field']} are kept as Mistral read them, not reviewed.",
            evidence=c["decision"], decided_by=who, date=date, source=src))
    for x in cfg.get("excluded_tables") or []:
        out.append(_ann(
            "excluded_table", f"volume2/table_{x['table']}.csv", scope="table",
            statement=f"Table {x['table']} is not in the dataset.", evidence=x["basis"],
            decided_by=who, date=str(x.get("date", date)), source=src))
    return out


def volume1_key_annotations() -> list[dict]:
    cfg = yaml.safe_load((CONFIG / "manual_keys.yaml").read_text())
    out = []
    for pdf, v in (cfg.get("arc_pages") or {}).items():
        if isinstance(v, dict) and "inferred" in v.get("method", ""):
            out.append(_ann(
                "key_decided", "volume1/arcs.csv", scope="key", match={"pdf_index": str(pdf)},
                field="run", alternative=None,
                statement=f"Run header unreadable on PDF page {pdf}; run set to {v['run']} "
                          f"({v['method']}).",
                evidence=f"{v['method']}; with this key 269 of 270 cells agree with the independent "
                         f"transcription by J. S. Irwin (see reference_comparison.csv)",
                decided_by=cfg["reviewer"], date=str(v.get("date", cfg["date"])),
                source="config/manual_keys.yaml"))
    return out


# Statements recorded in the docs (docs/volume2.md, README) rather than in a config file
DOCUMENTED = [
    _ann("unit_as_printed", "volume2/table_9.1.csv", scope="key", match={"table": "9.1"}, field="unit",
         printed="Kcal/cm² sec", alternative="10^-3 cal cm^-2 s^-1",
         statement="Table 9.1 is headed \"Kcal/cm² sec\" but its values are in 10^-3 cal cm^-2 s^-1. "
                   "The unit column keeps the printed heading.",
         evidence="Table 9.2 (cal/cm² min) equals 0.06 x Table 9.1 for q_c, q_e, q_s and R_n in every "
                  "release.",
         decided_by="project owner", date="2026-11-16", source="docs/volume2.md"),
    _ann("unit_as_printed", "volume2/table_9.1.csv", scope="key", match={"quantity": "R_n_plus_sum_q"},
         field="quantity", printed="R_n + Σq_i", alternative="-(R_n + Σq)",
         statement="The last column of Table 9.1 is headed \"R_n + Σq_i\" but holds -(R_n + Σq).",
         evidence="Holds in every release (check 9.1-sum).",
         decided_by="project owner", date="2026-11-16", source="docs/volume2.md"),
]


def build() -> list[dict]:
    reads = _second_readings()
    anns = (suspect_annotations() + volume1_key_annotations() + volume2_key_annotations()
            + DOCUMENTED + quality_annotations(reads))
    ids = [a["id"] for a in anns]
    assert len(ids) == len(set(ids)), "duplicate annotation id"
    return anns


def main() -> None:
    anns = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for a in anns:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    (OUT.parent / "annotation_categories.json").write_text(
        json.dumps(CATEGORIES, indent=1, ensure_ascii=False) + "\n")
    from collections import Counter
    print(f"{len(anns)} annotations -> {OUT.relative_to(REPO)}")
    for k, n in Counter(a["category"] for a in anns).most_common():
        print(f"  {k}: {n}")


if __name__ == "__main__":
    main()

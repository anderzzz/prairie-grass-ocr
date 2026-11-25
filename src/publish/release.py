"""The data release: datasets + metadata -> release/prairie-grass-data/

    cd src && uv run python -m publish.release      (make release)

Bundle layout (paths as used by `file` in annotations.jsonl):

  README.md                     data card (docs/data_card.md, with counts filled in; HF YAML header)
  datapackage.json              Frictionless Data Package: every file and column described
  LICENSE                       CC0 1.0 (the data and its documentation)
  volume1/*.csv                 Volume I tables 5.1-5.4, 6.1, run remarks
  volume2/table_<id>.csv        Volume II tables
  annotations/annotations.jsonl, annotation_categories.json, reference_comparison.csv

The scanned report volumes are not included (see the data card, "Source").

Every column of every shipped CSV must have an entry in FIELDS: an undocumented
column stops the build. The build also checks each value against its declared
type, the enumerated columns against their documented values, and the primary
keys for uniqueness, so datapackage.json cannot drift from the data. (The
Frictionless validator itself is not a dependency; `frictionless validate
datapackage.json` can be run on the bundle.)
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "release" / "prairie-grass-data"
META = REPO / "config" / "release.yaml"
CARD = REPO / "docs" / "data_card.md"
NOTEBOOKS = REPO / "notebooks"
NOTEBOOK_REQUIREMENTS = ["pandas>=2.2", "matplotlib>=3.8", "scipy>=1.11", "scikit-learn>=1.4",
                         "huggingface_hub>=0.23  # only to download the data when it is not alongside"]

# ---------------------------------------------------------------- field dictionary
STATUS = {
    "value": "a number was printed; it is in the value column",
    "not_measurable": "blank in Tables 5.2/5.3: no measurable concentration (Vol. I pp. 79, 193)",
    "missing": "printed as missing: 'M' in Volume I, '--' in Volume II, blank in Table 5.4 (its legend)",
    "not_printed": "Volume II: nothing printed in the cell (e.g. a sounding level without that quantity)",
    "text": "words, kept as text (e.g. 'rain', 'Calm', 'MB', remarks)",
    "code": "Table 13.1 '#' column: a two-figure trace code, not a number",
    "illegible": "the print could not be read by the project owner; no value",
    "unread": "token not interpretable as any of the above",
}
QUALITY = {
    "owner": "the project owner read the cell from the scan",
    "two_readers": "Mistral OCR and Claude Sonnet read the same token independently",
    "single_reader": "Mistral OCR only, and no consistency check involved the cell",
    "printed_inconsistent": "the owner confirmed the print, but it fails a consistency check",
    "context": "the readers differed; the reading that fits the height profile / neighbouring hours / "
               "another table was kept (Tables 8.1, 8.2; decided by Claude under the owner's method)",
    "rule": "the readers differed and the owner left it open; the reading under which the checks pass was kept",
    "doubtful": "the readers differ and nothing decides; Mistral's reading is kept",
    "illegible": "no usable value (see status)",
    "unread": "no usable value (see status)",
}
KIND = {"number": "a number", "missing": "'--' or 'M'", "blank": "nothing printed", "range": "a printed range 'a to b'",
        "above": "a bound such as '>100'", "text": "words", "unread": "not interpretable"}


def F(type_: str, description: str, **kw) -> dict:
    return {"type": type_, "description": description, **kw}


FIELDS: dict[str, dict] = {
    # keys and positions
    "run": F("string", "Gas release (run) number as printed: 1-68 plus 35S and 48S, which are distinct releases. "
                       "Read as a string."),
    "release": F("string", "Gas release number (= Volume I `run`), as a string (35S, 48S exist). Empty where the "
                           "row is not tied to a release."),
    "release_token": F("string", "The release number as printed"),
    "arc_m": F("integer", "Radius of the sampling arc", unit="m"),
    "post": F("integer", "Sampler post number on the arc: 1-91 on the 50-400 m arcs, 1-181 on the 800 m arc"),
    "bearing_deg": F("integer", "Bearing of the post. Post 1 is due west (270 deg); spacing 2 deg on 50-400 m arcs, "
                                "1 deg on the 800 m arc (Vol. I p. 79)", unit="deg"),
    "tower": F("integer", "Tower number 1-6, on the 100 m arc between posts 28-29, 35-36, 42-43, 49-50, 56-57, 63-64"),
    "height_m": F("number", "Measurement height; negative = depth below the surface (soil)", unit="m"),
    "date": F("date", "Date (1956), ISO format. Table 6.1: carried forward from the cell to the left where printed blank"),
    "date_token": F("string", "The date as printed"),
    "date_read": F("date", "Tables 8.1/8.2: the date as read from a smudged page header, where it differs from `date`"),
    "time_cst": F("string", "Time, Central Standard Time, hhmm as printed"),
    "time_cst_interpreted": F("string", "Table 10.1: the owner's reading of a time judged a typing error in the original"),
    "time_token": F("string", "Table 12.1: the sounding time as printed (e.g. 1050C)"),
    "cst": F("string", "Observation time, Central Standard Time, hhmm. Times marked * on the page belong to the "
                       "next day (already applied in `date`)"),
    "cst_token": F("string", "The time as printed, with its * marker"),
    "field_test": F("string", "Table 13.1 aircraft field test number as printed (one is 48S). Not a release "
                              "number: the flights were not made at release times"),
    "field_test_token": F("string", "The field test number as printed"),
    "header_token": F("string", "Table 13.1: the block header as printed"),
    "section": F("string", "Tables 8.1/8.2: the printed section", enum=["radiation", "temperature", "vapor_pressure",
                 "wind_speed", "wind_direction", "soil_temperature_change", "precipitation"]),
    "panel": F("integer", "Panel of the printed table (0-based)"),
    "block": F("integer", "Block within the panel or page (0-based)"),
    "row": F("integer", "Row within the block (0-based)"),
    "col": F("integer", "Column of the printed grid (0-based)"),
    "row_key": F("string", "Printed row labels, joined with ' | '"),
    "part": F("string", "Table 12.1: sounding or winds", enum=["sounding", "winds"]),
    "level": F("integer", "Level index within the sounding or flight (Tables 12.1, 13.1)"),
    "level_label": F("string", "Printed level label (SFC = surface)"),
    "location": F("string", "Table 6.1: source = 2 m on the base line; 450m = the 450 m mast",
                  enum=["source", "450m"]),
    "period_min": F("integer", "Table 6.1 averaging period; the 10 min source period coincides with the release",
                    unit="min"),
    "quantity": F("string", "What the cell measures. In small tables: the printed column heading, units included"),
    "unit": F("string", "Unit as printed in the table heading, even where the heading is known to be wrong "
                        "(Table 9.1)"),
    "applies_to": F("string", "Which data the remark qualifies"),
    "remark": F("string", "The printed remark"),
    # values
    "token": F("string", "The printed token, exactly as read (e.g. .0183, (2.4), >100, --). Empty = nothing printed"),
    "value": F("number", "Parsed number. Filled only when status = value (and kind is number or above)"),
    "value_lo": F("number", "Lower bound of a printed range 'a to b' (Table 11.1)"),
    "value_hi": F("number", "Upper bound of a printed range 'a to b' (Table 11.1)"),
    "concentration_mg_m3": F("number", "Ten-minute mean SO2 concentration as printed, NOT corrected for evaporation "
                                       "(factors in evaporation_correction.csv). Filled only when status = value",
                             unit="mg m-3"),
    "status": F("string", "What the cell holds, derived only from the printed token: " +
                "; ".join(f"{k} = {v}" for k, v in STATUS.items()), enum=list(STATUS)),
    "kind": F("string", "Shape of the printed token: " + "; ".join(f"{k} = {v}" for k, v in KIND.items()),
              enum=list(KIND)),
    "estimated": F("boolean", "Printed as an estimate: '*' in Tables 5.3 and 6.1, parentheses '(x)' in Volume II"),
    "footnote": F("boolean", "Printed with '*'; the footnote text is in page_footnotes (Tables 8.x)"),
    "page_footnotes": F("string", "Tables 8.1/8.2: the footnote printed on the page"),
    "erratum": F("string", "Table 10.1: the owner judges the printed value a typing error in the original; the token "
                           "is kept unchanged"),
    "note": F("boolean", "Table 12.1: the cell holds a note rather than a measurement"),
    # quality and provenance
    "quality": F("string", "Standing of the cell, strongest first: " +
                 "; ".join(f"{k} = {v}" for k, v in QUALITY.items()), enum=list(QUALITY)),
    "value_source": F("string", "How the printed token was established: mistral; mistral, confirmed by sonnet; or a "
                                "review decision with its basis, decider and date"),
    "reviewed": F("boolean", "The cell went through review by the project owner"),
    "pending": F("boolean", "A review decision is still open (all false in this release)"),
    "check_failures": F("string", "Consistency checks the final token still fails, ';'-separated (expected for "
                                  "printed inconsistencies)"),
    "review_note": F("string", "The reviewer's note, where one was made"),
    "flagged": F("boolean", "Volume I: the extraction pipeline raised a doubt (reader disagreement, low confidence, "
                            "layout); not cleared by review"),
    "flag_notes": F("string", "Volume I: the pipeline's doubts, as text"),
    "flags": F("string", "Parser and reader doubts, ';'-separated"),
    "conf": F("number", "Mistral OCR word confidence (0-1)"),
    "outlier": F("string", "Outlier screen: 'spike (+-n scales)' or 'global (+-n scales)'. Marks only; nothing removed"),
    "suspect": F("boolean", "The project owner suspects an error in the ORIGINAL 1958 report; the printed value is kept"),
    "suspect_alternative": F("string", "The suspected intended value (carried alongside, never substituted)"),
    "suspect_note": F("string", "The evidence for the suspicion, with decider and date"),
    "key_source": F("string", "How the row key (run, date) was established: pipeline, or manual with decider, date "
                              "and basis"),
    "read_by": F("string", "Tables 8.x: set where the precipitation row was read from its own image strip"),
    "table": F("string", "Table number in the report (e.g. 5.2, 8.1)"),
    "pdf_index": F("integer", "0-based page index in the scanned volume PDF (see data card, Source)"),
    "printed_page": F("integer", "Page number printed in the report"),
    "cell_id": F("string", "Stable cell identifier; joins to annotations.jsonl"),
    "grid_ti": F("integer", "Index of the table on the page (OCR layout; for tracing)"),
    "grid_row": F("integer", "Index of the row in the OCR layout (for tracing)"),
}

# per-file overrides of a shared field's meaning
OVERRIDES = {
    ("evaporation_correction.csv", "value"): F("number", "Correction factor for evaporative loss: multiply the "
                                                         "concentration by it. Towers take the 100 m factor"),
    ("source_strength.csv", "value"): F("number", "Release rate Q as printed", unit="g s-1"),
    ("slow_response_wind.csv", "value"): F("number", "Value as printed, in `unit`. Rows with quantity key:date / "
                                                     "key:time_cst hold the printed keys"),
    ("slow_response_wind.csv", "estimated"): F("boolean", "Printed with '*': estimate from an incomplete record"),
    ("run_remarks.csv", "value_source"): F("string", "How the remark text was established"),
}

# Columns of the comparison with the earlier transcription: described in config/release.yaml
# (comparison_file.fields), so that no code here names that transcription (tests/test_isolation.py).
EXTRA_FIELDS = {k: {**v, "description": " ".join(v["description"].split())}
                for k, v in (yaml.safe_load(META.read_text())["comparison_file"]["fields"] or {}).items()}

# ---------------------------------------------------------------- resources
V1 = REPO / "output" / "volume1" / "dataset"
V2 = REPO / "output" / "volume2" / "dataset"
PUB = REPO / "output" / "publish"

V2_TITLES = {
    "7.1": "Standard error of mean potential temperature",
    "7.2": "Statistical measures of temperature",
    "8.1": "Micrometeorology at gas-release times: radiation, air and soil temperature, vapour pressure, wind "
           "speed and direction, soil temperature change, precipitation",
    "8.2": "Micrometeorology at other times (hourly), same layout as 8.1",
    "8.3": "Soil moisture and density",
    "9.1": "Heat budget, Texas A&M (unit printed 'Kcal/cm2 sec'; in fact 1e-3 cal cm-2 s-1, = Table 9.2 / 0.06)",
    "9.2": "Heat budget, Texas A&M (cal cm-2 min-1)",
    "9.3": "Percent of double-level values within 10 % of profile values",
    "9.4": "Heat-budget balance statistics (text: fitted equations, error terms)",
    "10.1": "Heat budget, University of Wisconsin (langley min-1)",
    "11.1": "Change of temperature gradient, optical method, 10-12 July",
    "11.2": "Change of temperature gradient, optical method, 21, 23 and 31 July",
    "12.1": "Rawinsonde soundings and winds",
    "13.1": "Aircraft observations (field-test numbers are not release numbers)",
}


def resources() -> list[dict]:
    r = [
        ("volume1/arcs.csv", V1 / "arcs.csv", "Table 5.2: SO2 concentrations on the five sampling arcs at 1.5 m, "
         "one row per run, arc and post", ["run", "arc_m", "post"]),
        ("volume1/towers.csv", V1 / "towers.csv", "Table 5.3: SO2 concentrations on the six towers, one row per run, "
         "tower and height", ["run", "tower", "height_m"]),
        ("volume1/source_strength.csv", V1 / "source_strength.csv", "Table 5.1: release rate Q per run", ["cell_id"]),
        ("volume1/evaporation_correction.csv", V1 / "evaporation_correction.csv", "Table 5.4: correction factors "
         "for evaporative loss, per run and arc (not applied to the concentrations)", ["cell_id"]),
        ("volume1/slow_response_wind.csv", V1 / "slow_response_wind.csv", "Table 6.1: slow-response 2 m wind speed, "
         "direction and sigma-theta at the source and the 450 m mast, 10 and 20 min periods", ["cell_id"]),
        ("volume1/run_remarks.csv", V1 / "run_remarks.csv", "Per-run remarks printed with Table 5.2 and in the Table "
         "6.1 legend", ["cell_id"]),
    ]
    for p in sorted(V2.glob("table_*.csv"), key=lambda p: [int(x) for x in p.stem.split("_")[1].split(".")]):
        t = p.stem.split("_")[1]
        r.append((f"volume2/{p.name}", p, f"Volume II Table {t}: {V2_TITLES[t]}", ["cell_id"]))
    cmp = yaml.safe_load(META.read_text())["comparison_file"]
    r.append((f"annotations/{cmp['file']}", PUB / cmp["file"], " ".join(cmp["description"].split()), ["cell_id"]))
    return [{"path": a, "src": b, "description": c, "key": d} for a, b, c, d in r]


# ---------------------------------------------------------------- checks
def _ok(type_: str, v: str) -> bool:
    if v == "":
        return True
    if type_ == "integer":
        return re.fullmatch(r"-?\d+", v) is not None
    if type_ == "number":
        try:
            float(v)
            return True
        except ValueError:
            return False
    if type_ == "boolean":
        return v in ("True", "False")
    if type_ == "date":
        return re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) is not None
    return True


def schema_for(res: dict) -> tuple[dict, list[dict]]:
    with res["src"].open(newline="") as f:
        rows = list(csv.DictReader(f))
    name = res["src"].name
    fields, problems = [], []
    for col in rows[0].keys():
        fd = OVERRIDES.get((name, col)) or FIELDS.get(col) or EXTRA_FIELDS.get(col)
        if fd is None:
            problems.append(f"{name}: column {col!r} is not documented in FIELDS")
            continue
        bad = [r[col] for r in rows if not _ok(fd["type"], r[col])]
        if bad:
            problems.append(f"{name}: {col} declared {fd['type']} but holds {bad[:3]}")
        if "enum" in fd:
            extra = {r[col] for r in rows} - set(fd["enum"]) - {""}
            if extra:
                problems.append(f"{name}: {col} has undocumented values {sorted(extra)}")
        field = {"name": col, "type": fd["type"], "description": fd["description"]}
        if fd["type"] == "boolean":
            field.update(trueValues=["True"], falseValues=["False"])
        if fd["type"] == "date":
            field["format"] = "%Y-%m-%d"
        if "unit" in fd:
            field["unit"] = fd["unit"]
        if "enum" in fd:
            field["constraints"] = {"enum": fd["enum"]}
        fields.append(field)
    keys = [tuple(r[k] for k in res["key"]) for r in rows]
    dup = len(keys) - len(set(keys))
    if dup:
        problems.append(f"{name}: primary key {res['key']} has {dup} duplicates")
    if problems:
        raise SystemExit("\n".join(problems))
    schema = {"fields": fields, "missingValues": [""], "primaryKey": res["key"]}
    return schema, rows


# ---------------------------------------------------------------- data card
def _table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_card(meta: dict, loaded: dict[str, list[dict]], n_ann: int) -> str:
    files = _table(["File", "Content", "Rows"],
                   [[f"`{r['path']}`", r["description"], f"{len(loaded[r['path']]):,}"] for r in resources()])
    q = Counter()
    for path, rows in loaded.items():
        if path.startswith("volume2/"):
            q.update(r["quality"] for r in rows)
    quality = _table(["quality", "Volume II cells", "Meaning"],
                     [[f"`{k}`", f"{q[k]:,}", QUALITY[k]] for k in QUALITY if q[k]])
    st = Counter()
    for path, rows in loaded.items():
        if path.startswith(("volume1/arcs", "volume1/towers")):
            st.update(r["status"] for r in rows)
    v1status = ", ".join(f"{k} {v:,}" for k, v in st.most_common())
    scans = _table(["Volume", "URL", "Bytes", "SHA-256"],
                   [[s["volume"], s["url"], f"{s['bytes']:,}", f"`{s['sha256']}`"] for s in meta["scans"]])
    card = CARD.read_text()
    for k, v in {"title": meta["title"], "version": meta["version"], "date": meta.get("date") or date.today().isoformat(),
                 "file_table": files, "quality_table": quality, "v1_status": v1status, "scan_table": scans,
                 "n_annotations": f"{n_ann:,}", "creators": "; ".join(c.get("display", c["name"]) for c in meta["creators"] + meta.get("contributors", [])),
                 "citation": meta["citation"].strip()}.items():
        card = card.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{\w+\}\}", card)
    if left:
        raise SystemExit(f"data card: unfilled placeholders {left}")
    return card


HF_DTYPE = {"string": "string", "integer": "int64", "number": "float64", "boolean": "bool", "date": "string"}


def hf_front_matter(pkg_res: list[dict]) -> str:
    """YAML header for the Hugging Face dataset card: licence, tags and one viewer config per table.

    Hugging Face reads it and hides it; other renderers show it as a block at the top. Column types
    come from datapackage.json, so `run` stays a string (35S) instead of being guessed as an integer.
    Only an empty cell is null (`keep_default_na: false`), so printed tokens such as NA stay text."""
    lines = ["---", "license: cc0-1.0", "pretty_name: Project Prairie Grass (1956)", "language:", "- en",
             "size_categories:", "- 10K<n<100K", "task_categories:", "- tabular-regression", "tags:"]
    lines += [f"- {k}" for k in ["atmospheric-dispersion", "air-pollution", "micrometeorology", "physics",
                                 "benchmark", "historical-data", "tabular"]]
    def cname(path: str) -> str:
        return path.removesuffix(".csv").split("/")[-1].replace(".", "_")
    csvs = [r for r in pkg_res if r["format"] == "csv"]
    lines += ["configs:"]
    for i, r in enumerate(csvs):
        lines += [f"- config_name: {cname(r['path'])}", f"  data_files: {r['path']}",
                  "  keep_default_na: false", "  na_values:", "  - ''"]
        if i == 0:
            lines.append("  default: true")
    # annotations.jsonl gets no config: in a repo of CSVs the HF loader would parse it as CSV.
    lines += ["dataset_info:"]
    for r in csvs:
        lines += [f"- config_name: {cname(r['path'])}", "  features:"]
        for f in r["schema"]["fields"]:
            lines += [f"  - name: {f['name']}", f"    dtype: {HF_DTYPE[f['type']]}"]
    return "\n".join(lines + ["---", ""]) + "\n"


# ---------------------------------------------------------------- build
def main() -> None:
    meta = yaml.safe_load(META.read_text())
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    pkg_res, loaded = [], {}
    for res in resources():
        schema, rows = schema_for(res)
        loaded[res["path"]] = rows
        dest = OUT / res["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(res["src"], dest)
        pkg_res.append({"name": re.sub(r"[^a-z0-9]+", "-", res["path"].lower().removesuffix(".csv")).strip("-"),
                        "path": res["path"], "format": "csv", "mediatype": "text/csv", "encoding": "utf-8",
                        "description": res["description"], "schema": schema})
    ann_dir = OUT / "annotations"
    ann_dir.mkdir(exist_ok=True)
    shutil.copyfile(PUB / "annotations.jsonl", ann_dir / "annotations.jsonl")
    shutil.copyfile(PUB / "annotation_categories.json", ann_dir / "annotation_categories.json")
    ann = [json.loads(line) for line in (PUB / "annotations.jsonl").open()]
    known = {(r["path"], c["cell_id"]) for r in resources() for c in loaded[r["path"]]}
    orphans = [a["id"] for a in ann if a["scope"] == "cell" and (a["file"], a["cell_id"]) not in known]
    if orphans:
        raise SystemExit(f"annotations for cells not in the bundle: {orphans[:5]}")
    pkg_res += [
        {"name": "annotations", "path": "annotations/annotations.jsonl", "format": "jsonl",
         "mediatype": "application/jsonl", "encoding": "utf-8",
         "description": "Curators' statements about the data beyond the printed token, one JSON object per line: "
                        "suspected errors in the original, keys set by a person, doubtful readings, readings decided "
                        "by context or rule, printed inconsistencies, units kept as printed, an excluded table. "
                        "Keyed by `file` + `cell_id` (scope cell), a column selector `match` (scope key) or the "
                        "whole table. Categories in annotation_categories.json."},
        {"name": "annotation-categories", "path": "annotations/annotation_categories.json", "format": "json",
         "mediatype": "application/json", "encoding": "utf-8",
         "description": "Glossary of the annotation categories"},
    ]
    pkg = {
        "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
        "name": meta["name"], "title": meta["title"], "version": meta["version"],
        "description": " ".join(meta["description"].split()),
        **({"homepage": meta["homepage"]} if meta.get("homepage") else {}),
        "licenses": [{"name": "CC0-1.0", "path": "https://creativecommons.org/publicdomain/zero/1.0/",
                      "title": "CC0 1.0 Universal"}],
        "contributors": [{"title": c["name"], "roles": c.get("roles", ["creator"]),
                          **({"path": f"https://orcid.org/{c['orcid']}"} if c.get("orcid") else {})}
                         for c in meta["creators"] + meta.get("contributors", [])],
        "sources": [{"title": s["title"], "path": s.get("url", "")} for s in meta["sources"]],
        "keywords": meta["keywords"],
        "created": meta.get("date") or date.today().isoformat(),
        "resources": pkg_res,
    }
    (OUT / "datapackage.json").write_text(json.dumps(pkg, indent=1, ensure_ascii=False) + "\n")
    (OUT / "README.md").write_text(hf_front_matter(pkg_res) + render_card(meta, loaded, len(ann)))
    shutil.copyfile(REPO / "LICENSE-DATA", OUT / "LICENSE")
    # Introductory notebooks (with their outputs) and their helper; they find the data one level up.
    nb_dir = OUT / "notebooks"
    nb_dir.mkdir()
    for f in sorted(NOTEBOOKS.glob("*.ipynb")) + [NOTEBOOKS / "pgdata.py"]:
        shutil.copyfile(f, nb_dir / f.name)
    (nb_dir / "requirements.txt").write_text("\n".join(NOTEBOOK_REQUIREMENTS) + "\n")
    shutil.copyfile(NOTEBOOKS / "LICENSE", nb_dir / "LICENSE")
    n = sum(len(v) for v in loaded.values())
    print(f"release: {OUT}  {len(pkg_res)} resources, {n:,} rows, {len(ann)} annotations")


if __name__ == "__main__":
    main()

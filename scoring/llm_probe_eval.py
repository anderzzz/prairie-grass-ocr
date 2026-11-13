"""Evaluate the vision-LLM probe on dev pages against the reference.

    uv run python -m scoring.llm_probe_eval [--model claude-haiku-5-5]

Needs output/scores/dev/cells.csv (scoring.score --set dev) and
output/experiments/llm_probe_<model>.csv. Writes
output/scores/dev/llm_probe_<model>.md (gitignored with the other scores).
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict

from .score import SCORES, compare, ref_kind, tok_kind
from .reference import HEIGHTS

REPO_OUT = SCORES / "dev"


def ok(tok: str, c: dict) -> bool:
    k, v = tok_kind(tok)
    rk, rv = ref_kind(c["ref_value"] or None) if c["ref_kind"] else ("", None)
    return compare(k, v, rk, rv) == "match"


def digits(t: str) -> str:
    return "".join(ch for ch in t if ch.isdigit())


def kind_of_error(tok: str, ref: str) -> str:
    if tok in ("", "ILLEGIBLE"):
        return "blank/illegible"
    r = f"{float(ref):.3f}".rstrip("0").rstrip(".") if ref else ""
    if digits(tok).lstrip("0") == digits(r).lstrip("0"):
        return "decimal point / leading zero"
    if len(digits(tok)) != len(digits(r).lstrip("0") or "0") and digits(r).lstrip("0").startswith(digits(tok).lstrip("0")[:2]):
        return "digit dropped or added"
    return "wrong digit(s)"


def neighbour_refs(cells: dict, c: dict) -> set[str]:
    """Reference values of the cells above and below in the same column."""
    if c["table"] == "5.2":
        p = int(c["post"])
        keys = [f"p{c['pdf_index']}_5.2_r{c['run']}_{c['arc_m']}_{q}" for q in (p - 1, p + 1)]
    else:
        i = HEIGHTS.index(c["height_m"])
        keys = [f"p{c['pdf_index']}_5.3_r{c['run']}_{c['tower']}_{HEIGHTS[j]}"
                for j in (i - 1, i + 1) if 0 <= j < len(HEIGHTS)]
    return {cells[k]["ref_value"] for k in keys if k in cells and cells[k]["ref_kind"] == "number"}


def main(model: str) -> str:
    cells = {c["cell_id"]: c for c in csv.DictReader((REPO_OUT / "cells.csv").open())}
    probe = list(csv.DictReader((SCORES.parent / "experiments" / f"llm_probe_{model}.csv").open()))
    by_mode = defaultdict(dict)
    for p in probe:
        by_mode[p["mode"]][p["cell_id"]] = p
    L = [f"# Vision-LLM probe: {model} on dev pages", ""]
    base_ids = list(by_mode["cell"])
    tok_in = sum(int(p["input_tokens"]) for p in probe)
    tok_out = sum(int(p["output_tokens"]) for p in probe)
    L += [f"{len(probe)} reads, {tok_in} input / {tok_out} output tokens.", ""]

    def table(ids, title):
        L.append(f"## {title} ({len(ids)} cells)")
        L.append("")
        L.append("| reader | correct | accuracy |")
        L.append("|---|---|---|")
        rows = [("tesseract", lambda i: cells[i]["raw_tesseract"]),
                ("easyocr", lambda i: cells[i]["raw_easyocr"]),
                ("offline consensus", lambda i: cells[i]["consensus_token"])]
        for m in ("glyphs", "cell", "cell_rules", "context"):
            if all(i in by_mode[m] for i in ids):
                rows.append((f"LLM {m}", lambda i, m=m: by_mode[m][i]["text"]))
        for name, f in rows:
            n = sum(ok(f(i), cells[i]) for i in ids)
            L.append(f"| {name} | {n} | {n / len(ids):.3f} |")
        L.append("")

    table(base_ids, "All cells the offline readers read")
    flagged = list(by_mode["context"])
    table(flagged, "Cells flagged by the offline pipeline (where a third reader would be consulted)")
    unflagged_wrong = [i for i in base_ids if cells[i]["outcome"] != "match" and not
                       any(cells[i][k] == "True" for k in ("flag_readers_disagree",
                                                           "flag_low_confidence", "flag_token_unexpected"))]
    if unflagged_wrong:
        L.append(f"Offline errors with no cell-level flag: {len(unflagged_wrong)}; LLM cell_rules "
                 f"reads {sum(ok(by_mode['cell_rules'][i]['text'], cells[i]) for i in unflagged_wrong)} "
                 "of them correctly, i.e. it would disagree with the offline readers there.")
        L.append("")

    # three-reader vote
    L.append("## Three-reader vote (tesseract, easyocr, LLM cell_rules)")
    L.append("")
    outcomes = Counter()
    for i in base_ids:
        t = [cells[i]["raw_tesseract"], cells[i]["raw_easyocr"], by_mode["cell_rules"][i]["text"]]
        norm = [tok.replace(" ", "").replace(",", ".") for tok in t]
        cnt = Counter(norm)
        top, n = cnt.most_common(1)[0]
        if n == 3:
            cls = "unanimous"
        elif n == 2:
            cls = "2 of 3"
        else:
            cls = "all differ (take LLM)"
            top = norm[2]
        outcomes[(cls, ok(top, cells[i]))] += 1
    L.append("| agreement | cells | correct | error rate |")
    L.append("|---|---|---|---|")
    for cls in ("unanimous", "2 of 3", "all differ (take LLM)"):
        good, bad = outcomes[(cls, True)], outcomes[(cls, False)]
        if good + bad:
            L.append(f"| {cls} | {good + bad} | {good} | {bad / (good + bad):.3f} |")
    tot_good = sum(v for (c, g), v in outcomes.items() if g)
    L.append(f"| all | {len(base_ids)} | {tot_good} | {1 - tot_good / len(base_ids):.3f} |")
    L.append("")

    # LLM self-reported uncertainty
    for m in ("cell_rules", "context"):
        ids = list(by_mode[m])
        unc = [i for i in ids if by_mode[m][i]["uncertain"] == "True"]
        wrong = [i for i in ids if not ok(by_mode[m][i]["text"], cells[i])]
        L.append(f"## `uncertain` flag, mode {m}")
        L.append("")
        L.append(f"flagged uncertain {len(unc)}/{len(ids)}; errors {len(wrong)}; errors flagged "
                 f"{sum(i in unc for i in wrong)}/{len(wrong)}; error rate when uncertain "
                 f"{sum(i in wrong for i in unc) / max(1, len(unc)):.3f}, when not "
                 f"{sum(i in wrong for i in ids if i not in unc) / max(1, len(ids) - len(unc)):.3f}")
        L.append("")

    # error types and context contamination
    for m in ("glyphs", "cell", "cell_rules", "context"):
        ids = list(by_mode[m])
        errs = Counter(kind_of_error(by_mode[m][i]["text"], cells[i]["ref_value"])
                       for i in ids if not ok(by_mode[m][i]["text"], cells[i]))
        L.append(f"- error types, {m}: {dict(errs)}")
    copied = [i for i in by_mode["context"] if not ok(by_mode["context"][i]["text"], cells[i])
              and any(tok_kind(by_mode["context"][i]["text"])[1] is not None
                      and abs(tok_kind(by_mode["context"][i]["text"])[1] - float(v)) < 5e-4
                      for v in neighbour_refs(cells, cells[i]))]
    L += ["", f"Context mode: {len(copied)} wrong answers equal a neighbouring row's reference "
          "value (possible copying from context)."]

    L += ["", "## Examples where the LLM (cell_rules) and the offline consensus differ", "",
          "| cell | tesseract | easyocr | consensus | LLM | LLM note | reference |", "|---|---|---|---|---|---|---|"]
    ex = [i for i in base_ids if by_mode["cell_rules"][i]["text"] != cells[i]["consensus_token"]]
    for i in ex[:40]:
        c, p = cells[i], by_mode["cell_rules"][i]
        L.append(f"| {i} | {c['raw_tesseract']} | {c['raw_easyocr']} | {c['consensus_token']} | "
                 f"{p['text']} | {p['note'][:90]} | {c['ref_value']} |")
    text = "\n".join(L) + "\n"
    (REPO_OUT / f"llm_probe_{model}.md").write_text(text)
    return text


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-haiku-5-5")
    print(main(ap.parse_args().model))

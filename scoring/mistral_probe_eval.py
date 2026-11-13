"""Compare Mistral OCR (page-level) with the other readers on dev pages.

    uv run python -m scoring.mistral_probe_eval [--model mistral-ocr-4-1]
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter

from .llm_probe_eval import ok
from .score import SCORES

EXP = SCORES.parent / "experiments"


def main(model: str) -> str:
    cells = {c["cell_id"]: c for c in csv.DictReader((SCORES / "dev" / "cells.csv").open())}
    mi = {r["cell_id"]: r for r in csv.DictReader((EXP / f"mistral_{model}.csv").open())}
    son = {r["cell_id"]: r for r in csv.DictReader((EXP / "llm_probe_claude-sonnet-5-5.csv").open())
           if r["mode"] == "cell_rules"}
    hai = {r["cell_id"]: r for r in csv.DictReader((EXP / "llm_probe_claude-haiku-5-5.csv").open())
           if r["mode"] == "cell_rules"}
    L = [f"# Mistral OCR ({model}) on dev pages", ""]
    allids = [i for i in cells if i in mi]
    inked = [i for i in allids if i in son]
    flagged = [i for i in inked if any(cells[i][k] == "True" for k in
                                       ("flag_readers_disagree", "flag_low_confidence", "flag_token_unexpected"))]
    readers = {
        "tesseract": lambda i: cells[i]["raw_tesseract"],
        "easyocr": lambda i: cells[i]["raw_easyocr"],
        "offline consensus": lambda i: cells[i]["consensus_token"],
        "Haiku cell_rules": lambda i: hai[i]["text"] if i in hai else "",
        "Sonnet cell_rules": lambda i: son[i]["text"] if i in son else "",
        "Mistral": lambda i: mi[i]["text"],
    }
    L += ["| reader | all cells incl. blanks | cells with ink | flagged cells |", "|---|---|---|---|"]
    for name, f in readers.items():
        acc = [sum(ok(f(i), cells[i]) for i in ids) / len(ids) for ids in (allids, inked, flagged)]
        L.append(f"| {name} | {acc[0]:.3f} | {acc[1]:.3f} | {acc[2]:.3f} |")
    L += ["", f"cells: all {len(allids)}, inked {len(inked)}, flagged {len(flagged)}", ""]

    # blanks: Mistral values where nothing is printed / missed values
    spur = [i for i in allids if i not in son and mi[i]["text"] and cells[i]["ref_kind"] != "number"]
    L.append(f"Mistral reports a value in {len(spur)} cells where the offline readers found no "
             "glyph ink and the reference has no number.")
    miss = [i for i in allids if not mi[i]["text"] and cells[i]["ref_kind"] == "number"]
    L.append(f"Mistral leaves {len(miss)} cells blank that the reference has a number for.")
    L.append("")

    def vote(ids, names, label):
        res = Counter()
        for i in ids:
            toks = [readers[n](i).replace(" ", "").replace(",", ".") for n in names]
            top, n = Counter(toks).most_common(1)[0]
            cls = "unanimous" if n == len(names) else ("majority" if n > len(names) / 2 else "no majority")
            res[(cls, ok(top, cells[i]))] += 1
        L.append(f"### Vote: {label} ({len(ids)} inked cells)")
        L.append("")
        L.extend(["| agreement | cells | wrong | error rate |", "|---|---|---|---|"])
        for cls in ("unanimous", "majority", "no majority"):
            g, b = res[(cls, True)], res[(cls, False)]
            if g + b:
                L.append(f"| {cls} | {g + b} | {b} | {b / (g + b):.3f} |")
        L.append("")

    vote(inked, ["tesseract", "easyocr", "Mistral"], "tesseract, easyocr, Mistral")
    vote(inked, ["tesseract", "easyocr", "Sonnet cell_rules"], "tesseract, easyocr, Sonnet")
    vote(inked, ["Mistral", "Sonnet cell_rules"], "Mistral, Sonnet")
    vote(inked, ["tesseract", "easyocr", "Mistral", "Sonnet cell_rules"], "all four")

    # confidence calibration
    confs = [(float(mi[i]["conf"]), ok(mi[i]["text"], cells[i])) for i in inked if mi[i]["conf"]]
    L.append("### Mistral word confidence (inked cells)")
    L.append("")
    L += ["| min word confidence | cells | error rate |", "|---|---|---|"]
    for lo, hi in ((0, 0.9), (0.9, 0.99), (0.99, 0.999), (0.999, 1.01)):
        sel = [g for c, g in confs if lo <= c < hi]
        if sel:
            L.append(f"| {lo}-{min(hi, 1)} | {len(sel)} | {1 - sum(sel) / len(sel):.3f} |")
    L.append("")
    L += ["### Cells where Mistral and Sonnet agree but are wrong", "",
          "| cell | Mistral | Sonnet | tesseract | easyocr | reference |", "|---|---|---|---|---|---|"]
    for i in inked:
        m, s = readers["Mistral"](i), readers["Sonnet cell_rules"](i)
        if m.replace(",", ".") == s.replace(",", ".") and not ok(m, cells[i]):
            c = cells[i]
            L.append(f"| {i} | {m} | {s} | {c['raw_tesseract']} | {c['raw_easyocr']} | {c['ref_value']} |")
    text = "\n".join(L) + "\n"
    (SCORES / "dev" / f"mistral_{model}.md").write_text(text)
    return text


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="mistral-ocr-4-1")
    print(main(ap.parse_args().model))

"""HTML table (Mistral output) -> list of rows of cell texts, spans expanded.

A colspan cell is placed in its first column and the columns it spans are
filled with None (so a section heading never looks like a value); a rowspan
cell is repeated downward with its text (it labels each spanned row).
"""
from __future__ import annotations

import html
import re

TABLE_RE = re.compile(r"<table>.*?</table>", re.S)
ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<t([dh])([^>]*)>(.*?)</t[dh]>", re.S)


def text(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " / ", s)
    s = re.sub(r"<sup>(.*?)</sup>", r"^\1", s)
    s = re.sub(r"<sub>(.*?)</sub>", r"_\1", s)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def grid(table_html: str, words: list | None = None, with_conf: bool = False) -> list[list]:
    """Rows of cell texts; with_conf=True gives (text, min word confidence)."""
    rows: list[list] = []
    pending: dict[int, tuple[int, str]] = {}  # col -> (rows left, text)
    for rm in ROW_RE.finditer(table_html):
        row: list[str | None] = []
        col = 0

        def fill():
            nonlocal col
            while col in pending:
                n, t = pending[col]
                row.append(t)
                if n <= 1:
                    del pending[col]
                else:
                    pending[col] = (n - 1, t)
                col += 1

        for cm in CELL_RE.finditer(rm.group(1)):
            fill()
            attrs = cm.group(2)
            cs = int((re.search(r'colspan="(\d+)"', attrs) or [0, 1])[1])
            rs = int((re.search(r'rowspan="(\d+)"', attrs) or [0, 1])[1])
            t = text(cm.group(3))
            if with_conf:
                a, b = rm.start(1) + cm.start(3), rm.start(1) + cm.end(3)
                cf = [w["confidence"] for w in (words or []) if a <= w["start_index"] < b]
                t = (t, min(cf) if cf else None)
            row.append(t)
            if rs > 1:
                pending[col] = (rs - 1, t)
            row.extend([None] * (cs - 1))
            col += cs
        fill()
        rows.append(row)
    return rows


def tables(md: str) -> list[list[list[str | None]]]:
    return [grid(m.group(0)) for m in TABLE_RE.finditer(md)]


def outside(md: str) -> str:
    """Page text outside the tables."""
    return TABLE_RE.sub("\n[TABLE]\n", md)

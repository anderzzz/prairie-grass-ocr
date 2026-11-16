"""Mistral OCR of every supplementary page (cached); writes the page markdown
to output/volume1s/mistral/p<idx>.md for inspection.

    cd src && uv run python -m volume1s.ocr
"""
from __future__ import annotations

from .pages import OUT, inventory, page_markdown, pages_of


def main() -> None:
    d = OUT / "mistral"
    d.mkdir(parents=True, exist_ok=True)
    for t in inventory():
        for i in pages_of(t):
            (d / f"p{i}.md").write_text(page_markdown(i))
            print(t, i, "ok")


if __name__ == "__main__":
    main()

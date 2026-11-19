"""The reference transcription is an answer key: extraction code must never read it."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACT = ROOT / "src" / "extract"
DATASET = ROOT / "src" / "dataset"  # the dataset build may not read it either
VOLUME2 = ROOT / "src" / "volume2"  # Volume II has no reference, and must not acquire one by accident
VOLUME1S = ROOT / "src" / "volume1s"  # Tables 5.1, 5.4, 6.1: no reference either
PUBLISH = ROOT / "src" / "publish"  # annotations: built from the datasets and configs only

# any mention of the reference directory or the reference files themselves
FORBIDDEN = re.compile(r"reference[/\\'\"]|\breference\b\s*[/)]|PGARCS|PGVertConc|harmo\.org|D6589|\bscoring\b",
                       re.IGNORECASE)


def test_extract_never_references_answer_key():
    offenders = []
    for path in (sorted(EXTRACT.rglob("*.py")) + sorted(DATASET.rglob("*.py")) + sorted(VOLUME2.rglob("*.py"))
                 + sorted(VOLUME1S.rglob("*.py")) + sorted(PUBLISH.rglob("*.py"))):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if FORBIDDEN.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, "extraction code mentions the reference:\n" + "\n".join(offenders)


def test_forbidden_pattern_catches_obvious_cases():
    for s in ['open("reference/PGARCS.txt")', "REPO / 'reference' / x", "from scoring import x",
              "Path('reference/')"]:
        assert FORBIDDEN.search(s), s

"""Volume II token parsing: values come from the printed token only."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volume2.common import STATUS, parse  # noqa: E402
from volume2.tables8 import release_label  # noqa: E402


def test_tokens():
    assert parse("--")["kind"] == "missing"
    assert parse("")["kind"] == "blank"
    assert parse("- .28")["value"] == -0.28
    p = parse("(-.09)")
    assert p["estimated"] and p["value"] == -0.09
    p = parse("20.7*")
    assert p["footnote"] and p["value"] == 20.7
    p = parse(">100")
    assert p["kind"] == "above" and p["value"] == 100
    p = parse(".021 to .024")
    assert p["kind"] == "range" and p["lo"] == 0.021 and p["hi"] == 0.024
    for w in ("rain", "MB", "Calm", "Signal Failure / No Data"):
        assert parse(w)["kind"] == "text"
    assert parse("3.2.1")["kind"] == "unread"


def test_status_never_invents_a_value():
    for tok in ("", "--", "rain", "MB", "?", "3.2.1"):
        p = parse(tok)
        assert p["value"] is None and STATUS[p["kind"]] != "value", tok


def test_release_labels():
    assert release_label("35s") == "35S" and release_label("48a") == "48S"
    assert release_label("7") == "7" and release_label("x") == ""

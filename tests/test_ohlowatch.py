"""`tools/pool_of_radiance/ohlowatch.py`'s `rows` mode, offline (#414).

`rows_mode()` renders the Quest Log panel from a captured `$4900`-`$64FF`
window with no emulator involved, which is the half of the tool this suite can
exercise. The window this test builds is all zero bytes -- a party that has
never been to the City Hall -- so what matters here is only that the call
returns rows rather than raising.

`#158 (Track the quests the game itself forgets, starting with Ohlo's potion)`
removed `WISH_EXPERIMENTAL_QUESTS` and `automap.questlog.enabled()` along with
it; `rows_mode()` still imported `enabled` and called it, which raised
`ImportError` the moment this mode ran (#414).
"""

import argparse
import json
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.pool_of_radiance import ohlowatch  # noqa: E402


def test_rows_mode_runs_with_no_quests_environment_variable(tmp_path, capsys):
    """`rows_mode()` must not import the flag `#158` deleted.

    Red before the fix: `from automap.questlog import QuestLogPanel, enabled`
    raised `ImportError: cannot import name 'enabled' from 'automap.questlog'`
    before a single row could be drawn.
    """
    window = bytes(ohlowatch.SAVE0_LEN)  # never been to the City Hall
    binp = tmp_path / "window.bin"
    binp.write_bytes(window)

    args = argparse.Namespace(bin=str(binp), png="", width=300)
    assert ohlowatch.rows_mode(args) == 0

    out = json.loads(capsys.readouterr().out)
    assert "groups" in out
    assert "gate" not in out


def test_capture_reports_completed_rows_with_the_active_rows(
        tmp_path, monkeypatch, capsys):
    """A finished quest remains in the driver's terminal evidence."""
    class Keyboard:
        def screenshot(self, path):
            pathlib.Path(path).write_bytes(b"")

    class Session:
        kbd = Keyboard()

    monkeypatch.setattr(ohlowatch, "watched", lambda sess: {
        "area": 20, "square": [0, 0, 0], "4A81": 255,
        "4A04": 0, "4ABB": 0,
    })
    monkeypatch.setattr(ohlowatch, "live_window", lambda sess: b"window")
    monkeypatch.setattr(ohlowatch, "render", lambda binp, png: {"groups": {
        "commissions": [{"name": "Clear the Slums", "state": "offered"}],
        "completed": [{"name": "Ohlo's potion", "state": ""}],
    }})

    ohlowatch.capture(Session(), tmp_path, "finished", "test")

    out = capsys.readouterr().out
    assert "Row: 'Clear the Slums' / 'offered'" in out
    assert "Row: \"Ohlo's potion\" / ''" in out

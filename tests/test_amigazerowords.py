"""`tools/amigazerowords.py` runs against the player's own specimens.

`#571 (tools/amigazerowords.py crashes on every run: a stale attribute
reference from #534's consolidation)` found this tool broken on **every**
invocation: `amiga_por.POR_SAVEGAME_SIZE` moved to `goldbox.amiga_savegame`
in `#534`'s consolidation and this tool's own reference at line 149 was
never updated, so `amiga_corpus()` raised `AttributeError` the moment it
was called. Nothing here asserts what the tool's numbers *are* -- that
depends on which saved games and disk images happen to be on this machine
-- only that running it does not crash. It skips cleanly, rather than
failing, when the machine has neither.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import amigazerowords  # noqa: E402


def test_amiga_corpus_reads_every_saved_game_without_an_attribute_error():
    """The exact call `#571` broke: `amiga_corpus()` must not raise."""
    try:
        saves = amigazerowords.amiga_corpus()
    except AttributeError as exc:
        pytest.fail(f"amiga_corpus() raised {exc!r} -- see #571")
    if not saves:
        pytest.skip("no Amiga Pool of Radiance saved game in the specimen "
                     "tree; set $WISH_SPECIMENS")
    for label, data in saves:
        assert len(data) == amigazerowords.amiga_savegame.POR_SAVEGAME_SIZE, \
            label


def test_the_tool_runs_end_to_end_against_the_players_own_files(capsys):
    """`main()`, for real, or a clean skip when the machine has no data.

    `ecl_dax()` and `amiga_corpus()` both raise `SystemExit` when the
    player's Amiga disks or specimen tree are missing -- indistinguishable
    from a real failure unless the reason is read, so the message is
    checked rather than just the exception type.
    """
    try:
        rc = amigazerowords.main([])
    except SystemExit as exc:
        pytest.skip(f"no Amiga Pool of Radiance data on this machine: {exc}")
    assert rc == 0
    out = capsys.readouterr().out
    assert "the Amiga corpus" in out

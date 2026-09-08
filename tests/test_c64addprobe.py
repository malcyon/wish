"""The parts of the add-list probe a machine with no emulator can check.

`tools/c64addprobe.py` drives the running game, so what it establishes cannot
be asserted here. What can is that it refuses rather than guesses: a run with
no save named, and a run that cannot find the player's own disks, both stop
before they claim an emulator slot -- a slot claimed and then abandoned is one
no other agent can use until the process dies.

`#439 (A rename in Wish leaves a parked character's own file on the C64 save
disk under the old name)` is the ticket it belongs to.
"""

from __future__ import annotations

import pytest
from conftest import load_tools_module

probe = load_tools_module("c64addprobe")


def test_a_run_with_no_save_is_refused():
    """`--save` is required: there is nothing to probe without a disk whose
    file name and stored name disagree."""
    with pytest.raises(SystemExit) as stopped:
        probe.main([])
    assert stopped.value.code != 0


def test_no_disks_stops_before_a_slot_is_claimed(tmp_path, monkeypatch):
    """A slot claimed by a run that then gives up is a slot nobody else can
    have until the process dies, so the refusal comes first."""
    claimed = []
    monkeypatch.setattr(probe.gamedisks, "find", lambda _key: "")
    monkeypatch.setattr(probe.por, "claim_slot",
                        lambda *a, **kw: claimed.append(a) or pytest.fail(
                            "claimed a slot with no disks to run"))
    monkeypatch.delenv("POR_DISKS", raising=False)
    with pytest.raises(SystemExit) as stopped:
        probe.main(["--save", str(tmp_path / "nothing.D64")])
    assert "disks" in str(stopped.value)
    assert claimed == []


def test_the_docstring_says_which_question_is_still_open():
    """The tool exists to answer two questions and has answered one. A reader
    who cannot tell which is which will run it and believe the wrong half."""
    assert "ANSWERED" in probe.__doc__
    assert "OPEN" in probe.__doc__

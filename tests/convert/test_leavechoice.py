"""The player's choice of what to leave behind reaches the C64 writer (#432).

A DOS Silver Blades character whose joined scrolls need more than the C64's
sixteen slots converts once the player names what stays behind; each item left
is one line of `Report.left_behind` and never a loss, so Save As does not
refuse the player's own choice.
"""

from __future__ import annotations

import logging
import shutil

import pytest
from test_joinedscroll import (
    SCROLL_A,
    SCROLL_B,
    SSB,
    _party_file,
    _record,
    _shipped_party,
)

from editor import convert, dosimport, saveplan
from goldbox import dos_codec

NO_LEAVE_MESSAGE = "need 17 C64 item slots"


def _crowded_folder(tmp_path):
    """The archives' shipped Silver Blades party with member 1's pack
    replaced by fifteen items and a joined pair: 17 C64 slots."""
    folder = tmp_path / "crowded"
    shutil.copytree(_shipped_party(), folder)
    (folder / "CHRDATA1.SAV").write_bytes(_record(16))
    (folder / "CHRDATA1.STF").write_bytes(
        _party_file(15, SCROLL_A, SCROLL_B))
    return folder


def _files():
    return dosimport.GameFiles(icon=bytes(36), animate=bytes(852))


def test_a_pack_that_needs_17_slots_converts_once_the_player_chooses(
        tmp_path, caplog):
    folder = _crowded_folder(tmp_path)
    with pytest.raises(dos_codec.JoinedScrollsDoNotFit,
                       match=NO_LEAVE_MESSAGE):
        dosimport.rehearse(folder, "A", _files())

    # The wish logger is silenced while the GUI debug log is off, and a
    # logger level filters before caplog's root handler sees the record.
    with caplog.at_level(logging.INFO, logger="wish"):
        conversion = dosimport.rehearse(folder, "A", _files(),
                                        leave={0: {3}})
    report = conversion.report
    assert len(report.left_behind) == 1
    assert "left behind" in report.left_behind[0]
    for line in (*report.losses, *report.dropped):
        assert "inventory" not in line.lower(), line
    # The writer logs each left item; a second logger repeating them would
    # print every line twice.
    logged = [r.getMessage() for r in caplog.records
              if any(line in r.getMessage() for line in report.left_behind)]
    assert len(logged) == len(report.left_behind) == 1, logged


def test_saveplan_rehearse_hands_the_choice_to_the_direction(monkeypatch):
    monkeypatch.setattr(saveplan, "requirements", lambda *a: [])
    seen = {}

    class Fake:
        destination_port = "c64"
        source_port = "dos"

        def rehearse(self, source, slot, options, names=None, leave=None):
            seen["leave"] = leave
            return "rehearsal"

    class Source:
        slot = "A"
        path = "x"

    class Assets:
        game_files = object()

        def has(self, need):
            return True

    got = saveplan.rehearse(Fake(), Source(), Assets(),
                            leave={0: frozenset({3})})
    assert got == ("rehearsal", "A")
    assert seen["leave"] == {0: frozenset({3})}


@pytest.mark.parametrize("name", [
    "C64ToDos", "AmigaToDos", "C64ToAmiga", "DosToAmiga"])
def test_a_direction_that_writes_no_c64_record_refuses_a_choice(name):
    direction = getattr(convert, name, None)
    if direction is None:
        pytest.skip(f"no {name} class")
    inst = direction.__new__(direction)
    inst.source_port, inst.destination_port = "a", "b"
    inst.shape = SSB
    with pytest.raises(saveplan.SaveAsError):
        inst.rehearse(type("S", (), {"slot": "A", "path": "x"})(), "A", None,
                      leave={0: {1}})


def test_the_choice_reaches_the_dos_to_c64_direction(monkeypatch):
    seen = {}

    def fake(folder, slot, options, leave=None):
        seen["leave"] = leave
        raise RuntimeError("stop")

    monkeypatch.setattr(dosimport, "rehearse", fake)
    direction = convert.DosToC64.__new__(convert.DosToC64)
    direction.source_port, direction.shape = "dos", SSB
    direction._name = "N{slot}"

    class Source:
        def folder(self):
            import contextlib
            return contextlib.nullcontext("f")

    with pytest.raises(RuntimeError):
        direction.rehearse(Source(), "A", _files(), leave={0: {3}})
    assert seen["leave"] == {0: {3}}

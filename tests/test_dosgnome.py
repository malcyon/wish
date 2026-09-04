"""`tools/dosgnome.py`, the DOS character-creation drive (#84).

Driving the game needs DOSBox, an X display and about a minute a boot, so what
is tested here is the part that decides what a run *does* -- the step grammar
-- and the part that decides what a run *says*, which is how a `.SPC` file is
split into records.  Both have a failure that does not look like one: a `!C`
pressed as a key gives a run with no snapshots and a log that reads as if
everything worked, and a record split at the wrong stride gives ids that are
somebody else's payload bytes and look like effect numbers.

The reading is then corroborated against the player's own archives, which is
the point of the tool: the eight characters rolled for #84 reproduced the
census these files carry, so the same reader has to agree with them.
"""

import functools
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import dosgnome  # noqa: E402

#: Name -> the effect ids the archives' own `.SPC` files hold for that
#: character, established in `docs/117-save-conversion.md` and reproduced from
#: the game's creation screens in #84.  THRENDER GRONE is a dwarf, PHINEAS a
#: halfling, and the pair is what makes 26 and 47 the dwarf's rather than
#: every sturdy race's.
CENSUS = {
    "CHRDATA1.SPC": [90, 97, 26, 47],       # THRENDER GRONE, dwarf
    "CHRDATA6.SPC": [90, 97],               # PHINEAS, halfling
    "CHRDATA3.SPC": [107],                  # RHIANNON, elf
}


def _candidates():
    """`gamedisks.toml`'s own search list for the DOS archives (#212)."""
    from tools import gamedisks
    return gamedisks.candidates("dos-archives")


@functools.lru_cache(maxsize=1)
def _shipped_saves():
    """`Default files/Saves` for DOS Pool of Radiance, or None.

    The shipped directory rather than the played one, because the census
    above names files by slot letter and the shipped copy is the one both
    archive collections agree on.
    """
    for root in _candidates():
        if not root.is_dir():
            continue
        for path in root.glob("*/games/POOLRAD/Default files/Saves"):
            if (path / "CHRDATA1.SPC").is_file():
                return path
    return None


# --- the step grammar --------------------------------------------------------


def test_a_bare_keysym_is_pressed():
    for key in ("Return", "Escape", "End", "c", "y", "1"):
        assert dosgnome.step_kind(key) == ("key", key)


def test_a_bang_snapshots_and_does_not_press_anything():
    """The `SAVE` directory is the whole measurement, and this is the prefix
    that takes a copy of it."""
    assert dosgnome.step_kind("!gnome2") == ("snapshot", "gnome2")
    assert dosgnome.step_kind("!final") == ("snapshot", "final")


def test_a_hash_types_a_string_rather_than_pressing_one_key():
    """`CHARACTER NAME:` wants eight keystrokes, and a step called `#gnomf1`
    pressed as a keysym is a step `xdotool` refuses."""
    assert dosgnome.step_kind("#gnomf1") == ("type", "gnomf1")


def test_a_tilde_waits():
    assert dosgnome.step_kind("~3") == ("wait", 3.0)
    assert dosgnome.step_kind("~0.5") == ("wait", 0.5)


def test_a_tilde_with_no_number_is_refused_rather_than_pressed_as_a_key():
    """Falling back to "press it as a key" would swallow the typo and leave
    the run looking like it worked."""
    with pytest.raises(ValueError):
        dosgnome.step_kind("~soon")


# --- splitting a `.SPC` file -------------------------------------------------


def test_records_are_nine_bytes_each():
    data = bytes(range(27))
    assert dosgnome.records(data) == [data[0:9], data[9:18], data[18:27]]


def test_a_short_tail_is_dropped_rather_than_padded():
    """The record count comes from the file's length, so a file that is not a
    multiple of nine is a fact about the run rather than something to round
    away -- `goldbox.dos.EFFECT_NEXT_NULL`, which measured that."""
    assert dosgnome.records(bytes(9 + 4)) == [bytes(9)]
    assert dosgnome.records(bytes(5)) == []
    assert dosgnome.records(b"") == []


def test_an_empty_file_is_reported_rather_than_read_as_no_effects(tmp_path):
    """A human carries no `.SPC` file at all; a zero-length one would be a
    different thing and has to be visible."""
    path = tmp_path / "EMPTY.SPC"
    path.write_bytes(b"")
    assert dosgnome.describe(path) == ["EMPTY.SPC: 0 bytes, no whole record"]


def test_describe_names_the_id_and_the_four_payload_bytes(tmp_path):
    """One innate record, in the shape every measured specimen holds."""
    path = tmp_path / "ONE.SPC"
    path.write_bytes(bytes((97, 0, 0, 0xFF, 0)) + bytes(4))
    line, = dosgnome.describe(path)
    assert "id  97" in line
    assert "payload 00 00 ff 00" in line
    assert "next 00000000" in line


# --- corroboration against the player's own files ----------------------------


@pytest.mark.skipif(_shipped_saves() is None,
                    reason="needs the DOS archives; set FR_ARCHIVES")
@pytest.mark.parametrize("name,ids", sorted(CENSUS.items()))
def test_the_reader_reproduces_the_archives_census(name, ids):
    """The dwarf, the halfling and the elf, read off the shipped saves.

    This is the control on the gnome measurement: the same reader, the same
    stride, applied to three characters whose ids were established
    independently.  A wrong stride would show up here as ids nobody has ever
    named.
    """
    path = _shipped_saves() / name
    assert [rec[0] for rec in dosgnome.records(path.read_bytes())] == ids


@pytest.mark.skipif(_shipped_saves() is None,
                    reason="needs the DOS archives; set FR_ARCHIVES")
def test_every_innate_record_in_the_archives_carries_the_same_payload():
    """`00 00 FF 00`, in every innate record the archives hold.

    `goldbox.dos.INNATE_PAYLOAD` is those four bytes and #84 confirmed them
    for a gnome's 18 and 48 as well; the archives are where the other six ids
    were measured, so a change to the reader that broke the shape would fail
    here rather than only in an emulator run nobody reruns.
    """
    from goldbox import dos
    seen = 0
    for path in sorted(_shipped_saves().glob("*.SPC")):
        for rec in dosgnome.records(path.read_bytes()):
            if rec[0] in dos.INNATE_EFFECTS:
                assert rec[1:5] == dos.INNATE_PAYLOAD, (path.name, rec[0])
                seen += 1
    assert seen >= 6, "no innate records found, so nothing was checked"

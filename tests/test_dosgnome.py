"""`tools/dosgnome.py`, the DOS character-creation drive (#84).

Driving the game needs DOSBox, an X display and about a minute a boot, so what
is tested here is the part that decides what a run *does* -- the step grammar
-- and the part that decides what a run *says*, which is how a `.SPC` file is
split into records.  Both have a failure that does not look like one: a `!C`
pressed as a key gives a run with no snapshots and a log that reads as if
everything worked, and a record split at the wrong stride gives ids that are
somebody else's payload bytes and look like effect numbers.

The reading is then corroborated against the eight characters #84 rolled --
one per race, created keystroke by keystroke in the game's own screens and
kept in the specimen tree.  **They replaced the archives here on 2026-09-04**:
the census used to be read off `Default files/Saves`, which is a download with
no chain of custody and cannot be told from a party somebody edited, and
`#246 (Nothing tells an engine-written DOS record from one edited with Gold
Box Companion, and conclusions already rest on edited ones)` is why that is no
longer good enough for a measurement.  `.claude/rules/testing.md`'s "A
specimen is only evidence if we know who wrote it" is the rule.
"""

import pathlib
import sys

import pytest
from gamedata import needs_specimens, specimen

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import dosgnome  # noqa: E402

#: Specimen -> the effect ids the engine wrote into that character's `.SPC`
#: at creation.  One per race, from #84's eight rolls: the gnome's 18 and 48
#: are what the issue was opened to find, and the dwarf beside the halfling is
#: what makes 26 and 47 the dwarf's rather than every sturdy race's.
#:
#: `human7` is in the table with an empty list because the engine writes a
#: human **no `.SPC` file at all**, which is the case a reader that treats a
#: missing file as an empty one would never notice going wrong.
CENSUS = {
    "dwarfc4": ("halfelf-DWARFC4.SPC", [90, 97, 26, 47]),
    "halfl5": ("party-HALFL5.SPC", [90, 97]),
    "elf6": ("party-ELF6.SPC", [107]),
    "halfe8": ("party-HALFE8.SPC", [124]),
    "gnomf1": ("halfelf-GNOMF1.SPC", [97, 18, 47, 48]),
    "gnomt2": ("halfelf-GNOMT2.SPC", [97, 18, 47, 48]),
    "gnomft3": ("halfelf-GNOMFT3.SPC", [97, 18, 47, 48]),
    "human7": ("party-HUMAN7.SPC", []),
}

#: The `#249` party, rolled a fortnight after #84's eight and by a different
#: tool, as the same-boot control on the table above: four races repeated, and
#: the two humans carrying no `.SPC` again.
CONTROL_PARTY = "por-party-l1-rolled"
CONTROL = {
    "WISHMAG.SPC": [107],                   # elf
    "WISHTHI.SPC": [90, 97],                # halfling
    "WISHDWF.SPC": [90, 97, 26, 47],        # dwarf
    "WISHHEL.SPC": [124],                   # half-elf
}


# The archives' `Default files/Saves` used to be found here and the census read
# off it.  It is gone rather than left unused: a helper that resolves an
# untrusted directory is one import away from being the corpus again.


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


@needs_specimens
@pytest.mark.parametrize("name,filename,ids",
                         [(name, f, ids) for name, (f, ids) in sorted(
                             CENSUS.items())])
def test_the_reader_reproduces_the_racial_effect_sets(name, filename, ids):
    """Six races, read off characters this project watched being rolled.

    The same reader and the same stride applied to a dwarf, a halfling, an
    elf, a half-elf, three gnomes and a human.  A wrong stride shows up here
    as ids nobody has ever named; a reader that guessed the race from
    anything but the file would have to guess right eight times.
    """
    path = specimen(name) / filename
    if not ids:
        assert not path.exists(), f"{filename} exists, but a human has none"
        return
    assert [rec[0] for rec in dosgnome.records(path.read_bytes())] == ids


@needs_specimens
@pytest.mark.parametrize("filename,ids", sorted(CONTROL.items()))
def test_a_second_party_rolled_later_reproduces_the_same_sets(filename, ids):
    """`#249`'s party against `#84`'s eight: four races, same ids.

    Two parties, two tools, two evenings, one engine.  This is what makes the
    table above a property of the race rather than of one run's rolls.
    """
    path = specimen(CONTROL_PARTY) / filename
    assert [rec[0] for rec in dosgnome.records(path.read_bytes())] == ids


@needs_specimens
def test_every_innate_record_we_watched_being_written_carries_the_same_payload():
    """`00 00 FF 00`, in every innate record in the specimen tree.

    `goldbox.dos.INNATE_PAYLOAD` is those four bytes.  24 innate records
    across the two parties, and every one of them holds the same four -- so a
    change to the reader that broke the shape fails here rather than only in
    an emulator run nobody reruns.
    """
    from goldbox import dos
    seen = 0
    for name in tuple(CENSUS) + (CONTROL_PARTY,):
        for path in sorted(specimen(name).glob("*.SPC")):
            for rec in dosgnome.records(path.read_bytes()):
                if rec[0] in dos.INNATE_EFFECTS:
                    assert rec[1:5] == dos.INNATE_PAYLOAD, (path.name, rec[0])
                    seen += 1
    assert seen >= 24, f"only {seen} innate records checked"

"""Party strength: `DUNGEON $1BE8`, re-implemented in `goldbox/strength.py`.

The routine is what sizes a random encounter -- its value becomes the count
operand of `LOADMON` in twelve area scripts -- so what is tested here is every
term that moves it and, just as much, the things that famously do not:
experience, ability scores, the clock, current hit points.

The data is the player's own: `tests/fixtures` for the captured single
character, and the `PORSAVE*.D64` save disks for the six-character party that
settled the question. Nothing here is a slice of a game file.
"""

from __future__ import annotations

import pathlib

import pytest
from gamedata import FIXTURES, disk_dir

from automap.target import MemoryTarget
from goldbox import strength
from goldbox.savegame import HEADER_SIZE, ROSTER_STRIDE, SLOT_STRIDE


def captured() -> tuple[bytearray, bytearray]:
    """BRUTUS alone in New Phlan: the two blocks a live read makes."""
    save0 = bytearray((FIXTURES / "savedgame0.bin").read_bytes()[2:])
    roster = bytearray((FIXTURES / "savedgame1.bin").read_bytes()[2:])
    return save0, roster


def record_byte(save0: bytearray, slot: int, offset: int, value: int) -> None:
    save0[HEADER_SIZE + slot * SLOT_STRIDE + offset] = value


def roster_byte(roster: bytearray, slot: int, offset: int, value: int) -> None:
    roster[slot * ROSTER_STRIDE + offset] = value


def value_of(save0, roster) -> int:
    return strength.from_bytes(bytes(save0), bytes(roster)).total


# --- the sum, against real data ---------------------------------------------

def test_the_captured_character_sums_the_way_the_routine_does():
    save0, roster = captured()
    party = strength.from_bytes(bytes(save0), bytes(roster))
    (brutus,) = party.parts
    assert brutus.name == "BRUTUS"
    # THAC0 18, so a field of 42: 5 x (42 - 39) = 15, plus 11 hit points
    # maximum. A fighter, so no class term, and AC 9 is nowhere near the floor.
    assert brutus.thac0 == 18 and brutus.hp_term == 11
    assert brutus.thac0_term == 15 and brutus.armour_term == 0
    assert brutus.total == 26
    assert (party.total, party.value) == (26, 2)


@pytest.mark.skipif(disk_dir() is None, reason="needs the player's save disks")
@pytest.mark.parametrize("disk, expected", [("PORSAVE", 11), ("PORSAVE11", 13)])
def test_the_save_disks_give_the_numbers_the_experiment_recorded(disk, expected):
    """The six-character party, before and after the shopping trip.

    115 -> 11 and 130 -> 13, with MALCYON 27 and BRUTUS 26 in the second. This
    is the whole of `docs/114-party-strength.md` checked end to end.
    """
    from goldbox.d64 import D64, load_payload

    path = pathlib.Path(disk_dir()) / f"{disk}.D64"
    if not path.exists():
        pytest.skip(f"no {disk}.D64 here")
    image = D64.open(str(path))
    party = strength.from_bytes(load_payload(image, "SAVEDGAME0"),
                                load_payload(image, "SAVEDGAME1"))
    assert party.value == expected
    assert [p.name for p in party.parts] == [
        "MALCYON", "LADY KATHERINE", "ROLAND", "SILAS", "MAGNUS", "BRUTUS"]
    if disk == "PORSAVE11":
        assert [p.total for p in party.parts] == [27, 13, 16, 24, 24, 26]
        assert party.total == 130
        assert party.slums_count == 8            # (13 / 3) * 2
    else:
        assert party.total == 115
        assert party.slums_count == 6


# --- which slots count ------------------------------------------------------

def test_a_dead_character_stops_counting():
    """`$1BF6 BMI`: bit 7 of roster +0x00, seen going $01 -> $84 on death.

    The party gets *weaker* encounters while somebody is down, which is the
    opposite of the usual assumption about difficulty scaling.
    """
    save0, roster = captured()
    assert value_of(save0, roster) == 26
    roster_byte(roster, 0, 0x00, 0x84)
    assert value_of(save0, roster) == 0


def test_an_empty_slot_is_skipped():
    save0, roster = captured()
    roster_byte(roster, 0, 0x00, 0x00)
    assert strength.from_bytes(bytes(save0), bytes(roster)).parts == ()


def test_party_size_is_only_the_number_of_terms():
    """No head count anywhere in the routine: a second character adds its own
    sum and nothing else."""
    save0, roster = captured()
    roster[ROSTER_STRIDE:2 * ROSTER_STRIDE] = roster[:ROSTER_STRIDE]
    save0[HEADER_SIZE + SLOT_STRIDE:HEADER_SIZE + 2 * SLOT_STRIDE] = \
        save0[HEADER_SIZE:HEADER_SIZE + SLOT_STRIDE]
    assert value_of(save0, roster) == 52


# --- the terms --------------------------------------------------------------

def test_a_better_thac0_is_worth_five_a_point():
    save0, roster = captured()
    roster_byte(roster, 0, 0x0E, 43)               # THAC0 17, one better
    assert value_of(save0, roster) == 26 + 5


def test_the_thac0_field_is_used_as_stored_and_wraps_below_39():
    """`$1C01 SBC #$27` has no underflow guard. A current THAC0 worse than 21
    -- a cursed weapon is the plausible route -- makes the term enormous."""
    save0, roster = captured()
    roster_byte(roster, 0, 0x0E, 38)               # THAC0 22
    party = strength.from_bytes(bytes(save0), bytes(roster))
    (one,) = party.parts
    assert one.wrapped and one.thac0_term == 5 * 255
    assert party.value > 100


def test_hit_points_are_the_maximum_and_wounds_do_not_shrink_them():
    """Record 0x076, not the roster's current hit points. Curse of the Azure
    Bonds reads current; Pool of Radiance does not."""
    save0, roster = captured()
    roster_byte(roster, 0, 0x19, 1)                # nearly dead
    assert value_of(save0, roster) == 26
    record_byte(save0, 0, 0x076, 40)
    assert value_of(save0, roster) == 26 - 11 + 40


def test_armour_class_counts_only_from_zero_and_better():
    """`$1C16 SBC #$3C / BCC`: the field is `60 - AC`, so the term is silent
    until AC reaches 0 and is worth five a point after that."""
    save0, roster = captured()
    for field, term in ((51, 0), (59, 0), (60, 0), (62, 10)):
        roster_byte(roster, 0, 0x0F, field)
        assert value_of(save0, roster) == 26 + term


def test_a_cleric_scores_four_a_level_and_a_magic_user_eight():
    save0, roster = captured()
    record_byte(save0, 0, 0x0A0, 3)                # level 3
    record_byte(save0, 0, 0x0EB, 0x08)             # fighter: no class term
    assert value_of(save0, roster) == 26
    record_byte(save0, 0, 0x0EB, 0x02)             # cleric
    assert value_of(save0, roster) == 26 + 12
    record_byte(save0, 0, 0x0EB, 0x01)             # magic-user
    assert value_of(save0, roster) == 26 + 24
    record_byte(save0, 0, 0x0EB, 0x03)             # both, one level byte
    assert value_of(save0, roster) == 26 + 36


# --- and what does not move it ----------------------------------------------

def test_experience_and_ability_scores_and_the_clock_do_nothing():
    """The routine reads five fields and no others. The folklore about all-18
    parties is right only through THAC0 and hit points."""
    save0, roster = captured()
    for offset in range(0x14, 0x1A):               # the six ability scores
        record_byte(save0, 0, offset, 18)
    for offset in (0x0E8, 0x0E9, 0x0EA):           # experience, 24-bit
        record_byte(save0, 0, offset, 0xFF)
    save0[0x49C7 - 0x4900:0x49CA - 0x4900] = b"\x09\x09\x09"    # the clock
    assert value_of(save0, roster) == 26


def test_no_party_strength_byte_is_stored_anywhere():
    """It is recomputed on every call, so the same bytes always give the same
    answer and no cached copy can go stale."""
    save0, roster = captured()
    first = strength.from_bytes(bytes(save0), bytes(roster))
    assert first.total == strength.from_bytes(bytes(save0), bytes(roster)).total


# --- the divide, and what the scripts do with it ----------------------------

def test_the_sum_is_divided_once_at_the_end():
    """PoR divides the 16-bit total; CoAB divides per character, which with six
    characters loses up to 5."""
    save0, roster = captured()
    record_byte(save0, 0, 0x076, 29)               # 15 + 29 = 44
    party = strength.from_bytes(bytes(save0), bytes(roster))
    assert (party.total, party.value) == (44, 4)


def test_the_slums_count_is_the_strength_divided_by_three_times_two():
    save0, roster = captured()
    record_byte(save0, 0, 0x076, 115)
    party = strength.from_bytes(bytes(save0), bytes(roster))
    assert party.value == 13 and party.slums_count == 8


# --- how it is read ---------------------------------------------------------

def test_it_reads_a_live_machine_through_any_target():
    save0, roster = captured()
    machine = MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(roster)})
    assert strength.read_live(machine).total == 26
    assert [addr for addr, _ in machine.reads] == [0x4900, 0x8300]


def test_the_breakdown_names_every_term_it_used():
    save0, roster = captured()
    (one,) = strength.from_bytes(bytes(save0), bytes(roster)).parts
    assert dict(one.terms) == {"THAC0": 15, "hp max": 11}
    assert one.line == "BRUTUS 26 = 15 THAC0 + 11 hp max"


def test_short_blocks_are_refused_rather_than_read_as_zeros():
    save0, roster = captured()
    with pytest.raises(ValueError):
        strength.from_bytes(bytes(save0[:0x100]), bytes(roster))
    with pytest.raises(ValueError):
        strength.from_bytes(bytes(save0), bytes(roster[:0x40]))


# --- and where the window puts it -------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def a_window(app, tmp_path, monkeypatch, machine):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from automap.state import Automapper
    from automap.window import AutomapWindow

    return AutomapWindow(Automapper(machine, {}), drive=False)


def test_the_window_shows_the_strength_and_follows_the_live_bytes(
        app, tmp_path, monkeypatch):
    """Live data, not the save file: the number moves as the party does.

    Readying a better weapon is the cheap way to see it move, and is exactly
    what moved it on Donald's disks.
    """
    save0, roster = captured()
    machine = MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(roster)})
    window = a_window(app, tmp_path, monkeypatch, machine)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert "party strength 2" in window.strength_label.text()
    assert "BRUTUS 26 = 15 THAC0 + 11 hp max" in window.strength_label.toolTip()

    roster_byte(roster, 0, 0x0E, 60)                     # THAC0 0, absurdly good
    machine.memory[0x8300] = bytes(roster)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert "party strength 11" in window.strength_label.text()


def test_the_line_says_what_the_number_costs(app, tmp_path, monkeypatch):
    """A bare 2 says nothing; the slums count is what a player feels."""
    save0, roster = captured()
    window = a_window(app, tmp_path, monkeypatch,
                      MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(roster)}))
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert "slums encounter 0 monsters" in window.strength_label.text()
    grid = window.centralWidget().layout()
    assert grid.getItemPosition(grid.indexOf(window.strength_label))[0] == 2

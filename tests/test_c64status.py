from __future__ import annotations

"""Carrying a character's status and out-of-play flag across a conversion.

#235 (Two unattributed DOS byte ranges in the combat tail are dropped
converting to C64, and nobody knows what they hold) started as two
unattributed runs and ended with a measurement at both ends: DOS keeps the
status at record 0x10C and an active flag at 0x10D, and the C64 packs both
into record 0x100 -- the low three bits are the state the sheet puts into
words and bit 7 is whether the game is still playing the character.

`goldbox/c64_codec.py` used to write a hard 1 there and call the field
"roster bookkeeping, not character state", so a DOS character who was dead
arrived on the C64 alive and one the game had taken out of the party arrived
a full member.  These are the tests of the carry that replaced it.

None of them needs a save on disk: the DOS side is a record built here and
the C64 side is a neutral character built here, which is what makes them run
on a machine with no game disks.
"""

import re

import pytest

from goldbox import c64_codec, dos, dos_layout, neutral
from goldbox.layout import Confidence
from goldbox.neutral import NeutralCharacter
from goldbox.record import CharacterRecord

#: The C64 bytes the six overlays are seen to write for a party member, and
#: the word `LIBRARY $38BE` draws for each.  `$84` DYING is in the list even
#: though the sheet cannot be made to show it by playing -- `COMBAT $2161`
#: turns every `$84` in the party into `$85` as the fight ends -- because the
#: engine does not normalise the byte on load and a staged one reads back.
ENGINE_WRITES = {
    0x01: "okay", 0x82: "gone", 0x83: "dead", 0x84: "dying",
    0x85: "unconscious", 0x86: "running", 0x87: "stoned",
}

TAIL = dos_layout.FIELDS_BY_NAME["field_10c_10f"]
CONSTANT = dos_layout.FIELDS_BY_NAME["field_83_87"]


def _dos_record(tail: bytes = b"\x00\x01\x00\x00",
                constant: bytes = b"\x00\x00\x01\x00\x00") -> dos.DosCharacter:
    """A Pool of Radiance record that is zero but for the two #235 runs."""
    raw = bytearray(dos_layout.RECORD_SIZE)
    raw[TAIL.offset:TAIL.end] = tail
    raw[CONSTANT.offset:CONSTANT.end] = constant
    return dos.DosCharacter(bytes(raw))


def _c64_record(status: int) -> CharacterRecord:
    rec = CharacterRecord(bytes(CharacterRecord.SIZE))
    rec.set("roster_in_use", status)
    return rec


# --- DOS to the C64 ----------------------------------------------------------

def test_a_dos_character_the_game_knocked_out_arrives_unconscious():
    """The whole of what a player loses, in one assertion.

    `04 00 00 00` is what the DOS engine itself wrote for MAGNUS, who came out
    of a driven fight at 0 hit points: status 4, Unconscious, and the active
    flag clear.  The C64's own byte for that character is `$85` -- 5 is
    UNCONSIOUS in the game's table and bit 7 is the out-of-play flag -- which
    is what an orc taking a C64 character to his last hit point made the
    engine write in a driven fight.

    Before the carry this wrote `$01`, OK, and the character arrived well.
    """
    char = _dos_record(b"\x04\x00\x00\x00")
    rec, rep = c64_codec.write(dos.to_neutral(char))
    assert rec.get("roster_in_use") == 0x85
    # And the report says where it came from rather than calling it a
    # constant, which is what it used to say.
    assert "unconscious" in rep.sources[0x100]


def test_a_dos_character_still_standing_arrives_ok_and_in_play():
    """The control for the test above: the same conversion, one byte apart."""
    char = _dos_record(b"\x00\x01\x00\x00")
    rec, _ = c64_codec.write(dos.to_neutral(char))
    assert rec.get("roster_in_use") == 0x01


@pytest.mark.parametrize("number,expected", [
    (0, 0x01),      # Okay
    (3, 0x86),      # Running
    (4, 0x85),      # Unconscious
    (5, 0x84),      # Dying
    (6, 0x83),      # Dead
    (7, 0x87),      # Stoned
    (8, 0x82),      # Gone
])
def test_every_dos_status_with_a_c64_value_crosses_to_it(number, expected):
    """Seven of the nine DOS states, each to the C64 byte the engine writes.

    The two enumerations are **different** and this is what a table rather
    than a copy is for: DOS 6 is Dead and the C64's DEAD is 3, DOS 3 is
    Running and the C64's RUNNING is 6.  Copying the number across would put
    a dead character in as a running one.
    """
    active = 1 if number == 0 else 0
    char = _dos_record(bytes([number, active, 0, 0]))
    rec, _ = c64_codec.write(dos.to_neutral(char))
    assert rec.get("roster_in_use") == expected


@pytest.mark.parametrize("number,name", [(1, "animated"),
                                         (2, "temporarily gone")])
def test_a_dos_state_the_c64_does_not_have_is_reported(number, name):
    """The legitimate "the destination has no such field" case, and it is
    established rather than assumed: `LIBRARY $38BE` indexes seven words with
    three bits and neither of these is among them.  `SPELLE04 $AA11` writes
    `$03` beside creature type 4, undead, which is the nearest thing to
    Animated and is a **dead** character with bit 7 clear on something the
    same routine marks as not a player character -- so it is not the same
    thing and is not used."""
    char = _dos_record(bytes([number, 1, 0, 0]))
    assert dos.to_neutral(char).get("status") == name
    rec, rep = c64_codec.write(dos.to_neutral(char))
    assert rec.get("roster_in_use") == 0x01
    assert c64_codec.NO_C64_STATUS[name] in rep.dropped, rep.dropped


def test_a_dos_status_past_the_end_of_the_table_is_reported_not_guessed():
    """The game has nine states and a save holding a tenth is not one of
    them, so the reader says so rather than picking the nearest."""
    char = _dos_record(bytes([len(neutral.STATUS_NAMES), 1, 0, 0]))
    out = dos.to_neutral(char)
    assert "status" not in out
    assert any("status" in line for line in out.dropped), out.dropped


# --- the C64 back to the neutral record --------------------------------------

def test_a_c64_character_the_game_marked_dead_reads_back_as_the_dos_number():
    """`$83` is DEAD on the C64 and Dead is 6 in the DOS enumeration.

    Read the C64 byte, and the number the DOS record would want is the index
    of the neutral name in the game's own nine status words -- which is the
    order `neutral.STATUS_NAMES` carries and DOS's own numbering.
    """
    out = c64_codec.read(_c64_record(0x83))
    assert out.get("status") == "dead"
    assert neutral.STATUS_NAMES.index(out.get("status")) == 6
    assert out.get("active") is False


@pytest.mark.parametrize("byte,name", sorted(ENGINE_WRITES.items()))
def test_every_status_the_c64_engine_writes_round_trips(byte, name):
    """Read a C64 record and write it back: seven of seven come out the same
    byte.  A table wrong in one direction and not the other would pass one of
    these tests and fail this one."""
    out = c64_codec.read(_c64_record(byte))
    assert out.get("status") == name
    rec, _ = c64_codec.write(out)
    assert rec.get("roster_in_use") == byte


def test_an_empty_roster_slot_is_not_a_state():
    """Zero at record 0x100 means the slot holds no character -- it is what
    DROP CHARACTER writes (`CAMP $0C0B`) -- so it sets neither field rather
    than reading as the first word of the table."""
    out = c64_codec.read(_c64_record(0x00))
    assert "status" not in out
    assert "active" not in out


# --- and back to DOS ----------------------------------------------------------

def test_a_c64_character_the_game_marked_dead_writes_the_dos_number_back():
    """The other direction, and the reason a table is needed rather than a
    copy: the C64's DEAD is 3 and DOS's is 6.  Writing the C64 byte straight
    into the DOS record would make a dead character a running one."""
    out = c64_codec.read(_c64_record(0x83))
    rec, _, _, rep = dos.write(out)
    assert rec[TAIL.offset] == 6
    assert rec[TAIL.offset + 1] == 0        # the active flag, DOS polarity
    assert "dead" in rep.sources[TAIL.offset]


@pytest.mark.parametrize("byte,number", [
    (0x01, 0), (0x82, 8), (0x83, 6), (0x84, 5),
    (0x85, 4), (0x86, 3), (0x87, 7),
])
def test_every_c64_status_writes_the_dos_number_for_the_same_word(byte, number):
    """Seven of seven, each C64 byte to the DOS number for the same word.

    The two enumerations agree nowhere but Okay: 3 is DEAD on the C64 and
    Running in DOS, 6 is RUNNING on the C64 and Dead in DOS.  A conversion
    that copied the low three bits would swap those two silently.
    """
    rec, _, _, _ = dos.write(c64_codec.read(_c64_record(byte)))
    assert rec[TAIL.offset] == number
    assert rec[TAIL.offset + 1] == (1 if byte == 0x01 else 0)


def test_a_dos_record_at_status_four_round_trips_through_the_c64_and_back():
    """The whole carry in one pass: the DOS bytes the engine wrote for a
    character it knocked out, to the C64 byte the C64 engine writes for the
    same thing, and back to the DOS bytes it started from."""
    char = _dos_record(b"\x04\x00\x00\x00")
    c64, _ = c64_codec.write(dos.to_neutral(char))
    assert c64.get("roster_in_use") == 0x85
    rec, _, _, _ = dos.write(c64_codec.read(c64))
    assert bytes(rec[TAIL.offset:TAIL.offset + 2]) == b"\x04\x00"


def test_the_combat_side_and_quickfight_now_carry_across_and_back():
    """The last two bytes of #235 (Two unattributed DOS byte ranges in the
    combat tail are dropped converting to C64, and nobody knows what they
    hold): 0x10E is the combat side and 0x10F is quickfight, and the C64
    keeps both in one byte at record 0x10C -- bit 0 the side, bit 7
    quickfight -- named `combat_side` in `goldbox/layout.py`.  Before this,
    a source that quick-fought lost it going to the C64 and gained it coming
    back, unconditionally."""
    quick = _dos_record(b"\x00\x01\x00\x01")
    assert dos.to_neutral(quick).get("status") == "okay"
    c64, _ = c64_codec.write(dos.to_neutral(quick))
    assert c64.get("combat_side") == 0x80
    rec, _, _, _ = dos.write(c64_codec.read(c64))
    assert bytes(rec[TAIL.offset + 2:TAIL.end]) == b"\x00\x01"


# --- the combat side and quickfight, packed into one C64 byte ---------------

@pytest.mark.parametrize("hostile,quickfight,byte", [
    (0, 0, 0x00),
    (1, 1, 0x81),
    (0, 1, 0x80),
    (1, 0, 0x01),
])
def test_dos_hostile_and_quickfight_pack_into_one_c64_byte(
        hostile, quickfight, byte):
    """The DOS engine's own script-field accessor over C64 record 0x10C
    (docs/169-dos-combat-side.md): `0x81` if the side bit is set, `0x80` if
    only quickfight is, else 0."""
    char = _dos_record(bytes([0, 1, hostile, quickfight]))
    rec, _ = c64_codec.write(dos.to_neutral(char))
    assert rec.get("combat_side") == byte


@pytest.mark.parametrize("byte,hostile,quickfight", [
    (0x00, 0, 0),
    (0x81, 1, 1),
    (0x80, 0, 1),
    (0x01, 1, 0),
])
def test_the_c64_byte_unpacks_into_dos_hostile_and_quickfight(
        byte, hostile, quickfight):
    """The reverse of the table above, over the same four values."""
    rec = _c64_record(0x01)
    rec.set("combat_side", byte)
    out = c64_codec.read(rec)
    assert out.get("hostile") is bool(hostile)
    assert out.get("quickfight") is bool(quickfight)
    written, _, _, _ = dos.write(out)
    assert written[TAIL.offset + 2] == hostile
    assert written[TAIL.offset + 3] == quickfight


@pytest.mark.parametrize("status,active,hostile,quickfight", [
    (0, 1, 0, 0),
    (4, 0, 1, 1),
    (6, 0, 0, 1),
    (0, 1, 1, 0),
])
def test_the_whole_combat_tail_round_trips_through_dos(
        status, active, hostile, quickfight):
    """DOS -> neutral -> DOS keeps all four bytes of the combat tail, for
    four values spanning both the status/active pair and the side/quickfight
    pair -- not just the two #235 first converted."""
    tail = bytes([status, active, hostile, quickfight])
    char = _dos_record(tail)
    rec, _, _, _ = dos.write(dos.to_neutral(char))
    assert bytes(rec[TAIL.offset:TAIL.end]) == tail


def test_field_10c_10f_no_longer_shows_as_dropped():
    """The whole point of naming C64 record 0x10C: `field_10c_10f` comes off
    the drop list entirely, both in the table and in what a real conversion
    reports."""
    assert "field_10c_10f" not in dict(dos.DROPPED)
    assert "field_10c_10f" not in dos.UNREPORTED_DROPS
    disposition = dos.field_disposition()
    assert not disposition["field_10c_10f"].startswith("dropped:")

    char = _dos_record(b"\x00\x01\x01\x01")
    _rec, report = dos.to_c64_record(char)
    assert not [d for d in report.dropped if "field_10c_10f" in d]
    assert not [d for d in report.dropped if "quickfight" in d.lower()]


# --- bit 7 is a flag of its own ----------------------------------------------

def test_bit_seven_is_read_apart_from_the_status():
    """Measured in the running game, one boot, four values and three
    controls: `$81` -- OK with the flag set -- drew OK on the character sheet
    and **red** in the party panel, and `$05` -- unconscious with the flag
    clear -- drew UNCONSIOUS on the sheet and the panel's ordinary colour.
    Two of two red against nine of nine not, across that boot and an all-`$01`
    control.  `LIBRARY $38BE` masks the byte with 7 before drawing the word
    and `$3E47` is `LDX $6E34 / CMP #$80 / BCC + / LDX #$02`, which is the
    same partition read out of the code.
    """
    okay_but_out = c64_codec.read(_c64_record(0x81))
    assert okay_but_out.get("status") == "okay"
    assert okay_but_out.get("active") is False

    hurt_but_in = c64_codec.read(_c64_record(0x05))
    assert hurt_but_in.get("status") == "unconscious"
    assert hurt_but_in.get("active") is True


def test_the_two_ports_hold_the_flag_at_opposite_polarities():
    """DOS `0x10D` is 1 for a character shown normally; the C64's bit 7 is set
    for one that is not.  Both draw the name red in the party panel, which is
    what says they are the same flag -- so a conversion that copied the bit
    instead of converting it would invert every character."""
    active = dos.to_neutral(_dos_record(b"\x00\x01\x00\x00"))
    assert active.get("active") is True
    rec, _ = c64_codec.write(active)
    assert not rec.get("roster_in_use") & 0x80

    inactive = dos.to_neutral(_dos_record(b"\x00\x00\x00\x00"))
    assert inactive.get("active") is False
    rec, _ = c64_codec.write(inactive)
    assert rec.get("roster_in_use") & 0x80


def test_a_source_with_a_status_and_no_active_flag_takes_bit_seven_from_it():
    """The Amiga has no located home for either, and a C64-to-C64 edit may
    supply one and not the other.  Every value the C64 engine writes for a
    party member pairs the two -- `$01` is the only one with bit 7 clear --
    so a status with no flag beside it gets the flag the engine would have
    given it, and that rule is stated in the report rather than silent."""
    char = NeutralCharacter("test")
    char.set("status", "dead", "made up")
    rec, rep = c64_codec.write(char)
    assert rec.get("roster_in_use") == 0x83
    assert "computed from the status" in rep.sources[0x100]


# --- the run at 0x083 stays a constant ---------------------------------------

def test_the_five_bytes_at_0x083_still_reach_nothing_in_the_c64_record():
    """The other half of #235, kept from drifting: `field_83_87` is
    `00 00 01 00 00` in 101 of 101 engine-written Pool of Radiance records
    and the character sheet is pixel-identical whatever it holds, so it is a
    documented constant and **not** converted.

    Two records differing only in those five bytes have to convert to the
    same C64 record.  The pair below it is the control: two differing only in
    the status byte have to convert to different ones, which is what says
    this test is comparing something that can move.
    """
    one, _ = c64_codec.write(dos.to_neutral(
        _dos_record(constant=b"\x00\x00\x01\x00\x00")))
    two, _ = c64_codec.write(dos.to_neutral(
        _dos_record(constant=b"\x11\x22\x33\x44\x55")))
    assert one.to_bytes() == two.to_bytes()

    well, _ = c64_codec.write(dos.to_neutral(_dos_record(b"\x00\x01\x00\x00")))
    hurt, _ = c64_codec.write(dos.to_neutral(_dos_record(b"\x04\x00\x00\x00")))
    assert well.to_bytes() != hurt.to_bytes()


# --- what a player reads ------------------------------------------------------

def test_no_c64_status_drop_line_carries_developer_detail():
    """The same guard `tests/test_dosconvert.py` puts on the DOS table, for
    the lines this conversion composes: no file offset and no bare issue
    number in front of a player (`.claude/rules/gui-text.md`).  #244 (Every
    DROPPED entry's composed line carries a raw hex file offset in front of
    the player, not only the two #235 fixed) is the one that found the class
    of defect."""
    hex_offset = re.compile(r"0[xX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+")
    bare_issue = re.compile(r"#\d+")
    for name, why in c64_codec.NO_C64_STATUS.items():
        assert not hex_offset.search(why), (name, why)
        assert not bare_issue.search(why), (name, why)
        assert why[:1].isupper(), (name, why)

    for number in (1, 2):
        _, rep = c64_codec.write(
            dos.to_neutral(_dos_record(bytes([number, 1, 0, 0]))))
        for line in rep.dropped:
            assert not bare_issue.search(line), line


# --- the byte the engine itself wrote ----------------------------------------

def _unconscious_specimen():
    """The one C64 save anybody here has where record 0x100 is not 0 or 1.

    `$WISH_SPECIMENS`' `porunconscious1`: the party walked into the Slums
    ambush with one character's hit points set to 1 through the monitor and
    nothing else, so the engine's own damage code wrote the byte -- roster
    slot 5 went `$01` to `$84` when an orc reached his last hit point and
    `$84` to `$85` as the fight ended -- and then `ENCAMP > SAVE`.  Sweeping
    every `.d64` on this machine found 0 in 70 roster slots and 1 in 234 and
    nothing else, which is why this had to be made rather than found.

    `tools/statusdrive.py --save PORSAVE13.D64 --victim 5` regenerates it.
    """
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from tools import specimens

    for entry in specimens.list_specimens():
        if entry.get("name") == "porunconscious1":
            for path in entry["_files"]:
                if path.name.lower().endswith(".d64"):
                    return path
    return None


def test_the_byte_the_engine_wrote_reads_as_unconscious_and_out_of_play():
    """Bytes matching a table is necessary and not sufficient; this is the
    one place the table meets a byte the game itself put on a disk."""
    from goldbox import savegame
    from goldbox.d64 import D64, split_load_address

    path = _unconscious_specimen()
    if path is None:
        pytest.skip("no porunconscious1 specimen; "
                    "tools/statusdrive.py --victim 5 makes one")
    _, body = split_load_address(D64.open(str(path)).read_file("SAVEDGAME1"))
    roster = [body[i * savegame.ROSTER_STRIDE] for i in range(8)]
    assert roster == [1, 1, 1, 1, 1, 0x85, 0, 0], roster

    out = c64_codec.read(_c64_record(roster[5]))
    assert out.get("status") == "unconscious"
    assert out.get("active") is False
    # And the DOS numbers a conversion of him would write.
    rec, _, _, _ = dos.write(out)
    assert bytes(rec[TAIL.offset:TAIL.offset + 2]) == b"\x04\x00"


# --- the vocabulary and the tables agree -------------------------------------

def test_the_c64_table_names_only_states_the_vocabulary_declares():
    """A codec that spelled a state the neutral record does not have would be
    a value no other port could ever read."""
    assert set(c64_codec.STATUS_BITS) <= set(neutral.STATUS_NAMES)
    assert set(c64_codec.NO_C64_STATUS) <= set(neutral.STATUS_NAMES)
    # Nine states, seven with a C64 value and two without: every name is
    # accounted for one way or the other.
    assert (set(c64_codec.STATUS_BITS) | set(c64_codec.NO_C64_STATUS)) \
        == set(neutral.STATUS_NAMES)
    assert set(c64_codec.STATUS_BITS.values()) == set(range(1, 8))


def test_the_dos_reader_grades_the_two_bytes_above_the_field_they_sit_in():
    """The status and the active flag are each CONFIRMED on their own
    evidence, independent of whatever `field_10c_10f`'s own grade is (now
    CONFIRMED too, since all four bytes are understood -- #235,
    docs/169-dos-combat-side.md)."""
    out = dos.to_neutral(_dos_record(b"\x04\x00\x00\x00"))
    assert out.value("status").confidence is Confidence.CONFIRMED
    assert out.value("active").confidence is Confidence.CONFIRMED

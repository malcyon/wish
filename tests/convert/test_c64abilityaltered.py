"""The ability-altered flag, which the two ports keep in different bytes.

#620 (A C64 party that used the trainer cannot be saved as a DOS save,
because the DOS writer zeroes the byte recording it).  The C64 sets bit 0 of
record `0x0B8` when a score is altered in the character-modification screen
(`GEN $155D`); DOS writes `1` into record `0x085` as the last statement of
MODIFY CHARACTER, reached only by the key `0x4B`, `K` for KEEP
(`GAME.OVR 0x01C263`).  `0x085` is also DOS's treasure share, and both
engines read the share only for a character they drive:

    006891  cmp byte ptr es:[di + 0x84], 0x7f   ; jbe -- the else branch
    0068A7  mov al, byte ptr es:[di + 0x85] / and al, 7

with the same guard in front of the zero test at `0x0069B6` and in front of
`POST.COM $194F`, the C64's one and only reference to its own `0x0FA`.  So
for a player character the byte is the flag on both ports, and the
conversion crosses `0x0B8` bit 0 to the share byte and back.

The control byte itself cannot hold the flag: `GAME.OVR 0x0251B7` tests it
for **equality** with `0` before pooling a character's coin into the party
totals, so `0x01` there would leave a converted character out.

Most of these build records from zeroes.  The last reads the player's own
`PORSAVE*.D64` save disks through the registry and skips without them.
"""

from __future__ import annotations

import gamedata
import pytest

from goldbox import c64_codec, dos_codec, dos_port
from goldbox.record import CharacterRecord

F83 = dos_port.FIELDS_BY_NAME["field_83_87"]
CONTROL = F83.offset + 1
SHARE = F83.offset + 2


def _c64_record(flags: int, share: int = 0,
                name: bytes = b"BRUTUS") -> CharacterRecord:
    """A C64 record that is zero but for its name and the two bytes."""
    rec = CharacterRecord.blank()
    rec.set("name", name)
    rec.set("flags_0b8", flags)
    rec.set("treasure_share", share)
    return rec


def _dos_character(window: bytes) -> dos_codec.DosCharacter:
    """A Pool of Radiance DOS record that is zero but for `field_83_87`."""
    raw = bytearray(dos_port.RECORD_SIZE)
    raw[F83.offset:F83.end] = window
    return dos_codec.DosCharacter(bytes(raw))


def _to_dos(rec: CharacterRecord) -> bytes:
    out, _itm, _spc, _rep = dos_codec.write(
        c64_codec.read(rec, game="pool-of-radiance"))
    return bytes(out)


def _back_to_c64(raw: bytes) -> CharacterRecord:
    rec, _rep = c64_codec.write(
        dos_codec.to_neutral(dos_codec.DosCharacter(raw)))
    return rec


# --- C64 to DOS and back ----------------------------------------------------

def test_a_trainer_altered_player_reaches_dos_and_comes_back():
    """BRUTUS, who holds `0x01` at `0x0B8` on twelve of the player's fifteen
    Pool of Radiance save disks.  Without the fix the DOS writer put `0x00`
    in both bytes and the flag came back 0."""
    raw = _to_dos(_c64_record(0x01))

    assert raw[CONTROL] == 0x00
    assert raw[SHARE] == 0x01

    back = _back_to_c64(raw)
    assert back.get("flags_0b8") == 0x01
    assert back.get("treasure_share") == 0


def test_a_player_who_never_used_the_trainer_is_unchanged():
    """The other 78 of the 90 records on those disks: both bytes zero on the
    way out, both zero on the way back."""
    raw = _to_dos(_c64_record(0x00))

    assert raw[CONTROL] == 0x00 and raw[SHARE] == 0x00

    back = _back_to_c64(raw)
    assert back.get("flags_0b8") == 0x00
    assert back.get("treasure_share") == 0


def test_the_control_byte_is_exactly_zero_even_with_the_flag_set():
    """`GAME.OVR 0x0251B7` pools a character's coin into the party totals
    only when the control byte reads exactly `0` or `0xB3`, so a converted
    player character carrying `0x01` there would be left out of the pool."""
    assert _to_dos(_c64_record(0x01))[CONTROL] == 0x00


@pytest.mark.parametrize("control,share", [(0xB1, 0), (0x80, 3), (0xB2, 1)])
def test_a_companions_control_byte_and_share_still_cross(control, share):
    """The bytes a companion has -- DIRTEN's `0xB1` is morale 98 -- convert as
    they did before: the whole control byte, and the raw share beside it.
    Bit 0 of a companion's byte is the low bit of his morale and not a flag,
    so nothing about him goes through the crossing above."""
    raw = _to_dos(_c64_record(control, share))

    assert raw[CONTROL] == control
    assert raw[SHARE] == share

    back = _back_to_c64(raw)
    assert back.get("flags_0b8") == control
    assert back.get("treasure_share") == share


# --- DOS to the C64 and back ------------------------------------------------

def test_the_dos_flag_becomes_the_c64s_own_bit():
    """`00 00 01 00 00` is what 64 of the 177 Pool of Radiance DOS records on
    this machine hold.  The C64 keeps that fact at `0x0B8` bit 0, and its own
    `0x0FA` -- which no file of the title ever writes -- stays zero."""
    rec, _rep = c64_codec.write(
        dos_codec.to_neutral(_dos_character(b"\x00\x00\x01\x00\x00")))

    assert rec.get("flags_0b8") == 0x01
    assert rec.get("treasure_share") == 0

    assert _to_dos(rec)[SHARE] == 0x01


@pytest.mark.parametrize("window", [b"\x00\x00\x01\x00\x00",
                                    b"\x00\x00\x00\x00\x00",
                                    b"\x00\xB1\x03\x00\x00",
                                    b"\x00\x00\x03\x00\x00"])
def test_a_dos_window_returns_byte_for_byte_through_the_c64(window):
    """Every combination any record on this machine holds, and a player
    character with a raw share no engine writes, back where it started."""
    rec, _rep = c64_codec.write(dos_codec.to_neutral(_dos_character(window)))

    assert bytes(_to_dos(rec)[F83.offset:F83.end]) == window


# --- the player's own save disks --------------------------------------------

@gamedata.needs_disks
def test_every_record_on_the_player_s_save_disks_round_trips():
    """Each character of each `PORSAVE*.D64`, C64 to DOS to C64, on both
    bytes.  Skips where this machine's registry has no such disks, and says
    how many records carried the flag: a run where none did has measured the
    conversion of the flag not at all."""
    from editor.saveplan import c64_slot_records

    disks = gamedata.save_disks()
    if not disks:
        pytest.skip("needs the Pool of Radiance C64 save disks")
    records = flagged = 0
    wrong = []
    for disk in disks:
        try:
            party = c64_slot_records(disk)
        except Exception:
            continue          # a roster disk with no saved game on it
        for rec in party:
            records += 1
            flagged += rec.get("flags_0b8") & 0x01
            back = _back_to_c64(_to_dos(rec))
            if (back.get("flags_0b8"), back.get("treasure_share")) != (
                    rec.get("flags_0b8"), rec.get("treasure_share")):
                wrong.append((disk.name, rec.get("name"),
                              rec.get("flags_0b8"),
                              back.get("flags_0b8")))
    assert records, f"no records on {[d.name for d in disks]}"
    assert wrong == []
    if not flagged:
        pytest.skip(f"{records} records and none with the flag set")

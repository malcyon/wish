"""A companion's name keeps a real `$20` in the Amiga Pool of Radiance record.

The game gives Princess Fatima `$20` spaces when she joins and a script
compares them byte for byte; a player character's typed space is `$FF`.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from support.amigarecords import sample  # noqa: E402

from goldbox import amiga_por, c64_codec  # noqa: E402

#: The control byte, `0x085` in the Amiga record; bit 7 marks a companion.
CONTROL = 0x085


def _converted(name: bytes, control: int) -> bytes:
    record, _, _, _ = amiga_por.write_por(sample(name="QUINN"))
    dos = bytearray(amiga_por.to_dos_record(
        amiga_por.AmigaPorCharacter.from_bytes(record)))
    dos[0] = len(name)
    dos[1:1 + len(name)] = name
    dos[CONTROL - 1] = control
    return amiga_por.from_dos_record(bytes(dos))


def test_a_companions_space_is_written_as_20():
    out = _converted(b"PRINCESS FATIMA", 0xB2)
    assert out[:16] == b"PRINCESS FATIMA\0"
    assert out[8] == 0x20


def test_a_player_characters_space_stays_ff():
    out = _converted(b"LADY KATHERINE", 0x00)
    assert out[:16] == b"LADY\xffKATHERINE\0\0"


def test_a_character_the_game_took_over_keeps_ff():
    out = _converted(b"LADY KATHERINE", c64_codec.DOS_PC_TAKEN_OVER)
    assert out[:16] == b"LADY\xffKATHERINE\0\0"


def test_a_c64_companion_converts_to_the_amiga_with_20():
    char = sample(name="PRINCESS FATIMA", npc=True)
    char.set("npc_control_byte", 0xB2, "a built companion's control byte")
    record = amiga_por.write_por(char)[0]
    assert record[:16] == b"PRINCESS FATIMA\0"


def test_an_amiga_companions_20_converts_back_to_an_ordinary_space():
    record, _, _, _ = amiga_por.write_por(sample(name="QUINN"))
    amiga = bytearray(record)
    amiga[:16] = b"PRINCESS FATIMA\0"
    dos = amiga_por.to_dos_record(
        amiga_por.AmigaPorCharacter.from_bytes(bytes(amiga)))
    assert dos[0] == 15
    assert dos[1:16] == b"PRINCESS FATIMA"
    assert amiga_por.AmigaPorCharacter.from_bytes(bytes(amiga)).name == \
        "PRINCESS FATIMA"

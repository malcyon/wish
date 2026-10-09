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

from goldbox import amiga_por  # noqa: E402

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

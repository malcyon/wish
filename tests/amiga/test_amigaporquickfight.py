"""Amiga Pool of Radiance's quickfight flag sits at record `0x111`.

`goldbox.amiga_por.AMIGA_POR_QUICKFIGHT` names the byte the combat menu's
QUICK sets in `/program`.  These tests pin it against made-up records: it is
DOS `0x10F` under the shift map, and the reader and writer move it as that
byte and touch nothing beside it.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from support.amigarecords import sample  # noqa: E402

from goldbox import amiga_por, dos_port  # noqa: E402

#: The DOS record's quickfight byte, the fourth of `field_10c_10f`.
DOS_QUICKFIGHT = dos_port.FIELDS_BY_NAME["field_10c_10f"].offset + 3


def _record(**at: int) -> bytes:
    record, _, _, _ = amiga_por.write_por(sample(name="QUINN"))
    record = bytearray(record)
    for offset, value in at.items():
        record[int(offset, 16)] = value
    return bytes(record)


def test_the_constant_is_dos_0x10f_under_the_shift_map():
    assert DOS_QUICKFIGHT == 0x10F
    assert amiga_por.AMIGA_POR_QUICKFIGHT == 0x111
    assert amiga_por.amiga_por_offset(DOS_QUICKFIGHT) == \
        amiga_por.AMIGA_POR_QUICKFIGHT


def test_a_set_byte_reads_as_dos_quickfight_and_nothing_else():
    clear = amiga_por.to_dos_record(
        amiga_por.AmigaPorCharacter.from_bytes(_record()))
    quick = amiga_por.to_dos_record(
        amiga_por.AmigaPorCharacter.from_bytes(_record(**{"0x111": 1})))
    assert clear[DOS_QUICKFIGHT] == 0
    assert quick[DOS_QUICKFIGHT] == 1
    assert [i for i in range(len(quick)) if quick[i] != clear[i]] == \
        [DOS_QUICKFIGHT]


def test_the_side_byte_beside_it_does_not_read_as_quickfight():
    side = amiga_por.to_dos_record(
        amiga_por.AmigaPorCharacter.from_bytes(_record(**{"0x110": 1})))
    assert side[DOS_QUICKFIGHT] == 0
    assert side[DOS_QUICKFIGHT - 1] == 1


def test_the_writer_puts_dos_quickfight_at_the_constant():
    dos = bytearray(amiga_por.to_dos_record(
        amiga_por.AmigaPorCharacter.from_bytes(_record())))
    dos[DOS_QUICKFIGHT] = 1
    out = amiga_por.from_dos_record(bytes(dos))
    assert out[amiga_por.AMIGA_POR_QUICKFIGHT] == 1
    assert out[amiga_por.AMIGA_POR_QUICKFIGHT - 1] == 0

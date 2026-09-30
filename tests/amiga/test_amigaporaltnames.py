from __future__ import annotations

"""An Amiga Pool of Radiance name typed with Alt or Ctrl holds a byte outside
`0x20`-`0x7E`.  The reader keeps it as the Latin-1 character with that number,
and a writer that cannot hold it records a loss instead of writing `?` or
raising.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from support.amigarecords import sample  # noqa: E402

from goldbox import amiga_por, dos_codec  # noqa: E402


def _character(byte: int):
    record, _, _, _ = amiga_por.write_por(sample(name="XAY"))
    record = bytearray(record)
    record[1] = byte
    return amiga_por.AmigaPorCharacter.from_bytes(bytes(record))


def _name_losses(rep):
    return [line for line in rep.losses if line.startswith("Name ")]


def test_an_alt_byte_reads_back_as_its_latin1_character():
    assert amiga_por.to_dos_character(_character(0xE5)).name == "X\xe5Y"


def test_a_ctrl_byte_reads_back_unchanged():
    assert amiga_por.to_dos_character(_character(0x01)).name == "X\x01Y"


@pytest.mark.parametrize("byte", [0xE5, 0x01])
def test_a_dos_write_accounts_for_the_byte_and_writes_no_question_mark(byte):
    record, _, _, rep = dos_codec.write(amiga_por.to_neutral(_character(byte)))
    assert len(_name_losses(rep)) == 1
    table = dos_codec.FIELDS_BY_NAME_FOR["pool-of-radiance"]
    at = table["name_length"].offset
    assert 0x3F not in record[at + 1:at + 1 + record[at]]


@pytest.mark.parametrize("byte", [0xE5, 0x01])
def test_a_c64_write_accounts_for_the_byte_instead_of_raising(byte):
    ch = amiga_por.to_dos_character(_character(byte))
    _, rep = dos_codec.to_c64_record(ch)[:2]
    assert len(_name_losses(rep)) == 1


def test_a_tilde_is_no_loss_on_either_writer():
    ch = _character(0x7E)
    record, _, _, rep = dos_codec.write(amiga_por.to_neutral(ch))
    assert not _name_losses(rep)
    table = dos_codec.FIELDS_BY_NAME_FOR["pool-of-radiance"]
    at = table["name_length"].offset
    assert record[at + 2] == 0x7E
    _, c64 = dos_codec.to_c64_record(amiga_por.to_dos_character(ch))[:2]
    assert not _name_losses(c64)

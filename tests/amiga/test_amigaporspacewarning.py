from __future__ import annotations

"""A space in a name is written to the Amiga Pool of Radiance record as `$FF`,
which the game draws as a blank and keeps through every save, so `write_por`
reports no warning about it and the name reads back with its space.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from support.amigarecords import sample  # noqa: E402

from goldbox import amiga_por, dos_codec  # noqa: E402


def test_a_space_is_written_as_ff_and_reads_back_as_a_space():
    """A DOS or C64 name with a space goes to the Amiga as `$FF`, the byte the
    game itself writes for a typed space and keeps through every save, so the
    space survives and no warning about it is reported."""
    record, _, _, rep = amiga_por.write_por(sample(name="LADY KATHERINE"))
    assert record[:16] == b"LADY\xffKATHERINE\0\0"
    assert amiga_por.AmigaPorCharacter.from_bytes(record).name == \
        "LADY KATHERINE"
    assert not any("dropped on the Amiga" in w for w in rep.warnings)


def test_two_spaces_are_both_written_as_ff():
    record, _, _, rep = amiga_por.write_por(sample(name="MARY SUE FOX"))
    assert record[:13] == b"MARY\xffSUE\xffFOX\0"
    assert amiga_por.AmigaPorCharacter.from_bytes(record).name == \
        "MARY SUE FOX"
    assert not any("dropped on the Amiga" in w for w in rep.warnings)


def test_a_name_with_no_space_gets_no_warning():
    _, _, _, rep = amiga_por.write_por(sample(name="MAGNUS"))
    assert not any("dropped on the Amiga" in w for w in rep.warnings)


def test_a_typed_ff_space_reads_as_a_space_and_converts_to_dos_as_one():
    """`#631 (A Pool of Radiance character created in the Amiga game with a
    space in his name converts as MARY?SUE, because the reader decodes the
    game's $FF as a replacement character)`: Amiga Pool of Radiance's own
    Create New Character writes `$FF`, not `$20`, for a typed space
    (`docs/206-three-amiga-questions.md`), and draws that byte as a blank
    cell rather than as a replacement character.

    `goldbox.dos_codec.DosCharacter.name` maps `$FF` to a space before
    decoding, gated on `is_pool_of_radiance`. A record built with a genuine
    `$FF` in the name comes back as `MARY SUE` rather than `MARY�SUE`,
    and the DOS bytes it converts to hold the space (`0x20`), not the `?`
    (`0x3F`) a replacement character would encode to.
    """
    record, _, _, _ = amiga_por.write_por(sample(name="MARY SUE"))
    record = bytearray(record)
    record[4] = 0xFF
    ch = amiga_por.AmigaPorCharacter.from_bytes(bytes(record))

    assert amiga_por.to_dos_character(ch).name == "MARY SUE"

    dos_record, _, _, _ = dos_codec.write(amiga_por.to_neutral(ch))
    assert dos_record[:9] == bytes((0x08, 0x4D, 0x41, 0x52, 0x59, 0x20,
                                     0x53, 0x55, 0x45))

from __future__ import annotations

"""`goldbox.amiga_por.write_por` warns a player when their character's name will
lose its space on the Amiga's first save.

`#308 (Does Amiga Pool of Radiance drop the space out of a character's name
when it saves?)` measured the engine stripping every space out of every
name it saves, including one its own name-entry box had just accepted --
nothing on our side causes it and nothing on our side can prevent it, so the
record keeps the player's name whole and this is the sentence that tells him
what will happen to it.  Donald's ruling, verbatim: *"WARNING: Spaces in
names are dropped on the Amiga. GUY DE VALOIS will become GUYDEVALOIS."*

LADY KATHERINE is not a stand-in: she is the character
`tests/convert/test_toamigapor.py::test_a_space_in_a_name_is_written_through_to_the_amiga_record`
already proves keeps her space going in, from the real C64 party
`WISH-SPEC-por-party-twin-pair` -- the same one `#308` read the engine's own
save of back as `LADYKATHERINE`.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from support.amigarecords import sample  # noqa: E402

from goldbox import amiga_por, dos_codec  # noqa: E402

WARNING = "WARNING: Spaces in names are dropped on the Amiga. "


def test_a_name_with_a_space_gets_donalds_warning():
    _, _, _, rep = amiga_por.write_por(sample(name="LADY KATHERINE"))
    assert WARNING + "LADY KATHERINE will become LADYKATHERINE." \
        in rep.warnings


def test_two_spaces_are_both_dropped():
    _, _, _, rep = amiga_por.write_por(sample(name="MARY SUE FOX"))
    assert WARNING + "MARY SUE FOX will become MARYSUEFOX." in rep.warnings


def test_a_name_with_no_space_gets_no_warning():
    """MAGNUS, one of the same party's characters, converted with his name
    unchanged in `#308`'s own run -- the control the ruling is about."""
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

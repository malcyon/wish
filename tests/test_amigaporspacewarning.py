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
`tests/test_toamigapor.py::test_a_space_in_a_name_is_written_through_to_the_amiga_record`
already proves keeps her space going in, from the real C64 party
`WISH-SPEC-por-party-twin-pair` -- the same one `#308` read the engine's own
save of back as `LADYKATHERINE`.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from test_amiga import sample  # noqa: E402

from goldbox import amiga_por  # noqa: E402

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

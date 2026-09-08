from __future__ import annotations

"""A crossed Amiga Curse or Silver Blades ability pair keeps its permanent
and in-force halves apart through `goldbox.amiga.to_neutral_later`, the same
crossed-pair bug `#404 (A converted Curse or Silver Blades character keeps a
temporary strength boost or drain for good, because the two halves of the
DOS ability pair are crossed)` fixed on the DOS side --
`#406 (An Amiga Curse or Silver Blades character converted from the Amiga
keeps a temporary strength boost or drain for good, the same crossed-pair
bug as #404)`.

**Established by reading `/Curse` and `/Secret` themselves**, not by
inference from the DOS engine: both recompute an ability the identical way
DOS's own routine does (`docs/204-the-dos-ability-pair.md`) -- seed from
byte 0 of the pair (and byte `0x1D` for the percentile), walk the item and
spell effects, and store the result to byte 1 (and `0x1C`).  `/Curse` file
offset `0xf5ee` seeds and `0xf9ce`-`0xf9ec` stores; `/Secret` file offset
`0x131f8`/`0x13202` seeds and `0x13608`-`0x13612` stores.  Byte 0 is written
by nothing else in either binary except character creation's own roll, the
same shape `#401 (Which byte of a DOS ability pair is the current score, now
that the C64's two arrays are named)` found in five DOS engines.

**No real specimen can show this**, the same as on DOS and the C64: every
ability pair across all 21 Amiga Curse and Silver Blades records this
project can reach holds its two bytes equal, which is why the crossing has
to be built rather than found -- `test_no_real_amiga_specimen_shows_the_crossing`
measures it rather than asserting it from memory.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from test_amiga import (  # noqa: E402
    _ability_record,
    curse_characters,
    silver_blades_characters,
)

from goldbox import amiga  # noqa: E402
from goldbox import dos as _dos

SHAPES = (amiga.CURSE_SHAPE, amiga.SILVER_BLADES_SHAPE)
SIX_SCORES = tuple(n for n in _dos.ABILITY_ORDER if n != "exceptional_strength")


def test_no_real_amiga_specimen_shows_the_crossing():
    """0 of 147 pairs across all 21 real Amiga Curse and Silver Blades
    records differ, so nothing on the disks or in `$WISH_SPECIMENS` can
    prove which byte the engine treats as current -- exactly the shape
    `#401` found on DOS (0 of 406) and the C64 (0 of 6).  This is why the
    tests below build the crossing rather than finding one.
    """
    total = diff = 0
    for char in curse_characters() + silver_blades_characters():
        for name in _dos.ABILITY_ORDER:
            pair = char.get(name)
            total += 1
            if pair[0] != pair[-1]:
                diff += 1
    assert total == 147, total
    assert diff == 0, diff


def test_a_crossed_six_ability_pair_lands_in_force_at_the_second_byte():
    """Strength through charisma: byte 0 is the permanent score behind the
    character and byte 1 is what is in force -- a girdle's boost or a
    shadow's drain.  Before the fix this test fails on every one of the six,
    landing byte 0 at the neutral ability and byte 1 at `abilities_second`.
    """
    seen = 0
    for shape in SHAPES:
        for name in SIX_SCORES:
            char = _ability_record(shape, name, 0x12, 0x09)
            out = amiga.to_neutral_later(char)
            assert out.get(name) == 0x09, (shape.key, name)
            assert out.get("abilities_second")[name] == 0x12, (shape.key, name)
            seen += 1
    assert seen == 12, seen


def test_a_crossed_exceptional_strength_lands_in_force_at_the_first_byte():
    """The percentile pair runs the other way: `0x1C` is in force and
    `0x1D` is the permanent copy -- unchanged by this fix, and asserted
    separately because a blanket swap would pass the six scores above and
    break this one.
    """
    for shape in SHAPES:
        char = _ability_record(shape, "exceptional_strength", 0x64, 0x00)
        out = amiga.to_neutral_later(char)
        assert out.get("exceptional_strength") == 0x64, shape.key
        assert out.get("abilities_second")["exceptional_strength"] == 0x00, \
            shape.key


def test_an_agreeing_pair_converts_exactly_as_before():
    """The control: every real specimen holds equal halves, and an equal
    pair converts to the same neutral value whichever byte is called
    current -- so this test cannot tell the fix from the bug, and it is here
    to prove the fix does not disturb the ordinary case.
    """
    for shape in SHAPES:
        for name in _dos.ABILITY_ORDER:
            char = _ability_record(shape, name, 0x0F, 0x0F)
            out = amiga.to_neutral_later(char)
            assert out.get(name) == 0x0F, (shape.key, name)
            assert out.get("abilities_second")[name] == 0x0F, (shape.key, name)

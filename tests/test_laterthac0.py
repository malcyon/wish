"""`tools/laterthac0.py` reads the later DOS titles' THAC0 tables.

`#318 (DOS gives a low-level magic-user or thief THAC0 20 where the C64 gives
21, and our table holds only the C64's)` was answered for Pool of Radiance and
left open for Curse and Silver Blades, because the tool that reads Pool of
Radiance's table cannot read theirs: it anchors on the eight class bits that
follow it, `02 20 08 40 80 01 04 10`, and the later titles carry a different
permutation, `02 10 08 40 40 01 04 20`.  So the census exits with "the
class-bit anchor occurs 0 times" and no table.

Everything here reads the player's own files and skips without them.  The
control is Pool of Radiance: the locator finds it by a completely different
route -- the one block of plausible THAC0 bytes whose length is
`class_levels` wide times the stride the engine multiplies by -- and has to
land on the byte `tools/thac0census.py` finds by the class-bit anchor.

The rows themselves are not asserted here.  What is asserted is what the
issue turns on: **where the two ports disagree**, per title, against
`goldbox/levels.py`, whose C64 rows are cold-read off the player's own `GEN`
by `tests/test_curselevels.py` and `tests/test_coldread.py`.
"""

from __future__ import annotations

import pytest

from tools import laterthac0, thac0census

CURSE = "curse-of-the-azure-bonds"
SSB = "secret-of-the-silver-blades"
POOL = "pool-of-radiance"

#: Where each title's DOS table and its C64 rules give a different THAC0.
#: `(class, level, DOS, C64)`, measured 2026-09-07.
DISAGREE = {
    POOL: [("magic-user", level, 20, 21) for level in range(1, 6)]
          + [("thief", level, 20, 21) for level in range(1, 5)],
    CURSE: [("fighter", 2, 20, 19), ("magic-user", 11, 17, 16),
            ("paladin", 2, 20, 19), ("ranger", 2, 20, 19)]
           + [("thief", level, 20, 21) for level in range(1, 5)],
    SSB: [("fighter", 2, 20, 19)]
         + [("magic-user", level, 17, 16) for level in range(11, 16)]
         + [("paladin", 2, 20, 19), ("ranger", 2, 20, 19)]
         + [("thief", level, 20, 21) for level in range(1, 5)],
}

#: How many records of each title reproduce from its own table, and how many
#: do not.  Every miss is a magic-user, and every one of them is a record the
#: rebuild loop has not run over since it was created, dual-classed or
#: imported -- see `docs/135-levelling.md`.
RECORDS = {POOL: (202, 0), CURSE: (77, 9), SSB: (72, 2)}


def _located(title: str):
    try:
        return laterthac0.locate(title)
    except (FileNotFoundError, SystemExit) as why:
        pytest.skip(f"no DOS {title} on this machine: {why}")


def test_the_locator_lands_where_the_class_bit_anchor_does():
    """Pool of Radiance is the control, because both routes reach it.

    `tools/thac0census.py` anchors on the class-bit run; this anchors on the
    block's length and the paragraph boundary.  Two routes, one address.
    """
    found = _located(POOL)
    image = thac0census.dos_image(POOL)
    anchor = image.find(thac0census.DOS_CLASS_BITS)

    assert anchor > 0
    assert found.base == anchor - found.rows * found.stride
    assert found.table()["fighter"][:5] == [20, 19, 18, 17, 16]


@pytest.mark.parametrize("title,rows,stride,segment",
                         [(POOL, 8, 11, 0xC7C), (CURSE, 8, 13, 0xABE),
                          (SSB, 7, 19, 0xDE2)])
def test_every_title_is_located_by_three_independent_checks(
        title, rows, stride, segment):
    """The shape comes from the engine and the record, not from a guess.

    `rows` is the width of `class_levels`, which is 7 for Silver Blades
    because it drops the monk; `stride` is the `mul` in the engine's own
    lookup; and the data segment is what makes the block's address a
    paragraph past `DS:0` -- three things that would have to agree by
    coincidence for a wrong block to pass.
    """
    found = _located(title)

    assert (found.rows, found.stride) == (rows, stride)
    assert found.data_segment == segment
    assert len(found.class_bits) == rows
    assert sorted(found.class_bits)[:4] == [1, 2, 4, 8]


@pytest.mark.parametrize("title", [POOL, CURSE, SSB])
def test_the_two_ports_disagree_where_they_are_known_to(title):
    """The finding itself, pinned so a table change has to argue with it."""
    _located(title)

    assert sorted(laterthac0.disagreements(title)) == sorted(DISAGREE[title])


@pytest.mark.parametrize("title", [POOL, CURSE, SSB])
def test_every_record_reproduces_except_the_ones_the_loop_never_ran_over(
        title):
    """Counts, because a sweep with no count proves nothing.

    **The claim is the miss count, not the corpus size.** The first number
    was pinned as a literal until 2026-09-08, when it went 202 -> 214
    overnight: a night of driven runs had added twelve Pool of Radiance
    records, and a test that fails because the project measured more of the
    game is a test that trains people to edit it without reading it. That is
    the same shape `#362 (The two THAC0/damage-bonus population tests in
    test_derive.py have outgrown their exception counts, and PORSAVEA/PORSAVEB
    carry the same anomaly #348 found)` took out of `test_derive.py`.

    So the corpus may only grow, and every record in it must still reproduce.
    A table that stopped reproducing raises the miss count; a record whose
    stored byte nobody has accounted for raises it too. Either turns this red,
    which is what it is for.
    """
    _located(title)
    agree, total, lines = laterthac0.sweep(title)
    if not total:
        pytest.skip(f"no DOS {title} records on this machine")
    want_agree, want_miss = RECORDS[title]

    assert total - agree == want_miss, "\n".join(lines)
    assert agree >= want_agree, (
        f"{agree} records reproduce, down from {want_agree} when this was "
        f"measured -- the corpus does not shrink, so something stopped being "
        f"read\n" + "\n".join(lines))


@pytest.mark.parametrize("title,constants",
                         [(POOL, [0, 0, 40]), (CURSE, [0, 0, 40, 40]),
                          (SSB, [0, 0, 40])])
def test_nothing_clamps_the_field_and_creation_writes_a_flat_40(
        title, constants):
    """The whole mechanism, in one census of `GAME.OVR`.

    Every constant any engine stores into `thac0_base` is here: the zero a
    rebuild loop starts from, and a single flat 40 at character creation --
    which Curse's compiler emitted twice.  Nothing anywhere compares the field
    against a constant, so a record holding 40 where the table says 39 is a
    value nothing has refreshed rather than a clamp.
    """
    try:
        sites = laterthac0.writers(title)
    except FileNotFoundError as why:
        pytest.skip(f"no DOS {title} on this machine: {why}")

    assert sorted(imm for _, _, imm in sites if imm is not None) == constants
    assert laterthac0.constant_compares(title) == []

"""`tools/c64/laterthac0.py` reads the later DOS titles' THAC0 tables.

`#318 (DOS gives a low-level magic-user or thief THAC0 20 where the C64 gives
21, and our table holds only the C64's)` was answered for Pool of Radiance and
left open for Curse and Silver Blades, because the tool that reads Pool of
Radiance's table cannot read theirs: it anchors on the eight class bits that
follow it, `02 20 08 40 80 01 04 10`, and the later titles carry a different
permutation, `02 10 08 40 40 01 04 20`.  So the sweep exits with "the
class-bit anchor occurs 0 times" and no table.

Everything here reads the player's own files and skips without them.  The
control is Pool of Radiance: the locator finds it by a completely different
route -- the one block of plausible THAC0 bytes whose length is
`class_levels` wide times the stride the engine multiplies by -- and has to
land on the byte `tools/records/thac0sweep.py` finds by the class-bit anchor.

The rows themselves are not asserted here.  What is asserted is what the
issue turns on: **where the two ports disagree**, per title, against
`goldbox/levels.py`, whose C64 rows are cold-read off the player's own `GEN`
by `tests/curse_of_the_azure_bonds/test_curselevels.py` and `tests/c64/test_coldread.py`.
"""

from __future__ import annotations

import pytest

from tools.c64 import laterthac0
from tools.records import thac0sweep

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

#: The fewest records of each title the sweep must read, and the fewest of
#: them that reproduce from the title's own table.  These are lower bounds
#: against an empty or shrunken read: the specimens grow, so an exact count
#: would fail on every new one.  A regained old class is part of the rule, so
#: a magic-user who hit with the paladin 5 row they left reproduces.  Every
#: miss left is one kind: a magic-user of level 1 to 5 storing THAC0 20 where
#: the table says 21, the flat 40 creation and the class change write
#: (`test_nothing_clamps_the_field_and_creation_writes_a_flat_40`, below) and
#: that the engine's load and resave wrote back over our 39 in a `C64ToDos`
#: resave of PHILIPPE.  Curse's are PHILIPPE, BRYTWYN, MATHEW and two unnamed
#: mages, in the archives and in the specimens driven on from one another;
#: Silver Blades' are PAINE, magic-user 1, in `ssb-234-dualclassed` and
#: `ssb-234-party-pair`.
RECORDS = {POOL: (202, 202), CURSE: (158, 138), SSB: (74, 72)}


def _located(title: str):
    try:
        return laterthac0.locate(title)
    except (FileNotFoundError, SystemExit) as why:
        pytest.skip(f"no DOS {title} on this machine: {why}")


def test_the_locator_lands_where_the_class_bit_anchor_does():
    """Pool of Radiance is the control, because both routes reach it.

    `tools/records/thac0sweep.py` anchors on the class-bit run; this anchors on the
    block's length and the paragraph boundary.  Two routes, one address.
    """
    found = _located(POOL)
    image = thac0sweep.dos_image(POOL)
    anchor = image.find(thac0sweep.DOS_CLASS_BITS)

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
def test_every_record_reproduces_except_the_magic_users_the_dos_engine_stores_20_for(
        title):
    """A miss is only a magic-user of level 1 to 5 storing 20 against 21.

    The rule is asserted and the counts are only lower bounds, so the
    specimens may grow.  Every other record must reproduce, so a fixed known
    miss alongside a new broken record fails.
    """
    _located(title)
    agree, total, lines = laterthac0.sweep(title)
    if not total:
        pytest.skip(f"no DOS {title} records on this machine")
    want_total, want_agree = RECORDS[title]

    assert total >= want_total and agree >= want_agree, (
        f"{agree} of {total} records reproduce, against at least "
        f"{want_agree} of {want_total} when this was measured -- the "
        f"specimens do not shrink, so something stopped being read\n"
        + "\n".join(lines))
    unknown = [(source, name, held, stored, want)
               for source, name, held, _, stored, want
               in laterthac0.outcomes(title)
               if stored != want
               and not (set(held) == {"magic-user"}
                        and 1 <= held["magic-user"] <= 5
                        and (stored, want) == (20, 21))]
    assert unknown == []


class _Table:
    def table(self):
        return {"magic-user": [21] * 5, "paladin": [20, 20, 19, 18, 17]}


@pytest.mark.parametrize("title,want",
                         [(CURSE, 17), (SSB, 21)])
def test_a_regained_class_is_folded_in_for_curse_only(
        monkeypatch, title, want):
    monkeypatch.setattr(laterthac0, "locate", lambda _: _Table())
    monkeypatch.setattr(laterthac0, "records", lambda _: iter(
        [("synthetic/A.SAV", "X", {"magic-user": 3}, {"paladin": 5}, 21)]))

    assert [w for *_, w in laterthac0.outcomes(title)] == [want]


@pytest.mark.parametrize("title,constants",
                         [(POOL, [0, 0, 40]), (CURSE, [0, 0, 40, 40]),
                          (SSB, [0, 0, 40])])
def test_nothing_clamps_the_field_and_creation_writes_a_flat_40(
        title, constants):
    """The whole mechanism, in one sweep of `GAME.OVR`.

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

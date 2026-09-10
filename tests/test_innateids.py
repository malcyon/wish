"""`tools/innateids.py`: where a DOS innate effect id comes from.

`#395 (A Curse cleric carries the ranger's innate effect and a human carries
the elf's, in the specimen both ids were graded from)` asked what effect ids
134 and 107 mean in Curse of the Azure Bonds, after a code review found a
cleric carrying 134 and a human carrying 107.  The answer is in the engine:
character creation switches on the record's race byte and on its class byte
and calls `add_affect` with a constant id, and that switch is what the `seed`
subcommand reads.

The walker is tested on a **synthetic** overlay built here, byte by byte, so
these tests say something on a machine with no game on it.  The two tests that
read a real `GAME.OVR` skip without the archives, and they are the ones that
carry the finding: Curse's ranger is 134 and its elf is 107, Silver Blades'
ranger is 105, and Pool of Radiance seeds no class effect at all.
"""

from __future__ import annotations

import struct

import pytest

# **The skip has to come before the import, not beside it.** `tools/innateids.py`
# imports `capstone` at module level, so `from tools import innateids` raises
# `ModuleNotFoundError` on a machine without it -- and every CI runner is one.
# A skip written after this line never runs: the module fails to import first
# and pytest reports an error rather than a skip. That is the mistake that
# turned `main` red on all four jobs this morning in `tests/test_amigaglobal.py`
# and again here.
pytest.importorskip("capstone")

from goldbox import dos  # noqa: E402
from goldbox import dos_layout as dl  # noqa: E402
from tools import innateids  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

#: The far call the synthetic overlay uses for `add_affect`.
CALL = (0x1234, 0x0056)

#: A far call to somewhere else, so `add_affect` has to choose.
DECOY = (0x4321, 0x0010)


def _lcall(target):
    seg, off = target
    return b"\x9a" + struct.pack("<HH", off, seg)


def _push(value):
    """`xor ax, ax / push ax` for zero, `mov al, imm / push ax` otherwise."""
    return b"\x31\xc0\x50" if value == 0 else bytes((0xB0, value, 0x50))


def _add_affect(eid, duration=0, data=0xFF, flag=0, target=CALL):
    return (b"\xff\x76\xfe\xff\x76\xfc"          # push the record pointer
            + _push(eid) + _push(duration) + _push(data) + _push(flag)
            + _lcall(target))


def _read_field(offset):
    """`mov al, byte ptr es:[di + offset]`."""
    return b"\x26\x8a\x45" + bytes((offset,))


def _branch(value, *ids, target=CALL):
    """`cmp al, value / jne +N` then an `add_affect` per id."""
    body = b"".join(_add_affect(i, target=target) for i in ids)
    return b"\x3c" + bytes((value,)) + b"\x75" + bytes((len(body),)) + body


def _switch(field, branches, target=CALL):
    return _read_field(field) + b"".join(
        _branch(value, *ids, target=target) for value, ids in branches)


def test_the_walker_reads_a_branchs_add_affect_arguments():
    """Two branches, one call each: the four constants come back in push
    order, under the value the branch compares against."""
    ovr = _switch(0x74, [(2, (107,)), (4, (124,))])
    found = innateids.seed_switches(ovr, CALL, 0x74)
    assert found == [(0, {2: [(107, 0, 0xFF, 0)],
                          4: [(124, 0, 0xFF, 0)]})]


def test_the_walker_keeps_every_call_in_a_branch_in_order():
    """A dwarf's three ids are three tuples under one branch value."""
    ovr = _switch(0x74, [(1, (97, 26, 47)), (2, (107,))])
    (_, table), = innateids.seed_switches(ovr, CALL, 0x74)
    assert [c[0] for c in table[1]] == [97, 26, 47]
    assert table[2] == [(107, 0, 0xFF, 0)]


def test_a_switch_on_another_record_byte_is_not_read_as_this_one():
    """The bug this was written after: asking for the class byte and being
    handed the race switch, because the reader never checked which byte the
    read it anchored on named."""
    ovr = _switch(0x74, [(2, (107,)), (4, (124,))])
    assert innateids.seed_switches(ovr, CALL, 0x74)
    with pytest.raises(ValueError, match="0x75"):
        innateids.seed_switches(ovr, CALL, 0x75)


def test_the_walk_stops_at_the_next_record_bytes_switch():
    """A race switch immediately followed by a class switch does not run on
    into it: 134 belongs to the class table and must not appear in the race
    one."""
    ovr = (_switch(0x74, [(2, (107,)), (4, (124,))])
           + _switch(0x75, [(3, (8,)), (4, (134,))]))
    (_, race), = innateids.seed_switches(ovr, CALL, 0x74)
    (_, klass), = innateids.seed_switches(ovr, CALL, 0x75)
    assert race == {2: [(107, 0, 0xFF, 0)], 4: [(124, 0, 0xFF, 0)]}
    assert klass == {3: [(8, 0, 0xFF, 0)], 4: [(134, 0, 0xFF, 0)]}


def test_add_affect_is_the_call_the_race_switch_makes():
    """Not "the call reached with constants most often", which picks the wrong
    routine in Pool of Radiance: the call **inside a race switch**.  Here the
    decoy has four constant sites against the real one's two."""
    ovr = (b"".join(_add_affect(i, target=DECOY) for i in (1, 2, 3, 4))
           + _switch(0x74, [(1, (97, 26)), (2, (107,))]))
    assert innateids.add_affect(ovr, 0x74) == CALL


def test_a_call_whose_arguments_are_computed_is_not_read_as_a_constant():
    """`add_affect` is also called with an id taken from a spell or an item.
    Those sites have to come back as *not* constant rather than as a guess,
    or the census of "where does 134 come from" would invent an answer."""
    computed = (b"\xff\x76\xfe\xff\x76\xfc"
                + b"\x8a\x46\xf0\x50"            # mov al, [bp - 0x10]; push ax
                + _push(0) + _push(0xFF) + _push(0)
                + _lcall(CALL))
    ovr = computed + _add_affect(134)
    sites = innateids.constant_sites(ovr, CALL)
    assert len(sites) == 1
    assert innateids.constant_sites(ovr, CALL, 134) == sites
    assert innateids.constant_sites(ovr, CALL, 107) == []


def test_the_id_of_a_site_is_the_first_of_the_four_pushed():
    ovr = _add_affect(105, duration=0, data=0xFF, flag=0)
    at, = innateids.constant_sites(ovr, CALL, 105)
    assert innateids._pushed_before(ovr, at) == [105, 0, 0xFF, 0]


# --- the finding itself, off the player's own archives -----------------------
def _game(stem):
    from tools import dosbox
    try:
        return dosbox.find_game(stem)
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {stem} archives ($FR_ARCHIVES)")


def _tables(stem, key):
    game = _game(stem)
    ovr = (game / "GAME.OVR").read_bytes()
    fields = dl.FIELDS_BY_NAME_FOR[key]
    target = innateids.add_affect(ovr, fields["race"].offset)
    race = innateids.seed_switches(ovr, target, fields["race"].offset)
    try:
        klass = innateids.seed_switches(ovr, target,
                                        fields["char_class"].offset)
    except ValueError:
        klass = []
    return ovr, target, race, klass


def test_curse_seeds_134_for_a_ranger_and_107_for_an_elf():
    """`#395`'s question, answered from the engine rather than from a save.

    Every copy of Curse's race switch gives race 2 the single id 107 and gives
    the human nothing at all; the class switch gives class 4 -- ranger -- the
    single id 134, and class 0 -- cleric -- nothing.  So neither of the two
    records `#395` names could have been seeded that way at creation.
    """
    ovr, target, race, klass = _tables("CURSE", "curse-of-the-azure-bonds")
    assert race, "no race switch found in Curse's GAME.OVR"
    for _, table in race:
        assert table[2] == [(107, 0, 0xFF, 0)]
        assert 7 not in table                     # human, seeded nothing
    (_, by_class), = klass
    assert by_class[4] == [(134, 0, 0xFF, 0)]     # ranger
    assert by_class[3] == [(8, 0, 0xFF, 0)]       # paladin
    assert by_class[10] == [(134, 0, 0xFF, 0)]    # cleric/ranger
    assert 0 not in by_class                      # cleric, seeded nothing
    assert 5 not in by_class                      # magic-user, likewise


def test_curse_pushes_134_and_107_at_no_other_constant_site():
    """The ids are not merely seeded by class and race -- **nothing else in
    the overlay adds them with a constant**, which is what makes a record
    carrying one without the class or race an anomaly rather than a second
    route nobody had found.

    The limit, stated because it is real: 23 of Curse's 51 `add_affect` sites
    take a computed id, so this is exhaustive over the constant sites only.
    """
    ovr, target, race, klass = _tables("CURSE", "curse-of-the-azure-bonds")
    class_at = klass[0][0]
    race_starts = [at for at, _ in race]
    for site in innateids.constant_sites(ovr, target, 134):
        assert class_at <= site < class_at + 0x400
    for site in innateids.constant_sites(ovr, target, 107):
        assert any(at <= site < at + 0x400 for at in race_starts)


def test_silver_blades_seeds_105_for_the_same_ranger_slot():
    """The split `#388` established from specimens, taken from the engine:
    the class byte's ranger branch hands 105 in Silver Blades where Curse
    hands 134, and both hand the paladin 8."""
    _, _, race, klass = _tables("SECRET", "secret-of-the-silver-blades")
    (_, by_class), = klass
    assert by_class[4] == [(105, 0, 0xFF, 0)]
    assert by_class[3] == [(8, 0, 0xFF, 0)]
    assert race, "no race switch found in Silver Blades' GAME.OVR"


def test_pool_of_radiance_seeds_no_class_effect_at_all():
    """Why `goldbox.dos.INNATE_EFFECTS`' default set needs no class ids, and
    why `#388` was a later-titles bug: Pool of Radiance's creation has a race
    switch and no class switch, and never pushes 8, 105 or 134."""
    ovr, target, race, klass = _tables("POOLRAD", "pool-of-radiance")
    assert race, "no race switch found in Pool of Radiance's GAME.OVR"
    assert klass == []
    for eid in (8, 105, 134):
        assert innateids.constant_sites(ovr, target, eid) == []
    (_, by_race), = race
    assert by_race[2] == [(107, 0, 0xFF, 0)]      # elf, the shared racial id


# --- #490: the race table has to be each title's own, not Pool of Radiance's
# or the C64's --------------------------------------------------------------
def test_curse_seeds_its_own_race_table_not_pool_of_radiances():
    """`goldbox.dos.RACE_COMBAT_EFFECTS_CURSE` against the engine's own
    switch (`GAME.OVR:0x1E244`), which never pushes 90 for anybody -- a
    converted Curse dwarf or halfling used to arrive with it anyway, because
    the writer read Pool of Radiance's table (#490)."""
    _, _, race, _ = _tables("CURSE", "curse-of-the-azure-bonds")
    assert race, "no race switch found in Curse's GAME.OVR"
    for _, by_race in race:                    # Curse keeps two copies (#395)
        for num, name in ((1, "dwarf"), (3, "gnome"), (5, "halfling")):
            ids = tuple(c[0] for c in by_race[num])
            assert ids == dos.RACE_COMBAT_EFFECTS_CURSE[name], name
            assert 90 not in ids, name


def test_silver_blades_seeds_its_own_race_table_not_the_c64s():
    """`goldbox.dos.RACE_COMBAT_EFFECTS_SILVER_BLADES` against the engine's
    own switch (`GAME.OVR:0x1DF47`).  The table used to be read off the C64's
    seed table, which seeds two trait slots per race where DOS calls
    `add_affect` a third time -- so a converted dwarf and gnome arrived with
    no saving-throw record at all, and a converted halfling carried 92, an id
    the DOS engine never writes (#490)."""
    _, _, race, _ = _tables("SECRET", "secret-of-the-silver-blades")
    (_, by_race), = race
    names = {1: "elf", 2: "half-elf", 3: "dwarf", 4: "gnome", 5: "halfling"}
    for num, name in names.items():
        ids = tuple(c[0] for c in by_race[num])
        assert ids == dos.RACE_COMBAT_EFFECTS_SILVER_BLADES[name], name
    assert 92 not in (c[0] for c in by_race[5])   # the C64's own halfling id

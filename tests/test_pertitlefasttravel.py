"""Fast travel in a title that is not Pool of Radiance.

`#15 (Fast Travel for more than one Gold Box title)`. `tests/test_newecl.py`
checks the *numbers* against the games' own overlays and needs the player's
disks; these check what the code does with them, and need nothing at all.

**What these cannot show.** That a fast travel driven this way lands a party in
Curse or Silver Blades. Curse's half is measured -- four driven warps on a
pooled emulator, `#19` -- but through `tools/cursewarp.py`'s own writes rather
than through `automap/actions.py`, and no Silver Blades party has been
fast-travelled at all. What is asserted here is that the right title's
addresses are written, in the handler's order, and that a title nobody has
read is refused rather than written to with somebody else's numbers.
"""

from __future__ import annotations

import pytest

from automap import actions, fasttravel
from automap.target import MemoryTarget
from goldbox import games

WORLD = 1                               # the mode flag: DUNGEON is resident

CURSE = games.CURSE_OF_THE_AZURE_BONDS
SILVER = games.SECRET_OF_THE_SILVER_BLADES
POOL = games.POOL_OF_RADIANCE


class Machine(MemoryTarget):
    """`MemoryTarget` with a program counter, the way `tests/test_debugmode.py`
    does it: `Target` is `read` and `write` and nothing else, so the CPU is
    reached through the optional hook a real backend offers."""

    def __init__(self, memory=None, pc: int = 0):
        super().__init__(memory)
        self._pc = pc
        self.jumps: list[int] = []

    def pc(self) -> int:
        return self._pc

    def set_pc(self, address: int) -> None:
        self._pc = address
        self.jumps.append(address)


def machine(game, *, area: int = 1, disk: int = 2, indoors: int = 1,
            pc: int | None = None) -> Machine:
    """A party of `game` standing in an area, idle in the key-wait loop."""
    row = fasttravel.addresses_for(game)
    return Machine({game.mode_flag: bytes([WORLD]),
                    row.slot: bytes([area]),
                    row.disk: bytes([disk]),
                    row.indoors: bytes([indoors]),
                    row.live_square: bytes([4, 4, 0])},
                   pc=row.key_wait[0] if pc is None else pc)


class Row:
    """One area of a table, as `FastTravel` reads one: an id, a disk and a
    square. Not `goldbox.areas.Area` -- a test of the write path should not
    wait on a title's own table, real or not."""

    def __init__(self, id: int, disk: int, arrival=None, outdoors=False):
        self.id, self.disk, self.arrival, self.outdoors = (id, disk, arrival,
                                                           outdoors)
        self.name = f"area ${id:02X}"


# --- the table ---------------------------------------------------------------

def test_three_titles_have_addresses_and_three_do_not():
    """Reading an overlay is what puts a title in the table, and only that.

    The Krynn pair and Gateway are absent rather than carrying a plausible
    row: an address nobody measured reads as somebody else's byte, and the
    failure is a `JMP` into another overlay rather than a message.
    """
    assert set(fasttravel.ADDRESSES) == {
        "pool-of-radiance", "curse-of-the-azure-bonds",
        "secret-of-the-silver-blades"}
    for game in games.GAMES:
        assert fasttravel.supported(game) == (game.key in fasttravel.ADDRESSES)


def test_a_row_can_be_looked_up_by_whatever_the_caller_is_holding():
    """A `Game`, a key, a title, or None -- because `goldbox/areas.py` spells a
    title one way and `goldbox/games.py` another, and the seam between them is
    where a lookup silently answers nothing."""
    row = fasttravel.CURSE_OF_THE_AZURE_BONDS
    assert fasttravel.addresses_for(CURSE) is row
    assert fasttravel.addresses_for("curse-of-the-azure-bonds") is row
    assert fasttravel.addresses_for("Curse of the Azure Bonds") is row
    assert fasttravel.addresses_for() is fasttravel.POOL_OF_RADIANCE
    assert fasttravel.addresses_for("Pools of Darkness") is None


def test_the_pool_of_radiance_constants_still_name_pool_of_radiance():
    """The module constants are one row of the table now, and four tools and
    two test files import them expecting Pool of Radiance's numbers."""
    assert actions.NEWECL_TAIL == 0x2034
    assert actions.KEY_WAIT == (0x10C2, 0x10EC)
    assert actions.KEY_FETCH == (0x2E4E, 0x2E6B)
    assert actions.FASTTRAVEL_SLOT == 0x6E1B
    assert actions.FASTTRAVEL_DISK == 0x6E12
    assert actions.FASTTRAVEL_FROM == 0x49F2
    assert actions.FASTTRAVEL_SCRATCH == 0x4A00
    assert actions.FASTTRAVEL_INDOORS == 0x49E6
    assert actions.WALL_SLOT_PINNED == 0x49E7
    assert actions.FASTTRAVEL_WALLS_SLOT == 0x6E1C
    assert actions.FASTTRAVEL_TRAVEL_X == 0x49C3
    assert (actions.FASTTRAVEL_X, actions.FASTTRAVEL_Y,
            actions.FASTTRAVEL_FACING) == (0xC04B, 0xC04C, 0xC04D)


# --- the writes --------------------------------------------------------------

def test_a_curse_trip_writes_curses_addresses_and_none_of_pool_of_radiances():
    """The whole point of the ticket, as a list of addresses.

    A trip made with Pool of Radiance's numbers in a Curse machine writes
    `$6E1B` -- which is nothing there -- and leaves the cache slot the loader
    actually reads, `$7F1B`, untouched, so the party stays put and five
    unrelated bytes have been changed.
    """
    got = dict(actions.newecl_writes(
        1, 3, disk=2, arrival=(10, 1, 0),
        addresses=fasttravel.CURSE_OF_THE_AZURE_BONDS))
    assert got == {0x4BE7: bytes(3),          # wall slots unpinned
                   0x7F12: b"\x02",           # the side the area is on
                   0xC04B: bytes([10, 1, 0]),  # the arrival square
                   0x4BF2: b"\x01",           # came from area 1
                   0x7F1B: b"\x83",           # area 3, flagged for reload
                   0x4C00: bytes(0x20)}       # the scratch wipe
    for pool_only in (0x6E1B, 0x6E12, 0x49F2, 0x4A00, 0x6E1C, 0x49E7):
        assert pool_only not in got


def test_silver_blades_makes_the_sixth_write_and_the_others_do_not():
    """`$4BFB` is zeroed by Silver Blades' handler and by no other title's.

    It is the flag that suppresses the party's coordinates on the status line
    (`docs/138-multiple-games.md` §8). Eleven of the twenty-two areas set it
    again in their own arrival script and four never touch it, so a trip that
    skipped this write would drop a party into one of those four with its
    coordinates hidden and nothing to say why.
    """
    silver = dict(actions.newecl_writes(0x10, 0x11, disk=2,
                                        addresses=fasttravel.
                                        SECRET_OF_THE_SILVER_BLADES))
    assert silver[0x4BFB] == b"\x00"
    for other in (fasttravel.POOL_OF_RADIANCE,
                  fasttravel.CURSE_OF_THE_AZURE_BONDS):
        assert 0x4BFB not in dict(actions.newecl_writes(1, 2, addresses=other))


def test_the_sixth_write_goes_in_front_of_the_wipe_like_the_handler():
    """`LDX #$1F / LDA #$00 / STA $4BFB / STA $4C00,X / DEX / BPL`.

    The order is the handler's own. Nothing has been shown to depend on it and
    that is the reason to keep it: a sequence copied from a routine is
    checkable against the routine, and a sequence rearranged for tidiness is
    not.
    """
    addrs = [a for a, _ in actions.newecl_writes(
        0x10, 0x11, addresses=fasttravel.SECRET_OF_THE_SILVER_BLADES)]
    assert addrs.index(0x4BFB) == addrs.index(0x4C00) - 1


def test_no_walls_slot_is_written_in_a_title_that_has_no_walls_file():
    """`#156`'s write is Pool of Radiance's `WALLS00` and nothing else's.

    A directory read of all nine Pool of Radiance sides, all six Curse sides
    and all six Silver Blades sides finds `WALLS00` on Pool of Radiance's
    alone. Writing `$FF` into the later titles' `$7F1C` would be setting a
    cache slot for a file they do not have, on the strength of a bug measured
    in another game.
    """
    pool = dict(actions.newecl_writes(20, 18, addresses=None))
    assert pool[actions.FASTTRAVEL_WALLS_SLOT] == b"\xff"
    for game in (CURSE, SILVER):
        row = fasttravel.addresses_for(game)
        assert row.walls_slot is None
        writes = dict(actions.newecl_writes(1, 2, addresses=row))
        assert 0x7F1C not in writes


def test_the_wall_slots_are_unpinned_in_every_title():
    """`#179`'s write does transfer, because the array does.

    Each title's `DUNGEON` reads `<flag+1>,X` exactly once, in front of the
    same wall-unpack setup -- `$49E7` in Pool of Radiance, `$4BE7` in the
    other two. `tests/test_newecl.py` re-derives it off the disks; this is the
    write that follows from it.
    """
    for game, at in ((POOL, 0x49E7), (CURSE, 0x4BE7), (SILVER, 0x4BE7)):
        row = fasttravel.addresses_for(game)
        assert row.wall_slot_pinned == at
        assert dict(actions.newecl_writes(1, 2, addresses=row))[at] == bytes(3)


def test_an_overland_square_cannot_be_asked_for_where_there_is_no_grid():
    """Pool of Radiance is the only title with a square-engine overland.

    `$49C3` is inside the save image, so the arithmetic that moves the other
    save-relative addresses would hand back `$4BC3` for Curse and it would
    look entirely plausible. There is nothing there to write to, and a
    ValueError is better than two bytes into whatever is.
    """
    with pytest.raises(ValueError, match="no travel grid"):
        actions.newecl_writes(1, 2, overland=(7, 29),
                              addresses=fasttravel.CURSE_OF_THE_AZURE_BONDS)


# --- the action --------------------------------------------------------------

def test_a_curse_party_is_travelled_with_curses_tail():
    """End to end against a fake machine: the writes land and the PC moves.

    `$21DD`, which is Curse's `NEWECL` tail. `$2034` there is some other
    routine of Curse's `DUNGEON` entirely.
    """
    target = machine(CURSE, area=1, disk=2)
    ft = actions.FastTravel(CURSE)
    outcome = ft.apply(target, area=Row(3, disk=2, arrival=(10, 1, 0)))
    assert outcome.ok, outcome.message
    assert target.jumps == [0x21DD]
    assert target.memory[0x7F1B] == b"\x83"
    assert target.memory[0x4BF2] == b"\x01"
    assert target.memory[0xC04B] == bytes([10, 1, 0])


def test_a_silver_blades_party_is_travelled_with_silver_blades_tail():
    target = machine(SILVER, area=0x10, disk=3)
    ft = actions.FastTravel(SILVER)
    outcome = ft.apply(target, area=Row(0x11, disk=3, arrival=(1, 1, 0)))
    assert outcome.ok, outcome.message
    assert target.jumps == [0x210C]
    assert target.memory[0x7F1B] == bytes([0x11 | 0x80])
    assert target.memory[0x4BFB] == b"\x00"


def test_pool_of_radiance_is_unchanged_by_any_of_this():
    """The one title a player can use today, jumping where it always did."""
    target = machine(POOL, area=1, disk=3)
    ft = actions.FastTravel()
    outcome = ft.apply(target, area=Row(20, disk=4, arrival=(1, 14, 1)))
    assert outcome.ok, outcome.message
    assert target.jumps == [actions.NEWECL_TAIL]
    assert target.memory[actions.FASTTRAVEL_SLOT] == bytes([20 | 0x80])
    assert target.memory[actions.FASTTRAVEL_WALLS_SLOT] == b"\xff"


def test_the_key_wait_window_is_the_running_titles_own():
    """Pool of Radiance's `$10C2` is inside Curse's `DUNGEON` too, and is not
    its key-wait loop -- so a PC there has to be refused in a Curse session
    even though the same number is accepted in a Pool of Radiance one."""
    target = machine(CURSE, pc=0x10C2)
    verdict = actions.FastTravel(CURSE).legality(target, Row(3, disk=2))
    assert not verdict
    assert "$101D" in verdict.reason and "$10C2" in verdict.reason
    assert actions.FastTravel(CURSE).legality(
        machine(CURSE, pc=0x101D), Row(3, disk=2)).ok


def test_a_title_nobody_has_read_is_refused_rather_than_written_to():
    """Champions of Krynn has a mode flag nobody has found and a `NEWECL`
    nobody has located, so there is no tail to jump to. The refusal is the
    sentence every other action already gives for an unmeasured address."""
    krynn = games.CHAMPIONS_OF_KRYNN
    assert fasttravel.addresses_for(krynn) is None
    ft = actions.FastTravel(krynn)
    target = Machine({}, pc=0x10C2)
    assert not ft.legality(target, Row(1, disk=1))
    outcome = ft.run(target, area=Row(1, disk=1))
    assert not outcome.ok
    assert outcome.writes == ()
    assert target.jumps == []
    assert krynn.title in outcome.message


def test_the_dropdown_is_offered_nothing_for_a_title_with_no_addresses():
    """Two gates, and a row has to pass both.

    `goldbox.areas.areas_for_title` says whether the table has been written
    down and this says whether the writes have been read. A table with no
    addresses behind it would put the right area id at the wrong byte, which
    is `#14`'s corruption with the two halves swapped.
    """
    assert actions.area_rows("Champions of Krynn") == ()
    assert actions.area_rows(games.POOL_OF_RADIANCE.title)


def test_the_way_back_is_looked_up_in_the_title_being_travelled_in():
    """An id means a different place in each game, so `FastTravel Back` has to
    resolve it in the title being travelled in rather than in Pool of
    Radiance's table, which is what it did whatever was running.

    **Both Curse and Silver Blades answer with a row now** -- neither did when
    this test was written, because `goldbox.areas.areas_for_title` refused
    each title until its table was built
    (`#20 (Build an area table for Silver Blades)`,
    `#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one, which
    the importer refuses today)` step 0b). `21` decimal is `$15`, a different
    place in each of the three titles: Sokol Keep in Pool of Radiance, a
    side-2 area on `GEO21` in Silver Blades, and Curse's own `$15` on `GEO15`.
    """
    assert actions.FastTravel()._row(21) is not None
    curse = actions.FastTravel(CURSE)._row(21)
    assert curse is not None and curse.geos == ("GEO15",)
    silver = actions.FastTravel(SILVER)._row(0x21)
    assert silver is not None and silver.geos == ("GEO21",)
    assert actions.FastTravel()._row(21).name == "Sokol Keep"
    assert actions.FastTravel(SILVER)._row(0x0C) is None
    assert actions.FastTravel(CURSE)._row(0x0C) is None

"""The three shipped area tables, re-derived off the player's own disks.

`goldbox/areas.py` carries three tables -- thirty Pool of Radiance rows,
twenty-five Curse rows and twenty-two Silver Blades rows -- and every one of
them was produced by `tools/areatable.py` walking the game's own `ECL` scripts
and then **copied into a source file**. A copied table is a claim nothing
checks: it survives a wrong stride, a re-cracked release and a paste error, and
the first symptom is a fast travel writing an area's id with another area's
disk side and the loader asking for a side the player does not own.

So these re-derive each table and diff it, field by field, against what the
package ships. Nothing is compared against a number typed into this file except
the handful of documented differences, each of which is named and explained.

`#15 (Fast Travel for more than one Gold Box title)` is the ticket. Game data
comes off the player's disks at run time (`tests/gamedata.py`'s rule) and every
test here skips when the title's disks are not on the machine.
"""

from __future__ import annotations

import pytest

from goldbox import areas, c64_port
from tools import areatable, gamedisks

TITLES = {
    c64_port.POOL_OF_RADIANCE: areas.POOL_OF_RADIANCE,
    c64_port.CURSE_OF_THE_AZURE_BONDS: areas.CURSE_OF_THE_AZURE_BONDS,
    c64_port.SECRET_OF_THE_SILVER_BLADES: areas.SECRET_OF_THE_SILVER_BLADES,
}


def _derive(game):
    """`{id: Row}` off the disks, or a skip when the disks are not here."""
    root = gamedisks.find(game.key)
    if root is None:
        pytest.skip(f"no {game.title} disks on this machine")
    _machine, _base, _scripts, rows = areatable.derive(str(root), game)
    return {row.id: row for row in rows}


@pytest.fixture(scope="module")
def pool():
    return _derive(c64_port.POOL_OF_RADIANCE)


@pytest.fixture(scope="module")
def curse():
    return _derive(c64_port.CURSE_OF_THE_AZURE_BONDS)


@pytest.fixture(scope="module")
def silver():
    return _derive(c64_port.SECRET_OF_THE_SILVER_BLADES)


def _table(game):
    return {a.id: a for a in areas.areas_for(TITLES[game])}


def _square(area):
    return None if area.arrival is None else (
        area.arrival.x, area.arrival.y, area.arrival.facing)


# -- the two later titles, which are pure derivations ------------------------

def test_curses_twenty_five_rows_are_what_the_disks_say(curse):
    """Every id, side and map in `AREAS_CURSE`, off the six sides.

    This is the whole of that table: it carries no name and no arrival square,
    so id, side and maps is everything a diff can compare, and 25 of 25 agree.
    """
    table = _table(c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert set(curse) == set(table)
    assert len(table) == 25
    assert {id: (r.side, r.maps, r.sqrdata) for id, r in curse.items()} == \
        {id: (a.disk, tuple(a.geos), a.sqrdata) for id, a in table.items()}


def test_silver_blades_twenty_two_rows_are_what_the_disks_say(silver):
    """Id, side, maps **and** arrival square, 22 of 22.

    Silver Blades' table is the one that carries derived arrival squares, and
    twelve of the rows have one. All twelve come back the same, which is what
    makes this the stronger of the two later-title checks.
    """
    table = _table(c64_port.SECRET_OF_THE_SILVER_BLADES)
    assert set(silver) == set(table)
    assert len(table) == 22
    assert {id: (r.side, r.maps, r.square) for id, r in silver.items()} == \
        {id: (a.disk, tuple(a.geos), _square(a)) for id, a in table.items()}
    assert sum(1 for a in table.values() if a.arrival is not None) == 12


# -- Pool of Radiance, the control -------------------------------------------

def test_pool_of_radiance_sides_and_square_data_all_agree(pool):
    """Thirty rows, and the three `SQRDATA` names, against a curated table.

    Pool of Radiance's table is the one built by hand over many sessions and
    corroborated in the running game, so it is what says whether the
    derivation is any good rather than the other way round.
    """
    table = _table(c64_port.POOL_OF_RADIANCE)
    assert set(pool) == set(table)
    assert {id: r.side for id, r in pool.items()} == \
        {id: a.disk for id, a in table.items()}
    assert {id: r.sqrdata for id, r in pool.items()} == \
        {id: a.sqrdata for id, a in table.items()}


def test_the_maps_agree_apart_from_three_rows_that_are_understood(pool):
    """27 of 30 agree, and each of the three that do not is named.

    * `$03` and `$05` are `dynamic_geo` rows: they issue no static
      `LOADFILES` at all and the table's entry is the documentation's
      inference from the id, which `goldbox/areas.py` says is wrong for both.
      The derivation finding nothing is the derivation being right.
    * `$07` loads a second map, `LOADFILES 3, 2, 255` at `ECL07+$01C2`, and
      the table carries only `GEO07`. `ECL07` is the only script on any Pool
      of Radiance side that loads `GEO03`.

    Written as an exact set so that a *fourth* difference fails the test.
    """
    table = _table(c64_port.POOL_OF_RADIANCE)
    differ = {id: (pool[id].maps, tuple(a.geos))
              for id, a in table.items() if pool[id].maps != tuple(a.geos)}
    assert differ == {
        0x03: ((), ("GEO03",)),
        0x05: ((), ("GEO05",)),
        0x07: (("GEO07", "GEO03"), ("GEO07",)),
    }


def test_an_outdoor_load_is_not_a_map(pool):
    """The three wilderness windows load a `SQRDATA`, not a `GEO`.

    `LOADFILES` dispatches on the indoors flag `$49E6`, so its first operand
    names a `SQRDATA` when that flag is zero. `ECL19`, `ECL1A` and `ECL1B`
    each carry one map load with the flag set and one outdoor load with it
    clear, and reading the outdoor one as a map is what had `ECL19` claiming
    `GEO04` -- a Valjevo Castle floor on side 5, which a wilderness script on
    side 6 could not load without a disk swap.

    The three numbers land on `SQRDATA04`, `SQRDATA05` and `SQRDATA06`, which
    is what `goldbox/areas.py` already carries for these three areas from a
    different measurement entirely.
    """
    for id, geo, sqrdata in ((0x19, "GEO19", "SQRDATA04"),
                             (0x1A, "GEO1A", "SQRDATA05"),
                             (0x1B, "GEO1B", "SQRDATA06")):
        assert pool[id].maps == (geo,), f"${id:02X}"
        assert pool[id].sqrdata == sqrdata, f"${id:02X}"


def test_a_derived_arrival_square_is_right_ten_times_in_eleven(pool):
    """The calibration that grades every derived square in every title.

    Pool of Radiance's arrival squares were recorded from driven arrivals, so
    they are the ground truth a static walk can be scored against. Eleven rows
    have both a recorded square and a derived one and ten match.

    The eleventh is `$16`, where the two are reading different things rather
    than one being a misdecode: `ECL16`'s entry 4 places a party at (15, 0, 2)
    behind two `COMPARE [$49F2], n / IF= / EXIT` guards, so that is where a
    party arriving from anywhere but areas 22 and 23 is put, and the table's
    (15, 7, 1) is where one driven arrival ended up.

    That one miss is why a derived square is PROBABLE and never better, and it
    is asserted here rather than left as a sentence in a comment.
    """
    table = _table(c64_port.POOL_OF_RADIANCE)
    both = {id: (pool[id].square, _square(a)) for id, a in table.items()
            if a.arrival is not None and pool[id].square is not None}
    assert len(both) == 11
    wrong = {id: v for id, v in both.items() if v[0] != v[1]}
    assert wrong == {0x16: ((15, 0, 2), (15, 7, 1))}


def test_the_walk_abstains_rather_than_guessing(pool):
    """Five measured squares the derivation declines to name.

    `$00`, `$0A`, `$0E` and `$17` have two or three departing scripts naming
    different squares and `$0D` has none, so the walk answers None. An area a
    table declines to place a party in is better than one it places a party in
    wrongly, and this pins that the abstention is deliberate.
    """
    table = _table(c64_port.POOL_OF_RADIANCE)
    abstained = {id for id, a in table.items()
                 if a.arrival is not None and pool[id].square is None}
    assert abstained == {0x00, 0x0A, 0x0D, 0x0E, 0x17}

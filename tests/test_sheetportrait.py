"""Only Pool of Radiance's C64 character sheet draws a portrait (#300).

Two kinds of test, and the second is the one that could go wrong quietly.

`goldbox.portraits.draws_sheet_portrait` is a fact about three engines, and
the fact was read out of them: Pool of Radiance's `LIBRARY $48A4` asks the
loader for the `HEAD<xx>` and `BODY<xx>` files the character record names,
and neither later title's `LIBRARY` calls the loader at all.  So the second
group re-derives that off the player's own disks rather than trusting the
frozenset -- if somebody points `gamedisks.toml` at a different rip, or a
title's `LIBRARY` turns out to be built differently, this is what says so.

The disk-backed tests skip cleanly with no disks, which is
`tests/gamedata.py`'s rule and `tools/gamedisks.py`'s job here.
"""

from __future__ import annotations

import functools

import pytest

from goldbox import games, portraits
from tools import gamedisks, portraitdraw

#: Loader slots 13 and 14 are `BODY<xx>` and `HEAD<xx>`
#: (`docs/140-loaded-files-cache.md`).
ART_SLOTS = (13, 14)

TITLES = (
    ("pool-of-radiance", "POR_DISKS"),
    ("curse-of-the-azure-bonds", "COAB_DISKS"),
    ("secret-of-the-silver-blades", "SSB_DISKS"),
)


@functools.lru_cache(maxsize=8)
def _disks(key: str):
    return gamedisks.find(key)


def _library_asks(key: str):
    """`(address, slot)` for every loader call in that title's `LIBRARY`."""
    sides = portraitdraw.sides_of(key, None)
    assert sides, f"{key}: no sides"
    side, library = portraitdraw.read_named(sides, b"LIBRARY")
    assert library is not None, f"{key}: no LIBRARY on any of its sides"
    base, good, bad = portraitdraw.base_of(library)
    assert good > bad, (
        f"{key}: no load address makes {side}'s LIBRARY decode -- "
        f"{good} good jump targets against {bad} bad at ${base:04X}")
    tables = portraitdraw.library_tables(library, base)
    assert tables, f"{key}: LIBRARY's 25-slot table is not in it"
    out = []
    for entry in (tables["ensure_entry"], tables["reload_entry"]):
        for at in portraitdraw.calls_to(library, entry):
            out.append((base + at, portraitdraw.slot_asked_for(library, at)))
    return sorted(out)


# -- the fact, as the conversion will read it -------------------------------
def test_pool_of_radiance_is_the_one_title_that_draws_a_sheet_portrait():
    assert portraits.draws_sheet_portrait(games.POOL_OF_RADIANCE)
    assert not portraits.draws_sheet_portrait(games.CURSE_OF_THE_AZURE_BONDS)
    assert not portraits.draws_sheet_portrait(
        games.SECRET_OF_THE_SILVER_BLADES)


def test_the_predicate_takes_a_key_as_well_as_a_game():
    assert portraits.draws_sheet_portrait("pool-of-radiance")
    assert not portraits.draws_sheet_portrait("curse-of-the-azure-bonds")
    # A title nobody has measured is not a title with a portrait.
    assert not portraits.draws_sheet_portrait("champions-of-krynn")


def test_no_other_title_has_been_claimed_without_being_measured():
    """The frozenset is a claim about engines, one per key in it.

    Adding a key here means somebody read that title's sheet routine.  This
    fails the moment one is added without the tests below being extended to
    cover it.
    """
    assert portraits.SHEET_PORTRAIT_TITLES == {"pool-of-radiance"}


# -- the same fact, re-derived off the player's own disks --------------------
@pytest.mark.skipif(_disks("pool-of-radiance") is None,
                    reason="needs the Pool of Radiance disks; set POR_DISKS")
def test_pool_of_radiances_library_asks_the_loader_for_head_and_body():
    """`LIBRARY $48B8`/`$48C0`: record 0x0FE into slot 14, 0x0FF into 13."""
    asks = _library_asks("pool-of-radiance")
    art = [(a, s) for a, s in asks if s in ART_SLOTS]
    assert sorted(s for _a, s in art) == [13, 14], (
        f"Pool of Radiance's LIBRARY asks for {asks}, which is not the "
        f"one head and one body the sheet portrait needs")


@pytest.mark.parametrize("key,env", [t for t in TITLES if t[0] != TITLES[0][0]])
def test_the_later_titles_library_never_calls_the_loader(key, env):
    """No loader call at all -- so no sheet portrait, whatever a record says.

    This is stronger than "asks for no art": Curse's and Silver Blades'
    `LIBRARY` reach the loader zero times, so the portrait step is absent
    rather than disabled.
    """
    if _disks(key) is None:
        pytest.skip(f"needs that title's disks; set ${env}")
    asks = _library_asks(key)
    assert asks == [], (
        f"{key}: LIBRARY now calls the loader at {asks} -- if any of those "
        f"asks for slot 13 or 14 this title draws a sheet portrait after "
        f"all, and goldbox.portraits.SHEET_PORTRAIT_TITLES is wrong")
    assert not portraits.draws_sheet_portrait(key)


def test_no_title_means_pool_of_radiance_like_every_other_resolver():
    """`draws_sheet_portrait(None)` answers True, and the reason is a habit.

    Every other resolver in this package treats a missing title as Pool of
    Radiance -- `goldbox.spells.for_game`, `goldbox.levels.for_game`,
    `goldbox.traits.for_game`, `goldbox.c64_save.container_for` and
    `goldbox.c64_codec.record_shape` -- because every caller that passes none
    predates the second game and means the first. A predicate that answered
    False here would be the one in the family that disagreed, and it would
    disagree in the direction that drops a portrait Pool of Radiance really
    does draw.
    """
    assert portraits.draws_sheet_portrait(None) is True
    assert portraits.draws_sheet_portrait() is True

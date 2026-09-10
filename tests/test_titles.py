"""`goldbox/titles.py`, stage 1 of `#470 (Give the project a neutral title
beside its neutral character record, with one port per platform a title
shipped on)`.

Two things this pins down, beside the module existing at all:

* **Pools of Darkness is a `Title` and not a `Game`.** It has no C64 release,
  so `goldbox.games.BY_KEY` must never answer for it -- that silent fallback
  to Pool of Radiance's tables was `#460 (goldbox/games.py has no Pools of
  Darkness entry, so every lookup answers with Pool of Radiance's tables for
  it)`.
* **A `Game`'s races and class bits are the very same object as its
  `Title`'s**, not merely an equal copy, which is what proves the tuple is
  defined once rather than twice and kept in step by hand.

The DOS/C64 race-table comparison below is the exception table measured for
`#470` and posted on its issue on 2026-09-09 ("Question 2 settled: five
exception rows over three titles"), with one row removed: `#470`'s own stage
1 adds `(7, "monster")` to `RACES_SILVER_BLADES`, which was the one row of
the five that was our own gap rather than a real disagreement between the
two race tables, so it no longer disagrees and is not listed.
"""

from __future__ import annotations

import pytest

from goldbox import dos_layout, games, titles

# --- the seven titles, and the C64 title Pools of Darkness never had -------

def test_seven_titles_including_pools_of_darkness_with_no_c64_row():
    assert len(titles.TITLES) == 7
    assert titles.by_key("pools-of-darkness").title == "Pools of Darkness"
    assert games.BY_KEY.get("pools-of-darkness") is None


def test_by_key_raises_for_an_unknown_key():
    with pytest.raises(titles.UnknownTitleError):
        titles.by_key("not-a-real-title")


def test_games_unknown_game_error_is_the_titles_error():
    """`games.UnknownGameError` is an alias, not a second class."""
    assert games.UnknownGameError is titles.UnknownTitleError


# --- the six C64 titles: titles.py and games.py must agree ------------------

C64_KEYS = (
    "pool-of-radiance", "curse-of-the-azure-bonds",
    "secret-of-the-silver-blades", "champions-of-krynn",
    "death-knights-of-krynn", "gateway-to-the-savage-frontier",
)


@pytest.mark.parametrize("key", C64_KEYS)
def test_race_and_class_tables_agree_with_the_c64_port(key):
    game = games.by_key(key)
    assert titles.race_table(key) == games.race_table(game)
    assert titles.class_table(key) == games.class_table(game)


@pytest.mark.parametrize("game, title", [
    (games.POOL_OF_RADIANCE, titles.POOL_OF_RADIANCE),
    (games.CURSE_OF_THE_AZURE_BONDS, titles.CURSE_OF_THE_AZURE_BONDS),
    (games.SECRET_OF_THE_SILVER_BLADES, titles.SECRET_OF_THE_SILVER_BLADES),
    (games.CHAMPIONS_OF_KRYNN, titles.CHAMPIONS_OF_KRYNN),
    (games.DEATH_KNIGHTS_OF_KRYNN, titles.DEATH_KNIGHTS_OF_KRYNN),
    (games.GATEWAY_TO_THE_SAVAGE_FRONTIER,
     titles.GATEWAY_TO_THE_SAVAGE_FRONTIER),
])
def test_a_games_races_and_class_bits_are_its_titles_own_object(game, title):
    """Identity, not equality -- the tuple is defined once."""
    assert game.races is title.races
    assert game.class_bits is title.class_bits


# --- the DOS titles: titles.py and dos_layout.py, except where they always
# --- disagreed --------------------------------------------------------------

#: Where a title's rules-level race list (`titles.py`) and its DOS
#: executable's own string table (`dos_layout.DosShape.race_numbers`)
#: disagree, and why.  Every row is a code no character-generation menu
#: offers; every code not in this table has to agree on both sides, which is
#: what the test below asserts.  Measured for #470 on 2026-09-09: the DOS
#: side from each executable via `tools/dosraces.py --check` (4 of 4 tables
#: reproduced), the C64 side from the three-instruction label lookup in each
#: title's `LIBRARY`, and both against 257 C64 `MON*` records and 475 DOS
#: records.
#:
#: key -> {code: (Title.races name, race_numbers name, what the C64 prints)}
RACE_TABLE_EXCEPTIONS: dict[str, dict[int, tuple[str | None, str, str]]] = {
    "pool-of-radiance": {
        # `LIBRARY $3508` special-cases race 0 to string index 7, MONSTER --
        # and 63 of the title's 116 C64 `MON*` records read 0, exactly as the
        # DOS side does.  Our tuple is 1-based and leaves 0 out; the editor
        # adds it back for display in `editor/enums.py`.
        0: (None, "monster", "MONSTER"),
        # `race - 1` puts 8 on string index 7 as well, so the C64 answers
        # MONSTER for a code the DOS table does not reach -- it has eight
        # entries, 0 to 7.  Nothing writes 8: 0 of 257 C64 `MON*` records and
        # 0 of 475 DOS records carry it.
        8: ("monster", None, "MONSTER"),
    },
    "curse-of-the-azure-bonds": {
        0: (None, "monster", "MONSTER"),          # as Pool of Radiance
        # Curse dropped half-orc from generation.  Its DOS executable still
        # ships Pool of Radiance's whole eight-entry table with `Half-Orc` at
        # 6; the C64 removed the HALF-ORC string and pointed table entries 5
        # and 6 at the same `HUMAN`, so 6 and 7 are indistinguishable on
        # screen (`docs/125-bug-notes.md` N4).  `titles.RACES_CURSE` leaves 6
        # unnamed on purpose: "half-orc" contradicts what the game prints and
        # "human" would let an import rewrite a 7 as a 6.
        6: (None, "half-orc", "HUMAN"),
        8: ("monster", None, "MONSTER"),
    },
    "secret-of-the-silver-blades": {
        # The DOS executable's entry 0 is `Tribble`, the game's own joke.  The
        # C64 lookup has no special case, so race 0 reads item-name pool entry
        # 140, which happens to be a second copy of `ELF`.  Reached by
        # nothing: 0 of 57 DOS records and 0 of 71 C64 `MON*` records read 0.
        0: (None, "tribble", "ELF"),
        # Code 7 is NOT listed here any more.  `LIBRARY $306A` folds race 7
        # and above to MONSTER, and 50 of the title's 71 C64 `MON*` records
        # read 7 -- the C64 agreed with the DOS table all along, and
        # `RACES_SILVER_BLADES` was simply missing the entry.  #470's stage 1
        # added `(7, "monster")`, so the two sides now agree here and the
        # loop below checks it like any other code.
    },
    # Pools of Darkness has no exceptions: its races tuple is built straight
    # from `dos_layout.POOLS_OF_DARKNESS_RACE_NUMBERS`, so the two sides are
    # the same table by construction.
}

#: The four titles with both a C64 `races` tuple and a DOS `DosShape`.
#: Gateway to the Savage Frontier has no `DosShape` and contributes no row;
#: Pools of Darkness has no C64 `races` tuple of its own kind but does have
#: both a `Title.races` and a `DosShape`, so it is in this list.
DOS_TITLE_KEYS = (
    "pool-of-radiance", "curse-of-the-azure-bonds",
    "secret-of-the-silver-blades", "pools-of-darkness",
)


@pytest.mark.parametrize("key", DOS_TITLE_KEYS)
def test_titles_and_dos_race_tables_agree_except_the_documented_exceptions(
        key):
    shape = dos_layout.shape_for(key)
    race_names = titles.by_key(key).race_names or {}
    exceptions = RACE_TABLE_EXCEPTIONS.get(key, {})
    for code, dos_name in enumerate(shape.race_numbers):
        title_name = race_names.get(code)
        if code in exceptions:
            expected_title_name, expected_dos_name, _ = exceptions[code]
            assert (title_name, dos_name) == (
                expected_title_name, expected_dos_name), (key, code)
            continue
        if title_name is None:
            continue  # this title's races tuple simply does not reach here
        assert title_name == dos_name, (key, code, title_name, dos_name)


def test_the_gap_this_stage_fixes_is_closed():
    """`#470`'s one correction: Silver Blades' race 7 was a bare number
    where Pool of Radiance's and Curse's print MONSTER for their own edge
    code. It is a missing entry, not a difference between the games."""
    assert dict(titles.RACES_SILVER_BLADES)[7] == "monster"


def test_pool_of_radiance_and_curse_keep_their_honest_unreached_eight():
    """Nothing writes race 8 in either title, and it stays: the C64 really
    does print MONSTER for it, so deleting it would be unsupported by
    anything the games do."""
    assert dict(titles.RACES_FORGOTTEN_REALMS)[8] == "monster"
    assert dict(titles.RACES_CURSE)[8] == "monster"

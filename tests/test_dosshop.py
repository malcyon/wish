"""New Phlan's four shops, and the record the engine wrote after a purchase.

`tools/dosshop.py` walks a DOS Pool of Radiance party into a shop.  Three
things about it can be checked with no emulator, and they fail for different
reasons.

**Where the shops are** is arithmetic over the player's own files: `ECL00`'s
twenty-eight-way `ONGOTO`, the four arms that end in `TREASURE` and the
`$6E6C` "a shop instead of a fight" side channel, and the squares `GEO00`
gives those arm numbers to.  A wrong square sends a run into a wall and costs
a boot to find out.

**Which port that reading came from.**  The DOS build's own `GEO3.DAX` block
0 is byte-identical to the C64's `GEO00`, and its `ECL3.DAX` block 0 puts the
same four shop ids at the same arms.  That is what makes a table read on one
port legitimate on the other, and it is checked here rather than asserted in
a comment.

**What the engine wrote** is `WISH-SPEC-por-party-l1-shopped`: a party rolled
in the game's own creation screens which bought two hand axes with the gold
the engine gave it.  What is asserted is the engine's arithmetic -- the purse,
the item weights and the encumbrance it recomputed -- never anything this
project staged.  These skip where the specimen tree or the disks are absent,
which is every CI runner.
"""

from __future__ import annotations

import gamedata
import pytest

from goldbox import dos_codec
from goldbox import geo as geolib
from tools import dosbox, dosshop

SHOPPED = "por-party-l1-shopped"
BEFORE = "por-party-l1-intown"


@pytest.fixture(scope="module")
def new_phlan():
    """`GEO00` off the player's own C64 disks: area 0's map."""
    if gamedata.disk_dir() is None:
        pytest.skip("needs the player's Pool of Radiance disks")
    return geolib.Geo(gamedata.game_file("GEO00"))


@pytest.fixture(scope="module")
def dos_game():
    """The DOS install, wherever `tools/dosbox.py` finds it."""
    try:
        where = dosbox.find_game()
    except Exception:
        pytest.skip("needs the DOS Pool of Radiance install")
    if not (where / dosshop.DOS_GEO_DAX).is_file():
        pytest.skip(f"no {dosshop.DOS_GEO_DAX} in {where}")
    return where


# -- where the shops are -----------------------------------------------------


def test_the_shop_squares_agree_with_the_players_own_map(new_phlan):
    """Every square in `SHOPS` carries the script id the table claims, and
    every approach square can step the way the tool means to walk it."""
    assert dosshop.check_shops(new_phlan) == []


def test_no_approach_square_is_a_shop_it_did_not_mean_to_enter(new_phlan):
    """A run pokes the party onto its approach square, which fires nothing,
    and then steps.  If the approach were another shop's square the *next*
    step out of it would open a shop nobody asked for, so the ones that are
    get named here rather than discovered in a boot."""
    on_a_shop = {row["shop"]: row["approach"][0]
                 for row in dosshop.SHOPS.values()
                 if new_phlan.script_id(*row["approach"][0])}
    assert on_a_shop == {52: (9, 10)}, (
        "the set of shops whose only approach is another shopfront has "
        "changed; 52 at (8,10) is reached from 54's (9,10) and was the only "
        "one")


def test_every_shop_has_its_own_script_id(new_phlan):
    """Four shops, four distinct arms, four distinct ids.  A repeat would
    mean two shops share a dispatch arm, which the tool's `--shop` could not
    tell apart."""
    assert len(dosshop.SHOPS) == 4
    assert len({row["shop"] for row in dosshop.SHOPS.values()}) == 4


# -- and that the reading transfers to the port being driven -----------------


def test_the_dos_build_ships_the_same_new_phlan_map(dos_game, new_phlan):
    """`GEO3.DAX` block 0 against `GEO00` off the C64 disks, byte for byte.

    The shop table was read on the C64 and every run walks it under DOSBox.
    """
    assert dosshop.geo00_dos(dos_game).to_bytes() == new_phlan.to_bytes()


def test_the_dos_script_puts_the_same_shops_at_the_same_arms(dos_game):
    """`ECL3.DAX` block 0's own `ONGOTO`, its own `TREASURE` statements."""
    assert dosshop.shop_arms(dosshop.ecl00_dos(dos_game)) == {
        script_id: row["shop"] for script_id, row in dosshop.SHOPS.items()}


def test_the_script_base_is_measured_rather_than_assumed(dos_game):
    """The DOS block carries two bytes in front of the C64's `$9900`."""
    assert dosshop.ecl_base(dosshop.ecl00_dos(dos_game)) == 0x98FE


def test_the_arm_table_is_the_twenty_eight_the_dispatch_declares(dos_game):
    arms = dosshop.arm_table(dosshop.ecl00_dos(dos_game))
    assert len(arms) == dosshop.ARMS
    for script_id in dosshop.SHOPS:
        assert arms[script_id] not in (arms[11], arms[0]), (
            f"arm {script_id} shares the do-nothing stub's address")


# -- what the engine wrote when the party bought something -------------------


def _record(name, filename):
    return dos_codec.read_character(gamedata.specimen(name) / filename)


def test_the_shopped_character_carries_what_the_shop_sold_him():
    """Two hand axes at 50 weight each, neither readied, bought for 1 gp."""
    who = _record(SHOPPED, "CHRDATF1.SAV")
    assert who.name == "WISHFTR"
    assert who.get("item_count") == 2
    assert [it.get("weight") for it in who.items] == [50, 50]
    assert [it.get("value") for it in who.items] == [1, 1]
    assert [it.get("readied") for it in who.items] == [0, 0]


def test_the_shopped_record_balances_because_a_sheet_was_drawn():
    """What the engine left after two purchases and a look at the sheet.

    Before the trip the record held 140 gold, no items and encumbrance 140.
    After it the engine wrote 27 platinum and 3 gold -- 138 gp of value in
    **thirty coins** -- two items of 50, and encumbrance 130.  So the field
    counts coins rather than their value.

    It balances because the run opened `VIEW` in the shop, and every screen
    that draws encumbrance recomputes it first (`docs/125-bug-notes.md` N19).
    A purchase on its own does not leave it right, which is what
    `test_a_purchase_writes_the_sum_from_before_the_money_was_taken` measures.
    """
    who = _record(SHOPPED, "CHRDATF1.SAV")
    assert who.money["platinum"] == 27
    assert who.money["gold"] == 3
    assert sum(who.money.values()) == 30
    assert who.get("encumbrance") == 130
    assert who.expected_encumbrance() == 130


def test_the_five_who_bought_nothing_are_untouched():
    """The controls, in the same save: only the buyer's record moved."""
    for slot in range(2, 7):
        after = _record(SHOPPED, f"CHRDATF{slot}.SAV")
        before = _record(BEFORE, f"CHRDATE{slot}.SAV")
        assert after.money == before.money, after.name
        assert after.get("encumbrance") == before.get("encumbrance")
        assert after.get("item_count") == 0


def test_every_record_in_the_shopped_save_balances():
    """Six of six, one of them carrying items the engine put there."""
    for slot in range(1, 7):
        who = _record(SHOPPED, f"CHRDATF{slot}.SAV")
        assert who.get("encumbrance") == who.expected_encumbrance(), who.name


# -- the purchase bug, and its control ---------------------------------------

SPOILED = "por-shop-encumbrance-spoiled"
CONTROL = "por-shop-encumbrance-control"

#: What was staged into every record's stored encumbrance for these two
#: specimens.  The engine's own arithmetic cannot produce it for any of
#: these six characters, which is why it was chosen -- but `#429
#: (tools/dosshop.py stages its spoiled encumbrance after the load, so the
#: engine never reads it)` found that in both of these the poke landed
#: *after* the boot had already loaded the party, so it never reached the
#: engine's resident copy of the record.  CONTROL's own "recompute" was
#: that bug's artefact and is gone below; SPOILED's purchase number does
#: not depend on it either way, which is also explained below.
SPOIL = 999


def test_a_purchase_writes_the_sum_from_before_the_money_was_taken():
    """`docs/125-bug-notes.md` N19, measured in Pool of Radiance.

    WISHFTR bought one hand axe listed at 1 gp with a purse of 140 gold
    coins, and the engine wrote **190** into stored encumbrance -- his purse
    as it stood *before* it paid, 140 coins, plus the axe's 50.  The right
    sum is 81: paying 1 gp of 140 left 27 platinum and 4 gold, which is
    thirty-one coins.

    **This specimen's own 999 poke does not touch this finding.** `#429`
    found it landed after the boot, so it never reached the engine's
    resident copy of the record -- which settles what an earlier version of
    this test tried to read from the same number: 140 + 50 is 190 whether
    `shop_buy` rebuilt the whole sum or added the axe's weight to what was
    already there, so the 190 cannot say which. What it does show, and what
    the poke's timing does not touch, is that the coins were already spent
    when the write happened and the field is one purchase behind.
    """
    who = _record(SPOILED, "CHRDATG1.SAV")
    assert who.name == "WISHFTR"
    assert who.get("item_count") == 1
    assert sum(who.money.values()) == 31
    assert who.expected_encumbrance() == 81
    assert who.get("encumbrance") == 190


def test_the_five_who_bought_nothing_came_out_of_the_shop_correct():
    """The controls inside the same save: the wrong number is the buyer's."""
    for slot in range(2, 7):
        who = _record(SPOILED, f"CHRDATG{slot}.SAV")
        assert who.get("encumbrance") == who.expected_encumbrance(), who.name


def test_an_ordinary_in_town_save_preserves_stored_encumbrance():
    """`#429` corrected this: a plain save does not rewrite the field.

    `CONTROL`'s own "all six come back correct" was staged the same way
    `#429` found broken -- the 999 landed on disk after `open_loaded` had
    already booted DOSBox and loaded the party, so the engine's resident
    copy was never spoiled and its save simply wrote that untouched, already
    -correct copy back. `WISH-SPEC-por-enc-spoiled-campsave` is the same
    experiment with the poke moved before the boot, by `tools/dosencsave.py`
    -- which is the order this tool now uses too. All six come back **still
    holding 999**, so an ordinary camp save preserves whatever the engine
    loaded and recomputes nothing. `tests/test_dosencsave.py` pins this
    specimen and its two companions, `-menusave` and `-viewed`.
    """
    for slot in range(1, 7):
        who = _record("por-enc-spoiled-campsave", f"CHRDATB{slot}.SAV")
        assert who.get("encumbrance") == SPOIL, who.name
        assert who.get("encumbrance") != who.expected_encumbrance(), who.name


def test_the_training_ladder_kept_a_stale_value_through_the_same_engine():
    """And the contradiction that is not resolved, pinned so it stays visible.

    Nine ladder rungs saved a record whose stored encumbrance disagrees with
    its purse by the training fee, so whatever rewrites the field in an
    in-town camp save did not happen on those boots.  The two differ in the
    save path -- `ENCAMP` from the map against the training hall's own party
    menu -- and nobody has separated them.
    """
    if not gamedata.have_specimen("por-party-ladder-rung1"):
        pytest.skip("needs specimen WISH-SPEC-por-party-ladder-rung1")
        return
    who = dos_codec.read_character(
        gamedata.specimen("por-party-ladder-rung1") / "CHRDATE1.SAV")
    assert who.get("encumbrance") == 21000
    assert who.expected_encumbrance() == 19000

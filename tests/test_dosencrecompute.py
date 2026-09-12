"""`tools/dosencrecompute.py` reads the recompute out of the shipped binaries.

`#323 (The encumbrance identity does not survive the training fee, so failing
it is not evidence of an edited record)`.  The finding the tool carries is that
**the engine has no path on which a coin purse changes and the total is
rebuilt in the same routine**, which is why a training fee survives a save,
and that Pool of Radiance takes 5000 tenths of a pound off for a readied bag
of holding, which is a way a record fails the identity *below* the sum without
anybody having edited it.

Everything here needs the player's copy of *Forgotten Realms: The Archives*
and skips without it, the way `tests/gamedata.py` skips without the C64 disks.
The two tests that need no game data at all are the ones that would go red on
a reader mistake rather than on a missing corpus: the gate reader, and the
insistence that the money fields come from `goldbox/dos_layout.py`.

One thing these do **not** assert: a remembered address.  The tool finds the
routine by signature, and pinning `0x1758` here would turn a re-derivation
into a copy of the answer.  What is pinned is the *shape* -- a zero, an
accumulate and a store, in that order, in one routine.
"""

from __future__ import annotations

import pytest

# `capstone` is not a declared dependency of this project -- the same reason
# `tests/test_amiga68k.py` and its neighbours skip rather than fail. The tool
# reaches it through `tools/dosovrmap.py`, so the import below is what fails
# on a machine without it, and CI is such a machine: this file was green here
# and red on both Linux jobs, 2026-09-09.
pytest.importorskip("capstone")

from goldbox import dos_port as dl  # noqa: E402
from tools import dosencrecompute as der  # noqa: E402

#: The three titles `#323` asks about.  Pools of Darkness is left out because
#: it ships no EXEPACKed loader, so it has no unit map and no far callers --
#: which the tool reports rather than hides, and which is not a finding here.
TITLES = ("POOLRAD", "CURSE", "SECRET")


def _found(stem: str):
    try:
        return der.find_recompute(stem)
    except (FileNotFoundError, der.NotFound) as exc:
        pytest.skip(f"no DOS {stem} on this machine: {exc}")


def test_the_money_offsets_come_from_the_layout_rather_than_a_local_table():
    """A shape correction in `goldbox/dos_layout.py` must move this tool.

    The failure this prevents is silent: a tool with its own copy of the seven
    displacements goes on reading whatever used to be at `0x88` and reports a
    confident zero.
    """
    for stem, key in der.SHAPE_KEY.items():
        fields = dl.FIELDS_BY_NAME_FOR[key]
        got = der.offsets(stem)
        assert got["encumbrance"] == fields["encumbrance"].offset
        assert got["coins"] == [fields[c].offset for c in der.COIN_FIELDS
                                if c in fields]
        assert got["valuables"] == [fields[c].offset
                                    for c in der.VALUABLE_FIELDS
                                    if c in fields]


def test_the_coin_purses_are_counted_apart_from_gems_and_jewelry():
    """Lumping the seven together is what made the first reading wrong.

    One routine per title decrements `gems` and calls the recompute, so a
    single count over all seven money fields reports "one routine does both"
    and hides that no *coin* writer ever does.
    """
    assert set(der.COIN_FIELDS).isdisjoint(der.VALUABLE_FIELDS)
    assert "gold" in der.COIN_FIELDS and "gems" in der.VALUABLE_FIELDS


@pytest.mark.parametrize("stem", TITLES)
def test_the_recompute_zeroes_the_field_before_it_accumulates(stem):
    """The routine rebuilds the total rather than adjusting it.

    Three writes in order inside one routine: a `mov` of zero, the `add` that
    accumulates one item's weight, and the `mov` that stores the running sum
    after the seven purses.  A routine that only ever added would leave a
    stale total exactly where a fee does, and the two would be
    indistinguishable from outside.
    """
    found = _found(stem)
    mnems = [w["mnem"] for w in found["writes_in_routine"]]
    assert mnems[:3] == ["mov m16,r16", "add m16,r16", "mov m16,r16"], mnems
    assert found["start"] < found["accumulate"]


@pytest.mark.parametrize("stem", TITLES)
def test_no_routine_that_writes_a_coin_purse_calls_the_recompute(stem):
    """The whole of why a training fee survives a save.

    If this ever goes green-to-red, the engine has a path that repairs the
    total when money moves, and `.claude/rules/testing.md`'s account of why a
    stale total is not evidence of an edit needs re-reading.
    """
    found = _found(stem)
    ovr = found["files"]["GAME.OVR"]
    callers = {der.routine_start(ovr, site)
               for name, site in der.call_sites(found) if name == "GAME.OVR"}
    writers = der.money_writers(found, "coins")
    assert callers, "no caller found at all -- the unit map or the scan broke"
    assert writers, "no coin writer found at all -- the scan broke"
    assert not set(writers) & callers


@pytest.mark.parametrize("stem", TITLES)
def test_exactly_one_routine_writes_gems_or_jewelry_and_recomputes(stem):
    """The appraise screen, and it is the exception that proves the rule.

    It is asserted rather than waved at because it is the one counterexample
    to the sentence above, and a second one appearing would mean the sentence
    is about a coincidence rather than about how the engine is built.
    """
    found = _found(stem)
    ovr = found["files"]["GAME.OVR"]
    callers = {der.routine_start(ovr, site)
               for name, site in der.call_sites(found) if name == "GAME.OVR"}
    both = set(der.money_writers(found, "valuables")) & callers
    assert len(both) == 1, sorted(hex(b) for b in both)


def test_pool_of_radiance_discounts_a_readied_bag_of_holding():
    """5000 tenths of a pound, gated on a local the item walk sets.

    This is the term `goldbox.dos.expected_encumbrance` does not have, so a
    character carrying one stores *below* the sum with nobody having edited
    anything.
    """
    found = _found("POOLRAD")
    bag = der.bag_block(found)
    assert bag["state"] == "live", bag
    assert len(bag["writes"]) == 2, bag        # the zero, and the item walk


def test_curse_ships_the_same_block_with_nothing_to_switch_it_on():
    """A defect in the game rather than in this reader.

    Curse of the Azure Bonds has the identical tail and its gating local is
    written once, by the initialising zero.  So the branch cannot be taken and
    a bag of holding reduces nothing in that title.  Stated as one write
    rather than as "dead code", because the count is what was measured.
    """
    found = _found("CURSE")
    bag = der.bag_block(found)
    assert bag["state"] == "dead", bag
    assert len(bag["writes"]) == 1, bag
    assert found["start"] < bag["writes"][0] < bag["discount"], bag


def test_silver_blades_has_no_such_block_at_all():
    """Not a dead branch -- an absent one, which is a different claim."""
    assert der.bag_block(_found("SECRET"))["state"] == "absent"

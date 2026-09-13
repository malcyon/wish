"""`tools/enccensus.py` counts an encumbrance failure only where there is one.

`#323 (The encumbrance identity does not survive the training fee, so failing
it is not evidence of an edited record)`.  Two ways the census lied before
these tests existed, both of which would have made the ticket's headline
number wrong:

* **A record whose item file is not beside it "fails" by its whole
  inventory.**  `goldbox.dos_codec.read_character` gives an export with no `.ITM`
  no items and does not complain, so its money alone is compared against a
  stored total that counts items.  Six Amiga `.cha` exports on the Curse save
  disk declare 6 to 16 items each and were being reported as misses of +240
  to +1034.
* **A record found in two places took the grade of whichever path was walked
  first.**  The archives' `games/POOLRAD/GAME/POOLRAD/SAVE` is byte-identical
  to `~/dos_por_play/SAVE`, every record in which has been through Gold Box
  Companion's editor, so grading the archive copy `found` launders it.

The corpus test at the bottom is the finding itself -- every record the
player's own archives ship balances exactly -- and skips without the archives.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import c64_codec, layout
from goldbox import dos_port as dl
from tools import dostailcensus, enccensus

ENCUMBRANCE = dl.FIELDS_BY_NAME["encumbrance"].offset
ITEM_COUNT = dl.FIELDS_BY_NAME["item_count"].offset
GOLD = dl.FIELDS_BY_NAME["gold"].offset
SIZE = dl.POOL_OF_RADIANCE.record_size


def _record(path: pathlib.Path, *, gold: int = 0, encumbrance: int = 0,
            items: int = 0) -> pathlib.Path:
    """A Pool of Radiance record carrying just the three fields in the sum."""
    data = bytearray(SIZE)
    data[GOLD:GOLD + 2] = gold.to_bytes(2, "little")
    data[ENCUMBRANCE:ENCUMBRANCE + 2] = encumbrance.to_bytes(2, "little")
    data[ITEM_COUNT] = items
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(data))
    return path


def test_leading_number_reads_the_count_off_a_cached_inventory_line():
    """`37 Darts` against a quantity byte of 50 is the disagreement the
    stacks mode exists to find; a line with no count must not read as one."""
    assert enccensus.leading_number("37 Darts ") == 37
    assert enccensus.leading_number(" No   Quarter Staff ") is None
    assert enccensus.leading_number(" Yes  * Bracers AC 6 ") is None
    assert enccensus.leading_number("") is None


def test_a_record_in_the_played_directory_and_the_archives_grades_edited():
    """The archives' installed save directory is byte-identical to the play
    directory, so a record found in both is an edited record however
    respectable the other path looks."""
    both = ["/home/x/Downloads/fr-archives/games/POOLRAD/GAME/POOLRAD/SAVE/"
            "CHRDATA4.SAV",
            "/home/x/dos_por_play/SAVE/CHRDATA4.SAV"]
    assert enccensus._grade(both) == "edited"
    assert enccensus._grade(both[:1]) == "found"
    assert enccensus._grade(["/home/x/wish-specimens/por-dos/W/CHRDATA1.SAV"]) \
        == "spec"


def test_a_record_whose_item_file_is_missing_is_not_called_a_failure(tmp_path):
    """It declares three items nobody can weigh, so neither side of the sum
    is known.  Counting it as a miss is what put six Amiga exports into
    `#323`'s first headline number."""
    _record(tmp_path / "EXPORT.CHA", gold=100, encumbrance=900, items=3)

    rows, _skipped = enccensus.dos_rows([tmp_path])

    assert len(rows) == 1
    assert rows[0].declared == 3 and rows[0].items == 0
    assert not rows[0].readable
    assert rows[0].delta == 800          # what it would have been reported as


def test_a_record_with_no_items_is_judged_on_its_money_alone(tmp_path):
    """The training-fee shape: no items at all, and the stored total 1000
    above the purse.  This one is a real failure and must be counted."""
    _record(tmp_path / "CHRDATA1.SAV", gold=19000, encumbrance=20000)

    rows, _skipped = enccensus.dos_rows([tmp_path])

    assert len(rows) == 1 and rows[0].readable
    assert rows[0].delta == 1000


def test_a_balancing_record_is_not_a_miss(tmp_path):
    _record(tmp_path / "CHRDATA2.SAV", gold=537, encumbrance=537)

    rows, _skipped = enccensus.dos_rows([tmp_path])

    assert rows[0].readable and rows[0].delta == 0


def test_the_finder_keeps_the_same_exclusions_as_the_field_census(tmp_path):
    """A Gateway `.GUY` is Curse's record size and must not be read through
    Curse's table -- `#400`'s bug, and this finder is a second copy of that
    walk, so it has to keep the exclusion."""
    gateway = (tmp_path / "games/Gateway to the Savage Frontier/SAVE")
    gateway.mkdir(parents=True)
    (gateway / "TARLREN.GUY").write_bytes(
        bytes(dl.CURSE_OF_THE_AZURE_BONDS.record_size))

    rows, skipped = enccensus.dos_rows([tmp_path])

    assert rows == []
    assert skipped["gateway to the savage frontier"] == 1


def test_the_c64_record_has_no_encumbrance_to_check():
    """No C64 save can fail this identity, so no C64 save can be judged by
    it.  If the field is ever located on the C64 this test goes red and the
    census gains a third port.

    The layout assertion is the tripwire and always was.  The other one
    followed `encumbrance` from `c64_codec.DROPPED` to `c64_codec.DERIVED`
    on 2026-09-13: the C64 has nothing to store, and its engine recomputes
    the total from the purses and item weights while drawing a sheet --
    measured in the running game on both later titles,
    `docs/139-per-title-validation.md` row A8.  A conversion that reported a
    loss there was reporting a number the destination computes for itself.
    """
    assert "encumbrance" in dict(c64_codec.DERIVED)
    assert "encumbrance" not in dict(c64_codec.DROPPED)
    assert "encumbrance" not in layout.FIELDS_BY_NAME


# --- the corpus, off the player's own files ----------------------------------

def _archive_saves():
    root = dostailcensus.archives()
    if root is None:
        pytest.skip("no Forgotten Realms archives on this machine")
    found = sorted(p for p in root.rglob("Saves")
                   if p.is_dir() and any(p.glob("*.SAV")))
    if not found:
        pytest.skip("the archives here ship no Default files/Saves")
    return found


def test_every_record_the_archives_ship_balances_exactly():
    """`.claude/rules/testing.md` used to say six of the eighteen Pool of
    Radiance records in `Default files/Saves` fail the identity.  They do
    not, and neither does anything else the archives ship: 54 distinct
    records over four titles, 0 misses, measured 2026-09-07 (Treasures of
    the Savage Frontier's fourteen are skipped, having no layout here).  A
    reader change that brings the six back turns this red, which is the
    point of pinning it.
    """
    rows, _skipped = enccensus.dos_rows(_archive_saves())

    assert rows, "the archives are here but no record was read"
    misses = [r for r in rows if r.readable and r.delta]
    assert misses == [], "\n".join(
        f"{r.who} {r.where} stored={r.stored} coins={r.coins} "
        f"items={r.carried} delta={r.delta:+d}" for r in misses)

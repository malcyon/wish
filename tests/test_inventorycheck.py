from __future__ import annotations

"""An inventory edited in Wish, on Curse and on Silver Blades.

`docs/139-per-title-validation.md` A13 -- *"inventory edit, add, remove"* --
was `V` for Pool of Radiance and `U` for both later titles until 2026-09-08.
`#32 (One Curse session, to get a party with items)` step 4 is the same
sentence: *"round-trip an item edit and confirm it in the game"*.

**The confirming half of that cannot be a test**, because it needs the running
game. `tools/inventorycheck.py` is the run and the two issues carry what the
game drew, on VICE pool slot 7, 2026-09-08:

| | Curse, `curse-party-with-items` | Silver Blades, `ssb-d-engine-resave` |
|---|---|---|
| unedited | 10 rows, 7 `SILVER MIRROR`, `YES 1 FLASK OF OIL` | 12 rows, `30 ARROW +1` |
| edited | 7 rows, 3 mirrors, `9 SILVER MIRROR`, `TWO-HANDED SWORD` | 10 rows, `9 ARROW +1`, `CANARY` |

What is asserted here is the half a machine with no emulator can check: that
`tools/inventorycheck.stage` puts those bytes in the item area the game then
read, and that it puts them nowhere else.

Every test skips without the specimen tree, which CI has none of, and the two
that add an item skip without the player's own game disks -- adding one copies
a record off them (`editor.inventory`).
"""

import pathlib
import shutil

import pytest

from goldbox import c64_save, games
from goldbox.d64 import D64, split_load_address
from goldbox.items import ITEM_SIZE, ITEMS_PER_CHARACTER
from tests import gamedata
from tools import inventorycheck

#: The two specimens, the character on each who carries anything, and the
#: `tools/gamedisks.py` key that finds that title's sides.
CURSE = ("curse-party-with-items", "MALE ELF MAGE",
         "curse-of-the-azure-bonds")
SSB = ("ssb-d-engine-resave", "Guy de Valois",
       "secret-of-the-silver-blades")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _specimen_disk(name: str) -> pathlib.Path:
    """A single-file C64 specimen, checked against its own recorded hash.

    `tests.gamedata.specimen` takes a specimen that is a *directory*; the C64
    ones are a `.D64` beside a `.provenance.toml`, so the hash check is done
    here -- a specimen somebody has edited is no longer evidence, which is
    the whole of `#246`.
    """
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py and "
                    "$WISH_SPECIMENS")
    found = sorted(root.glob(f"*-c64/WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    disk = found[0]
    prov = disk.parent / f"WISH-SPEC-{name}.provenance.toml"
    if not prov.is_file():
        pytest.fail(f"{disk}: no provenance.toml -- not a specimen")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    for filename, expected in recorded.items():
        actual = specimens.sha256_file(disk.parent / filename)
        if actual != expected:
            pytest.fail(f"WISH-SPEC-{name}: {filename} has changed -- recorded "
                        f"{expected[:12]}, now {actual[:12]}; it is no longer "
                        f"evidence. Run tools/specimens.py check")
    return disk


def _disks(key: str) -> str:
    from tools import gamedisks
    where = gamedisks.find(key)
    if not where:
        pytest.skip(f"needs the player's own {key} disks")
    sides = sorted(pathlib.Path(where).glob("*.[dD]64"))
    if not sides:
        pytest.skip(f"no .d64 sides under {where}")
    return str(sides[0])


def _copy(path, tmp_path) -> str:
    """The specimen tree is read-only; every test works on its own copy."""
    out = tmp_path / pathlib.Path(path).name
    shutil.copy(path, out)
    out.chmod(0o644)
    return str(out)


def _payload(path) -> bytes:
    disk = D64.open(str(path))
    game = games.detect(disk)
    _addr, payload = split_load_address(disk.read_file(game.save_file))
    return bytes(payload)


def _names(path, side):
    from goldbox import items
    return items.load_item_names(side, games.detect(D64.open(str(path))))


def _listed(path, slot, side) -> list[tuple[str, int, bool]]:
    """The occupied item records, as `(name, quantity, readied)`."""
    block = inventorycheck.item_block(path, slot)
    return [(r["name"], r["quantity"], r["readied"])
            for r in inventorycheck.describe_block(block, _names(path, side))]


# --- what the C64 draws for a name that has lower case in it -----------------

def test_a_lower_case_letter_draws_as_the_glyph_forty_hex_below_it():
    """`Guy de Valois` is `G59 $% V!,/)3` on the party panel.

    Pinned against what VICE drew in `work/issue139-a13/ssb-run1`: this save
    was converted from DOS, which keeps mixed case, and a run looking for the
    name the record holds found nobody on the panel at all.
    """
    assert inventorycheck.as_drawn("Guy de Valois") == "G59 $% V!,/)3"
    assert inventorycheck.as_drawn("MALE ELF MAGE") == "MALE ELF MAGE"


# --- reading the item screen -------------------------------------------------

def test_the_item_list_reader_drops_the_frame_and_the_empty_slots():
    """Column 39 is the window's border and is never blank.

    A reader that took the row to the end of the line came back with every
    empty slot on the list as an item -- nineteen rows for a character
    carrying ten (`work/issue139-a13/control`).
    """
    rows = [""] * 25
    rows[3] = "*EQUIPPED ITEM                         <"
    rows[5] = "$ NO  TWO-HANDED SWORD                 $"
    rows[6] = "$ YES 1 FLASK OF OIL                   $"
    rows[7] = "$ NO  9 SILVER MIRROR                  *"
    rows[8] = "$                                      <"
    rows[9] = "$                                      $"
    assert inventorycheck.item_list(rows) == [
        "NO  TWO-HANDED SWORD",
        "YES 1 FLASK OF OIL",
        "NO  9 SILVER MIRROR",
    ]


def test_the_item_list_stops_at_pool_of_radiances_exit_row():
    rows = [""] * 25
    rows[5] = "$ NO  DAGGER                           $"
    rows[6] = "$ EXIT                                 $"
    rows[7] = "$ NO  NOT THIS ONE                     $"
    assert inventorycheck.item_list(rows) == ["NO  DAGGER"]


# --- the three edits, on each later title ------------------------------------

def test_a_curse_inventory_takes_a_remove_an_edit_and_an_add(app, tmp_path):
    """The seven rows VICE drew, in the order the save holds them.

    The game lists them backwards -- item 6 first, item 0 last -- so this
    asserts the save's own order and `#32`'s comment carries the screen's.
    """
    name, who, key = CURSE
    side = _disks(key)
    out = str(tmp_path / "edited.D64")
    report = inventorycheck.stage(_copy(_specimen_disk(name), tmp_path), out,
                                  who, delete=4, quantity=9,
                                  add="TWO-HANDED SWORD", game_disk=side)
    assert report["slot"] == 5
    assert len(report["before"]) == 10
    assert _listed(out, 5, side) == [
        ("SILVER MIRROR", 9, False),
        ("SILVER MIRROR", 0, False),
        ("SILVER MIRROR", 0, False),
        ("FLASK OF OIL", 1, False),
        ("FLASK OF OIL", 1, False),
        ("FLASK OF OIL", 1, True),
        ("TWO-HANDED SWORD", 0, False),
    ]


def test_a_silver_blades_inventory_takes_the_same_three(app, tmp_path):
    name, who, key = SSB
    side = _disks(key)
    out = str(tmp_path / "ssb-edited.D64")
    report = inventorycheck.stage(_copy(_specimen_disk(name), tmp_path), out,
                                  who, delete=0, quantity=9, add="CANARY",
                                  game_disk=side, delete_rows=[9, 10, 11],
                                  quantity_row=1)
    assert report["slot"] == 5
    assert len(report["before"]) == 12
    assert _listed(out, 5, side) == [
        ("MAGE SCROLL 3 SPELLS", 0, False),
        ("ARROW +1", 9, False),
        ("LEATHER ARMOR +1", 0, False),
        ("SCALE MAIL +2", 0, False),
        ("GAUNTLETS OF OGRE POWER", 0, False),
        ("WAND OF ICE STORM", 0, False),
        ("BRACERS AC 6", 0, False),
        ("HALBERD +2", 0, False),
        ("MACE +1", 0, False),
        ("CANARY", 0, False),
    ]


# --- and nothing else --------------------------------------------------------

@pytest.mark.parametrize("name,who,key", [CURSE, SSB], ids=["curse", "ssb"])
def test_an_edit_moves_no_byte_outside_that_characters_item_page(
        app, tmp_path, name, who, key):
    """Every byte that moved is inside the edited character's own page.

    Which is what makes the screen readings attributable: a run that changed
    one character's items and some byte of a neighbour's could have drawn its
    seven rows for either reason.
    """
    side = _disks(key)
    base = _copy(_specimen_disk(name), tmp_path)
    out = str(tmp_path / "edited.D64")
    report = inventorycheck.stage(base, out, who, delete=1, quantity=9,
                                  add=None, game_disk=side)
    before, after = _payload(base), _payload(out)
    assert len(before) == len(after)
    game = games.detect(D64.open(out))
    page = c64_save.CONTAINERS[game.key].items(report["slot"])
    moved = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert moved, "the edit wrote nothing at all"
    outside = [i for i in moved
               if not page <= i < page + ITEM_SIZE * ITEMS_PER_CHARACTER]
    assert outside == [], (
        f"{len(outside)} bytes moved outside slot {report['slot']}'s item "
        f"page, first at {outside[0]:#06x}")


@pytest.mark.parametrize("name,who,key", [CURSE, SSB], ids=["curse", "ssb"])
def test_a_save_with_no_edit_leaves_the_item_area_byte_for_byte(
        app, tmp_path, name, who, key):
    """Opening and saving must write nothing, or nothing above is evidence."""
    _disks(key)                     # skip alike, so the pair reports together
    base = _copy(_specimen_disk(name), tmp_path)
    out = str(tmp_path / "untouched.D64")
    inventorycheck.stage(base, out, who, delete=0, quantity=None, add=None)
    assert _payload(base) == _payload(out)

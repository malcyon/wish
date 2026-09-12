from __future__ import annotations

"""The seven purses edited in Wish, on Curse and on Silver Blades.

`docs/139-per-title-validation.md` A8 -- *"the seven money fields"* -- read
`V (gold only)` for both later titles until 2026-09-08, with the note that the
other six were untested on any title but Pool of Radiance. It was the last
unverified cell in that table anybody on this project could reach.

**The confirming half of that cannot be a test**, because it needs the running
game. `tools/pursecheck.py` is the run, and `#33 (One Silver Blades session, for the
whole editor path)` and `#32 (One Curse session, to get a party with items)`
carry what the game drew, on VICE pool slot 0, 2026-09-08, six boots:

| disk | character | the money box the game drew | `ENCUMBRANCE` |
|---|---|---|---|
| Curse, edited | `MALE ELF MAGE` | all seven, `JEWELRY 77` down to `COPPER 1111` | 16953 |
| Curse, unedited | `MALE ELF MAGE` | `PLATINUM 300` alone | 445 |
| Curse, edited | `CLERIC`, untouched | `PLATINUM 300` alone | 300 |
| Silver Blades, edited | `MORGAINE` | the same seven values | 16808 |
| Silver Blades, unedited | `MORGAINE` | **empty** | 0 |
| Silver Blades, edited | `MALACHITE`, untouched | `GOLD 4` alone | 4 |

What is asserted here is the half a machine with no emulator can check: that
`tools/pursecheck.stage` puts those seven numbers in the record the game then
read, that it puts them nowhere else, and that the encumbrance the engine drew
is the one this file predicts from the same bytes.

Eight of the twelve tests need the specimen tree, which CI has none of --
four functions run once per title. The other four are the screen reader and
the arithmetic, and they run everywhere.
"""

import pathlib
import shutil

import pytest

from goldbox import c64_port, c64_save
from goldbox.d64 import D64, split_load_address
from tests import gamedata
from tools import pursecheck

#: The two specimens and the character edited on each.  Curse's carries ten
#: items, so its encumbrance is coins *and* weight; Silver Blades' MORGAINE
#: carries nothing, so hers is the coins alone and the two together check the
#: identity from both ends.
CURSE = ("curse-party-with-items", "MALE ELF MAGE", 5)
SSB = ("ssb-d-engine-resave", "MORGAINE", 0)

#: What was staged into every purse, distinct so no two lines of the drawn
#: money box could be confused for each other.
STAGED = {"copper": 1111, "silver": 2222, "electrum": 3333, "gold": 4444,
          "platinum": 5555, "gems": 66, "jewelry": 77}


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _specimen_disk(name: str) -> pathlib.Path:
    """A single-file C64 specimen, checked against its own recorded hash.

    `tests.gamedata.specimen` takes a specimen that is a *directory*; the C64
    ones are a `.D64` beside a `.provenance.toml`, so the hash check is done
    here -- a specimen somebody has edited is no longer evidence.
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


def _copy(path, tmp_path) -> str:
    """The specimen tree is read-only; every test works on its own copy."""
    out = tmp_path / pathlib.Path(path).name
    shutil.copy(path, out)
    out.chmod(0o644)
    return str(out)


def _payload(path) -> bytes:
    disk = D64.open(str(path))
    game = c64_port.detect(disk)
    _addr, payload = split_load_address(disk.read_file(game.save_file))
    return bytes(payload)


# --- reading the money box off the sheet -------------------------------------

def test_the_money_box_reader_finds_all_seven_purses():
    """The seven lines Curse drew for `MALE ELF MAGE`, in the sheet's order.

    Pinned against what VICE drew in `work/issue139-a8/curse-edited-run`.  The
    engine's loop counts down from purse six, so jewelry is at the top and
    copper below `CHR` -- Pool of Radiance's order, unchanged in Curse.
    """
    rows = [""] * 25
    rows[7] = "$STR 16     JEWELRY  77                *"
    rows[8] = "$INT 18     GEMS     66                $"
    rows[9] = "$WIS 11     PLATINUM 5555              $"
    rows[10] = "*DEX 18     GOLD     4444              $"
    rows[11] = "<CON 14     ELECTRUM 3333              $"
    rows[12] = "$CHR 15     SILVER   2222              $"
    rows[13] = "$           COPPER   1111              $"
    rows[16] = "$AC 6   THACO  21    ENCUMBRANCE 16953 $"
    assert pursecheck.money_box(rows) == dict(STAGED, ENCUMBRANCE=16953)


def test_the_money_box_reader_reads_silver_blades_boxed_column():
    """The same seven, in the other title's layout.

    Silver Blades gives the money a boxed column of its own with the number
    right-aligned, so a reader tied to Curse's spacing would find none of it
    (`work/issue139-a8/ssb-edited-run`).
    """
    rows = [""] * 25
    rows[9] = "$STR 17            $JEWELRY         77 $"
    rows[10] = "%INT 18            %GEMS            66 %"
    rows[11] = "%WIS 14            %PLATINUM      5555 %"
    rows[12] = "%DEX 17            %GOLD          4444 %"
    rows[13] = "%CON 16            %ELECTRUM      3333 %"
    rows[14] = "%CHR 16            %SILVER        2222 %"
    rows[15] = "&                  &COPPER        1111 &"
    rows[17] = "$ARMOR CLASS     7 $ENCUMBRANCE  16808 $"
    assert pursecheck.money_box(rows) == dict(STAGED, ENCUMBRANCE=16808)


def test_a_purse_that_is_zero_draws_no_line_at_all():
    """The control run's box, which is the whole reason A8 sat open.

    `LIBRARY $31F2` skips a purse whose sixteen bits are zero, so a character
    with one purse draws one line -- and every capture this project took
    before 2026-09-08 was of a character like that
    (`work/issue139-a8/ssb-control-run`).
    """
    rows = [""] * 25
    rows[9] = "$STR 17            $                   $"
    rows[17] = "$ARMOR CLASS     7 $ENCUMBRANCE      0 $"
    box = pursecheck.money_box(rows)
    assert [f for f in pursecheck.PURSES if f in box] == []
    assert box == {"ENCUMBRANCE": 0}


def test_a_purse_word_inside_an_item_name_is_not_a_purse():
    """`GEMS` on the sheet's equipped-item line has no number after it.

    Curse's sheet draws the readied item under the ability scores -- the
    edited run's said `1 FLASK OF OIL` -- and an item whose name held a purse
    word would otherwise be read as a purse of that name.
    """
    rows = [""] * 25
    rows[19] = "$GEMS OF SEEING                        $"
    rows[20] = "$COPPER RING +1                        $"
    assert pursecheck.money_box(rows) == {}


# --- what the editor writes --------------------------------------------------

@pytest.mark.parametrize("name,who,slot", [CURSE, SSB], ids=["curse", "ssb"])
def test_all_seven_purses_land_in_the_record(app, tmp_path, name, who, slot):
    """The numbers the form's spin boxes were given, read back off the disk.

    Read through `goldbox.savegame` rather than through the widgets that set
    them, because the question is whether `EditorBinding._flush` put the bytes
    where the engine reads them -- and the engine did read them.
    """
    out = str(tmp_path / "edited.D64")
    report = pursecheck.stage(_copy(_specimen_disk(name), tmp_path), out, who,
                              dict(STAGED))
    assert report["slot"] == slot
    assert report["after"] == STAGED
    assert pursecheck.purses_on_disk(out, slot) == STAGED


@pytest.mark.parametrize("name,who,slot,drawn", [
    CURSE + (16953,), SSB + (16808,)], ids=["curse", "ssb"])
def test_the_predicted_encumbrance_is_the_one_the_game_drew(
        app, tmp_path, name, who, slot, drawn):
    """`sum(purses) + sum(item weight x quantity)`, against the screen.

    The C64 record has no encumbrance field -- `goldbox/c64_codec.py` lists it
    as derived -- so the engine recomputes this while drawing the sheet.  It
    is what turns seven labels on a screenshot into a reading of seven
    *numbers*: Curse's 16953 is 16808 of coins plus 145 tenths of a pound of
    items, and Silver Blades' MORGAINE carries nothing, so hers is the coins
    alone.
    """
    out = str(tmp_path / "edited.D64")
    pursecheck.stage(_copy(_specimen_disk(name), tmp_path), out, who,
                     dict(STAGED))
    assert pursecheck.expected_encumbrance(out, slot) == drawn


@pytest.mark.parametrize("name,who,slot", [CURSE, SSB], ids=["curse", "ssb"])
def test_an_edit_moves_no_byte_outside_that_characters_save_slot(
        app, tmp_path, name, who, slot):
    """Twelve bytes, all of them the money block of one 256-byte slot.

    Which is what makes the screen readings attributable: a run that changed
    one character's purses and some byte of a neighbour's could have drawn its
    seven lines for either reason.  Twelve and not fourteen because the high
    bytes of gems and jewelry were already zero and stayed zero.
    """
    base = _copy(_specimen_disk(name), tmp_path)
    out = str(tmp_path / "edited.D64")
    pursecheck.stage(base, out, who, dict(STAGED))
    before, after = _payload(base), _payload(out)
    assert len(before) == len(after)
    game = c64_port.detect(D64.open(out))
    page = c64_save.CONTAINERS[game.key].slot(slot)
    moved = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert moved, "the edit wrote nothing at all"
    outside = [i for i in moved if not page + 0x0BB <= i <= page + 0x0C8]
    assert outside == [], (
        f"{len(outside)} bytes moved outside slot {slot}'s money block, "
        f"first at {outside[0]:#06x}")
    assert len(moved) == 12


@pytest.mark.parametrize("name,who,slot", [CURSE, SSB], ids=["curse", "ssb"])
def test_a_save_with_no_edit_is_written_back_byte_for_byte(
        app, tmp_path, name, who, slot):
    """The control disk, through the same handlers, must move nothing.

    Both control runs were booted from a disk this path produced, so if it
    wrote anything of its own the control would be measuring that instead.
    """
    base = _copy(_specimen_disk(name), tmp_path)
    out = str(tmp_path / "control.D64")
    report = pursecheck.stage(base, out, who, {})
    assert report["save_said"] == "no changes"
    assert _payload(base) == _payload(out)

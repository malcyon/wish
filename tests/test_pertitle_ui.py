"""The editor and the tools, once they stopped assuming Pool of Radiance.

Two things were still wired to one title. The character sheet named a race from
Pool of Radiance's list whatever save was open -- so a Silver Blades human, code
6, read as HALF-ORC -- and it asked for item names without saying which title,
which put Curse's names at Pool of Radiance's `$6F00` and produced nothing at
all. Three tools globbed `POOL*.D64` besides.

Most of what is here needs no disks: the tables are data, and the dropdowns can
be filled without opening a file. The two that do need disks skip.
"""

from __future__ import annotations

import os
import pathlib
import shutil

import pytest

from automap import live
from editor.enums import class_bit_names, race_names, tables_for
from por import games

POOL = games.POOL_OF_RADIANCE
CURSE = games.CURSE_OF_THE_AZURE_BONDS
SSB = games.SECRET_OF_THE_SILVER_BLADES
KRYNN = games.CHAMPIONS_OF_KRYNN

#: A title whose race and class lists we do not have. `None` there means "we do
#: not know", and the editor must show the raw number rather than invent one.
UNTABLED = games.Game(key="untabled", title="Untabled", save_file=b"SAVEX",
                      save_load_address=0x4B00, save_size=0x1D00)


# --- the tables -------------------------------------------------------------

def test_the_race_table_follows_the_title():
    assert race_names(POOL)[7] == "HUMAN"
    assert race_names(POOL)[6] == "HALF-ORC"
    # Silver Blades drops half-orc and re-orders, moving human to 6.
    assert race_names(SSB)[6] == "HUMAN"
    assert 7 not in race_names(SSB)
    # Krynn is the 0-based one, and 0 is a race rather than "monster".
    assert race_names(KRYNN)[0] == "SILVANESTI ELF"


def test_curses_sixth_race_is_left_unnamed():
    """Curse's own label table points both 6 and 7 at HUMAN.

    Naming 6 "half-orc" would contradict what the game prints and naming it
    "human" would give two codes one name, so it gets neither.
    """
    assert race_names(CURSE)[7] == "HUMAN"
    assert 6 not in race_names(CURSE)


def test_a_title_with_no_tables_names_nothing():
    assert race_names(UNTABLED) == {}
    assert class_bit_names(UNTABLED) == {}
    assert tables_for(UNTABLED)["race"] == {}
    # The tables that are the same in every title are still there.
    assert tables_for(UNTABLED)["alignment"][0] == "LAWFUL GOOD"


def test_the_class_table_gains_the_later_titles_classes():
    assert class_bit_names(POOL)[8] == "fighter"
    assert 0x40 not in class_bit_names(POOL)
    assert class_bit_names(CURSE)[0x40] == "paladin"
    assert class_bit_names(CURSE)[0x80] == "ranger"
    assert class_bit_names(KRYNN)[0x10] == "knight"
    # The classic four still multi-class, and every one of their masks is
    # offered; the classes above them are single-class and get one entry each.
    assert class_bit_names(CURSE)[15] == "magic-user/cleric/thief/fighter"


# --- the dropdowns ----------------------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    """An editor with no file open. Never closed, so nothing can prompt."""
    from editor.window import EditorWindow
    return EditorWindow()


def _codes(combo) -> list[int]:
    return [combo.itemData(i) for i in range(combo.count())]


def _label(combo, code: int) -> str:
    return combo.itemText(combo.findData(code))


def test_the_race_dropdown_follows_the_open_game(window):
    race = window._widgets["race"]
    window._fill_combos(SSB)
    assert _codes(race) == [1, 2, 3, 4, 5, 6]
    assert "HUMAN" in _label(race, 6)


def test_changing_game_leaves_no_stale_race_behind(window):
    """The bug a refill without a clear would leave: Silver Blades' 6 is HUMAN
    and Pool of Radiance's is HALF-ORC, and only one of them can be on screen."""
    race = window._widgets["race"]
    window._fill_combos(SSB)
    window._fill_combos(POOL)
    assert _codes(race) == [0, 1, 2, 3, 4, 5, 6, 7, 8]
    assert "HALF-ORC" in _label(race, 6)
    assert _codes(race).count(6) == 1


def test_a_code_the_title_does_not_name_shows_its_number(window):
    """A Pool of Radiance half-orc carried into Curse, and Curse's own 6."""
    from editor.window import _select
    race = window._widgets["race"]
    window._fill_combos(CURSE)
    assert 6 not in _codes(race)
    _select(race, 6)
    assert race.currentData() == 6
    assert race.currentText().startswith("6")
    assert "not in the game's table" in race.currentText()


def test_a_title_we_have_no_race_list_for_offers_none(window):
    race = window._widgets["race"]
    window._fill_combos(UNTABLED)
    assert _codes(race) == []


def test_filling_the_combos_is_not_an_edit(window):
    """Clearing a combo emits `currentIndexChanged`, which must not mark a
    character dirty -- the refill happens on open, before a row is chosen."""
    window._fill_combos(CURSE)
    window._fill_combos(POOL)
    assert window.dirty == set()


# --- the disk globs ---------------------------------------------------------

def _touch(directory: pathlib.Path, *names: str) -> None:
    for name in names:
        (directory / name).write_bytes(b"")


#: Two patterns that both match `POOL1.D64`, which is what the real pair does
#: on a case-insensitive filesystem: `POOL*.D64` and `pool*.d64` are the same
#: set of files there, and a loop that does not dedupe opens each disk twice.
#: Linux keeps the two names apart, so the overlap has to be arranged.
BOTH_MATCH = ("POOL*.[dD]64", "POOL?.D64")


def test_the_map_reads_each_disk_once(tmp_path, monkeypatch):
    from automap import paths
    _touch(tmp_path, "POOL1.D64", "POOL2.D64")
    monkeypatch.setattr(paths, "disk_globs", lambda game=None: BOTH_MATCH)
    assert [p.name for p in live._disk_images(tmp_path)] == ["POOL1.D64",
                                                            "POOL2.D64"]


def test_genmaps_reads_each_disk_once(tmp_path, monkeypatch):
    from tools import genmaps
    _touch(tmp_path, "POOL1.D64", "POOL2.D64")
    monkeypatch.setattr(genmaps, "disk_globs", lambda game=None: BOTH_MATCH)
    found = [os.path.basename(d) for d in genmaps.game_disks(str(tmp_path))]
    assert found == ["POOL1.D64", "POOL2.D64"]


def test_geomap_reads_each_disk_once(tmp_path, monkeypatch):
    from tools import geomap
    _touch(tmp_path, "POOL1.D64", "POOL2.D64")
    monkeypatch.setattr(geomap, "disk_globs", lambda game=None: BOTH_MATCH)
    found = [os.path.basename(d) for d in geomap.game_disks(str(tmp_path))]
    assert found == ["POOL1.D64", "POOL2.D64"]


def test_a_lower_cased_disk_is_found_as_well(tmp_path):
    """The reason there are two patterns: a directory unpacked from an archive
    that lower-cased every name is still a set of game disks."""
    from tools import genmaps, geomap
    _touch(tmp_path, "POOL1.D64", "pool2.d64")
    assert len(live._disk_images(tmp_path)) == 2
    assert len(genmaps.game_disks(str(tmp_path))) == 2
    assert len(geomap.game_disks(str(tmp_path))) == 2


def test_the_map_globs_the_title_it_is_given(tmp_path):
    _touch(tmp_path, "POOL1.D64", "CURSE_A.D64")
    assert [p.name for p in live._disk_images(tmp_path)] == ["POOL1.D64"]
    assert [p.name for p in live._disk_images(tmp_path, CURSE)] == ["CURSE_A.D64"]


def test_no_tool_still_hard_codes_the_pool_glob():
    from tools import genmaps, geomap
    for module in (live, genmaps, geomap):
        source = pathlib.Path(module.__file__).read_text()
        assert "POOL*.D64" not in source, f"{module.__name__} globs one title"


# --- item names, which need the player's disks ------------------------------

def _copy_disks(source: pathlib.Path, pattern: str, into: pathlib.Path) -> None:
    for disk in sorted(source.glob(pattern)):
        shutil.copy(disk, into / disk.name)


def test_a_curse_save_gets_curse_item_names(app, tmp_path):
    """The `$9E00` table, not the `$6F00` one: without the title in hand the
    lookup lands on nothing and every item shows as its word index."""
    from por.items import load_item_names
    from tests.gamedata import curse_dir
    where = curse_dir()
    if where is None:
        pytest.skip("needs the Curse disks; set COAB_DISKS to where they are")
    _copy_disks(where, "CURSE*.[dD]64", tmp_path)
    save = next((p for p in sorted(tmp_path.glob("CURSE*.[dD]64"))
                 if _is_save(p, CURSE)), None)
    if save is None:
        pytest.skip("no Curse disk here carries a whole SAVEAZURE")

    from editor.window import EditorWindow
    window = EditorWindow(str(save))
    assert window.party.game is CURSE
    assert window.item_names, "no item names off a Curse disk"
    disk = window._find_game_disk()
    assert window.item_names == load_item_names(disk, CURSE)
    assert load_item_names(disk) == {}      # what the missing title cost


def test_a_silver_blades_save_shows_its_own_races(app, tmp_path):
    """Human is 6 here and half-orc does not exist, so the same byte that
    reads HALF-ORC in Pool of Radiance must read HUMAN."""
    ssb_dir = pytest.importorskip("tests.test_silverblades").ssb_dir
    where = ssb_dir()
    if where is None:
        pytest.skip("needs the Silver Blades disks; set SSB_DISKS")
    _copy_disks(where, "SILVER*.[dD]64", tmp_path)
    save = next((p for p in sorted(tmp_path.glob("SILVER*.[dD]64"))
                 if _is_save(p, SSB)), None)
    if save is None:
        pytest.skip("no Silver Blades disk here carries a SAVEDBASH")

    from editor.window import EditorWindow
    window = EditorWindow(str(save))
    assert window.party.game is SSB
    race = window._widgets["race"]
    assert "HUMAN" in _label(race, 6)
    window.ui.roster.selectRow(0)
    assert race.currentData() is not None
    # A ranger and a paladin are in the shipped party, and neither is a class
    # Pool of Radiance has.
    bits = {window.party.member(r).record.class_bits
            for r in range(window.model.rowCount())}
    assert bits & {0x40, 0x80}, "no later-title class in the shipped party"
    for code in sorted(bits & {0x40, 0x80}):
        assert _label(window._widgets["class_bits"], code)


def _is_save(path: pathlib.Path, game: games.Game) -> bool:
    """Does this disk carry a whole save of that title?

    Curse's side B has a truncated `SAVEAZURE` demo party under the same name,
    which `matches_payload` is exactly for.
    """
    from por.d64 import D64
    try:
        disk = D64.open(path)
        entry = disk.find(game.save_file)
        return entry is not None and game.matches_payload(disk.read_file(entry))
    except Exception:
        return False

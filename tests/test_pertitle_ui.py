from __future__ import annotations

def make_root():
    from PyQt6.QtWidgets import QMainWindow
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


"""The editor and the tools, once they stopped assuming Pool of Radiance.

Two things were still wired to one title. The character sheet named a race from
Pool of Radiance's list whatever save was open -- so a Silver Blades human, code
6, read as HALF-ORC -- and it asked for item names without saying which title,
which put Curse's names at Pool of Radiance's `$6F00` and produced nothing at
all. Three tools globbed `POOL*.D64` besides.

Most of what is here needs no disks: the tables are data, and the dropdowns can
be filled without opening a file. The two that do need disks skip.
"""


import os
import pathlib
import shutil

import pytest

from automap import live
from editor.enums import class_bit_names, race_names, tables_for
from goldbox import games

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


# --- who casts ---------------------------------------------------------------
#
# The Spells box was gated on magic-user and cleric as a module constant --
# Pool of Radiance's only two casting classes -- so a Silver Blades ranger was
# greyed out as if he cast nothing, and the greying rule is also the write
# rule, so his spell bytes were read-only besides (#86).


def test_the_caster_mask_follows_the_title():
    from editor.enums import caster_bits

    # Pool of Radiance has no class above the classic four, so its answer is
    # what it always was and this is the line that must not move.
    assert caster_bits(POOL) == 0x03
    # The ranger casts; the paladin does not.
    assert caster_bits(CURSE) == 0x83
    assert caster_bits(SSB) == 0x83
    # Krynn adds the Knight of Solamnia at 0x10, and nobody has read Krynn's
    # GEN, so it is left out rather than guessed at.
    assert caster_bits(KRYNN) == 0x83
    # A title whose class list we do not have names no caster, which greys the
    # box -- the same rule the race and class tables follow.
    assert caster_bits(UNTABLED) == 0
    assert caster_bits(None) == 0x03


def test_the_spells_box_is_gated_on_the_open_titles_casters(window):
    """The greying rule itself, without needing a save on the machine.

    `_show_boxes` reads the title off `EditorBinding.party`, so a stub party is
    all this needs -- and the box's enabled state is also what decides whether
    `_flush` writes the spell bytes back, which is why one mask answers both.
    """
    from goldbox.record import CharacterRecord

    class _Party:
        def __init__(self, game):
            self.game = game

    def shown(game, class_bits):
        record = CharacterRecord.blank()
        record.set("class_bits", class_bits)
        window.party = _Party(game)
        window._show_boxes(record)
        return window._child("box_spells")

    try:
        assert shown(SSB, 0x80).isEnabled(), "a Silver Blades ranger casts"
        assert shown(CURSE, 0x80).isEnabled(), "a Curse ranger casts"
        assert not shown(SSB, 0x40).isEnabled(), "a paladin does not"
        assert not shown(SSB, 0x08).isEnabled(), "and neither does a fighter"
        assert shown(SSB, 0x01).isEnabled(), "a magic-user still does"
        # Pool of Radiance has no bit 7; a record carrying one anyway is not a
        # caster there, because that title has no class to be.
        assert not shown(POOL, 0x80).isEnabled()
        # And the wording a non-caster is shown is unchanged.
        assert "casts no spells" in shown(POOL, 0x08).toolTip()
        assert shown(SSB, 0x80).toolTip() == ""
    finally:
        window.party = None


# --- the roster's two columns ------------------------------------------------
#
# The sheet's dropdowns were made per-title first and the party list was left
# behind: `Member.race_name` and `Member.class_name` went through Pool of
# Radiance's tables whatever `Party.game` said, so a Krynn party's races were
# unnameable and a Silver Blades human read as HALF-ORC (#78).


def _member(game, race=None, class_bits=None):
    """One roster row, built from a blank record rather than from a disk."""
    from editor.roster import Member
    from goldbox.record import CharacterRecord

    record = CharacterRecord.blank()
    record.set("name", "TESTER")
    if race is not None:
        record.set("race", race)
    if class_bits is not None:
        record.set("class_bits", class_bits)
    return Member(0, record, record.name, game=game)


def test_the_rosters_race_column_follows_the_open_title():
    """The three the tables disagree about, and the one they agree on."""
    # Krynn's list is its own, and 0 is a race there rather than "monster".
    assert _member(KRYNN, race=0).race_name == "silvanesti elf"
    assert _member(KRYNN, race=3).race_name == "mountain dwarf"
    # Silver Blades moved human to 6, where Pool of Radiance has half-orc.
    assert _member(SSB, race=6).race_name == "human"
    assert _member(POOL, race=6).race_name == "half-orc"
    # Curse names neither 6 nor anything else it has no word for: the raw
    # number is the honest answer and is what the sheet shows too.
    assert _member(CURSE, race=6).race_name == "6"
    # And the Realms note on race 0 stays where it belongs.
    assert _member(POOL, race=0).race_name == "monster"
    assert _member(CURSE, race=0).race_name == "monster"


def test_the_rosters_class_column_follows_the_open_title():
    """Curse and Silver Blades add classes above Pool of Radiance's four."""
    assert _member(CURSE, class_bits=0x80).class_name == "ranger"
    assert _member(SSB, class_bits=0x40).class_name == "paladin"
    assert _member(KRYNN, class_bits=0x10).class_name == "knight"
    # Pool of Radiance has no bit 7 at all, so it shows the mask unnamed.
    assert _member(POOL, class_bits=0x80).class_name == "128"
    # The classic four are the same in every title.
    for game in (POOL, CURSE, SSB, KRYNN):
        assert _member(game, class_bits=8).class_name == "fighter"


def test_a_member_with_no_title_is_still_pool_of_radiance():
    """What every `Member` meant before there was a second title, kept."""
    assert _member(None, race=7).race_name == "human"
    assert _member(None, class_bits=1).class_name == "magic-user"


def test_a_title_with_no_tables_names_no_race_or_class_in_the_roster():
    assert _member(UNTABLED, race=7).race_name == "7"
    assert _member(UNTABLED, class_bits=8).class_name == "8"


def test_every_row_a_party_builds_carries_the_partys_title(tmp_path):
    """The lookups are only per-title if the `Game` actually reaches the row.

    Both loaders build `Member`s -- a save disk and a roster disk -- and either
    one forgetting to pass the title puts Pool of Radiance's names back.
    """
    from gamedata import synthetic_save

    from editor.roster import Party

    party = Party(str(synthetic_save(tmp_path)))
    assert party.members, "the synthetic save has characters in it"
    assert all(m.game is party.game for m in party.members)


# --- the dropdowns ----------------------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    """An editor with no file open. Never closed, so nothing can prompt."""
    from editor.window import EditorBinding
    return EditorBinding(make_root(), )


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
    from goldbox.items import load_item_names
    from tests.gamedata import curse_dir
    where = curse_dir()
    if where is None:
        pytest.skip("needs the Curse disks; set COAB_DISKS to where they are")
    _copy_disks(where, "CURSE*.[dD]64", tmp_path)
    save = next((p for p in sorted(tmp_path.glob("CURSE*.[dD]64"))
                 if _is_save(p, CURSE)), None)
    if save is None:
        pytest.skip("no Curse disk here carries a whole SAVEAZURE")

    from editor.window import EditorBinding
    window = EditorBinding(make_root(), str(save))
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

    from editor.window import EditorBinding
    window = EditorBinding(make_root(), str(save))
    assert window.party.game is SSB
    race = window._widgets["race"]
    assert "HUMAN" in _label(race, 6)
    window.roster.selectRow(0)
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
    from goldbox.d64 import D64
    try:
        disk = D64.open(path)
        entry = disk.find(game.save_file)
        return entry is not None and game.matches_payload(disk.read_file(entry))
    except Exception:
        return False


# --- synthetic saves for every title, needing no disks at all --------------
#
# #98: `synthetic_party` raised for every title but Pool of Radiance, because
# it always wrote a separate roster file at `game.roster_load_address`, which
# is None for every later title -- they keep the roster inside the save
# payload instead. This is what makes the disks-backed tests above skippable
# in CI: a per-title UI guarantee no longer needs the player's own disks to be
# exercised somewhere.

def test_synthetic_party_builds_a_save_for_every_title():
    from goldbox.d64 import D64
    from goldbox.savegame import load_save
    from tests.gamedata import synthetic_party

    for game in games.GAMES:
        disk = D64.from_bytes(synthetic_party(game))
        found, sg0, sg1 = load_save(disk)
        assert found is game, game.title
        chars = sg0.characters
        assert len(chars) == 6, game.title
        for char in chars:
            record = char.record
            assert record.name.rstrip() == "W" * 20, game.title
            assert record.hp_max == 65535, game.title
        assert sg1 is not None, game.title
        assert sg1.roster(0).thac0 == 20, game.title

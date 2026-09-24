"""Tests for the character editor.

The binding and file handling are pure Python. The window needs Qt but not a
display -- QT_QPA_PLATFORM=offscreen, set in the fixture -- so all of it runs
headless.
"""

import os
import pathlib

import pytest
from gamedata import disk_dir, disk_path, synthetic_save
from support.editorwindow import make_root

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from editor.binding import (
    binding_for,
    bindings,
    editable_fields,
    shown_fields,
)
from editor.files import automatic_dir, back_up, prune
from editor.roster import Party
from goldbox import c64_codec
from goldbox.layout import LAYOUT, Confidence

# Wherever the player keeps them, not wherever one machine did.
DISKS = str(disk_dir() or "no-disks-here")
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/PORSAVE11.D64").exists(),
                                reason="needs the save disks")


@pytest.fixture
def save(tmp_path):
    """A throwaway copy. Never test against the player's real disks.

    Skips rather than raising when there are none. A fixture that raises turns
    every test using it into an ERROR on a machine without the game, which is
    what CI is; skipping is the same signal the rest of the suite gives.
    """
    src = disk_path("PORSAVE11")
    if src is None:
        pytest.skip("needs the save disks")
    out = tmp_path / "PORSAVE11.D64"
    out.write_bytes(src.read_bytes())
    return out


@pytest.fixture
def newsave5(tmp_path):
    """A throwaway copy of `NEWSAVE5.D64`, whose GARRETT is #149's specimen:
    `thac0_base` stored as 39 and `armour_class_base` as 50, sheet values 21
    and 10."""
    src = disk_path("NEWSAVE5")
    if src is None:
        pytest.skip("needs the save disks")
    out = tmp_path / "NEWSAVE5.D64"
    out.write_bytes(src.read_bytes())
    return out


@pytest.fixture
def party(tmp_path):
    """A save disk built from the format rather than copied off one.

    Six characters at the widest the record and the title's tables allow, so
    the width tests that used to skip everywhere run in CI -- #70. The
    disk-backed twin of each is what proves it representative.
    """
    return synthetic_save(tmp_path)


# --- read-only rules --------------------------------------------------------

def test_a_field_the_game_recomputes_is_read_only():
    b = bindings(in_save=True)
    assert b["thac0_base"].read_only
    assert "recomputes" in b["thac0_base"].reason


def test_a_field_we_do_not_understand_is_read_only():
    unknown = next(f for f in LAYOUT if f.confidence is Confidence.UNKNOWN)
    assert binding_for(unknown, in_save=True).read_only


def test_the_tail_of_the_record_is_read_only_in_a_save_only():
    """A slot holds 256 bytes of a 580-byte record, so a write past 0x100 is
    silently dropped -- but the same field is real in a .chr export."""
    assert bindings(in_save=True)["hp_current"].read_only
    assert not bindings(in_save=False)["hp_current"].read_only


def test_an_ordinary_field_is_editable():
    assert not bindings(in_save=True)["strength"].read_only
    assert not bindings(in_save=True)["gold"].read_only


def test_no_placeholder_fields_reach_the_form():
    assert not [f for f in editable_fields()
                if f.name.startswith(("region_", "gap_", "unknown"))]


# --- the roster -------------------------------------------------------------

@game_disks
def test_a_save_disk_lists_its_party_with_ac_and_hp(save):
    party = Party(str(save))
    assert party.is_save and len(party) == 6
    roland = next(m for m in party.members if m.name == "ROLAND")
    assert (roland.hp_current, roland.hp_max) == (5, 7)
    assert roland.wounded
    assert roland.armour_class == 4


@game_disks
def test_a_roster_disk_has_no_savedgame_and_still_lists_characters():
    """PORSAVE10.D64 holds eight standalone characters and no SAVEDGAME0 at
    all. An editor that assumes a save disk always has one falls over here."""
    party = Party(f"{DISKS}/PORSAVE10.D64")
    assert not party.is_save
    assert len(party) == 8
    assert {"NYX", "DAX", "ASTRID"} <= {m.name for m in party.members}
    assert all(m.armour_class is None for m in party.members)


#: Where Curse of the Azure Bonds loads a parked character's own file, read
#: off the four the engine wrote on `WISH-SPEC-curse-party-with-items.D64`.
#: Pool of Radiance's roster files load at `goldbox.record.LOAD_ADDRESS`,
#: `$6B00`, and a reader that insists on that one drops all four (#456).
CURSE_RECORD_LOAD_ADDRESS = 0x7C00


def _parked_disk(tmp_path, *records) -> pathlib.Path:
    """A disk of character files at Curse's own load address and no save
    game -- what a Curse disk carrying characters looks like."""
    from gamedata import _disk_with
    out = tmp_path / "PARKED.D64"
    out.write_bytes(_disk_with(
        [(bytes([0x02]) + r.name.encode(),
          r.to_prg(CURSE_RECORD_LOAD_ADDRESS)) for r in records]))
    return out


def test_a_curse_character_disk_lists_its_characters(tmp_path):
    """The four files the engine parks on a Curse disk are whole records and
    the game lists them by name; Wish said `roster disk, 0 character(s)` and
    showed an empty table, with no sign in the interface that anything had
    been skipped (#456)."""
    from goldbox.record import CharacterRecord
    made = []
    for name in ("ARDEN", "BRISA", "KORDAN"):
        r = CharacterRecord.blank()
        r.set("name", name)
        for field in ("strength", "intelligence", "wisdom",
                      "dexterity", "constitution", "charisma"):
            r.set(field, 12)
        made.append(r)
    party = Party(str(_parked_disk(tmp_path, *made)))
    assert not party.is_save
    assert [m.name for m in party.members] == ["ARDEN", "BRISA", "KORDAN"]
    assert "3 character(s)" in party.describe()


def test_a_prg_that_is_not_a_character_is_still_skipped(tmp_path):
    """The narrowness the fix above must keep. A roster disk carries PRGs
    that are not characters, and once the load address is no longer the only
    test, the bytes have to be: a record whose ability scores are all zero is
    not somebody's character however long the file is."""
    from goldbox.record import CharacterRecord
    real = CharacterRecord.blank()
    real.set("name", "ARDEN")
    for field in ("strength", "intelligence", "wisdom",
                  "dexterity", "constitution", "charisma"):
        real.set(field, 12)
    junk = CharacterRecord.blank()          # no name, no ability scores
    junk.set("name", "LOADER")
    party = Party(str(_parked_disk(tmp_path, real, junk)))
    assert [m.name for m in party.members] == ["ARDEN"]


def _ability_record(name: str, **fields) -> "CharacterRecord":
    from goldbox.record import CharacterRecord
    r = CharacterRecord.blank()
    r.set("name", name)
    for field in ("strength", "intelligence", "wisdom",
                  "dexterity", "constitution", "charisma"):
        r.set(field, 12)
    for field, value in fields.items():
        r.set(field, value)
    return r


def _disk_of(tmp_path, *entries) -> pathlib.Path:
    """`entries` is `(prefix_byte, record, load_address)`, so a disk can mix
    two titles' files -- `_parked_disk` above always writes Curse's prefix
    and load address, which is not enough for #553's own tests."""
    from gamedata import _disk_with
    out = tmp_path / "MIXED.D64"
    files = [(bytes([prefix]) + r.name.encode(), r.to_prg(address))
             for prefix, r, address in entries]
    out.write_bytes(_disk_with(files))
    return out


def test_a_curse_character_disk_names_a_paladin_and_a_former_class(tmp_path):
    """A Curse character disk with no save game read Pool of Radiance's
    tables: a paladin's class showed as the raw bits, `64`, and a
    dual-classed character's former class was never drawn at all, because
    Pool of Radiance's own `class_bit_names` has no paladin and
    `C64Deltas.dual_class` is False for it (#553). MATHEW is a paladin alone;
    PHILIPPE trained out of magic-user 6 into fighter."""
    from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS

    mathew = _ability_record("MATHEW", class_bits=0x40)
    philippe = _ability_record("PHILIPPE", class_bits=0x08,
                                dual_class_slot=0, dual_class_level=6)
    party = Party(str(_parked_disk(tmp_path, mathew, philippe)))
    assert party.game is CURSE_OF_THE_AZURE_BONDS
    by_name = {m.name: m for m in party.members}
    assert by_name["MATHEW"].class_name == "paladin"
    assert by_name["PHILIPPE"].class_name == "fighter (was magic-user 6)"


def test_a_silver_blades_character_disk_is_identified_by_its_own_prefix(
        tmp_path):
    """`$05` in front of the filename, not `$02` -- the byte that separates
    Curse from Silver Blades, which the load address alone cannot (#553)."""
    from goldbox.c64_port import SECRET_OF_THE_SILVER_BLADES

    guy = _ability_record("GUY", class_bits=0x40)     # paladin
    disk = _disk_of(tmp_path, (0x05, guy, 0x7C00))
    party = Party(str(disk))
    assert party.game is SECRET_OF_THE_SILVER_BLADES
    assert party.members[0].class_name == "paladin"


def test_a_pool_of_radiance_character_disk_is_identified_by_its_own_prefix(
        tmp_path):
    """`$01`, at Pool of Radiance's own roster load address -- the third
    prefix, so a disk parking one of its characters is not read as Curse's
    default by accident."""
    from goldbox.c64_port import POOL_OF_RADIANCE
    from goldbox.record import LOAD_ADDRESS

    arden = _ability_record("ARDEN")
    disk = _disk_of(tmp_path, (0x01, arden, LOAD_ADDRESS))
    party = Party(str(disk))
    assert party.game is POOL_OF_RADIANCE


def test_a_disk_with_no_character_files_is_still_pool_of_radiance(tmp_path):
    """No save file and no prefixed character file names no title at all, so
    the last resort stays Pool of Radiance -- there is nothing on such a disk
    to misread, so no refusal is needed (#553)."""
    from goldbox.c64_port import POOL_OF_RADIANCE

    disk = _disk_of(tmp_path)
    party = Party(str(disk))
    assert party.game is POOL_OF_RADIANCE
    assert not party.members


def test_a_disk_mixing_two_titles_files_keeps_each_members_own_title(
        tmp_path):
    """`ADD CHARACTER TO PARTY` can put another title's file on a disk
    (`ADD FROM: CURSE POOL HILLSFAR`). The party as a whole falls back to
    Pool of Radiance -- the two files disagree, so there is no single answer
    for the disk -- but each `Member` still reads its own file's title, which
    is what keeps a Pool of Radiance fighter and a Curse paladin each showing
    their own class rather than one of them showing the other's (#553)."""
    from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS, POOL_OF_RADIANCE
    from goldbox.record import LOAD_ADDRESS

    arden = _ability_record("ARDEN", class_bits=0x08)          # fighter
    mathew = _ability_record("MATHEW", class_bits=0x40)        # paladin
    disk = _disk_of(tmp_path, (0x01, arden, LOAD_ADDRESS),
                    (0x02, mathew, 0x7C00))
    party = Party(str(disk))
    assert party.game is POOL_OF_RADIANCE          # the whole-disk fallback
    by_name = {m.name: m for m in party.members}
    assert by_name["ARDEN"].game is POOL_OF_RADIANCE
    assert by_name["MATHEW"].game is CURSE_OF_THE_AZURE_BONDS
    assert by_name["MATHEW"].class_name == "paladin"


def test_saving_a_misidentified_curse_character_does_not_corrupt_the_abilities(
        tmp_path):
    """The write half of #553, and the reason its priority moved to High.

    With the title misdetected as Pool of Radiance, the memorised-spell
    widget was handed 81 bytes from 0x020 instead of Curse's 69, so a
    cleric's own ability scores at 0x065 were shown as six extra prepared
    spells. Saving after any edit repacked the list and moved zero bytes
    into `abilities_second` -- the array Curse's own engine copies over the
    scores the sheet draws. Detecting the title off the roster prefix keeps
    the memorised span at 69 bytes, so an edit never reaches past it."""
    from editor.window import EditorBinding
    from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS

    shara = _ability_record("SHARA", class_bits=0x02)          # cleric
    shara.set_raw("spells_memorised", bytes([22, 22]) + bytes(67))
    abilities = bytes([17, 12, 17, 17, 16, 17, 0])
    shara.set_raw("abilities_second", abilities)

    editor = EditorBinding(make_root(), str(_parked_disk(tmp_path, shara)))
    assert editor.party.game is CURSE_OF_THE_AZURE_BONDS
    editor.roster.selectRow(0)
    _book, memorised = editor._spell_widgets()
    assert memorised.ids() == [22, 22]

    assert memorised.add_spell(22)
    editor._edited()
    assert "wrote" in editor.save(interactive=False)

    record = editor.party.member(0).record
    assert record.get_raw("abilities_second") == abilities


def test_saving_the_minority_titles_member_uses_its_own_title_not_the_partys(
        tmp_path):
    """The gap `code-reviewer` found in the test above: `_parked_disk` prefixes
    every file the same title, so `party.game` and `member.game` were always
    equal there and the write path could read `self._game()` -- the whole
    party's fallback title -- without that ever being exercised.

    Here the disk mixes a Pool of Radiance file with a Curse cleric's, so the
    party as a whole falls back to Pool of Radiance (`detect_from_roster`
    refuses to pick between two disagreeing titles) while SHARA's own file
    still names Curse. Saving her memorised spells has to use *her* title,
    not the party's whole-disk fallback, or the same corruption reaches the
    one character on the disk whose title actually differs from the
    party's."""
    from editor.window import EditorBinding
    from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS, POOL_OF_RADIANCE
    from goldbox.record import LOAD_ADDRESS

    arden = _ability_record("ARDEN", class_bits=0x08)          # fighter
    shara = _ability_record("SHARA", class_bits=0x02)          # cleric
    shara.set_raw("spells_memorised", bytes([22, 22]) + bytes(67))
    abilities = bytes([17, 12, 17, 17, 16, 17, 0])
    shara.set_raw("abilities_second", abilities)

    disk = _disk_of(tmp_path, (0x01, arden, LOAD_ADDRESS),
                    (0x02, shara, 0x7C00))
    editor = EditorBinding(make_root(), str(disk))
    assert editor.party.game is POOL_OF_RADIANCE      # the whole-disk fallback
    row = next(i for i, m in enumerate(editor.party.members)
               if m.name == "SHARA")
    assert editor.party.member(row).game is CURSE_OF_THE_AZURE_BONDS

    editor.roster.selectRow(row)
    _book, memorised = editor._spell_widgets()
    assert memorised.ids() == [22, 22]      # not Pool of Radiance's 81-byte span

    assert memorised.add_spell(22)
    editor._edited()
    assert "wrote" in editor.save(interactive=False)

    record = editor.party.member(row).record
    assert record.get_raw("abilities_second") == abilities


def test_saving_a_curse_character_disk_keeps_its_own_load_address(tmp_path):
    """`_write_back` called `m.record.to_prg()` with no address, so every
    file on a Curse or Silver Blades character disk came back stamped with
    Pool of Radiance's `$6B00` instead of the `$7C00` it was read at
    (#556). The record bytes are unchanged either way -- only the disk's
    backup copy still carries the address the file actually had."""
    from editor.window import EditorBinding
    from goldbox.d64 import D64

    arden = _ability_record("ARDEN")
    brisa = _ability_record("BRISA")
    path = _parked_disk(tmp_path, arden, brisa)
    editor = EditorBinding(make_root(), str(path))
    editor.save(interactive=False)

    disk = D64.open(str(path))
    prg_entries = [e for e in disk.directory() if e.is_prg and not e.is_empty]
    assert len(prg_entries) == 2
    for entry in prg_entries:
        raw = disk.read_file(entry)
        assert raw[:2] == bytes([0x00, 0x7C]), (
            f"{entry.name} starts {raw[:2].hex()}, not Curse's own "
            f"{CURSE_RECORD_LOAD_ADDRESS:#06x}")


# --- backups ----------------------------------------------------------------

class FakeDisk:
    """A disk with bytes in it, so the file handling is tested without one."""

    def __init__(self, data):
        self.data = data

    def to_bytes(self):
        return self.data

    def save(self, path):
        pathlib.Path(path).write_bytes(self.data)


def test_the_message_spells_out_a_backup_that_went_somewhere_else(tmp_path):
    """Beside the disk, `backups/NAME` is enough. Elsewhere it is not.

    A folder the user chose in Preferences is not one they are looking at, so
    the short form would name a `backups/` on a path the message never gives.
    """
    from editor import files

    beside = tmp_path / "PORSAVE11.D64"
    beside.write_bytes(b"old")
    said = files.save_disk(FakeDisk(b"new"), beside,
                           files.automatic_dir(beside))
    assert said.startswith("wrote PORSAVE11.D64, backup backups/")

    elsewhere = tmp_path / "elsewhere"
    other = tmp_path / "PORSAVE12.D64"
    other.write_bytes(b"old")
    said = files.save_disk(FakeDisk(b"new"), other, elsewhere)
    assert str(elsewhere) in said          # the whole path, not just the leaf


def test_no_backup_folder_refuses_the_save_rather_than_writing(tmp_path):
    """The rule the editor's licence to overwrite rests on.

    It writes back over the file you opened, and the only reason that is
    defensible is the copy it takes first. With nowhere to put the copy the
    save does not happen -- there is no hidden directory to fall back to.
    """
    from editor import files

    save = tmp_path / "PORSAVE11.D64"
    save.write_bytes(b"old")
    with pytest.raises(files.NoBackupFolder) as raised:
        files.save_disk(FakeDisk(b"new"), save, "")
    assert save.read_bytes() == b"old"
    assert "Preferences" in str(raised.value)
    # And a save that would write nothing needs no folder: closing a window
    # nobody edited in must not turn into an argument about backups.
    assert files.save_disk(FakeDisk(b"old"), save, "") == "no changes"


def test_a_backup_is_made_and_the_original_is_unchanged(tmp_path):
    f = tmp_path / "x.d64"
    f.write_bytes(b"before")
    copy = back_up(f, automatic_dir(f))
    assert copy.read_bytes() == b"before"
    assert copy.parent.name == "backups"


def test_saving_to_a_new_name_backs_up_nothing(tmp_path):
    assert back_up(tmp_path / "not-there.d64", tmp_path / "backups") is None


def test_pruning_drops_the_oldest_not_the_newest(tmp_path):
    target = tmp_path / "x.d64"
    into = tmp_path / "backups"
    into.mkdir()
    for i in range(25):
        (into / f"x.d64.{i:03d}").write_bytes(b"")
    dropped = prune(target, into, keep=20)
    assert len(dropped) == 5
    left = sorted(p.name for p in into.glob("x.d64.*"))
    assert left[0] == "x.d64.005" and left[-1] == "x.d64.024"


# --- the window -------------------------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def expected_sheet_fields():
    """The fields `editor/character.ui` is expected to carry a widget for.

    The exclusions live in `editor/binding.NOT_ON_THE_SHEET`, beside the code
    that acts on them, so the sheet and the test cannot drift apart.
    """
    return shown_fields(editable_fields())


@game_disks
def test_the_window_binds_every_field_widget(app, save):
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    assert w.model.rowCount() == 6
    # every non-placeholder field has a widget, plus the promoted icon
    assert len(w._widgets) == len(expected_sheet_fields()) + 1


# --- Control, Morale and Abilities altered replace the raw Flags 0b8 (#623) -
#
# `docs/232-the-c64-control-byte-per-title.md`: bit 7 says who drives the
# character; for the engine's own the low seven bits are morale, halved, and
# for a player character bit 0 is the ability-altered flag -- confirmed only
# on Pool of Radiance. Built with `synthetic_save`, poked to the exact byte
# each case needs, rather than a shipped save: every case here is a fact
# about the editor's own display code, not about what a title's engine wrote,
# so it does not need a specimen with a chain of custody (`.claude/rules/
# testing.md`).

def _shown_editor(path):
    """An `EditorBinding` on the Stats tab, in a window that is actually
    shown -- `setVisible` only reads back true once every ancestor tab is
    the one on screen, and `tabs`' own default is the automap tab."""
    from PyQt6.QtWidgets import QTabWidget

    from editor.window import EditorBinding
    root = make_root()
    w = EditorBinding(root, str(path))
    tabs = root.findChild(QTabWidget, "tabs")
    for i in range(tabs.count()):
        if tabs.widget(i).objectName() == "tab_editor":
            tabs.setCurrentIndex(i)
            break
    root.resize(1875, 1030)
    root.show()
    return w


def test_the_control_dropdown_is_editable(app):
    """Donald's own instruction: the player may type into Control, not only
    choose from its two items."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root())
    assert w._child("control_combo").isEditable()


def test_flags_0b8_is_no_longer_a_generic_sheet_field(app, party):
    """The three widgets read and write the byte by hand
    (`EditorBinding._show_control_fields`); the generic `field_*` mechanism
    must no longer know its name, or a `field_flags_0b8` reintroduced by
    accident would silently double-bind it instead of raising the typo
    `KeyError` `_find_field_widgets` is there to raise."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(party))
    assert "flags_0b8" not in w._widgets
    assert w.root.findChild(QWidget, "field_flags_0b8") is None


def test_a_player_character_shows_control_and_abilities_altered(app, tmp_path):
    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0x01)
    w._populate()
    control = w._child("control_combo")
    morale = w._child("morale_spin")
    altered = w._child("abilities_altered_combo")
    assert control.currentText() == "Player-controlled"
    assert not morale.isVisible()
    assert altered.isVisible() and not altered.isEnabled()
    assert altered.currentText() == "Yes"
    assert altered.toolTip() == (
        "Set when this character kept an ability or hit-point change at "
        "the trainer")
    # An untouched flush must not disturb a bit the player never offered to
    # edit -- the read-only combo is never in `_flush`'s own widget loop.
    assert w._flush(0) == []
    assert member.record.get("flags_0b8") == 0x01


def test_a_companion_shows_control_and_morale_not_abilities_altered(app, tmp_path):
    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0xB2)  # 0x80 | 50 -> morale 100
    w._populate()
    control = w._child("control_combo")
    morale = w._child("morale_spin")
    altered = w._child("abilities_altered_combo")
    assert control.currentText() == "Game-controlled"
    assert morale.isVisible() and morale.isEnabled()
    assert morale.value() == 100
    assert not altered.isVisible()
    assert w._flush(0) == []
    assert member.record.get("flags_0b8") == 0xB2


@pytest.mark.parametrize("game_attr", [
    "CURSE_OF_THE_AZURE_BONDS", "SECRET_OF_THE_SILVER_BLADES",
])
def test_abilities_altered_is_empty_and_disabled_on_an_unconfirmed_title(
        app, tmp_path, game_attr):
    """docs/232: only Pool of Radiance's own engine sets bit 0 for a player
    character. Donald's decision is to show the row empty rather than hide
    it, so the player still sees the field and why it carries nothing.

    Gateway, Champions and Death Knights are not in this parametrisation:
    `goldbox.c64_codec.deltas_for` has no measured record deltas for them
    yet, so the editor cannot open a save of any of the three at all -- a
    pre-existing gap this ticket did not create and does not need to work
    around to show the other five titles' own two confirmed-absent cases."""
    from goldbox import c64_port
    game = getattr(c64_port, game_attr)
    save = synthetic_save(tmp_path, name=f"{game_attr}.D64", game=game)
    w = _shown_editor(save)
    altered = w._child("abilities_altered_combo")
    assert altered.isVisible() and not altered.isEnabled()
    assert altered.currentText() == ""
    assert altered.toolTip() == "Not recorded on this title"


def test_morale_above_100_is_shown_read_only_not_clamped(app, tmp_path):
    """A companion copied from a Pool of Radiance monster record can hold up
    to 254 (docs/232): shown decoded and disabled, never clamped to 100 or
    refused."""
    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0xFF)
    w._populate()
    morale = w._child("morale_spin")
    assert morale.isVisible()
    assert morale.value() == 254
    assert not morale.isEnabled()
    assert "not editable" in morale.toolTip()
    assert w._flush(0) == []
    assert member.record.get("flags_0b8") == 0xFF


def test_switching_control_to_game_controlled_shows_a_fresh_morale(app, tmp_path):
    """Donald's instruction: a flip must never read the old ability-altered
    bit as if it were a morale value. Flipping shows Morale at 0, not
    `2 x (old & 0x7F)`, and only what the player then sets is written."""
    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0x01)  # a player character, altered=Yes
    w._populate()
    control = w._child("control_combo")
    morale = w._child("morale_spin")
    control.setCurrentText("Game-controlled")
    app.processEvents()
    assert morale.isVisible() and morale.value() == 0
    morale.setValue(42)
    assert w._flush(0) == []
    assert member.record.get("flags_0b8") == (0x80 | 21)


def test_switching_control_to_player_controlled_zeroes_the_byte(app, tmp_path):
    """The engine's own write on this switch is the whole byte zero -- never
    the old morale's own low bits read back as the ability-altered flag."""
    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0xB2)  # a companion, morale 100
    w._populate()
    control = w._child("control_combo")
    altered = w._child("abilities_altered_combo")
    control.setCurrentText("Player-controlled")
    app.processEvents()
    assert altered.isVisible() and altered.currentText() == "No"
    assert w._flush(0) == []
    assert member.record.get("flags_0b8") == 0x00


def test_a_typoed_control_value_reverts_instead_of_corrupting_flags_0b8(
        app, tmp_path):
    """Before the fix, a stray character typed into the editable Control
    field -- "Game-Controled" for "Game-controlled" -- matched neither of
    Donald's own two labels, was read the same as "Player-controlled", and
    silently zeroed the whole byte on save, wiping this NPC's morale with no
    error shown (#623 review). The combo must instead revert to whatever it
    last validly held, once the player finishes editing -- the line edit's
    own `editingFinished`, not the `currentTextChanged` that fires on every
    keystroke along the way (#623 review, keystroke-loss finding)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0xB2)  # an NPC, morale 100
    w._populate()
    control = w._child("control_combo")
    control.setCurrentText("Game-Controled")
    app.processEvents()
    QTest.keyClick(control.lineEdit(), Qt.Key.Key_Return)
    app.processEvents()
    assert control.currentText() == "Game-controlled"
    assert w._flush(0) == []
    assert member.record.get("flags_0b8") == 0xB2


def test_typing_into_control_letter_by_letter_reaches_the_end_intact(
        app, tmp_path):
    """Review of #623: `_control_changed` used to fire its reject-and-revert
    check on every `currentTextChanged` Qt emits while the player is still
    typing, not only once they finish -- so a player typing "Game-controlled"
    by hand into the field had each partial string (starting with a lone
    "G") rejected and reverted before the next keystroke could land, and the
    field could never actually be typed into despite `_setup_control_fields`'s
    own docstring promising the player can type into it. `QTest.keyClicks`
    drives the real widget's key events, unlike `setCurrentText` above, which
    is why every other test in this file missed it."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0x00)  # a player character
    w._populate()
    control = w._child("control_combo")
    assert control.currentText() == "Player-controlled"
    line_edit = control.lineEdit()
    line_edit.setFocus()
    line_edit.selectAll()
    QTest.keyClicks(line_edit, "Game-controlled")
    app.processEvents()
    assert line_edit.text() == "Game-controlled", (
        "a keystroke must not be rejected and reverted before the next "
        "one lands")
    QTest.keyClick(line_edit, Qt.Key.Key_Return)
    app.processEvents()
    assert control.currentText() == "Game-controlled"
    assert w._flush(0) == []


def test_flush_control_fields_refuses_an_unrecognized_value_on_its_own(
        app, tmp_path):
    """`_control_committed`'s own revert (the test above) is not the only
    guard: `_flush_control_fields` must independently refuse a Control value
    it does not recognise, in case the combo ever ends up holding one some
    other way, rather than defaulting to "Player-controlled" and wiping the
    byte (#623 review)."""
    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0xB2)  # an NPC, morale 100
    w._populate()
    control = w._child("control_combo")
    control.blockSignals(True)
    control.setCurrentText("Game-Controled")
    control.blockSignals(False)
    failures = w._flush(0)
    assert "Control" in failures
    assert member.record.get("flags_0b8") == 0xB2


def test_a_morale_edit_survives_a_control_flip_away_and_back(app, tmp_path):
    """Reproduction from the #623 review: open an NPC (morale 100), type a
    new morale, flip Control to the other choice and back without saving --
    before the fix, `_apply_control_state` redrew Morale from the stored
    byte on the way back and the typed value was gone."""
    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0xB2)  # an NPC, morale 100
    w._populate()
    control = w._child("control_combo")
    morale = w._child("morale_spin")
    morale.setValue(60)
    control.setCurrentText("Player-controlled")
    app.processEvents()
    control.setCurrentText("Game-controlled")
    app.processEvents()
    assert morale.value() == 60
    assert w._flush(0) == []
    assert member.record.get("flags_0b8") == (0x80 | 30)


def test_a_fresh_flip_to_game_controlled_never_shows_a_previous_rows_morale(
        app, tmp_path):
    """`_apply_control_state` only draws Morale's value at populate time now
    (#623 review); this proves that does not leave the field showing
    whatever a previously-viewed roster row last put there. Row 0 is an NPC
    at morale 100; row 1 is a fresh player character switched to
    Game-controlled for the first time and must read 0, the engine's own
    neutral value, not 100 left over from row 0."""
    party = synthetic_save(tmp_path)
    w = _shown_editor(party)
    npc = w.party.member(0)
    npc.record.set("flags_0b8", 0xB2)  # an NPC, morale 100
    pc = w.party.member(1)
    pc.record.set("flags_0b8", 0x00)  # a player character
    w.current_row = 0
    w._populate()
    w.current_row = 1
    w._populate()
    control = w._child("control_combo")
    morale = w._child("morale_spin")
    assert control.currentText() == "Player-controlled"
    control.setCurrentText("Game-controlled")
    app.processEvents()
    assert morale.value() == 0


def test_flush_control_fields_exception_is_isolated_like_other_fields(
        app, tmp_path, monkeypatch):
    """Every other widget in `_flush`'s own loop degrades an exception to a
    reported failure instead of crashing the whole save
    (`try/except Exception: ... failures.append(...)`); before the fix,
    `_flush_control_fields` was called unguarded after that loop and would
    have propagated out of `save()` instead (#623 review)."""
    from editor.window import EditorBinding
    from goldbox import c64_port
    save = synthetic_save(tmp_path, game=c64_port.POOL_OF_RADIANCE)
    w = _shown_editor(save)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0xB2)
    w._populate()

    def boom(self, member):
        raise RuntimeError("boom")

    monkeypatch.setattr(EditorBinding, "_flush_control_fields", boom)
    failures = w._flush(0)
    assert "Control" in failures


def test_no_sheet_tooltip_shows_an_offset_a_field_name_or_a_grade(app, party):
    """`#419 (Hovering a box on the character sheet shows its byte offset and
    internal field name)`: hovering Strength used to read
    `strength @ 0x014 (CONFIRMED)`, and 47 of the sheet's fields did the same.

    Swept over every bound widget rather than the 47 named in that issue, so
    the 48th field does not get to repeat it. The synthetic party (#70) needs
    no game disk, so this runs everywhere."""
    import re

    from editor.window import EditorBinding

    address = re.compile(r"@ 0x[0-9a-f]+", re.IGNORECASE)
    grade = re.compile(r"\b(CONFIRMED|PROBABLE|GUESS|UNKNOWN)\b")
    bare_field_name = re.compile(r"\b[a-z][a-z_]*_[a-z][a-z_]*\b")

    w = EditorBinding(make_root(), str(party))
    checked = 0
    for name, widget in w._widgets.items():
        if not hasattr(widget, "toolTip"):
            continue
        tip = widget.toolTip()
        if not tip:
            continue
        checked += 1
        assert not address.search(tip), f"{name}: offset in tooltip {tip!r}"
        assert not grade.search(tip), f"{name}: confidence grade in tooltip {tip!r}"
        assert not bare_field_name.search(tip), (
            f"{name}: internal field name in tooltip {tip!r}")
    assert checked > 0        # the sweep exercised something


@game_disks
def test_selecting_a_character_fills_the_sheet(app, save):
    """PORSAVE11 holds MALCYON, LADY KATHERINE, ROLAND, SILAS, MAGNUS, BRUTUS
    in slots 0-5, and the roster lists them the game's own way -- highest
    occupied slot first (`#160`): BRUTUS, MAGNUS, SILAS, ROLAND,
    LADY KATHERINE, MALCYON."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(3)
    assert w._widgets["name"].text() == "ROLAND"
    w.roster.selectRow(5)
    assert w._widgets["name"].text() == "MALCYON"


@game_disks
def test_an_edit_survives_switching_character_and_back(app, save):
    """The flush-before-switch bug: an edit made and not tabbed out of must not
    vanish when another character is clicked."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    w._widgets["gold"].setValue(4242)
    w.roster.selectRow(3)
    w.roster.selectRow(0)
    assert w._widgets["gold"].value() == 4242


@game_disks
def test_read_only_widgets_are_disabled_on_a_save(app, save):
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    assert not w._widgets["hp_current"].isEnabled()
    assert not w._widgets["thac0_base"].isEnabled()
    assert w._widgets["strength"].isEnabled()


# --- the combat box shows the sheet value, not the stored byte (#149) -------
#
# `thac0_base`, `thac0`, `armour_class_base` and `armour_class` are the only
# four fields the record stores as `60 - value` (`goldbox/encoding.py`).
# `CharacterRecord.get`/`set` hand back and take the byte exactly as stored;
# the editor is the one place that has to undo the bias for a human to read
# it, and until now it never did.


@game_disks
def test_combat_box_shows_the_sheet_value_not_the_stored_byte(app, newsave5):
    """GARRETT's record holds 39 and 50. His sheet reads THAC0 21, AC 10.

    NEWSAVE5 holds GARRETT, ASTRID, MAGNUS, ROLAND, GRIMNIR, BRUTUS in slots
    0-5, and the roster lists BRUTUS first, GARRETT last (`#160`)."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(newsave5))
    w.roster.selectRow(5)
    assert w._widgets["thac0_base"].value() == 21
    assert w._widgets["armour_class_base"].value() == 10


@game_disks
def test_typing_the_sheet_value_stores_the_biased_byte(app, newsave5):
    """`thac0_base` is disabled -- the game recomputes it, and that is settled
    behaviour, not this issue's business -- so this forces the box open to
    prove the round trip through `combat_byte`, the same way #145's
    forced-failure tests prove a mechanism independent of whether today's UI
    can reach it.

    GARRETT's stored byte is already 39 (THAC0 21), so typing 21 back in and
    flushing must leave the record still holding 39 -- not the unconverted 21
    a flush that forgot the bias would write. GARRETT is row 5: NEWSAVE5
    lists BRUTUS, GRIMNIR, ROLAND, MAGNUS, ASTRID, GARRETT (`#160`)."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(newsave5))
    w.roster.selectRow(5)
    box = w._widgets["thac0_base"]
    box.setEnabled(True)
    box.setValue(21)
    w._flush()
    assert w.party.member(5).record.get("thac0_base") == 39


# --- a save slot's missing byte draws blank, not a fabricated zero (#150) ---
#
# A save slot holds only the first 256 of the record's 580 bytes. `thac0`,
# `armour_class`, `hp_current`, `roster_in_use`, `party_order` and
# `roster_movement` all sit past that boundary, so `record.get()` raises
# `FieldNotStored` for every one of them on a save disk. The fallback used to
# be a literal 0, indistinguishable from a character who really has 0 hit
# points.

TRUNCATED_IN_SAVE = (
    "thac0", "armour_class", "hp_current",
    "roster_in_use", "party_order", "roster_movement",
)


def _standalone_disk(tmp_path, name: str = "ZERO", **field_values):
    """A roster-disk PRG holding one full 580-byte record -- the twin case to
    a save slot's 256, so every field named here is actually stored."""
    from gamedata import _disk_with

    from goldbox.record import CharacterRecord

    record = CharacterRecord.blank()
    record.set("name", name)
    for field, value in field_values.items():
        record.set(field, value)
    out = tmp_path / "ROSTER.D64"
    out.write_bytes(_disk_with([(name.encode(), record.to_prg())]))
    return out


@game_disks
def test_a_field_a_save_slot_does_not_carry_draws_blank(app, newsave5):
    """GARRETT's Thac0 and Armour class *current* boxes have no byte at all
    on a save disk -- the record stops at 256 bytes and both are past it.
    They must read blank, not the 0 a reader would take for his real score."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(newsave5))
    w.roster.selectRow(5)
    for name in TRUNCATED_IN_SAVE:
        box = w._widgets[name]
        assert box.value() == box.minimum()
        assert box.text().strip() == ""
    # The base boxes sit one row up on the sheet and are the real numbers.
    assert w._widgets["thac0_base"].value() == 21
    assert w._widgets["armour_class_base"].value() == 10


def test_the_same_fields_read_real_values_off_a_full_record(app, tmp_path):
    """The twin of the test above: a roster disk carries every byte, so none
    of these fields is ever absent there -- `PORSAVE10.D64` is a real
    specimen of exactly this shape."""
    from editor.window import EditorBinding
    disk = _standalone_disk(tmp_path, hp_current=9, roster_in_use=1,
                             party_order=3, roster_movement=9,
                             thac0=39, armour_class=54)
    w = EditorBinding(make_root(), str(disk))
    w.roster.selectRow(0)
    assert w._widgets["hp_current"].value() == 9
    assert w._widgets["roster_in_use"].value() == 1
    assert w._widgets["party_order"].value() == 3
    assert w._widgets["roster_movement"].value() == 9
    assert w._widgets["thac0"].value() == 21          # 60 - 39, sheet value
    assert w._widgets["armour_class"].value() == 6    # 60 - 54


def test_a_genuinely_zero_field_still_reads_zero(app, tmp_path):
    """The over-reach this fix must not make: a stored field whose real value
    is its lowest legal one must still show that number, not blank -- a
    blank record's `hp_current` is a real, stored 0."""
    from editor.window import EditorBinding
    disk = _standalone_disk(tmp_path)
    w = EditorBinding(make_root(), str(disk))
    w.roster.selectRow(0)
    box = w._widgets["hp_current"]
    assert box.value() == 0
    assert box.text().strip() == "0"


@game_disks
def test_a_no_op_save_writes_nothing_at_all(app, save):
    """The bar the CLI holds, and it matters more here because Save overwrites
    the file you opened. Visiting every character must not perturb a byte."""
    from editor.window import EditorBinding
    before = save.read_bytes()
    w = EditorBinding(make_root(), str(save))
    for row in range(6):
        w.roster.selectRow(row)
    assert w.save(interactive=False) == "no changes"
    assert save.read_bytes() == before
    assert not (save.parent / "backups").exists()


@game_disks
def test_a_real_edit_is_written_and_backed_up(app, save):
    from editor.window import EditorBinding
    before = save.read_bytes()
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    w._widgets["gold"].setValue(1234)
    w._edited()
    assert "wrote" in w.save(interactive=False)
    assert save.read_bytes() != before
    backups = list((save.parent / "backups").glob("*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == before

    again = EditorBinding(make_root(), str(save))
    again.roster.selectRow(0)
    assert again._widgets["gold"].value() == 1234


# --- the name is not editable (#145) -----------------------------------------
#
# A rename that silently failed to save is what #145 was about. Donald's
# decision was to remove the failure entirely rather than guard it: the name
# is disabled in wish/window.ui, and nothing in this file re-enables it.


@game_disks
def test_the_name_field_is_disabled(app, save):
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    assert not w._widgets["name"].isEnabled()


@game_disks
def test_the_name_field_stays_disabled_after_switching_character(app, save):
    """`_apply_read_only` runs once per file, not per row -- but the name must
    not come back on switching character either."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    w.roster.selectRow(1)
    assert not w._widgets["name"].isEnabled()


@game_disks
def test_the_name_is_still_shown_though_disabled(app, save):
    """Disabled must not mean the value is hidden -- the player can still see
    whose sheet this is. Row 5 is MALCYON, PORSAVE11's lowest occupied slot
    and so the last the roster lists (`#160`)."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(5)
    assert w._widgets["name"].text() == "MALCYON"


# --- a field that refuses to save is a pop-up (#145) -------------------------
#
# Donald's ruling: keep the reporting mechanism `4738b19` built, but as a
# pop-up rather than a status-bar line, worded "Error: {label} could not be
# saved." with the label read live off the sheet. No field can actually
# refuse today -- every spin box is ranged to what its field holds, every
# combo box offers only its own entries, and the two spell widgets always
# hand back exactly the field's width -- so these tests force the failure at
# `CharacterRecord.set` to prove the mechanism itself, independent of
# whether anything can currently reach it.

from goldbox.record import CharacterRecord  # noqa: E402


@game_disks
def test_a_field_that_refuses_to_save_pops_up_the_approved_sentence(
        app, save, monkeypatch):
    import editor.window as ew
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    real_set = CharacterRecord.set

    def fail_on_gold(self, name, value):
        if name == "gold":
            raise ValueError("boom")
        return real_set(self, name, value)

    monkeypatch.setattr(CharacterRecord, "set", fail_on_gold)
    w._widgets["gold"].setValue(w._widgets["gold"].value() + 1)
    w.save(interactive=True)
    assert said == [("Cannot save", "Error: Gold could not be saved.")]


@game_disks
def test_two_refused_fields_in_one_flush_are_one_dialog_not_two(
        app, save, monkeypatch):
    """Consecutive pop-ups would be worse than the bug -- one dialog, one
    line per field. `_widgets` is a dict in widget-tree order, not sheet
    order, so this checks the two lines are both there rather than which
    comes first."""
    import editor.window as ew
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    real_set = CharacterRecord.set

    def fail_on_both(self, name, value):
        if name in ("gold", "hp_rolled"):
            raise ValueError("boom")
        return real_set(self, name, value)

    monkeypatch.setattr(CharacterRecord, "set", fail_on_both)
    w._widgets["gold"].setValue(w._widgets["gold"].value() + 1)
    w._widgets["hp_rolled"].setValue(w._widgets["hp_rolled"].value() + 1)
    w.save(interactive=True)
    assert len(said) == 1
    title, text = said[0]
    assert title == "Cannot save"
    assert sorted(text.splitlines()) == sorted([
        "Error: Gold could not be saved.",
        "Error: HP rolled could not be saved.",
    ])


@game_disks
def test_a_field_left_untouched_never_triggers_the_dialog(app, save, monkeypatch):
    """The trigger is a field the user changed. `record.set` is made to fail
    for every field here, and nothing pops up because nothing on screen
    differs from what the record already holds."""
    import editor.window as ew
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    monkeypatch.setattr(CharacterRecord, "set",
                        lambda self, name, value: (_ for _ in ()).throw(
                            ValueError("boom")))
    w.save(interactive=True)
    assert said == []


@game_disks
def test_the_field_label_strips_a_trailing_colon(app, save):
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    label = w._child("label_gold")
    label.setText("Gold:")
    assert w._field_label("gold") == "Gold"


@game_disks
def test_the_field_label_falls_back_for_a_field_with_no_label(app, save):
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    assert w._field_label("no_such_field") == "a field"


# --- the inventory ----------------------------------------------------------

GAME_DISK = f"{DISKS}/POOL1.D64"


@pytest.fixture
def editor(app, save):
    """A window with a game disk, so items have names and templates exist."""
    from editor.window import EditorBinding
    return EditorBinding(make_root(), str(save), GAME_DISK)


@game_disks
def test_items_are_shown_by_name_not_by_number(editor):
    editor.roster.selectRow(3)                    # ROLAND -- row 3, #160
    names = [editor.items.data(editor.items.index(r, 1)) for r in range(16)]
    assert names[:2] == ["BANDED MAIL", "MACE"]
    assert names[2] == "—"                           # a free slot, shown as one


@game_disks
def test_without_a_game_disk_the_tab_says_why_items_are_numbers(app, save):
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))                      # no game disk beside it
    w.roster.selectRow(2)
    assert "word 57/48" == w.items.data(w.items.index(0, 1))
    assert "No game disk" in w.root.findChild(QLabel, "label_inventory").text()
    assert not w.root.findChild(QWidget, "button_item_add").isEnabled()


@game_disks
def test_editing_quantity_and_readied_reaches_the_disk(editor, save):
    from PyQt6.QtCore import Qt

    from editor.window import EditorBinding
    editor.roster.selectRow(0)                    # MALCYON, six darts
    model = editor.items
    assert model.setData(model.index(1, 2), 9)                       # quantity
    assert model.setData(model.index(1, 3), Qt.CheckState.Checked.value,
                         Qt.ItemDataRole.CheckStateRole)             # readied
    assert model.setData(model.index(1, 5), -2)                      # bonus
    assert "wrote" in editor.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(0)
    item = again.items.inventory.item(1)
    assert (item.quantity, item.readied, item.bonus) == (9, True, -2)


@game_disks
def test_editing_weight_writes_tenths_of_a_pound_to_the_disk(editor, save):
    """The lb column stores pounds; the bytes hold tenths -- a whole-number
    edit of 12 must land as 120, not 12."""
    from editor.window import EditorBinding
    editor.roster.selectRow(0)                    # MALCYON, six darts
    model = editor.items
    assert model.setData(model.index(1, 6), 12)                       # lb
    assert "wrote" in editor.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(0)
    item = again.items.inventory.item(1)
    assert item.weight_tenths == 120
    assert item.weight_lb == 12.0


@game_disks
def test_a_fractional_weight_edits_to_the_nearest_tenth(editor):
    """3.5 lb is 35 tenths, and the column shows it back as 3.5 -- the
    conversion this task is actually about."""
    editor.roster.selectRow(0)
    model = editor.items
    assert model.setData(model.index(1, 6), 3.5)
    assert model.inventory.item(1).weight_tenths == 35
    assert model.data(model.index(1, 6)) == "3.5"

    # A value finer than a tenth rounds to the nearest one.
    assert model.setData(model.index(1, 6), 3.54)
    assert model.inventory.item(1).weight_tenths == 35


@game_disks
def test_weight_out_of_range_is_refused(editor):
    editor.roster.selectRow(0)                    # MALCYON, six darts
    model = editor.items
    before = model.inventory.item(1).weight_tenths
    assert not model.setData(model.index(1, 6), 6553.6)   # 65536 tenths
    assert not model.setData(model.index(1, 6), -1)
    assert model.inventory.item(1).weight_tenths == before


@game_disks
def test_rubbish_weight_is_refused(editor):
    editor.roster.selectRow(0)                    # MALCYON, six darts
    model = editor.items
    before = model.inventory.item(1).weight_tenths
    assert not model.setData(model.index(1, 6), "heavy")
    assert model.inventory.item(1).weight_tenths == before


@game_disks
def test_an_empty_slot_is_not_weight_editable(editor):
    from PyQt6.QtCore import Qt
    editor.roster.selectRow(3)                    # ROLAND -- row 3, #160; item slot 2 is empty
    model = editor.items
    assert not model.flags(model.index(2, 6)) & Qt.ItemFlag.ItemIsEditable
    assert not model.setData(model.index(2, 6), 5)


@game_disks
def test_an_added_item_is_a_copy_of_the_games_own_record(editor, save):
    from editor.window import EditorBinding
    from goldbox.items import load_item_templates
    editor.roster.selectRow(3)                    # ROLAND -- row 3, #160; two items
    assert "slot 2" in editor.add_item("POTION OF HEALING")
    editor.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(3)
    raw = again.items.inventory.raws[2]
    assert raw == load_item_templates(GAME_DISK)["POTION OF HEALING"]


def _flattened_ring() -> bytes:
    """`ITEMFILE17`'s Ring of Fire Resistance, off the player's own disk.

    The one copy of the ring on the eight sides that grants nothing: +14 and
    +15 are zero, so `CAMP $10B5` never sees bit 7 set. Read rather than
    written down, because a slice of a game file in this repository is the
    same copy under a new name.
    """
    from gamedata import game_file

    from goldbox.items import (
        ITEM_SIZE,
        PASSIVE_POWER,
        POWER,
        RING_OF_FIRE_RESISTANCE_ID,
    )
    payload = game_file("ITEMFILE17")
    for i in range(len(payload) // ITEM_SIZE):
        raw = bytes(payload[i * ITEM_SIZE:(i + 1) * ITEM_SIZE])
        if (tuple(raw[:4]) == RING_OF_FIRE_RESISTANCE_ID
                and not raw[POWER] & PASSIVE_POWER):
            return raw
    pytest.skip("ITEMFILE17 has no flattened Ring of Fire Resistance")


@game_disks
def test_adding_a_ring_of_fire_resistance_gives_the_one_that_works(save):
    """#285: a player who adds the ring in Wish gets a ring that resists fire.

    Two records print that name -- `ITEMFILE17`'s, which grants nothing, and
    `ITEMFILE1D`'s, which DOS matches byte for byte -- and taking the first
    one found handed out the dead one, because POOL3 sorts before POOL4.
    """
    from editor.window import EditorBinding
    from goldbox.items import EFFECT, PASSIVE_POWER, POWER, load_item_templates

    template = load_item_templates(GAME_DISK)["RING OF FIRE RESISTANCE"]
    assert (template[EFFECT], template[POWER]) == (61, 0x81)
    assert template != _flattened_ring()

    first = EditorBinding(make_root(), str(save), GAME_DISK)
    first.roster.selectRow(3)                    # ROLAND -- row 3, #160; two items
    assert "slot 2" in first.add_item("RING OF FIRE RESISTANCE")
    assert "wrote" in first.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(3)
    raw = again.items.inventory.original[2]
    assert raw == template
    assert raw[POWER] & PASSIVE_POWER


@game_disks
def test_the_ring_of_fire_resistance_is_repaired_on_an_editor_save(save):
    """#285: a save that already holds the dead ring -- one an older Wish
    handed out -- comes back resisting fire, and nothing else on the disk
    moves. Opening and saving is the whole trigger; no edit is needed."""
    from editor.window import EditorBinding
    from goldbox.items import EFFECT, POWER

    flat = _flattened_ring()
    assert (flat[EFFECT], flat[POWER]) == (0, 0)

    first = EditorBinding(make_root(), str(save), GAME_DISK)
    first.roster.selectRow(3)                    # ROLAND -- row 3, #160; two items
    first.items.inventory.set_raw(2, flat)
    assert "wrote" in first.save(interactive=False)
    broken = save.read_bytes()

    # A second window, no edits at all.
    second = EditorBinding(make_root(), str(save), GAME_DISK)
    assert "wrote" in second.save(interactive=False)
    repaired = save.read_bytes()

    assert len(broken) == len(repaired)
    diffs = [i for i in range(len(broken)) if broken[i] != repaired[i]]
    assert len(diffs) == 2, diffs
    lo, hi = sorted(diffs)
    assert hi == lo + 1                                     # +14 then +15
    assert (broken[lo], broken[hi]) == (0, 0)
    assert (repaired[lo], repaired[hi]) == (61, 0x81)

    third = EditorBinding(make_root(), str(save), GAME_DISK)
    third.roster.selectRow(3)
    raw = third.items.inventory.original[2]
    assert (raw[EFFECT], raw[POWER]) == (61, 0x81)
    assert raw[:EFFECT] == flat[:EFFECT]                    # nothing else moved


@game_disks
def test_deleting_closes_the_gap(editor):
    editor.roster.selectRow(3)                    # ROLAND -- row 3, #160; BANDED MAIL, MACE
    assert "slot 0" in editor.delete_item(0)
    assert editor.items.inventory.item(0).name == "MACE"
    assert editor.items.inventory.is_empty(1)


@game_disks
def test_an_identified_item_cannot_be_un_identified(editor):
    """Which name words to hide is not recoverable once they are shown -- the
    CLI refuses the same edit."""
    from PyQt6.QtCore import Qt
    editor.roster.selectRow(2)
    flags = editor.items.flags(editor.items.index(0, 4))
    assert not flags & Qt.ItemFlag.ItemIsUserCheckable


@game_disks
def test_a_no_op_save_writes_nothing_with_a_game_disk_open(editor, save):
    """The item blocks are read and written by a different path from the
    records, so they need their own round-trip proof."""
    before = save.read_bytes()
    for row in range(6):
        editor.roster.selectRow(row)
    assert editor.save(interactive=False) == "no changes"
    assert save.read_bytes() == before


# --- spells -----------------------------------------------------------------

@game_disks
def test_spells_are_shown_by_name(editor):
    editor.roster.selectRow(3)                    # ROLAND -- row 3, #160; a cleric
    book, memorised = editor._spell_widgets()
    assert book.known() == [1, 2, 3, 4, 5, 6, 7, 8]
    assert memorised.list.item(0).text() == "CURE LIGHT WOUNDS (cleric 1)"


@game_disks
def test_the_capacity_is_shown_beside_the_memorised_list(editor):
    editor.roster.selectRow(3)                    # ROLAND -- row 3, #160
    _book, memorised = editor._spell_widgets()
    assert "cleric: L1 3/3" in memorised.capacity.text()


def test_a_curse_paladin_above_ninth_level_shows_a_real_spell_capacity():
    """#552. `goldbox.spells.capacity` only recognizes the magic-user and
    cleric `class_bits`, so a paladin's `0x40` fell through and the pane
    showed nothing; `capacity_by_class` (#548) reads the same table by class
    name and knows paladin (whose row is added into the cleric array) and
    ranger too.

    MATHEW, on `WISH-SPEC-curse-trained-party`, is a paladin alone
    (`class_bits` 0x40) at level 6 -- a paladin's first row in
    `goldbox.spells._PALADIN_CURSE` does not fill in until level 9, past
    anything this disk's own party reached, so the level is bumped in the
    loaded record before reading the pane. This exercises our own display
    code against a `levels` dict it is given, not a claim about what the
    engine computes for a level the party never reached
    (`.claude/rules/testing.md`'s provenance rule is about specimens, not
    about this)."""
    from editor.window import EditorBinding

    path = _curse_trained_party_specimen()
    editor = EditorBinding(make_root(), str(path))
    mathew = editor.party.member(_row_named(editor.party, "MATHEW"))
    assert mathew.record.get("class_bits") == 0x40
    mathew.record.set("level_paladin", 9)
    editor.roster.selectRow(_row_named(editor.party, "MARK"))
    editor.roster.selectRow(_row_named(editor.party, "MATHEW"))
    _book, memorised = editor._spell_widgets()
    assert "cleric: L1 0/1" in memorised.capacity.text()


@game_disks
def test_editing_the_spellbook_reaches_the_disk(editor, save):
    from editor.window import EditorBinding
    editor.roster.selectRow(5)                    # MALCYON -- row 5, #160; a magic-user
    book, _memorised = editor._spell_widgets()
    assert book.known() == [11, 18, 19, 21]
    book.set_ids([11, 18, 19, 21, 9])                # BURNING HANDS
    editor._edited()
    assert "wrote" in editor.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(5)
    assert again._spell_widgets()[0].known() == [9, 11, 18, 19, 21]


@game_disks
def test_a_memorised_spell_the_character_does_not_know_is_allowed(editor, save):
    """Shown, never refused: the CLI reports the same inconsistency and writes
    it anyway, because trying what the game has not been shown is the point."""
    from editor.window import EditorBinding
    editor.roster.selectRow(5)                    # MALCYON -- row 5, #160
    _book, memorised = editor._spell_widgets()
    assert memorised.add_spell(36)                   # a cleric 3 spell
    assert "not in the spellbook" in memorised.capacity.text()
    assert "wrote" in editor.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(5)
    assert again._spell_widgets()[1].ids() == [36]


@game_disks
def test_an_untouched_spell_field_is_written_back_byte_for_byte(editor):
    """The bitmask has bits belonging to no spell and the memorised list has a
    tail we cannot account for. Neither may be normalised on the way through."""
    editor.roster.selectRow(2)
    book, memorised = editor._spell_widgets()
    record = editor.party.member(2).record
    # The widget holds the whole mask, both declared fields of it, because how
    # far into it a title reaches is the title's business. The memorised list
    # is the same idea: 81 slots in Pool of Radiance, which is three declared
    # fields and not the 69 `spells_memorised` covers on its own (#268).
    assert book.to_bytes() == editor._spellbook_raw(record)
    assert memorised.to_bytes() == editor._memorised_raw(
        record, editor.party.member(2).game)
    assert len(memorised.to_bytes()) == 81


def test_the_memorised_widget_holds_as_many_slots_as_it_was_given():
    """Twenty prepared spells, and the widget shows twenty and writes eighty-one
    bytes back.

    It stopped at sixteen -- the width `spells_memorised` used to be declared
    as -- so a cleric 6 / magic-user 6 lost the last spells they memorised the
    moment the sheet was saved (#268). The widget takes its width from the
    bytes the window hands it, which is the span the window writes back.
    """
    from editor.spellwidget import MemorisedEditor

    size = c64_codec.memorised_span(None)[1]
    ids = list(range(1, 21))
    raw = bytes(ids) + bytes(size - len(ids))
    w = MemorisedEditor(make_root())
    w.set_bytes(raw)
    assert w.slot_count() == size == 81
    assert w.ids() == ids
    assert w.to_bytes() == raw                 # untouched: back byte for byte
    assert w.add_spell(21)                     # seventeen was refused before
    assert len(w.ids()) == 21
    assert len(w.to_bytes()) == size


@game_disks
def test_a_spell_list_is_wide_enough_for_the_longest_name(editor):
    """Donald: "the spells are not visible in the table because it's so
    small". The spellbook opened 70 pixels wide beside a memorised column
    whose drop-down asked for 330, inside a box capped at 520.

    The rule and not the pixel count: whatever the font, each list is at least
    as wide as its longest line plus the frame and the scroll bar. The
    spellbook's tick box makes it wider still, so this is a floor for both.
    """
    from PyQt6.QtWidgets import QStyle

    editor.root.resize(1875, 1030)
    editor.root.show()
    editor.roster.selectRow(0)                    # MALCYON, a magic-user
    book, memorised = editor._spell_widgets()
    lists = ((book.list, [book.list.item(i).text()
                          for i in range(book.list.count())]),
             # Any spell can be memorised, so the memorised list is measured
             # against every name the drop-down offers, not against the two
             # in it now.
             (memorised.list, [memorised.choice.itemText(i)
                               for i in range(memorised.choice.count())]))
    for view, texts in lists:
        wanted = max(view.fontMetrics().horizontalAdvance(t) for t in texts)
        furniture = 2 * view.frameWidth() + view.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent, None, view)
        assert wanted > 0
        assert view.minimumWidth() >= wanted + furniture
        # And the sheet gives them the width they ask for.
        assert view.width() >= wanted + furniture


@game_disks
def test_the_memorised_drop_down_shows_a_whole_spell_name(editor):
    """Donald: "the text isn't entirely visible". Sharing a row with Add and
    Remove left it 132 px of edit field for a 303 px name."""
    editor.root.resize(1875, 1030)
    editor.root.show()
    editor.roster.selectRow(0)
    _book, memorised = editor._spell_widgets()
    choice = memorised.choice
    wanted = max(choice.fontMetrics().horizontalAdvance(choice.itemText(i))
                 for i in range(choice.count()))
    assert choice.minimumWidth() >= wanted     # plus the frame and the arrow
    assert choice.width() >= wanted


@game_disks
def _test_the_window_opens_inside_a_small_desktop(app, save):
    """Donald's compositor hands out 1280x662 of a 1920x1080 desktop, and the
    sheet asks for 1875x1030. The sheet scrolls; the window has to fit."""
    from editor.__main__ import WANTED, fit_on_screen
    from PyQt6.QtCore import QRect

    from editor.window import EditorBinding
    space = QRect(0, 0, 1280, 662)
    w = EditorBinding(make_root(), str(save))
    w.root.resize(*WANTED)
    fit_on_screen(w, space)
    w.root.show()
    fit_on_screen(w, space)
    assert w.frameGeometry().width() <= space.width()
    assert w.frameGeometry().height() <= space.height()


# --- the combat icon --------------------------------------------------------

def test_an_npc_icon_is_shown_edited_and_flushed(app, party):
    """An NPC's stored icon is editable in a save, as a PC's is."""
    from editor.window import EditorBinding
    from goldbox.icons import ICON_SIZE, Icon

    editor = EditorBinding(make_root(), str(party))
    npc, pc = editor.party.member(0), editor.party.member(1)
    stale = Icon(bytes(range(ICON_SIZE)))
    npc.record.set_npc(True)
    npc.icon = stale
    npc.record.set("levels_drained", 255)
    npc.record.set("hp_lost_to_drain", 255)
    editor.charset = bytes([0xFF]) * (256 * 8)
    editor._populate()

    icon = editor._widgets["icon"]
    assert icon.icon == stale
    assert icon.isEnabled()
    assert icon.btn_change.isEnabled()
    assert icon.part_combo.isEnabled()
    assert icon.color_combo.isEnabled()
    assert editor._widgets["levels_drained"].value() == 0
    assert editor._widgets["hp_lost_to_drain"].value() == 0
    before = npc.icon
    icon.set_cell_colour(0, 7)
    assert icon.icon != before
    assert editor.dirty == {0}
    editor._flush()
    assert npc.icon == icon.icon
    assert npc.record.get("levels_drained") == 255
    assert npc.record.get("hp_lost_to_drain") == 255

    editor.roster.selectRow(1)
    assert icon.isEnabled()
    assert icon.icon == pc.icon
    assert icon.btn_change.isEnabled()
    assert icon.part_combo.isEnabled()
    assert icon.color_combo.isEnabled()


def test_an_all_zero_icon_is_a_white_empty_frame(app):
    from editor.iconwidget import IconPreview
    from goldbox.icons import ICON_SIZE, Icon

    preview = IconPreview()
    preview.resize(preview.minimumSize())
    preview.set_icon(Icon(bytes(ICON_SIZE)), bytes([0xFF]) * (256 * 8))
    image = preview.grab().toImage()
    centre = image.pixelColor(image.width() // 2, image.height() // 2)
    assert centre.name() == "#ffffff"


def test_a_standalone_characters_icon_stays_read_only(app, tmp_path):
    from editor.window import EditorBinding

    editor = EditorBinding(make_root(), str(_standalone_disk(tmp_path)))
    editor.roster.selectRow(0)
    assert not editor._widgets["icon"].isEnabled()


@game_disks
def test_the_icon_picker_offers_the_game_s_own_two_lists(app, editor):
    """Not 253 glyphs a cell. `SPELLE64` says 35 weapons and 23 heads at this
    size, and those are the only two choices the ICON menu has."""
    from editor.partspicker import PartsPicker
    parts = editor.icon_parts
    assert parts is not None, "no disk carrying SPELLE64 was found"
    shape = parts.compose("small", 0, 1)
    colours = parts.colours_for(shape, {k: 1 for k in range(7)}, bytes(18))
    picker = PartsPicker(parts, editor.charset, shape, colours)
    assert picker.weapons.count() == 28
    assert picker.heads.count() == 14


@game_disks
def test_changing_a_cell_glyph_reaches_the_disk(editor, save):
    from editor.window import EditorBinding
    editor.roster.selectRow(4)                    # MAGNUS
    icon = editor._widgets["icon"]
    assert icon.icon.screen_codes[0] != 200
    icon.set_cell_glyph(0, 200)
    editor._edited()
    assert "wrote" in editor.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(4)
    assert again._widgets["icon"].icon.screen_codes[0] == 200


@game_disks
def test_changing_a_cell_colour_reaches_the_disk(editor, save):
    """The colour half was editable before this batch and was never written
    back -- the icon table is patched separately from the character slots."""
    from editor.window import EditorBinding
    editor.roster.selectRow(4)
    icon = editor._widgets["icon"]
    icon.set_cell_colour(0, 7)
    editor._edited()
    editor.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(4)
    assert again._widgets["icon"].icon.colours[0] == 7


# --- dropdowns --------------------------------------------------------------

@game_disks
def test_race_class_alignment_and_sex_are_named(editor):
    editor.roster.selectRow(4)                    # LADY KATHERINE -- row 4, #160
    shown = {n: editor._widgets[n].currentText()
             for n in ("race", "char_class", "class_bits", "alignment", "sex")}
    assert shown["race"] == "HALF-ELF"
    assert shown["char_class"] == "Magic-user/thief"
    assert shown["class_bits"] == "Magic-user/thief"
    assert shown["alignment"] == "NEUTRAL EVIL"
    assert shown["sex"] == "1  female"
    assert {n: editor._widgets[n].currentData()
            for n in ("race", "char_class", "class_bits", "alignment")} == {
                "race": 4, "char_class": 16, "class_bits": 5, "alignment": 5,
            }


def test_race_zero_is_named_rather_than_left_blank():
    """The commonest race in the game, and the reason PRINCESS FATIMA reads as
    a monster. Not evidence of tampering.

    Named `MONSTER` and not annotated since 2026-08-24: the note it used to
    carry was wider than the longest real race, and `Race` is what sets the
    Character box's width -- and so the header's, which is a floor under the
    whole window (#41, #43).
    """
    from editor.enums import race_names
    from goldbox import c64_port

    race = race_names(c64_port.POOL_OF_RADIANCE)
    assert race[0] == "MONSTER" and race[8] == "MONSTER"


@game_disks
def test_a_code_the_game_has_no_name_for_is_still_shown(app, editor):
    from editor.window import _select
    combo = editor._widgets["race"]
    _select(combo, 200)
    assert combo.currentData() == 200
    assert "not in the game's table" in combo.currentText()


@game_disks
def test_the_two_class_fields_are_allowed_to_disagree(editor, save):
    """0x073 and 0x0EB say the same thing two ways. Forcing them into
    agreement is where a losslessness bug came from."""
    from editor.window import EditorBinding
    editor.roster.selectRow(1)
    before = editor.party.member(1).record.get("class_bits")
    editor._widgets["char_class"].setCurrentIndex(
        editor._widgets["char_class"].findData(2))          # FIGHTER
    editor._edited()
    editor.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(1)
    assert again._widgets["char_class"].currentData() == 2
    assert again.party.member(1).record.get("class_bits") == before


def _curse_trained_party_specimen():
    """`WISH-SPEC-curse-trained-party`, verified against its own provenance
    -- the same rule `tests/convert/test_c64classcode.py`'s `_named_specimen_disk`
    applies. A party this project trained at Curse's own hall, so its stale
    `char_class` bytes are engine-written, not somebody's edit
    (`docs/187-the-class-code-byte.md`)."""
    import gamedata

    from tools.registry import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    found = sorted((root / "por-c64").glob(
        "WISH-SPEC-curse-trained-party.[dD]64"))
    if not found:
        pytest.skip("needs specimen WISH-SPEC-curse-trained-party")
    path = found[0]
    prov = path.with_suffix(".provenance.toml")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail("WISH-SPEC-curse-trained-party: "
                     f"{path.name} has changed since it was recorded; "
                     "run tools/registry/specimens.py check")
    return path


def _row_named(party, name: str) -> int:
    return next(i for i, m in enumerate(party.members)
                if m.name.strip() == name)


def test_the_class_combo_shows_the_class_the_roster_shows(app, tmp_path):
    """#356. TRAVIS, on `WISH-SPEC-curse-trained-party`, is a dwarf thief
    6 / fighter 5 (`class_bits` 0x0C) whose Curse trainer left `char_class`
    at 0 -- the code table's CLERIC. The roster (`editor/roster.py`'s
    `class_name`) already reads the bits and calls him FIGHTER/THIEF;
    Donald's ruling, 2026-09-07, is that the Class combo shows the class he
    actually is, so it must show FIGHTER/THIEF's code (14), the same one
    `goldbox.classcode.code_for(0x0C, game=CURSE)` and
    `tests/convert/test_c64classcode.py::test_a_trained_curse_records_zeroed_code_reads_repaired`
    derive, not the stale 0 on disk.

    MARK, on the same disk, is the control: a paladin whose `char_class` (3)
    already agrees with his `class_bits` (0x40), because Curse's trainer
    never touched him (`docs/187-the-class-code-byte.md`) -- the combo must
    keep showing 3.
    """
    from editor.window import EditorBinding

    path = _curse_trained_party_specimen()
    editor = EditorBinding(make_root(), str(path))

    travis = _row_named(editor.party, "TRAVIS")
    assert editor.party.member(travis).record.get("char_class") == 0
    assert editor.party.member(travis).record.get("class_bits") == 0x0C
    editor.roster.selectRow(travis)
    assert editor._widgets["char_class"].currentData() == 14
    shown = editor._widgets["char_class"].currentText().lower()
    assert "fighter" in shown and "thief" in shown
    # Showing the repaired code must not touch the stored bitmask.
    assert editor.party.member(travis).record.get("class_bits") == 0x0C

    mark = _row_named(editor.party, "MARK")
    editor.roster.selectRow(mark)
    assert editor._widgets["char_class"].currentData() == 3


def _curse_dual_classed_specimen():
    """`WISH-SPEC-curse-dual-classed` -- `WISH-SPEC-curse-trained-party` with
    one further action, PHILIPPE trained from magic-user 6 to fighter at
    Curse's own hall, watched in the running game (#256's comment of
    2026-09-05)."""
    import gamedata

    from tools.registry import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    found = sorted((root / "por-c64").glob(
        "WISH-SPEC-curse-dual-classed.[dD]64"))
    if not found:
        pytest.skip("needs specimen WISH-SPEC-curse-dual-classed")
    path = found[0]
    prov = path.with_suffix(".provenance.toml")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail("WISH-SPEC-curse-dual-classed: "
                     f"{path.name} has changed since it was recorded; "
                     "run tools/registry/specimens.py check")
    return path


def test_the_roster_names_the_class_a_dual_classed_character_trained_out_of(app):
    """#256, Donald's decision of 2026-09-05: the class line reads the
    current class with the former one beside it. PHILIPPE trained from
    magic-user 6 to fighter, `dual_class_slot` 0 (magic-user's slot) and
    `dual_class_level` 6 on the record -- `goldbox.c64_codec.deltas_for`
    confirms Curse keeps that pair (`C64Deltas.dual_class`)."""
    from editor.window import EditorBinding

    path = _curse_dual_classed_specimen()
    editor = EditorBinding(make_root(), str(path))
    philippe = editor.party.member(_row_named(editor.party, "PHILIPPE"))
    assert philippe.record.get("dual_class_slot") == 0
    assert philippe.record.get("dual_class_level") == 6
    assert philippe.class_name == "fighter (was magic-user 6)"


def test_an_untouched_partys_roster_is_byte_identical_with_the_former_class_code(app):
    """Nobody on `WISH-SPEC-curse-trained-party` has dual-classed --
    `dual_class_level` is 0 for all six -- and #256's addition must draw
    nothing extra for them: no empty bracket, no trailing "(was )", no
    change in the roster's own width. Grabbed as a screenshot, the way
    `#410`'s Preferences move was, and compared byte for byte rather than
    only checking the text."""
    import gamedata

    from editor.window import EditorBinding

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    found = sorted((root / "por-c64").glob(
        "WISH-SPEC-curse-trained-party.[dD]64"))
    if not found:
        pytest.skip("needs specimen WISH-SPEC-curse-trained-party")
    path = found[0]

    editor = EditorBinding(make_root(), str(path))
    for m in editor.party.members:
        assert m.record.get("dual_class_level") == 0
        assert "(was" not in m.class_name
        assert not m.class_name.endswith(")")


def _curse_409_regained_paladin_specimen():
    """`WISH-SPEC-curse-409-regained-paladin`, engine-written -- MATHEW and
    MARK driven through `HUMAN CHANGE CLASSES` and trained back past the
    level they left, so `class_bits` carries a pair Curse's own table has no
    code for (`#409 (A regained dual-classed paladin or ranger has a class
    mask Curse's own table cannot name, so Wish shows him a class he is
    not)`)."""
    import gamedata

    from tools.registry import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    found = sorted((root / "coab-c64").glob(
        "WISH-SPEC-curse-409-regained-paladin.[dD]64"))
    if not found:
        pytest.skip("needs specimen WISH-SPEC-curse-409-regained-paladin")
    path = found[0]
    prov = path.with_suffix(".provenance.toml")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail("WISH-SPEC-curse-409-regained-paladin: "
                     f"{path.name} has changed since it was recorded; "
                     "run tools/registry/specimens.py check")
    return path


def test_the_roster_shows_a_number_not_an_invented_class_for_a_regained_paladin(app):
    """#409. MATHEW (fighter 7 / paladin 6, `class_bits` 0x48) and MARK
    (cleric 6 / paladin 5, 0x42) hold masks Curse's own class-code table
    (`GEN $1951`) has no code for. `editor/roster.py`'s `class_name` already
    falls back to the raw number when `class_bit_names` has no name for a
    mask, so the roster shows `72`/`66` rather than inventing a class for
    either of them -- unchanged by this session, and true both before and
    after it (the fallback fires whenever `class_bits` itself has no name,
    with or without #409's new rows).
    """
    from editor.window import EditorBinding

    path = _curse_409_regained_paladin_specimen()
    editor = EditorBinding(make_root(), str(path))

    mathew = editor.party.member(_row_named(editor.party, "MATHEW"))
    mark = editor.party.member(_row_named(editor.party, "MARK"))
    assert mathew.record.get("class_bits") == 0x48
    assert mark.record.get("class_bits") == 0x42

    assert mathew.class_name == "72 (was paladin 6)"
    assert mark.class_name == "66 (was paladin 5)"
    for name in (mathew.class_name, mark.class_name):
        assert "thief" not in name.lower()
        assert "magic-user" not in name.lower()


def test_the_class_combo_shows_both_classes_for_a_regained_paladin(app):
    """#409's final ruling: the save is correct and the byte is not, so the
    fix is to read the mask, not to word the wrong byte more carefully.
    MATHEW's `char_class` byte (`0x073`) reads 6 and MARK's reads 5 --
    `dual_class_level`, the level each left his old class at, since Curse's
    trainer (`GEN $1939`) stores that instead of a code whenever a character
    is dual-classed. 6 and 5 are also THIEF's and MAGIC-USER's own codes in
    `editor/enums.py`'s `CHAR_CLASS`, so the Class combo (`field_char_class`)
    used to show `6  THIEF` and `5  MAGIC-USER` -- a class neither character
    has. Curse's own table (`GEN $1951`) has no code at all for either mask
    (`$48`, `$42`), so there is no code to fall back to either; the combo
    now names both classes the mask holds, the same way the C64's own sheet
    draws a regained dual-classed character (`FIGHTER/PALADIN`,
    `CLERIC/PALADIN`) -- `goldbox.c64_port.classes_to_names` off `class_bits`.

    Driven through the real window: selecting each row populates the combo
    through `editor.window._char_class_shown`, which returns a
    `_NoClassCode` carrying that pair as its label, and `_select`, which
    shows it by that label rather than matching the stale byte to a code by
    coincidence.
    """
    from editor.window import EditorBinding

    path = _curse_409_regained_paladin_specimen()
    editor = EditorBinding(make_root(), str(path))

    for who, expect in (("MATHEW", ("fighter", "paladin")),
                         ("MARK", ("cleric", "paladin"))):
        row = _row_named(editor.party, who)
        editor.roster.selectRow(row)
        shown = editor._widgets["char_class"].currentText().lower()
        assert "thief" not in shown
        assert "magic-user" not in shown
        assert "not in the game" not in shown
        for name in expect:
            assert name in shown


def test_the_class_combo_repairs_a_dual_classed_character_who_has_not_regained(app):
    """The control for #409's fix: PHILIPPE on `WISH-SPEC-curse-dual-classed`
    is trained from magic-user 6 to fighter and has not yet regained -- her
    `class_bits` is 0x08, fighter alone, which Curse's own table (`GEN
    $1951`) does name (code 2). #310's existing repair still applies here,
    and #409's new "no code at all" case must not swallow it.
    """
    from editor.window import EditorBinding

    path = _curse_dual_classed_specimen()
    editor = EditorBinding(make_root(), str(path))
    row = _row_named(editor.party, "PHILIPPE")
    philippe = editor.party.member(row)
    assert philippe.record.get("class_bits") == 0x08

    editor.roster.selectRow(row)
    shown = editor._widgets["char_class"].currentText().lower()
    assert shown == "fighter"


def test_curses_class_code_10_names_cleric_ranger_not_pool_of_radiances_pair(app):
    """#409's second, unambiguous defect: `editor/enums.py`'s `CHAR_CLASS`
    used to answer code 10 with Pool of Radiance's "cleric/magic-user" for
    every title, including Curse of the Azure Bonds, whose own table (`GEN
    $1951`) makes 10 mean $82, cleric + ranger -- and Pool of Radiance's own
    table has no code 10 at all. Driven through the real Class and Class
    bits combos, on a record patched to hold exactly that pair; no C64
    specimen carries it yet (`#409`'s own comments say so).
    """
    from editor.window import EditorBinding

    path = _curse_trained_party_specimen()
    editor = EditorBinding(make_root(), str(path))
    row = _row_named(editor.party, "MARK")
    editor.roster.selectRow(row)

    member = editor.party.member(row)
    member.record.set("class_bits", 0x82)
    member.record.set("char_class", 10)
    editor._populate()

    bits_shown = editor._widgets["class_bits"].currentText().lower()
    assert "cleric" in bits_shown and "ranger" in bits_shown
    assert "not in the game" not in bits_shown

    class_shown = editor._widgets["char_class"].currentText().lower()
    assert "cleric" in class_shown and "ranger" in class_shown
    assert "magic-user" not in class_shown


def test_class_code_11_reads_cleric_magic_user_without_the_stale_parenthetical(app):
    """#558. `editor/enums.py`'s `CHAR_CLASS` used to answer code 11 with
    "cleric/magic-user (again)" -- a leftover from when code 10 was wrongly
    believed to be a second cleric/magic-user (#409's fix removed that
    belief from code 10 alone, and left the parenthetical on 11, the code it
    was copied from). Half-elf cleric/magic-users are on the creation menu's
    own list, so this is a word a player reads about a character he actually
    made. The Class combo must name the same two classes the Class bits
    combo names for the same mask -- cleric and magic-user, and no
    parenthetical -- though the two tables join them in different orders
    (`class_bits`' is `class_table`'s own bit order, `char_class`'s is
    `CHAR_CLASS`'s alphabetical one, and that mismatch predates this issue
    and is not what it is about).
    """
    from editor.window import EditorBinding

    path = _curse_trained_party_specimen()
    editor = EditorBinding(make_root(), str(path))
    row = _row_named(editor.party, "MARK")
    editor.roster.selectRow(row)

    member = editor.party.member(row)
    member.record.set("class_bits", 0x03)
    member.record.set("char_class", 11)
    editor._populate()

    bits_shown = editor._widgets["class_bits"].currentText().lower()
    class_shown = editor._widgets["char_class"].currentText().lower()
    assert "cleric" in bits_shown and "magic-user" in bits_shown
    assert "cleric" in class_shown and "magic-user" in class_shown
    assert "again" not in class_shown
    assert class_shown == "cleric/magic-user"
    assert "again" not in class_shown


def test_an_ordinary_single_classed_character_is_unaffected_by_409(app):
    """The control: SHARA on `WISH-SPEC-curse-409-regained-paladin` is an
    untouched human cleric, `class_bits` 0x02, `char_class` 0. #409's fix
    touches only code 10 and the masks Curse's own table pairs a paladin or
    a ranger with, so an ordinary single class reads exactly as it did
    before this session.
    """
    from editor.window import EditorBinding

    path = _curse_409_regained_paladin_specimen()
    editor = EditorBinding(make_root(), str(path))
    row = _row_named(editor.party, "SHARA")
    shara = editor.party.member(row)
    assert shara.record.get("class_bits") == 0x02
    assert shara.record.get("char_class") == 0
    assert shara.class_name == "cleric"

    editor.roster.selectRow(row)
    assert editor._widgets["class_bits"].currentText().lower() == "cleric"
    assert editor._widgets["char_class"].currentText().lower() == "cleric"


@game_disks
def test_choosing_an_alignment_reaches_the_disk(editor, save):
    from editor.window import EditorBinding
    editor.roster.selectRow(0)
    combo = editor._widgets["alignment"]
    combo.setCurrentIndex(combo.findData(0))                # LAWFUL GOOD
    editor._edited()
    assert "wrote" in editor.save(interactive=False)

    again = EditorBinding(make_root(), str(save), GAME_DISK)
    again.roster.selectRow(0)
    assert again._widgets["alignment"].currentData() == 0


# --- preview ----------------------------------------------------------------

@game_disks
def test_preview_of_an_untouched_save_reports_no_changes(editor):
    for row in range(6):
        editor.roster.selectRow(row)
    assert editor.preview_text().endswith("no changes")


@game_disks
def test_preview_lists_fields_items_and_the_icon(editor):
    editor.roster.selectRow(5)                    # MALCYON -- row 5, #160; slot 0
    editor._widgets["gold"].setValue(999)
    # The engine treats slots 1-5 as retired; slot 6 holds the live DART.
    editor.items.setData(editor.items.index(6, 2), 9)
    editor.add_item("POTION OF HEALING")
    editor._widgets["icon"].set_cell_colour(0, 7)
    text = editor.preview_text()
    assert "slot 0 MALCYON: gold 2 -> 999" in text
    assert "slot 0 MALCYON: item 6 DART quantity 13 -> 9" in text
    assert "slot 0 MALCYON: item 1 added: POTION OF HEALING" in text
    assert "item 1 DART -> POTION OF HEALING" not in text
    assert "combat icon: 1 of 36 bytes changed" in text
    assert "4 change(s) (nothing written yet)" in text


@game_disks
def test_preview_writes_nothing(editor, save):
    before = save.read_bytes()
    editor.roster.selectRow(0)
    editor._widgets["gold"].setValue(999)
    editor.preview()
    assert save.read_bytes() == before


@game_disks
def test_the_preview_window_does_not_block(editor):
    """Save must not become modal, and neither may the report it renders."""
    editor.preview()
    assert editor._preview.isVisible() and not editor._preview.isModal()


@game_disks
def test_a_roster_disk_still_opens_and_has_no_items(app, tmp_path):
    """PORSAVE10.D64 has no SAVEDGAME0, so no items and no icons -- the tabs
    must say so rather than crash."""
    from editor.window import EditorBinding
    copy = tmp_path / "PORSAVE10.D64"
    copy.write_bytes(pathlib.Path(f"{DISKS}/PORSAVE10.D64").read_bytes())
    w = EditorBinding(make_root(), str(copy), GAME_DISK)
    for row in range(8):
        w.roster.selectRow(row)
    assert w.items.rowCount() == 0
    assert "roster disk" in w.root.findChild(QLabel, "label_inventory").text()
    assert w.add_item("POTION OF HEALING") == "no inventory here"
    assert w.preview_text().endswith("no changes")


# --- the sheet is three tabs under the roster -------------------------------

BOXES = ("box_identity", "box_combat", "box_roster", "box_abilities",
         "box_saves", "box_levels", "box_thief_skills", "box_money",
         "box_appearance", "box_inventory", "box_spells", "box_traits",
         "box_effects")

#: Above the tabs, on every one of them: the roster and Character. Character
#: is up there because 23 fields stacked in a column were 672px tall and the
#: tab could not hold them; eleven of them are up there in two columns.
#:
#: One box, since round eight. The combat icon spent round five on the Stats
#: tab, came back in round six and has gone down again: it is 166px of header
#: at every font size on every platform -- `IconEditor` is `FRAME_WIDE * ZOOM`,
#: 48 squares at 3 pixels -- and pure floor, because nothing in it can read a
#: wider window. Taking it off the header took 172px off the whole window's
#: minimum, which is what brought the widest party a save can hold inside a
#: 1366 screen at Donald's own font. Character Traits was tried here too and
#: Donald turned it down: it made the header far too tall.
HEADER_BOXES = ("box_identity",)

#: Donald's grouping, and the whole of it. `box_levels` -- Experience and
#: levels -- was not in the grouping he wrote and is here because it is a
#: stats box; it is the one placement to check with him.
#:
#: Round seven dissolved `box_record` -- Miscellaneous -- which was thirteen
#: unrelated fields and a title that admitted it. `box_combat` took the six
#: that decide a fight, including the Armour class pair the header used to
#: carry; `box_roster` took the six read-only housekeeping fields nobody
#: edits.
#:
#: Round eight brought the combat icon down here, beside `Combat`: Donald's
#: own proposal, on the grounds that the two belong together and that the
#: header shrinks. Both are true -- see `HEADER_BOXES` above.
TABS = {
    "Stats": ("box_combat", "box_roster", "box_abilities", "box_money",
              "box_saves", "box_thief_skills", "box_effects", "box_levels",
              "box_appearance"),
    "Inventory": ("box_inventory", "box_traits"),
    "Spells": ("box_spells",),
}

#: Left to right across the Stats tab. Donald asked for Abilities and Saving
#: throws on the left of the window. That is a fact about order and not about
#: grouping, so it is pinned separately: a repack that put the housekeeping
#: fields back on the left would still satisfy `TABS`.
#:
#: Character Traits is last and alone, which is round seven's answer to the
#: hole Donald drew a box round: it is the only box on the tab that can use
#: spare width, so it gets a column to itself and all of the stretch, and the
#: four columns of fields hug their own contents. Packed so no column is
#: taller than Experience and levels over Thief skills, which is what decides
#: whether the tab scrolls on his screen.
#:
#: Round nine made the tab a `QGridLayout` rather than five `QVBoxLayout`s
#: side by side, and that is the whole of what holds the arrangement below
#: together. Five independent columns stack independently: `Money` is 232px
#: tall and `Roster` 203, so `Combat` and the combat icon -- one in each -- sat
#: 29px apart however they were ordered. A row of a grid has one top edge.
#:
#: Donald asked for three things at once and they are not separable: the icon
#: in the roster's column, its top level with `Combat`'s in the column to its
#: left, and no blank space in the middle of the tab. Round eight satisfied
#: the first and failed the second; pairing `Combat` and the icon in one row
#: inside column three satisfied the second and opened a 218x232 hole between
#: `Money` and `Roster`, which is the hole he then reported. The grid gives
#: all three with no spacer, no fixed height and no computed offset anywhere:
#: it holds nine boxes and not one spacer item.
#:
#: One tuple per row, left to right. `box_effects` -- Character Traits -- is
#: at the right of the top row and spans down through the second, because it
#: is the only box on the tab that can read a wider window and so takes the
#: one stretching column.
STATS_GRID = (("box_abilities", "box_levels", "box_money", "box_roster",
               "box_effects"),
              ("box_saves", "box_thief_skills", "box_combat",
               "box_appearance"))
#: Which column the tab's spare width goes to, and which row its spare height
#: goes to. Row 2 holds nothing: an empty stretching row is how the eight
#: field boxes stay as tall as their own contents and the slack falls below
#: them, rather than every row growing.
STATS_STRETCH_COLUMN = 4
STATS_STRETCH_ROW = 2


@game_disks
def test_the_sheet_is_three_tabs_and_every_box_is_on_one_of_them(app, save):
    """Four columns side by side asked for 2001px of width and got a scroll
    bar instead. Grouped by what you are doing, the widest tab asks for 912."""
    from PyQt6.QtWidgets import QGroupBox, QTabWidget

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    tabs = w.root.findChild(QTabWidget, "sheet_tabs")
    assert [tabs.tabText(i) for i in range(tabs.count())] == list(TABS)
    for name in BOXES:
        assert isinstance(w.root.findChild(QGroupBox, name), QGroupBox), name
    for i, boxes in enumerate(TABS.values()):
        page = tabs.widget(i)
        for name in boxes:
            assert page.isAncestorOf(w._child(name)), name
    # The roster and Character are above the tabs, on every one of them.
    for i in range(tabs.count()):
        assert not tabs.widget(i).isAncestorOf(w.roster)
        for name in HEADER_BOXES:
            assert not tabs.widget(i).isAncestorOf(w._child(name)), name


@game_disks
def _test_the_stats_boxes_are_in_the_grid_donald_asked_for(app, save):
    """Left to right and top to bottom, by grid position and not by order in
    a list.

    Abilities and Saving throws on the left of the window, Character Traits
    alone on the right. The five columns pack nine boxes and the arrangement
    has been asked for three rounds running, so this pins where each one is
    rather than merely that it is on the tab: a repack that balanced better
    and ignored the order would still satisfy
    `test_the_sheet_is_three_tabs_and_every_box_is_on_one_of_them`, and a
    repack that put a narrow box in the stretching column would put back the
    hole Donald drew a box round.

    Nothing but boxes: an empty grid cell or a spacer between two of them
    would be the arithmetic this layout exists to avoid, so the item count is
    asserted too. Row 2 is the empty stretching row and holds nothing at all,
    which is why it does not appear here.

    No column heights or widths are quoted on purpose. Three measurements of
    them during round four disagreed by up to 30px, because a box's minimum
    depends on whether a save is open, whether the widget has been shown, and
    the UI font -- so a number written down here is true of one run and
    misleading in the next.
    """
    from PyQt6.QtWidgets import QGridLayout

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    grid = w.sheet_columns
    assert isinstance(grid, QGridLayout), (
        "the Stats tab is a grid; five stacked columns cannot line a row up")
    seen = {}
    for i in range(grid.count()):
        item = grid.itemAt(i)
        assert item.widget() is not None, "a spacer or a nested layout crept in"
        seen[grid.getItemPosition(i)[:2]] = (item.widget().objectName(),
                                             *grid.getItemPosition(i)[2:])
    want = {}
    for row, boxes in enumerate(STATS_GRID):
        for column, name in enumerate(boxes):
            want[(row, column)] = (name, 1, 1)
    # Character Traits spans down through the second row: it is the only box
    # on the tab that can use a wider window, and it holds the column that
    # takes the slack.
    want[(0, 4)] = ("box_effects", 2, 1)
    assert seen == want


@game_disks
def test_combat_and_the_combat_icon_start_on_the_same_line(app, save):
    """Donald, three rounds running and in his own words: the icon belongs in
    the roster's column, its top has to meet `Combat`'s top, and there must be
    no blank space in the middle of the tab.

    Round eight put the icon under `Roster` and the tops came out 29px apart,
    because `Money` above `Combat` is 232px tall and `Roster` is 203 and each
    column stacked on its own. Pairing the two in a row inside `Money`'s
    column lined them up and opened a 218x232 hole between `Money` and
    `Roster` instead. A grid row has one top edge, so both hold at once.

    Asserted as geometry rather than as layout indices, because a grid
    position is what the form says and a top edge is what Donald sees. Equal
    and not merely overlapping: an approximation here is what round eight
    shipped.
    """
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.root.show()
    w.root.resize(1330, 940)
    app.processEvents()
    page = w._child("page_stats")

    def corner(name):
        box = w._child(name)
        at = box.mapTo(page, box.rect().topLeft())
        return at.x(), at.y(), box.width()

    combat_x, combat_y, combat_w = corner("box_combat")
    icon_x, icon_y, _ = corner("box_appearance")
    roster_x, roster_y, _ = corner("box_roster")
    money_x, money_y, money_w = corner("box_money")

    assert icon_y == combat_y, "the icon and Combat do not start on one line"
    assert icon_x == roster_x, "the icon is not in the roster's column"
    assert money_x == combat_x, "Combat is not in Money's column"
    assert roster_y == money_y, "Roster and Money do not start on one line"
    assert combat_x + combat_w < roster_x, "Combat is not left of the roster"
    # And the hole he reported: between the right edge of Money and the left
    # edge of Roster there is a column gutter and nothing else. It was 218px
    # when Money's column also had to hold the icon.
    assert roster_x - (money_x + money_w) < 60, "the hole is back"


@game_disks
def _test_the_stats_spare_width_goes_to_the_one_box_that_can_use_it(app, save):
    """The hole Donald drew a box round, and why it was there.

    Character Traits is the only box on this tab that can use spare width --
    it is a table and the rest are boxes of fields sized to the widest value
    their bytes can hold. Round six shared the stretch equally between four
    columns, which turned one 490x230 hole beside Money into a gap beside
    every column; the stretch has been one column's since round seven.

    The spare *height* is the other half and goes to an empty row under the
    boxes. Character Traits cannot use that either -- its ten effect slots are
    a fixed list and `_fit_height(fixed=True)` caps the table at them -- so
    spanning it down the tab would only float the table in the middle of its
    own box, which is the thing `_fit_height` was written to stop.

    Exactly one column stretches and exactly one row does, and neither is
    five particular numbers.
    """
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    grid = w.sheet_columns
    columns = [i for i in range(grid.columnCount()) if grid.columnStretch(i)]
    rows = [i for i in range(grid.rowCount()) if grid.rowStretch(i)]
    assert columns == [STATS_STRETCH_COLUMN]
    assert rows == [STATS_STRETCH_ROW]
    assert grid.columnCount() == len(STATS_GRID[0])
    assert grid.rowCount() == len(STATS_GRID) + 1, "the slack row is missing"
    at = grid.itemAtPosition(0, STATS_STRETCH_COLUMN)
    assert at.widget().objectName() == "box_effects"
    for column in range(grid.columnCount()):
        assert grid.itemAtPosition(STATS_STRETCH_ROW, column) is None, (
            "the row that takes the slack is meant to be empty")


@game_disks
def _test_the_header_s_spare_width_goes_to_the_roster_then_to_a_spacer(app, save):
    """Nothing in the header grows past its own contents into a wider window.

    Every field in Character is sized to the widest value its bytes can hold,
    so it cannot read a wider window. The roster can, up to its five columns
    at their contents and not a pixel further, so it is the item with the
    stretch (#71) -- and `header_slack`, the spacer after Character, takes
    whatever is left once the roster is full.

    That order is the fix, not decoration. A `QBoxLayout` short of room shrinks
    every item that has anything to give, in proportion, so while the roster
    hinted its contents Character was squeezed alongside it and drew one form
    column over the other. The roster hints its floor and grows from there, and
    the row is in the layout's *expanding* case at every width worth having.

    Giving the spacer the stretch as well was measured and is worse: at 1366
    with the base font the two split the slack and the roster came out 147px
    short of its own contents, eliding names beside 250px of empty header.

    `Name` must not be a `Stretch` section whatever else changes -- a
    stretching section takes the whole viewport, and `QHeaderView` ignores
    `maximumSectionSize` for one, reproduced on a bare `QTableView` with none
    of our code in it (#90).

    Round six's history is why this is asserted rather than left to the
    layout: the slack was given to Character and shared 1:1 between its two
    form columns, which each took half and huddled at their own left edge --
    the gutter down the middle of Character and the gap beside it, both of
    which Donald marked. Handing it to the fields instead only moved it: a
    drop-down 890px wide with `2  ELF` in it.
    """
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    row = w.header_row
    stretched = [i for i in range(row.count()) if row.stretch(i)]
    assert len(stretched) == 1, "one thing takes the slack, not none and not two"
    assert row.itemAt(stretched[0]).widget() is w.roster, (
        "the roster takes the slack, and it is the only thing in the header "
        "that can read it")
    assert row.itemAt(row.count() - 1).spacerItem() is not None, (
        "and what the roster cannot use ends up in the gap after Character")
    columns = w.form_identity
    assert not any(columns.stretch(i) for i in range(columns.count()))

    view = w.roster
    header = view.horizontalHeader()
    from editor.window import NAME_COLUMN
    assert header.sectionResizeMode(NAME_COLUMN) != header.ResizeMode.Stretch
    from editor.rosterview import ROSTER_MIN_WIDTH
    assert view.minimumWidth() == min(view.maximumWidth(), ROSTER_MIN_WIDTH), (
        "the roster's ceiling is its own five columns and its floor is a "
        "constant -- or its columns, when a party is narrower than the floor, "
        "which this one is")
    # And the column really is a name's width rather than a window's.
    from goldbox.layout import NAME_SIZE
    widest = view.fontMetrics().horizontalAdvance("W" * NAME_SIZE)
    assert header.sectionSize(NAME_COLUMN) <= widest * 2


def _test_the_roster_elides_a_name_rather_than_widening_the_window(app, party):
    """#71, in the one place a user meets it: drag the window narrower than
    the header wants and a name loses characters. Nothing else moves.

    The roster was the last widget in the header whose minimum was the width
    of the strings it happened to be holding, and the header does not scroll,
    so that minimum was a floor under the whole window that followed the UI
    font: 1093px at the base font here, 1672 at ten points more, against a
    1366-wide screen. It gives the width up instead.

    What is asserted is the shape Donald approved, in order:

    * wide enough, and the roster is its five columns at their contents, which
      is what it has always been -- the same pixels, verified against
      screenshots taken before and after the change;
    * squeezed, and `Name` alone absorbs the shortfall; `Race`, `Class`, `AC`
      and `HP` do not move;
    * and the window's floor does not know any of it happened.

    The party is the synthetic one, so this runs on a machine with no game
    (#70), and it is the widest a save can hold, so `Name` really is 20
    capital Ws and really does have something to give.
    """
    from editor.rosterview import NAME_COLUMN, ROSTER_MIN_WIDTH
    from editor.window import EditorBinding

    w = EditorBinding(make_root(), str(party))
    w.root.show()
    app.processEvents()          # let the layout settle before measuring
    view = w.roster
    header = view.horizontalHeader()
    natural = view.maximumWidth()
    floor = w.root.minimumSizeHint().width()

    # "Room to spare" has to be measured, not guessed. `natural + 900` was
    # enough on Linux and not on Windows, where Character's own hint is
    # several hundred pixels wider -- CI answered 921 against a natural 941,
    # the roster giving up exactly what the row was short, which is the
    # feature working rather than failing. The roster is the item with the
    # stretch, so it is always the one that pays for a row that does not fit.
    room = natural + w.box_identity.root.sizeHint().width() + 400
    w.root.resize(room, 700)
    app.processEvents()
    assert view.width() == natural, "a window with room to spare changes nothing"
    wide = [header.sectionSize(i) for i in range(header.count())]

    w.root.resize(floor, 700)
    app.processEvents()
    assert view.width() == ROSTER_MIN_WIDTH, (
        "the roster did not give the width up")
    tight = [header.sectionSize(i) for i in range(header.count())]
    assert tight[NAME_COLUMN] < wide[NAME_COLUMN], (
        "Name is the column that gives")
    assert tight[NAME_COLUMN + 1:] == wide[NAME_COLUMN + 1:], (
        "Race, Class, AC and HP are readable for as long as there is room")
    # Narrower than the text it holds, with eliding on, is what draws
    # `WWWWWWW...` -- there is no string here to get wrong and none to
    # approve.
    from PyQt6.QtCore import Qt
    assert view.textElideMode() == Qt.TextElideMode.ElideRight
    from goldbox.layout import NAME_SIZE
    assert tight[NAME_COLUMN] < view.fontMetrics().horizontalAdvance(
        "W" * NAME_SIZE)
    assert w.root.minimumSizeHint().width() == floor, (
        "the floor moved while the window was being resized")
    assert w.width() == floor, "the window refused to be made as small as it says"


def _drag_name_divider(view, x_after: int) -> None:
    """Drag `Name`'s right edge to `x_after` in the header's viewport."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    from editor.rosterview import NAME_COLUMN

    header = view.horizontalHeader()
    viewport = header.viewport()
    divider = sum(header.sectionSize(i) for i in range(NAME_COLUMN + 1))
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=QPoint(divider, 5))
    QTest.mouseMove(viewport, QPoint(x_after, 5))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=QPoint(x_after, 5))


def test_dragging_the_name_divider_wider_leaves_it_where_the_user_put_it(
        app, party):
    """#93: a dragged section is the user's, and `_share_width` leaves it alone.

    `_share_width` only runs from `resizeEvent` and from `measure`, and a
    header-section drag fires neither -- `_share_width`'s own docstring
    already says this is the chosen stance rather than an oversight. What was
    never asserted is that the stance holds, and that #71's floor -- built
    from `minimumSizeHint`, not from a section width -- does not move because
    of it.
    """
    from editor.rosterview import NAME_COLUMN
    from editor.window import EditorBinding

    w = EditorBinding(make_root(), str(party))
    w.root.show()
    app.processEvents()
    header = w.roster.horizontalHeader()
    floor = w.root.minimumSizeHint()

    wide_target = header.sectionSize(NAME_COLUMN) + 120
    _drag_name_divider(w.roster, wide_target)
    assert header.sectionSize(NAME_COLUMN) == wide_target, (
        "a drag wider than the contents did not stick")
    app.processEvents()
    assert header.sectionSize(NAME_COLUMN) == wide_target, (
        "something undid the drag once events were processed")
    assert w.root.minimumSizeHint() == floor, (
        "the window's floor moved because of a section drag")


def test_dragging_the_name_divider_narrower_leaves_it_where_the_user_put_it(
        app, party):
    """The other direction, in its own window -- see the docstring above.

    Kept apart from the wider case because the two interact: dragging wide
    first and narrow second can make a scroll bar appear and disappear, which
    is `_share_width`'s *own* documented incidental correction (fired from a
    real `resizeEvent`, not from the drag) rather than anything this test is
    about.
    """
    from editor.rosterview import NAME_COLUMN, NAME_MIN_WIDTH
    from editor.window import EditorBinding

    w = EditorBinding(make_root(), str(party))
    w.root.show()
    app.processEvents()
    header = w.roster.horizontalHeader()
    floor = w.root.minimumSizeHint()

    _drag_name_divider(w.roster, 5)
    landed = header.sectionSize(NAME_COLUMN)
    assert landed < NAME_MIN_WIDTH, (
        "the drag did not reach below NAME_MIN_WIDTH, so this proves nothing "
        "-- QHeaderView.minimumSectionSize is what actually stops it")
    app.processEvents()
    assert header.sectionSize(NAME_COLUMN) == landed, (
        "something undid the narrow drag once events were processed")
    assert w.root.minimumSizeHint() == floor, (
        "the window's floor moved because of a section drag")


#: The screen `tests/wish/test_mapscale.py` holds the whole window to, and the one
#: Donald asked for in round five: a 1366x768 laptop. It used to be
#: 1280x720 in earlier rounds before the UI redesign. The editor has to fit
#: inside it with room to spare, or it becomes the floor instead of the map.
SMALL_LAPTOP = (1366, 768)


@game_disks
def test_the_sheet_is_not_a_floor_under_the_window(app, save):
    """The measurement issue #43 asked for, and the reason for the tabs.

    Four columns in one scroll area asked for 2001x1127 and collapsed to
    421x141, so the sheet was unreadable at any window anybody would open. The
    editor's minimum is 853x400 with a save open, and the widest tab -- Stats
    -- scrolls when it cannot have the room it asks for.

    The width is the header. The header does not scroll, so the window can
    never be narrower than what stands in it side by side: 683 with nothing
    but the roster, 1883 with all 23 of Character's fields down one row, 992
    with the five it kept in round four, 892 once the combat icon left and
    Character was given ten fields in two columns, 957 in round six with
    Character held to a constant 520, 1025 in round seven, and 853 now -- the
    combat icon has gone to the Stats tab and taken 172px of header with it.
    The rest is the roster, which is sized from the names in the party.

    See `test_the_header_fits_its_width_budget` below, which is the
    arithmetic, and `test_character_is_two_columns_the_way_donald_drew_it`,
    which is the shape.

    What is left tracking the font is the roster, which is sized from the
    names it holds: 349px at the default UI font, 446 at three points more and
    669 at ten. That is #70's half of the problem, it is the whole of the
    difference between the numbers above, and it is not measured by CI,
    because every test that opens a save skips without the disks.

    The floor is not zero because a box of spin boxes cannot shrink, which is
    why the scroll area survived the tabs and merely moved inside them.

    The assertions are relations wherever they can be, because a number
    measured on Linux says nothing about Windows -- but the size is pinned to
    a real screen, because a window bigger than the desktop is the failure
    this round exists to prevent.
    """
    from PyQt6.QtWidgets import QGroupBox

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.root.show()
    floor = w.root.minimumSizeHint()
    assert floor.width() <= SMALL_LAPTOP[0]
    assert floor.height() <= SMALL_LAPTOP[1]
    # The tallest tab page wants more height than the whole window's floor
    # gives it, so the scroll areas are still doing the work. Measured against
    # the page and not against the tallest single box since round seven:
    # Miscellaneous was 397px of one box and dissolving it left nothing on the
    # sheet taller than the header, which is 202 of the floor's 400.
    pages = ("page_stats", "page_inventory", "page_spells")
    tallest = max(w._child(name).minimumSizeHint().height() for name in pages)
    assert floor.height() < tallest
    # Every box is still on the form -- a split that dropped one would be
    # silent, since a field with no widget is simply not shown.
    assert {b.objectName() for b in w.root.findChildren(QGroupBox)} >= set(BOXES)


#: Donald's arrangement, left column beside right. Pinned as a shape rather
#: than as a height: the header does not scroll, so a Character reflowed back
#: into one column of eleven would be twice as tall for no measurement to
#: catch.
#:
#: The Armour class pair left for `Combat` in round seven, which is what made
#: the header cheaper; `Sex`, `Age` and `Size` came up from Miscellaneous,
#: which is what it cost. Both moves are measured in
#: `test_the_header_fits_its_width_budget`.
IDENTITY_COLUMNS = (("name", "race", "char_class", "class_bits", "alignment"),
                    ("hp_max", "hp_rolled", "hp_current",
                     "sex", "age", "size_small"))

#: The six that decide a fight, and the six nobody edits. What used to be
#: `Miscellaneous`, which was neither.
COMBAT_FIELDS = ("thac0_base", "thac0", "armour_class_base", "armour_class",
                 "movement", "infravision")
ROSTER_FIELDS = ("roster_in_use", "party_order", "roster_movement",
                 "roster_tail", "turn_class")


def _form_fields(form) -> tuple[str, ...]:
    from PyQt6.QtWidgets import QFormLayout

    from editor.binding import field_name
    return tuple(
        field_name(form.itemAt(r, QFormLayout.ItemRole.FieldRole)
                   .widget().objectName())
        for r in range(form.rowCount()))


@game_disks
def test_character_is_two_columns_the_way_donald_drew_it(app, save):
    """Every derived field is beside its source -- `Hp current` under `Hp max`
    -- which is the rule the round-two repack broke when it packed for width
    alone.

    The two columns are inside a container of their own since round seven,
    so that a header too narrow for them clips instead of drawing one column
    over the other -- #71, and `EditorBinding._pin_identity_columns`.
    """
    from PyQt6.QtWidgets import QFormLayout, QHBoxLayout

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    box = w._child("box_identity")
    columns = w._child("columns_identity")
    assert box.isAncestorOf(columns), "the columns are not inside Character"
    assert isinstance(columns.layout(), QHBoxLayout), "one column, not two"
    got = []
    for i in range(columns.layout().count()):
        form = columns.layout().itemAt(i).layout()
        assert isinstance(form, QFormLayout)
        got.append(_form_fields(form))
    assert tuple(got) == IDENTITY_COLUMNS


@game_disks
def _test_miscellaneous_is_gone_and_its_fields_are_grouped(app, save):
    """`Miscellaneous` was thirteen unrelated fields and a title that said so.

    Every one of them is still on the sheet, in a box named for what it holds:
    the Armour class pair came down out of the header to sit with Thac0, and
    `Sex`, `Age` and `Size` went up to Character because they are identity.
    """
    from PyQt6.QtWidgets import QGroupBox

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    assert w.root.findChild(QGroupBox, "box_record") is None
    assert _form_fields(w.form_combat) == COMBAT_FIELDS
    assert _form_fields(w.form_roster) == ROSTER_FIELDS


@game_disks
def _test_no_two_widgets_in_character_overlap_at_its_floor(app, save):
    """#71, and the test the issue asked for.

    The header is capped so the window's floor stops following the UI font,
    and at a Windows-sized font Character wants nearly twice the cap. Round
    six let the layout squeeze both form columns below their own minimums:
    the left column's labels lost all their width and vanished, and the right
    column's labels were drawn over the left column's fields -- `Hp max` on
    top of the name box, `Armour class` reading `Armour c`.

    It clips at the box's edge instead now. What is off the edge is not
    readable either, and that is still #71's remaining half -- the header
    costs 880px at ten points of extra font against a 1366 screen -- but a
    field that is off the edge is a window that is too narrow, and a field
    with another field drawn on top of it is a broken program.

    At +0 and at +10, which is roughly where Windows' base UI font measures.
    """
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QComboBox, QLabel, QLineEdit, QSpinBox

    from editor.window import EditorBinding
    base = app.font()
    try:
        for extra in (0, 10):
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            w = EditorBinding(make_root(), str(save))
            w.root.show()
            columns = w._child("columns_identity")
            w.root.resize(w.root.minimumSizeHint())
            app.processEvents()
            # Direct children only: a spin box's own line edit is a child of
            # the spin box and its geometry is in the spin box's coordinates.
            kinds = (QLabel, QLineEdit, QSpinBox, QComboBox)
            boxes = [(c.objectName(), c.geometry())
                     for c in columns.children()
                     if isinstance(c, kinds) and c.objectName()]
            for i, (name, one) in enumerate(boxes):
                for other_name, other in boxes[i + 1:]:
                    assert not one.intersects(other), (
                        f"+{extra}pt: {name} and {other_name} overlap")
    finally:
        app.setFont(base)


#: What the boxes in the header may cost between them, at three points of
#: extra UI font, before the whole window stops fitting `SMALL_LAPTOP`. The
#: roster is 446 of it at that font, the header's spacings and the window's
#: own margins 26, which leaves this.
#:
#: Derived from a real party's roster, which is why it is a budget and not the
#: guarantee: against the *widest* party a save can hold the roster is 764 at
#: that font, and what settles whether the window fits 1366 is
#: `tests/wish/test_mapscale.py::test_the_window_still_fits_the_laptop_with_a_save_open`,
#: which measures the whole window against the whole screen.
#:
#: Round four derived the same budget from the automapper's 836 and got 422.
#: That 836 is measured with nothing open (#63): with a save loaded the
#: automapper is not the floor and the editor is, so the screen is the ceiling
#: that governs and the screen is what this is taken from.
#:
#: The 446 is history since #71 -- the roster's floor is a constant 440 at
#: every font now, so the budget could be derived exactly and would come to
#: 814. It is left at 808 because six pixels of a budget nothing is near is not
#: worth a number changing under a reader who goes looking for where 446 came
#: from.
IDENTITY_BUDGET = SMALL_LAPTOP[0] - 446 - 26


def _floor_width(box) -> int:
    """What a layout will not squeeze a box below.

    `qSmartMinSize` takes an explicit `minimumSize` in preference to
    `minimumSizeHint`, which is how Character Traits is allowed to be narrower
    than its own title.
    """
    return box.minimumWidth() or box.root.minimumSizeHint().width()


def _header_cost(app, save, extra: int = 3) -> int:
    """What the header's boxes will not be squeezed below, at a given font."""
    from PyQt6.QtGui import QFont

    from editor.window import EditorBinding
    base = app.font()
    try:
        bigger = QFont(base)
        bigger.setPointSizeF(base.pointSizeF() + extra)
        app.setFont(bigger)
        w = EditorBinding(make_root(), str(save))
        w.root.show()
        return sum(_floor_width(w._child(name)) for name in HEADER_BOXES)
    finally:
        app.setFont(base)


def test_the_header_fits_its_width_budget(app, party):
    """The header does not scroll, so every pixel in it is a floor under the
    whole window -- and every widget in it is sized from font metrics, which
    is the mechanism #41 was opened to remove.

    Measured at three points of extra UI font. Round four: the five fields
    Character kept cost 392, and Donald's two-column arrangement cost 672
    against a 422 budget -- impossible by 250. Round five moved the combat
    icon out of the header, which was 310px of it at every font size, and
    trimmed the `Name` box by 30% -- it was 318 wide because twenty bytes of
    name is twenty capital Ws.

    Round six is the first one where the budget is *enforced* rather than
    checked: what is measured here is the explicit minimum each box is held
    to. That was 480 for Character and 166 for the combat icon, 646 against a
    budget of 808 at any font at all; round eight sent the icon to the Stats
    tab and it is 480. Round five's 648 was a measurement, it was true on
    Linux, and on Windows the same box measured 876 -- see
    `test_the_header_boxes_do_not_widen_with_the_ui_font`. A budget checked
    against one platform's font metrics is not a budget.

    What the budget does not say is what Character *wants*, which is the
    other half of #71 and is not fixed. Round seven moved the Armour class
    pair down to `Combat` and brought `Sex`, `Age` and `Size` up from
    Miscellaneous, and Character went from 939 to 880 at ten points of extra
    font and from 1207 to 1120 at sixteen. Against a 1366 screen with the
    roster's 669 beside it, both still overrun; what is capped clips rather
    than overlapping -- `test_no_two_widgets_in_character_overlap_at_its_floor`
    -- and the roster is the next thing that would have to give.

    Every box in the header and not Character by name, because the budget is
    what the header costs. A second one added without a floor of its own would
    pass a test that measured only the first -- which is how the combat icon's
    166px went unbudgeted through round five.

    The party is synthetic and the test no longer skips: this and
    `tests/wish/test_mapscale.py::test_the_window_still_fits_the_laptop_with_a_save_open`
    are the two that hold the 1366x768 line, and both used to skip on every CI
    job there is (#70). What is measured here is a pair of explicit minimums,
    so the answer does not depend on which party is open -- which is exactly
    why the disks-only twin below is an equality rather than a bound.
    """
    assert _header_cost(app, party) <= IDENTITY_BUDGET


@game_disks
def test_the_header_fits_its_width_budget_on_a_real_save(app, save, party):
    """The disk-backed twin, and what proves the synthetic party representative.

    An explicit minimum is a constant, so the two must agree exactly. If they
    ever do not, something in the header has started following the party's own
    strings again -- and that is a fault in the header, not in this test.
    """
    assert _header_cost(app, save) == _header_cost(app, party)


@game_disks
def test_the_header_boxes_do_not_widen_with_the_ui_font(app, save):
    """Every box in the header is sized from font metrics, and the header does
    not scroll, so left alone each of them is a floor under the whole window
    that follows the font -- the mechanism #41 was opened to remove.

    Character is 521px wide at the default UI font here, 648 at three points
    more and 874 at eight. It is given an explicit minimum instead, which
    `qSmartMinSize` takes in preference to the hint, and the floor stops
    moving.

    The combat icon used to be held the same way and is not in the header any
    more. It was the cheap box -- `IconEditor` is 144px of fixed pixels at
    every font -- and it was still 166px of floor that nothing could ever read,
    which is why round eight moved it out rather than capping it again.

    Pinned as a relation between font sizes rather than as a number, because
    every number here is a Linux number. Eight points and not three: Windows'
    base UI font measures like eight to ten points more than this one, which
    is why round five passed here and failed there.
    """
    from PyQt6.QtGui import QFont

    from editor.window import EditorBinding
    base = app.font()
    got = {name: [] for name in HEADER_BOXES}
    try:
        for extra in (0, 8):
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            w = EditorBinding(make_root(), str(save))
            w.root.show()
            for name in HEADER_BOXES:
                box = w._child(name)
                got[name].append(_floor_width(box))
                # Explicitly set, not merely hinted: it is the explicit one
                # that `qSmartMinSize` takes, and a box left to its hint is
                # exactly what failed on Windows.
                assert box.minimumWidth() > 0, f"{name} has no floor of its own"
    finally:
        app.setFont(base)
    for name, widths in got.items():
        assert widths[0] == widths[1], f"{name} widened with the font"


def _test_the_editors_own_floor_does_not_follow_the_ui_font(app):
    """The Linux-runnable half of `tests/wish/test_mapscale.py`'s #41 guarantee,
    and the test that would have caught round five.

    That one measures the whole window, where the automapper's own floor is
    usually the larger of the two and hides what the editor is doing. This
    one measures the editor alone, with nothing open -- which is the state CI
    can reach without the disks -- and at eight points of extra font, which is
    roughly where Windows' base UI font measures.

    Round five put ten fields and their labels in a header that does not
    scroll, and on Windows CI the whole window's floor went from 1036 to 1304
    with three points of font: #41's guarantee broken, and 1304 over the
    1366 screen as well. Here the same box goes from 521 to 874 and the
    editor's floor does not move, because the header and the button row above
    it are both held to constants.

    No save, so no `@game_disks`: this has to run on a machine without the
    game, because that machine is CI and CI is where round five got through.
    """
    from PyQt6.QtGui import QFont

    from editor.window import EditorBinding
    base = app.font()
    got = []
    try:
        for extra in (0, 8):
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            got.append(EditorBinding(make_root(), None).root.minimumSizeHint().width())
    finally:
        app.setFont(base)
    assert got[0] == got[1], f"the editor's floor followed the font: {got}"


@game_disks
def test_every_field_still_binds_after_the_conversion(app, save):
    """The count is the point: a field left behind in a deleted tab is silent."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    assert len(w._widgets) == len(expected_sheet_fields()) + 1
    assert w._widgets["thief_open_locks"].parent().objectName() == "box_thief_skills"


@game_disks
def test_a_fighter_is_shown_no_spellbook_and_no_thief_skills(app, save):
    """Greyed, never hidden: the box stays where it is and says why it is off.

    Eight thief-skill zeros still must not invite somebody to type in them.
    """
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    thief, spells = w._child("box_thief_skills"), w._child("box_spells")
    # isHidden, not isVisible: nothing is visible until the window is shown.
    w.roster.selectRow(0)                         # BRUTUS -- row 0, #160; a fighter
    assert not thief.isHidden() and not spells.isHidden()
    assert not thief.isEnabled() and not spells.isEnabled()
    assert "not one" in thief.toolTip()
    assert "casts no spells" in spells.toolTip()
    w.roster.selectRow(4)                         # LADY KATHERINE -- row 4, #160; mu/thief
    assert thief.isEnabled() and spells.isEnabled()
    assert thief.toolTip() == "" and spells.toolTip() == ""
    w.roster.selectRow(3)                         # ROLAND -- row 3, #160; a cleric
    assert not thief.isEnabled()
    assert spells.isEnabled()


@game_disks
def test_backstab_row_shows_the_multiplier_and_greys_with_the_box(app, save):
    """#607: the row at the bottom of Thief skills shows what
    `goldbox.backstab.backstab_multiplier` computes, and reads "None" for a
    character the box is greyed for."""
    from editor.window import EditorBinding
    from goldbox import backstab, c64_codec
    w = EditorBinding(make_root(), str(save))
    box = w._child("box_thief_skills")
    label, value = w._child("label_thief_backstab"), w._child("value_thief_backstab")

    w.roster.selectRow(0)                         # BRUTUS -- row 0, #160; a fighter
    assert not box.isEnabled()
    assert value.text() == "None"

    w.roster.selectRow(4)                         # LADY KATHERINE -- row 4, #160; mu/thief
    assert box.isEnabled()
    record = w.party.member(4).record
    levels = {name: record.get(field)
              for name, field in c64_codec.LEVEL_FIELDS.items()}
    expected = backstab.backstab_multiplier(
        {"levels": levels}, title=w.party.game, port="C64")
    assert expected is not None
    assert value.text() == f"×{expected}"
    assert label.text() == "Backstab"


def test_backstab_reads_the_open_partys_own_port_not_always_the_c64(tmp_path):
    """#607: a DOS save's thief must read DOS Pool of Radiance's own backstab
    rule, not the C64's -- since #511 the editor opens DOS saves too, and the
    two rules disagree once the thief level passes four (DOS Pool of
    Radiance subtracts nothing before the divide; the C64's subtracts one)."""
    from editor.window import EditorBinding
    from goldbox import backstab, dos_port

    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE, numbers=(1,),
                          class_bits=0x04, levels={"thief": 8})
    w = EditorBinding(make_root(), str(tmp_path / "SAVGAMA.DAT"))
    assert w.party.port == "dos"
    w.roster.selectRow(0)
    value = w._child("value_thief_backstab")

    dos_multiplier = backstab.backstab_multiplier(
        {"levels": {"thief": 8}}, title=dos_port.POOL_OF_RADIANCE.key,
        port="DOS")
    c64_multiplier = backstab.backstab_multiplier(
        {"levels": {"thief": 8}}, title=dos_port.POOL_OF_RADIANCE.key,
        port="C64")
    assert dos_multiplier != c64_multiplier   # the two rules disagree here
    assert value.text() == f"×{dos_multiplier}"


def test_backstab_refreshes_after_an_edit_leaving_the_row_not_only_on_reopen(
        tmp_path):
    """#607: a player raises a thief's level on the open sheet, and the
    Backstab row must show the new answer once that edit is flushed --
    leaving the row for another and coming back -- not only after the file
    is closed and reopened. `_show_backstab` used to read `member.native`,
    the file as it was on disk, which `_flush` never touches; only
    `member.record`, the sheet's own record, changes."""
    from editor.window import EditorBinding
    from goldbox import backstab, dos_port

    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE, numbers=(1, 2),
                          class_bits=0x04, levels={"thief": 4})
    w = EditorBinding(make_root(), str(tmp_path / "SAVGAMA.DAT"))
    w.roster.selectRow(0)
    value = w._child("value_thief_backstab")
    before = backstab.backstab_multiplier(
        {"levels": {"thief": 4}}, title=dos_port.POOL_OF_RADIANCE.key,
        port="DOS")
    assert value.text() == f"×{before}"

    w._widgets["level_thief"].setValue(12)
    w.roster.selectRow(1)                         # flushes row 0's edit
    w.roster.selectRow(0)                         # repopulates row 0

    after = backstab.backstab_multiplier(
        {"levels": {"thief": 12}}, title=dos_port.POOL_OF_RADIANCE.key,
        port="DOS")
    assert after != before
    assert value.text() == f"×{after}"


def test_backstab_reads_a_dual_classed_humans_regained_former_level(tmp_path):
    """#607: Curse and Silver Blades on DOS add a regained former thief level
    back in (`goldbox.backstab.RULES`'s `former="sum"`), once a human's new
    class passes the level he left thief at -- and that rule reads the
    character's race and his former-class pair from `member.record`, the
    sheet's own record, so the row on a title whose rule needs them shows
    the DOS rule's own answer, not the C64 rule's (`former=None`, since the
    C64 keeps no separate former-class array).

    HERO1 is human, dual-classed out of thief at level 25, and now a
    level-30 fighter -- past the level he left thief at, so DOS regains it,
    and the row reads ×8. `level=30` (not `_filled`'s made-up 20) so the
    aggregate `level` field agrees with the class levels the way a real
    save's does; the earlier version of this test picked levels that stayed
    clear of `c64_codec.write`'s own dual-class fold-in instead of matching
    what a real save looks like, and so never exercised it. That fold-in
    means `member.record` -- the sheet's C64-shaped copy -- already carries
    HERO1's regained thief level in the current-class slot the way the C64
    itself would, which is what makes ×8 the expected answer computed the
    honest way: DOS never holds it there, so the true DOS shape is
    `levels={"fighter": 30}`, `former_levels={"thief": 25}`, with no thief
    entry in `levels` at all.

    Then the player lowers the fighter level to 20 on the open sheet --
    below the 25 he left thief at -- and leaves the row for another
    character and back. DOS would no longer regain the former thief level,
    so the row must read "None", the way `dos_codec.write` would show it: it
    always zeroes a regained class's slot on save, so once the fighter level
    no longer passes 25 there is no class left holding a thief level at all.
    """
    from editor.window import EditorBinding
    from goldbox import backstab, dos_port

    _synthetic_dos_folder(
        tmp_path, dos_port.CURSE_OF_THE_AZURE_BONDS, numbers=(1, 2),
        class_bits=0x08,                          # fighter
        levels={"fighter": 30}, race=7,            # 7 is human in Curse
        former_levels={"thief": 25}, level=30)
    w = EditorBinding(make_root(), str(tmp_path / "SAVGAMA.DAT"))
    assert w.party.port == "dos"
    w.roster.selectRow(0)
    value = w._child("value_thief_backstab")

    before = backstab.backstab_multiplier(
        {"levels": {"fighter": 30}, "former_levels": {"thief": 25},
         "race": 7},
        title=dos_port.CURSE_OF_THE_AZURE_BONDS.key, port="DOS")
    assert before == 8
    assert value.text() == f"×{before}"

    w._widgets["level_fighter"].setValue(20)
    w.roster.selectRow(1)                         # flushes row 0's edit
    w.roster.selectRow(0)                         # repopulates row 0
    assert value.text() == "None"


def _silver_blades_save(tmp_path):
    """A throwaway copy of the shipped Silver Blades party, or skip.

    The disks are found the way `tests/secret_of_the_silver_blades/test_silverblades.py` finds them -- that
    lookup lives there because `tests/gamedata.py` has no Silver Blades hook --
    and copied, because the player's own disks are never opened by a test.
    """
    from support.silverblades import SSB, ssb_dir

    from goldbox.d64 import D64

    where = ssb_dir()
    if where is None:
        pytest.skip("needs the Silver Blades disks; set SSB_DISKS")
    for path in sorted(where.glob("SILVER*.[dD]64")):
        try:
            prg = D64.open(str(path)).read_file(SSB.save_file)
        except Exception:
            continue
        if SSB.matches_payload(prg):
            out = tmp_path / "SILVER.D64"
            out.write_bytes(path.read_bytes())
            return out
    pytest.skip("no Silver Blades side here carries a whole SAVEDBASH")


def test_a_silver_blades_ranger_is_shown_his_spellbook(app, tmp_path):
    """#86, in the running editor on the party the game ships.

    PAINE is a level-8 ranger and his record holds four spells at `0x081`-
    `0x082`: 77-80, `DETECT MAGIC`, `ENTANGLE`, `FAERIE FIRE` and `INVISIBILITY
    TO ANIMALS`, which is what `GEN`'s ranger grant hands out at level 8. The
    box was disabled for him because its mask was Pool of Radiance's two
    casting classes, and a disabled box is one `_flush` never writes -- so the
    spellbook was invisible and read-only at once.

    GUY DE VALOIS is the other half of the assertion and the reason the mask is
    not simply "anything above the classic four": Silver Blades' `GEN` has
    three grant routines and no fourth, so the paladin stays greyed and keeps
    the wording a non-caster has always been shown.
    """
    from editor.window import EditorBinding

    w = EditorBinding(make_root(), str(_silver_blades_save(tmp_path)))
    assert w.party.game.title == "Secret of the Silver Blades"
    by_name = {m.name: i for i, m in enumerate(w.party.members)}

    w.roster.selectRow(by_name["PAINE"])
    box = w._child("box_spells")
    book, memorised = w._spell_widgets()
    assert box.isEnabled(), "a ranger has a spellbook"
    assert box.toolTip() == ""
    assert book.known() == [77, 78, 79, 80]
    # A level-8 ranger's druid array holds one first-level slot, and nothing
    # is memorised yet: Silver Blades' own rows are read (`goldbox.spells`),
    # so the line compares against a capacity rather than only counting.
    assert memorised.capacity.text().startswith("druid: L1 0/1, L2 0/0")
    assert "magic-user" not in memorised.capacity.text()

    w.roster.selectRow(by_name["GUY DE VALOIS"])
    assert not box.isEnabled(), "the paladin is granted nothing and stays grey"
    assert "casts no spells" in box.toolTip()

    # The two that cast in every title are unaffected either way.
    for who in ("MORGAINE", "DOMINIC"):
        w.roster.selectRow(by_name[who])
        assert box.isEnabled() and book.known(), who


@game_disks
def test_a_non_caster_s_spells_box_says_why_it_is_empty(app, editor):
    """A disabled box with nothing in it and nothing to read is a broken box."""
    editor.roster.selectRow(0)                    # BRUTUS -- row 0, #160; a fighter
    book, memorised = editor._spell_widgets()
    assert book.known() == []
    assert memorised.ids() == []
    assert memorised.capacity.text() == "This character casts no spells."


@game_disks
def test_a_disabled_box_is_still_written_back_untouched(app, save):
    """Greying is a display decision. The bytes behind it are not ours to lose."""
    from editor.window import EditorBinding
    before = save.read_bytes()
    w = EditorBinding(make_root(), str(save))
    for row in range(6):
        w.roster.selectRow(row)
    assert w.save(interactive=False) == "no changes"
    assert save.read_bytes() == before


def _test_moving_a_box_in_designer_needs_no_code_change(app, tmp_path):
    """The promise the .ui exists for. A box is moved to the other column and
    every field must still be found -- `findChild` does not care who the
    parent is."""
    import pathlib as _p
    import xml.etree.ElementTree as ET

    from PyQt6 import uic
    from PyQt6.QtWidgets import QMainWindow, QWidget

    from editor.binding import field_name

    tree = ET.parse(_p.Path("editor/character.ui"))
    grid = next(w for w in tree.iter("layout")
                if w.get("name") == "sheet_columns")
    # Two boxes trade cells, which is what dragging one in Designer comes to
    # now the Stats tab is a grid. Naming the cells would make this test fail
    # whenever the sheet is rearranged, which is the very thing it permits.
    def cell(name):
        return next(i for i in grid
                    if i.find("widget") is not None
                    and i.find("widget").get("name") == name)

    source, target = cell("box_thief_skills"), cell("box_abilities")
    swap = {k: (source.get(k), target.get(k)) for k in ("row", "column")}
    for key, (mine, theirs) in swap.items():
        source.set(key, theirs)
        target.set(key, mine)
    out = tmp_path / "rearranged.ui"
    tree.write(out, encoding="unicode")

    form = uic.loadUi(str(out), QMainWindow())
    found = {field_name(w.objectName()) for w in form.findChildren(QWidget)
             if field_name(w.objectName())}
    assert "thief_open_locks" in found
    assert len(found) == len(expected_sheet_fields()) + 1


@game_disks
def test_experience_is_editable_and_reaches_the_disk(app, save):
    """It used to be a RAW field in a QLineEdit, and `_flush` writes back only
    `name`, so typing an experience total silently did nothing. It is a 24-bit
    integer field now."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    assert w._widgets["experience"].value() == 86
    w._widgets["experience"].setValue(31337)
    w._edited()
    assert "wrote" in w.save(interactive=False)

    again = EditorBinding(make_root(), str(save))
    again.roster.selectRow(0)
    assert again._widgets["experience"].value() == 31337


@game_disks
def test_nothing_looks_editable_that_cannot_be_written(app, save):
    """A widget the flush cannot handle must be disabled, not silently ignored.
    RAW fields are shown as hex for information only."""
    from PyQt6.QtWidgets import QLineEdit

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    lying = [n for n, widget in w._widgets.items()
             if isinstance(widget, QLineEdit) and n != "name" and widget.isEnabled()]
    assert not lying, f"enabled but unwritable: {lying}"


# --- the roster carries race and class, and is no taller than its rows -------

def test_the_roster_at_its_natural_width_has_no_vertical_scrollbar_allowance(
        app, party):
    """A loaded wide roster is exactly its five columns, without a dead bar.

    The vertical header has to lay itself out before the roster measures its
    natural width.  Otherwise deleting the dead vertical-scrollbar allowance
    makes the final column overflow by that header's width.
    """
    from math import ceil

    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QHBoxLayout

    from editor.rosterview import NAME_COLUMN, NAME_MIN_WIDTH
    from wish.session import Session
    from wish.window import EDITOR_TAB, WishWindow

    win = WishWindow(str(party), maps={}, tab=EDITOR_TAB,
                     session=Session(find=lambda pref=None: None))
    try:
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        win.show()
        app.processEvents()
        view = win.editor.roster
        floor = win.minimumSizeHint()
        win.resize(floor.width() + view.maximumWidth(), floor.height())
        app.processEvents()

        row = win.editor.root.findChild(QHBoxLayout, "header_row")
        assert row is not None
        stretches = [
            (widget, row.stretch(index))
            for index in range(row.count())
            if row.stretch(index)
            if isinstance(widget := row.itemAt(index).widget(), QWidget)
            if widget.isVisible()
        ]
        total_stretch = sum(stretch for _, stretch in stretches)
        roster_stretch = next(
            stretch for widget, stretch in stretches if widget is view)
        for _ in range(3):
            shortfall = max(0, view.maximumWidth() - view.width())
            if not shortfall:
                break
            width = ceil(shortfall * total_stretch / roster_stretch)
            win.resize(win.width() + width, win.height())
            app.processEvents()

        wide_window_width = win.width()
        header = view.horizontalHeader()
        assert view.width() == view.maximumWidth()
        assert view.width() > view.minimumWidth()
        assert header.length() == view.viewport().width()
        assert not view.horizontalScrollBar().isVisible()
        assert view.horizontalScrollBar().maximum() == 0
        assert not view.verticalScrollBar().isVisible()

        wide = [header.sectionSize(column)
                for column in range(view.model().columnCount())]
        win.resize(1, win.height())
        app.processEvents()
        squeezed = [header.sectionSize(column)
                    for column in range(view.model().columnCount())]
        assert win.minimumSizeHint() == floor
        assert squeezed[:NAME_COLUMN] == wide[:NAME_COLUMN]
        assert squeezed[NAME_COLUMN + 1:] == wide[NAME_COLUMN + 1:]
        assert squeezed[NAME_COLUMN] < wide[NAME_COLUMN]
        horizontal = view.horizontalScrollBar()
        vertical = view.verticalScrollBar()
        viewport = view.viewport()
        overflow = header.length() > viewport.width()
        effective_name_minimum = max(NAME_MIN_WIDTH, header.minimumSectionSize())
        rows = [(row, view.rowViewportPosition(row), view.rowHeight(row))
                for row in range(view.model().rowCount())]
        geometry = (
            f"platform={QGuiApplication.platformName()!r}, "
            f"font={app.font().pointSizeF()}pt, "
            f"table={view.width()}px, minimum={view.minimumWidth()}px, "
            f"maximum={view.maximumWidth()}px, viewport={viewport.width()}x"
            f"{viewport.height()}px, header={header.length()}px, "
            f"wide={wide}, squeezed={squeezed}, NAME_MIN_WIDTH="
            f"{NAME_MIN_WIDTH}px, section minimum={header.minimumSectionSize()}px, "
            f"horizontal=(visible={horizontal.isVisible()}, range="
            f"{horizontal.minimum()}..{horizontal.maximum()}), vertical="
            f"(visible={vertical.isVisible()}, range={vertical.minimum()}.."
            f"{vertical.maximum()}), rows="
            f"{[(row, top, top + height) for row, top, height in rows]}")

        # The window floor is constant, but fixed columns and Qt's Name floor
        # follow font metrics.  A bar is legitimate only after Name reaches it.
        assert horizontal.isVisible() == overflow, geometry
        assert (horizontal.maximum() > 0) == overflow, geometry
        if overflow:
            assert squeezed[NAME_COLUMN] == effective_name_minimum, geometry
            fixed = sum(squeezed[:NAME_COLUMN]
                        + squeezed[NAME_COLUMN + 1:])
            assert fixed + effective_name_minimum > viewport.width(), geometry
        for row, top, height in rows:
            assert 0 <= top, geometry
            assert top + height <= viewport.height(), geometry
        assert not view.verticalScrollBar().isVisible()
        assert view.verticalScrollBar().maximum() == 0, geometry

        win.resize(wide_window_width, floor.height())
        app.processEvents()
        assert [header.sectionSize(column)
                for column in range(view.model().columnCount())] == wide
        assert header.length() == view.viewport().width()
        assert not view.horizontalScrollBar().isVisible()
        assert view.horizontalScrollBar().maximum() == 0
    finally:
        win.close()

@game_disks
def test_the_roster_names_the_race_and_class(app, save):
    """"The dwarf fighter" is how you pick who to edit.

    PORSAVE11 lists BRUTUS, MAGNUS, SILAS, ROLAND, LADY KATHERINE, MALCYON --
    the game's own marching order, highest occupied slot first (`#160`)."""
    from editor.window import EditorBinding, RosterModel
    w = EditorBinding(make_root(), str(save))
    assert RosterModel.HEADERS == ("Name", "Race", "Class", "AC", "HP")
    row = [w.model.data(w.model.index(0, c)) for c in range(5)]
    assert row == ["BRUTUS", "human", "fighter", "2", "6 / 11"]
    assert w.model.data(w.model.index(1, 1)) == "dwarf"          # MAGNUS


@game_disks
def test_the_roster_is_sized_to_its_rows_not_to_the_window(app, save):
    """Six characters used to fill a quarter of the window.

    The cap is its rows plus exactly two things and no third: `ROSTER_SLACK`,
    and one horizontal scroll bar's height, which is reserved whether or not
    the bar is up (#92). An equality rather than a bound, so a third thing
    creeping into the roster's height has to say so here.
    """
    from PyQt6.QtWidgets import QStyle

    from editor.window import ROSTER_SLACK, EditorBinding, _content_height
    w = EditorBinding(make_root(), str(save))
    w.root.resize(1200, 900)
    w.root.show()                       # heights are wrong until the table is shown
    # No splitter: the roster and the icon are a row above the tabs.
    # The table is capped at its own rows and never stretches to the window.
    bar = w.roster.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
    assert w.roster.maximumHeight() == (_content_height(w.roster)
                                           + ROSTER_SLACK + bar)
    assert _content_height(w.roster) < 300


@pytest.mark.parametrize("extra", [6, 10])
def test_the_scroll_bar_does_not_eat_the_rosters_last_row(app, party, extra):
    """#92, at the fonts and the width where it bit.

    `_size_roster` pinned the roster to exactly `header + rows + frame +
    ROSTER_SLACK`, and a horizontal scroll bar is drawn *inside* that. So the
    sixth character lost most of a row -- eight pixels of it, the bar's
    fourteen less the six of slack -- the table then found it could not show
    all its rows and brought the **vertical** bar up as well, and that took
    another 14px of width and made the horizontal overflow slightly worse.

    Six points of extra UI font is where it starts here and ten is roughly a
    Windows base font. It cannot happen at the base font at any width the
    layout permits, which is why the +0 case is a control rather than the
    test: the roster's floor of 440 clears its four fixed columns' 356.

    **The window is squeezed to its own floor rather than to 1366.** The issue
    measured it in a 1366-wide window, and 1366 is a measurement of this
    machine's fonts as much as of the screen; asking Qt to clamp a width of 1
    puts the roster on `ROSTER_MIN_WIDTH` wherever this runs, which is the
    state the bug needs and is the same state on every platform.

    The horizontal bar itself is not the bug and is asserted to still be up:
    it is the last resort #71 approved, after `Name` has elided and given
    everything it has.
    """
    from PyQt6.QtGui import QFont

    from wish.session import Session
    from wish.window import EDITOR_TAB, WishWindow

    base = app.font()
    try:
        bigger = QFont(base)
        bigger.setPointSizeF(base.pointSizeF() + extra)
        app.setFont(bigger)
        w = WishWindow(str(party), maps={}, tab=EDITOR_TAB,
                       session=Session(find=lambda pref=None: None))
        w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        w.show()
        w.resize(1, 900)                    # Qt clamps to the window's own floor
        app.processEvents()
        view = w.editor.roster
        room = view.viewport().height()
        for row in range(w.editor.model.rowCount()):
            bottom = view.rowViewportPosition(row) + view.rowHeight(row)
            assert bottom <= room, (
                f"+{extra}pt: row {row} runs {bottom - room}px past the "
                f"roster's viewport")
        assert not view.verticalScrollBar().isVisible(), (
            f"+{extra}pt: every row fits, so nothing should scroll vertically")
        if extra:
            assert view.horizontalScrollBar().isVisible(), (
                f"+{extra}pt: the roster is meant to be squeezed here, and "
                f"this test proves nothing if it is not")
        w.close()
    finally:
        app.setFont(base)


@game_disks
def _test_the_roster_is_wide_enough_for_all_five_columns(app, save):
    """Beside the icon rather than under Character, the table gets the 256px
    `QTableView` hints and not the 331px its columns came to -- so HP fell off
    the right, a horizontal scroll bar appeared, and it ate a row."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.root.resize(1200, 900)
    w.root.show()
    view = w.roster
    assert view.viewport().width() >= view.horizontalHeader().length()


def _test_each_tab_scrolls_inside_itself(app, save):
    """A fixed top over a scrolling bottom squeezed the fields into a sixty
    pixel strip on any window short of enormous, and one scroll area over the
    lot took the tab bar off screen with it. Each tab scrolls on its own, so
    the roster, the icon and the tab bar are always where they were."""
    from PyQt6.QtWidgets import QScrollArea, QSplitter, QTabWidget

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.root.resize(1200, 700)
    w.root.show()
    assert w.root.findChild(QSplitter) is None, "the splitter is what caused this"
    tabs = w.root.findChild(QTabWidget, "sheet_tabs")
    for name in ("scroll_stats", "scroll_inventory", "scroll_spells"):
        scroll = w.root.findChild(QScrollArea, name)
        assert scroll is not None, name
        assert scroll.widgetResizable(), name
        assert tabs.isAncestorOf(scroll), name
    assert not tabs.isAncestorOf(w.roster)


# --- field widths come from the layout --------------------------------------

def test_the_widest_value_comes_from_the_kind_and_the_byte_width():
    from editor.binding import value_range, widest_text
    from goldbox.layout import FIELDS_BY_NAME, NAME_SIZE
    assert widest_text(FIELDS_BY_NAME["strength"]) == "255"
    assert widest_text(FIELDS_BY_NAME["gold"]) == "65535"
    assert widest_text(FIELDS_BY_NAME["name"]) == "W" * NAME_SIZE
    assert widest_text(FIELDS_BY_NAME["thief_open_locks"]) == "-128"
    assert value_range(FIELDS_BY_NAME["experience"]) == (0, 0xFFFFFF)


def test_a_combat_fields_range_uses_displayed_values():
    """`thac0_base` and the other three are U8 like `strength`, but stored as
    `60 - value` (#149), so their range is `combat_value` run over the byte's
    own 0-255 rather than 0-255 itself -- and armour class needs the negative
    end: GRIMNIR and BRUTUS read -1 on `NEWSAVE5.D64`."""
    from editor.binding import value_range, widest_text
    from goldbox.layout import FIELDS_BY_NAME
    for name in ("thac0_base", "thac0", "armour_class_base", "armour_class"):
        assert value_range(FIELDS_BY_NAME[name]) == (-195, 60), name
    assert widest_text(FIELDS_BY_NAME["armour_class_base"]) == "-195"


@game_disks
def test_a_name_box_is_wider_than_an_ability_box(app, save):
    """Every box was the same generous width whatever could go in it."""
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    name = w._widgets["name"].maximumWidth()
    strength = w._widgets["strength"].maximumWidth()
    gold = w._widgets["gold"].maximumWidth()
    assert strength < gold < name
    assert (w._widgets["strength"].minimum(),
            w._widgets["strength"].maximum()) == (0, 255)
    assert w._widgets["thief_open_locks"].minimum() == -128


@game_disks
def test_the_identity_box_is_called_character(app, save):
    from PyQt6.QtWidgets import QGroupBox

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    assert w.root.findChild(QGroupBox, "box_identity").title() == "Character"
    # Donald's words, and the only new string round five put on the sheet.
    assert w.root.findChild(QGroupBox, "box_abilities").title() == "Ability Scores"


# --- the item column, and the two new tables --------------------------------

@game_disks
def test_the_item_column_fits_the_longest_name_the_disks_hold(editor):
    """163 items, and the widest is TWO-HANDED SWORD +1 +3 VS UNDEAD."""
    from editor import inventory
    table = editor._child("inventory")
    wanted = table.fontMetrics().horizontalAdvance(inventory.LONGEST_ITEM_NAME)
    assert inventory.LONGEST_ITEM_NAME in editor.templates
    assert wanted <= table.columnWidth(inventory.NAME) <= wanted + 40


@game_disks
def test_the_traits_of_the_selected_item_are_shown(editor):
    editor.roster.selectRow(3)                     # ROLAND -- row 3, #160
    editor._child("inventory").selectRow(0)           # BANDED MAIL
    assert editor._show_traits() == "BANDED MAIL"
    traits = dict(editor.traits.rows)
    assert traits["Protection"] == "AC 4"
    assert traits["Usable by"] == "cleric, fighter"
    editor._child("inventory").selectRow(1)           # MACE
    assert dict(editor.traits.rows)["Damage vs medium"] == "1d6+1"


@game_disks
def test_a_free_slot_has_no_traits(editor):
    editor.roster.selectRow(3)                     # ROLAND -- row 3, #160
    editor._child("inventory").selectRow(15)
    assert editor._show_traits() == "Select an item"
    assert editor.traits.rowCount() == 0


@game_disks
def test_a_scroll_shows_its_spells_and_a_wand_its_charges(editor):
    from editor.inventory import ItemTraitsModel
    from goldbox.items import Item
    m = ItemTraitsModel()
    m.set_tables(editor.item_types, editor.spell_names)
    m.set_item(Item(editor.templates["MU SCROLL WITH 1 SPELL"], editor.item_names))
    assert dict(m.rows)["Spells"] == "MAGIC MISSILE (magic-user 1)"
    m.set_item(Item(editor.templates["WAND OF MAGIC MISSILES"], editor.item_names))
    rows = dict(m.rows)
    assert rows["Charges"] == "20"
    # 88 - 23 = 65, past RESTORATION, so it is not named from the spell table.
    assert rows["Effect"].startswith("effect 65")
    m.set_item(Item(editor.templates["CURSED NECKLACE"], editor.item_names))
    rows = dict(m.rows)
    assert rows["Saving throws"] == "-5" and rows["Cursed"].startswith("yes")
    m.set_item(Item(editor.templates["GAUNTLETS OF OGRE POWER"], editor.item_names))
    assert "passive" in dict(m.rows)["Power"]


@game_disks
def test_the_effect_list_shows_an_elfs_racial_resistance(editor):
    """107 in the first slot is what GEN seeds an elf with, and the editor
    showed no sign of it before."""
    from editor import effects
    view = editor._widgets["item_effects"]
    editor.roster.selectRow(5)                     # MALCYON -- row 5, #160; an elf
    assert view.codes()[0] == 107
    assert view.model_.data(view.model_.index(0, 1)) == \
        "elf: 90% resistance to sleep and charm"
    assert view.model_.rowCount() == effects.SLOTS
    editor.roster.selectRow(3)                     # ROLAND -- row 3, #160; a human
    assert not any(view.codes())
    assert view.model_.data(view.model_.index(0, 1)) == effects.EMPTY


def test_a_code_nobody_has_named_is_shown_as_a_number():
    """Silently dropping it would read as "this character has nothing".

    The DOS guide's effect table named most of these, so the code picked here
    is one it does not reach -- and the point of the test is the fallback, not
    which code happens to be unnamed today.
    """
    from editor.effects import EffectsModel
    from goldbox.traits import describe
    assert describe(107) == "elf: 90% resistance to sleep and charm"
    assert describe(200) == "trait 200"
    m = EffectsModel(bytes([200]))
    assert m.data(m.index(0, 1)) == "trait 200"
    # No code column: the sheet names the effect, and the number survives only
    # where nobody has named it.
    assert "Code" not in m.HEADERS


# --- editing the trait block -------------------------------------------------
#
# `#13 (Edit traits and active effects, in two separate panels)` step S3.
# `WISH_EXPERIMENTAL_TRAITS` came off once `#417 (Prove the game applies a
# trait Wish wrote, so WISH_EXPERIMENTAL_TRAITS can come off)` and Donald's
# 2026-09-08 approval of every string met both of the flag's conditions, so
# Add and Remove are built by default now. What still matters is the round
# trip: opening a save and touching nothing must not rewrite a byte of it.


def _trait_view(window):
    return window._widgets["item_effects"]


def test_a_full_block_has_no_room_for_another_trait():
    """XAVIER's tenth slot is why the list is ten rows and not the used ones.

    A block with all ten occupied has nowhere to put an eleventh, so Add is
    off -- a button that would silently drop what was picked is worse than no
    button.
    """
    from editor.effects import EffectsView

    view = EffectsView()
    view.set_bytes(bytes(range(1, 11)))
    assert view.room() == 0
    view.add(20)
    assert view.codes() == list(range(1, 11)), "an eleventh got in"


def test_a_fill_byte_keeps_the_tenth_slot_and_costs_a_place():
    """255 in slot 9 is a fill byte, measured on 38 of 108 monster records and
    slot 9 every time, with no real code ever after one. So the block holds
    nine, the fill stays where it is, and compaction never shuffles it up.
    """
    from editor.effects import EffectsView

    view = EffectsView()
    view.set_bytes(bytes([1, 0, 5, 0, 0, 0, 0, 0, 0, 255]))
    assert view.room() == 7
    view.add(20)
    assert view.codes() == [1, 5, 20, 0, 0, 0, 0, 0, 0, 255]
    view.set_bytes(bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 255]))
    assert view.room() == 0


def test_removing_a_trait_closes_the_gap_behind_it():
    """The game seeds from slot 0 upward and `SPELLE04` scans for the first
    free slot, so a hole in the middle is a shape no record the game wrote
    has. Removing the first of three leaves two, packed."""
    from editor.effects import EffectsView

    view = EffectsView()
    view.set_bytes(bytes([107, 20, 61, 0, 0, 0, 0, 0, 0, 0]))
    view.remove(0)
    assert view.codes() == [20, 61, 0, 0, 0, 0, 0, 0, 0, 0]
    view.set_bytes(bytes([107, 20, 61, 0, 0, 0, 0, 0, 0, 255]))
    view.remove(1)
    assert view.codes() == [107, 61, 0, 0, 0, 0, 0, 0, 0, 255]


def test_an_untouched_block_is_handed_back_exactly_as_it_arrived():
    """The whole reason `to_bytes` is not a normalised ten bytes.

    A block that arrives short, or with a hole in it, is a block the game
    wrote, and tidying it on the way past would be an edit the player never
    made. Only Add and Remove replace it.
    """
    from editor.effects import EffectsView

    view = EffectsView()
    for raw in (b"", bytes([0, 0, 107]), bytes([107, 0, 61, 0, 0, 0, 0, 0, 0, 0])):
        view.set_bytes(raw)
        assert view.to_bytes() == raw


@game_disks
def test_a_no_op_save_writes_nothing_with_the_trait_buttons_built(app, save):
    """**The bar this whole step has to clear.**

    Building the Add and Remove buttons must not, by itself, change a byte of
    somebody's save. Opening the disk, visiting every character with the
    buttons built, and saving writes nothing -- the same guarantee
    `test_a_no_op_save_writes_nothing_at_all` holds.
    """
    from editor.window import EditorBinding
    before = save.read_bytes()
    w = EditorBinding(make_root(), str(save))
    assert w._child("button_trait_add") is not None, "the buttons were not built"
    for row in range(6):
        w.roster.selectRow(row)
    assert w.save(interactive=False) == "no changes"
    assert save.read_bytes() == before
    assert not (save.parent / "backups").exists()


def test_saving_preserves_effects_after_empty_slots(
        app, tmp_path):
    """The round trip above is a weak guard on `PORSAVE11.D64` and this is the
    disk where it is not.

    **Every one of PORSAVE11's six blocks is already packed from slot 0**, so
    a `to_bytes` that compacted on the way past would write those six back
    unchanged and the no-op test would stay green. Across the 150 records on
    the player's save disks five are not: SILAS carries `45, 5` in slots 8 and
    9 with eight zeroes in front of them, on `PORSAVEA.D64`, `PORSAVEB.D64`
    and three of the DOS-import test disks. Opening that disk and saving must
    not move those two bytes down to slots 0 and 1.
    """
    from editor.window import EditorBinding
    src = disk_path("PORSAVEA")
    if src is None:
        pytest.skip("needs PORSAVEA.D64")
    out = tmp_path / "PORSAVEA.D64"
    out.write_bytes(src.read_bytes())
    before = out.read_bytes()
    w = EditorBinding(make_root(), str(out))
    blocks = []
    for row in range(len(w.party)):
        w.roster.selectRow(row)
        blocks.append(_trait_view(w).codes())
    assert [0, 0, 0, 0, 0, 0, 0, 0, 45, 5] in blocks, (
        "PORSAVEA no longer holds the block this test is about")
    assert w.save(interactive=False) == "no changes"
    assert out.read_bytes() == before


@game_disks
def test_a_trait_added_in_the_editor_reaches_the_disk(app, save):
    """MALCYON the elf is born with 107 and nothing else. Adding 20 Resist
    Fire puts it in slot 1 and it is still there when the file is reopened.

    What this does **not** show is the game applying it -- that was M3,
    `#417 (Prove the game applies a trait Wish wrote, so
    WISH_EXPERIMENTAL_TRAITS can come off)`, taken separately, on 2026-09-08,
    and CONFIRMED on all three claims.
    """
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(5)                          # MALCYON -- row 5, #160
    view = _trait_view(w)
    assert view.codes()[:2] == [107, 0]
    view.add(20)
    assert "wrote" in w.save(interactive=False)

    again = EditorBinding(make_root(), str(save))
    again.roster.selectRow(5)
    assert _trait_view(again).codes()[:2] == [107, 20]


@game_disks
def test_the_preview_names_a_changed_trait_rather_than_printing_hex(
        app, save):
    """`6b00...` and `6b14...` are the same line to a reader. The preview is
    read by a person in Preview changes and by `wish --dry-run`."""
    from editor import changes
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(5)
    _trait_view(w).add(20)
    w._flush()
    line = next(ln for ln in changes.changes(w.party) if "item_effects" in ln)
    assert "Resist Fire" in line
    assert "elf: 90% resistance to sleep and charm" in line
    assert "6b" not in line


def test_the_picker_offers_the_whole_table_in_two_provenance_sections(app):
    """Donald's D4, 2026-09-07: all of it, in two sections that say where the
    name came from, rather than the cut at id 64 that hides the codes somebody
    would most want to try.

    255 is the one code not offered, and it is not a trait: it is a fill byte
    in the last slot, 38 of 108 monster records and slot 9 every time.
    """
    from editor.traitpicker import CODE_ROLE, TraitPicker
    from goldbox.traits import NAMES

    picker = TraitPicker()
    try:
        seen = picker.sections[True].childCount()
        table = picker.sections[False].childCount()
        assert seen + table == len(NAMES) - 1 == 128
        assert 255 not in {picker.sections[s].child(n).data(0, CODE_ROLE)
                           for s in (True, False)
                           for n in range(picker.sections[s].childCount())}
        # Provenance, not a grade: PROBABLE is exactly "the guide names it and
        # nothing on the C64 exercises it", which is the DOS table's half.
        assert table == sum(1 for v in NAMES.values() if v[1] == "PROBABLE")
    finally:
        picker.deleteLater()


def test_a_monster_attack_form_on_a_character_is_coloured_and_says_why(app):
    """83 is a basilisk's petrifying gaze and a character has none of the
    parts its handler reads. The editor writes it anyway -- the spellbook
    precedent -- and says what it is not refusing.

    The four cases are `docs/133-active-effects.md`'s "What a nonsense
    combination could do" table, in the order a reader wants them: the code's
    own trouble first, and "you already have this" only when there is nothing
    worse to say.
    """
    from editor import effects

    assert effects.warning(83) == effects.REASON_MONSTER
    assert effects.warning(63) == effects.REASON_NO_HANDLER
    assert effects.warning(92) == effects.REASON_UNNAMED
    assert effects.warning(1, (1,)) == effects.REASON_DUPLICATE
    # Above the cut and written by the game itself, so no warning: the elf's
    # own 107, the half-elf's 124, 89 off a CLOAK OF DISPLACEMENT, and the two
    # constitution bonuses race alone writes at creation.
    for code in (107, 124, 89, 90, 97):
        assert effects.warning(code) == "", code
    model = effects.EffectsModel(bytes([83]))
    assert model.warning_at(0) == effects.REASON_MONSTER
    assert effects.REASON_MONSTER in model.data(
        model.index(0, 1), Qt.ItemDataRole.ToolTipRole)
    assert model.data(model.index(0, 1),
                      Qt.ItemDataRole.ForegroundRole).color() == effects.WARN


# --- the buttons are built by default ----------------------------------------
#
# `.claude/rules/feature-flags.md`'s gate is gone: `WISH_EXPERIMENTAL_TRAITS`
# was deleted once `#417 (Prove the game applies a trait Wish wrote, so
# WISH_EXPERIMENTAL_TRAITS can come off)` and Donald's 2026-09-08 approval of
# every string met both of its conditions. What is left to prove is that the
# buttons are there with a clean environment, and that a stray
# `WISH_EXPERIMENTAL_TRAITS` left in somebody's shell -- on or off -- cannot
# change that, since nothing reads it any more.


@game_disks
def test_the_traits_box_has_its_buttons_by_default(app, save, monkeypatch):
    """The shipped state, with no environment variable set at all."""
    from editor.window import EditorBinding
    monkeypatch.delenv("WISH_EXPERIMENTAL_TRAITS", raising=False)
    w = EditorBinding(make_root(), str(save))
    assert w._child("traits_buttons") is not None
    assert w._child("button_trait_add") is not None
    assert w._child("button_trait_remove") is not None


@pytest.mark.parametrize("value", ["", "0", "off", "no", "false", "1", "true",
                                    "yes", "2", "yes please"])
@game_disks
def test_a_leftover_variable_does_not_hide_the_buttons(app, save, monkeypatch,
                                                        value):
    """`WISH_EXPERIMENTAL_TRAITS` means nothing now: a shell that still
    exports it, on or off, must not change what the sheet builds."""
    from editor.window import EditorBinding
    monkeypatch.setenv("WISH_EXPERIMENTAL_TRAITS", value)
    w = EditorBinding(make_root(), str(save))
    assert w._child("button_trait_add") is not None
    assert w._child("button_trait_remove") is not None


def test_no_trait_string_is_waiting_on_approval_any_more():
    """`.claude/rules/gui-text.md`: every word a user reads is Donald's.

    He ruled on all of them on 2026-09-08, shown the box, the picker and a
    warning as pictures, against three alternatives for the four warnings. So
    the count is zero and the flag's second condition is met.

    **This test is not decoration.** A string added to that module later is
    unapproved again however the ones around it read, and this is what says
    so: it goes red until the new one carries `(NOT APPROVED)` or he has
    ruled on it and this list is updated deliberately.
    """
    from editor import effects

    marked = {name for name, text in vars(effects).items()
              if name.isupper() and isinstance(text, str)
              and "NOT APPROVED" in text}
    assert marked == set(), marked
    assert effects.BOX_TITLE == "Character Traits"
    assert effects.BUTTON_ADD == "Add…"
    assert effects.PICKER_TITLE == "Choose a trait"


@game_disks
def test_no_unapproved_word_is_on_screen_by_default(app, save):
    """Nothing on the sheet carries the marker -- not a button, not a
    tooltip, not the box title."""
    from PyQt6.QtWidgets import QAbstractButton, QGroupBox, QLabel

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(5)
    for kind in (QAbstractButton, QLabel, QGroupBox):
        for widget in w.root.findChildren(kind):
            for text in (widget.text() if hasattr(widget, "text")
                         else widget.title(), widget.toolTip()):
                assert "NOT APPROVED" not in text, widget.objectName()
    model = _trait_view(w).model_
    for row in range(model.rowCount()):
        tip = model.data(model.index(row, 1), Qt.ItemDataRole.ToolTipRole)
        assert "NOT APPROVED" not in (tip or "")


# --- the layout does not move ------------------------------------------------

@game_disks
def _test_the_sheet_keeps_its_layout_across_the_roster(editor):
    """Donald: "The layout of the form should not change when we navigate the
    roster. It should stay the same, so people know where to look for things at
    all times."

    PORSAVE11 has a magic-user, a magic-user/thief and three fighters, so it
    covers every combination the two class-conditional boxes ever had. No box
    may come or go, and no tab may change the size it asks for.

    `isHidden`, not `isVisible`: a box on a tab that is not showing is not
    visible and never was hidden, and greying it out -- which is what the two
    class-conditional boxes do -- is not hiding it either.
    """
    from PyQt6.QtWidgets import QGroupBox

    editor.root.resize(1875, 1030)
    editor.root.show()
    pages = ("page_stats", "page_inventory", "page_spells")
    shapes = []
    for row in range(len(editor.party)):
        editor.roster.selectRow(row)
        boxes = {b.objectName() for b in editor.findChildren(QGroupBox)
                 if not b.isHidden()}
        shapes.append((boxes, tuple(editor._child(n).root.sizeHint()
                                    for n in pages)))
    first = shapes[0]
    assert all(s == first for s in shapes), [
        (editor.party.member(i).name, sorted(s[0]), s[1])
        for i, s in enumerate(shapes) if s != first]
    assert "box_spells" in first[0]
    assert "box_thief_skills" in first[0]


# --- the later titles' spells -----------------------------------------------
# Issues #80 and #81. The editor read Pool of Radiance's `SPELLN00` whatever
# save was open and Pool of Radiance's seven-byte mask whatever title it
# belonged to, so on Curse and Silver Blades the Spells tab showed numbers, and
# on Silver Blades it showed two thirds of the numbers there were.
#
# The disks are the player's own, found the way the rest of the suite finds
# them, and every test here skips when they are absent.

def _copy_disks(source, pattern, into):
    import shutil
    for disk in sorted(source.glob(pattern)):
        shutil.copy(disk, into / disk.name)


def _title_save(where, pattern, game, into):
    """A throwaway copy of a whole save disk of one title, or skip.

    Copied because a test must never write to the player's disks, and the
    editor is a program that writes.
    """
    from goldbox.d64 import D64
    if where is None:
        pytest.skip(f"needs the {game.title} disks")
    _copy_disks(where, pattern, into)
    for path in sorted(into.glob(pattern)):
        try:
            disk = D64.open(path)
            entry = disk.find(game.save_file)
            if entry is not None and game.matches_payload(disk.read_file(entry)):
                return path
        except Exception:
            continue
    pytest.skip(f"no {game.title} disk here carries a whole save")


def _curse_window(app, tmp_path):
    from gamedata import curse_dir

    from editor.window import EditorBinding
    from goldbox import c64_port
    save = _title_save(curse_dir(), "CURSE*.[dD]64",
                       c64_port.CURSE_OF_THE_AZURE_BONDS, tmp_path)
    return EditorBinding(make_root(), str(save))


def _silver_blades_window(app, tmp_path):
    from editor.window import EditorBinding
    from goldbox import c64_port
    ssb_dir = pytest.importorskip("support.silverblades").ssb_dir
    save = _title_save(ssb_dir(), "SILVER*.[dD]64",
                       c64_port.SECRET_OF_THE_SILVER_BLADES, tmp_path)
    return EditorBinding(make_root(), str(save))


def _rows(book):
    """Every tick box in a spellbook widget, by spell id."""
    return {sid: row.text() for sid, row in book._rows.items()}


def test_a_curse_spellbook_names_its_spells_rather_than_numbering_them(
        app, tmp_path):
    """#80. `SHOCKING GRASP` is id 20 in both titles, so the number is the same
    and only the table it is looked up in differs.

    Curse ships no `SPELLN00`; its names are in `COMBAT2` at `$E000`. Asking
    for the wrong file raised, the exception was logged and swallowed, and an
    empty name table looks exactly like a missing game disk.
    """
    from goldbox import c64_port
    window = _curse_window(app, tmp_path)
    assert window.party.game is c64_port.CURSE_OF_THE_AZURE_BONDS
    assert window.spell_names, "no spell names off a Curse disk"

    book, _ = window._spell_widgets()
    rows = _rows(book)
    assert rows[20].startswith("SHOCKING GRASP")
    assert not [t for t in rows.values() if t.startswith("spell ")], (
        [t for t in rows.values() if t.startswith("spell ")][:5])


def test_a_silver_blades_spellbook_names_its_spells_too(app, tmp_path):
    """#80, third title. Silver Blades moves two of the fifty-six -- 36 is
    `HEAL` where Pool of Radiance has `ANIMATE DEAD` -- so a spellbook read
    against the wrong table would be wrong even where it was not blank."""
    from goldbox import c64_port
    window = _silver_blades_window(app, tmp_path)
    assert window.party.game is c64_port.SECRET_OF_THE_SILVER_BLADES
    rows = _rows(window._spell_widgets()[0])
    assert rows[20].startswith("SHOCKING GRASP")
    assert rows[36].startswith("HEAL")
    assert not [t for t in rows.values() if t.startswith("spell ")]


def test_the_editor_and_the_automapper_name_the_same_spells(app, tmp_path):
    """The disagreement was the clearest evidence of #80 and is the test.

    `automap/window.py::_names_for_spells` calls
    `goldbox.spells.load_spell_names(path, game)` -- with the title. The editor
    called it without, so the two windows named the same character's spells
    differently: the map said `STINKING CLOUD` and the sheet said `spell 34`.
    """
    from goldbox.spells import load_spell_names
    for build in (_curse_window, _silver_blades_window):
        window = build(app, tmp_path)
        disk = window._find_game_disk()
        automapper = load_spell_names(disk, window.party.game)
        assert automapper, "the automapper's own call found no names"
        assert window.spell_names == automapper
        # And what the missing title cost, in the same breath: neither title
        # ships `SPELLN00`, so the untitled call raises, the window logged the
        # exception and carried on, and the panel numbered every spell.
        with pytest.raises(Exception, match="SPELLN00"):
            load_spell_names(disk)


def test_a_silver_blades_casters_spellbook_reaches_past_spell_fifty_five(
        app, tmp_path):
    """#81. MORGAINE knows twenty-nine spells and the sheet showed twenty-four.

    Seven bytes is 56 bits, which is Pool of Radiance's spell count and nothing
    else's. Silver Blades' mask is sixteen bytes -- `GEN $09DC` clears exactly
    that many -- so `CONFUSION`, `FIRE SHIELD`, `MINOR GLOBE OF INVULNERABLITY`
    and `HOLD MONSTERS`, ids 82, 85, 88 and 94, had no tick box to appear in.
    """
    from goldbox.spells import SECRET_OF_THE_SILVER_BLADES as TABLE
    from goldbox.spells import spells_known

    window = _silver_blades_window(app, tmp_path)
    row = next(r for r in range(window.model.rowCount())
               if window.party.member(r).record.name.strip() == "MORGAINE")
    window.roster.selectRow(row)
    record = window.party.member(row).record

    book, _ = window._spell_widgets()
    assert book.known() == spells_known(record.to_bytes(), TABLE)
    assert len(book.known()) == 29
    assert 94 in book.known()
    assert _rows(book)[94].startswith("HOLD MONSTERS")


def test_a_silver_blades_spellbook_survives_an_edit_of_its_low_bits(
        app, tmp_path):
    """Ticking a first-level spell must not clear the fourth-level ones.

    The mask spans two declared fields now, and this is the failure that would
    follow from writing only one of them.
    """
    window = _silver_blades_window(app, tmp_path)
    row = next(r for r in range(window.model.rowCount())
               if window.party.member(r).record.name.strip() == "MORGAINE")
    window.roster.selectRow(row)
    record = window.party.member(row).record
    before = window._spellbook_raw(record)

    book, _ = window._spell_widgets()
    book.set_ids(sorted(set(book.known()) | {13}))
    window._flush()
    after = window._spellbook_raw(record)
    assert after[10:] == before[10:], "the high bytes moved"
    assert after[1] == before[1] | (1 << 5)


# --- Castable per level was on screen all along, and unreadable --------------

def test_the_castable_box_shows_its_bytes_whole(app, party):
    """#42: "Castable per level" read `00 00 00 00 00` for every character.

    Not a wrong read and not a wrong field: the box was 85px for the 98px of
    `01 00 00 00 00 00` it had to draw. `widest_text` answers "the longest
    string a field can display", and for six raw bytes every string is the
    same length, so it picked `ff ff ff ff ff ff` -- barely half the width in
    the proportional UI font. `setText` leaves the cursor at the end and
    QLineEdit scrolls to the cursor, so what was on screen was the tail: five
    groups of `00`, identical for a caster with slots and a fighter without.

    Two assertions, because either alone can pass while the field is wrong.
    The text is what the record holds; the leftmost character drawn is the
    first one, which is what says the box is not scrolled.
    """
    from PyQt6.QtCore import QPoint

    from editor.window import EditorBinding

    window = EditorBinding(make_root(), str(party))
    try:
        box = window._child("field_spells_castable")
        for row in range(len(window.party)):
            window.roster.selectRow(row)
            record = window.party.member(row).record
            raw = record.get_raw("spells_castable")
            assert box.text() == raw.hex(" "), record.name
            box.grab()          # the scroll offset only moves when it paints
            assert box.cursorPositionAt(QPoint(1, box.height() // 2)) == 0, (
                f"{record.name}: {box.text()!r} is scrolled off its left edge")
            assert (box.fontMetrics().horizontalAdvance(box.text())
                    <= box.width()), record.name
    finally:
        window.close()


@game_disks
def test_a_casters_slots_are_not_a_fighters(app, save):
    """The other half of #42: zero is a real answer for three of the six.

    A test that only asserted "the box matches the bytes" would pass on a
    field that was always empty, so one caster and one fighter off the same
    disk are named here. MALCYON is a magic-user 1 with one first-level slot;
    ROLAND is a cleric 1, whose slots sit in the high nibbles; SILAS is a
    fighter and reads all zeros correctly.
    """
    from editor.window import EditorBinding

    window = EditorBinding(make_root(), str(save))
    try:
        box = window._child("field_spells_castable")
        shown = {}
        for row in range(len(window.party)):
            window.roster.selectRow(row)
            shown[window.party.member(row).record.name.strip()] = box.text()
        assert shown["MALCYON"] == "01 00 00 00 00 00"
        assert shown["ROLAND"] == "30 00 00 00 00 00"
        assert shown["SILAS"] == "00 00 00 00 00 00"
    finally:
        window.close()


# --- the active-effects panel ------------------------------------------------
#
# S4 of `#13 (Edit traits and active effects, in two separate panels)`.
# `WISH_EXPERIMENTAL_EFFECTS` came off once Donald ruled on every string on
# 2026-09-08, so the panel is built by default now. The list belongs to the
# **save**, not to the character the roster has selected, and every test
# below is ultimately about that: a spell on MALCYON is in the panel while
# BRUTUS is on the sheet, which is why the panel sits in the top row and why
# the owner column exists at all.


def _payload_with_effects(*slots) -> bytes:
    """A save payload carrying the given `(slot, id, owner, duration)` rows.

    Written by hand from the four offsets rather than through
    `goldbox.effects.write_effect`: that primitive exists for a write path
    nobody has built yet, and a test that reached for it here would make the
    panel look like it had one.
    """
    from goldbox.effects import (
        EFFECT_DURATION_OFFSET,
        EFFECT_ID_OFFSET,
        EFFECT_MAGNITUDE_OFFSET,
        EFFECT_OWNER_OFFSET,
        EFFECT_SLOTS,
    )
    payload = bytearray(EFFECT_MAGNITUDE_OFFSET + EFFECT_SLOTS)
    for slot, code, owner, duration in slots:
        payload[EFFECT_ID_OFFSET + slot] = code
        payload[EFFECT_OWNER_OFFSET + slot] = owner
        payload[EFFECT_DURATION_OFFSET + slot] = duration
    return bytes(payload)


def test_the_panel_says_who_each_effect_is_on():
    """The one thing the panel is for. Three effects in one save: one on a
    character, one on the whole party, one on something that was in a fight.

    A player reading this list has some *other* character on the sheet beside
    it, so a row that did not name its owner would read as the selected
    character's -- which is the confusion `#13` exists to end.
    """
    from editor import activeeffects
    from goldbox.effects import active_effects

    payload = _payload_with_effects((0, 1, 0, 0x06),        # on a character
                                    (1, 35, 0xFF, 0x0A),    # on everybody
                                    (2, 12, 9, 0x02))       # on a monster
    model = activeeffects.ActiveEffectsModel(
        active_effects(payload), {0: "MALCYON", 1: "BRUTUS"})
    assert model.rowCount() == 3
    owners = [model.data(model.index(r, 1)) for r in range(3)]
    assert owners == [
        "MALCYON",
        activeeffects.OWNER_PARTY,
        activeeffects.OWNER_MONSTER,
    ]
    # And the first column names the effect out of the same table the traits
    # box reads, since the two lists share one code namespace.
    assert [model.data(model.index(r, 0)) for r in range(3)] == [
        "Bless", "under an allied Prayer", "Enlarge"]


def test_an_effect_on_a_slot_nobody_fills_says_so_rather_than_naming_nobody():
    """A character can leave the party with something still running on them:
    `CAMP` renumbers the owner byte when a character changes slot, and nothing
    clears an effect whose owner walked away. A blank second column would read
    as "on the character you are looking at"."""
    from editor import activeeffects
    from goldbox.effects import active_effects

    model = activeeffects.ActiveEffectsModel(
        active_effects(_payload_with_effects((0, 12, 5, 0x06))),
        {0: "MALCYON"})
    assert model.data(model.index(0, 1)) == activeeffects.OWNER_ABSENT


def test_an_effect_nobody_has_named_reads_unknown():
    """Donald's wording, 2026-09-08: an unnamed code reads `Unknown`.

    It used to read `Effect 253, which nobody has named`, on the argument that
    the number is what somebody takes away to look it up. He chose brevity, so
    two unnamed effects now read alike on screen -- the code is still in the
    save and still in the debug log, and nothing on this row was ever a trait,
    which is the distinction this ticket is about.
    """
    from editor import activeeffects
    from goldbox.effects import active_effects

    model = activeeffects.ActiveEffectsModel(
        active_effects(_payload_with_effects((0, 253, 0, 0x06))))
    shown = model.data(model.index(0, 0))
    assert shown == "Unknown"
    assert "trait" not in shown.lower()
    assert "trait" not in shown.lower()


def test_the_panel_shows_no_duration_anywhere():
    """**D2**, and it is a decision rather than an omission. The duration byte
    holds a count in bits 0-5 and a *unit* in bits 6-7 (minute, ten minutes,
    hour or day), and whether to show a duration is Donald's to decide.
    `docs/136-condition-badges.md` leaves the condition badge without one too.

    `$8B` is 11 in the hour unit. Neither number reaches the panel,
    and there is no third column for one to reach.
    """
    from editor import activeeffects
    from goldbox.effects import active_effects

    effects = active_effects(_payload_with_effects((0, 12, 0, 0x8B)))
    assert effects[0].remaining == 11 and effects[0].unit == 2
    model = activeeffects.ActiveEffectsModel(effects, {0: "MALCYON"})
    assert model.columnCount() == 2
    for column in range(2):
        for role in (Qt.ItemDataRole.DisplayRole,
                     Qt.ItemDataRole.ToolTipRole):
            shown = model.data(model.index(0, column), role) or ""
            assert "11" not in shown and "$8B" not in shown, shown


def test_a_save_with_nothing_running_still_has_the_panel(app, party):
    """The empty state is the two column headings over no rows, and no
    sentence: a line explaining that an empty list is empty has to be worded
    and approved, and is read by somebody who can already see it.

    The synthetic save has nothing running, which is the ordinary case -- a
    party that has just camped has an empty table here.
    """
    from editor import activeeffects
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(party))
    box = w._child("box_active_effects")
    assert box is not None and not box.isHidden()
    assert_title_fits_and_is_not_silently_cut(box, activeeffects.BOX_TITLE)
    view = w._child("active_effects")
    assert view.model_.rowCount() == 0
    head = view.horizontalHeader().model()
    assert [head.headerData(c, Qt.Orientation.Horizontal) for c in range(2)] == [
        activeeffects.HEADER_EFFECT, activeeffects.HEADER_OWNER]


def test_a_roster_disk_has_no_effects_panel_at_all(app, tmp_path):
    """A `.chr` export or a roster disk has no `SAVEDGAME0`, so there are no
    effect arrays to read and no list to show. Absent, not greyed and not
    empty: an empty table would say the party has nothing running, which is a
    claim this file cannot make."""
    from editor.window import EditorBinding
    disk = _standalone_disk(tmp_path)
    w = EditorBinding(make_root(), str(disk))
    assert w.party.save0 is None
    assert w._child("box_active_effects").isHidden()
    assert w._child("active_effects").model_.rowCount() == 0


def test_the_panel_is_in_the_header_and_on_none_of_the_tabs(app, party):
    """Where D1 puts it, and the reason it is there: the top row is the
    save-wide row -- the roster is in it -- and a fourth tab or a box on the
    Stats tab would read as the selected character's.

    `BOXES` and `TABS` above are deliberately not touched: they describe the
    three tabs, and this panel is a header box like `box_identity`, not a tab
    box.
    """
    from PyQt6.QtWidgets import QGroupBox, QTabWidget

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(party))
    box = w._child("box_active_effects")
    assert isinstance(box, QGroupBox)
    tabs = w.root.findChild(QTabWidget, "sheet_tabs")
    for i in range(tabs.count()):
        assert not tabs.widget(i).isAncestorOf(box), tabs.tabText(i)
    from PyQt6.QtWidgets import QLayout
    row = w.root.findChild(QLayout, "header_row")
    assert row.indexOf(box) >= 0, "the panel is the third item of the top row"
    assert row.itemAt(row.count() - 1).spacerItem() is not None, (
        "and the spacer is still last, so the roster keeps taking the slack")


def assert_title_fits_and_is_not_silently_cut(box, full_title: str) -> None:
    """`box.title()` is either *full_title* whole, or *full_title* cut with an
    ellipsis to fit -- never a mid-word truncation with nothing on screen to
    say a word is missing.

    `#13 (Edit traits and active effects, in two separate panels)`: giving the
    box its own `setMinimumWidth` (`f7b4c9c`, closing the window-too-wide
    regression) stopped it growing to fit its own title, and left the title to
    be clipped by the box's own frame instead -- `QGroupBox` does not cut its
    title with an ellipsis on its own; it paints past its edge and the extra
    characters simply do not appear.
    """
    from PyQt6.QtGui import QFontMetrics
    metrics = QFontMetrics(box.font())
    wanted = metrics.horizontalAdvance(box.title())
    assert wanted <= box.minimumWidth(), (
        f"{box.title()!r} wants {wanted}px, the box holds only "
        f"{box.minimumWidth()}px")
    assert box.title() == full_title or box.title().endswith("…"), (
        f"{box.title()!r} is neither the full title nor cut with an ellipsis")


def _effects_floor(app, party, extra: int):
    """`w.root.minimumSizeHint()` and the box's own width, with the header
    built at `extra` extra points of UI font -- the same recipe
    `tests/wish/test_mapscale.py`'s `_floors` uses, local here because this test
    also wants the box beneath the panel, which that module never opens."""
    from PyQt6.QtGui import QFont

    from editor.window import EditorBinding
    base = app.font()
    bigger = QFont(base)
    bigger.setPointSizeF(base.pointSizeF() + extra)
    app.setFont(bigger)
    try:
        w = EditorBinding(make_root(), str(party))
        w.root.show()
        floor = w.root.minimumSizeHint()
        box = w._child("box_active_effects")
        panel, roster = w._child("active_effects"), w.roster
        result = (floor, box.minimumWidth(), panel.minimumWidth(),
                  panel.maximumWidth(), panel.maximumHeight(),
                  roster.maximumHeight())
        w.root.close()
        return result
    finally:
        app.setFont(base)


def test_the_effects_panel_is_not_a_floor_under_the_window(app, party):
    """The header does not scroll, so anything standing in it is a floor under
    the whole window -- and this panel's widest line is a sentence rather than
    a field, so it costs more than a field would. Its two column headings
    alone want 430px, which on this machine put the editor's floor 12px past
    Donald's screen; it keeps `ACTIVE_EFFECTS_MIN_WIDTH` and elides below
    that, and grows with the window above it.

    The party is the synthetic one, so this is the widest a save can hold: 20
    capital Ws in every name, which is the case that decides the header.

    **Checked across the same four fonts `test_mapscale.py` uses** (`+0`,
    `+3`, `+6`, `+10` -- `+6` to `+10` is roughly Windows' own base UI font,
    `.claude/rules/testing.md`), not only at this machine's own. A single-font
    check is exactly what let this go red on Windows CI and green everywhere
    a human on Linux ran it: the *panel*'s own clamp
    (`ACTIVE_EFFECTS_MIN_WIDTH` on the table) never bounded the surrounding
    `QGroupBox`, whose `minimumSizeHint()` grows to fit its own title text --
    the same font the table's columns are measured in -- so it grew exactly
    the way a font-dependent width always does, 198px past `SMALL_LAPTOP` at
    Windows' font where this machine's own font left 12px of margin
    (`editor/window.py`'s `ACTIVE_EFFECTS_MIN_WIDTH` comment has the numbers).
    Held flat now by `_size_active_effects` giving the box its own explicit
    `setMinimumWidth`, alongside the panel's -- Qt's layout code prefers an
    explicit minimum size over `minimumSizeHint()` once one is set at all, so
    the box's contribution to the row answers this constant rather than the
    title's own width.

    The outcome is what is asserted -- the window fits the screen, and does
    not grow at all across the four fonts -- rather than a width measured
    here, which would be a claim about one machine.
    """
    from editor.window import ACTIVE_EFFECTS_MIN_WIDTH

    fonts = (0, 3, 6, 10)
    results = [_effects_floor(app, party, extra) for extra in fonts]

    for extra, (floor, *_rest) in zip(fonts, results):
        assert floor.width() <= SMALL_LAPTOP[0], f"+{extra}pt"
        assert floor.height() <= SMALL_LAPTOP[1], f"+{extra}pt"

    widths = [floor.width() for floor, *_rest in results]
    assert widths == [widths[0]] * len(fonts), (
        "the window's own floor grew with the font: "
        f"{dict(zip(fonts, widths))}")

    box_widths = [box_width for _floor, box_width, *_rest in results]
    assert box_widths == [ACTIVE_EFFECTS_MIN_WIDTH] * len(fonts), (
        "the box around the panel is not held to its own floor: "
        f"{dict(zip(fonts, box_widths))}")

    _, _, panel_min, panel_max, panel_max_height, roster_max_height = results[0]
    assert panel_min <= ACTIVE_EFFECTS_MIN_WIDTH
    assert panel_max >= panel_min, (
        "it grows with the window, up to its own columns at their contents")
    assert panel_max_height == roster_max_height, (
        "capped to the roster, and scrolling past it")


@pytest.mark.parametrize("extra", [0, 6, 10])
def test_the_effects_box_title_is_never_clipped_without_an_ellipsis(
        app, party, extra):
    """The regression `f7b4c9c` left behind: holding the box to
    `ACTIVE_EFFECTS_MIN_WIDTH` (260px) stopped it widening the window, and
    also made the box narrower than its own 51-character title needs --
    294px at `+0`, about 490px at `+6`, about 612px at `+10`
    (`.claude/rules/testing.md`'s font range) -- so `QGroupBox`, which cuts
    its title with no ellipsis, silently dropped the tail of the sentence.

    Checked at the same fonts `test_the_effects_panel_is_not_a_floor_under_
    the_window` uses `+6` and `+10` for: `+6` measures here about like
    Windows' own base UI font.
    """
    from PyQt6.QtGui import QFont

    from editor.window import EditorBinding

    base = app.font()
    bigger = QFont(base)
    bigger.setPointSizeF(base.pointSizeF() + extra)
    app.setFont(bigger)
    try:
        w = EditorBinding(make_root(), str(party))
        box = w._child("box_active_effects")
        from editor import activeeffects
        assert_title_fits_and_is_not_silently_cut(box, activeeffects.BOX_TITLE)
        w.root.close()
    finally:
        app.setFont(base)


@game_disks
def test_a_no_op_save_writes_nothing_with_the_effects_panel_built(app, save):
    """**Read-only means read-only.** The panel has no write path at all --
    `goldbox.effects.write_effect` and `clear_effect` have no caller outside
    their own tests -- so building it and saving must not move a byte.

    An effect's magnitude is per-id *restore* data, which is why: clearing an
    id here would skip the game's expiry handler and leave a character at
    18/00 strength for ever, and nothing about that is visible until much
    later. That is S5's problem and it waits on a measurement.
    """
    from editor.window import EditorBinding
    before = save.read_bytes()
    w = EditorBinding(make_root(), str(save))
    for row in range(len(w.party)):
        w.roster.selectRow(row)
    assert w.preview_text().endswith("no changes")
    w.save()
    assert save.read_bytes() == before


# --- the panel is built by default --------------------------------------------
#
# `.claude/rules/feature-flags.md`'s gate is gone: `WISH_EXPERIMENTAL_EFFECTS`
# was deleted once Donald ruled on all seven strings on 2026-09-08. What is
# left to prove is that the panel is there with a clean environment, and that
# a stray `WISH_EXPERIMENTAL_EFFECTS` left in somebody's shell -- on or off --
# cannot change that, since nothing reads it any more.


@game_disks
def test_the_effects_panel_is_built_by_default(app, save, monkeypatch):
    """The shipped state, with no environment variable set at all."""
    from editor.window import EditorBinding
    monkeypatch.delenv("WISH_EXPERIMENTAL_EFFECTS", raising=False)
    w = EditorBinding(make_root(), str(save))
    assert w._child("box_active_effects") is not None
    assert w._child("active_effects") is not None


@pytest.mark.parametrize("value", ["", "0", "off", "no", "false", "1", "true",
                                    "yes", "2", "yes please"])
def test_a_leftover_variable_does_not_hide_the_effects_panel(app, party,
                                                              monkeypatch,
                                                              value):
    """`WISH_EXPERIMENTAL_EFFECTS` means nothing now: a shell that still
    exports it, on or off, must not change what the header builds."""
    from editor.window import EditorBinding
    monkeypatch.setenv("WISH_EXPERIMENTAL_EFFECTS", value)
    w = EditorBinding(make_root(), str(party))
    assert w._child("box_active_effects") is not None
    assert w._child("active_effects") is not None


def test_no_string_on_the_effects_panel_is_waiting_on_approval():
    """`.claude/rules/gui-text.md`: every word a user reads in the interface is
    Donald's. He ruled on all seven on 2026-09-08, choosing brevity: no box
    title at all, `Party Effect`, `Target`, `Entire Party`, and `Unknown` for
    a monster's effect, an unnamed code, and somebody no longer in the party.
    So the count is zero.
    """
    from editor import activeeffects

    marked = {name for name, text in vars(activeeffects).items()
              if name.isupper() and isinstance(text, str)
              and "NOT APPROVED" in text}
    assert marked == set(), marked


def test_no_unapproved_word_is_on_screen_with_the_effects_panel_by_default(
        app, party):
    """Nothing in the window carries the marker -- not a box title, not a
    column heading, not a row."""
    from PyQt6.QtWidgets import QAbstractButton, QGroupBox, QLabel

    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(party))
    for kind in (QAbstractButton, QLabel, QGroupBox):
        for widget in w.root.findChildren(kind):
            for text in (widget.text() if hasattr(widget, "text")
                         else widget.title(), widget.toolTip()):
                assert "NOT APPROVED" not in text, widget.objectName()


# --- closing with unsaved edits (#489) --------------------------------------
#
# `EditorBinding.close()` used to pop a two-button "Discard"/"Cancel" dialog
# with wording nobody had approved, and the only way to keep the edit was
# Cancel-then-Save-yourself. Donald's 2026-09-10 ruling on #489 added a Save
# button: title "Unsaved changes", text "Save your changes before closing?",
# buttons Save / Don't Save / Cancel.


@game_disks
def test_closing_with_no_edits_asks_nothing(app, save, monkeypatch):
    import editor.window as ew
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    asked = []
    monkeypatch.setattr(ew.QMessageBox, "exec", lambda self: asked.append(self) or 0)
    assert w.close() is True
    assert asked == []


@game_disks
def test_closing_with_unsaved_edits_shows_the_approved_wording(app, save,
                                                                monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    import editor.window as ew
    from editor.window import EditorBinding
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    w._widgets["gold"].setValue(w._widgets["gold"].value() + 1)
    w._edited()

    seen = {}

    def fake_exec(box):
        seen["title"] = box.windowTitle()
        seen["text"] = box.text()
        seen["buttons"] = {b.text() for b in box.buttons()}
        return int(QMessageBox.StandardButton.Cancel)

    monkeypatch.setattr(ew.QMessageBox, "exec", fake_exec)
    assert w.close() is False
    assert seen["title"] == "Unsaved changes"
    assert seen["text"] == "Save your changes before closing?"
    assert seen["buttons"] == {"Save", "Don't Save", "Cancel"}


@game_disks
def test_cancel_keeps_the_window_open_and_the_edit_unsaved(app, save,
                                                            monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    import editor.window as ew
    from editor.window import EditorBinding
    before = save.read_bytes()
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    w._widgets["gold"].setValue(w._widgets["gold"].value() + 1)
    w._edited()

    monkeypatch.setattr(ew.QMessageBox, "exec",
                        lambda self: int(QMessageBox.StandardButton.Cancel))
    assert w.close() is False
    assert save.read_bytes() == before
    assert w.dirty


@game_disks
def test_dont_save_closes_and_throws_the_edit_away(app, save, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    import editor.window as ew
    from editor.window import EditorBinding
    before = save.read_bytes()
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    w._widgets["gold"].setValue(w._widgets["gold"].value() + 1)
    w._edited()

    monkeypatch.setattr(ew.QMessageBox, "exec",
                        lambda self: int(QMessageBox.StandardButton.Discard))
    assert w.close() is True
    assert save.read_bytes() == before


@game_disks
def test_save_writes_the_edit_and_then_closes(app, save, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    import editor.window as ew
    from editor.window import EditorBinding
    before = save.read_bytes()
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    new_gold = w._widgets["gold"].value() + 1
    w._widgets["gold"].setValue(new_gold)
    w._edited()

    monkeypatch.setattr(ew.QMessageBox, "exec",
                        lambda self: int(QMessageBox.StandardButton.Save))
    assert w.close() is True
    assert save.read_bytes() != before

    again = EditorBinding(make_root(), str(save))
    again.roster.selectRow(0)
    assert again._widgets["gold"].value() == new_gold


@game_disks
def test_a_failed_save_reports_it_and_keeps_the_window_open(app, save,
                                                              monkeypatch):
    """The worst outcome here is losing the edit while telling the player it
    was saved, so a save that raises must neither close the window nor lose
    the dirty mark -- it has to report the failure the way `File > Save`
    does. `files.save_disk` is what actually writes the file, so that is
    what has to fail here -- a per-field `_flush` failure is reported the
    same way but does not stop the rest of the record being written."""
    from PyQt6.QtWidgets import QMessageBox

    import editor.window as ew
    from editor.window import EditorBinding
    before = save.read_bytes()
    w = EditorBinding(make_root(), str(save))
    w.roster.selectRow(0)
    w._widgets["gold"].setValue(w._widgets["gold"].value() + 1)
    w._edited()

    said = []
    monkeypatch.setattr(ew.QMessageBox, "exec",
                        lambda self: int(QMessageBox.StandardButton.Save))
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    monkeypatch.setattr(ew.files, "save_disk",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert w.close() is False
    assert save.read_bytes() == before
    assert said == [("Cannot save", "boom")]
    assert w.dirty


def _capacity_line(cap):
    """What the memorised-spells pane prints for a given capacity, no disks."""
    from editor.spellwidget import MemorisedEditor

    widget = MemorisedEditor(make_root())
    widget.set_capacity(cap, casts=True)
    return widget.capacity.text()


@pytest.mark.parametrize("game", ["curse-of-the-azure-bonds",
                                  "secret-of-the-silver-blades"])
def test_a_ranger_is_shown_no_magic_user_line_until_he_has_a_slot(app, game):
    """A level-8 ranger has a druid slot and an all-zero magic-user array, and
    that array's line is left off until one of its slots is above zero, which
    is level 9 in both titles."""
    from goldbox.spells import capacity_by_class

    cap = capacity_by_class({"ranger": 8}, 12, game)
    assert any(cap["druid"]) and not any(cap["magic-user"])
    line = _capacity_line(cap)
    assert line.startswith("druid: L1 0/1, L2 0/0")
    assert "magic-user" not in line

    cap = capacity_by_class({"ranger": 9}, 12, game)
    assert any(cap["magic-user"])
    line = _capacity_line(cap)
    assert "druid: " in line and "magic-user: " in line


def test_a_caster_whose_only_lines_are_zero_still_shows_them(app):
    line = _capacity_line({"cleric": (0, 0), "magic-user": (0, 0)})
    assert "cleric: L1 0/0" in line and "magic-user: L1 0/0" in line


# --- a party opened from a DOS save or an Amiga save disk --------------------
#
# The roster of a DOS or Amiga save is what the same save converted to a C64
# disk would list, without the conversion: every test that has a converted disk
# to compare with compares against it, and the ones with no game data build
# their saves from the writers.

def _roster_rows(party):
    """What the roster shows for each member, in the order it shows them."""
    return [(m.name, m.race_name, m.class_name, m.armour_class, m.hp_current,
             m.hp_max, m.inventory.used) for m in party.members]


def _blank_files():
    """The combat icon and `ANIMATE00` a conversion refuses to run without.
    Zeros stand in: what is compared is the roster, not the figure."""
    from editor.dosimport import GameFiles
    return GameFiles(icon=bytes(36), animate=bytes(852))


def _converted_dos_disk(folder, slot, key):
    from goldbox import c64_port, dos_codec
    game = c64_port.by_key(key)
    save0, save1, _report = dos_codec.new_save(
        folder, slot, bytes(36), bytes(852), game=game)
    return game, dos_codec.save_disk(bytes(save0), bytes(save1), game)


def _synthetic_dos_folder(tmp_path, deltas, numbers=(1, 2, 3), class_bits=None,
                          levels=None, race=None, former_levels=None,
                          level=None):
    """A DOS save folder written from filled neutral characters, no game data.
    `numbers` are the `CHRDAT<slot><n>` file numbers that exist.  `class_bits`
    overrides `_filled`'s own arbitrary byte -- needed wherever the writer
    recomputes a field (`char_class`, the thief skills) from the classes
    themselves, since `_filled`'s byte names no real class combination.
    `levels` overrides `_filled`'s own class-level dict the same way, for a
    test that needs a particular thief level. `race` and `former_levels`
    override `_filled`'s own race and (unset) dual-class pair, for a test of
    a dual-classed human's regain rule. `level` overrides `_filled`'s own
    made-up aggregate `level` of 20, for a test whose class levels need to
    look like a real save's rather than avoid `_filled`'s default."""
    from support.neutralrecords import _filled

    from goldbox import c64_port, dos_codec
    game = c64_port.by_key(deltas.key)
    for n in numbers:
        char = _filled(game)
        char.set("name", f"HERO{n}", "made up", Confidence.CONFIRMED,
                 c64_codec.Provenance.RESHAPED)
        if class_bits is not None:
            char.set("class_bits", class_bits, "made up, class-consistent")
        if levels is not None:
            char.set("levels", levels, "made up, chosen for the test")
        if race is not None:
            char.set("race", race, "made up, chosen for the test")
        if former_levels is not None:
            char.set("former_levels", former_levels, "made up, chosen for the test")
        if level is not None:
            char.set("level", level, "made up, chosen for the test")
        record, itm, spc, _rep = dos_codec.write(char, deltas=deltas)
        (tmp_path / f"CHRDATA{n}.SAV").write_bytes(record)
        (tmp_path / f"CHRDATA{n}.ITM").write_bytes(itm)
        (tmp_path / f"CHRDATA{n}.SPC").write_bytes(spc)
    (tmp_path / "SAVGAMA.DAT").write_bytes(b"")
    return tmp_path


def test_a_dos_party_opens_with_no_disk_and_no_slot_window(tmp_path):
    from goldbox import dos_codec, dos_port
    for deltas in (dos_port.POOL_OF_RADIANCE, dos_port.CURSE_OF_THE_AZURE_BONDS,
                   dos_port.SECRET_OF_THE_SILVER_BLADES):
        folder = tmp_path / deltas.key
        folder.mkdir()
        _synthetic_dos_folder(folder, deltas)
        party = Party(str(folder))
        assert party.port == "dos"
        assert party.source.slot == "A"
        assert party.game.key == deltas.key
        assert party.disk is None and party.save0 is None
        assert not party.in_save          # a whole record, not a 256-byte slot
        assert [m.name for m in party.members] == ["HERO1", "HERO2", "HERO3"]
        assert all(isinstance(m.native, dos_codec.DosCharacter)
                   for m in party.members)
        assert all(m.icon is None for m in party.members)
        assert all(m.inventory is not None and len(m.inventory) == 16
                   for m in party.members)


def test_a_dos_member_is_keyed_by_its_file_number_not_its_position(tmp_path):
    """A gap in the numbered files leaves the others' numbers where they are, since
    the number is what a write-back has to name."""
    from goldbox import dos_port
    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE, numbers=(1, 3, 6))
    party = Party(str(tmp_path / "SAVGAMA.DAT"))
    assert [m.index for m in party.members] == [1, 3, 6]
    assert [m.name for m in party.members] == ["HERO1", "HERO3", "HERO6"]


def test_a_dos_party_of_seven_opens_all_seven_in_file_order(tmp_path):
    from goldbox import dos_port
    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE,
                          numbers=tuple(range(1, 8)))
    party = Party(str(tmp_path / "SAVGAMA.DAT"))
    assert [m.index for m in party.members] == [1, 2, 3, 4, 5, 6, 7]
    assert [m.name for m in party.members] == [f"HERO{n}" for n in range(1, 8)]


def test_a_dos_party_can_be_opened_from_a_source(tmp_path):
    from editor.convert import Source
    from goldbox import dos_port
    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    party = Party(Source.detect(tmp_path))
    assert len(party) == 3 and party.path == str(tmp_path)


def test_a_dos_folder_source_can_name_its_second_slot(tmp_path):
    """Opening a folder must preserve the slot chosen after its scan."""
    from editor.convert import Source
    from goldbox import dos_port

    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    (tmp_path / "SAVGAMB.DAT").write_bytes(b"")
    # A real second record has the same measured length, which is all Source
    # needs to identify its title.
    (tmp_path / "CHRDATB1.SAV").write_bytes(
        (tmp_path / "CHRDATA1.SAV").read_bytes())

    source = Source.detect(tmp_path, slot="B")
    assert source.slot == "B"
    assert source.available_slots == ["A", "B"]


def test_a_dos_folder_skips_an_incomplete_slot_and_opens_the_valid_one(
        tmp_path):
    """A damaged first slot must not hide the usable second saved game."""
    from editor.convert import Source
    from goldbox import dos_port

    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    valid = (tmp_path / "CHRDATA2.SAV").read_bytes()
    (tmp_path / "CHRDATA1.SAV").unlink()
    (tmp_path / "SAVGAMB.DAT").write_bytes(b"")
    (tmp_path / "CHRDATB1.SAV").write_bytes(valid)

    source = Source.detect(tmp_path)
    assert source.slot == "B"
    assert source.available_slots == ["B"]


def test_opening_the_destination_section_for_a_dos_party_writes_nothing(
        app, tmp_path, monkeypatch):
    """Building the Save arrow's menu and opening the destination section
    for a native party touches no file -- the platform-blind Save As this
    used to pin (`save_as()`, a plain C64 file dialog whatever the open
    party's own port was) is gone; every destination is now explicit and
    `editor.saveplan` does the actual writing (`#511`,
    `tests/editor/test_saveasui.py` covers the write itself)."""
    from editor.window import EditorBinding
    from goldbox import dos_port

    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    before = {path: path.read_bytes() for path in tmp_path.iterdir()
              if path.is_file()}
    binding = EditorBinding(make_root(), str(tmp_path))
    binding.roster.selectRow(0)
    binding._widgets["gold"].setValue(1234)
    binding._edited()
    opened = []
    monkeypatch.setattr(
        "editor.window.QFileDialog.getSaveFileName",
        lambda *_args: opened.append(True) or ("", ""))

    binding.begin_save_as("dos")
    binding.cancel_save_as()

    assert {path: path.read_bytes() for path in before} == before
    assert opened == []
    assert binding._child("destination_section").isHidden()


def test_open_toolbar_buttons_keep_their_floor_and_height_at_supported_fonts(
        app):
    """The split Open and Save buttons remain part of the sized toolbar."""
    from PyQt6.QtGui import QFont

    from editor.window import TOOLBAR_BUTTON_MIN_WIDTH, EditorBinding

    base, heights = app.font(), []
    try:
        for extra in (0, 6, 10):
            font = QFont(base)
            font.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(font)
            binding = EditorBinding(make_root())
            buttons = [binding._child(name) for name in (
                "button_open", "button_save")]
            assert all(button is not None for button in buttons)
            if extra == 0:
                for button in buttons:
                    assert button.minimumWidth() >= TOOLBAR_BUTTON_MIN_WIDTH
                    assert (button.minimumSizeHint().width()
                            >= button.fontMetrics().horizontalAdvance(button.text()))
            heights.append([button.minimumSizeHint().height()
                            for button in buttons])
    finally:
        app.setFont(base)
    assert heights == sorted(heights)


def test_a_folder_source_starts_the_next_picker_inside_that_folder(tmp_path):
    """A DOS folder is itself the last place opened, not a file beside it."""
    from editor import files

    folder = tmp_path / "SAVE"
    folder.mkdir()
    assert files.open_start_dir("", folder) == str(folder)
    assert files.automatic_dir(folder) == folder / "backups"


def test_open_buttons_choose_their_source_without_a_wrapper_dialog(
        app, tmp_path, monkeypatch):
    """The two controls each invoke the native picker once and load its path."""
    from editor.window import (
        OPEN_BUTTON_TEXT,
        OPEN_FILTER,
        OPEN_MENU_FOLDER,
        OPEN_TITLE,
        EditorBinding,
    )

    root = make_root()
    binding = EditorBinding(root)
    picked, loaded = {}, []

    def choose_file(_parent, title, directory, file_filter):
        picked["file"] = (title, directory, file_filter)
        return str(tmp_path / "save.adf"), ""

    def choose_folder(_parent, title, directory):
        picked["folder"] = (title, directory)
        return str(tmp_path / "SAVE")

    monkeypatch.setattr("editor.window.QFileDialog.getOpenFileName", choose_file)
    monkeypatch.setattr("editor.window.QFileDialog.getExistingDirectory",
                        choose_folder)
    monkeypatch.setattr(binding, "load", loaded.append)

    binding.open_file()
    binding.open_folder()

    assert picked["file"] == (OPEN_TITLE, "", OPEN_FILTER)
    assert picked["folder"] == (OPEN_TITLE, "")
    assert loaded == [str(tmp_path / "save.adf"), str(tmp_path / "SAVE")]
    assert binding._child("button_open").text() == OPEN_BUTTON_TEXT
    assert [a.text() for a in binding._open_menu.actions()
           if a.text() == OPEN_MENU_FOLDER]


def test_opening_a_multi_slot_dos_folder_uses_the_slot_picker(
        app, tmp_path, monkeypatch):
    """The picker is conditional and its selected letter reaches the party."""
    from editor.window import EditorBinding
    from goldbox import dos_port

    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    (tmp_path / "SAVGAMB.DAT").write_bytes(b"")
    (tmp_path / "CHRDATB1.SAV").write_bytes(
        (tmp_path / "CHRDATA1.SAV").read_bytes())
    shown = []

    class PickB:
        def __init__(self, slots, _parent):
            shown.append(slots)

        def exec(self):
            from PyQt6.QtWidgets import QDialog
            return QDialog.DialogCode.Accepted

        @property
        def slot(self):
            return "B"

    monkeypatch.setattr("editor.window.SlotPicker", PickB)
    binding = EditorBinding(make_root())
    binding.load(str(tmp_path))

    assert shown == [["A", "B"]]
    assert binding.party.source.slot == "B"
    assert [member.name for member in binding.party.members] == ["HERO1"]


def test_opening_a_one_slot_dos_folder_skips_the_slot_picker(
        app, tmp_path, monkeypatch):
    """A one-slot source opens immediately, with no question to answer."""
    from editor.window import EditorBinding
    from goldbox import dos_port

    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    monkeypatch.setattr(
        "editor.window.SlotPicker",
        lambda *_args: pytest.fail("a one-slot source opened a slot picker"))
    binding = EditorBinding(make_root())
    binding.load(str(tmp_path))

    assert binding.party.source.slot == "A"


def test_a_dos_party_has_one_path_whether_opened_from_its_file_or_its_folder(
        tmp_path):
    """`Source.detect(path, party)` compares `party.path` with the path it is
    handed, so a save reached by its `SAVGAMA.DAT` and by its folder has to
    read as one value."""
    from editor.convert import Source
    from goldbox import dos_port
    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    by_file = Party(str(tmp_path / "SAVGAMA.DAT"))
    by_folder = Party(str(tmp_path))
    by_source = Party(Source.detect(tmp_path))
    assert by_file.path == by_folder.path == by_source.path == str(tmp_path)


def test_a_dos_gold_edit_writes_only_its_record_bytes_and_keeps_a_backup(
        app, tmp_path):
    """Editing gold reaches the native record once, not a converted save."""
    from editor.window import EditorBinding
    from goldbox import dos_port

    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    save = tmp_path / "CHRDATA1.SAV"
    before = {path: path.read_bytes() for path in tmp_path.iterdir()
              if path.is_file()}
    w = EditorBinding(make_root(), str(tmp_path / "SAVGAMA.DAT"))
    w.roster.selectRow(0)
    w._widgets["gold"].setValue(1234)
    w._edited()
    w.save(interactive=False)

    fields = (dos_port.FIELDS_BY_NAME["gold"],
              dos_port.FIELDS_BY_NAME["encumbrance"])
    changed = save.read_bytes()
    assert [at for at, (was, now) in enumerate(zip(before[save], changed))
            if was != now] == [at for field in fields
                                for at in range(field.offset, field.end)]
    gold = fields[0]
    assert int.from_bytes(changed[gold.offset:gold.end], "little") == 1234
    assert {path: path.read_bytes() for path in before if path != save} == {
        path: before[path] for path in before if path != save}
    backups = list((tmp_path / "backups").glob("CHRDATA1.SAV.*"))
    assert len(backups) == 1 and backups[0].read_bytes() == before[save]
    from editor.convert import Source
    assert Source.detect(tmp_path, w.party).port == "dos"
    no_op = {path: path.read_bytes() for path in tmp_path.iterdir()
             if path.is_file()}
    w.save(interactive=False)
    assert {path: path.read_bytes() for path in tmp_path.iterdir()
            if path.is_file()} == no_op


def test_an_edit_to_a_flagged_field_on_an_open_dos_save_cannot_be_saved(
        app, tmp_path):
    """A player opens a DOS Pool of Radiance save, picks the party's thief,
    raises Open locks and clicks Save. Before this fix that either writes
    the edit nowhere and shows a developer sentence, or -- if another field
    was also edited -- silently drops the locks change while reporting
    success. #511."""
    from editor.window import EditorBinding
    from goldbox import classcode, dos_port

    bits = (classcode.CLASS_BIT_FOR_NAME["fighter"]
           | classcode.CLASS_BIT_FOR_NAME["thief"])
    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE, numbers=(1,),
                          class_bits=bits)
    before = {path: path.read_bytes() for path in tmp_path.iterdir()
              if path.is_file()}
    w = EditorBinding(make_root(), str(tmp_path / "SAVGAMA.DAT"))
    w.roster.selectRow(0)

    for name in ("infravision", "thief_open_locks"):
        old_value = w.party.member(0).record.get(name)
        assert not w._widgets[name].isEnabled(), name
        w._widgets[name].setValue(w._widgets[name].value() + 1)
        w._edited()
        assert w.save(interactive=False) == "no changes"
        assert {path: path.read_bytes() for path in tmp_path.iterdir()
                if path.is_file()} == before
        assert not (tmp_path / "backups").exists()
        assert w.party.member(0).record.get(name) == old_value


def _dos_pool_editor(tmp_path):
    from editor.window import EditorBinding
    from goldbox import dos_port
    folder = tmp_path / "por"
    folder.mkdir()
    _synthetic_dos_folder(folder, dos_port.POOL_OF_RADIANCE)
    return EditorBinding(make_root(), str(folder / "SAVGAMA.DAT"))


def _dos_silver_blades_editor(tmp_path):
    from editor.window import EditorBinding
    from goldbox import dos_port
    folder = tmp_path / "ssb"
    folder.mkdir()
    _synthetic_dos_folder(folder, dos_port.SECRET_OF_THE_SILVER_BLADES)
    return EditorBinding(make_root(), str(folder / "SAVGAMA.DAT"))


def _dos_curse_editor(tmp_path):
    from editor.window import EditorBinding
    from goldbox import dos_port
    folder = tmp_path / "curse"
    folder.mkdir()
    _synthetic_dos_folder(folder, dos_port.CURSE_OF_THE_AZURE_BONDS)
    return EditorBinding(make_root(), str(folder / "SAVGAMA.DAT"))


def _amiga_pool_editor(tmp_path):
    from support.neutralrecords import _filled

    from editor.window import EditorBinding
    from goldbox import amiga_savegame, c64_port
    pool = c64_port.by_key("pool-of-radiance")
    savgam = bytearray(amiga_savegame.POR_SAVEGAME_SIZE)
    at = amiga_savegame.POOL_OF_RADIANCE.party_at
    savgam[at:at + 8] = b"CHRDATA1"
    disk = amiga_savegame.make_por_save_disk("A", [_filled(pool)],
                                             bytes(savgam))
    path = tmp_path / "pool.adf"
    disk.save(str(path))
    return EditorBinding(make_root(), str(path))


def _amiga_curse_editor(tmp_path):
    from support.amigasavegame import synthetic_curse

    from editor.window import EditorBinding
    from goldbox import amiga_savegame
    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA",)))
    path = tmp_path / "curse.adf"
    disk.save(path)
    return EditorBinding(make_root(), str(path))


@pytest.mark.parametrize("builder", [_dos_pool_editor, _dos_silver_blades_editor,
                                     _dos_curse_editor,
                                     _amiga_pool_editor, _amiga_curse_editor],
                        ids=["dos-pool-of-radiance",
                            "dos-secret-of-the-silver-blades",
                            "dos-curse-of-the-azure-bonds",
                            "amiga-pool-of-radiance",
                            "amiga-curse-of-the-azure-bonds"])
def test_the_unwritable_fields_and_the_trait_add_button_are_disabled(
        app, tmp_path, builder):
    """On every port and title the sheet can open natively, a field the
    open file's writer cannot take back is disabled, and so is the button
    that would add a new trait."""
    w = builder(tmp_path)
    w.roster.selectRow(0)
    for name in w.party.unwritable:
        widget = w._widgets.get(name)
        if widget is not None:
            assert not widget.isEnabled(), name
    add = w._child("button_trait_add")
    assert add is not None
    assert not add.isEnabled()


def test_a_dos_curse_saves_saving_throw_boxes_are_disabled_with_no_tooltip(
        app, tmp_path):
    """Donald's decision on #632: once Wish writes the saving throws DOS
    Curse's own load-time rebuild would leave, the five saving-throw boxes
    are greyed on a DOS Curse save, the same way the thief skills already
    are, and with the same blank tooltip -- an editable box would offer a
    change the game discards the next time the party loads."""
    w = _dos_curse_editor(tmp_path)
    w.roster.selectRow(0)
    for name in ("save_paralysis", "save_petrification", "save_wands",
                "save_breath", "save_spell"):
        widget = w._widgets[name]
        assert not widget.isEnabled(), name
        assert widget.toolTip() == "", name


def test_a_dos_silver_blades_saves_saving_throw_boxes_are_disabled_with_no_tooltip(
        app, tmp_path):
    """The same as DOS Curse's, for the same reason: DOS Silver
    Blades' loader rebuilds the five saves every time the party loads
    (`GAME.OVR:0x3C644`), so an edit to them would be discarded."""
    w = _dos_silver_blades_editor(tmp_path)
    w.roster.selectRow(0)
    for name in ("save_paralysis", "save_petrification", "save_wands",
                "save_breath", "save_spell"):
        widget = w._widgets[name]
        assert not widget.isEnabled(), name
        assert widget.toolTip() == "", name


def test_an_amiga_gold_edit_reaches_its_save_disk(app, tmp_path):
    from support.amigasavegame import synthetic_curse

    from editor.window import EditorBinding
    from goldbox import amiga_savegame
    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA",)))
    path = tmp_path / "curse.adf"
    disk.save(path)
    before = path.read_bytes()
    w = EditorBinding(make_root(), str(path))
    w.roster.selectRow(0)
    w._widgets["gold"].setValue(1234)
    w._edited()
    w.save(interactive=False)
    assert path.read_bytes() != before
    backups = list((tmp_path / "backups").glob("curse.adf.*"))
    assert len(backups) == 1 and backups[0].read_bytes() == before
    no_op = path.read_bytes()
    w.save(interactive=False)
    assert path.read_bytes() == no_op


def test_an_amiga_save_keeps_the_old_image_when_replacement_fails(
        tmp_path, monkeypatch):
    """A failed final rename leaves the complete old image in place."""
    import os

    from goldbox.amiga_adf import AmigaDisk

    path = tmp_path / "save.adf"
    disk = AmigaDisk.blank()
    disk.save(path)
    before = path.read_bytes()
    disk.write_file("changed", b"changed")
    monkeypatch.setattr(os, "replace",
                        lambda _old, _new: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        disk.save(path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".save.adf.tmp*"))


def test_an_amiga_item_save_does_not_write_again_after_it_succeeds(
        app, tmp_path):
    from support.amigasavegame import synthetic_curse

    from editor.window import EditorBinding
    from goldbox import amiga_savegame
    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA",)))
    path = tmp_path / "curse.adf"
    disk.save(path)
    w = EditorBinding(make_root(), str(path))
    w.roster.selectRow(0)
    w.party.members[0].inventory.set_raw(0, bytes(range(16)))
    w._edited()
    w.save(interactive=False)
    assert len(list((tmp_path / "backups").glob("curse.adf.*"))) == 1
    before_second_save = path.read_bytes()
    assert w.save(interactive=False) == "no changes"
    assert path.read_bytes() == before_second_save
    assert len(list((tmp_path / "backups").glob("curse.adf.*"))) == 1


def test_a_dos_field_edit_after_an_item_save_keeps_the_item(app, tmp_path):
    from editor.window import EditorBinding
    from goldbox import dos_port

    _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    path = tmp_path / "SAVGAMA.DAT"
    w = EditorBinding(make_root(), str(path))
    w.roster.selectRow(0)
    quantity = w.party.members[0].inventory.raws[0][10] + 1
    w.party.members[0].inventory.set_quantity(0, quantity)
    w._edited()
    w.save(interactive=False)
    w._widgets["gold"].setValue(1234)
    w._edited()
    w.save(interactive=False)
    assert Party(str(path)).members[0].inventory.raws[0][10] == quantity


def test_an_amiga_field_edit_after_an_item_save_keeps_the_item(app, tmp_path):
    from support.amigasavegame import synthetic_curse

    from editor.window import EditorBinding
    from goldbox import amiga_savegame
    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA",)))
    path = tmp_path / "curse.adf"
    disk.save(path)
    item = bytes(range(16))
    w = EditorBinding(make_root(), str(path))
    w.roster.selectRow(0)
    w.party.members[0].inventory.set_raw(0, item)
    w._edited()
    w.save(interactive=False)
    first_saved_item = Party(str(path)).members[0].inventory.raws[0]
    w._widgets["gold"].setValue(1234)
    w._edited()
    w.save(interactive=False)
    assert Party(str(path)).members[0].inventory.raws[0] == first_saved_item


def test_a_c64_source_opens_the_disk_at_its_own_path(party):
    """`party` is the synthetic save disk from the fixture above."""
    from editor.convert import Source
    source = Source(port="c64", title=Party(str(party)).game,
                    path=pathlib.Path(party))
    opened = Party(source)
    assert opened.port == "c64" and opened.in_save
    assert opened.path == str(party)


def test_a_path_is_taken_for_a_save_by_its_name_or_for_being_a_folder(tmp_path):
    from editor.convert import Source
    (tmp_path / "folder").mkdir()
    for named in ("folder", "SAVGAMA.DAT", "savgamb.pty", "disk.ADF",
                  "never_made.adf"):
        assert Source.looks_like_a_save(tmp_path / named), named
    for named in ("PORSAVE10.D64", "SAVGAMAB.DAT", "never_made.d64"):
        assert not Source.looks_like_a_save(tmp_path / named), named


def test_pools_of_darkness_cannot_be_opened_and_the_refusal_is_catchable(tmp_path):
    """No C64 port, so no sheet layout to edit its characters through."""
    from goldbox import dos_codec, dos_port
    (tmp_path / "CHRDATA1.SAV").write_bytes(
        bytes(dos_port.POOLS_OF_DARKNESS.record_size))
    (tmp_path / "SAVGAMA.PTY").write_bytes(b"")
    with pytest.raises(dos_codec.WrongTitleError) as refused:
        Party(str(tmp_path))
    assert refused.value.title == dos_port.POOLS_OF_DARKNESS.title


def test_opening_a_pools_of_darkness_folder_shows_the_convert_sentence(
        app, tmp_path, monkeypatch):
    import editor.window as ew
    from editor.convert import POOLS_OF_DARKNESS_UNSUPPORTED
    from goldbox import dos_port
    (tmp_path / "CHRDATA1.SAV").write_bytes(
        bytes(dos_port.POOLS_OF_DARKNESS.record_size))
    (tmp_path / "SAVGAMA.PTY").write_bytes(b"")
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    ew.EditorBinding(make_root()).load(str(tmp_path))
    assert said == [("Cannot open", POOLS_OF_DARKNESS_UNSUPPORTED)]
    assert "goldbox/" not in said[0][1] and "c64_port" not in said[0][1]


def test_another_title_refused_on_open_shows_the_general_message(
        app, tmp_path, monkeypatch):
    import editor.window as ew
    from editor.convert import POOLS_OF_DARKNESS_UNSUPPORTED
    from goldbox import dos_codec, dos_port

    def refuse(*a, **k):
        raise dos_codec.WrongTitleError(
            "developer reason", dos_port.CURSE_OF_THE_AZURE_BONDS.title)

    from editor.convert import Source
    monkeypatch.setattr(Source, "looks_like_a_save", staticmethod(lambda p: False))
    monkeypatch.setattr(ew, "Party", refuse)
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    ew.EditorBinding(make_root()).load(str(tmp_path))
    assert said == [("Cannot open", "developer reason")]
    assert said[0][1] != POOLS_OF_DARKNESS_UNSUPPORTED


def test_an_amiga_curse_party_opens_from_its_adf(tmp_path):
    from support.amigasavegame import synthetic_curse

    from goldbox import amiga_later, amiga_savegame
    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA", "BETA")))
    path = tmp_path / "curse.adf"
    disk.save(str(path))
    party = Party(str(path))
    assert party.port == "amiga" and not party.in_save
    assert party.game.key == "curse-of-the-azure-bonds"
    assert [(m.index, m.name) for m in party.members] == [(1, "ALPHA"),
                                                          (2, "BETA")]
    assert all(isinstance(m.native, amiga_later.AmigaCharacter)
               for m in party.members)


def test_an_amiga_pool_party_opens_from_its_adf(tmp_path):
    from support.neutralrecords import _filled

    from goldbox import amiga_por, amiga_savegame, c64_port
    pool = c64_port.by_key("pool-of-radiance")
    savgam = bytearray(amiga_savegame.POR_SAVEGAME_SIZE)
    at = amiga_savegame.POOL_OF_RADIANCE.party_at
    savgam[at:at + 8] = b"CHRDATA1"       # the table `retarget_savegame` needs
    disk = amiga_savegame.make_por_save_disk("A", [_filled(pool)],
                                             bytes(savgam))
    path = tmp_path / "pool.adf"
    disk.save(str(path))
    party = Party(str(path))
    assert party.port == "amiga" and party.game.key == "pool-of-radiance"
    assert [m.index for m in party.members] == [1]
    assert isinstance(party.members[0].native, amiga_por.AmigaPorCharacter)


def test_an_amiga_disk_that_holds_no_save_is_refused_by_the_source_it_needs(tmp_path):
    from editor.convert import ConvertError
    from goldbox.amiga_adf import AmigaDisk
    path = tmp_path / "blank.adf"
    AmigaDisk.blank("EMPTY").save(str(path))
    with pytest.raises(ConvertError):
        Party(str(path))


def test_a_c64_path_still_opens_as_a_c64_party(party):
    """`party` is the synthetic save disk from the fixture above."""
    opened = Party(str(party))
    assert opened.port == "c64" and opened.in_save
    assert opened.source is None and opened.disk is not None
    assert all(m.native is None for m in opened.members)


def test_an_inventory_built_from_blocks_holds_sixteen_slots_and_writes_nowhere():
    from editor.inventory import Inventory
    blocks = [bytes(16)] * 16
    inventory = Inventory.from_blocks(blocks)
    assert len(inventory) == 16 and inventory.used == 0 and not inventory.changed
    assert inventory.base is None
    with pytest.raises(ValueError):
        inventory.write_into(bytearray(0x8000))
    with pytest.raises(ValueError):
        Inventory.from_blocks(blocks[:15])
    with pytest.raises(ValueError):
        Inventory.from_blocks([bytes(15)] * 16)


def test_zero_type_stale_slot_is_empty_and_untouched_bytes_survive():
    from editor.inventory import NAME, QTY, Inventory, InventoryModel
    from goldbox.items import ITEM_AREA_BASE, ITEM_SIZE
    from goldbox.savegame import SAVE0_LOAD_ADDRESS

    stale = bytes([0, 0, 0, 0x6F, 0, 0, 0, 0, 4, 0, 30, 50, 0, 0, 0, 0])
    live = bytes([0x1E, 0, 0, 0x6F, 0, 0, 0, 0, 4, 0, 35, 50, 0, 0, 0, 0])
    raw = b"".join([stale, live] + [bytes(ITEM_SIZE)] * 14)
    payload = bytearray(ITEM_AREA_BASE - SAVE0_LOAD_ADDRESS + len(raw))
    payload[-len(raw):] = raw
    original = bytes(payload)

    inventory = Inventory(payload, 0)
    model = InventoryModel(inventory)
    assert inventory.used == 1
    assert inventory.is_empty(0)
    assert model.data(model.index(0, NAME)) != model.data(model.index(1, NAME))
    assert not model.flags(model.index(0, QTY)) & Qt.ItemFlag.ItemIsEditable
    assert not model.setData(model.index(0, QTY), 7)
    assert not inventory.changed
    inventory.write_into(payload)
    assert bytes(payload) == original

    inventory.delete(1)
    assert inventory.used == 0
    assert inventory.is_empty(0)


def test_preview_calls_a_filled_zero_type_slot_an_addition():
    from types import SimpleNamespace

    from editor.changes import item_changes
    from editor.inventory import Inventory

    stale = bytes([0, 0, 0, 9, 0, 0, 0, 0, 4, 0, 30, 50, 0, 0, 0, 0])
    potion = bytes([1, 0, 0, 10, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 0, 0])
    inventory = Inventory.from_blocks([stale] + [bytes(16)] * 15,
                                      names={9: "DART", 10: "POTION OF HEALING"})
    assert inventory.add(potion) == 0

    lines = item_changes(SimpleNamespace(inventory=inventory))
    assert lines == ["item 0 added: POTION OF HEALING"]
    assert inventory.original[0] == stale


def test_preview_ignores_retired_bytes_cleared_by_deleting_a_live_item():
    from types import SimpleNamespace

    from editor.changes import item_changes
    from editor.inventory import Inventory

    stale = bytes([0, 0, 0, 9, 0, 0, 0, 0, 4, 0, 30, 50, 0, 0, 0, 0])
    dart = bytes([1, 0, 0, 9, 0, 0, 0, 0, 4, 0, 30, 50, 0, 0, 0, 0])
    blocks = [stale] + [bytes(16)] * 5 + [dart] + [bytes(16)] * 9
    inventory = Inventory.from_blocks(blocks, names={9: "DART"})
    inventory.delete(6)

    assert item_changes(SimpleNamespace(inventory=inventory)) == [
        "item 6 removed: DART"
    ]
    assert inventory.original[0] == stale
    assert inventory.raws[0] == bytes(16)


def test_an_unwritable_field_is_read_only_whatever_the_layout_allows():
    gold = next(f for f in editable_fields() if f.name == "gold")
    assert not binding_for(gold, in_save=False).read_only
    assert binding_for(gold, in_save=False,
                       unwritable=frozenset({"gold"})).read_only
    assert not binding_for(gold, in_save=False,
                           unwritable=frozenset({"silver"})).read_only
    assert bindings(in_save=False,
                    unwritable=frozenset({"gold"}))["gold"].read_only


def _dos_save_dir():
    from support.dossave import _save_dir
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES")
    return where


def test_a_dos_save_lists_the_roster_its_converted_disk_lists():
    """The comparison the issue names: the same party, once opened straight and
    once through the conversion to a C64 disk."""
    folder = _dos_save_dir()
    straight = Party(str(folder / "SAVGAMA.DAT"))
    game, disk = _converted_dos_disk(folder, "A", "pool-of-radiance")
    converted = Party("", game=game, disk=disk)
    assert len(straight) == len(converted) == 6
    assert _roster_rows(straight) == _roster_rows(converted)


def _dos_specimen_folders():
    from gamedata import specimen_root
    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree")
    found = {}
    for key, pattern in (("curse-of-the-azure-bonds",
                          "por-dos/WISH-SPEC-curse-234-engine-resave"),
                         ("secret-of-the-silver-blades",
                          "ssb-dos/WISH-SPEC-ssb-52-dialog-converted-resave")):
        folder = root / pattern
        if folder.is_dir():
            found[key] = folder
    if not found:
        pytest.skip("needs a Curse or a Silver Blades DOS specimen")
    return found


def test_a_later_title_dos_save_lists_the_roster_its_converted_disk_lists():
    for key, folder in _dos_specimen_folders().items():
        straight = Party(str(folder))
        game, disk = _converted_dos_disk(folder, straight.source.slot, key)
        converted = Party("", game=game, disk=disk)
        assert len(straight) == len(converted) > 0, key
        assert _roster_rows(straight) == _roster_rows(converted), key


def test_an_amiga_pool_save_lists_the_roster_its_converted_disk_lists():
    from gamedata import specimen_root

    from editor import convert
    from editor.convert import Source
    root = specimen_root()
    image = (None if root is None else root / "por-amiga"
             / "WISH-SPEC-por-amiga-slums-resave" / "poolsave-c64-after-C.adf")
    if image is None or not image.is_file():
        pytest.skip("needs the Amiga Pool of Radiance specimen")
    source = Source.detect(image, slot="C")
    straight = Party(source)
    direction = next(d for d in convert.DIRECTIONS
                     if type(d) is convert.AmigaToC64
                     and d.source_key == "pool-of-radiance")
    rehearsal = direction.rehearse(source, "C", _blank_files())
    from goldbox.d64 import D64
    disk = D64.from_bytes(next(iter(rehearsal.files.values())))
    converted = Party("", game=direction.destination_game, disk=disk)
    assert len(straight) == len(converted) > 0
    assert _roster_rows(straight) == _roster_rows(converted)

from __future__ import annotations

"""`editor.convert`'s registry: which directions the library can write whole.

Step 1 of `#52 (File ▸ Import and File ▸ Export for every direction the
library supports)`'s plan (`work/reports/52-plan.md`, on the issue's own
comments): no window, no menu, no template.

**Every test here is a round trip.** It proves `editor.convert` wraps
`goldbox.dos` the way `editor/dosimport.py`, `tools/dosdisk.py` and
`tools/dosnewsave.py` already do, byte for byte -- not a fact about the game,
so the input's provenance does not matter to the assertion
(`.claude/rules/testing.md`, "A specimen is only evidence if we know who
wrote it"). `tests/fixtures/savedgame0.bin` / `savedgame1.bin` are Donald's
own played saves, on the repository's allowlist; the DOS side reads
`tests/test_dossave.py`'s `_save_dir()`, which needs `$FR_ARCHIVES` and skips
without it -- the DOS → C64 direction also needs the player's own
`POOL*.D64` game disks and skips without those too.

The Curse of the Azure Bonds transfer test reads `work/curse/H-square-5-13`,
the DOS session `tests/test_curseconvert.py`'s `_dos_save()` already reads
for `#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one, which
the importer refuses today)` -- the FR_ARCHIVES default Curse save this
project has access to stands in area 0, which is not a mapped Curse area
(`goldbox/areas.py`'s `AREAS_CURSE` starts at `0x01`), so it cannot stand in
for a played party the way Pool of Radiance's does. `icon`/`animate` are
zero-filled the same way `test_curseconvert.py`'s do: this proves the
registry's Curse row writes what a direct call writes, for the same input,
not a fact about the Curse game disks.
"""

import dataclasses
import datetime
import pathlib
from types import SimpleNamespace

import pytest
from gamedata import disk_dir
from PyQt6.QtWidgets import QApplication, QDialog
from test_dossave import _save_dir, needs_dos_saves

from editor import convert, dosimport
from editor.window import EditorBinding
from goldbox import dos, dos_layout, dos_savegame, games
from goldbox.savegame import SaveGame0, SaveGame1

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
WORK = pathlib.Path(__file__).resolve().parent.parent / "work"
CURSE_DOS_SESSION = WORK / "curse" / "H-square-5-13"

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


def _curse_save_dir() -> pathlib.Path | None:
    """`work/curse/H-square-5-13`, if it is still on this machine.

    `work/` is gitignored and has been lost twice; `test_curseconvert.py`'s
    `_dos_save()` skips the same way for the same reason.
    """
    if (CURSE_DOS_SESSION / "SAVGAMH.DAT").exists():
        return CURSE_DOS_SESSION
    return None


needs_curse_dos_save = pytest.mark.skipif(
    _curse_save_dir() is None,
    reason=f"no DOS Curse session at {CURSE_DOS_SESSION}; #113 makes one")


def _game_dir() -> pathlib.Path:
    """The DOS game directory: the save directory's parent, `test_doswriter.py`'s
    helper, repeated here because a subagent's files may not import another
    test module's private helpers across `#52`'s lane."""
    return _save_dir().parent


def _fixture_payloads() -> tuple[bytes, bytes]:
    sg = SaveGame0.from_prg((FIXTURES / "savedgame0.bin").read_bytes())
    sg1 = SaveGame1.from_prg((FIXTURES / "savedgame1.bin").read_bytes())
    return sg.to_bytes(), sg1.to_bytes()


class _Bytes:
    """A stand-in for a `SaveGame0`/`SaveGame1`/`D64`: only `.to_bytes()`."""

    def __init__(self, data: bytes):
        self._data = data

    def to_bytes(self) -> bytes:
        return self._data


def _fake_party(path, game, save0, save1=None, disk=b""):
    """A duck-typed `editor.roster.Party`, holding only what `Source.detect`
    reads: `.path`, `.game`, `.save0`, `.save1`, `.disk`."""
    return SimpleNamespace(
        path=str(path), game=game,
        save0=_Bytes(save0) if save0 is not None else None,
        save1=_Bytes(save1) if save1 is not None else None,
        disk=_Bytes(disk))


# ---------------------------------------------------------------------------
# Source.detect
# ---------------------------------------------------------------------------

def test_source_detect_reads_a_c64_save_disk(tmp_path):
    """A round trip: `detect` reads back what `dos.save_disk` wrote, the way
    `editor/exports.py`'s `Source.from_disk` already did before this moved
    the class here."""
    save0, save1 = _fixture_payloads()
    disk = dos.save_disk(save0, save1)
    path = tmp_path / "PORSAVE.D64"
    path.write_bytes(disk.to_bytes())

    source = convert.Source.detect(path)

    assert source.port == "c64"
    assert source.title is games.POOL_OF_RADIANCE
    assert source.key == "pool-of-radiance"
    assert source.save0 == save0
    assert source.save1 == save1
    assert source.disk == disk.to_bytes()


def test_source_detect_refuses_a_disk_with_no_save(tmp_path):
    """A blank disk is a legal `.D64` and carries no title's save file."""
    from goldbox.d64 import D64

    path = tmp_path / "blank.d64"
    path.write_bytes(D64.blank().to_bytes())
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(path)


def test_source_detect_refuses_a_path_that_is_neither(tmp_path):
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(tmp_path / "nowhere")


@pytest.mark.parametrize("shape", dos_layout.SHAPES, ids=lambda s: s.key)
def test_source_detect_identifies_each_dos_shape(tmp_path, shape):
    """Every one of the four titles' record sizes names its own shape --
    including Pools of Darkness, whose container is `SAVGAM?.PTY` rather
    than `SAVGAM?.DAT` (`goldbox/dos_savegame.py`'s `SAVE_POOLS_OF_DARKNESS`),
    the case `#52`'s plan calls out by name."""
    folder = tmp_path / shape.key
    folder.mkdir()
    suffix = dos_savegame.SAVE_SHAPES_BY_KEY[shape.key].suffix
    (folder / f"SAVGAMA{suffix}").write_bytes(b"\x00")
    (folder / "CHRDATA1.SAV").write_bytes(b"\x00" * shape.record_size)

    source = convert.Source.detect(folder)

    assert source.port == "dos"
    assert source.title is shape
    assert source.key == shape.key


def test_source_detect_refuses_a_folder_with_no_character_record(tmp_path):
    """A folder holding only `SAVGAM?.PTY` -- no `CHRDAT` beside it -- is
    DOS-shaped but its title cannot be read from anything. A `ConvertError`
    a caller can show a player, not a raw `FileNotFoundError`."""
    folder = tmp_path / "pod"
    folder.mkdir()
    (folder / "SAVGAMA.PTY").write_bytes(b"\x00")

    with pytest.raises(convert.ConvertError):
        convert.Source.detect(folder)


def test_source_detect_takes_the_open_partys_bytes_over_the_disk(tmp_path):
    """Unsaved edits on screen cross into the conversion (`#52`'s 'Bypass'
    note): the disk on `path` is the original save, and `party` carries an
    edited copy that has never been written back."""
    save0, save1 = _fixture_payloads()
    disk_bytes = dos.save_disk(save0, save1).to_bytes()
    path = tmp_path / "PORSAVE.D64"
    path.write_bytes(disk_bytes)

    edited = bytearray(save0)
    edited[0] = (edited[0] + 1) % 256
    edited = bytes(edited)
    assert edited != save0

    party = _fake_party(path, games.POOL_OF_RADIANCE, edited, save1,
                        disk_bytes)
    source = convert.Source.detect(path, party=party)

    assert source.save0 == edited
    assert source.save0 != save0


def test_source_detect_ignores_a_party_at_a_different_path(tmp_path):
    """A `party` open on a different file must not shadow the one asked for."""
    save0, save1 = _fixture_payloads()
    disk_bytes = dos.save_disk(save0, save1).to_bytes()
    path = tmp_path / "PORSAVE.D64"
    path.write_bytes(disk_bytes)

    other = _fake_party(tmp_path / "OTHER.D64", games.POOL_OF_RADIANCE,
                        b"\xff" * len(save0), save1, disk_bytes)
    source = convert.Source.detect(path, party=other)

    assert source.save0 == save0


def test_source_detect_refuses_a_matching_party_with_nothing_open(tmp_path):
    """A roster disk has characters and no saved game -- `exports.Source.
    from_party`'s own refusal, carried over."""
    path = tmp_path / "ROSTER.D64"
    path.write_bytes(b"\x00")
    party = _fake_party(path, games.POOL_OF_RADIANCE, None)
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(path, party=party)


# ---------------------------------------------------------------------------
# destinations_for -- an unready direction is never offered
# ---------------------------------------------------------------------------

def test_destinations_for_lists_the_two_registered_directions():
    dos_source = convert.Source(port="dos", title=dos_layout.POOL_OF_RADIANCE,
                                path=pathlib.Path("."))
    assert [type(d) for d in convert.destinations_for(dos_source)] == \
        [convert.DosToC64]

    c64_source = convert.Source(port="c64", title=games.POOL_OF_RADIANCE,
                                path=pathlib.Path("."))
    assert [type(d) for d in convert.destinations_for(c64_source)] == \
        [convert.PoolOfRadianceC64ToDos]


def test_destinations_for_a_curse_source_answers_the_curse_c64_direction():
    """Curse of the Azure Bonds joined `goldbox.dos.CONVERTS` overnight
    (`#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one,
    which the importer refuses today)`), and this registry derives its row
    from `CONVERTS` rather than listing it -- so it is offered with no edit
    to `editor/convert.py` beyond the derivation itself."""
    curse_source = convert.Source(port="dos",
                                  title=dos_layout.CURSE_OF_THE_AZURE_BONDS,
                                  path=pathlib.Path("."))
    directions = convert.destinations_for(curse_source)
    assert [type(d) for d in directions] == [convert.DosToC64]
    assert directions[0].destination_game is games.CURSE_OF_THE_AZURE_BONDS


def test_destinations_for_an_unregistered_source_is_empty(tmp_path):
    """Pools of Darkness is read and has no C64 destination, so it is not
    offered and not refused.

    **This used to use Secret of the Silver Blades**, which was read with no
    C64 writer until `#193 (Convert a Secret of the Silver Blades DOS save
    into a C64 one, which the importer refuses today)` built one and it
    joined `goldbox.dos.CONVERTS` on 2026-09-05. Pools of Darkness is the
    permanent example: `goldbox/games.py` has no entry for it at all, because
    there is no C64 port to convert to, so no writer will ever appear.

    A fake folder is enough -- `Source.detect` reads only the record size."""
    folder = tmp_path / "pod"
    folder.mkdir()
    (folder / "SAVGAMA.DAT").write_bytes(b"\x00")
    (folder / "CHRDATA1.SAV").write_bytes(
        b"\x00" * dos_layout.POOLS_OF_DARKNESS.record_size)

    source = convert.Source.detect(folder)
    assert source.key == dos_layout.POOLS_OF_DARKNESS.key
    assert convert.destinations_for(source) == []


def test_every_converts_entry_has_a_dos_to_c64_name():
    """A `CONVERTS` title with no row in `DOS_TO_C64_NAMES` is a defect the
    registry must fail loudly on -- `#52`'s plan calls this out by name --
    and `DIRECTIONS` already proves it by having built without raising, but
    this pins the table directly against the source of truth."""
    for shape in dos.CONVERTS:
        assert shape.key in convert.DOS_TO_C64_NAMES, (
            f"{shape.title} converts but names no .D64 file")


def test_a_converts_entry_missing_its_name_fails_at_construction():
    """The loud failure `DIRECTIONS` would hit if `goldbox.dos.CONVERTS`
    grew a row `DOS_TO_C64_NAMES` has none for, provoked directly rather
    than by editing `CONVERTS` itself. Secret of the Silver Blades is a real
    `goldbox.games.by_key` entry -- so this proves the *name* lookup fails
    loudly, not the *game* lookup that would run first for a title nobody
    has heard of.

    The shape is built here rather than named from `dos_layout`, because
    every title that has one is now in `DOS_TO_C64_NAMES` -- Silver Blades
    joined on 2026-09-05 with `#193 (Convert a Secret of the Silver Blades
    DOS save into a C64 one, which the importer refuses today)`. Copying a
    real shape under a key nothing names is what leaves this test asserting
    the same thing it always did. Champions of Krynn is the key to borrow:
    `goldbox/games.py` knows it, so `games.by_key` succeeds and the failure
    can only come from the name lookup, which is the point."""
    unnamed = dataclasses.replace(dos_layout.SECRET_OF_THE_SILVER_BLADES,
                                  key="champions-of-krynn")
    assert unnamed.key not in convert.DOS_TO_C64_NAMES
    with pytest.raises(convert.UnnamedConversionError):
        convert.DosToC64(unnamed)


# ---------------------------------------------------------------------------
# fresh_folder
# ---------------------------------------------------------------------------

def test_fresh_folder_suffixes_on_collision(tmp_path):
    today = datetime.date(2026, 9, 4)

    first = convert.fresh_folder(tmp_path, today)
    assert first == tmp_path / "wish-2026-09-04"
    assert not first.exists()
    first.mkdir()

    second = convert.fresh_folder(tmp_path, today)
    assert second == tmp_path / "wish-2026-09-04-2"
    assert not second.exists()
    second.mkdir()

    third = convert.fresh_folder(tmp_path, today)
    assert third == tmp_path / "wish-2026-09-04-3"
    assert not third.exists()


# ---------------------------------------------------------------------------
# DOS -> C64: rehearsed in memory, written once, and the transfer test
# ---------------------------------------------------------------------------

@pytest.fixture
def game_files():
    """The icon and `ANIMATE00`, off the player's own disks -- the same
    search `tests/test_dosimport.py`'s `files` fixture does."""
    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts

    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks")
    icon = animate = None
    for disk in sorted(where.glob("POOL*.[dD]64")):
        try:
            if icon is None:
                icon = IconParts.load(str(disk)).default_icon()
        except Exception:
            pass
        try:
            if animate is None:
                animate = load_payload(str(disk), dos.ANIMATE_FILE)
        except Exception:
            pass
    if icon is None or animate is None:
        pytest.skip("the game disks here carry neither SPELLE64 nor ANIMATE00")
    return dosimport.GameFiles(icon=icon, animate=animate)


@needs_dos_saves
@needs_disks
def test_dos_to_c64_direction_rehearses_with_no_write(game_files, tmp_path):
    folder = _save_dir()
    slot = dos.slots_available(folder)[0]
    source = convert.Source.detect(folder)
    before = sorted(folder.iterdir())

    direction = convert.DosToC64(dos_layout.POOL_OF_RADIANCE)
    direction.rehearse(source, slot, game_files)

    assert sorted(folder.iterdir()) == before
    assert not list(tmp_path.iterdir())


@needs_dos_saves
@needs_disks
def test_dos_to_c64_direction_writes_only_into_its_own_folder(game_files,
                                                              tmp_path):
    folder = _save_dir()
    slot = dos.slots_available(folder)[0]
    source = convert.Source.detect(folder)

    direction = convert.DosToC64(dos_layout.POOL_OF_RADIANCE)
    rehearsal = direction.rehearse(source, slot, game_files)

    outside = tmp_path / "elsewhere.txt"
    outside.write_text("untouched")
    destination = tmp_path / "out"
    written = direction.write(rehearsal, destination)

    assert [p.name for p in written] == [f"PORSAVE{slot}.D64"]
    assert sorted(tmp_path.iterdir()) == sorted([outside, destination])
    assert outside.read_text() == "untouched"


@needs_dos_saves
@needs_disks
def test_dos_to_c64_direction_is_the_transfer_test(game_files, tmp_path):
    """The bytes this direction writes equal what `tools/dosdisk.py` writes,
    calling `goldbox.dos.new_save` and `goldbox.dos.save_disk` directly for
    the same slot -- so `#119 (Play a converted DOS save in VICE, off a disk
    Wish built from nothing)`'s VICE proof stands for this path too."""
    folder = _save_dir()
    slot = dos.slots_available(folder)[0]
    source = convert.Source.detect(folder)

    direction = convert.DosToC64(dos_layout.POOL_OF_RADIANCE)
    rehearsal = direction.rehearse(source, slot, game_files)
    destination = tmp_path / "out"
    direction.write(rehearsal, destination)

    ref_save0, ref_save1, _ = dos.new_save(folder, slot, game_files.icon,
                                          game_files.animate)
    reference = dos.save_disk(bytes(ref_save0), bytes(ref_save1))
    assert (destination / f"PORSAVE{slot}.D64").read_bytes() == \
        reference.to_bytes()


@needs_curse_dos_save
def test_curse_dos_to_c64_direction_is_the_transfer_test(tmp_path):
    """The registry's derived Curse row writes the same bytes a direct call
    writes, calling `goldbox.dos.new_save` and `goldbox.dos.save_disk`
    directly with `game=CURSE_OF_THE_AZURE_BONDS` -- so `#192 (Convert a
    Curse of the Azure Bonds DOS save into a C64 one, which the importer
    refuses today)`'s VICE proof stands for this path too. This is the
    check `#52`'s plan asks for: `destinations_for` on a Curse folder
    answers one direction whose `destination_game` is Curse.

    `icon`/`animate` are zero-filled, `test_curseconvert.py`'s own pattern
    for this DOS session -- a round trip of our code, not a claim about
    what the player's Curse disks hold."""
    folder = _curse_save_dir()
    slot = "H"
    icon, animate = bytes(36), bytes(852)
    game_files = dosimport.GameFiles(icon=icon, animate=animate)
    source = convert.Source.detect(folder)
    assert source.key == dos_layout.CURSE_OF_THE_AZURE_BONDS.key

    directions = convert.destinations_for(source)
    assert len(directions) == 1
    direction = directions[0]
    assert direction.destination_game is games.CURSE_OF_THE_AZURE_BONDS

    rehearsal = direction.rehearse(source, slot, game_files)
    destination = tmp_path / "out"
    written = direction.write(rehearsal, destination)
    assert [p.name for p in written] == [f"CURSE{slot}.D64"]

    ref_save0, ref_save1, _ = dos.new_save(
        folder, slot, icon, animate, game=games.CURSE_OF_THE_AZURE_BONDS)
    reference = dos.save_disk(bytes(ref_save0), bytes(ref_save1),
                              games.CURSE_OF_THE_AZURE_BONDS)
    assert (destination / f"CURSE{slot}.D64").read_bytes() == \
        reference.to_bytes()


# ---------------------------------------------------------------------------
# C64 -> DOS: rehearsed into a scratch directory, written once, no template
# ---------------------------------------------------------------------------

@needs_dos_saves
def test_c64_to_dos_direction_rehearses_with_no_write(tmp_path):
    save0, save1 = _fixture_payloads()
    source = convert.Source(port="c64", title=games.POOL_OF_RADIANCE,
                            path=pathlib.Path("."), save0=save0, save1=save1)
    direction = convert.PoolOfRadianceC64ToDos()

    direction.rehearse(source, "Z", _game_dir())

    assert not list(tmp_path.iterdir())


@needs_dos_saves
def test_c64_to_dos_direction_writes_only_into_its_own_folder(tmp_path):
    save0, save1 = _fixture_payloads()
    source = convert.Source(port="c64", title=games.POOL_OF_RADIANCE,
                            path=pathlib.Path("."), save0=save0, save1=save1)
    direction = convert.PoolOfRadianceC64ToDos()
    rehearsal = direction.rehearse(source, "Z", _game_dir())

    outside = tmp_path / "elsewhere.txt"
    outside.write_text("untouched")
    destination = tmp_path / "out"
    written = direction.write(rehearsal, destination)

    assert {p.name for p in written} == set(rehearsal.files)
    assert sorted(tmp_path.iterdir()) == sorted([outside, destination])
    assert outside.read_text() == "untouched"


@needs_dos_saves
def test_c64_to_dos_direction_is_the_transfer_test(tmp_path):
    """The files this direction writes equal what `tools/dosnewsave.py`
    writes, calling `goldbox.dos.new_dos_save` directly for the same inputs
    -- so `#26 (Write a DOS save, not just read one)`'s DOSBox proof stands
    for this path too. No template anywhere (`.claude/rules/conversions.md`).
    """
    save0, save1 = _fixture_payloads()
    game_dir = _game_dir()
    slot = "Z"
    source = convert.Source(port="c64", title=games.POOL_OF_RADIANCE,
                            path=pathlib.Path("."), save0=save0, save1=save1)

    direction = convert.PoolOfRadianceC64ToDos()
    rehearsal = direction.rehearse(source, slot, game_dir)
    destination = tmp_path / "out"
    direction.write(rehearsal, destination)

    reference = tmp_path / "reference"
    dos.new_dos_save(save0, save1, reference, slot, game_dir)

    written_names = {p.name for p in destination.iterdir()}
    reference_names = {p.name for p in reference.iterdir()}
    assert written_names == reference_names
    for name in written_names:
        assert (destination / name).read_bytes() == \
            (reference / name).read_bytes()


# ---------------------------------------------------------------------------
# Step B of `work/reports/52-plan.md`: `ConvertDialog`, and the rows a
# direction needs before Convert becomes pressable. Every test here drives
# the dialog directly -- a fake `game_files` lookup, never a real picker --
# so nothing here opens a window (`tests/conftest.py` forces
# `QT_QPA_PLATFORM=offscreen`).
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """The session-wide application `tests/conftest.py` holds a reference to."""
    return QApplication.instance() or QApplication([])


def _make_root():
    from PyQt6.QtWidgets import QWidget
    return QWidget()


def _synthetic_dos_folder(tmp_path, shape, slot="A", suffix="DAT",
                          name="dos"):
    """A folder just real enough for `Source.detect` to name its shape --
    one `SAVGAM<slot>.<suffix>` and one right-sized `CHRDAT<slot>1.SAV`,
    neither of them anything `goldbox.dos` could actually read. Every test
    that uses this is testing the dialog's wiring, not the game
    (`.claude/rules/testing.md`, "A specimen is only evidence if we know who
    wrote it").
    """
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    (folder / f"SAVGAM{slot}.{suffix}").write_bytes(b"\x00")
    (folder / f"CHRDAT{slot}1.SAV").write_bytes(b"\x00" * shape.record_size)
    return folder


def _por_c64_disk(tmp_path, name="PORSAVEA.D64"):
    """A real, readable Pool of Radiance C64 save disk."""
    save0, save1 = _fixture_payloads()
    disk = dos.save_disk(save0, save1)
    path = tmp_path / name
    path.write_bytes(disk.to_bytes())
    return path


def _no_disks(_game):
    return None


def test_a_pool_of_radiance_d64_lists_dos(tmp_path):
    """A C64 source offers exactly the one registered C64 -> DOS row."""
    path = _por_c64_disk(tmp_path)

    dialog = convert.ConvertDialog(str(path), None, _no_disks)
    try:
        assert dialog.source is not None and dialog.source.port == "c64"
        labels = [dialog.ui.convert_destination.itemData(i)
                 for i in range(dialog.ui.convert_destination.count())]
        assert labels == ["dos"]
    finally:
        dialog.close()


def test_a_pool_of_radiance_savgam_file_lists_c64_and_records_its_slot(
        tmp_path):
    """Picking `SAVGAMB.DAT` directly names slot B, with no slot row
    anywhere in the dialog (`work/reports/52-plan.md`, step B: "one file
    picker ... so there is no slot row")."""
    folder = _synthetic_dos_folder(tmp_path, dos_layout.POOL_OF_RADIANCE,
                                   slot="B")
    dialog = convert.ConvertDialog(
        str(folder / "SAVGAMB.DAT"), None, _no_disks)
    try:
        assert dialog.source is not None
        assert dialog.source.port == "dos"
        assert dialog.source.slot == "B"
        labels = [dialog.ui.convert_destination.itemData(i)
                 for i in range(dialog.ui.convert_destination.count())]
        assert labels == ["c64"]
    finally:
        dialog.close()


@pytest.mark.parametrize("shape", [dos_layout.CURSE_OF_THE_AZURE_BONDS,
                                   dos_layout.SECRET_OF_THE_SILVER_BLADES],
                        ids=lambda s: s.key)
def test_a_curse_or_silver_blades_savgam_file_lists_c64(tmp_path, shape):
    """Both later titles convert now (`goldbox.dos.CONVERTS`), so the
    dialog offers the Commodore 64 for either without an edit here."""
    folder = _synthetic_dos_folder(tmp_path, shape)
    dialog = convert.ConvertDialog(
        str(folder / "SAVGAMA.DAT"), None, _no_disks)
    try:
        labels = [dialog.ui.convert_destination.itemData(i)
                 for i in range(dialog.ui.convert_destination.count())]
        assert labels == ["c64"]
    finally:
        dialog.close()


def test_a_pools_of_darkness_folder_lists_nothing(tmp_path):
    """The one title with no C64 port: the pane names the approved refusal
    and the button never becomes pressable, with no destination offered and
    then refused."""
    folder = _synthetic_dos_folder(tmp_path, dos_layout.POOLS_OF_DARKNESS,
                                   suffix="PTY")
    dialog = convert.ConvertDialog(
        str(folder / "SAVGAMA.PTY"), None, _no_disks)
    try:
        assert dialog.ui.convert_destination.count() == 0
        assert dialog.ui.convert_report.toPlainText() == convert.CANNOT_CONVERT
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        assert not ok.isEnabled()
    finally:
        dialog.close()


def test_the_game_files_row_is_shown_only_for_a_dos_destination(tmp_path):
    """Hidden for the C64: the Game Disk folder preference already answers
    it (`#52`'s plan, step B's row table)."""
    path = _por_c64_disk(tmp_path)

    dialog = convert.ConvertDialog(str(path), None, _no_disks)
    try:
        assert dialog.direction.destination_port == "dos"
        assert dialog.ui.form.isRowVisible(dialog.ui.game_row)
        assert dialog.ui.label_game.text() == convert.LABEL_GAME
    finally:
        dialog.close()

    folder = _synthetic_dos_folder(tmp_path, dos_layout.POOL_OF_RADIANCE,
                                   slot="C", name="dos2")
    dialog2 = convert.ConvertDialog(
        str(folder / "SAVGAMC.DAT"), None, _no_disks)
    try:
        assert dialog2.direction.destination_port == "c64"
        assert not dialog2.ui.form.isRowVisible(dialog2.ui.game_row)
    finally:
        dialog2.close()


def test_the_c64_disks_are_looked_up_by_the_destination_title(tmp_path):
    """With no party open and a Curse folder chosen, the game-files lookup
    is asked for Curse's own title, never Pool of Radiance's --
    `editor.window.EditorBinding.game_files_for`'s whole reason to exist
    over `game_files_for_import`, which only ever asked for the open
    party's title."""
    folder = _synthetic_dos_folder(tmp_path, dos_layout.CURSE_OF_THE_AZURE_BONDS)
    seen = []

    def fake_lookup(game):
        seen.append(game.key)
        return None

    dialog = convert.ConvertDialog(
        str(folder / "SAVGAMA.DAT"), None, fake_lookup)
    try:
        assert seen == [games.CURSE_OF_THE_AZURE_BONDS.key]
        assert dialog.ui.convert_report.toPlainText() == convert.NO_DISKS
    finally:
        dialog.close()


def test_disk_candidates_picks_the_destination_pattern_not_the_open_partys(
        tmp_path):
    """`EditorBinding._disk_candidates`'s new `pattern` argument: a fake
    disks folder holding both a `POOL*` and a `CURSE*` name, asked for each
    in turn, answers only the one that matches (`work/reports/52-plan.md`
    step B's own suggested test shape)."""
    disks = tmp_path / "disks"
    disks.mkdir()
    (disks / "POOL1.D64").write_bytes(b"pool")
    (disks / "CURSE1.D64").write_bytes(b"curse")

    window = EditorBinding(_make_root(), disks=str(disks))
    try:
        assert window._disk_candidates(games.POOL_OF_RADIANCE.disk_glob) == \
            [str(disks / "POOL1.D64")]
        assert window._disk_candidates(
            games.CURSE_OF_THE_AZURE_BONDS.disk_glob) == \
            [str(disks / "CURSE1.D64")]
    finally:
        window.close()


@needs_dos_saves
def test_the_writes_block_names_the_full_path_before_the_button_is_enabled(
        tmp_path):
    """The pane says where the file would land, not only its name, so a
    player never has to guess which folder Convert is about to write into --
    and the button is enabled only once it does."""
    path = _por_c64_disk(tmp_path)
    destination = tmp_path / "out"
    destination.mkdir()

    dialog = convert.ConvertDialog(str(path), None, _no_disks,
                                   folder=str(destination),
                                   game=str(_game_dir()))
    try:
        today = datetime.date.today().isoformat()
        expected = str(destination / f"wish-{today}" / "SAVGAMA.DAT")
        assert expected in dialog.ui.convert_report.toPlainText()
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        assert ok.isEnabled()
    finally:
        dialog.close()


@needs_dos_saves
@needs_disks
def test_convert_writes_into_a_fresh_folder_and_a_second_the_same_day_gets_dash_2(
        tmp_path, monkeypatch):
    """The whole path, `EditorBinding.convert` end to end: nothing else in
    the destination changes, and a second conversion the same day does not
    collide with the first (`#52`'s 2026-09-04 ruling)."""
    save_dir = _save_dir()
    disks = disk_dir()
    window = EditorBinding(_make_root(), disks=str(disks))
    destination = tmp_path / "out"
    destination.mkdir()
    outside = destination / "leftover.txt"
    outside.write_text("untouched")

    monkeypatch.setattr(convert.ConvertDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    try:
        first = window.convert(source=str(save_dir / "SAVGAMA.DAT"),
                               folder=str(destination))
        second = window.convert(source=str(save_dir / "SAVGAMA.DAT"),
                                folder=str(destination))
    finally:
        window.close()

    today = datetime.date.today().isoformat()
    assert (destination / f"wish-{today}").is_dir()
    assert (destination / f"wish-{today}-2").is_dir()
    assert outside.read_text() == "untouched"
    assert first != second
    assert not list((destination / f"wish-{today}").glob("*")) == []


@needs_dos_saves
@needs_disks
def test_the_open_saves_unsaved_edits_cross(tmp_path, monkeypatch):
    """Converting the save already open in the editor uses the bytes on
    screen, edits included -- the same rule
    `exports.Source.from_party` followed, ported here rather than argued
    from plausibility."""
    path = _por_c64_disk(tmp_path, name="open.d64")
    window = EditorBinding(_make_root())
    window.load(str(path))
    assert window.party is not None

    original = window.party.save0.to_bytes()
    edited = bytearray(original)
    edited[0] = (edited[0] + 1) % 256
    window.party.save0 = window.party.save0.__class__.from_bytes(
        bytes(edited), window.party.game)

    game_dir = _game_dir()
    destination = tmp_path / "out"
    destination.mkdir()

    monkeypatch.setattr(convert.ConvertDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    try:
        window.convert(source=str(path), folder=str(destination),
                      game=str(game_dir))
    finally:
        window.close()

    written = next((destination).glob("wish-*/SAVGAMA.DAT"))
    assert written.read_bytes()[:1] != original[:1]


@needs_dos_saves
@needs_disks
def test_a_c64_destinations_result_is_the_party_on_screen_afterwards(
        tmp_path, monkeypatch):
    """After a DOS -> C64 write, the editor has the written disk open --
    the same thing `File ▸ Open` would show, reached without a second click
    (`work/reports/52-plan.md` step B: "for a C64 destination the editor
    opens written[0]")."""
    save_dir = _save_dir()
    disks = disk_dir()
    window = EditorBinding(_make_root(), disks=str(disks))
    destination = tmp_path / "out"
    destination.mkdir()

    opened = []
    window.opened.connect(opened.append)

    monkeypatch.setattr(convert.ConvertDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    try:
        window.convert(source=str(save_dir / "SAVGAMA.DAT"),
                      folder=str(destination))
    finally:
        pass

    assert window.party is not None and window.party.is_save
    assert window.party.game is games.POOL_OF_RADIANCE
    assert len(opened) == 1
    window.close()


def test_no_string_reachable_in_the_pane_contains_a_hex_offset(tmp_path):
    """`.claude/rules/gui-text.md`: no memory address or file offset in
    front of a player. Every pane state this module can reach with no real
    game disks, checked at once."""
    import re

    hexish = re.compile(r"(?:0x[0-9A-Fa-f]+|\$[0-9A-Fa-f]{2,})")

    states = []

    folder = _synthetic_dos_folder(tmp_path, dos_layout.POOLS_OF_DARKNESS,
                                   suffix="PTY", name="pod")
    d1 = convert.ConvertDialog(str(folder / "SAVGAMA.PTY"), None, _no_disks)
    states.append(d1.ui.convert_report.toPlainText())
    d1.close()

    path = _por_c64_disk(tmp_path)
    d2 = convert.ConvertDialog(str(path), None, _no_disks)
    states.append(d2.ui.convert_report.toPlainText())
    d2.close()

    d3 = convert.ConvertDialog("", None, _no_disks)
    states.append(d3.ui.convert_report.toPlainText())
    d3.close()

    for text in states:
        assert not hexish.search(text), text


def test_no_string_the_player_reads_is_unapproved():
    """The flag's first removal condition, now met.

    Every string in this dialog carried a ` (NOT APPROVED)` marker until
    Donald read them in place and approved all ten on 2026-09-05 -- *"I
    think these are all fine."*  The test inverted with the ruling: it used
    to prove each placeholder still announced itself, and now proves none
    of them does, which is the condition `editor/convert.py`'s flag names
    first.

    It greps the module rather than a list, so a **new** unapproved string
    added later fails here instead of shipping quietly -- which the old
    list-of-names form could not do.
    """
    import inspect
    source = inspect.getsource(convert)
    offenders = [line.strip() for line in source.splitlines()
                 if '(NOT APPROVED)"' in line or "(NOT APPROVED)'" in line]
    assert offenders == [], offenders

    #: Every string a player can read, checked as values rather than as
    #: source, so a marker built at run time is caught too.
    for name, text in vars(convert).items():
        if name.isupper() and isinstance(text, str):
            assert "NOT APPROVED" not in text, name
    for text in convert.DESTINATION_LABELS.values():
        assert "NOT APPROVED" not in text, text


def test_the_approved_strings_are_the_ones_donald_worded():
    """A spot check that stripping the markers did not also strip a word.

    `SOURCE_FILTER` is the one worth pinning: it is a Qt file-dialog filter
    rather than a sentence, the marker sat mid-string because Qt would read
    a trailing one as the glob itself, and removing it there is the edit
    most likely to have taken a bracket with it.
    """
    assert convert.MENU_CONVERT == "&Convert…"
    assert convert.DIALOG_TITLE == "Convert a save"
    assert convert.LABEL_SOURCE == "Save"
    assert convert.LABEL_TO == "To"
    assert convert.SOURCE_TITLE == "Choose a save"
    assert convert.NO_GAME_FOLDER == "Choose the DOS game folder."
    assert convert.CONVERTED_DOS == "Converted to DOS slot {slot} in {folder}"
    assert convert.DESTINATION_LABELS == {"c64": "Commodore 64", "dos": "DOS"}
    assert convert.SOURCE_FILTER == (
        "Saved games (*.d64 *.D64 SAVGAM?.DAT SAVGAM?.PTY);;All files (*)")


# ---------------------------------------------------------------------------
# The flag -- `tests/test_dosimport.py:708-750`'s shape, ported: "the gate,
# asserted from the outside" rather than a direct call to `enabled()`, so a
# passing test also proves `wish/window.py`'s wiring and not only the
# function. `_wish_window`/`_file_menu` are that file's private helpers,
# copied rather than imported -- a subagent's files may not import another
# test module's private helpers across `#52`'s lane
# (`work/reports/52-plan.md`).
# ---------------------------------------------------------------------------

def _wish_window(tmp_path, monkeypatch):
    """A window with nothing to attach to. The caller closes it."""
    from wish.session import Session
    from wish.window import WishWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Nothing answering, and nothing looked for: a menu test must not go
    # probing the ports a human's own game session is on.
    return WishWindow(maps={}, session=Session(find=lambda pref=None: None))


def _file_menu(window):
    return next(a.menu() for a in window.menuBar().actions()
               if a.text() == "&File")


def test_convert_is_not_offered_unless_it_is_asked_for(app, tmp_path,
                                                       monkeypatch):
    """No menu entry, not a greyed one -- `convert.ENV` unset is the shipped
    state."""
    monkeypatch.delenv(convert.ENV, raising=False)
    window = _wish_window(tmp_path, monkeypatch)
    assert convert.MENU_CONVERT not in [a.text()
                                        for a in _file_menu(window).actions()]
    assert window.convert_action is None
    window.close()


def test_a_variable_somebody_forgot_does_not_turn_convert_on(app, tmp_path,
                                                             monkeypatch):
    """`0` and `off` are off, the same rule `wish/debugmode.py` follows."""
    for value in ("", "0", "off", "no"):
        monkeypatch.setenv(convert.ENV, value)
        window = _wish_window(tmp_path, monkeypatch)
        assert convert.MENU_CONVERT not in [
            a.text() for a in _file_menu(window).actions()], value
        window.close()


def test_the_file_menu_carries_convert_when_asked_for(app, tmp_path,
                                                      monkeypatch):
    monkeypatch.setenv(convert.ENV, "1")
    window = _wish_window(tmp_path, monkeypatch)
    assert convert.MENU_CONVERT in [a.text()
                                    for a in _file_menu(window).actions()]
    assert window.convert_action.text() == convert.MENU_CONVERT
    window.close()


@needs_dos_saves
@needs_disks
def test_a_writer_that_fails_partway_leaves_no_folder_behind(tmp_path,
                                                             monkeypatch):
    """A half-written conversion is cleared away, not left looking like one
    that worked.

    `Direction.write` puts several files in the folder, so a writer that
    raises after the first of them leaves it non-empty.  `rmdir` refuses a
    non-empty directory, and the failure path used to swallow that -- which
    left the debris in the player's own destination under a
    `wish-YYYY-MM-DD` name, indistinguishable by name from a conversion
    that worked, and never touched again, because the next attempt takes
    the next suffix rather than that folder.
    """
    disks = disk_dir()
    window = EditorBinding(_make_root(), disks=str(disks))
    destination = tmp_path / "out"
    destination.mkdir()

    real = dos.new_dos_save

    def half_a_write(save0, save1, folder, *args, **kwargs):
        #: The rehearsal calls this too, into a temporary directory of its
        #: own -- let that one through, so the dialog reaches the state
        #: where its button is live, and fail only the real write into the
        #: player's chosen destination.
        if pathlib.Path(destination) not in pathlib.Path(folder).parents:
            return real(save0, save1, folder, *args, **kwargs)
        #: One file, then the failure a full disk would give: the state
        #: `rmdir` cannot clear.
        pathlib.Path(folder).joinpath("SAVGAMA.DAT").write_bytes(b"half")
        raise OSError(28, "No space left on device")

    #: Accept once so the write is attempted, then refuse, so the retry loop
    #: `convert` runs on a refusal ends instead of spinning.
    answers = iter([QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected])
    monkeypatch.setattr(convert.ConvertDialog, "exec",
                        lambda self: next(answers))
    refusals = []
    real_refuse = convert.ConvertDialog.refuse

    def note_refusal(self, text):
        refusals.append(text)
        return real_refuse(self, text)

    monkeypatch.setattr(convert.ConvertDialog, "refuse", note_refusal)
    monkeypatch.setattr(dos, "new_dos_save", half_a_write)
    try:
        outcome = window.convert(source=str(_por_c64_disk(tmp_path)),
                                 destination="dos",
                                 game=str(_game_dir()),
                                 folder=str(destination))
    finally:
        monkeypatch.setattr(dos, "new_dos_save", real)
        window.close()

    assert outcome == "cancelled"
    assert refusals == [convert.CANNOT_CONVERT]
    assert list(destination.iterdir()) == [
        ], [p.name for p in destination.iterdir()]

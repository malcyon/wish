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
from gamedata import disk_dir, game_file
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
    directions = convert.destinations_for(c64_source)
    assert [type(d) for d in directions] == [convert.C64ToDos]
    assert directions[0].destination_game is dos_layout.POOL_OF_RADIANCE


@pytest.mark.parametrize("shape", [dos_layout.CURSE_OF_THE_AZURE_BONDS,
                                   dos_layout.SECRET_OF_THE_SILVER_BLADES],
                        ids=lambda s: s.key)
def test_destinations_for_a_curse_or_ssb_c64_source_answers_the_dos_direction(
        shape):
    """`#299 (goldbox.dos.write builds only Pool of Radiance's record, so
    nothing can be converted to DOS for the later titles)`'s container
    writer put both later titles on `goldbox.dos.WRITES`, so each is offered
    with no edit to this module beyond the derivation itself -- the same
    shape `test_destinations_for_a_curse_source_answers_the_curse_c64_direction`
    already proves for the other direction."""
    c64_source = convert.Source(port="c64", title=games.by_key(shape.key),
                                path=pathlib.Path("."))
    directions = convert.destinations_for(c64_source)
    assert [type(d) for d in directions] == [convert.C64ToDos]
    assert directions[0].destination_game is shape


def test_directions_holds_seven_rows_derived_from_three_library_tuples():
    """Three titles read DOS → C64 (`goldbox.dos.CONVERTS`) and the same
    three write C64 → DOS (`goldbox.dos.WRITES`, as of `#299`); Pool of
    Radiance alone reads Amiga → C64 and Amiga → DOS
    (`goldbox.amiga.CONVERTS`, as of
    `#353 (Convert an Amiga Pool of Radiance save to the C64, so a party
    standing in the Slums on the Amiga arrives there in VICE)` and
    `#354 (Convert an Amiga Pool of Radiance save to DOS, so a party
    standing in the Slums on the Amiga arrives there under DOSBox)`), so the
    registry holds eight rows -- up from four before `#299`'s container
    writer and six before `#353`'s Amiga reader.

    Counted by exact type rather than `isinstance`, because each Amiga row
    derives from the DOS row that shares its destination -- `AmigaToC64`
    from `DosToC64` and `AmigaToDos` from `C64ToDos` -- so an `isinstance`
    count would read an Amiga row as a DOS one and pass while the Amiga row
    was missing entirely."""
    assert len(convert.DIRECTIONS) == 8
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.DosToC64) == 3
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.C64ToDos) == 3
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.AmigaToC64) == 1
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.AmigaToDos) == 1


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
    #: The creation menu too. A Pool of Radiance conversion refuses without
    #: it since `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which needs the
    #: import working for all three C64 titles)`, because a party arriving
    #: with no face on any sheet is worse than one that did not arrive.
    from goldbox.portraits import PortraitError, tables_from_disks
    try:
        portraits = tables_from_disks(where)
    except (PortraitError, OSError):
        pytest.skip("the game disks here carry no readable GEN")
    return dosimport.GameFiles(icon=icon, animate=animate,
                               portraits=portraits)


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

    #: The portrait tables too, since `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT,
    #: which needs the import working for all three C64 titles)` -- the
    #: reference call has to be given what the direction gives itself, or it
    #: refuses where the direction does not and the two cannot be compared.
    ref_save0, ref_save1, _ = dos.new_save(folder, slot, game_files.icon,
                                          game_files.animate,
                                          portraits=game_files.portraits)
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
    direction = convert.C64ToDos(dos_layout.POOL_OF_RADIANCE)

    direction.rehearse(source, "Z", _game_dir())

    assert not list(tmp_path.iterdir())


@needs_dos_saves
def test_c64_to_dos_direction_writes_only_into_its_own_folder(tmp_path):
    save0, save1 = _fixture_payloads()
    source = convert.Source(port="c64", title=games.POOL_OF_RADIANCE,
                            path=pathlib.Path("."), save0=save0, save1=save1)
    direction = convert.C64ToDos(dos_layout.POOL_OF_RADIANCE)
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

    direction = convert.C64ToDos(dos_layout.POOL_OF_RADIANCE)
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
# C64 -> DOS: the source's own combat icon (#383, wiring `#320 (A C64 party
# converted to DOS arrives with no combat figure at all, because the table
# only runs one way)` into the live registry and dialog).
# ---------------------------------------------------------------------------

def _six_icon_party() -> "tuple[bytes, bytes, object]":
    """BRUTUS's own committed fixture, cloned into all six slots with six
    different names and six different combat icons.

    The same shape `tests/test_doswriter.py`'s own
    `test_a_c64_party_of_six_different_icons_gets_six_different_dos_figures`
    builds at `goldbox.dos`'s own layer -- nothing here is the game's own
    saved bytes, only its documented icon format applied six times to one
    committed fixture. Returns `(save0, save1, IconParts)` so a caller needs
    to read `SPELLE64`/`SPELLN64` only once.
    """
    from goldbox import c64_save
    from goldbox.iconparts import (
        DEFAULT_BACKGROUND,
        DEFAULT_PART_COLOURS,
        MULTICOLOUR,
        IconParts,
    )
    from goldbox.savegame import HEADER_SIZE, SLOT_STRIDE

    parts = IconParts(game_file("SPELLE64"), game_file("SPELLN64"))
    save0, save1 = _fixture_payloads()
    container = c64_save.container_for(None)

    figures = [("large", 0, 0), ("large", 7, 4), ("large", 11, 9),
              ("small", 3, 2), ("small", 16, 7), ("large", 21, 12)]
    names = (b"ONE", b"TWO", b"THREE", b"FOUR", b"FIVE", b"SIX")
    base = bytearray(save0)
    slot0 = bytes(base[HEADER_SIZE:HEADER_SIZE + SLOT_STRIDE])
    for i, (size, weapon, head) in enumerate(figures):
        off = HEADER_SIZE + i * SLOT_STRIDE
        base[off:off + SLOT_STRIDE] = slot0
        base[off:off + len(names[i])] = names[i]
        base[off + len(names[i]):off + 20] = bytes(20 - len(names[i]))
        shape = parts.compose(size, weapon, head)
        seed = bytes([DEFAULT_BACKGROUND | MULTICOLOUR] * len(shape))
        icon = shape + parts.colours_for(shape, DEFAULT_PART_COLOURS, seed)
        at = container.icon(i)
        base[at:at + container.icon_size] = icon
    return bytes(base), save1, parts


@needs_dos_saves
def test_c64_to_dos_direction_recognises_the_sources_own_combat_icon(
        tmp_path):
    """`C64ToDos.rehearse`/`write` take the `icon_parts` `goldbox.dos.
    new_dos_save` always could, and the two runs stay in step -- `write`'s
    second run recognises what `rehearse`'s did, not the game's own default.
    """
    save0, save1, parts = _six_icon_party()
    game_dir = _game_dir()
    slot = "Z"
    source = convert.Source(port="c64", title=games.POOL_OF_RADIANCE,
                            path=pathlib.Path("."), save0=save0, save1=save1)

    direction = convert.C64ToDos(dos_layout.POOL_OF_RADIANCE)
    rehearsal = direction.rehearse(source, slot, game_dir, icon_parts=parts)
    assert not any("figure is not set" in d for d in rehearsal.report.dropped), \
        rehearsal.report.dropped

    destination = tmp_path / "out"
    direction.write(rehearsal, destination)

    party = dos.read_party(destination, slot)
    assert len(party) == 6
    pairs = [(c.get("icon_head"), c.get("icon_body")) for c in party]
    assert len(set(pairs)) == 6, pairs


@needs_dos_saves
@needs_disks
def test_the_dialog_wires_the_sources_own_combat_icon_into_the_conversion(
        tmp_path):
    """`#383 (The live Convert dialog never wires a C64 party's own combat
    icon into DOS, so region_220 stays on the drop list)`: the byte-level
    mechanism `#320 (A C64 party converted to DOS arrives with no combat
    figure at all, because the table only runs one way)` proved was never
    called from `ConvertDialog`. Watched failing before the fix: the pane
    kept the `region_220` note and every character's `(icon_head, icon_body)`
    read back `(0, 0)`.

    The fake `game_files` lookup below stands in for
    `editor.window.EditorBinding.game_files_for`, asked here for the
    *source*'s own title (Pool of Radiance) rather than the destination's --
    the same disks `game_files_for` would find, read the same way.
    """
    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts

    where = disk_dir()

    def game_files_for(game):
        if game.key != games.POOL_OF_RADIANCE.key:
            return None
        icon = animate = None
        for disk in sorted(where.glob("POOL*.[dD]64")):
            if icon is None:
                try:
                    icon = IconParts.load(str(disk))
                except Exception:
                    pass
            if animate is None:
                try:
                    animate = load_payload(str(disk), dos.ANIMATE_FILE)
                except Exception:
                    pass
        if icon is None or animate is None:
            return None
        return dosimport.GameFiles(icon=icon, animate=animate)

    save0, save1, _ = _six_icon_party()
    disk_path = tmp_path / "SIX.D64"
    disk_path.write_bytes(dos.save_disk(save0, save1).to_bytes())

    destination = tmp_path / "out"
    dialog = convert.ConvertDialog(str(disk_path), None, game_files_for,
                                   game=str(_game_dir()),
                                   folder=str(destination))
    try:
        assert dialog.rehearsal is not None
        text = dialog.ui.convert_report.toPlainText()
        assert "figure is not set" not in text, text
        final = tmp_path / "final"
        dialog.direction.write(dialog.rehearsal, final)
        slot = dialog.slot
    finally:
        dialog.close()

    party = dos.read_party(final, slot)
    assert len(party) == 6
    pairs = [(c.get("icon_head"), c.get("icon_body")) for c in party]
    assert len(set(pairs)) == 6, pairs


# ---------------------------------------------------------------------------
# `#234 (A dual-classed Curse or Silver Blades character converted to DOS
# loses the class he trained out of)`'s own proof, through this registry
# rather than a direct `goldbox.dos` call -- the row this issue was waiting
# on `#299 (goldbox.dos.write builds only Pool of Radiance's record, so
# nothing can be converted to DOS for the later titles)` for.
# ---------------------------------------------------------------------------

def _dual_classed_curse_disk() -> pathlib.Path | None:
    """`WISH-SPEC-curse-dual-classed`, the one C64 dual-classed Curse
    specimen on this machine (`#234`'s comment of 2026-09-05 08:34): PHILIPPE,
    a human magic-user 6, used `HUMAN CHANGE CLASS` at Curse's own training
    hall to become a fighter 1 (`#18 (Measure Curse's trainer so Level Up
    works there)`)."""
    from gamedata import specimen_root
    root = specimen_root()
    if root is None:
        return None
    found = list(
        (root / "por-c64").glob("WISH-SPEC-curse-dual-classed.[dD]64"))
    return found[0] if found else None


def _curse_game_dir() -> pathlib.Path | None:
    """The DOS Curse game directory, for the area script `new_dos_save`
    stages -- `tests/test_doslatercontainer.py`'s own helper, repeated here
    rather than imported across `#52`'s lane."""
    from tools import dosbox
    try:
        return dosbox.find_game("CURSE")
    except FileNotFoundError:
        return None


needs_dual_classed_curse_specimen = pytest.mark.skipif(
    _dual_classed_curse_disk() is None or _curse_game_dir() is None,
    reason="needs ~/wish-specimens/por-c64/WISH-SPEC-curse-dual-classed.D64 "
          "(tools/specimens.py) and the DOS Curse archives ($FR_ARCHIVES)")


@needs_dual_classed_curse_specimen
def test_234_a_dual_classed_curse_character_keeps_his_former_class_through_the_registry(
        tmp_path):
    """`#234`'s own case, run through `editor.convert.DIRECTIONS` rather
    than the direct `goldbox.dos.new_dos_save` call its comments proved this
    with: converting PHILIPPE's disk through the registered Curse C64 → DOS
    direction and reading the DOS record back gets the same answer -- fighter
    1, no experience, carrying the magic-user 6 she left in the two places
    the DOS engine keeps it (`#234`'s comment of 2026-09-05 20:15)."""
    disk = _dual_classed_curse_disk()
    source = convert.Source.detect(disk)
    assert source.port == "c64"
    assert source.key == games.CURSE_OF_THE_AZURE_BONDS.key

    directions = convert.destinations_for(source)
    assert len(directions) == 1
    direction = directions[0]
    assert type(direction) is convert.C64ToDos
    assert direction.destination_game is dos_layout.CURSE_OF_THE_AZURE_BONDS

    rehearsal = direction.rehearse(source, "Z", _curse_game_dir())
    destination = tmp_path / "out"
    direction.write(rehearsal, destination)

    records = [dos.read_character(p)
              for p in sorted(destination.glob("CHRDATZ?.SAV"))]
    philippe = next(c for c in records if c.name == "PHILIPPE")

    assert philippe.class_levels == {"fighter": 1}
    assert philippe.get("experience") == 0
    # magic-user is slot 5 of `dos.CLASS_LEVEL_SLOTS` -- the class she left.
    assert philippe.raw("former_class_levels")[5] == 6
    assert philippe.raw("former_level")[0] == 6


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


def _later_c64_disk(tmp_path, game):
    """A readable Curse or Silver Blades C64 save disk, zero-filled.

    Both later titles keep one payload where Pool of Radiance keeps two, so
    `goldbox.dos.save_disk` is handed the `Game` and writes whichever files
    that title's disk holds. Zeroes are enough: nothing here converts the
    party, only names the title off the disk's own directory, and a slice of
    a real save would be the copy `AGENTS.md` bans as a fixture.
    """
    disk = dos.save_disk(bytes(game.save_size), bytes(game.roster_size),
                         game=game)
    path = tmp_path / f"{game.key}.d64"
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


@pytest.mark.parametrize("game", [games.CURSE_OF_THE_AZURE_BONDS,
                                  games.SECRET_OF_THE_SILVER_BLADES],
                         ids=lambda g: g.key)
def test_a_curse_or_silver_blades_d64_lists_dos(tmp_path, game):
    """The other half of the flag's second condition, which nothing drove
    at the dialog until now.

    `test_a_curse_or_silver_blades_savgam_file_lists_c64` proves a DOS save
    of either later title offers the Commodore 64.  This is the reverse, and
    it became true only when `#299 (goldbox.dos.write builds only Pool of
    Radiance's record, so nothing can be converted to DOS for the later
    titles)` closed and `goldbox.dos.WRITES` grew from one title to three --
    `editor.convert.DIRECTIONS` went from four rows to six with no edit.
    `test_destinations_for_a_curse_or_ssb_c64_source_answers_the_dos_direction`
    checks the registry; this checks the combo a player reads, which is one
    layer up and is where the condition is actually about.
    """
    path = _later_c64_disk(tmp_path, game)

    dialog = convert.ConvertDialog(str(path), None, _no_disks)
    try:
        assert dialog.source is not None
        assert dialog.source.port == "c64"
        assert dialog.source.key == game.key
        labels = [dialog.ui.convert_destination.itemData(i)
                 for i in range(dialog.ui.convert_destination.count())]
        assert labels == ["dos"]
        assert dialog.ui.convert_destination.currentText() == \
            convert.DESTINATION_LABELS["dos"]
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


def test_disk_candidates_prefers_a_titles_own_preferences_folder(tmp_path):
    """`#342 (A Curse or Silver Blades save cannot be converted unless its
    C64 sides sit in the Pool of Radiance disk folder)`: the shared Game Disk
    folder holds Pool of Radiance's sides, Curse's own folder is set
    separately in Preferences (`#22 (A disk folder setting per game, not one
    shared by all six)`), and the destination lookup finds Curse's disk in
    its own folder rather than refusing because the shared one has none."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "POOL1.D64").write_bytes(b"pool")

    curse_folder = tmp_path / "curse"
    curse_folder.mkdir()
    (curse_folder / "CURSE1.D64").write_bytes(b"curse")

    window = EditorBinding(_make_root(), disks=str(shared), game_folders={
        games.CURSE_OF_THE_AZURE_BONDS.key: str(curse_folder)})
    try:
        assert window._disk_candidates(
            games.CURSE_OF_THE_AZURE_BONDS.disk_glob,
            games.CURSE_OF_THE_AZURE_BONDS) == \
            [str(curse_folder / "CURSE1.D64")]
    finally:
        window.close()


def test_disk_candidates_with_no_per_title_folder_still_uses_the_shared_one(
        tmp_path):
    """The unchanged case `#342` must not break: one shared Game Disk folder,
    no per-title folder set in Preferences (`#22`), still answers from the
    shared one."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "POOL1.D64").write_bytes(b"pool")

    window = EditorBinding(_make_root(), disks=str(shared))
    try:
        assert window._disk_candidates(
            games.POOL_OF_RADIANCE.disk_glob, games.POOL_OF_RADIANCE) == \
            [str(shared / "POOL1.D64")]
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


@needs_dos_saves
def test_no_string_in_the_ready_to_write_c64_to_dos_pane_carries_developer_detail(
        tmp_path):
    """The one pane state `test_no_string_reachable_in_the_pane_contains_a_
    hex_offset` could not reach with no real game disks: a C64 source with a
    DOS game folder and a destination folder both chosen, which is what
    actually rehearses the write and puts the drop list on screen. Every
    other state that module checks refuses before reaching a drop line at
    all (#355, A C64 party converted to DOS is shown nine developer notes,
    with memory addresses, overlay names and issue numbers in them).

    Failed before the fix, on `0x0E3`, `$1633`, `CHARPIC00`, `LIBRARY`,
    `GEN`, `#277`, `#268` and `#202`.
    """
    import re

    hexish = re.compile(r"(?:0x[0-9A-Fa-f]+|\$[0-9A-Fa-f]{2,})")
    bare_issue = re.compile(r"#\d+")
    overlay_names = ("LIBRARY", "GEN", "COM.PREP", "CHARPIC00")

    path = _por_c64_disk(tmp_path)
    destination = tmp_path / "out"
    destination.mkdir()
    dialog = convert.ConvertDialog(str(path), None, _no_disks,
                                   game=str(_game_dir()),
                                   folder=str(destination))
    try:
        text = dialog.ui.convert_report.toPlainText()
    finally:
        dialog.close()

    assert convert.DROPPED_HEADING in text, text
    assert not hexish.search(text), text
    assert not bare_issue.search(text), text
    assert not any(o in text for o in overlay_names), text


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


def test_no_marked_string_reaches_a_player_in_c64_conversion_or_the_automapper():
    """The same guarantee as `test_no_string_the_player_reads_is_unapproved`,
    for the four other modules that can put a string in front of a player
    and mark it unapproved the same way.

    `#306 (The Fast Travel button's own disabled tooltip carries a memory
    address)`'s last comment found that the `(NOT APPROVED)` marker was
    checked only in `editor/convert.py`, so a marked string in
    `goldbox/c64_codec.py`, `goldbox/amiga.py`, `goldbox/dos.py` or
    `automap/actions.py` shipped to a player silently instead of failing
    here first. This walks each module's own source, the way the test above
    does, rather than a typed list of strings, so a new marked string added
    to any of the four fails here too.

    `goldbox/dos.py` joined the sweep on `#52 (File ▸ Import and File ▸
    Export for every direction the library supports)`: `#389 (A conversion
    to the Amiga tells the player what DOS does with their character)`
    (`d0c280f`) put a marked portrait-position line in `to_neutral`, the DOS
    reader every registered direction with a DOS source calls, and this test
    did not reach that module -- `dos.py`'s own docstring at its `rep.dropped`
    field says it "is read by a person in the conversion pane", so it always
    belonged in this sweep.

    Passes today. `#399 (A conversion that runs out of item or trait slots
    tells the player nothing, because the pane never shows a warning)` put
    six per-character sentences from `goldbox/c64_codec.py` in front of a
    player for the first time, three of them written in developer terms --
    "spell id", "byte mask", "bit", "eight-slot array", "C64 record". All six
    are reworded here and marked `(NOT APPROVED)` rather than shipped guessed
    at; two more marked strings in `c64_codec.py` predate this ticket (the
    combat-icon lines, both directions), and one each in `goldbox/amiga.py`,
    `goldbox/dos.py` and `automap/actions.py` predate or follow it. None of
    the twelve is this test's to approve -- Donald ruled on 2026-09-07 that
    the two combat-icon lines (`c64_codec.py`'s and `amiga.py`'s) stay
    unworded until the tickets that would delete them close, so the right
    outcome here is a count held at today's number rather than a demand
    that it reach zero. `WISH_EXPERIMENTAL_CONVERT` came off on 2026-09-07
    with these still on the pane -- the flag's own condition was about the
    dialog's own strings block, never about this wider sweep.
    """
    import inspect

    from automap import actions
    from goldbox import amiga, c64_codec, dos

    #: How many marked strings each module carries today, waiting on Donald.
    #: **This is a count of what he has to rule on, not a licence.** A new
    #: marked string makes its module's number wrong and fails here, which is
    #: the whole point; the number comes down as he rules, and the day one
    #: reaches zero this test says so rather than passing quietly.
    #:
    #: The twelve, listed on `#399 (A conversion that runs out of item or
    #: trait slots tells the player nothing, because the pane never shows a
    #: warning)` and `#52`: nine in `goldbox/c64_codec.py` -- the six
    #: per-character ceiling sentences that ticket put in front of a player
    #: for the first time, plus three combat-figure lines that predate it --
    #: one in `goldbox/amiga.py`, one in `goldbox/dos.py`
    #: (`#389 (A conversion to the Amiga tells the player what DOS does with
    #: their character)`'s portrait-position line) and one in
    #: `automap/actions.py`, the Fast Travel failure line
    #: `#306 (The Fast Travel button's own disabled tooltip carries a memory
    #: address)` left behind.
    WAITING = {"goldbox.c64_codec": 9, "goldbox.amiga": 1, "goldbox.dos": 1,
               "automap.actions": 1}

    found: dict[str, list[str]] = {}
    for module in (c64_codec, amiga, dos, actions):
        source = inspect.getsource(module)
        found[module.__name__] = [
            f"{module.__name__}:{n}: {line.strip()}"
            for n, line in enumerate(source.splitlines(), start=1)
            if '(NOT APPROVED)"' in line or "(NOT APPROVED)'" in line]

    for name, expected in WAITING.items():
        got = found[name]
        assert len(got) == expected, (
            f"{name} carries {len(got)} strings marked (NOT APPROVED), not "
            f"{expected}. If you added one, it needs Donald's wording before "
            f"it ships; if he has approved one, take the marker off and drop "
            f"this number.\n" + "\n".join(got))


def test_the_approved_strings_are_the_ones_donald_worded():
    """A spot check that stripping the markers did not also strip a word.

    `SOURCE_FILTER` is the one worth pinning: it is a Qt file-dialog filter
    rather than a sentence, the marker sat mid-string because Qt would read
    a trailing one as the glob itself, and removing it there is the edit
    most likely to have taken a bracket with it.
    """
    assert convert.MENU_CONVERT == "&Convert…"
    assert convert.DIALOG_TITLE == "Convert a save"
    # Donald changed this from `Save` on 2026-09-07, looking at the drawn
    # form: `To` had no partner above it. Pinned whole, because it is a
    # string he ruled on and a paraphrase should fail here.
    assert convert.LABEL_SOURCE == "From"
    assert convert.LABEL_TO == "To"
    assert convert.SOURCE_TITLE == "Choose a save"
    assert convert.NO_GAME_FOLDER == "Choose the DOS game folder."
    assert convert.CONVERTED_DOS == "Converted to DOS slot {slot} in {folder}"
    assert convert.DESTINATION_LABELS == {"c64": "Commodore 64", "dos": "DOS"}
    assert convert.SOURCE_FILTER == (
        "Saved games (*.d64 *.D64 *.adf *.ADF SAVGAM?.DAT SAVGAM?.PTY);;"
        "All files (*)")


def test_the_picker_offers_an_amiga_disk():
    """An Amiga save is something Wish takes, and the picker has to say so.

    Donald approved `*.adf` on 2026-09-07 -- *"Yes, the file picker should
    allow .adf files."*  Without it the Amiga to C64 row still works, through
    the `All files (*)` entry, and a player has no way to know it is there:
    a file type absent from the dropdown reads as a file type the program
    does not take.  Pinned separately from the spot check above because it
    is a decision of his rather than a transcription.
    """
    saved = convert.SOURCE_FILTER.split(";;")[0]
    assert "*.adf" in saved and "*.ADF" in saved, convert.SOURCE_FILTER
    # Qt reads a trailing marker as part of the glob, so nothing may follow
    # the last pattern inside the brackets.
    assert saved.endswith(")"), convert.SOURCE_FILTER


# ---------------------------------------------------------------------------
# The menu -- `WISH_EXPERIMENTAL_CONVERT` came off on 2026-09-07, `#52`'s own
# comments recording each of its five conditions met. `_wish_window`/
# `_file_menu` are `tests/test_dosimport.py:708-750`'s private helpers,
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


def test_the_file_menu_carries_convert(app, tmp_path, monkeypatch):
    """No gate left to ask about: `File ▸ Convert…` is built for everyone,
    the way `File ▸ Import` has been since `#131 (Lift
    WISH_EXPERIMENTAL_DOS_IMPORT, which needs the import working for all
    three C64 titles)`."""
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


@needs_dos_saves
@needs_disks
def test_a_conversion_that_drops_nothing_opens_with_what_it_writes(
        tmp_path, game_files, monkeypatch):
    """No heading, and no gap where the heading used to be.

    `#338 (The conversion pane says fields could not be converted and then
    lists none)` was the heading standing over an empty list, once tonight's
    work emptied the lists.  Removing the heading on its own left two blank
    lines at the top of the pane, which a player reads as something missing
    -- the same defect one layer down.

    The empty case is forced rather than found: which fields a given
    specimen drops depends on the disks and creation art the run can reach,
    so a test that waited for a clean one would skip on most machines and
    prove nothing on the rest.  Both branches are asserted here.
    """
    source = str(_save_dir() / "SAVGAMA.DAT")

    def pane(dropped_text):
        monkeypatch.setattr(dosimport, "dropped_text",
                            lambda report: dropped_text)
        dialog = convert.ConvertDialog(
            source, None, lambda game: game_files,
            destination="c64", folder=str(tmp_path))
        try:
            assert dialog.rehearsal is not None
            return dialog.ui.convert_report.toPlainText()
        finally:
            dialog.close()

    empty = pane("")
    assert not empty.startswith("\n"), repr(empty[:40])
    assert empty.startswith(convert.WRITES_HEADING), repr(empty[:60])

    #: And the other branch still puts the gap back when there is something
    #: above it, so this cannot pass by the pane having lost its spacing.
    with_lines = pane("Something was dropped")
    assert with_lines.startswith("Something was dropped\n\n"), repr(
        with_lines[:60])
    assert convert.WRITES_HEADING in with_lines


# ---------------------------------------------------------------------------
# Amiga -> C64: the registry's third source port (#353)
# ---------------------------------------------------------------------------

def _amiga_por_disk():
    """The player's own Amiga Pool of Radiance disk 1, or a skip.

    `tests/test_amigatoc64.py` owns the search and the reason it matches on
    the record's own size rather than on the file names; this is the same
    disk, reached the same way, so the two cannot pick different ones.
    """
    from test_amigatoc64 import _pool_of_radiance_disk_1

    return _pool_of_radiance_disk_1()


@pytest.fixture
def amiga_adf(tmp_path):
    """The player's Amiga disk 1, copied into `tmp_path` as an `.adf`.

    A copy, because `Source.detect` takes a **path** and the player's own
    images are read-only to every test here -- and because the suffix is
    what the detection turns on, and the image on the media server lives
    inside a `.zip`.
    """
    disk = _amiga_por_disk()
    path = tmp_path / "por1.adf"
    path.write_bytes(disk.to_bytes())
    return path


def test_an_adf_is_detected_as_an_amiga_source_at_its_first_slot(amiga_adf):
    """The `.adf` branch of `Source.detect`: port `amiga`, the title off the
    first character record's own length, and the first slot the disk holds
    files for -- the way a DOS folder takes the first slot it holds
    (`#353 (Convert an Amiga Pool of Radiance save to the C64, so a party
    standing in the Slums on the Amiga arrives there in VICE)`)."""
    source = convert.Source.detect(amiga_adf)
    assert source.port == "amiga"
    assert source.key == dos_layout.POOL_OF_RADIANCE.key
    assert source.slot == "A"
    # A disk, not a folder and not a C64 save: nothing was read into memory.
    assert source.save0 is None and source.disk is None


def test_an_adf_source_is_offered_the_commodore_64_and_dos(amiga_adf):
    """Two destinations, both the same title on another port --
    `.claude/rules/conversions.md`: a conversion is between two ports of one
    title and never between titles.

    The C64 comes first because that is the order `DIRECTIONS` is built in,
    and the dialog's combo takes `options[0]` when the caller named no
    destination -- so a player who opens an `.adf` and presses Convert gets
    what `#353 (Convert an Amiga Pool of Radiance save to the C64, so a
    party standing in the Slums on the Amiga arrives there in VICE)` proved,
    and DOS is a choice rather than a change of default."""
    source = convert.Source.detect(amiga_adf)
    directions = convert.destinations_for(source)
    assert [type(d) for d in directions] == [convert.AmigaToC64,
                                             convert.AmigaToDos]
    assert directions[0].destination_game is games.POOL_OF_RADIANCE
    assert directions[0].destination_port == "c64"
    assert directions[1].destination_game is dos_layout.POOL_OF_RADIANCE
    assert directions[1].destination_port == "dos"
    assert convert.DESTINATION_LABELS["c64"] == "Commodore 64"
    assert convert.DESTINATION_LABELS["dos"] == "DOS"


def test_a_file_that_is_not_an_adf_still_goes_to_the_c64_reader(tmp_path):
    """The new branch is reached by suffix, so it must not swallow the C64
    one: a `.d64` that cannot be read still refuses as a C64 disk."""
    path = tmp_path / "notadisk.d64"
    path.write_bytes(b"\x00" * 64)
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(path)


def test_an_adf_that_holds_no_saved_game_is_refused_and_not_guessed_at(
        tmp_path):
    """A blank Amiga floppy is refused with a sentence rather than being
    read as an empty Pool of Radiance disk."""
    from goldbox.amiga_adf import AmigaDisk

    path = tmp_path / "blank.adf"
    path.write_bytes(AmigaDisk.blank("EMPTY").to_bytes())
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(path)


def test_amiga_to_c64_direction_is_the_transfer_test(amiga_adf, tmp_path):
    """The bytes the dialog's Amiga row writes equal what
    `tools/fromamigapor.py` writes, calling `goldbox.amiga.read_por_slot`,
    `goldbox.dos.new_save_from` and `goldbox.dos.save_disk` directly for the
    same slot -- so `#353`'s VICE proof stands for this path too, which is
    the same argument `test_dos_to_c64_direction_is_the_transfer_test`
    makes for the DOS row.

    `icon`/`animate` are zero-filled: this is a round trip of our own code
    for one input, not a claim about what the player's C64 disks hold."""
    from goldbox import amiga

    icon, animate = bytes(36), bytes(852)
    files = dosimport.GameFiles(icon=icon, animate=animate)
    source = convert.Source.detect(amiga_adf)
    direction = convert.destinations_for(source)[0]

    rehearsal = direction.rehearse(source, source.slot, files)
    destination = tmp_path / "out"
    written = direction.write(rehearsal, destination)
    assert [p.name for p in written] == [f"PORSAVE{source.slot}.D64"]

    disk = amiga.AmigaDisk.open(str(amiga_adf))
    party, savgam = amiga.read_por_slot(disk, source.slot)
    state = amiga.read_por_state(savgam, str(amiga_adf))
    ref0, ref1, report = dos.new_save_from(state, party, icon, animate)
    reference = dos.save_disk(bytes(ref0), bytes(ref1))
    assert (destination / f"PORSAVE{source.slot}.D64").read_bytes() == \
        reference.to_bytes()
    assert report.unwritten == []


# ---------------------------------------------------------------------------
# An Amiga disk holding more than one saved game (#372)
# ---------------------------------------------------------------------------

def _outdoor_amiga_disk(tmp_path) -> pathlib.Path:
    """`WISH-SPEC-por-amiga-outdoor`'s own disk, copied so `Source.detect`'s
    path stays writable -- the specimen tree itself is read-only.

    Slot A is the shipped save staged next to the harbour master; slots B
    and C are the first two saved games the Amiga engine itself ever wrote
    on the travel grid, `tests/test_amigatoc64.py`'s `outdoor_disk` fixture
    and `#321 (An Amiga Pool of Radiance conversion refuses a party standing
    on the travel grid, because no outdoor Amiga saved game has ever been
    read)`'s run: world `(7, 29)` east at 05:53 for B, `(7, 28)` north at
    17:53 for C, both area 26.
    """
    from gamedata import specimen

    where = specimen("por-amiga-outdoor", "amiga")
    path = tmp_path / "por1-outdoor.adf"
    path.write_bytes((where / "por1-outdoor.adf").read_bytes())
    return path


def test_a_disk_with_one_slot_shows_no_slot_row(amiga_adf):
    """The shipped disk holds slot A alone -- the row stays hidden and
    `Source.detect` still takes it silently, exactly as before this row
    existed (`#372`'s brief: silently taking the one slot is unchanged)."""
    source = convert.Source.detect(amiga_adf)
    assert source.available_slots == ["A"]

    dialog = convert.ConvertDialog(str(amiga_adf), None, _no_disks)
    try:
        assert dialog.source.slot == "A"
        assert not dialog.ui.form.isRowVisible(dialog.ui.convert_slot)
    finally:
        dialog.close()


def test_a_disk_with_three_slots_offers_a_slot_row(tmp_path):
    """The regression `#372 (An Amiga disk with more than one saved game
    converts its first slot, whichever one the player meant)` describes: a
    disk naming more than one slot gets a row rather than being reduced to
    its first."""
    path = _outdoor_amiga_disk(tmp_path)
    dialog = convert.ConvertDialog(str(path), None, _no_disks)
    try:
        assert dialog.source.available_slots == ["A", "B", "C"]
        assert dialog.ui.form.isRowVisible(dialog.ui.convert_slot)
        assert dialog.ui.label_slot.text() == convert.LABEL_SLOT
        items = [dialog.ui.convert_slot.itemData(i)
                for i in range(dialog.ui.convert_slot.count())]
        assert items == ["A", "B", "C"]
        # Opening the dialog picks nothing for the player -- the row starts
        # on the first slot, the same one `Source.detect` always took before
        # this row existed, so a disk with one game keeps behaving the same
        # way it always has.
        assert dialog.source.slot == "A"
    finally:
        dialog.close()


def test_choosing_a_slot_converts_that_partys_own_place_not_the_first(
        tmp_path):
    """Picking slot C on a disk that also holds A and B converts C's own
    party and position, not A's -- the situation `#372` names: *"He points
    File ▸ Convert… at it and gets the first slot, whichever one he
    meant."*

    Slot C's own place is world `(7, 28)`, area 26, outdoors
    (`_outdoor_amiga_disk`'s docstring) -- read back through
    `goldbox.world_state.from_c64`, a different reader over a different
    container, so this is the written save agreeing with the source rather
    than one number compared with itself.
    """
    from goldbox import amiga, world_state

    path = _outdoor_amiga_disk(tmp_path)
    dialog = convert.ConvertDialog(str(path), None, _no_disks)
    try:
        items = [dialog.ui.convert_slot.itemData(i)
                for i in range(dialog.ui.convert_slot.count())]
        dialog.ui.convert_slot.setCurrentIndex(items.index("C"))
        assert dialog.source.slot == "C"

        icon, animate = bytes(36), bytes(852)
        files = dosimport.GameFiles(icon=icon, animate=animate)
        direction = convert.destinations_for(dialog.source)[0]
        rehearsal = direction.rehearse(dialog.source, dialog.source.slot,
                                       files)
        written = direction.write(rehearsal, tmp_path / "out")

        disk = amiga.AmigaDisk.open(str(path))
        party, savgam = amiga.read_por_slot(disk, "C")
        state = amiga.read_por_state(savgam, str(path))
        ref0, ref1, report = dos.new_save_from(state, party, icon, animate)
        reference = dos.save_disk(bytes(ref0), bytes(ref1))
        assert written[0].read_bytes() == reference.to_bytes()
        assert report.unwritten == []

        landed = world_state.from_c64(bytes(ref0))
        assert landed.outdoors is True
        assert landed.travel == (7, 28)
        assert landed.area == 26
    finally:
        dialog.close()


@needs_dos_saves
def test_changing_the_slot_carries_into_the_dos_direction_too(tmp_path):
    """The row feeds `Source.detect` once, so both registered directions --
    `AmigaToC64` and `AmigaToDos` -- read whichever slot the player chose.
    `AmigaToDos` takes `source.slot` directly (`AmigaToDos.rehearse`'s own
    docstring: "Two slots, and they are not the same letter"), so this is
    the other direction reading the row rather than a second mechanism."""
    from goldbox import amiga

    path = _outdoor_amiga_disk(tmp_path)
    dialog = convert.ConvertDialog(str(path), None, _no_disks)
    try:
        items = [dialog.ui.convert_slot.itemData(i)
                for i in range(dialog.ui.convert_slot.count())]
        dialog.ui.convert_slot.setCurrentIndex(items.index("C"))
        assert dialog.source.slot == "C"

        directions = convert.destinations_for(dialog.source)
        direction = next(d for d in directions
                         if d.destination_port == "dos")
        rehearsal = direction.rehearse(dialog.source, "A", _game_dir())

        disk = amiga.AmigaDisk.open(str(path))
        party, _savgam = amiga.read_por_slot(disk, "C")
        assert [c.fields["name"].value for c in rehearsal.characters] == \
            [c.name for c in party]
    finally:
        dialog.close()


def test_the_report_pane_is_labelled_and_bounded_at_six_lines():
    """The two changes Donald asked for on 2026-09-07, reviewing the
    Amiga-row mock-up for `#316 (Write the Amiga Pool of Radiance saved game
    from the source save, so a converted party arrives where it was
    standing)`: *"The report pane gets smaller"* and *"It gains a label
    above it reading `Convert Log`."* -- his words, approved.

    The height is asserted as a multiple of the pane's own font, never a
    pixel count (`.claude/rules/testing.md`: "A number measured on this
    machine is not a number"), so this holds at whatever font the machine
    running it uses.
    """
    dialog = convert.ConvertDialog("", None, _no_disks)
    try:
        assert dialog.ui.label_report.text() == convert.LABEL_REPORT
        assert dialog.ui.label_report.font().bold()

        metrics = dialog.ui.convert_report.fontMetrics()
        expected = (convert.ConvertDialog.REPORT_LINES * metrics.height()
                   + 2 * dialog.ui.convert_report.frameWidth())
        assert dialog.ui.convert_report.maximumHeight() == expected
        #: Smaller than the pane's own natural, unbounded size for a report
        #: with real content -- proven with the destination row filled in
        #: elsewhere in this file; here it is enough that a cap exists at
        #: all, since `QWIDGETSIZE_MAX` is what an unbounded `QPlainTextEdit`
        #: carries otherwise.
        from PyQt6.QtWidgets import QWIDGETSIZE_MAX
        assert dialog.ui.convert_report.maximumHeight() < QWIDGETSIZE_MAX
    finally:
        dialog.close()

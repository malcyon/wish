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

import gamedata
import pytest
from gamedata import disk_dir, game_file
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFileDialog
from test_dossave import _save_dir, needs_dos_saves

from editor import convert, dosimport
from editor.window import EditorBinding
from goldbox import dos, dos_layout, dos_savegame, games, titles
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

def test_destinations_for_lists_pool_of_radiances_registered_directions():
    """Pool of Radiance is the one title with an Amiga writer
    (`goldbox.amiga.WRITES`, `#316 (Write the Amiga Pool of Radiance saved
    game from the source save, so a converted party arrives where it was
    standing)`), so its two sources each answer two directions rather than
    one -- DOS still first for a DOS source, C64 still first for a C64
    source."""
    dos_source = convert.Source(port="dos", title=dos_layout.POOL_OF_RADIANCE,
                                path=pathlib.Path("."))
    assert [type(d) for d in convert.destinations_for(dos_source)] == \
        [convert.DosToC64, convert.DosToAmiga]

    c64_source = convert.Source(port="c64", title=games.POOL_OF_RADIANCE,
                                path=pathlib.Path("."))
    directions = convert.destinations_for(c64_source)
    assert [type(d) for d in directions] == \
        [convert.C64ToDos, convert.C64ToAmiga]
    assert directions[0].destination_game is dos_layout.POOL_OF_RADIANCE
    assert directions[1].destination_game is dos_layout.POOL_OF_RADIANCE


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


def test_directions_holds_ten_rows_derived_from_four_library_tuples():
    """Three titles read DOS → C64 (`goldbox.dos.CONVERTS`) and the same
    three write C64 → DOS (`goldbox.dos.WRITES`, as of `#299`); Pool of
    Radiance alone reads Amiga → C64 and Amiga → DOS
    (`goldbox.amiga.CONVERTS`, as of
    `#353 (Convert an Amiga Pool of Radiance save to the C64, so a party
    standing in the Slums on the Amiga arrives there in VICE)` and
    `#354 (Convert an Amiga Pool of Radiance save to DOS, so a party
    standing in the Slums on the Amiga arrives there under DOSBox)`), and
    Pool of Radiance alone writes C64 → Amiga and DOS → Amiga
    (`goldbox.amiga.WRITES`, `#316 (Write the Amiga Pool of Radiance saved
    game from the source save, so a converted party arrives where it was
    standing)`), so the registry holds ten rows -- up from four before
    `#299`'s container writer, six before `#353`'s Amiga reader, and eight
    before `#316`'s Amiga saved-game writer.

    Counted by exact type rather than `isinstance`, because each Amiga row
    derives from the DOS row that shares its destination -- `AmigaToC64`
    from `DosToC64` and `AmigaToDos` from `C64ToDos` -- so an `isinstance`
    count would read an Amiga row as a DOS one and pass while the Amiga row
    was missing entirely. `C64ToAmiga` and `DosToAmiga` derive from
    `Direction` directly, so they need no such care."""
    assert len(convert.DIRECTIONS) == 10
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.DosToC64) == 3
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.C64ToDos) == 3
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.AmigaToC64) == 1
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.AmigaToDos) == 1
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.C64ToAmiga) == 1
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.DosToAmiga) == 1


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
    for shape in convert.C64_PAIRED:
        assert shape.key in convert.DOS_TO_C64_NAMES, (
            f"{shape.title} converts but names no .D64 file")
    # `dos.CONVERTS` and `C64_PAIRED` differ by exactly the titles with no
    # C64 port, and there is one: Pools of Darkness reads and writes for its
    # **Amiga** pairing (`#194 (Import and export a Pools of Darkness save
    # between DOS and the Amiga)`) and has no `.D64` to name, ever.
    #
    # **The guard behind `C64_PAIRED` moved conceptually, not in code, for
    # `#470 (Give the project a neutral title beside its neutral character
    # record, with one port per platform a title shipped on)`'s stage 2.**
    # It used to read as "is this a title we know" -- true before `goldbox/
    # titles.py` existed, since `games.BY_KEY` was every title this project
    # had a registry for. It now reads as "does this title have a C64 port",
    # which `games.BY_KEY` still answers, because `goldbox/titles.py`'s
    # seven-title registry is the one that would answer the first question
    # and get this one wrong -- see
    # `test_the_c64_guard_is_the_port_registry_not_the_title_one` below.
    assert [s.key for s in dos.CONVERTS if s not in convert.C64_PAIRED] == \
        [dos_layout.POOLS_OF_DARKNESS.key]


def test_the_c64_guard_is_the_port_registry_not_the_title_one():
    """The landmine `#470`'s stage 2 named by hand: swapping `C64_PAIRED`'s
    `games.BY_KEY` guard for `goldbox.titles.BY_KEY` -- the natural-looking
    move once every other per-title table in this stage reads through
    `titles` instead of `games` -- would put Pools of Darkness back into
    `C64_PAIRED`, since `titles.BY_KEY` knows it and `games.BY_KEY` does not.
    `DIRECTIONS` would then build `DosToC64(pools-of-darkness)` at import
    time and raise `UnnamedConversionError`, which is the same failure
    `#194`'s comment of 2026-09-08 records from before this guard existed,
    the other way round.

    So this pins the one fact that makes `games.BY_KEY` the right guard and
    `titles.BY_KEY` the wrong one: a title can be known without having a C64
    port, and Pools of Darkness is the permanent example."""
    assert dos_layout.POOLS_OF_DARKNESS.key not in games.BY_KEY
    assert dos_layout.POOLS_OF_DARKNESS.key in titles.BY_KEY


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
    called from `ConvertDialog`. Watched failing before the fix: `report.
    dropped` kept the `region_220` note and every character's `(icon_head,
    icon_body)` read back `(0, 0)`.

    Checked against `report.dropped` directly, not the pane -- since
    2026-09-08 (`.claude/rules/conversions.md`) the pane never carries the
    drop list at all, so a check against its text would pass whether or not
    the icon was actually wired.

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
        assert not any("figure is not set" in d
                       for d in dialog.rehearsal.report.dropped), \
            dialog.rehearsal.report.dropped
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
# `#482 (With no game disks for the source title, a C64 party converted to
# DOS or the Amiga silently arrives with no combat figures, though a C64
# destination refuses)`: the source's own disks are needed for the combat
# icon exactly the way a C64 destination's already are, and a missing set
# refuses the same way -- rather than converting with `icon_parts=None` and
# every figure silently the game's own default.
# ---------------------------------------------------------------------------

def test_a_c64_source_with_no_disks_is_refused_for_a_dos_destination(
        tmp_path):
    """Watched failing before the fix: with `_no_disks`, `dialog.rehearsal`
    was not `None` and the Convert button was pressable, exactly `#482`'s
    silent loss."""
    path = _por_c64_disk(tmp_path)

    dialog = convert.ConvertDialog(str(path), None, _no_disks,
                                   destination="dos",
                                   game=str(tmp_path / "unread"),
                                   folder=str(tmp_path / "out"))
    try:
        assert dialog.direction.destination_port == "dos"
        assert dialog.rehearsal is None
        assert dialog._blocked == (convert.NO_DISKS_TITLE, convert.NO_DISKS)
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        assert not ok.isEnabled()
    finally:
        dialog.close()


def test_a_c64_source_with_no_disks_is_refused_for_an_amiga_destination(
        tmp_path):
    """The same refusal, for the other silent direction `#482` named."""
    path = _por_c64_disk(tmp_path)

    dialog = convert.ConvertDialog(str(path), None, _no_disks,
                                   destination="amiga",
                                   disk=str(tmp_path / "unread.adf"),
                                   folder=str(tmp_path / "out"))
    try:
        assert dialog.direction.destination_port == "amiga"
        assert dialog.rehearsal is None
        assert dialog._blocked == (convert.NO_DISKS_TITLE, convert.NO_DISKS)
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        assert not ok.isEnabled()
    finally:
        dialog.close()


# The unchanged case: `test_the_c64_disks_are_looked_up_by_the_destination_
# title` above already proves a C64 destination still refuses through this
# same `NO_DISKS` line, so the fix above did not move the case that already
# worked.


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


@pytest.fixture(autouse=True)
def _no_real_modals(monkeypatch):
    """Neutralise `QMessageBox.critical`/`.warning`/`.information` by
    default, for every test in this module.

    `ConvertDialog._maybe_warn` (2026-09-10) pops a real one once a dialog
    is `_interactive` -- true for anything built and then driven further,
    `_choose_files()`, `_choose_source()` and a second `replan()` among
    them. Without this fixture several of those hang under `pytest`'s
    offscreen platform, waiting on a `QMessageBox.exec()` nobody can
    dismiss: seen directly, a serial (`-n0`) run of this whole file was
    killed by its own 300-second `timeout` with no test past the first one
    that reaches this having printed anything at all.

    A test that wants to know what the dialog actually showed does its own
    `monkeypatch.setattr` on `convert.QMessageBox` -- `test_editor.py`'s own
    pattern for `EditorBinding.save`'s failures -- which simply replaces
    this default for that one test.

    `EditorBinding.save()` (`#515`) can now open a real `getSaveFileName`
    chooser too, whenever `window.close()` is called on a dirty party with
    no path -- the same hazard as the message boxes above, and the same
    fix: default it to a cancelled chooser so nothing here can block on
    one, and a test that wants to drive the chooser overrides this default
    the same way `test_dosimport.py` does.
    """
    monkeypatch.setattr(convert.QMessageBox, "critical",
                        lambda *a, **k: None)
    monkeypatch.setattr(convert.QMessageBox, "warning",
                        lambda *a, **k: None)
    #: `EditorBinding.convert`'s own success pop-up, `QMessageBox.
    #: information` (`#52`) -- the same class object `convert.QMessageBox`
    #: names, so patching it here reaches `editor/window.py`'s call too.
    monkeypatch.setattr(convert.QMessageBox, "information",
                        lambda *a, **k: None)
    #: Same reasoning, for `QFileDialog.getSaveFileName` -- the same class
    #: object `editor/window.py`'s `save()` and `save_as()` call.
    monkeypatch.setattr(convert.QFileDialog, "getSaveFileName",
                        lambda *a, **k: ("", ""))


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


def _some_disks(_game):
    """A `game_files` lookup standing in for disks that were found, carrying
    no icon table.

    Building one would mean reading a real disk, and no test here needs it:
    `#482 (With no game disks for the source title, a C64 party converted to
    DOS or the Amiga silently arrives with no combat figures, though a C64
    destination refuses)`'s guard checks only that this answers something,
    and the callers below test the write path rather than the combat icon,
    which `#422 (A C64 party converted to an Amiga save disk arrives with no
    combat figure at all, because C64ToAmiga never recognises it)` and
    `#383 (The live Convert dialog never wires a C64 party's own combat icon
    into DOS, so region_220 stays on the drop list)` already cover."""
    return SimpleNamespace(icon=None)


def test_a_pool_of_radiance_d64_lists_dos(tmp_path):
    """A C64 source offers the registered C64 -> DOS row and, since
    `#316 (Write the Amiga Pool of Radiance saved game from the source
    save, so a converted party arrives where it was standing)`, the
    registered C64 -> Amiga row -- DOS still first, so a player who presses
    Convert without looking gets what `#26 (Write a DOS save, not just read
    one)` proved."""
    path = _por_c64_disk(tmp_path)

    dialog = convert.ConvertDialog(str(path), None, _no_disks)
    try:
        assert dialog.source is not None and dialog.source.port == "c64"
        labels = [dialog.ui.convert_destination.itemData(i)
                 for i in range(dialog.ui.convert_destination.count())]
        assert labels == ["dos", "amiga"]
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
    picker ... so there is no slot row"), and since `#316` offers the
    registered DOS -> Amiga row too."""
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
        assert labels == ["c64", "amiga"]
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
        assert dialog._blocked == (convert.DIALOG_TITLE, convert.CANNOT_CONVERT)
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        assert not ok.isEnabled()
    finally:
        dialog.close()


def test_the_game_files_row_is_shown_for_every_destination_with_its_own_label(
        tmp_path):
    """The row that used to appear and vanish is one row now, always shown,
    in all six directions (`#413 (The Convert window changes shape depending
    on which platforms you are converting between)`) -- only its label
    changes, from `DOS game folder` to `C64 game disks` as the destination
    does."""
    path = _por_c64_disk(tmp_path)

    dialog = convert.ConvertDialog(str(path), None, _no_disks)
    try:
        assert dialog.direction.destination_port == "dos"
        assert dialog.ui.form.isRowVisible(dialog.ui.files_row)
        assert dialog.ui.label_files.text() == convert.LABEL_GAME
    finally:
        dialog.close()

    folder = _synthetic_dos_folder(tmp_path, dos_layout.POOL_OF_RADIANCE,
                                   slot="C", name="dos2")
    dialog2 = convert.ConvertDialog(
        str(folder / "SAVGAMC.DAT"), None, _no_disks)
    try:
        assert dialog2.direction.destination_port == "c64"
        assert dialog2.ui.form.isRowVisible(dialog2.ui.files_row)
        assert dialog2.ui.label_files.text() == convert.LABEL_C64
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
        assert dialog._blocked == (convert.NO_DISKS_TITLE, convert.NO_DISKS)
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
def test_the_destination_line_is_blank_with_nothing_chosen(tmp_path):
    """Before a source is picked, before it can be read, and before a
    destination folder is chosen, the line under `Write to` says nothing --
    it is not the label with nothing after it, and not a guess at a file
    Convert is not about to write.

    Fails before the fix: reverting `replan`'s own reset (put the file back,
    per `.claude/rules/scratch.md`, then delete `__pycache__`) leaves
    `AttributeError: 'Ui_ConvertDialog' object has no attribute
    'convert_destination_line'` instead, since the widget and the reset are
    the same commit -- seen red, then the fix put back.
    """
    empty_source = convert.ConvertDialog("", None, _no_disks)
    try:
        assert empty_source.ui.convert_destination_line.text() == ""
    finally:
        empty_source.close()

    path = _por_c64_disk(tmp_path)
    no_folder_chosen = convert.ConvertDialog(str(path), None, _some_disks,
                                             game=str(_game_dir()))
    try:
        assert no_folder_chosen.rehearsal is not None
        assert no_folder_chosen.ui.convert_destination_line.text() == ""
    finally:
        no_folder_chosen.close()


@needs_dos_saves
def test_the_destination_line_names_the_folder_before_the_button_is_enabled(
        tmp_path):
    """The destination line under `Write to` says where the write would
    land, not the files inside it, so a player never has to guess which
    folder Convert is about to write into -- and the button is enabled
    only once it does.

    Names the folder alone since 2026-09-10's second ruling that day: a
    C64 -> DOS write can name a dozen files, and joining them onto one
    line forced the dialog to 6688px wide. Fails before that fix -- the
    file's own name, `SAVGAMA.DAT`, appearing in the line asserted below --
    seen red when the destination text still comma-joined every file in
    `rehearsal.files`, then the fix put back.

    `_some_disks`, not `_no_disks`: this row's own C64 -> DOS default
    direction now refuses with no source disks (`#482`), and this test is
    about the destination line rather than that refusal."""
    path = _por_c64_disk(tmp_path)
    destination = tmp_path / "out"
    destination.mkdir()

    dialog = convert.ConvertDialog(str(path), None, _some_disks,
                                   folder=str(destination),
                                   game=str(_game_dir()))
    try:
        today = datetime.date.today().isoformat()
        expected_folder = str(destination / f"wish-{today}")
        assert dialog.ui.convert_destination_line.text() == \
            convert.DESTINATION_PREFIX + expected_folder
        assert "SAVGAMA.DAT" not in dialog.ui.convert_destination_line.text()
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


def test_convert_with_no_source_opens_the_dialog_instead_of_a_picker(
        tmp_path, monkeypatch):
    """`#412 (File ▸ Convert demands a save in a file picker before it will
    show you the Convert window)`: choosing File ▸ Convert… with no source
    goes straight to the Convert window -- the picker `getOpenFileName` used
    to open first is never called at all."""
    window = EditorBinding(_make_root())

    def _refuse_a_picker(*args, **kwargs):
        raise AssertionError("a file picker opened before the Convert window")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", _refuse_a_picker)

    opened = []
    original_exec = convert.ConvertDialog.exec

    def _record_and_reject(self):
        opened.append(self)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(convert.ConvertDialog, "exec", _record_and_reject)
    try:
        outcome = window.convert()
    finally:
        window.close()
        monkeypatch.setattr(convert.ConvertDialog, "exec", original_exec)

    assert outcome == "cancelled"
    assert len(opened) == 1
    assert opened[0].ui.convert_source.text() == ""


def test_convert_is_not_pressable_with_an_empty_from_row():
    """The `Convert` button stays disabled until a source is chosen --
    `#412 (File ▸ Convert demands a save in a file picker before it will
    show you the Convert window)`."""
    dialog = convert.ConvertDialog("", None, _no_disks)
    try:
        button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert not button.isEnabled()
    finally:
        dialog.close()


def test_choosing_a_source_through_the_row_populates_the_to_combo(tmp_path):
    """The row's own `Choose` button does what the old picker in front of
    the window used to do: naming a source populates the `To` combo --
    `#412 (File ▸ Convert demands a save in a file picker before it will
    show you the Convert window)`."""
    path = _por_c64_disk(tmp_path)
    dialog = convert.ConvertDialog("", None, _no_disks)
    try:
        assert dialog.ui.convert_destination.count() == 0
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                QFileDialog, "getOpenFileName",
                lambda *args, **kwargs: (str(path), ""))
            dialog._choose_source()
        assert dialog.ui.convert_destination.count() > 0
    finally:
        dialog.close()


@needs_dos_saves
@needs_disks
def test_the_open_saves_unsaved_edits_cross(tmp_path, monkeypatch):
    """Converting the save already open in the editor uses the bytes on
    screen, edits included -- the same rule
    `exports.Source.from_party` followed, ported here rather than argued
    from plausibility.

    `disks=` is passed now: with none configured, `window.game_files_for`
    answered `None` for every title regardless of the real disks
    `@needs_disks` requires, and a C64 -> DOS conversion with no source disks
    now refuses (`#482`) rather than converting with no combat icon."""
    path = _por_c64_disk(tmp_path, name="open.d64")
    window = EditorBinding(_make_root(), disks=str(disk_dir()))
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
def test_an_edit_typed_on_the_sheet_and_never_saved_still_converts(
        app, tmp_path, monkeypatch):
    """The sibling above edits `party.save0` directly, which is the disk
    image `Source.detect` already reads -- so it cannot tell `convert` was
    missing the `_flush`/`_write_back` pair `export_source` has always had
    (`#478 (File ▸ Convert converts the save as it was opened, not as it is
    on screen, because it never flushes the editor's own edits)`). This one
    goes through the widget instead: BRUTUS's own gold, typed on the sheet
    and never saved, has to reach the converted DOS record.

    `disks=` is passed now, for the same reason the sibling above needs it:
    a C64 -> DOS conversion with no source disks refuses (`#482`)."""
    from test_editor import make_root

    from editor.window import EditorBinding

    path = _por_c64_disk(tmp_path, name="open.d64")
    window = EditorBinding(make_root(), disks=str(disk_dir()))
    window.load(str(path))
    window.roster.selectRow(0)
    assert window._widgets["gold"].value() == 120        # BRUTUS, unedited
    window._widgets["gold"].setValue(9999)

    game_dir = _game_dir()
    destination = tmp_path / "out"
    destination.mkdir()

    monkeypatch.setattr(convert.ConvertDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    # No `window.close()` afterwards, unlike the sibling above: the gold
    # edit went through a widget and so is in `self.dirty`, and `close()`
    # pops a real, blocking `QMessageBox.question` for unsaved changes --
    # the sibling's edit bypasses that by writing `party.save0` directly.
    window.convert(source=str(path), folder=str(destination),
                  game=str(game_dir))

    written = next(destination.glob("wish-*/CHRDATA1.SAV"))
    assert dos.read_character(written).money["gold"] == 9999


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


@needs_dos_saves
@needs_disks
def test_a_successful_c64_conversion_pops_the_confirmation_after_loading_it(
        tmp_path, monkeypatch):
    """`#52`'s `CONVERT_SUCCESS` box, on the C64 branch -- the one
    destination with no status-line note of its own (`self.load()` is all
    it did before this, easy to miss when a save was already open). The
    party is already on screen when the box appears, since `EditorBinding.
    convert` calls `self.load()` first (`test_a_c64_destinations_result_is_
    the_party_on_screen_afterwards` proves that load); this only adds the
    pop-up on top of it, with Donald's own wording and the same folder the
    dialog's `Destination:` line names."""
    save_dir = _save_dir()
    disks = disk_dir()
    window = EditorBinding(_make_root(), disks=str(disks))
    destination = tmp_path / "out"
    destination.mkdir()

    shown = []
    monkeypatch.setattr(convert.ConvertDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(
        convert.QMessageBox, "information",
        lambda parent, title, text: shown.append((title, text)))
    opened = []
    window.opened.connect(opened.append)
    try:
        window.convert(source=str(save_dir / "SAVGAMA.DAT"),
                      folder=str(destination))
    finally:
        window.close()

    today = datetime.date.today().isoformat()
    fresh = destination / f"wish-{today}"
    assert len(opened) == 1        # the party was already loaded
    assert shown == [(convert.DIALOG_TITLE,
                     convert.CONVERT_SUCCESS.format(folder=fresh))]


def test_no_string_reachable_in_the_pane_contains_a_hex_offset(tmp_path):
    """`.claude/rules/gui-text.md`: no memory address or file offset in
    front of a player. Every state this module can reach with no real game
    disks, checked at once -- the destination line, and the refusal
    `_blocked` would show in a modal (`_no_real_modals` keeps the modal
    itself from actually opening; the text is checked here instead)."""
    import re

    hexish = re.compile(r"(?:0x[0-9A-Fa-f]+|\$[0-9A-Fa-f]{2,})")

    states = []

    folder = _synthetic_dos_folder(tmp_path, dos_layout.POOLS_OF_DARKNESS,
                                   suffix="PTY", name="pod")
    d1 = convert.ConvertDialog(str(folder / "SAVGAMA.PTY"), None, _no_disks)
    states.append(d1.ui.convert_destination_line.text())
    states.append(d1._blocked[1] if d1._blocked else "")
    d1.close()

    path = _por_c64_disk(tmp_path)
    d2 = convert.ConvertDialog(str(path), None, _no_disks)
    states.append(d2.ui.convert_destination_line.text())
    states.append(d2._blocked[1] if d2._blocked else "")
    d2.close()

    d3 = convert.ConvertDialog("", None, _no_disks)
    states.append(d3.ui.convert_destination_line.text())
    states.append(d3._blocked[1] if d3._blocked else "")
    d3.close()

    for text in states:
        assert not hexish.search(text), text


@needs_dos_saves
def test_no_string_in_the_ready_to_write_c64_to_dos_pane_carries_developer_detail(
        tmp_path):
    """The one pane state `test_no_string_reachable_in_the_pane_contains_a_
    hex_offset` could not reach with no real game disks: a C64 source with a
    DOS game folder and a destination folder both chosen, which is what
    actually rehearses the write and used to put the drop list on screen.
    Every other state that module checks refuses before reaching a drop
    line at all (#355, A C64 party converted to DOS is shown nine developer
    notes, with memory addresses, overlay names and issue numbers in them).

    Failed before the original fix, on `0x0E3`, `$1633`, `CHARPIC00`,
    `LIBRARY`, `GEN`, `#277`, `#268` and `#202` -- back when the drop lines
    themselves reached the pane. Donald's ruling of 2026-09-08
    (`.claude/rules/conversions.md`) took the whole drop list out of what a
    player reads, so this now pins the stronger guarantee: the drop list is
    real for this conversion, none of it is in the pane at all, and it
    reaches the debug log instead -- `WISH_DEBUG` is exactly where a
    developer note like these belongs (`.claude/rules/gui-text.md` exempts
    that log from the same rule by name).

    `_some_disks`, not `_no_disks`: a C64 source converting to DOS with no
    source disks now refuses before ever reaching a rehearsal (`#482`), and
    this test is about the drop list a *completed* rehearsal produces --
    `icon=None` still leaves the combat-icon field on that list, the same
    drop `#482`'s own audit quotes.
    """
    import re

    from wish import debuglog

    hexish = re.compile(r"(?:0x[0-9A-Fa-f]+|\$[0-9A-Fa-f]{2,})")
    bare_issue = re.compile(r"#\d+")
    overlay_names = ("LIBRARY", "GEN", "COM.PREP", "CHARPIC00")

    path = _por_c64_disk(tmp_path)
    destination = tmp_path / "out"
    destination.mkdir()
    debuglog.start()
    try:
        dialog = convert.ConvertDialog(str(path), None, _some_disks,
                                       game=str(_game_dir()),
                                       folder=str(destination))
        try:
            text = (dialog.ui.convert_destination_line.text()
                    + (dialog._name_warning or ""))
            dropped = dialog.rehearsal.report.dropped
        finally:
            dialog.close()
        log_text = debuglog.path().read_text(encoding="utf-8")
    finally:
        debuglog.stop()

    #: Proof this reached the drop-list state the test is about.
    assert dropped, "expected this conversion to have drop lines to check"
    #: Gone from the pane entirely, not merely cleaned up.
    assert not any(d in text for d in dropped), text
    assert not hexish.search(text), text
    assert not bare_issue.search(text), text
    assert not any(o in text for o in overlay_names), text
    #: And carried to the debug log instead, so a bug report can still say
    #: what this conversion left behind.
    assert all(d in log_text for d in dropped), log_text


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

    # The two codecs by their own names rather than through the
    # `goldbox/dos.py` and `goldbox/amiga.py` shims: `#470`'s stage 8 moved
    # the code to `dos_codec.py` and `amiga_codec.py`, and
    # `inspect.getsource` of a shim reads the shim, which carries no strings
    # at all. `WAITING` is keyed on `module.__name__`, so both move together.
    from goldbox import amiga_codec, c64_codec, dos_codec

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
    #: `automap.actions` went from one to two on 2026-09-07: Curse's trainer
    #: raises every ready class in one press (`GEN $14F8`), so the message
    #: after a level-up can now name more than one class in a sentence --
    #: a shape no player has seen, because Pool of Radiance's trainer never
    #: raises two classes at once. `#415 (automap/window.py picks the
    #: level-up spell dialog's class the same wrong way plan would have,
    #: blocking Curse's trainer)`. Naming only the last class raised would
    #: under-report what changed on the character's own sheet, so the
    #: sentence is the right one and only the wording waits on Donald.
    #: And from two to three on 2026-09-07, in the same file: the
    #: confirmation dialog that warns of a lost level had the same gap --
    #: `LevelUp.confirmation` now previews the whole `plan_all` chain rather
    #: than one step, and a chain of more than one class needs the same kind
    #: of multi-class sentence the outcome message above already carries
    #: (`#418 (The level-up confirmation dialog previews one step of a Curse
    #: dual-training press, not the whole chain)`).
    #: And from three to five on 2026-09-08: `#207 (Run an exit's own
    #: handler before Fast Travel warps out)` gave `FastTravel._run_via_exit`
    #: two new lines -- what a player reads when the exit's own handler is
    #: about to run ("answer whatever the game asks") and what they read if
    #: the stack could not be rebuilt to reach it. Neither existed before:
    #: a fast travel used to enter `NEWECL` at its own tail and never handed
    #: control back to a live script the player could be asked anything by.
    #: `goldbox.amiga` went from one to two on 2026-09-08: `pod_to_neutral`
    #: is the first thing that reads an Amiga Pools of Darkness `.pc` into
    #: the neutral record (`#194 (Import and export a Pools of Darkness save
    #: between DOS and the Amiga)`), and 37 of the 75 neutral fields have no
    #: located home in that record yet -- the spellbook, the item region, the
    #: effect region and the combat tail among them. One sentence naming that
    #: is what keeps the loss out of silence; thirty-seven written by an
    #: agent would be the opposite of Donald wording what a player reads.
    #: `goldbox.dos` went from one to eight and `goldbox.amiga` from two to
    #: three on 2026-09-08, closing the write-side half of `#389 (A
    #: conversion to the Amiga tells the player what DOS does with their
    #: character)` its own last comment left open: `goldbox.dos.write` always
    #: builds a DOS record, even when `goldbox.amiga.write_por` and
    #: `write_later` re-cut it into an Amiga one, and five of its own canned
    #: drop reasons named "DOS" regardless of which writer was asking --
    #: `write` now takes an `into` parameter the two Amiga writers pass
    #: `"Amiga"` through, so the composed sentences differ by wording rather
    #: than by number, and each of the five needed its own marker. A sixth
    #: line in `goldbox.dos.write` and one in `goldbox.amiga.to_neutral` had
    #: the same defect in the same commit but only lost the word "DOS"
    #: without otherwise changing, so they carry a marker too rather than
    #: being judged already-approved by resemblance to the old wording --
    #: `.claude/rules/gui-text.md`'s own ruling on that shortcut, "it matches
    #: the wording already there is not approval".
    #: **Four came off on 2026-09-09, and none of them was approved: they
    #: stopped being strings a player can reach.** Donald's ruling of
    #: 2026-09-08 sent the drop list to `wish/debuglog.py`
    #: (`.claude/rules/conversions.md`, *"a drop line is therefore never a
    #: string Donald words"*), and `.claude/rules/gui-text.md` exempts that
    #: log by name, so a line that only ever lands on `report.dropped` is
    #: nobody's to word. `editor/dosimport.pane_text` is the whole of what
    #: the Convert dialog draws and it reads `messages` and `losses` alone,
    #: logging `dropped` instead. The four: `goldbox.c64_codec`'s
    #: combat-icon line in `write` (9 to 8), `goldbox.dos.to_neutral`'s
    #: portrait-position line (8 to 7), and `goldbox.amiga`'s `0x11F`
    #: trailing-pad line and its `field_83_87` treasure-share entry in
    #: `LATER_DROPPED_PLAYER_TEXT` (3 to 1).
    #:
    #: **The drop lines that kept their marker did so for one reason**:
    #: `editor/exports.py`'s own pane still draws `report.dropped` through
    #: `exports.losses`, and `File ▸ Export` is built whenever
    #: `WISH_EXPERIMENTAL_EXPORT` is set. That pane reads a **C64** save, so
    #: every drop line the C64 reader and the DOS and Amiga writers compose
    #: can still reach a person -- which is `goldbox.c64_codec`'s
    #: `READ_DROPPED_PLAYER_TEXT` entry and all seven of `goldbox.dos`'s.
    #: The four above are on the other side of that split: a C64
    #: *destination*, a DOS *reader* and an Amiga *reader* reach the Convert
    #: dialog and nothing else.
    #:
    #: `goldbox.amiga`'s remaining one is `pod_to_neutral`'s, and it is a
    #: **warning** rather than a drop: a reader's warnings reach the pane
    #: through `losses` on any conversion to the C64. Nothing calls
    #: `pod_to_neutral` outside the tests today, so it reaches no player yet;
    #: the marker stays because wiring it up is what `#194 (Import and export
    #: a Pools of Darkness save between DOS and the Amiga)` is for.
    # `automap.actions` went 4 -> 3 when Fast Travel's failure line got the
    # wording Donald ruled on 2026-09-07 (`#306 (The Fast Travel button's own
    # disabled tooltip carries a memory address)`), which had been recorded
    # there and never applied.
    #
    # **`goldbox.c64_codec` went 8 to 1 on 2026-09-09, and none of the seven
    # was approved: the sentences themselves are gone.** All six of #399's
    # own per-character ceiling sentences (memorised spells, the spellbook,
    # the class array, both trait-slot lines and the inventory line) are
    # deleted, not reworded: Donald ruled, on the 950-character census #399's
    # own closing comment carries, that no real conversion reaches any of
    # these ceilings -- "I agree that we do not need the sentences." A short
    # comment citing #399 sits where each one was. The one line left is the
    # combat-icon figure, `#320`/`#355` territory and untouched here.
    #
    # `goldbox.dos` went 7 to 6 the same day, also with nothing approved:
    # `encumbrance`'s drop-list line moved to `WRITE_DERIVED` (#483, The
    # Convert flag could come off while two fields are still lost, because a
    # silencing list keeps them out of the count that decides it), which
    # `write` now consumes with `use()` rather than ever composing a report
    # line for -- so, like the four that came off the day before, it stopped
    # being a string a player, or even a developer reading `report.dropped`,
    # can reach.
    WAITING = {"goldbox.c64_codec": 1, "goldbox.amiga_codec": 1,
               "goldbox.dos_codec": 6,
               # 3 -> 2 on 2026-09-10: Donald approved the failure line for
               # a Fast Travel that cannot walk the party through a door
               # (`#493 (A Fast Travel that fails walking the party out
               # leaves them at the doorway and says they have not moved)`),
               # once its fix made "the party is back where it started" true.
               "automap.actions": 2}

    found: dict[str, list[str]] = {}
    for module in (c64_codec, amiga_codec, dos_codec, actions):
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
    assert convert.DESTINATION_LABELS == {
        "c64": "Commodore 64", "dos": "DOS", "amiga": "Amiga"}
    assert convert.SOURCE_FILTER == (
        "Saved games (*.d64 *.D64 *.adf *.ADF SAVGAM?.DAT SAVGAM?.PTY);;"
        "All files (*)")
    # Ruled on `#316 (Write the Amiga Pool of Radiance saved game from the
    # source save, so a converted party arrives where it was standing)`,
    # 2026-09-07 -- `LABEL_DISK` over `Amiga disk 2` and `Amiga data disk`,
    # `CONVERTED_AMIGA` over the `CONVERTED_DOS` shape.
    assert convert.LABEL_DISK == "Amiga game disk 2"
    assert convert.DISK_TITLE == "Choose Amiga game disk 2"
    assert convert.NO_DISK == "Choose Amiga game disk 2."
    assert convert.DISK_FILTER == "Amiga disks (*.adf *.ADF);;All files (*)"
    assert convert.CONVERTED_AMIGA == \
        "Wrote POOLSAVE.ADF to {folder}. Load game {slot}."


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


@needs_dos_saves
@needs_disks
def test_a_successful_rehearsal_still_calls_pane_text_for_its_own_logging(
        tmp_path, game_files, monkeypatch):
    """`_rehearse_and_report` still calls `dosimport.pane_text` on every
    successful rehearsal, even though nothing shows what it returns any
    more (2026-09-10) -- `pane_text`'s own `report.dropped` logging is the
    reason, and the only way `report.dropped` keeps reaching the debug log
    without duplicating that logic here.

    Fails before the fix: with the call removed, `calls` stays empty --
    seen red by deleting the `dosimport.pane_text(self.rehearsal.report)`
    line, then the fix put back.
    """
    source = str(_save_dir() / "SAVGAMA.DAT")
    calls = []
    real_pane_text = dosimport.pane_text

    def spy(report):
        calls.append(report)
        return real_pane_text(report)

    monkeypatch.setattr(dosimport, "pane_text", spy)
    dialog = convert.ConvertDialog(
        source, None, lambda game: game_files,
        destination="c64", folder=str(tmp_path))
    try:
        assert dialog.rehearsal is not None
        assert calls == [dialog.rehearsal.report]
    finally:
        dialog.close()


def test_a_name_too_long_for_dos_pops_a_warning_and_nothing_else_does(
        tmp_path, monkeypatch):
    """The one `C64SaveReport.losses` line Donald ruled a player is
    entitled to see -- a name DOS's own fifteen-character field could not
    hold whole -- reaches a modal; the other two kinds his ruling named as
    bugs rather than platform limits (#508, #509) reach the debug log
    instead, and `report.messages` and `report.dropped` reach neither.

    The dialog's own first `replan()`, inside `__init__`, is not
    `_interactive` (`ConvertDialog.__init__`'s own docstring note), so a
    second `replan()` is what a real player's next action would trigger --
    changing the destination combo, say -- and is what is called here to
    reach the point `_maybe_warn` actually pops anything.

    Fails before the fix: with `name_warnings` returning the whole
    `losses` list instead of the filtered one, `warned` below gains the
    spell-count line as a second entry -- seen red by reverting
    `editor.dosimport.name_warnings` to `return list(report.losses)`, then
    the fix put back.
    """
    folder = _synthetic_dos_folder(tmp_path, dos_layout.POOL_OF_RADIANCE)
    destination = tmp_path / "out"
    destination.mkdir()

    report = SimpleNamespace(
        messages=["Your party had not set out yet, so it starts at the "
                  "beginning of the story."],
        losses=["SOVELISS: Name 'Soveliss' is longer than the DOS 15 "
                "characters; truncated",
                "MIALEE: 8 spells memorised and Pool of Radiance has 6 "
                "slots; the rest dropped"],
        dropped=["quickfight: the C64 has no matching option"])

    def fake_rehearse(self, source, slot, options):
        return convert.Rehearsal(report, {"PORSAVEA.D64": b"\x00" * 4})

    monkeypatch.setattr(convert.DosToC64, "rehearse", fake_rehearse)

    warned = []
    monkeypatch.setattr(convert.QMessageBox, "warning",
                        lambda self_, title, text: warned.append((title, text)))
    critical = []
    monkeypatch.setattr(convert.QMessageBox, "critical",
                        lambda self_, title, text: critical.append((title, text)))

    game_files = dosimport.GameFiles(icon=b"", animate=b"")
    dialog = convert.ConvertDialog(
        str(folder), None, lambda game: game_files,
        destination="c64", folder=str(destination))
    try:
        assert dialog.rehearsal is not None
        #: The dialog's own construction ran non-interactively; this is
        #: the first `replan()` a real player's own next action would
        #: trigger.
        dialog.replan()
    finally:
        dialog.close()

    assert warned == [(convert.DIALOG_TITLE, report.losses[0])], warned
    assert critical == [], critical


# ---------------------------------------------------------------------------
# `#52 (File ▸ Import and File ▸ Export for every direction the library
# supports)`'s own comment of 2026-09-10: choosing a save in `From` used to
# pop `Choose where to write.` in a modal before the player had touched
# anything past that one field -- "you think all users using this tool made
# a mistake". `NO_FOLDER`, `NO_GAME_FOLDER`, `NO_DISK` and `NO_DISKS` are the
# four rows this names; none of them may open a modal any more, because
# `_settle_button` already leaves Convert disabled for exactly as long as
# each one holds. `CANNOT_CONVERT` is the opposite case named in the same
# comment -- a source the player actually chose and Wish cannot read -- and
# stays modal.
# ---------------------------------------------------------------------------

@needs_dos_saves
def test_no_folder_chosen_pops_no_modal(tmp_path):
    """The bug itself: a readable source, a destination that needs nothing
    else, and no folder chosen yet -- `_blocked` still names `NO_FOLDER` for
    the disabled button to explain, but `QMessageBox.critical` is never
    called for it.

    Fails before the fix: reverting `_maybe_warn` to fire on any
    `self._blocked` (put the file back per `.claude/rules/scratch.md`, then
    delete `__pycache__`) makes `critical` gain
    `(convert.DIALOG_TITLE, convert.NO_FOLDER)` the moment `_choose_folder`'s
    own `replan()` is *not* the one under test -- construction alone already
    reaches this, since `NO_FOLDER` is set on the dialog's own first
    `replan()` -- seen red, then the fix put back.
    """
    path = _por_c64_disk(tmp_path)
    critical = []

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(convert.QMessageBox, "critical",
                            lambda self_, title, text: critical.append((title, text)))
        # `_some_disks`, not `_no_disks`: this C64 source's own game files
        # are checked before the folder is (`_rehearse_and_report`'s own
        # order), and `_no_disks` here would reach `NO_DISKS` instead of the
        # `NO_FOLDER` this test is about (`#482`).
        dialog = convert.ConvertDialog(str(path), None, _some_disks,
                                       destination="dos",
                                       game=str(_game_dir()))
        try:
            # Re-run interactively -- the dialog's own first `replan()` is
            # not `_interactive`, so this is what a real player's next
            # action (choosing this same folder by hand) would trigger.
            dialog._interactive = True
            dialog.replan()
            assert dialog._blocked == (convert.DIALOG_TITLE, convert.NO_FOLDER)
            ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
            assert not ok.isEnabled()
        finally:
            dialog.close()

    assert critical == [], critical


def test_no_game_folder_chosen_pops_no_modal(tmp_path):
    """The twin of `test_no_folder_chosen_pops_no_modal` for `NO_GAME_FOLDER`
    -- a DOS destination with everything else named but the game folder.

    Fails before the fix the same way, on `(convert.DIALOG_TITLE,
    convert.NO_GAME_FOLDER)` instead."""
    path = _por_c64_disk(tmp_path)
    critical = []

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(convert.QMessageBox, "critical",
                            lambda self_, title, text: critical.append((title, text)))
        dialog = convert.ConvertDialog(str(path), None, _no_disks,
                                       destination="dos",
                                       folder=str(tmp_path / "out"))
        try:
            dialog._interactive = True
            dialog.replan()
            assert dialog._blocked == (convert.DIALOG_TITLE,
                                       convert.NO_GAME_FOLDER)
            ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
            assert not ok.isEnabled()
        finally:
            dialog.close()

    assert critical == [], critical


def test_no_disk_chosen_pops_no_modal(tmp_path):
    """The twin for `NO_DISK` -- an Amiga destination with no disk 2
    chosen yet."""
    path = _por_c64_disk(tmp_path)
    critical = []

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(convert.QMessageBox, "critical",
                            lambda self_, title, text: critical.append((title, text)))
        dialog = convert.ConvertDialog(str(path), None, _some_disks,
                                       destination="amiga",
                                       folder=str(tmp_path / "out"))
        try:
            dialog._interactive = True
            dialog.replan()
            assert dialog._blocked == (convert.DIALOG_TITLE, convert.NO_DISK)
            ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
            assert not ok.isEnabled()
        finally:
            dialog.close()

    assert critical == [], critical


@needs_dos_saves
def test_no_disks_in_preferences_pops_no_modal(tmp_path):
    """The twin for `NO_DISKS` -- `#482`'s own refusal, with no game disks
    for the destination title, popped a modal named `Game disks not found`
    on every field change before this fix."""
    path = _por_c64_disk(tmp_path)
    critical = []

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(convert.QMessageBox, "critical",
                            lambda self_, title, text: critical.append((title, text)))
        dialog = convert.ConvertDialog(str(path), None, _no_disks,
                                       destination="dos",
                                       game=str(_game_dir()),
                                       folder=str(tmp_path / "out"))
        try:
            dialog._interactive = True
            dialog.replan()
            assert dialog._blocked == (convert.NO_DISKS_TITLE, convert.NO_DISKS)
            ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
            assert not ok.isEnabled()
        finally:
            dialog.close()

    assert critical == [], critical


def test_an_unreadable_source_still_pops_a_modal(tmp_path):
    """The one case that stays modal: the player chose a file and Wish
    cannot read it, which is a real refusal of something they actually
    asked for -- not a row they have simply not filled in yet.

    Fails before the fix existed at all -- this is the behaviour `_blocked`
    already had (`test_a_pools_of_darkness_folder_lists_nothing` pins the
    same refusal without a modal spy); checked here so the modal-suppression
    change above cannot be read as covering this case too."""
    unreadable = tmp_path / "not-a-save.d64"
    unreadable.write_bytes(b"\x00" * 4)
    critical = []

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(convert.QMessageBox, "critical",
                            lambda self_, title, text: critical.append((title, text)))
        dialog = convert.ConvertDialog("", None, _no_disks)
        try:
            dialog._source_path = str(unreadable)
            dialog.ui.convert_source.setText(str(unreadable))
            dialog._interactive = True
            dialog.replan()
            assert dialog._blocked == (convert.DIALOG_TITLE,
                                       convert.CANNOT_CONVERT)
        finally:
            dialog.close()

    assert critical == [(convert.DIALOG_TITLE, convert.CANNOT_CONVERT)], critical


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


def test_a_disk_with_one_slot_shows_no_slot_combo(amiga_adf):
    """The shipped disk holds slot A alone -- the combo stays hidden and
    `Source.detect` still takes it silently, exactly as before this combo
    existed (`#372`'s brief: silently taking the one slot is unchanged).

    The combo sits on the `From` row rather than owning one of its own
    since `#413 (The Convert window changes shape depending on which
    platforms you are converting between)`, so hiding it is the widget's
    own visibility, not a form row's -- the `From` row itself is always
    visible, with or without a slot to choose."""
    source = convert.Source.detect(amiga_adf)
    assert source.available_slots == ["A"]

    dialog = convert.ConvertDialog(str(amiga_adf), None, _no_disks)
    try:
        assert dialog.source.slot == "A"
        assert dialog.ui.form.isRowVisible(dialog.ui.label_source)
        # `isVisibleTo`, not `isVisible`: this dialog is never `.show()`n in
        # a test, and a widget's `isVisible()` answers `False` for that
        # reason alone, whatever `setVisible` was last called with.
        assert not dialog.ui.convert_slot.isVisibleTo(dialog)
    finally:
        dialog.close()


def test_a_disk_with_three_slots_offers_a_slot_combo(tmp_path):
    """The regression `#372 (An Amiga disk with more than one saved game
    converts its first slot, whichever one the player meant)` describes: a
    disk naming more than one slot gets a combo rather than being reduced to
    its first -- on the `From` row, beside `Choose…`
    (`#413`'s comment of 2026-09-09)."""
    path = _outdoor_amiga_disk(tmp_path)
    dialog = convert.ConvertDialog(str(path), None, _no_disks)
    try:
        assert dialog.source.available_slots == ["A", "B", "C"]
        assert dialog.ui.convert_slot.isVisibleTo(dialog)
        items = [dialog.ui.convert_slot.itemData(i)
                for i in range(dialog.ui.convert_slot.count())]
        assert items == ["A", "B", "C"]
        assert dialog.ui.convert_slot.currentText() == \
            convert.SLOT_ITEM.format(slot="A")
        # Opening the dialog picks nothing for the player -- the combo
        # starts on the first slot, the same one `Source.detect` always
        # took before this combo existed, so a disk with one game keeps
        # behaving the same way it always has.
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


def test_the_report_pane_carries_no_label_and_no_box(tmp_path):
    """Donald asked for the report pane's `Convert Log` label removed on
    2026-09-10, having found it still there: *"I still see the Convert
    Log. I specifically asked for that to be removed."* -- and then, on
    being shown a screenshot with the box it headed still standing under
    it: *"the box under it has to be removed, too. That was the entire
    point."*

    Fails before either fix: `hasattr(dialog.ui, "label_report")` was true
    with `Convert Log` as its text before the first, and
    `hasattr(dialog.ui, "convert_report")` was true before the second --
    both seen red, then put back.
    """
    dialog = convert.ConvertDialog("", None, _no_disks)
    try:
        assert not hasattr(dialog.ui, "label_report")
        assert not hasattr(dialog.ui, "convert_report")
    finally:
        dialog.close()


# ---------------------------------------------------------------------------
# C64 -> Amiga and DOS -> Amiga: one POOLSAVE.ADF, no template
# (`#316 (Write the Amiga Pool of Radiance saved game from the source save,
# so a converted party arrives where it was standing)`, `#36 (Write an
# Amiga disk image, not just the character files)`)
# ---------------------------------------------------------------------------

def test_a_curse_c64_source_is_offered_no_amiga_row():
    """`goldbox.amiga.WRITES` holds Pool of Radiance alone -- no Amiga
    saved-game writer exists yet for Curse of the Azure Bonds or Secret of
    the Silver Blades (`#359`'s step 6) -- so a Curse source is offered only
    the registered C64 -> DOS row, the same way
    `test_destinations_for_a_curse_source_answers_the_curse_c64_direction`
    already proves for the reverse direction."""
    from goldbox import amiga

    assert amiga.WRITES == (dos_layout.POOL_OF_RADIANCE,)

    curse_source = convert.Source(port="c64", title=games.CURSE_OF_THE_AZURE_BONDS,
                                  path=pathlib.Path("."))
    directions = convert.destinations_for(curse_source)
    assert [type(d) for d in directions] == [convert.C64ToDos]


def test_the_files_row_relabels_itself_for_an_amiga_destination(tmp_path):
    """The twin of
    `test_the_game_files_row_is_shown_for_every_destination_with_its_own_label`,
    now that a C64 source offers an Amiga destination too -- one row, same
    place, relabelled. `NO_DISK` is what the pane says with nothing chosen
    yet, exactly as `NO_GAME_FOLDER` does for the DOS destination."""
    path = _por_c64_disk(tmp_path)

    dialog = convert.ConvertDialog(str(path), None, _no_disks,
                                   destination="amiga")
    try:
        assert dialog.direction.destination_port == "amiga"
        assert dialog.ui.form.isRowVisible(dialog.ui.files_row)
        assert dialog.ui.label_files.text() == convert.LABEL_DISK
        assert dialog._blocked == (convert.DIALOG_TITLE, convert.NO_DISK)
    finally:
        dialog.close()

    dialog2 = convert.ConvertDialog(str(path), None, _no_disks,
                                    destination="dos")
    try:
        assert dialog2.direction.destination_port == "dos"
        assert dialog2.ui.form.isRowVisible(dialog2.ui.files_row)
        assert dialog2.ui.label_files.text() == convert.LABEL_GAME
    finally:
        dialog2.close()


def test_the_dialog_writes_an_adf_when_a_disk_and_folder_are_given(tmp_path):
    """Driven the way `EditorBinding.convert` drives it -- every row
    pre-filled, no picker -- so this proves the dialog's own
    `_rehearse_and_report` amiga branch reaches Convert, not only that
    `Direction.rehearse` works when called directly the way the transfer
    tests below call it. Repeats `fresh_folder` then `Direction.write` by
    hand, at the dialog level, rather than through `EditorBinding.convert` --
    `test_window_convert_writes_an_amiga_disk_and_reports_the_load_letter`
    below is the twin that drives the whole path including `disk=` and the
    `CONVERTED_AMIGA` status line.

    `_some_disks`, not `_no_disks`: a C64 source converting to Amiga now
    refuses with no source disks (`#482`), and this test is about the write
    path rather than the combat icon.
    """
    from test_toamigapor import _c64_specimen

    from goldbox import amiga

    disk2 = _por_amiga_disk_2(tmp_path)
    c64_path = _c64_specimen("por-party-twin-pair")
    destination = tmp_path / "out"
    destination.mkdir()

    dialog = convert.ConvertDialog(str(c64_path), None, _some_disks,
                                   destination="amiga", disk=str(disk2),
                                   folder=str(destination))
    try:
        assert dialog.rehearsal is not None
        assert convert.POOLSAVE_FILENAME in dialog.rehearsal.files
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        assert ok.isEnabled()

        fresh = convert.fresh_folder(destination)
        fresh.mkdir()
        written = dialog.direction.write(dialog.rehearsal, fresh)
        assert [p.name for p in written] == [convert.POOLSAVE_FILENAME]
        # Opens clean, or `AmigaDiskError` raises and the test fails.
        amiga.AmigaDisk.open(str(fresh / convert.POOLSAVE_FILENAME))
    finally:
        dialog.close()


def test_window_convert_writes_an_amiga_disk_and_reports_the_load_letter(
        tmp_path, monkeypatch):
    """`EditorBinding.convert`'s `disk=` argument and its `CONVERTED_AMIGA`
    status line, end to end -- the two pieces `#36 (Write an Amiga disk
    image, not just the character files)`'s 2026-09-07 comment left for this
    session, because `editor/window.py` was another agent's file that
    night. Drives `File ▸ Convert…` exactly the way a player would with
    every row already filled in (`disk=` is the twin of `game=`), so this
    proves the wiring the dialog-level test above cannot: that
    `EditorBinding.convert` itself knows to write into a fresh folder, name
    it `POOLSAVE.ADF`, and report the approved sentence rather than falling
    through to `CONVERTED_DOS` or trying to `self.load()` it as a C64
    save.

    `window.game_files_for` is patched to answer something for every title:
    with no disks folder set on this `EditorBinding`, it would otherwise
    return `None` for the specimen's own title and the conversion would now
    refuse (`#482`) -- this test is about `EditorBinding.convert`'s own
    wiring, not about the combat icon."""
    from test_toamigapor import _c64_specimen

    from goldbox import amiga

    disk2 = _por_amiga_disk_2(tmp_path)
    c64_path = _c64_specimen("por-party-twin-pair")
    window = EditorBinding(_make_root())
    destination = tmp_path / "out"
    destination.mkdir()

    monkeypatch.setattr(convert.ConvertDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(window, "game_files_for", _some_disks)
    try:
        note = window.convert(source=str(c64_path), destination="amiga",
                              disk=str(disk2), folder=str(destination))
    finally:
        window.close()

    today = datetime.date.today().isoformat()
    fresh = destination / f"wish-{today}"
    written = fresh / convert.POOLSAVE_FILENAME
    assert list(fresh.iterdir()) == [written]
    assert note == convert.CONVERTED_AMIGA.format(slot="A", folder=fresh)
    # Opens clean and the slot is readable, or this raises.
    disk = amiga.AmigaDisk.open(str(written))
    assert disk.read_file("/save") is not None


def test_window_convert_reports_the_amiga_status_line_with_no_real_disk(
        tmp_path, monkeypatch):
    """CI-safe twin of the test above, with no specimen or Amiga disk 2:
    proves `EditorBinding.convert`'s own amiga branch -- the fresh folder,
    the one `POOLSAVE.ADF`, and `CONVERTED_AMIGA` rather than `CONVERTED_DOS`
    or the C64 `self.load()` branch -- on a hand-built
    `_synthetic_amiga_rehearsal()`, the same rehearsal
    `test_write_puts_one_adf_in_its_own_folder` proves `Direction.write` with."""
    from goldbox import dos_layout

    window = EditorBinding(_make_root())
    destination = tmp_path / "out"
    destination.mkdir()

    rehearsal = _synthetic_amiga_rehearsal()
    direction = convert.C64ToAmiga(dos_layout.POOL_OF_RADIANCE)

    class _FakeDialog:
        def __init__(self, *args, **kwargs):
            self.direction = direction
            self.rehearsal = rehearsal
            self.slot = "A"
            self.folder = str(destination)

        def exec(self):
            return QDialog.DialogCode.Accepted

        def close(self):
            pass

    monkeypatch.setattr(convert, "ConvertDialog", _FakeDialog)
    try:
        note = window.convert(source="ignored", destination="amiga",
                              disk="ignored", folder=str(destination))
    finally:
        window.close()

    today = datetime.date.today().isoformat()
    fresh = destination / f"wish-{today}"
    written = fresh / convert.POOLSAVE_FILENAME
    assert note == convert.CONVERTED_AMIGA.format(slot="A", folder=fresh)
    assert written.read_bytes() == b"not a real disk"
    assert list(fresh.iterdir()) == [written]


def test_a_successful_amiga_conversion_pops_the_confirmation_alongside_the_status_line(
        tmp_path, monkeypatch):
    """`#52`'s `CONVERT_SUCCESS` box, on the Amiga branch, alongside --
    never instead of -- `CONVERTED_AMIGA`'s own status line: that line
    still carries the load-game letter Donald's new sentence does not name,
    so both fire on the one write. CI-safe, the same
    `_synthetic_amiga_rehearsal()` plumbing as the status-line test above."""
    from goldbox import dos_layout

    window = EditorBinding(_make_root())
    destination = tmp_path / "out"
    destination.mkdir()

    rehearsal = _synthetic_amiga_rehearsal()
    direction = convert.C64ToAmiga(dos_layout.POOL_OF_RADIANCE)

    class _FakeDialog:
        def __init__(self, *args, **kwargs):
            self.direction = direction
            self.rehearsal = rehearsal
            self.slot = "A"
            self.folder = str(destination)

        def exec(self):
            return QDialog.DialogCode.Accepted

        def close(self):
            pass

    shown = []
    monkeypatch.setattr(convert, "ConvertDialog", _FakeDialog)
    monkeypatch.setattr(
        convert.QMessageBox, "information",
        lambda parent, title, text: shown.append((title, text)))
    try:
        note = window.convert(source="ignored", destination="amiga",
                              disk="ignored", folder=str(destination))
    finally:
        window.close()

    today = datetime.date.today().isoformat()
    fresh = destination / f"wish-{today}"
    assert note == convert.CONVERTED_AMIGA.format(slot="A", folder=fresh)
    assert shown == [(convert.DIALOG_TITLE,
                     convert.CONVERT_SUCCESS.format(folder=fresh))]


def test_a_successful_dos_conversion_pops_the_confirmation_alongside_the_status_line(
        tmp_path, monkeypatch):
    """`#52`'s `CONVERT_SUCCESS` box, on the DOS branch, alongside --
    never instead of -- `CONVERTED_DOS`'s own status line and the slot it
    names. CI-safe: a hand-built direction that never touches real game
    data, the same shape as the Amiga test above."""
    window = EditorBinding(_make_root())
    destination = tmp_path / "out"
    destination.mkdir()

    class _FakeDosDirection:
        destination_port = "dos"

        def write(self, rehearsal, folder):
            path = pathlib.Path(folder) / "SAVGAMA.DAT"
            path.write_bytes(b"not a real save")
            return [path]

    class _FakeDialog:
        def __init__(self, *args, **kwargs):
            self.direction = _FakeDosDirection()
            self.rehearsal = object()
            self.slot = "A"
            self.folder = str(destination)

        def exec(self):
            return QDialog.DialogCode.Accepted

        def close(self):
            pass

    shown = []
    monkeypatch.setattr(convert, "ConvertDialog", _FakeDialog)
    monkeypatch.setattr(
        convert.QMessageBox, "information",
        lambda parent, title, text: shown.append((title, text)))
    try:
        note = window.convert(source="ignored", destination="dos",
                              folder=str(destination))
    finally:
        window.close()

    today = datetime.date.today().isoformat()
    fresh = destination / f"wish-{today}"
    assert note == convert.CONVERTED_DOS.format(slot="A", folder=fresh)
    assert shown == [(convert.DIALOG_TITLE,
                     convert.CONVERT_SUCCESS.format(folder=fresh))]


def test_a_refused_conversion_never_pops_the_success_confirmation(
        tmp_path, monkeypatch):
    """A write that fails still shows only its own refusal
    (`CANNOT_CONVERT`, via `dialog.refuse`) -- never `CONVERT_SUCCESS`
    alongside it. CI-safe: a direction whose `write` always raises, the
    same retry shape `test_a_writer_that_fails_partway_leaves_no_folder_
    behind` proves against a real DOS write."""
    window = EditorBinding(_make_root())
    destination = tmp_path / "out"
    destination.mkdir()

    class _FailingDirection:
        destination_port = "dos"

        def write(self, rehearsal, folder):
            pathlib.Path(folder).joinpath("partial.dat").write_bytes(b"x")
            raise OSError("disk full")

    dialogs = []

    class _FakeDialog:
        def __init__(self, *args, **kwargs):
            self.direction = _FailingDirection()
            self.rehearsal = object()
            self.slot = "A"
            self.folder = str(destination)
            self.refusals = []
            self._answers = iter([QDialog.DialogCode.Accepted,
                                 QDialog.DialogCode.Rejected])
            dialogs.append(self)

        def exec(self):
            return next(self._answers)

        def refuse(self, text):
            self.refusals.append(text)

        def close(self):
            pass

    shown = []
    monkeypatch.setattr(convert, "ConvertDialog", _FakeDialog)
    monkeypatch.setattr(
        convert.QMessageBox, "information",
        lambda *a, **k: shown.append(a))
    try:
        outcome = window.convert(source="ignored", destination="dos",
                                folder=str(destination))
    finally:
        window.close()

    assert outcome == "cancelled"
    assert dialogs[0].refusals == [convert.CANNOT_CONVERT]
    assert shown == []


def _synthetic_amiga_rehearsal():
    """An `AmigaWriteRehearsal` with no real game data behind it, on a
    `synthetic_savegame()` (`tests/test_amiga.py`), so
    `C64ToAmiga.write`/`DosToAmiga.write`'s own file-placement shape can be
    proven on CI -- `write` reads only `rehearsal.files`, never the disk
    that built it, so nothing here needs an Amiga disk or a specimen."""
    from test_amiga import synthetic_savegame

    return convert.AmigaWriteRehearsal(
        convert.neutral.Report(),
        {convert.POOLSAVE_FILENAME: b"not a real disk"},
        party=[], state=None, slot="A", savegame=synthetic_savegame())


def test_a_rehearsal_writes_nothing(tmp_path):
    """Building a rehearsal by hand touches no disk -- the same guarantee
    `test_c64_to_dos_direction_rehearses_with_no_write` proves by calling
    the real `rehearse`, which this direction cannot do without a player's
    own Amiga disk 2."""
    rehearsal = _synthetic_amiga_rehearsal()
    assert not list(tmp_path.iterdir())
    assert rehearsal.files[convert.POOLSAVE_FILENAME] == b"not a real disk"


def test_write_puts_one_adf_in_its_own_folder(tmp_path):
    """`write` puts exactly one `POOLSAVE.ADF` in the folder it is given and
    touches nothing else -- the same shape
    `test_c64_to_dos_direction_writes_only_into_its_own_folder` proves for
    the DOS destination. One rehearsal proves both directions, since
    `C64ToAmiga.write` and `DosToAmiga.write` are the same few lines."""
    rehearsal = _synthetic_amiga_rehearsal()
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("untouched")

    for direction in (convert.C64ToAmiga(dos_layout.POOL_OF_RADIANCE),
                      convert.DosToAmiga(dos_layout.POOL_OF_RADIANCE)):
        destination = tmp_path / "out" / type(direction).__name__
        written = direction.write(rehearsal, destination)
        assert [p.name for p in written] == [convert.POOLSAVE_FILENAME]
        assert written[0].read_bytes() == b"not a real disk"
        assert list(destination.iterdir()) == [destination / convert.POOLSAVE_FILENAME]

    assert outside.read_text() == "untouched"


def _por_amiga_disk_2(tmp_path):
    """Amiga Pool of Radiance disk 2, or a skip -- `test_toamigapor.py`'s
    own finder, shared here so the two suites cannot pick different disks."""
    from test_toamigapor import _por_disk_2

    return _por_disk_2(tmp_path)


def test_c64_to_amiga_direction_is_the_transfer_test(tmp_path):
    """Every file on the `.adf` this direction writes equals, byte for
    byte, the same file on a disk built by calling `goldbox.dos.c64_party`,
    `goldbox.amiga.por_state_from_c64`, `goldbox.amiga.new_por_savegame` and
    `goldbox.amiga.make_por_save_disk` by hand -- the same argument
    `test_dos_to_c64_direction_is_the_transfer_test` makes for the DOS row.

    **File content, not the disk's raw bytes**: `goldbox.amiga_adf.
    AmigaDisk.write_file` stamps each header block with the wall-clock time
    it was called, so two builds a tick apart differ in their timestamp and
    checksum bytes even from identical input -- measured directly, twelve
    bytes of 901,120 move between two back-to-back `make_por_save_disk`
    calls on the same party. `read_file` returns only the data payload,
    which carries none of that.

    `CHRDATA1` is BRUTUS and `CHRDATA6` is MALCYON, the C64's own marching
    order (`#385 (A C64 party converted to an Amiga disk marches in the
    reverse of its C64 order)`, closed before this row was built): this
    direction calls `dos.c64_party` exactly as `tools/toamigapor.py` does
    since that fix, so the two cannot disagree.
    """
    from test_toamigapor import _c64_specimen

    from goldbox import amiga

    disk2 = _por_amiga_disk_2(tmp_path)
    c64_path = _c64_specimen("por-party-twin-pair")

    source = convert.Source.detect(c64_path)
    direction = next(d for d in convert.destinations_for(source)
                     if d.destination_port == "amiga")
    assert type(direction) is convert.C64ToAmiga

    rehearsal = direction.rehearse(source, "A", disk2)
    out_dir = tmp_path / "out"
    written = direction.write(rehearsal, out_dir)
    assert [p.name for p in written] == [convert.POOLSAVE_FILENAME]

    ecl = amiga.AmigaDisk.open(str(disk2)).read_file("/ecl.dax")
    party, _icons = dos.c64_party(source.save0, source.save1,
                                  game=games.by_key(dos_layout.POOL_OF_RADIANCE.key))
    state = amiga.por_state_from_c64(source.save0, str(source.path))
    savegame, report = amiga.new_por_savegame(
        state, "A", len(party), ecl,
        portraits=any("portrait_head" in c for c in party))
    reference = amiga.make_por_save_disk("A", party, savegame)
    assert report.unwritten == []

    out_disk = amiga.AmigaDisk.open(str(out_dir / convert.POOLSAVE_FILENAME))
    written_paths = sorted(p for p, e in out_disk.walk() if not e.is_dir)
    reference_paths = sorted(p for p, e in reference.walk() if not e.is_dir)
    assert written_paths == reference_paths
    for path in written_paths:
        assert out_disk.read_file(path) == reference.read_file(path), path

    slot_party, _savgam = amiga.read_por_slot(out_disk, "A")
    names = [c.name for c in slot_party]
    assert names[0] == "BRUTUS"
    assert names[-1] == "MALCYON"


@pytest.mark.skipif(not gamedata.have_specimen("por-item-granted"),
                    reason="needs WISH-SPEC-por-item-granted")
def test_dos_to_amiga_direction_is_the_transfer_test(tmp_path):
    """The DOS-sourced twin: the disk's slot list names the source's own
    letter -- D, not A -- and the built saved game carries THRENDER GRONE's
    own square and clock rather than SSI's, `#316`'s whole point at the
    level a player would notice it."""
    from goldbox import amiga

    disk2 = _por_amiga_disk_2(tmp_path)
    folder = gamedata.specimen("por-item-granted")

    source = convert.Source.detect(folder / "SAVGAMD.DAT")
    assert source.port == "dos" and source.slot == "D"
    direction = next(d for d in convert.destinations_for(source)
                     if d.destination_port == "amiga")
    assert type(direction) is convert.DosToAmiga

    rehearsal = direction.rehearse(source, "A", disk2)
    out_dir = tmp_path / "out"
    direction.write(rehearsal, out_dir)

    out_disk = amiga.AmigaDisk.open(str(out_dir / convert.POOLSAVE_FILENAME))
    assert amiga.read_slot_list(out_disk, drawer="") == ["D"]

    savgam_path = folder / "SAVGAMD.DAT"
    state = amiga.por_state_from_dos(savgam_path.read_bytes(), str(savgam_path))
    built = out_disk.read_file("/savgamD.dat")
    assert (built[amiga.POR_POS_X], built[amiga.POR_POS_Y],
           built[amiga.POR_POS_FACING]) == (state.x, state.y, state.facing * 2)


# ---------------------------------------------------------------------------
# The four-row form (#413, "The Convert window changes shape depending on
# which platforms you are converting between") -- the same four rows, in the
# same places, for every one of the six directions.
# ---------------------------------------------------------------------------

def _four_rows_in_order(dialog):
    """`From`, `To`, the game-files row, `Write to` -- in that order, and
    none of the four hidden. `QFormLayout.itemAt` reads the row structure
    itself rather than the dialog's own widget list, so a row moved back
    into existence by accident would still be caught even if nothing else
    here happened to touch it."""
    form = dialog.ui.form
    assert form.rowCount() == 4
    names = [form.itemAt(i, form.ItemRole.LabelRole).widget().objectName()
            for i in range(4)]
    assert names == ["label_source", "label_to", "label_files",
                     "label_folder"]
    for name in names:
        assert form.isRowVisible(getattr(dialog.ui, name)), name


def test_the_form_holds_four_rows_for_every_dos_or_c64_destination(tmp_path):
    """The four directions a DOS or a C64 source offers -- no real game
    disks needed, so this covers most of the six unconditionally. The row
    that used to appear and vanish (`_settle_game_row`/`_settle_disk_row`,
    before this issue) is the third one here, in the same place regardless
    of which of the three platforms is the destination."""
    dos_folder = _synthetic_dos_folder(tmp_path, dos_layout.POOL_OF_RADIANCE)
    c64_path = _por_c64_disk(tmp_path)
    cases = [
        (dos_folder / "SAVGAMA.DAT", "c64", convert.LABEL_C64),
        (dos_folder / "SAVGAMA.DAT", "amiga", convert.LABEL_DISK),
        (c64_path, "dos", convert.LABEL_GAME),
        (c64_path, "amiga", convert.LABEL_DISK),
    ]
    for source_path, destination, label in cases:
        dialog = convert.ConvertDialog(str(source_path), None, _no_disks,
                                       destination=destination)
        try:
            assert dialog.direction.destination_port == destination, \
                (source_path, destination)
            _four_rows_in_order(dialog)
            assert dialog.ui.label_files.text() == label, destination
        finally:
            dialog.close()


def test_the_form_holds_four_rows_for_an_amiga_source_too(amiga_adf):
    """The two remaining directions, an Amiga `.adf` converting to the
    Commodore 64 or to DOS -- needs the player's own Amiga disks to detect
    the source at all (`amiga_adf`'s own fixture), so this is the other
    half of `test_the_form_holds_four_rows_for_every_dos_or_c64_destination`
    rather than folded into it."""
    for destination, label in (("c64", convert.LABEL_C64),
                               ("dos", convert.LABEL_GAME)):
        dialog = convert.ConvertDialog(str(amiga_adf), None, _no_disks,
                                       destination=destination)
        try:
            assert dialog.direction.destination_port == destination
            _four_rows_in_order(dialog)
            assert dialog.ui.label_files.text() == label, destination
        finally:
            dialog.close()


def test_an_amiga_source_with_several_slots_shows_the_slot_combo_and_the_dos_folder_together(
        tmp_path):
    """The case that settled where the `Slot` combo goes (`#413`'s comment
    of 2026-09-09): an Amiga source with more than one saved game,
    converting to DOS, needs the slot *and* the DOS game folder at once.
    Both fit because the combo rides on the `From` row instead of taking
    the third-row position the DOS folder needs -- under the rejected
    design the window would have grown to five rows here, which is the
    shape `#413` exists to remove."""
    path = _outdoor_amiga_disk(tmp_path)
    dialog = convert.ConvertDialog(str(path), None, _no_disks,
                                   destination="dos")
    try:
        assert dialog.direction.destination_port == "dos"
        assert dialog.source.available_slots == ["A", "B", "C"]
        assert dialog.ui.convert_slot.isVisibleTo(dialog)
        assert dialog.ui.label_files.text() == convert.LABEL_GAME
        _four_rows_in_order(dialog)
    finally:
        dialog.close()


def test_the_c64_row_is_prefilled_from_preferences_and_editing_it_holds_only_for_this_conversion(
        tmp_path, monkeypatch):
    """Donald, 2026-09-09: *"How about you include a file input, but
    autofill it with whatever is in the preferences,"* and, on what
    editing the row does to that setting: *"Just this conversion.
    Preferences is untouched."*

    `preferences` stands in for `Settings.game_folders` -- a simple dict,
    since this module must never import `wish.preferences`, and the
    injected `game_folder` callable is the only way its value reaches the
    dialog, the same way `game_files` already stands in for the rest of
    Preferences' own search."""
    prefs_folder = tmp_path / "prefs-folder"
    prefs_folder.mkdir()
    preferences = {games.POOL_OF_RADIANCE.key: str(prefs_folder)}

    def game_folder(game):
        return preferences.get(game.key)

    folder = _synthetic_dos_folder(tmp_path, dos_layout.POOL_OF_RADIANCE)
    dialog = convert.ConvertDialog(
        str(folder / "SAVGAMA.DAT"), None, _no_disks,
        destination="c64", game_folder=game_folder)
    try:
        assert dialog.direction.destination_port == "c64"
        assert dialog.ui.convert_files.text() == str(prefs_folder)

        chosen = tmp_path / "player-chosen-folder"
        chosen.mkdir()
        monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                            lambda *args, **kwargs: str(chosen))
        dialog._choose_files()

        assert dialog.ui.convert_files.text() == str(chosen)
        # Preferences itself never moved -- nothing in this module can
        # write to it, and this is the behavioural proof rather than an
        # inspection of the source for an import that is not there.
        assert preferences[games.POOL_OF_RADIANCE.key] == str(prefs_folder)

        # A later `replan()` -- what changing the `To` combo and changing
        # it back would trigger -- does not overwrite the player's own
        # choice with Preferences' answer again.
        dialog.replan()
        assert dialog.ui.convert_files.text() == str(chosen)
    finally:
        dialog.close()


def test_window_convert_hands_the_dialog_its_own_preferences_folder():
    """`EditorBinding.convert` passes `game_folder=`, so the C64 row is
    prefilled from Preferences in the running editor.

    `#413 (The Convert window changes shape depending on which platforms you
    are converting between)` built the prefilled row and its dialog-level
    tests pass a stand-in, so all of them went green while
    `EditorBinding.convert` passed nothing at all -- a player with a C64
    folder set still saw a blank row, which is the feature the ticket was
    for. Caught by the review of `1c3bfa1`.

    This asserts the wiring rather than the behaviour, because the behaviour
    is already covered: what can rot is the one argument at the call site.
    `_own_disk_folder` is the right function and reads only
    `Settings.game_folders`, not `automap.paths.resolve_disks`' full
    precedence, which would start a search of the machine when no folder is
    set for either title.
    """
    import inspect

    from editor import window as window_mod

    source = inspect.getsource(window_mod.EditorBinding.convert)
    assert "game_folder=self._own_disk_folder" in source, (
        "EditorBinding.convert must pass game_folder= or the C64 row is "
        "blank however the player has set Preferences")

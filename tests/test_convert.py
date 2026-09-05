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
from test_dossave import _save_dir, needs_dos_saves

from editor import convert, dosimport
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

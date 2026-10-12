from __future__ import annotations

"""`editor.convert`'s registry: which directions the library can write whole.

Step 1 of `#52 (File ▸ Import and File ▸ Export for every direction the
library supports)`'s plan (`cited/reports/52-plan.md`, on the issue's own
comments): no window, no menu, no template.

**Every test here is a round trip.** It proves `editor.convert` wraps
`goldbox.dos_codec` the way `editor/dosimport.py`, `tools/dos/dosdisk.py` and
`tools/dos/dosnewsave.py` already do, byte for byte -- not a fact about the game,
so the input's provenance does not matter to the assertion
(`.claude/rules/testing.md`, "A specimen is only evidence if we know who
wrote it"). `tests/fixtures/savedgame0.bin` / `savedgame1.bin` are Donald's
own played saves, on the repository's allowlist; the DOS side reads
`tests/dos/test_dossave.py`'s `_save_dir()`, which needs `$FR_ARCHIVES` and skips
without it -- the DOS → C64 direction also needs the player's own
`POOL*.D64` game disks and skips without those too.

The Curse of the Azure Bonds transfer test reads
`WISH-SPEC-curse-131-four-items-readied`, the DOS session
`tests/convert/test_curseconvert.py`'s `_dos_save()` already reads
for the work on converting a Curse of the Azure Bonds DOS save into a C64 one -- the FR_ARCHIVES default Curse save this
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
from gamedata import disk_dir
from PyQt6.QtWidgets import QApplication
from support.convertparty import _fixture_payloads, _six_icon_party
from support.dossave import _save_dir, needs_dos_saves

from editor import convert, dosimport, saveplan
from editor.window import EditorBinding
from goldbox import c64_port, dos_codec, dos_port, dos_savegame, titles

#: The played DOS Curse session this reads, and the slot in it.  It was
#: `curse/H-square-5-13` (scratch, deleted), which is gone from this machine --
#: scratch has been lost twice -- so this follows
#: `test_curseconvert.py`'s `_dos_save()` onto the specimen tree, where
#: `#131`'s own session stands in Tilverton with four items readied.
CURSE_SPECIMEN, CURSE_SLOT = "curse-131-four-items-readied", "I"

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


def _curse_save_dir() -> pathlib.Path | None:
    """The DOS Curse session in the specimen tree, or `None`."""
    if not gamedata.have_specimen(CURSE_SPECIMEN):
        return None
    return gamedata.specimen(CURSE_SPECIMEN)


needs_curse_dos_save = pytest.mark.skipif(
    not gamedata.have_specimen(CURSE_SPECIMEN),
    reason=f"needs specimen WISH-SPEC-{CURSE_SPECIMEN}; set $WISH_SPECIMENS "
           f"or see tools/registry/specimens.py")


def _game_dir() -> pathlib.Path:
    """The DOS game directory: the save directory's parent, `test_doswriter.py`'s
    helper, repeated here because a subagent's files may not import another
    test module's private helpers across `#52`'s lane."""
    return _save_dir().parent


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
    """A round trip: `detect` reads back what `dos_codec.save_disk` wrote, the way
    `editor/exports.py`'s `Source.from_disk` already did before this moved
    the class here."""
    save0, save1 = _fixture_payloads()
    disk = dos_codec.save_disk(save0, save1)
    path = tmp_path / "PORSAVE.D64"
    path.write_bytes(disk.to_bytes())

    source = convert.Source.detect(path)

    assert source.port == "c64"
    assert source.title is c64_port.POOL_OF_RADIANCE
    assert source.key == "pool-of-radiance"
    assert source.save0 == save0
    assert source.save1 == save1
    assert source.disk == disk.to_bytes()


def test_source_detect_blocks_a_disk_with_no_save(tmp_path):
    """A blank disk is a legal `.D64` and carries no title's save file."""
    from goldbox.d64 import D64

    path = tmp_path / "blank.d64"
    path.write_bytes(D64.blank().to_bytes())
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(path)


def test_source_detect_blocks_a_path_that_is_neither(tmp_path):
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(tmp_path / "nowhere")


@pytest.mark.parametrize("deltas", dos_port.DELTAS, ids=lambda s: s.key)
def test_source_detect_identifies_each_dos_title(tmp_path, deltas):
    """Every one of the four titles' record sizes names its own deltas --
    including Pools of Darkness, whose container is `SAVGAM?.PTY` rather
    than `SAVGAM?.DAT` (`goldbox/dos_savegame.py`'s `SAVE_POOLS_OF_DARKNESS`),
    the case `#52`'s plan calls out by name."""
    folder = tmp_path / deltas.key
    folder.mkdir()
    suffix = dos_savegame.CONTAINERS_BY_KEY[deltas.key].suffix
    (folder / f"SAVGAMA{suffix}").write_bytes(b"\x00")
    (folder / "CHRDATA1.SAV").write_bytes(b"\x00" * deltas.record_size)

    source = convert.Source.detect(folder)

    assert source.port == "dos"
    assert source.title is deltas
    assert source.key == deltas.key


def test_source_detect_blocks_a_folder_with_no_character_record(tmp_path):
    """A folder holding only `SAVGAM?.PTY` -- no `CHRDAT` beside it -- is
    DOS-style but its title cannot be read from anything. A `ConvertError`
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
    disk_bytes = dos_codec.save_disk(save0, save1).to_bytes()
    path = tmp_path / "PORSAVE.D64"
    path.write_bytes(disk_bytes)

    edited = bytearray(save0)
    edited[0] = (edited[0] + 1) % 256
    edited = bytes(edited)
    assert edited != save0

    party = _fake_party(path, c64_port.POOL_OF_RADIANCE, edited, save1,
                        disk_bytes)
    source = convert.Source.detect(path, party=party)

    assert source.save0 == edited
    assert source.save0 != save0


def test_source_detect_ignores_a_party_at_a_different_path(tmp_path):
    """A `party` open on a different file must not shadow the one asked for."""
    save0, save1 = _fixture_payloads()
    disk_bytes = dos_codec.save_disk(save0, save1).to_bytes()
    path = tmp_path / "PORSAVE.D64"
    path.write_bytes(disk_bytes)

    other = _fake_party(tmp_path / "OTHER.D64", c64_port.POOL_OF_RADIANCE,
                        b"\xff" * len(save0), save1, disk_bytes)
    source = convert.Source.detect(path, party=other)

    assert source.save0 == save0


def test_source_detect_blocks_a_matching_party_with_nothing_open(tmp_path):
    """A roster disk has characters and no saved game -- `exports.Source.
    from_party`'s own rejection, passed along."""
    path = tmp_path / "ROSTER.D64"
    path.write_bytes(b"\x00")
    party = _fake_party(path, c64_port.POOL_OF_RADIANCE, None)
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(path, party=party)


# ---------------------------------------------------------------------------
# destinations_for -- an unready direction is never offered
# ---------------------------------------------------------------------------

def test_destinations_for_lists_pool_of_radiances_registered_directions():
    """Pool of Radiance is the one title with an Amiga writer
    (`goldbox.amiga_shared.WRITES`, `#316 (Write the Amiga Pool of Radiance saved
    game from the source save, so a converted party arrives where it was
    standing)`), so its two sources each answer two directions rather than
    one -- DOS still first for a DOS source, C64 still first for a C64
    source."""
    dos_source = convert.Source(port="dos", title=dos_port.POOL_OF_RADIANCE,
                                path=pathlib.Path("."))
    assert [type(d) for d in convert.destinations_for(dos_source)] == \
        [convert.DosToC64, convert.DosToAmiga]

    c64_source = convert.Source(port="c64", title=c64_port.POOL_OF_RADIANCE,
                                path=pathlib.Path("."))
    directions = convert.destinations_for(c64_source)
    assert [type(d) for d in directions] == \
        [convert.C64ToDos, convert.C64ToAmiga]
    assert directions[0].destination_game is dos_port.POOL_OF_RADIANCE
    assert directions[1].destination_game is dos_port.POOL_OF_RADIANCE


@pytest.mark.parametrize("deltas", [dos_port.CURSE_OF_THE_AZURE_BONDS,
                                   dos_port.SECRET_OF_THE_SILVER_BLADES],
                        ids=lambda s: s.key)
def test_destinations_for_a_curse_or_ssb_c64_source_answers_both_directions(
        deltas):
    """`#299 (goldbox.dos.write builds only Pool of Radiance's record, so
    nothing can be converted to DOS for the later titles)`'s container
    writer put both later titles on `goldbox.dos_codec.WRITES`, so each is offered
    with no edit to this module beyond the derivation itself -- the same
    way `test_destinations_for_a_curse_source_answers_the_curse_c64_direction`
    already proves for the other direction."""
    c64_source = convert.Source(port="c64", title=c64_port.by_key(deltas.key),
                                path=pathlib.Path("."))
    directions = convert.destinations_for(c64_source)
    assert [type(d) for d in directions] == [convert.C64ToDos,
                                             convert.C64ToAmiga]
    assert directions[0].destination_game is deltas
    assert directions[1].destination_game is deltas


def test_directions_holds_twenty_rows_eighteen_derived_from_library_tuples():
    """Three titles read DOS → C64 (`goldbox.dos_codec.CONVERTS`) and the same
    three write C64 → DOS (`goldbox.dos_codec.WRITES`, as of `#299`); all
    three read Amiga → C64 and Amiga → DOS
    (`goldbox.amiga_shared.CONVERTS`, as of
    `#353 (Convert an Amiga Pool of Radiance save to the C64, so a party
    standing in the Slums on the Amiga arrives there in VICE)` and
    `#354 (Convert an Amiga Pool of Radiance save to DOS, so a party
    standing in the Slums on the Amiga arrives there under DOSBox)`), and
    all three write C64 → Amiga and DOS → Amiga
    (`goldbox.amiga_shared.WRITES`, `#316 (Write the Amiga Pool of Radiance saved
    game from the source save, so a converted party arrives where it was
    standing)`), so the registry holds eighteen rows -- up from four before
    `#299`'s container writer, six before `#353`'s Amiga reader, and eight
    before `#316`'s Amiga saved-game writer.

    Counted by exact type rather than `isinstance`, because each Amiga row
    derives from the DOS row that shares its destination -- `AmigaToC64`
    from `DosToC64` and `AmigaToDos` from `C64ToDos` -- so an `isinstance`
    count would read an Amiga row as a DOS one and pass while the Amiga row
    was missing entirely. `C64ToAmiga` and `DosToAmiga` derive from
    `Direction` directly, so they need no such care."""
    assert len(convert.DIRECTIONS) == 20
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.DosToC64) == 3
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.C64ToDos) == 3
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.AmigaToC64) == 3
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.AmigaToDos) == 3
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.C64ToAmiga) == 3
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.DosToAmiga) == 3
    # Pools of Darkness has no C64 port, so its two rows are listed by hand.
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.PodAmigaToDos) == 1
    assert sum(1 for d in convert.DIRECTIONS
              if type(d) is convert.PodDosToAmiga) == 1


def test_destinations_for_a_curse_source_answers_the_curse_c64_direction():
    """Curse of the Azure Bonds joined `goldbox.dos_codec.CONVERTS` overnight
    (the work on converting a Curse of the Azure Bonds DOS save into a C64 one), and this registry derives its row
    from `CONVERTS` rather than listing it -- so it is offered with no edit
    to `editor/convert.py` beyond the derivation itself."""
    curse_source = convert.Source(port="dos",
                                  title=dos_port.CURSE_OF_THE_AZURE_BONDS,
                                  path=pathlib.Path("."))
    directions = convert.destinations_for(curse_source)
    assert [type(d) for d in directions] == [convert.DosToC64,
                                             convert.DosToAmiga]
    assert directions[0].destination_game is c64_port.CURSE_OF_THE_AZURE_BONDS


def test_a_pools_of_darkness_folder_is_offered_only_the_amiga(tmp_path):
    """Pools of Darkness has no C64 port, so a DOS save of it is offered the
    Amiga and nothing else.

    **This used to use Secret of the Silver Blades**, which was read with no
    C64 writer until the work on converting a Secret of the Silver Blades DOS save into a C64 one built one and it
    joined `goldbox.dos_codec.CONVERTS` on 2026-09-05. Pools of Darkness is the
    permanent example: `goldbox/c64_port.py` has no entry for it at all, because
    there is no C64 port to convert to, so no writer will ever appear.

    A fake folder is enough -- `Source.detect` reads only the record size."""
    folder = tmp_path / "pod"
    folder.mkdir()
    (folder / "SAVGAMA.DAT").write_bytes(b"\x00")
    (folder / "CHRDATA1.SAV").write_bytes(
        b"\x00" * dos_port.POOLS_OF_DARKNESS.record_size)

    source = convert.Source.detect(folder)
    assert source.key == dos_port.POOLS_OF_DARKNESS.key
    assert [type(d) for d in convert.destinations_for(source)] == [
        convert.PodDosToAmiga]


def test_every_converts_entry_has_a_dos_to_c64_name():
    """A `CONVERTS` title with no row in `DOS_TO_C64_NAMES` is a defect the
    registry must fail loudly on -- `#52`'s plan calls this out by name --
    and `DIRECTIONS` already proves it by having built without raising, but
    this pins the table directly against the source of truth."""
    for deltas in convert.C64_PAIRED:
        assert deltas.key in convert.DOS_TO_C64_NAMES, (
            f"{deltas.title} converts but names no .D64 file")
    # `dos_codec.CONVERTS` and `C64_PAIRED` differ by exactly the titles with no
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
    assert [s.key for s in dos_codec.CONVERTS if s not in convert.C64_PAIRED] == \
        [dos_port.POOLS_OF_DARKNESS.key]


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
    assert dos_port.POOLS_OF_DARKNESS.key not in c64_port.BY_KEY
    assert dos_port.POOLS_OF_DARKNESS.key in titles.BY_KEY


def test_a_converts_entry_missing_its_name_fails_at_construction():
    """The loud failure `DIRECTIONS` would hit if `goldbox.dos_codec.CONVERTS`
    grew a row `DOS_TO_C64_NAMES` has none for, provoked directly rather
    than by editing `CONVERTS` itself. Secret of the Silver Blades is a real
    `goldbox.c64_port.by_key` entry -- so this proves the *name* lookup fails
    loudly, not the *game* lookup that would run first for a title nobody
    has heard of.

    The deltas object is built here rather than named from `dos_port`, because
    every title that has one is now in `DOS_TO_C64_NAMES` -- Silver Blades
    joined on 2026-09-05 with the work on converting a Secret of the Silver Blades DOS save into a C64 one. Copying a
    real deltas under a key nothing names is what leaves this test asserting
    the same thing it always did. Champions of Krynn is the key to borrow:
    `goldbox/c64_port.py` knows it, so `c64_port.by_key` succeeds and the failure
    can only come from the name lookup, which is the point."""
    unnamed = dataclasses.replace(dos_port.SECRET_OF_THE_SILVER_BLADES,
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
    search `tests/convert/test_dosimport.py`'s `files` fixture does."""
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
                animate = load_payload(str(disk), dos_codec.ANIMATE_FILE)
        except Exception:
            pass
    if icon is None or animate is None:
        pytest.skip("the game disks here carry neither SPELLE64 nor ANIMATE00")
    #: The creation menu too. A Pool of Radiance conversion blocks without
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
    slot = dos_codec.slots_available(folder)[0]
    source = convert.Source.detect(folder)
    before = sorted(folder.iterdir())

    direction = convert.DosToC64(dos_port.POOL_OF_RADIANCE)
    direction.rehearse(source, slot, game_files)

    assert sorted(folder.iterdir()) == before
    assert not list(tmp_path.iterdir())


@needs_dos_saves
@needs_disks
def test_dos_to_c64_direction_writes_only_into_its_own_folder(game_files,
                                                              tmp_path):
    folder = _save_dir()
    slot = dos_codec.slots_available(folder)[0]
    source = convert.Source.detect(folder)

    direction = convert.DosToC64(dos_port.POOL_OF_RADIANCE)
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
    """The bytes this direction writes equal what `tools/dos/dosdisk.py` writes,
    calling `goldbox.dos_codec.new_save` and `goldbox.dos_codec.save_disk` directly for
    the same slot -- so `#119 (Play a converted DOS save in VICE, off a disk
    Wish built from nothing)`'s VICE proof stands for this path too."""
    folder = _save_dir()
    slot = dos_codec.slots_available(folder)[0]
    source = convert.Source.detect(folder)

    direction = convert.DosToC64(dos_port.POOL_OF_RADIANCE)
    rehearsal = direction.rehearse(source, slot, game_files)
    destination = tmp_path / "out"
    direction.write(rehearsal, destination)

    #: The portrait tables too, since `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT,
    #: which needs the import working for all three C64 titles)` -- the
    #: reference call has to be given what the direction gives itself, or it
    #: blocks where the direction does not and the two cannot be compared.
    ref_save0, ref_save1, _ = dos_codec.new_save(folder, slot, game_files.icon,
                                          game_files.animate,
                                          portraits=game_files.portraits)
    reference = dos_codec.save_disk(bytes(ref_save0), bytes(ref_save1))
    assert (destination / f"PORSAVE{slot}.D64").read_bytes() == \
        reference.to_bytes()


@needs_curse_dos_save
def test_curse_dos_to_c64_direction_is_the_transfer_test(tmp_path):
    """The registry's derived Curse row writes the same bytes a direct call
    writes, calling `goldbox.dos_codec.new_save` and `goldbox.dos_codec.save_disk`
    directly with `game=CURSE_OF_THE_AZURE_BONDS` -- so the work on converting a Curse of the Azure Bonds DOS save into a C64 one's VICE proof stands for this path too. This is the
    check `#52`'s plan asks for: `destinations_for` on a Curse folder
    answers one direction whose `destination_game` is Curse.

    `icon`/`animate` are zero-filled, `test_curseconvert.py`'s own pattern
    for this DOS session -- a round trip of our code, not a claim about
    what the player's Curse disks hold."""
    folder = _curse_save_dir()
    slot = CURSE_SLOT
    icon, animate = bytes(36), bytes(852)
    game_files = dosimport.GameFiles(icon=icon, animate=animate)
    source = convert.Source.detect(folder)
    assert source.key == dos_port.CURSE_OF_THE_AZURE_BONDS.key

    directions = convert.destinations_for(source)
    assert [type(direction) for direction in directions] == [
        convert.DosToC64, convert.DosToAmiga]
    direction = directions[0]
    assert direction.destination_game is c64_port.CURSE_OF_THE_AZURE_BONDS

    rehearsal = direction.rehearse(source, slot, game_files)
    destination = tmp_path / "out"
    written = direction.write(rehearsal, destination)
    assert [p.name for p in written] == [f"CURSE{slot}.D64"]

    ref_save0, ref_save1, _ = dos_codec.new_save(
        folder, slot, icon, animate, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    reference = dos_codec.save_disk(bytes(ref_save0), bytes(ref_save1),
                              c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert (destination / f"CURSE{slot}.D64").read_bytes() == \
        reference.to_bytes()


# ---------------------------------------------------------------------------
# C64 -> DOS: rehearsed into a scratch directory, written once, no template
# ---------------------------------------------------------------------------

@needs_dos_saves
def test_c64_to_dos_direction_rehearses_with_no_write(tmp_path):
    save0, save1 = _fixture_payloads()
    source = convert.Source(port="c64", title=c64_port.POOL_OF_RADIANCE,
                            path=pathlib.Path("."), save0=save0, save1=save1)
    direction = convert.C64ToDos(dos_port.POOL_OF_RADIANCE)

    direction.rehearse(source, "Z", _game_dir())

    assert not list(tmp_path.iterdir())


@needs_dos_saves
def test_c64_to_dos_direction_writes_only_into_its_own_folder(tmp_path):
    save0, save1 = _fixture_payloads()
    source = convert.Source(port="c64", title=c64_port.POOL_OF_RADIANCE,
                            path=pathlib.Path("."), save0=save0, save1=save1)
    direction = convert.C64ToDos(dos_port.POOL_OF_RADIANCE)
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
    """The files this direction writes equal what `tools/dos/dosnewsave.py`
    writes, calling `goldbox.dos_codec.new_dos_save` directly for the same inputs
    -- so `#26 (Write a DOS save, not just read one)`'s DOSBox proof stands
    for this path too. No template anywhere (`.claude/rules/conversions.md`).
    """
    save0, save1 = _fixture_payloads()
    game_dir = _game_dir()
    slot = "Z"
    source = convert.Source(port="c64", title=c64_port.POOL_OF_RADIANCE,
                            path=pathlib.Path("."), save0=save0, save1=save1)

    direction = convert.C64ToDos(dos_port.POOL_OF_RADIANCE)
    rehearsal = direction.rehearse(source, slot, game_dir)
    destination = tmp_path / "out"
    direction.write(rehearsal, destination)

    reference = tmp_path / "reference"
    dos_codec.new_dos_save(save0, save1, reference, slot, game_dir)

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


@needs_dos_saves
def test_c64_to_dos_direction_recognises_the_sources_own_combat_icon(
        tmp_path):
    """`C64ToDos.rehearse`/`write` take the `icon_parts` `goldbox.dos_codec.
    new_dos_save` always could, and the two runs stay in step -- `write`'s
    second run recognises what `rehearse`'s did, not the game's own default.
    """
    save0, save1, parts = _six_icon_party()
    game_dir = _game_dir()
    slot = "Z"
    source = convert.Source(port="c64", title=c64_port.POOL_OF_RADIANCE,
                            path=pathlib.Path("."), save0=save0, save1=save1)

    direction = convert.C64ToDos(dos_port.POOL_OF_RADIANCE)
    rehearsal = direction.rehearse(source, slot, game_dir, icon_parts=parts)
    assert not any("figure is not set" in d for d in rehearsal.report.dropped), \
        rehearsal.report.dropped

    destination = tmp_path / "out"
    direction.write(rehearsal, destination)

    party = dos_codec.read_party(destination, slot)
    assert len(party) == 6
    pairs = [(c.get("icon_head"), c.get("icon_body")) for c in party]
    assert len(set(pairs)) == 6, pairs


# ---------------------------------------------------------------------------
# `#234 (A dual-classed Curse or Silver Blades character converted to DOS
# loses the class he trained out of)`'s own proof, through this registry
# rather than a direct `goldbox.dos_codec` call -- the row this issue was waiting
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
    stages -- `tests/dos/test_doslatercontainer.py`'s own helper, repeated here
    rather than imported across `#52`'s lane."""
    from tools.dos import dosbox
    try:
        return dosbox.find_game("CURSE")
    except FileNotFoundError:
        return None


needs_dual_classed_curse_specimen = pytest.mark.skipif(
    _dual_classed_curse_disk() is None or _curse_game_dir() is None,
    reason="needs ~/wish-specimens/por-c64/WISH-SPEC-curse-dual-classed.D64 "
          "(tools/registry/specimens.py) and the DOS Curse archives ($FR_ARCHIVES)")


@needs_dual_classed_curse_specimen
def test_234_a_dual_classed_curse_character_keeps_his_former_class_through_the_registry(
        tmp_path):
    """`#234`'s own case, run through `editor.convert.DIRECTIONS` rather
    than the direct `goldbox.dos_codec.new_dos_save` call its comments proved this
    with: converting PHILIPPE's disk through the registered Curse C64 → DOS
    direction and reading the DOS record back gets the same answer -- fighter
    1, no experience, carrying the magic-user 6 she left in the two places
    the DOS engine keeps it (`#234`'s comment of 2026-09-05 20:15)."""
    disk = _dual_classed_curse_disk()
    source = convert.Source.detect(disk)
    assert source.port == "c64"
    assert source.key == c64_port.CURSE_OF_THE_AZURE_BONDS.key

    directions = convert.destinations_for(source)
    assert [type(direction) for direction in directions] == [
        convert.C64ToDos, convert.C64ToAmiga]
    direction = directions[0]
    assert type(direction) is convert.C64ToDos
    assert direction.destination_game is dos_port.CURSE_OF_THE_AZURE_BONDS

    rehearsal = direction.rehearse(source, "Z", _curse_game_dir())
    destination = tmp_path / "out"
    direction.write(rehearsal, destination)

    records = [dos_codec.read_character(p)
              for p in sorted(destination.glob("CHRDATZ?.SAV"))]
    philippe = next(c for c in records if c.name == "PHILIPPE")

    assert philippe.class_levels == {"fighter": 1}
    assert philippe.get("experience") == 0
    # magic-user is slot 5 of `dos_codec.CLASS_LEVEL_SLOTS` -- the class she left.
    assert philippe.raw("former_class_levels")[5] == 6
    assert philippe.raw("former_level")[0] == 6



@pytest.fixture
def app():
    """The session-wide application `tests/conftest.py` holds a reference to."""
    return QApplication.instance() or QApplication([])


def _make_root():
    from PyQt6.QtWidgets import QWidget
    return QWidget()


def test_disk_candidates_picks_the_destination_pattern_not_the_open_partys(
        tmp_path):
    """`EditorBinding._disk_candidates`'s new `pattern` argument: a fake
    disks folder holding both a `POOL*` and a `CURSE*` name, asked for each
    in turn, answers only the one that matches (`cited/reports/52-plan.md`
    step B's own suggested test design)."""
    disks = tmp_path / "disks"
    disks.mkdir()
    (disks / "POOL1.D64").write_bytes(b"pool")
    (disks / "CURSE1.D64").write_bytes(b"curse")

    window = EditorBinding(_make_root(), disks=str(disks))
    try:
        assert window._disk_candidates(c64_port.POOL_OF_RADIANCE.disk_glob) == \
            [str(disks / "POOL1.D64")]
        assert window._disk_candidates(
            c64_port.CURSE_OF_THE_AZURE_BONDS.disk_glob) == \
            [str(disks / "CURSE1.D64")]
    finally:
        window.close()


def test_disk_candidates_prefers_a_titles_own_preferences_folder(tmp_path):
    """`#342 (A Curse or Silver Blades save cannot be converted unless its
    C64 sides sit in the Pool of Radiance disk folder)`: the shared Game Disk
    folder holds Pool of Radiance's sides, Curse's own folder is set
    separately in Preferences (`#22 (A disk folder setting per game, not one
    shared by all six)`), and the destination lookup finds Curse's disk in
    its own folder rather than blocking because the shared one has none."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "POOL1.D64").write_bytes(b"pool")

    curse_folder = tmp_path / "curse"
    curse_folder.mkdir()
    (curse_folder / "CURSE1.D64").write_bytes(b"curse")

    window = EditorBinding(_make_root(), disks=str(shared), game_folders={
        c64_port.CURSE_OF_THE_AZURE_BONDS.key: str(curse_folder)})
    try:
        assert window._disk_candidates(
            c64_port.CURSE_OF_THE_AZURE_BONDS.disk_glob,
            c64_port.CURSE_OF_THE_AZURE_BONDS) == \
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
            c64_port.POOL_OF_RADIANCE.disk_glob, c64_port.POOL_OF_RADIANCE) == \
            [str(shared / "POOL1.D64")]
    finally:
        window.close()


def test_no_marked_string_reaches_a_player_in_c64_conversion_or_the_automapper():
    """The same guarantee as `test_no_string_the_player_reads_is_unapproved`,
    for the four other modules that can put a string in front of a player
    and mark it unapproved the same way.

    `#306 (The Fast Travel button's own disabled tooltip carries a memory
    address)`'s last comment found that the `(NOT APPROVED)` marker was
    checked only in `editor/convert.py`, so a marked string in
    `goldbox/c64_codec.py`, `goldbox/amiga.py`, `goldbox/dos_codec.py` or
    `automap/actions.py` shipped to a player silently instead of failing
    here first. This walks each module's own source, the way the test above
    does, rather than a typed list of strings, so a new marked string added
    to any of the four fails here too.

    `goldbox/dos_codec.py` joined the sweep on `#52 (File ▸ Import and File ▸
    Export for every direction the library supports)`: `#389 (A conversion
    to the Amiga tells the player what DOS does with their character)`
    (`d0c280f`) put a marked portrait-position line in `to_neutral`, the DOS
    reader every registered direction with a DOS source calls, and this test
    did not reach that module -- `dos_codec.py`'s own docstring at its `rep.dropped`
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
    `goldbox/dos_codec.py` and `automap/actions.py` predate or follow it. None of
    the twelve is this test's to approve -- Donald ruled on 2026-09-07 that
    the two combat-icon lines (`c64_codec.py`'s and `amiga.py`'s) stay
    unworded until the tickets that would delete them close, so the right
    outcome here is a count held at today's number rather than a demand
    that it reach zero. `WISH_EXPERIMENTAL_CONVERT` came off on 2026-09-14
    with these still on the pane -- it did not come off on 2026-09-07, as
    an earlier version of this sentence said: that lift went straight back
    the same night. The flag's own condition was about the dialog's own
    strings block, never about this wider sweep.
    """
    import inspect

    from automap import actions

    # The two codecs by their own names rather than through the
    # `goldbox/dos_codec.py` and `goldbox/amiga.py` shims: `#470`'s stage 8 moved
    # the code to `dos_codec.py` and `amiga_codec.py`, and
    # `inspect.getsource` of a shim reads the shim, which carries no strings
    # at all. `WAITING` is keyed on `module.__name__`, so both move together.
    # Stage 10 then split the Amiga codec by title and `amiga_codec.py` became
    # a shim itself; the one marked string is the Pools of Darkness reader's,
    # so it is `goldbox/amiga_pod.py` that is read here now.
    from goldbox import amiga_pod, c64_codec, dos_codec

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
    #: one in `goldbox/amiga.py`, one in `goldbox/dos_codec.py`
    #: (`#389 (A conversion to the Amiga tells the player what DOS does with
    #: their character)`'s portrait-position line) and one in
    #: `automap/actions.py`, the Fast Travel failure line
    #: `#306 (The Fast Travel button's own disabled tooltip carries a memory
    #: address)` left behind.
    #: `automap.actions` went from one to two on 2026-09-07: Curse's trainer
    #: raises every ready class in one press (`GEN $14F8`), so the message
    #: after a level-up can now name more than one class in a sentence --
    #: a case no player has seen, because Pool of Radiance's trainer never
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
    #: `goldbox.dos_codec` went from one to eight and `goldbox.amiga` from two to
    #: three on 2026-09-08, closing the write-side half of `#389 (A
    #: conversion to the Amiga tells the player what DOS does with their
    #: character)` its own last comment left open: `goldbox.dos_codec.write` always
    #: builds a DOS record, even when `goldbox.amiga.write_por` and
    #: `write_later` re-cut it into an Amiga one, and five of its own canned
    #: drop reasons named "DOS" regardless of which writer was asking --
    #: `write` now takes an `into` parameter the two Amiga writers pass
    #: `"Amiga"` through, so the composed sentences differ by wording rather
    #: than by number, and each of the five needed its own marker. A sixth
    #: line in `goldbox.dos_codec.write` and one in `goldbox.amiga.to_neutral` had
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
    #: Save As draws and it reads `messages` and `losses` alone,
    #: logging `dropped` instead. The four: `goldbox.c64_codec`'s
    #: combat-icon line in `write` (9 to 8), `goldbox.dos_codec.to_neutral`'s
    #: portrait-position line (8 to 7), and `goldbox.amiga`'s `0x11F`
    #: trailing-pad line and its `field_83_87` treasure-share entry in
    #: `LATER_DROPPED_PLAYER_TEXT` (3 to 1).
    #:
    #: **The seven that kept their marker until 2026-09-14 did so for one
    #: reason, and that reason is gone.** `editor/exports.py`'s own pane used
    #: to draw `report.dropped` through `exports.losses` whenever
    #: `WISH_EXPERIMENTAL_EXPORT` was set, reading a **C64** save -- so every
    #: drop line the C64 reader and the DOS and Amiga writers compose could
    #: still reach a person, which was `goldbox.c64_codec`'s
    #: `READ_DROPPED_PLAYER_TEXT` entry and six of `goldbox.dos_codec`'s.
    #: `File ▸ Export` is deleted whole (`#52 (File ▸ Import and File ▸
    #: Export for every direction the library supports)`'s 2026-09-09
    #: ruling, carried out 2026-09-14) -- `editor/exports.py`, `exports.ui`,
    #: `ui_exports.py` and `WISH_EXPERIMENTAL_EXPORT` are all gone -- so
    #: nothing draws either module's drop text any more.
    #: `editor/convert.py`'s own dialog, the only one left, sends
    #: `report.dropped` to `wish/debuglog.py` and nowhere else
    #: (`.claude/rules/conversions.md`, *"a drop line is therefore never a
    #: string Donald words"*), which `.claude/rules/gui-text.md` exempts from
    #: approval by name. So the seven markers came off with the pane, the
    #: same way the four on 2026-09-09 came off with `WISH_EXPERIMENTAL_
    #: EXPORT`'s own sibling change: nobody worded them, they stopped being
    #: strings a player can reach.
    #:
    #: `goldbox.amiga_pod`'s one remaining marker is `pod_to_neutral`'s, and
    #: it is a **warning** rather than a drop: a reader's warnings reached
    #: the exports pane through `losses` on any conversion to the C64.
    #: Nothing calls `pod_to_neutral` outside the tests today, so it reached
    #: no player even before the pane went; the marker stays because wiring
    #: it up is what `#194 (Import and export a Pools of Darkness save
    #: between DOS and the Amiga)` is for.
    # `automap.actions` went 4 -> 3 when Fast Travel's failure line got the
    # wording Donald ruled on 2026-09-07 (`#306 (The Fast Travel button's own
    # disabled tooltip carries a memory address)`), which had been recorded
    # there and never applied.
    #
    # **`goldbox.c64_codec` went 8 to 1 on 2026-09-09, and none of the seven
    # was approved: the sentences themselves are gone.** All six of #399's
    # own per-character ceiling sentences (memorised spells, the spellbook,
    # the class array, both trait-slot lines and the inventory line) are
    # deleted, not reworded: Donald ruled, on the 950-character sweep #399's
    # own closing comment carries, that no real conversion reaches any of
    # these ceilings -- "I agree that we do not need the sentences." A short
    # comment citing #399 sits where each one was. The one line left was the
    # combat-icon figure, `#320`/`#355` territory -- and that one went to 0
    # on 2026-09-14 for the `File ▸ Export`-deletion reason above.
    #
    # `goldbox.dos_codec` went 7 to 6 on 2026-09-09, also with nothing
    # approved: `encumbrance`'s drop-list line moved to `WRITE_DERIVED`
    # (#483, The Convert flag could come off while two fields are still
    # lost, because a silencing list keeps them out of the count that
    # decides it), which `write` now consumes with `use()` rather than ever
    # composing a report line for. That was the same kind of change as the
    # four on 2026-09-09; the remaining six (`abilities_second`,
    # `former_levels` twice, `spells_castable['druid']`, the shared
    # `portrait_head`/`portrait_body` line and `Dead`'s status line) went to
    # 0 on 2026-09-14 for the `File ▸ Export`-deletion reason above.
    # `goldbox.amiga_pod` 1 -> 0: the Amiga reader's marked warning was
    # deleted, because it stopped being true, rather than worded by Donald.
    #
    # `automap.actions` 1 -> 3 -> 0: Fast Travel's three strings (the
    # two-hop's walking-out and giving-up lines, and the one-hop "Walking out
    # towards" line) were approved by the owner as worded, so every swept
    # module was 0. `automap.actions` went 0 -> 2 -> 0: the two-hop's
    # wrong-door cancel and every-door-fights rejection were approved as worded.
    WAITING = {"goldbox.c64_codec": 0, "goldbox.amiga_pod": 0,
               "goldbox.dos_codec": 0, "automap.actions": 0}

    found: dict[str, list[str]] = {}
    for module in (c64_codec, amiga_pod, dos_codec, actions):
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


@pytest.mark.parametrize("value", ["1", "0", "true", "off", "", "no"])
def test_convert_does_not_depend_on_the_removed_variable(value, app, tmp_path,
                                                         monkeypatch):
    """`WISH_EXPERIMENTAL_CONVERT` governed `File ▸ Convert…` until
    2026-09-14; any value left behind in a shell's environment now -- on,
    off, or nonsense -- must leave the File menu exactly as it is with
    nothing set.

    Put the `if convert.enabled():` gate back in `wish/window.py`
    (`.claude/rules/scratch.md`: copy the file aside, edit, diff it against
    the copy, put the copy back, clear `__pycache__`) to watch this fail:
    with the gate restored, `convert.enabled()` no longer exists at all,
    so every value here raises instead of matching the reference menu.
    """
    monkeypatch.delenv("WISH_EXPERIMENTAL_CONVERT", raising=False)
    reference = _wish_window(tmp_path, monkeypatch)
    reference_texts = [a.text() for a in _file_menu(reference).actions()]
    reference.close()

    monkeypatch.setenv("WISH_EXPERIMENTAL_CONVERT", value)
    window = _wish_window(tmp_path, monkeypatch)
    assert [a.text() for a in _file_menu(window).actions()] == reference_texts
    window.close()


# ---------------------------------------------------------------------------
# Amiga -> C64: the registry's third source port (#353)
# ---------------------------------------------------------------------------

def _amiga_por_disk():
    """The player's own Amiga Pool of Radiance disk 1, or a skip.

    `tests/convert/test_amigatoc64.py` owns the search and the reason it matches on
    the record's own size rather than on the file names; this is the same
    disk, reached the same way, so the two cannot pick different ones.
    """
    from support.amigatoc64 import _pool_of_radiance_disk_1

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
    assert source.key == dos_port.POOL_OF_RADIANCE.key
    assert source.slot == "A"
    # A disk, not a folder and not a C64 save: nothing was read into memory.
    assert source.save0 is None and source.disk is None


def test_a_file_that_is_not_an_adf_still_goes_to_the_c64_reader(tmp_path):
    """The new branch is reached by suffix, so it must not swallow the C64
    one: a `.d64` that cannot be read still blocks as a C64 disk."""
    path = tmp_path / "notadisk.d64"
    path.write_bytes(b"\x00" * 64)
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(path)


def test_an_adf_that_holds_no_saved_game_is_blocked_and_not_guessed_at(
        tmp_path):
    """A blank Amiga floppy is blocked with a sentence rather than being
    read as an empty Pool of Radiance disk."""
    from goldbox.amiga_adf import AmigaDisk

    path = tmp_path / "blank.adf"
    path.write_bytes(AmigaDisk.blank("EMPTY").to_bytes())
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(path)


def test_an_adf_with_no_save_drawer_says_it_holds_no_saved_game(tmp_path):
    """A disk with no `save` entry has no slots, so opening it says so in the
    editor's own sentence and not with the drawer lookup's error."""
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

    disk = AmigaDisk.blank("Secret 2")
    assert amiga_savegame.por_slots_present(disk) == []

    path = tmp_path / "secret2.adf"
    path.write_bytes(disk.to_bytes())
    with pytest.raises(convert.ConvertError) as raised:
        convert.Source.detect(path)
    assert "holds no Amiga saved game" in str(raised.value)
    assert "has no" not in str(raised.value)


def test_amiga_to_c64_direction_is_the_transfer_test(amiga_adf, tmp_path):
    """The bytes the dialog's Amiga row writes equal what
    `tools/amiga/fromamigapor.py` writes, calling `goldbox.amiga_savegame.read_por_slot`,
    `goldbox.dos_codec.new_save_from` and `goldbox.dos_codec.save_disk` directly for the
    same slot -- so `#353`'s VICE proof stands for this path too, which is
    the same argument `test_dos_to_c64_direction_is_the_transfer_test`
    makes for the DOS row.

    `icon`/`animate` are zero-filled: this is a round trip of our own code
    for one input, not a claim about what the player's C64 disks hold."""
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

    icon, animate = bytes(36), bytes(852)
    files = dosimport.GameFiles(icon=icon, animate=animate)
    source = convert.Source.detect(amiga_adf)
    direction = convert.destinations_for(source)[0]

    rehearsal = direction.rehearse(source, source.slot, files)
    destination = tmp_path / "out"
    written = direction.write(rehearsal, destination)
    assert [p.name for p in written] == [f"PORSAVE{source.slot}.D64"]

    disk = AmigaDisk.open(str(amiga_adf))
    party, savgam = amiga_savegame.read_por_slot(disk, source.slot)
    state = amiga_savegame.read_por_state(savgam, str(amiga_adf))
    ref0, ref1, report = dos_codec.new_save_from(state, party, icon, animate)
    reference = dos_codec.save_disk(bytes(ref0), bytes(ref1))
    assert (destination / f"PORSAVE{source.slot}.D64").read_bytes() == \
        reference.to_bytes()
    assert report.unwritten == []


# ---------------------------------------------------------------------------
# C64 -> Amiga and DOS -> Amiga: one POOLSAVE.ADF, no template
# (`#316 (Write the Amiga Pool of Radiance saved game from the source save,
# so a converted party arrives where it was standing)`, `#36 (Write an
# Amiga disk image, not just the character files)`)
# ---------------------------------------------------------------------------

def test_a_curse_c64_source_is_offered_an_amiga_row():
    """The later-title writer adds Amiga without displacing DOS."""
    from goldbox import amiga_shared

    assert amiga_shared.WRITES == (
        dos_port.POOL_OF_RADIANCE,
        dos_port.CURSE_OF_THE_AZURE_BONDS,
        dos_port.SECRET_OF_THE_SILVER_BLADES,
    )

    curse_source = convert.Source(port="c64", title=c64_port.CURSE_OF_THE_AZURE_BONDS,
                                  path=pathlib.Path("."))
    directions = convert.destinations_for(curse_source)
    assert [type(d) for d in directions] == [convert.C64ToDos,
                                             convert.C64ToAmiga]


def _synthetic_amiga_rehearsal():
    """An `AmigaWriteRehearsal` with no real game data behind it, on a
    `synthetic_savegame()` (`tests/amiga/test_amiga.py`), so
    `C64ToAmiga.write`/`DosToAmiga.write`'s own file-placement form can be
    proven on CI -- `write` reads only `rehearsal.files`, never the disk
    that built it, so nothing here needs an Amiga disk or a specimen."""
    from support.amigarecords import synthetic_savegame

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
    touches nothing else -- the same form
    `test_c64_to_dos_direction_writes_only_into_its_own_folder` proves for
    the DOS destination. One rehearsal proves both directions, since
    `C64ToAmiga.write` and `DosToAmiga.write` are the same few lines."""
    rehearsal = _synthetic_amiga_rehearsal()
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("untouched")

    for direction in (convert.C64ToAmiga(dos_port.POOL_OF_RADIANCE),
                      convert.DosToAmiga(dos_port.POOL_OF_RADIANCE)):
        destination = tmp_path / "out" / type(direction).__name__
        written = direction.write(rehearsal, destination)
        assert [p.name for p in written] == [convert.POOLSAVE_FILENAME]
        assert written[0].read_bytes() == b"not a real disk"
        assert list(destination.iterdir()) == [destination / convert.POOLSAVE_FILENAME]

    assert outside.read_text() == "untouched"


def _por_amiga_disk_2(tmp_path):
    """Amiga Pool of Radiance disk 2, or a skip -- `test_toamigapor.py`'s
    own finder, shared here so the two suites cannot pick different disks."""
    from support.toamigapor import _por_disk_2

    return _por_disk_2(tmp_path)


def test_c64_to_amiga_direction_is_the_transfer_test(tmp_path):
    """Every file on the `.adf` this direction writes equals, byte for
    byte, the same file on a disk built by calling `goldbox.dos_codec.c64_party`,
    `goldbox.amiga_savegame.por_state_from_c64`, `goldbox.amiga_savegame.new_por_savegame` and
    `goldbox.amiga_savegame.make_por_save_disk` by hand -- the same argument
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
    direction calls `dos_codec.c64_party` exactly as `tools/amiga/toamigapor.py` does
    since that fix, so the two cannot disagree.
    """
    from support.toamigapor import _c64_specimen

    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

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

    ecl = AmigaDisk.open(str(disk2)).read_file("/ecl.dax")
    party, _icons = dos_codec.c64_party(source.save0, source.save1,
                                  game=c64_port.by_key(dos_port.POOL_OF_RADIANCE.key))
    state = amiga_savegame.por_state_from_c64(source.save0, str(source.path))
    savegame, report = amiga_savegame.new_por_savegame(
        state, "A", len(party), ecl,
        portraits=any("portrait_head" in c for c in party))
    reference = amiga_savegame.make_por_save_disk("A", party, savegame)
    assert report.unwritten == []

    out_disk = AmigaDisk.open(str(out_dir / convert.POOLSAVE_FILENAME))
    written_paths = sorted(p for p, e in out_disk.walk() if not e.is_dir)
    reference_paths = sorted(p for p, e in reference.walk() if not e.is_dir)
    assert written_paths == reference_paths
    for path in written_paths:
        assert out_disk.read_file(path) == reference.read_file(path), path

    slot_party, _savgam = amiga_savegame.read_por_slot(out_disk, "A")
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
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

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

    out_disk = AmigaDisk.open(str(out_dir / convert.POOLSAVE_FILENAME))
    assert amiga_savegame.read_slot_list(out_disk, drawer="") == ["D"]

    savgam_path = folder / "SAVGAMD.DAT"
    state = amiga_savegame.por_state_from_dos(savgam_path.read_bytes(), str(savgam_path))
    built = out_disk.read_file("/savgamD.dat")
    assert (built[amiga_savegame.POR_POS_X], built[amiga_savegame.POR_POS_Y],
           built[amiga_savegame.POR_POS_FACING]) == (state.x, state.y, state.facing * 2)


def test_rehearse_por_savegame_copies_each_characters_own_losses():
    """`_rehearse_por_savegame` (#619) copies `dropped` and `warnings` off
    each character's own `write_por` report onto the rehearsal's report,
    and now does the same for `losses` -- a name cut to the Amiga's own
    field width, or a value clamped into a narrower one, has to reach the
    same report `saveplan.losses` reads, not stop at
    each character's own.

    Fails before the fix: `report.losses` is empty even though
    `char_report.losses` names something -- seen red by removing the
    `report.losses.extend(char_report.losses)` line and putting it back.
    """
    from types import SimpleNamespace

    from goldbox import neutral

    party = [{"name": "ONE"}, {"name": "TWO"}]

    def fake_write_por(char, icon=None):
        report = neutral.Report()
        report.lost(f"{char['name']}: Name is longer than the Amiga field; "
                   f"truncated")
        return b"", b"", b"", report

    fake_savegame = SimpleNamespace(converted=[])

    def fake_new_por_savegame(state, slot, count, ecl_dax, portraits=False):
        return b"", fake_savegame

    fake_disk = SimpleNamespace(verify=lambda: [], to_bytes=lambda: b"")

    import editor.convert as convert_mod

    orig_write_por = convert_mod.amiga_por.write_por
    orig_new_por_savegame = convert_mod.amiga_savegame.new_por_savegame
    orig_make_por_save_disk = convert_mod.amiga_savegame.make_por_save_disk
    convert_mod.amiga_por.write_por = fake_write_por
    convert_mod.amiga_savegame.new_por_savegame = fake_new_por_savegame
    convert_mod.amiga_savegame.make_por_save_disk = \
        lambda slot, party, savegame, icons: fake_disk
    try:
        rehearsal = convert_mod._rehearse_por_savegame(
            state=None, slot="A", party=party, ecl_dax=b"")
    finally:
        convert_mod.amiga_por.write_por = orig_write_por
        convert_mod.amiga_savegame.new_por_savegame = orig_new_por_savegame
        convert_mod.amiga_savegame.make_por_save_disk = orig_make_por_save_disk

    assert rehearsal.report.losses == [
        "ONE: Name is longer than the Amiga field; truncated",
        "TWO: Name is longer than the Amiga field; truncated"]


# ---------------------------------------------------------------------------
# A Pool of Radiance conversion's movement is computed from the ITEMS table,
# so both routes that build a `GameFiles` have to carry it.
# ---------------------------------------------------------------------------

def _giles_roster_movement(payload_pair) -> int:
    """GILES's roster-block `+0x1B`, the byte the encounter menu's FLEE reads."""
    save0, save1 = payload_pair
    party = dos_codec.read_party(_save_dir(), "A")
    names = [c.name for c in party]
    place = dos_codec.marching_slot(names.index("GILES"), len(party))
    return bytes(save1)[place * dos_codec.ROSTER_STRIDE + 0x1B]


def _files_giles_stale(files):
    from editor.dosimport import rehearse
    conversion = rehearse(_save_dir(), "A", files)
    return _giles_roster_movement((conversion.save0.to_bytes(),
                                   conversion.save1.to_bytes()))


@needs_dos_saves
def test_the_folder_route_reads_the_item_types_and_converts_giles_to_nine():
    """GILES's DOS record stores 12 where the rule gives 9; the folder-row
    route (`_game_files_from_folder`) must hand `rehearse` the ITEMS table."""
    if disk_dir() is None:
        pytest.skip("needs the game disks")
    files = saveplan._game_files_from_folder(disk_dir(), c64_port.POOL_OF_RADIANCE)
    assert files is not None and files.item_types
    assert _files_giles_stale(files) == 9


@needs_dos_saves
def test_the_preferences_route_reads_the_item_types_and_converts_giles_to_nine(app):
    """`EditorBinding.game_files_for`, the route Save As and an unedited
    Convert row take."""
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow

    if disk_dir() is None:
        pytest.skip("needs the game disks")
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    window = EditorBinding(root, disks=str(disk_dir()))
    try:
        files = window.game_files_for(c64_port.POOL_OF_RADIANCE)
        assert files is not None and files.item_types
        assert _files_giles_stale(files) == 9
    finally:
        window.close()


def _disk_with_a_looping_root_hash_chain(tmp_path):
    import struct

    from goldbox.amiga_adf import BLOCK_SIZE, AmigaDisk

    disk = AmigaDisk.blank("Secret 2")
    disk.write_file("LOOP.BIN", b"x")
    block = disk.lookup("LOOP.BIN").block
    struct.pack_into(">I", disk._data, block * BLOCK_SIZE + BLOCK_SIZE - 16,
                     block)
    path = tmp_path / "loop.adf"
    path.write_bytes(disk.to_bytes())
    return path, AmigaDisk.open(str(path))


def test_a_root_directory_that_cannot_be_read_is_not_reported_as_holding_no_save(
        tmp_path):
    """Only an absent `save` entry means no slots; a looping hash chain in the
    root says nothing about whether the disk holds a saved game."""
    from goldbox import amiga_savegame

    path, disk = _disk_with_a_looping_root_hash_chain(tmp_path)
    with pytest.raises(amiga_savegame.AmigaSaveError, match="loops"):
        amiga_savegame.por_slots_present(disk)
    with pytest.raises(convert.ConvertError) as raised:
        convert.Source.detect(path)
    assert "holds no" not in str(raised.value)


def test_an_explicit_drawer_is_used_without_looking_for_the_save_entry():
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

    disk = AmigaDisk.blank("Secret 2")
    assert amiga_savegame.por_slots_present(disk, "") == []
    assert amiga_savegame.por_slots_present(disk, "save") == []

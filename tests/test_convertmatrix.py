"""Step 4 of `#358 (Finish the C64 ↔ DOS conversion matrix: six directions
registered, two defects and a question left)`: for every one of the six DOS
↔ C64 directions, the bytes `File ▸ Convert…`'s own code path writes --
`editor.convert.ConvertDialog` ▸ `Direction.rehearse` ▸ `Direction.write` --
are compared against the bytes the library's own entry point writes for the
same input, called directly (`goldbox.dos.new_save`/`save_disk` for a DOS
source, `goldbox.dos.new_dos_save` for a C64 one).

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)`'s own `tests/test_convert.py` already proves this for
`DosToC64`/`C64ToDos` called directly for Pool of Radiance and for Curse of
the Azure Bonds (`test_dos_to_c64_direction_is_the_transfer_test`,
`test_curse_dos_to_c64_direction_is_the_transfer_test`,
`test_c64_to_dos_direction_is_the_transfer_test`) -- but never for Secret of
the Silver Blades in either direction, and never through the `ConvertDialog`
widget itself rather than the bare `Direction`. `tools/convertrun.py`, which
built the six `*-52-dialog-converted-resave` specimens this module reads,
already drives the real dialog and an emulator; this is the byte-level half
that tool's own docstring says the transfer tests stand in for -- generalised
to all six directions in one place, since Secret of the Silver Blades had
none.

**Six of six directions run on this machine.** DOS → C64 reads a real DOS
save for each title (`~/wish-specimens`, `tools/specimens.py`) and each
title's own C64 game disks (`tools/gamedisks.py`, never a hardcoded path);
Curse of the Azure Bonds and Secret of the Silver Blades resolved through
`/mnt/media/roms/c64/...`, on `gamedisks.toml`'s own committed search list.
C64 → DOS reads a real C64 save for Curse and Silver Blades and the
allowlisted `tests/fixtures/savedgame0.bin`/`savedgame1.bin` for Pool of
Radiance -- `test_convert.py`'s own fixture, not a new one -- and each
title's DOS archive tree (`tools/dosbox.find_game`, `$FR_ARCHIVES`). Every
`pytest.skip` below names what would be missing if this ran somewhere else.

**The specimen tree files every C64 and DOS specimen under `por-c64`/
`por-dos` regardless of title** -- `curse-h-engine-resave` and
`ssb-d-engine-resave` are `platform = "c64"` and their own title in
`provenance.toml`, physically inside `por-c64/`, where `tools/specimens.py`'s
own `container = f"{slug}-{platform}"` would have put them in `coab-c64`/
`ssb-c64` (and some specimens, `curse-52-dialog-converted-resave` among them,
really are there). `_dos_specimen`/`_c64_specimen` below glob across every
`*-dos`/`*-c64` container rather than assume one, so this is read once and
not chased per specimen; it costs nothing to work around and is not a code
defect, so it gets no issue of its own.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
from gamedata import specimen_root
from PyQt6.QtWidgets import QApplication

from editor import convert, dosimport
from goldbox import dos, dos_layout, games
from goldbox.d64 import load_payload
from goldbox.iconparts import IconParts
from goldbox.portraits import PortraitError, tables_from_disks
from goldbox.savegame import SaveGame0, SaveGame1
from tools import dosbox, gamedisks

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Finding the inputs -- never a hardcoded path.
# ---------------------------------------------------------------------------

def _dos_specimen(name: str) -> pathlib.Path | None:
    """The DOS specimen folder named `name`, in whichever `*-dos` container
    it landed in (see the module docstring)."""
    root = specimen_root()
    if root is None:
        return None
    found = list(root.glob(f"*-dos/WISH-SPEC-{name}"))
    return found[0] if found else None


def _c64_specimen(name: str) -> pathlib.Path | None:
    """The C64 specimen disk named `name`, in whichever `*-c64` container it
    landed in (see the module docstring)."""
    root = specimen_root()
    if root is None:
        return None
    found = list(root.glob(f"*-c64/WISH-SPEC-{name}.[dD]64"))
    return found[0] if found else None


def _c64_game_files(game: "games.Game") -> "dosimport.GameFiles | None":
    """The icon, `ANIMATE00` and the creation menu off `game`'s own C64
    disks, found through `tools/gamedisks.py` -- the project's own registry
    for a test or tool that needs the player's disks, never a path typed into
    this file. `None` when this machine has neither -- the same refusal
    `editor.window.EditorBinding.game_files_for` gives the running dialog,
    which is what makes the dialog's own pane say `NO_DISKS` rather than
    silently rehearsing with nothing.
    """
    where = gamedisks.find(game.key)
    if where is None:
        return None
    icon = animate = None
    for disk in sorted(pathlib.Path(where).glob("*.[dD]64")):
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
    portraits = None
    if game.key == games.POOL_OF_RADIANCE.key:
        try:
            portraits = tables_from_disks(where)
        except (PortraitError, OSError):
            portraits = None
    return dosimport.GameFiles(icon=icon, animate=animate, portraits=portraits)


def _fixture_payloads() -> tuple[bytes, bytes]:
    """Donald's own played Pool of Radiance save, on the repository's
    allowlist -- `test_convert.py`'s own fixture, read again rather than
    copied."""
    sg = SaveGame0.from_prg((FIXTURES / "savedgame0.bin").read_bytes())
    sg1 = SaveGame1.from_prg((FIXTURES / "savedgame1.bin").read_bytes())
    return sg.to_bytes(), sg1.to_bytes()


# ---------------------------------------------------------------------------
# DOS -> C64, all three titles: `WISH-SPEC-por-party-l1-intown`,
# `WISH-SPEC-curse-131-dualclassed-in-area-1` and
# `WISH-SPEC-ssb-234-party-pair` (slot C of its two) -- the same three DOS
# specimens `tools/convertrun.py` fed the dialog to build the three
# `*-52-dialog-converted-resave` C64 specimens this module's docstring names.
# ---------------------------------------------------------------------------

DOS_TO_C64_CASES = [
    pytest.param("por-party-l1-intown", None, games.POOL_OF_RADIANCE,
                id="pool-of-radiance"),
    pytest.param("curse-131-dualclassed-in-area-1", None,
                games.CURSE_OF_THE_AZURE_BONDS,
                id="curse-of-the-azure-bonds"),
    pytest.param("ssb-234-party-pair", "SAVGAMC.DAT",
                games.SECRET_OF_THE_SILVER_BLADES,
                id="secret-of-the-silver-blades"),
]


@pytest.mark.parametrize("specimen_name, file_name, game", DOS_TO_C64_CASES)
def test_dos_to_c64_matches_the_library_for_every_title(
        app, tmp_path, specimen_name, file_name, game):
    """`ConvertDialog` ▸ `DosToC64.rehearse`/`write` writes the same `.d64`
    bytes `goldbox.dos.new_save` + `goldbox.dos.save_disk` write directly for
    the same DOS source, the same icon/animate/portraits and the same slot --
    and reports the same drops. Proves requirements 1-4 of `#358`'s step 4 in
    one assertion each: the direction registered and offered is `DosToC64`,
    its destination is `game` -- the same title the source names, on the C64
    port, never a different one -- `rehearse` produces a report, the written
    bytes are identical to the library's own call, and the drops agree.
    """
    folder = _dos_specimen(specimen_name)
    if folder is None:
        pytest.skip(f"needs ~/wish-specimens/*-dos/WISH-SPEC-{specimen_name} "
                    f"(tools/specimens.py)")
    game_files = _c64_game_files(game)
    if game_files is None:
        pytest.skip(f"needs {game.title}'s own C64 disks, found through "
                    f"tools/gamedisks.py")

    source_path = (folder / file_name) if file_name else folder
    out = tmp_path / "out"
    dialog = convert.ConvertDialog(str(source_path), None,
                                   lambda g: game_files,
                                   destination="c64", folder=str(out))
    try:
        assert type(dialog.direction) is convert.DosToC64
        assert dialog.direction in convert.DIRECTIONS
        assert dialog.source.key == game.key
        assert dialog.direction.destination_game.key == game.key
        # First, not only: `#36 (Write an Amiga disk image, not just the
        # character files)` registered the two Amiga rows on 2026-09-07, so a
        # Pool of Radiance source now offers Amiga as well. What this line
        # guards is the order -- a player who presses Convert without looking
        # gets the destination `#26 (Write a DOS save, not just read one)`
        # proved, not whichever row was registered last.
        offered = [type(d) for d in convert.destinations_for(dialog.source)]
        assert offered[0] is convert.DosToC64, offered
        assert dialog.rehearsal is not None, dialog._blocked
        slot = dialog.source.slot
        written = dialog.direction.write(dialog.rehearsal,
                                         tmp_path / "dialog-write")
    finally:
        dialog.close()

    ref_save0, ref_save1, ref_report = dos.new_save(
        folder, slot, game_files.icon, game_files.animate,
        portraits=game_files.portraits, game=game)
    reference = dos.save_disk(bytes(ref_save0), bytes(ref_save1), game)

    assert len(written) == 1
    assert written[0].read_bytes() == reference.to_bytes()
    # **This line compares two empty lists on this direction today**, and says
    # so rather than looking like evidence it is not.  `DOS_TO_C64_NAMES`'
    # sibling `DROPPED_PLAYER_TEXT` is empty since Donald's ruling of
    # 2026-09-06 took its only two entries out, so `to_neutral` never drops a
    # sentence and nothing else on this path does either.  The byte comparison
    # above is what carries this test; the C64 -> DOS half of the file has
    # real lines in it and this assertion does real work there.  Found by the
    # review of `686fd61`.  It stops being vacuous the day a DOS -> C64
    # conversion drops anything, which is what it is here to catch.
    assert dialog.rehearsal.report.dropped == list(ref_report.dropped)


# ---------------------------------------------------------------------------
# C64 -> DOS, all three titles: the allowlisted fixture for Pool of Radiance,
# and the clean, engine-written `WISH-SPEC-curse-h-engine-resave` and
# `WISH-SPEC-ssb-d-engine-resave` C64 specimens for the other two.
# ---------------------------------------------------------------------------

C64_TO_DOS_CASES = [
    pytest.param(None, games.POOL_OF_RADIANCE, "POOLRAD",
                id="pool-of-radiance"),
    pytest.param("curse-h-engine-resave", games.CURSE_OF_THE_AZURE_BONDS,
                "CURSE", id="curse-of-the-azure-bonds"),
    pytest.param("ssb-d-engine-resave", games.SECRET_OF_THE_SILVER_BLADES,
                "SECRET", id="secret-of-the-silver-blades"),
]


@pytest.mark.parametrize("specimen_name, game, stem", C64_TO_DOS_CASES)
def test_c64_to_dos_matches_the_library_for_every_title(
        app, tmp_path, specimen_name, game, stem):
    """`ConvertDialog` ▸ `C64ToDos.rehearse`/`write` writes the same DOS
    files `goldbox.dos.new_dos_save` writes directly for the same C64 source,
    the same DOS game directory and slot `"A"` -- and reports the same drops.
    Same four requirements as the DOS -> C64 case above, mirrored: the
    direction is `C64ToDos`, its destination is `game`'s own DOS shape, never
    another title's.
    """
    try:
        game_dir = dosbox.find_game(stem)
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {game.title} archives ($FR_ARCHIVES)")

    if specimen_name is None:
        save0, save1 = _fixture_payloads()
        disk_path = tmp_path / "PORSAVE.D64"
        disk_path.write_bytes(dos.save_disk(save0, save1).to_bytes())
    else:
        disk_path = _c64_specimen(specimen_name)
        if disk_path is None:
            pytest.skip(f"needs ~/wish-specimens/*-c64/"
                        f"WISH-SPEC-{specimen_name}.D64 (tools/specimens.py)")
        source = convert.Source.detect(disk_path)
        save0, save1 = source.save0, source.save1

    shape = dos_layout.SHAPES_BY_KEY[game.key]
    out = tmp_path / "out"
    # An `icon=None` game-files stand-in -- no C64 disks handed to the
    # dialog for the source's own combat icon (`#383 (The live Convert
    # dialog never wires a C64 party's own combat icon into DOS, so
    # region_220 stays on the drop list)`'s own wiring, already proven in
    # `test_convert.py`); both sides of this comparison then take
    # `icon_parts=None`, the game's own default figure, so the two calls
    # stay comparable without a fourth disk search. `lambda g: None` would
    # answer no disks at all, which a C64 source now refuses for
    # (`#482 (With no game disks for the source title, a C64 party converted
    # to DOS or the Amiga silently arrives with no combat figures, though a
    # C64 destination refuses)`).
    dialog = convert.ConvertDialog(
        str(disk_path), None, lambda g: SimpleNamespace(icon=None),
        destination="dos", game=str(game_dir), folder=str(out))
    try:
        assert type(dialog.direction) is convert.C64ToDos
        assert dialog.direction in convert.DIRECTIONS
        assert dialog.source.key == shape.key
        assert dialog.direction.destination_game.key == shape.key
        # First, not only: `#36 (Write an Amiga disk image, not just the
        # character files)` registered the two Amiga rows on 2026-09-07, so a
        # Pool of Radiance source now offers Amiga as well. What this line
        # guards is the order -- a player who presses Convert without looking
        # gets the destination `#26 (Write a DOS save, not just read one)`
        # proved, not whichever row was registered last.
        offered = [type(d) for d in convert.destinations_for(dialog.source)]
        assert offered[0] is convert.C64ToDos, offered
        assert dialog.rehearsal is not None, dialog._blocked
        assert dialog.slot == "A"
        written = dialog.direction.write(dialog.rehearsal,
                                         tmp_path / "dialog-write")
    finally:
        dialog.close()

    reference_dir = tmp_path / "reference"
    ref_report = dos.new_dos_save(save0, save1, reference_dir, "A", game_dir,
                                  title=game)

    written_names = {p.name for p in written}
    reference_names = {p.name for p in reference_dir.iterdir()}
    assert written_names == reference_names
    for name in written_names:
        assert (tmp_path / "dialog-write" / name).read_bytes() == \
            (reference_dir / name).read_bytes()
    assert dialog.rehearsal.report.dropped == list(ref_report.dropped)

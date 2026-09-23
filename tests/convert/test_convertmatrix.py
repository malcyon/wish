"""Step 4 of `#358 (Finish the C64 ↔ DOS conversion matrix: six directions
registered, two defects and a question left)`: for every one of the six DOS
↔ C64 directions, the bytes `File ▸ Convert…`'s own code path writes --
`editor.convert.ConvertDialog` ▸ `Direction.rehearse` ▸ `Direction.write` --
are compared against the bytes the library's own entry point writes for the
same input, called directly (`goldbox.dos_codec.new_save`/`save_disk` for a DOS
source, `goldbox.dos_codec.new_dos_save` for a C64 one).

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)`'s own `tests/convert/test_convert.py` already proves this for
`DosToC64`/`C64ToDos` called directly for Pool of Radiance and for Curse of
the Azure Bonds (`test_dos_to_c64_direction_is_the_transfer_test`,
`test_curse_dos_to_c64_direction_is_the_transfer_test`,
`test_c64_to_dos_direction_is_the_transfer_test`) -- but never for Secret of
the Silver Blades in either direction, and never through the `ConvertDialog`
widget itself rather than the bare `Direction`. `tools/convert/convertrun.py`, which
built the six `*-52-dialog-converted-resave` specimens this module reads,
already drives the real dialog and an emulator; this is the byte-level half
that tool's own docstring says the transfer tests stand in for -- generalised
to all six directions in one place, since Secret of the Silver Blades had
none.

**Six of six directions run on this machine.** DOS → C64 reads a real DOS
save for each title (`~/wish-specimens`, `tools/registry/specimens.py`) and each
title's own C64 game disks (`automap/gamedisks.py`, never a hardcoded path);
Curse of the Azure Bonds and Secret of the Silver Blades resolved through
`/mnt/media/roms/c64/...`, on `gamedisks.yaml`'s own committed search list.
C64 → DOS reads a real C64 save for Curse and Silver Blades and the
allowlisted `tests/fixtures/savedgame0.bin`/`savedgame1.bin` for Pool of
Radiance -- `test_convert.py`'s own fixture, not a new one -- and each
title's DOS archive tree (`tools/dos/dosbox.find_game`, `$FR_ARCHIVES`). Every
`pytest.skip` below names what would be missing if this ran somewhere else.

**The specimen tree files every C64 and DOS specimen under `por-c64`/
`por-dos` regardless of title** -- `curse-h-engine-resave` and
`ssb-d-engine-resave` are `platform = "c64"` and their own title in
`provenance.toml`, physically inside `por-c64/`, where `tools/registry/specimens.py`'s
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

from automap import gamedisks
from editor import convert, dosimport, roster, saveplan
from goldbox import c64_port, dos_codec, dos_port
from goldbox.d64 import D64, load_payload
from goldbox.iconparts import IconParts, c64_icon_tables
from goldbox.layout import NAME_SIZE
from goldbox.portraits import PortraitError, tables_from_disks
from goldbox.savegame import SaveGame0, SaveGame1, load_save
from tools.convert import convertdrops
from tools.dos import dosbox

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


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


def _c64_game_files(game: "c64_port.Game") -> "dosimport.GameFiles | None":
    """The icon, `ANIMATE00` and the creation menu off `game`'s own C64
    disks, found through `automap/gamedisks.py` -- the project's own registry
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
                animate = load_payload(str(disk), dos_codec.ANIMATE_FILE)
            except Exception:
                pass
    if icon is None or animate is None:
        return None
    portraits = None
    if game.key == c64_port.POOL_OF_RADIANCE.key:
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
# specimens `tools/convert/convertrun.py` fed the dialog to build the three
# `*-52-dialog-converted-resave` C64 specimens this module's docstring names.
# ---------------------------------------------------------------------------

DOS_TO_C64_CASES = [
    pytest.param("por-party-l1-intown", None, c64_port.POOL_OF_RADIANCE,
                id="pool-of-radiance"),
    pytest.param("curse-131-dualclassed-in-area-1", None,
                c64_port.CURSE_OF_THE_AZURE_BONDS,
                id="curse-of-the-azure-bonds"),
    pytest.param("ssb-234-party-pair", "SAVGAMC.DAT",
                c64_port.SECRET_OF_THE_SILVER_BLADES,
                id="secret-of-the-silver-blades"),
]


@pytest.mark.parametrize("specimen_name, file_name, game", DOS_TO_C64_CASES)
def test_dos_to_c64_matches_the_library_for_every_title(
        app, tmp_path, specimen_name, file_name, game):
    """`ConvertDialog` ▸ `DosToC64.rehearse`/`write` writes the same `.d64`
    bytes `goldbox.dos_codec.new_save` + `goldbox.dos_codec.save_disk` write directly for
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
                    f"(tools/registry/specimens.py)")
    game_files = _c64_game_files(game)
    if game_files is None:
        pytest.skip(f"needs {game.title}'s own C64 disks, found through "
                    f"automap/gamedisks.py")

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

    ref_save0, ref_save1, ref_report = dos_codec.new_save(
        folder, slot, game_files.icon, game_files.animate,
        portraits=game_files.portraits, game=game)
    reference = dos_codec.save_disk(bytes(ref_save0), bytes(ref_save1), game)

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
    pytest.param(None, c64_port.POOL_OF_RADIANCE, "POOLRAD",
                id="pool-of-radiance"),
    pytest.param("curse-h-engine-resave", c64_port.CURSE_OF_THE_AZURE_BONDS,
                "CURSE", id="curse-of-the-azure-bonds"),
    pytest.param("ssb-d-engine-resave", c64_port.SECRET_OF_THE_SILVER_BLADES,
                "SECRET", id="secret-of-the-silver-blades"),
]


@pytest.mark.parametrize("specimen_name, game, stem", C64_TO_DOS_CASES)
def test_c64_to_dos_matches_the_library_for_every_title(
        app, tmp_path, specimen_name, game, stem):
    """`ConvertDialog` ▸ `C64ToDos.rehearse`/`write` writes the same DOS
    files `goldbox.dos_codec.new_dos_save` writes directly for the same C64 source,
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
        disk_path.write_bytes(dos_codec.save_disk(save0, save1).to_bytes())
    else:
        disk_path = _c64_specimen(specimen_name)
        if disk_path is None:
            pytest.skip(f"needs ~/wish-specimens/*-c64/"
                        f"WISH-SPEC-{specimen_name}.D64 (tools/registry/specimens.py)")
        source = convert.Source.detect(disk_path)
        save0, save1 = source.save0, source.save1

    shape = dos_port.DELTAS_BY_KEY[game.key]
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
    ref_report = dos_codec.new_dos_save(save0, save1, reference_dir, "A", game_dir,
                                  title=game)

    written_names = {p.name for p in written}
    reference_names = {p.name for p in reference_dir.iterdir()}
    assert written_names == reference_names
    for name in written_names:
        assert (tmp_path / "dialog-write" / name).read_bytes() == \
            (reference_dir / name).read_bytes()
    assert dialog.rehearsal.report.dropped == list(ref_report.dropped)


# ---------------------------------------------------------------------------
# `#511 (Open a DOS save folder and an Amiga save disk in the Character
# Editor, so editing a DOS character does not mean two conversions)`'s stage
# 4 condition: `File > Open` + `File > Save As` have to cover every
# registered direction "without losing any capability" before `File >
# Convert...` can go. `saveplan.prepare_save_as` is Save As's own route --
# `editor.window.EditorBinding.save_as` calls it the same way -- so this
# proves it for the same specimens the dialog byte-comparison above already
# exercises, plus the four Amiga directions that comparison does not cover.
#
# A case that raises `saveplan.SaveAsError` here is a real conversion defect
# (`.claude/rules/conversions.md`: refusing a save is not a fix), not
# something for this test to work around.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("specimen_name, file_name, game",
                         DOS_TO_C64_CASES)
def test_save_as_prepares_what_convert_writes_dos_to_c64(
        app, tmp_path, specimen_name, file_name, game):
    """`saveplan.prepare_save_as` returns a `SavePlan` for the same DOS
    source and C64 destination the dialog comparison above already writes,
    rather than raising `SaveAsError`."""
    folder = _dos_specimen(specimen_name)
    if folder is None:
        pytest.skip(f"needs ~/wish-specimens/*-dos/WISH-SPEC-{specimen_name} "
                    f"(tools/registry/specimens.py)")

    source_path = (folder / file_name) if file_name else folder
    party = roster.Party(str(source_path))
    try:
        assets = saveplan.resolve_assets(party.source, "c64",
                                         game_files=convertdrops.game_files)
    except saveplan.MissingAssets:
        pytest.skip(f"needs {game.title}'s own C64 disks, found through "
                    f"automap/gamedisks.py")

    plan = saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64", assets)
    assert isinstance(plan, saveplan.SavePlan)


@pytest.mark.parametrize("specimen_name, game, stem", C64_TO_DOS_CASES)
def test_save_as_prepares_what_convert_writes_c64_to_dos(
        app, tmp_path, specimen_name, game, stem):
    """The C64 -> DOS half of the same proof, for the same specimens the
    dialog comparison above already writes."""
    try:
        game_dir = dosbox.find_game(stem)
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {game.title} archives ($FR_ARCHIVES)")

    if specimen_name is None:
        save0, save1 = _fixture_payloads()
        disk_path = tmp_path / "PORSAVE.D64"
        disk_path.write_bytes(dos_codec.save_disk(save0, save1).to_bytes())
    else:
        disk_path = _c64_specimen(specimen_name)
        if disk_path is None:
            pytest.skip(f"needs ~/wish-specimens/*-c64/"
                        f"WISH-SPEC-{specimen_name}.D64 (tools/registry/specimens.py)")

    party = roster.Party(str(disk_path))
    # `Party.source` is `None` for a C64 disk -- the editor's own C64 party
    # carries no `Source`, unlike a DOS or an Amiga one -- so the route is
    # detected off the path directly, the same object `prepare_save_as`
    # itself builds from the open party's snapshot.
    source = party.source or convert.Source.detect(disk_path)
    try:
        assets = saveplan.resolve_assets(source, "dos",
                                         game_files=convertdrops.game_files,
                                         dos_folder=game_dir)
    except saveplan.MissingAssets:
        pytest.skip(f"needs {game.title}'s own C64 disks, found through "
                    f"automap/gamedisks.py")

    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "out", assets)
    assert isinstance(plan, saveplan.SavePlan)


# ---------------------------------------------------------------------------
# The four Amiga directions: `AmigaToC64`, `AmigaToDos`, `C64ToAmiga` and
# `DosToAmiga`, one instance per title in `goldbox.amiga_shared.CONVERTS`/
# `WRITES`. Specimens come from `tools/convert/convertdrops.sources`, which
# already knows how to turn the later titles' engine-written containers into
# disk images `Source.detect` accepts; the destination's own Amiga game data
# comes from `convertdrops.amiga_game_disks`.
# ---------------------------------------------------------------------------

_AMIGA_DIRECTIONS = [d for d in convert.DIRECTIONS
                     if type(d) in (convert.AmigaToC64, convert.AmigaToDos,
                                    convert.C64ToAmiga, convert.DosToAmiga)]


@pytest.mark.parametrize(
    "direction",
    [pytest.param(d, id=f"{type(d).__name__}-{d.shape.key}")
     for d in _AMIGA_DIRECTIONS])
def test_save_as_prepares_what_convert_writes_amiga_directions(
        app, tmp_path, direction):
    """The Amiga half of the same proof: a source of `direction`'s own port
    and title, found on this machine, prepares a `SavePlan` for `direction`'s
    destination rather than raising `SaveAsError`."""
    root = specimen_root()
    if root is None:
        pytest.skip("needs ~/wish-specimens (tools/registry/specimens.py)")
    scratch = tmp_path / "convertdrops-scratch"
    scratch.mkdir()

    source_path = None
    for candidate in convertdrops.sources(root, scratch):
        try:
            candidate_source = convert.Source.detect(candidate)
        except Exception:
            continue
        if (candidate_source.port == direction.source_port
                and candidate_source.key == direction.source_key):
            source_path = candidate
            break
    if source_path is None:
        pytest.skip(f"needs a {direction.source_port} specimen for "
                    f"{direction.shape.key} (tools/convert/convertdrops.sources)")

    party = roster.Party(str(source_path))
    source = party.source or convert.Source.detect(source_path)

    kwargs = {"game_files": convertdrops.game_files}
    if direction.destination_port == "dos":
        stem = convertdrops.DOS_DIRS.get(direction.shape.key)
        try:
            kwargs["dos_folder"] = dosbox.find_game(stem) if stem else None
        except FileNotFoundError:
            kwargs["dos_folder"] = None
    elif direction.destination_port == "amiga":
        kwargs["amiga_disk"] = convertdrops.amiga_game_disks(scratch).get(
            direction.shape.key)

    try:
        assets = saveplan.resolve_assets(source, direction.destination_port,
                                         **kwargs)
    except saveplan.MissingAssets as exc:
        pytest.skip(f"needs {', '.join(exc.missing)} for "
                    f"{direction.shape.title} ({direction.destination_port})")

    suffix = saveplan.DESTINATION_SUFFIX.get(direction.destination_port, "")
    plan = saveplan.prepare_save_as(
        party, direction.destination_port, tmp_path / f"out{suffix}", assets)
    assert isinstance(plan, saveplan.SavePlan)


# ---------------------------------------------------------------------------
# A dual-classed former paladin's cure-disease count. The C64 zeroes 0x012 for
# a class he has left and refills it to the full count for his old level when
# he regains the class, so a DOS count equal to that full count loses nothing.
# ---------------------------------------------------------------------------

def _former_paladin_write(former_level, cures):
    """A blank Curse DOS record made a magic-user 1 who left paladin at
    `former_level` holding `cures` uses, written to a C64 record."""
    from goldbox import c64_codec
    char = dos_codec.to_neutral(dos_codec.DosCharacter(
        bytes(dos_port.CURSE_OF_THE_AZURE_BONDS.record_size),
        deltas=dos_port.CURSE_OF_THE_AZURE_BONDS))
    char.set("levels", {"magic-user": 1}, "test")
    char.set("former_levels", {"paladin": former_level}, "test")
    char.set("paladin_cures", cures, "test")
    return c64_codec.write(char)


def test_a_dual_classed_former_paladin_at_his_full_count_loses_nothing():
    """MATHEW's state, synthetically: paladin 5 held 1 use, the full count."""
    rec, rep = _former_paladin_write(5, 1)
    assert rec.get("paladin_cures") == 0 and rec.get("lay_on_hands_uses") == 0
    assert not [x for x in rep.losses if "paladin_cures" in x]


def test_a_dual_classed_former_paladin_below_his_full_count_still_reports():
    """Paladin 6 holds 1 of his 2; the regain would give him 2, so the DOS
    state is not reproduced and the loss is kept."""
    rec, rep = _former_paladin_write(6, 1)
    assert rec.get("paladin_cures") == 0
    assert [x for x in rep.losses if "paladin_cures" in x]


@pytest.mark.parametrize("game", [dos_port.CURSE_OF_THE_AZURE_BONDS,
                                  dos_port.SECRET_OF_THE_SILVER_BLADES])
def test_a_regained_dos_paladin_writes_his_cure_count_to_the_c64(game):
    """Fighter 7 who left paladin at 6 is a paladin again: 0x012 holds 2."""
    from goldbox import c64_codec
    char = dos_codec.to_neutral(dos_codec.DosCharacter(
        bytes(game.record_size), deltas=game))
    char.set("levels", {"fighter": 7}, "test")
    char.set("level", 7, "test")
    char.set("former_levels", {"paladin": 6}, "test")
    char.set("paladin_cures", 2, "test")
    rec, rep = c64_codec.write(char)
    assert rec.to_bytes()[0x012] == 2
    assert not [x for x in rep.losses if "paladin_cures" in x]


def test_a_regained_paladin_specimen_goes_c64_to_dos_and_back(app, tmp_path):
    """MATHEW and MARK hold 2 and 1 uses on the C64 disk; the DOS folder made
    from it, saved as a C64 disk again, keeps both."""
    disk = _c64_specimen("curse-409-regained-paladin")
    if disk is None:
        pytest.skip("needs ~/wish-specimens/*-c64/"
                    "WISH-SPEC-curse-409-regained-paladin.d64")
    try:
        game_dir = dosbox.find_game("CURSE")
    except FileNotFoundError:
        pytest.skip("needs the DOS Curse of the Azure Bonds archives "
                    "($FR_ARCHIVES)")
    party = roster.Party(str(disk))
    source = party.source or convert.Source.detect(disk)
    try:
        assets = saveplan.resolve_assets(source, "dos",
                                         game_files=convertdrops.game_files,
                                         dos_folder=game_dir)
    except saveplan.MissingAssets:
        pytest.skip("needs the C64 Curse disks, found through "
                    "automap/gamedisks.py")
    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "dos", assets)
    folder = tmp_path / "dos"
    folder.mkdir()
    for name, data in plan.files.items():
        (folder / name).write_bytes(data)

    back = roster.Party(str(folder))
    try:
        assets = saveplan.resolve_assets(back.source, "c64",
                                         game_files=convertdrops.game_files)
    except saveplan.MissingAssets:
        pytest.skip("needs the C64 Curse disks, found through "
                    "automap/gamedisks.py")
    again = saveplan.prepare_save_as(back, "c64", tmp_path / "out.d64", assets)
    assert isinstance(again, saveplan.SavePlan)
    from support.doslatertitles import _c64_party
    (image,) = again.files
    (tmp_path / "read-back.d64").write_bytes(again.files[image])
    _game, chars = _c64_party(tmp_path / "read-back.d64")
    cures = {c.get("name"): c.get("paladin_cures") for c in chars}
    assert cures["MATHEW"] == 2 and cures["MARK"] == 1


def _mathew_in(chars):
    (mathew,) = [c for c in chars if c.get("name") == "MATHEW"]
    return mathew


def test_a_c64_former_paladin_specimen_converts_to_dos_at_his_full_count():
    """`WISH-SPEC-curse-52-dialog-converted-resave`'s MATHEW is a former
    paladin 5 who has not regained the class, so the C64 holds 0 for him;
    DOS never reseeds the byte, so it must hold the full count."""
    from support.doslatertitles import _c64_party
    disk = _c64_specimen("curse-52-dialog-converted-resave")
    if disk is None:
        pytest.skip("needs ~/wish-specimens/*-c64/WISH-SPEC-"
                    "curse-52-dialog-converted-resave")
    _game, chars = _c64_party(disk)
    mathew = _mathew_in(chars)
    assert mathew.get("paladin_cures") == 0
    assert not mathew.get("levels").get("paladin")
    rec, _itm, _spc, rep = dos_codec.write(mathew)
    at = dos_port.FIELDS_BY_NAME_FOR[mathew.game.key]["paladin_cures"].offset
    assert rec[at] == 1
    assert not [x for x in rep.dropped if "paladin_cures" in x]


def test_a_dual_classed_dos_paladin_holds_his_count_again_through_the_c64():
    from goldbox import c64_codec
    folder = _dos_specimen("curse-131-dualclassed-in-area-1")
    if folder is None:
        pytest.skip("needs ~/wish-specimens/*-dos/WISH-SPEC-"
                    "curse-131-dualclassed-in-area-1")
    char = dos_codec.to_neutral(dos_codec.read_character(
        folder / "CHRDATJ1.SAV"))
    at = dos_port.FIELDS_BY_NAME_FOR[char.game]["paladin_cures"].offset
    before, _, _, _ = dos_codec.write(char)
    assert before[at] == 1
    c64, _rep = c64_codec.write(char, payload=bytearray(0x4000), party_slot=0)
    again = c64_codec.read(c64, game=char.game)
    after, _, _, rep = dos_codec.write(again)
    assert after[at] == 1
    assert not [x for x in rep.dropped if "paladin_cures" in x]


def test_mathew_dual_classed_writes_zero_cure_bytes_and_no_loss():
    """`WISH-SPEC-curse-131-dualclassed-in-area-1`'s MATHEW (CHRDATJ1.SAV, a
    save found in the specimen tree): 0x012 and 0x013 zero, no cure row."""
    from goldbox import c64_codec
    folder = _dos_specimen("curse-131-dualclassed-in-area-1")
    if folder is None:
        pytest.skip("needs ~/wish-specimens/*-dos/WISH-SPEC-"
                    "curse-131-dualclassed-in-area-1")
    char = dos_codec.to_neutral(dos_codec.read_character(
        folder / "CHRDATJ1.SAV"))
    assert char.get("paladin_cures") == 1 and not char.get("levels").get("paladin")
    payload = bytearray(0x4000)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=0)
    raw = rec.to_bytes()
    assert rec.get("paladin_cures") == 0
    assert rec.get("lay_on_hands_uses") == 0
    assert raw[0x012] == 0 and raw[0x013] == 0
    assert not [x for x in rep.losses if "paladin_cures" in x]
    assert not [x for x in rep.warnings if "paladin_cures" in x]


@pytest.mark.parametrize("disk_name", ["TEST_DOS_IMPORT9.D64",
                                       "TEST_DOS_IMPORT8_FIXED.D64",
                                       "TEST_DOS_IMPORT6.D64",
                                       "TEST_DOS_IMPORT7.D64",
                                       "TEST_DOS_IMPORT8.D64"])
def test_a_c64_party_with_a_companion_saves_as_dos(app, tmp_path, disk_name):
    """The companion's template fill converts: the drain pair reaches DOS as
    the stored 0xFF and the dual-class pair as the writer's 0, and his combat
    figure is the seeded default's whether the disk holds it or holds zeros."""
    try:
        game_dir = dosbox.find_game("POOLRAD")
    except FileNotFoundError:
        pytest.skip("needs the DOS Pool of Radiance archives ($FR_ARCHIVES)")
    where = gamedisks.find(c64_port.POOL_OF_RADIANCE.key)
    disk_path = pathlib.Path(where) / disk_name if where else None
    if disk_path is None or not disk_path.exists():
        pytest.skip(f"needs {disk_name} in the Pool of Radiance folder")

    party = roster.Party(str(disk_path))
    source = party.source or convert.Source.detect(disk_path)
    try:
        assets = saveplan.resolve_assets(source, "dos",
                                         game_files=convertdrops.game_files,
                                         dos_folder=game_dir)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")

    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "out", assets)
    assert isinstance(plan, saveplan.SavePlan)

    def offset(name):
        return dos_port.FIELDS_BY_NAME[name].offset

    companions = [
        data for name, data in plan.files.items()
        if name.upper().startswith("CHRDAT") and name.upper().endswith(".SAV")
        and data[offset("levels_drained")] == 0xFF]
    assert companions, "no character file holds the companion's drain fill"
    for data in companions:
        assert data[offset("hp_lost_to_drain")] == 0xFF
        assert data[0x086:0x088] == b"\x00\x00"
        icon = assets.source_files.icon
        want = icon.dos_icon_from_c64(icon.default_icon(),
                                      c64_icon_tables(title=c64_port.POOL_OF_RADIANCE.key))
        assert (data[offset("icon_head")], data[offset("icon_body")],
                data[offset("icon_colours"):offset("icon_colours") + 6]) == (
                    want.head, want.body, bytes(want.colours))


# ---------------------------------------------------------------------------
# A party of seven: the roster the C64 save holds and the DOS save carries.
# ---------------------------------------------------------------------------

SEVEN_MEMBERS = 7


def test_a_seven_member_dos_party_saves_as_c64_with_all_seven(app, tmp_path):
    """`WISH-SPEC-issue641-dirten-seven-resave` (a seven-character DOS
    Pool of Radiance save the engine re-saved, slot B): Save As to a C64
    disk prepares a plan and the disk it writes holds all seven."""
    folder = _dos_specimen("issue641-dirten-seven-resave")
    if folder is None:
        pytest.skip("needs ~/wish-specimens/*-dos/"
                    "WISH-SPEC-issue641-dirten-seven-resave "
                    "(tools/registry/specimens.py)")
    party = roster.Party(str(folder))
    assert len(party.members) == SEVEN_MEMBERS
    try:
        assets = saveplan.resolve_assets(party.source, "c64",
                                         game_files=convertdrops.game_files)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks, found through "
                    "automap/gamedisks.py")

    plan = saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64", assets)

    (image,) = plan.files
    disk = tmp_path / "read-back.d64"
    disk.write_bytes(plan.files[image])
    _game, save0, _save1 = load_save(D64.open(str(disk)))
    written = [bytes(slot.window[:NAME_SIZE]).split(b"\0")[0]
               for slot in save0.slots if slot.window[0]]
    expected = [member.record.get("name").encode("ascii")
                for member in party.members]
    # The C64 marches in the reverse of the DOS order, so the seven are
    # compared as a set: what this pins is that none is lost.
    assert sorted(written) == sorted(expected)
    # DIRTEN is the seventh member, the one a six-file reader drops.
    assert expected[SEVEN_MEMBERS - 1] == b"DIRTEN"
    assert b"DIRTEN" in written


def test_a_seven_member_c64_party_saves_as_dos_with_all_seven(app, tmp_path):
    """`TEST_DOS_IMPORT9.D64` (a seven-character Pool of Radiance C64
    save): Save As to a DOS folder prepares a plan and the
    folder it writes holds seven character files."""
    try:
        game_dir = dosbox.find_game("POOLRAD")
    except FileNotFoundError:
        pytest.skip("needs the DOS Pool of Radiance archives ($FR_ARCHIVES)")
    where = gamedisks.find(c64_port.POOL_OF_RADIANCE.key)
    disk_path = pathlib.Path(where) / "TEST_DOS_IMPORT9.D64" if where else None
    if disk_path is None or not disk_path.exists():
        pytest.skip("needs TEST_DOS_IMPORT9.D64 in the Pool of Radiance folder")

    party = roster.Party(str(disk_path))
    source = party.source or convert.Source.detect(disk_path)
    try:
        assets = saveplan.resolve_assets(source, "dos",
                                         game_files=convertdrops.game_files,
                                         dos_folder=game_dir)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")

    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "out", assets)

    characters = [name for name in plan.files
                  if name.upper().startswith("CHRDAT")
                  and name.upper().endswith(".SAV")]
    assert len(characters) == SEVEN_MEMBERS, sorted(plan.files)
    # The seventh member arrives in the seventh file, under his own name,
    # rather than any seven files being present.
    for number, member in enumerate(party.members, start=1):
        record = tmp_path / f"CHRDATA{number}.SAV"
        record.write_bytes(plan.files[f"CHRDATA{number}.SAV"])
        assert dos_codec.read_character(record).name == member.record.get(
            "name")

"""An Amiga Pool of Radiance save becomes a DOS save folder.

`#354 (Convert an Amiga Pool of Radiance save to DOS, so a party standing in
the Slums on the Amiga arrives there under DOSBox)` -- the mirror of
`#353 (Convert an Amiga Pool of Radiance save to the C64, so a party standing
in the Slums on the Amiga arrives there in VICE)`, whose reading half this
direction reuses whole (`tests/test_amigatoc64.py` owns those tests).

**What is left for this file is the writing half**, and it is a shorter list
than `#353`'s because the destination is the port the Amiga record was
already shaped like: `goldbox.amiga.to_dos_record` re-cuts 288 Amiga bytes
into the 285 DOS ones, so a converted record can be compared with its source
field for field rather than through a codec. That comparison is the point of
this file -- `test_the_written_record_is_the_amiga_record` names every byte
that is allowed to differ and why, and a new difference fails.

**A conversion is not proven until it runs** (`.claude/rules/conversions.md`),
and none of this is that proof. Two DOSBox runs on 2026-09-07 are, and they
are on `#354`: the Slums party of `WISH-SPEC-por-amiga-slums-resave` slot C
arriving in area 20 at 14,4 facing west at 21:22, and the shipped Amiga disk
1 party arriving in New Phlan at 0,4 at 05:48 and walking out of it into the
Slums. What is here keeps that true afterwards.

Every test is a round trip of this project's own code, so the input's
provenance does not matter to the assertion (`.claude/rules/testing.md`).
The DOS game directory is needed for the party's own `ECL<n>.DAX` and the
tests skip without it.
"""

from __future__ import annotations

import pathlib

import pytest
from test_dossave import _save_dir, needs_dos_saves

from editor import convert
from goldbox import amiga_por, dos_codec, dos_port, dos_savegame, world_state
from goldbox.amiga_adf import AmigaDisk

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

def _game_dir() -> pathlib.Path:
    """The DOS game directory, the one holding `ECL<n>.DAX`: the save
    directory's parent, the way `tests/test_convert.py`'s own `_game_dir`
    finds it."""
    return _save_dir().parent


@pytest.fixture
def shipped_adf(tmp_path) -> pathlib.Path:
    """The player's Amiga Pool of Radiance disk 1, copied out as an `.adf`.

    A copy, because `Source.detect` takes a **path**, the player's own images
    are read-only to every test here, and the image on the media server lives
    inside a `.zip`. `tests/test_amigatoc64.py` owns the search and the
    reason it matches on the record's own 288 bytes rather than on the file
    names, so the two files cannot pick different disks.
    """
    from test_amigatoc64 import _pool_of_radiance_disk_1

    path = tmp_path / "por1.adf"
    path.write_bytes(_pool_of_radiance_disk_1().to_bytes())
    return path


@pytest.fixture
def one_character_adf(tmp_path) -> pathlib.Path:
    """`WISH-SPEC-por-amiga-dos-slums-resave` slot E, a party of **one**.

    `.claude/rules/conversions.md` asks for the extreme case as well as the
    typical one, and this is the only engine-written Amiga saved game this
    project has for a one-character party -- the case where
    `CHRDAT<slot>2`-`6` must not be written at all.
    """
    from tests import gamedata

    where = gamedata.specimen("por-amiga-dos-slums-resave", "amiga")
    path = tmp_path / "poolsave.adf"
    path.write_bytes((where / "poolsave-dos-after-E.adf").read_bytes())
    return path


def _direction() -> convert.AmigaToDos:
    return convert.AmigaToDos(dos_port.POOL_OF_RADIANCE)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def test_an_amiga_source_offers_dos_as_well_as_the_commodore_64(shipped_adf):
    """A player pointing `File ▸ Convert…` at an `.adf` is offered both
    ports, and the C64 stays first so the default is what `#353` proved."""
    source = convert.Source.detect(shipped_adf)
    directions = convert.destinations_for(source)
    assert [d.destination_port for d in directions] == ["c64", "dos"]
    assert type(directions[1]) is convert.AmigaToDos
    assert directions[1].destination_game is dos_port.POOL_OF_RADIANCE


def test_the_amiga_to_dos_row_takes_the_c64_to_dos_constructor():
    """`AmigaToDos` derives from `C64ToDos` for `__init__` and nothing else,
    the way `AmigaToC64` derives from `DosToC64`: the destination is the same
    DOS save folder written by the same engine, and only the source read
    differs. A copy of that constructor would be a second place for the
    `games.by_key` check that fails loudly at import time."""
    assert issubclass(convert.AmigaToDos, convert.C64ToDos)
    assert convert.AmigaToDos.rehearse is not convert.C64ToDos.rehearse
    assert convert.AmigaToDos.write is not convert.C64ToDos.write
    direction = _direction()
    assert direction.source_port == "amiga"
    assert direction.source_key == dos_port.POOL_OF_RADIANCE.key


def test_a_source_with_no_amiga_slot_is_refused_rather_than_guessed_at(
        shipped_adf):
    """Unreachable through the dialog, whose `.adf` branch always names a
    slot -- but a caller building a `Source` by hand must be refused rather
    than have a slot letter invented for it."""
    source = convert.Source(port="amiga", title=dos_port.POOL_OF_RADIANCE,
                            path=shipped_adf, slot=None)
    with pytest.raises(convert.ConvertError):
        _direction().rehearse(source, "A", _game_dir())


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

@needs_dos_saves
def test_the_rehearsal_writes_nothing(shipped_adf, tmp_path):
    """`goldbox.dos.new_dos_save_from` writes real files, so the rehearsal
    runs into a scratch directory the player never sees -- the same order
    `C64ToDos` follows."""
    source = convert.Source.detect(shipped_adf)
    _direction().rehearse(source, "A", _game_dir())
    assert [p.name for p in tmp_path.iterdir()] == ["por1.adf"]


@needs_dos_saves
def test_the_write_lands_only_in_its_own_folder(shipped_adf, tmp_path):
    source = convert.Source.detect(shipped_adf)
    direction = _direction()
    rehearsal = direction.rehearse(source, "A", _game_dir())

    outside = tmp_path / "elsewhere.txt"
    outside.write_text("untouched")
    destination = tmp_path / "out"
    written = direction.write(rehearsal, destination)

    assert {p.name for p in written} == set(rehearsal.files)
    assert outside.read_text() == "untouched"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "elsewhere.txt", "out", "por1.adf"]


@needs_dos_saves
def test_the_dos_slot_written_is_not_the_amiga_slot_read(one_character_adf,
                                                         tmp_path):
    """**Two slots, and they are not the same letter.** The Amiga slot is
    `source.slot` -- E on this disk -- and the DOS slot is what the dialog
    passes, always `A` for a fresh folder. Reading the wrong one converts
    whichever Amiga slot happens to share the DOS letter, which on this disk
    is a different party: slot D is `goldbox.amiga.write_por_slot`'s own
    output and slot E is the Amiga engine's resave of it."""
    source = convert.Source.detect(one_character_adf)
    assert source.slot == "D"          # the first slot the disk holds files for
    source.slot = "E"                  # the engine's own, the one to convert

    direction = _direction()
    rehearsal = direction.rehearse(source, "A", _game_dir())
    written = direction.write(rehearsal, tmp_path / "out")

    assert sorted(p.name for p in written) == [
        "CHRDATA1.ITM", "CHRDATA1.SAV", "CHRDATA1.SPC", "SAVGAMA.DAT"]
    # Slot E's own party, not slot D's: one character, and the name written
    # is his.
    party, _ = amiga_por.read_por_slot(AmigaDisk.open(str(one_character_adf)), "E")
    assert len(party) == 1
    written_name = dos_codec.DosCharacter(
        (tmp_path / "out" / "CHRDATA1.SAV").read_bytes()).name
    assert written_name == party[0].name


@needs_dos_saves
def test_a_party_of_one_writes_one_record_and_no_others(one_character_adf,
                                                        tmp_path):
    """The empty case `.claude/rules/conversions.md` asks for: a
    one-character party must leave `CHRDATA2`-`6` off the disk entirely, and
    the saved game's own name table must name one file rather than six --
    `#68 (A converted party smaller than the last one arrives with the
    remainder of that party still in it)` is what happens when it does not.
    """
    source = convert.Source.detect(one_character_adf)
    source.slot = "E"
    direction = _direction()
    rehearsal = direction.rehearse(source, "A", _game_dir())
    direction.write(rehearsal, tmp_path / "out")

    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    # The one character's record, the items he carries and the effects
    # running on him -- and nothing named CHRDATA2 to CHRDATA6.
    assert names == ["CHRDATA1.ITM", "CHRDATA1.SAV", "CHRDATA1.SPC",
                     "SAVGAMA.DAT"]
    savgam = (tmp_path / "out" / "SAVGAMA.DAT").read_bytes()
    assert dos_savegame.party_size(savgam) == 1
    # **All six names, and the party size is what says how many are read.**
    # The two ports part company here: `goldbox.amiga.retarget_savegame`
    # fills the Amiga table only as far as the party goes, and
    # `goldbox.dos_savegame.put_character_files` writes six because no DOS
    # specimen shows what a blanked entry does. So converting a party of one
    # is not converting a table of one.
    assert dos_savegame.character_files(savgam) == [
        f"CHRDATA{n}" for n in range(1, 7)]


@needs_dos_saves
def test_the_transfer_test_says_the_dialog_writes_what_the_library_writes(
        shipped_adf, tmp_path):
    """The bytes the dialog's Amiga → DOS row writes equal what
    `tools/fromamigapor.py --to dos` writes, calling `read_por_slot`,
    `read_por_state` and `goldbox.dos.new_dos_save_from` directly for the
    same slot -- so `#354`'s DOSBox proof stands for the dialog's own path
    too, which is the argument
    `test_c64_to_dos_direction_is_the_transfer_test` makes for the C64 row.
    """
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                           / "tools"))
    import fromamigapor

    source = convert.Source.detect(shipped_adf)
    direction = _direction()
    rehearsal = direction.rehearse(source, "A", _game_dir())
    destination = tmp_path / "out"
    direction.write(rehearsal, destination)

    reference = tmp_path / "reference"
    fromamigapor.build_dos(AmigaDisk.open(str(shipped_adf)), source.slot,
                           _game_dir(), reference, "A")

    written = {p.name for p in destination.iterdir()}
    assert written == {p.name for p in reference.iterdir()}
    for name in written:
        assert (destination / name).read_bytes() == \
            (reference / name).read_bytes(), name


# ---------------------------------------------------------------------------
# What arrived
# ---------------------------------------------------------------------------

@needs_dos_saves
def test_the_place_and_the_clock_are_the_amiga_saved_game_s(shipped_adf,
                                                            tmp_path):
    """The whole point of the ticket: not the six characters, which have
    crossed since 2026-08-26, but the game around them.

    Every field of `goldbox.world_state.WorldState` is compared, read back
    off the DOS container this wrote -- so a writer that stopped writing the
    quest flags, or the wallset, or the script scratch fails here rather than
    in DOSBox. `header` is the one exception and it is not a loss: Pool of
    Radiance copies none of the later titles' header words, and `$49FD` and
    `$49FE` are the two wall colours the arriving area's own ECL prologue
    writes on entry. The DOSBox run of 2026-09-07 watched the engine put the
    Slums' own 8 and 9 back into a save this wrote zero into.
    """
    source = convert.Source.detect(shipped_adf)
    direction = _direction()
    rehearsal = direction.rehearse(source, "A", _game_dir())
    direction.write(rehearsal, tmp_path / "out")

    disk = AmigaDisk.open(str(shipped_adf))
    _, savgam = amiga_por.read_por_slot(disk, source.slot)
    want = amiga_por.read_por_state(savgam, source=str(shipped_adf))
    got = world_state.from_dos(
        (tmp_path / "out" / "SAVGAMA.DAT").read_bytes(), source="written")

    for field in ("area", "geo", "x", "y", "facing", "clock", "wallset",
                  "flags", "scratch", "outdoors", "travel", "set_out"):
        assert getattr(got, field) == getattr(want, field), field
    assert got.header != want.header      # the two wall colours, above


@needs_dos_saves
def test_the_written_record_is_the_amiga_record(shipped_adf, tmp_path):
    """Every byte of every record, against the Amiga record it came from.

    The Amiga and DOS records are the same layout, so this is a byte
    comparison rather than a field-by-field one -- and it is masked by the
    writer's own declared lists rather than by whatever happened to differ,
    which is `.claude/rules/conversions.md`'s rule for a round trip. What is
    allowed to differ, and why:

    * `field_83_87` -- `goldbox.amiga.to_dos_record` writes those five bytes
      zero because the second insertion is not located, and the DOS writer
      writes the constant `00 00 01 00 00` that 101 of 101 engine-written
      Pool of Radiance records hold;
    * `unnamed_0ab` -- the identity byte, replaced by `identity_byte`'s
      digest rather than the Amiga record's own, which is
      `#378 (An Amiga character converted to DOS loses the identity byte his
      own record has always held)`;
    * `item_chain`, `hands_used`, `heap_104` -- live heap and combat state,
      `goldbox.dos.WRITE_UNSOURCED`, which the engine rebuilds on load.

    A new name in that set is a new loss and fails here.
    """
    source = convert.Source.detect(shipped_adf)
    direction = _direction()
    rehearsal = direction.rehearse(source, "A", _game_dir())
    direction.write(rehearsal, tmp_path / "out")

    allowed = {"field_83_87", "unnamed_0ab", "item_chain", "hands_used",
               "heap_104"}
    party, _ = amiga_por.read_por_slot(AmigaDisk.open(str(shipped_adf)),
                                   source.slot)
    assert len(party) == 6
    for n, char in enumerate(party, 1):
        want = char.to_bytes()
        got = (tmp_path / "out" / f"CHRDATA{n}.SAV").read_bytes()
        assert len(want) == len(got) == dos_port.POOL_OF_RADIANCE.record_size
        differing = {_field_at(i) for i in range(len(got))
                     if want[i] != got[i]}
        assert differing <= allowed, (char.name, sorted(differing - allowed))


def _field_at(offset: int) -> str:
    """Which Pool of Radiance record field covers `offset`."""
    for name, field in dos_port.FIELDS_BY_NAME.items():
        if field.offset <= offset < field.offset + field.size:
            return name
    return f"unnamed byte {offset:#05x}"


@needs_dos_saves
def test_the_party_arrives_with_its_own_combat_figures(shipped_adf, tmp_path):
    """**The figure a player drew on the Amiga is the figure DOS combat
    draws**, and it is the one thing in the record that does not reach the
    DOS writer through the neutral vocabulary.

    `goldbox.dos.to_neutral` has nowhere to put `icon_head`, `icon_body` and
    the six `icon_colours` bytes -- the C64 stores drawn cells rather than an
    index -- so a party read into neutral records and written straight back
    out arrives with six identical default figures, which is
    `#130 (A converted DOS party arrives with six identical combat figures,
    not its own)` in this direction. `editor.convert.amiga_combat_icon` is
    what stops it.

    **This fails without that argument**: drop the `icons=` from
    `AmigaToDos.rehearse` and every head and body below reads 0 and every
    colour block reads the game's own default, so both assertions go.
    """
    source = convert.Source.detect(shipped_adf)
    direction = _direction()
    rehearsal = direction.rehearse(source, "A", _game_dir())
    direction.write(rehearsal, tmp_path / "out")

    party, _ = amiga_por.read_por_slot(AmigaDisk.open(str(shipped_adf)),
                                   source.slot)
    heads, bodies = set(), set()
    for n, char in enumerate(party, 1):
        record = dos_codec.DosCharacter(
            (tmp_path / "out" / f"CHRDATA{n}.SAV").read_bytes())
        assert record.get("icon_head") == char.get("icon_head"), char.name
        assert record.get("icon_body") == char.get("icon_body"), char.name
        assert record.raw("icon_colours") == char.raw("icon_colours"), char.name
        heads.add(record.get("icon_head"))
        bodies.add(record.get("icon_body"))

    # Not one figure repeated six times, which is what #130 describes: the
    # shipped party names five distinct heads and five distinct bodies.
    assert len(heads) > 1 and len(bodies) > 1


@needs_dos_saves
def test_the_party_is_written_in_the_amiga_s_own_order(shipped_adf, tmp_path):
    """**No reversal here, and that is the difference from `#353`.** The
    Amiga lists a party in DOS file order -- `CHRDAT<letter>1` first -- so
    `CHRDATA1.SAV` is the Amiga's own `CHRDATA1.sav`. `#101`'s reversal, and
    `goldbox.dos.marching_slot`, are the C64's business: it displays the
    highest occupied slot first and the two lists really are reverses there.
    """
    source = convert.Source.detect(shipped_adf)
    direction = _direction()
    rehearsal = direction.rehearse(source, "A", _game_dir())
    direction.write(rehearsal, tmp_path / "out")

    party, _ = amiga_por.read_por_slot(AmigaDisk.open(str(shipped_adf)),
                                   source.slot)
    written = [dos_codec.DosCharacter(
        (tmp_path / "out" / f"CHRDATA{n}.SAV").read_bytes()).name
        for n in range(1, len(party) + 1)]
    assert written == [c.name for c in party]


@needs_dos_saves
def test_every_byte_of_the_saved_game_has_a_source(shipped_adf, tmp_path):
    """No template anywhere (`.claude/rules/conversions.md`): a byte with no
    source is a byte written zero by accident rather than by measurement, and
    `goldbox.dos.new_dos_save_from` raises rather than hand one back. This
    asserts the report says so rather than trusting the raise."""
    source = convert.Source.detect(shipped_adf)
    rehearsal = _direction().rehearse(source, "A", _game_dir())
    assert rehearsal.report.unwritten == []
    assert len(rehearsal.report.sources) == rehearsal.report.total


@needs_dos_saves
def test_the_shipped_amiga_party_is_shown_no_drop_lines(shipped_adf):
    """What a player reads, and for this party it is nothing at all.

    The Slums specimen shows two portrait lines instead, because its own
    sheet portrait position is 0 and nothing was lost --
    `#377 (The conversion pane says a portrait could not be converted for a
    character who never had one)`. Asserting the empty case here rather than
    both keeps this test about the direction rather than about `#377`.
    """
    source = convert.Source.detect(shipped_adf)
    rehearsal = _direction().rehearse(source, "A", _game_dir())
    assert rehearsal.report.dropped == []

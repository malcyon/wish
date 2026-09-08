from __future__ import annotations

"""Converting Amiga Pool of Radiance's combat figure from a C64 or DOS
source (#422 (A C64 party converted to an Amiga save disk arrives with no
combat figure at all, because C64ToAmiga never recognises it)).

`#396 (Whether an Amiga Curse or Silver Blades record's combat-icon fields
share DOS's own numbering is unmeasured)` and `#319 (The Amiga export's drop
line still says a conversion "does not carry" a combat icon)` already gave
`goldbox.amiga.write_later` an `icon` argument and wired it through
`editor.convert.amiga_combat_icon` for Curse and Silver Blades. This file is
the same fix for Pool of Radiance's own writer, `goldbox.amiga.write_por`,
which `#383 (The live Convert dialog never wires a C64 party's own combat
icon into DOS, so region_220 stays on the drop list)` proves the shape of on
the DOS side.

Two levels: `write_por` itself, against a synthetic character built by
`test_amiga.sample()` -- no disk needed -- and the live `C64ToAmiga`
direction and dialog, which need the source title's own `SPELLE64`/
`SPELLN64` to recognise a C64 icon and the player's own Amiga disk 2 for the
`ecl.dax` every Amiga save needs.
"""

import pathlib

import gamedata
import pytest
from test_amiga import sample
from test_convert import _six_icon_party
from test_toamigapor import _por_disk_2

from editor import convert, dosimport
from goldbox import dos, dos_layout, games
from goldbox.amiga import AmigaPorCharacter, write_por
from goldbox.iconparts import DosIcon

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

needs_dos_saves = pytest.mark.skipif(
    gamedata.disk_dir() is None,
    reason="needs the player's own POR*.d64; set $POR_DISKS")

FIGURE_NOT_SET = "figure is not set"


# ---------------------------------------------------------------------------
# `write_por` itself: no disk needed, `DosIcon` built by hand
# ---------------------------------------------------------------------------

def test_write_por_took_no_icon_argument_before_this_fix():
    """Regression marker: `write_por(char, icon=...)` raised `TypeError`
    before this ticket, because the parameter did not exist at all -- the
    second half of #422's root cause, distinct from #383's wiring-only half.
    Reverting `goldbox/amiga.py`'s `write_por` to `HEAD` and rerunning this
    file makes every test below fail at collection or at this call; this one
    names why.
    """
    icon = DosIcon(head=1, body=2, colours=bytes(6),
                   figure_source="test", colours_source="test")
    write_por(sample(), icon=icon)  # raises TypeError without the fix


def test_a_given_icon_writes_its_own_head_body_and_colours():
    icon = DosIcon(head=5, body=9, colours=bytes(range(1, 7)),
                   figure_source="test figure", colours_source="test colours")
    record, _, _, rep = write_por(sample(), icon=icon)
    char = AmigaPorCharacter.from_bytes(record)
    assert char.get("icon_head") == 5
    assert char.get("icon_body") == 9
    assert bytes(char.get("icon_colours")) == bytes(range(1, 7))
    assert not any(FIGURE_NOT_SET in d for d in rep.dropped), rep.dropped


def test_with_no_icon_the_figure_is_zero_as_before():
    """The default stays `None`, so a caller that gives `write_por` nothing
    -- every caller before this ticket -- sees exactly what it always did:
    the game's own zero figure. `sample()` has no C64 record behind it, so
    there is no `region_220` drop line to check here -- that line belongs
    to `goldbox.c64_codec.read`, and the direction-level tests below are
    where a real C64 source's own drop line is checked, both ways."""
    record, _, _, rep = write_por(sample())
    char = AmigaPorCharacter.from_bytes(record)
    assert char.get("icon_head") == 0
    assert char.get("icon_body") == 0
    assert not any(FIGURE_NOT_SET in d for d in rep.dropped), rep.dropped


# ---------------------------------------------------------------------------
# `C64ToAmiga`: the live direction, with a source whose six icons differ
# ---------------------------------------------------------------------------

@needs_dos_saves
def test_c64_to_amiga_direction_recognises_the_sources_own_combat_icon(
        tmp_path):
    """`C64ToAmiga.rehearse` takes the `icon_parts` `goldbox.dos.c64_party`
    always could, the way `C64ToDos.rehearse` already does (#383) -- and
    `goldbox.amiga.write_por` now has somewhere to put what it recognises.

    Watched failing before the fix: `C64ToAmiga.rehearse` took no
    `icon_parts` keyword at all (`TypeError`), and even patched to accept
    and discard one, every character's `(icon_head, icon_body)` read back
    `(0, 0)` because `write_por` had no `icon` parameter to hand it to.
    """
    from goldbox.amiga import AmigaDisk, read_por_slot

    save0, save1, parts = _six_icon_party()
    disk2 = _por_disk_2(tmp_path)
    source = convert.Source(port="c64", title=games.POOL_OF_RADIANCE,
                            path=pathlib.Path("SIX.D64"),
                            save0=save0, save1=save1)

    direction = convert.C64ToAmiga(dos_layout.POOL_OF_RADIANCE)
    rehearsal = direction.rehearse(source, "A", disk2, icon_parts=parts)
    assert not any(FIGURE_NOT_SET in d for d in rehearsal.report.dropped), \
        rehearsal.report.dropped

    out_dir = tmp_path / "out"
    direction.write(rehearsal, out_dir)
    out_disk = AmigaDisk.open(str(out_dir / convert.POOLSAVE_FILENAME))
    party, _savgam = read_por_slot(out_disk, "A")
    pairs = [(c.get("icon_head"), c.get("icon_body")) for c in party]
    assert len(set(pairs)) == 6, pairs


@needs_dos_saves
def test_c64_to_amiga_direction_with_no_icon_parts_still_converts(tmp_path):
    """A source the caller hands no icon table for -- no player disks, or a
    disk `IconParts.load` cannot read -- still writes a complete Amiga save;
    every figure is the game's own default and the drop line names it, as
    `C64ToDos`'s own fallback already documents for the DOS destination."""
    from goldbox.amiga import AmigaDisk, read_por_slot

    save0, save1, _parts = _six_icon_party()
    disk2 = _por_disk_2(tmp_path)
    source = convert.Source(port="c64", title=games.POOL_OF_RADIANCE,
                            path=pathlib.Path("SIX.D64"),
                            save0=save0, save1=save1)

    direction = convert.C64ToAmiga(dos_layout.POOL_OF_RADIANCE)
    rehearsal = direction.rehearse(source, "A", disk2)  # no icon_parts
    assert any(FIGURE_NOT_SET in d for d in rehearsal.report.dropped), \
        rehearsal.report.dropped

    out_dir = tmp_path / "out"
    direction.write(rehearsal, out_dir)
    out_disk = AmigaDisk.open(str(out_dir / convert.POOLSAVE_FILENAME))
    party, _savgam = read_por_slot(out_disk, "A")
    assert len(party) == 6
    pairs = [(c.get("icon_head"), c.get("icon_body")) for c in party]
    assert pairs == [(0, 0)] * 6, pairs


# ---------------------------------------------------------------------------
# `DosToAmiga`: a DOS source's own icon_head/icon_body/icon_colours, already
# a `DosIcon`-shaped number in the record (#424 (A DOS party converted to an
# Amiga save disk arrives with no combat figure either, though #422 says
# that route needs no fix))
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not gamedata.have_specimen("por-item-granted"),
                    reason="needs WISH-SPEC-por-item-granted")
def test_dos_to_amiga_direction_carries_the_sources_own_combat_icon(
        tmp_path):
    """`DosToAmiga.rehearse` used to hand `_rehearse_por_savegame` no
    `icons` at all -- `dos.to_neutral` has nowhere to put a combat figure,
    and the raw `DosCharacter` list `dos.read_party` returns was discarded
    before `write_por` ever saw it. `amiga_combat_icon` reads the figure off
    that raw record instead, the same shape `AmigaToDos.rehearse` already
    uses for an Amiga source.

    Watched failing before the fix: `(icon_head, icon_body) == (0, 0)`, read
    back off the written disk, for a specimen that carries its own flail and
    banded mail -- the measurement `#424`'s own issue body cites.
    """
    from goldbox.amiga import AmigaDisk, read_por_slot

    disk2 = _por_disk_2(tmp_path)
    folder = gamedata.specimen("por-item-granted")

    source = convert.Source.detect(folder / "SAVGAMD.DAT")
    assert source.port == "dos" and source.slot == "D"
    direction = convert.DosToAmiga(dos_layout.POOL_OF_RADIANCE)

    raw_party = dos.read_party(folder, "D")
    expected = [(c.get("icon_head"), c.get("icon_body")) for c in raw_party]
    assert expected != [(0, 0)] * len(expected), \
        "the specimen itself carries no combat icon -- pick a different one"

    rehearsal = direction.rehearse(source, "A", disk2)
    assert not any(FIGURE_NOT_SET in d for d in rehearsal.report.dropped), \
        rehearsal.report.dropped

    out_dir = tmp_path / "out"
    direction.write(rehearsal, out_dir)
    out_disk = AmigaDisk.open(str(out_dir / convert.POOLSAVE_FILENAME))
    party, _savgam = read_por_slot(out_disk, "D")
    pairs = [(c.get("icon_head"), c.get("icon_body")) for c in party]
    assert pairs == expected, pairs


# ---------------------------------------------------------------------------
# The dialog: `ConvertDialog._rehearse_and_report`'s branch reaches "amiga"
# ---------------------------------------------------------------------------

@needs_dos_saves
def test_the_dialog_wires_the_sources_own_combat_icon_into_an_amiga_convert(
        tmp_path):
    """`#422`'s own item 3: the `source_port == "c64"` branch that fetches
    `icon_parts` off the player's disks used to fire only for a DOS
    destination. The fake `game_files` lookup stands in for
    `editor.window.EditorBinding.game_files_for`, asked here for the
    *source*'s own title (Pool of Radiance) exactly as `#383`'s own dialog
    test asks it for the DOS direction.
    """
    from goldbox.amiga import AmigaDisk, read_por_slot
    from goldbox.iconparts import IconParts

    where = gamedata.disk_dir()

    def game_files_for(game):
        if game.key != games.POOL_OF_RADIANCE.key:
            return None
        icon = None
        for disk in sorted(where.glob("POOL*.[dD]64")):
            try:
                icon = IconParts.load(str(disk))
                break
            except Exception:
                continue
        if icon is None:
            return None
        return dosimport.GameFiles(icon=icon, animate=b"")

    save0, save1, _parts = _six_icon_party()
    disk_path = tmp_path / "SIX.D64"
    disk_path.write_bytes(dos.save_disk(save0, save1).to_bytes())
    disk2 = _por_disk_2(tmp_path)

    destination = tmp_path / "out"
    destination.mkdir()
    dialog = convert.ConvertDialog(str(disk_path), None, game_files_for,
                                   destination="amiga", disk=str(disk2),
                                   folder=str(destination))
    try:
        assert dialog.rehearsal is not None
        text = dialog.ui.convert_report.toPlainText()
        assert FIGURE_NOT_SET not in text, text
        final = tmp_path / "final"
        dialog.direction.write(dialog.rehearsal, final)
    finally:
        dialog.close()

    out_disk = AmigaDisk.open(str(final / convert.POOLSAVE_FILENAME))
    party, _savgam = read_por_slot(out_disk, "A")
    pairs = [(c.get("icon_head"), c.get("icon_body")) for c in party]
    assert len(set(pairs)) == 6, pairs

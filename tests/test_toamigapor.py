"""`tools/toamigapor.py`: a C64 or DOS party written into an Amiga save slot.

This is the direction `#105 (Write an Amiga Pool of Radiance character, not
just a Pools of Darkness one)` exists for, and on 2026-09-05 both halves of it
were loaded in Amiga Pool of Radiance under WinUAE -- the six C64 characters of
`WISH-SPEC-por-party-twin-pair` in slot B and the one DOS character of
`WISH-SPEC-por-item-granted` in slot D, each drawn on the party panel, the
character sheet and, where the character owned anything, the ITEMS screen.
`docs/182-amiga-por-in-the-running-game.md` carries the screenshots and the
byte-level comparisons.  What is here is what keeps that true afterwards.

Everything reads the Amiga disk out of `gamedisks.toml`'s `amiga` entry and the
parties out of `$WISH_SPECIMENS`, so nothing is committed and everything skips
on a machine that has neither.
"""

from __future__ import annotations

import hashlib
import pathlib

import pytest

from tests import gamedata

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# ---------------------------------------------------------------------------
# Finding a disk to write onto
# ---------------------------------------------------------------------------

def _por_disk_1(tmp_path: pathlib.Path) -> pathlib.Path:
    """A writable copy of an Amiga Pool of Radiance disk 1, or a skip.

    The images on this machine are inside `.zip`s, so `tools/amigasaves.py`'s
    reader is what gets at them.  The disk is identified by a `savgamA.dat` of
    Pool of Radiance's own length rather than by its file name, which differs
    between the four rips here -- and rather than by the name alone, because
    the Curse save disk carries a `save/savgamA.dat` too and it is 15221 bytes
    where this title's is 13141.
    """
    from goldbox.amiga import POR_SAVEGAME_SIZE
    from goldbox.amiga_adf import AmigaDisk
    from tools import amigasaves, gamedisks

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    for _name, data in amigasaves.images():
        try:
            disk = AmigaDisk(bytearray(data))
            savegame = disk.read_file("save/savgamA.dat")
        except Exception:
            continue
        if len(savegame) != POR_SAVEGAME_SIZE:
            continue
        where = tmp_path / "por1.adf"
        where.write_bytes(bytes(data))
        return where
    pytest.skip("no Amiga Pool of Radiance disk 1; set $AMIGA_DISKS")


def _por_disk_2(tmp_path: pathlib.Path) -> pathlib.Path:
    """A Pool of Radiance disk 2 image, or a skip.

    Needed since `#316 (Write the Amiga Pool of Radiance saved game from the
    source save, so a converted party arrives where it was standing)`: the
    saved game is built rather than copied, and the one part of it no
    character record holds is the area's own 7680-byte ECL script, which the
    Amiga keeps in a single `ecl.dax` on the `POOLDATA` volume.  Identified by
    carrying that file rather than by its name, which differs between rips.
    """
    from goldbox.amiga_adf import AmigaDisk
    from tools import amigasaves, gamedisks

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    for _name, data in amigasaves.images():
        try:
            AmigaDisk(bytearray(data)).read_file("/ecl.dax")
        except Exception:
            continue
        where = tmp_path / "por2.adf"
        where.write_bytes(bytes(data))
        return where
    pytest.skip("no Amiga Pool of Radiance disk 2; set $AMIGA_DISKS")


def _c64_specimen(name: str) -> pathlib.Path:
    """A C64 specimen disk, which is one file rather than a directory."""
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


def _read_slot(image: pathlib.Path, letter: str) -> list:
    """Every character of one slot on a disk, back through the reader."""
    import tempfile

    from goldbox import amiga
    from goldbox.amiga_adf import AmigaDisk, AmigaDiskError

    disk = AmigaDisk.open(image)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for index in range(1, amiga.POR_PARTY_MAX + 1):
            stem = f"/{amiga.POR_SAVE_DRAWER}/" \
                   f"{amiga.por_filename(letter, index, '')}"
            try:
                record = disk.read_file(stem + ".sav")
            except AmigaDiskError:
                break
            here = pathlib.Path(tmp) / f"{letter}{index}.sav"
            here.write_bytes(record)
            for suffix in (".itm", ".spc"):
                try:
                    here.with_suffix(suffix).write_bytes(
                        disk.read_file(stem + suffix))
                except AmigaDiskError:
                    pass
            out.append(amiga.to_neutral(amiga.read_amiga_por(here)))
    return out


# ---------------------------------------------------------------------------
# The two directions, each against the party the emulator actually loaded
# ---------------------------------------------------------------------------

def test_a_c64_party_reaches_an_amiga_slot_with_its_names_and_hit_points(
        tmp_path):
    """Six of six, and the six the Amiga's party panel drew on 2026-09-05.

    The hit points are the assertion that matters: they are the C64 record's
    own and nothing derives them, so a wrong offset anywhere in the
    transposition moves one.
    """
    from tools import toamigapor

    party = _c64_specimen("por-party-twin-pair")
    disk = _por_disk_1(tmp_path)
    out = tmp_path / "por1-B.adf"
    toamigapor.main([str(disk), "--to", "B", "--out", str(out),
                     "--data-disk", str(_por_disk_2(tmp_path)),
                     "--c64", str(party)])

    drawn = [(str(c.get("name")), c.get("hp_current"))
             for c in _read_slot(out, "B")]
    assert drawn == [("MALCYON", 4), ("TWIN", 4), ("ROLAND", 7),
                     ("LADY KATHERINE", 5), ("MAGNUS", 9), ("BRUTUS", 11)]


@pytest.mark.skipif(not gamedata.have_specimen("por-item-granted"),
                    reason="needs WISH-SPEC-por-item-granted")
def test_a_dos_character_reaches_an_amiga_slot_with_his_two_items(tmp_path):
    """THRENDER GRONE's flail and banded mail, which the Amiga ITEMS screen
    drew as `YES FLAIL` and `YES BANDED MAIL`."""
    from tools import toamigapor

    where = gamedata.specimen("por-item-granted")
    disk = _por_disk_1(tmp_path)
    out = tmp_path / "por1-D.adf"
    toamigapor.main([str(disk), "--to", "D", "--out", str(out),
                     "--data-disk", str(_por_disk_2(tmp_path)),
                     "--dos", str(where), "--dos-slot", "D"])

    party = _read_slot(out, "D")
    assert len(party) == 1
    assert str(party[0].get("name")) == "THRENDER GRONE"
    assert len(party[0].get("inventory") or []) == 2


def test_the_slot_letter_lands_in_its_own_byte_of_the_picker_list(tmp_path):
    """`save/save` is an array indexed by the slot letter (#109), so a party
    written into `D` puts `D` at byte 3 and leaves bytes 1 and 2 alone."""
    from goldbox import amiga
    from goldbox.amiga_adf import AmigaDisk
    from tools import toamigapor

    party = _c64_specimen("por-party-twin-pair")
    disk = _por_disk_1(tmp_path)
    out = tmp_path / "por1-D.adf"
    toamigapor.main([str(disk), "--to", "D", "--out", str(out),
                     "--data-disk", str(_por_disk_2(tmp_path)),
                     "--c64", str(party)])
    listed = AmigaDisk.open(out).read_file(amiga.POR_SLOT_LIST)
    assert listed == b"A  D      "


def test_a_space_in_a_name_is_written_through_to_the_amiga_record(tmp_path):
    """LADY KATHERINE keeps her space, and this test is here because the
    engine does not.

    Loaded in Amiga Pool of Radiance the panel reads `LADY KATHERINE`; camp,
    save, and the engine writes the record back as `LADYKATHERINE`, which the
    panel then draws -- `#308 (Does Amiga Pool of Radiance drop the space out of
    a character's name when it saves?)`.  The tempting
    repair is to strip the space on our side so the two agree.  That would
    lose it immediately instead of on the first save, and this fails if
    anybody does it.
    """
    from tools import toamigapor

    party = _c64_specimen("por-party-twin-pair")
    disk = _por_disk_1(tmp_path)
    out = tmp_path / "por1-B.adf"
    toamigapor.main([str(disk), "--to", "B", "--out", str(out),
                     "--data-disk", str(_por_disk_2(tmp_path)),
                     "--c64", str(party)])

    from goldbox.amiga_adf import AmigaDisk
    record = AmigaDisk.open(out).read_file("/save/CHRDATB4.sav")
    assert bytes(record[:16]) == b"LADY KATHERINE\x00\x00"


def test_the_input_disk_is_not_written(tmp_path):
    """`--out` is required and the image named on the command line is read
    only, because the next caller's will be the player's own."""
    from tools import toamigapor

    party = _c64_specimen("por-party-twin-pair")
    disk = _por_disk_1(tmp_path)
    before = hashlib.sha256(disk.read_bytes()).hexdigest()
    toamigapor.main([str(disk), "--to", "B", "--out", str(tmp_path / "o.adf"),
                     "--data-disk", str(_por_disk_2(tmp_path)),
                     "--c64", str(party)])
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == before


def test_the_saved_game_is_the_partys_own_place_and_not_the_disks(tmp_path):
    """The whole of #316, at the level a player would notice it.

    The Amiga disk this is written onto has one saved game on it, SSI's, and
    it stands at (0,4) facing west at 05:48 in New Phlan.  The C64 party is
    somewhere else at another time.  Before the saved game was built the
    converted party arrived on SSI's square at SSI's clock; this asserts it
    arrives on its own.
    """
    from goldbox import amiga, dos_savegame, games
    from goldbox.amiga_adf import AmigaDisk
    from goldbox.d64 import load_payload
    from tools import toamigapor

    party = _c64_specimen("porunconscious1")
    disk = _por_disk_1(tmp_path)
    out = tmp_path / "poolsave-B.adf"
    toamigapor.main([str(_por_disk_2(tmp_path)), "--to", "B",
                     "--save-disk", str(out), "--c64", str(party)])

    source = load_payload(str(party),
                          games.by_key("pool-of-radiance").save_file)
    state = amiga.por_state_from_c64(source, str(party))
    built = AmigaDisk.open(out).read_file("/savgamB.dat")
    shipped = AmigaDisk.open(disk).read_file("/save/savgamA.dat")

    assert (built[amiga.POR_POS_X], built[amiga.POR_POS_Y],
            built[amiga.POR_POS_FACING]) == (state.x, state.y,
                                             state.facing * 2)
    assert amiga.por_word(built, dos_savegame.SCRIPT) == state.area
    for i, digit in enumerate(state.clock):
        assert amiga.por_word(built, dos_savegame.CLOCK + i) == digit

    # And it is not the disk's, which is the failure this replaces: a
    # difference here means the party moved rather than that a byte drifted.
    assert built[amiga.POR_POS_X:amiga.POR_POS_FACING + 1] != \
        shipped[amiga.POR_POS_X:amiga.POR_POS_FACING + 1]
    start, end = amiga.POR_ECL_BUFFER
    assert built[start:end] != shipped[start:end]


def test_the_copied_container_is_still_reachable_and_says_so(tmp_path, capsys):
    """`--container` is an experiment rather than a conversion.

    It puts the party in somebody else's place on purpose -- which is what
    `tools/porslot.py` does between two Amiga slots -- so it stays, and the
    run says in words that the place is not the party's.
    """
    from goldbox import amiga
    from goldbox.amiga_adf import AmigaDisk
    from tools import toamigapor

    party = _c64_specimen("porunconscious1")
    disk = _por_disk_1(tmp_path)
    out = tmp_path / "por1-B.adf"
    toamigapor.main([str(disk), "--to", "B", "--out", str(out),
                     "--container", "A", "--c64", str(party)])
    assert "the place, the clock" in capsys.readouterr().out

    built = AmigaDisk.open(out).read_file("/save/savgamB.dat")
    shipped = AmigaDisk.open(disk).read_file("/save/savgamA.dat")
    assert built[amiga.POR_POS_X:amiga.POR_POS_FACING + 1] == \
        shipped[amiga.POR_POS_X:amiga.POR_POS_FACING + 1]


# ---------------------------------------------------------------------------
# Refusals, which need no game data at all
# ---------------------------------------------------------------------------

def test_two_sources_at_once_are_refused(tmp_path):
    from tools import toamigapor

    with pytest.raises(SystemExit) as caught:
        toamigapor.main([str(tmp_path / "x.adf"), "--to", "B",
                         "--out", str(tmp_path / "o.adf"),
                         "--c64", "a.d64", "--dos", "b"])
    assert "exactly one" in str(caught.value)


def test_no_source_at_all_is_refused(tmp_path):
    from tools import toamigapor

    with pytest.raises(SystemExit) as caught:
        toamigapor.main([str(tmp_path / "x.adf"), "--to", "B",
                         "--out", str(tmp_path / "o.adf")])
    assert "exactly one" in str(caught.value)


@pytest.mark.skipif(not gamedata.have_specimen("curse-234-before"),
                    reason="needs WISH-SPEC-curse-234-before")
def test_a_dos_curse_party_is_refused_before_any_conversion_work(tmp_path):
    """A conversion is between two ports of the same title.

    Pointing this at a DOS Curse folder used to print a full report that read
    like a working conversion and then die several calls down in `write_por`
    with `a DOS Pool of Radiance record is 285 bytes, got 422` -- a traceback
    naming a size, where what was wrong was the title.  `--c64` had this check
    from the start and `--dos` did not.
    """
    from tools import toamigapor

    where = gamedata.specimen("curse-234-before")
    disk = _por_disk_1(tmp_path)
    out = tmp_path / "por1-refused.adf"
    with pytest.raises(SystemExit) as raised:
        toamigapor.main([str(disk), "--to", "B", "--out", str(out),
                         "--dos", str(where), "--dos-slot", "C"])
    assert "Curse" in str(raised.value), raised.value
    assert not out.exists()


def test_the_input_disk_cannot_be_named_as_the_output(tmp_path):
    """A player's own disk given twice is refused before anything is written.

    `tools/porslot.py` has refused this from the start and said why: the
    player keeps their disks somewhere the script is pointed at by hand, so
    naming the same file as the source and the destination is a typo away.
    `tools/toamigapor.py` had no such guard, and either `--out` or
    `--save-disk` would have overwritten the disk it had just read.
    """
    import hashlib

    from tools import toamigapor

    disk = _por_disk_1(tmp_path)
    before = hashlib.sha256(disk.read_bytes()).hexdigest()
    for flag in ("--out", "--save-disk"):
        with pytest.raises(SystemExit) as raised:
            toamigapor.main([str(disk), "--to", "B", flag, str(disk),
                             "--c64", str(_c64_specimen("por-party-twin-pair"))])
        assert "input disk" in str(raised.value), raised.value
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == before

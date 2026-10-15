"""A companion who joined on the C64 converts to DOS and to the Amiga.

The C64 Curse join copies his `MON` file, so his portrait and dual-class bytes
hold `$FF`, and leaves his slot's icon as it was. DOS and the Amiga draw a
joined companion as his picture, and their own joins copy his `MON*CHA.DAX` or
`MONCHA.GLB` record: portrait `$FF`, former classes zero, icon zero. So a
converted companion gets the bytes the destination's own join writes, and the
icon his destination never draws is not a loss. The tests read the player's
own disks, the DOS archive and the specimen tree, and skip without them.
"""

from __future__ import annotations

import functools
import pathlib
import struct

import gamedata
import pytest
from gamedata import specimen_root
from PyQt6.QtWidgets import QApplication

from editor import convert, roster, saveplan
from goldbox import amiga_later, c64_codec, dos_codec, dos_port, dos_savegame
from goldbox.companions import (
    COMPANION_FILL,
    CURSE_KEY,
    JOIN_ICON,
    JOINABLE,
    MON_SIZE,
    Companions,
    companion_fill,
)
from goldbox.d64 import D64, split_load_address
from goldbox.dos_codec import FIELDS_BY_NAME_FOR
from goldbox.iconparts import IconParts, c64_icon_tables
from tools.convert import convertdrops
from tools.dos import dosbox

NATIVE_JOIN = "c64-join-alias-dragonbait-wish388"
DOS_JOIN = "curse-pit-join-alias-dragonbait-dos"
DOS_JOIN_FILES = {"ALIAS": "CHRDATD7.SAV", "DRAGONBAIT": "CHRDATD8.SAV"}
COMPANIONS = ("ALIAS", "DRAGONBAIT")
MON_OF = {"ALIAS": 0x16, "DRAGONBAIT": 0x17}
#: The DOS record fields each join sets for a companion, and that a converted
#: one must match.
JOIN_FIELDS = ("portrait_head", "portrait_body", "former_level",
               "former_class_levels", "icon_head", "icon_body",
               "icon_colours", "unnamed_0ab")
CURSE_DOS = dos_port.CURSE_OF_THE_AZURE_BONDS
TABLE = FIELDS_BY_NAME_FOR[CURSE_KEY]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _native_join() -> pathlib.Path:
    root = specimen_root()
    found = list(root.glob(f"*-c64/WISH-SPEC-{NATIVE_JOIN}.[dD]64")) if root else []
    if not found:
        pytest.skip(f"needs specimen WISH-SPEC-{NATIVE_JOIN}")
    return found[0]


@functools.lru_cache(maxsize=None)
def _table() -> Companions:
    return Companions.load(CURSE_KEY, gamedata.curse_disks())


def _field(record: bytes, name: str, at=lambda offset: offset) -> bytes:
    f = TABLE[name]
    return bytes(record[at(f.offset):at(f.offset) + f.size])


def _dos_join(name: str) -> dict[str, bytes]:
    folder = gamedata.specimen(DOS_JOIN)
    record = (pathlib.Path(folder) / DOS_JOIN_FILES[name]).read_bytes()
    return {f: _field(record, f) for f in JOIN_FIELDS}


def _prepare(app, tmp_path, dest: str):
    disk = _native_join()
    party = roster.Party(str(disk))
    source = party.source or convert.Source.detect(disk)
    kwargs = {"game_files": convertdrops.game_files}
    if dest == "dos":
        try:
            kwargs["dos_folder"] = dosbox.find_game("CURSE")
        except FileNotFoundError:
            pytest.skip("needs the DOS Curse archive ($FR_ARCHIVES)")
    else:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        kwargs["amiga_disk"] = convertdrops.amiga_game_disks(scratch).get(CURSE_KEY)
        kwargs["amiga_disk_one"] = convertdrops.amiga_disks_one(scratch).get(CURSE_KEY)
    try:
        assets = saveplan.resolve_assets(source, dest, **kwargs)
    except saveplan.MissingAssets as exc:
        pytest.skip(f"needs {', '.join(exc.missing)}")
    suffix = saveplan.DESTINATION_SUFFIX.get(dest, "")
    # Fails without the fix: DroppedFields for the combat figure, the
    # dual-class pair and the portrait head.
    return saveplan.prepare_save_as(party, dest, tmp_path / f"out{suffix}",
                                    assets)


def test_a_c64_joined_companion_saves_as_dos_with_the_dos_joins_bytes(
        app, tmp_path):
    plan = _prepare(app, tmp_path, "dos")
    assert isinstance(plan, saveplan.SavePlan)
    seen = set()
    for name, data in plan.files.items():
        if not (name.upper().startswith("CHRDAT")
                and name.upper().endswith(".SAV")):
            continue
        who = data[1:1 + data[0]].decode("latin-1")
        if who in COMPANIONS:
            seen.add(who)
            assert {f: _field(data, f) for f in JOIN_FIELDS} == _dos_join(who)
    assert seen == set(COMPANIONS)


def test_a_c64_joined_companion_saves_as_amiga_with_the_amiga_joins_bytes(
        app, tmp_path):
    plan = _prepare(app, tmp_path, "amiga")
    assert isinstance(plan, saveplan.SavePlan)
    deltas = amiga_later.CURSE_DELTAS
    fill = companion_fill(CURSE_KEY, "Amiga")
    head, body, colours = JOIN_ICON[CURSE_KEY]
    seen = set()
    for name, data in plan.files.items():
        written = tmp_path / f"written-{name}"
        written.write_bytes(data)
        for member in roster.Party(convert.Source.detect(written)).members:
            raw = member.native.raw
            who = raw[:16].split(b"\0")[0].decode("latin-1")
            if who not in COMPANIONS:
                continue
            seen.add(who)

            def get(f):
                return _field(raw, f, deltas.offset)
            assert get("portrait_head")[0] == fill["portrait_head"]
            assert get("portrait_body")[0] == fill["portrait_body"]
            assert not any(get("former_class_levels"))
            assert get("former_level") == b"\0"
            assert (get("icon_head")[0], get("icon_body")[0],
                    get("icon_colours")) == (head, body, colours)
            assert get("unnamed_0ab") == _dos_join(who)["unnamed_0ab"]
    assert seen == set(COMPANIONS)


def test_a_dos_joined_companion_gets_the_c64_joins_bytes():
    """C64 to DOS and back gives the companion the bytes he started with."""
    folder = gamedata.specimen(DOS_JOIN)
    table = _table()
    fill = companion_fill(CURSE_KEY, "C64")
    for char in dos_codec.read_party(folder, "D"):
        neutral = dos_codec.to_neutral(char)
        rec, rep = c64_codec.write(neutral, icon=table.default_icon,
                                   companions=table)
        raw = rec.to_bytes()
        if str(neutral.get("name")) in COMPANIONS:
            # Fails without the fix: 0 in all four.
            assert (raw[0x0FE], raw[0x0FF], raw[0x0B9], raw[0x0BA]) == (
                fill["portrait_head"], fill["portrait_body"],
                fill["dual_class_slot"], fill["dual_class_level"])
        else:
            assert raw[0x0FE] != 0xFF and raw[0x0BA] != 0xFF


def test_the_c64_joins_fill_reads_as_no_class_left():
    """The `$FF` pair is the join's fill, not a class the companion left."""
    disk = _native_join()
    from goldbox.d64 import D64
    from goldbox.savegame import load_save
    game, save0, save1 = load_save(D64.open(disk))
    names = set()
    for slot in save0.characters:
        neutral = dos_codec.c64_member_neutral(
            save0.to_bytes(), save1.to_bytes(), game, slot.index)
        name = str(neutral.get("name"))
        if name in COMPANIONS:
            names.add(name)
            assert slot.record.get("dual_class_level") == 0xFF
            assert neutral.get("former_levels") == {}
            assert not [w for w in neutral.warnings if "dual_class" in w]
    assert names == set(COMPANIONS)


def test_a_zero_curse_icon_entry_converts_as_the_seeded_default():
    """A player's all-zero entry is the default `INIT` seeds, not a loss."""
    disk = _native_join()
    from goldbox.d64 import D64
    from goldbox.savegame import load_save
    game, save0, save1 = load_save(D64.open(disk))
    raw0 = bytearray(save0.to_bytes())
    player = next(s for s in save0.characters
                  if s.record.get("name") not in COMPANIONS)
    at = game.icon(player.index)
    raw0[at:at + game.icon_size] = bytes(game.icon_size)
    parts = next(IconParts.load(side) for side in gamedata.curse_disks()
                 if side.find(b"SPELLE64") and side.find(b"SPELLN64"))
    want = parts.dos_icon_from_c64(parts.default_icon(),
                                   c64_icon_tables(title=CURSE_KEY))
    characters, icons = dos_codec.c64_party(
        bytes(raw0), save1.to_bytes(), game, icon_parts=parts,
        companions=_table())
    note = c64_codec.READ_DROPPED_PLAYER_TEXT["region_220"]
    by_name = {str(c.get("name")): (c, i) for c, i in zip(characters, icons)}
    char, icon = by_name[str(player.record.get("name"))]
    # Fails without the fix: no icon, and the drop line stays.
    assert icon is not None
    assert (icon.head, icon.body, icon.colours) == (
        want.head, want.body, want.colours)
    assert note not in char.dropped
    for name in COMPANIONS:
        char, icon = by_name[name]
        assert note not in char.dropped
        assert (icon.head, icon.body, icon.colours) == JOIN_ICON[CURSE_KEY]


def test_the_c64_fill_is_what_every_joinable_mon_file_holds():
    fill = COMPANION_FILL[CURSE_KEY]["C64"]
    offsets = {"portrait_head": 0x0FE, "portrait_body": 0x0FF,
               "dual_class_slot": 0x0B9, "dual_class_level": 0x0BA}
    for mon_id in JOINABLE[CURSE_KEY]:
        stem = f"MON{mon_id:02X}".encode()
        side = next(d for d in gamedata.curse_disks() if d.find(stem))
        payload = split_load_address(side.read_file(stem))[1]
        assert len(payload) == MON_SIZE
        assert {f: payload[o] for f, o in offsets.items()} == fill


def test_the_dos_fill_is_what_every_joinable_dos_record_holds():
    try:
        game = pathlib.Path(dosbox.find_game("CURSE"))
    except FileNotFoundError:
        pytest.skip("needs the DOS Curse archive ($FR_ARCHIVES)")
    fill = COMPANION_FILL[CURSE_KEY]["DOS"]
    head, body, colours = JOIN_ICON[CURSE_KEY]
    found = set()
    for path in sorted(game.glob("MON*CHA.DAX")):
        for block_id, record in dos_savegame.dax_blocks(path.read_bytes(),
                                                        path.name):
            if block_id not in JOINABLE[CURSE_KEY]:
                continue
            found.add(block_id)
            assert _field(record, "portrait_head")[0] == fill["portrait_head"]
            assert _field(record, "portrait_body")[0] == fill["portrait_body"]
            assert not any(_field(record, "former_class_levels"))
            assert (_field(record, "icon_head")[0],
                    _field(record, "icon_body")[0],
                    _field(record, "icon_colours")) == (head, body, colours)
    assert found == set(JOINABLE[CURSE_KEY])


def _glib_records(data: bytes) -> list[bytes]:
    """Every block of an Amiga `MONCHA.GLB`: a GLIB table of offsets, each
    block run-length coded with a repeat of 257 less the count byte."""
    count = int.from_bytes(data[8:10], "big")
    offsets = struct.unpack_from(f">{count + 1}I", data, 16)
    out = []
    for n in range(1, count):
        block, record, i = data[offsets[n]:offsets[n + 1]], bytearray(), 0
        while i < len(block):
            if block[i] < 0x80:
                record += block[i + 1:i + 2 + block[i]]
                i += block[i] + 2
            else:
                record += bytes([block[i + 1]]) * (257 - block[i])
                i += 2
        out.append(bytes(record))
    return out


def test_the_amiga_fill_is_what_every_joinable_amiga_record_holds():
    """`/Curse 0x26306` loads a companion's `MONCHA.GLB` record, a DOS-layout
    record, and `0x270A6` copies these bytes unchanged."""
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves
    data = None
    for _label, image in amigasaves.images():
        try:
            data = AmigaDisk(bytearray(image)).read_file("/DISKB/MONCHA.GLB")
            break
        except Exception:
            continue
    if data is None:
        pytest.skip("needs the Amiga Curse disk B")
    fill = COMPANION_FILL[CURSE_KEY]["Amiga"]
    head, body, colours = JOIN_ICON[CURSE_KEY]
    names = {_table().monsters[m].name for m in JOINABLE[CURSE_KEY]}
    found = set()
    for record in _glib_records(data):
        assert len(record) == CURSE_DOS.record_size
        name = record[1:1 + record[0]].decode("latin-1")
        if name not in names:
            continue
        found.add(name)
        assert _field(record, "portrait_head")[0] == fill["portrait_head"]
        assert _field(record, "portrait_body")[0] == fill["portrait_body"]
        assert not any(_field(record, "former_class_levels"))
        assert (_field(record, "icon_head")[0], _field(record, "icon_body")[0],
                _field(record, "icon_colours")) == (head, body, colours)
    assert found == names


AMIGA_PIT_SAVE = "curse-c64join-alias-dragonbait-amiga-pit-save"
C64_JOIN_DOS_RESAVE = "curse-c64join-alias-dragonbait-dos-resave"


def _disk_mon(mon: int) -> bytes:
    """`MON<mon>`'s payload read straight off the player's Curse side that holds it."""
    for side in gamedata.curse_disks():
        entry = side.find(f"MON{mon:02X}".encode())
        if entry is not None:
            return split_load_address(side.read_file(entry))[1]
    pytest.skip(f"needs MON{mon:02X} on a Curse side")


def _disk_default_icon() -> bytes:
    """The icon the C64's own join leaves in a joined companion's slot, composed
    from the player's side that carries the icon tables."""
    return next(IconParts.load(side).default_icon()
                for side in gamedata.curse_disks()
                if side.find(b"SPELLE64") and side.find(b"SPELLN64"))


def _save_as_c64(app, tmp_path, source_path, slot):
    """What Save As to the C64 writes for the party in `source_path`."""
    from goldbox.savegame import load_save
    source = convert.Source.detect(pathlib.Path(source_path), slot=slot)
    party = roster.Party(source)
    try:
        assets = saveplan.resolve_assets(
            source, "c64", game_files=convertdrops.game_files)
    except saveplan.MissingAssets as exc:
        pytest.skip(f"needs {', '.join(exc.missing)}")
    plan = saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64", assets)
    assert isinstance(plan, saveplan.SavePlan)
    (data,) = plan.files.values()
    return load_save(D64.from_bytes(data))


def _assert_the_c64_figure(app, tmp_path, source_path, slot=None) -> None:
    """Save As to the C64 gives each companion his own figure.

    The story byte is what his `MON` file holds at `0x0E5`, read here off the
    disk; the picture at `0x0E6` is the file's own number, since the file holds
    the join's `$FF` fill there; `0x0E7` holds the converted mark; the size
    byte is 1; and his icon entry is the default the C64 join leaves, composed
    here from the disk's own icon tables.
    """
    game, save0, _save1 = _save_as_c64(app, tmp_path, source_path, slot)
    raw0 = save0.to_bytes()
    icon = _disk_default_icon()
    seen = set()
    for member in save0.characters:
        name = str(member.record.get("name"))
        if name not in COMPANIONS:
            continue
        seen.add(name)
        mon = _disk_mon(MON_OF[name])
        record = member.record.to_bytes()
        assert (record[0x0E5], record[0x0E6], record[0x0E7]) == (
            mon[0x0E5], MON_OF[name], 0x01), name
        assert record[0x099] == 1, name
        at = game.icon(member.index)
        assert raw0[at:at + game.icon_size] == icon, name
    assert seen == set(COMPANIONS)


def test_a_c64_joined_companion_through_dos_comes_back_with_his_c64_figure(
        app, tmp_path):
    """Specimen: the native C64 join, to DOS as Wish writes it, to the C64."""
    plan = _prepare(app, tmp_path, "dos")
    folder = tmp_path / "dos"
    folder.mkdir()
    for name, data in plan.files.items():
        (folder / name).write_bytes(data)
    # Fails without the story write in c64_codec.write: 0x0E5 stays 0.
    _assert_the_c64_figure(app, tmp_path, folder)


def test_a_c64_joined_companion_through_the_amiga_comes_back_with_his_c64_figure(
        app, tmp_path):
    """Specimen: the native C64 join, to the Amiga as Wish writes it, to the C64."""
    plan = _prepare(app, tmp_path, "amiga")
    (name, data), = plan.files.items()
    written = tmp_path / name
    written.write_bytes(data)
    _assert_the_c64_figure(app, tmp_path, written)


def test_the_amiga_games_own_save_of_a_c64_joined_party_converts_to_the_c64_figure(
        app, tmp_path):
    """Specimen: Amiga Curse's own save (slot B) of a party that joined on the C64.

    Slot A was written by Wish and slot B by the running Amiga game, which
    loaded A and saved; the specimen's provenance records both.
    """
    folder = gamedata.specimen(AMIGA_PIT_SAVE, "amiga")
    _assert_the_c64_figure(app, tmp_path, folder / "fetched-save.adf", "B")


def test_the_dos_games_own_resave_of_a_c64_joined_party_converts_to_the_c64_figure(
        app, tmp_path):
    """Specimen: DOS Curse's own resave of a party that joined on the C64."""
    folder = gamedata.specimen(C64_JOIN_DOS_RESAVE)
    _assert_the_c64_figure(app, tmp_path, folder, "D")


SSB_KEY = "secret-of-the-silver-blades"
SIR_DERIC_SPECIMEN = "WISH-SPEC-ssb-sir-deric-joined-s2b"


def _sir_deric_specimen() -> pathlib.Path:
    """Silver Blades' own save (a game-written disk, the provenance records
    the run) taken after SIR DERIC joined on arriving in the Compound."""
    root = specimen_root()
    found = list(root.glob(f"ssb-c64/{SIR_DERIC_SPECIMEN}.[dD]64")) if root else []
    if not found:
        pytest.skip(f"needs specimen {SIR_DERIC_SPECIMEN}")
    return found[0]


def test_a_silver_blades_companion_through_dos_comes_back_with_his_c64_figure(
        app, tmp_path):
    """Specimen: SIR DERIC joined on the C64 (the game's own save), to DOS as
    Wish writes it, back to the C64.

    His picture, story byte and default icon are all read off the player's own
    Silver Blades disks, not hard-coded.
    """
    from support.silverblades import ssb_disks
    sides = ssb_disks()
    companions = Companions.load(SSB_KEY, sides)
    mon = companions.match("SIR DERIC")
    assert mon is not None
    picture = companions.picture_for(mon)
    icon = next(IconParts.load(side).default_icon() for side in sides
                if side.find(b"SPELLE64") and side.find(b"SPELLN64"))

    disk = _sir_deric_specimen()
    party = roster.Party(str(disk))
    source = party.source or convert.Source.detect(disk)
    try:
        assets = saveplan.resolve_assets(
            source, "dos", game_files=convertdrops.game_files,
            dos_folder=dosbox.find_game("SECRET"))
    except FileNotFoundError:
        pytest.skip("needs the DOS Silver Blades archive ($FR_ARCHIVES)")
    except saveplan.MissingAssets as exc:
        pytest.skip(f"needs {', '.join(exc.missing)}")
    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "out", assets)
    assert isinstance(plan, saveplan.SavePlan)
    dos = tmp_path / "dos"
    dos.mkdir()
    table = FIELDS_BY_NAME_FOR[SSB_KEY]
    deric = None
    for name, data in plan.files.items():
        (dos / name).write_bytes(data)
        if (name.upper().startswith("CHRDAT") and name.upper().endswith(".SAV")
                and data[1:1 + data[0]] == b"SIR DERIC"):
            deric = data
    assert deric is not None
    assert deric[table["unnamed_0ab"].offset] == picture

    game, save0, _save1 = _save_as_c64(app, tmp_path, dos, None)
    raw0 = save0.to_bytes()
    (member,) = [m for m in save0.characters
                 if str(m.record.get("name")) == "SIR DERIC"]
    record = member.record.to_bytes()
    # Fails without the picture write in c64_codec.write: 0x0E6 stays 0.
    assert (record[0x0E5], record[0x0E6], record[0x0E7]) == (
        companions.story_byte(mon), picture, 0x01)
    assert record[0x099] == 1
    at = game.icon(member.index)
    assert raw0[at:at + game.icon_size] == icon

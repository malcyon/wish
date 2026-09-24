"""The later-title Amiga saved-game reader, writer and fresh disk."""

from __future__ import annotations

import pathlib

import pytest
from gamedata import specimen_root

from goldbox import amiga_later, amiga_savegame, dos_savegame
from goldbox.amiga_adf import AmigaDisk
from tools.amiga import amigasaves
from tools.registry import specimens


def _fake_record(shape, name: str) -> bytes:
    raw = bytearray(shape.deltas.record_size)
    raw[:len(name)] = name.encode("ascii")
    for i in range(6):
        raw[0x10 + 2 * i] = raw[0x11 + 2 * i] = 12
    return bytes(raw)


def _synthetic(shape, names=("ALPHA", "BETA")) -> bytes:
    out = bytearray((2 if shape is amiga_savegame.CURSE else 1,))
    vm = bytearray(amiga_savegame.VM_BYTES)
    for address, value in ((dos_savegame.DISK, out[0]),
                           (dos_savegame.PARTY_SIZE, len(names)),
                           (dos_savegame.SCRIPT, 1)):
        at = shape.vm_offset(address) - 1
        vm[at:at + 2] = value.to_bytes(2, "big")
    out += vm
    out += bytes(shape.ecl_bytes)
    out += (3).to_bytes(shape.x_bytes, "big")
    out += (14).to_bytes(shape.x_bytes, "big")
    out += bytes((2, 0, 0, 0, 4, 2))
    for block, slot in ((1, 1), (2, 2), (0xFFFF, 0xFFFF)):
        out += block.to_bytes(2, "big") + slot.to_bytes(2, "big")
    out += len(names).to_bytes(2, "big")
    for name in names:
        out += _fake_record(shape, name)
    return bytes(out)


@pytest.mark.parametrize("container", amiga_savegame.CONTAINERS[:2],
                         ids=lambda container: container.key)
def test_each_measured_header_parses_without_game_data(container):
    save = amiga_savegame.parse(_synthetic(container), container)
    assert (save.x, save.y, save.facing) == (3, 14, 2)
    assert save.wallset == ((1, 1), (2, 2), (0xFFFF, 0xFFFF))
    assert [char.name for char in save.characters] == ["ALPHA", "BETA"]


def test_the_two_first_record_offsets_are_the_engines_own():
    assert amiga_savegame.CURSE.party_at == 0x3219
    assert amiga_savegame.SILVER_BLADES.party_at == 0x1417


def test_pool_container_uses_its_independent_fixed_party_table_offset():
    container = amiga_savegame.POOL_OF_RADIANCE
    assert container.fixed_size == 13141
    assert container.party_at == 12813
    data = bytearray(container.fixed_size)
    data[container.count_at] = 1
    at = container.vm_offset(dos_savegame.PARTY_SIZE)
    data[at:at + 2] = (1).to_bytes(2, "big")
    data[container.party_at:container.party_at + 8] = b"CHRDATA1"
    parsed = amiga_savegame.parse(data, container)
    assert parsed.names[:2] == ("CHRDATA1", "")


def test_strict_pool_parse_rejects_a_count_word_or_filename_table_that_disagrees():
    container = amiga_savegame.POOL_OF_RADIANCE
    data = bytearray(container.fixed_size)
    data[container.count_at] = 1
    data[container.party_at:container.party_at + 8] = b"CHRDATA1"
    with pytest.raises(amiga_savegame.AmigaSaveError, match="\\$503E"):
        amiga_savegame.parse(data, container)
    assert amiga_savegame.parse(data, container, validate=False).names[0] == "CHRDATA1"

    at = container.vm_offset(dos_savegame.PARTY_SIZE)
    data[at:at + 2] = (1).to_bytes(2, "big")
    data[container.party_at:container.party_at + 8] = b"NOTANAME"
    with pytest.raises(amiga_savegame.AmigaSaveError, match="CHRDAT"):
        amiga_savegame.parse(data, container)


def _pool_save(*, count: int = 1, word_count: int | None = None,
               name: bytes = b"CHRDATA1") -> bytes:
    container = amiga_savegame.POOL_OF_RADIANCE
    data = bytearray(container.fixed_size)
    data[container.count_at] = count
    at = container.vm_offset(dos_savegame.PARTY_SIZE)
    data[at:at + 2] = (count if word_count is None else word_count).to_bytes(2, "big")
    data[container.party_at:container.party_at + len(name)] = name
    return bytes(data)


class _PoolSlotDisk:
    volume_name = "SYNTHETIC"

    def __init__(self, save: bytes):
        self.save = save

    def read_file(self, path: str) -> bytes:
        # One file per member up to the party limit, so a count above it is read to the limit.
        for n in range(1, amiga_savegame.PARTY_MAX + 1):
            if path.endswith(f"CHRDATA{n}.sav"):
                return b"character"
            if path.endswith((f"CHRDATA{n}.itm", f"CHRDATA{n}.spc")):
                return b""
        if path.endswith("savgamA.dat"):
            return self.save
        raise amiga_savegame.AmigaDiskError(path)


# The party limit is `PARTY_MAX`; the middle case pins the count just above it,
# which the slot reader clamps to the limit.
@pytest.mark.parametrize(("count", "word_count", "name", "members"), [
    (1, 2, b"CHRDATA1", 1),
    (amiga_savegame.PARTY_MAX + 1, amiga_savegame.PARTY_MAX + 1, b"CHRDATA1",
     amiga_savegame.PARTY_MAX),
    (1, 1, b"NOTANAME", 1),
], ids=("count-word-disagreement", "party-count-outside-one-to-eight",
        "non-chrdat-name"))
def test_pool_conversion_readers_keep_their_pre_consolidation_acceptance(
        count, word_count, name, members, monkeypatch):
    """Pool conversion only used fixed-size validation before consolidation."""
    from goldbox import amiga_por

    save = _pool_save(count=count, word_count=word_count, name=name)
    monkeypatch.setattr(amiga_por, "por_character", lambda *args, **kwargs: object())
    monkeypatch.setattr(amiga_por, "to_dos_character", lambda character: character)

    state = amiga_savegame.read_por_state(save, "synthetic save")
    party, returned = amiga_savegame.read_por_slot(_PoolSlotDisk(save), "A", "SAVE")

    assert state.source == "synthetic save"
    assert len(party) == members
    assert returned == save


@pytest.mark.parametrize("size", [
    amiga_savegame.POR_SAVEGAME_SIZE - 1,
    amiga_savegame.POR_SAVEGAME_SIZE + 1,
], ids=("short", "long"))
def test_pool_conversion_readers_still_refuse_a_non_fixed_size_save(size, monkeypatch):
    """The pre-consolidation readers both retained the fixed-size boundary."""
    from goldbox import amiga_por

    save = bytes(size)
    monkeypatch.setattr(amiga_por, "por_character", lambda *args, **kwargs: object())
    monkeypatch.setattr(amiga_por, "to_dos_character", lambda character: character)

    with pytest.raises(amiga_savegame.AmigaSaveError, match=str(amiga_savegame.POR_SAVEGAME_SIZE)):
        amiga_savegame.read_por_state(save)
    with pytest.raises(amiga_savegame.AmigaSaveError, match=str(amiga_savegame.POR_SAVEGAME_SIZE)):
        amiga_savegame.read_por_slot(_PoolSlotDisk(save), "A", "SAVE")


def test_a_fresh_disk_has_only_the_save_drawer_and_slot():
    data = _synthetic(amiga_savegame.CURSE, ("ALPHA",))
    disk = amiga_savegame.make_save_disk(amiga_savegame.CURSE, "D", data)
    assert [(path, len(disk.read_file(path))) for path, _ in disk.walk()] == [
        ("/SAVE/savgamD.dat", len(data))]
    assert amiga_savegame.slots_present(disk, amiga_savegame.CURSE) == ["D"]
    assert amiga_savegame.read_slot(disk, "D").characters[0].name == "ALPHA"
    assert disk.verify() == []


def _verified_later_save(drawer: str, specimen: str, filename: str) -> pathlib.Path:
    root = specimen_root()
    if root is None:
        pytest.skip("needs the engine-written Amiga specimen tree")
    where = root / drawer / specimen
    provenance = where / "provenance.toml"
    if not provenance.is_file():
        pytest.skip(f"needs {where}")
    recorded = specimens.read_provenance(provenance).get("sha256", {})
    path = where / filename
    if filename not in recorded or specimens.sha256_file(path) != recorded[filename]:
        pytest.fail(f"{path} no longer matches its provenance")
    return path


def _curse_ecl() -> bytes:
    for _label, image in amigasaves.images():
        try:
            disk = AmigaDisk(image)
            return disk.read_file("/DISKB/ECL.GLB")
        except Exception:
            continue
    pytest.skip("needs the player's Amiga Curse disk B")


@pytest.mark.parametrize("shape,drawer,specimen,filename", [
    (amiga_savegame.CURSE, "coab-amiga",
     "WISH-SPEC-coab-amiga-resave", "savgamE.dat"),
    (amiga_savegame.SILVER_BLADES, "ssb-amiga",
     "WISH-SPEC-ssbwalk", "savgamF.sav"),
])
def test_an_engine_written_save_round_trips_square_clock_and_order(
        shape, drawer, specimen, filename):
    path = _verified_later_save(drawer, specimen, filename)
    source = amiga_savegame.parse(path.read_bytes(), shape, str(path))
    state = amiga_savegame.state_from_savegame(source)
    neutral_party = [amiga_later.to_neutral_later(char)
                     for char in source.characters]
    built, report = amiga_savegame.new_savegame(
        state, neutral_party, "B",
        _curse_ecl() if shape is amiga_savegame.CURSE else None)
    landed = amiga_savegame.parse(built, shape)
    landed_state = amiga_savegame.state_from_savegame(landed)

    assert report.unwritten == []
    assert report.total == len(built)
    assert (landed.x, landed.y, landed.facing) == (
        source.x, source.y, source.facing)
    assert landed_state.clock == state.clock
    assert [char.name for char in landed.characters] == [
        char.name for char in source.characters]
    assert landed_state.wallset == state.wallset


def test_the_diagnostic_tool_parses_through_the_library(tmp_path, monkeypatch):
    """The checker requests tolerant parsing from the one library parser."""
    from tools.amiga import amigasavecheck as tool

    path = tmp_path / "synthetic.dat"
    path.write_bytes(_synthetic(amiga_savegame.CURSE, ("ALPHA",)))
    original = amiga_savegame.parse
    calls = []
    reported = []

    def parse(data, container=None, source="", validate=True):
        calls.append((source, validate))
        return original(data, container, source, validate)

    monkeypatch.setattr(amiga_savegame, "parse", parse)
    monkeypatch.setattr(tool, "report",
                        lambda save, label="": reported.append(save) or "report")

    assert tool.main([str(path)]) == 0
    assert calls == [(str(path), False)]
    assert len(reported) == 1
    assert isinstance(reported[0], amiga_savegame.AmigaSavegame)


# --- a party saved before BEGIN ADVENTURING ----------------------------------

#: `(registry entry, C64 disk, C64 save file, DOS archive directory)`.
PRE_ADVENTURE = {
    "curse-of-the-azure-bonds": (
        "CURSE_C.D64", "SAVEAZURE", "CURSE"),
    "secret-of-the-silver-blades": (
        "SILVER-6.D64", "SAVEDBASH", "SECRET"),
}


def _c64_pre_adventure(key: str) -> bytes:
    from automap import gamedisks
    from goldbox.d64 import D64, split_load_address
    disk, name, _stem = PRE_ADVENTURE[key]
    for root in gamedisks.candidates(key):
        path = root / disk
        if path.is_file():
            return split_load_address(D64.open(path).read_file(name))[1]
    pytest.skip(f"needs {disk} from the {key} registry entry")


def _dos_shipped(stem: str) -> bytes:
    from support.dossave import _game_dirs
    folder = _game_dirs().get(stem)
    if folder is None or not (folder / "SAVGAMA.DAT").is_file():
        pytest.skip("needs the archives' shipped saves")
    return (folder / "SAVGAMA.DAT").read_bytes()


def _shipped_amiga_silver_blades() -> bytes:
    for _label, image in amigasaves.images():
        try:
            return AmigaDisk(image).read_file("/SAVE/savgamA.sav")
        except Exception:
            continue
    pytest.skip("needs the player's Amiga Silver Blades disk")


def _unswapped(data: bytes) -> bytes:
    """The Amiga variable array with each word swapped back to DOS order."""
    out = bytearray(data[:1 + amiga_savegame.VM_BYTES])
    for i in range(1, len(out), 2):
        out[i:i + 2] = out[i:i + 2][::-1]
    return bytes(out)


@pytest.mark.parametrize("key", sorted(PRE_ADVENTURE))
def test_a_party_saved_before_begin_adventuring_converts_to_the_shipped_form(key):
    """Area 0 is no area of either title, so the Amiga save is the
    initialiser's form: Silver Blades' header equals the shipped Amiga
    pre-adventure save's, and Curse's, with the word swap undone, equals the
    DOS archives' pre-adventure save."""
    from goldbox import c64_port, dos_codec, world_state
    game = c64_port.by_key(key)
    save0 = _c64_pre_adventure(key)
    state = world_state.from_c64(save0, game=game)
    assert state.set_out is False
    assert (state.area, state.geo) == (0, 0)
    characters, _icons = dos_codec.c64_party(save0, None, game)
    shape = amiga_savegame.container_for(key)
    is_curse = shape is amiga_savegame.CURSE

    # The Curse script region stays zero, so no ECL.GLB is needed.
    built, report = amiga_savegame.new_savegame(state, characters, "B")

    assert report.unwritten == []
    assert amiga_savegame.parse(built, shape).count == len(characters) == 6
    if is_curse:
        shipped = _dos_shipped("CURSE")
        vm_end = 1 + amiga_savegame.VM_BYTES
        assert _unswapped(built) == shipped[:vm_end]
        assert built[vm_end:shape.square_at] == shipped[vm_end:shape.square_at]
        assert not any(built[shape.ecl_at:shape.square_at])
    else:
        shipped = _shipped_amiga_silver_blades()
        assert built[:shape.party_at] == shipped[:shape.party_at]


def _dos_saves_folder(stem: str) -> pathlib.Path:
    from support.dossave import _game_dirs
    folder = _game_dirs().get(stem)
    if folder is None or not (folder / "SAVGAMA.DAT").is_file():
        pytest.skip("needs the archives' shipped saves")
    return folder


@pytest.mark.parametrize("key", sorted(PRE_ADVENTURE))
def test_a_dos_party_saved_before_begin_adventuring_converts_to_the_amiga_pre_adventure_form(key):
    """A DOS save from the party menu reads back at the title's arrival square,
    and the Amiga writer still emits the initialiser's form: Silver Blades'
    header equals the shipped Amiga pre-adventure save's, and Curse's, with
    the word swap undone, equals the DOS array with a zero script region."""
    from goldbox import dos_codec, world_state
    stem = PRE_ADVENTURE[key][2]
    folder = _dos_saves_folder(stem)
    shape = amiga_savegame.container_for(key)
    container = dos_savegame.container_for(key)
    dos = (folder / f"SAVGAMA{container.suffix}").read_bytes()
    party = [dos_codec.to_neutral(c) for c in dos_codec.read_party(folder, "A")]
    state = world_state.from_dos(dos, container)
    assert state.set_out is False

    built, report = amiga_savegame.new_savegame(state, party, "A")

    assert report.unwritten == []
    assert amiga_savegame.parse(built, shape).count == len(party) == 6
    if shape is amiga_savegame.CURSE:
        vm_end = 1 + amiga_savegame.VM_BYTES
        assert _unswapped(built) == dos[:vm_end]
        assert built[vm_end:shape.square_at] == dos[vm_end:shape.square_at]
        assert not any(built[shape.ecl_at:shape.square_at])
    else:
        shipped = _shipped_amiga_silver_blades()
        assert built[:shape.party_at] == shipped[:shape.party_at]


@pytest.mark.parametrize("key", sorted(PRE_ADVENTURE))
def test_an_amiga_party_saved_before_begin_adventuring_converts_to_the_dos_pre_adventure_form(
        key, tmp_path):
    """The Amiga reader hands the writer the arrival square, and the DOS save
    is still the party menu's own: its bytes up to the party table equal the
    archives' shipped pre-adventure save."""
    from goldbox import amiga_later, c64_port, dos_codec, world_state
    from goldbox.iconparts import amiga_combat_icon
    from tools.dos import dosbox
    stem = PRE_ADVENTURE[key][2]
    folder = _dos_saves_folder(stem)
    try:
        game_dir = dosbox.find_game(stem)
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {stem} archives")
    container = dos_savegame.container_for(key)
    shape = amiga_savegame.container_for(key)
    if shape is amiga_savegame.CURSE:
        game = c64_port.by_key(key)
        save0 = _c64_pre_adventure(key)
        characters, _icons = dos_codec.c64_party(save0, None, game)
        data, _report = amiga_savegame.new_savegame(
            world_state.from_c64(save0, game=game), characters, "A")
    else:
        data = _shipped_amiga_silver_blades()
    save = amiga_savegame.parse(data, shape)
    state = amiga_savegame.state_from_savegame(save)
    party = list(save.characters)
    neutral = [amiga_later.to_neutral_later(c) for c in party]

    report = dos_codec.new_dos_save_from(
        state, neutral, tmp_path, "A", game_dir,
        icons=[amiga_combat_icon(c) for c in party])

    shipped = (folder / f"SAVGAMA{container.suffix}").read_bytes()
    written = (tmp_path / f"SAVGAMA{container.suffix}").read_bytes()
    assert report.unwritten == []
    assert written[:container.party_table] == shipped[:container.party_table]
    assert len(dos_codec.read_party(tmp_path, "A")) == len(party) == 6


@pytest.mark.parametrize("key", sorted(PRE_ADVENTURE))
def test_an_amiga_party_saved_before_begin_adventuring_converts_to_the_c64_s_own_form(key):
    """An Amiga party that has not set out converts to a C64 save whose
    header, every byte before the combat icons, equals the C64 game's own
    pre-adventure save -- so `BEGIN ADVENTURING` plays the opening there,
    where a party placed at the arrival square skips it.  Silver Blades'
    source is the shipped `savgamA.sav`; Curse has no Amiga pre-adventure
    save, so its source is the Amiga writer's output from `SAVEAZURE`."""
    from goldbox import c64_port, c64_save, dos_codec, world_state
    from goldbox.iconparts import amiga_combat_icon
    game = c64_port.by_key(key)
    shipped_c64 = _c64_pre_adventure(key)
    shape = amiga_savegame.container_for(key)
    if shape is amiga_savegame.CURSE:
        characters, _icons = dos_codec.c64_party(shipped_c64, None, game)
        data, _report = amiga_savegame.new_savegame(
            world_state.from_c64(shipped_c64, game=game), characters, "A")
    else:
        data = _shipped_amiga_silver_blades()
    save = amiga_savegame.parse(data, shape)
    state = amiga_savegame.state_from_savegame(save)
    party = list(save.characters)

    save0, _save1, report = dos_codec.new_save_from_neutral(
        state, [amiga_later.to_neutral_later(c) for c in party],
        [amiga_combat_icon(c) for c in party], bytes(36), bytes(852),
        game=game)

    cont = c64_save.container_for(game)
    assert report.messages == []
    assert save0[:cont.icon_table] == shipped_c64[:cont.icon_table]
    assert world_state.from_c64(bytes(save0), game=game).set_out is False

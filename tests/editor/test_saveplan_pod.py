"""Save As for a Pools of Darkness save, behind
`WISH_EXPERIMENTAL_POD_CONVERT`: the library half of the Amiga destination,
which is a copy of the player's disk 3 holding the slot and its vault, and of
the DOS destination, which is a folder.

**The synthetic tests need no game data**: a one-character DOS folder, a
disk 3 built from its documented drawers, and a container written from the
documented offsets. **The specimen tests read the player's own saves and
disks** at run time and skip without them, which is what CI does.
"""
from __future__ import annotations

import pathlib
import struct

import pytest
from test_podparty import (
    OFF,
    _amiga_images,
    _amiga_sources,
    _dos_sources,
    _flag,
)
from test_podwindow import _no_box, _synthetic_folder, _window

from editor import convert, podsheet, saveplan
from editor.roster import Party
from goldbox import amiga_pod, amiga_savegame, dos_codec, dos_port, dos_savegame
from goldbox.amiga_adf import AmigaDisk

POD = dos_port.POOLS_OF_DARKNESS


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# What the tests save from and onto
# ---------------------------------------------------------------------------

def _container() -> bytes:
    """A well-formed `SAVGAMA.PTY` for one character, from the documented
    offsets."""
    save = dos_savegame.SAVE_POOLS_OF_DARKNESS
    out = bytearray(save.size)
    variables = bytearray(dos_savegame.POD_VAR_COUNT)
    variables[dos_savegame.POD_PARTY_COUNT - 1] = 1
    first = dos_savegame.POD_CLOCK - dos_savegame.POD_VAR_FIRST
    variables[first:first + dos_savegame.POD_CLOCK_DIGITS] = bytes(
        [1, 2, 3, 4, 5, 6, 7])
    out[:save.var_bytes] = variables
    out[save.pos_x] = 11
    out[save.pos_y] = 22
    out[save.pos_facing] = 3 * dos_savegame.FACING_SCALE
    out[save.previous_mode] = dos_savegame.POD_MODE_WILDERNESS
    out[save.mode] = dos_savegame.POD_MODE_DUNGEON
    struct.pack_into("<H", out, dos_savegame.POD_MAP, 99)
    struct.pack_into("<H", out, dos_savegame.POD_MAP_BLOCK, 5)
    out[save.party_size_byte] = 1
    return bytes(out)


def _record() -> podsheet.PodSheetRecord:
    """A human fighter holding one item: single-class, with no spells."""
    record = podsheet.PodSheetRecord(bytes(podsheet.SIZE))
    record.set("name", "GRIMNIR")
    record.set("race", 5)
    record.set("class_bits", 0x08)
    record.set("char_class", 2)
    record.set("level", 6)
    record.set("level_fighter", 6)
    record.set("hp_max", 40)
    record.set("hp_current", 40)
    record.set("strength", 17)
    record.set("experience", 123456)
    record.set("age", 30)
    record.set("item_count", 1)
    # What every character the game wrote holds in these three DOS-only
    # fields, which the Amiga block keeps as one value of its own.
    raw = bytearray(record.to_bytes())
    for field, value in (("icon_dimension", b"\x01"), ("size", b"\x01"),
                         ("unnamed_1a4", b"\x02\x02")):
        spec = podsheet.TABLE[field]
        raw[spec.offset:spec.offset + spec.size] = value
    return podsheet.PodSheetRecord(bytes(raw))


def _dos_folder(root: pathlib.Path, vault: bytes | None = None
                ) -> pathlib.Path:
    """`root/SAVE`: slot A with one character, a container and a vault."""
    folder = _synthetic_folder(root)
    (folder / "CHRDATA1.SAV").write_bytes(_record().to_bytes())
    (folder / "SAVGAMA.PTY").write_bytes(_container())
    if vault is None:
        vault = dos_codec.pod_vault_to_dos(dos_codec.PodVault(
            5, 6, 7, (bytes(dos_codec.ITEM_SIZE),)))
    (folder / "VAULTA.DAT").write_bytes(vault)
    return folder


def _disk_three(held: str = "A", vault_only: bool = False) -> AmigaDisk:
    """A disk 3 from the documented drawers, holding slot `held`'s files."""
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.make_dir("/DISK3")
    disk.write_file(f"/{amiga_savegame.SAVE_DRAWER}/spindisk", b"\x01" * 40)
    disk.write_file(f"/{amiga_savegame.SAVE_DRAWER}/WRITE.ME", b"\x02" * 8)
    disk.write_file("/DISK3/GEN.TLB", b"\x03" * 600)
    if not vault_only:
        disk.write_file(amiga_savegame.pod_slot_path(held), b"\x00" * 10)
    disk.write_file(amiga_savegame.pod_vault_path(held),
                    b"\xEE" * amiga_savegame.POD_VAULT_SIZE)
    return disk


def _disk_one() -> AmigaDisk:
    disk = AmigaDisk.blank("POD 1")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    return disk


def _files(image: bytes) -> dict[str, bytes]:
    disk = AmigaDisk(bytearray(image))
    return {path.lower(): disk.read_file(path)
            for path, entry in disk.walk() if not entry.is_dir}


def _folder_files(folder: pathlib.Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())
            if p.is_file()}


def _dos_party(monkeypatch, tmp_path, vault: bytes | None = None):
    _flag(monkeypatch, "1")
    folder = _dos_folder(tmp_path, vault)
    return folder, Party(convert.Source.detect(folder, slot="A"))


def _disk_file(tmp_path, disk: AmigaDisk, name: str = "disk3.adf"
               ) -> pathlib.Path:
    path = tmp_path / name
    path.write_bytes(disk.to_bytes())
    return path


def _to_amiga(party, tmp_path, disk_path, target="out.adf"):
    assets = saveplan.resolve_assets(
        convert.Source.of_snapshot(saveplan.prepare(party)), "amiga",
        amiga_disk_three=disk_path)
    return saveplan.prepare_save_as(party, "amiga", tmp_path / target, assets)


# ---------------------------------------------------------------------------
# The routes a Pools of Darkness save has
# ---------------------------------------------------------------------------

def _source(port: str):
    return convert.Source(port=port, title=POD, path=pathlib.Path("."),
                          slot="A")


@pytest.mark.parametrize("value", OFF)
def test_a_forgotten_flag_offers_no_conversion(monkeypatch, value):
    _flag(monkeypatch, value)
    assert saveplan.destination_ports(_source("dos")) == ["dos"]
    assert saveplan.destination_ports(_source("amiga")) == ["amiga"]


def test_the_ports_are_the_two_the_title_shipped_on(monkeypatch):
    _flag(monkeypatch, "1")
    assert saveplan.destination_ports(_source("dos")) == ["dos", "amiga"]
    assert saveplan.destination_ports(_source("amiga")) == ["amiga", "dos"]


def test_the_save_menu_has_no_c64_entry(app, monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    window = _window()
    window.load(str(_dos_folder(tmp_path)))
    labels = [action.text() for action in window._save_menu.actions()]
    assert labels == ["Save As DOS…", "Save As Amiga…"]


def test_the_amiga_destination_needs_disk_three_and_nothing_else(monkeypatch):
    _flag(monkeypatch, "1")
    assert saveplan.requirements(_source("dos"), "amiga") == (
        saveplan.AMIGA_DISK_THREE,)
    assert saveplan.requirements(_source("amiga"), "dos") == ()
    assert saveplan.requirements(_source("dos"), "dos") == ()


def test_the_convert_dialog_does_not_offer_the_disk_three_route(
        monkeypatch):
    _flag(monkeypatch, "1")
    assert convert.amiga_needs_disk_three(POD)
    assert not convert.amiga_needs_disk_three(
        dos_port.CURSE_OF_THE_AZURE_BONDS)
    assert not convert.amiga_needs_game_disk(POD)


# ---------------------------------------------------------------------------
# Finding and checking disk 3
# ---------------------------------------------------------------------------

def test_a_disk_three_in_the_folder_is_found_and_other_disks_are_not(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    folder = tmp_path / "disks"
    folder.mkdir()
    (folder / "a-disk-one.adf").write_bytes(_disk_one().to_bytes())
    (folder / "b-notes.adf").write_bytes(b"not a disk")
    assert saveplan.find_disk_three(folder) is None
    (folder / "c-disk-three.adf").write_bytes(_disk_three().to_bytes())
    assert saveplan.find_disk_three(folder) == folder / "c-disk-three.adf"
    assert saveplan.find_disk_three(tmp_path / "missing") is None
    assert saveplan.find_disk_three(None) is None


def test_resolving_with_no_disk_three_says_it_is_missing(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    with pytest.raises(saveplan.MissingAssets) as caught:
        saveplan.resolve_assets(_source("dos"), "amiga", game_folder=tmp_path)
    assert caught.value.missing == (saveplan.AMIGA_DISK_THREE,)


def test_resolving_takes_the_disk_three_from_the_folder(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    path = _disk_file(tmp_path, _disk_three())
    assets = saveplan.resolve_assets(_source("dos"), "amiga",
                                     game_folder=tmp_path)
    assert assets.amiga_disk_three == path


def test_a_disk_one_named_as_disk_three_is_stopped_before_anything_is_written(
        monkeypatch, tmp_path):
    folder, party = _dos_party(monkeypatch, tmp_path)
    wrong = _disk_file(tmp_path, _disk_one(), "disk1.adf")
    with pytest.raises(saveplan.WrongDiskThree):
        saveplan.resolve_assets(_source("dos"), "amiga",
                                amiga_disk_three=wrong)
    # Handed straight to the rehearsal, the writer stops it too.
    out = tmp_path / "out.adf"
    assets = saveplan.Assets(amiga_disk_three=wrong)
    with pytest.raises(convert.ConvertError):
        saveplan.prepare_save_as(party, "amiga", out, assets)
    assert not out.exists()


def test_a_save_as_cannot_land_on_the_disk_three_it_reads(
        monkeypatch, tmp_path):
    folder, party = _dos_party(monkeypatch, tmp_path)
    disk = _disk_file(tmp_path, _disk_three())
    assets = saveplan.Assets(amiga_disk_three=disk)
    with pytest.raises(saveplan.SaveAsError):
        saveplan.prepare_save_as(party, "amiga", disk, assets)


# ---------------------------------------------------------------------------
# Save As Amiga
# ---------------------------------------------------------------------------

def test_a_letter_that_holds_only_a_vault_is_replaced(monkeypatch, tmp_path):
    folder, party = _dos_party(monkeypatch, tmp_path)
    disk = _disk_file(tmp_path, _disk_three(vault_only=True))
    plan = _to_amiga(party, tmp_path, disk)
    written = _files(next(iter(plan.files.values())))
    assert amiga_savegame.pod_slot_path("A").lower() in written


def test_save_as_amiga_writes_the_slot_and_its_vault_and_nothing_else(
        monkeypatch, tmp_path):
    folder, party = _dos_party(monkeypatch, tmp_path)
    held = _disk_three("A")
    held.write_file("/SAVE/VaultB.DAT", b"\xBB" * 40)
    disk = _disk_file(tmp_path, held)
    before = disk.read_bytes()
    source_before = _folder_files(folder)
    plan = _to_amiga(party, tmp_path, disk)
    [image] = plan.files.values()
    after, kept = _files(image), _files(before)
    changed = {p for p in set(after) | set(kept) if after.get(p) != kept.get(p)}
    assert changed == {"/save/savgama.pty", "/save/vaulta.dat"}
    assert set(after) == set(kept)
    assert disk.read_bytes() == before
    assert _folder_files(folder) == source_before
    vault = amiga_savegame.pod_vault_from_amiga(after["/save/vaulta.dat"])
    assert (vault.platinum, vault.gems, vault.jewelry) == (5, 6, 7)
    assert len(vault.items) == 1


def test_the_destination_opens_and_holds_the_party(monkeypatch, tmp_path):
    folder, party = _dos_party(monkeypatch, tmp_path)
    plan = _to_amiga(party, tmp_path, _disk_file(tmp_path, _disk_three()))
    published = saveplan.publish(plan, party, backups=str(tmp_path / "b"))
    [member] = published.party.members
    assert member.name == "GRIMNIR"
    assert published.party.source.slot == "A"


def test_an_edited_stat_and_item_cross_before_any_save(monkeypatch, tmp_path):
    folder, party = _dos_party(monkeypatch, tmp_path)
    [member] = party.members
    member.record.set("strength", 12)
    member.inventory.set_quantity(0, 3)
    on_disk = _folder_files(folder)
    plan = _to_amiga(party, tmp_path, _disk_file(tmp_path, _disk_three()))
    assert _folder_files(folder) == on_disk
    published = saveplan.publish(plan, party, backups=str(tmp_path / "b"))
    [back] = published.party.members
    assert back.record.get("strength") == 12
    assert back.inventory.item(0).quantity == 3


def _weighted_party(monkeypatch, tmp_path, weight: int = 80):
    """`_dos_party` whose one item weighs `weight` and whose stored load
    balances, so the load the writers store is the one a Save As expects."""
    _flag(monkeypatch, "1")
    folder = _dos_folder(tmp_path)
    data = bytearray((folder / "CHRDATA1.THG").read_bytes())
    data[dos_codec.DosItem._TABLE["weight"].span] = struct.pack("<H", weight)
    (folder / "CHRDATA1.THG").write_bytes(bytes(data))
    record = podsheet.PodSheetRecord((folder / "CHRDATA1.SAV").read_bytes())
    record.set("encumbrance", record.get("platinum") + weight)
    (folder / "CHRDATA1.SAV").write_bytes(record.to_bytes())
    return folder, Party(convert.Source.detect(folder, slot="A"))


def _published_load(party, tmp_path, port):
    """The `encumbrance` a Save As to `port` publishes; a stop fails the test."""
    if port == "amiga":
        disk = _disk_file(tmp_path, _disk_three())
        plan = _to_amiga(party, tmp_path, disk)
    else:
        plan = saveplan.prepare_save_as(party, "dos", tmp_path / "dos-out")
    published = saveplan.publish(plan, party, backups=str(tmp_path / "b"))
    [back] = published.party.members
    return back.record.get("encumbrance")


def test_a_stale_stored_load_is_expected_only_by_a_dos_destination(
        monkeypatch, tmp_path):
    folder, _ = _weighted_party(monkeypatch, tmp_path)
    record = podsheet.PodSheetRecord((folder / "CHRDATA1.SAV").read_bytes())
    balanced = record.get("encumbrance")
    record.set("encumbrance", balanced + 4)
    (folder / "CHRDATA1.SAV").write_bytes(record.to_bytes())
    [member] = Party(convert.Source.detect(folder, slot="A")).members
    assert saveplan.pod_written_encumbrance(member, "dos") == balanced + 4
    assert saveplan.pod_written_encumbrance(member, "amiga") == balanced


@pytest.mark.parametrize("port", ["amiga", "dos"])
def test_an_edited_quantity_moves_the_expected_load_on_every_route(
        monkeypatch, tmp_path, port):
    folder, party = _weighted_party(monkeypatch, tmp_path)
    [member] = party.members
    start = member.record.get("encumbrance")
    member.inventory.set_quantity(0, 3)
    assert _published_load(party, tmp_path, port) == start + 80 * 2


@pytest.mark.parametrize("port", ["amiga", "dos"])
def test_an_edited_coin_amount_moves_the_expected_load(
        monkeypatch, tmp_path, port):
    folder, party = _weighted_party(monkeypatch, tmp_path)
    [member] = party.members
    start = member.record.get("encumbrance")
    member.record.set("platinum", member.record.get("platinum") + 500)
    assert _published_load(party, tmp_path, port) == start + 500


def test_a_vault_of_two_hundred_and_one_items_converts_whole(
        monkeypatch, tmp_path):
    item = bytes(dos_codec.ITEM_SIZE)
    big = dos_codec.pod_vault_to_dos(dos_codec.PodVault(
        0, 0, 0, (item,) * (amiga_savegame.POD_VAULT_NODES + 1)))
    folder, party = _dos_party(monkeypatch, tmp_path, vault=big)
    plan = _to_amiga(party, tmp_path, _disk_file(tmp_path, _disk_three()))
    [image] = plan.files.values()
    raw = _files(image)["/save/vaulta.dat"]
    assert len(raw) == 16 + 20 * 201
    assert len(amiga_savegame.pod_vault_from_amiga(raw).items) == 201


def test_a_vault_over_the_game_pool_stays_stopped(monkeypatch, tmp_path):
    item = bytes(dos_codec.ITEM_SIZE)
    big = dos_codec.pod_vault_to_dos(dos_codec.PodVault(
        0, 0, 0, (item,) * (amiga_savegame.POD_POOL_NODES + 1)))
    folder, party = _dos_party(monkeypatch, tmp_path, vault=big)
    out = tmp_path / "out.adf"
    with pytest.raises(convert.ConvertError):
        _to_amiga(party, tmp_path, _disk_file(tmp_path, _disk_three()))
    assert not out.exists()


# ---------------------------------------------------------------------------
# Save As DOS, from an Amiga disk 3 this library wrote
# ---------------------------------------------------------------------------

def test_save_as_dos_writes_the_container_the_records_and_the_vault(
        monkeypatch, tmp_path):
    folder, party = _dos_party(monkeypatch, tmp_path)
    plan = _to_amiga(party, tmp_path, _disk_file(tmp_path, _disk_three()))
    published = saveplan.publish(plan, party, backups=str(tmp_path / "b"))
    amiga = published.party
    on_disk = _folder_files(folder)
    [member] = amiga.members
    member.record.set("strength", 14)
    plan = saveplan.prepare_save_as(amiga, "dos", tmp_path / "dos-out")
    assert set(plan.files) >= {"SAVGAMA.PTY", "CHRDATA1.SAV", "VAULTA.DAT"}
    again = saveplan.publish(plan, amiga, backups=str(tmp_path / "b"))
    written = _folder_files(tmp_path / "dos-out")
    assert written == dict(plan.files)
    assert written["VAULTA.DAT"] == on_disk["VAULTA.DAT"]
    [back] = again.party.members
    assert back.name == "GRIMNIR"
    assert back.record.get("strength") == 14


# ---------------------------------------------------------------------------
# Every save we have
# ---------------------------------------------------------------------------

def _registered_disk_three(tmp_path) -> pathlib.Path:
    for n, (_label, data, _slots) in enumerate(_amiga_images()):
        if amiga_savegame.is_pod_disk_three(AmigaDisk(data)):
            path = tmp_path / f"specimen-disk3-{n}.adf"
            path.write_bytes(data)
            return path
    pytest.skip("needs an Amiga Pools of Darkness disk 3; set "
                "$WISH_SPECIMENS or $AMIGA_DISKS")


def test_every_dos_slot_crosses_to_the_amiga_with_nothing_lost(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    disk = _registered_disk_three(tmp_path)
    checked = held_bonus = 0
    for source in _dos_sources():
        party = Party(source)
        plan = _to_amiga(party, tmp_path, disk)
        # The readied items' saving-throw bonus is rebuilt by both games on
        # load, so a character holding it is not a loss and not a stop.
        held_bonus += any(m.record.to_bytes()[
            podsheet.TABLE["item_save_bonus"].offset] for m in party.members)
        report = plan.report
        assert (report.dropped, report.losses) == ([], []), (
            source.path, source.slot)
        checked += 1
    assert checked
    assert held_bonus


def test_every_amiga_slot_crosses_to_dos_with_nothing_lost(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    checked = 0
    for n, (label, source) in enumerate(_amiga_sources(tmp_path)):
        plan = saveplan.prepare_save_as(Party(source), "dos",
                                        tmp_path / f"dos-{n}")
        report = plan.report
        assert (report.dropped, report.losses) == ([], []), label
        # A new DOS folder is always slot A.
        assert {"SAVGAMA.PTY", "VAULTA.DAT"} <= set(plan.files), label
        checked += 1
    assert checked


# ---------------------------------------------------------------------------
# What the read-back compares
# ---------------------------------------------------------------------------

def _pair(monkeypatch, tmp_path):
    folder, party = _dos_party(monkeypatch, tmp_path)
    [member] = party.members
    want = saveplan.edited_record(member)
    assert want.items, "the synthetic character holds an item"
    return want, saveplan.PodCompared(want.to_bytes())


def test_a_changed_thief_skill_and_a_dropped_item_are_both_caught(
        monkeypatch, tmp_path):
    want, got = _pair(monkeypatch, tmp_path)
    got.items = want.items
    assert saveplan.compare([want], [got]) == []
    got.set("thief_pick_pockets", 200)
    lost = saveplan.compare([want], [got])
    assert [line.split(":")[0] for line in lost] == ["thief_pick_pockets"]
    got.set("thief_pick_pockets", want.get("thief_pick_pockets"))
    got.items = ()
    assert [line.split(":")[0] for line in saveplan.compare([want], [got])
            ] == ["items"]


def test_fields_only_the_dos_record_has_are_compared(monkeypatch, tmp_path):
    want, got = _pair(monkeypatch, tmp_path)
    got.items = want.items
    for field in ("former_class_levels", "field_83_87", "save_spell",
                  "spells_castable_cleric", "icon_head"):
        spec = podsheet.TABLE[field]
        raw = bytearray(want.to_bytes())
        raw[spec.offset] ^= 0x55
        changed = saveplan.PodCompared(bytes(raw))
        changed.items = want.items
        assert [line.split(":")[0]
                for line in saveplan.compare([want], [changed])] == [field]


def test_a_spellbook_byte_changing_value_is_a_declared_change(
        monkeypatch, tmp_path):
    want, got = _pair(monkeypatch, tmp_path)
    got.items = want.items
    reason = saveplan.POD_VALUE_CHANGES["spellbook"][1]
    assert "non-zero" in reason and "identical" in reason
    assert "pending" not in reason
    spec = podsheet.TABLE["spellbook"]
    odd = bytearray(want.to_bytes())
    odd[spec.offset + 117] = 8
    held = saveplan.PodCompared(bytes(odd))
    held.items = want.items
    # 8 and 1 are the one declared change; a known spell that goes missing
    # is not.
    one = bytearray(odd)
    one[spec.offset + 117] = 1
    amiga = saveplan.PodCompared(bytes(one))
    amiga.items = want.items
    assert saveplan.compare([held], [amiga]) == []
    one[spec.offset + 117] = 0
    gone = saveplan.PodCompared(bytes(one))
    gone.items = want.items
    assert [line.split(":")[0] for line in saveplan.compare([held], [gone])
            ] == ["spellbook"]


def test_every_field_left_uncompared_names_its_reason():
    for field, reason in saveplan.POD_NOT_COMPARED.items():
        assert field in podsheet.TABLE and reason, field
    for field in ("thief_pick_pockets", "former_class_levels", "field_83_87",
                  "spells_castable_cleric", "icon_head", "item_count"):
        assert field not in saveplan.POD_NOT_COMPARED


def test_the_item_save_bonus_is_not_a_loss_because_both_games_rebuild_it(
        monkeypatch, tmp_path):
    want, got = _pair(monkeypatch, tmp_path)
    got.items = want.items
    assert saveplan.POD_NOT_COMPARED["item_save_bonus"]
    spec = podsheet.TABLE["item_save_bonus"]
    raw = bytearray(want.to_bytes())
    raw[spec.offset] = 2
    held = saveplan.PodCompared(bytes(raw))
    held.items = want.items
    assert saveplan.compare([held], [got]) == []
    assert saveplan.compare([want], [got]) == []


@pytest.mark.parametrize("field, lost", [("unnamed_1a4", b"\x00\x00"),
                                         ("size", b"\x00")])
def test_the_read_back_fails_when_a_write_loses_size_or_the_creature_pair(
        field, lost):
    want = _record()
    raw = bytearray(want.to_bytes())
    spec = podsheet.TABLE[field]
    raw[spec.offset:spec.offset + spec.size] = lost
    got = podsheet.PodSheetRecord(bytes(raw))
    assert [line.split(":")[0] for line in saveplan.compare([want], [got])
            ] == [field]


# ---------------------------------------------------------------------------
# The spell-slot arrays on a DOS to Amiga Save As
# ---------------------------------------------------------------------------

def _castable_pair(monkeypatch, tmp_path):
    want, got = _pair(monkeypatch, tmp_path)
    got.items = want.items
    spec = podsheet.TABLE["spells_castable_magic_user"]
    raw = bytearray(want.to_bytes())
    raw[spec.offset + 4] ^= 0x0C
    changed = saveplan.PodCompared(bytes(raw))
    changed.items = want.items
    return want, changed


def _amiga_destination(tmp_path):
    return saveplan.Destination("amiga", tmp_path / "out.adf", "A", None, True)


def test_the_slot_arrays_are_compared_on_every_save_as(
        monkeypatch, tmp_path):
    want, changed = _castable_pair(monkeypatch, tmp_path)
    amiga = _amiga_destination(tmp_path)
    for destination, source_port in (
            (amiga, "dos"), (amiga, "amiga"), (None, "dos"),
            (saveplan.Destination("dos", tmp_path, "A", None, False), "amiga")):
        lines = saveplan.compare([want], [changed], destination,
                                 source_port=source_port)
        assert [line.split(":")[0] for line in lines] == [
            "spells_castable_magic_user"]


def _ringed_pair(monkeypatch, tmp_path, written_level_five):
    from goldbox import spells
    from goldbox.items import READIED

    want, _ = _pair(monkeypatch, tmp_path)
    want.set("level_magic_user", 28)
    want.set("intelligence", 18)
    want.set("wisdom", 18)
    ring = bytearray(16)
    ring[6] = READIED
    ring[15] = 0x81
    want.items = (bytes(ring),)
    base = spells.pod_slot_arrays({"magic-user": 28}, 18, 18)
    got = saveplan.PodCompared(want.to_bytes())
    got.items = want.items
    for _name, field in podsheet.SLOT_ARRAYS:
        got.set_raw(field, bytes(base["cleric" if "cleric" in field else
                                   "druid" if "druid" in field
                                   else "magic-user"]))
    mage = list(base["magic-user"])
    mage[4] = written_level_five
    got.set_raw("spells_castable_magic_user", bytes(mage))
    return want, got


def test_a_readied_ring_is_expected_to_double_level_five_on_the_amiga(
        monkeypatch, tmp_path):
    amiga = _amiga_destination(tmp_path)
    want, got = _ringed_pair(monkeypatch, tmp_path, 12)
    assert saveplan.compare([want], [got], amiga, source_port="dos") == []
    (tmp_path / "again").mkdir()
    want, ignored = _ringed_pair(monkeypatch, tmp_path / "again", 6)
    lines = saveplan.compare([want], [ignored], amiga, source_port="dos")
    assert [line.split(":")[0] for line in lines] == [
        "spells_castable_magic_user"]


def test_a_dos_mage_whose_stored_slots_differ_crosses_the_rebuilt_value_whole(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    folder = _dos_folder(tmp_path)
    path = folder / "CHRDATA1.SAV"
    record = podsheet.PodSheetRecord(path.read_bytes())
    record.set("class_bits", 0x01)
    record.set("char_class", 0)
    record.set("level_fighter", 0)
    record.set("level_magic_user", 28)
    record.set("intelligence", 18)
    record.set("wisdom", 18)
    # No ring is readied, so DOS rebuilds 6 on load and never shows this 12;
    # the Amiga, which does not rebuild, must hold the 6.
    record.set_raw("spells_castable_magic_user", bytes((6, 6, 6, 6, 12) + (6,) * 4))
    path.write_bytes(record.to_bytes())
    party = Party(convert.Source.detect(folder, slot="A"))
    disk = _disk_file(tmp_path, _disk_three())
    plan = _to_amiga(party, tmp_path, disk)
    assert (plan.report.dropped, plan.report.losses) == ([], [])


def _regained_cleric_mage(race: int = 5) -> podsheet.PodSheetRecord:
    """A human magic-user 12 who left cleric 11 behind, so the former class is
    regained."""
    record = podsheet.PodSheetRecord(bytes(podsheet.SIZE))
    record.set_raw("name", b"\x05HILDE".ljust(16, b"\0"))
    record.set_raw("race", bytes((race,)))
    record.set_raw("class_bits", bytes((1,)))
    record.set_raw("class_levels", bytes((0, 0, 0, 0, 0, 12, 0)))
    record.set_raw("former_class_levels", bytes((11, 0, 0, 0, 0, 0, 0)))
    record.set_raw("former_level", bytes((11,)))
    record.set("intelligence", 18)
    record.set("wisdom", 18)
    return record


def test_the_dos_rebuilt_slots_of_a_regained_former_cleric_match_the_writer():
    record = _regained_cleric_mage()
    want = (7, 6, 5, 4, 2, 1, 0, 0, 0)
    assert saveplan._dos_rebuilt_slots(record)["spells_castable_cleric"] == (
        bytes(want))
    char = dos_codec.to_neutral(dos_codec.DosCharacter(record.to_bytes()))
    pc, _ = amiga_pod.to_pc(char)
    written = dict(amiga_pod.PodCharacter.from_bytes(pc).spells_castable)
    assert written["cleric"] == want


def test_the_dos_rebuilt_slots_of_a_non_human_leave_the_former_class_out():
    rebuilt = saveplan._dos_rebuilt_slots(_regained_cleric_mage(race=1))
    assert rebuilt["spells_castable_cleric"] == bytes(9)


# ---------------------------------------------------------------------------
# THAC0 and saving throws the DOS load rebuilds
# ---------------------------------------------------------------------------

_FIGHTER_14_SAVES = (5, 6, 7, 5, 8)
_FIGHTER_15_SAVES = (4, 5, 6, 4, 7)


def _fighter_14(folder: pathlib.Path) -> None:
    """Slot A's character as a human pure fighter 14 with constitution 18, the
    THAC0 and saving throws the game stored for him at that level."""
    path = folder / "CHRDATA1.SAV"
    record = podsheet.PodSheetRecord(path.read_bytes())
    record.set("level_fighter", 14)
    record.set("constitution", 18)
    record.set("thac0_base", 52)
    for name, value in zip(("save_paralysis", "save_petrification",
                            "save_wands", "save_breath", "save_spell"),
                           _FIGHTER_14_SAVES):
        record.set(name, value)
    path.write_bytes(record.to_bytes())


def _amiga_first_block(plan) -> bytes:
    [image] = plan.files.values()
    disk = AmigaDisk(bytearray(image))
    save = amiga_savegame.pod_parse(
        amiga_savegame.pod_read_slot(disk, "A"))
    return save.blocks[0]


def test_a_dos_level_edit_reaches_the_amiga_with_the_thac0_dos_shows(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    folder = _dos_folder(tmp_path)
    _fighter_14(folder)
    party = Party(convert.Source.detect(folder, slot="A"))
    party.members[0].record.set("level_fighter", 15)
    disk = _disk_file(tmp_path, _disk_three())
    plan = _to_amiga(party, tmp_path, disk)
    block = _amiga_first_block(plan)
    assert block[0x07F] == 54
    assert tuple(block[0x083:0x088]) == _FIGHTER_15_SAVES
    assert block[0x0AB] == 4
    assert block[0x089] == 15
    report = plan.report
    assert (report.dropped, report.losses, report.warnings) == ([], [], [])


def test_save_as_checks_the_rebuilt_thac0_against_what_the_writer_stored(
        monkeypatch, tmp_path):
    amiga = _amiga_destination(tmp_path)
    want, _ = _pair(monkeypatch, tmp_path)
    want.set("level_fighter", 15)
    want.set("constitution", 18)
    want.set("thac0_base", 52)
    for name, value in zip(("save_paralysis", "save_petrification",
                            "save_wands", "save_breath", "save_spell"),
                           _FIGHTER_14_SAVES):
        want.set(name, value)
    right = saveplan.PodCompared(want.to_bytes())
    right.items = want.items
    right.set("thac0_base", 54)
    # The current THAC0 moves by the base's two points.
    right.set("thac0_current", 2)
    right.set("level", 15)
    right.set_raw("attack_forms", bytes((4,) + (0,) * 7))
    for name, value in zip(("save_paralysis", "save_petrification",
                            "save_wands", "save_breath", "save_spell"),
                           _FIGHTER_15_SAVES):
        right.set(name, value)
    assert saveplan.compare([want], [right], amiga, source_port="dos") == []
    stale = saveplan.PodCompared(want.to_bytes())
    stale.items = want.items
    fields = [line.split(":")[0] for line in
              saveplan.compare([want], [stale], amiga, source_port="dos")]
    assert "thac0_base" in fields
    assert "save_paralysis" in fields


def test_every_dos_record_we_have_is_what_the_dos_load_rebuilds(
        monkeypatch, tmp_path):
    from goldbox import amiga_pod_recompute, pod_rewrite

    _flag(monkeypatch, "1")
    # Wish's own Save As output, not a game save.
    written_by_wish = ("pod-678-amiga-converted-walked-dos",
                       "wish2-l2r8-saveas-dos-strength-edit-vault40")
    seen: set[bytes] = set()
    found = []
    for source in _dos_sources():
        if source.slot == "A" and any(n in str(source.path)
                                      for n in written_by_wish):
            continue
        for member in Party(source).members:
            raw = member.record.to_bytes()
            if raw in seen:
                continue
            seen.add(raw)
            amiga = pod_rewrite.amiga_record_from_dos(raw)
            try:
                built = amiga_pod_recompute.recomputed_block(
                    amiga, dos_load=True)
            except amiga_pod_recompute.RecomputeError:
                continue
            found.append((source, member, amiga, built))
    if len(found) < 70:
        pytest.skip(f"needs the full set of Pools of Darkness DOS saves; "
                    f"found {len(found)} distinct records, not 70")
    for source, member, amiga, built in found:
        for name in amiga_pod_recompute.DOS_LOAD_FIELDS:
            at, size = pod_rewrite.AMIGA_PLACES[name].span
            assert built[at:at + size] == amiga[at:at + size], (
                source.path, source.slot, member.record.get("name"), name)

"""Writing a Pools of Darkness saved game -- DOS from an Amiga slot.

Commit 1 of `#194 (Import and export a Pools of Darkness save between DOS
and the Amiga)`: `goldbox.dos_codec.pod_savgam`/`new_pod_save_from`, and
`editor.convert.PodAmigaToDos` behind `WISH_EXPERIMENTAL_POD_CONVERT`.

`write_dos_save_from` cannot host this title (`_c64_game_of` refuses one
with no C64 port), so `pod_savgam` builds the 1364-byte `SAVGAM<slot>.PTY`
field by field rather than through `savgam_writes`/`savgam_zeroes`, which
reach `dos_savegame.word_offset` and refuse a byte-wide variable array.

**The specimens are the player's own DOS archives and Amiga disk images**,
read through `support.dossave._game_dirs()` and
`tools.amiga.podsavegame`/`tools.amiga.amigasaves`. Everything that needs
them skips cleanly without them, which is what CI does; the synthetic
buffers are built from the documented format and are nobody's game data.
"""
from __future__ import annotations

import dataclasses
import struct

import pytest
from support.dossave import _game_dirs

from editor import convert, saveplan
from goldbox import (
    amiga_pod,
    amiga_savegame,
    dos_codec,
    dos_port,
    dos_savegame,
    world_state,
)
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError

POD = dos_savegame.SAVE_POOLS_OF_DARKNESS


# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------

def _amiga_pod_source():
    import pathlib
    return convert.Source(port="amiga", title=dos_port.POOLS_OF_DARKNESS,
                          path=pathlib.Path("."))


def _c64_por_source():
    import pathlib

    from goldbox import c64_port
    return convert.Source(port="c64", title=c64_port.POOL_OF_RADIANCE,
                          path=pathlib.Path("."))


@pytest.mark.parametrize("value", [None, "0", "off", ""])
def test_pod_directions_are_not_offered_unless_the_flag_is_set(
        monkeypatch, value):
    if value is None:
        monkeypatch.delenv(convert.POD_CONVERT_ENV, raising=False)
    else:
        monkeypatch.setenv(convert.POD_CONVERT_ENV, value)
    assert convert.destinations_for(_amiga_pod_source()) == []


def test_pod_directions_are_offered_once_the_flag_is_set(monkeypatch):
    monkeypatch.setenv(convert.POD_CONVERT_ENV, "1")
    directions = convert.destinations_for(_amiga_pod_source())
    assert [type(d) for d in directions] == [convert.PodAmigaToDos]
    # The C64-shared rows are untouched: a Pool of Radiance C64 source still
    # answers the same two directions it always has.
    assert [type(d) for d in convert.destinations_for(_c64_por_source())] == [
        convert.C64ToDos, convert.C64ToAmiga]


# ---------------------------------------------------------------------------
# `pod_savgam`, against a synthetic state
# ---------------------------------------------------------------------------

def _hand_built_pod_save(count: int = 3) -> bytearray:
    """A well-formed 1364-byte container, from the documented offsets rather
    than a game file. Non-zero everywhere `pod_savgam` writes."""
    out = bytearray(POD.size)
    variables = bytearray(dos_savegame.POD_VAR_COUNT)
    variables[dos_savegame.POD_PARTY_COUNT - 1] = count
    first = dos_savegame.POD_CLOCK - dos_savegame.POD_VAR_FIRST
    variables[first:first + dos_savegame.POD_CLOCK_DIGITS] = \
        bytes([1, 2, 3, 4, 5, 6, 7])
    out[:POD.var_bytes] = variables
    out[POD.pos_x] = 11
    out[POD.pos_y] = 22
    out[POD.pos_facing] = 3 * dos_savegame.FACING_SCALE
    out[POD.tail_scratch] = 44
    out[POD.tail_scratch + 1] = 55
    out[POD.previous_mode] = dos_savegame.POD_MODE_WILDERNESS
    out[POD.mode] = dos_savegame.POD_MODE_DUNGEON
    struct.pack_into("<H", out, dos_savegame.POD_MAP, 99)
    struct.pack_into("<H", out, dos_savegame.POD_MAP_BLOCK, 5)
    out[POD.party_size_byte] = count
    return out


def test_pod_savgam_round_trips_a_synthetic_state():
    raw = _hand_built_pod_save(3)
    state = world_state.pod_from_dos(bytes(raw))
    out, report = dos_codec.pod_savgam(state, "A", 3)
    assert world_state.pod_from_dos(bytes(out)) == state
    assert bytes(out[:POD.party_table]) == bytes(raw[:POD.party_table])
    assert report.unwritten == []


def test_pod_savgam_refuses_a_count_disagreeing_with_variable_32():
    raw = _hand_built_pod_save(3)
    state = world_state.pod_from_dos(bytes(raw))
    with pytest.raises(dos_codec.DosRecordError, match="variable 32"):
        dos_codec.pod_savgam(state, "A", 4)


# ---------------------------------------------------------------------------
# The vault: `PodVault`, its DOS codec and its Amiga codec (#651)
# ---------------------------------------------------------------------------

def _amiga_node(**fields) -> bytes:
    """One twenty-byte Amiga item node, big-endian, from `amiga_pod`'s own map."""
    raw = bytearray(amiga_pod.ITEM_FILE_SIZE)
    for name, value in fields.items():
        f, at = amiga_pod.ITEM_FIELDS[name], amiga_pod.ITEM_FIELD_AT[name]
        raw[at:at + f.size] = value.to_bytes(f.size, "big")
    return bytes(raw)


def _dos_item_record(type_index: int = 5) -> bytes:
    """A 63-byte DOS item record with `next` and `readied` already zero, so
    it round-trips through `pod_vault_to_dos` unchanged."""
    raw = bytearray(range(dos_port.ITEM_SIZE))
    for name in ("next", "readied"):
        f = dos_port.ITEM_FIELDS_BY_NAME[name]
        raw[f.offset:f.end] = bytes(f.size)
    raw[dos_port.ITEM_FIELDS_BY_NAME["type_index"].offset] = type_index
    return bytes(raw)


def _amiga_vault(header: tuple[int, int, int], count: int, body: bytes,
                 marker: int = amiga_savegame.POD_VAULT_MARKER) -> bytes:
    return (struct.pack(">III", *header) + struct.pack(">HH", marker, count)
            + body)


def test_amiga_to_dos_decode_splits_the_case_and_swaps_the_long_sword_type():
    sword = _amiga_node(type_index=1, weight=60, quantity=1)
    case = _amiga_node(type_index=0x49, quantity=2, weight=2)
    mage = _amiga_node(type_index=39, charges=5, effect=6, power=7,
                       weight=1, quantity=1)
    cleric = _amiga_node(type_index=40, charges=8, effect=9, power=10,
                         weight=1, quantity=1)
    longsword = _amiga_node(type_index=105, weight=80, quantity=1)
    data = _amiga_vault((1, 2, 3), 3, sword + case + mage + cleric + longsword)
    data += bytes(amiga_savegame.POD_VAULT_SIZE - len(data))

    vault = amiga_savegame.pod_vault_from_amiga(data)
    assert (vault.platinum, vault.gems, vault.jewelry) == (1, 2, 3)
    assert len(vault.items) == 4
    got = [dos_codec.DosItem(r) for r in vault.items]
    assert [(i.get("type_index"), i.get("weight")) for i in got] == [
        (1, 60), (39, 2), (40, 2), (73, 80)]
    assert [(i.get("charges"), i.get("effect"), i.get("power"))
           for i in got[1:3]] == [(5, 6, 7), (8, 9, 10)]
    for record in vault.items:
        f = dos_port.ITEM_FIELDS_BY_NAME["next"]
        assert record[f.offset:f.end] == bytes(f.size)
        assert record[dos_port.ITEM_FIELDS_BY_NAME["readied"].offset] == 0


def test_pod_vault_round_trips_through_dos_bytes():
    v = dos_codec.PodVault(1, 2, 3, (_dos_item_record(5), _dos_item_record(9)))
    assert dos_codec.pod_vault_from_dos(dos_codec.pod_vault_to_dos(v)) == v
    assert dos_codec.pod_vault_to_dos(dos_codec.EMPTY_POD_VAULT) == bytes(12)
    assert dos_codec.pod_vault_from_dos(bytes(12)) == dos_codec.EMPTY_POD_VAULT


def test_pod_vault_round_trips_two_hundred_case_free_items():
    items = tuple(_dos_item_record(n % 128) for n in range(200))
    v = dos_codec.PodVault(0, 0, 0, items)
    raw = dos_codec.pod_vault_to_dos(v)
    assert len(raw) == 12 + 63 * 200
    assert dos_codec.pod_vault_from_dos(raw) == v


def test_pod_vault_from_dos_refuses_a_partial_trailing_record():
    with pytest.raises(dos_codec.DosRecordError):
        dos_codec.pod_vault_from_dos(bytes(12 + 63 + 5))


def test_pod_vault_from_amiga_refuses_a_wrong_marker():
    data = _amiga_vault((0, 0, 0), 0, b"", marker=0x1234)
    with pytest.raises(amiga_savegame.AmigaSaveError, match="marker"):
        amiga_savegame.pod_vault_from_amiga(data)


def test_pod_vault_from_amiga_refuses_a_case_walking_past_two_hundred_nodes():
    case = _amiga_node(type_index=0x49, quantity=201)
    scroll = _amiga_node(type_index=39, quantity=0)
    data = _amiga_vault((0, 0, 0), 1, case + scroll * 201)
    with pytest.raises(amiga_savegame.AmigaSaveError, match="200"):
        amiga_savegame.pod_vault_from_amiga(data)


def test_pod_vault_to_amiga_round_trips_case_free_items():
    one = amiga_pod.PodItem.from_bytes(
        _amiga_node(type_index=1, weight=10, quantity=1)).to_dos_bytes()
    two = amiga_pod.PodItem.from_bytes(
        _amiga_node(type_index=2, weight=20, quantity=3)).to_dos_bytes()
    v = dos_codec.PodVault(10, 20, 30, (one, two))
    raw = amiga_savegame.pod_vault_to_amiga(v)
    assert len(raw) == amiga_savegame.POD_VAULT_SIZE
    assert raw[16 + 2 * amiga_savegame.POD_ITEM_BYTES:] == bytes(
        amiga_savegame.POD_VAULT_SIZE - 16 - 2 * amiga_savegame.POD_ITEM_BYTES)
    assert amiga_savegame.pod_vault_from_amiga(raw) == v


def test_pod_vault_to_amiga_refuses_more_than_two_hundred_items():
    v = dos_codec.PodVault(0, 0, 0, tuple(_dos_item_record() for _ in range(201)))
    with pytest.raises(amiga_savegame.AmigaSaveError, match="200"):
        amiga_savegame.pod_vault_to_amiga(v)


def test_pod_vault_to_amiga_refuses_a_dos_type_105_record():
    v = dos_codec.PodVault(0, 0, 0, (_dos_item_record(105),))
    with pytest.raises(amiga_savegame.AmigaSaveError, match="105"):
        amiga_savegame.pod_vault_to_amiga(v)


def test_pod_vault_to_amiga_accepts_exactly_two_hundred_items():
    v = dos_codec.PodVault(0, 0, 0, tuple(_dos_item_record() for _ in range(200)))
    raw = amiga_savegame.pod_vault_to_amiga(v)
    assert len(raw) == amiga_savegame.POD_VAULT_SIZE


def test_pod_vault_from_amiga_accepts_exactly_two_hundred_nodes():
    head = _amiga_node(type_index=1, weight=1, quantity=1)
    data = _amiga_vault((0, 0, 0), 200, head * 200)
    data += bytes(amiga_savegame.POD_VAULT_SIZE - len(data))
    vault = amiga_savegame.pod_vault_from_amiga(data)
    assert len(vault.items) == 200


# ---------------------------------------------------------------------------
# `pod_read_vault`: a missing file is empty, a corrupt one is a refusal (#651)
# ---------------------------------------------------------------------------

class _CorruptOnRead:
    """A real `AmigaDisk`, wrapped so one named path's `read_file` raises,
    while `lookup`/`entries` still show it in the drawer listing -- a
    corrupt file, not an absent one."""

    def __init__(self, disk: AmigaDisk, corrupt_path: str):
        self._disk = disk
        self._corrupt_path = corrupt_path.upper()

    def lookup(self, path):
        return self._disk.lookup(path)

    def entries(self, header=None):
        return self._disk.entries(header)

    def read_file(self, path):
        if path.upper() == self._corrupt_path:
            raise AmigaDiskError("simulated corruption")
        return self._disk.read_file(path)


def test_pod_read_vault_is_empty_with_no_save_drawer():
    disk = AmigaDisk.blank()
    assert amiga_savegame.pod_read_vault(disk, "A") == dos_codec.EMPTY_POD_VAULT


def test_pod_read_vault_is_empty_with_no_vault_file():
    disk = AmigaDisk.blank()
    disk.make_dir("/SAVE")
    assert amiga_savegame.pod_read_vault(disk, "A") == dos_codec.EMPTY_POD_VAULT


def test_pod_read_vault_raises_on_a_vault_file_that_exists_but_is_corrupt():
    disk = AmigaDisk.blank()
    disk.make_dir("/SAVE")
    path = amiga_savegame.pod_vault_path("A")
    disk.write_file(path, bytes(amiga_savegame.POD_VAULT_SIZE))
    wrapped = _CorruptOnRead(disk, path)
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_read_vault(wrapped, "A")


# ---------------------------------------------------------------------------
# Every DOS Pools of Darkness specimen, rebuilt byte for byte
# ---------------------------------------------------------------------------

def _pod_dos_dir():
    dirs = _game_dirs()
    if "Pools of Darkness" not in dirs:
        pytest.skip("needs the Pools of Darkness DOS archive; set $FR_ARCHIVES")
    return dirs["Pools of Darkness"]


def test_every_dos_pools_of_darkness_specimen_rebuilds_byte_for_byte():
    """`support.dossave._game_dirs()`, not `tools.dos.dossavgam.containers`,
    which buckets by container size and would put Treasures of the Savage
    Frontier's two 1364-byte files in the same bucket."""
    folder = _pod_dos_dir()
    found = sorted(folder.glob("SAVGAM?.PTY"))
    if not found:
        pytest.skip("no Pools of Darkness SAVGAM?.PTY in the archive")
    for path in found:
        letter = path.stem[-1]
        raw = path.read_bytes()
        state = world_state.pod_from_dos(raw)
        out, report = dos_codec.pod_savgam(state, letter, state.count)
        # The mask comes from the report and the count, not from the diff:
        # the bytes noted PARTY_TABLE_SCRATCH, and the name entries past
        # count, which the engine left as stack there and this writer fills.
        mask = {i for i, why in report.sources.items()
                if why == dos_codec.PARTY_TABLE_SCRATCH}
        for n in range(dos_savegame.PARTY_ENTRIES):
            if n >= state.count:
                at = POD.party_table + n * dos_savegame.PARTY_ENTRY
                mask.update(range(at, at + dos_savegame.PARTY_ENTRY))
        diff = [i for i in range(len(raw)) if raw[i] != out[i] and i not in mask]
        assert diff == [], (path, diff[:10])


# ---------------------------------------------------------------------------
# `new_pod_save_from`, against every played Amiga slot
# ---------------------------------------------------------------------------

def _pod_amiga_slots():
    from tools.amiga import podsavegame

    found = podsavegame.slots()
    if not found:
        pytest.skip("no Amiga Pools of Darkness saved game; set $AMIGA_DISKS")
    return [(f"{name}#{i}" if i else name, blob)
            for name, copies in found.items()
            for i, (_label, blob) in enumerate(copies)]


def _pod_amiga_disks_with_vaults():
    """Each disk-and-slot holding a Pools of Darkness saved game, alongside
    its already-open `AmigaDisk`, so the vault beside the same slot can be
    read too. Skips cleanly with no disks, as `_pod_amiga_slots` does."""
    from tools.amiga import amigasaves

    found = []
    for label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
        except (AmigaDiskError, ValueError):
            continue
        try:
            slots = amiga_savegame.pod_slots_present(disk)
        except amiga_savegame.AmigaSaveError:
            continue
        for letter in slots:
            found.append((f"{label}:{letter}", disk, letter))
    if not found:
        pytest.skip("no Amiga Pools of Darkness saved game; set $AMIGA_DISKS")
    return found


def test_new_pod_save_from_writes_every_played_amiga_slot(tmp_path):
    """Also proves the vault converts rather than being written empty: the
    2026-09-23 comment measured this loses 40 to 99 items on five of six
    distinct played vaults. The distinct record counts, once cases are
    split, are the ones the 2026-09-27 plan measured: 0, 64, 97, 88, 99, 40."""
    seen = 0
    distinct_counts = set()
    for name, disk, letter in _pod_amiga_disks_with_vaults():
        seen += 1
        blob = amiga_savegame.pod_read_slot(disk, letter)
        state = amiga_savegame.pod_from_amiga(blob, source=name)
        characters = [amiga_pod.pod_to_neutral(block)
                     for block in amiga_savegame.pod_parse(blob).blocks]
        vault = amiga_savegame.pod_read_vault(disk, letter)
        out = tmp_path / f"slot{seen}"
        report = dos_codec.new_pod_save_from(
            state, characters, out, "A", vault=vault)

        raw = (out / "SAVGAMA.PTY").read_bytes()
        assert (dataclasses.replace(world_state.pod_from_dos(raw), source="")
               == dataclasses.replace(state, source="")), name
        got_vault = dos_codec.pod_vault_from_dos(
            (out / "VAULTA.DAT").read_bytes())
        assert got_vault == vault, name
        distinct_counts.add(len(vault.items))
        assert sorted(p.name for p in out.glob("CHRDATA*.SAV")) == [
            f"CHRDATA{n}.SAV" for n in range(1, len(characters) + 1)], name

        party = dos_codec.read_party(out, "A")
        assert [c.name for c in party] == [
            c.get("name") for c in characters], name

        assert report.dropped == [], name
        assert report.losses == [], name
    assert seen >= 8
    assert distinct_counts == {0, 64, 97, 88, 99, 40}


def test_a_converted_slot_weighs_what_the_amiga_computed(tmp_path):
    """The Amiga's stored encumbrance is `money + sum(weight x quantity)`
    with a scroll case counted as one item; DOS recounts from the scrolls
    themselves, so the scrolls must weigh what their case did."""
    seen = 0
    for name, blob in _pod_amiga_slots():
        characters, stored = [], []
        for block in amiga_savegame.pod_parse(blob).blocks:
            seen += 1
            characters.append(amiga_pod.pod_to_neutral(block))
            stored.append(amiga_pod.PodCharacter.from_bytes(block).encumbrance)
        state = amiga_savegame.pod_from_amiga(blob, source=name)
        out = tmp_path / f"slot{seen}"
        dos_codec.new_pod_save_from(state, characters, out, "A",
                                    vault=dos_codec.EMPTY_POD_VAULT)
        got = [c.expected_encumbrance()
               for c in dos_codec.read_party(out, "A")]
        assert got == stored, name
    assert seen > 0


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_an_amiga_disk_holding_pod_slots_is_detected(tmp_path):
    from tools.amiga import amigasaves

    seen = 0
    for label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
        except (AmigaDiskError, ValueError):
            continue
        try:
            slots = amiga_savegame.pod_slots_present(disk)
        except amiga_savegame.AmigaSaveError:
            continue
        if not slots:
            continue
        seen += 1
        path = tmp_path / f"disk3-{seen}.adf"
        path.write_bytes(data)
        source = convert.Source.detect(path)
        assert source.port == "amiga", label
        assert source.key == "pools-of-darkness", label
        assert source.available_slots == slots, label
    if not seen:
        pytest.skip("no Amiga disk with a Pools of Darkness saved game; "
                    "set $AMIGA_DISKS")


def _synthetic_amiga_pod_save(count: int = 1) -> bytes:
    """A well-formed Amiga Pools of Darkness savegame, from the documented
    format rather than a game file -- `tools/amiga/podsavegame.py`'s own
    `build()` helper, minimal and self-contained here."""
    out = bytearray(amiga_savegame.POD_VAR_BYTES)
    out[dos_savegame.POD_PARTY_COUNT - 1] = count
    out += bytes((3, 4, 2, 5, 137, 0))   # x, y, facing, wall, property, pad
    out += bytes((dos_savegame.POD_MODE_DUNGEON, dos_savegame.POD_MODE_DUNGEON))
    out += struct.pack(">HHH", 6, 0, count)
    for n in range(count):
        record = bytearray(b"\x5A" * amiga_savegame.POD_RECORD_BYTES)
        struct.pack_into(">I", record, amiga_savegame.POD_ITEM_COUNT_AT, 0)
        struct.pack_into(">I", record, amiga_savegame.POD_EFFECT_HEAD_AT, 0)
        name = f"WHO{n}".encode()
        record[amiga_savegame.POD_NAME_AT:
              amiga_savegame.POD_NAME_AT + len(name) + 1] = name + b"\x00"
        out += record
    out += b"\xA5" * (amiga_savegame.POD_SAVEGAME_SIZE - len(out))
    return bytes(out)


def test_a_built_amiga_disk_with_one_pod_slot_is_detected():
    disk = AmigaDisk.blank("PDARKSAVE")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(amiga_savegame.pod_slot_path("A"),
                    _synthetic_amiga_pod_save())
    assert amiga_savegame.pod_slots_present(disk) == ["A"]


def test_a_curse_save_disk_has_no_pod_slot():
    """The two containers name their slot differently -- `SavGamA.pty`
    against `savgamA.dat` -- so a legitimate Curse save disk answers no
    Pools of Darkness slots without `pod_slots_present` ever having to
    parse the file it does not own."""
    from support.amigasavegame import synthetic_curse

    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA",)))
    assert amiga_savegame.pod_slots_present(disk) == []


# ---------------------------------------------------------------------------
# The row, end to end
# ---------------------------------------------------------------------------

def test_the_pod_amiga_to_dos_row_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv(convert.POD_CONVERT_ENV, "1")
    from tools.amiga import amigasaves

    for label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
            slots = amiga_savegame.pod_slots_present(disk)
        except (AmigaDiskError, ValueError, amiga_savegame.AmigaSaveError):
            continue
        if slots:
            break
    else:
        pytest.skip("no Amiga disk with a Pools of Darkness saved game; "
                    "set $AMIGA_DISKS")

    path = tmp_path / "disk3.adf"
    path.write_bytes(data)
    source = convert.Source.detect(path)
    assert source.port == "amiga" and source.key == "pools-of-darkness"

    assert saveplan.requirements(source, "dos") == ()
    direction = convert.destinations_for(source)[0]
    rehearsal, slot = saveplan.rehearse(direction, source, saveplan.Assets())
    assert slot == "A"
    assert "SAVGAMA.PTY" in rehearsal.files
    assert "VAULTA.DAT" in rehearsal.files
    assert any(name.startswith("CHRDATA") and name.endswith(".SAV")
              for name in rehearsal.files)


# ---------------------------------------------------------------------------
# Commit 2: the class bits of a former ranger, and `pod_new_savegame`
# ---------------------------------------------------------------------------

def test_a_magic_user_who_was_a_ranger_reads_back_as_class_bits_129():
    """DOS reads the same character as 129; without the former levels the
    ranger's bit 6 reads as a paladin and `write_pod` refuses him."""
    slots = amiga_pod.CLASS_LEVEL_SLOTS
    levels = [0] * len(slots)
    levels[slots.index("MAGIC-USER")] = 13
    former = [0] * len(slots)
    former[slots.index("RANGER")] = 9
    raw = amiga_pod.PodWriter(
        name="DUAL", hit_points_max=30, level=13,
        character_class=amiga_pod.CLASSES.index("MAGIC-USER"),
        class_levels=tuple(levels), former_class_levels=tuple(former),
        class_bits=amiga_pod.CLASS_BIT["magic-user"]
        | amiga_pod.CLASS_BIT["ranger"]).to_bytes()
    char = amiga_pod.pod_to_neutral(raw)
    assert char.get("class_bits") == 129
    amiga_pod.write_pod(char)


def test_write_pod_accepts_every_block_of_every_played_slot():
    for label, blob in _pod_amiga_slots():
        for block in amiga_savegame.pod_parse(blob).blocks:
            try:
                amiga_pod.write_pod(amiga_pod.pod_to_neutral(block))
            except ValueError as error:
                pytest.fail(f"{label}: {error}")


def _round_trip_new_savegame(blob: bytes):
    save = amiga_savegame.pod_parse(blob)
    state = amiga_savegame.pod_from_amiga(blob)
    characters = [amiga_pod.pod_to_neutral(b) for b in save.blocks]
    built, report = amiga_savegame.pod_new_savegame(state, characters)
    return save, state, built, report


def test_pod_new_savegame_rebuilds_every_played_amiga_slot():
    for label, blob in _pod_amiga_slots():
        save, state, built, report = _round_trip_new_savegame(blob)
        at = amiga_savegame.POD_PARTY_AT
        assert built[:at] == blob[:at], label
        rebuilt = amiga_savegame.pod_parse(built)
        # A scroll case converts to its own scrolls (#650), so a block that
        # held one comes back with no bundle and a different size.
        for was, now in zip(save.characters, rebuilt.characters):
            if was.bundled:
                # Every scroll of the case becomes an item of its own and the
                # case itself goes: these four blocks each hold one case.
                assert now.bundled == 0, (label, was.name)
                assert now.items == was.items - 1 + was.bundled, (
                    label, was.name)
            else:
                assert now.size == was.size, (label, was.name)
        assert amiga_savegame.pod_from_amiga(built) == state, label
        assert len(built) == amiga_savegame.POD_SAVEGAME_SIZE, label
        assert report.unwritten == []
        assert [c.name.strip() for c in rebuilt.characters] == \
            [c.name.strip() for c in save.characters], label


#: Neutral fields a rebuilt block legitimately reads back differently: the
#: game recomputes the first five on load, and the icon is the engine's own
#: default rather than the source's. `name` is compared stripped.
_REBUILD_DIFFERS = {"armour_class", "roster_tail", "movement_current",
                    "thac0_current", "encumbrance", "combat_figure", "name"}


def _rebuilt_characters(blob: bytes):
    save, _state, built, _report = _round_trip_new_savegame(blob)
    return zip(save.blocks, amiga_savegame.pod_parse(built).blocks)


def _neutral_diffs(blob: bytes, fields=None) -> list[tuple[int, str]]:
    out = []
    for i, (was, now) in enumerate(_rebuilt_characters(blob)):
        a, b = amiga_pod.pod_to_neutral(was), amiga_pod.pod_to_neutral(now)
        assert str(a.get("name")).strip() == str(b.get("name")).strip()
        for name in set(a.keys()) | set(b.keys()):
            if name in _REBUILD_DIFFERS:
                continue
            if fields is not None and name not in fields:
                continue
            if fields is None and name in _KNOWN_REBUILD_DIFFS:
                continue
            if a.get(name) != b.get(name):
                out.append((i, name))
    return out


#: Two fields that do change on a rebuild, tracked on #735.
_KNOWN_REBUILD_DIFFS = ("class_bits", "spells_memorised")


def test_pod_new_savegame_keeps_every_played_character_field():
    for label, blob in _pod_amiga_slots():
        assert _neutral_diffs(blob) == [], label


@pytest.mark.xfail(strict=True, reason="#735: class_bits and the order of "
                   "spells_memorised change on a rebuild")
def test_pod_new_savegame_keeps_class_bits_and_spell_order():
    diffs = []
    for label, blob in _pod_amiga_slots():
        diffs += [(label, *d) for d in
                  _neutral_diffs(blob, fields=_KNOWN_REBUILD_DIFFS)]
    assert diffs == []


def test_pod_new_savegame_rebuilds_every_dos_specimen():
    folder = _pod_dos_dir()
    found = sorted(folder.glob("SAVGAM?.PTY"))
    if not found:
        pytest.skip("no Pools of Darkness SAVGAM?.PTY in the archive")
    for path in found:
        letter = path.stem[-1]
        state = world_state.pod_from_dos(path.read_bytes())
        party = dos_codec.read_party(folder, letter)
        characters = [dos_codec.to_neutral(c) for c in party]
        state = dataclasses.replace(state, count=len(characters))
        built, _report = amiga_savegame.pod_new_savegame(state, characters)
        assert len(built) == amiga_savegame.POD_SAVEGAME_SIZE
        assert amiga_savegame.pod_from_amiga(built) == dataclasses.replace(
            state, source="")


def _synthetic_state(count: int) -> world_state.PodWorldState:
    return amiga_savegame.pod_from_amiga(_synthetic_amiga_pod_save(count))


def _synthetic_fighter(name: str) -> bytes:
    return amiga_pod.PodWriter(
        name=name, hit_points_max=9,
        character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 3, 0, 0, 0, 0),
        class_bits=amiga_pod.CLASS_BIT["fighter"]).to_bytes()


def test_pod_new_savegame_builds_one_synthetic_character():
    state = _synthetic_state(1)
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    built, report = amiga_savegame.pod_new_savegame(state, [char])
    assert len(built) == amiga_savegame.POD_SAVEGAME_SIZE
    assert amiga_savegame.pod_from_amiga(built) == state
    assert amiga_savegame.pod_parse(built).characters[0].name == "ONE"
    assert report.unwritten == []


def test_pod_new_savegame_refuses_a_party_the_state_does_not_count():
    state = _synthetic_state(2)
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_new_savegame(state, [char])
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_new_savegame(state, [])
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_new_savegame(state, [char] * 9)


@pytest.mark.parametrize("count", [0, 9])
def test_pod_new_savegame_refuses_a_party_outside_one_to_eight(count):
    # The state counts the same number, so only the range check can refuse.
    state = dataclasses.replace(_synthetic_state(1), count=count)
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    with pytest.raises(amiga_savegame.AmigaSaveError, match="1 to"):
        amiga_savegame.pod_new_savegame(state, [char] * count)

"""Writing a Pools of Darkness saved game -- DOS from an Amiga slot.

Commit 1 of `#194 (Import and export a Pools of Darkness save between DOS
and the Amiga)`: `goldbox.dos_codec.pod_savgam`/`new_pod_save_from`, and
`editor.convert.PodAmigaToDos` behind `WISH_EXPERIMENTAL_POD_CONVERT`.

`write_dos_save_from` cannot host this title (`_c64_game_of` blocks one
with no C64 port), so `pod_savgam` builds the 1364-byte `SAVGAM<slot>.PTY`
field by field rather than through `savgam_writes`/`savgam_zeroes`, which
reach `dos_savegame.word_offset` and block a byte-wide variable array.

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
from support.dossave import _game_dirs, _records

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


def test_pod_savgam_blocks_a_count_disagreeing_with_variable_32():
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


def test_pod_vault_from_dos_blocks_a_partial_trailing_record():
    with pytest.raises(dos_codec.DosRecordError):
        dos_codec.pod_vault_from_dos(bytes(12 + 63 + 5))


def test_pod_vault_from_amiga_blocks_a_wrong_marker():
    data = _amiga_vault((0, 0, 0), 0, b"", marker=0x1234)
    with pytest.raises(amiga_savegame.AmigaSaveError, match="marker"):
        amiga_savegame.pod_vault_from_amiga(data)


def test_pod_vault_from_amiga_blocks_more_nodes_than_the_game_pool_holds():
    case = _amiga_node(type_index=0x49, quantity=200)
    scroll = _amiga_node(type_index=39, quantity=0)
    data = _amiga_vault((0, 0, 0), 51, case + scroll * 200 + case + scroll * 200
                        + _amiga_node(type_index=1, quantity=1) * 49)
    with pytest.raises(amiga_savegame.AmigaSaveError, match="holds more items"):
        amiga_savegame.pod_vault_from_amiga(data)


def test_pod_vault_from_amiga_reads_a_vault_past_two_hundred_nodes():
    case = _amiga_node(type_index=0x49, quantity=2)
    scroll = _amiga_node(type_index=39, quantity=0)
    sword = _amiga_node(type_index=1, quantity=1)
    data = _amiga_vault((0, 0, 0), 199, sword * 198 + case + scroll * 2)
    assert len(amiga_savegame.pod_vault_from_amiga(data).items) == 200


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


def _bundled_party() -> bytes:
    """A two-member party whose item nodes (P) are 3 + (2 + 4 scrolls) = 9."""
    out = bytearray(amiga_savegame.POD_VAR_BYTES)
    out[dos_savegame.POD_PARTY_COUNT - 1] = 2
    out += bytes((3, 4, 2, 5, 137, 0))
    out += bytes((dos_savegame.POD_MODE_DUNGEON, dos_savegame.POD_MODE_DUNGEON))
    out += struct.pack(">HHH", 6, 0, 2)
    plain = _amiga_node(type_index=1, quantity=1)
    bundle = bytearray(plain)
    bundle[0] = amiga_savegame.POD_BUNDLE_ID
    bundle[amiga_savegame.POD_BUNDLE_COUNT] = 4
    for n, nodes in enumerate((plain * 3, plain + bytes(bundle) + plain * 4)):
        record = bytearray(b"\x5A" * amiga_savegame.POD_RECORD_BYTES)
        struct.pack_into(">I", record, amiga_savegame.POD_ITEM_COUNT_AT,
                         (3, 2)[n])
        struct.pack_into(">I", record, amiga_savegame.POD_EFFECT_HEAD_AT, 0)
        name = f"WHO{n}".encode()
        record[amiga_savegame.POD_NAME_AT:
               amiga_savegame.POD_NAME_AT + len(name) + 1] = name + b"\x00"
        out += record + nodes
    out += b"\xA5" * (amiga_savegame.POD_SAVEGAME_SIZE - len(out))
    return bytes(out)


def _items(n: int) -> dos_codec.PodVault:
    return dos_codec.PodVault(
        7, 8, 9, tuple(_dos_item_record(1 + i % 100) for i in range(n)))


def test_pod_party_nodes_counts_items_and_bundled_scrolls():
    assert amiga_savegame.pod_party_nodes(_bundled_party()) == 9


@pytest.mark.parametrize("n", [201, 445 - 9])
def test_pod_vault_past_two_hundred_converts_both_ways_with_every_item(n):
    v = _items(n)
    raw = amiga_savegame.pod_vault_to_amiga(v, 9)
    assert len(raw) == 16 + 20 * n
    assert struct.unpack_from(">HH", raw, 12) == (0xFFFF, n)
    back = amiga_savegame.pod_vault_from_amiga(raw)
    assert len(back.items) == n
    assert (back.platinum, back.gems, back.jewelry) == (7, 8, 9)
    assert amiga_savegame.pod_vault_to_amiga(back, 9) == raw


def test_amiga_to_dos_converts_a_full_pool_vault_to_every_dos_record(
        tmp_path, monkeypatch):
    """The DOS loader has no count and no cap, so all 448 nodes the Amiga
    pool can hold arrive as 448 DOS records."""
    monkeypatch.setenv(convert.POD_CONVERT_ENV, "1")
    state = _synthetic_state(1)
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    built, _ = amiga_savegame.pod_new_savegame(state, [char])
    n = 448
    sword = _amiga_node(type_index=1, weight=60, quantity=1)
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(amiga_savegame.pod_slot_path("A"), built)
    disk.write_file(amiga_savegame.pod_vault_path("A"),
                    _amiga_vault((7, 8, 9), n, sword * n))
    path = tmp_path / "disk3.adf"
    path.write_bytes(disk.to_bytes())

    rehearsal = convert.PodAmigaToDos().rehearse(
        convert.Source.detect(path), "A", None)

    raw = rehearsal.files["VAULTA.DAT"]
    assert len(raw) == 12 + dos_port.ITEM_SIZE * n
    assert len(dos_codec.pod_vault_from_dos(raw).items) == n


def test_pod_vault_one_past_the_pool_headroom_stops():
    with pytest.raises(amiga_savegame.AmigaSaveError, match="room for 436"):
        amiga_savegame.pod_vault_to_amiga(_items(446 - 9), 9)


def test_pod_vault_past_two_hundred_needs_the_party_count():
    with pytest.raises(amiga_savegame.AmigaSaveError, match="pool"):
        amiga_savegame.pod_vault_to_amiga(_items(201))


def test_pod_vault_of_two_hundred_or_fewer_ignores_the_party_count():
    v = _items(150)
    assert (amiga_savegame.pod_vault_to_amiga(v)
            == amiga_savegame.pod_vault_to_amiga(v, 400))


def test_pod_slot_on_disk_three_writes_a_vault_past_two_hundred_nodes():
    party = _bundled_party()
    vault = amiga_savegame.pod_vault_to_amiga(_items(436), 9)
    out = amiga_savegame.pod_slot_on_disk_three(
        _synthetic_disk_three("A"), "B", party, vault)
    assert out.read_file(amiga_savegame.pod_vault_path("B")) == vault


def test_pod_slot_on_disk_three_stops_a_vault_the_pool_cannot_hold():
    party = _bundled_party()
    vault = amiga_savegame.pod_vault_to_amiga(_items(436), 9)
    bigger = vault + _amiga_node(type_index=1, quantity=1)
    bigger = bigger[:12] + struct.pack(">HH", 0xFFFF, 437) + bigger[16:]
    with pytest.raises(amiga_savegame.AmigaSaveError, match="room for 436"):
        amiga_savegame.pod_slot_on_disk_three(
            _synthetic_disk_three("A"), "B", party, bigger)


def test_pod_vault_to_amiga_blocks_a_dos_type_105_record():
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
# `pod_read_vault`: a missing file is empty, a corrupt one is a rejection (#651)
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
    ranger's bit 6 reads as a paladin and `write_pod` blocks him."""
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


def _dual_class_magic_user(former_cleric: int) -> "amiga_pod.PodWriter":
    slots = amiga_pod.CLASS_LEVEL_SLOTS
    levels = [0] * len(slots)
    levels[slots.index("MAGIC-USER")] = 12
    former = [0] * len(slots)
    former[slots.index("CLERIC")] = former_cleric
    raw = amiga_pod.PodWriter(
        name="DUAL", hit_points_max=30, level=12,
        character_class=amiga_pod.CLASSES.index("MAGIC-USER"),
        class_levels=tuple(levels), former_class_levels=tuple(former),
        class_bits=3 if former_cleric < 12 else 1).to_bytes()
    return amiga_pod.write_pod(amiga_pod.pod_to_neutral(raw))[0]


def test_a_class_passed_in_level_keeps_its_bit_and_one_not_yet_passed_does_not():
    assert _dual_class_magic_user(11).class_bits == 3
    assert _dual_class_magic_user(13).class_bits == 1
    # The rule is strictly former < level: a former level equal to the
    # current one has not been passed.
    assert _dual_class_magic_user(12).class_bits == 1


def test_a_current_class_with_no_level_data_still_gets_its_bit():
    raw = amiga_pod.PodWriter(
        name="MAGE", hit_points_max=9, level=3,
        character_class=amiga_pod.CLASSES.index("MAGIC-USER"),
        class_levels=(0, 0, 0, 0, 0, 3, 0),
        class_bits=amiga_pod.CLASS_BIT["magic-user"]).to_bytes()
    char = amiga_pod.pod_to_neutral(raw)
    char.fields.pop("levels")
    assert amiga_pod.write_pod(char)[0].class_bits == 1


def test_pending_memorised_spells_keep_the_order_they_were_saved_in():
    saved = bytes((129, 1, 1, 1, 186, 186, 58, 58))
    raw = bytearray(amiga_pod.PodWriter(
        name="MAGE", hit_points_max=9, level=3,
        character_class=amiga_pod.CLASSES.index("MAGIC-USER"),
        class_levels=(0, 0, 0, 0, 0, 3, 0),
        class_bits=amiga_pod.CLASS_BIT["magic-user"]).to_bytes())
    at = amiga_pod.SPELLS_MEMORISED
    raw[at:at + len(saved)] = saved
    char = amiga_pod.pod_to_neutral(bytes(raw))
    rebuilt = amiga_pod.write_pod(char)[0].to_bytes()
    assert rebuilt[at:at + len(saved)] == saved


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


def _neutral_diffs(blob: bytes) -> list[tuple[int, str]]:
    out = []
    for i, (was, now) in enumerate(_rebuilt_characters(blob)):
        a, b = amiga_pod.pod_to_neutral(was), amiga_pod.pod_to_neutral(now)
        assert str(a.get("name")).strip() == str(b.get("name")).strip()
        for name in set(a.keys()) | set(b.keys()):
            if name in _REBUILD_DIFFERS:
                continue
            if a.get(name) != b.get(name):
                out.append((i, name))
    return out


def test_pod_new_savegame_keeps_every_played_character_field():
    for label, blob in _pod_amiga_slots():
        assert _neutral_diffs(blob) == [], label


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


def test_the_darkness_slot_reader_gives_each_character_s_effect_nodes():
    """`--expect` judges a Pools of Darkness run on this reading: one HEAL node,
    id 140 for 1380 minutes, comes back as its four fields under the name."""
    from tools.amiga import route_darkness
    from tools.amiga.route import effect_fields
    node = bytes((amiga_pod.LAY_ON_HANDS_AMIGA_ID, 0)) + struct.pack(">H", 1380) + bytes(6)
    fighter = amiga_pod.PodWriter(
        name="ONE", hit_points_max=9,
        character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 3, 0, 0, 0, 0),
        class_bits=amiga_pod.CLASS_BIT["fighter"], effects=(node,)).to_bytes()
    built, _ = amiga_savegame.pod_new_savegame(
        _synthetic_state(1), [amiga_pod.pod_to_neutral(fighter)])
    parsed = amiga_savegame.pod_parse(built)
    assert parsed.effect_nodes == tuple(
        amiga_pod.PodCharacter(block).effects for block in parsed.blocks) == ((node,),)
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(amiga_savegame.pod_slot_path("C"), built)
    reading = route_darkness.DARKNESS.read_slot(disk, "C")
    assert "decode_error" not in reading
    assert reading["effects"] == {"ONE": [list(effect_fields(node))]}
    assert reading["effects"] == {"ONE": [[140, 1380, 0, 0]]}


def test_pod_new_savegame_takes_a_neutral_record_with_no_paladin_cures():
    """A Pool of Radiance record has no cure-disease byte, so the neutral
    value is None; the writer leaves 0x080 zero and the plan still names it."""
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    char.fields.pop("paladin_cures", None)
    assert char.get("paladin_cures") is None
    built, report = amiga_savegame.pod_new_savegame(
        _synthetic_state(1), [char])
    assert report.unwritten == []
    assert built[amiga_savegame.POD_PARTY_AT + amiga_pod.PALADIN_CURES] == 0


def test_pod_new_savegame_builds_a_party_from_a_pool_of_radiance_record():
    name, raw = next(iter(_records().items()))
    char = dos_codec.to_neutral(dos_codec.DosCharacter(raw))
    assert char.get("paladin_cures") is None, name
    built, report = amiga_savegame.pod_new_savegame(
        _synthetic_state(1), [char])
    assert report.unwritten == [], name
    assert len(built) == amiga_savegame.POD_SAVEGAME_SIZE


#: The Amiga record's level-drain marks and ready-to-train byte: the highest
#: experience, the seven highest class levels, the highest hit points and the
#: flag the party list colours a name by.
_DRAIN_MARK_SPANS = ((0x048, 0x04C), (0x096, 0x09D), (0x0B6, 0x0B7),
                     (0x0CB, 0x0CC))


def test_pod_new_savegame_keeps_the_drain_marks_and_the_training_flag():
    """A rebuilt block holds the same bytes at the four places, where the
    writer used to leave them zero for 38 of the 88 played characters."""
    held = 0
    for label, blob in _pod_amiga_slots():
        for i, (was, now) in enumerate(_rebuilt_characters(blob)):
            for first, last in _DRAIN_MARK_SPANS:
                assert now[first:last] == was[first:last], (
                    label, i, hex(first))
                held += any(was[first:last])
    assert held > 0


def test_amiga_to_dos_keeps_the_drain_marks(tmp_path):
    """The DOS resave of a converted party carries the Amiga's marks and
    ready-to-train byte, which came out zero before."""
    held = 0
    for n, (name, disk, letter) in enumerate(_pod_amiga_disks_with_vaults()):
        blob = amiga_savegame.pod_read_slot(disk, letter)
        state = amiga_savegame.pod_from_amiga(blob, source=name)
        blocks = amiga_savegame.pod_parse(blob).blocks
        characters = [amiga_pod.pod_to_neutral(b) for b in blocks]
        out = tmp_path / f"slot{n}"
        dos_codec.new_pod_save_from(
            state, characters, out, "A",
            vault=amiga_savegame.pod_read_vault(disk, letter))
        party = dos_codec.read_party(out, "A")
        for block, char in zip(blocks, party):
            source = amiga_pod.PodCharacter.from_bytes(block)
            assert list(char.raw("highest_class_levels")) == \
                source.class_levels_highest, (name, char.name)
            assert char.get("highest_experience") == \
                source.experience_highest, (name, char.name)
            assert char.get("highest_hp_max") == source.hp_max_highest, (
                name, char.name)
            assert bool(char.get("ready_to_train")) == source.ready_to_train, (
                name, char.name)
            held += source.experience_highest > 0
    assert held > 0


def test_pod_new_savegame_credits_each_byte_it_leaves_zero_by_name():
    """The `unwritten` gate only means something when the writer says what it
    left zero: every byte of a block is a field the plan wrote or a row of
    `LEFT_ZERO` or `DERIVED`, none is a blanket credit, and a writer whose
    plan lost a field is blocked."""
    state = _synthetic_state(1)
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    built, report = amiga_savegame.pod_new_savegame(state, [char])
    at = amiga_savegame.POD_PARTY_AT
    size = amiga_savegame._pod_walk(built[at:], 0).size
    notes = {report.sources[at + offset] for offset in range(size)}
    assert not any("record writer leaves zero" in why for why in notes), notes
    for offset in (amiga_pod.CLASS_LEVELS_HIGHEST, amiga_pod.EXPERIENCE_HIGHEST,
                   amiga_pod.HP_MAX_HIGHEST, amiga_pod.READY_TO_TRAIN,
                   amiga_pod.FORMER_LEVEL, amiga_pod.NPC_CONTROL,
                   amiga_pod.FORMER_CLASS_LEVELS):
        assert not report.sources[at + offset].startswith("left zero"), (
            hex(offset), report.sources[at + offset])
    for first, last, why in amiga_pod.LEFT_ZERO:
        for offset in range(first, last + 1):
            if offset not in (amiga_pod.EFFECT_CHAIN, amiga_pod.ITEM_CHAIN):
                assert report.sources[at + offset] == f"left zero: {why}"


def test_pod_new_savegame_blocks_a_writer_whose_plan_lost_a_field(monkeypatch):
    plan = amiga_pod.PodWriter._plan

    def without_former_class_levels(self):
        return [row for row in plan(self)
                if row[2] != "former_class_levels"]

    monkeypatch.setattr(amiga_pod.PodWriter, "_plan",
                        without_former_class_levels)
    state = _synthetic_state(1)
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    with pytest.raises(amiga_savegame.AmigaSaveError, match="no source"):
        amiga_savegame.pod_new_savegame(state, [char])


def test_pod_new_savegame_blocks_a_party_the_state_does_not_count():
    state = _synthetic_state(2)
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_new_savegame(state, [char])
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_new_savegame(state, [])
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_new_savegame(state, [char] * 9)


@pytest.mark.parametrize("count", [0, 9])
def test_pod_new_savegame_blocks_a_party_outside_one_to_eight(count):
    # The state counts the same number, so only the range check can block.
    state = dataclasses.replace(_synthetic_state(1), count=count)
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    with pytest.raises(amiga_savegame.AmigaSaveError, match="1 to"):
        amiga_savegame.pod_new_savegame(state, [char] * count)


_NO_VALUE = "the neutral source has no value"


def _no_value_notes(char) -> set[str]:
    _rec, _, _, rep = dos_codec.write(char, dos_port.POOLS_OF_DARKNESS)
    return {why.split(":")[0] for why in rep.sources.values()
            if _NO_VALUE in why}


def test_an_explicit_zero_drain_mark_is_not_reported_as_missing():
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    assert char.get("highest_experience") == 0
    assert _no_value_notes(char) == set()


def test_a_missing_drain_mark_is_reported_as_missing():
    char = amiga_pod.pod_to_neutral(_synthetic_fighter("ONE"))
    for name in ("highest_levels", "highest_experience", "highest_hp_max",
                 "ready_to_train"):
        char.fields.pop(name)
    assert _no_value_notes(char) == {
        "highest_class_levels", "highest_experience", "highest_hp_max",
        "ready_to_train"}


# ---------------------------------------------------------------------------
# `pod_slot_on_disk_three`: the Pools of Darkness disk 3 with a slot written
# ---------------------------------------------------------------------------

def _synthetic_disk_three(held: str = "A", data_drawer: bool = True) -> AmigaDisk:
    """A disk 3 built from the documented drawers and nobody's game data,
    already holding slot `held` with a vault of its own."""
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    if data_drawer:
        disk.make_dir("/DISK3")
    disk.write_file(f"/{amiga_savegame.SAVE_DRAWER}/spindisk", b"\x01" * 40)
    disk.write_file(f"/{amiga_savegame.SAVE_DRAWER}/WRITE.ME", b"\x02" * 8)
    if data_drawer:
        disk.write_file("/DISK3/GEN.TLB", b"\x03" * 600)
    disk.write_file(amiga_savegame.pod_slot_path(held),
                    _synthetic_amiga_pod_save(2))
    disk.write_file(amiga_savegame.pod_vault_path(held),
                    b"\xEE" * amiga_savegame.POD_VAULT_SIZE)
    return disk


def _a_vault() -> bytes:
    return amiga_savegame.pod_vault_to_amiga(dos_codec.EMPTY_POD_VAULT)


def _files(disk: AmigaDisk) -> dict[str, bytes]:
    return {path.lower(): disk.read_file(path)
            for path, entry in disk.walk() if not entry.is_dir}


def test_pod_slot_on_disk_three_replaces_both_files_and_nothing_else():
    disk = _synthetic_disk_three("A")
    before = disk.to_bytes()
    built = _synthetic_amiga_pod_save(3)
    out = amiga_savegame.pod_slot_on_disk_three(
        disk, "A", built, _a_vault(), replace=True)
    assert disk.to_bytes() == before
    after, kept = _files(out), _files(disk)
    changed = {p for p in kept if kept[p] != after.get(p)}
    assert changed == {"/save/savgama.pty", "/save/vaulta.dat"}
    assert set(after) == set(kept)
    assert after["/save/savgama.pty"] == built
    assert after["/save/vaulta.dat"] == _a_vault()


def test_pod_slot_on_disk_three_adds_a_letter_the_disk_lacks():
    disk = _synthetic_disk_three("A")
    out = amiga_savegame.pod_slot_on_disk_three(
        disk, "e", _synthetic_amiga_pod_save(1), _a_vault())
    assert amiga_savegame.pod_slots_present(out) == ["A", "E"]
    assert _files(out)["/save/vaulta.dat"] == _files(disk)["/save/vaulta.dat"]
    assert out.read_file(amiga_savegame.pod_vault_path("E")) == _a_vault()


@pytest.mark.parametrize("drop", ["/DISK3", "/SAVE/spindisk", "/SAVE/WRITE.ME"])
def test_pod_slot_on_disk_three_blocks_a_disk_missing_a_marker(drop):
    disk = _synthetic_disk_three(data_drawer=drop != "/DISK3")
    if drop != "/DISK3":
        disk.remove_file(drop)
    with pytest.raises(AmigaDiskError):
        amiga_savegame.pod_slot_on_disk_three(
            disk, "A", _synthetic_amiga_pod_save(1), _a_vault())


def test_is_pod_disk_three_agrees_with_the_checks_the_writer_makes():
    assert amiga_savegame.is_pod_disk_three(_synthetic_disk_three())
    assert not amiga_savegame.is_pod_disk_three(
        _synthetic_disk_three(data_drawer=False))
    curse = AmigaDisk.blank("CurseA")
    curse.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    assert not amiga_savegame.is_pod_disk_three(curse)
    assert not amiga_savegame.is_pod_disk_three(AmigaDisk.blank("EMPTY"))


def test_pod_slot_on_disk_three_blocks_a_curse_disk_one():
    disk = AmigaDisk.blank("CurseA")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(f"/{amiga_savegame.SAVE_DRAWER}/spindisk", b"\x01")
    disk.write_file("/Curse", b"\x00" * 10)
    with pytest.raises(AmigaDiskError):
        amiga_savegame.pod_slot_on_disk_three(
            disk, "A", _synthetic_amiga_pod_save(1), _a_vault())


def test_pod_slot_on_disk_three_blocks_files_the_game_would_not_write():
    disk = _synthetic_disk_three()
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_slot_on_disk_three(
            disk, "A", _synthetic_amiga_pod_save(1)[:-1], _a_vault())
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_slot_on_disk_three(
            disk, "A", _synthetic_amiga_pod_save(1), _a_vault()[:-1])
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.pod_slot_on_disk_three(
            disk, "K", _synthetic_amiga_pod_save(1), _a_vault())


def _registered_disk_three() -> AmigaDisk:
    import hashlib

    from tools.amiga import amigasaves, route_darkness
    for _label, data in amigasaves.images():
        if (hashlib.sha256(data).hexdigest()
                == route_darkness.DARKNESS_DISK3_SHA256):
            return AmigaDisk(data)
    pytest.skip("needs the registered Pools of Darkness disk 3; set $AMIGA_DISKS")


#: The DOS specimens, each a folder the DOS game wrote a slot into: seven
#: from the game and slot A of `pod-678-amiga-converted-walked-dos`, which
#: Wish wrote.  Two hold no `VAULT<L>.DAT`.
_DOS_SLOT_SPECIMENS = (
    "dos-pod-foundation-walked",
    "pod-628-amiga-to-dos-eric-rest-heal",
    "pod-628-dos-lay-then-rest-1h",
    "pod-650-savgama-join-weight-dos",
    "pod-650-savgamb-walked-dos",
    "pod-678-amiga-converted-walked-dos",
)


def _pod_specimen(name: str, tree: str = "pod-dos"):
    """One specimen folder in *tree*, hashed against its own `provenance.toml`
    first so an edited file fails here rather than being measured.  Skips
    without the specimen tree."""
    import pathlib

    import gamedata

    from tools.registry import specimens
    root = gamedata.specimen_root()
    where = root / tree / f"WISH-SPEC-{name}" if root else None
    if where is None or not where.is_dir():
        pytest.skip(f"needs specimen WISH-SPEC-{name} in the {tree} tree; "
                    f"see tools/registry/specimens.py and $WISH_SPECIMENS")
    recorded = specimens.read_provenance(where / "provenance.toml").get(
        "sha256", {})
    for filename, expected in recorded.items():
        if specimens.sha256_file(where / filename) != expected:
            pytest.fail(f"WISH-SPEC-{name}: {filename} has changed; it is no "
                        f"longer evidence")
    return pathlib.Path(where)


#: Disk 3 as the Amiga game left it after loading the Wish-written slot C,
#: saving F at once, walking one square and saving G.
_STAGE5_DISK3 = "wish-plane-2-darkness-o5uxg2bsfvztk-mfrwgzlqoqza"


@pytest.mark.parametrize("letter,minutes", [("C", 1380), ("F", 1380), ("G", 1370)])
def test_the_darkness_slot_reader_reads_saint_eric_s_heal_node_off_the_game_s_disk(
        letter, minutes):
    """Node 140 as Wish wrote it (C), as the game saved it on load (F), and
    ten minutes lower after the walk (G); `--expect` accepts that value and
    refutes the one a minute count off."""
    from tools.amiga import route_darkness
    from tools.amiga.route import check_expect
    folder = _pod_specimen(_STAGE5_DISK3, tree="pod-amiga")
    disk = AmigaDisk((folder / "fetched-disk3.adf").read_bytes())
    reading = route_darkness.DARKNESS.read_slot(disk, letter)
    assert "decode_error" not in reading
    assert [140, minutes, 0, 0] in reading["effects"]["saint eric"]
    assert check_expect(reading, ("saint eric", 140, minutes, 0))[0]
    other = 1370 if minutes == 1380 else 1380
    assert not check_expect(reading, ("saint eric", 140, other, 0))[0]


def _registered_dos_slots():
    found = []
    for name in _DOS_SLOT_SPECIMENS:
        folder = _pod_specimen(name)
        for path in sorted(folder.glob("SAVGAM?.PTY")):
            found.append((f"{name}:{path.stem[-1]}", folder, path.stem[-1]))
    return found


def _dos_vault(folder, letter) -> dos_codec.PodVault:
    path = folder / f"VAULT{letter}.DAT"
    if not path.is_file():
        return dos_codec.EMPTY_POD_VAULT
    return dos_codec.pod_vault_from_dos(path.read_bytes())


def test_every_registered_dos_slot_is_written_onto_disk_three_with_nothing_lost():
    """8 of 8 slots across 6 specimens, the DOS game's own saves except slot A
    of `pod-678-amiga-converted-walked-dos`, which Wish wrote."""
    disk = _registered_disk_three()
    slots = _registered_dos_slots()
    assert len(slots) == 8
    for label, folder, letter in slots:
        raw = (folder / f"SAVGAM{letter}.PTY").read_bytes()
        state = world_state.pod_from_dos(raw)
        party = dos_codec.read_party(folder, letter)
        characters = [dos_codec.to_neutral(c) for c in party]
        state = dataclasses.replace(state, count=len(characters))
        vault = _dos_vault(folder, letter)
        built, report = amiga_savegame.pod_new_savegame(state, characters)
        assert (report.dropped, report.losses, report.warnings) == ([], [], []), label
        out = amiga_savegame.pod_slot_on_disk_three(
            disk, letter, built, amiga_savegame.pod_vault_to_amiga(vault),
            replace=True)

        # Only the two replaced files differ from the original disk.
        before, after = _files(disk), _files(out)
        replaced = {amiga_savegame.pod_slot_path(letter).lower(),
                    amiga_savegame.pod_vault_path(letter).lower()}
        assert {p for p in set(before) | set(after)
                if before.get(p) != after.get(p)} <= replaced, label

        # An Amiga reader reads back what was written.
        back = amiga_savegame.pod_read_slot(out, letter)
        assert amiga_savegame.pod_from_amiga(back) == dataclasses.replace(
            state, source=""), label
        # A name's spaces cross unchanged: DOS's "saint eric  " arrives
        # as "saint eric  ".
        assert [amiga_pod.pod_to_neutral(b).get("name")
                for b in amiga_savegame.pod_parse(back).blocks] == [
            c.get("name") for c in characters], label
        assert amiga_savegame.pod_read_vault(out, letter) == vault, label


def _every_disk_three():
    """Every Pools of Darkness disk 3 image on this machine, as `(label,
    disk)`: those with the drawers `pod_slot_on_disk_three` insists on."""
    from tools.amiga import amigasaves
    found = []
    for label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
            for path, want_dir in amiga_savegame.POD_DISK_THREE_MARKERS:
                if disk.lookup(path).is_dir != want_dir:
                    raise AmigaDiskError(path)
        except (AmigaDiskError, ValueError):
            continue
        found.append((label, disk))
    if not found:
        pytest.skip("needs a Pools of Darkness disk 3; set $AMIGA_DISKS")
    return found


def _two_hundred_item_vault() -> bytes:
    item = bytearray(dos_codec.ITEM_SIZE)
    return amiga_savegame.pod_vault_to_amiga(
        dos_codec.PodVault(1, 2, 3, (bytes(item),) * amiga_savegame.POD_VAULT_NODES))


def test_the_largest_slot_fits_every_disk_three_for_every_letter():
    """A full party and a 200-item vault, replacing a letter the disk holds
    or adding one it lacks, on every disk 3 image here -- the free space
    left over is what `free_count` says after each."""
    built = _synthetic_amiga_pod_save(8)
    vault = _two_hundred_item_vault()
    for label, disk in _every_disk_three():
        for letter in "ADHIJ":
            out = amiga_savegame.pod_slot_on_disk_three(
                disk, letter, built, vault, replace=True)
            assert out.free_count() >= 0, (label, letter)
            assert amiga_savegame.pod_read_vault(out, letter) == \
                amiga_savegame.pod_vault_from_amiga(vault), (label, letter)


def test_a_party_of_one_and_an_empty_vault_write_on_a_synthetic_disk_three():
    out = amiga_savegame.pod_slot_on_disk_three(
        _synthetic_disk_three(), "B", _synthetic_amiga_pod_save(1), _a_vault())
    assert amiga_savegame.pod_read_vault(out, "B") == dos_codec.EMPTY_POD_VAULT


# ---------------------------------------------------------------------------
# `editor.convert.PodDosToAmiga`, not registered anywhere a player reaches
# ---------------------------------------------------------------------------

def _dos_source(folder, letter):
    import pathlib
    return convert.Source(port="dos", title=dos_port.POOLS_OF_DARKNESS,
                          path=pathlib.Path(folder), slot=letter)


def _amiga_source(disk_bytes, letter):
    import pathlib
    return convert.Source(port="amiga", title=dos_port.POOLS_OF_DARKNESS,
                          path=pathlib.Path("."), slot=letter,
                          image=disk_bytes)


def test_pod_dos_to_amiga_is_registered_only_with_the_flag_set(monkeypatch):
    assert convert.PodDosToAmiga in {type(d) for d in convert.POD_DIRECTIONS}
    assert convert.PodDosToAmiga not in {type(d) for d in convert.DIRECTIONS}
    dos = convert.Source(port="dos", title=dos_port.POOLS_OF_DARKNESS,
                         path=__import__("pathlib").Path("."))
    monkeypatch.delenv(convert.POD_CONVERT_ENV, raising=False)
    assert convert.destinations_for(dos) == []
    monkeypatch.setenv(convert.POD_CONVERT_ENV, "1")
    assert [type(d) for d in convert.destinations_for(dos)] == [
        convert.PodDosToAmiga]


def test_pod_dos_to_amiga_returns_the_image_and_writes_it(tmp_path):
    folder = _pod_specimen("dos-pod-foundation-walked")
    held = next(p.stem[-1] for p in sorted(folder.glob("SAVGAM?.PTY")))
    direction = convert.PodDosToAmiga()
    rehearsal = direction.rehearse(
        _dos_source(folder, held), held, None,
        disk_three=_synthetic_disk_three(held), replace=True)
    assert rehearsal.files == {convert.POOLSAVE_FILENAME: rehearsal.disk}
    [written] = direction.write(rehearsal, tmp_path / "out")
    assert written.read_bytes() == rehearsal.disk


def test_a_letter_the_disk_already_holds_is_not_replaced_unasked():
    disk = _synthetic_disk_three("A")
    before = disk.to_bytes()
    with pytest.raises(amiga_savegame.AmigaSlotTaken):
        amiga_savegame.pod_slot_on_disk_three(
            disk, "A", _synthetic_amiga_pod_save(1), _a_vault())
    # Either file alone is enough to count as taken.
    only_vault = _synthetic_disk_three("A")
    only_vault.remove_file(amiga_savegame.pod_slot_path("A"))
    with pytest.raises(amiga_savegame.AmigaSlotTaken):
        amiga_savegame.pod_slot_on_disk_three(
            only_vault, "A", _synthetic_amiga_pod_save(1), _a_vault())
    out = amiga_savegame.pod_slot_on_disk_three(
        disk, "A", _synthetic_amiga_pod_save(1), _a_vault(), replace=True)
    assert out.read_file(amiga_savegame.pod_vault_path("A")) == _a_vault()
    assert disk.to_bytes() == before


def test_pod_dos_to_amiga_blocks_an_unasked_replacement():
    folder = _pod_specimen("dos-pod-foundation-walked")
    held = next(p.stem[-1] for p in sorted(folder.glob("SAVGAM?.PTY")))
    with pytest.raises(convert.ConvertError):
        convert.PodDosToAmiga().rehearse(
            _dos_source(folder, held), held, None,
            disk_three=_synthetic_disk_three(held))


def test_pod_dos_to_amiga_blocks_a_slot_other_than_the_sources():
    with pytest.raises(convert.ConvertError):
        convert.PodDosToAmiga().rehearse(
            _dos_source(".", "A"), "B", None,
            disk_three=_synthetic_disk_three("A"), replace=True)


def test_pod_dos_to_amiga_turns_an_oversized_vault_into_a_convert_error(tmp_path):
    folder = _pod_specimen("dos-pod-foundation-walked")
    held = next(p.stem[-1] for p in sorted(folder.glob("SAVGAM?.PTY")))
    for path in folder.iterdir():
        if path.is_file():
            (tmp_path / path.name).write_bytes(path.read_bytes())
    item = bytes(dos_codec.ITEM_SIZE)
    big = dos_codec.PodVault(
        0, 0, 0, (item,) * (amiga_savegame.POD_POOL_NODES + 1))
    (tmp_path / f"VAULT{held}.DAT").write_bytes(
        dos_codec.pod_vault_to_dos(big))
    with pytest.raises(convert.ConvertError):
        convert.PodDosToAmiga().rehearse(
            _dos_source(tmp_path, held), held, None,
            disk_three=_synthetic_disk_three("A"),
            replace=True)


def test_pod_dos_to_amiga_needs_the_players_disk_three():
    with pytest.raises(convert.ConvertError):
        convert.PodDosToAmiga().rehearse(
            _dos_source(".", "A"), "A", None)


def test_pod_dos_to_amiga_has_no_pack_to_leave_anything_of():
    with pytest.raises(saveplan.SaveAsError):
        convert.PodDosToAmiga().rehearse(
            _dos_source(".", "A"), "A", None, leave={0: [1]})


def test_dos_to_amiga_to_dos_is_the_source_outside_the_declared_mask(tmp_path):
    """Every registered DOS slot (8 of 8, 7 written by the DOS game) goes
    through `PodDosToAmiga` onto the registered disk 3 and back through
    `PodAmigaToDos`.  The saved game equals the source outside the
    container's `PARTY_TABLE_SCRATCH` notes and the entries past the party,
    the vault is identical, and every character reads back as the same
    neutral record, name included.

    The 510-byte records are compared at 0x1F1-0x1FD, the cached combat
    tail, and not byte for byte: the item and effect files differ in the heap
    pointers and rendered-line caches, and are filed rather than hidden.
    """
    disk = _registered_disk_three()
    for label, folder, letter in _registered_dos_slots():
        rehearsal = convert.PodDosToAmiga().rehearse(
            _dos_source(folder, letter), letter, None, disk_three=disk,
            replace=True)
        assert (rehearsal.report.dropped, rehearsal.report.losses,
                rehearsal.report.warnings) == ([], [], []), label
        # The Amiga file holds the source's own cached values, so the round
        # trip does not have to rebuild them.  The source's values are
        # nonzero, so a change in either side shows here.
        amiga_party = [
            amiga_pod.pod_to_neutral(b) for b in amiga_savegame.pod_parse(
                amiga_savegame.pod_read_slot(
                    AmigaDisk(rehearsal.disk), letter)).blocks]
        src = [dos_codec.to_neutral(c)
               for c in dos_codec.read_party(folder, letter)]
        for a, b in zip(src, amiga_party):
            for key in ("armour_class", "thac0_current", "movement_current"):
                assert a.get(key) != 0, (label, a.get("name"), key)
                assert b.get(key) == a.get(key), (label, a.get("name"), key)
        back = convert.PodAmigaToDos().rehearse(
            _amiga_source(rehearsal.disk, letter), letter, None)

        original = (folder / f"SAVGAM{letter}.PTY").read_bytes()
        got = back.files[f"SAVGAM{letter}.PTY"]
        state = world_state.pod_from_dos(original)
        _, built = dos_codec.pod_savgam(state, letter, state.count)
        mask = {i for i, why in built.sources.items()
                if why == dos_codec.PARTY_TABLE_SCRATCH}
        for n in range(state.count, dos_savegame.PARTY_ENTRIES):
            at = POD.party_table + n * dos_savegame.PARTY_ENTRY
            mask.update(range(at, at + dos_savegame.PARTY_ENTRY))
        assert [i for i in range(len(original))
                if original[i] != got[i] and i not in mask] == [], label

        vault = _dos_vault(folder, letter)
        assert dos_codec.pod_vault_from_dos(
            back.files[f"VAULT{letter}.DAT"]) == vault, label

        source_chars = dos_codec.read_party(folder, letter)
        source_party = [dos_codec.to_neutral(c) for c in source_chars]
        tmp = tmp_path / label.replace(":", "-")
        tmp.mkdir()
        for name, data in back.files.items():
            (tmp / name).write_bytes(data)
        round_chars = dos_codec.read_party(tmp, letter)
        round_party = [dos_codec.to_neutral(c) for c in round_chars]
        assert len(round_party) == len(source_party), label
        # DOS rebuilds the spell-slot arrays on every character load (the
        # recompute at GAME.OVR 0x3836D), so they carry no player state here.
        # A slot A written by Wish's own Save As holds the Amiga's all-zero
        # thief saves, which DOS rebuilds on load and so never shows; the
        # Amiga file now holds the DOS value, and the round trip returns it.
        skipped = {"spells_castable"}
        if any(n in label for n in ("pod-678-amiga-converted-walked-dos:A",
                                    "wish2-l2r8-saveas-dos-strength-edit-"
                                    "vault40-game-save-d:A")):
            skipped |= {"save_paralysis", "save_petrification",
                                    "save_wands", "save_breath", "save_spell"}
        for a, b in zip(source_party, round_party):
            assert ({k: v.value for k, v in a.fields.items()
                     if k not in skipped}
                    == {k: v.value for k, v in b.fields.items()
                        if k not in skipped}
                    ), (label, a.get("name"))
        for a, b in zip(source_chars, round_chars):
            assert a._data[0x1F1:0x1FE] == b._data[0x1F1:0x1FE], label

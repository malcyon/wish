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


def test_new_pod_save_from_writes_every_played_amiga_slot(tmp_path):
    seen = 0
    for name, blob in _pod_amiga_slots():
        seen += 1
        state = amiga_savegame.pod_from_amiga(blob, source=name)
        characters = [amiga_pod.pod_to_neutral(block)
                     for block in amiga_savegame.pod_parse(blob).blocks]
        out = tmp_path / f"slot{seen}"
        report = dos_codec.new_pod_save_from(state, characters, out, "A")

        raw = (out / "SAVGAMA.PTY").read_bytes()
        assert (dataclasses.replace(world_state.pod_from_dos(raw), source="")
               == dataclasses.replace(state, source="")), name
        assert (out / "VAULTA.DAT").read_bytes() == bytes(12), name
        assert sorted(p.name for p in out.glob("CHRDATA*.SAV")) == [
            f"CHRDATA{n}.SAV" for n in range(1, len(characters) + 1)], name

        party = dos_codec.read_party(out, "A")
        assert [c.name for c in party] == [
            c.get("name") for c in characters], name

        assert report.dropped == [], name
        assert report.losses == [], name
    assert seen >= 8


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
        dos_codec.new_pod_save_from(state, characters, out, "A")
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

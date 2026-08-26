"""Curse of the Azure Bonds reads with Pool of Radiance's decoders.

`docs/116-second-game.md` establishes that the two C64 games share the 580-byte
character record, the roster block, the map format and the item tables, and
that the save geometry is Pool of Radiance's constants plus `$200`.

This module is what stops that quietly ceasing to be true. Every invariant here
is checked over **both** games through the same code path, so a change made to
suit one and breaking the other fails on the other's side rather than shipping.
The Curse half skips when the disks are absent, like every other test that
needs game data.
"""

from __future__ import annotations

import pytest

from goldbox import geo, items, savegame
from goldbox.d64 import split_load_address
from goldbox.layout import RECORD_SIZE
from goldbox.record import CharacterRecord
from tests.gamedata import (
    FIXTURES,
    curse_disks,
    curse_file,
    disk_dir,
    game_file,
    needs_curse_disks,
)

# Curse's save image sits exactly one 512-byte page pair above Pool of
# Radiance's. Every header address follows from this one number.
CURSE_SHIFT = 0x200
CURSE_SAVE_LOAD = savegame.SAVE0_LOAD_ADDRESS + CURSE_SHIFT      # $4B00
CURSE_SAVE_SIZE = 7424
CURSE_SLOT_BASE = CURSE_SAVE_LOAD + savegame.HEADER_SIZE         # $4F00
CURSE_ROSTER_BASE = 0x6700
CURSE_NAME_TABLE = 0x5700
CURSE_NAME_STRIDE = 0x10

#: Where a character record keeps its eight per-class levels, and the bitmask
#: that says which of them are in use. Both games; Curse fills 6 and 7.
CLASS_LEVELS = 0x0C9
CLASS_LEVEL_COUNT = 8
CLASS_BITS = 0x0EB
PALADIN, RANGER = 6, 7

#: The roster block is record bytes `0x100`-`0x11F` in both games.
ROSTER_IN_RECORD = 0x100


# --- helpers ----------------------------------------------------------------


def _curse_save() -> bytes:
    """SSI's own pre-generated Curse party, as a raw memory image."""
    load, payload = split_load_address(curse_file("SAVEAZURE"))
    assert load == CURSE_SAVE_LOAD, f"expected ${CURSE_SAVE_LOAD:04X}"
    return payload


def _slots(payload: bytes, base: int, load: int, count: int = 8):
    """The occupied `$100` slots of a save image, as (index, bytes)."""
    out = []
    for i in range(count):
        off = base - load + i * savegame.SLOT_STRIDE
        slot = payload[off:off + savegame.SLOT_STRIDE]
        if len(slot) == savegame.SLOT_STRIDE and any(slot):
            out.append((i, slot))
    return out


def _record(slot: bytes) -> CharacterRecord:
    """A slot is the first 256 bytes of the record; pad and decode."""
    return CharacterRecord(bytes(slot) + bytes(RECORD_SIZE - len(slot)))


def _class_invariant(slot: bytes) -> None:
    """`class_bits` is exactly one bit per non-zero slot of the level array.

    This is the assertion that fails if the eight-byte array at `0x0C9` is ever
    narrowed back to four, or if the bitmask is re-read as anything other than
    one bit per array slot.
    """
    levels = slot[CLASS_LEVELS:CLASS_LEVELS + CLASS_LEVEL_COUNT]
    expected = sum(1 << i for i, lv in enumerate(levels) if lv)
    assert slot[CLASS_BITS] == expected, (
        f"class_bits {slot[CLASS_BITS]:#04x} does not match the level array "
        f"{list(levels)}"
    )


def _sane_record(rec: CharacterRecord) -> None:
    """Things true of any Gold Box C64 character in either game."""
    assert 1 <= rec.race <= 7
    assert 0 < rec.hp_max <= 999
    assert 0 < rec.level <= 40
    assert rec.hp_rolled <= rec.hp_max
    for save in (rec.save_paralysis, rec.save_petrification, rec.save_wands,
                 rec.save_breath, rec.save_spell):
        assert 1 <= save <= 20, f"saving throw {save} out of range"
    assert 1 <= rec.movement <= 24


def _por_slots():
    """Pool of Radiance's own saved party, from the player's fixtures."""
    payload = (FIXTURES / "party6_savedgame0.bin").read_bytes()[2:]
    return payload, _slots(payload, savegame.SLOT_AREA_BASE,
                           savegame.SAVE0_LOAD_ADDRESS)


# --- the record -------------------------------------------------------------


def test_pool_of_radiance_records_satisfy_the_shared_invariants():
    """The control. If this fails the invariants are wrong, not Curse."""
    _, slots = _por_slots()
    assert slots, "the six-character fixture should have occupied slots"
    for _, slot in slots:
        _class_invariant(slot)
        _sane_record(_record(slot))


@needs_curse_disks
def test_curse_records_decode_at_pool_of_radiance_offsets():
    payload = _curse_save()
    assert len(payload) == CURSE_SAVE_SIZE
    slots = _slots(payload, CURSE_SLOT_BASE, CURSE_SAVE_LOAD)
    assert len(slots) == 6, "SSI ships six pre-generated characters"
    for _, slot in slots:
        _class_invariant(slot)
        _sane_record(_record(slot))


@needs_curse_disks
def test_curse_uses_the_upper_half_of_the_class_level_array():
    """Paladin and ranger are array slots 6 and 7, and no offset moves."""
    slots = _slots(_curse_save(), CURSE_SLOT_BASE, CURSE_SAVE_LOAD)
    used = set()
    for _, slot in slots:
        for i, lv in enumerate(slot[CLASS_LEVELS:CLASS_LEVELS + CLASS_LEVEL_COUNT]):
            if lv:
                used.add(i)
    assert PALADIN in used and RANGER in used

    _, por = _por_slots()
    por_used = {i
                for _, slot in por
                for i, lv in enumerate(slot[CLASS_LEVELS:CLASS_LEVELS + CLASS_LEVEL_COUNT])
                if lv}
    assert not (por_used & {4, 5, PALADIN, RANGER}), (
        "Pool of Radiance should never fill the upper half of the array")


@needs_curse_disks
def test_curse_records_round_trip_through_por_record():
    for _, slot in _slots(_curse_save(), CURSE_SLOT_BASE, CURSE_SAVE_LOAD):
        raw = bytes(slot) + bytes(RECORD_SIZE - len(slot))
        assert CharacterRecord(raw).to_bytes() == raw


@needs_curse_disks
def test_curse_second_ability_array_mirrors_the_first():
    """`0x065`-`0x06B` repeats the seven scores at `0x014`-`0x01A`.

    A field Curse fills and Pool of Radiance leaves at zero -- and it sits
    inside a region `goldbox/layout.py` marks UNKNOWN, so it displaces nothing.
    """
    for _, slot in _slots(_curse_save(), CURSE_SLOT_BASE, CURSE_SAVE_LOAD):
        assert slot[0x065:0x06C] == slot[0x014:0x01B]

    _, por = _por_slots()
    for _, slot in por:
        assert slot[0x065:0x06C] == bytes(7)


# --- the save game ----------------------------------------------------------


@needs_curse_disks
def test_curse_save_geometry_is_pool_of_radiance_shifted():
    payload = _curse_save()
    # The header is the same $400, so the slots start at the same offset in.
    assert CURSE_SLOT_BASE - CURSE_SAVE_LOAD == savegame.HEADER_SIZE
    # Combat icons sit $120 below the slots in both games.
    icons = CURSE_SLOT_BASE - 0x120
    assert icons - CURSE_SAVE_LOAD == (savegame.ICON_TABLE_BASE
                                       - savegame.SAVE0_LOAD_ADDRESS)
    assert any(payload[icons - CURSE_SAVE_LOAD:
                       icons - CURSE_SAVE_LOAD
                       + savegame.SLOT_COUNT * savegame.ICON_SIZE])
    # The image ends one page past the roster, which is the last thing in it.
    assert CURSE_SAVE_LOAD + len(payload) == CURSE_ROSTER_BASE + 0x100


@needs_curse_disks
def test_curse_roster_block_is_record_bytes_0x100_to_0x11f():
    """The relationship `docs/30-savegame-layout.md` predicts, in Curse."""
    payload = _curse_save()
    slots = _slots(payload, CURSE_SLOT_BASE, CURSE_SAVE_LOAD)
    for index, slot in slots:
        off = CURSE_ROSTER_BASE - CURSE_SAVE_LOAD + index * savegame.ROSTER_STRIDE
        block = payload[off:off + savegame.ROSTER_STRIDE]
        assert len(block) == savegame.ROSTER_STRIDE
        assert ROSTER_IN_RECORD + savegame.ROSTER_STRIDE <= RECORD_SIZE
        assert block[savegame.ROSTER_SLOT_INDEX] == index
        # HP and movement are the roster's copies of record fields.
        rec = _record(slot)
        assert block[savegame.ROSTER_HP_CURRENT] == rec.hp_max
        assert block[savegame.ROSTER_MOVEMENT] == rec.movement


@needs_curse_disks
def test_curse_carries_a_name_table_pool_of_radiance_has_not():
    """`$5700` holds 16 bytes of name per character, in slot order."""
    payload = _curse_save()
    base = CURSE_NAME_TABLE - CURSE_SAVE_LOAD
    slots = _slots(payload, CURSE_SLOT_BASE, CURSE_SAVE_LOAD)
    for index, slot in slots:
        entry = payload[base + index * CURSE_NAME_STRIDE:
                        base + (index + 1) * CURSE_NAME_STRIDE]
        assert entry.split(b"\0")[0] == slot[:CURSE_NAME_STRIDE].split(b"\0")[0]


# --- the maps ---------------------------------------------------------------


def _reciprocity(payload: bytes) -> float:
    """The fraction of wall edges that agree read from both squares.

    A wrong plane assignment collapses this, so it is the cheapest proof that
    the decoder is reading the right game.
    """
    g = geo.Geo(payload)
    ok = total = 0
    for y in range(geo.GRID):
        for x in range(geo.GRID):
            for direction in geo.DIRECTIONS:
                dx, dy = geo.STEP[direction]
                nx, ny = x + dx, y + dy
                if not (0 <= nx < geo.GRID and 0 <= ny < geo.GRID):
                    continue
                total += 1
                ok += g.barrier(x, y, direction) == g.barrier(
                    nx, ny, geo.OPPOSITE[direction])
    return ok / total


@needs_curse_disks
def test_curse_maps_decode_with_the_unmodified_decoder():
    seen = 0
    for disk in curse_disks():
        for entry in disk.directory():
            if not entry.name.startswith(b"GEO"):
                continue
            load, payload = split_load_address(disk.read_file(entry))
            assert len(payload) == geo.GEO_SIZE
            score = _reciprocity(payload)
            assert score > 0.92, f"{entry.name!r} reciprocity {score:.3f}"
            seen += 1
    assert seen >= 16, f"expected at least 16 Curse maps, found {seen}"


@pytest.mark.skipif(disk_dir() is None, reason="needs the game disks")
def test_pool_of_radiance_maps_clear_the_same_bar():
    """The control for the reciprocity threshold."""
    assert _reciprocity(game_file("GEO04")) > 0.92


# --- the item tables --------------------------------------------------------


def _item_types(payload: bytes):
    return [payload[i * items.ITEM_TYPE_SIZE:(i + 1) * items.ITEM_TYPE_SIZE]
            for i in range(items.ITEM_TYPE_COUNT)]


@needs_curse_disks
@pytest.mark.skipif(disk_dir() is None, reason="needs the game disks")
def test_curse_item_types_are_the_same_table_with_ranger_added():
    por = game_file("ITEMS")                       # already past the load address
    _, coab = split_load_address(curse_file("ITEMS"))
    size = items.ITEM_TYPE_COUNT * items.ITEM_TYPE_SIZE
    assert len(por) == len(coab) == size

    ranger_bit, paladin_bit = 0x80, 0x40
    paladin_records = added = 0
    for a, b in zip(_item_types(por), _item_types(coab)):
        pa, cb = a[items.TYPE_CLASS_USAGE], b[items.TYPE_CLASS_USAGE]
        if pa & paladin_bit:
            paladin_records += 1
            if cb & ranger_bit:
                added += 1
    assert paladin_records > 50, "Pool of Radiance already reserves bit 6"
    assert added > 0.9 * paladin_records, (
        f"Curse set the ranger bit on only {added} of {paladin_records} "
        "records where Pool of Radiance sets the paladin bit")


@needs_curse_disks
@pytest.mark.skipif(disk_dir() is None, reason="needs the game disks")
def test_curse_item_names_need_only_a_new_base_address(monkeypatch):
    """The word table is the same structure at a different resident base."""
    por_names = items.load_item_names(str(next(disk_dir().glob("POOL1.[dD]64"))))
    monkeypatch.setattr(items, "NAMES_LOAD_ADDRESS", 0x9E00)
    disk = next(d for d in curse_disks() if b"ITEMNAMES" in d)
    coab_names = items.load_item_names(disk)

    assert len(coab_names) >= 250
    shared = set(por_names) & set(coab_names)
    identical = sum(1 for k in shared if por_names[k] == coab_names[k])
    assert identical > 200, (
        f"only {identical} of {len(shared)} shared indices carry the same word")

"""Helpers `test_amigasavegame` shares with the test files that reuse them."""
from __future__ import annotations

from goldbox import amiga_port, amiga_savegame, dos_port
from goldbox.amiga_savegame import (
    CURSE,
    SILVER_BLADES,
)


def fake_record(deltas: amiga_port.AmigaDeltas, name: str) -> bytes:
    """A record the signature scan accepts, carrying no items or effects."""
    raw = bytearray(deltas.record_size)
    raw[:len(name)] = name.encode()
    for i in range(6):
        raw[0x10 + 2 * i] = raw[0x11 + 2 * i] = 12
    return bytes(raw)


def vm_with(deltas, **words) -> bytearray:
    vm = bytearray(amiga_savegame.VM_BYTES)
    for name, value in words.items():
        at = deltas.vm_offset(int(name, 16)) - deltas.vm_at
        vm[at:at + 2] = value.to_bytes(2, "big")
    return vm


def curse_item_node() -> bytes:
    """One Curse item node a character can hold: a made-up type, quantity one."""
    raw = bytearray(amiga_port.CURSE_DELTAS.item_size)
    for field, value in (("type_index", 1), ("quantity", 1)):
        raw[amiga_port.CURSE_DELTAS.item_offset(
            dos_port.item_field_by_name(field).offset)] = value
    return bytes(raw)


def curse_record_with_item(name: str) -> bytes:
    """`fake_record`'s character holding one item, as a saved game stores it."""
    from goldbox.amiga_later import AmigaCharacter, AmigaItem

    deltas = amiga_port.CURSE_DELTAS
    return AmigaCharacter.from_bytes(
        fake_record(deltas, name), deltas,
        items=[AmigaItem.from_bytes(curse_item_node(), deltas)]).block_bytes()


def synthetic_curse(names=("ALPHA", "BETA"), item=False) -> bytes:
    out = bytearray([2])
    out += vm_with(CURSE, **{"0x5012": 2, "0x503E": len(names),
                             "0x49C9": 1, "0x49C8": 1, "0x49C7": 5})
    out += bytes(amiga_savegame.ECL_BYTES)
    out += (3).to_bytes(2, "big") + (14).to_bytes(2, "big") + bytes([2, 0, 0, 0])
    out += bytes([4, 2])
    for block, slot in ((1, 1), (2, 2), (3, 3)):
        out += block.to_bytes(2, "big") + slot.to_bytes(2, "big")
    out += len(names).to_bytes(2, "big")
    for n in names:
        out += (curse_record_with_item(n) if item
                else fake_record(amiga_port.CURSE_DELTAS, n))
    return bytes(out)


def synthetic_silver_blades(names=("GAMMA",)) -> bytes:
    out = bytearray([1])
    out += vm_with(SILVER_BLADES, **{"0x5012": 1, "0x503E": len(names)})
    out += bytes([7, 13, 0, 0, 0, 0])
    out += bytes([4, 0])
    out += bytes.fromhex("00000001ffffffffffffffff")
    out += len(names).to_bytes(2, "big")
    for n in names:
        out += fake_record(amiga_port.SILVER_BLADES_DELTAS, n)
    return bytes(out)


def synthetic_disk_one(key: str, slots=("A",)):
    """A blank OFS disk laid out like a later title's disk 1: the title's
    executable, `/SAVE/spindisk` and a slot for each letter, all made up."""
    from goldbox.amiga_adf import AmigaDisk

    container = amiga_savegame.container_for(key)
    disk = AmigaDisk.blank("Disk1")
    disk.write_file(amiga_savegame.DISK_ONE_EXECUTABLE[container.key],
                    b"made-up executable")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(f"/{amiga_savegame.SAVE_DRAWER}/spindisk",
                    b"made-up spindisk" * 40)
    make = (synthetic_curse if container is CURSE else synthetic_silver_blades)
    for letter in slots:
        disk.write_file(amiga_savegame.slot_path(container, letter),
                        make(("BUNDLED",)))
    return disk

"""Add an effect node to a character in a running Amiga game, as the game's own constructor does.

Silver Blades and Pools of Darkness keep every effect node in one fixed-size
pool: a descriptor in the small-data segment holds the slot count (`u16`), the
element size (`u16`, 10), the base address (`u32`) and then an allocation
bitmap, one bit a slot, bit 0 of byte 0 first. The allocator (`/Secret
0x2F30E`, `/Pools of Darkness 0x2D32A`) takes the first byte of the bitmap
that is not `0xFF`, the lowest clear bit in it, sets that bit and hands back
`base + slot * size`; the constructor (`/Secret 0x12DAC`, `/Pools of Darkness
0x12FD4`) appends that node at the tail of the character's effect list and
writes its `next` (NULL), id, duration and the two bytes at +4 and +5. Nothing
writes +1. `docs/202-the-amiga-effect-node-pad.md` has the pool and the node,
and `docs/124-amiga-port.md` §1.23 the trainer's call.

`writes` makes the same allocation from what it reads and returns the writes
in the order a running game can take them: the node's bytes first, then its
bitmap bit, then the link that puts it on the list, so until the last write
the game sees a free or a leaked slot and never a half-built node. It checks
that the descriptor reads as the game set it up and that every node already
on the list is a slot the bitmap holds, and raises `EffectError` before any
write when either does not.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import amiga, amigaparty


class EffectError(Exception):
    """The pool or the list did not read as the game keeps them, or the pool
    is full; nothing was written."""


@dataclass(frozen=True)
class Pool:
    """One title's effect-node pool: where its descriptor is and how the game
    set it up."""

    #: The descriptor's offset in the data hunk.
    descriptor: int
    #: The slot count the set-up routine is called with.
    count: int
    #: The element size the set-up routine writes.
    size: int = 10

    @property
    def bitmap_bytes(self) -> int:
        return (self.count + 7) // 8


#: Per `amiga.MACHINES` key. `/Secret`: descriptor `g7618`, set up at
#: `0x1BF94` (count `0xD4` from `0x1D6C8`); `/Pools of Darkness`: `g75A2`, set
#: up at `0x1BAEC` (count `0x190` from `0x1D89A`). CONFIRMED from the code.
POOLS: dict[str, Pool] = {
    "secret-of-the-silver-blades": Pool(0x7618, 0xD4),
    "pools-of-darkness": Pool(0x75A2, 0x190),
}


@dataclass(frozen=True)
class NewEffect:
    """The constructor's arguments after the character: id, duration and the
    bytes it stores at +4 and +5."""

    id: int
    duration: int = 0
    at4: int = 0xFF
    at5: int = 0


def _u16(raw: bytes, at: int) -> int:
    return int.from_bytes(raw[at:at + 2], "big")


def _u32(raw: bytes, at: int) -> int:
    return int.from_bytes(raw[at:at + 4], "big")


def _slot(bitmap: bytearray, count: int) -> int | None:
    """The allocator's choice: the first byte that is not `0xFF`, its lowest
    clear bit; None when that slot is past the count, where the game hands
    back NULL. The game's scan only stops at byte `count - 1`, past the
    bitmap, but any slot it finds there is past the count too, so the scan
    here stops at the bitmap's end with the same answer."""
    index = 0
    while index < len(bitmap) and bitmap[index] == 0xFF:
        index += 1
    if index == len(bitmap):
        return None
    bit = 0
    while bit < 8 and bitmap[index] & (1 << bit):
        bit += 1
    slot = index * 8 + bit
    return slot if slot < count else None


def _sext16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def read_pool(target, key: str, data_base: int | None = None
              ) -> tuple[int, int, int, bytes]:
    """The pool descriptor of the title `key` names, read from the running
    game: slot count, element size, base address and the bitmap's bytes."""
    pool = POOLS.get(key)
    if pool is None:
        raise EffectError(f"no effect pool is known for {key}")
    base_of_data = target.data_base if data_base is None else data_base
    if base_of_data is None:
        raise EffectError("the data hunk's address has not been measured")
    raw = bytes(target.read(base_of_data + pool.descriptor,
                            8 + pool.bitmap_bytes))
    return _u16(raw, 0), _u16(raw, 2), _u32(raw, 4), raw[8:]


def writes(target, key: str, record_address: int, effects,
           data_base: int | None = None) -> tuple[tuple[int, bytes], ...]:
    """The `(address, bytes)` writes, in order, that add each of `effects`
    (`NewEffect`) to the record at `record_address`, as the constructor would
    one call at a time. Reads only; `add` makes the writes."""
    effects = tuple(effects)
    if not effects:
        return ()
    row = amigaparty.ROWS.get(key)
    if row is None:
        raise EffectError(f"no effect pool is known for {key}")
    count, size, base, found = read_pool(target, key, data_base)
    pool = POOLS[key]
    at = (target.data_base if data_base is None else data_base) + pool.descriptor
    if (count, size) != (pool.count, pool.size):
        raise EffectError(f"the effect pool reads {count} slots of {size} "
                          f"bytes, not the {pool.count} of {pool.size} the "
                          f"game sets up")
    memory = getattr(target, "memory", amiga.MEMORY)
    if base & 1 or not any(lo <= base and base + count * size <= lo + span
                           for lo, span in memory):
        raise EffectError(f"the effect pool's base {base:#x} is not in the "
                          f"Amiga's memory")
    bitmap = bytearray(found)
    head = _u32(bytes(target.read(record_address + row.effects.head, 4)), 0)
    try:
        nodes = amigaparty.chain(target, head, row.effects.link,
                                 row.effects.size, "the effect list")
    except amigaparty.PartyError as exc:
        raise EffectError(str(exc)) from exc
    for node in nodes:
        offset = node.address - base
        slot = offset // size
        if (offset < 0 or offset % size or slot >= count
                or not bitmap[slot // 8] & (1 << slot % 8)):
            raise EffectError(f"effect node {node.address:#x} is not a slot "
                              f"the pool has handed out")
    link = (nodes[-1].address + row.effects.link if nodes
            else record_address + row.effects.head)
    out = []
    for effect in effects:
        slot = _slot(bitmap, count)
        if slot is None:
            raise EffectError("the effect pool is full")
        node = base + _sext16(slot * size)
        bitmap[slot // 8] |= 1 << slot % 8
        out.append((node, bytes([effect.id & 0xFF])))
        out.append((node + 2, (effect.duration & 0xFFFF).to_bytes(2, "big")
                    + bytes([effect.at4 & 0xFF, effect.at5 & 0xFF])
                    + bytes(4)))
        out.append((at + 8 + slot // 8, bytes([bitmap[slot // 8]])))
        out.append((link, node.to_bytes(4, "big")))
        link = node + row.effects.link
    return tuple(out)


def add(target, key: str, record_address: int, effects,
        data_base: int | None = None) -> tuple[tuple[int, bytes], ...]:
    """Make `writes`' writes, and return them."""
    made = writes(target, key, record_address, effects, data_base)
    for address, data in made:
        target.write(address, data)
    return made

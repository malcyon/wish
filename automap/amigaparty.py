"""Where each Amiga Gold Box title keeps its live party, and a read-only walk of it.

The Amiga engines keep the party as a singly linked list of heap records, not at
fixed addresses. A data-hunk global holds the first record's address, each
record holds the next one's at a fixed offset, and the last record's link is
NULL. Each record holds the heads of two more lists of the same kind: its
items and its running effects.

Every list offset below was read out of the title's own save routine, which
walks the list to write it, and its loader, which allocates each record, reads
the file into it and appends it to the list; then measured on a running game.
`docs/96-live-memory-automapper.md`, "The party in memory", has the routines,
the measurements and the grades.

**A live record is the saved record, byte for byte, except for its pointers.**
The save routines write each record straight out of its heap allocation, so
what differs between memory and the file is only the longwords that hold heap
addresses: the file keeps whatever addresses the party had when it was saved.
`PartyRow.pointers` lists them, and `comparable` blanks them so a record can be
compared with its file. Pools of Darkness keeps the item count in its file
where memory keeps the item-list head.

Everything here reads; nothing writes. `row_for`, `mode` and `read_party` take
a target the way `automap/amigaactions.py` calls them. A row's `confirmed` set
stays empty until a write to each field has been proven in the running game,
so no Action button is offered on the strength of this module alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldbox import amiga_pod, amiga_por, amiga_port

from . import amiga

#: The engines take eight characters (`docs/165-amiga-savegame.md`), and a
#: member's slot byte is 0-7.
MAX_MEMBERS = 8

#: During a fight the same list holds the monsters after the party, with
#: slot byte 8, so the list can be longer than a party; a walk that has not
#: reached NULL after this many records is not reading the list.
MAX_RECORDS = 64

#: A character has at most this many items or effects in any title; a chain
#: longer than this is not a chain the engine built.
MAX_NODES = 64

#: Bytes of name, NUL included, at the row's `name` offset.
NAME_SIZE = 16


class PartyError(amiga.GuestError):
    """The list did not read as a party: a stray, odd or repeated pointer."""


@dataclass(frozen=True)
class Chain:
    """A list hanging off a record: its head's record offset, then per node."""

    #: Record offset of the `u32` big-endian head pointer, NULL when empty.
    head: int
    #: Node offset of the node's own `u32` next pointer, NULL on the last.
    link: int
    #: Bytes the engine allocates per node.
    size: int


@dataclass(frozen=True)
class Spot:
    """A field: its offset in a record or node, its width, and its bits."""

    offset: int
    length: int = 1
    mask: int = 0xFF

    def value(self, raw: bytes) -> int:
        return int.from_bytes(raw[self.offset:self.offset + self.length],
                              "big") & self.mask


@dataclass(frozen=True)
class PartyRow:
    """One title's party list and fields, as offsets.

    `head`, `current` and `mode` are offsets into the data hunk that
    `amiga.AmigaTarget.locate` finds (`h32` on Pool of Radiance, the
    small-data hunk on the other three). The rest are offsets into a record
    or a node. The spots come from the title's codec (`goldbox/amiga_*.py`)
    and say where an action would write; `confirmed` says which writes have
    been proven.
    """

    title: str
    #: The first record's address, `u32`.
    head: int
    #: The highlighted member's address, `u32`; the loader sets it to `head`.
    current: int
    #: The record's own next pointer, `u32`, NULL on the last record.
    next_offset: int
    #: Bytes the save routine writes per record, and the loader reads.
    record_size: int
    #: The byte the engine numbers each member's party slot in, 0-7.
    slot: int
    items: Chain
    effects: Chain
    #: Record offsets of every longword that holds a heap address in memory.
    pointers: tuple[int, ...]
    #: The game-mode byte, and the value it holds in a fight.
    mode: int
    name: int
    hp: Spot
    hp_max: Spot
    memorised: Spot
    #: In an item node: the three hidden-name bits.
    hidden: Spot
    quickfight: Spot | None
    combat_value: int = 5
    #: Action names whose writes have been proven in the running game.
    confirmed: frozenset[str] = frozenset()
    #: Action names proven safe during a fight.
    combat_legal: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Node:
    """One item or effect node: where it is and its bytes."""

    address: int
    raw: bytes


@dataclass(frozen=True)
class AmigaMember:
    """One party member as the list holds it, decoded through its row."""

    row: PartyRow
    index: int
    address: int
    raw: bytes
    item_nodes: tuple[Node, ...] = ()
    effect_nodes: tuple[Node, ...] = ()

    @property
    def slot(self) -> int:
        return self.raw[self.row.slot]

    @property
    def in_party(self) -> bool:
        """False for a monster the engine appends to the list in a fight."""
        return self.slot < MAX_MEMBERS

    @property
    def name(self) -> str:
        text = self.raw[self.row.name:self.row.name + NAME_SIZE]
        return text.split(b"\0")[0].replace(b"\xff", b" ").decode("latin1")

    @property
    def hp(self) -> int:
        return self.row.hp.value(self.raw)

    @property
    def hp_max(self) -> int:
        return self.row.hp_max.value(self.raw)

    @property
    def quickfight(self) -> bool:
        spot = self.row.quickfight
        return spot is not None and bool(spot.value(self.raw))

    def memorised(self) -> bytes:
        spot = self.row.memorised
        return self.raw[spot.offset:spot.offset + spot.length]

    def items(self) -> tuple[tuple[int, bytes], ...]:
        return tuple((n.address, n.raw) for n in self.item_nodes)

    def effects(self) -> tuple[tuple[int, bytes], ...]:
        return tuple((n.address, n.raw) for n in self.effect_nodes)


def _longwords(start: int, count: int = 1) -> tuple[int, ...]:
    return tuple(start + 4 * i for i in range(count))


def _later(deltas: amiga_port.AmigaDeltas, quickfight: int) -> dict:
    """The field spots Curse and Silver Blades share, through their deltas."""
    def at(name: str) -> int:
        return deltas.offset(deltas.dos_field(name).offset)

    memorised = deltas.dos_field("spells_memorised")
    return dict(
        name=0, hp=Spot(at("hp_current")), hp_max=Spot(at("hp_max")),
        memorised=Spot(deltas.offset(memorised.offset), memorised.size),
        hidden=Spot(deltas.item_offset(0x035), 1, 0x07),
        quickfight=Spot(quickfight))


#: The four titles, keyed as `amiga.MACHINES` is.
ROWS: dict[str, PartyRow] = {
    # `/program`: save 0x27750 walks `h32+0xAEE` through record +0x106;
    # character writer 0x2646C writes 0x120 bytes, items (0x41) from +0xCA
    # and effects (10) from +0x80; reader 0x267CE clears +0x106, +0xCA, +0x80
    # and +0x10A; append 0x26EAE sets `h32+0xAEA`.
    "pool-of-radiance": PartyRow(
        title="Pool of Radiance", head=0xAEE, current=0xAEA,
        next_offset=0x106, record_size=0x120, slot=0xC1,
        items=Chain(head=0xCA, link=0x2A, size=0x41),
        effects=Chain(head=0x80, link=0x06, size=0x0A),
        pointers=(0x080, 0x0CA, 0x106, 0x10A), mode=0xBA,
        name=0, hp=Spot(amiga_por.amiga_por_offset(0x11B)),
        hp_max=Spot(amiga_por.amiga_por_offset(0x032)),
        memorised=Spot(amiga_por.amiga_por_offset(0x017), 21),
        hidden=Spot(amiga_por.amiga_por_item_offset(0x035), 1, 0x07),
        quickfight=Spot(amiga_por.AMIGA_POR_QUICKFIGHT)),
    # `/Curse`: save 0x26AF8 walks `g3cf8` through +0x18E; writer 0x260C4
    # writes 0x1AC, items (0x42) from +0x152, effects (10) from +0xF2;
    # reader 0x25056 clears +0x18E and +0x192; 0x1A45C rebuilds the
    # thirteen readied-item pointers at +0x156.
    "curse-of-the-azure-bonds": PartyRow(
        title="Curse of the Azure Bonds", head=0x3CF8, current=0x3CFC,
        next_offset=0x18E, record_size=0x1AC, slot=0x147,
        items=Chain(head=0x152, link=0x2A, size=0x42),
        effects=Chain(head=0xF2, link=0x06, size=0x0A),
        pointers=(0x0F2, *_longwords(0x152, 14), 0x18E, 0x192),
        mode=0x3D56, **_later(amiga_port.CURSE_DELTAS, 0x19D)),
    # `/Secret`: save 0x27C10 walks `g5168` through +0x13A; writer 0x2713C
    # writes 0x154, items (0x46) from +0xFE, effects (10) from +0x96;
    # reader 0x268C0 clears +0x13A and +0x13E.
    "secret-of-the-silver-blades": PartyRow(
        title="Secret of the Silver Blades", head=0x5168, current=0x516C,
        next_offset=0x13A, record_size=0x154, slot=0xF1,
        items=Chain(head=0xFE, link=0x2A, size=0x46),
        effects=Chain(head=0x96, link=0x06, size=0x0A),
        pointers=(0x096, *_longwords(0xFE, 14), 0x13A, 0x13E),
        mode=0x525C, **_later(amiga_port.SILVER_BLADES_DELTAS, 0x146)),
    # `/Pools of Darkness`: save 0x270E0 walks `g57a4` through +0x00, at most
    # eight; writer 0x26338 writes 0x194 with the item count put in +0x08 for
    # the write, effects (10) from +0x04 and twenty bytes of each item node
    # from +0x2E; append 0x27394 sets `g57a8`. +0x0C-+0x3F are thirteen
    # readied-item pointers; +0x44-+0x5F read the same in memory and file.
    "pools-of-darkness": PartyRow(
        title="Pools of Darkness", head=0x57A4, current=0x57A8,
        next_offset=0x00, record_size=0x194, slot=0xBD,
        items=Chain(head=0x08, link=0x2A, size=0x42),
        effects=Chain(head=0x04, link=0x06, size=0x0A),
        pointers=(0x00, 0x04, 0x08, *_longwords(0x0C, 13)), mode=0x5B12,
        name=amiga_pod.NAME, hp=Spot(amiga_pod.HP_CURRENT),
        hp_max=Spot(amiga_pod.HP_MAX),
        memorised=Spot(amiga_pod.SPELLS_MEMORISED,
                       amiga_pod.SPELLS_MEMORISED_LENGTH),
        hidden=Spot(amiga_pod.ITEM_NODE_BASE + amiga_pod._item_offset(0x035),
                    1, 0x07),
        quickfight=Spot(amiga_pod.QUICKFIGHT)),
}


def _u32(raw: bytes, at: int = 0) -> int:
    return int.from_bytes(raw[at:at + 4], "big")


def _check_pointer(address: int, length: int, what: str) -> None:
    if address & 1:
        raise PartyError(f"{what} is at {address:#x}, an odd address, so it is "
                         f"not a record the engine allocated")
    if not any(base <= address and address + length <= base + size
               for base, size in amiga.MEMORY):
        raise PartyError(f"{what} is at {address:#x}, outside the Amiga's "
                         f"memory")


def chain(read, first: int, link: int, size: int, what: str,
          limit: int = MAX_NODES) -> tuple[Node, ...]:
    """Every node of one list from its first address, in list order.

    `read(addr, length)` returns bytes. Raises `PartyError` on a stray, odd or
    repeated pointer, or on a list longer than `limit`.
    """
    out: list[Node] = []
    seen: set[int] = set()
    address = first
    while address:
        if len(out) == limit:
            raise PartyError(f"{what} has not ended after {limit} nodes")
        if address in seen:
            raise PartyError(f"{what} comes back to {address:#x}")
        _check_pointer(address, size, f"{what} node {len(out) + 1}")
        seen.add(address)
        raw = bytes(read(address, size))
        out.append(Node(address, raw))
        address = _u32(raw, link)
    return tuple(out)


def walk(read, row: PartyRow, data_base: int) -> tuple[AmigaMember, ...]:
    """Every record on the list, in list order, from a running Amiga or a dump.

    That is the party, and in a fight the monsters after it (`in_party`
    False). An empty list (the head is NULL, as before a game is loaded) is
    an empty tuple. Raises `PartyError` when a list does not read as one.
    """
    head = _u32(bytes(read(data_base + row.head, 4)))
    records = chain(read, head, row.next_offset, row.record_size,
                    f"{row.title}'s party list", MAX_RECORDS)
    out = []
    for index, node in enumerate(records):
        whose = f"member {index + 1}'s"
        items = chain(read, _u32(node.raw, row.items.head), row.items.link,
                      row.items.size, f"{whose} item list")
        effects = chain(read, _u32(node.raw, row.effects.head),
                        row.effects.link, row.effects.size,
                        f"{whose} effect list")
        out.append(AmigaMember(row, index, node.address, node.raw, items,
                               effects))
    return tuple(out)


def plausible(member: AmigaMember) -> bool:
    """Whether a member reads as a character rather than as other bytes."""
    name = member.name
    return (bool(name) and all(" " <= c <= "~" for c in name)
            and member.hp <= member.hp_max)


def comparable(raw: bytes, row: PartyRow) -> bytes:
    """A record with every pointer longword zeroed, for comparing with a file."""
    out = bytearray(raw[:row.record_size])
    for at in row.pointers:
        out[at:at + 4] = bytes(len(out[at:at + 4]))
    return bytes(out)


def _unwrap(target):
    return getattr(target, "target", target)


def row_for(target) -> PartyRow | None:
    """The row for the title a target is attached to, None for any other."""
    layout = getattr(_unwrap(target), "layout", None)
    for key, machine in amiga.MACHINES.items():
        if layout is machine or (layout is not None
                                 and getattr(layout, "title", None)
                                 == machine.title):
            return ROWS.get(key)
    return None


def mode(target) -> int | None:
    """The game-mode byte, None while it cannot be read."""
    tgt = _unwrap(target)
    row = row_for(tgt)
    base = getattr(tgt, "data_base", None)
    if row is None or base is None:
        return None
    try:
        return bytes(tgt.read(base + row.mode, 1))[0]
    except amiga.NotConnected:
        return None


def read_party(target) -> tuple[AmigaMember, ...] | None:
    """The party members, or None when there is none to read or it does not decode.

    Monsters on the list in a fight are left out.

    None is ordinary at the title screen, mid-load or before `locate`: the
    list is empty or half built, and a half-built record is not a character.
    """
    tgt = _unwrap(target)
    row = row_for(tgt)
    base = getattr(tgt, "data_base", None)
    if row is None or base is None:
        return None
    try:
        records = walk(tgt.read, row, base)
    except amiga.NotConnected:
        return None
    party = tuple(m for m in records if m.in_party)
    if (not party or len(party) > MAX_MEMBERS
            or not all(plausible(m) for m in party)):
        return None
    return party

"""The companions a C64 Curse or Silver Blades party can hold, read off the
player's own `MON` files.

A companion joins through script opcode `$36` (`ADDNPC`), which copies one
480-byte `MON<id>` payload into a party slot, name included, and writes no
icon. So a C64 companion is identified by his name, and this table answers the
three things a conversion to or from the C64 needs about him:

* :meth:`Companions.match` -- which `MON` file a companion's name came from;
* :meth:`Companions.picture_for` -- the combat-picture id the DOS and Amiga
  joins write for that file, which is the bare `MON` id in both titles;
* :meth:`Companions.story_byte` -- the `0x0E5` byte his `MON` file holds,
  which `COM.PREP` reads to draw a story companion with his own `COMPIC` art;
* :meth:`Companions.join_kept` -- the other bytes his `MON` file gives a
  C64 join that no port's record converts, so that a companion converted
  into the C64 holds what the C64's own join gives him;

plus :attr:`Companions.default_icon`, the 36-byte icon `INIT` seeds every
party slot with, and so the one a companion who joins an unused slot fights
with.

**A story byte is never a picture or a monster id.** Silver Blades' story
bytes are the demo's picture swaps, and `$4D` is both SIEGLINDA's story byte
and VALA's `MON` id, so nothing here maps one to the other.

Nothing is stored: every name and byte is read from the disks at run time, as
`goldbox.iconparts.IconParts.load` and `goldbox.items.load_item_types` are.
`docs/241-a-companions-combat-figure-on-each-port.md` has the reads behind
every constant below.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass

from .d64 import D64, D64Error, split_load_address
from .iconparts import IconParts
from .layout import NAME_SIZE

CURSE_KEY = "curse-of-the-azure-bonds"
SILVER_BLADES_KEY = "secret-of-the-silver-blades"

#: The payload length of every `MON` file in both titles.
MON_SIZE = 480

#: `0x0E4`-`0x0E7` of a `MON` payload: fill, story byte, and two bytes the
#: game never reads.
REGION_OFFSET = 0x0E4
REGION_SIZE = 4
STORY_OFFSET = 0x0E5

HEX_DIGITS = b"0123456789ABCDEFabcdef"

#: The record runs `(offset, size)` a C64 join keeps from the companion's
#: `MON` file that no DOS or Amiga field converts, per title.  `ADDNPC`
#: (Curse `DUNGEON $28E2`) loads the whole `MON` file over the slot's
#: record and then writes only `0x0D1`-`0x0D2` (zero), the control byte
#: `0x0B8`, `0x10C`-`0x10D`, and what the strength and roster recomputes
#: rebuild, so every byte here is his file's own: `$FF` at `0x0B7`,
#: `level_monk`, `0x0D3`, `region_0e4` and `monster_count` in all seven
#: joinable Curse files, `$FF` at `0x088`-`0x097` in four of them, and
#: per-monster values at `0x01B`, `0x06C`-`0x06D` and `0x11C`.  The C64
#: writer has no source for any of them and writes 0 for every other
#: character.  No absolute or immediate-indexed reference in any of Curse's
#: 412 files reads `0x01B`-`0x01F`, `0x06C`-`0x070`, `0x088`-`0x097`,
#: `0x0B7`, `0x0D3`-`0x0D4`, `0x0E4` or `0x11C`; `level_monk` is one slot
#: of the class-level array, and the readers of `monster_count` take the
#: same branch for `$FF` as for 0 on a party slot (`goldbox/layout.py`).
#: Silver Blades has no row: its five joinable files hold 0 at every byte
#: the writer leaves unsourced, and `0x01B`-`0x01F` is its memorised-spell
#: list, which is converted.
JOIN_KEPT: dict[str, tuple[tuple[int, int], ...]] = {
    CURSE_KEY: ((0x01B, 5), (0x06C, 5), (0x088, 16), (0x0B7, 1), (0x0CE, 1),
                (0x0D3, 2), (0x0E4, 1), (0x0FB, 1), (0x11C, 1)),
}

#: The `MON` ids each title's `ADDNPC` statements name, from a control-flow
#: walk of every area script on the C64 sides; the DOS scripts name the same.
JOINABLE: dict[str, frozenset[int]] = {
    CURSE_KEY: frozenset({0x16, 0x17, 0x3B, 0x43, 0x55, 0x58, 0x5A}),
    SILVER_BLADES_KEY: frozenset({0x32, 0x33, 0x34, 0x4D, 0x4E}),
}


#: The combat icon `(head, body, colours)` the DOS and Amiga joins give a
#: companion: all zero in the 7 joinable Curse `MON*CHA.DAX` and `MONCHA.GLB`
#: records and in both companions of the DOS Pit join save.  Neither engine
#: draws it: a Curse member at control `$80` or above fights as his picture
#: (`GAME.OVR 0x1F3D9`).  Silver Blades' records are zero too, but where its
#: engines draw a companion has not been read, so it has no row.
JOIN_ICON: dict[str, tuple[int, int, bytes]] = {CURSE_KEY: (0, 0, bytes(6))}

#: The figure-size byte a companion's own join writes, per title and port.
#: The C64 join copies `0x099` of his `MON` file (1 in all twelve joinable
#: Curse and Silver Blades files); the DOS join copies the size of his
#: `MON*CHA.DAX` record (0 in all 81 Curse records); the Amiga join copies
#: that of his `MONCHA.GLB` record (0 in the 7 joinable Curse and the 5
#: joinable Silver Blades records).  A title absent here has
#: no measured companion value, so its companions' size is converted as a
#: player's is.
COMPANION_SIZE: dict[str, dict[str, int]] = {
    CURSE_KEY: {"C64": 1, "DOS": 0, "Amiga": 0},
    SILVER_BLADES_KEY: {"C64": 1, "DOS": 0, "Amiga": 0},
}


def companion_size(key: str, port: str) -> int | None:
    """The size byte `port`'s join gives a companion of title `key`, or None
    when none is measured."""
    return COMPANION_SIZE.get(key, {}).get(port)


#: The sheet-portrait and dual-class bytes a companion's own join writes, per
#: title and port, where they differ from what a player character holds.
#: The C64 join copies them from his `MON` file (7 of 7 joinable Curse files);
#: the DOS join from his `MON*CHA.DAX` record (7 of 7, and both companions of
#: the DOS Pit join save), and the Amiga join from his `MONCHA.GLB` record
#: (7 of 7; `/Curse` 0x26306 loads it and 0x270A6 copies these bytes
#: unchanged).  DOS and the Amiga keep no dual-class pair, only the former
#: levels, which all three joins leave zero.  Silver Blades holds zero in all
#: of them on every port, which is what a player holds, so it has no row.
COMPANION_FILL: dict[str, dict[str, dict[str, int]]] = {
    CURSE_KEY: {
        "C64": {"portrait_head": 0xFF, "portrait_body": 0x00,
                "dual_class_slot": 0xFF, "dual_class_level": 0xFF},
        "DOS": {"portrait_head": 0xFF, "portrait_body": 0x00},
        "Amiga": {"portrait_head": 0xFF, "portrait_body": 0x00},
    },
}


def companion_fill(key: str, port: str) -> dict[str, int]:
    """The bytes `port`'s join gives a companion of title `key` that a player
    character does not hold, by field name; empty when none is measured."""
    return dict(COMPANION_FILL.get(key, {}).get(port, {}))


def _name_from(raw: bytes) -> str:
    """A NUL-padded name field as text, cut at the first NUL."""
    return raw[:NAME_SIZE].split(b"\0", 1)[0].decode("latin-1").strip()


def _key(name: str | bytes) -> str:
    text = _name_from(name) if isinstance(name, (bytes, bytearray)) else name
    return text.strip().upper()


def _open(disk: D64 | str | os.PathLike) -> D64:
    if isinstance(disk, D64):
        return disk
    try:
        return D64.open(disk)
    except (OSError, D64Error) as exc:
        raise ValueError(f"{os.fspath(disk)} is not a readable disk image") from exc


def _mon_id(entry_name: bytes) -> int | None:
    name = entry_name.rstrip(b"\xa0 ")
    if len(name) != 5 or not name.startswith(b"MON"):
        return None
    digits = name[3:]
    if not all(c in HEX_DIGITS for c in digits):
        return None
    return int(digits.decode("ascii"), 16)


@dataclass(frozen=True)
class Monster:
    """One `MON` file: its id, its name, its `0x0E4`-`0x0E7` bytes, and the
    whole 480-byte payload when it was read off a disk."""

    mon_id: int
    name: str
    region: bytes
    payload: bytes = b""

    @property
    def story_byte(self) -> int:
        return self.region[STORY_OFFSET - REGION_OFFSET]

    @property
    def is_story(self) -> bool:
        """Whether `COM.PREP` draws him with `COMPIC<story byte>`: it takes
        the byte only when it is neither 0 nor 128 or above."""
        return 0 < self.story_byte < 0x80


class Companions:
    """One title's `MON` files, the default icon, and the lookups."""

    def __init__(self, key: str, monsters: dict[int, Monster],
                 default_icon: bytes):
        if key not in JOINABLE:
            raise ValueError(f"{key} has no companion table")
        missing = sorted(JOINABLE[key] - set(monsters))
        if missing:
            raise ValueError(
                "these disks hold no " + ", ".join(f"MON{m:02X}" for m in missing))
        self.key = key
        self.monsters = dict(monsters)
        self.default_icon = bytes(default_icon)
        self._by_name: dict[str, list[int]] = {}
        for mon_id in sorted(self.monsters):
            self._by_name.setdefault(
                _key(self.monsters[mon_id].name), []).append(mon_id)

    @classmethod
    def load(cls, key: str,
             disks: Iterable[D64 | str | os.PathLike]) -> "Companions":
        """Read every `MON` file and the icon tables off one title's sides.

        A `MON` file found on two sides must hold the same bytes on both;
        disks that disagree are two different releases and raise, as does a
        path that is not a readable disk image.
        """
        monsters: dict[int, Monster] = {}
        payloads: dict[int, bytes] = {}
        icon: bytes | None = None
        for disk in disks:
            image = _open(disk)
            for entry in image.iter_directory():
                mon_id = _mon_id(entry.name)
                if mon_id is None or not entry.is_prg:
                    continue
                payload = split_load_address(image.read_file(entry))[1]
                if len(payload) != MON_SIZE:
                    raise ValueError(
                        f"MON{mon_id:02X} is {len(payload)} bytes, not {MON_SIZE}")
                if mon_id in payloads:
                    if payloads[mon_id] != payload:
                        raise ValueError(
                            f"MON{mon_id:02X} differs between two sides")
                    continue
                payloads[mon_id] = payload
                monsters[mon_id] = Monster(
                    mon_id, _name_from(payload),
                    payload[REGION_OFFSET:REGION_OFFSET + REGION_SIZE],
                    payload)
            if icon is None and image.find(b"SPELLE64") and image.find(b"SPELLN64"):
                icon = IconParts.load(image).default_icon()
        if icon is None:
            raise ValueError("no side here carries SPELLE64 and SPELLN64")
        return cls(key, monsters, icon)

    def match(self, name: str | bytes) -> int | None:
        """The `MON` id a companion with this name joined from, or None.

        A name only one `MON` file carries gives that file. Where two share a
        name, the one a script can add wins if exactly one of them can; no
        two joinable files share a name in either title.
        """
        ids = self._by_name.get(_key(name), [])
        if len(ids) == 1:
            return ids[0]
        joinable = [i for i in ids if i in JOINABLE[self.key]]
        return joinable[0] if len(joinable) == 1 else None

    def name_matches(self, mon_id: int, name: str | bytes) -> bool:
        """Whether `MON<mon_id>` carries this name."""
        monster = self.monsters.get(mon_id)
        return monster is not None and _key(monster.name) == _key(name)

    def picture_for(self, mon_id: int) -> int:
        """The combat-picture id the DOS and Amiga joins write for this file.

        Both write the operand itself: Curse `GAME.OVR 0x1ECE5`, Silver Blades
        `GAME.OVR 0x25EE7` and `/Secret 0x276E6`. Silver Blades' three swaps
        apply only to the demo's picture load, never to the saved byte.
        """
        if mon_id not in self.monsters:
            raise KeyError(f"no MON{mon_id:02X} on these disks")
        return mon_id

    def story_byte(self, mon_id: int) -> int:
        """`0x0E5` as `MON<mon_id>` holds it: what a join leaves there."""
        if mon_id not in self.monsters:
            raise KeyError(f"no MON{mon_id:02X} on these disks")
        return self.monsters[mon_id].story_byte

    def join_kept(self, mon_id: int) -> list[tuple[int, bytes]]:
        """`(offset, bytes)` for each :data:`JOIN_KEPT` run of this title, as
        `MON<mon_id>` holds it: what a C64 join leaves there."""
        monster = self.monsters.get(mon_id)
        if monster is None:
            raise KeyError(f"no MON{mon_id:02X} on these disks")
        runs = JOIN_KEPT.get(self.key, ())
        if runs and len(monster.payload) != MON_SIZE:
            raise ValueError(f"MON{mon_id:02X} was not read whole")
        return [(offset, monster.payload[offset:offset + size])
                for offset, size in runs]

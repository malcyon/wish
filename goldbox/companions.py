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

#: The `MON` ids each title's `ADDNPC` statements name, from a control-flow
#: walk of every area script on the C64 sides; the DOS scripts name the same.
JOINABLE: dict[str, frozenset[int]] = {
    CURSE_KEY: frozenset({0x16, 0x17, 0x3B, 0x43, 0x55, 0x58, 0x5A}),
    SILVER_BLADES_KEY: frozenset({0x32, 0x33, 0x34, 0x4D, 0x4E}),
}


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
    """One `MON` file: its id, its name and its `0x0E4`-`0x0E7` bytes."""

    mon_id: int
    name: str
    region: bytes

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
                    payload[REGION_OFFSET:REGION_OFFSET + REGION_SIZE])
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

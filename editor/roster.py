"""The party list, and the three kinds of file it can come from.

The roster mirrors what the game itself prints: **name, armour class, current
hit points**, and nothing else. That is not a design preference -- disassembling
all 64 call sites into the game's string printer, while hunting for a status
field, showed the C64 party list prints exactly those three and colours the hit
points when current is below maximum.

Armour class and current hit points come from the party roster, not from the
character record. They live nowhere else in a save.

Which title a disk belongs to is detected from its directory and kept as
`Party.game`; no filename is spelled out here any more. Pool of Radiance writes
`SAVEDGAME0` plus `SAVEDGAME1`, Curse of the Azure Bonds writes `SAVEAZURE`
alone, and `goldbox/games.py` is the only place that knows the difference.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from goldbox import games
from goldbox.d64 import D64
from goldbox.games import ICON_TABLE_OFFSET, Game
from goldbox.icons import ICON_SIZE, Icon, icon_for_slot
from goldbox.record import CharacterRecord
from goldbox.savegame import SaveGame0, SaveGame1, load_save

from .inventory import Inventory

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: when the log is on and its level swallows them when it is off -- and
#: `editor` still imports nothing from `wish`.
_log = logging.getLogger("wish.editor.roster")


@dataclass
class Member:
    """One row of the roster."""

    index: int                       # slot number, or position on a roster disk
    record: CharacterRecord
    name: str
    armour_class: int | None = None
    hp_current: int | None = None
    hp_max: int | None = None
    source: bytes | None = None      # the disk file, for a standalone character
    inventory: Inventory | None = None   # items live in SAVEDGAME0 only
    icon: Icon | None = None             # from the shared table at $4BE0
    icon_original: Icon | None = None
    record_original: bytes | None = None  # as read, for the change preview
    #: Which title this character's save came from, so the two names below are
    #: looked up in that title's tables rather than Pool of Radiance's. **None
    #: means Pool of Radiance**, which is what a `Member` built without one
    #: meant before there was a second title (#78).
    game: Game | None = None

    @property
    def is_npc(self) -> bool:
        return self.record.is_npc

    @property
    def race_name(self) -> str:
        """The race spelled out, in the open title's own list.

        Race 0 is real -- 75 monster records carry it and the Realms titles
        print MONSTER -- so it is named, not blanked. Krynn's 0 is a race in
        its own right (`silvanesti elf`), which is why the note belongs to the
        table rather than to this lookup.
        """
        from .enums import race_labels
        try:
            code = int(self.record.get("race"))
        except Exception as exc:
            # Read for every visible row on every repaint, so one line and no
            # traceback: a record whose race will not read is a blank cell, not
            # a reason to stop drawing the table.
            _log.debug("no race for %s: %s", self.name, exc)
            return ""
        return race_labels(self.game).get(code, str(code))

    @property
    def class_name(self) -> str:
        """From `class_bits` at 0x0EB, the field the game itself reads.

        `char_class` at 0x073 says the same thing a second way and the two are
        allowed to disagree; the roster shows the one the game acts on.

        The bits are per title: Curse and Silver Blades add a paladin and a
        ranger above the classic four, and Krynn a Knight of Solamnia.
        """
        from .enums import CHAR_CLASS, class_bit_names
        try:
            bits = int(self.record.get("class_bits"))
        except Exception as exc:
            _log.debug("no class_bits for %s: %s", self.name, exc)
            return ""
        if bits:
            return class_bit_names(self.game).get(bits, str(bits))
        try:
            return CHAR_CLASS.get(int(self.record.get("char_class")), "")
        except Exception as exc:
            _log.debug("no char_class for %s: %s", self.name, exc)
            return ""

    @property
    def wounded(self) -> bool:
        return (self.hp_current is not None and self.hp_max is not None
                and self.hp_current < self.hp_max)

    @property
    def hp_text(self) -> str:
        if self.hp_current is None:
            return ""
        return f"{self.hp_current} / {self.hp_max}"


class Party:
    """Everything editable in one opened file.

    Three shapes of file all arrive here and produce the same roster:

    * a **save disk** -- one title's save files, up to eight slots;
    * a **roster disk** -- no save games at all, just standalone character
      files. `PORSAVE10.D64` is one, and an editor that assumes a save game
      exists falls over on it;
    * anything else holding standalone characters.

    Detection is by what the directory holds, never by the filename of the disk
    -- and that now identifies the *title* as well as the kind of disk.
    """

    def __init__(self, path: str, game: Game | None = None, disk=None):
        """`disk` is an image already in memory, standing in for reading one.

        The one caller is the DOS import, which builds a converted disk that
        has never been written anywhere and needs the roster read off *it*
        rather than off the template still on disk under `path`. Everything
        else leaves it None and the file is opened as always.
        """
        self.path = path
        self.disk = D64.open(path) if disk is None else disk
        self.game = game or games.detect(self.disk, games.DEFAULT)
        self.is_save = games.detect(self.disk) is not None
        self.save0: SaveGame0 | None = None
        self.save1: SaveGame1 | None = None
        self.members: list[Member] = []
        if self.is_save:
            self._load_save()
        else:
            self._load_standalone()

    # -- kinds of file ----------------------------------------------------

    def _load_save(self) -> None:
        self.game, self.save0, self.save1 = load_save(self.disk, self.game)
        payload = self.save0.to_bytes()
        for slot in self.save0.characters:
            record = slot.record
            icon = icon_for_slot(payload, slot.index)
            member = Member(slot.index, record, record.name,
                            inventory=Inventory(payload, slot.index),
                            icon=icon, icon_original=icon,
                            record_original=record.to_bytes(),
                            game=self.game)
            if self.save1 is not None:
                block = self.save1.roster(slot.index)
                if block.occupied:
                    member.armour_class = block.armour_class
                    member.hp_current = block.hit_points
                    member.hp_max = record.hp_max
            self.members.append(member)

    def _load_standalone(self) -> None:
        """A roster disk: one character per PRG file, no save games.

        Armour class and hit points stay blank -- there is no roster to read
        them from, and inventing them would be worse than a gap.
        """
        for i, entry in enumerate(self.disk.directory()):
            if not entry.is_prg or entry.is_empty:
                continue
            try:
                record = CharacterRecord.from_prg(self.disk.read_file(entry))
            except Exception as exc:
                # A roster disk carries PRGs that are not characters -- the
                # loader among them -- so a file that will not parse is the
                # filter working, not a fault.
                _log.debug("%s is not a character record: %s", entry.name, exc)
                continue
            self.members.append(
                Member(i, record, record.name, source=entry.name,
                       record_original=record.to_bytes(), game=self.game))

    # -- what the window asks ---------------------------------------------

    @property
    def in_save(self) -> bool:
        """True when edits go into a 256-byte slot rather than a whole record."""
        return self.is_save

    def write_items(self) -> None:
        """Push edited item blocks back into the save payload.

        Only when something actually moved: a block nobody touched is not
        rewritten, so a no-op save stays byte-identical.
        """
        if self.save0 is None:
            return
        changed = [m for m in self.members
                   if m.inventory is not None and m.inventory.changed]
        if not changed:
            return
        payload = bytearray(self.save0.to_bytes())
        for m in changed:
            m.inventory.write_into(payload)
        self.save0 = SaveGame0.from_bytes(bytes(payload), self.game)

    def write_icons(self) -> None:
        """Push edited combat icons back into the shared icon table.

        A save keeps the icons in one table of eight, not in the character
        slots, so this is a second patch into the same payload as the items --
        and, like them, only for a character whose icon actually moved.
        """
        if self.save0 is None:
            return
        changed = [m for m in self.members
                   if m.icon is not None and m.icon != m.icon_original]
        if not changed:
            return
        payload = bytearray(self.save0.to_bytes())
        for m in changed:
            at = ICON_TABLE_OFFSET + m.index * ICON_SIZE
            payload[at:at + ICON_SIZE] = m.icon.raw
        self.save0 = SaveGame0.from_bytes(bytes(payload), self.game)

    def member(self, row: int) -> Member:
        return self.members[row]

    def __len__(self) -> int:
        return len(self.members)

    def describe(self) -> str:
        # A roster disk holds bare character files and names no title, so it is
        # not labelled with one rather than guessed at.
        if not self.is_save:
            return f"roster disk, {len(self.members)} character(s)"
        return f"{self.game.title} save disk, {len(self.members)} character(s)"

"""The character sheet's record for a Pools of Darkness character.

The sheet edits every other title through the 580-byte C64
:class:`goldbox.record.CharacterRecord`.  Pools of Darkness never shipped on
the C64, and that record cannot hold what its characters carry: 27 spell-slot
bytes for nine spell levels, thief skills up to 255, a base and an in-force
byte for each ability, 141 memorised positions and 32 bits of experience.
:class:`PodSheetRecord` is a stand-in for
`CharacterRecord` over the title's own 510-byte DOS record instead.

It answers the sheet's field names -- `level_cleric`, `hp_max`,
`thief_pick_pockets` -- out of the DOS record's own bytes.  A sheet name this
title has no byte for is in :data:`UNWRITABLE` and reads as not stored.  Any
other name that is a DOS field of this title (`class_levels`, `size`) reads
that field, so a byte with no sheet name is still reachable and is never
rewritten by an edit elsewhere.

An Amiga character is rendered as this DOS record by the writer the DOS Save
As already uses (:func:`amiga_member`); the sheet edits the rendering, and
:func:`rewrite_record` copies back only the fields that moved.
"""

from __future__ import annotations

import dataclasses
from typing import Any, NamedTuple

from goldbox import dos_codec, dos_port, rewrite
from goldbox.items import ITEM_SIZE, ITEMS_PER_CHARACTER
from goldbox.layout import FIELDS_BY_NAME, Field, Kind
from goldbox.neutral import NeutralCharacter
from goldbox.record import FieldNotStored

DELTAS = dos_port.POOLS_OF_DARKNESS
TABLE: dict[str, Field] = dos_codec.FIELDS_BY_NAME_FOR[DELTAS.key]
SIZE = DELTAS.record_size

#: The sheet's six ability names. Each is a DOS pair whose first byte is the
#: permanent score and whose second is the score in force
#: (`goldbox.dos_codec._ability_pair`, read from the engine).
ABILITIES = ("strength", "intelligence", "wisdom", "dexterity",
             "constitution", "charisma")

#: Sheet level name -> the slot of the DOS `class_levels` array it reads
#: (`goldbox.dos_codec.CLASS_LEVEL_SLOTS`). Druid has no sheet name in any
#: title; slots 1, 3 and 4 have no box and keep their bytes.
LEVEL_SLOTS = {
    name: slot for slot, _class, name in dos_codec.CLASS_LEVEL_SLOTS
    if name is not None and slot < TABLE["class_levels"].size
}

#: The three nine-byte spell-slot arrays, in record order: one byte a spell
#: level, the number of spells of that level the class may memorise.
SLOT_ARRAYS = (("cleric", "spells_castable_cleric"),
               ("druid", "spells_castable_druid"),
               ("magic-user", "spells_castable_magic_user"))

#: Sheet names whose value is one DOS field of the same width under another
#: name.
RENAMED = {
    "thac0": "thac0_current",
    "roster_movement": "movement_current",
}

#: Sheet names read straight from the DOS field of the same name, at the DOS
#: field's own width: hit points are one byte, the thief skills unsigned
#: bytes and experience four bytes.
SAME_NAME = frozenset({
    "thac0_base", "race", "char_class", "age", "hp_max",
    "save_paralysis", "save_petrification", "save_wands", "save_breath",
    "save_spell", "movement", "level", "turn_class",
    "thief_pick_pockets", "thief_open_locks", "thief_find_traps",
    "thief_move_silently", "thief_hide_in_shadows", "thief_hear_noise",
    "thief_climb_walls", "thief_read_languages",
    "platinum", "gems", "jewelry", "sex", "alignment", "armour_class_base",
    "experience", "hp_rolled", "armour_class", "hp_current",
    "paladin_cures", "roster_tail", "attack_forms", "experience_award",
})

#: The names the sheet record answers that are not plain copies of one DOS
#: field: the name, the ability pairs, the class-level slots, size, the
#: class mask and the three spell fields.
SPECIAL = frozenset({
    "name", "exceptional_strength", "size_small", "class_bits",
    "spells_memorised", "spells_known", "spells_castable",
    *ABILITIES, *LEVEL_SLOTS,
})

MAPPED = SAME_NAME | SPECIAL | frozenset(RENAMED)

#: Every field the sheet binds (`editor.binding.shown_fields`) that this
#: title's record has no byte for: the four coins below platinum, the drain
#: counters, the item-effect slots, infravision, the strength index and the
#: party order. `Party.unwritable` greys them.
UNWRITABLE = frozenset({
    "copper", "silver", "electrum", "gold",
    "levels_drained", "hp_lost_to_drain",
    "item_effects", "infravision", "strength_index", "party_order",
})

#: The Amiga greys the same names as DOS: its sheet record is the block
#: rendered as a DOS record with the class code, the turning row and the class
#: levels taken from the block itself (:func:`amiga_member`), and each of them
#: has a place in the block (`goldbox.pod_rewrite.AMIGA_PLACES`).
AMIGA_UNWRITABLE = UNWRITABLE


def unwritable(port: str) -> frozenset[str]:
    """The sheet names a party on `port` greys: :data:`AMIGA_UNWRITABLE` on
    the Amiga, :data:`UNWRITABLE` on DOS."""
    return AMIGA_UNWRITABLE if port == "amiga" else UNWRITABLE


#: The bit the DOS control byte sets for a character the engine drives: the
#: first byte of this title's four-byte `field_83_87`
#: (`goldbox.dos_codec.to_neutral`).
NPC_BIT = 0x80
_CONTROL_AT = TABLE["field_83_87"].offset

#: The number of memorised-spell positions, filled from the end.
MEMORISED_SIZE = TABLE["spells_memorised"].size
#: The number of spellbook bytes: byte *n* is spell id *n + 1*.
SPELLBOOK_SIZE = TABLE["spellbook"].size


def _decode(f: Field, raw: bytes) -> Any:
    if f.kind is Kind.U8:
        return raw[0]
    if f.kind is Kind.I8:
        return raw[0] - 256 if raw[0] > 127 else raw[0]
    if f.kind in (Kind.U16LE, Kind.UINT_LE):
        return int.from_bytes(raw, "little")
    return bytes(raw)


def _encode(f: Field, name: str, value: Any) -> bytes:
    if f.kind in (Kind.U8, Kind.U16LE, Kind.UINT_LE):
        value = int(value)
        top = (1 << (8 * f.size)) - 1
        if not 0 <= value <= top:
            raise ValueError(f"{name}: {value} does not fit in {f.size} "
                             f"byte(s), 0 to {top}")
        return value.to_bytes(f.size, "little")
    if f.kind is Kind.I8:
        value = int(value)
        if not -128 <= value <= 127:
            raise ValueError(f"{name}: {value} does not fit in a signed byte")
        return bytes([value & 0xFF])
    data = bytes(value)
    if len(data) != f.size:
        raise ValueError(f"{name}: expected exactly {f.size} raw bytes, got "
                         f"{len(data)}")
    return data


def _byte(name: str, value: Any) -> int:
    """`value` as one unsigned byte, or the error a box out of range gets."""
    value = int(value)
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name}: {value} does not fit in a byte, 0 to 255")
    return value


def _sheet_kind(name: str) -> tuple[Kind, int]:
    """The kind and width a sheet name's value has in this title."""
    if name == "name":
        return Kind.ASCII_NUL, TABLE["name_text"].size
    if name in ABILITIES or name == "exceptional_strength":
        return Kind.U8, 1
    if name in LEVEL_SLOTS or name in ("size_small", "class_bits"):
        return Kind.U8, 1
    if name == "spells_memorised":
        return Kind.RAW, MEMORISED_SIZE
    if name == "spells_known":
        return Kind.RAW, SPELLBOOK_SIZE
    if name == "spells_castable":
        return Kind.RAW, sum(TABLE[f].size for _c, f in SLOT_ARRAYS)
    f = TABLE[RENAMED.get(name, name)]
    return f.kind, f.size


class PodSheetRecord:
    """A mutable view over one 510-byte Pools of Darkness DOS record, read and
    written through the sheet's own field names.

    The bytes are held verbatim, so a record no field was set on returns
    exactly what it was built from, and a set touches only the bytes of the
    field it names.  A set that leaves the value as :meth:`get` already reads
    it writes nothing, so a store of every box on save moves no byte that was
    not edited.
    """

    __slots__ = ("_data",)

    SIZE = SIZE

    def __init__(self, data: bytes) -> None:
        if len(data) != SIZE:
            raise dos_codec.DosRecordError(
                f"a Pools of Darkness record is {SIZE} bytes, got {len(data)}")
        self._data = bytearray(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "PodSheetRecord":
        return cls(data)

    def to_bytes(self) -> bytes:
        return bytes(self._data)

    def __bytes__(self) -> bytes:
        return self.to_bytes()

    def __len__(self) -> int:
        return SIZE

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PodSheetRecord):
            return self._data == other._data
        if isinstance(other, (bytes, bytearray)):
            return bytes(self._data) == bytes(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(bytes(self._data))

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"

    # -- which names this record answers ----------------------------------

    @staticmethod
    def maps(name: str) -> bool:
        """Whether `name` reads a byte of this title's record."""
        return name in MAPPED or (name in TABLE and name not in UNWRITABLE)

    def is_stored(self, name: str) -> bool:
        return self.maps(name)

    @staticmethod
    def sheet_field(name: str) -> Field:
        """The sheet's `goldbox.layout.Field` for `name`, at this title's
        width and kind, so `editor.binding.value_range` gives the box the
        range this record can hold: 0-255 for a thief skill or hit points,
        32 bits for experience.  The offset is this record's own where the
        name reads one DOS field or byte, else the start of the first field
        it reads.
        """
        if not PodSheetRecord.maps(name):
            raise FieldNotStored(f"Pools of Darkness has no {name} field")
        kind, size = _sheet_kind(name)
        dos = {"name": "name_length", "exceptional_strength":
               "exceptional_strength", "size_small": "size",
               "spells_known": "spellbook",
               "spells_castable": "spells_castable_cleric"}
        if name in LEVEL_SLOTS:
            at = TABLE["class_levels"].offset + LEVEL_SLOTS[name]
        elif name in ABILITIES:
            at = TABLE[name].offset + 1
        else:
            at = TABLE[dos.get(name, RENAMED.get(name, name))].offset
        base = FIELDS_BY_NAME.get(name)
        if base is None:
            source = TABLE[RENAMED.get(name, name)]
            return dataclasses.replace(source, offset=at, size=size, kind=kind,
                                       name=name)
        return dataclasses.replace(base, offset=at, size=size, kind=kind)

    # -- generic field access ---------------------------------------------

    def _dos(self, name: str) -> bytes:
        f = TABLE[name]
        return bytes(self._data[f.span])

    def _put(self, name: str, data: bytes) -> None:
        f = TABLE[name]
        self._data[f.span] = data

    def get(self, name: str) -> Any:
        """The value of the sheet field `name`, decoded as the sheet reads it.

        Raises `goldbox.record.FieldNotStored` for a name this title has no
        byte for, which is the same answer a C64 save slot gives for a byte
        past its 256.
        """
        if not self.maps(name):
            raise FieldNotStored(f"Pools of Darkness has no {name} field")
        if name == "name":
            return self.name
        if name in ABILITIES:
            return self._dos(name)[1]
        if name == "exceptional_strength":
            return self._dos(name)[0]
        if name in LEVEL_SLOTS:
            return self._dos("class_levels")[LEVEL_SLOTS[name]]
        if name == "size_small":
            return max(0, self._data[TABLE["size"].offset] - 1)
        if name == "class_bits":
            return dos_codec.neutral_class_bits_from(
                self._data[TABLE["class_bits"].offset],
                self._dos("class_levels"), self._dos("former_class_levels"))
        if name in ("spells_memorised", "spells_known", "spells_castable"):
            return self.get_raw(name)
        f = TABLE[RENAMED.get(name, name)]
        return _decode(f, self._data[f.span])

    def set(self, name: str, value: Any) -> None:
        """Encode `value` into the sheet field `name`.

        Only that field's bytes move, and nothing moves when `value` is what
        :meth:`get` already reads.  An ability writes both bytes of its pair,
        the permanent score and the score in force, as a character with no
        item or spell on that score holds them: the engine rebuilds the score
        in force from the permanent one, so an edit to the in-force byte
        alone is undone by the game, and an item or spell still running is
        put back on top of the edited score at that rebuild.
        """
        if not self.maps(name):
            raise FieldNotStored(f"Pools of Darkness has no {name} field")
        if value == self.get(name):
            return
        if name == "name":
            self._set_name(str(value))
        elif name in ABILITIES or name == "exceptional_strength":
            at = TABLE[name].offset
            score = _byte(name, value)
            self._data[at:at + 2] = bytes([score, score])
        elif name in LEVEL_SLOTS:
            at = TABLE["class_levels"].offset + LEVEL_SLOTS[name]
            self._data[at] = _byte(name, value)
        elif name == "size_small":
            self._data[TABLE["size"].offset] = _byte(name, int(value) + 1)
        elif name == "class_bits":
            self._data[TABLE["class_bits"].offset] = _byte(
                name, dos_codec.dos_class_bits(_byte(name, value)))
        elif name in ("spells_memorised", "spells_known", "spells_castable"):
            self.set_raw(name, value)
        else:
            dos = RENAMED.get(name, name)
            self._put(dos, _encode(TABLE[dos], name, value))

    def get_raw(self, name: str) -> bytes:
        """The bytes of `name` as the sheet reads them.

        `spells_memorised` is the 141 positions in the C64's order, highest
        spell first from the front: the DOS record fills them from the end,
        and reversing the run is the whole transpose
        (`goldbox.dos_codec.DosCharacter.spells_memorised`).  `spells_known`
        is the spellbook's 126 bytes, one an id, and `spells_castable` the
        three nine-byte slot arrays in record order (cleric, druid,
        magic-user).
        """
        if name == "spells_memorised":
            return bytes(reversed(self._dos("spells_memorised")))
        if name == "spells_known":
            return self._dos("spellbook")
        if name == "spells_castable":
            return b"".join(self._dos(f) for _c, f in SLOT_ARRAYS)
        if name == "name":
            return self._dos("name_length") + self._dos("name_text")
        if name in ABILITIES or name == "exceptional_strength":
            return bytes([self.get(name)])
        if name in LEVEL_SLOTS or name in ("size_small", "class_bits"):
            return bytes([self.get(name)])
        if not self.maps(name):
            raise FieldNotStored(f"Pools of Darkness has no {name} field")
        return self._dos(RENAMED.get(name, name))

    def set_raw(self, name: str, data: bytes) -> None:
        """The inverse of :meth:`get_raw`, over the same bytes."""
        data = bytes(data)
        kind, size = ((Kind.RAW, 1 + TABLE["name_text"].size)
                      if name == "name" else _sheet_kind(name))
        if len(data) != size:
            raise ValueError(f"{name}: expected exactly {size} bytes, got "
                             f"{len(data)}")
        if name == "spells_memorised":
            self._put("spells_memorised", bytes(reversed(data)))
        elif name == "spells_known":
            self._put("spellbook", data)
        elif name == "spells_castable":
            at = 0
            for _c, f in SLOT_ARRAYS:
                self._put(f, data[at:at + TABLE[f].size])
                at += TABLE[f].size
        elif name == "name":
            width = TABLE["name_text"].size
            if data[0] > width:
                raise ValueError(f"name: length {data[0]} is more than "
                                 f"{width}")
            self._put("name_length", data[:1])
            self._put("name_text", data[1:])
        elif name in ABILITIES or name == "exceptional_strength" or (
                name in LEVEL_SLOTS or name in ("size_small", "class_bits")):
            self.set(name, data[0])
        else:
            if not self.maps(name):
                raise FieldNotStored(f"Pools of Darkness has no {name} field")
            self._put(RENAMED.get(name, name), data)

    # -- what the sheet and the roster ask by attribute -------------------

    @property
    def name(self) -> str:
        width = TABLE["name_text"].size
        n = self._data[TABLE["name_length"].offset]
        if not 0 <= n <= width:
            raise dos_codec.DosRecordError(f"name length {n} is not 0-{width}")
        return self._dos("name_text")[:n].decode("latin1")

    def _set_name(self, text: str) -> None:
        width = TABLE["name_text"].size
        raw = text.encode("latin1")
        if len(raw) > width:
            raise ValueError(f"name: {text!r} is longer than {width} "
                             f"characters")
        self._put("name_length", bytes([len(raw)]))
        self._put("name_text", raw + bytes(width - len(raw)))

    @property
    def hp_max(self) -> int:
        return self.get("hp_max")

    @property
    def class_bits(self) -> int:
        return self.get("class_bits")

    @property
    def is_npc(self) -> bool:
        """Bit 7 of the control byte, which the engine tests to decide
        whether it drives the character itself."""
        return bool(self._data[_CONTROL_AT] & NPC_BIT)

    def ability_pair(self, name: str) -> tuple[int, int]:
        """One ability as `(in_force, permanent)`."""
        raw = self._dos(name)
        if name == "exceptional_strength":
            return raw[0], raw[1]
        return raw[1], raw[0]

    def class_levels(self) -> dict[str, int]:
        """Every class slot this title has, druid, paladin and ranger
        included, by class name; zero where the character has no level."""
        raw = self._dos("class_levels")
        return {cls: raw[slot] for slot, cls, _n in dos_codec.CLASS_LEVEL_SLOTS
                if slot < len(raw)}

    def former_class(self) -> tuple[str, int] | None:
        """The class a dual-classed human left and the level he left it at,
        off the record's own `former_class_levels`; None for a character
        holding no former class or, never measured, more than one."""
        raw = self._dos("former_class_levels")
        held = [(cls, raw[slot]) for slot, cls, _n in
                dos_codec.CLASS_LEVEL_SLOTS if slot < len(raw) and raw[slot]]
        return held[0] if len(held) == 1 else None

    # -- spells ------------------------------------------------------------

    def spell_slots(self) -> dict[str, tuple[int, ...]]:
        """Each caster class's nine slot bytes, spell level 1 first."""
        return {cls: tuple(self._dos(f)) for cls, f in SLOT_ARRAYS}

    def memorised_capacity(self) -> int:
        """How many spells the record's own slot bytes allow, all classes
        and levels together.  Read from the record rather than computed from
        the class levels, because a dual-classed character keeps the slots
        of the class he left: ABAGAIL (former cleric 11, magic-user 12)
        holds 46, where her current levels alone give 21."""
        return sum(self.get_raw("spells_castable"))

    def memorised(self) -> list[int]:
        """The memorised spell bytes in the C64's order, highest first, with
        bit 7 (memorising, not yet learnt) kept."""
        return [b for b in self.get_raw("spells_memorised") if b]

    def set_memorised(self, spells: list[int]) -> None:
        if len(spells) > MEMORISED_SIZE:
            raise ValueError(f"spells_memorised: {len(spells)} spells, the "
                             f"record holds {MEMORISED_SIZE}")
        raw = bytes(spells) + bytes(MEMORISED_SIZE - len(spells))
        if raw != self.get_raw("spells_memorised"):
            self.set_raw("spells_memorised", raw)

    def known_ids(self) -> list[int]:
        """The spell ids the spellbook holds: any non-zero byte."""
        return [i + 1 for i, b in enumerate(self._dos("spellbook")) if b]

    def set_known_ids(self, ids) -> None:
        """Write the spellbook as `ids`.  A byte for an id that stays known
        keeps its value -- the engine writes only 1, and the one byte of 8
        measured stays 8 -- an added id gets 1 and a removed one 0."""
        wanted = set(int(i) for i in ids)
        bad = [i for i in wanted if not 1 <= i <= SPELLBOOK_SIZE]
        if bad:
            raise ValueError(f"spells_known: ids {sorted(bad)} are outside "
                             f"1-{SPELLBOOK_SIZE}")
        book = bytearray(self._dos("spellbook"))
        for n in range(SPELLBOOK_SIZE):
            if (n + 1) in wanted and not book[n]:
                book[n] = 1
            elif (n + 1) not in wanted:
                book[n] = 0
        self._put("spellbook", bytes(book))


# ---------------------------------------------------------------------------
# One member, from either port
# ---------------------------------------------------------------------------
class PodMember(NamedTuple):
    """What the roster needs for one Pools of Darkness character.

    `dos` is the DOS character the sheet record was built from: the one the
    DOS reader read, or for an Amiga character the one the DOS writer
    rendered from it.  `native` is what the port itself holds: the
    `DosCharacter` again on DOS, the Amiga block on the Amiga.
    """

    record: PodSheetRecord
    dos: dos_codec.DosCharacter
    neutral: NeutralCharacter
    native: Any


def dos_member(path) -> PodMember:
    """One `CHRDAT<slot><n>.SAV` and its siblings."""
    char = dos_codec.read_character(path)
    if char.deltas is not DELTAS:
        raise dos_codec.DosRecordError(
            f"{path} is a {char.deltas.key} record, not Pools of Darkness")
    return PodMember(PodSheetRecord(char.to_bytes()), char,
                     dos_codec.to_neutral(char), char)


def amiga_member(block: bytes, position: int) -> PodMember:
    """One Amiga character block, rendered as the DOS record.

    The rendering is the one a Save As DOS writes for this character: the
    neutral record from `goldbox.amiga_pod.pod_to_neutral`, written by
    `goldbox.dos_codec.write` with the combat figure set to the file
    position, as `goldbox.dos_codec.new_pod_save_from` does.  The block
    itself is kept as `native`.  The class code, the turning row and the
    seven class levels are the block's own bytes rather than the rendering's:
    `goldbox.dos_codec.write` rebuilds the code from the levels and zeroes the
    levels of a class a dual-classed human left, so a value typed into any of
    them would read back changed.
    """
    from goldbox import amiga_pod

    neutral = amiga_pod.pod_to_neutral(block)
    rec, itm, spc, _report = dos_codec.write(neutral, deltas=DELTAS)
    record = bytearray(rec)
    record[TABLE["combat_figure"].offset] = position
    record[TABLE["char_class"].offset] = block[amiga_pod.CLASS]
    record[TABLE["turn_class"].offset] = block[amiga_pod.TURN_CLASS]
    levels = TABLE["class_levels"]
    record[levels.span] = block[
        amiga_pod.CLASS_LEVELS:amiga_pod.CLASS_LEVELS + levels.size]
    effects = [spc[i:i + dos_codec.EFFECT_SIZE]
               for i in range(0, len(spc), dos_codec.EFFECT_SIZE)]
    char = dos_codec.DosCharacter(
        bytes(record), dos_codec.item_nodes(itm, DELTAS.item_size), effects,
        deltas=DELTAS)
    return PodMember(PodSheetRecord(bytes(record)), char, neutral,
                     bytes(block))


def item_blocks(char: dos_codec.DosCharacter) -> list[bytes]:
    """The sixteen item slots the sheet's inventory shows: the first sixteen
    items projected by `goldbox.dos_codec.item_to_c64`, empty slots after.
    Items past the sixteenth are not shown; nothing here writes them."""
    shown = [dos_codec.item_to_c64(i.to_bytes())
             for i in char.items[:ITEMS_PER_CHARACTER]]
    return shown + [bytes(ITEM_SIZE)] * (ITEMS_PER_CHARACTER - len(shown))


def rewrite_record(original: bytes, before: PodSheetRecord,
                   after: PodSheetRecord) -> tuple[bytes, list[str]]:
    """`original` with only the DOS fields `before` and `after` disagree
    about copied from `after`, through `goldbox.rewrite.patch` and this
    title's `goldbox.rewrite.dos_spans`.

    `original` is the DOS record the character came from.  A field nobody
    edited keeps those bytes, so the druid, paladin and ranger levels, the
    drain marks and every byte with no box survive an edit elsewhere.
    Returns the bytes and the names of the DOS fields that moved.
    """
    spans, _unplaced = rewrite.dos_spans(DELTAS)
    return rewrite.patch(original, before.to_bytes(), after.to_bytes(), spans,
                         edited=before.to_bytes() != after.to_bytes())

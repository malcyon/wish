"""Decode / encode a Pool of Radiance (C64) 580-byte character record.

:class:`CharacterRecord` operates on a plain ``bytes`` object and knows nothing
about where those bytes came from -- a .d64 image, a save file, emulator RAM,
a hex editor.  Bytes in, bytes out.

The record is held verbatim as a mutable buffer and fields are read and written
*through* :mod:`goldbox.layout`.  That is deliberate: it makes a decode/encode
cycle byte-exact by construction, so the many bytes whose meaning we have not
yet worked out can never be dropped, normalised or zeroed on the way through.

Typical use::

    rec = CharacterRecord.from_prg(open("brutus.chr", "rb").read())
    print(rec.name, rec.strength, rec.exceptional_strength)
    rec.strength = 17
    open("brutus2.chr", "wb").write(rec.to_prg())
    print(rec.dump())
"""

from __future__ import annotations

from typing import Any, Iterator

from . import encoding, petscii
from .layout import (
    LAYOUT,
    LOAD_ADDRESS,
    PRG_SIZE,
    RECORD_SIZE,
    Confidence,
    Field,
    Kind,
    field_by_name,
    named_fields,
    unknown_fields,
)

__all__ = [
    "RecordSizeError",
    "CharacterRecord",
    "strip_load_address",
    "add_load_address",
]


class RecordSizeError(ValueError):
    """Raised when a buffer is not the size a character record must be."""


# ---------------------------------------------------------------------------
# PRG wrapper helpers -- thin and explicit; disk I/O lives elsewhere.
# ---------------------------------------------------------------------------
def strip_load_address(data: bytes, expected: int | None = LOAD_ADDRESS) -> bytes:
    """Drop the 2-byte little-endian PRG load address from *data*.

    Args:
        data: A 582-byte PRG image of one character record.
        expected: Load address to check for, or None to skip the check.
            The mismatch is reported as a ValueError, not silently ignored.

    Raises:
        RecordSizeError: if *data* is not 582 bytes.
        ValueError: if the load address is present but not *expected*.
    """
    if len(data) != PRG_SIZE:
        raise RecordSizeError(
            f"expected {PRG_SIZE} bytes of PRG data (2-byte load address + "
            f"{RECORD_SIZE}-byte record), got {len(data)}"
        )
    address = data[0] | (data[1] << 8)
    if expected is not None and address != expected:
        raise ValueError(
            f"unexpected PRG load address {address:#06x}; expected {expected:#06x}"
        )
    return bytes(data[2:])


def add_load_address(record: bytes, address: int = LOAD_ADDRESS) -> bytes:
    """Prepend a 2-byte little-endian PRG load address to a record."""
    if len(record) != RECORD_SIZE:
        raise RecordSizeError(
            f"expected a {RECORD_SIZE}-byte record, got {len(record)}"
        )
    if not 0 <= address <= 0xFFFF:
        raise ValueError(f"load address {address:#x} out of range")
    return bytes([address & 0xFF, (address >> 8) & 0xFF]) + bytes(record)


# ---------------------------------------------------------------------------
# Per-kind codecs
# ---------------------------------------------------------------------------
def _decode_field(f: Field, raw: bytes) -> Any:
    if f.kind is Kind.U8:
        return raw[0]
    if f.kind is Kind.I8:
        return raw[0] - 256 if raw[0] > 127 else raw[0]
    if f.kind in (Kind.U16LE, Kind.UINT_LE):
        return int.from_bytes(raw, "little")
    if f.kind is Kind.ASCII_NUL:
        return petscii.decode_record_name(raw)
    return bytes(raw)


def _encode_field(f: Field, value: Any) -> bytes:
    if f.kind is Kind.I8:
        value = int(value)
        if not -128 <= value <= 127:
            raise ValueError(f"{f.name}: {value} does not fit in a signed byte")
        return bytes([value & 0xFF])
    if f.kind is Kind.U8:
        value = int(value)
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{f.name}: {value} does not fit in a byte")
        return bytes([value])
    if f.kind in (Kind.U16LE, Kind.UINT_LE):
        value = int(value)
        limit = (1 << (8 * f.size)) - 1
        if not 0 <= value <= limit:
            raise ValueError(f"{f.name}: {value} does not fit in {f.size} bytes")
        return value.to_bytes(f.size, "little")
    if f.kind is Kind.ASCII_NUL:
        return petscii.encode_record_name(str(value), f.size)
    data = bytes(value)
    if len(data) != f.size:
        raise ValueError(
            f"{f.name}: expected exactly {f.size} raw bytes, got {len(data)}"
        )
    return data


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------
# Six bytes read $FF in every one of the five NPCs on npc_party.d64 and $00 in
# every player character we hold, so an NPC is reliably recognisable.
#
# What they are is now clearer and less flag-like: all five of those NPCs are
# records the game itself ships in its MON* files, and the six bytes read $FF
# *in the shipped file*, before any save is involved. So this is residue of the
# $FF fill a shipped record carries, surviving the load into a party slot, and
# a player character has $00 because nothing ever wrote $FF. Whether the game
# tests any of them is unproven -- possibly none -- so we read and write all
# six together and treat writing the flag as unproven in both directions.
#
# Two more offsets of the original eight, 0x0B9 and 0x0BA, are not fill at
# all: they are dual_class_slot and dual_class_level, a dual-classed human's
# old class and the level it was left at, written by Curse of the Azure
# Bonds, Secret of the Silver Blades and Gateway to the Savage Frontier and
# never touched by Pool of Radiance -- see goldbox/layout.py and #224
# (0x0B9 and 0x0BA are documented both as an NPC marker and as the dual-class
# slot). A dual-classed character of those three titles is non-zero there and
# $00 at the other six, which is not corruption -- #229 (A dual-classed
# Curse character imports with a warning that its record is corrupt).
#
# 0x0E6-0x0E7 read $FF FF in those NPCs too and were briefly counted here, but
# they are a *different* field: every player character has a non-zero,
# high-entropy value there, so they are not a 0/$FF pair and are left alone.
NPC_MARKER_OFFSETS = (0x0B7, 0x0D3, 0x0D4, 0x0E4, 0x0E5, 0x0FB)
NPC_MARKER = 0xFF

# The flag the game actually tests, at record offset 0x0B8.
NPC_FLAG_OFFSET = 0x0B8
NPC_FLAG_BIT = 0x80
SCORE_ALTERED_BIT = 0x01


class FieldNotStored(KeyError):
    """A field beyond the bytes this record actually carries."""


class CharacterRecord:
    """A mutable view over one 580-byte character record.

    Named fields from :mod:`goldbox.layout` are exposed as attributes, e.g.
    ``.name``, ``.strength``, ``.exceptional_strength``.  Unknown regions are
    reachable through :meth:`get_raw` / :meth:`set_raw` but are otherwise left
    strictly alone.
    """

    __slots__ = ("_data", "stored_size")

    SIZE = RECORD_SIZE

    def __init__(self, data: bytes, stored_size: int | None = None) -> None:
        if len(data) != RECORD_SIZE:
            raise RecordSizeError(
                f"a character record is {RECORD_SIZE} bytes, got {len(data)}"
                + (
                    f" (looks like PRG data -- use {type(self).__name__}.from_prg)"
                    if len(data) == PRG_SIZE
                    else ""
                )
            )
        object.__setattr__(self, "_data", bytearray(data))
        object.__setattr__(self, "stored_size",
                           RECORD_SIZE if stored_size is None else stored_size)

    # -- constructors ------------------------------------------------------
    @classmethod
    def from_bytes(cls, data: bytes) -> "CharacterRecord":
        """Build from exactly 580 record bytes."""
        return cls(data)

    @classmethod
    def from_prg(
        cls, data: bytes, expected_load_address: int | None = LOAD_ADDRESS
    ) -> "CharacterRecord":
        """Build from the 582-byte PRG form, discarding the load address.

        This is a convenience shim only; reading the PRG out of a disk image is
        another module's job.
        """
        return cls(strip_load_address(data, expected_load_address))

    @classmethod
    def blank(cls) -> "CharacterRecord":
        """An all-zero record, useful as a scratch buffer for experiments."""
        return cls(bytes(RECORD_SIZE))

    # -- serialisation -----------------------------------------------------
    def to_bytes(self) -> bytes:
        """The 580 record bytes.  Byte-exact with the input if untouched."""
        return bytes(self._data)

    def to_prg(self, address: int = LOAD_ADDRESS) -> bytes:
        """The 582-byte PRG form (load address + record)."""
        return add_load_address(bytes(self._data), address)

    def __bytes__(self) -> bytes:
        return self.to_bytes()

    def __len__(self) -> int:
        return len(self._data)

    # -- generic field access ---------------------------------------------
    @property
    def thac0_base_value(self) -> int:
        """Base THAC0 as the sheet shows it, not the `60 - x` byte.

        `get("thac0_base")` returns 39 for a THAC0 of 21, which is correct and
        catches people out. Use this.
        """
        return encoding.combat_value(self.get("thac0_base"))

    @property
    def armour_class_base_value(self) -> int:
        """Base armour class, unbiased. 10 for every player character; a monster
        carries its real AC here."""
        return encoding.combat_value(self.get("armour_class_base"))

    def is_stored(self, name: str) -> bool:
        """Does this record actually carry the bytes of `name`?

        A record read out of a **save slot** holds only its first 256 bytes;
        the rest is zero padding. That matters because the tail is not junk --
        `0x100`-`0x11F` is the SAVEDGAME1 roster block and `0x120`+ is the item
        area, both of which the game keeps elsewhere. Reading `armour_class`
        from a slot therefore yields `60 - 0`, i.e. **AC 60**, which is a
        plausible-looking number and completely wrong.
        """
        return field_by_name(name).end <= self.stored_size

    def get(self, name: str) -> Any:
        """Decoded value of the field called *name*."""
        f = field_by_name(name)
        if f.end > self.stored_size:
            raise FieldNotStored(
                f"{name} is at {f.offset:#05x}, past the {self.stored_size} "
                f"bytes this record carries. A save slot stores 256; the "
                f"roster block and the item area hold the rest. Read it from "
                f"there, or check is_stored() first")
        return _decode_field(f, self._data[f.span])

    def set(self, name: str, value: Any) -> None:
        """Encode *value* into the field called *name*.

        Only the bytes belonging to that field are touched.
        """
        f = field_by_name(name)
        encoded = _encode_field(f, value)
        assert len(encoded) == f.size  # codecs must be width-exact
        self._data[f.span] = encoded

    def get_raw(self, name: str) -> bytes:
        """Raw bytes of the field called *name*, whatever its kind."""
        f = field_by_name(name)
        return bytes(self._data[f.span])

    def set_raw(self, name: str, data: bytes) -> None:
        """Overwrite the raw bytes of the field called *name*."""
        f = field_by_name(name)
        data = bytes(data)
        if len(data) != f.size:
            raise ValueError(
                f"{name}: expected exactly {f.size} bytes, got {len(data)}"
            )
        self._data[f.span] = data

    def slice(self, offset: int, size: int) -> bytes:
        """Raw bytes at an arbitrary offset (for exploratory work)."""
        if offset < 0 or offset + size > RECORD_SIZE:
            raise IndexError(
                f"slice {offset:#x}+{size} escapes the {RECORD_SIZE}-byte record"
            )
        return bytes(self._data[offset : offset + size])

    def fields(self) -> Iterator[tuple[Field, Any]]:
        """Yield ``(field, decoded value)`` for every entry in the layout."""
        for f in LAYOUT:
            yield f, _decode_field(f, self._data[f.span])

    def to_dict(self, include_unknown: bool = False) -> dict[str, Any]:
        """Decoded fields as a dict, keyed by field name."""
        return {
            f.name: _decode_field(f, self._data[f.span])
            for f in LAYOUT
            if f.is_known or include_unknown
        }

    # -- comparison / debugging -------------------------------------------
    def __eq__(self, other: object) -> bool:
        if isinstance(other, CharacterRecord):
            return self._data == other._data
        if isinstance(other, (bytes, bytearray)):
            return bytes(self._data) == bytes(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(bytes(self._data))

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} name={self.name!r} "
            f"STR={self.strength}/{self.exceptional_strength:02d} "
            f"INT={self.intelligence} WIS={self.wisdom} DEX={self.dexterity} "
            f"CON={self.constitution} CHA={self.charisma}>"
        )

    def diff(self, other: "CharacterRecord | bytes") -> list[tuple[int, int, int]]:
        """Byte-level differences: ``(offset, mine, theirs)`` for each mismatch."""
        theirs = bytes(other._data) if isinstance(other, CharacterRecord) else bytes(other)
        if len(theirs) != RECORD_SIZE:
            raise RecordSizeError(
                f"cannot diff against {len(theirs)} bytes; need {RECORD_SIZE}"
            )
        return [
            (i, a, b) for i, (a, b) in enumerate(zip(self._data, theirs)) if a != b
        ]

    def dump(self, show_zero_unknowns: bool = False, width: int = 16) -> str:
        """A readable summary: known fields, then a hex view of unknown regions.

        Args:
            show_zero_unknowns: Also print unknown regions that are entirely
                zero in this record.  Off by default -- during discovery the
                non-zero regions are the interesting ones.
            width: Bytes per hex line.
        """
        lines = [f"CharacterRecord {RECORD_SIZE} bytes"]
        lines.append("")
        lines.append("known fields:")
        for f in named_fields():
            value = _decode_field(f, self._data[f.span])
            shown = repr(value) if isinstance(value, (str, bytes)) else str(value)
            lines.append(
                f"  {f.offset:#05x} {f.label:<8} {shown:<24} "
                f"[{f.confidence.value}]"
            )

        lines.append("")
        lines.append(
            "unknown regions"
            + ("" if show_zero_unknowns else " (non-zero only)")
            + ":"
        )
        any_shown = False
        for f in unknown_fields():
            raw = bytes(self._data[f.span])
            if not any(raw) and not show_zero_unknowns:
                continue
            any_shown = True
            tag = " *candidate*" if f.candidate else ""
            lines.append(f"  {f.name}: {f.label}  ({f.size} bytes){tag}")
            if f.note:
                lines.append(f"    note: {f.note}")
            lines.extend(
                "    " + line for line in _hexdump(raw, f.offset, width)
            )
        if not any_shown:
            lines.append("  (none)")
        return "\n".join(lines)

    def hexdump(self, width: int = 16) -> str:
        """Full hex dump of the record."""
        return "\n".join(_hexdump(bytes(self._data), 0, width))

    # -- player character or NPC ------------------------------------------
    @property
    def is_npc(self) -> bool:
        """True for an NPC or a monster: bit 7 of `0x0B8`.

        This is the byte the game itself tests. Every read of $6BB8 in the
        overlays checks bit 7; the party-count routine tallies player
        characters with it and enforces CMP #$06, which is the six-PC limit;
        and NPC money is zeroed on it. npc_party.d64 splits three players from
        five NPCs exactly here.

        The six $FF bytes at `NPC_MARKER_OFFSETS` correlate perfectly and
        were read as the flag for a while. They are fill residue -- they read
        $FF in the shipped MON* files before any save exists.
        """
        return bool(self._data[NPC_FLAG_OFFSET] & NPC_FLAG_BIT)

    @property
    def score_altered_at_trainer(self) -> bool:
        """Bit 0 of `0x0B8`, set by GEN $155D when a score is changed.

        **Nothing reads it back.** A forum rumour holds that an original
        developer said altering scores carries a penalty in play; on this port
        there is no code that could apply one.
        """
        return bool(self._data[NPC_FLAG_OFFSET] & SCORE_ALTERED_BIT)

    @property
    def npc_marker_is_consistent(self) -> bool:
        """False if the six residue bytes are half set -- no save has been
        seen like that, so it means something has corrupted the record.

        `0x0B9`/`0x0BA` used to be two of the eight and are gone from the
        set: they are `dual_class_slot`/`dual_class_level`, a real field in
        three titles, and a dual-classed character legitimately holds them
        non-zero while these six stay $00 -- #229 (A dual-classed Curse
        character imports with a warning that its record is corrupt).
        """
        vals = {self._data[o] for o in NPC_MARKER_OFFSETS}
        return vals in ({NPC_MARKER}, {0x00})

    def set_npc(self, value: bool) -> None:
        """Set or clear the flag the game tests.

        The six residue bytes are left alone: writing them changes nothing
        the game reads, and rewriting bytes we do not understand is how a
        lossless editor stops being lossless.
        """
        if value:
            self._data[NPC_FLAG_OFFSET] |= NPC_FLAG_BIT
        else:
            self._data[NPC_FLAG_OFFSET] &= ~NPC_FLAG_BIT & 0xFF


def _hexdump(data: bytes, base: int, width: int = 16) -> list[str]:
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        hexpart = " ".join(f"{b:02X}" for b in chunk)
        text = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        lines.append(f"{base + i:#06x}  {hexpart:<{width * 3 - 1}}  {text}")
    return lines


# ---------------------------------------------------------------------------
# Attribute access, generated from the layout.
#
# Adding a named field to goldbox.layout automatically gives it an attribute here;
# no edit to this module is needed.
# ---------------------------------------------------------------------------
def _make_property(f: Field) -> property:
    def getter(self: CharacterRecord, _f: Field = f) -> Any:
        return _decode_field(_f, self._data[_f.span])

    def setter(self: CharacterRecord, value: Any, _f: Field = f) -> None:
        self._data[_f.span] = _encode_field(_f, value)

    doc = f"{f.label} ({f.kind.value} at {f.offset:#05x}, {f.confidence.value})"
    if f.note:
        doc += f"\n\n{f.note}"
    return property(getter, setter, doc=doc)


for _f in LAYOUT:
    if _f.confidence is not Confidence.UNKNOWN:
        setattr(CharacterRecord, _f.name, _make_property(_f))
del _f

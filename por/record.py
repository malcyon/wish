"""Decode / encode a Pool of Radiance (C64) 580-byte character record.

:class:`CharacterRecord` operates on a plain ``bytes`` object and knows nothing
about where those bytes came from -- a .d64 image, a save file, emulator RAM,
a hex editor.  Bytes in, bytes out.

The record is held verbatim as a mutable buffer and fields are read and written
*through* :mod:`por.layout`.  That is deliberate: it makes a decode/encode
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

from . import petscii
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
    if f.kind is Kind.U16LE:
        return int.from_bytes(raw, "little")
    if f.kind is Kind.ASCII_NUL:
        return petscii.decode_record_name(raw)
    return bytes(raw)


def _encode_field(f: Field, value: Any) -> bytes:
    if f.kind is Kind.U8:
        value = int(value)
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{f.name}: {value} does not fit in a byte")
        return bytes([value])
    if f.kind is Kind.U16LE:
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
# Eight bytes read $FF in every one of the five NPCs on npc_party.d64 and $00
# in all twenty player characters we hold. Whether one of these is the flag and
# the rest follow from it, or all eight are separate "not applicable"
# sentinels, is unproven -- so we read and write all eight together.
#
# 0x0E6-0x0E7 read $FF FF in those NPCs too and were briefly counted here, but
# they are a *different* field: every player character has a non-zero,
# high-entropy value there, so they are not a 0/$FF pair and are left alone.
NPC_MARKER_OFFSETS = (0x0B7, 0x0B9, 0x0BA, 0x0D3, 0x0D4,
                      0x0E4, 0x0E5, 0x0FB)
NPC_MARKER = 0xFF


class CharacterRecord:
    """A mutable view over one 580-byte character record.

    Named fields from :mod:`por.layout` are exposed as attributes, e.g.
    ``.name``, ``.strength``, ``.exceptional_strength``.  Unknown regions are
    reachable through :meth:`get_raw` / :meth:`set_raw` but are otherwise left
    strictly alone.
    """

    __slots__ = ("_data",)

    SIZE = RECORD_SIZE

    def __init__(self, data: bytes) -> None:
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
    def get(self, name: str) -> Any:
        """Decoded value of the field called *name*."""
        f = field_by_name(name)
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
        """True when every byte of the NPC fingerprint reads $FF.

        See `NPC_MARKER_OFFSETS`. Eight bytes agree perfectly across all
        twenty-five characters we hold, so an NPC is reliably *recognisable*;
        which byte the game actually tests is not known.
        """
        return all(self._data[o] == NPC_MARKER for o in NPC_MARKER_OFFSETS)

    @property
    def npc_marker_is_consistent(self) -> bool:
        """False if the fingerprint is half set -- a state no save has been
        seen in, and a sign something has corrupted the record."""
        vals = {self._data[o] for o in NPC_MARKER_OFFSETS}
        return vals in ({NPC_MARKER}, {0x00})

    def set_npc(self, value: bool) -> None:
        """Write the whole fingerprint. Unproven in both directions -- nothing
        has yet been changed here and checked in game."""
        for o in NPC_MARKER_OFFSETS:
            self._data[o] = NPC_MARKER if value else 0x00


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
# Adding a named field to por.layout automatically gives it an attribute here;
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

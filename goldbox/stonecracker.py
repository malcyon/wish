"""StoneCracker 4.04 (`S404`) crunched Amiga files, decrunched in memory.

One release of Amiga Pools of Darkness carries its program crunched this way:
a Hunk executable whose last code hunk holds a decrunch stub, then an `S404`
header and the packed stream. Nothing here runs that stub. The format is read
from it -- the decrunch and hunk-rebuild routines in the crunched
`/Pools of Darkness` of the `[a]` disk 1 -- and implemented independently;
`docs/86-spell-table.md` has the evidence that the result is the program.

**The header.** `S404`, then three big-endian longs: the gap the stub leaves
between the header and its output when it decrunches in place (unused here),
the decrunched length, and the packed length counted from that last long's own
offset. The packed stream follows the header and ends in a six-byte trailer
of three words: the bit width of a far offset, the partly used last bit
buffer, and how many of its high bits are still unread.

**The stream** is read backwards, a 16-bit word at a time from the trailer
towards the header, each word most significant bit first; the output is built
backwards too, from its last byte to its first. A token is:

| bits | meaning |
|---|---|
| `0`, 8 bits | one literal byte |
| `11`, 1 bit `v` | copy `2 + v` bytes |
| `101`, 2 bits `v` | copy `4 + v` bytes |
| `1001`, 4 bits `v` < 15 | copy `8 + v` bytes |
| `1001`, `1111`, 5 bits `v` | `14 + v` literal bytes, 8 bits each |
| `1000`, bytes `b` | copy `23 + sum(b)` bytes; each 8-bit `b` of 255 is followed by another |

A copy is followed by its offset: `1` and the trailer's width in bits plus
`0x220`; `01` and 5 bits; `00` and 9 bits plus `0x20`. Offset `n` copies from
`n + 1` bytes above the byte being written, one byte at a time, so a copy may
overlap itself.

**The decrunched executable** is StoneCracker's own layout, not a Hunk file:
a long holding the number of hunks less one, one size long per hunk (in longs,
bit 30 asking for chip memory as in a hunk header), then blocks introduced by
a word. A nonzero word starts the next hunk: with bit 14 set, the hunk's
contents follow as a word and that many longs, the length's high bits being
the introducing word's bits 0-13; with bit 14 clear the hunk has no contents.
A zero word starts the relocations for the last hunk with contents, in groups
aligned to a word: a count (zero ends them), the target hunk, then a long
whose top byte selects the width of every later entry (2: three bytes, 6: two,
10: one) and whose low 24 bits are the first offset; each later entry is the
difference from the previous offset. The word `$FFFF` ends the layout.

**The layout keeps no hunk types.** Code and data hunks are introduced alike,
so `hunk_file` calls the first hunk code (AmigaDOS starts a program at its
first byte), every other hunk with contents data, and one without contents
BSS, unless told otherwise; the uncrunched Pools of Darkness builds are laid
out exactly that way.
"""

from __future__ import annotations

import dataclasses
import struct

from . import amiga_hunks

MAGIC = b"S404"
NAME = "StoneCracker 4.04"

#: The layout's end marker, and its "this hunk has contents" bit.
_END = 0xFFFF
_HAS_CONTENTS = 0x4000

#: A relocation group's selector byte: how many bytes each later entry takes.
_DELTA_WIDTH = {2: 3, 6: 2, 10: 1}


class StoneCrackerError(ValueError):
    """The bytes are not a StoneCracker 4.04 stream this module can decrunch."""


@dataclasses.dataclass(frozen=True)
class Header:
    """The `S404` header at `at`: lengths, and where the stream lies."""
    at: int
    gap: int
    length: int
    packed: int

    @property
    def start(self) -> int:
        """The first byte of the packed stream."""
        return self.at + 16

    @property
    def trailer(self) -> int:
        """The six-byte trailer's offset, just past the packed stream."""
        return self.at + 12 + self.packed

    @property
    def end(self) -> int:
        return self.trailer + 6


def header(data: bytes, at: int = 0) -> Header:
    """The `S404` header at `at`; raises `StoneCrackerError` if it is not one."""
    if data[at:at + 4] != MAGIC or at + 22 > len(data):
        raise StoneCrackerError(f"no {NAME} header at {at:#x}")
    gap, length, packed = struct.unpack_from(">III", data, at + 4)
    head = Header(at, gap, length, packed)
    if packed < 4 or packed % 2 or head.end > len(data):
        raise StoneCrackerError(
            f"the {NAME} stream at {at:#x} claims {packed} packed bytes; "
            f"{len(data) - at - 18} are there")
    return head


class _Bits:
    """The stream's bits in the order the decruncher takes them."""

    def __init__(self, data: bytes, head: Header):
        self.data = data
        self.low = head.start
        self.width, self.buffer, self.left = struct.unpack_from(
            ">HHH", data, head.trailer)
        if not 1 <= self.width <= 16 or self.left > 16:
            raise StoneCrackerError(
                f"bad {NAME} trailer: offset width {self.width}, "
                f"{self.left} bits left")
        self.buffer = (self.buffer >> (16 - self.left)) if self.left else 0
        self.word = head.trailer

    def take(self, n: int) -> int:
        """The next `n` bits, first-read bit most significant."""
        while self.left < n:
            self.word -= 2
            if self.word < self.low:
                raise StoneCrackerError(f"the {NAME} stream ends early")
            self.buffer = (self.buffer << 16) | (
                self.data[self.word] << 8 | self.data[self.word + 1])
            self.left += 16
        self.left -= n
        value = self.buffer >> self.left
        self.buffer &= (1 << self.left) - 1
        return value


def decrunch(data: bytes, at: int = 0) -> bytes:
    """The decrunched bytes of the `S404` stream whose header is at `at`.

    Raises `StoneCrackerError` for a stream that reads past its own start,
    copies from beyond what it has written, or overruns its stated length.
    """
    head = header(data, at)
    bits = _Bits(data, head)
    out = bytearray(head.length)
    o = head.length                     # out[o:] is written
    take = bits.take

    def literal(count):
        nonlocal o
        if count > o:
            raise StoneCrackerError(f"{NAME} literals overrun the output")
        for _ in range(count):
            o -= 1
            out[o] = take(8)

    while o > 0:
        if not take(1):
            literal(1)
            continue
        if take(1):
            count = 2 + take(1)
        elif take(1):
            count = 4 + take(2)
        elif take(1):
            v = take(4)
            if v == 15:
                literal(14 + take(5))
                continue
            count = 8 + v
        else:
            count = 23
            while (v := take(8)) == 255:
                count += 255
            count += v
        if take(1):
            offset = 0x220 + take(bits.width)
        elif take(1):
            offset = take(5)
        else:
            offset = 0x20 + take(9)
        src = o + offset
        if src >= head.length or count > o:
            raise StoneCrackerError(
                f"{NAME} copy of {count} from offset {offset} at {o} "
                f"leaves the output")
        for _ in range(count):
            o -= 1
            out[o] = out[src]
            src -= 1
    return bytes(out)


@dataclasses.dataclass
class Segment:
    """One hunk of the decrunched layout."""
    #: The hunk-header size long: longs to allocate, bits 30-31 memory flags.
    size: int
    #: The hunk's contents, or None for a hunk without any.
    contents: bytes | None = None
    #: `{target hunk: [offsets]}` of its 32-bit relocations.
    relocs: dict[int, list[int]] = dataclasses.field(default_factory=dict)

    @property
    def allocated(self) -> int:
        return 4 * (self.size & 0x3FFFFFFF)


def segments(layout: bytes) -> list[Segment]:
    """The hunks of StoneCracker's decrunched executable layout.

    Raises `StoneCrackerError` when the layout does not add up: more hunks
    than it declares, contents longer than a hunk's size, relocations before
    any contents, an unknown entry width, or no end marker.
    """
    def word(p):
        if p + 2 > len(layout):
            raise StoneCrackerError("the layout ends without its end marker")
        return struct.unpack_from(">H", layout, p)[0]

    if len(layout) < 4:
        raise StoneCrackerError("the layout is too short for a hunk count")
    count = struct.unpack_from(">I", layout, 0)[0] + 1
    if 8 + 4 * count > len(layout) or count > 0xFFFF:
        raise StoneCrackerError(f"the layout claims {count} hunks")
    hunks = [Segment(size) for size in
             struct.unpack_from(f">{count}I", layout, 4)]
    p = 4 + 4 * count
    current = -1
    with_contents = None
    while (kind := word(p)) != _END:
        p += 2
        if kind:
            current += 1
            if current >= count:
                raise StoneCrackerError(f"more than the {count} hunks declared")
            if kind & _HAS_CONTENTS:
                longs = (kind & 0x3FFF) << 16 | word(p)
                p += 2
                if 4 * longs > hunks[current].allocated or p + 4 * longs > len(layout):
                    raise StoneCrackerError(
                        f"hunk {current} holds {4 * longs} bytes; it has room "
                        f"for {hunks[current].allocated}")
                hunks[current].contents = layout[p:p + 4 * longs]
                p += 4 * longs
                with_contents = current
            continue
        if with_contents is None:
            raise StoneCrackerError("relocations before any hunk with contents")
        relocs = hunks[with_contents].relocs
        while True:
            p += p & 1
            entries = word(p)
            if entries == 0:
                p += 2
                break
            target = word(p + 2)
            if target >= count or p + 8 > len(layout):
                raise StoneCrackerError(f"relocation to hunk {target} of {count}")
            selector = layout[p + 4]
            offset = struct.unpack_from(">I", layout, p + 4)[0] & 0xFFFFFF
            width = _DELTA_WIDTH.get(selector)
            if width is None:
                raise StoneCrackerError(f"relocation entry width {selector}")
            p += 8
            offsets = [offset]
            for _ in range(entries - 1):
                offset += int.from_bytes(layout[p:p + width], "big")
                p += width
                offsets.append(offset)
            if p > len(layout):
                raise StoneCrackerError("the relocations run past the layout")
            relocs.setdefault(target, []).extend(offsets)
    return hunks


def hunk_file(hunks: list[Segment], kinds: list[int] | None = None) -> bytes:
    """A standard Hunk executable holding `hunks`.

    `kinds` gives each hunk's `amiga_hunks.HUNK_CODE`, `HUNK_DATA` or
    `HUNK_BSS`; by default the first is code, the others with contents data
    and those without BSS, as the module docstring explains.
    """
    if kinds is None:
        kinds = [amiga_hunks.HUNK_BSS if h.contents is None else
                 amiga_hunks.HUNK_CODE if i == 0 else amiga_hunks.HUNK_DATA
                 for i, h in enumerate(hunks)]

    def u32(n):
        return struct.pack(">I", n)

    out = bytearray(u32(amiga_hunks.HUNK_HEADER) + u32(0) + u32(len(hunks))
                    + u32(0) + u32(len(hunks) - 1))
    out += b"".join(u32(h.size) for h in hunks)
    for hunk, kind in zip(hunks, kinds):
        if kind == amiga_hunks.HUNK_BSS:
            out += u32(kind) + u32(hunk.size & 0x3FFFFFFF)
        else:
            body = hunk.contents or b""
            out += u32(kind) + u32(len(body) // 4) + body
        if hunk.relocs:
            out += u32(amiga_hunks.HUNK_RELOC32)
            for target, offsets in sorted(hunk.relocs.items()):
                out += u32(len(offsets)) + u32(target)
                out += b"".join(u32(o) for o in sorted(offsets))
            out += u32(0)
        out += u32(amiga_hunks.HUNK_END)
    return bytes(out)


def find(program: bytes) -> Header | None:
    """The `S404` header in a crunched Hunk executable, or None.

    The header sits in a code hunk after the decrunch stub, and its stream
    and trailer end within the last long of that hunk.
    """
    if MAGIC not in program:
        return None
    try:
        hunks, _ = amiga_hunks.parse(program)
    except (ValueError, IndexError, struct.error):
        return None
    for hunk in hunks:
        if hunk.kind != "CODE" or hunk.file_offset is None:
            continue
        end = hunk.file_offset + hunk.size
        at = program.find(MAGIC, hunk.file_offset, end)
        while at >= 0:
            try:
                head = header(program[:end], at)
            except StoneCrackerError:
                head = None
            if head is not None and end - head.end < 4:
                return head
            at = program.find(MAGIC, at + 1, end)
    return None


def is_crunched(program: bytes) -> bool:
    """Whether `program` is a StoneCracker 4.04-crunched Hunk executable."""
    return find(program) is not None


def uncrunch(program: bytes) -> bytes:
    """The Hunk executable a crunched one decrunches to.

    Raises `StoneCrackerError` when `program` is not crunched or does not
    decrunch.
    """
    head = find(program)
    if head is None:
        raise StoneCrackerError(f"not a {NAME}-crunched Hunk executable")
    return hunk_file(segments(decrunch(program, head.at)))


def as_loaded(program: bytes) -> bytes:
    """`program` decrunched if it is crunched, otherwise unchanged.

    The call for any reader of an Amiga program: an uncrunched one costs a
    search for the magic.
    """
    return uncrunch(program) if is_crunched(program) else program

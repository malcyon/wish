#!/usr/bin/env python3
"""A 68000 disassembler that refuses to guess.

Written to read the Amiga Gold Box binaries, which are Motorola 68000 and
nothing later.  The one rule that matters: **an encoding this does not
recognise prints as ``dc.w $xxxx``, never as a plausible instruction.**  A
disassembler that invents an instruction is worse than one that stops, because
the invented instruction gets believed and written into a document.

So every field is checked before a mnemonic is emitted.  An addressing mode the
instruction cannot take, a 68020 full-format index extension, a size field the
opcode does not define, a word that runs off the end of the buffer -- each one
falls through to ``dc.w`` rather than being rounded to the nearest instruction
that fits.

**Two of those refusals are judgement, not the instruction set**, and the
distinction matters enough to say here: a 68020 index extension and a branch to
an odd address are both encodings a 68000 will happily execute -- it ignores
the reserved extension bits, and it takes the odd branch and address-errors
afterwards.  Neither is refused because the CPU cannot do it.  They are refused
because **no assembler emits them**, so a word carrying one is data rather than
code, and telling those apart is most of the work in a binary with strings and
tables scattered through its code hunk.  Do not cite this file for what a 68000
can and cannot encode.

Nothing outside the range the caller asked for is read.  An instruction whose
extension words would cross the end of the window prints as ``dc.w`` instead,
because a window landing one instruction short of a hunk boundary would
otherwise disassemble the relocation table behind it and say nothing about
having done so.

Displacements are resolved: ``bcc``, ``bsr``, ``dbcc`` and every PC-relative
effective address print the absolute address they reach, so a branch target can
be looked up without arithmetic.  Addresses are file offsets unless ``--base``
says otherwise.

Command line::

    tools/m68dis.py FILE --offset 0x255B2 --length 0x200
    tools/m68dis.py FILE --refs 0x255B2 --offset 0x28 --length 0x4D2E0

``--refs`` is the other half of reading a loader: given the offset of a string
or a routine, it walks the range one word at a time and reports every
instruction whose resolved target is that address.  That is how the code that
opens ``NAME.pc`` was found, the string itself being the only fixed point.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

__all__ = [
    "Instruction",
    "decode",
    "disassemble",
    "format_line",
    "references_to",
]


CC = (
    "t", "f", "hi", "ls", "cc", "cs", "ne", "eq",
    "vc", "vs", "pl", "mi", "ge", "lt", "gt", "le",
)

SIZE_SUFFIX = {0: "b", 1: "w", 2: "l"}


class _Undecodable(Exception):
    """The word under the cursor is not a 68000 instruction we recognise."""


@dataclass(frozen=True)
class Instruction:
    """One decoded instruction, or one word of data when nothing decoded.

    ``address`` is in whatever space the caller chose -- file offsets by
    default.  ``words`` is the raw big-endian words the instruction occupies,
    so a caller can print the bytes beside the text.  ``target`` is the
    absolute address a branch, jump or PC-relative reference reaches, and is
    ``None`` for everything else.  ``known`` is ``False`` for a ``dc.w``.
    """

    address: int
    words: tuple[int, ...]
    mnemonic: str
    operands: str
    target: int | None = None
    known: bool = True

    @property
    def size(self) -> int:
        return 2 * len(self.words)

    @property
    def text(self) -> str:
        return f"{self.mnemonic} {self.operands}".rstrip()


class _Cursor:
    """Reads big-endian words and remembers which ones it consumed."""

    def __init__(self, data: bytes, pos: int, address: int,
                 end: int | None = None) -> None:
        self._data = data
        self._start = pos
        self._pos = pos
        self._address = address
        self._end = len(data) if end is None else min(end, len(data))
        self.words: list[int] = []

    def word(self) -> int:
        if self._pos + 2 > self._end:
            raise _Undecodable("ran off the end of the buffer")
        value = int.from_bytes(self._data[self._pos:self._pos + 2], "big")
        self.words.append(value)
        self._pos += 2
        return value

    @property
    def here(self) -> int:
        """The address of the next word -- what the 68000 uses as PC."""
        return self._address + (self._pos - self._start)


def _s8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def _s16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _disp(value: int) -> str:
    return f"-${-value:x}" if value < 0 else f"${value:x}"


def _imm(value: int) -> str:
    return f"#${value:x}"


# --------------------------------------------------------------------------
# Effective addresses
# --------------------------------------------------------------------------

# Which of the twelve 68000 addressing modes an operand slot may use.  Named so
# a handler can say what it means rather than repeat a set of numbers.
DATA = frozenset({"Dn", "(An)", "(An)+", "-(An)", "d(An)", "d(An,Xn)",
                  "abs.w", "abs.l", "d(PC)", "d(PC,Xn)", "#"})
ALL = DATA | {"An"}
MEMORY = DATA - {"Dn"}
ALTERABLE = ALL - {"d(PC)", "d(PC,Xn)", "#"}
DATA_ALTERABLE = DATA - {"d(PC)", "d(PC,Xn)", "#"}
MEM_ALTERABLE = MEMORY - {"d(PC)", "d(PC,Xn)", "#"}
CONTROL = {"(An)", "d(An)", "d(An,Xn)", "abs.w", "abs.l", "d(PC)", "d(PC,Xn)"}


def _ea_kind(mode: int, reg: int) -> str:
    if mode < 7:
        return ("Dn", "An", "(An)", "(An)+", "-(An)", "d(An)", "d(An,Xn)")[mode]
    return {0: "abs.w", 1: "abs.l", 2: "d(PC)", 3: "d(PC,Xn)", 4: "#"}.get(reg, "")


def _brief_index(ext: int) -> str:
    # Bit 8 selects the 68020 full extension format and bits 10-9 are its
    # scale.  A 68000 has neither and ignores the bits, so silicon would run
    # this -- but no assembler targeting a 68000 emits it, which makes a word
    # carrying it data rather than code.  Refusing is what separates the two
    # in a binary with strings and tables scattered through its code hunk.
    if ext & 0x0700:
        raise _Undecodable("68020 index extension: an assembler would not emit this")
    letter = "a" if ext & 0x8000 else "d"
    number = (ext >> 12) & 7
    width = "l" if ext & 0x0800 else "w"
    return f"{letter}{number}.{width}"


def _ea(cur: _Cursor, mode: int, reg: int, size: int, allowed: frozenset | set):
    """Decode one effective address.  Returns (text, target-or-None)."""
    kind = _ea_kind(mode, reg)
    if kind == "" or kind not in allowed:
        raise _Undecodable(f"addressing mode {mode}/{reg} not allowed here")

    if kind == "Dn":
        return f"d{reg}", None
    if kind == "An":
        return f"a{reg}", None
    if kind == "(An)":
        return f"(a{reg})", None
    if kind == "(An)+":
        return f"(a{reg})+", None
    if kind == "-(An)":
        return f"-(a{reg})", None
    if kind == "d(An)":
        return f"{_disp(_s16(cur.word()))}(a{reg})", None
    if kind == "d(An,Xn)":
        ext = cur.word()
        index = _brief_index(ext)
        return f"{_disp(_s8(ext & 0xFF))}(a{reg},{index})", None
    if kind == "abs.w":
        value = cur.word()
        return f"${value:04x}.w", _s16(value) & 0xFFFF_FFFF
    if kind == "abs.l":
        value = (cur.word() << 16) | cur.word()
        return f"${value:08x}", value
    if kind == "d(PC)":
        pc = cur.here
        target = pc + _s16(cur.word())
        return f"${target:x}(pc)", target
    if kind == "d(PC,Xn)":
        pc = cur.here
        ext = cur.word()
        index = _brief_index(ext)
        target = pc + _s8(ext & 0xFF)
        return f"${target:x}(pc,{index})", target
    # Immediate.
    if size == 0:
        return _imm(cur.word() & 0xFF), None
    if size == 1:
        return _imm(cur.word()), None
    if size == 2:
        return _imm((cur.word() << 16) | cur.word()), None
    raise _Undecodable("immediate of no size")


def _reglist(mask: int, predecrement: bool) -> str:
    """Render a MOVEM mask.

    The mask is read the other way round for ``-(An)``: bit 0 is A7 there and
    D0 everywhere else.  Getting that backwards is the classic MOVEM bug, and
    it is silent -- the register names simply come out wrong.
    """
    names = [f"d{n}" for n in range(8)] + [f"a{n}" for n in range(8)]
    if predecrement:
        names.reverse()
    present = [names[bit] for bit in range(16) if mask & (1 << bit)]
    if not present:
        return ""

    order = {name: index for index, name in enumerate(
        [f"d{n}" for n in range(8)] + [f"a{n}" for n in range(8)])}
    present.sort(key=lambda name: order[name])

    groups: list[str] = []
    run: list[str] = []
    for name in present:
        if run and order[name] == order[run[-1]] + 1 and name[0] == run[-1][0]:
            run.append(name)
        else:
            if run:
                groups.append(run)
            run = [name]
    groups.append(run)

    parts = []
    for run in groups:
        parts.append(run[0] if len(run) == 1 else f"{run[0]}-{run[-1]}")
    return "/".join(parts)


# --------------------------------------------------------------------------
# The opcode map
# --------------------------------------------------------------------------


# BTST may read anything a data operand can be read from, but not an
# immediate: there is nothing to test a bit of.
BTST_DEST = DATA - {"#"}

# ORI/ANDI/EORI to the condition codes and to the status register are six
# fixed encodings, and they sit in the slot the general immediate decoder
# would otherwise read as "destination is an immediate".
_TO_CONDITION_CODES = {
    0x003C: ("ori", "ccr", 0),
    0x007C: ("ori", "sr", 1),
    0x023C: ("andi", "ccr", 0),
    0x027C: ("andi", "sr", 1),
    0x0A3C: ("eori", "ccr", 0),
    0x0A7C: ("eori", "sr", 1),
}


def _line0(op: int, cur: _Cursor):
    mode, reg = (op >> 3) & 7, op & 7

    if op in _TO_CONDITION_CODES:
        name, register, size = _TO_CONDITION_CODES[op]
        word = cur.word()
        value = word & 0xFF if size == 0 else word
        return name, f"{_imm(value)},{register}", None

    if op & 0x0100:
        dn = (op >> 9) & 7
        if mode == 1:                                     # MOVEP
            disp = _disp(_s16(cur.word()))
            opmode = (op >> 6) & 3
            suffix = "w" if opmode in (0, 2) else "l"
            if opmode < 2:
                return f"movep.{suffix}", f"{disp}(a{reg}),d{dn}", None
            return f"movep.{suffix}", f"d{dn},{disp}(a{reg})", None
        name = ("btst", "bchg", "bclr", "bset")[(op >> 6) & 3]
        allowed = BTST_DEST if name == "btst" else DATA_ALTERABLE
        text, _ = _ea(cur, mode, reg, 2, allowed)
        return name, f"d{dn},{text}", None

    kind = (op >> 9) & 7
    size = (op >> 6) & 3

    if kind == 4:                                          # static bit ops
        name = ("btst", "bchg", "bclr", "bset")[size]
        bit = cur.word()
        allowed = BTST_DEST if name == "btst" else DATA_ALTERABLE
        text, _ = _ea(cur, mode, reg, 2, allowed)
        return name, f"{_imm(bit & 0xFF)},{text}", None

    names = {0: "ori", 1: "andi", 2: "subi", 3: "addi", 5: "eori", 6: "cmpi"}
    if kind not in names or size == 3:
        raise _Undecodable("no such immediate group")
    name = names[kind]
    value, _ = _ea(cur, 7, 4, size, {"#"})
    text, _ = _ea(cur, mode, reg, size, DATA_ALTERABLE)
    return f"{name}.{SIZE_SUFFIX[size]}", f"{value},{text}", None


def _move(op: int, cur: _Cursor):
    size = {1: 0, 3: 1, 2: 2}.get((op >> 12) & 3)
    if size is None:
        raise _Undecodable("move with no size")
    src_mode, src_reg = (op >> 3) & 7, op & 7
    dst_mode, dst_reg = (op >> 6) & 7, (op >> 9) & 7
    source, _ = _ea(cur, src_mode, src_reg, size, ALL if size else DATA)
    if dst_mode == 1:
        if size == 0:
            raise _Undecodable("movea has no byte size")
        dest, _ = _ea(cur, dst_mode, dst_reg, size, ALTERABLE)
        return f"movea.{SIZE_SUFFIX[size]}", f"{source},{dest}", None
    dest, _ = _ea(cur, dst_mode, dst_reg, size, DATA_ALTERABLE)
    return f"move.{SIZE_SUFFIX[size]}", f"{source},{dest}", None


def _line4(op: int, cur: _Cursor):
    mode, reg = (op >> 3) & 7, op & 7
    size = (op >> 6) & 3

    if op == 0x4AFC:
        return "illegal", "", None
    if op == 0x4E70:
        return "reset", "", None
    if op == 0x4E71:
        return "nop", "", None
    if op == 0x4E72:
        return "stop", _imm(cur.word()), None
    if op == 0x4E73:
        return "rte", "", None
    if op == 0x4E75:
        return "rts", "", None
    if op == 0x4E76:
        return "trapv", "", None
    if op == 0x4E77:
        return "rtr", "", None
    if 0x4E40 <= op <= 0x4E4F:
        return "trap", _imm(op & 0xF), None
    if 0x4E50 <= op <= 0x4E57:
        return "link", f"a{op & 7},#{_disp(_s16(cur.word()))}", None
    if 0x4E58 <= op <= 0x4E5F:
        return "unlk", f"a{op & 7}", None
    if 0x4E60 <= op <= 0x4E67:
        return "move.l", f"a{op & 7},usp", None
    if 0x4E68 <= op <= 0x4E6F:
        return "move.l", f"usp,a{op & 7}", None
    if 0x4E80 <= op <= 0x4EBF:
        text, target = _ea(cur, mode, reg, 2, CONTROL)
        return "jsr", text, target
    if 0x4EC0 <= op <= 0x4EFF:
        text, target = _ea(cur, mode, reg, 2, CONTROL)
        return "jmp", text, target

    top = (op >> 9) & 7
    if (op & 0x01C0) == 0x01C0:                            # LEA
        text, target = _ea(cur, mode, reg, 2, CONTROL)
        return "lea", f"{text},a{top}", target
    if (op & 0x01C0) == 0x0180:                            # CHK.W
        text, _ = _ea(cur, mode, reg, 1, DATA)
        return "chk.w", f"{text},d{top}", None

    if (op & 0x0800) == 0 and size == 3:                   # MOVE from/to SR/CCR
        if top == 0:
            text, _ = _ea(cur, mode, reg, 1, DATA_ALTERABLE)
            return "move.w", f"sr,{text}", None
        if top == 2:
            text, _ = _ea(cur, mode, reg, 1, DATA)
            return "move.w", f"{text},ccr", None
        if top == 3:
            text, _ = _ea(cur, mode, reg, 1, DATA)
            return "move.w", f"{text},sr", None
        raise _Undecodable("no such move to/from a control register")

    if (op & 0xFFB8) == 0x4880:                            # EXT
        suffix = "w" if (op & 0x0040) == 0 else "l"
        return f"ext.{suffix}", f"d{reg}", None
    if (op & 0xFFF8) == 0x4840:
        return "swap", f"d{reg}", None
    if (op & 0xFFC0) == 0x4840:                            # PEA
        text, target = _ea(cur, mode, reg, 2, CONTROL)
        return "pea", text, target
    if (op & 0xFFC0) == 0x4800:
        text, _ = _ea(cur, mode, reg, 0, DATA_ALTERABLE)
        return "nbcd", text, None
    if (op & 0xFFC0) == 0x4AC0:
        text, _ = _ea(cur, mode, reg, 0, DATA_ALTERABLE)
        return "tas", text, None

    if (op & 0xFB80) == 0x4880:                            # MOVEM
        to_memory = (op & 0x0400) == 0
        suffix = "w" if (op & 0x0040) == 0 else "l"
        mask = cur.word()
        allowed = (MEM_ALTERABLE - {"(An)+"}) if to_memory else (CONTROL | {"(An)+"})
        text, _ = _ea(cur, mode, reg, 1 if suffix == "w" else 2, allowed)
        registers = _reglist(mask, predecrement=(mode == 4))
        if to_memory:
            return f"movem.{suffix}", f"{registers},{text}", None
        return f"movem.{suffix}", f"{text},{registers}", None

    if size == 3:
        raise _Undecodable("no size-3 encoding in this group")
    # NEGX/CLR/NEG/NOT/TST are bits 11-8, not 11-9: bit 8 set is CHK or LEA
    # (both handled above) or nothing at all.  Reading only bits 11-9 turns
    # every odd value into whichever of these happens to sit beside it, which
    # is how `neg.w (a2)` was invented out of the letters `ER` in a string.
    if op & 0x0100:
        raise _Undecodable("bit 8 set: not a unary operation on a 68000")
    unary = {0: "negx", 1: "clr", 2: "neg", 3: "not", 5: "tst"}
    if top not in unary:
        raise _Undecodable("no such unary operation")
    name = unary[top]
    text, _ = _ea(cur, mode, reg, size, DATA_ALTERABLE)
    return f"{name}.{SIZE_SUFFIX[size]}", text, None


def _line5(op: int, cur: _Cursor):
    mode, reg = (op >> 3) & 7, op & 7
    size = (op >> 6) & 3
    condition = (op >> 8) & 0xF

    if size == 3:
        if mode == 1:                                      # DBcc
            pc = cur.here
            target = pc + _s16(cur.word())
            name = {0: "dbt", 1: "dbra"}.get(condition, f"db{CC[condition]}")
            return name, f"d{reg},${target:x}", target
        name = {0: "st", 1: "sf"}.get(condition, f"s{CC[condition]}")
        text, _ = _ea(cur, mode, reg, 0, DATA_ALTERABLE)
        return name, text, None

    count = (op >> 9) & 7 or 8
    name = "subq" if op & 0x0100 else "addq"
    if mode == 1 and size == 0:
        raise _Undecodable("addq/subq to an address register has no byte size")
    text, _ = _ea(cur, mode, reg, size, ALTERABLE)
    return f"{name}.{SIZE_SUFFIX[size]}", f"{_imm(count)},{text}", None


def _line6(op: int, cur: _Cursor):
    condition = (op >> 8) & 0xF
    displacement = op & 0xFF
    pc = cur.here
    if displacement == 0:
        offset = _s16(cur.word())
        suffix = ".w"
    else:
        offset = _s8(displacement)
        suffix = ".b"
    target = pc + offset
    if target & 1:
        # A legal encoding that faults when it runs: the 68000 takes the
        # branch and then address-errors on the odd PC.  No assembler emits
        # one, so in practice this is two letters of a string that happen to
        # start with $6x -- which is most of what line 6 finds in data.
        raise _Undecodable("odd branch target: an assembler would not emit this")
    name = {0: "bra", 1: "bsr"}.get(condition, f"b{CC[condition]}")
    return name + suffix, f"${target:x}", target


def _line7(op: int, cur: _Cursor):
    if op & 0x0100:
        raise _Undecodable("moveq with bit 8 set")
    return "moveq", f"{_imm(op & 0xFF)},d{(op >> 9) & 7}", None


def _line8_or_c(op: int, cur: _Cursor, is_and: bool):
    mode, reg = (op >> 3) & 7, op & 7
    dn = (op >> 9) & 7
    opmode = (op >> 6) & 7
    name = "and" if is_and else "or"

    if opmode == 3:
        text, _ = _ea(cur, mode, reg, 1, DATA)
        return ("mulu.w" if is_and else "divu.w"), f"{text},d{dn}", None
    if opmode == 7:
        text, _ = _ea(cur, mode, reg, 1, DATA)
        return ("muls.w" if is_and else "divs.w"), f"{text},d{dn}", None

    if opmode in (4, 5, 6) and mode in (0, 1):
        if opmode == 4:
            bcd = "abcd" if is_and else "sbcd"
            if mode == 0:
                return bcd, f"d{reg},d{dn}", None
            return bcd, f"-(a{reg}),-(a{dn})", None
        if is_and and opmode == 5 and mode == 0:
            return "exg", f"d{dn},d{reg}", None
        if is_and and opmode == 5 and mode == 1:
            return "exg", f"a{dn},a{reg}", None
        if is_and and opmode == 6 and mode == 1:
            return "exg", f"d{dn},a{reg}", None
        raise _Undecodable("no such register-to-register encoding")

    size = opmode & 3
    if size == 3:
        raise _Undecodable("no size-3 encoding")
    if opmode < 3:
        text, _ = _ea(cur, mode, reg, size, DATA)
        return f"{name}.{SIZE_SUFFIX[size]}", f"{text},d{dn}", None
    text, _ = _ea(cur, mode, reg, size, MEM_ALTERABLE)
    return f"{name}.{SIZE_SUFFIX[size]}", f"d{dn},{text}", None


def _line9_or_d(op: int, cur: _Cursor, is_add: bool):
    mode, reg = (op >> 3) & 7, op & 7
    dn = (op >> 9) & 7
    opmode = (op >> 6) & 7
    name = "add" if is_add else "sub"

    if opmode in (3, 7):
        size = 1 if opmode == 3 else 2
        text, _ = _ea(cur, mode, reg, size, ALL)
        return f"{name}a.{SIZE_SUFFIX[size]}", f"{text},a{dn}", None

    size = opmode & 3
    if opmode in (4, 5, 6) and mode in (0, 1):
        suffix = SIZE_SUFFIX[size]
        if mode == 0:
            return f"{name}x.{suffix}", f"d{reg},d{dn}", None
        return f"{name}x.{suffix}", f"-(a{reg}),-(a{dn})", None
    if opmode < 3:
        text, _ = _ea(cur, mode, reg, size, ALL if size else DATA)
        return f"{name}.{SIZE_SUFFIX[size]}", f"{text},d{dn}", None
    text, _ = _ea(cur, mode, reg, size, MEM_ALTERABLE)
    return f"{name}.{SIZE_SUFFIX[size]}", f"d{dn},{text}", None


def _lineb(op: int, cur: _Cursor):
    mode, reg = (op >> 3) & 7, op & 7
    dn = (op >> 9) & 7
    opmode = (op >> 6) & 7

    if opmode in (3, 7):
        size = 1 if opmode == 3 else 2
        text, _ = _ea(cur, mode, reg, size, ALL)
        return f"cmpa.{SIZE_SUFFIX[size]}", f"{text},a{dn}", None
    size = opmode & 3
    if opmode < 3:
        text, _ = _ea(cur, mode, reg, size, ALL if size else DATA)
        return f"cmp.{SIZE_SUFFIX[size]}", f"{text},d{dn}", None
    if mode == 1:
        return f"cmpm.{SIZE_SUFFIX[size]}", f"(a{reg})+,(a{dn})+", None
    text, _ = _ea(cur, mode, reg, size, DATA_ALTERABLE)
    return f"eor.{SIZE_SUFFIX[size]}", f"d{dn},{text}", None


def _linee(op: int, cur: _Cursor):
    kinds = ("as", "ls", "rox", "ro")
    direction = "l" if op & 0x0100 else "r"
    size = (op >> 6) & 3
    if size == 3:                                          # memory, one bit
        if op & 0x0800:
            raise _Undecodable("no such memory shift")
        name = kinds[(op >> 9) & 3] + direction
        text, _ = _ea(cur, (op >> 3) & 7, op & 7, 1, MEM_ALTERABLE)
        return f"{name}.w", text, None
    name = kinds[(op >> 3) & 3] + direction
    suffix = SIZE_SUFFIX[size]
    count = (op >> 9) & 7
    if op & 0x0020:
        return f"{name}.{suffix}", f"d{count},d{op & 7}", None
    return f"{name}.{suffix}", f"{_imm(count or 8)},d{op & 7}", None


def decode(data: bytes, offset: int, address: int | None = None,
           end: int | None = None) -> Instruction:
    """Decode the one instruction at ``offset``.

    ``address`` is what to call that offset when printing; it defaults to the
    offset itself, so the addresses in the output are file offsets.  ``end``
    bounds how far the instruction may reach: an instruction whose extension
    words would cross it comes back as ``dc.w`` rather than reading past it,
    which is what keeps a window ending one instruction short of a hunk
    boundary from disassembling the relocation table that follows.  An
    encoding this does not recognise comes back as a one-word ``dc.w`` with
    ``known`` false -- never as a guess.
    """
    if address is None:
        address = offset
    # `end` bounds this the same way `len(data)` does, so a window with no
    # whole word left in it is refused here rather than inside `_Cursor`.
    # `decode` is public and `_Undecodable` is not: without this, a caller
    # passing a narrow `end` got a private exception out of the one function
    # whose contract is that an undecodable word comes back as `dc.w` (#148).
    limit = len(data) if end is None else min(end, len(data))
    if offset + 2 > limit:
        raise ValueError("offset is past the end of the buffer")

    cur = _Cursor(data, offset, address, end)
    op = cur.word()
    line = op >> 12

    try:
        if line == 0:
            mnemonic, operands, target = _line0(op, cur)
        elif line in (1, 2, 3):
            mnemonic, operands, target = _move(op, cur)
        elif line == 4:
            mnemonic, operands, target = _line4(op, cur)
        elif line == 5:
            mnemonic, operands, target = _line5(op, cur)
        elif line == 6:
            mnemonic, operands, target = _line6(op, cur)
        elif line == 7:
            mnemonic, operands, target = _line7(op, cur)
        elif line in (8, 12):
            mnemonic, operands, target = _line8_or_c(op, cur, is_and=(line == 12))
        elif line in (9, 13):
            mnemonic, operands, target = _line9_or_d(op, cur, is_add=(line == 13))
        elif line == 11:
            mnemonic, operands, target = _lineb(op, cur)
        elif line == 14:
            mnemonic, operands, target = _linee(op, cur)
        else:
            # Line A and line F are the two trap lines.  A 68000 has no
            # instructions there, so naming one would be inventing it.
            raise _Undecodable("line A/F")
    except _Undecodable:
        return Instruction(address, (op,), "dc.w", f"${op:04x}", None, False)

    return Instruction(address, tuple(cur.words), mnemonic, operands, target)


def disassemble(data: bytes, offset: int, length: int,
                base: int = 0) -> list[Instruction]:
    """Decode ``length`` bytes from ``offset``, one instruction at a time.

    Nothing outside the window is read.  An instruction that would run past
    the end of it prints as ``dc.w`` instead, because the alternative is a
    window that silently disassembles whatever the caller did not ask for --
    a relocation table, the next hunk, another file's bytes.
    """
    out: list[Instruction] = []
    end = min(offset + length, len(data))
    pos = offset
    while pos + 2 <= end:
        item = decode(data, pos, base + pos, end)
        out.append(item)
        pos += item.size
    return out


def format_line(item: Instruction) -> str:
    raw = " ".join(f"{word:04x}" for word in item.words)
    return f"{item.address:08x}  {raw:<24}{item.mnemonic:<10}{item.operands}"


def references_to(data: bytes, target: int, offset: int, length: int,
                  base: int = 0) -> list[Instruction]:
    """Every instruction in the range whose resolved target is ``target``.

    Walks word by word rather than instruction by instruction, because the
    point is to find code whose entry point is unknown: an instruction stream
    read from the wrong parity is a different stream, and a reference can hide
    in either.  Duplicates and false positives are the caller's to judge.
    """
    hits: list[Instruction] = []
    end = min(offset + length, len(data))
    for pos in range(offset, end - 1, 2):
        item = decode(data, pos, base + pos, end)
        if item.known and item.target == target:
            hits.append(item)
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("file")
    parser.add_argument("--offset", default="0",
                        help="file offset to start at (0x... accepted)")
    parser.add_argument("--length", default="0x100",
                        help="how many bytes to cover")
    parser.add_argument("--base", default="0",
                        help="address of file offset 0; addresses are file "
                             "offsets when this is 0, which is the default")
    parser.add_argument("--refs", default=None,
                        help="instead of disassembling, report every "
                             "instruction in the range whose target is this "
                             "address")
    args = parser.parse_args(argv)

    offset = int(args.offset, 0)
    length = int(args.length, 0)
    base = int(args.base, 0)
    with open(args.file, "rb") as handle:
        data = handle.read()

    if args.refs is not None:
        for item in references_to(data, int(args.refs, 0), offset, length, base):
            print(format_line(item))
        return 0

    for item in disassemble(data, offset, length, base):
        print(format_line(item))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Read each Amiga title's backstab multiplier from its own executable.

    tools/amiga/amigabackstab.py
    tools/amiga/amigabackstab.py --title curse-of-the-azure-bonds
    tools/amiga/amigabackstab.py --check

The multiplier arithmetic is found by its instruction structure rather than by
the addresses printed, and everything else -- the predicate it is gated on,
the record bytes it reads, the clamp where there is one, and the damage byte
it multiplies -- is read out from there. The executables come from the
registry's ``amiga`` disks and are never written. Needs ``capstone``.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

import capstone  # noqa: E402

from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools.amiga import amigasaves  # noqa: E402

THIEF_SLOT = 6


@dataclasses.dataclass(frozen=True)
class Title:
    """One Amiga title, where its executable is, and what its path looks like.

    `form` is `divide` where the engine divides the thief level without
    subtracting first, `inline` where it builds the effective level from both
    level arrays in the caller, and `helper` where it calls one shared
    class-level routine for it.
    """

    key: str
    title: str
    executable_path: str
    form: str
    current_thief: int | None
    former_thief: int | None
    clamp: int | None


TITLES = {
    title.key: title
    for title in (
        Title("pool-of-radiance", "Pool of Radiance", "/program",
              "divide", 0x09E, None, None),
        Title("curse-of-the-azure-bonds", "Curse of the Azure Bonds",
              "/Curse", "inline", 0x110, 0x118, None),
        Title("secret-of-the-silver-blades", "Secret of the Silver Blades",
              "/Secret", "inline", 0x0B2, 0x0B9, None),
        Title("pools-of-darkness", "Pools of Darkness",
              "/Pools of Darkness", "helper", None, None, 5),
    )
}

#: `tst.l Dn / bpl / addq.l #3 / asr.l #2 / addq.l #2`: a signed divide by
#: four with no subtraction before it, which is Pool of Radiance's whole sum.
_DIVIDE_TAIL = (0x4A80, 0x6A02, 0x5680, 0xE480, 0x5480)

#: `subq.w #1 / ext.l / divs.w #4 / addq.w #2`, the later titles' arithmetic.
_SUBTRACT_TAIL = (0x5340, 0x48C0, 0x81FC, None, 0x5440)

#: `move.w #6, -(a7)`: the class index Pools of Darkness asks its helper for.
_THIEF_INDEX = bytes((0x3F, 0x3C, 0x00, THIEF_SLOT))


def builds(title: Title) -> dict[bytes, list[str]]:
    """Every build of this title's executable on the player's disks."""
    found: dict[bytes, list[str]] = {}
    name = title.executable_path.rsplit("/", 1)[-1]
    for label, image in amigasaves.images():
        try:
            disk = AmigaDisk(image)
            paths = [path for path, _entry in disk.walk()
                     if path.rsplit("/", 1)[-1] == name]
        except (AmigaDiskError, ValueError):
            continue
        for path in paths:
            try:
                found.setdefault(disk.read_file(path), []).append(label)
            except (AmigaDiskError, ValueError):
                continue
    return found


def executable(title: Title) -> bytes | None:
    """The build of this title's executable the most disk images agree on.

    The images are not all the same file -- a cracked rip and a patched build
    sit beside the original on this machine -- so taking the first one found
    would make a run against an odd rip look like a finding about the game.
    """
    found = builds(title)
    if not found:
        return None
    return max(found, key=lambda raw: (len(found[raw]), len(raw)))


def _word(raw: bytes, at: int) -> int:
    return struct.unpack_from(">H", raw, at)[0]


def _tail(raw: bytes, title: Title) -> tuple[int, int]:
    """The one multiplier arithmetic run, as `(file offset, register)`."""
    pattern = _DIVIDE_TAIL if title.form == "divide" else _SUBTRACT_TAIL
    hits = []
    for at in range(0, len(raw) - 2 * len(pattern), 2):
        for reg in range(8):
            want = [None if word is None else word for word in pattern]
            if pattern is _DIVIDE_TAIL:
                want = [w if w == 0x6A02 else w | reg for w in want]
            else:
                want = [pattern[0] | reg, pattern[1] | reg,
                        pattern[2] | (reg << 9), 0x0004, pattern[4] | reg]
            if all(_word(raw, at + 2 * i) == w for i, w in enumerate(want)):
                hits.append((at, reg))
    if len(hits) != 1:
        raise ValueError(
            f"{title.title}: expected one multiplier arithmetic run, "
            f"found {len(hits)}")
    return hits[0]


def _record_reads(raw: bytes, start: int, end: int) -> list[int]:
    """Every `move.b d16(An), Dn` displacement between two file offsets."""
    out = []
    for at in range(start, end, 2):
        word = _word(raw, at)
        if (word & 0xF1F8) == 0x1028:          # move.b d16(An), Dn
            out.append(_word(raw, at + 2))
    return out


def _call_target(raw: bytes, at: int) -> int | None:
    """Where a `bsr.w` or a `jsr d16(pc)` at `at` goes."""
    if _word(raw, at) not in (0x6100, 0x4EBA):
        return None
    return at + 2 + struct.unpack_from(">h", raw, at + 2)[0]


def _predicate_call(raw: bytes, tail: int, title: Title) -> tuple[int, int]:
    """The gate call before the arithmetic, as `(call site, target)`.

    The call is the last one before the arithmetic whose result is tested and
    branched on, which is what makes it the gate rather than a neighbour.
    """
    for at in range(tail - 2, max(0, tail - 0x40), -2):
        target = _call_target(raw, at)
        if target is None:
            continue
        window = raw[at + 4:at + 0x0E]
        if b"\x4a\x00" in window and (b"\x67" in window[2:] or
                                      b"\x67\x00" in window):
            return at, target
        raise ValueError(
            f"{title.title}: the call before the arithmetic is not tested")
    raise ValueError(f"{title.title}: no predicate call before the arithmetic")


def _callers(raw: bytes, target: int) -> list[int]:
    return [at for at in range(0, len(raw) - 4, 2)
            if _call_target(raw, at) == target]


def _damage(raw: bytes, tail: int, reg: int, title: Title) -> str:
    """The place the multiplied damage comes from and goes back to."""
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    instructions = list(md.disasm(raw[tail:tail + 0x30], tail))
    multiply = next((i for i in instructions
                     if i.mnemonic.startswith("muls")
                     or (title.form == "divide"
                         and i.mnemonic in ("jsr", "bsr.w"))), None)
    if multiply is None:
        raise ValueError(f"{title.title}: the multiplier is never applied")
    if multiply.mnemonic in ("jsr", "bsr.w"):
        # Pool of Radiance has no `muls`: it passes the factor and the damage
        # to a multiply routine, the way its C64 port calls `LIBRARY`'s. The
        # damage is whatever went into the register the factor is not in.
        carried = [i for i in instructions
                   if i.address < multiply.address
                   and i.mnemonic.startswith("move")
                   and i.op_str.endswith(("d0", "d1", "d2", "d3"))
                   and not i.op_str.endswith(f"d{reg}")
                   and not i.op_str.startswith("#")]
        if not carried:
            raise ValueError(
                f"{title.title}: the multiply routine is passed no damage")
        source, product = carried[-1].op_str.rsplit(",", 1)[0].strip(), "d0"
    else:
        source, product = (part.strip() for part in multiply.op_str.split(","))
    if source.startswith("d") and len(source) == 2:
        loads = [i for i in instructions
                 if i.address < multiply.address
                 and i.mnemonic.startswith("move")
                 and i.op_str.endswith(f", {source}")
                 and not i.op_str.startswith("#")]
        if not loads:
            raise ValueError(
                f"{title.title}: the multiplied damage is loaded from nowhere")
        source = loads[-1].op_str.rsplit(",", 1)[0].strip()
    stores = [i for i in instructions
              if i.address > multiply.address
              and i.mnemonic.startswith("move")
              and i.op_str.startswith(f"{product},")]
    if not stores or stores[0].op_str.split(",", 1)[1].strip() != source:
        raise ValueError(
            f"{title.title}: the multiplied damage is not stored back")
    carrying = {f"d{reg}"}
    for instruction in instructions:
        if instruction.address >= multiply.address:
            break
        if not instruction.mnemonic.startswith("move"):
            continue
        came, went = (part.strip() for part in instruction.op_str.split(","))
        if came in carrying and went.startswith("d") and len(went) == 2:
            carrying.add(went)
    if not carrying & set(multiply.op_str.replace(",", " ").split()) \
            and product not in carrying:
        raise ValueError(
            f"{title.title}: the applied factor is not the computed one")
    return source


def inspect(raw: bytes, title: Title) -> dict:
    """Return instruction evidence for one Amiga title's backstab path."""
    tail, reg = _tail(raw, title)
    call, predicate = _predicate_call(raw, tail, title)
    reads = _record_reads(raw, call, tail)

    if title.form == "helper":
        if _THIEF_INDEX not in raw[call:tail]:
            raise ValueError(
                f"{title.title}: the class-level helper is not asked for the "
                f"thief")
        expected: list[int] = []
    else:
        expected = [slot for slot in (title.former_thief, title.current_thief)
                    if slot is not None]
        if reads != expected:
            raise ValueError(
                f"{title.title}: the arithmetic reads "
                f"{[hex(read) for read in reads]}, not "
                f"{[hex(slot) for slot in expected]}")

    predicate_window = raw[predicate:predicate + 0x80]
    for slot in expected:
        if struct.pack(">H", slot) not in predicate_window:
            raise ValueError(
                f"{title.title}: the predicate does not name record "
                f"0x{slot:03X}")
    if title.form == "helper" and _THIEF_INDEX not in predicate_window:
        raise ValueError(
            f"{title.title}: the predicate does not ask for the thief level")

    clamp = None
    after = raw[tail + 2 * 5:tail + 2 * 5 + 0x10]
    for at in range(0, len(after) - 4, 2):
        if (_word(after, at) & 0xFFF8) == 0x0C00:      # cmpi.b #imm, Dn
            clamp = _word(after, at + 2)
            break
    if clamp != title.clamp:
        raise ValueError(
            f"{title.title}: the clamp is {clamp}, not {title.clamp}")

    damage = _damage(raw, tail, reg, title)
    subtract = title.form != "divide"
    level = ("the shared class-level routine for class 6" if
             title.form == "helper" else
             "class_levels[thief] + former_class_levels[thief] * regained"
             if title.former_thief is not None else "class_levels[thief]")
    multiplier = ("((effective thief level - 1) // 4) + 2" if subtract
                  else "(effective thief level // 4) + 2")
    if title.clamp is not None:
        multiplier = f"min({multiplier}, {title.clamp})"
    return {
        "title": title.key,
        "form": title.form,
        "formula": tail,
        "register": reg,
        "predicate": predicate,
        "predicate_call": call,
        "predicate_callers": _callers(raw, predicate),
        "record_reads": reads,
        "current_thief": title.current_thief,
        "former_thief": title.former_thief,
        "clamp": clamp,
        "damage": damage,
        "effective_level": level,
        "multiplier": multiplier,
    }


def inspect_title(title: Title) -> dict:
    """Read this title's executable off the player's disks and inspect it."""
    raw = executable(title)
    if raw is None:
        raise SystemExit(f"No Amiga {title.title} executable on any disk here.")
    return inspect(raw, title)


def _print(finding: dict) -> None:
    print(finding["title"])
    print(f"  Effective     {finding['effective_level']}")
    print(f"  Multiplier    0x{finding['formula']:X}: "
          f"{finding['multiplier']}")
    print(f"  Applied       to {finding['damage']}")
    print(f"  Predicate     0x{finding['predicate']:X}, called from "
          + ", ".join(f"0x{at:X}" for at in finding["predicate_callers"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", choices=sorted(TITLES), action="append",
                        help="inspect one title; default is every title")
    parser.add_argument("--check", action="store_true",
                        help="exit nonzero if a reading is missing")
    args = parser.parse_args(argv)
    failed = False
    for key in args.title or list(TITLES):
        try:
            finding = inspect_title(TITLES[key])
        except (OSError, SystemExit, ValueError) as exc:
            print(f"{key}: {exc}")
            failed = True
            continue
        _print(finding)
    return 1 if args.check and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

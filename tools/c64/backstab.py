#!/usr/bin/env python3
"""Read every C64 title's backstab path from its own overlays.

    tools/c64/backstab.py
    tools/c64/backstab.py --title secret-of-the-silver-blades
    tools/c64/backstab.py --title pool-of-radiance --disks /path/to/disks

One overlay supplies the thief-level gate and the multiplier arithmetic,
another copies the result and applies it to rolled damage, a third adjusts the
number needed to hit, the byte multiply lives in the title's library overlay,
and `GEN` restores a dual-classed character's old level in the three titles
that have such a path at all. The files are read from the player's C64 disks
and never written.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import c64_port  # noqa: E402
from tools.c64 import coldread  # noqa: E402

GEN_BASE = 0x0800

LEVEL = 0x0A0
DUAL_CLASS_SLOT = 0x0B9
DUAL_CLASS_LEVEL = 0x0BA
CLASS_LEVELS = 0x0C9
THIEF_SLOT = 2
LEVEL_THIEF = CLASS_LEVELS + THIEF_SLOT
CLASS_BITS = 0x0EB
CLASS_MASKS = bytes((0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80))

#: Absolute-addressing opcodes named in the census of the multiplier byte.
OPCODES = {0xAD: "LDA", 0xAE: "LDX", 0xAC: "LDY", 0x8D: "STA", 0x8E: "STX",
           0x8C: "STY", 0xCD: "CMP", 0xEE: "INC", 0xCE: "DEC", 0x0D: "ORA",
           0x2D: "AND"}


@dataclasses.dataclass(frozen=True)
class Title:
    """One C64 title, the overlays its backstab path lives in, and its cap.

    Each overlay's base is the address `LINKER` gives it, which is not what its
    PRG header claims. `library` is `None` for a title whose library overlay
    has no ASCII directory entry: it is then found by the multiply routine.
    """

    game: c64_port.C64Container
    formula: bytes
    formula_base: int
    attack: bytes
    attack_base: int
    to_hit: bytes
    to_hit_base: int
    library: bytes | None
    cap: int | None


TITLES = {
    title.game.key: title
    for title in (
        Title(c64_port.POOL_OF_RADIANCE, b"SQRPACI01", 0x0400,
              b"SQRPACI01", 0x0400, b"COMBAT", 0x0800, b"LIBRARY", None),
        Title(c64_port.CURSE_OF_THE_AZURE_BONDS, b"COMBAT2", 0xE000,
              b"ECL64", 0x8000, b"ECL64", 0x8000, b"LIBRARY", None),
        Title(c64_port.SECRET_OF_THE_SILVER_BLADES, b"COMBAT2", 0xE000,
              b"ECL64", 0x8000, b"ECL64", 0x8000, b"LIBRARY", 14),
        Title(c64_port.GATEWAY_TO_THE_SAVAGE_FRONTIER, b"COMBAT2", 0xE000,
              b"ECL64", 0x8000, b"ECL64", 0x8000, b"LIBRARY", None),
        Title(c64_port.CHAMPIONS_OF_KRYNN, b"COMBAT2", 0xE000,
              b"ECL64", 0x8000, b"ECL64", 0x8000, b"LIBRARY", None),
        Title(c64_port.DEATH_KNIGHTS_OF_KRYNN, b"COMBAT2", 0xE000,
              b"CODE03", 0x8000, b"CODE03", 0x8000, None, 14),
    )
}

#: `LIBRARY`'s eight-bit multiply: the product's high byte comes back in X.
_MULTIPLY = bytes.fromhex(
    "85 ab 86 4b a9 00 85 4c a2 07 46 ab 90 03 18 65 4b 6a 66 4c ca 10 f3 "
    "85 4d aa a5 4c 18 60"
)

#: `CPX #$00 / BEQ +2 / LDA #$F0`: the two titles that refuse to let a
#: multiplied damage roll wrap past a byte store 240 instead.
_CLAMP = bytes.fromhex("e0 00 f0 02 a9 f0")
CLAMP_DAMAGE = 0xF0


def _u16(value: int) -> bytes:
    return struct.pack("<H", value)


def _one(body: bytes, pattern: bytes, what: str) -> int:
    hits = []
    at = body.find(pattern)
    while at >= 0:
        hits.append(at)
        at = body.find(pattern, at + 1)
    if len(hits) != 1:
        raise ValueError(
            f"{what}: expected one instruction signature, found {len(hits)}")
    return hits[0]


def _all_wild(body: bytes, pattern: tuple[int | None, ...]) -> list[int]:
    return [at for at in range(len(body) - len(pattern) + 1)
            if all(want is None or body[at + i] == want
                   for i, want in enumerate(pattern))]


def _one_wild(body: bytes, pattern: tuple[int | None, ...], what: str) -> int:
    hits = _all_wild(body, pattern)
    if len(hits) != 1:
        raise ValueError(
            f"{what}: expected one instruction signature, found {len(hits)}")
    return hits[0]


def _branch_target(body: bytes, at: int) -> int:
    displacement = struct.unpack("b", body[at + 1:at + 2])[0]
    return at + 2 + displacement


def _formula_pattern(title: Title, record: int) -> tuple[int | None, ...]:
    gate = (0xAE, (record + LEVEL_THIEF) & 0xFF,
            (record + LEVEL_THIEF) >> 8, 0xF0, None)
    cap = () if title.cap is None else (
        0xE0, title.cap, 0x90, 0x02, 0xA2, title.cap,
    )
    return gate + cap + (0xCA, 0x8A, 0x4A, 0x4A, 0xAA, 0xE8, 0xE8, 0x86, 0xB0)


def _references(overlays: dict[str, tuple[bytes, int]], address: int
                ) -> list[tuple[str, int, str]]:
    """Every absolute instruction in the loaded overlays naming `address`."""
    want = bytes((address & 0xFF, address >> 8))
    out = []
    for name, (body, base) in overlays.items():
        at = body.find(want)
        while at >= 0:
            if at and body[at - 1] in OPCODES:
                out.append((name, base + at - 1, OPCODES[body[at - 1]]))
            at = body.find(want, at + 1)
    return sorted(set(out), key=lambda row: (row[0], row[1]))


def _regain(gen: bytes, record: int, title: Title) -> dict | None:
    """`GEN`'s generic dual-class regain, or None where the title has none."""
    pattern = (
        0xAD, (record + DUAL_CLASS_LEVEL) & 0xFF,
        (record + DUAL_CLASS_LEVEL) >> 8,
        0xF0, None,
        0xCD, (record + LEVEL) & 0xFF, (record + LEVEL) >> 8,
        0xB0, None,
        0xAE, (record + DUAL_CLASS_SLOT) & 0xFF,
        (record + DUAL_CLASS_SLOT) >> 8,
        0x9D, (record + CLASS_LEVELS) & 0xFF, (record + CLASS_LEVELS) >> 8,
        0xBD, None, None,
        0x0D, (record + CLASS_BITS) & 0xFF, (record + CLASS_BITS) >> 8,
        0x8D, (record + CLASS_BITS) & 0xFF, (record + CLASS_BITS) >> 8,
    )
    hits = _all_wild(gen, pattern)
    if not hits:
        return None
    if len(hits) != 1:
        raise ValueError(
            f"{title.game.title}: {len(hits)} dual-class regain sites in GEN")
    regain = hits[0]
    if (_branch_target(gen, regain + 3) != regain + 31
            or _branch_target(gen, regain + 8) != regain + 31):
        raise ValueError(
            f"{title.game.title}: dual-class gates do not share the failure exit")
    return {"regain": GEN_BASE + regain,
            "class_mask_table": struct.unpack_from("<H", gen, regain + 17)[0]}


def _never_named(files: dict[str, bytes], address: int) -> int:
    """How many bytes anywhere on the disks are this address, little-endian.

    A count of zero is the evidence that a title has no dual-class regain to
    read: no instruction anywhere can name the byte as an absolute operand.
    """
    want = bytes((address & 0xFF, address >> 8))
    total = 0
    for body in files.values():
        at = body.find(want)
        while at >= 0:
            total += 1
            at = body.find(want, at + 1)
    return total


def inspect(files: dict[str, bytes], title: Title) -> dict:
    """Return instruction evidence for one C64 title's backstab path."""
    record = coldread.staging(title.game)

    def named(name: bytes) -> bytes:
        try:
            return files[name.decode("latin1")]
        except KeyError:
            raise ValueError(
                f"{title.game.title}: no {name.decode('latin1')} on any side"
            ) from None

    combat = named(title.formula)
    attack = named(title.attack)
    to_hit_body = named(title.to_hit)
    gen = named(b"GEN")

    branch_at = 3
    formula = _one_wild(combat, _formula_pattern(title, record),
                        f"{title.game.title} multiplier")

    tail = _one(combat[formula:formula + 0x80], b"\x38\x60\x18\x60",
                f"{title.game.title} predicate returns") + formula
    success, failure = tail, tail + 2
    if _branch_target(combat, formula + branch_at) != failure:
        raise ValueError(f"{title.game.title}: zero thief level does not fail")
    if _u16(record + CLASS_BITS) in combat[formula:failure + 2]:
        raise ValueError(
            f"{title.game.title}: bounded backstab predicate names class_bits")

    store_mark = b"\xaa\xe8\xe8\x86\xb0"
    multiplier_store = _one(
        combat[formula:success], store_mark,
        f"{title.game.title} multiplier store") + formula + 3

    formula_address = title.formula_base + formula
    wrapper_call = _one(attack, b"\x20" + _u16(formula_address),
                        f"{title.game.title} predicate caller")
    copy = _one(attack[wrapper_call:wrapper_call + 0x30], b"\xa5\xb0\x8d",
                f"{title.game.title} multiplier copy") + wrapper_call
    multiplier_address = struct.unpack_from("<H", attack, copy + 3)[0]

    to_hit_pattern = (
        0xAD, None, None, 0x18, 0x6D, None, None, 0xAE,
        multiplier_address & 0xFF, multiplier_address >> 8,
        0xF0, 0x02, 0x69, 0xFE, 0x8D, None, None,
    )
    to_hit = _one_wild(to_hit_body, to_hit_pattern,
                       f"{title.game.title} backstab to-hit adjustment")
    to_hit_number = struct.unpack_from("<H", to_hit_body, to_hit + 1)[0]
    if struct.unpack_from("<H", to_hit_body, to_hit + 15)[0] != to_hit_number:
        raise ValueError(
            f"{title.game.title}: the to-hit adjustment stores somewhere else")

    damage_pattern = (
        0xAD, multiplier_address & 0xFF, multiplier_address >> 8,
        0xF0, None, 0xAE, None, None, 0x20, None, None,
    )
    damage = _one_wild(attack, damage_pattern,
                       f"{title.game.title} damage multiply")
    damage_roll = struct.unpack_from("<H", attack, damage + 6)[0]
    multiply_address = struct.unpack_from("<H", attack, damage + 9)[0]
    application = attack[damage:damage + 0x20]
    if bytes((0x8D,)) + _u16(damage_roll) not in application:
        raise ValueError(
            f"{title.game.title}: multiplied damage is not stored back")
    clamp = CLAMP_DAMAGE if attack[damage + 11:damage + 17] == _CLAMP else None

    library_name, library = _library(files, title)
    multiply_offset = library.find(_MULTIPLY)
    if multiply_offset < 0 or library.find(_MULTIPLY, multiply_offset + 1) >= 0:
        raise ValueError(
            f"{title.game.title}: {library_name} does not hold exactly one "
            f"byte multiply routine")
    library_base = multiply_address - multiply_offset

    overlays = {
        library_name: (library, library_base),
        title.formula.decode("latin1"): (combat, title.formula_base),
        title.attack.decode("latin1"): (attack, title.attack_base),
        title.to_hit.decode("latin1"): (to_hit_body, title.to_hit_base),
    }
    references = _references(overlays, multiplier_address)

    regain = _regain(gen, record, title)
    if regain is None:
        named_anywhere = _never_named(files, record + DUAL_CLASS_LEVEL)
        if named_anywhere:
            raise ValueError(
                f"{title.game.title}: no regain path in GEN, but "
                f"{named_anywhere} bytes name dual_class_level")
        class_masks: tuple[int, ...] = ()
        class_mask_file = None
    else:
        class_mask_file, class_masks = _class_masks(
            title, regain["class_mask_table"], gen, library, library_base)

    capped = ("thief level" if title.cap is None
              else f"min(thief level, {title.cap})")
    return {
        "title": title.game.key,
        "files": {
            "formula": title.formula.decode("latin1"),
            "attack": title.attack.decode("latin1"),
            "to_hit": title.to_hit.decode("latin1"),
            "multiply": library_name,
            "regain": "GEN" if regain else None,
            "class_mask": class_mask_file,
        },
        "bases": {
            title.formula.decode("latin1"): title.formula_base,
            title.attack.decode("latin1"): title.attack_base,
            title.to_hit.decode("latin1"): title.to_hit_base,
            library_name: library_base,
            "GEN": GEN_BASE,
        },
        "record": record,
        "fields": {
            "level": LEVEL,
            "dual_class_slot": DUAL_CLASS_SLOT,
            "dual_class_level": DUAL_CLASS_LEVEL,
            "class_levels": CLASS_LEVELS,
            "level_thief": LEVEL_THIEF,
            "class_bits": CLASS_BITS,
        },
        "thief_level_gate": "level_thief > 0",
        "multiplier": f"(({capped} - 1) // 4) + 2",
        "cap": title.cap,
        "formula": formula_address,
        "multiplier_store": title.formula_base + multiplier_store,
        "predicate_success": title.formula_base + success,
        "predicate_failure": title.formula_base + failure,
        "predicate_call": title.attack_base + wrapper_call,
        "multiplier_address": multiplier_address,
        "to_hit_adjustment": title.to_hit_base + to_hit + 12,
        "to_hit_number": to_hit_number,
        "damage_application": title.attack_base + damage,
        "damage_roll": damage_roll,
        "damage_clamp": clamp,
        "multiply_routine": multiply_address,
        "references": references,
        "regain": regain["regain"] if regain else None,
        "class_mask_table": regain["class_mask_table"] if regain else None,
        "class_masks": class_masks,
        "regained": (
            "dual_class_level > 0 and level > dual_class_level restores "
            "class_levels[dual_class_slot]"
        ) if regain else "no instruction anywhere names dual_class_level",
        "class_bits_in_predicate": False,
    }


def _library(files: dict[str, bytes], title: Title) -> tuple[str, bytes]:
    """The overlay holding the byte multiply, by name or by its own bytes."""
    if title.library is not None:
        name = title.library.decode("latin1")
        if name not in files:
            raise ValueError(f"{title.game.title}: no {name} on any side")
        return name, files[name]
    holders = [name for name, body in files.items() if _MULTIPLY in body]
    if len(holders) != 1:
        raise ValueError(
            f"{title.game.title}: {len(holders)} files hold the byte multiply")
    return holders[0], files[holders[0]]


def _class_masks(title: Title, table: int, gen: bytes, library: bytes,
                 library_base: int) -> tuple[str, tuple[int, ...]]:
    """Read the class-bit table the regain path indexes, from its owner."""
    owners = [
        (name, body, base)
        for name, body, base in (("GEN", gen, GEN_BASE),
                                 ("LIBRARY", library, library_base))
        if base <= table <= base + len(body) - len(CLASS_MASKS)
    ]
    if len(owners) != 1:
        raise ValueError(
            f"{title.game.title}: class-mask table ${table:04X} "
            f"belongs to {len(owners)} loaded overlays")
    name, body, base = owners[0]
    masks = body[table - base:table - base + len(CLASS_MASKS)]
    if masks != CLASS_MASKS:
        raise ValueError(
            f"{title.game.title}: class-mask table is {masks.hex(' ')}, "
            f"not {CLASS_MASKS.hex(' ')}")
    return name, tuple(masks)


def inspect_title(title: Title, root: str | None = None) -> dict:
    """Read every file on this title's sides and inspect its backstab path."""
    return inspect(coldread.every_file(title.game, root), title)


def _label(name: str) -> str:
    """A directory entry, or a description where it is not ASCII."""
    return name if name.isascii() and name.isprintable() else "an unnamed overlay"


def _print(finding: dict) -> None:
    print(finding["title"])
    files = {key: _label(value) if isinstance(value, str) else value
             for key, value in finding["files"].items()}
    print(f"  Thief gate    {files['formula']} ${finding['formula']:04X}: "
          f"{finding['thief_level_gate']}")
    print(f"  Multiplier    {finding['multiplier']} -> "
          f"${finding['multiplier_address']:04X}")
    print(f"  Applied       {files['attack']} "
          f"${finding['damage_application']:04X} through {files['multiply']} "
          f"${finding['multiply_routine']:04X}"
          + ("" if finding["damage_clamp"] is None
             else f", clamped to {finding['damage_clamp']}"))
    print(f"  To-hit        {files['to_hit']} "
          f"${finding['to_hit_adjustment']:04X}: -2 on "
          f"${finding['to_hit_number']:04X}")
    if finding["regain"] is None:
        print(f"  Regain        {finding['regained']}")
    else:
        print(f"  Regain        GEN ${finding['regain']:04X}: "
              f"{finding['regained']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", choices=sorted(TITLES), action="append",
                        help="inspect one title; default is every title")
    parser.add_argument("--disks", help="directory holding one title's disks")
    parser.add_argument("--check", action="store_true",
                        help="exit nonzero if a reading is missing")
    args = parser.parse_args(argv)
    keys = args.title or list(TITLES)
    if args.disks and len(keys) != 1:
        parser.error("--disks requires exactly one --title")
    failed = False
    for key in keys:
        try:
            finding = inspect_title(TITLES[key], args.disks)
        except (OSError, SystemExit, ValueError) as exc:
            print(f"{key}: {exc}")
            failed = True
            continue
        _print(finding)
    return 1 if args.check and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read the later C64 titles' backstab paths from their own overlays.

    tools/c64/backstab.py
    tools/c64/backstab.py --title secret-of-the-silver-blades
    tools/c64/backstab.py --title curse-of-the-azure-bonds --disks /path/to/disks

``COMBAT2`` supplies the thief-level gate and multiplier arithmetic, ``ECL64``
applies the result to damage and the attack roll, ``LIBRARY`` supplies the
multiply routine, and ``GEN`` restores a dual-classed character's old level.
The files are read from the player's C64 disks and never written.
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

COMBAT2_BASE = 0xE000
ECL64_BASE = 0x8000
GEN_BASE = 0x0800
LIBRARY_BASE = 0x2DC8
RECORD_BASE = 0x7C00

LEVEL = 0x0A0
DUAL_CLASS_SLOT = 0x0B9
DUAL_CLASS_LEVEL = 0x0BA
CLASS_LEVELS = 0x0C9
THIEF_SLOT = 2
LEVEL_THIEF = CLASS_LEVELS + THIEF_SLOT
CLASS_BITS = 0x0EB
CLASS_MASKS = bytes((0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80))


@dataclasses.dataclass(frozen=True)
class Title:
    """One later C64 title and the one arithmetic difference in its path."""

    game: c64_port.C64Container
    cap: int | None


TITLES = {
    game.key: Title(game, cap)
    for game, cap in (
        (c64_port.CURSE_OF_THE_AZURE_BONDS, None),
        (c64_port.SECRET_OF_THE_SILVER_BLADES, 14),
    )
}


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


def _one_wild(body: bytes, pattern: tuple[int | None, ...], what: str) -> int:
    hits = []
    for at in range(len(body) - len(pattern) + 1):
        if all(want is None or body[at + i] == want
               for i, want in enumerate(pattern)):
            hits.append(at)
    if len(hits) != 1:
        raise ValueError(
            f"{what}: expected one instruction signature, found {len(hits)}")
    return hits[0]


def _branch_target(body: bytes, at: int) -> int:
    displacement = struct.unpack("b", body[at + 1:at + 2])[0]
    return at + 2 + displacement


def _formula_pattern(title: Title) -> tuple[int | None, ...]:
    gate = (0xAE, (RECORD_BASE + LEVEL_THIEF) & 0xFF,
            (RECORD_BASE + LEVEL_THIEF) >> 8, 0xF0, None)
    cap = () if title.cap is None else (
        0xE0, title.cap, 0x90, 0x02, 0xA2, title.cap,
    )
    return gate + cap + (0xCA, 0x8A, 0x4A, 0x4A, 0xAA, 0xE8, 0xE8, 0x86, 0xB0)


_MULTIPLY = bytes.fromhex(
    "85 ab 86 4b a9 00 85 4c a2 07 46 ab 90 03 18 65 4b "
    "6a 66 4c ca 10 f3 85 4d aa a5 4c 18 60"
)


def inspect(combat2: bytes, ecl64: bytes, gen: bytes, library: bytes,
            title: Title) -> dict:
    """Return instruction evidence for one later C64 backstab path."""
    branch_at = 3
    formula = _one_wild(combat2, _formula_pattern(title),
                        f"{title.game.title} multiplier")

    tail = _one(combat2[formula:formula + 0x80], b"\x38\x60\x18\x60",
                f"{title.game.title} predicate returns") + formula
    success, failure = tail, tail + 2
    if _branch_target(combat2, formula + branch_at) != failure:
        raise ValueError(f"{title.game.title}: zero thief level does not fail")
    if _u16(RECORD_BASE + CLASS_BITS) in combat2[formula:failure + 2]:
        raise ValueError(
            f"{title.game.title}: bounded backstab predicate names class_bits")

    store_mark = b"\xaa\xe8\xe8\x86\xb0"
    multiplier_store = _one(
        combat2[formula:success], store_mark,
        f"{title.game.title} multiplier store") + formula + 3

    formula_address = COMBAT2_BASE + formula
    wrapper_call = _one(ecl64, b"\x20" + _u16(formula_address),
                        f"{title.game.title} predicate caller")
    copy = _one(ecl64[wrapper_call:wrapper_call + 0x30], b"\xa5\xb0\x8d",
                f"{title.game.title} multiplier copy") + wrapper_call
    multiplier_address = struct.unpack_from("<H", ecl64, copy + 3)[0]

    to_hit_pattern = (
        0xAD, 0x58, 0x94, 0x18, 0x6D, None, None, 0xAE,
        multiplier_address & 0xFF, multiplier_address >> 8,
        0xF0, 0x02, 0x69, 0xFE, 0x8D, 0x58, 0x94,
    )
    to_hit = _one_wild(ecl64, to_hit_pattern,
                       f"{title.game.title} backstab to-hit adjustment")

    damage_pattern = (
        0xAD, multiplier_address & 0xFF, multiplier_address >> 8,
        0xF0, None, 0xAE, 0x5F, 0x94, 0x20, None, None,
    )
    damage = _one_wild(ecl64, damage_pattern,
                       f"{title.game.title} damage multiply")
    multiply_address = struct.unpack_from("<H", ecl64, damage + 9)[0]
    application = ecl64[damage:damage + 0x20]
    if b"\x8d\x5f\x94" not in application:
        raise ValueError(
            f"{title.game.title}: multiplied damage is not stored")
    multiply_offset = multiply_address - LIBRARY_BASE
    if not 0 <= multiply_offset <= len(library) - len(_MULTIPLY):
        raise ValueError(
            f"{title.game.title}: multiply target is outside LIBRARY")
    if library[multiply_offset:multiply_offset + len(_MULTIPLY)] != _MULTIPLY:
        raise ValueError(
            f"{title.game.title}: damage target is not the byte multiply routine")

    regain_pattern = (
        0xAD, (RECORD_BASE + DUAL_CLASS_LEVEL) & 0xFF,
        (RECORD_BASE + DUAL_CLASS_LEVEL) >> 8,
        0xF0, None,
        0xCD, (RECORD_BASE + LEVEL) & 0xFF, (RECORD_BASE + LEVEL) >> 8,
        0xB0, None,
        0xAE, (RECORD_BASE + DUAL_CLASS_SLOT) & 0xFF,
        (RECORD_BASE + DUAL_CLASS_SLOT) >> 8,
        0x9D, (RECORD_BASE + CLASS_LEVELS) & 0xFF,
        (RECORD_BASE + CLASS_LEVELS) >> 8,
        0xBD, None, None,
        0x0D, (RECORD_BASE + CLASS_BITS) & 0xFF,
        (RECORD_BASE + CLASS_BITS) >> 8,
        0x8D, (RECORD_BASE + CLASS_BITS) & 0xFF,
        (RECORD_BASE + CLASS_BITS) >> 8,
    )
    regain = _one_wild(gen, regain_pattern,
                       f"{title.game.title} dual-class regain")
    if (_branch_target(gen, regain + 3) != regain + 31
            or _branch_target(gen, regain + 8) != regain + 31):
        raise ValueError(
            f"{title.game.title}: dual-class gates do not share the failure exit")
    class_mask_table = struct.unpack_from("<H", gen, regain + 17)[0]
    owners = [
        (name, body, base)
        for name, body, base in (
            ("GEN", gen, GEN_BASE),
            ("LIBRARY", library, LIBRARY_BASE),
        )
        if base <= class_mask_table <= base + len(body) - len(CLASS_MASKS)
    ]
    if len(owners) != 1:
        raise ValueError(
            f"{title.game.title}: class-mask table ${class_mask_table:04X} "
            f"belongs to {len(owners)} loaded overlays")
    class_mask_file, class_mask_body, class_mask_base = owners[0]
    class_masks = class_mask_body[
        class_mask_table - class_mask_base:
        class_mask_table - class_mask_base + len(CLASS_MASKS)
    ]
    if class_masks != CLASS_MASKS:
        raise ValueError(
            f"{title.game.title}: class-mask table is {class_masks.hex(' ')}, "
            f"not {CLASS_MASKS.hex(' ')}")

    capped = ("thief level" if title.cap is None
              else f"min(thief level, {title.cap})")
    formula_text = f"(({capped} - 1) // 4) + 2"
    return {
        "title": title.game.key,
        "files": {
            "formula": "COMBAT2",
            "attack": "ECL64",
            "multiply": "LIBRARY",
            "regain": "GEN",
            "class_mask": class_mask_file,
        },
        "bases": {
            "COMBAT2": COMBAT2_BASE,
            "ECL64": ECL64_BASE,
            "LIBRARY": LIBRARY_BASE,
            "GEN": GEN_BASE,
        },
        "fields": {
            "level": LEVEL,
            "dual_class_slot": DUAL_CLASS_SLOT,
            "dual_class_level": DUAL_CLASS_LEVEL,
            "class_levels": CLASS_LEVELS,
            "level_thief": LEVEL_THIEF,
            "class_bits": CLASS_BITS,
        },
        "thief_level_gate": "level_thief > 0",
        "multiplier": formula_text,
        "cap": title.cap,
        "formula": formula_address,
        "multiplier_store": COMBAT2_BASE + multiplier_store,
        "predicate_success": COMBAT2_BASE + success,
        "predicate_failure": COMBAT2_BASE + failure,
        "predicate_call": ECL64_BASE + wrapper_call,
        "multiplier_address": multiplier_address,
        "to_hit_adjustment": ECL64_BASE + to_hit + 12,
        "damage_application": ECL64_BASE + damage,
        "multiply_routine": multiply_address,
        "regain": GEN_BASE + regain,
        "class_mask_table": class_mask_table,
        "class_masks": tuple(class_masks),
        "regained": (
            "dual_class_level > 0 and level > dual_class_level restores "
            "class_levels[dual_class_slot]"
        ),
        "class_bits_in_predicate": False,
    }


def inspect_title(title: Title, root: str | None = None) -> dict:
    """Read and inspect the four overlays for ``title``."""
    game = title.game
    return inspect(
        coldread.overlay(game, b"COMBAT2", root),
        coldread.overlay(game, b"ECL64", root),
        coldread.overlay(game, b"GEN", root),
        coldread.overlay(game, b"LIBRARY", root),
        title,
    )


def _print(finding: dict) -> None:
    print(finding["title"])
    print(f"  Thief gate    COMBAT2 ${finding['formula']:04X}: "
          f"{finding['thief_level_gate']}")
    print(f"  Multiplier    {finding['multiplier']}")
    print(f"  Applied       ECL64 ${finding['damage_application']:04X} through "
          f"LIBRARY ${finding['multiply_routine']:04X}")
    print(f"  To-hit        ECL64 ${finding['to_hit_adjustment']:04X}: -2")
    print(f"  Regain        GEN ${finding['regain']:04X}: "
          f"{finding['regained']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", choices=sorted(TITLES), action="append",
                        help="inspect one title; default is both")
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

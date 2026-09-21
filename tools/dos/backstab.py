#!/usr/bin/env python3
"""Read the later DOS titles' backstab rules from their own engines.

    tools/dos/backstab.py
    tools/dos/backstab.py --game CURSE --game-dir /path/to/CURSE
    tools/dos/backstab.py --check

The attack resolver, its backstab predicate and the dual-class regain helper
are found by their instruction bytes rather than by the offsets printed in the
report. ``GAME.OVR`` supplies the attack code; the title's loader -- Curse's
and Silver Blades' ``START.EXE``, Pools of Darkness' ``GAME.EXE`` -- supplies
the overlay map which resolves the far calls. Both files are read from the
player's DOS archives and never written.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import struct
import sys

import capstone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import dos_port  # noqa: E402
from tools.dos import dosbox, dosovrmap, dospod, unexepack  # noqa: E402


@dataclasses.dataclass(frozen=True)
class Title:
    """The fields and compiler form expected from one supported engine.

    `arithmetic` is `shift` or `idiv` where the effective thief level is built
    inline, and `helper` where the engine calls one shared class-level routine
    for it. `loader` is the executable carrying the overlay map.
    """

    stem: str
    key: str
    arithmetic: str
    loader: str = "START.EXE"


TITLES = {
    "CURSE": Title("CURSE", "curse-of-the-azure-bonds", "shift"),
    "SECRET": Title("SECRET", "secret-of-the-silver-blades", "idiv"),
    "DARKNESS": Title("DARKNESS", "pools-of-darkness", "helper", "GAME.EXE"),
}

THIEF_SLOT = 6
PROLOGUE = b"\x55\x89\xe5"


def _u16(value: int) -> bytes:
    return struct.pack("<H", value)


def _near_target(image: bytes, call: int) -> int:
    return call + 3 + struct.unpack_from("<h", image, call + 1)[0]


def _one(image: bytes, pattern: bytes, what: str) -> int:
    hits = []
    at = image.find(pattern)
    while at >= 0:
        hits.append(at)
        at = image.find(pattern, at + 1)
    if len(hits) != 1:
        raise ValueError(
            f"{what}: expected one instruction signature, found {len(hits)}")
    return hits[0]


def _fields(title: Title) -> dict[str, int]:
    fields = dos_port.FIELDS_BY_NAME_FOR[title.key]
    deltas = dos_port.deltas_for(title.key)
    return {
        "race": fields["race"].offset,
        "human_race": deltas.race_numbers.index("human"),
        "class_levels": fields["class_levels"].offset,
        "former_class_levels": fields["former_class_levels"].offset,
        "current_thief": fields["class_levels"].offset + THIEF_SLOT,
        "former_thief": fields["former_class_levels"].offset + THIEF_SLOT,
        "former_level": fields["former_level"].offset,
        "class_bits": fields["class_bits"].offset,
    }


def _formula_pattern(title: Title, fields: dict[str, int]) -> bytes:
    """The whole effective-level arithmetic, from former level through +2."""
    before_current = (
        b"\x26\x8a\x85" + _u16(fields["former_thief"])
        + b"\x98"
        + (b"\xf7\xe2" if title.arithmetic == "shift" else b"\xf7\xea")
        + b"\x8b\xd0\xc4\x7e\x0c\x26\x8a\x85"
        + _u16(fields["current_thief"]) + b"\x98\x03\xc2\x48"
    )
    if title.arithmetic == "shift":
        return before_current + b"\xd1\xe8\xd1\xe8\x40\x40"
    return before_current + b"\x99\xb9\x04\x00\xf7\xf9\x05\x02\x00"


def _callers(image: bytes, target: int) -> list[int]:
    return [at for at in range(len(image) - 3)
            if image[at] == 0xE8 and _near_target(image, at) == target]


def _es_displacements(image: bytes, start: int, end: int) -> set[int]:
    """Direct ES-relative displacements in one known-aligned routine."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    md.detail = True
    out = set()
    for instruction in md.disasm(image[start:end], start):
        for operand in instruction.operands:
            if (operand.type == capstone.x86.X86_OP_MEM
                    and operand.mem.segment == capstone.x86.X86_REG_ES):
                out.add(operand.mem.disp)
    return out


def inspect(overlay: bytes, start_exe: bytes, title: Title) -> dict:
    """Return the instruction evidence for one later DOS backstab path.

    The result is absent unless the damage formula, both gate branches and the
    resolved regain helper all agree on the title's record offsets.
    """
    fields = _fields(title)
    formula = _one(overlay, _formula_pattern(title, fields),
                   f"{title.stem} multiplier")
    formula_end = formula + len(_formula_pattern(title, fields))
    damage_mul_opcode = (b"\xf7\xe2" if title.arithmetic == "shift"
                         else b"\xf7\xea")
    application = overlay[formula_end:formula_end + 9]
    if not (application[:3] == b"\x8b\xd0\xa0"
            and application[5:7] == b"\x30\xe4"
            and application[7:9] == damage_mul_opcode):
        raise ValueError(f"{title.stem}: computed multiplier is not applied")

    call_mark = overlay.rfind(b"\x0e\xe8", max(0, formula - 0x30), formula)
    if call_mark < 0:
        raise ValueError(
            f"{title.stem}: no backstab predicate call before multiplier")
    predicate_call = call_mark + 1
    predicate = _near_target(overlay, predicate_call)

    current_test_bytes = (
        b"\x26\x80\xbd" + _u16(fields["current_thief"]) + b"\x00\x7f")
    former_test_bytes = (
        b"\x26\x80\xbd" + _u16(fields["former_thief"]) + b"\x00\x7e")
    current_test = overlay.find(current_test_bytes, predicate, predicate + 0x100)
    former_test = overlay.find(former_test_bytes, predicate, predicate + 0x100)
    if current_test < 0 or former_test < 0 or former_test <= current_test:
        raise ValueError(f"{title.stem}: the current/former thief gate is missing")
    predicate_end = overlay.find(PROLOGUE, predicate + len(PROLOGUE))
    if predicate_end < 0:
        raise ValueError(f"{title.stem}: cannot bound the backstab predicate")
    predicate_fields = _es_displacements(overlay, predicate, predicate_end)
    if fields["class_bits"] in predicate_fields:
        raise ValueError(f"{title.stem}: backstab predicate reads class_bits")

    # The same far helper gates a former thief level in the predicate and
    # multiplies that level by 0/1 in the damage formula.
    formula_far = overlay.rfind(b"\x9a", max(0, formula - 0x18), formula)
    gate_far = overlay.find(b"\x9a", former_test + len(former_test_bytes),
                            former_test + len(former_test_bytes) + 0x18)
    if formula_far < 0 or gate_far < 0:
        raise ValueError(f"{title.stem}: the regain-helper calls are missing")
    far = overlay[formula_far:formula_far + 5]
    if overlay[gate_far:gate_far + 5] != far:
        raise ValueError(
            f"{title.stem}: gate and multiplier use different helpers")
    helper_off, helper_seg = struct.unpack_from("<HH", far, 1)

    start_image, _ = unexepack.unpack(start_exe)
    source, helper = dosovrmap.resolve(
        dosovrmap.units(start_image, len(overlay)), helper_seg, helper_off)
    if source != "GAME.OVR" or helper is None:
        raise ValueError(
            f"{title.stem}: regain helper does not resolve into GAME.OVR")
    if overlay[helper:helper + 3] != PROLOGUE:
        raise ValueError(
            f"{title.stem}: resolved regain helper has no prologue")
    current_call_mark = overlay.find(b"\x0e\xe8", helper, helper + 0x20)
    if current_call_mark < 0:
        raise ValueError(f"{title.stem}: regain helper has no level call")
    current_level_routine = _near_target(overlay, current_call_mark + 1)
    human_test = (
        b"\xc4\x7e\x06\x26\x80\x7d" + bytes((fields["race"],
                                                fields["human_race"]))
    )
    level_test = b"\x26\x80\xbd" + _u16(fields["class_levels"]) + b"\x00"
    level_read = b"\x26\x8a\x85" + _u16(fields["class_levels"])
    current_window = overlay[current_level_routine:current_level_routine + 0x80]
    if not (current_window.startswith(PROLOGUE)
            and human_test in current_window
            and level_test in current_window
            and level_read in current_window):
        raise ValueError(
            f"{title.stem}: active-level helper lacks its human/level-array read")
    former_level_cmp = overlay.find(
        b"\x26\x3a\x85" + _u16(fields["former_level"]),
        helper, helper + 0x40)
    if former_level_cmp < 0:
        raise ValueError(
            f"{title.stem}: regain helper does not compare former_level")
    strict_greater = (
        b"\x26\x3a\x85" + _u16(fields["former_level"])
        + (b"\xb0\x00\x7e\x01\x40" if title.arithmetic == "shift"
           else b"\x7f\x04\xb0\x00\xeb\x02\xb0\x01")
    )
    if overlay[former_level_cmp:former_level_cmp + len(strict_greater)] \
            != strict_greater:
        raise ValueError(f"{title.stem}: regain comparison is not strict >")

    return {
        "stem": title.stem,
        "fields": fields,
        "formula": formula,
        "current_read": formula + 13,
        "damage_mul": formula_end + 7,
        "predicate": predicate,
        "predicate_call": predicate_call,
        "predicate_callers": _callers(overlay, predicate),
        "predicate_fields": predicate_fields,
        "current_test": current_test,
        "former_test": former_test,
        "regain_calls": [gate_far, formula_far],
        "regain_far": (helper_seg, helper_off),
        "regain_helper": helper,
        "current_level_routine": current_level_routine,
        "former_level_cmp": former_level_cmp,
        "multiplier": "((effective thief level - 1) // 4) + 2",
        "effective_level": (
            "class_levels[thief] + "
            "former_class_levels[thief] * regained"
        ),
        "gate": (
            "class_levels[thief] > 0 or "
            "(former_class_levels[thief] > 0 and regained)"
        ),
        "regained": "human and active class level > former_level",
    }


def _all_wild(image: bytes, pattern: tuple[int | None, ...]) -> list[int]:
    anchor = bytes(pattern[:2])
    last = len(image) - len(pattern)
    out, at = [], image.find(anchor)
    while 0 <= at <= last:
        if all(want is None or image[at + i] == want
               for i, want in enumerate(pattern)):
            out.append(at)
        at = image.find(anchor, at + 1)
    return out


def _one_wild(image: bytes, pattern: tuple[int | None, ...], what: str) -> int:
    hits = _all_wild(image, pattern)
    if len(hits) != 1:
        raise ValueError(
            f"{what}: expected one instruction signature, found {len(hits)}")
    return hits[0]


#: `mov al,6 / push ax / lcall`: the shared class-level helper asked for the
#: thief slot, the only place Pools of Darkness gets an effective thief level.
_POD_THIEF_LEVEL = (0xB0, THIEF_SLOT, 0x50, 0x9A, None, None, None, None)

#: The multiplier, its clamp and the multiply it is applied with. The four
#: `[bp+d]` displacements are checked equal and the two damage-word addresses
#: are checked equal after the match.
_POD_FORMULA = _POD_THIEF_LEVEL + (
    0x30, 0xE4, 0x48, 0xD1, 0xE8, 0xD1, 0xE8, 0x40, 0x40,
    0x88, 0x46, None,
    0x80, 0x7E, None, 0x05, 0x76, 0x04, 0xC6, 0x46, None, 0x05,
    0x8A, 0x46, None, 0x30, 0xE4, 0xF7, 0x26, None, None, 0xA3, None, None,
)
POD_CLAMP = 5

#: `al = max(al, ah)` spelled out by the compiler, in the class-level helper.
_POD_MAX = (0x8A, 0x46, None, 0x3A, 0x46, None, 0x76, 0x08,
            0x8A, 0x46, None, 0x88, 0x46, None, 0xEB, 0x06,
            0x8A, 0x46, None, 0x88, 0x46, None)

#: `mov al,0 / jbe +1 / inc ax`: the regain helper's strictly-greater test.
_POD_STRICT = b"\xb0\x00\x76\x01\x40"


def inspect_pools_of_darkness(overlay: bytes, loader: bytes,
                              title: Title) -> dict:
    """Return the instruction evidence for the Pools of Darkness path.

    The engine does not build the effective thief level inline as Curse and
    Silver Blades do: it calls one shared class-level routine, which takes the
    larger of the current and the regained former slot, and it clamps the
    multiplier itself rather than the level.
    """
    fields = _fields(title)
    formula = _one_wild(overlay, _POD_FORMULA, f"{title.stem} multiplier")
    slot = overlay[formula + 19]
    if not all(overlay[formula + at] == slot for at in (22, 28, 32)):
        raise ValueError(f"{title.stem}: the clamp is on another local")
    damage_word = struct.unpack_from("<H", overlay, formula + 37)[0]
    if struct.unpack_from("<H", overlay, formula + 40)[0] != damage_word:
        raise ValueError(f"{title.stem}: the multiplied damage is not stored back")

    helper_off, helper_seg = struct.unpack_from("<HH", overlay, formula + 4)
    start_image, _ = unexepack.unpack(loader)
    units = dosovrmap.units(start_image, len(overlay))
    source, helper = dosovrmap.resolve(units, helper_seg, helper_off)
    if source != "GAME.OVR" or helper is None:
        raise ValueError(
            f"{title.stem}: the class-level helper is not in GAME.OVR")
    window = overlay[helper:helper + 0x60]
    if not window.startswith(PROLOGUE):
        raise ValueError(f"{title.stem}: the class-level helper has no prologue")
    current_read = b"\x26\x8a\x85" + _u16(fields["class_levels"])
    former_read = b"\x26\x8a\x85" + _u16(fields["former_class_levels"])
    if current_read not in window or former_read not in window:
        raise ValueError(
            f"{title.stem}: the class-level helper reads neither level array")
    if not _all_wild(window, _POD_MAX):
        raise ValueError(
            f"{title.stem}: the class-level helper does not take the larger")

    regain_call = window.find(b"\x0e\xe8")
    if regain_call < 0:
        raise ValueError(f"{title.stem}: the class-level helper calls nothing")
    regain_helper = _near_target(overlay, helper + regain_call + 1)
    former_level_cmp = overlay.find(
        b"\x26\x3a\x85" + _u16(fields["former_level"]),
        regain_helper, regain_helper + 0x40)
    if former_level_cmp < 0:
        raise ValueError(
            f"{title.stem}: the regain helper does not compare former_level")
    if overlay[former_level_cmp + 5:former_level_cmp + 10] != _POD_STRICT:
        raise ValueError(f"{title.stem}: regain comparison is not strict >")
    level_call = overlay.find(b"\x0e\xe8", regain_helper, former_level_cmp)
    if level_call < 0:
        raise ValueError(f"{title.stem}: the regain helper has no level call")
    current_level_routine = _near_target(overlay, level_call + 1)
    human_test = (b"\xc4\x7e\x06\x26\x80\xbd" + _u16(fields["race"])
                  + bytes((fields["human_race"], 0x74)))
    level_test = b"\x26\x80\xbd" + _u16(fields["class_levels"]) + b"\x00"
    current_window = overlay[current_level_routine:current_level_routine + 0x80]
    if not (current_window.startswith(PROLOGUE)
            and human_test in current_window
            and level_test in current_window
            and current_read in current_window):
        raise ValueError(
            f"{title.stem}: active-level helper lacks its human/level-array read")

    call_mark = overlay.rfind(b"\x0e\xe8", max(0, formula - 0x30), formula)
    if call_mark < 0:
        raise ValueError(
            f"{title.stem}: no backstab predicate call before the multiplier")
    predicate_call = call_mark + 1
    predicate = _near_target(overlay, predicate_call)
    predicate_end = overlay.find(PROLOGUE, predicate + len(PROLOGUE))
    if predicate_end < 0:
        raise ValueError(f"{title.stem}: cannot bound the backstab predicate")
    gate = overlay.find(
        bytes(_POD_THIEF_LEVEL[:4]) + _u16(helper_off) + _u16(helper_seg)
        + b"\x08\xc0\x76", predicate, predicate_end)
    if gate < 0:
        raise ValueError(
            f"{title.stem}: the predicate does not gate on the thief level")
    predicate_fields = _es_displacements(overlay, predicate, predicate_end)
    if fields["class_bits"] in predicate_fields:
        raise ValueError(f"{title.stem}: backstab predicate reads class_bits")

    return {
        "stem": title.stem,
        "fields": fields,
        "formula": formula + 8,
        "thief_level_call": formula,
        "multiplier_clamp": formula + 20,
        "clamp": POD_CLAMP,
        "damage_mul": formula + 35,
        "damage_word": damage_word,
        "predicate": predicate,
        "predicate_call": predicate_call,
        "predicate_callers": _callers(overlay, predicate),
        "predicate_fields": predicate_fields,
        "predicate_gate": gate,
        "level_helper_far": (helper_seg, helper_off),
        "level_helper": helper,
        "regain_helper": regain_helper,
        "current_level_routine": current_level_routine,
        "former_level_cmp": former_level_cmp,
        "multiplier": "min(((effective thief level - 1) // 4) + 2, 5)",
        "effective_level": (
            "max(class_levels[thief], "
            "former_class_levels[thief] * regained)"
        ),
        "gate": "effective thief level > 0",
        "regained": "human and active class level > former_level",
    }


def find_game(title: Title) -> pathlib.Path:
    """The title's game directory inside the player's archives.

    `dosbox.find_game` searches for `START.EXE`, which Pools of Darkness does
    not ship; `dospod.find_game` searches for its `START.BAT` instead.
    """
    if title.loader == "START.EXE":
        return dosbox.find_game(title.stem)
    return dospod.find_game(title.stem)


def inspect_dir(game_dir: pathlib.Path, title: Title) -> dict:
    """Read and inspect ``GAME.OVR`` and the title's loader in ``game_dir``."""
    overlay = (game_dir / "GAME.OVR").read_bytes()
    loader = (game_dir / title.loader).read_bytes()
    if title.arithmetic == "helper":
        return inspect_pools_of_darkness(overlay, loader, title)
    return inspect(overlay, loader, title)


def _print_pools_of_darkness(finding: dict) -> None:
    fields = finding["fields"]
    print(finding["stem"])
    print(f"  Gate           GAME.OVR:0x{finding['predicate']:X}, thief level "
          f"at 0x{finding['predicate_gate']:X}")
    print(f"  Effective      GAME.OVR:0x{finding['level_helper']:X}: "
          f"{finding['effective_level']}, slots at record "
          f"0x{fields['current_thief']:03X} and "
          f"0x{fields['former_thief']:03X}")
    print(f"  Multiplier     GAME.OVR:0x{finding['formula']:X}: "
          f"{finding['multiplier']}")
    print(f"    Applied      GAME.OVR:0x{finding['damage_mul']:X} to "
          f"0x{finding['damage_word']:04X}")
    print(f"  Regain helper  GAME.OVR:0x{finding['regain_helper']:X}; "
          f"{finding['regained']}")
    print("  Predicate uses " + ", ".join(
        f"0x{at:X}" for at in finding["predicate_callers"]))


def _print(finding: dict) -> None:
    if "clamp" in finding:
        _print_pools_of_darkness(finding)
        return
    fields = finding["fields"]
    print(finding["stem"])
    print(f"  Gate           GAME.OVR:0x{finding['predicate']:X}")
    print(f"    Current      0x{finding['current_test']:X} tests record "
          f"0x{fields['current_thief']:03X} > 0")
    print(f"    Former       0x{finding['former_test']:X} tests record "
          f"0x{fields['former_thief']:03X} > 0, then regained")
    print(f"  Multiplier     GAME.OVR:0x{finding['formula']:X}: "
          f"{finding['multiplier']}")
    print(f"    Applied      GAME.OVR:0x{finding['damage_mul']:X}")
    print(f"  Effective      {finding['effective_level']}")
    seg, off = finding["regain_far"]
    print(f"  Regain helper  {seg:04X}:{off:04X} -> GAME.OVR:"
          f"0x{finding['regain_helper']:X}; {finding['regained']}")
    print("  Predicate uses " + ", ".join(
        f"0x{at:X}" for at in finding["predicate_callers"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", choices=sorted(TITLES), action="append",
                        help="inspect one title; default is every title")
    parser.add_argument("--game-dir", type=pathlib.Path,
                        help="directory holding GAME.OVR and the title's "
                             "loader; requires one --game")
    parser.add_argument("--check", action="store_true",
                        help="exit nonzero if a reading is missing")
    args = parser.parse_args(argv)
    stems = args.game or list(TITLES)
    if args.game_dir is not None and len(stems) != 1:
        parser.error("--game-dir requires exactly one --game")

    failed = False
    for stem in stems:
        title = TITLES[stem]
        try:
            directory = args.game_dir or find_game(title)
            finding = inspect_dir(directory, title)
        except (FileNotFoundError, OSError, ValueError) as exc:
            print(f"{stem}: {exc}")
            failed = True
            continue
        _print(finding)
    return 1 if args.check and failed else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Read C64 duration packing and Pool effect encodings from the player's code.

The output is evidence for a conversion, not a conversion writer. Duration
packing is checked on all three C64 titles; the DOS/C64 value comparisons are
Pool of Radiance's only. See docs/226-the-c64-running-effect-crosswalk.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from automap.paths import tool_disks  # noqa: E402
from goldbox import c64_port  # noqa: E402
from tools.c64 import coldread, d6502  # noqa: E402


@dataclasses.dataclass(frozen=True)
class PackingSite:
    """The operands locating one title's count promotion and slot stores."""

    file: str
    base: int
    count_test: int
    ratio_read: int
    division_call: int
    unit_merge: int
    stores: tuple[int, int, int, int]
    library_base: int


SITES = {
    "pool-of-radiance": PackingSite(
        "SPELLE04", 0xA700, 0xA7C9, 0xA7D5, 0xA7DC, 0xA7E5,
        (0xA816, 0xA81C, 0xA822, 0xA82D), 0x2C48),
    "curse-of-the-azure-bonds": PackingSite(
        "ECL65", 0x8000, 0x8116, 0x8122, 0x8129, 0x8132,
        (0x8162, 0x8168, 0x816E, 0x8179), 0x2DC8),
    "secret-of-the-silver-blades": PackingSite(
        "ECL65", 0x8000, 0x8116, 0x8122, 0x8129, 0x8132,
        (0x8162, 0x8168, 0x816E, 0x8179), 0x2DC8),
}


def operand(body: bytes, base: int, at: int, opcode: int) -> int:
    """Read an instruction operand, rejecting a different engine build."""
    offset = at - base
    size = d6502.SZ[d6502.T[opcode][1]]
    if offset < 0 or offset + size > len(body) or body[offset] != opcode:
        raise ValueError(f"Expected opcode ${opcode:02X} at ${at:04X}")
    return int.from_bytes(body[offset + 1:offset + size], "little")


@dataclasses.dataclass(frozen=True)
class Packing:
    """Measurements from a title's cast-time count promotion."""

    title: str
    threshold: int
    ratios: tuple[int, ...]
    units: tuple[int, ...]
    arrays: tuple[int, ...]
    divide: int

    def from_minutes(self, minutes: int) -> int:
        """Extend the engine's integer promotion to a DOS u16 minute count.

        This reproduces its truncation, not an exact conversion policy. The
        game's input count is a byte in the spell's initial unit; a DOS word
        can need more promotions than one C64 cast.
        """
        if not 0 <= minutes <= 0xFFFF:
            raise ValueError("Minutes must be in 0..65535")
        count, unit = minutes, 0
        while count >= self.threshold:
            unit += 1
            if unit == len(self.units):
                raise ValueError("Duration exceeds the measured C64 units")
            count //= self.ratios[unit]
        return count | self.units[unit]


def read_packing(title: str, code: bytes, library: bytes) -> Packing:
    """Read the count limit, divisors, unit bits and all four store operands."""
    site = SITES[title]
    def get(at: int, op: int) -> int:
        return operand(code, site.base, at, op)
    threshold = get(site.count_test, 0xC9)
    ratio_at = get(site.ratio_read, 0xBD) - site.base
    units_at = get(site.unit_merge, 0x1D) - site.base
    divide = get(site.division_call, 0x20)
    if not (0 <= ratio_at <= len(code) - 4
            and 0 <= units_at <= len(code) - 4):
        raise ValueError("Duration table is outside its overlay")
    # The restoring division keeps its quotient in $4C/$4D and its
    # remainder elsewhere; the return reads the quotient without rounding.
    if (operand(library, site.library_base, divide + 0x31, 0xA5),
            operand(library, site.library_base, divide + 0x33, 0xA6)) != (0x4C, 0x4D):
        raise ValueError("Division no longer returns the quotient in A/X")
    operand(library, site.library_base, divide + 0x35, 0x60)
    return Packing(title, threshold, tuple(code[ratio_at:ratio_at + 4]),
                   tuple(code[units_at:units_at + 4]),
                   tuple(get(at, 0x9D) for at in site.stores), divide)


def remaining_minutes(byte: int, clock_minutes: int) -> int | None:
    """The camp-clock expiry time; None means the zero byte never expires."""
    if not 0 <= byte <= 0xFF or clock_minutes < 0:
        raise ValueError("Invalid duration byte or clock")
    if byte == 0:
        return None
    count, unit = byte & 0x3F, byte >> 6
    if count == 0:
        raise ValueError("Nonzero duration with zero count is not measured")
    scale = (1, 10, 60, 1440)[unit]
    return count * scale - clock_minutes % scale


def exact_durations(minutes: int, clock_minutes: int) -> tuple[int, ...]:
    """Every ordinary C64 byte expiring after exactly these camp minutes."""
    if not 1 <= minutes <= 0xFFFF or clock_minutes < 0:
        raise ValueError("An expiring duration needs positive minutes and a clock")
    return tuple(byte for byte in range(1, 256) if byte & 0x3F
                 and remaining_minutes(byte, clock_minutes) == minutes)


@dataclasses.dataclass(frozen=True)
class SpellPair:
    """One spell position independently read from the two Pool tables."""

    spell: int
    dos_effect: int
    c64_camp_effect: int
    c64_camp_handler: int


def spell_pairs(c64_table: bytes, dos_image: bytes) -> tuple[SpellPair, ...]:
    """Compare the 56 spell rows, excluding the following item-only rows."""
    if len(c64_table) < 56 * 7 or len(dos_image) <= 0xC7C0 + 0x3204 + 56 * 16:
        raise ValueError("Truncated spell table")
    return tuple(SpellPair(
        spell, dos_image[0xC7C0 + 0x3204 + spell * 16],
        c64_table[(spell - 1) * 7 + 3] & 0x7F,
        int.from_bytes(c64_table[(spell - 1) * 7 + 5:spell * 7], "little"))
        for spell in range(1, 57))


def _x86(body: bytes, at: int, mnemonic: str, operands: str) -> None:
    import capstone

    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    instruction = next(decoder.disasm(body[at:at + 15], at), None)
    if instruction is None or (instruction.mnemonic, instruction.op_str) != (
            mnemonic, operands):
        raise ValueError(f"Expected {mnemonic} {operands} at DOS 0x{at:X}")


def _c64(body: bytes, at: int, opcode: int, value: int, base: int = 0xA700) -> None:
    if operand(body, base, at, opcode) != value:
        raise ValueError(f"Different operand at C64 ${at:04X}")


def confirm_pool_values(camp_spells: bytes, combat_spells: bytes,
                        camp: bytes, combat_table: bytes, dos_ovr: bytes,
                        dos_image: bytes) -> tuple[str, ...]:
    """Check the instructions establishing each Pool value comparison.

    These are individual operand measurements, not copied routines. Handler
    pointers come from the engines' own dispatch tables before their code is
    interpreted.
    """
    from tools.dos import dosracialseed

    for eid, expected in {12: 0xF115, 13: 0x11DF6, 14: 0xF231, 28: 0xF61B,
                          38: 0xF115, 39: 0xF8A6, 49: 0xFF0D}.items():
        if dosracialseed.handler_offset(dos_ovr, dos_image, eid) != expected:
            raise ValueError(f"Different DOS handler for effect {eid}")
    for eid, expected in {12: 0xA81D, 13: 0xA83F, 14: 0xA83F, 28: 0xA8FA,
                          38: 0xA81D, 39: 0xA977, 49: 0xA9B9}.items():
        lo = combat_table[0xDA63 - 0xD60A + eid]
        hi = combat_table[0xDAEE - 0xD60A + eid]
        if lo | hi << 8 != expected:
            raise ValueError(f"Different C64 handler for effect {eid}")

    _x86(dos_ovr, 0x2AF70, "cmp", "byte ptr es:[di + 4], 0")
    _c64(camp, 0x132A, 0xBD, 0x4B80, 0x0800)
    _c64(camp, 0x132D, 0x10, 0x0F, 0x0800)
    _c64(camp, 0x1430, 0xA9, 7, 0x0800)
    _c64(camp, 0x143A, 0x69, 0x99, 0x0800)
    _c64(camp_spells, 0xA79F, 0xAD, 0x28CA)
    _c64(camp_spells, 0xA7A2, 0x29, 0x7F)
    _x86(dos_ovr, 0x27A4C, "mov", "al, byte ptr [di + 0x3204]")

    _x86(dos_ovr, 0x2BFD9, "add", "ax, 0x64")
    _x86(dos_ovr, 0x2BFDF, "cmp", "byte ptr [bp + 8], 0x12")
    _x86(dos_ovr, 0x2BFE5, "mov", "al, byte ptr [bp + 6]")
    _x86(dos_ovr, 0x2BFEA, "inc", "ax")
    _x86(dos_ovr, 0x2C013, "cmp", "byte ptr es:[di], 0x65")
    _x86(dos_ovr, 0x2C017, "ja", "0x2c031")
    _x86(dos_ovr, 0x2C021, "dec", "ax")
    _x86(dos_ovr, 0xF11E, "cmp", "byte ptr es:[di + 3], 0x7f")
    _c64(camp_spells, 0xAD0B, 0x29, 0x7F)
    _c64(camp_spells, 0xAD0F, 0xC9, 101)
    _c64(camp_spells, 0xAD13, 0xE9, 100)
    _c64(camp_spells, 0xAD18, 0x8D, 0x6B1A)
    _c64(camp_spells, 0xAD1B, 0x8E, 0x6B14)
    _c64(combat_spells, 0xA827, 0xC9, 101)

    _x86(dos_ovr, 0xF237, "mov", "al, byte ptr es:[di + 3]")
    _x86(dos_ovr, 0xF23E, "mov", "byte ptr es:[di + 0x15], al")
    _c64(camp_spells, 0xAD27, 0x29, 0x7F)
    _c64(camp_spells, 0xAD29, 0x8D, 0x6B19)

    _x86(dos_ovr, 0xF627, "mov", "al, byte ptr es:[di + 3]")
    _x86(dos_ovr, 0xF670, "dec", "byte ptr es:[di + 3]")
    _c64(combat_spells, 0xA8FD, 0xBC, 0x4B80)
    _c64(combat_spells, 0xA915, 0xDE, 0x4B80)

    _x86(dos_ovr, 0xF8B3, "and", "al, 0x10")
    _x86(dos_ovr, 0xF8C2, "add", "ax, 0x10")
    _x86(dos_ovr, 0xF8EF, "inc", "word ptr es:[di + 0x30]")
    _c64(combat_spells, 0xA981, 0x29, 0x10)
    _c64(combat_spells, 0xA986, 0x09, 0x10)
    _c64(combat_spells, 0xA98B, 0xEE, 0x6B74)

    _x86(dos_ovr, 0xFF1A, "and", "al, 0x10")
    _x86(dos_ovr, 0xFF28, "mov", "al, byte ptr es:[di + 0x10e]")
    _x86(dos_ovr, 0xFF30, "jne", "0xff48")
    _x86(dos_ovr, 0xFF48, "dec", "byte ptr [0x6822]")
    for at, opcode in ((0xA9BF, 0x0A), (0xA9C0, 0x0A), (0xA9C1, 0x2A)):
        _c64(combat_spells, at, opcode, 0)
    _c64(combat_spells, 0xA9C2, 0x4D, 0x6C0C)
    _c64(combat_spells, 0xA9C5, 0x29, 1)
    _c64(combat_spells, 0xA9C7, 0xD0, 0xE9)
    _c64(combat_spells, 0xA9B2, 0xEE, 0x2AFE)
    _c64(combat_spells, 0xA9C9, 0xCE, 0x2AFE)

    # The generic path writes the caster's level unless a handler supplied
    # a value. DOS chooses that same level before passing data to add_affect.
    _c64(camp_spells, 0xA825, 0xAD, 0x2879)
    _c64(camp_spells, 0xA82A, 0xAD, 0x2878)
    _c64(camp_spells, 0xA82D, 0x9D, 0x4B80)
    _x86(dos_ovr, 0x2791B, "lcall", "0xba, 0x26c2")
    _x86(dos_ovr, 0x27920, "mov", "byte ptr [bp - 0x2a], al")
    _x86(dos_ovr, 0x27A5A, "mov", "al, byte ptr [bp - 0x2a]")
    _x86(dos_ovr, 0x2BDE6, "mov", "byte ptr es:[di + 3], al")
    return ("Generic caster level", "Strength", "Charisma", "Mirror Image",
            "Haste age marker", "Prayer allegiance", "Removal flag")


def ordinary_level_ids(pairs: tuple[SpellPair, ...]) -> tuple[int, ...]:
    """Ids whose camp handler reaches the generic caster-level slot writer."""
    return tuple(sorted({p.dos_effect for p in pairs
                         if p.dos_effect == p.c64_camp_effect != 0
                         and p.c64_camp_handler in (0xA858, 0xA85E)}))


def strength_value(dos_data: int) -> int:
    """The C64 value for one unstacked DOS strength-restore node."""
    if not 1 <= dos_data <= 0x7F:
        raise ValueError("Overlapping or invalid DOS strength data is not mapped")
    return dos_data - 1 if dos_data <= 101 else dos_data


def flagged_value(value: int, flag: int) -> int:
    """Combine a measured seven-bit value with the separate DOS boolean."""
    if not 0 <= value <= 0x7F or flag not in (0, 1):
        raise ValueError("A C64 magnitude needs seven value bits and a boolean flag")
    return value | flag << 7


def prayer_allegiance(dos_data: int) -> int:
    """The C64 bit matching DOS Prayer's combat-side comparison, alone."""
    if not 0 <= dos_data <= 0xFF:
        raise ValueError("DOS data must be a byte")
    return (1 - ((dos_data >> 4) & 1)) << 6


def load_c64(title: str, root: str | None = None) -> tuple[bytes, bytes]:
    game = c64_port.by_key(title)
    if root is None:
        found = tool_disks(game)
        if found is None:
            raise FileNotFoundError(f"No C64 disks found for {title}")
        root = str(found)
    site = SITES[title]
    return (coldread.overlay(game, site.file.encode(), root),
            coldread.overlay(game, b"LIBRARY", root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", choices=tuple(SITES), default="pool-of-radiance")
    parser.add_argument("--disks", help="Directory containing this title's C64 disks")
    parser.add_argument("--dos-dir", type=pathlib.Path,
                        help="Pool directory containing START.EXE and GAME.OVR")
    args = parser.parse_args(argv)
    try:
        game = c64_port.by_key(args.title)
        root = args.disks or tool_disks(game)
        if root is None:
            raise FileNotFoundError(f"No C64 disks found for {args.title}")
        root = str(root)
        code, library = load_c64(args.title, root)
        packing = read_packing(args.title, code, library)
    except FileNotFoundError as exc:
        print(exc)
        return 2
    site = SITES[args.title]
    print(f"CONFIRMED {args.title}: {site.file} ${site.count_test:04X}; "
          f"count limit {packing.threshold}, ratios {packing.ratios}, "
          f"unit bits {packing.units}")
    print("Arrays: " + ", ".join(f"${a:04X}" for a in packing.arrays))
    print(f"CONFIRMED Library quotient return at ${packing.divide:04X}; truncates")
    if args.title != "pool-of-radiance":
        print("UNKNOWN Effect id/data crosswalk for this title; not extrapolated")
        return 0

    from tools.dos import dosbox, unexepack

    try:
        game_dir = args.dos_dir or dosbox.find_game()
        dos_ovr = (game_dir / "GAME.OVR").read_bytes()
        dos_image, _ = unexepack.unpack((game_dir / "START.EXE").read_bytes())
    except FileNotFoundError as exc:
        print(f"No DOS engine: {exc}")
        return 2
    def read(name: str) -> bytes:
        return coldread.overlay(game, name.encode(), root)
    pairs = spell_pairs(read("ECL65"), dos_image)
    checks = confirm_pool_values(code, read("SPELLE01"), read("CAMP"),
                                 read("SPELLE65"), dos_ovr, dos_image)
    print(f"CONFIRMED {len(pairs)} spell pairs; camp-id differences: "
          + str([(p.spell, p.dos_effect, p.c64_camp_effect) for p in pairs
                 if p.dos_effect != p.c64_camp_effect]))
    print(f"CONFIRMED Generic caster-level ids: {ordinary_level_ids(pairs)}")
    print("CONFIRMED Value checks: " + ", ".join(checks))
    print("UNKNOWN Overlapping strength nodes; Prayer owner/global conversion; "
          "unlisted data encodings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

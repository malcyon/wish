#!/usr/bin/env python3
"""Read C64 duration packing and Pool effect encodings from the player's code.

The output is evidence for a conversion, not a conversion writer. Each title's
checked handlers delimit its value rules; unlisted ids remain unknown.
See docs/226-the-c64-running-effect-crosswalk.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from automap.paths import tool_disks  # noqa: E402
from goldbox import c64_port  # noqa: E402
from goldbox.effects import EFFECT_SLOTS, ENLARGE_STRENGTHS, PARTY_WIDE  # noqa: E402
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

DOS_TITLES = {"pool-of-radiance": "POOLRAD", "curse-of-the-azure-bonds": "CURSE",
              "secret-of-the-silver-blades": "SECRET"}


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


def duration_census(clock_minutes: int) -> tuple[int, int]:
    """Exact DOS minute values and worst early expiry under a floor policy.

    Enumerates the measured camp-clock model, not a conversion policy chosen
    by a writer. Zero-count encodings are excluded because they are unmeasured.
    """
    values = sorted({remaining_minutes(byte, clock_minutes)
                     for byte in range(1, 256) if byte & 0x3F})
    exact = sum(value <= 0xFFFF for value in values)
    loss = max(min(right - 1, 0xFFFF) - left
               for left, right in zip(values, values[1:]) if left <= 0xFFFF)
    return exact, loss


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


def confirm_pool_state(files: dict[str, bytes], dos_ovr: bytes) -> tuple[str, ...]:
    """Check overlapping-strength transitions and Prayer's owner predicate."""
    spells, library = files["SPELLE04"], files["LIBRARY"]
    for at, opcode, value in (
            (0xA8F4, 0x8D, 0x6B14), (0xA8FA, 0x8D, 0x6B1A),
            (0xA8FD, 0xA9, 38), (0xA8FF, 0x20, 0x3FE1),
            (0xA902, 0xB0, 0x0D), (0xA904, 0xA9, 12),
            (0xA906, 0x20, 0x3FE1), (0xA909, 0xB0, 6),
            (0xA90E, 0x4C, 0xA858), (0xA911, 0x60, 0)):
        _c64(spells, at, opcode, value)
    for at, mnemonic, operands in (
            (0x2C0D3, "cmp", "byte ptr es:[di + 3], 0x80"),
            (0x2C129, "add", "ax, 0x80"),
            (0x2C12F, "mov", "byte ptr es:[di + 3], al"),
            (0xF11E, "cmp", "byte ptr es:[di + 3], 0x7f"),
            (0xF17E, "cmp", "byte ptr es:[di], 0xc"),
            (0xF187, "cmp", "byte ptr es:[di], 0x26"),
            (0xF1B8, "ja", "0xf1c8"),
            (0xF1C6, "jbe", "0xf1e0"),
            (0xF213, "mov", "byte ptr es:[di + 3], al"),
            (0xF21D, "mov", "byte ptr es:[di + 0x10], al"),
            (0xF227, "mov", "byte ptr es:[di + 0x16], al")):
        _x86(dos_ovr, at, mnemonic, operands)
    for at, opcode, value in (
            (0x3FE1, 0xAE, 0x6DB4), (0x3FE7, 0x8E, 0x6E6F),
            (0x3FEF, 0xDD, 0x4900), (0x3FF8, 0xBD, 0x4940),
            (0x3FFB, 0x30, 0x0A), (0x3FFD, 0xCD, 0x6E6F),
            (0x4000, 0xF0, 5), (0x4005, 0x18, 0), (0x4008, 0x38, 0),
            (0x4027, 0x20, 0x3FE4)):
        _c64(library, at, opcode, value, 0x2C48)

    row = files["ECL65"][41 * 7:42 * 7]
    if len(row) != 7 or (row[2], row[3] & 0x7F) != (0x80, 35):
        raise ValueError("Different Pool camp Prayer row")
    for at, opcode, value in ((0xA703, 0x38, 0), (0xA704, 0x30, 0x0A),
                              (0xA710, 0xA9, 0xFF), (0xA81C, 0x9D, 0x4940)):
        _c64(spells, at, opcode, value)
    _c64(files["CAMP"], 0x1415, 0x8D, 0x28DE, 0x0800)
    _c64(files["COMBAT"], 0x28A4, 0xAE, 0x6DB4, 0x0800)
    _c64(files["COMBAT"], 0x28A7, 0x4C, 0x4027, 0x0800)
    for at, opcode, value in ((0x077A, 0x20, 0x28A4), (0x077E, 0xB0, 0x0B),
                              (0x078B, 0xAE, 0x6E6E), (0x0791, 0xBD, 0xDA63),
                              (0x0797, 0xBD, 0xDAEE)):
        _c64(files["SQRPACI01"], at, opcode, value, 0x0400)
    from tools.c64 import traitquery

    decoded = traitquery.read_lists(files["SPELLE65"], 0x570, 139)
    if (decoded is None or len(decoded[0]) != 20
            or any(49 not in decoded[0][i] for i in (10, 12))
            or any(35 in row for row in decoded[0])):
        raise ValueError("Different Pool Prayer check lists")
    return ("Strength stacking differs", "Prayer character-owner route")


#: Pool of Radiance's camp expiry dispatch, which `ECL65` holds immediately
#: after its 469-byte spell table: the ids, then the handler's low and high
#: bytes. `CAMP $12FD` walks the ids until one matches `$6E6E`.
POOL_EXPIRY_IDS = 0x9AD5
POOL_EXPIRY_LOW = 0x9AEE
POOL_EXPIRY_HIGH = 0x9B06
POOL_EXPIRY_ENTRIES = 24


def pool_expiry_handlers(ecl65: bytes) -> dict[int, int]:
    """Pool's expiry handler per effect id, read off the table after the
    spell rows."""
    count = POOL_EXPIRY_ENTRIES
    start = POOL_EXPIRY_IDS - 0x9900
    ids = ecl65[start:start + count + 1]               # the walk stops at a zero
    low = ecl65[POOL_EXPIRY_LOW - 0x9900:][:count]
    high = ecl65[POOL_EXPIRY_HIGH - 0x9900:][:count]
    if len(ids) != count + 1 or len(low) != count or len(high) != count:
        raise ValueError("The Pool expiry table runs off the end of ECL65")
    if ids[count]:
        raise ValueError(f"A {count + 1}th Pool expiry id, {ids[count]}")
    out = {eid: lo | hi << 8 for eid, lo, hi in zip(ids, low, high)}
    if len(out) != count or 0 in out:
        raise ValueError(f"{len(out)} distinct Pool expiry ids, not {count}")
    return out


def confirm_pool_expiry(camp: bytes, spells: bytes,
                        ecl65: bytes) -> tuple[str, ...]:
    """Check that Pool expires each slot on its own, for that slot's owner.

    The cast refuses a second strength node, and this is the other half of
    that: the sweep and the handler read one slot at a time, so the arrays
    themselves hold as many strength restores as a writer stages.
    """
    for at, opcode, value in (                        # the sweep, 63 down to 0
            (0x1299, 0xA2, EFFECT_SLOTS - 1), (0x129E, 0xBD, 0x4900),
            (0x12A3, 0xBD, 0x4980), (0x12AE, 0x9D, 0x4980),
            (0x12B4, 0x20, 0x131F), (0x12BA, 0xCA, 0), (0x12BB, 0x10, 0xDE),
            (0x131F, 0xBD, 0x4900), (0x1322, 0x8D, 0x6E6E),  # this slot's id
            (0x1327, 0x9D, 0x4900), (0x132A, 0xBD, 0x4B80),  # and magnitude
            (0x132D, 0x10, 0x0F), (0x132F, 0x8D, 0x28E7),
            (0x1332, 0xBD, 0x4940), (0x1335, 0x8D, 0x28DE),  # and owner
            (0x1338, 0x20, 0x0FC8), (0x133B, 0x20, 0x12F8),
            (0x0FC8, 0x8D, 0x6DB4), (0x0FCE, 0x30, 5),       # owner selects
            (0x0FD0, 0x20, 0x4415),                          # the character
            (0x12FD, 0xBD, POOL_EXPIRY_IDS), (0x1302, 0xCD, 0x6E6E),
            (0x130A, 0xBD, POOL_EXPIRY_LOW), (0x1310, 0xBD, POOL_EXPIRY_HIGH),
            (0x1316, 0xAD, 0x28E7)):                  # magnitude in A
        _c64(camp, at, opcode, value, 0x0800)
    handlers = pool_expiry_handlers(ecl65)
    if handlers.get(38) != 0xAD0B or handlers.get(12) != 0xAD0B:
        raise ValueError("Pool's strength ids no longer share the restore handler")
    for at, opcode, value in (                        # the restore itself
            (0xAD0B, 0x29, 0x7F), (0xAD0D, 0xA2, 0x12), (0xAD0F, 0xC9, 101),
            (0xAD13, 0xE9, 100), (0xAD18, 0x8D, 0x6B1A), (0xAD1B, 0x8E, 0x6B14)):
        _c64(spells, at, opcode, value)
    return ("One expiry call per slot", "The slot's own owner and magnitude",
            "Ids 38 and 12 share the restore handler")


def confirm_later_values(title: str, combat: bytes, table: bytes,
                         dos_ovr: bytes, dos_image: bytes) -> tuple[str, ...]:
    """Check each later title's own combat handlers, including an unmapped case."""
    from tools.dos import dosracialseed

    if title == "curse-of-the-azure-bonds":
        handlers = {28: (0x10626, 0x20DC), 39: (0x10A8C, 0x2201),
                    49: (0x110B0, 0x2264)}
        low, high = 0xEE2A, 0xEEBC
        haste = (0x10A99, 0x10AA8, 0x10AD5, "0x76", 0x220B)
        prayer = (0x110BD, 0x110CB, "0x197", 0x110D3, "0x110eb", 0x226A)
        mirror_load, mirror_dec = 0x20DF, 0x20F2
    elif title == "secret-of-the-silver-blades":
        handlers = {28: (0x1174E, 0x25F1), 39: (0x11CCD, 0x2752),
                    49: (0x122B3, 0x27BD)}
        low, high = 0xEF90, 0xF001
        haste = (0x11CE0, 0x11CEF, 0x11D23, "0x6e", 0x275C)
        prayer = (0x122C8, 0x122DB, "0x1a8", 0x122E3, "0x122fa", 0x27C3)
        mirror_load, mirror_dec = 0x25FB, 0x260E
    else:
        raise ValueError(f"Later-title value rules are not mapped for {title}")
    for eid, (dos_at, c64_at) in handlers.items():
        if dosracialseed.handler_offset(dos_ovr, dos_image, eid) != dos_at:
            raise ValueError(f"Different DOS handler for effect {eid}")
        if (table[low - 0xE000 + eid] | table[high - 0xE000 + eid] << 8) != c64_at:
            raise ValueError(f"Different C64 handler for effect {eid}")

    test, mark, age, age_field, c64 = haste
    _x86(dos_ovr, test, "and", "al, 0x10")
    _x86(dos_ovr, mark, "add", "ax, 0x10")
    _x86(dos_ovr, age, "inc", f"word ptr es:[di + {age_field}]")
    for step, opcode, value in ((0, 0x29, 0x10), (5, 0x09, 0x10),
                               (7, 0x9D, 0x4D80), (10, 0xEE, 0x7C74),
                               (15, 0xEE, 0x7C75)):
        _c64(combat, c64 + step, opcode, value, 0x0800)

    test, side, side_field, branch, target, c64 = prayer
    _x86(dos_ovr, test, "and", "al, 0x10")
    _x86(dos_ovr, side, "mov", f"al, byte ptr es:[di + {side_field}]")
    _x86(dos_ovr, branch, "jne", target)
    for step, opcode, value in ((0, 0x0A, 0), (1, 0x0A, 0), (2, 0x2A, 0),
                               (3, 0x4D, 0x7D0C), (6, 0x29, 1),
                               (8, 0xF0, 0xE9), (-13, 0xEE, 0xA903),
                               (-10, 0xEE, 0xA915), (13, 0xCE, 0xA915)):
        _c64(combat, c64 + step, opcode, value, 0x0800)

    _c64(combat, mirror_load, 0xBC, 0x4D80, 0x0800)
    _c64(combat, mirror_dec, 0xDE, 0x4D80, 0x0800)
    _c64(combat, mirror_dec + 3, 0xD0, 0x14, 0x0800)
    if title == "curse-of-the-azure-bonds":
        _x86(dos_ovr, 0x10638, "mov", "cl, 4")
        _x86(dos_ovr, 0x1063A, "shr", "ax, cl")
        _x86(dos_ovr, 0x1067F, "dec", "byte ptr es:[di + 3]")
        _x86(dos_ovr, 0x10686, "cmp", "byte ptr es:[di + 3], 0")
        mirror = "Mirror Image raw-decrement mismatch"
    else:
        for at, mnemonic, operands in (
                (0x117D7, "mov", "cx, 4"), (0x117DA, "shr", "ax, cl"),
                (0x117DF, "dec", "byte ptr [bp - 1]"),
                (0x117E2, "cmp", "byte ptr [bp - 1], 0"),
                (0x11807, "mov", "cx, 4"), (0x1180A, "shl", "ax, cl"),
                (0x11816, "and", "al, 0xf"), (0x11818, "or", "al, byte ptr [bp - 1]"),
                (0x1181E, "mov", "byte ptr es:[di + 3], al")):
            _x86(dos_ovr, at, mnemonic, operands)
        mirror = "Mirror Image count"
    return ("Haste age marker", "Prayer allegiance", mirror)


@dataclasses.dataclass(frozen=True)
class SlotSite:
    """Where one title keeps the allocator every cast goes through."""

    search: int
    ids: int
    owners: int
    cast_file: str
    cast_base: int
    cast_match: int
    cast_free: int
    durations: int
    new_duration: int
    compare: int
    replace_at: int
    abandon_at: int
    value_write: int
    value: int
    level: int
    magnitudes: int


SLOTS = {
    "pool-of-radiance": SlotSite(
        0x3FE4, 0x4900, 0x4940, "SPELLE04", 0xA700, 0xA7F1, 0xA80A,
        0x4980, 0x2871, 0xA7F6, 0xA807, 0xA830, 0xA825, 0x2879, 0x2878, 0x4B80),
    "curse-of-the-azure-bonds": SlotSite(
        0x409F, 0x4B00, 0x4B40, "ECL65", 0x8000, 0x813E, 0x8156,
        0x4B80, 0x2BF4, 0x8143, 0x815F, 0x817C, 0x8171, 0x2BFC, 0x2BFB, 0x4D80),
    "secret-of-the-silver-blades": SlotSite(
        0x3854, 0x4B00, 0x4B40, "ECL65", 0x8000, 0x813E, 0x8156,
        0x4B80, 0x2A67, 0x8143, 0x815F, 0x817C, 0x8171, 0x2A6F, 0x2A6E, 0x4D80),
}


def confirm_slot_rule(title: str, library: bytes, cast: bytes) -> tuple[str, ...]:
    """Check the allocator's own scan direction, owner test and free-slot call.

    One routine in all three engines: it walks slot 63 down to 0 for an id and
    an owner, taking a negative owner as a match for any query, and the cast
    calls it twice -- once for the pair it is about to write and once with id 0
    and owner `$FF` for a free slot.
    """
    site, base = SLOTS[title], SITES[title].library_base
    for step, opcode, value in (
            (0, 0x8D, 0), (3, 0x8E, 0), (6, 0xA2, EFFECT_SLOTS - 1),
            (11, 0xDD, site.ids), (14, 0xD0, 0x0E), (16, 0xC9, 0),
            (18, 0xF0, 0x0F), (20, 0xBD, site.owners), (23, 0x30, 0x0A),
            (25, 0xCD, 0), (28, 0xF0, 5), (30, 0xCA, 0), (31, 0x10, 0xE7),
            (33, 0x18, 0), (34, 0x60, 0)):
        at = site.search + step
        got = operand(library, base, at, opcode)
        if value and got != value:
            raise ValueError(f"Different allocator operand at ${at:04X}")
    _c64(cast, site.cast_match, 0x20, site.search, site.cast_base)
    _c64(cast, site.cast_free, 0xA9, 0, site.cast_base)
    _c64(cast, site.cast_free + 2, 0xA2, PARTY_WIDE, site.cast_base)
    _c64(cast, site.cast_free + 4, 0x20, site.search, site.cast_base)
    slot_compare(title, cast)
    # A value byte of zero is replaced by the caster's level on its way into
    # the magnitude array, so no cast can leave a zero magnitude behind.
    _c64(cast, site.value_write, 0xAD, site.value, site.cast_base)
    _c64(cast, site.value_write + 3, 0xD0, 3, site.cast_base)
    _c64(cast, site.value_write + 5, 0xAD, site.level, site.cast_base)
    _c64(cast, site.value_write + 8, 0x9D, site.magnitudes, site.cast_base)
    return ("Highest free slot", "One slot per id and owner",
            "A negative owner matches any query",
            "The larger duration byte keeps the slot, and zero is not larger",
            "A zero value becomes the caster's level")


def slot_compare(title: str, cast: bytes) -> tuple[tuple[str, int], ...]:
    """Where each of the cast's four duration tests goes, in the cast's code.

    A cast that finds its own (id, owner) already in a slot compares the two
    **duration bytes**: a new byte of zero takes the slot, an old byte of zero
    keeps it, and otherwise the numerically larger byte wins with a tie going
    to the new cast. `goldbox.effects.replaces_slot` is that rule.
    """
    site, at = SLOTS[title], SLOTS[title].compare
    pool = title == "pool-of-radiance"
    _c64(cast, at, 0xAD, site.new_duration, site.cast_base)
    _c64(cast, at + 5, 0xBD, site.durations, site.cast_base)
    _c64(cast, at + 10, 0xCD, site.new_duration, site.cast_base)
    tests = ((3, 0xF0, site.replace_at), (8, 0xF0, site.abandon_at)) + (
        ((13, 0xF0, site.replace_at), (15, 0xB0, site.abandon_at)) if pool else
        ((13, 0x90, site.replace_at), (15, 0xF0, site.replace_at),
         (17, 0xB0, site.abandon_at)))
    out = []
    for step, opcode, target in tests:
        here = at + step
        offset = operand(cast, site.cast_base, here, opcode)
        went = here + 2 + (offset - 256 if offset > 127 else offset)
        if went != target:
            raise ValueError(f"Branch at ${here:04X} goes to ${went:04X}")
        out.append((f"${here:04X}", went))
    return tuple(out)


@dataclasses.dataclass(frozen=True)
class AbilitySite:
    """One later title's ability-effect packing, recompute and DOS twin."""

    packer: int
    enlarge: int
    friends: int
    strength: int
    mirror: int
    roll: int
    level: int
    magnitude: int
    value_helper: int
    strength_recompute: int
    charisma_recompute: int
    enlarge_read: int
    strengths: int
    percentiles: int
    dice: tuple[int, int]
    dos_mirror_shift: int
    dos_friends: int
    dos_strength_add: int
    dos_strength_id: int
    dos_enlarge_ladder: int
    dos_enlarge_field: str
    dos_strength_ladder: int
    dos_times_ten: tuple[tuple[str, str], ...]
    dos_enlarge_change: int


ABILITIES = {
    "curse-of-the-azure-bonds": AbilitySite(
        0x8241, 0x8214, 0x8231, 0x828D, 0x8282, 0x8068, 0x2BFB, 0x2BFC,
        0x9797, 0x9175, 0x9733, 0x91D1, 0x9223, 0x922F, (0xE3, 0x4D),
        0x30710, 0x30199, 0x30D8C, 0x30D98, 0x2FFCD, "0x4ccd",
        0x30D3A, (("mov", "dx, 0xa"), ("mul", "dx")), 0x30068),
    "secret-of-the-silver-blades": AbilitySite(
        0x828A, 0x825D, 0x827A, 0x82D6, 0x82CB, 0x8068, 0x2A6E, 0x2A6F,
        0x99EA, 0x9647, 0x9990, 0x969D, 0x96E9, 0x96F5, (0x145, 0x43),
        0x2EF75, 0x2E9DF, 0x2F5D2, 0x2F5DE, 0x2E80D, "0x64d8",
        0x2F580, (("mov", "cx, 0xa"), ("imul", "cx")), 0x2E8AF),
}

#: Where both later titles keep the score in force and the class levels the
#: Strength cast picks its die from, in the staged record at `$7C00`.
LATER_STRENGTH = 0x7C14
LATER_PERCENTILE = 0x7C1A
LATER_CLASS_LEVELS = 0x7CC9

#: What Enlarge sets strength to by caster level, read off both ports.
ENLARGE_TABLE = bytes.fromhex("12 12 12 12 12 12 13 14 15 16 17 18")
ENLARGE_PERCENTILES = bytes.fromhex("00 01 33 4c 5b 64 00 00 00 00 00 00")


def confirm_later_ability_values(title: str, ecl65: bytes,
                                 dos_ovr: bytes) -> tuple[str, ...]:
    """Check each later title's ability packing against its DOS twin.

    The later titles derive the score in force from the permanent one, so a
    magnitude holds a modifier: the bonus one less than itself in the upper
    nibble, the caster's level in the low one and bit 7 set. Mirror Image is
    the one id that packs no level on the C64 and does on DOS.
    """
    site = ABILITIES[title]
    for step in range(4):                       # the bonus into the top nibble
        _c64(ecl65, site.packer + step, 0x0A, 0, 0x8000)
    _c64(ecl65, site.packer + 4, 0x0D, site.level, 0x8000)
    _c64(ecl65, site.packer + 7, 0x09, 0x80, 0x8000)
    _c64(ecl65, site.packer + 9, 0x8D, site.magnitude, 0x8000)

    _c64(ecl65, site.enlarge, 0xAD, site.level, 0x8000)
    _c64(ecl65, site.enlarge + 3, 0x09, 0x80, 0x8000)
    _c64(ecl65, site.enlarge + 5, 0x8D, site.magnitude, 0x8000)

    _c64(ecl65, site.roll, 0xA2, 4, 0x8000)     # the d4 both casts roll
    for at, count in ((site.friends, 2), (site.mirror, 1)):
        _c64(ecl65, at, 0xA9, count, 0x8000)
        _c64(ecl65, at + 2, 0x20, site.roll, 0x8000)
    _c64(ecl65, site.friends + 6, 0xE9, 1, 0x8000)
    _c64(ecl65, site.friends + 8, 0x20, site.packer, 0x8000)
    _c64(ecl65, site.mirror + 5, 0x8D, site.magnitude, 0x8000)

    _c64(ecl65, site.value_helper + 5, 0xBD, 0x4D80, 0x8000)
    _c64(ecl65, site.value_helper + 8, 0x29, 0x7F, 0x8000)
    for step in range(10, 14):                  # four shifts: the top nibble
        _c64(ecl65, site.value_helper + step, 0x4A, 0, 0x8000)
    _c64(ecl65, site.strength_recompute, 0xA9, 38, 0x8000)
    _c64(ecl65, site.strength_recompute + 2, 0x20, site.value_helper, 0x8000)
    _c64(ecl65, site.charisma_recompute, 0xA9, 14, 0x8000)
    _c64(ecl65, site.charisma_recompute + 2, 0x20, site.value_helper, 0x8000)
    _c64(ecl65, site.charisma_recompute + 7, 0xEE, 0x7C19, 0x8000)
    _c64(ecl65, site.charisma_recompute + 11, 0x6D, 0x7C19, 0x8000)

    _c64(ecl65, site.enlarge_read, 0xBD, 0x4D80, 0x8000)
    _c64(ecl65, site.enlarge_read + 3, 0x29, 0x0F, 0x8000)
    _c64(ecl65, site.enlarge_read + 5, 0xC9, 10, 0x8000)
    _c64(ecl65, site.enlarge_read + 12, 0xE9, 1, 0x8000)
    for at, expected in ((site.strengths, ENLARGE_TABLE),
                         (site.percentiles, ENLARGE_PERCENTILES)):
        if ecl65[at - 0x8000:at - 0x8000 + len(expected)] != expected:
            raise ValueError(f"Different Enlarge table at ${at:04X}")
    strength_cast_steps(title, ecl65)
    strength_ladder(title, ecl65)

    unit, entry = site.dice
    _x86(dos_ovr, site.dos_mirror_shift - 0x0D, "mov", "al, 1")
    _x86(dos_ovr, site.dos_mirror_shift - 0x0A, "mov", "al, 4")
    _x86(dos_ovr, site.dos_mirror_shift - 7, "lcall", f"{hex(unit)}, {hex(entry)}")
    _x86(dos_ovr, site.dos_mirror_shift, "mov", "cx, 4")
    _x86(dos_ovr, site.dos_mirror_shift + 3, "shl", "ax, cl")
    _x86(dos_ovr, site.dos_friends, "mov", "al, 2")
    _x86(dos_ovr, site.dos_friends + 3, "mov", "al, 4")
    _x86(dos_ovr, site.dos_friends + 6, "lcall", f"{hex(unit)}, {hex(entry)}")
    _x86(dos_ovr, site.dos_strength_add, "add", "ax, 0x64")
    _x86(dos_ovr, site.dos_strength_id, "mov", "al, 0x26")
    _x86(dos_ovr, site.dos_enlarge_ladder, "mov",
         f"byte ptr [{site.dos_enlarge_field}], 0x12")
    _x86(dos_ovr, site.dos_enlarge_change, "or", "al, al")
    dos_strength_arrival(title, dos_ovr)
    if dos_enlarge_ladder(title, dos_ovr) != ENLARGE_STRENGTHS:
        raise ValueError("Different DOS Enlarge ladder")
    return ("Strength bonus in the top nibble", "Friends bonus in the top nibble",
            "Enlarge level in the low nibble", "Mirror Image count alone",
            "The two ports' Enlarge tables agree")


def strength_cast_steps(title: str, ecl65: bytes) -> None:
    """Check that the Strength cast packs one less than the die it rolled.

    It takes the highest nonzero class level as the class index, rolls that
    class's die, and passes the roll **decremented** to the packer -- which is
    the other half of the recompute applying one more step than the nibble
    holds.
    """
    site = ABILITIES[title]
    _c64(ecl65, site.strength, 0xA2, 7, 0x8000)
    _c64(ecl65, site.strength + 2, 0xBD, LATER_CLASS_LEVELS, 0x8000)
    _c64(ecl65, site.strength + 7, 0xCA, 0, 0x8000)      # down through the eight
    _c64(ecl65, site.strength + 19, 0xCA, 0, 0x8000)     # the roll, less one
    _c64(ecl65, site.strength + 20, 0x8A, 0, 0x8000)
    _c64(ecl65, site.strength + 21, 0x20, site.packer, 0x8000)


def strength_ladder(title: str, ecl65: bytes) -> None:
    """Check the recompute's ladder step and the loop that runs it.

    One step is `+1` below 18 and `+10` percentile at it; 90 to 99 becomes 100
    and 18/100 is where it stops. The loop count is the operand of an `LDA #`
    the routine writes to itself, so the ladder climbs one more step than the
    magnitude's nibble holds.
    """
    site, at = ABILITIES[title], ABILITIES[title].strength_recompute
    counter = at + 66                                   # the LDA # operand byte
    for step, opcode, value in (
            (0, 0xA9, 38), (2, 0x20, site.value_helper), (7, 0x8D, counter),
            (10, 0xA9, 0x12), (12, 0xA2, 100), (14, 0xCD, LATER_STRENGTH),
            (21, 0xEC, LATER_PERCENTILE), (28, 0xAD, LATER_STRENGTH),
            (31, 0xC9, 0x12), (35, 0xEE, LATER_STRENGTH), (38, 0xA9, 0),
            (42, 0xAD, LATER_PERCENTILE), (45, 0xC9, 100), (49, 0xC9, 90),
            (53, 0xA9, 100), (57, 0x69, 10), (59, 0x8D, LATER_PERCENTILE),
            (62, 0xCE, counter), (65, 0xA9, 0xFF), (67, 0x10, 0xC2)):
        _c64(ecl65, at + step, opcode, value, 0x8000)


def dos_strength_arrival(title: str, dos_ovr: bytes) -> None:
    """Check the DOS cast's closed form for the same ladder, and its clamp.

    `(new - 18) * 10 + the old percentile`, clamped to 100. The clamp is why
    `goldbox.effects.lower_strength` has no answer at 18/100: the node keeps
    the die roll rather than the steps the clamp let through.
    """
    site, at = ABILITIES[title], ABILITIES[title].dos_strength_ladder
    _x86(dos_ovr, at, "mov", "al, byte ptr [bp - 7]")
    _x86(dos_ovr, at + 5, "sub", "ax, 0x12")
    for step, (mnemonic, operands) in zip((8, 11), site.dos_times_ten):
        _x86(dos_ovr, at + step, mnemonic, operands)
    _x86(dos_ovr, at + 18, "mov", "al, byte ptr es:[di + 0x1c]")
    _x86(dos_ovr, at + 24, "add", "ax, dx")
    _x86(dos_ovr, at + 29, "cmp", "byte ptr [bp - 5], 0x64")
    _x86(dos_ovr, at + 35, "mov", "byte ptr [bp - 5], 0x64")


def dos_enlarge_ladder(title: str, dos_ovr: bytes) -> tuple[tuple[int, int], ...]:
    """The scores the DOS Enlarge cast writes, by caster level 1 to 10.

    The cast writes 18/00 into its two scratch bytes and then a ladder of
    `cmp al, <level>` tests overwrites one of them. A level past the ladder's
    last test leaves the 18/00 it started with; levels 10 and 11 share the
    last entry.
    """
    import capstone

    site = ABILITIES[title]
    at, field = site.dos_enlarge_ladder, int(site.dos_enlarge_field, 0)
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    head: list[int | None] = [None, None]
    pending: list[int] = []
    out: dict[int, tuple[int, int]] = {}
    for instruction in decoder.disasm(dos_ovr[at:at + 0xA0], at):
        mnemonic, operands = instruction.mnemonic, instruction.op_str
        if mnemonic == "cmp" and operands.startswith("al, "):
            pending.append(int(operands.split(", ")[1], 0))
        elif mnemonic == "jmp":
            pending = []
        elif mnemonic == "mov" and operands.startswith("byte ptr ["):
            where, _, value = operands.partition("], ")
            index = {f"byte ptr [{field:#x}": 0,
                     f"byte ptr [{field + 1:#x}": 1}.get(where)
            if index is None:
                continue
            if not pending:
                head[index] = int(value, 0)
                continue
            if None in head:
                raise ValueError("The DOS Enlarge ladder writes before its default")
            score = list(head)
            score[index] = int(value, 0)
            for level in pending:
                out[level] = (score[0], score[1])
        if len(out) >= 11:
            break
    if sorted(out) != list(range(1, 12)):
        raise ValueError(f"The DOS Enlarge ladder has levels {sorted(out)}")
    return tuple(out[level] for level in range(1, 11))


def mirror_zero_roll(title: str, combat: bytes, library: bytes) -> int:
    """Check what a later title's Mirror Image does with a magnitude of zero.

    The handler puts the magnitude in Y and asks the shared `random(0..Y)`
    helper for the image that absorbs the hit; only a nonzero answer costs an
    image and only that decrement removes the slot. With Y zero the helper
    returns zero, so a zero magnitude absorbs nothing and never expires. The
    engines' own casts cannot write one (`confirm_slot_rule`), which is why
    `goldbox.effects.mirror_image_count` of a spent DOS Curse node has no C64
    magnitude to be.
    """
    load = {"curse-of-the-azure-bonds": 0x20DF,
            "secret-of-the-silver-blades": 0x25FB}[title]
    _c64(combat, load - 3, 0xAE, 0x7F78, 0x0800)
    _c64(combat, load, 0xBC, 0x4D80, 0x0800)
    roll = operand(combat, 0x0800, load + 3, 0x20)
    _c64(combat, load + 6, 0xF0, 0x24, 0x0800)        # a zero roll absorbs none
    _c64(library, roll, 0x98, 0, 0x2DC8)              # TYA, the count into A
    at = roll + 1
    if library[at - 0x2DC8] == 0xD0:                  # Curse tests both ways
        at += 2
    straight = at + 2 + operand(library, 0x2DC8, at, 0xF0)
    _c64(library, straight, 0x8D, 0x03C8, 0x2DC8)     # a zero count stores zero
    return roll


def mirror_image_value(title: str, dos_data: int) -> int:
    """The remaining image count a DOS node holds, for either port's reading.

    Pool of Radiance keeps it in the whole data byte; Curse of the Azure Bonds
    and Secret of the Silver Blades keep it in the upper nibble, which is what
    both casts write and both selection rolls read. Curse's own handler then
    decrements the whole byte instead of the nibble, so its count falls by one
    on the first absorbed hit and then only every sixteenth -- a defect in that
    engine, not a second meaning for the byte.
    """
    if not 0 <= dos_data <= 0xFF:
        raise ValueError("DOS data must be a byte")
    if title not in SITES:
        raise ValueError(f"Mirror Image is not mapped for {title}")
    return dos_data if title == "pool-of-radiance" else dos_data >> 4


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


def prayer_allegiance(dos_data: int, *, title: str = "pool-of-radiance") -> int:
    """The C64 bit matching DOS Prayer's combat-side comparison, alone."""
    if not 0 <= dos_data <= 0xFF:
        raise ValueError("DOS data must be a byte")
    if title not in SITES:
        raise ValueError(f"Prayer is not mapped for {title}")
    side = (dos_data >> 4) & 1
    return (side ^ (title == "pool-of-radiance")) << 6


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
                        help="DOS directory containing START.EXE and GAME.OVR")
    parser.add_argument("--clock-minutes", type=int, default=0,
                        help="Destination camp-clock minutes for the duration census")
    args = parser.parse_args(argv)
    if args.clock_minutes < 0:
        parser.error("Clock minutes must be zero or greater (--clock-minutes)")
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
    exact, loss = duration_census(args.clock_minutes)
    print(f"CONFIRMED Camp-clock arithmetic at {args.clock_minutes} minutes: "
          f"{exact}/65535 exact durations; floor-policy loss at most {loss} minutes")

    from tools.dos import dosbox, unexepack

    try:
        game_dir = args.dos_dir or dosbox.find_game(DOS_TITLES[args.title])
        dos_ovr = (game_dir / "GAME.OVR").read_bytes()
        dos_image, _ = unexepack.unpack((game_dir / "START.EXE").read_bytes())
    except FileNotFoundError as exc:
        print(f"No DOS engine: {exc}")
        return 2
    def read(name: str) -> bytes:
        return coldread.overlay(game, name.encode(), root)
    slots = confirm_slot_rule(args.title, library,
                              code if args.title == "pool-of-radiance"
                              else read("ECL65"))
    print("CONFIRMED Slot rule: " + ", ".join(slots))
    if args.title != "pool-of-radiance":
        checks = confirm_later_values(args.title, read("COMBAT"), read("COMBAT2"),
                                      dos_ovr, dos_image)
        print("CONFIRMED Value checks: " + ", ".join(checks))
        abilities = confirm_later_ability_values(args.title, read("ECL65"), dos_ovr)
        print("CONFIRMED Ability checks: " + ", ".join(abilities))
        roll = mirror_zero_roll(args.title, read("COMBAT"), library)
        print(f"CONFIRMED Mirror Image rolls through ${roll:04X}; "
              "a zero magnitude absorbs nothing and never expires")
        print("UNKNOWN Prayer global merging and all unlisted ids")
        return 0
    files = {"SPELLE04": code, "LIBRARY": library}
    files.update({name: read(name) for name in (
        "ECL65", "SPELLE01", "CAMP", "SPELLE65", "COMBAT", "SQRPACI01")})
    pairs = spell_pairs(files["ECL65"], dos_image)
    checks = confirm_pool_values(code, files["SPELLE01"], files["CAMP"],
                                 files["SPELLE65"], dos_ovr, dos_image)
    states = confirm_pool_state(files, dos_ovr)
    expiry = confirm_pool_expiry(files["CAMP"], code, files["ECL65"])
    print("CONFIRMED Expiry: " + ", ".join(expiry))
    print(f"CONFIRMED {len(pairs)} spell pairs; camp-id differences: "
          + str([(p.spell, p.dos_effect, p.c64_camp_effect) for p in pairs
                 if p.dos_effect != p.c64_camp_effect]))
    print(f"CONFIRMED Generic caster-level ids: {ordinary_level_ids(pairs)}")
    print("CONFIRMED Value checks: " + ", ".join(checks))
    print("CONFIRMED State checks: " + ", ".join(states))
    print("UNKNOWN Strength-chain timeline conversion; Prayer global merging; "
          "all unlisted data encodings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

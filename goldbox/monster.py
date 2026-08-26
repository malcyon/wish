"""Attacks and the experience award, read off a character record.

Every creature in the game -- a goblin as much as a fighter -- is one 580-byte
character record, so this is not a monster-only decode; a level-1 player
character reads here as one unarmed 1d2 attack, which `GEN $0BBE` writes.

**The offsets are literals rather than `goldbox/layout.py` fields.** The layout
carries `0x0D9`-`0x0E0` as one named block, `attack_forms`, because the sheet
has no box for a monster's attack table; this view is where it is read apart.
The reading itself is CONFIRMED --
`COMBAT $0CAD` rolls damage through `LDA $6C13,Y` / `LDX $6C15,Y` with a stride
of 2, which is what proves there are exactly two attack forms, and twenty
creatures match the *Monster Manual*. Full write-up in
`work/reports/disasm-batch.md`.

Read `0x0D9`-`0x0E0`, never the working copies at `0x111`-`0x118`: in a shipped
`MON*` file those are stale scratch -- `MON61 BANDIT` holds the ASCII of an
unrelated string there.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

# One attack form is five bytes, spread across five parallel two-entry arrays.
FORMS = 2
ATTACKS_X2 = 0x0D9        # attacks per round, doubled
DAMAGE_DICE = 0x0DB
DAMAGE_DIE = 0x0DD
DAMAGE_MODIFIER = 0x0DF   # signed

XP_BASE = 0x0F7           # 16-bit little-endian
XP_PER_HP = 0x0F9

SAVING_THROWS = (
    ("paralysis, poison and death", "save_paralysis"),
    ("petrification and polymorph", "save_petrification"),
    ("rod, staff and wand", "save_wands"),
    ("breath weapon", "save_breath"),
    ("spell", "save_spell"),
)


@dataclass(frozen=True)
class Attack:
    """One of the two attack forms: how often, and for how much."""

    form: int
    per_round_x2: int
    dice: int
    die: int
    modifier: int

    @property
    def exists(self) -> bool:
        return bool(self.per_round_x2 and self.dice and self.die)

    @property
    def per_round(self) -> Fraction:
        """`COMBAT $12EC` adds the round's parity before halving, so an odd
        stored value really is AD&D's 3/2 attacks per round and not a rounding
        error: 3 gives one attack on even rounds and two on odd."""
        return Fraction(self.per_round_x2, 2)

    @property
    def rate_text(self) -> str:
        rate = self.per_round
        return (f"{rate.numerator}/{rate.denominator}" if rate.denominator != 1
                else str(rate.numerator))

    @property
    def damage_text(self) -> str:
        sign = "" if not self.modifier else f"{self.modifier:+d}"
        return f"{self.dice}d{self.die}{sign}"

    @property
    def text(self) -> str:
        rate = self.rate_text
        word = "attack" if rate == "1" else "attacks"
        return f"{rate} {word} per round ({self.damage_text})"


def _byte(record, offset: int) -> int:
    return record.slice(offset, 1)[0]


def _signed(value: int) -> int:
    return value - 256 if value > 127 else value


def attacks(record) -> tuple[Attack, ...]:
    """The attack forms this creature actually has, in order."""
    out = []
    for form in range(FORMS):
        attack = Attack(
            form=form,
            per_round_x2=_byte(record, ATTACKS_X2 + form),
            dice=_byte(record, DAMAGE_DICE + form),
            die=_byte(record, DAMAGE_DIE + form),
            modifier=_signed(_byte(record, DAMAGE_MODIFIER + form)),
        )
        if attack.exists:
            out.append(attack)
    return tuple(out)


def experience_award(record, hp_max: int | None = None) -> int:
    """What killing this creature is worth.

    `POST.COM $09BB`: a 16-bit base plus a per-hit-point rate times the
    creature's maximum hit points, which is how AD&D expresses an award.
    """
    base = _byte(record, XP_BASE) | (_byte(record, XP_BASE + 1) << 8)
    if hp_max is None:
        hp_max = record.get("hp_max")
    return base + _byte(record, XP_PER_HP) * hp_max


def saving_throws(record) -> tuple[tuple[str, int], ...]:
    """The five saves, as (what against, the number to roll)."""
    return tuple((label, record.get(field)) for label, field in SAVING_THROWS)

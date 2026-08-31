"""What the dice did, beside what the game printed.

`combatlog.py` keeps the line the game *prints* -- `BRUTUS ATTACKS ORC AND HITS
FOR 7 POINTS OF DAMAGE`. This is what the game *rolled*, which is a different
thing and is shown nowhere: the d20, the number it had to reach, and the dice
the damage came off. No Qt in here, the same way `combat.py` has none.

Every address is from `docs/147-combat-rolls.md`, measured on a static read of
`COMBAT` plus two driven slums fights.

| where | what |
|---|---|
| `$2B10` | the d20. **20 is stored as 100**, and on a natural 1 it is not written |
| `$A4F0` | the number the roll had to reach, `60 - AC` of the target plus modifiers |
| `$A4F4` / `$A4F5` | acting combatant / target, 0-7 the party and 8 upward monsters |
| `$A4F8` | the damage |
| `$A4F9` / `$A4FA` | attempts and landings in this action, cleared at `COMBAT $11AC` |
| `$A4FB` | the hit flag |

## The dice come from the battle roster and nowhere else

`$0CFE` calls `$2744` to make the **target** resident, so after an attack lands
`$6C13`/`$6C15`/`$6C17` are the target's attack table and `$6C0E` is the
target's THAC0. Both would give a plausible wrong answer rather than an obvious
one. Everything about the attacker is therefore read from its own roster block
at `$8300 + index * 32`, where `RosterBlock` already decodes THAC0, armour
class and `1d8+5`.

`needed` is `THAC0 of the attacker - AC of the target`, which is the AD&D rule
and reproduces both worked examples in `docs/147`: BRUTUS THAC0 18 against an
orc's AC 6 is 12, and an orc's THAC0 19 against BRUTUS' AC 2 is 17. It is
computed from the two roster blocks rather than from `$A4F0 - $6C0E` because
`$6C0E` is the resident block, and after a hit the resident block is the
target's.

## A roll is shown only when it can be tied to the message

The rolls are read in the same poll as the message but are not inherently tied
to it, and a line that confidently names the wrong attacker is worse than no
line. `roll_line` therefore prints nothing unless **all** of these hold:

* the message says its subject hit or missed -- `AND HITS FOR` or `AND MISSES`;
* the acting combatant `$A4F4` names is the combatant the message names;
* `$A4FB` agrees with the message about whether it landed;
* on a hit, `$A4F8` is the number the message printed.

## A natural 1 is named, never numbered

`COMBAT $127F CMP #$01 / BEQ $12AF` returns before the store at `$1289`, so on
a natural 1 `$2B10` still holds the *previous* attack's roll. The tell is an
arithmetic contradiction: the attack missed, and the number in `$2B10` would
have hit. That catches every natural 1 whose stale value is at or above the
number needed, and cannot catch one whose stale value would have missed anyway
-- there is nothing in memory that distinguishes that case, and it prints the
stale number as though it were real. PROBABLE, from the code: no natural 1 came
up in either driven fight, and the first one seen in a running game promotes or
refutes it.

## Rolls that were never seen

Two attacks resolved between two polls collapse to the last one, and the first
one's message is painted over as well, so neither is recovered. `$A4F9` counts
attempts within an action, so a jump of more than one says how many were
missed: `RollWatch` counts them and `Roll.missed` carries the number to
whichever message comes next.

**It is never shown to the player.** Donald's ruling, 2026-08-31: the roll line
says the roll and no more. The count goes to the debug log instead, which is
where this project already puts a number that is about the reverse engineering
rather than about the game -- the same call that moved the loaded-files readout
off the bottom strip. It is kept rather than deleted because it is the only
measure of how much the poll rate loses, and that is worth knowing when the
feature is doubted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from goldbox.savegame import ROSTER_STRIDE, SAVE1_LOAD_ADDRESS, RosterBlock

#: `COMBAT $1289`. One byte, and 20 is stored as 100.
D20 = 0x2B10
NATURAL_20 = 100
D20_SIDES = 20

#: `$A4F0`-`$A4FB`: everything about the attack in progress, in one range.
ATTACK = 0xA4F0
ATTACK_LEN = 0x0C
# `$A4F0` itself -- the number the roll had to reach -- has deliberately no
# offset here, because nothing reads it. `needed` is `THAC0 of the attacker -
# AC of the target`, computed from the two roster blocks: the alternative,
# `$A4F0 - $6C0E`, subtracts the *resident* block's THAC0, and after a hit the
# resident block is the target's. A constant sitting beside `ACTOR` and
# `DAMAGE` reads as though the code touched the byte, and it does not.
ACTOR = 0xA4F4 - ATTACK
TARGET = 0xA4F5 - ATTACK
DAMAGE = 0xA4F8 - ATTACK
ATTEMPTS = 0xA4F9 - ATTACK
LANDINGS = 0xA4FA - ATTACK
HIT = 0xA4FB - ATTACK

#: The battle roster: 64 blocks of 32 bytes filling `$8300`-`$8AFF`, the same
#: table `combat.read_battle` reads. Read whole because the block wanted is
#: named by `$A4F4`, which arrives in the same burst.
ROSTER = SAVE1_LOAD_ADDRESS
ROSTER_BLOCKS = 64
ROSTER_LEN = ROSTER_BLOCKS * ROSTER_STRIDE


@dataclass(frozen=True)
class Roll:
    """One reading of the attack bytes, with the attacker's own numbers.

    `raw` is `$2B10` as it stood; `d20` is it decoded, and None where the byte
    cannot be a d20 at all. `needed` and `dice` are None where the roster block
    they would come from is empty.
    """

    raw: int
    actor: int
    target: int
    hit: bool
    damage: int
    attempts: int
    landings: int
    needed: int | None = None
    dice: str | None = None
    #: Attempts that resolved between two polls and were never seen.
    missed: int = 0

    @property
    def d20(self) -> int | None:
        """`$2B10` as a die roll. 100 is a natural 20; nothing else above 20
        can be one, and a stale byte often is not."""
        if self.raw == NATURAL_20:
            return D20_SIDES
        return self.raw if 1 <= self.raw <= D20_SIDES else None

    @property
    def natural_one(self) -> bool:
        """The attack missed and the number in `$2B10` would have hit it.

        Nothing else writes that contradiction: `$1289` stores the roll the
        comparison at `$12B1` then uses, so a roll that reached `needed` and
        missed is a roll that was never stored.
        """
        if self.hit or self.needed is None:
            return False
        return self.d20 is not None and self.d20 >= self.needed


def _block(roster: bytes, index: int) -> RosterBlock | None:
    at = index * ROSTER_STRIDE
    if index < 0 or at + ROSTER_STRIDE > len(roster):
        return None
    block = RosterBlock(bytearray(roster), index)
    return block if block.occupied else None


def _dice(block: RosterBlock, damage: int) -> str | None:
    """The attacker's primary attack, as `1d8+5`, when it could have rolled
    this damage.

    The range check is the guard against reading the wrong block: `1d8+5` can
    produce 6 to 13 and nothing else, so damage outside that says the dice and
    the damage do not belong together and the clause is left off rather than
    printed wrong.
    """
    dice, die, bonus = block.damage_dice, block.damage_die, block.damage_bonus
    if not dice or not die:
        return None
    if not dice + bonus <= damage <= dice * die + bonus:
        return None
    return block.damage


def read(d20: bytes, state: bytes, roster: bytes) -> Roll | None:
    """A `Roll` from the three ranges, or None if they are too short."""
    if len(d20) < 1 or len(state) < ATTACK_LEN:
        return None
    actor, target = state[ACTOR], state[TARGET]
    roll = Roll(raw=d20[0], actor=actor, target=target,
                hit=bool(state[HIT]), damage=state[DAMAGE],
                attempts=state[ATTEMPTS], landings=state[LANDINGS])
    attacker, defender = _block(roster, actor), _block(roster, target)
    if attacker is None or defender is None:
        return roll
    return replace(roll, needed=attacker.thac0 - defender.armour_class,
                   dice=_dice(attacker, roll.damage))


class RollWatch:
    """Counts the attempts that resolved between two polls.

    `$A4F9` is cleared per action at `COMBAT $11AC` and stepped per attempt at
    `$1222`, so it going up by more than one, or starting an action above one,
    is exactly the rolls polling did not see.
    """

    def __init__(self) -> None:
        self._attempts = 0
        self._missed = 0

    def update(self, roll: Roll | None) -> None:
        """One poll's reading. Call on every poll, not only on a new message."""
        if roll is None:
            return
        now, before = roll.attempts, self._attempts
        if now > before:
            self._missed += now - before - 1
        elif now < before:
            self._missed += max(0, now - 1)     # a fresh action, already past 1
        self._attempts = now

    def take(self) -> int:
        """How many have been missed since this was last asked."""
        missed, self._missed = self._missed, 0
        return missed

    def reset(self) -> None:
        """Forget the fight that just ended.

        `$A4F9` is cleared per action, so it counts within one fight and
        carries no meaning across two. Left at the value the last fight ended
        on, the first poll of the next fight can read the same number back --
        `update` then sees `now == before`, takes neither branch, and a real
        missed roll is never counted.
        """
        self._attempts = 0
        self._missed = 0


def claimed_hit(text: str) -> bool | None:
    """What the message says its own subject's attack did, or None.

    `AND HITS FOR` and `AND MISSES` are the game's own phrases, out of the
    `SPELLN00` table. `IS HIT FOR` is deliberately not one of them: its subject
    is the target rather than the attacker.
    """
    if "AND MISSES" in text:
        return False
    if "AND HITS FOR" in text:
        return True
    return None


def matches(roll: Roll | None, msg, names: dict[int, str]) -> bool:
    """Does this roll belong to this message? Four checks, all required."""
    if roll is None or not msg.subject:
        return False
    landed = claimed_hit(msg.text)
    if landed is None or landed != roll.hit:
        return False
    who = names.get(roll.actor)
    if not who or who.strip().upper() != msg.subject.strip().upper():
        return False
    if landed and msg.damage is not None and msg.damage != roll.damage:
        return False
    return roll.needed is not None


def roll_line(msg, names: dict[int, str]) -> str | None:
    """The line to show under a message, or None where nothing can be shown.

    Donald's wording, settled on #139:

        BRUTUS rolled 19, needed 12, 1d8+5 = 7
        ORC rolled 4, needed 17
        BRUTUS rolled a natural 1
    """
    roll = getattr(msg, "roll", None)
    if not matches(roll, msg, names):
        return None
    who = msg.subject.strip()
    if roll.natural_one:
        return f"{who} rolled a natural 1"
    if roll.d20 is None:
        return None                 # the byte cannot be a d20; say nothing
    line = f"{who} rolled {roll.d20}, needed {roll.needed}"
    if roll.hit and roll.dice:
        line += f", {roll.dice} = {roll.damage}"
    return line

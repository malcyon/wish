"""A thief's backstab damage multiplier, worked out from a character record.

No port stores it: every engine computes ``((effective thief level - 1) div 4)
+ 2`` when it rolls the damage, and this is that arithmetic with each title's
and port's differences kept apart (`docs/225-the-dos-backstab-multiplier.md`,
and `docs/221-thief-abilities-in-dos-pool-of-radiance.md` for DOS Pool of
Radiance).  Only the damage multiplier is computed; the to-hit adjustment the
engines also make is not read well enough to reproduce.

Nothing here reads a file or a disk, and nothing is written.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from . import titles

__all__ = ["backstab_multiplier", "effective_thief_level", "PORTS", "RULES"]

#: The ports a rule is measured for, in the names `NeutralCharacter.port` uses.
PORTS = ("DOS", "C64", "Amiga")

_SUM = "sum"
_MAX = "max"


@dataclasses.dataclass(frozen=True)
class Rule:
    """One title's arithmetic on one port."""

    #: How the thief slot and the former thief slot combine: `"sum"` adds the
    #: former level once regained, `"max"` takes the larger, and None means the
    #: title's arithmetic reads the current thief slot alone.
    former: str | None
    #: Taken off the level before the division by four; Pool of Radiance on DOS
    #: and the Amiga subtracts nothing, so its steps fall at 4, 8 and 12.
    subtract: int = 1
    #: The effective level is held at this before the arithmetic.
    level_cap: int | None = None
    #: The multiplier is held at this after the arithmetic.
    multiplier_cap: int | None = None


#: One row per (title key, port) whose rule was read from the engine.
RULES: dict[tuple[str, str], Rule] = {
    # DOS.  Pool of Radiance keeps no former-class array; Curse and Silver
    # Blades add the regained former slot; Pools of Darkness takes the larger
    # and clamps the multiplier.
    ("pool-of-radiance", "DOS"): Rule(former=None, subtract=0),
    ("curse-of-the-azure-bonds", "DOS"): Rule(former=_SUM),
    ("secret-of-the-silver-blades", "DOS"): Rule(former=_SUM),
    ("pools-of-darkness", "DOS"): Rule(former=_MAX, multiplier_cap=5),
    # C64.  The current thief slot is the whole answer: Curse, Silver Blades
    # and Gateway have a generic dual-class regain that writes the old level
    # back into it, and Pool of Radiance, Champions and Death Knights have no
    # such path that has been found.  Two titles clamp the level at 14.
    ("pool-of-radiance", "C64"): Rule(former=None),
    ("curse-of-the-azure-bonds", "C64"): Rule(former=None),
    ("secret-of-the-silver-blades", "C64"): Rule(former=None, level_cap=14),
    ("gateway-to-the-savage-frontier", "C64"): Rule(former=None),
    ("champions-of-krynn", "C64"): Rule(former=None),
    ("death-knights-of-krynn", "C64"): Rule(former=None, level_cap=14),
    # Amiga.  Each port computes what its DOS counterpart computes.
    ("pool-of-radiance", "Amiga"): Rule(former=None, subtract=0),
    ("curse-of-the-azure-bonds", "Amiga"): Rule(former=_SUM),
    ("secret-of-the-silver-blades", "Amiga"): Rule(former=_SUM),
    ("pools-of-darkness", "Amiga"): Rule(former=_MAX, multiplier_cap=5),
}


def _key(title: Any) -> str | None:
    """A title's key from a key, or from any object carrying one."""
    if title is None:
        return None
    return title if isinstance(title, str) else getattr(title, "key", None)


def _is_human(char: Any, title_key: str) -> bool:
    """Whether the record's race code names a human.

    The code is an index into the table of the title the record was made in,
    so it is read in the record's own `game` table when it has one, and in the
    resolved title's otherwise.
    """
    game_key = _key(getattr(char, "game", None))
    if game_key not in titles.BY_KEY:
        game_key = title_key
    try:
        names = titles.by_key(game_key).race_names
    except titles.UnknownTitleError:
        return False
    return bool(names) and names.get(char.get("race")) == "human"


def _regained(char: Any, title_key: str, former_thief: int) -> bool:
    """Whether a human's new class has passed the level he left thief at.

    The engine's active class is the first positive entry of the level
    array whose class the character has not left -- a DOS record never
    holds a current level in a class named in `former_levels`, so a class
    that appears in both is the stale, about-to-be-zeroed one and never the
    active one. The rule accepts only a strictly greater level than the one
    he left thief at.
    """
    if not former_thief or not _is_human(char, title_key):
        return False
    former = char.get("former_levels") or {}
    active = next((v for k, v in (char.get("levels") or {}).items()
                   if v and k not in former), 0)
    return active > former_thief


def effective_thief_level(char: Any, title: Any = None,
                          port: str | None = None) -> int:
    """The thief level the engine feeds its arithmetic, after any level cap.

    0 means the engine finds no thief, so there is no backstab; a record with
    no `levels` and one with a thief level of 0 are not told apart.
    """
    rule, title_key = _rule(char, title, port)
    thief = int((char.get("levels") or {}).get("thief") or 0)
    former_thief = int((char.get("former_levels") or {}).get("thief") or 0)
    regained = (rule.former is not None
                and _regained(char, title_key, former_thief))
    if rule.former == _SUM:
        level = thief + former_thief * regained
    elif rule.former == _MAX:
        level = max(thief, former_thief * regained)
    else:
        level = thief
    if rule.level_cap is not None:
        level = min(level, rule.level_cap)
    return level


def _rule(char: Any, title: Any, port: str | None) -> tuple[Rule, str]:
    title_key = (_key(title) or _key(getattr(char, "game", None))
                 or titles.DEFAULT.key)
    port = port or getattr(char, "port", None)
    try:
        return RULES[(title_key, port)], title_key
    except KeyError:
        raise ValueError(
            f"no backstab rule is read for title {title_key!r} on port "
            f"{port!r}; the rules cover {sorted(RULES)}") from None


def backstab_multiplier(char: Any, title: Any = None,
                        port: str | None = None) -> int | None:
    """The factor a thief's backstab multiplies rolled damage by, or None.

    `char` is a `NeutralCharacter` or anything with its `get`, read for
    `levels`, `former_levels` and `race`.  `title` is a `goldbox.titles` key
    and `port` one of :data:`PORTS`; each defaults to the record's own `game`
    and `port`, and a record with no `game` is Pool of Radiance's, as
    `NeutralCharacter` documents.  None means the engine's thief gate is
    closed -- no current thief level, and no former one regained -- so the
    character has no backstab; a missing `levels` and a thief level of 0 are
    the same.  A pair with no measured rule raises ValueError rather than
    borrowing a neighbour's.

    An override chooses the rule and is valid only for a record already in
    that title's and port's form: the race code is read in the record's own
    `game` table, and a record from another port that stores the former slot
    differently would be counted twice.

    Unpinned rules, by the engine instructions read: the Amiga Pools of
    Darkness class-level routine is not read at all, so taking the larger of
    the current and former slot, and the regain test, are unestablished there;
    the Amiga Pool of Radiance multiply callee is inferred from its operands;
    the Amiga Curse and Silver Blades regain test is taken to be the DOS one
    because the instructions were matched and not the routine; that no C64 Pool
    of Radiance, Champions or Death Knights path regains a former thief is
    PROBABLE; and whether anything else clamps in DOS Curse and Silver Blades
    is not read.  Pools of Darkness on DOS taking the larger of the two slots
    agrees with the sum only on records no engine writes.  The rest is read
    from the instructions.
    """
    rule, _ = _rule(char, title, port)
    level = effective_thief_level(char, title, port)
    if level <= 0:
        return None
    multiplier = (level - rule.subtract) // 4 + 2
    if rule.multiplier_cap is not None:
        multiplier = min(multiplier, rule.multiplier_cap)
    return multiplier

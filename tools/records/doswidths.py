#!/usr/bin/env python3
"""Boundary characters and field widths for the DOS writer, for `tests/records/test_boundary.py`.

`tools/records/boundarywidths.py` is this for `goldbox.c64_codec.write`; this
is the same idea for `goldbox.dos_codec.write`, in all four titles it writes.
The widths are the DOS record's own, so a scalar's range is read off
`goldbox.dos_port.FIELDS_BY_NAME_FOR` and the set of scalars off
`dos_codec.write_targets`, never typed: a field whose width the table changes
moves here with it.

The characters are read as though off a C64 record (`port="C64"`), because
that is what a conversion into DOS receives and it is the port that makes the
writer recompute thief skills and spell slots through DOS's own tables.

    tools/records/doswidths.py

prints every title's scalars with the range of the DOS field each lands in.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import dos_codec, dos_port, levels
from goldbox.neutral import NeutralCharacter
from tools.records import boundarychars, boundarywidths

#: The four titles `goldbox.dos_codec.write` builds a record for.
GAMES = tuple(s.key for s in dos_codec.WRITES)

#: How `write_targets` words a target that is taken from a neutral field.
_FROM_NEUTRAL = re.compile(r"from neutral (\w+)")


@dataclasses.dataclass(frozen=True)
class Scalar:
    """One neutral field the DOS writer copies into a single numeric field."""

    neutral: str
    dos: str
    size: int
    low: int
    high: int


#: What the boundary is for every numeric DOS target that is not a simple copy
#: of one neutral scalar, one sentence each, keyed by the neutral field the
#: writer takes it from.  `tests/records/test_boundary.py` fails on a numeric
#: target in `dos_codec.write_targets` whose neutral field is in neither this
#: table nor `scalars()`, so a field added to the writer has to say what its
#: extreme is.
STRUCTURED: dict[str, str] = {
    "name": "the count byte is the length of the name, 0 to 15, and is "
            "computed from it rather than being set",
    "levels": "attack_level is worked out from the class levels through the "
              "title's own rule, and never copied, except in Pools of "
              "Darkness, where no rule has been measured and the source's "
              "own byte is copied as a one-byte number",
    "size_small": "DOS stores size_small plus one, so the neutral ceiling is "
                  "one under the byte's own, and 255 is clamped with a "
                  "line naming `size`",
    "class_bits": "a bitmask, the ranger's bit 7 folded onto DOS's bit 6, so "
                  "255 comes back as 127; only one past a byte is a width",
    "former_levels": "the one level a dual-classed character left, again in "
                     "its own byte, taken from the class it left",
    "paladin_cures": "the source's own byte, or the class rule's when the "
                     "source has none; the boundary base character sets none, "
                     "so `test_boundary.py` sets one directly",
}

#: Neutral fields the writer recomputes on every character, so a value set on
#: one never reaches its byte and neither a round trip nor a value past its
#: width says anything about it.  Reasons are the writer's own.
ALWAYS_RECOMPUTED: dict[str, str] = {
    "thac0_base": "recomputed from the class levels through the title's own "
                  "DOS table",
    "char_class": "recomputed from the class mask when the source record "
                  "contradicts itself",
    "attack_level": "the destination's own rule from the class levels: the "
                    "constant 1 in DOS Pool of Radiance, the best fighting "
                    "level floored at 1 in Curse and Silver Blades; Pools of "
                    "Darkness has no such field",
    "spells_castable": "recomputed from the class levels and wisdom through "
                       "DOS's own table for a C64 source, whose engine "
                       "never stores one",
}

#: The five saves, always recomputed for a C64 source on the titles whose DOS
#: load-time save rebuild has been read -- `levels.LevelTables.
#: dos_save_rule_read`: Pool of Radiance, Curse of the Azure Bonds and Secret
#: of the Silver Blades. Pools of Darkness still copies the source's own byte.
_LOAD_REBUILT_SAVES: dict[str, str] = {
    "save_paralysis": "the DOS engine recomputes all five saves on load "
                      "from class, level and the class rebuild's own table, "
                      "for a C64 source",
    "save_petrification": "see save_paralysis",
    "save_wands": "see save_paralysis",
    "save_breath": "see save_paralysis",
    "save_spell": "see save_paralysis",
}

#: Current THAC0, always recomputed for a C64 source on the titles in
#: `dos_codec._UNARMED_THAC0_REBUILD_TITLES` -- Curse alone.
_LOAD_REBUILT_THAC0: dict[str, str] = {
    "thac0_current": "recomputed through DOS Curse's own unarmed combat "
                     "rebuild for a C64 source, the same as thac0_base",
}

#: Everything the writer may recompute for some character, which is a longer
#: list than the one above: the eight thief percentages when the character has
#: a thief level, and the five saves and current THAC0 on the titles
#: `always_recomputed` leaves them out for, where nothing forces the
#: recompute but a C64 source's own class or race could still make one land
#: there some day. `tests/records/
#: test_boundary.py` part A's four cases include all of those, so it leaves
#: the whole set out of the round trip by name.
RECOMPUTED: dict[str, str] = {
    **ALWAYS_RECOMPUTED,
    **_LOAD_REBUILT_SAVES,
    **_LOAD_REBUILT_THAC0,
    **{name: "recomputed from the title's own thief table for race, level "
             "and dexterity, for a character with a thief level"
       for name, _ in dos_codec.WRITE_DIRECT if name.startswith("thief_")},
}


def always_recomputed(game: str) -> dict[str, str]:
    """`ALWAYS_RECOMPUTED` as it holds in `game`: the five saves join it on
    every title whose DOS load-time save rebuild has been read, and current
    THAC0 on the titles whose unarmed combat rebuild has."""
    out = dict(ALWAYS_RECOMPUTED)
    if levels.for_game(game).dos_save_rule_read:
        out |= _LOAD_REBUILT_SAVES
    if game in dos_codec._UNARMED_THAC0_REBUILD_TITLES:
        out |= _LOAD_REBUILT_THAC0
    return out


def scalars(game: str) -> list[Scalar]:
    """Every numeric DOS target `game`'s writer copies one neutral scalar into.

    A target counts when `write_targets` says `from neutral <name>`, the DOS
    field is a number, and the neutral field is not one `STRUCTURED` gives its
    own sentence.  Read from the tables rather than typed.
    """
    table = dos_port.FIELDS_BY_NAME_FOR[game]
    out = []
    for dos_name, why in dos_codec.write_targets(game).items():
        m = _FROM_NEUTRAL.match(why)
        if not m or dos_name not in table:
            continue
        neutral = m.group(1)
        f = table[dos_name]
        span = boundarywidths.value_range(f.kind, f.size)
        if span is None or neutral in STRUCTURED:
            continue
        out.append(Scalar(neutral, dos_name, f.size, *span))
    return out


def structured_targets(game: str) -> dict[str, str]:
    """The numeric DOS targets `scalars` leaves out, by DOS name, with the
    neutral field each is taken from."""
    table = dos_port.FIELDS_BY_NAME_FOR[game]
    plain = {s.dos for s in scalars(game)}
    out = {}
    for dos_name, why in dos_codec.write_targets(game).items():
        m = _FROM_NEUTRAL.match(why)
        f = table.get(dos_name)
        if (m and f is not None and dos_name not in plain
                and boundarywidths.value_range(f.kind, f.size) is not None):
            out[dos_name] = m.group(1)
    return out


def c64_sourced(char: NeutralCharacter, game: str | None = None
                ) -> NeutralCharacter:
    """`char` as a C64 record would hand it to the DOS writer.

    The inverse of `boundarywidths.dos_sourced`: same values, `port="C64"`.
    Nothing else changes, because the base character the two share is a
    player character with no control byte, which is what both writers take.
    """
    out = NeutralCharacter("C64", source=char.source, game=game or char.game)
    out.fields = dict(char.fields)
    return out


def base(game: str) -> NeutralCharacter:
    """An unremarkable character in `game`, read off a C64 record."""
    return boundarychars._base(game)


def main(argv=None) -> int:
    for game in GAMES:
        print(game)
        skipped = RECOMPUTED
        for s in scalars(game):
            note = f"  ({skipped[s.neutral]})" if s.neutral in skipped else ""
            print(f"  {s.neutral:26} {s.low:>7} .. {s.high:<10}{note}")
        for dos_name, neutral in structured_targets(game).items():
            note = f"  ({skipped[dos_name]})" if dos_name in skipped else ""
            print(f"  {dos_name:26} structured, from {neutral}{note}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

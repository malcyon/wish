"""Helpers `test_neutral` shares with the test files that reuse them."""
from __future__ import annotations

from goldbox import c64_codec
from goldbox.layout import Confidence
from goldbox.neutral import NeutralCharacter, Provenance


def _filled(game=None) -> NeutralCharacter:
    """A neutral character with a different value in every field, so a value
    landing in the wrong place cannot pass."""
    char = NeutralCharacter("test", source="a made-up character", game=game)
    char.set("name", "ROUNDTRIP", "made up", Confidence.CONFIRMED,
             Provenance.RESHAPED)
    for n, (field, _) in enumerate(c64_codec.DIRECT):
        char.set(field, n + 1, f"made up, value {n + 1}")
    # `level`, the aggregate field, lands at 20 from this loop (index 19) --
    # made up like every other field here and free to disagree with whatever
    # `levels` or `former_levels` a caller sets afterwards.
    # `race` chooses the infravision the writer computes; keep it in range.
    char.set("race", 1, "made up: elf")
    char.set("spells_known", [1, 5, 55], "made up")
    char.set("spells_memorised", [44, 21, 3], "made up")
    char.set("levels", {"fighter": 7, "thief": 3}, "made up")
    char.set("spells_castable", {"cleric": (3, 2, 1),
                                 "magic-user": (4, 3, 2)}, "made up")
    char.set("size_small", 1, "made up")
    char.set("turn_power", 6, "made up")
    char.set("attack_forms", bytes(range(1, 9)), "made up")
    char.set("innate_effects", [18, 47], "made up")
    char.set("inventory", [bytes(range(16))], "made up")
    char.set("roster_tail", bytes(range(9)), "made up")
    # A real choice, not zero: `0x00` is `HEAD00`, the menu's own first
    # entry, and a source that never set the field at all is a different
    # fact from a source that chose it (#503, A C64 character with no sheet
    # portrait arrives in DOS or on the Amiga wearing the menu's first
    # head) -- so a fixture meant to catch a value landing in the wrong
    # place has to give the writer one to place.
    char.set("portrait_head", 0x08, "made up")
    char.set("portrait_body", 0x04, "made up")
    return char

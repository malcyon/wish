"""A Gold Box title's own rules -- races, classes -- apart from any platform
it shipped on.

`goldbox/games.py` used to be the only place these lived, folded in with the
C64 save container's own geometry. That worked while every title had a C64
port; Pools of Darkness never shipped on the C64, so it had nowhere to put a
races tuple or a class-bits tuple at all, and every lookup for it silently
answered Pool of Radiance's (`#460 (goldbox/games.py has no Pools of Darkness
entry, so every lookup answers with Pool of Radiance's tables for it)`).

**A `Title` is what a title's own rules are, whatever machine reads them.**
`goldbox/c64_port.py` still holds the six C64 titles' save-container geometry --
`BY_KEY` there stays six entries, and `c64_port.BY_KEY.get("pools-of-darkness")`
is `None` on purpose, because Pools of Darkness has no C64 container -- but
each `Game` row now takes its `races` and `class_bits` from here, so the
tuple is defined once and a `Game`'s is the very same object as its `Title`'s.

Building this module is `#470 (Give the project a neutral title beside its
neutral character record, with one port per platform a title shipped on)`,
stage 1 of nine. `Title.title` is the display name; `#470`'s comment of
2026-09-09 ("D1 answered") settles it as `title` rather than `name` and says
why, so it is not renamed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import dos_port

# --- race codes -------------------------------------------------------------
# The record's race byte at 0x072 (C64) / 0x02E (DOS) indexes a table of names
# the game itself carries, and that table is NOT the same in every title. Each
# list below was read off the player's disks twice over, from two independent
# places, and then checked against the six-character party each title ships
# inside its own save.
#
# Where the table lives:
#
# * Pool of Radiance, Curse and Gateway keep it in `LIBRARY`, reached through a
#   pointer table the resident code indexes with `LDA table,X / STA $07`. Base
#   $2C48 for Pool of Radiance and $2DC8 for the other two -- fitted, not read,
#   by scoring how many of the 66-odd pointers land on a string start (63 of 66
#   at $2C48 against 14 at the next best).
# * Silver Blades and the two Krynn titles fold the labels into `ITEMNAMES`'s
#   own 256-entry string pool, at pool index `140 + race`.
#
# And what generation offers: `GEN` carries the character-creation menu, and in
# Pool of Radiance, Curse and Gateway it is followed by the six bytes
# `01 02 03 04 05 07` -- the menu-entry-to-race-code map, which is why human is
# 7 in all three even though only six races can be rolled. Silver Blades and
# the Krynn titles have no such array, so their menu order *is* the code order.
#
# CONFIRMED for all six: every one of the 36 shipped pre-generated characters
# decodes to a race its class allows. The decisive ones are the rule cases --
# a paladin or a Knight of Solamnia must be human, a ranger human or half-elf --
# and Champions' TRAPSPRINGER, race 5, who is a kender by name.

#: Pool of Radiance and Gateway to the Savage Frontier, identically.
RACES_FORGOTTEN_REALMS = ((1, "dwarf"), (2, "elf"), (3, "gnome"),
                          (4, "half-elf"), (5, "halfling"), (6, "half-orc"),
                          (7, "human"), (8, "monster"))

#: Curse drops half-orc from generation but keeps human at 7: its label table
#: points BOTH 6 and 7 at HUMAN. 6 is left out here on purpose -- naming it
#: "half-orc" would contradict what the game prints, and naming it "human"
#: would give two codes one name and let an import silently rewrite a 7 as a 6.
#: A Pool of Radiance half-orc converted across shows as a bare `6`, which is the
#: honest answer.
RACES_CURSE = ((1, "dwarf"), (2, "elf"), (3, "gnome"), (4, "half-elf"),
               (5, "halfling"), (7, "human"), (8, "monster"))

#: Silver Blades drops half-orc and re-orders the rest, so human moves to 6.
#: Codes 1-6 are the generation menu in menu order; 0 also prints ELF.
#:
#: **7 was added for #470.** It is not a difference between the two games:
#: `LIBRARY $306A` folds race 7 and above to the MONSTER label, 50 of the
#: title's 71 C64 `MON*` records read 7, and `DosDeltas.race_numbers` for
#: this title says `monster` at 7 too -- so this table was simply missing the
#: entry, and a Silver Blades record at race 7 showed as a bare `7` instead of
#: MONSTER. See `#470`'s comment of 2026-09-09, "Question 2 settled".
RACES_SILVER_BLADES = ((1, "elf"), (2, "half-elf"), (3, "dwarf"),
                       (4, "gnome"), (5, "halfling"), (6, "human"),
                       (7, "monster"))

#: Krynn: a different list entirely, and the only one that is **0-based** --
#: Death Knights' CELESTE is race 0, which is why 0 had to be a real race
#: rather than the "monster" it is in the Realms titles.
RACES_KRYNN = ((0, "silvanesti elf"), (1, "qualinesti elf"), (2, "half-elf"),
               (3, "mountain dwarf"), (4, "hill dwarf"), (5, "kender"),
               (6, "human"))

#: Pools of Darkness has no C64 port, so this is not read off a C64 `LIBRARY`
#: like the six above -- it is built from `dos_port.POOLS_OF_DARKNESS_RACE_NUMBERS`,
#: the string table read out of the title's own `GAME.EXE`
#: (`#237 (The DOS race table is one table for four titles, and it is wrong for two of them)`), as pairs:
#: 0 = elf .. 6 = monster.
RACES_POOLS_OF_DARKNESS = tuple(
    enumerate(dos_port.POOLS_OF_DARKNESS_RACE_NUMBERS))

# --- class bits -------------------------------------------------------------
# 0x0EB, one bit per class. The low four are the whole story in Pool of
# Radiance; the later titles add classes above them.
#
# **The bit number is the slot number in the per-class level array**, and that
# array is eight bytes at 0x0C9-0x0D0, not four. Bit 4 is the knight at 0x0CD,
# bit 6 the paladin at 0x0CF, bit 7 the ranger at 0x0D0 -- so
# `class_bits == sum(1 << i for every non-zero slot i)` holds uniformly, on all
# 36 shipped characters in all six titles. It is a cross-title check, not a
# Pool of Radiance quirk, and `tests/test_gametables.py` asserts it.
#
# (An early report, since lost, said the rule fails for the
# 0x10/0x40/0x80 classes. It read only the first four slots of an eight-slot
# array; the levels are in the slots it did not read.)
CLASS_BITS_CLASSIC = ((1, "magic-user"), (2, "cleric"), (4, "thief"),
                      (8, "fighter"))

#: Curse, Silver Blades and Gateway. CONFIRMED for Curse, whose shipped party
#: has two characters literally named PALADIN (0x40) and RANGER (0x80); the
#: same two names sit at the same places in all three titles' label tables.
#:
#: Pools of Darkness has no C64 port and no class-bit table of its own read
#: off any disk; it shares this one, since it is the DOS engine directly
#: descended from Curse and Silver Blades' -- a standalone table in
#: `goldbox/amiga.py` said the same thing before
#: `#470 (Give the project a neutral title beside its neutral character
#: record, with one port per platform a title shipped on)`'s stage 2 deleted
#: it in favour of this row.
CLASS_BITS_WITH_PALADIN_RANGER = CLASS_BITS_CLASSIC + ((0x40, "paladin"),
                                                       (0x80, "ranger"))

#: Krynn adds the Knight of Solamnia at 0x10. PROBABLE: Champions' STRONGSWORD
#: and Death Knights' SIR DRYDEN are single-class 0x10, lawful good, and the
#: label pool carries KNIGHT and KNIGHT OF THE ROSE.
CLASS_BITS_KRYNN = CLASS_BITS_CLASSIC + ((0x10, "knight"), (0x40, "paladin"),
                                         (0x80, "ranger"))


@dataclass(frozen=True)
class Title:
    """One Gold Box title's own rules -- races, classes -- regardless of
    which machine's save a codec is reading.

    `races` and `class_bits` are pairs rather than dicts so the descriptor
    stays hashable and frozen; either may be `None`, and `None` means "we do
    not know", not "there are none" -- a caller that gets `None` must show
    the raw number rather than invent a name for it.
    """

    key: str                       # stable identifier, written into the YAML
    title: str                     # what a person calls it
    races: tuple[tuple[int, str], ...] | None = None
    class_bits: tuple[tuple[int, str], ...] | None = None

    #: Does this title have a square-engine overland at all? **True for Pool
    #: of Radiance only.** Curse of the Azure Bonds and Secret of the Silver
    #: Blades carry no `SQRDATA`, `SQRPACI` or `WALLS` on either side of any
    #: disk (`docs/121-silver-blades.md`, "No city-block/wilderness
    #: structure"), so `$49E6` and `$49C3` there would be read as this
    #: title's meaning of bytes that belong to something else -- a plausible
    #: wrong square, which `automap.target.party_fix` refuses to answer rather
    #: than guess at. See `automap.c64.C64Machine.indoors_flag_base` and
    #: `travel_position_base`, which are None wherever this is False.
    #:
    #: The status line's own `OUTDOORS` pattern is a different question and
    #: is not gated by this: `#205 (A party that walks out onto the travel
    #: grid leaves the automapper's marker behind)` found the literal string
    #: in both titles' `DUNGEON` overlay (`tools/outdoorsgrep.py`), sitting
    #: among other short message fragments (`EXIT`, `SEARCH`, `" IS "`)
    #: rather than proven to be a status-line reading -- open, and needs a
    #: driven session, not this table.
    #:
    #: It lives here rather than on the C64 container because it is a fact
    #: about the title's own rules; `#470`'s stage 6 moved the callers on to
    #: it, and `goldbox.c64_port.Game.travel_grid` is a read-through that
    #: stage 9 deletes.
    travel_grid: bool = False

    @property
    def race_names(self) -> dict[int, str] | None:
        """Race code -> name, or None when this title's list is unknown."""
        return None if self.races is None else dict(self.races)

    @property
    def class_bit_names(self) -> dict[int, str] | None:
        """Class bit -> name, or None when this title's list is unknown."""
        return None if self.class_bits is None else dict(self.class_bits)


POOL_OF_RADIANCE = Title(
    key="pool-of-radiance", title="Pool of Radiance",
    races=RACES_FORGOTTEN_REALMS, class_bits=CLASS_BITS_CLASSIC,
    travel_grid=True)

CURSE_OF_THE_AZURE_BONDS = Title(
    key="curse-of-the-azure-bonds", title="Curse of the Azure Bonds",
    races=RACES_CURSE, class_bits=CLASS_BITS_WITH_PALADIN_RANGER)

SECRET_OF_THE_SILVER_BLADES = Title(
    key="secret-of-the-silver-blades", title="Secret of the Silver Blades",
    races=RACES_SILVER_BLADES, class_bits=CLASS_BITS_WITH_PALADIN_RANGER)

CHAMPIONS_OF_KRYNN = Title(
    key="champions-of-krynn", title="Champions of Krynn",
    races=RACES_KRYNN, class_bits=CLASS_BITS_KRYNN)

DEATH_KNIGHTS_OF_KRYNN = Title(
    key="death-knights-of-krynn", title="Death Knights of Krynn",
    races=RACES_KRYNN, class_bits=CLASS_BITS_KRYNN)

GATEWAY_TO_THE_SAVAGE_FRONTIER = Title(
    key="gateway-to-the-savage-frontier", title="Gateway to the Savage Frontier",
    races=RACES_FORGOTTEN_REALMS, class_bits=CLASS_BITS_WITH_PALADIN_RANGER)

#: The whole reason this module exists: a title with no C64 release at all
#: (`#460 (goldbox/games.py has no Pools of Darkness entry, so every lookup
#: answers with Pool of Radiance's tables for it)`). It has its own races and
#: class bits and no C64 anything -- no row in `goldbox.c64_port.BY_KEY`, no
#: guard anywhere. Absent is ordinary.
POOLS_OF_DARKNESS = Title(
    key="pools-of-darkness", title="Pools of Darkness",
    races=RACES_POOLS_OF_DARKNESS,
    class_bits=CLASS_BITS_WITH_PALADIN_RANGER)

TITLES: tuple[Title, ...] = (
    POOL_OF_RADIANCE,
    CURSE_OF_THE_AZURE_BONDS,
    SECRET_OF_THE_SILVER_BLADES,
    CHAMPIONS_OF_KRYNN,
    DEATH_KNIGHTS_OF_KRYNN,
    GATEWAY_TO_THE_SAVAGE_FRONTIER,
    POOLS_OF_DARKNESS,
)

#: What a caller gets when nothing says otherwise. Pool of Radiance, because
#: every existing caller predates this module and means it.
DEFAULT = POOL_OF_RADIANCE

BY_KEY: dict[str, Title] = {t.key: t for t in TITLES}
BY_TITLE: dict[str, Title] = {t.title: t for t in TITLES}


class UnknownTitleError(ValueError):
    """Raised when a key names no title we know."""


def by_key(key: str) -> Title:
    try:
        return BY_KEY[key]
    except KeyError:
        raise UnknownTitleError(
            f"{key!r} is not a title this tool knows. "
            f"Try one of: {', '.join(sorted(BY_KEY))}") from None


def by_title(title: str | None) -> Title | None:
    """The title a person named, or None. Never falls back to a default.

    The windows carry the game as a plain string -- see `AutomapState.title` --
    and this is the one place that turns it back into a descriptor. None for an
    unrecognised name on purpose: a caller that needs an address has to notice
    it does not have one.
    """
    return BY_TITLE.get(title) if title else None


# ---------------------------------------------------------------------------
# The per-title tables, resolved
# ---------------------------------------------------------------------------
# `race`, `char_class` and `class_bits` are *indices into this title's own
# tables* wherever they appear -- in a C64 record, in `goldbox/neutral.py`'s
# vocabulary, in the YAML. Turning one into a name therefore needs the title,
# and every codec needs the same answer. These live here, beside the tables
# themselves, so that a codec asking for a name imports a table module rather
# than another codec.
#
# Duck-typed the way `goldbox.spells.for_game` is: a bare key or `None`
# resolves through `BY_KEY`; anything that already carries `race_names` --
# a `Title` or a `goldbox.c64_port.C64Container`, `races=None` included -- is read
# directly, which is what lets a caller ask to see the raw number for a title
# whose table is not (yet) known rather than get a wrong name.
def race_table(title: "Title | object | str | None" = None) -> dict[int, str]:
    """Race code -> name for a title, or Pool of Radiance's.

    Empty when the title's list is unknown, so a caller shows the raw number
    rather than inventing a name for it.
    """
    if title is None or isinstance(title, str):
        title = BY_KEY.get(title, DEFAULT)
    return title.race_names or {}


def class_table(title: "Title | object | str | None" = None
                 ) -> list[tuple[int, str]]:
    """The bit -> name pairs for a title, or Pool of Radiance's four.

    A title whose list we do not know gets an empty table, which makes
    :func:`classes_to_names` hand back the raw bitmask rather than a wrong
    name.
    """
    if title is None or isinstance(title, str):
        title = BY_KEY.get(title, DEFAULT)
    return list(title.class_bits or ())


def classes_to_names(bits: int, title: "Title | object | str | None" = None
                      ) -> list[str]:
    """The classes a bitmask holds, named -- or the mask itself, unnamed."""
    names = [name for bit, name in class_table(title) if bits & bit]
    if not names:                       # unknown encoding: keep it visible
        return [bits]
    return names

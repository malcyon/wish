"""One character, in no port's terms, and the report every codec fills in.

Three formats in two directions is six converters; three codecs around one
neutral record is three readers and three writers, and a fourth format then
costs two pieces rather than four.  This module is the middle.

    DOS file  --reader-->  NeutralCharacter  --writer-->  C64 record

A **reader** decodes one port's bytes into named neutral values.  A **writer**
encodes those values into another port's bytes.  Neither knows the other
exists: the DOS reader names DOS offsets, the C64 writer names C64 fields, and
what passes between them is this record.

What a neutral value carries
----------------------------
Not just a number.  Each :class:`Value` carries

* the decoded value, in the neutral convention the vocabulary below states;
* a **confidence**, taken from the grade the source port's field table gives
  the field it was read from.  A writer asks for what it is willing to stand
  behind (:meth:`NeutralCharacter.take`) and gets nothing rather than a guess
  -- refusing to write is the point of the grades, not a decoration on them;
* an **origin**, the reader's one-line phrase for where the value came from,
  which is what the writer's provenance report quotes.

Who says what
-------------
The split that keeps a codec honest is: **a reader says where a value came
from, a writer says where it went and what it could not take.**  So the DOS
reader's origin for the spellbook is "DOS spellbook @0x033, one byte per
spell" and the C64 writer's line is that phrase plus "packed to one bit" --
its own packing rule, not the reader's.  `port` names the source port so a
writer can say whose value it is turning away without knowing anything else
about it.

Reporting
---------
:class:`Report` is the one shape every direction reports in: a provenance for
every output byte, the fields left behind, and the conversions that changed
something.  :func:`disposition` builds the table that makes a silent drop
impossible -- a field the source declares and the codec names nowhere.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any, Iterable, Iterator, Sequence

from .layout import Confidence

__all__ = [
    "Provenance",
    "Value",
    "FIELDS",
    "NeutralCharacter",
    "NeutralError",
    "Report",
    "Writer",
    "disposition",
    "undeclared",
]


class NeutralError(KeyError):
    """A field name the neutral vocabulary does not declare."""


class Provenance(enum.Enum):
    """How a value's report line reads, which is also what kind of value it is.

    The separator is the whole of it, and the three of them are the three
    honest sentence shapes a provenance line has: this byte came *from*
    somewhere, this byte *is* something, or this byte is the same value in the
    destination's own shape.
    """

    #: Taken from a named field of the source port.  ``thac0 <- DOS ...``
    COPIED = " <- "
    #: Derived by a rule; the source port does not store it at all.
    #: ``infravision: computed from race ...``
    COMPUTED = ": "
    #: The same value, re-cut to the destination's shape.
    #: ``name, re-padded from ...``
    RESHAPED = ", "


@dataclasses.dataclass(frozen=True)
class Value:
    """One field of the neutral record: the value, where it came from, how far
    it is trusted, and the shape of the sentence that will report it."""

    value: Any
    origin: str
    confidence: Confidence = Confidence.CONFIRMED
    how: Provenance = Provenance.COPIED
    #: What the reader had to leave behind to produce this value -- the
    #: running spells left over when the innate ones were picked out, say.
    #: A writer emits them where it consumes the field, so a drop is reported
    #: beside the thing it was dropped from.
    dropped: tuple[str, ...] = ()

    def line(self, destination: str, extra: str = "") -> str:
        """The provenance line for a destination field this value fed.

        `extra` is the writer's own half -- the rule it applied on the way in,
        which the reader cannot know.
        """
        return f"{destination}{self.how.value}{self.origin}{extra}"


#: The neutral vocabulary: every field a codec may set, and what it means.
#:
#: A name here is the *thing*, not any port's storage of it, and a reader that
#: invents a name outside this table is refused -- a typo would otherwise be a
#: field silently unread by every writer.  Where a value needs a convention
#: (an order, a unit, an encoding) the entry states it, and that convention is
#: the neutral one: a port whose own encoding differs converts on the way in.
FIELDS: dict[str, str] = {
    # -- who they are -------------------------------------------------------
    "name": "the character's name, plain text",
    "sex": "0 male, 1 female",
    "race": "race index, in the shared Gold Box order",
    "char_class": "the single class code, in the shared 18-entry order",
    "class_bits": "one bit per class held, in the shared bit order",
    "alignment": "law * 3 + morality",
    "age": "age in years",
    "party_order": "position in the marching order",
    # -- abilities ----------------------------------------------------------
    "strength": "STR, 3-18 (25 for a monster)",
    "exceptional_strength": "the 18/xx percentile, 0 when there is none",
    "intelligence": "INT",
    "wisdom": "WIS",
    "dexterity": "DEX",
    "constitution": "CON",
    "charisma": "CHA",
    # -- level and health ---------------------------------------------------
    "level": "the character level the game itself keeps",
    "levels": "class name -> that class's level, in the source's slot order",
    "levels_drained": "levels lost to undead and not yet restored",
    "hp_lost_to_drain": "hit points lost with those levels",
    "experience": "experience points",
    "hp_max": "maximum hit points",
    "hp_rolled": "hit points rolled, before the constitution bonus",
    "hp_current": "hit points now",
    # -- fighting -----------------------------------------------------------
    "thac0_base": "the class-and-level THAC0, before anything carried",
    "thac0_current": "THAC0 as the game last computed it",
    "attack_level": "the level the attack tables are read at",
    "attack_forms": "the eight attack-form bytes",
    "armour_class_base": "armour class with nothing worn",
    "armour_class": "armour class as the game last computed it",
    "movement": "movement rate unencumbered",
    "movement_current": "movement rate as the game last computed it",
    "infravision": "infravision range in feet; a property of the race, which "
                   "some ports store and others derive",
    "turn_power": "the cleric's turning strength",
    "size_small": "0 small, 1 large",
    # -- saving throws ------------------------------------------------------
    "save_paralysis": "save vs paralysis, poison and death magic",
    "save_petrification": "save vs petrification and polymorph",
    "save_wands": "save vs rod, staff and wand",
    "save_breath": "save vs breath weapon",
    "save_spell": "save vs spell",
    # -- thief skills, percentages ------------------------------------------
    "thief_pick_pockets": "pick pockets, per cent",
    "thief_open_locks": "open locks, per cent",
    "thief_find_traps": "find and remove traps, per cent",
    "thief_move_silently": "move silently, per cent",
    "thief_hide_in_shadows": "hide in shadows, per cent",
    "thief_hear_noise": "hear noise, per cent",
    "thief_climb_walls": "climb walls, per cent",
    "thief_read_languages": "read languages, per cent (a halfling's is "
                            "negative)",
    # -- what they carry ----------------------------------------------------
    "copper": "copper pieces",
    "silver": "silver pieces",
    "electrum": "electrum pieces",
    "gold": "gold pieces",
    "platinum": "platinum pieces",
    "gems": "gems, counted not valued",
    "jewelry": "pieces of jewelry, counted not valued",
    "inventory": "the items carried, each in the shared sixteen-byte item "
                 "shape `por/items.py` reads",
    # -- magic --------------------------------------------------------------
    "spells_known": "spell ids in the spellbook, ascending",
    "spells_memorised": "spell ids memorised, highest first",
    "spells_castable": "class name -> slots free per spell level, ascending",
    # -- effects and the roster ---------------------------------------------
    "innate_effects": "effect ids that are properties of the character rather "
                      "than spells running on it",
    "roster_tail": "the derived combat block the roster keeps beside the "
                   "record",
    "npc": "true for a companion the party picked up rather than one the "
           "player made",
    # -- carried by some ports and not others -------------------------------
    # Declared here because a character has them, not because every writer
    # wants them: a writer that takes nothing from a field reports so.
    "encumbrance": "total weight carried, in tenths of a pound",
    "portrait_head": "portrait head index, in the source port's own art set",
    "portrait_body": "portrait body index, in the source port's own art set",
}


class NeutralCharacter:
    """One character as named neutral values, with a report line for each.

    `port` names the port a reader took this from -- "DOS", "C64", "Amiga" --
    so a writer can say whose value it is turning away.  `dropped` is what the
    reader itself could not carry: fields of the source with no neutral home,
    named on the way past rather than lost.

    `game` is the *title* whose tables the port-relative indices were read in
    -- `race`, `char_class` and `class_bits` are numbers into a table that is
    not the same in every Gold Box game, so a writer that wants a name asks
    `por/games.py` with this in hand.  None means Pool of Radiance's, which is
    what a caller with no title in hand means.
    """

    def __init__(self, port: str, source: str | None = None,
                 game: Any = None) -> None:
        self.port = port
        self.source = source
        self.game = game
        self.fields: dict[str, Value] = {}
        #: Source fields with no neutral home, said out loud by the reader.
        self.dropped: list[str] = []
        #: Anything the read itself could not do faithfully.
        self.warnings: list[str] = []

    # -- filling it in ------------------------------------------------------
    def set(self, name: str, value: Any, origin: str,
            confidence: Confidence = Confidence.CONFIRMED,
            how: Provenance = Provenance.COPIED,
            dropped: Sequence[str] = ()) -> None:
        if name not in FIELDS:
            raise NeutralError(
                f"{name!r} is not a neutral field; declare it in "
                f"por/neutral.py FIELDS or fix the spelling")
        self.fields[name] = Value(value, origin, confidence, how,
                                  tuple(dropped))

    def drop(self, what: str) -> None:
        self.dropped.append(what)

    # -- reading it out -----------------------------------------------------
    def __contains__(self, name: str) -> bool:
        return name in self.fields

    def __iter__(self) -> Iterator[str]:
        return iter(self.fields)

    def keys(self) -> Iterable[str]:
        return self.fields.keys()

    def value(self, name: str) -> Value:
        return self.fields[name]

    def get(self, name: str, default: Any = None) -> Any:
        v = self.fields.get(name)
        return default if v is None else v.value

    def take(self, name: str,
             floor: Confidence = Confidence.GUESS) -> Value | None:
        """The value, or None when the reader trusts it less than `floor`.

        This is how a codec refuses to write what it does not understand: it
        asks for a field at the grade it is willing to stand behind, and a
        field graded below that comes back as nothing to write and something
        to report, never as a plausible-looking guess.
        """
        v = self.fields.get(name)
        if v is None or _RANK[v.confidence] < _RANK[floor]:
            return None
        return v

    def unwritten(self, taken: Iterable[str]) -> list[str]:
        """Neutral fields a writer did not consume, in the order they were set.

        The other half of :func:`disposition`: that one catches a source field
        no codec names, this one catches a neutral value no writer took.
        """
        seen = set(taken)
        return [n for n in self.fields if n not in seen]


#: Ordered worst to best, so `take` can compare.  UNKNOWN is below every floor
#: a writer can name, which is what makes it unwritable.
_RANK = {Confidence.UNKNOWN: 0, Confidence.GUESS: 1,
         Confidence.PROBABLE: 2, Confidence.CONFIRMED: 3}


# ---------------------------------------------------------------------------
# The report -- what became of every byte, in one shape for every direction
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class Report:
    """Where each byte of the output came from, and what was left behind.

    `docs/117-save-conversion.md` makes this the test that replaces a round
    trip: for any offset in the output, say where that byte came from.  Each
    port's codec subclasses this to say how much of its output has to be
    explained -- every byte, or only the non-zero ones.
    """

    #: How many bytes the provenance covers.
    total: int = 0
    #: Offset -> a one-line provenance.
    sources: dict[int, str] = dataclasses.field(default_factory=dict)
    #: Fields with no home in the destination, said out loud rather than
    #: dropped.
    dropped: list[str] = dataclasses.field(default_factory=list)
    #: Anything the conversion could not do faithfully.
    warnings: list[str] = dataclasses.field(default_factory=list)

    def note(self, offset: int, size: int, why: str) -> None:
        for i in range(offset, offset + size):
            self.sources[i] = why

    def summary_notes(self) -> list[str]:
        """Lines a port's own report adds between the count and the warnings."""
        return []

    def summary(self) -> str:
        lines = [f"{len(self.sources)}/{self.total} bytes accounted for"]
        lines.extend(self.summary_notes())
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        for d in self.dropped:
            lines.append(f"  dropped: {d}")
        return "\n".join(lines)


class Writer:
    """The take-refuse-report protocol every writer shares.

    Hoisted from `por/c64_codec.write`, where `use` and `emit` were closures
    a second writer would have copied by hand -- which is exactly what
    `por/amiga.py` did, against a different middle, and the mistake this
    class exists to end.  A writer constructs one around the character and
    its own report and gets four things it would otherwise re-implement:

    * :meth:`use` -- take a field at the floor, and turn a refusal into a
      report line rather than silence.  A refused value's own `dropped` list
      still reaches the report: what a reader had to leave behind to produce
      a value is a fact about the source whether or not the value is written.
    * :meth:`emit` -- the provenance note for the bytes a value became.
    * :meth:`get` -- a plain value for a *derivation*, at the same floor.
      `NeutralCharacter.get` does not apply one, and a writer that computes
      a byte from a field it would have refused to copy is standing behind
      the value twice as hard, not half as hard.
    * :meth:`finish` -- the closing sweep: neutral fields this writer took
      nothing from, then the reader's own drops and warnings.

    `dropped` is the codec's own `(name, why)` table of fields it takes
    nothing from, so that the sweep reports *this* conversion's reason for
    leaving a field behind rather than a generic sentence.  It reports what
    the character actually carries, which is why the whole-contract statement
    lives in the codec's `field_disposition()` and is tested there instead.
    """

    def __init__(self, char: "NeutralCharacter", report: "Report",
                 into: str, floor: Confidence = Confidence.GUESS,
                 dropped: Sequence[tuple[str, str]] = ()) -> None:
        self.char = char
        self.report = report
        self.into = into
        self.floor = floor
        self.reasons = dict(dropped)
        self.taken: list[str] = []

    def use(self, name: str) -> Value | None:
        """The value, if the reader stands behind it at the floor.

        A field graded below the floor comes back as nothing to write and
        something to report, never as a plausible-looking guess.
        """
        self.taken.append(name)
        v = self.char.take(name, self.floor)
        if v is None and name in self.char:
            held = self.char.value(name)
            self.report.dropped.append(
                f"{self.char.port} {name}: read at {held.confidence}, "
                f"which is not a grade this conversion will write")
            self.report.dropped.extend(held.dropped)
        return v

    def emit(self, v: Value, destination: str, offset: int, size: int,
             extra: str = "") -> None:
        self.report.note(offset, size, v.line(destination, extra))
        self.report.dropped.extend(v.dropped)

    def get(self, name: str, default: Any = None) -> Any:
        """A bare value for a rule to compute from, floor applied.

        Does **not** count as taking the field: a writer that derives one
        byte from `race` and also copies `race` reports the copy, and a
        writer that only derives must still `use` the field once if it wants
        the field counted as consumed.
        """
        v = self.char.take(name, self.floor)
        return default if v is None else v.value

    def finish(self) -> None:
        """The closing sweep every writer used to copy by hand."""
        for name in self.char.unwritten(self.taken):
            why = self.reasons.get(name)
            self.report.dropped.append(
                f"{name}: {why}" if why else
                f"{name}: the neutral record carries it and the {self.into} "
                f"conversion takes nothing from it")
        self.report.dropped.extend(self.char.dropped)
        self.report.warnings.extend(self.char.warnings)


def disposition(direct: Sequence[tuple[str, str]],
                transformed: Sequence[tuple[str, str]],
                dropped: Sequence[tuple[str, str]],
                into: str) -> dict[str, str]:
    """Every field a codec knows about and what it does with it.

    The three tables are the codec's whole account of itself, and the test
    that keeps it honest is :func:`undeclared`: a field the source declares and
    none of the three names would be a field dropped in silence, which
    `docs/117-save-conversion.md` forbids.
    """
    out: dict[str, str] = {}
    for name, destination in direct:
        out[name] = f"copied to {into} {destination}"
    for name, why in transformed:
        out[name] = why
    for name, why in dropped:
        out[name] = f"dropped: {why}"
    return out


def undeclared(declared: Iterable[str],
               table: dict[str, str]) -> tuple[set[str], set[str]]:
    """`(unaccounted, unknown)`: source fields the codec never names, and
    names the codec claims that the source does not declare.  Both empty is
    the only passing state."""
    declared = set(declared)
    return declared - set(table), set(table) - declared

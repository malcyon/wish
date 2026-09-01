"""Typed notes on a square. No Qt in here, so it is testable headless.

A note is a **kind plus a few words**, because that is what the notes a player
actually makes look like: "there is a fight here", "locked, come back", "exit to
Kuto's Well". Half of them are things you want to see from across the map
without hovering -- the whole point is not walking back into a fight -- so the
kind carries an icon and the words are the tooltip.

Three deliberate choices in the storage:

* **A list per square**, not one string. Squares genuinely hold two things -- a
  fight and the treasure it guards.
* **`type` is a string**, not an index, so the file stays readable and a
  renamed or removed type degrades to an unknown icon rather than silently
  becoming a different one. `type_for` is where that happens.
* **The old format keeps loading.** `"6,2": "some text"` becomes one note of
  type `note`; `tests/test_automap.py` pins it. Nobody's notes get eaten by an
  upgrade.

The type table is data, so adding a type is a line here and nothing else --
but the *order* is the picker's layout as well as its order, five to a row
with each row one idea, so a new kind joins the row it belongs to rather than
the end. `PICKER_COLUMNS` is the width those rows were grouped for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

Square = tuple[int, int]


@dataclass(frozen=True)
class NoteType:
    """One kind of note: what it is called, and what it draws."""

    name: str           #: what goes in the file
    label: str          #: what the picker shows
    icon: str           #: a key into `automap.icons`
    hint: str           #: one line, for the picker's tooltip


#: The set, **in picker order**, and the order is the layout: five rows of
#: five, each row one idea. Reading across -- marks, what the square holds, a
#: fight, a person, a place you come back to. The picker shows no words, so
#: the grouping is the only thing helping somebody find a picture, and a row
#: that means something is worth more than an alphabet.
#:
#: The names and the descriptions are Donald's, settled on `#166`, and
#: `work/note-icons.md` renders every one at the two sizes he judged them at.
TYPES: tuple[NoteType, ...] = (
    # Marks: where you are, where you are going, how you get out.
    NoteType("note", "Note", "position-marker",
             "Anything that does not fit the others"),
    NoteType("point-of-interest", "Point of Interest", "pin",
             "Somewhere you've been, or somewhere you intend to go."),
    NoteType("exit", "Exit", "exit-door",
             "Where this map joins another"),
    NoteType("stairs", "Stairs", "stairs",
             "Up, down, or wherever the level changes"),
    NoteType("done", "Done", "check-mark",
             "Cleared, nothing left here"),

    # What the square itself holds.
    NoteType("locked", "Locked", "plain-padlock",
             "A door that beat you"),
    NoteType("danger", "Danger", "hazard-sign",
             "Traps, drains, whatever you want to avoid"),
    NoteType("trap", "Trap", "tripwire",
             "A trap you found, sprung or not"),
    NoteType("treasure", "Treasure", "open-treasure-chest",
             "Something to take, or taken"),
    NoteType("magic-items", "Magic items", "diamond-hilt",
             "Magic items"),

    # A fight, and what you are fighting.
    NoteType("encounter", "Encounter", "crossed-sabres",
             "A fight, set or remembered"),
    NoteType("orcs", "Orcs", "orc-head",
             "Orcs"),
    NoteType("goblins", "Goblins", "goblin-head",
             "Goblins, Hobgoblins, etc."),
    NoteType("undead", "Undead", "raise-zombie",
             "Undead"),
    NoteType("dragon", "Dragon", "dragon-head",
             "Dragon"),

    # Somebody standing there.
    NoteType("person", "Person", "person",
             "Trainer, shop, quest-giver"),
    NoteType("warrior", "Warrior", "barbute",
             "A fighter — guard, soldier, someone who blocks the way"),
    NoteType("cleric", "Cleric", "flanged-mace",
             "A cleric — healing, or a temple"),
    NoteType("thief", "Thief", "ninja-heroic-stance",
             "A thief — picking, hiding, or someone who steals"),
    NoteType("wizard", "Wizard", "wizard-face",
             "A spellcaster"),

    # Somewhere you come back to.
    NoteType("smith", "Smith", "anvil-impact",
             "A smith, for mending and buying arms"),
    NoteType("silversmith", "Silversmith", "gold-bar",
             "Silversmith"),
    NoteType("jeweler", "Jeweler", "cut-diamond",
             "Jeweler"),
    NoteType("inn", "Inn", "bed",
             "Somewhere to rest and get the spells back"),
    NoteType("tavern", "Tavern", "beer-stein",
             "Drink, gossip, and the people who have it"),
)

#: How many kinds go on one row of the picker. The rows above are the
#: grouping, so this is not a width the layout may choose for itself: change
#: it and the five ideas run into each other.
PICKER_COLUMNS = 5

#: What an untyped note becomes, and what the picker starts on.
DEFAULT = "note"

BY_NAME = {t.name: t for t in TYPES}


def type_for(name: str) -> NoteType:
    """The type, or a stand-in that says it is not one we know.

    A type dropped from the table must not turn its notes into some other
    type's, so an unknown name keeps its own name and gets the neutral marker.
    """
    known = BY_NAME.get(name)
    if known is not None:
        return known
    return NoteType(name, name or "?", "position-marker",
                    f"{name!r} is not a note type this version knows")


def stamp() -> str:
    """When a note was made, to the second. Never parsed -- only shown."""
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Note:
    """One note on one square."""

    text: str = ""
    type: str = DEFAULT
    at: str = ""

    @property
    def kind(self) -> NoteType:
        return type_for(self.type)

    @property
    def icon(self) -> str:
        return self.kind.icon

    @property
    def label(self) -> str:
        """`Encounter - dueling pairs`, or just the type when there are no
        words. A typed note with no text is a legitimate note: the icon is the
        whole message."""
        return f"{self.kind.label} - {self.text}" if self.text else self.kind.label

    def to_json(self) -> dict:
        out = {"type": self.type, "text": self.text}
        if self.at:
            out["at"] = self.at
        return out

    @classmethod
    def from_json(cls, payload) -> Note:
        """One note, from the new shape or from a bare string."""
        if isinstance(payload, str):
            return cls(text=payload, type=DEFAULT)
        return cls(text=str(payload.get("text", "")),
                   type=str(payload.get("type", DEFAULT)) or DEFAULT,
                   at=str(payload.get("at", "")))


def dump_notes(notes: dict[Square, list[Note]]) -> dict[str, list[dict]]:
    """The `"x,y": [...]` mapping the area file holds. Empty squares dropped."""
    out = {}
    for (x, y), items in sorted(notes.items()):
        kept = [n.to_json() for n in items if n.text or n.type != DEFAULT]
        if kept:
            out[f"{x},{y}"] = kept
    return out


def load_notes(payload) -> dict[Square, list[Note]]:
    """Read the mapping back, in whichever shape the file is in.

    Accepts the new list-per-square, a bare string per square (the format
    before types existed), and a single object per square. Anything else for a
    square is dropped rather than raising: half a notes file is better than
    none, and the file is hand-editable by design.
    """
    out: dict[Square, list[Note]] = {}
    for key, value in (payload or {}).items():
        try:
            a, b = str(key).split(",")
            square = (int(a), int(b))
        except ValueError:
            continue
        if isinstance(value, (str, dict)):
            value = [value]
        if not isinstance(value, list):
            continue
        items = [Note.from_json(v) for v in value
                 if isinstance(v, (str, dict))]
        items = [n for n in items if n.text or n.type != DEFAULT]
        if items:
            out[square] = items
    return out


def summary(items) -> str:
    """Every note on a square, one per line. The map's tooltip."""
    return "\n".join(n.label for n in items)

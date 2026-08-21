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

The type table is data, so adding a type is a line here and nothing else.
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
    key: str = ""       #: a letter that selects it in the picker


#: The set, in picker order. Nine is still scannable and still fits one row of
#: buttons.
TYPES: tuple[NoteType, ...] = (
    NoteType("encounter", "Encounter", "swords",
             "a fight, set or remembered", "E"),
    NoteType("treasure", "Treasure", "chest",
             "something to take, or taken", "T"),
    NoteType("person", "Person", "user",
             "trainer, shop, quest-giver", "P"),
    NoteType("exit", "Exit", "door-open",
             "where this map joins another", "X"),
    NoteType("locked", "Locked", "lock",
             "a door that beat you", "L"),
    NoteType("stairs", "Stairs", "stairs",
             "up, down, or wherever the level changes", "S"),
    NoteType("danger", "Danger", "triangle-exclamation",
             "traps, drains, whatever you want to avoid", "D"),
    NoteType("note", "Note", "location-dot",
             "anything that does not fit the others", "N"),
    NoteType("done", "Done", "check",
             "cleared, nothing left here", "C"),
)

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
    return NoteType(name, name or "?", "location-dot",
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

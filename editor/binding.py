"""Which widget edits which record field, and which must not be edited.

Two ideas hold this together.

**Widgets bind by `objectName`.** A widget called `field_strength` edits the
`strength` entry in `por/layout.py`. Nothing here knows where on the form a
widget sits, so `editor/character.ui` can be rearranged in Qt Designer without
touching a line of Python.

**Read-only is computed, never hand-listed.** Three independent reasons a field
must not be edited, each derived from something the project already maintains,
so none of them can go stale:

1. the game recomputes it (`por/derive.py` knows which),
2. we do not understand it (`Confidence.UNKNOWN`),
3. the write would be silently dropped -- a save slot is 256 bytes and a record
   is 580, so anything at `0x100` or above exists only in a `.chr` export.
"""

from __future__ import annotations

from dataclasses import dataclass

from por.layout import LAYOUT, Confidence, Field, Kind

PREFIX = "field_"

# A save slot holds only the first 256 bytes of the 580-byte record.
SLOT_BYTES = 0x100

# Values the game derives from the character plus their equipment and caches in
# the SAVEDGAME1 roster. Editing the record's copy achieves nothing: the game
# recomputes it on the next equipment change. por/derive.py computes what each
# should be, and the editor shows that beside the stored value.
DERIVED = frozenset({
    "armour_class", "armour_class_base", "thac0", "thac0_base",
    "strength_index",
})

# Not derived, but not ours to set either: these move only as a consequence of
# something else happening in play.
COMPUTED_IN_PLAY = frozenset({"levels_drained", "hp_lost_to_drain"})


@dataclass(frozen=True)
class Binding:
    field: Field
    read_only: bool
    reason: str

    @property
    def name(self) -> str:
        return self.field.name


def _is_placeholder(field: Field) -> bool:
    return field.name.startswith(("region_", "gap_", "unknown"))


def editable_fields() -> list[Field]:
    """Every field worth putting on a form, in record order."""
    return [f for f in LAYOUT if not _is_placeholder(f)]


def binding_for(field: Field, *, in_save: bool) -> Binding:
    """Decide whether `field` may be edited in this kind of file.

    `in_save` is True for a slot inside a save disk and False for a standalone
    `.chr` export, which is the whole 580 bytes.
    """
    if field.confidence is Confidence.UNKNOWN:
        return Binding(field, True, "not understood; preserved verbatim")
    if in_save and field.offset >= SLOT_BYTES:
        return Binding(field, True,
                       f"offset {field.offset:#05x} is past the {SLOT_BYTES} "
                       f"bytes a save slot holds; the write would be dropped")
    if field.name in DERIVED:
        return Binding(field, True,
                       "the game recomputes this from abilities and equipment")
    if field.name in COMPUTED_IN_PLAY:
        return Binding(field, True, "set by what happens in play, not by you")
    return Binding(field, False, "")


def bindings(*, in_save: bool) -> dict[str, Binding]:
    return {f.name: binding_for(f, in_save=in_save) for f in editable_fields()}


# -- how wide a box has to be ------------------------------------------------
#
# Derived from the layout, never hand-tuned: the kind and the byte width give
# the widest value the field can hold, so a field put on the form tomorrow is
# the right size without anybody sizing it.


def value_range(field: Field) -> tuple[int, int] | None:
    """The values these bytes can hold, or None if the field is not a number."""
    if field.kind is Kind.U8:
        return 0, 0xFF
    if field.kind is Kind.I8:
        return -128, 127
    if field.kind in (Kind.U16LE, Kind.UINT_LE):
        return 0, (1 << (8 * field.size)) - 1
    return None


def widest_text(field: Field) -> str:
    """The longest string the field can ever display.

    A name is its twenty characters, an ability score is "255", a thief skill
    is "-128" -- the minus sign is wider than the extra digit it replaces -- and
    a RAW field is its bytes as spaced hex, which is how the form shows them.
    """
    span = value_range(field)
    if span is not None:
        low, high = span
        return max(str(low), str(high), key=len)
    if field.kind is Kind.ASCII_NUL:
        return "W" * field.size
    return " ".join(["ff"] * field.size)


def widget_name(field_name: str) -> str:
    return f"{PREFIX}{field_name}"


def field_name(widget_name: str) -> str | None:
    if widget_name.startswith(PREFIX):
        return widget_name[len(PREFIX):]
    return None


#: Fields the CLI carries but the sheet does not show. `wish-cli` prints and
#: `yaml_io` round-trips them; the GUI has no widget for them, so a save leaves
#: their bytes exactly as it found them.
#:
#: Most of the second group were named from Curse, the Krynn titles and the
#: monster records, and read zero in every Pool of Radiance character -- there
#: is nothing for a player to edit. Keeping them listed rather than dropping
#: the count check in `tests/test_editor.py` keeps that check's point: a field
#: added tomorrow still has to get a widget or say here why not.
NOT_ON_THE_SHEET = (
    "portrait_head", "portrait_body",
    "attack_forms",       # a monster's two attack forms; not a player field
    "turn_power",         # the caster's half of turning, zero in this game
    "attack_level",       # Curse's fighting level, zero in this game
    "level_knight",       # Krynn class slots of the per-class level array
    "level_paladin",
    "level_ranger",
    "abilities_second",   # Curse's second ability block, zero in this game
    "inventory",          # editor/inventory.py edits the item slots
    # The high nine bytes of the spellbook bitmask. Not a field of its own on
    # the sheet: `field_spells_known` reads and writes both halves as one mask,
    # because which of them a spell id falls in is the title's business and not
    # the form's.
    "spells_known_high",
)


def shown_fields(fields):
    """The editable fields the sheet is expected to bind, in order."""
    return [f for f in fields if f.name not in NOT_ON_THE_SHEET]

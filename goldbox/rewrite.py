"""Write an edited character back into the save it came from, span by span.

The editor edits a C64 :class:`goldbox.record.CharacterRecord` whatever port
the save is, because that is the record the sheet binds to.  Converting the
whole character back on save would hand every *unedited* field the writer's
rendering of it rather than the engine's own bytes, and the two differ in
places -- the live heap pointers, the sheet-portrait pair, a saving throw a
recompute disagrees with.  `docs/223-the-differential-rewrite.md` is the
census of where.

So nothing here converts a character back.  The port's own writer renders the
character **twice**, once from the record as it was read and once from the
record as it was edited, and only the field spans where the two renderings
differ are copied onto the bytes the engine wrote.  An untouched field keeps
the engine's own bytes whatever the writer would have made of them; a save
with no edit in it is byte-identical by construction; an edited field is
converted exactly once, by the writer the conversion sweep already covers.

The three entry points are one per port container:
:func:`rewrite_dos` for a DOS `CHRDAT<slot><n>.SAV` and its item and effect
siblings, :func:`rewrite_amiga_por` for an Amiga Pool of Radiance
`CHRDAT<slot><n>.sav`, and :func:`rewrite_amiga_later` for one Amiga Curse or
Silver Blades block inside a saved game.
"""
from __future__ import annotations

from typing import Any, NamedTuple, Sequence

from . import amiga_later, amiga_por, c64_codec, dos_codec, dos_port
from .amiga_port import AmigaRecordError
from .iconparts import DosIcon, amiga_combat_icon
from .record import CharacterRecord


class RewriteError(ValueError):
    """A rewrite whose spans or items cannot be put back where they came
    from -- never a value a player typed, always a mismatch between the
    record handed in and the character it is supposed to belong to."""


class Span(NamedTuple):
    """One field of the port's own record, and where it sits in it."""

    name: str
    at: int
    size: int


class RewrittenDos(NamedTuple):
    """What a DOS or Amiga Pool of Radiance character is written back as."""

    record: bytes
    items: bytes
    effects: bytes


# ---------------------------------------------------------------------------
# The span maps: which bytes of the port's record each field owns
# ---------------------------------------------------------------------------
def dos_spans(deltas: Any) -> tuple[list[Span], list[str]]:
    """This DOS title's fields and their spans, and the ones with none.

    Every field of a DOS record has a span, so the second list is always
    empty; it is returned anyway so the three ports answer the same question
    the same way and a caller need not know which one it is holding.
    """
    deltas = dos_port.deltas_for(deltas)
    table = dos_port.FIELDS_BY_NAME_FOR[deltas.key]
    return [Span(f.name, f.offset, f.size) for f in table.values()], []


def amiga_por_spans() -> tuple[list[Span], list[str]]:
    """The Amiga Pool of Radiance record's fields and their spans.

    Built the way :func:`goldbox.amiga_por.from_dos_record` writes them: the
    name is one sixteen-byte NUL-padded run where DOS spends a count byte and
    fifteen, and everything else goes through
    :func:`goldbox.amiga_por.amiga_por_offset`.  A DOS offset inside the
    window the second insertion is somewhere in has no Amiga counterpart, so
    `field_83_87` is returned as unplaced rather than guessed at -- which
    leaves the engine's own bytes there, since an unplaced field is never
    copied.
    """
    spans = [Span("name", 0, amiga_por.AMIGA_POR_NAME_SIZE)]
    unplaced: list[str] = []
    for f in dos_port.LAYOUT:
        if f.name in ("name_length", "name_text"):
            continue
        try:
            at = amiga_por.amiga_por_offset(f.offset)
            for i in range(1, f.size):
                amiga_por.amiga_por_offset(f.offset + i)
        except AmigaRecordError:
            unplaced.append(f.name)
            continue
        spans.append(Span(f.name, at, f.size))
    return spans, unplaced


def amiga_later_spans(deltas: Any) -> tuple[list[Span], list[str]]:
    """An Amiga Curse or Silver Blades record's fields and their spans.

    The mirror of :func:`goldbox.amiga_later.from_dos_record_later`: the name
    is sixteen NUL-padded bytes, Silver Blades' spellbook is its own bitmask
    run at :data:`goldbox.amiga_later.AMIGA_SSB_SPELLBOOK_AT`, and every other
    field goes through :meth:`goldbox.amiga_port.AmigaDeltas.offset`.
    """
    spans = [Span("name", 0, amiga_later.AMIGA_NAME_SIZE)]
    unplaced: list[str] = []
    for f in dos_port.layout_for(deltas.dos):
        if f.name in ("name_length", "name_text"):
            continue
        if deltas.spellbook_bytes is not None and f.name == "spellbook":
            spans.append(Span("spellbook", amiga_later.AMIGA_SSB_SPELLBOOK_AT,
                              deltas.spellbook_bytes))
            continue
        try:
            at = deltas.offset(f.offset)
            for i in range(1, f.size):
                deltas.offset(f.offset + i)
        except AmigaRecordError:
            unplaced.append(f.name)
            continue
        spans.append(Span(f.name, at, f.size))
    return spans, unplaced


def dos_item_spans() -> list[Span]:
    """One DOS item node's fields.  The same table for all four titles:
    Silver Blades' four extra bytes are at the end and belong to no field."""
    return [Span(f.name, f.offset, f.size) for f in dos_port.ITEM_LAYOUT]


def amiga_item_spans(offset) -> tuple[list[Span], list[str]]:
    """One Amiga item node's fields, through the port's own item shift map.

    `offset` is :func:`goldbox.amiga_por.amiga_por_item_offset` or
    :meth:`goldbox.amiga_port.AmigaDeltas.item_offset`.
    """
    spans: list[Span] = []
    unplaced: list[str] = []
    for f in dos_port.ITEM_LAYOUT:
        try:
            at = offset(f.offset)
            for i in range(1, f.size):
                offset(f.offset + i)
        except AmigaRecordError:
            unplaced.append(f.name)
            continue
        spans.append(Span(f.name, at, f.size))
    return spans, unplaced


# ---------------------------------------------------------------------------
# The differential itself
# ---------------------------------------------------------------------------
def changed_spans(before: bytes, after: bytes,
                  spans: Sequence[Span]) -> list[Span]:
    """The spans the two renderings disagree about."""
    return [s for s in spans
            if before[s.at:s.at + s.size] != after[s.at:s.at + s.size]]


def patch(original: bytes, before: bytes, after: bytes,
          spans: Sequence[Span]) -> tuple[bytes, list[str]]:
    """`original` with the edited rendering's differing spans copied onto it.

    Returns the bytes and the names of the fields that moved.  `original` is
    what the engine wrote; `before` and `after` are the two renderings of the
    same character, so a span they agree about is a field nobody edited and
    the engine's bytes are kept.
    """
    if not len(before) == len(after) == len(original):
        raise RewriteError(
            f"a rewrite compares three records of one length; got "
            f"{len(original)}, {len(before)} and {len(after)}")
    out = bytearray(original)
    moved = changed_spans(before, after, spans)
    for s in moved:
        out[s.at:s.at + s.size] = after[s.at:s.at + s.size]
    return bytes(out), [s.name for s in moved]


# ---------------------------------------------------------------------------
# The items: sixteen C64 slots onto a port's own packed item list
# ---------------------------------------------------------------------------
class _ItemEdit(NamedTuple):
    index: int | None      # which of the original's items, or None when new
    before: bytes          # the C64 sixteen-byte block as it was read
    after: bytes           # the same slot as it was edited


def _c64_slots(inventory: bytes) -> list[bytes]:
    size = c64_codec.ITEM_SIZE
    return [inventory[n * size:(n + 1) * size]
            for n in range(c64_codec.ITEM_SLOTS)]


def node_bytes(item: Any) -> bytes:
    """One item node's bytes, whichever port's item object this is.

    A `DosItem` answers `bytes()`; the two Amiga item classes keep their
    bytes in `raw` and answer neither `__bytes__` nor `to_bytes`.
    """
    raw = getattr(item, "raw", None)
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    return bytes(item)


def _item_edits(before: CharacterRecord, after: CharacterRecord,
                original_count: int) -> list[_ItemEdit] | None:
    """What the sixteen C64 slots say should happen to the port's items.

    `None` when the record does not store an inventory at all -- a 256-byte
    save slot stops short of it -- and then the items are written back
    exactly as they were read.

    A slot's position is what ties a C64 item to the port's own item, because
    the C64's sixteen slots are fixed where the port's list is packed: an
    item deleted out of the middle shifts every item after it in the file and
    not one of them in the record.

    **A character carrying more than sixteen items keeps the rest.** The C64
    record has sixteen slots and the DOS and Amiga files have no such limit,
    so the sheet shows the first sixteen and the ones past them are written
    back exactly as they were read rather than dropped.
    """
    if not (before.is_stored("inventory") and after.is_stored("inventory")):
        return None
    was = _c64_slots(before.get_raw("inventory"))
    now = _c64_slots(after.get_raw("inventory"))
    filled = [n for n, block in enumerate(was) if any(block)]
    if len(filled) != min(original_count, c64_codec.ITEM_SLOTS):
        raise RewriteError(
            f"the record as it was read holds {len(filled)} items in its "
            f"sixteen C64 slots and the character it came from holds "
            f"{original_count}; there is no way to say which is which")
    out = []
    for n in range(c64_codec.ITEM_SLOTS):
        if not any(now[n]):
            continue
        index = filled.index(n) if any(was[n]) else None
        out.append(_ItemEdit(index, was[n], now[n]))
    return out


def _rewrite_items(edits: "list[_ItemEdit] | None",
                   originals: Sequence[bytes],
                   render, spans: Sequence[Span]) -> tuple[list[bytes],
                                                           list[str]]:
    """The port's item nodes, each either untouched or patched span by span.

    `render` turns one sixteen-byte C64 item block into this port's node;
    `originals` are the nodes the engine wrote, in the order the file holds
    them.
    """
    if edits is None:
        return list(originals), []
    out: list[bytes] = []
    moved: list[str] = []
    for n, edit in enumerate(edits):
        if edit.index is None:
            out.append(render(edit.after))
            moved.append(f"item {n}: added")
            continue
        original = originals[edit.index]
        if edit.before == edit.after:
            out.append(original)
            continue
        node, names = patch(original, render(edit.before),
                            render(edit.after), spans)
        out.append(node)
        moved.extend(f"item {n}: {name}" for name in names)
    for index in range(min(len(originals), c64_codec.ITEM_SLOTS)):
        if not any(e.index == index for e in edits):
            moved.append(f"item {index}: deleted")
    # Everything past the sixteenth was never on the sheet, so it goes back
    # exactly as it was read.
    out.extend(originals[c64_codec.ITEM_SLOTS:])
    return out, moved


# ---------------------------------------------------------------------------
# DOS
# ---------------------------------------------------------------------------
def rewrite_dos(original: "dos_codec.DosCharacter",
                before: CharacterRecord, after: CharacterRecord,
                game: Any = None,
                icon: "DosIcon | None" = None) -> RewrittenDos:
    """One DOS character written back, with only the edited fields changed.

    `original` is the character as `goldbox.dos_codec.read_character` read it,
    `before` the C64 record the editor built from it and `after` that record
    as the sheet left it.  `game` is the title's `goldbox.c64_port` container,
    which is what tells the reader whose race and class tables the record's
    indices are in.

    Returns the record, the item file and the effect file, each ready to be
    written under the title's own suffix -- `.ITM`/`.SPC` in Pool of
    Radiance, `.SWG`/`.FX` in Curse, `.STF`/`.SFX` in Silver Blades.  **The
    effect file is returned exactly as it was read**: the sheet's ten trait
    slots are not wired to the DOS effect nodes yet.

    `icon` is this character's own combat figure and defaults to the one the
    original record already holds, so a rewrite never disturbs it.
    """
    icon = amiga_combat_icon(original) if icon is None else icon
    deltas = original.deltas
    stride = deltas.item_size

    def render(rec: CharacterRecord) -> tuple[bytes, bytes]:
        neutral = c64_codec.read(rec, game=game)
        record, itm, _spc, _rep = dos_codec.write(neutral, deltas=deltas,
                                                  icon=icon)
        return record, itm

    rendered_before, _ = render(before)
    rendered_after, _ = render(after)
    spans, _unplaced = dos_spans(deltas)
    record, _moved = patch(original.to_bytes(), rendered_before,
                           rendered_after, spans)

    edits = _item_edits(before, after, len(original.items))
    nodes, _item_moved = _rewrite_items(
        edits, [node_bytes(i) for i in original.items],
        lambda block: dos_codec.item_from_c64(block, stride),
        dos_item_spans())
    effects = b"".join(bytes(e) for e in original.effects)
    return RewrittenDos(record, b"".join(nodes), effects)


# ---------------------------------------------------------------------------
# Amiga Pool of Radiance
# ---------------------------------------------------------------------------
def rewrite_amiga_por(original: "amiga_por.AmigaPorCharacter",
                      before: CharacterRecord, after: CharacterRecord,
                      game: Any = None,
                      icon: "DosIcon | None" = None) -> RewrittenDos:
    """One Amiga Pool of Radiance character written back.

    The DOS rewrite through :func:`goldbox.amiga_por.write_por`, whose record
    is the DOS one re-cut: `original` is an `AmigaPorCharacter` and the three
    byte strings returned are its `CHRDAT<slot><n>.sav`, `.itm` and `.spc`.

    **`field_83_87` is never copied**, because the Amiga's second insertion
    has not been located inside the run it straddles and there is no offset
    to copy it to; the engine's own bytes stay there.  Nothing the sheet can
    edit reaches that field.
    """
    icon = amiga_combat_icon(original) if icon is None else icon

    def render(rec: CharacterRecord) -> bytes:
        neutral = c64_codec.read(rec, game=game)
        record, _itm, _spc, _rep = amiga_por.write_por(neutral, icon=icon)
        return record

    spans, _unplaced = amiga_por_spans()
    record, _moved = patch(original.raw, render(before), render(after), spans)

    item_spans, _item_unplaced = amiga_item_spans(
        amiga_por.amiga_por_item_offset)
    edits = _item_edits(before, after, len(original.items))
    nodes, _item_moved = _rewrite_items(
        edits, [node_bytes(i) for i in original.items],
        lambda block: amiga_por.amiga_por_item_from_dos(
            dos_codec.item_from_c64(block, dos_port.ITEM_SIZE)),
        item_spans)
    effects = b"".join(bytes(e) for e in original.effects)
    return RewrittenDos(record, b"".join(nodes), effects)


# ---------------------------------------------------------------------------
# Amiga Curse of the Azure Bonds and Secret of the Silver Blades
# ---------------------------------------------------------------------------
def rewrite_amiga_later(original: "amiga_later.AmigaCharacter",
                        before: CharacterRecord, after: CharacterRecord,
                        game: Any = None,
                        icon: "DosIcon | None" = None
                        ) -> "amiga_later.AmigaCharacter":
    """One Amiga Curse or Silver Blades character written back.

    Returns an `AmigaCharacter`, which is what
    :func:`goldbox.amiga_savegame.rebuild` takes: neither title keeps its
    items and effects in sibling files, so the block is the unit.
    :meth:`goldbox.amiga_later.AmigaCharacter.block_bytes` sets `item_count`
    and the two chain heads to match what actually follows, and this sets
    `item_count` in the record it hands back as well so the two agree.

    **The effects are the ones that were read**, as for the other two ports.
    """
    icon = amiga_combat_icon(original) if icon is None else icon
    deltas = original.deltas

    def render(rec: CharacterRecord) -> bytes:
        neutral = c64_codec.read(rec, game=game)
        written, _rep = amiga_later.write_later(neutral, deltas=deltas,
                                                icon=icon)
        return written.raw

    spans, _unplaced = amiga_later_spans(deltas)
    record, _moved = patch(original.raw, render(before), render(after), spans)

    if deltas.item_size is None:
        item_spans: list[Span] = []
    else:
        item_spans, _item_unplaced = amiga_item_spans(deltas.item_offset)
    edits = _item_edits(before, after, len(original.items))
    nodes, _item_moved = _rewrite_items(
        edits, [node_bytes(i) for i in original.items],
        lambda block: amiga_later.amiga_later_item_from_dos(
            dos_codec.item_from_c64(block, deltas.dos.item_size), deltas),
        item_spans)
    items = [amiga_later.AmigaItem.from_bytes(node, deltas) for node in nodes]
    return amiga_later.AmigaCharacter.from_bytes(
        record, deltas, original.source, items, original.effects)

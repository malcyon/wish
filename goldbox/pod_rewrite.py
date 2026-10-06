"""Write an edited Pools of Darkness character back into the save it came
from, span by span.

The character sheet edits this title through its own 510-byte DOS record
(`editor.podsheet.PodSheetRecord`), so the edit arrives here as two DOS
records: the one the sheet was built from and the one it left.  Only the DOS
fields the two disagree about are written; every other byte keeps what the
engine wrote, and a character nobody edited comes back byte for byte.

On DOS the record is the save's own, so a changed field's bytes are copied
straight onto the file (:func:`rewrite_dos`).  The item file is patched node
by node from the sheet's sixteen item slots, and the effect file is returned
as it was read.

On the Amiga the sheet's record is a DOS rendering of the block, so each
changed DOS field is put at its own place in the block's 404-byte record,
in the Amiga's own encoding (:data:`AMIGA_PLACES`, built from
`goldbox.amiga_pod`'s offsets).  A changed field with no place there stops
the rewrite rather than vanishing (:class:`goldbox.rewrite.RewriteError`).
The items, the effects and every byte of the record no changed field owns
stay as the block held them (:func:`rewrite_amiga_record`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from . import amiga_pod, c64_codec, dos_codec, dos_port, rewrite
from .rewrite import RewriteError

DELTAS = dos_port.POOLS_OF_DARKNESS
TABLE = dos_codec.FIELDS_BY_NAME_FOR[DELTAS.key]
RECORD_SIZE = DELTAS.record_size
#: The C64 item block the sheet's inventory holds, and how many it shows.
ITEM_BLOCK = c64_codec.ITEM_SIZE
ITEM_SLOTS = c64_codec.ITEM_SLOTS
#: The first four bytes of a sheet item block: which item it is, rather than
#: what has happened to it (`goldbox.rewrite._C64_ITEM_IDENTITY`).
_ITEM_IDENTITY = 4


def changed_fields(before: bytes, after: bytes) -> list[str]:
    """The DOS fields the two records disagree about, in record order."""
    _check_pair(before, after)
    return [f.name for f in sorted(TABLE.values(), key=lambda f: f.offset)
            if before[f.span] != after[f.span]]


def _check_pair(before: bytes, after: bytes) -> None:
    if not len(before) == len(after) == RECORD_SIZE:
        raise RewriteError(
            f"a Pools of Darkness rewrite compares two {RECORD_SIZE}-byte "
            f"records; got {len(before)} and {len(after)}")


# ---------------------------------------------------------------------------
# DOS
# ---------------------------------------------------------------------------
class RewrittenPodDos(NamedTuple):
    """One DOS character's three files, and the names of what moved."""

    record: bytes
    items: bytes
    effects: bytes
    moved: tuple[str, ...] = ()


def item_blocks(items: Sequence[Any]) -> list[bytes]:
    """The sixteen sheet slots for `items`: item *n* in slot *n*, projected
    by `goldbox.dos_codec.item_to_c64`, empty slots after."""
    shown = [dos_codec.item_to_c64(bytes(i)) for i in items[:ITEM_SLOTS]]
    return shown + [bytes(ITEM_BLOCK)] * (ITEM_SLOTS - len(shown))


def _item_nodes(originals: Sequence[bytes], was: Sequence[bytes],
                now: Sequence[bytes]) -> tuple[list[bytes], list[str]]:
    """The item file's nodes after the sheet's edits, and what moved.

    `originals` are the nodes the engine wrote, `was` the sixteen slots the
    sheet was built from (:func:`item_blocks` of them) and `now` the slots as
    the sheet left them.  A slot whose block is the next original slot's
    unchanged keeps that original node whole, so deleting an item, which
    closes the gap, moves no other item's bytes.  Two items whose slots read
    the same are one item to the sheet, so deleting either keeps the later
    node.  A slot whose item is the same item as before (`_ITEM_IDENTITY`)
    is patched field by field; any other filled slot is a new node.  Nodes
    past the sixteenth were never on the sheet and are kept as they were
    read.
    """
    shown = min(len(originals), ITEM_SLOTS)
    if [n for n in range(ITEM_SLOTS) if any(was[n])] != list(range(shown)):
        raise RewriteError(
            f"the sheet's item slots as read do not hold this character's "
            f"first {shown} items in order")
    used: set[int] = set()
    out: list[bytes] = []
    moved: list[str] = []
    stride = DELTAS.item_size

    def render(block: bytes) -> bytes:
        return dos_codec.item_from_c64(block, stride)

    after = 0       # an unchanged item is looked for from here on, in order
    for n in range(ITEM_SLOTS):
        block = now[n]
        if not any(block):
            continue
        same = next((m for m in range(after, shown)
                     if m not in used and was[m] == block), None)
        if same is not None:
            used.add(same)
            after = same + 1
            out.append(bytes(originals[same]))
            if same != n:
                moved.append(f"item {same}: now item {len(out) - 1}")
            continue
        if (n < shown and n not in used
                and was[n][:_ITEM_IDENTITY] == block[:_ITEM_IDENTITY]):
            used.add(n)
            node, names = rewrite.patch(originals[n], render(was[n]),
                                        render(block), rewrite.dos_item_spans())
            out.append(node)
            moved.extend(f"item {n}: {name}" for name in names)
            continue
        out.append(render(block))
        moved.append(f"item {len(out) - 1}: added")
    moved.extend(f"item {m}: deleted" for m in range(shown) if m not in used)
    out.extend(bytes(o) for o in originals[ITEM_SLOTS:])
    return out, moved


def _load(record: bytes, nodes: Sequence[bytes]) -> int:
    """Money plus item weight times quantity, the sum the DOS writer stores
    as `encumbrance` (`goldbox.dos_codec.DosCharacter.expected_encumbrance`)."""
    items = [dos_codec.DosItem(n, DELTAS.item_size) for n in nodes]
    return dos_codec.DosCharacter(record, items, [],
                                  deltas=DELTAS).expected_encumbrance()


def _put_u(record: bytearray, name: str, value: int) -> None:
    f = TABLE[name]
    top = (1 << (8 * f.size)) - 1
    record[f.span] = max(0, min(value, top)).to_bytes(f.size, "little")


def rewrite_dos(original: "dos_codec.DosCharacter", before: bytes,
                after: bytes, items_was: Sequence[bytes] | None = None,
                items_now: Sequence[bytes] | None = None) -> RewrittenPodDos:
    """One DOS character's files with only the edited fields changed.

    `original` is the character as `goldbox.dos_codec.read_character` read
    it; `before` and `after` are the sheet's record as built and as left.
    `items_was` and `items_now` are the sheet's sixteen item slots as built
    and as left; None leaves the item file as it was read.

    When the items or the money moved, `encumbrance` moves by the same
    amount the money and item weight did, as the DOS writer's own sum would
    (`goldbox.dos_codec.write`), so a stored total the engine keeps out of
    step stays out of step by the same amount rather than being replaced;
    `item_count` is written only when the number of nodes changed.
    """
    _check_pair(before, after)
    if original.deltas is not DELTAS:
        raise RewriteError(f"a {original.deltas.key} character is not a "
                           f"Pools of Darkness one")
    originals = [bytes(i) for i in original.items]
    nodes, item_moved = originals, []
    if items_was is not None and items_now is not None:
        nodes, item_moved = _item_nodes(originals, items_was, items_now)
    spans, _unplaced = rewrite.dos_spans(DELTAS)
    record, moved = rewrite.patch(original.to_bytes(), before, after, spans)
    out = bytearray(record)
    if len(nodes) != len(originals):
        _put_u(out, "item_count", len(nodes))
        moved.append("item_count")
    was, now = _load(before, originals), _load(after, nodes)
    if was != now and "encumbrance" not in moved:
        f = TABLE["encumbrance"]
        _put_u(out, "encumbrance",
               int.from_bytes(out[f.span], "little") + now - was)
        moved.append("encumbrance")
    effects = b"".join(bytes(e) for e in original.effects)
    return RewrittenPodDos(bytes(out), b"".join(nodes), effects,
                           tuple(moved + item_moved))


# ---------------------------------------------------------------------------
# Amiga
# ---------------------------------------------------------------------------
class Place(NamedTuple):
    """Where one DOS field lives in an Amiga record, and how it is written.

    `put(record, dos_after, amiga_original)` writes the field's value from
    the edited DOS record into the Amiga record; `span` is the Amiga bytes it
    owns, for a caller that wants to say what moved.
    """

    span: tuple[int, int]
    put: Callable[[bytearray, bytes, bytes], None]


def _copy(name: str, at: int) -> Place:
    f = TABLE[name]

    def put(out: bytearray, dos: bytes, _orig: bytes) -> None:
        out[at:at + f.size] = dos[f.span]
    return Place((at, f.size), put)


def _swapped(name: str, at: int) -> Place:
    """A little-endian DOS number, big-endian on the 68000."""
    f = TABLE[name]

    def put(out: bytearray, dos: bytes, _orig: bytes) -> None:
        out[at:at + f.size] = int.from_bytes(dos[f.span], "little").to_bytes(
            f.size, "big")
    return Place((at, f.size), put)


def _scattered(name: str, offsets: Sequence[int]) -> Place:
    """A DOS field whose bytes the Amiga keeps apart, one offset a byte."""
    f = TABLE[name]

    def put(out: bytearray, dos: bytes, _orig: bytes) -> None:
        for i, at in enumerate(offsets):
            out[at] = dos[f.offset + i]
    return Place((min(offsets), max(offsets) - min(offsets) + 1), put)


def _name(out: bytearray, dos: bytes, _orig: bytes) -> None:
    """The DOS count and fifteen bytes as the Amiga's fifteen, NUL-padded.
    The terminator at `NAME + NAME_LENGTH` is not written."""
    count = dos[TABLE["name_length"].offset]
    text = dos[TABLE["name_text"].span][:count]
    at = amiga_pod.NAME
    out[at:at + amiga_pod.NAME_LENGTH] = text.ljust(amiga_pod.NAME_LENGTH,
                                                     b"\0")


def _memorised(out: bytearray, dos: bytes, _orig: bytes) -> None:
    """The 141 positions: DOS fills them from the end and the Amiga from the
    front, each ascending through memory, so the spells keep their order and
    move to the other end (`goldbox.amiga_pod.PodCharacter.spells_memorised`
    reads them back in the neutral order either way)."""
    ids = bytes(b for b in dos[TABLE["spells_memorised"].span] if b)
    at = amiga_pod.SPELLS_MEMORISED
    size = amiga_pod.SPELLS_MEMORISED_LENGTH
    out[at:at + size] = ids.ljust(size, b"\0")


def _spellbook(out: bytearray, dos: bytes, orig: bytes) -> None:
    """One DOS byte an id as the Amiga's bit an id, bit *i* of byte *i/8*
    for id *i + 1*.  The mask's two bits past the DOS book's 126 ids keep
    the block's own value."""
    book = dos[TABLE["spellbook"].span]
    at = amiga_pod.SPELLBOOK
    mask = bytearray(orig[at:at + amiga_pod.SPELLBOOK_BYTES])
    for i, byte in enumerate(book):
        bit = 1 << (i % 8)
        mask[i // 8] = (mask[i // 8] | bit) if byte else (mask[i // 8] & ~bit)
    out[at:at + amiga_pod.SPELLBOOK_BYTES] = mask


def _amiga_places() -> dict[str, Place]:
    a = amiga_pod
    places = {
        "name_length": Place((a.NAME, a.NAME_LENGTH), _name),
        "name_text": Place((a.NAME, a.NAME_LENGTH), _name),
        "exceptional_strength": _copy("exceptional_strength",
                                      a.EXCEPTIONAL_STRENGTH),
        "spells_memorised": Place((a.SPELLS_MEMORISED,
                                   a.SPELLS_MEMORISED_LENGTH), _memorised),
        "spellbook": Place((a.SPELLBOOK, a.SPELLBOOK_BYTES), _spellbook),
        "thac0_base": _copy("thac0_base", a.THAC0_BASE),
        "race": _copy("race", a.RACE),
        "char_class": _copy("char_class", a.CLASS),
        "paladin_cures": _copy("paladin_cures", a.PALADIN_CURES),
        "age": _swapped("age", a.AGE),
        "hp_max": _copy("hp_max", a.HP_MAX),
        "movement": _copy("movement", a.MOVEMENT),
        "level": _copy("level", a.LEVEL),
        "former_level": _copy("former_level", a.FORMER_LEVEL),
        "field_83_87": _scattered("field_83_87", (
            a.NPC_CONTROL, a.FIELD_83_87_SECOND, a.FIELD_83_87_THIRD,
            a.FIELD_83_87_FOURTH)),
        "platinum": _swapped("platinum", a.PLATINUM),
        "gems": _swapped("gems", a.GEMS),
        "jewelry": _swapped("jewelry", a.JEWELRY),
        "class_levels": _copy("class_levels", a.CLASS_LEVELS),
        "former_class_levels": _copy("former_class_levels",
                                     a.FORMER_CLASS_LEVELS),
        "highest_class_levels": _copy("highest_class_levels",
                                      a.CLASS_LEVELS_HIGHEST),
        "sex": _copy("sex", a.SEX),
        "alignment": _copy("alignment", a.ALIGNMENT),
        "attack_forms": _copy("attack_forms", a.ATTACK_FORMS),
        "armour_class_base": _copy("armour_class_base", a.ARMOUR_CLASS),
        "unnamed_0ab": _copy("unnamed_0ab", a.UNNAMED_0AB),
        "experience": _swapped("experience", a.EXPERIENCE),
        "highest_experience": _swapped("highest_experience",
                                       a.EXPERIENCE_HIGHEST),
        "highest_hp_max": _copy("highest_hp_max", a.HP_MAX_HIGHEST),
        "class_bits": _copy("class_bits", a.CLASS_BITS),
        "hp_rolled": _copy("hp_rolled", a.HP_ROLLED),
        "experience_award": _swapped("experience_award", a.EXPERIENCE_AWARD),
        "size": _copy("size", a.SIZE),
        "ready_to_train": _copy("ready_to_train", a.READY_TO_TRAIN),
        "thac0_current": _copy("thac0_current", a.THAC0_CURRENT),
        "armour_class": _copy("armour_class", a.ARMOUR_CLASS_CURRENT),
        "roster_tail": _copy("roster_tail", a.ROSTER_TAIL),
        "hp_current": _copy("hp_current", a.HP_CURRENT),
        "movement_current": _copy("movement_current", a.MOVEMENT_CURRENT),
    }
    for i, ability in enumerate(("strength", "intelligence", "wisdom",
                                 "dexterity", "constitution", "charisma")):
        places[ability] = _copy(ability, a.ABILITIES + 2 * i)
    for i, save in enumerate(("save_paralysis", "save_petrification",
                              "save_wands", "save_breath", "save_spell")):
        places[save] = _copy(save, a.SAVING_THROWS + i)
    for i, skill in enumerate(("thief_pick_pockets", "thief_open_locks",
                               "thief_find_traps", "thief_move_silently",
                               "thief_hide_in_shadows", "thief_hear_noise",
                               "thief_climb_walls", "thief_read_languages")):
        places[skill] = _copy(skill, a.THIEF_SKILLS + i)
    for i, cls in enumerate(a.SPELL_SLOT_CLASSES):
        name = "spells_castable_" + cls.replace("-", "_")
        places[name] = _copy(name, a.SPELLS_CASTABLE
                             + a.SPELL_SLOT_LEVELS * i)
    return places


#: DOS field -> its place in the Amiga record.  A DOS field missing here has
#: no place the Amiga reader (`goldbox.amiga_pod.pod_to_neutral`) reads back:
#: the heap and chain words, the item and effect bookkeeping, the derived
#: encumbrance and hands, the combat icon, the roster slot, the gaps, and
#: `turn_class`, whose Amiga byte neither reader reads.
AMIGA_PLACES: dict[str, Place] = _amiga_places()


def rewrite_amiga_record(block: bytes, before: bytes,
                         after: bytes) -> tuple[bytes, list[str]]:
    """`block` with each DOS field `before` and `after` disagree about put
    at its Amiga place, and the names of those fields.

    `block` is the character's whole block as the saved game holds it --
    the 404-byte record, its items, its effects -- and comes back the same
    length; only record bytes a changed field owns can move.
    """
    record = amiga_pod.RECORD_BYTES
    if len(block) < record:
        raise RewriteError(f"an Amiga Pools of Darkness block is at least "
                           f"{record} bytes, got {len(block)}")
    moved = changed_fields(before, after)
    placeless = [name for name in moved if name not in AMIGA_PLACES]
    if placeless:
        raise RewriteError(
            f"the Amiga record has no place for {', '.join(placeless)}, so "
            f"the edit would not be written")
    out = bytearray(block)
    done: set[int] = set()
    for name in moved:
        place = AMIGA_PLACES[name]
        if id(place.put) in done:
            continue
        done.add(id(place.put))
        place.put(out, after, bytes(block))
    return bytes(out), moved


def replace_records(data: bytes, characters: Sequence[Any],
                    blocks: Sequence[bytes]) -> bytes:
    """A `SavGam<L>.pty` with each character's block put back where
    `goldbox.amiga_savegame.pod_parse` found it.  Every block keeps its
    length, so nothing else in the file moves."""
    out = bytearray(data)
    for character, block in zip(characters, blocks):
        if len(block) != character.size:
            raise RewriteError(
                f"{character.name}'s block is {character.size} bytes and "
                f"its rewrite {len(block)}")
        out[character.at:character.at + character.size] = block
    return bytes(out)

"""Export a save's party to YAML and import it back.

The design goal is a **lossless round-trip**: exporting a save and importing it
unchanged must reproduce the original file byte for byte. That is what makes the
tool safe to use on a real save, and it is asserted by the tests.

Only fields we actually understand are editable. Everything else — the ~82% of
each record still unidentified, the party header, and everything in
`SAVEDGAME1` past its first page — is carried through untouched, because an edit
must never destroy bytes whose meaning we do not know.

Two files make up a save, and both are written. `SAVEDGAME0` holds the character
records; `SAVEDGAME1` opens with eight roster blocks holding the values the game
*derives* — armour class, THAC0, current hit points, movement and the damage
bonus. Those appear under `combat:`, together with the three bytes at
`+0x03`–`+0x05` whose meaning is not established, and are the only part of
`SAVEDGAME1` this module touches.

Two fields the game stores twice are kept in step, because writing one without
the other leaves a record no save has ever been seen in: the class code at
`0x073` follows the bitmask at `0x0EB`, and the character level at `0x0A0`
follows the per-class level array.

Items keep their raw bytes in the YAML alongside friendly values. On import the
raw bytes are the starting point and the friendly fields are applied over them,
so an item survives a round-trip exactly while `readied` and `quantity` remain
editable. Item *names* are indices into the game's own table and are exported
for reference only.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from . import derive
from .d64 import D64
from .icons import icon_for_slot
from .items import (
    ITEM_AREA_BASE,
    ITEM_BLOCK_STRIDE,
    ITEM_SIZE,
    ITEMS_PER_CHARACTER,
    ItemNameError,
    build_item,
    items_for_slot,
    load_item_names,
    load_item_templates,
    load_item_types,
    word_index,
)
from .record import CharacterRecord
from .savegame import SAVE0_LOAD_ADDRESS, SaveGame0, SaveGame1, SaveGameError
from .spells import (
    LAST_SPELL,
    capacity,
    describe,
    load_spell_names,
    spellbook_bytes,
    spells_known,
)

RACES = {1: "dwarf", 2: "elf", 3: "gnome", 4: "half-elf",
         5: "halfling", 6: "half-orc", 7: "human", 8: "monster"}
ALIGNMENTS = ["lawful good", "lawful neutral", "lawful evil",
              "neutral good", "true neutral", "neutral evil",
              "chaotic good", "chaotic neutral", "chaotic evil"]
CLASS_BITS = [(1, "magic-user"), (2, "cleric"), (4, "thief"), (8, "fighter")]
# Per-class levels, in the same order as the bits above.
LEVEL_FIELDS = {"magic-user": "level_magic_user", "cleric": "level_cleric",
                "thief": "level_thief", "fighter": "level_fighter"}
SEXES = {0: "male", 1: "female"}


class ValueError_(ValueError):
    """Raised with a message a person can act on."""


def _decode(table: dict[int, str], value: int, field: str) -> str | int:
    """Number -> name, leaving anything unrecognised as the raw number."""
    return table.get(value, value)


def _encode(table: dict[int, str], value, field: str) -> int:
    """Name -> number, accepting a raw number too."""
    if isinstance(value, int):
        return value
    wanted = str(value).strip().lower()
    for num, name in table.items():
        if name == wanted:
            return num
    options = ", ".join(sorted(table.values()))
    raise ValueError_(f"{field}: {value!r} is not valid. Use one of: {options}")


def classes_to_names(bits: int) -> list[str]:
    names = [name for bit, name in CLASS_BITS if bits & bit]
    if not names:                       # unknown encoding: keep it visible
        return [bits]
    return names


def names_to_classes(value) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = [value]
    bits = 0
    known = {name: bit for bit, name in CLASS_BITS}
    for item in value:
        if isinstance(item, int):
            bits |= item
            continue
        key = str(item).strip().lower()
        if key not in known:
            raise ValueError_(
                f"classes: {item!r} is not valid. Use any of: "
                f"{', '.join(known)} (a character may have more than one)")
        bits |= known[key]
    return bits


# Scalar record fields the YAML exposes for editing, ordered to match the
# in-game character sheet -- abilities STR/INT/WIS/DEX/CON/CHR, and money from
# jewelry down to copper, as the game lists them.
EDITABLE = [
    "name", "sex", "race", "age", "alignment",   # see FRIENDLY below
    "strength", "exceptional_strength", "intelligence", "wisdom",
    "dexterity", "constitution", "charisma",
    "hp_max", "hp_rolled",
    "jewelry", "gems", "platinum", "gold", "electrum", "silver", "copper",
    "movement", "infravision",
    "save_paralysis", "save_petrification", "save_wands",
    "save_breath", "save_spell",
    "thief_pick_pockets", "thief_open_locks", "thief_find_traps",
    "thief_move_silently", "thief_hide_in_shadows", "thief_hear_noise",
    "thief_climb_walls", "thief_read_languages",
    "portrait_head", "portrait_body",
]

# These appear in EDITABLE for ordering, but carry names rather than numbers in
# the YAML and are converted separately on import.
FRIENDLY = {"sex", "race", "alignment"}

# Inline guidance emitted next to fields whose numbers mean nothing on sight.
FIELD_COMMENTS = {
    "sex": "male or female",
    "race": ("dwarf, elf, gnome, half-elf, halfling, half-orc, human, "
             "monster"),
    "portrait_head": "which HEADnn file the character sheet draws",
    "portrait_body": "which BODYnn file the character sheet draws",
    "alignment": ("lawful good     lawful neutral    lawful evil\n"
                  "neutral good    true neutral      neutral evil\n"
                  "chaotic good    chaotic neutral   chaotic evil"),
    "classes": ("one or more of: magic-user, cleric, thief, fighter\n"
                "e.g. [magic-user, thief] for a multi-class character"),
    "class_code": ("the game stores the class twice: as the list above, and as\n"
                   "this single code. Edit `classes` and this follows. They can\n"
                   "disagree -- the game ships NPCs that do -- so it is left\n"
                   "alone unless you change one of them."),
    "levels": ("one level per class above. A dual-classed human keeps the old\n"
               "class frozen at its level while the new one advances, so these\n"
               "can differ. Adding a class here starts it at level 1."),
    "level": ("the character level the game keeps separately from the array\n"
              "above. Edit `levels` and this follows automatically; edit this\n"
              "and your value is kept."),
    "npc": ("true for a companion the party picked up rather than one you\n"
            "made. This is bit 7 of 0x0B8, the byte the game itself tests --\n"
            "it counts player characters with it and refuses a seventh."),
    "exceptional_strength": "0-100, only meaningful when strength is 18",
    "experience": "24-bit, so up to 16777215",
}

# char_class (0x073) says the same thing as the class_bits mask (0x0EB), and
# every specimen encodes it twice and agrees. Writing one without the other
# leaves a record no save has ever been seen in, so we keep them in step.
# Codes are the game's own, from the table the 1989 BASIC editor displays,
# which agrees with all four multi-class codes derived from the bitmask.
CLASS_CODES = {
    2: 0,        # cleric
    8: 2,        # fighter
    1: 5,        # magic-user
    4: 6,        # thief
    2 | 8: 8,        # cleric/fighter
    1 | 2 | 8: 9,    # cleric/fighter/magic-user
    1 | 2: 11,       # cleric/magic-user
    2 | 4: 12,       # cleric/thief
    1 | 8: 13,       # fighter/magic-user
    4 | 8: 14,       # fighter/thief
    1 | 4 | 8: 15,   # fighter/magic-user/thief
    1 | 4: 16,       # magic-user/thief
}


def class_code_for(bits: int) -> int:
    """The single class code matching a class bitmask.

    Three combinations have no code in the game's table -- magic-user/cleric/
    thief, cleric/thief/fighter, and all four at once. Refuse them rather than
    write a code that means something else.
    """
    try:
        return CLASS_CODES[bits]
    except KeyError:
        raise ValueError_(
            f"the game has no class code for {classes_to_names(bits)}; "
            f"valid combinations are: "
            + "; ".join(sorted(", ".join(classes_to_names(b))
                               for b in CLASS_CODES))) from None


# Groups get a blank line and a heading, so a long record stays readable.
SECTIONS = {
    "strength": "abilities",
    "hp_max": "hit points",
    "jewelry": "money",
    "movement": "movement and vision",
    "save_paralysis": "saving throws (derived -- the game may recompute these)",
    "thief_pick_pockets": "thief skills (derived; zero for non-thieves)",
}

# Experience is a 24-bit field and the layout now says so, so these are one
# line each. Kept as names rather than inlined because they read better at the
# call sites and because "u24" is what the format calls it.
def _u24(rec: CharacterRecord) -> int:
    return rec.get("experience")


def _set_u24(rec: CharacterRecord, value: int) -> None:
    rec.set("experience", value)


def _consistency(rec, block, payload, slot, names, types, spell_names):
    """Everything about this character that does not add up.

    Two kinds. The combat numbers are **cached** by the game and go stale when
    an ability score is edited, so they are checked against the rules. The
    spells are checked against each other: a memorised spell should be one the
    character knows, and no more should be memorised at a level than the
    character's class, level and Wisdom allow.

    Reported, never enforced. Neither rule has been proven by writing a save
    that breaks it and watching the game load it.
    """
    if types:
        readied = [(i, types[i.type_index])
                   for i in items_for_slot(payload, slot, names)
                   if i.readied and i.type_index in types]
        yield from derive.check(rec, block, readied)

    book = set(spells_known(rec.to_bytes()))
    memorised = [b for b in rec.get_raw("spells_memorised") if b]
    for sid in sorted(set(memorised) - book):
        yield (f"{describe(sid, spell_names)} is memorised but is not in the "
               f"spellbook")
    cap = capacity(rec.class_bits, rec.get("level"), rec.get("wisdom"))
    if cap:
        for level in (1, 2, 3):
            group = [s for s in memorised if _spell_level(s) == level]
            allowed = max((v[level - 1] for v in cap.values()), default=0)
            if len(group) > allowed:
                yield (f"{len(group)} spells memorised at level {level}, but "
                       f"only {allowed} may be")


def _spell_level(spell_id: int) -> int | None:
    from .spells import spell_group
    group = spell_group(spell_id)
    return group[1] if group else None


def _read_save1(img: D64) -> SaveGame1 | None:
    """SAVEDGAME1, or None if this disk has no such file.

    A game disk's sample save carries only SAVEDGAME0, so the combat block is
    optional rather than required.
    """
    try:
        return SaveGame1.from_prg(img.read_file(b"SAVEDGAME1"))
    except Exception:
        return None


def export_save(path: str, game_disk: str | None = None) -> dict[str, Any]:
    """Read a save disk and return the whole party as plain data."""
    img = D64.open(path)
    sg = SaveGame0.from_prg(img.read_file(b"SAVEDGAME0"))
    payload = sg.to_bytes()
    sg1 = _read_save1(img)

    names = types = spell_names = None
    if game_disk:
        try:
            names = load_item_names(game_disk)
        except Exception:
            names = None
        try:
            types = load_item_types(game_disk)
        except Exception:
            types = None
        try:
            spell_names = load_spell_names(game_disk)
        except Exception:
            spell_names = None

    party = []
    for slot in sg.characters:
        rec = slot.record
        entry: dict[str, Any] = {"slot": slot.index}
        for f in EDITABLE:
            entry[f] = rec.get(f)
        # Present the opaque numbers as names. The bitmask, the race table and
        # the alignment index are implementation details; a person editing this
        # file should not have to know them.
        entry["sex"] = _decode(SEXES, rec.sex, "sex")
        entry["race"] = _decode(RACES, rec.race, "race")
        entry["alignment"] = _decode(dict(enumerate(ALIGNMENTS)),
                                     rec.alignment, "alignment")
        entry["classes"] = classes_to_names(rec.class_bits)
        entry["class_code"] = rec.get("char_class")
        # One level per class the character actually has. A dual-classed human
        # keeps the old class at its frozen level while the new one advances,
        # which this represents directly.
        entry["levels"] = {name: rec.get(field)
                           for name, field in LEVEL_FIELDS.items()
                           if rec.class_bits & dict((n, b) for b, n in CLASS_BITS)[name]}
        entry["experience"] = _u24(rec)
        entry["items"] = []
        for it in items_for_slot(payload, slot.index, names):
            row: dict[str, Any] = {
                "name": it.name or "?", "readied": it.readied,
                "bonus": it.bonus, "quantity": it.quantity,
                "cost_gp": it.cost_gp, "weight_lb": it.weight_lb,
                "type": it.type_index, "identified": it.is_identified,
            }
            if not it.is_identified:
                row["_shows_as"] = it.unidentified_name
            kind = (types or {}).get(it.type_index)
            if kind is not None:
                row["_type_summary"] = kind.summary()
            row["raw"] = it.raw.hex()
            entry["items"].append(row)
        entry["icon"] = {
            "shape": icon_for_slot(payload, slot.index).shape.hex(),
            "colours": icon_for_slot(payload, slot.index).colours.hex(),
        }
        # The character level the game itself keeps, separate from the
        # per-class array above. They agree in every specimen, and every
        # specimen is single-class.
        entry["level"] = rec.get("level")
        entry["npc"] = rec.is_npc
        # The ids a character has memorised, highest spell level first.
        ids = [b for b in rec.get_raw("spells_memorised") if b]
        entry["spells"] = ids
        if ids:
            entry["_spells_named"] = [describe(i, spell_names) for i in ids]
        book = spells_known(rec.to_bytes())
        entry["spells_known"] = book
        if book:
            entry["_spells_known_named"] = [describe(i, spell_names) for i in book]
        cap = capacity(rec.class_bits, rec.get("level"), rec.get("wisdom"))
        if cap:
            entry["_spell_capacity"] = "; ".join(
                "%s %s" % (k, "/".join(str(n) for n in v)) for k, v in cap.items())
        if sg1 is not None:
            block = sg1.roster(slot.index)
            warnings = list(_consistency(rec, block, payload, slot.index,
                                         names, types, spell_names))
            if warnings:
                entry["_warnings"] = warnings
            entry["combat"] = {
                "armour_class": block.armour_class,
                "thac0": block.thac0,
                "damage_bonus": block.damage_bonus,
                "hp_current": block.hit_points,
                "movement_current": block.movement,
                "unknown_03_05": list(block.unknown_03_05),
            }
        party.append(entry)

    return {
        # Absolute, so `--import` can default to it and the YAML alone is
        # enough to reproduce an edit. The only non-party key, and the only one
        # that is data rather than guidance.
        "source_path": str(pathlib.Path(path).resolve()),
        "party": party,
    }


def _scalar(value: Any) -> str:
    """One value, quoted the way PyYAML would, so round-tripping is exact."""
    return yaml.safe_dump(value, default_flow_style=True).strip().rstrip("...").strip()


def _class_block(entry: dict[str, Any]) -> list[str]:
    """Class, levels and experience together -- they belong side by side, and
    the game's own character sheet shows level and experience on one line."""
    out = ["", "    # --- class"]
    for line in FIELD_COMMENTS["classes"].split("\n"):
        out.append(f"    # {line}")
    out.append(f"    classes: [{', '.join(str(c) for c in entry['classes'])}]")
    if "class_code" in entry:
        for line in FIELD_COMMENTS["class_code"].split("\n"):
            out.append(f"    # {line}")
        out.append(f"    class_code: {entry['class_code']}")
    for line in FIELD_COMMENTS["levels"].split("\n"):
        out.append(f"    # {line}")
    pairs = ", ".join(f"{k}: {v}" for k, v in entry["levels"].items())
    out.append(f"    levels: {{{pairs}}}")
    if "npc" in entry:
        for line in FIELD_COMMENTS["npc"].split("\n"):
            out.append(f"    # {line}")
        out.append(f"    npc: {_scalar(entry['npc'])}")
    if "level" in entry:
        for line in FIELD_COMMENTS["level"].split("\n"):
            out.append(f"    # {line}")
        out.append(f"    level: {entry['level']}")
    out.append(f"    experience: {entry['experience']}"
               f"    # {FIELD_COMMENTS['experience']}")
    return out


def strip_annotations(data: dict[str, Any]) -> dict[str, Any]:
    """The same document without its presentation-only keys.

    Keys beginning with `_` carry text we render as a YAML *comment* rather
    than as data -- currently just the item-type summary. They are derived from
    the game disk, not from the save, so they must not survive a round-trip.
    """
    out = dict(data)
    out["party"] = [{k: v for k, v in e.items() if not k.startswith("_")}
                    if not isinstance(e, dict) else
                    {k: (v if k != "items" else
                         [{ik: iv for ik, iv in it.items()
                           if not ik.startswith("_")} for it in v])
                     for k, v in e.items() if not k.startswith("_")}
                    for e in data.get("party", [])]
    return out


def to_yaml(data: dict[str, Any]) -> str:
    """Emit the document with field comments and in-game ordering.

    Hand-rolled because PyYAML cannot write comments. `yaml.safe_load` reads it
    back identically -- asserted in the tests -- and every scalar is rendered by
    PyYAML itself, so quoting and escaping stay correct.
    """
    out: list[str] = []
    name = pathlib.Path(data.get("source_path", "")).name or "save disk"
    out += [
        f"# Pool of Radiance character export -- {name}",
        "#",
        "# Edit any field below, then write it to a NEW disk with:",
        "#     wish.py --import <this file> --output NEW.D64",
        "#",
        "# The original disk is never modified. Unknown bytes and the party",
        "# header are carried through untouched.",
        "#",
        "# `combat:` is the one part of SAVEDGAME1 this file reaches. The game",
        "# caches those values rather than deriving them on load, so they can",
        "# go stale -- see the note above each block.",
        "",
        f"source_path: {_scalar(data['source_path'])}",
        "",
        "party:",
    ]

    for n, entry in enumerate(data["party"]):
        if n:
            out.append("")
        out.append(f"  - slot: {entry['slot']}")
        for field in EDITABLE:
            if field not in entry:
                continue
            if field in SECTIONS:
                out.append("")
                out.append(f"    # --- {SECTIONS[field]}")
            comment = FIELD_COMMENTS.get(field)
            if comment and "\n" in comment:
                for line in comment.split("\n"):
                    out.append(f"    # {line}")
                out.append(f"    {field}: {_scalar(entry[field])}")
            elif comment:
                out.append(f"    {field}: {_scalar(entry[field])}    # {comment}")
            else:
                out.append(f"    {field}: {_scalar(entry[field])}")

            if field == "alignment":
                out += _class_block(entry)


        out.append("")
        out += [
            "    # --- items. 'raw' is the whole 16-byte record and wins where it",
            "    # is present; the fields above it are applied over it. To CHANGE an",
            "    # item, edit a field. To DELETE one, remove its entry. To ADD one,",
            f"    # append an entry with no 'raw' (up to {ITEMS_PER_CHARACTER} per character):",
            "    #     - template: LONG SWORD +1",
            "    #       readied: true",
            "    # A template copies a real record out of the game's own item",
            "    # files, which is the best way to add a magical item: the bytes",
            "    # we do not understand come with it. docs/87-item-templates.md",
            "    # lists all 163. Failing that, build one from words and type:",
            "    #     - words: [LONG SWORD, '', '+1']   # noun, qualifier, suffix",
            "    #       type: 36                        # docs/85-item-tables.md",
            "    #       bonus: 1",
        ]
        if not entry["items"]:
            out.append("    items: []")
        else:
            out.append("    items:")
            for item in entry["items"]:
                out.append(f"      - name: {_scalar(item['name'])}")
                for k in ("readied", "bonus", "quantity", "cost_gp", "weight_lb"):
                    out.append(f"        {k}: {_scalar(item[k])}")
                shows = item.get("_shows_as")
                out.append(f"        identified: {_scalar(item['identified'])}"
                           + (f"    # unidentified, shows as {shows!r}"
                              if shows else ""))
                summary = item.get("_type_summary")
                out.append(f"        type: {_scalar(item['type'])}"
                           + (f"    # {summary}" if summary else ""))
                out.append(f"        raw: {_scalar(item['raw'])}")

        if entry.get("spells_known") is not None:
            out.append("")
            out += [
                "    # --- spells the character KNOWS: the spellbook. A cleric",
                "    # knows every spell of every level they can cast; a magic-user",
                "    # knows only what they have learned. Ids: docs/86-spell-table.md.",
            ]
            cap = entry.get("_spell_capacity")
            if cap:
                out.append(f"    # can memorise, by spell level: {cap}")
            if not entry["spells_known"]:
                out.append("    spells_known: []")
            else:
                named = entry.get("_spells_known_named") or []
                out.append("    spells_known:")
                for n_, sid in enumerate(entry["spells_known"]):
                    label = f"    # {named[n_]}" if n_ < len(named) else ""
                    out.append(f"      - {sid}{label}")

        if entry.get("spells") is not None:
            out.append("")
            out += [
                "    # --- spells currently MEMORISED, by id, highest level first.",
                "    # A subset of spells_known, limited by the capacity above.",
            ]
            if not entry["spells"]:
                out.append("    spells: []")
            else:
                named = entry.get("_spells_named") or []
                out.append("    spells:")
                for n_, sid in enumerate(entry["spells"]):
                    label = f"    # {named[n_]}" if n_ < len(named) else ""
                    out.append(f"      - {sid}{label}")

        if entry.get("_warnings"):
            out.append("")
            out.append("    # !! this character does not add up:")
            for line in entry["_warnings"]:
                out.append(f"    #    {line}")
            out += [
                "    # The combat numbers are cached by the game and only",
                "    # refreshed when equipment changes, so editing an ability",
                "    # score leaves them stale. Re-ready a weapon or a piece of",
                "    # armour in game, or correct them under `combat:` below.",
            ]

        combat = entry.get("combat")
        if combat:
            out.append("")
            out += [
                "    # --- combat (cached by the game in SAVEDGAME1, not in the",
                "    # character record). It recomputes armour class and THAC0 when",
                "    # equipment changes and never when an ability score changes, so",
                "    # raising dexterity here will not move armour_class by itself.",
                "    combat:",
                f"      armour_class: {_scalar(combat['armour_class'])}",
                f"      thac0: {_scalar(combat['thac0'])}",
                "      # strength bonus plus the readied weapon's own bonus",
                f"      damage_bonus: {_scalar(combat['damage_bonus'])}",
                f"      hp_current: {_scalar(combat['hp_current'])}",
                "      # drops with armour: 12 unencumbered, 9 in banded mail",
                f"      movement_current: {_scalar(combat['movement_current'])}",
                "      # three bytes whose meaning is NOT established. They were",
                "      # read as per-level spell counts, which fitted one save and",
                "      # is contradicted by another -- see docs/30-savegame-layout.md.",
                f"      unknown_03_05: [{', '.join(str(n) for n in combat['unknown_03_05'])}]",
            ]

        out.append("")
        out.append("    # --- combat icon: 18 screen codes, then 18 colours (0-15)")
        out.append("    icon:")
        out.append(f"      shape: {_scalar(entry['icon']['shape'])}")
        out.append(f"      colours: {_scalar(entry['icon']['colours'])}")

    return "\n".join(out) + "\n"


# Field name in the YAML -> attribute on a RosterBlock.
COMBAT_FIELDS = {
    "armour_class": "armour_class",
    "thac0": "thac0",
    "damage_bonus": "damage_bonus",
    "hp_current": "hit_points",
    "movement_current": "movement",
    "unknown_03_05": "unknown_03_05",
}


def _apply_combat(block, combat: dict[str, Any], slot: int, who: str) -> list[str]:
    """Write the SAVEDGAME1 roster fields, reporting what moved."""
    changes: list[str] = []
    for key, attr in COMBAT_FIELDS.items():
        if key not in combat:
            continue
        old = getattr(block, attr)
        new = combat[key]
        if attr == "unknown_03_05":
            new = tuple(int(n) for n in new)
        else:
            new = int(new)
        if new != old:
            try:
                setattr(block, attr, new)
            except SaveGameError as exc:
                raise ValueError_(f"slot {slot} {who}: {key}: {exc}") from None
            changes.append(f"slot {slot} {who}: {key} {old!r} -> {new!r}")
    return changes


def _tenths(value) -> int:
    return int(round(float(value) * 10))


def _item_bytes(item: dict[str, Any], names, where: str,
                templates: dict[str, bytes] | None = None) -> bytes:
    """The 16 bytes one YAML item entry describes.

    Three ways to say what an item is, in order of preference:

    * `raw` -- the whole record, which is what an export carries, so a
      round-trip is exact;
    * `template` -- copy a real record out of the game's own item files, which
      is much the best way to add a magical item, because every byte we do not
      understand comes along with it;
    * `words` and `type` -- build one from nothing, leaving those bytes zero.
    """
    base = None
    if item.get("raw") is not None:
        base = bytes.fromhex(str(item["raw"]))
        if len(base) != ITEM_SIZE:
            raise ValueError_(f"{where}: raw must be {ITEM_SIZE} bytes")
    elif item.get("template") is not None:
        wanted = str(item["template"]).strip()
        if not templates:
            raise ValueError_(
                f"{where}: 'template' needs a game disk to copy from; pass "
                f"--game-disk")
        match = next((v for k, v in templates.items()
                      if k.upper() == wanted.upper()), None)
        if match is None:
            raise ValueError_(
                f"{where}: no item called {wanted!r} on the game disks. "
                f"docs/87-item-templates.md lists them")
        base = match

    if base is None and not item.get("words"):
        raise ValueError_(
            f"{where}: an item needs 'raw', 'template', or 'words' (the "
            f"printed name as noun, qualifier, suffix)")

    def num(key, default=0):
        return default if item.get(key) is None else int(item[key])

    try:
        if base is None:
            return build_item(
                type_index=num("type"), words=item.get("words", ()),
                bonus=num("bonus"), quantity=num("quantity"),
                cost_gp=num("cost_gp"),
                weight_tenths=_tenths(item.get("weight_lb", 0)),
                readied=bool(item.get("readied")), names=names)
        raw = bytearray(base)
        if "readied" in item:
            raw[6] = (raw[6] | 0x80) if item["readied"] else (raw[6] & ~0x80)
        if item.get("type") is not None:
            raw[0] = num("type") & 0xFF
        if item.get("bonus") is not None:
            raw[4] = num("bonus") & 0xFF
        if item.get("quantity") is not None:
            raw[10] = num("quantity") & 0xFF
        if item.get("cost_gp") is not None:
            cost = num("cost_gp")
            if not 0 <= cost <= 0xFFFF:
                raise ValueError_(f"{where}: cost_gp must be 0-65535")
            raw[11], raw[12] = cost & 0xFF, cost >> 8
        if item.get("identified") is not None:
            if item["identified"]:
                raw[6] &= ~0x07
            elif not (raw[6] & 0x07):
                raise ValueError_(
                    f"{where}: cannot un-identify an item without knowing "
                    f"which name words to hide; copy a template instead")
        if item.get("weight_lb") is not None:
            wt = _tenths(item["weight_lb"])
            if not 0 <= wt <= 0xFFFF:
                raise ValueError_(f"{where}: weight_lb must be 0-6553.5")
            raw[8], raw[9] = wt & 0xFF, wt >> 8
        if item.get("words"):
            words = [word_index(names or {}, w) for w in list(item["words"])[:3]]
            words += [0] * (3 - len(words))
            raw[3], raw[2], raw[1] = words
        return bytes(raw)
    except ItemNameError as exc:
        raise ValueError_(f"{where}: {exc}") from None


def _apply_npc(rec, entry, slot: int, who: str) -> list[str]:
    """The NPC flag: bit 7 of 0x0B8, and nothing else.

    Pulled out of `import_into` because it is genuinely self-contained. Most of
    the rest of that function is not -- the class, per-class level and character
    level blocks share `classes_changed` and `levels_changed`, and separating
    them mechanically drops the coupling and breaks fifty tests. They stay
    together on purpose; see the comments there.
    """
    if "npc" not in entry or bool(entry["npc"]) == rec.is_npc:
        return []
    rec.set_npc(bool(entry["npc"]))
    return [
        f"slot {slot} {who}: npc {not entry['npc']} -> {bool(entry['npc'])}",
        f"slot {slot} {who}: NOTE only bit 7 of 0x0B8 was written. The eight "
        f"$FF residue bytes are left as found, so a character made an NPC this "
        f"way still looks like a player character to anything reading those "
        f"instead",
    ]


def import_into(save_path: str, data: dict[str, Any], out_path: str,
                game_disk: str | None = None) -> list[str]:
    """Apply a parsed YAML document to a save disk, writing to `out_path`.

    Returns a human-readable list of the changes made. The input file is never
    modified; the caller chooses the destination.
    """
    img = D64.open(save_path)
    sg = SaveGame0.from_prg(img.read_file(b"SAVEDGAME0"))
    sg1 = _read_save1(img)
    names = templates = None
    if game_disk:
        try:
            names = load_item_names(game_disk)
        except Exception:
            names = None
        try:
            templates = load_item_templates(game_disk, names)
        except Exception:
            templates = None
    changes: list[str] = []

    for entry in data.get("party", []):
        slot = entry["slot"]
        rec = sg.slot(slot).record
        if rec is None:
            raise ValueError(f"slot {slot} holds no character")
        who = rec.name

        for f in EDITABLE:
            if f not in entry or f in FRIENDLY:
                continue
            old = rec.get(f)
            new = entry[f]
            if new != old:
                rec.set(f, new)
                changes.append(f"slot {slot} {who}: {f} {old!r} -> {new!r}")

        for field, table in (("sex", SEXES), ("race", RACES),
                             ("alignment", dict(enumerate(ALIGNMENTS)))):
            if field not in entry:
                continue
            want = _encode(table, entry[field], field)
            if want != rec.get(field):
                changes.append(f"slot {slot} {who}: {field} "
                               f"{_decode(table, rec.get(field), field)!r} -> "
                               f"{entry[field]!r}")
                rec.set(field, want)

        # The next eighty lines -- classes, class code, per-class levels,
        # character level -- look like four independent blocks and are not. They
        # share `classes_changed` and `levels_changed`, and those two flags are
        # the whole reason the round trip is lossless: each says "the user
        # actually edited this", and without them the importer rewrites fields
        # nobody touched. Splitting them into separate functions was tried and
        # dropped the coupling silently; fifty tests caught it. They belong
        # together.
        #
        # The game stores the class twice, at 0x0EB as a bitmask and at 0x073
        # as a single code, and they do NOT always agree: DWARVEN FIGHTER
        # carries a fighter's bits and a cleric's code, and two more NPCs
        # disagree too. So reconcile them only when the classes were actually
        # edited. Left alone, a record that disagrees survives untouched --
        # which is what makes the round-trip lossless for an NPC.
        classes_changed = False
        if "classes" in entry:
            want = names_to_classes(entry["classes"])
            if want != rec.class_bits:
                classes_changed = True
                changes.append(f"slot {slot} {who}: classes "
                               f"{classes_to_names(rec.class_bits)} -> "
                               f"{entry['classes']}")
                rec.class_bits = want

        # class_code follows the bitmask when the classes were edited, unless
        # the file gives one of its own -- which is how an NPC-shaped record
        # gets written deliberately.
        old_code = rec.get("char_class")
        given_code = entry.get("class_code")
        # A code equal to the one exported was not touched by anybody, so it
        # does not count as an instruction -- same rule as `level`.
        explicit = given_code is not None and int(given_code) != old_code
        if explicit:
            want_code = int(given_code)
        elif classes_changed:
            want_code = class_code_for(rec.class_bits)
        else:
            want_code = old_code
        if want_code != old_code:
            if not 0 <= want_code <= 0xFF:
                raise ValueError_(
                    f"slot {slot} {who}: class_code must be 0-255")
            changes.append(f"slot {slot} {who}: class_code {old_code} -> "
                           f"{want_code}")
            rec.set("char_class", want_code)
            if want_code != class_code_for(rec.class_bits):
                changes.append(
                    f"slot {slot} {who}: NOTE class_code {want_code} does not "
                    f"match classes {classes_to_names(rec.class_bits)}. The "
                    f"game ships NPCs like that, but no player character has "
                    f"ever been seen that way")

        # Levels follow the classes, but only when the classes were edited: a
        # class newly present with no level given starts at 1, and a class just
        # removed has its level cleared. Otherwise only explicit values apply,
        # so a record whose array disagrees with its bits survives a round-trip.
        levels = entry.get("levels") or {}
        levels_changed = False
        for name, field in LEVEL_FIELDS.items():
            bit = dict((n, b) for b, n in CLASS_BITS)[name]
            if name in levels:
                want_level = int(levels[name])
            elif not classes_changed:
                continue
            elif rec.class_bits & bit:
                want_level = rec.get(field) or 1
            else:
                want_level = 0
            if want_level != rec.get(field):
                levels_changed = True
                changes.append(f"slot {slot} {who}: {name} level "
                               f"{rec.get(field)} -> {want_level}")
                rec.set(field, want_level)
        if not rec.npc_marker_is_consistent:
            changes.append(
                f"slot {slot} {who}: WARNING the eight NPC marker bytes disagree "
                f"with each other. No real save has been seen like that")
        changes += _apply_npc(rec, entry, slot, who)

        if "spells_known" in entry:
            book = [int(s) for s in (entry["spells_known"] or [])]
            for sid in book:
                if not 1 <= sid <= LAST_SPELL:
                    raise ValueError_(
                        f"slot {slot} {who}: {sid} is not a spell id "
                        f"(1-{LAST_SPELL})")
            want = spellbook_bytes(book)
            if want != rec.get_raw("spells_known"):
                changes.append(
                    f"slot {slot} {who}: spells_known "
                    f"{spells_known(rec.to_bytes())} -> {sorted(book)}")
                rec.set_raw("spells_known", want)

        if "spells" in entry:
            ids = [int(s) for s in (entry["spells"] or [])]
            if len(ids) > 16:
                raise ValueError_(
                    f"slot {slot} {who}: {len(ids)} memorised spells, but only "
                    f"16 fit in the record")
            for sid in ids:
                if not 1 <= sid <= LAST_SPELL:
                    raise ValueError_(
                        f"slot {slot} {who}: {sid} is not a spell id "
                        f"(1-{LAST_SPELL}); above that the table continues "
                        f"with combat messages")
            want = bytes(ids) + bytes(16 - len(ids))
            if want != rec.get_raw("spells_memorised"):
                changes.append(
                    f"slot {slot} {who}: spells "
                    f"{[b for b in rec.get_raw('spells_memorised') if b]} -> {ids}")
                rec.set_raw("spells_memorised", want)
                changes.append(
                    f"slot {slot} {who}: NOTE a memorised spell should also be "
                    f"in spells_known, and within the capacity the character's "
                    f"class, level and wisdom allow. Neither is enforced")

        # Character level. Reconcile it with the per-class array only when that
        # array was edited -- editing `levels` alone must not leave the two
        # disagreeing, but an import that edits nothing must not touch it
        # either. A record can arrive already disagreeing: `0x0A0` is the
        # leading candidate for *level highest*, so a level-drained character
        # disagrees by construction, and rewriting it would finish the drain.
        old_level = rec.get("level")
        per_class = [rec.get(f) for f in LEVEL_FIELDS.values() if rec.get(f)]
        want_level = int(entry.get("level", old_level))
        if (want_level == old_level and levels_changed
                and per_class and max(per_class) != old_level):
            want_level = max(per_class)
            if len(per_class) > 1:
                changes.append(
                    f"slot {slot} {who}: NOTE level set to {want_level}, the "
                    f"highest of the per-class levels. What this byte holds "
                    f"for a multi-class character is unproven -- no specimen "
                    f"above level 1 is multi-class")
        if want_level != old_level:
            changes.append(f"slot {slot} {who}: level {old_level} -> {want_level}")
            rec.set("level", want_level)

        if "experience" in entry and entry["experience"] != _u24(rec):
            changes.append(f"slot {slot} {who}: experience "
                           f"{_u24(rec)} -> {entry['experience']}")
            _set_u24(rec, entry["experience"])

        sg.write_record(slot, rec)

        # items: start from the raw bytes, apply the editable overrides
        payload = bytearray(sg.to_bytes())
        base = ITEM_AREA_BASE - SAVE0_LOAD_ADDRESS + slot * ITEM_BLOCK_STRIDE
        given = entry.get("items") or []
        if len(given) > ITEMS_PER_CHARACTER:
            raise ValueError_(
                f"slot {slot} {who}: {len(given)} items, but a character can "
                f"carry at most {ITEMS_PER_CHARACTER}")
        # Every slot is written, so removing an entry deletes that item rather
        # than leaving the old bytes behind. The game packs items from slot 0
        # with no gaps -- checked across every specimen -- so this is exact.
        for n in range(ITEMS_PER_CHARACTER):
            off = base + n * ITEM_SIZE
            old = bytes(payload[off:off + ITEM_SIZE])
            if n < len(given):
                item = given[n]
                raw = _item_bytes(item, names, f"slot {slot} item {n}",
                                  templates)
                label = item.get("name") or item.get("template") or "?"
            else:
                raw, label = bytes(ITEM_SIZE), None
            if raw != old:
                if label is None:
                    changes.append(f"slot {slot} {who}: item {n} removed")
                elif not any(old):
                    changes.append(f"slot {slot} {who}: item {n} added ({label})")
                else:
                    changes.append(f"slot {slot} {who}: item {n} ({label}) changed")
            payload[off:off + ITEM_SIZE] = raw

        # icon
        icon = entry.get("icon")
        if icon:
            from .icons import ICON_SIZE, ICON_TABLE_BASE
            new_icon = bytearray.fromhex(icon["shape"]) + bytearray.fromhex(icon["colours"])
            if len(new_icon) != ICON_SIZE:
                raise ValueError(f"slot {slot}: icon must total {ICON_SIZE} bytes")
            ibase = ICON_TABLE_BASE - SAVE0_LOAD_ADDRESS + slot * ICON_SIZE
            if bytes(new_icon) != bytes(payload[ibase:ibase + ICON_SIZE]):
                changes.append(f"slot {slot} {who}: combat icon changed")
            payload[ibase:ibase + ICON_SIZE] = new_icon

        sg = SaveGame0.from_bytes(bytes(payload))

        combat = entry.get("combat")
        if combat:
            if sg1 is None:
                raise ValueError_(
                    f"slot {slot}: the YAML carries a combat block but "
                    f"{save_path} has no SAVEDGAME1 to write it to")
            changes += _apply_combat(sg1.roster(slot), combat, slot, who)

    img.write_file_inplace(b"SAVEDGAME0", sg.to_prg())
    if sg1 is not None:
        img.write_file_inplace(b"SAVEDGAME1", sg1.to_prg())
    img.save(out_path)
    return changes

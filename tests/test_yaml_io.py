"""Tests for the YAML export/import round-trip.

The property that matters is **losslessness**: exporting a save and importing it
unchanged must reproduce the file byte for byte. Everything else the editor does
rests on that, because ~88% of each record is still unidentified and must be
carried through untouched.
"""

import pathlib

import pytest
import yaml
from gamedata import disk_dir

from goldbox.d64 import D64
from goldbox.savegame import SaveGame0
from goldbox.yaml_io import export_save, import_into, strip_annotations, to_yaml

# Wherever the player keeps them, not wherever one machine did.
DISKS = str(disk_dir() or "no-disks-here")
SAVE = f"{DISKS}/PORSAVE2.D64"
GAME = "work/POOL1.D64.orig"

# Needs a specimen under `work/`, which is gitignored: a checkout without
# it skips rather than fails.
pytestmark = pytest.mark.skipif(
    not pathlib.Path(GAME).exists(),
    reason="needs the disks under work/")


live = pytest.mark.skipif(not pathlib.Path(SAVE).exists(),
                          reason="needs a real save disk")


@live
def test_export_finds_the_whole_party():
    data = export_save(SAVE, GAME)
    assert len(data["party"]) == 6
    assert {e["name"] for e in data["party"]} == {
        "MALCYON", "LADY KATHERINE", "ROLAND", "SILAS", "MAGNUS", "BRUTUS"}


@live
def test_yaml_survives_a_serialisation_cycle():
    data = export_save(SAVE, GAME)
    # `_`-prefixed keys are rendered as comments, so they do not come back.
    assert yaml.safe_load(to_yaml(data)) == strip_annotations(data)


@live
def test_round_trip_is_byte_identical(tmp_path):
    """Export, import unchanged, and the disk must be bit-for-bit the same."""
    data = export_save(SAVE, GAME)
    out = tmp_path / "rt.d64"
    changes = import_into(SAVE, data, str(out))
    assert changes == []
    assert out.read_bytes() == pathlib.Path(SAVE).read_bytes()


@live
def test_editing_one_field_changes_exactly_one_byte(tmp_path):
    data = export_save(SAVE, GAME)
    target = next(e for e in data["party"] if e["name"] == "MALCYON")
    target["platinum"] = 99
    out = tmp_path / "edited.d64"
    changes = import_into(SAVE, data, str(out))
    assert len(changes) == 1 and "platinum" in changes[0]
    before, after = pathlib.Path(SAVE).read_bytes(), out.read_bytes()
    differing = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    assert len(differing) == 1


@live
def test_unknown_bytes_are_preserved(tmp_path):
    """An edit to SAVEDGAME0 must not disturb the header, SAVEDGAME1, or any
    unidentified byte. SAVEDGAME1 is writable now, but only the combat block
    reaches it -- a change to gold must leave it byte-identical."""
    data = export_save(SAVE, GAME)
    next(e for e in data["party"] if e["name"] == "BRUTUS")["gold"] = 123
    out = tmp_path / "e.d64"
    import_into(SAVE, data, str(out))
    a = SaveGame0.from_prg(D64.open(SAVE).read_file(b"SAVEDGAME0")).to_bytes()
    b = SaveGame0.from_prg(D64.open(str(out)).read_file(b"SAVEDGAME0")).to_bytes()
    assert a[:0x400] == b[:0x400]                       # party header untouched
    assert (D64.open(SAVE).read_file(b"SAVEDGAME1")
            == D64.open(str(out)).read_file(b"SAVEDGAME1"))


@live
def test_items_and_icons_survive_untouched(tmp_path):
    data = export_save(SAVE, GAME)
    out = tmp_path / "i.d64"
    import_into(SAVE, data, str(out))
    a = SaveGame0.from_prg(D64.open(SAVE).read_file(b"SAVEDGAME0")).to_bytes()
    b = SaveGame0.from_prg(D64.open(str(out)).read_file(b"SAVEDGAME0")).to_bytes()
    assert a[0x2E0:0x400] == b[0x2E0:0x400]             # icon table
    assert a[0x1000:] == b[0x1000:]                     # item area onward


@live
def test_readied_flag_is_editable(tmp_path):
    data = export_save(SAVE, GAME)
    brutus = next(e for e in data["party"] if e["name"] == "BRUTUS")
    brutus["items"][0]["readied"] = not brutus["items"][0]["readied"]
    out = tmp_path / "r.d64"
    changes = import_into(SAVE, data, str(out))
    assert any("item 0" in c for c in changes)


@live
def test_field_order_matches_the_game_sheet():
    """Abilities STR/INT/WIS/DEX/CON/CHR and money jewelry-down-to-copper, as
    the game lists them -- the money order was previously reversed."""
    text = to_yaml(export_save(SAVE, GAME))
    def order(names):
        return [text.index(f"\n    {n}:") for n in names]
    abilities = ["strength", "intelligence", "wisdom",
                 "dexterity", "constitution", "charisma"]
    money = ["jewelry", "gems", "platinum", "gold", "electrum", "silver", "copper"]
    assert order(abilities) == sorted(order(abilities))
    assert order(money) == sorted(order(money))


@live
def test_comments_list_the_valid_names():
    text = to_yaml(export_save(SAVE, GAME))
    assert "male or female" in text
    assert "human" in text
    assert "chaotic evil" in text
    assert "one or more of: magic-user, cleric, thief, fighter" in text


@live
def test_comments_do_not_affect_what_is_parsed():
    """The emitter is hand-rolled, so prove PyYAML reads back exactly the same
    data it would have without comments."""
    data = export_save(SAVE, GAME)
    parsed = yaml.safe_load(to_yaml(data))
    assert parsed["source_path"] == data["source_path"]
    assert set(parsed) == {"source_path", "game", "party"}  # guidance is comments, not data
    assert len(parsed["party"]) == len(data["party"])
    for got, want in zip(parsed["party"], strip_annotations(data)["party"]):
        for field, value in want.items():
            assert got[field] == value, field


def test_quoting_survives_awkward_names():
    """Scalars are rendered by PyYAML itself, so apostrophes are safe."""
    doc = {"source_path": "/tmp/x.d64", "party": [{
        "slot": 0, "name": "WILLIAM D'OR", "sex": "male", "race": "human",
        "age": 21, "alignment": "lawful good", "classes": ["fighter"],
        "levels": {"fighter": 1}, "experience": 0, "items": [],
        "icon": {"shape": "00", "colours": "01"}}]}
    assert yaml.safe_load(to_yaml(doc))["party"][0]["name"] == "WILLIAM D'OR"


# ---------------------------------------------------------------------------
# Friendly values: the YAML shows names, not the raw encodings
# ---------------------------------------------------------------------------
from goldbox.yaml_io import (  # noqa: E402
    ValueError_,
    classes_to_names,
    names_to_classes,
)


def test_class_bitmask_is_hidden_behind_names():
    assert classes_to_names(5) == ["magic-user", "thief"]
    assert classes_to_names(9) == ["magic-user", "fighter"]
    assert names_to_classes(["magic-user", "thief"]) == 5
    assert names_to_classes(["fighter"]) == 8


def test_class_names_round_trip_for_every_combination():
    for bits in range(1, 16):
        assert names_to_classes(classes_to_names(bits)) == bits


def test_class_names_are_case_and_order_insensitive():
    assert names_to_classes(["Thief", "MAGIC-USER"]) == 5


def test_raw_numbers_are_still_accepted():
    """Forgiving input: a person may write the number if they prefer."""
    assert names_to_classes(5) == 5


def test_bad_class_name_explains_itself():
    with pytest.raises(ValueError_) as e:
        names_to_classes(["paladin"])
    assert "paladin" in str(e.value) and "magic-user" in str(e.value)


@live
def test_yaml_shows_names_not_numbers():
    text = to_yaml(export_save(SAVE, GAME))
    assert "sex: female" in text
    assert "race: half-elf" in text
    assert "alignment: neutral evil" in text
    assert "classes: [magic-user, thief]" in text
    assert "class_bits" not in text            # the encoding is fully hidden


@live
def test_names_survive_a_round_trip(tmp_path):
    data = export_save(SAVE, GAME)
    out = tmp_path / "rt.d64"
    assert import_into(SAVE, data, str(out)) == []
    assert out.read_bytes() == pathlib.Path(SAVE).read_bytes()


@live
def test_editing_by_name_works(tmp_path):
    data = export_save(SAVE, GAME)
    k = next(e for e in data["party"] if e["name"] == "LADY KATHERINE")
    k["alignment"] = "chaotic evil"
    k["classes"] = ["magic-user", "thief", "fighter"]
    out = tmp_path / "e.d64"
    changes = import_into(SAVE, data, str(out))
    assert any("alignment" in c for c in changes)
    assert any("classes" in c for c in changes)
    after = export_save(str(out), GAME)
    got = next(e for e in after["party"] if e["name"] == "LADY KATHERINE")
    assert got["alignment"] == "chaotic evil"
    assert got["classes"] == ["magic-user", "thief", "fighter"]


@live
def test_guidance_is_comments_not_data():
    """The header explains the file without becoming a field you could edit."""
    text = to_yaml(export_save(SAVE, GAME))
    assert text.startswith("# Pool of Radiance character export")
    assert "never modified" in text
    assert "note:" not in text
    assert set(yaml.safe_load(text)) == {"source_path", "game", "party"}


@live
def test_sections_are_separated_by_blank_lines():
    text = to_yaml(export_save(SAVE, GAME))
    for heading in ("abilities", "money", "class", "items", "combat icon"):
        assert f"\n\n    # --- {heading}" in text, heading


# ---------------------------------------------------------------------------
# Per-class levels, which is what makes dual-classing representable
# ---------------------------------------------------------------------------
@live
def test_every_class_has_a_level_and_only_those_classes():
    """Across all specimens a level is non-zero exactly where the class bit is
    set -- 12 for 12, including five multi-class characters."""
    for entry in export_save(SAVE, GAME)["party"]:
        assert set(entry["levels"]) == set(entry["classes"])
        assert all(v > 0 for v in entry["levels"].values())


@live
def test_levels_survive_a_round_trip(tmp_path):
    data = export_save(SAVE, GAME)
    out = tmp_path / "rt.d64"
    assert import_into(SAVE, data, str(out)) == []


@live
def test_dual_classing_can_be_expressed(tmp_path):
    """Donald's Gold Box Companion observation: a human gains a second class
    while the first stays frozen at its level."""
    data = export_save(SAVE, GAME)
    silas = next(e for e in data["party"] if e["name"] == "SILAS")
    assert silas["classes"] == ["fighter"]
    silas["classes"] = ["thief", "fighter"]
    silas["levels"] = {"thief": 1, "fighter": 3}
    out = tmp_path / "dual.d64"
    import_into(SAVE, data, str(out))
    after = next(e for e in export_save(str(out), GAME)["party"]
                 if e["name"] == "SILAS")
    assert after["classes"] == ["thief", "fighter"]
    assert after["levels"] == {"thief": 1, "fighter": 3}


@live
def test_adding_a_class_defaults_it_to_level_1(tmp_path):
    data = export_save(SAVE, GAME)
    who = next(e for e in data["party"] if e["name"] == "ROLAND")
    who["classes"] = ["cleric", "fighter"]          # no level given for fighter
    out = tmp_path / "add.d64"
    import_into(SAVE, data, str(out))
    after = next(e for e in export_save(str(out), GAME)["party"]
                 if e["name"] == "ROLAND")
    assert after["levels"]["fighter"] == 1


@live
def test_removing_a_class_clears_its_level(tmp_path):
    data = export_save(SAVE, GAME)
    k = next(e for e in data["party"] if e["name"] == "LADY KATHERINE")
    k["classes"] = ["magic-user"]                   # drop thief
    out = tmp_path / "rm.d64"
    import_into(SAVE, data, str(out))
    after = next(e for e in export_save(str(out), GAME)["party"]
                 if e["name"] == "LADY KATHERINE")
    assert after["classes"] == ["magic-user"]
    assert "thief" not in after["levels"]


@live
def test_class_block_sits_between_alignment_and_abilities():
    """Reading order follows the character sheet: who they are, then what they
    are, then their numbers."""
    text = to_yaml(export_save(SAVE, GAME))
    assert text.index("\n    alignment:") \
        < text.index("\n    # --- class") \
        < text.index("\n    # --- abilities")


# --- SAVEDGAME1: the combat block -------------------------------------------

@live
def test_combat_block_is_exported():
    data = export_save(SAVE, GAME)
    malcyon = next(e for e in data["party"] if e["name"] == "MALCYON")
    # Checked against the character sheet on screen.
    assert malcyon["combat"] == {
        "armour_class": 8, "thac0": 20, "damage_bonus": 0, "hp_current": 4,
        "movement_current": 12, "unknown_03_05": [0, 0, 0],
    }
    # movement in the record is the *base*; the roster's drops with armour.
    roland = next(e for e in data["party"] if e["name"] == "ROLAND")
    assert roland["movement"] == 12 and roland["combat"]["movement_current"] == 9


@live
def test_combat_edits_reach_savedgame1_and_touch_nothing_else(tmp_path):
    data = export_save(SAVE, GAME)
    malcyon = next(e for e in data["party"] if e["name"] == "MALCYON")
    malcyon["combat"]["armour_class"] = 2
    malcyon["combat"]["hp_current"] = 3
    out = tmp_path / "c.d64"
    import_into(SAVE, data, str(out))

    before = D64.open(SAVE).read_file(b"SAVEDGAME1")
    after = D64.open(str(out)).read_file(b"SAVEDGAME1")
    differing = [i for i in range(len(before)) if before[i] != after[i]]
    assert differing == [2 + 0x0F, 2 + 0x19]           # AC and current HP only
    assert after[2 + 0x0F] == 60 - 2                   # stored as 60 - AC
    assert after[2 + 0x19] == 3
    # SAVEDGAME0 is not involved
    assert (D64.open(SAVE).read_file(b"SAVEDGAME0")
            == D64.open(str(out)).read_file(b"SAVEDGAME0"))


@live
def test_out_of_range_combat_value_is_refused(tmp_path):
    data = export_save(SAVE, GAME)
    next(e for e in data["party"] if e["name"] == "MALCYON")["combat"]["armour_class"] = 999
    with pytest.raises(ValueError, match="does not fit"):
        import_into(SAVE, data, str(tmp_path / "x.d64"))


# --- the two fields the game stores twice -----------------------------------

@live
def test_editing_levels_carries_the_character_level_with_it(tmp_path):
    """0x0A0 and the per-class array must not be left disagreeing. Before this
    was fixed, editing `levels` moved one and not the other."""
    data = export_save(SAVE, GAME)
    roland = next(e for e in data["party"] if e["name"] == "ROLAND")
    assert roland["level"] == 1
    roland["levels"]["cleric"] = 3
    out = tmp_path / "l.d64"
    import_into(SAVE, data, str(out))
    rec = _record(out, "ROLAND")
    assert rec.get("level_cleric") == 3
    assert rec.get("level") == 3


@live
def test_an_explicit_level_wins_over_the_derived_one(tmp_path):
    data = export_save(SAVE, GAME)
    roland = next(e for e in data["party"] if e["name"] == "ROLAND")
    roland["levels"]["cleric"] = 3
    roland["level"] = 5
    out = tmp_path / "l2.d64"
    import_into(SAVE, data, str(out))
    assert _record(out, "ROLAND").get("level") == 5


@live
def test_editing_classes_carries_char_class_with_it(tmp_path):
    """0x073 and the 0x0EB bitmask say the same thing, and every specimen
    agrees. Writing one without the other leaves a record no save has been
    seen in."""
    data = export_save(SAVE, GAME)
    silas = next(e for e in data["party"] if e["name"] == "SILAS")
    silas["classes"] = ["fighter", "cleric"]
    out = tmp_path / "cc.d64"
    import_into(SAVE, data, str(out))
    rec = _record(out, "SILAS")
    assert rec.get("class_bits") == 0b1010          # fighter | cleric
    assert rec.get("char_class") == 8               # the game's cleric/fighter code


@live
def test_a_class_combination_the_game_cannot_encode_is_refused(tmp_path):
    data = export_save(SAVE, GAME)
    next(e for e in data["party"] if e["name"] == "SILAS")["classes"] = [
        "magic-user", "cleric", "thief"]
    with pytest.raises(ValueError, match="no class code"):
        import_into(SAVE, data, str(tmp_path / "y.d64"))


def _record(disk, name):
    sg = SaveGame0.from_prg(D64.open(str(disk)).read_file(b"SAVEDGAME0"))
    return next(s.record for s in sg.characters if s.record.name == name)


# --- items: the type table, construction and removal -------------------------

@live
def test_item_type_summary_is_exported_as_a_comment_only():
    """The summary is derived from the game disk, not the save, so it must not
    come back through a round-trip as data."""
    data = export_save(SAVE, GAME)
    kath = next(e for e in data["party"] if e["name"] == "LADY KATHERINE")
    sword = kath["items"][0]
    assert sword["type"] == 37 and sword["bonus"] == 0
    assert "1d6" in sword["_type_summary"] and "fighter" in sword["_type_summary"]
    assert "_type_summary" not in yaml.safe_load(to_yaml(data))["party"][1]["items"][0]


@live
def test_an_item_can_be_built_from_words(tmp_path):
    data = export_save(SAVE, GAME)
    kath = next(e for e in data["party"] if e["name"] == "LADY KATHERINE")
    kath["items"] = kath["items"][:2] + [{
        "name": "LONG SWORD +1", "words": ["LONG SWORD", "", "+1"],
        "type": 36, "bonus": 1, "cost_gp": 3500, "weight_lb": 6.0,
        "readied": True}]
    out = tmp_path / "build.d64"
    import_into(SAVE, data, str(out), game_disk=GAME)

    made = _items(out, 1)[2]
    assert made.name == "LONG SWORD +1"
    assert (made.bonus, made.cost_gp, made.weight_lb, made.readied) == (1, 3500, 6.0, True)
    assert made.type_index == 36


@live
def test_removing_an_entry_removes_the_item(tmp_path):
    """Every slot is written, so a shorter list really deletes. Before this,
    the old bytes were left in place and the item survived."""
    data = export_save(SAVE, GAME)
    kath = next(e for e in data["party"] if e["name"] == "LADY KATHERINE")
    assert len(kath["items"]) == 3
    kath["items"] = kath["items"][:1]
    out = tmp_path / "del.d64"
    import_into(SAVE, data, str(out), game_disk=GAME)
    assert [i.name for i in _items(out, 1)] == ["SHORT SWORD"]


@live
def test_too_many_items_is_refused(tmp_path):
    data = export_save(SAVE, GAME)
    kath = next(e for e in data["party"] if e["name"] == "LADY KATHERINE")
    kath["items"] = kath["items"] * 6            # 18, over the 16 the game holds
    with pytest.raises(ValueError, match="at most 16"):
        import_into(SAVE, data, str(tmp_path / "many.d64"), game_disk=GAME)


@live
def test_an_ambiguous_item_word_is_refused(tmp_path):
    """RING appears twice in the name table and the two are not the same
    thing, so guessing would build the wrong item."""
    data = export_save(SAVE, GAME)
    next(e for e in data["party"] if e["name"] == "LADY KATHERINE")["items"] = [
        {"name": "RING", "words": ["RING"], "type": 66}]
    with pytest.raises(ValueError, match="appears at indices"):
        import_into(SAVE, data, str(tmp_path / "amb.d64"), game_disk=GAME)


# --- NPCs --------------------------------------------------------------------

@live
def test_the_party_is_all_player_characters():
    data = export_save(SAVE, GAME)
    assert all(e["npc"] is False for e in data["party"])


@live
def test_the_npc_flag_writes_only_the_byte_the_game_tests(tmp_path):
    """The eight $FF residue bytes must be left exactly as found. They are fill
    that survives the load, not a marker, and rewriting them would be the
    editor inventing state."""
    from goldbox.record import NPC_FLAG_BIT, NPC_FLAG_OFFSET, NPC_MARKER_OFFSETS
    data = export_save(SAVE, GAME)
    before = _record(SAVE, "MALCYON").to_bytes()
    next(e for e in data["party"] if e["name"] == "MALCYON")["npc"] = True
    out = tmp_path / "npc.d64"
    changes = import_into(SAVE, data, str(out), game_disk=GAME)
    rec = _record(out, "MALCYON")
    assert rec.is_npc
    raw = rec.to_bytes()
    assert raw[NPC_FLAG_OFFSET] & NPC_FLAG_BIT
    assert all(raw[o] == before[o] for o in NPC_MARKER_OFFSETS)
    assert any("NOTE" in c for c in changes)          # the caveat is reported


@live
def test_clearing_the_npc_flag_leaves_the_rest_of_0x0b8_alone(tmp_path):
    """Bit 0 records that a score was altered at the trainer. Toggling npc
    must not disturb it."""
    from goldbox.record import NPC_FLAG_OFFSET
    data = export_save(SAVE, GAME)
    entry = next(e for e in data["party"] if e["name"] == "MALCYON")
    entry["npc"] = True
    once = tmp_path / "on.d64"
    import_into(SAVE, data, str(once), game_disk=GAME)
    back = export_save(str(once), GAME)
    next(e for e in back["party"] if e["name"] == "MALCYON")["npc"] = False
    twice = tmp_path / "off.d64"
    import_into(str(once), back, str(twice), game_disk=GAME)
    assert (_record(twice, "MALCYON").to_bytes()[NPC_FLAG_OFFSET]
            == _record(SAVE, "MALCYON").to_bytes()[NPC_FLAG_OFFSET])


def _items(disk, slot):
    from goldbox.items import items_for_slot, load_item_names
    from goldbox.savegame import SaveGame0
    payload = SaveGame0.from_prg(D64.open(str(disk)).read_file(b"SAVEDGAME0")).to_bytes()
    return items_for_slot(payload, slot, load_item_names(GAME))


# --- memorised spells --------------------------------------------------------

SAVE4 = f"{DISKS}/PORSAVE4.D64"
live4 = pytest.mark.skipif(not pathlib.Path(SAVE4).exists(),
                           reason="needs the spell-memorising save")


@live4
def test_memorised_spells_match_what_donald_memorised():
    """Ground truth: ROLAND memorised Cure Light Wounds twice and Bless;
    MALCYON and LADY KATHERINE each memorised Sleep."""
    data = export_save(SAVE4, GAME)
    by = {e["name"]: e for e in data["party"]}
    assert by["ROLAND"]["spells"] == [3, 3, 1]
    assert by["MALCYON"]["spells"] == [21]
    assert by["LADY KATHERINE"]["spells"] == [21]
    assert by["SILAS"]["spells"] == []
    assert by["ROLAND"]["_spells_named"][0] == "CURE LIGHT WOUNDS (cleric 1)"
    assert by["MALCYON"]["_spells_named"] == ["SLEEP (magic-user 1)"]


@live4
def test_spells_can_be_edited(tmp_path):
    data = export_save(SAVE4, GAME)
    next(e for e in data["party"] if e["name"] == "MALCYON")["spells"] = [15, 21]
    out = tmp_path / "sp.d64"
    changes = import_into(SAVE4, data, str(out), game_disk=GAME)
    assert _record(out, "MALCYON").get_raw("spells_memorised")[:3] == bytes([15, 21, 0])
    assert any("NOTE" in c for c in changes)      # the count caveat is reported


@live4
def test_a_combat_message_id_is_not_a_spell(tmp_path):
    """Ids above 56 continue the same table with combat messages."""
    data = export_save(SAVE4, GAME)
    next(e for e in data["party"] if e["name"] == "MALCYON")["spells"] = [99]
    with pytest.raises(ValueError, match="is not a spell id"):
        import_into(SAVE4, data, str(tmp_path / "bad.d64"), game_disk=GAME)


@live4
def test_current_hit_points_differ_from_maximum():
    """LADY KATHERINE took one point of damage: the first specimen where the
    roster's current total is not simply a copy of hp_max."""
    data = export_save(SAVE4, GAME)
    kath = next(e for e in data["party"] if e["name"] == "LADY KATHERINE")
    assert kath["hp_max"] == 5
    assert kath["combat"]["hp_current"] == 4
    assert all(e["combat"]["hp_current"] == e["hp_max"]
               for e in data["party"] if e["name"] != "LADY KATHERINE")


@live4
def test_the_spellbook_is_exported_and_editable(tmp_path):
    """0x078-0x07E is what a character KNOWS, distinct from what is memorised.
    Clerics know every spell of every level they can cast; magic-users a subset."""
    data = export_save(SAVE4, GAME)
    by = {e["name"]: e for e in data["party"]}
    assert by["ROLAND"]["spells_known"] == [1, 2, 3, 4, 5, 6, 7, 8]     # all cleric 1
    assert by["MALCYON"]["spells_known"] == [11, 18, 19, 21]            # the starting mage book
    assert by["SILAS"]["spells_known"] == []                            # a fighter knows none
    # every memorised spell is one the character knows
    for e in data["party"]:
        assert set(e["spells"]) <= set(e["spells_known"])

    by["MALCYON"]["spells_known"] = [11, 15, 18, 19, 21]                # learn magic missile
    out = tmp_path / "book.d64"
    import_into(SAVE4, data, str(out), game_disk=GAME)
    from goldbox.spells import spells_known
    assert spells_known(_record(out, "MALCYON").to_bytes()) == [11, 15, 18, 19, 21]


@live4
def test_capacity_is_derived_not_read():
    """No field holds it; it follows from class, level and Wisdom -- and it
    matches what each caster actually has memorised."""
    from goldbox.spells import capacity
    data = export_save(SAVE4, GAME)
    by = {e["name"]: e for e in data["party"]}
    assert by["ROLAND"]["_spell_capacity"] == "cleric 3/0/0"       # WIS 16 at level 1
    assert by["MALCYON"]["_spell_capacity"] == "magic-user 1/0/0"
    assert len(by["ROLAND"]["spells"]) == 3
    assert capacity(2, 1, 16) == {"cleric": (3, 0, 0)}             # bonus only where castable


# --- templates, and the consistency checks ----------------------------------

@live
def test_an_item_can_be_copied_from_a_game_disk_template(tmp_path):
    """A template brings the bytes we do not understand with it, which is why
    it beats building an item from words."""
    data = export_save(SAVE, GAME)
    kath = next(e for e in data["party"] if e["name"] == "LADY KATHERINE")
    kath["items"].append({"template": "WAND OF MAGIC MISSILES", "readied": True})
    out = tmp_path / "t.d64"
    import_into(SAVE, data, str(out), game_disk=GAME)
    made = _items(out, 1)[-1]
    assert made.name == "WAND OF MAGIC MISSILES" and made.readied
    assert made.effects != (0, 0, 0)          # the effect bytes came across


@live
def test_an_unknown_template_is_refused(tmp_path):
    data = export_save(SAVE, GAME)
    next(e for e in data["party"] if e["name"] == "LADY KATHERINE")["items"] = [
        {"template": "SWORD OF PLOT ADVANCEMENT"}]
    with pytest.raises(ValueError, match="no item called"):
        import_into(SAVE, data, str(tmp_path / "u.d64"), game_disk=GAME)


@live
def test_a_consistent_party_raises_no_warnings():
    """Nobody in the unarmoured save should be flagged. BRUTUS used to be, on
    an armour class one point better than predicted -- which turned out to be
    our dexterity table, not his record."""
    data = export_save(f"{DISKS}/PORSAVE.D64", GAME)
    flagged = {e["name"]: e["_warnings"] for e in data["party"] if e.get("_warnings")}
    assert flagged == {}


@live
def test_the_dexterity_table_starts_a_point_early():
    """Pool of Radiance gives an armour class bonus from DEX 14, where AD&D 1st
    edition starts at 15. Read off the save where nobody wears anything, so
    armour class is 10 minus this and nothing else."""
    from goldbox.derive import dexterity_ac_bonus
    assert dexterity_ac_bonus(13) == 0
    assert dexterity_ac_bonus(14) == 1          # the book says 0
    assert dexterity_ac_bonus(15) == 1
    assert dexterity_ac_bonus(16) == 2
    data = export_save(f"{DISKS}/PORSAVE.D64", GAME)
    by = {e["name"]: e for e in data["party"]}
    assert by["ROLAND"]["dexterity"] == 13 and by["ROLAND"]["combat"]["armour_class"] == 10
    assert by["BRUTUS"]["dexterity"] == 14 and by["BRUTUS"]["combat"]["armour_class"] == 9
    assert by["MAGNUS"]["dexterity"] == 15 and by["MAGNUS"]["combat"]["armour_class"] == 9


@live4
def test_an_edited_ability_score_is_reported_as_stale():
    """MALCYON's dexterity was edited 16 -> 18 and the game never recomputed
    his armour class. This is the check that would have caught it."""
    data = export_save(SAVE4, GAME)
    warnings = next(e for e in data["party"] if e["name"] == "MALCYON")["_warnings"]
    assert any("armour class is cached as 8, but the rules give 6" in w
               for w in warnings)


@live4
def test_spell_inconsistencies_are_reported(tmp_path):
    data = export_save(SAVE4, GAME)
    malcyon = next(e for e in data["party"] if e["name"] == "MALCYON")
    malcyon["spells"] = [21, 15, 9]           # over capacity, two not in his book
    out = tmp_path / "sp.d64"
    import_into(SAVE4, data, str(out), game_disk=GAME)
    warnings = next(e for e in export_save(str(out), GAME)["party"]
                    if e["name"] == "MALCYON")["_warnings"]
    assert any("not in the spellbook" in w for w in warnings)
    assert any("only 1 may be" in w for w in warnings)


# --- records whose class fields disagree, as the game's own NPCs do ----------

def _disagreeing_save(tmp_path):
    """A save where a character has a fighter's bits and a cleric's code --
    the shape DWARVEN FIGHTER has in the shipped game data."""
    import shutil

    from goldbox.savegame import SaveGame0 as SG
    src = tmp_path / "npcish.d64"
    shutil.copy(SAVE, src)
    img = D64.open(str(src))
    sg = SG.from_prg(img.read_file(b"SAVEDGAME0"))
    rec = sg.slot(2).record
    rec.class_bits = 8              # fighter
    rec.set("char_class", 0)        # cleric
    sg.write_record(2, rec)
    img.write_file_inplace(b"SAVEDGAME0", sg.to_prg())
    img.save(str(src))
    return src


@live
def test_a_record_whose_class_fields_disagree_survives_a_round_trip(tmp_path):
    """wish used to force the two into agreement, which silently rewrote a
    byte on an import that edited nothing -- and would corrupt any NPC the
    game ships in that state."""
    src = _disagreeing_save(tmp_path)
    data = export_save(str(src), GAME)
    out = tmp_path / "rt.d64"
    changes = import_into(str(src), data, str(out), game_disk=GAME)
    assert changes == []
    assert src.read_bytes() == out.read_bytes()


@live
def test_the_per_class_levels_survive_it_too(tmp_path):
    """The level array was being reconciled against the bitmask the same way,
    which cleared a level nobody had asked to change."""
    src = _disagreeing_save(tmp_path)
    before = _record(src, "ROLAND").get("level_cleric")
    data = export_save(str(src), GAME)
    out = tmp_path / "lv.d64"
    import_into(str(src), data, str(out), game_disk=GAME)
    assert _record(out, "ROLAND").get("level_cleric") == before


@live
def test_an_npc_shaped_class_code_can_be_written_deliberately(tmp_path):
    src = _disagreeing_save(tmp_path)
    data = export_save(str(src), GAME)
    next(e for e in data["party"] if e["slot"] == 2)["class_code"] = 9
    out = tmp_path / "npc.d64"
    changes = import_into(str(src), data, str(out), game_disk=GAME)
    assert _record(out, "ROLAND").get("char_class") == 9
    assert _record(out, "ROLAND").get("class_bits") == 8      # bits untouched
    assert any("does not match classes" in c for c in changes)

from __future__ import annotations

"""The live actions, driven against a dictionary of bytes.

Nothing here needs an emulator: `MemoryTarget` is a `Target`, so an action that
writes through one is exercised exactly as it would be against VICE or a
Commodore 64 Ultimate -- and the assertions are on the addresses written, which
is the part that has to be right.

The party is the same captured machine `tests/test_automap.py` uses: BRUTUS
alone in New Phlan, `SAVEDGAME0` and the roster page as the live view reads
them.
"""


import pathlib

import pytest

from automap import actions, live
from automap.target import MemoryTarget
from goldbox import c64_codec, games, levelup
from goldbox import items as por_items
from goldbox.record import RECORD_SIZE, CharacterRecord
from goldbox.savegame import ROSTER_HP_CURRENT

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

WORLD, COMBAT = 1, 2          # $6E11: DUNGEON, COMBAT


def captured() -> tuple[bytearray, bytearray]:
    save0 = bytearray((FIXTURES / "savedgame0.bin").read_bytes()[2:])
    save1 = bytearray((FIXTURES / "savedgame1.bin").read_bytes()[2:])
    return save0, save1[:live.ROSTER_PAGE]


def machine(mode: int = WORLD, hp: int | None = None,
            item: bytes | None = None) -> MemoryTarget:
    """The captured party, optionally wounded or carrying a given item."""
    save0, save1 = captured()
    if hp is not None:
        save1[ROSTER_HP_CURRENT] = hp
    if item is not None:
        at = por_items.ITEM_AREA_BASE - 0x4900
        save0[at:at + len(item)] = item
    return MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(save1),
                         0x6E11: bytes([mode])})


def find(name: str, store=None) -> actions.Action:
    if name == "level-up":
        return actions.LevelUp()      # not on the bar; see the registry test
    for action in actions.actions(store):
        if action.name == name:
            return action
    raise AssertionError(f"no action named {name}")


# --- the gate ----------------------------------------------------------------


def test_the_mode_flag_is_what_decides_combat():
    assert actions.in_combat(machine(COMBAT))
    assert not actions.in_combat(machine(WORLD))


@pytest.mark.parametrize("name", ["heal", "identify", "store-spells",
                                  "restore-spells", "level-up"])
def test_the_actions_that_must_refuse_in_combat_do(name):
    action = find(name)
    verdict = action.legality(machine(COMBAT))
    assert not verdict and "fight" in verdict.reason
    assert not action.apply(machine(COMBAT)).ok


def test_refusing_in_combat_happens_at_apply_and_not_only_in_the_tooltip():
    """A button's enabled state is a poll interval stale, so the write itself
    has to check. Nothing may reach the machine."""
    target = machine(COMBAT)
    before = dict(target.memory)
    assert not find("identify").apply(target).ok
    assert target.memory == before


def test_healing_is_legal_out_of_combat():
    """The half of the gate `test_the_actions_that_must_refuse_in_combat_do`
    does not cover: Donald asked for Heal Party to refuse mid-fight the way
    Store/Restore Spells and Identify already do, and outside a fight it is
    unchanged."""
    assert find("heal").legality(machine(WORLD))


def test_every_action_refuses_with_no_emulator():
    for action in actions.actions():
        verdict = action.legality(None)
        assert not verdict and verdict.reason


def test_a_machine_with_no_party_in_it_refuses_at_apply():
    """Zeros are what the title screen, a disk load and a menu all look like.
    `legality` cannot tell mode 0 from an absent machine -- `read_party` can,
    and refusing there is what keeps a write off an empty slot."""
    empty = MemoryTarget({})
    assert not actions.in_combat(empty)
    outcome = find("heal").apply(empty)
    assert not outcome.ok and outcome.writes == ()


def test_read_party_refuses_a_roster_page_borrowed_by_a_picture():
    """#82: on Silver Blades, a full-screen picture leaves the roster page
    reading as graphics data while the record slots -- read from a different
    page -- are unaffected. `read_party`'s other checks would pass; only the
    roster page is scrap, and `roster_page_plausible` is what catches it."""
    from goldbox.savegame import ROSTER_SLOT_INDEX
    save0, save1 = captured()
    graphics = bytearray(save1)
    graphics[ROSTER_SLOT_INDEX] = 9          # BRUTUS is slot 0; this is not
    borrowed = MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(graphics),
                             0x6E11: bytes([WORLD])})
    assert actions.read_party(borrowed) is None

    # dismissed: the same page restored, and it reads normally again
    restored = MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(save1),
                             0x6E11: bytes([WORLD])})
    party = actions.read_party(restored)
    assert party is not None and party.by_slot(0).name == "BRUTUS"


def test_read_party_refuses_hit_points_above_the_recorded_maximum():
    """The second, independent check #82 names: BRUTUS's maximum is 11."""
    from goldbox.savegame import ROSTER_HP_CURRENT
    save0, save1 = captured()
    over = bytearray(save1)
    over[ROSTER_HP_CURRENT] = 255
    target = MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(over),
                          0x6E11: bytes([WORLD])})
    assert actions.read_party(target) is None


# --- healing -----------------------------------------------------------------


def test_healing_writes_the_roster_byte_and_nothing_else():
    target = machine(hp=5)
    outcome = find("heal").apply(target)
    assert outcome.ok
    assert outcome.writes == ((0x8300 + ROSTER_HP_CURRENT, b"\x0b"),)
    assert target.read(0x8300 + ROSTER_HP_CURRENT, 1) == b"\x0b"
    # One character: named, not counted -- "Healed 1 of 1." said nothing a
    # player could act on.
    assert outcome.message == "Healed BRUTUS up to full."


def test_healing_a_whole_party_writes_nothing_when_nobody_is_hurt():
    outcome = find("heal").apply(machine())
    assert outcome.ok and outcome.writes == ()
    # Nobody healed must not read "Healed  up to full.": the empty-list
    # sentence never reaches this branch, because it returns before the
    # "Healed ..." message is built.
    assert outcome.message == "All party members are at full health."


def test_healing_leaves_a_character_at_zero_alone():
    """Zero is dead or dying, and what else marks that is not decoded. Raising
    the hit point byte alone would be the half-write levelling refuses over."""
    outcome = find("heal").apply(machine(hp=0))
    assert outcome.writes == ()
    assert any("0" in note and "BRUTUS" in note for note in outcome.notes)


def test_healing_says_so_when_maximum_hit_points_do_not_fit_the_roster_byte():
    save0, save1 = captured()
    save0[0x4D00 - 0x4900 + 0x076] = 0x2C        # hp_max = 300, 16-bit at 0x076
    save0[0x4D00 - 0x4900 + 0x077] = 0x01
    save1[ROSTER_HP_CURRENT] = 5
    target = MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(save1),
                           0x6E11: bytes([WORLD])})
    outcome = find("heal").apply(target)
    assert outcome.writes == ((0x8300 + ROSTER_HP_CURRENT, b"\xff"),)
    assert any("255" in note for note in outcome.notes)


def party_of(entries: list[tuple[str, int, int]]) -> MemoryTarget:
    """`len(entries)` characters, each `(name, hp, hp_max)`, built from the
    captured BRUTUS slot -- everything but the name and the two hit-point
    fields is his, copied into as many slots as there are entries."""
    from goldbox.savegame import ROSTER_SLOT_INDEX, ROSTER_STRIDE
    save0, save1 = captured()
    rec_base = games.POOL_OF_RADIANCE.slot_area_base - 0x4900
    template_record = bytes(save0[rec_base:rec_base + 0x100])
    template_roster = bytes(save1[:ROSTER_STRIDE])
    for i, (name, hp, hp_max) in enumerate(entries):
        record = CharacterRecord.from_bytes(
            template_record.ljust(RECORD_SIZE, b"\x00"))
        record.set("name", name)
        record.set("hp_max", hp_max)
        save0[rec_base + i * 0x100:rec_base + (i + 1) * 0x100] = \
            bytes(record)[:0x100]
        roster = bytearray(template_roster)
        roster[ROSTER_SLOT_INDEX] = i
        roster[ROSTER_HP_CURRENT] = hp
        save1[i * ROSTER_STRIDE:(i + 1) * ROSTER_STRIDE] = roster
    return MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(save1),
                         0x6E11: bytes([WORLD])})


def test_healing_names_the_characters_it_healed():
    """Three healed, comma-delimited, in party order -- not a count."""
    target = party_of([("BRUTUS", 5, 11), ("MAGNUS", 3, 9),
                       ("LADY KATHERINE", 6, 12)])
    outcome = find("heal").apply(target)
    assert outcome.ok
    assert outcome.message == "Healed BRUTUS, MAGNUS, LADY KATHERINE up to full."


def test_a_character_already_at_full_is_not_named():
    """Only who was written, taken from `writes` and not from the whole
    party -- MAGNUS is already at his maximum and is skipped."""
    target = party_of([("BRUTUS", 5, 11), ("MAGNUS", 9, 9),
                       ("LADY KATHERINE", 6, 12)])
    outcome = find("heal").apply(target)
    assert outcome.ok
    assert outcome.message == "Healed BRUTUS, LADY KATHERINE up to full."
    assert "MAGNUS" not in outcome.message


# --- memorised spells --------------------------------------------------------


# Pool of Radiance's whole list, which is 81 slots and not the 69 the layout
# declares nor the 16 it used to (#268).
MEMORISED = c64_codec.memorised_span(None)[1]


def test_storing_then_restoring_puts_the_memorised_list_back(tmp_path):
    store = actions.SpellStore(tmp_path / "spells.json")
    target = machine()
    # BRUTUS is a fighter and prepares nothing, so give him a list: ids 1
    # BLESS and 3 CURE LIGHT WOUNDS, the two the layout note names.
    target.write(0x4D20, bytes([1, 3]) + bytes(MEMORISED - 2))
    assert find("store-spells", store).apply(target, disk="PORSAVE11").ok

    prepared = bytes(target.read(0x4D20, MEMORISED))
    target.write(0x4D20, bytes(MEMORISED))       # everything cast

    outcome = find("restore-spells", store).apply(target, disk="PORSAVE11")
    assert outcome.ok and outcome.writes == ((0x4D20, prepared),)
    assert target.read(0x4D20, MEMORISED) == prepared


def test_a_list_stored_before_the_span_was_known_still_restores(tmp_path):
    """A `spells.json` written when the field was sixteen bytes holds sixteen,
    and those sixteen are the front of the same run.

    Refusing it -- which the length check did, on "not 81 bytes" -- would have
    told a player nothing could be restored for a list this program itself
    stored last week (#268). Sixteen bytes go back at the front and the rest
    of the run is left alone, which is exactly what restoring did before.
    """
    store = actions.SpellStore(tmp_path / "spells.json")
    store.put("PORSAVE11", "BRUTUS", bytes([1, 3]) + bytes(14))
    target = machine()
    outcome = find("restore-spells", store).apply(target, disk="PORSAVE11")
    assert outcome.ok
    assert outcome.writes == ((0x4D20, bytes([1, 3]) + bytes(14)),)
    assert target.read(0x4D20, 16) == bytes([1, 3]) + bytes(14)


def test_a_stored_list_wider_than_the_record_is_refused(tmp_path):
    store = actions.SpellStore(tmp_path / "spells.json")
    store.put("PORSAVE11", "BRUTUS", bytes(MEMORISED + 1))
    outcome = find("restore-spells", store).apply(machine(), disk="PORSAVE11")
    assert outcome.writes == ()
    assert any("BRUTUS" in note and str(MEMORISED) in note
               for note in outcome.notes)


def test_the_store_survives_the_window_closing(tmp_path):
    path = tmp_path / "spells.json"
    actions.SpellStore(path).put("PORSAVE11", "BRUTUS", bytes(range(16)))
    again = actions.SpellStore(path)
    assert again.get("PORSAVE11", "BRUTUS") == bytes(range(16))
    assert again.names("PORSAVE11") == ("BRUTUS",)
    assert again.stored_at("PORSAVE11", "BRUTUS")


def test_the_store_is_keyed_by_disk_as_well_as_by_name(tmp_path):
    store = actions.SpellStore(tmp_path / "spells.json")
    store.put("PORSAVE11", "BRUTUS", b"\x01" + bytes(15))
    store.put("PORSAVE13", "BRUTUS", b"\x02" + bytes(15))
    assert store.get("PORSAVE11", "BRUTUS")[0] == 1
    assert store.get("PORSAVE13", "BRUTUS")[0] == 2


def test_an_unreadable_store_is_empty_rather_than_an_error(tmp_path):
    path = tmp_path / "spells.json"
    path.write_text("{ this is not json")
    assert actions.SpellStore(path).get("PORSAVE11", "BRUTUS") is None


def test_restoring_with_nothing_stored_writes_nothing_and_says_so(tmp_path):
    store = actions.SpellStore(tmp_path / "spells.json")
    outcome = find("restore-spells", store).apply(machine(), disk="PORSAVE11")
    assert outcome.writes == ()
    assert any("BRUTUS" in note for note in outcome.notes)


def test_the_memorised_list_is_written_inside_the_slot_the_character_owns():
    """0x020 + 81 ends at 0x071, well inside the $100 a live slot holds. A
    field past that belongs to the next character and must raise rather than
    corrupt them."""
    party = actions.read_party(machine())
    member = party.by_slot(0)
    assert member.field_address("spells_memorised") == 0x4D20
    with pytest.raises(ValueError):
        member.field_address("hp_current")           # 0x119, export only


# --- items -------------------------------------------------------------------


def unidentified() -> bytes:
    """One item with all three name words hidden and readied set.

    Built from the format, not copied: `goldbox.items.build_item` is the same
    constructor the editor uses.
    """
    raw = bytearray(por_items.build_item(type_index=0x24, words=(0xA5, 0x24, 0),
                                         bonus=4, readied=True))
    raw[6] |= por_items.HIDDEN_NAME_MASK
    return bytes(raw)


def test_identifying_clears_the_hidden_bits_and_keeps_readied():
    target = machine(item=unidentified())
    outcome = find("identify").apply(target)
    assert outcome.ok and outcome.writes == ((0x5906, b"\x80"),)
    assert target.read(0x5906, 1) == b"\x80"


def test_identifying_skips_an_item_that_is_already_identified():
    plain = bytearray(unidentified())
    plain[6] &= ~por_items.HIDDEN_NAME_MASK
    outcome = find("identify").apply(machine(item=bytes(plain)))
    assert outcome.ok and outcome.writes == ()


def test_identifying_asks_first():
    """There is no in-game undo, so the action carries its own question rather
    than trusting the caller to invent one."""
    assert getattr(find("identify"), "confirm", "") == ""


# --- levelling ---------------------------------------------------------------


def with_experience(points: int) -> MemoryTarget:
    """The captured party with BRUTUS given enough to train. 0x0E8, 24-bit."""
    save0, save1 = captured()
    at = games.POOL_OF_RADIANCE.slot_area_base - 0x4900 + 0x0E8
    save0[at:at + 3] = points.to_bytes(3, "little")
    return MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(save1),
                         0x6E11: bytes([WORLD])})


def test_levelling_refuses_without_the_experience_for_it():
    """BRUTUS is a fighter 1 with no experience, so there is nothing to take."""
    outcome = find("level-up").apply(machine(), slot=0)
    assert not outcome.ok and outcome.writes == ()
    assert "2001" in outcome.message


def test_levelling_refuses_before_it_reads_a_slot_that_is_not_there():
    assert not find("level-up").apply(machine(), slot=7).ok


def test_the_blockers_are_empty_because_every_field_is_confirmed():
    """The mechanism stays -- a field demoted in goldbox/layout.py stops the
    action dead -- but nothing is standing in the way today."""
    assert actions.level_up_blockers() == ()
    assert all(isinstance(b, str) for b in actions.level_up_blockers(None))


# --- one title has been measured and five have not ---------------------------

def test_levelling_a_character_in_another_title_refuses_and_writes_nothing():
    """#16. Silver Blades is the dangerous one now: its level tables are in
    `goldbox/levels.py` (#187), so selecting them looks like enough and is
    not -- its constitution hit-point bonus, thief-skill racial adjustment and
    wisdom bonus spells are still unread or unattributed
    (`docs/121-silver-blades.md`). Every derivation not yet its own was read
    at Pool of Radiance's addresses out of Pool of Radiance's `GEN`, so a
    Silver Blades fighter would be written Pool of Radiance's THAC0, saving
    throws and hit die.

    **Curse used to be this test's example and is not any more.** Its own
    trainer is now fully measured -- `goldbox/levelup.py` reproduces it and
    `automap/actions.py`'s `LevelUp.run` calls `plan_all` for it (`#18
    (Measure Curse's trainer so Level Up works there)`), and the one remaining
    gap, `automap/window.py`'s own decision of when to open the spell dialog,
    closed on `#415 (automap/window.py picks the level-up spell dialog's
    class the same wrong way plan would have, blocking Curse's trainer)`. A
    Curse fighter genuinely levels now; see
    `tests/test_cursetrainer.py::test_curse_is_now_in_trainer_measured`."""
    from goldbox import games

    # A Silver Blades-shaped machine, so the refusal is the trainer's and not
    # an accident of reading its addresses on Pool of Radiance's memory. Since
    # #29 Silver Blades *has* a combat flag, so `Action.legality` lets this
    # through and the gate that stops it is `level_up_blockers`, which is the
    # right one.
    save0, roster = captured()
    at = games.SECRET_OF_THE_SILVER_BLADES.slot_area_base - 0x4B00 + 0x0E8
    save0[at:at + 3] = (2001).to_bytes(3, "little")
    target = MemoryTarget({
        games.SECRET_OF_THE_SILVER_BLADES.save_load_address:
            bytes(save0 + roster),
        games.SECRET_OF_THE_SILVER_BLADES.mode_flag: bytes([WORLD])})
    before = dict(target.memory)
    outcome = actions.LevelUp(games.SECRET_OF_THE_SILVER_BLADES).apply(
        target, slot=0)
    assert not outcome.ok and outcome.writes == ()
    assert target.memory == before
    said = " ".join((outcome.message,) + outcome.notes)
    assert "Secret of the Silver Blades" in said


@pytest.mark.parametrize("game", ["secret-of-the-silver-blades",
                                  "champions-of-krynn",
                                  "death-knights-of-krynn",
                                  "gateway-to-the-savage-frontier"])
def test_every_title_but_pool_of_radiance_and_curse_is_refused_by_name(game):
    """Curse's trainer is fully measured now (`#18 (Measure Curse's trainer
    so Level Up works there)`, `#415 (automap/window.py picks the level-up
    spell dialog's class the same wrong way plan would have, blocking Curse's
    trainer)`), so it joined Pool of Radiance in `TRAINER_MEASURED` -- see
    `tests/test_cursetrainer.py::test_curse_is_now_in_trainer_measured`.
    Silver Blades has level tables of its own too (#187) but not a measured
    trainer; the other three have no tables at all, so `levels.for_game`
    falls back to Pool of Radiance's. Either way `trainer_measured` refuses
    every one of them, which is exactly the silent wrong answer the blocker
    is here to stop."""
    from goldbox import games

    blockers = actions.level_up_blockers(None, games.by_key(game))
    assert blockers and games.by_key(game).title in blockers[0]
    assert actions.level_up_blockers(None, games.POOL_OF_RADIANCE) == ()
    assert actions.level_up_blockers(
        None, games.CURSE_OF_THE_AZURE_BONDS) == ()


def test_levelling_writes_what_the_trainer_writes():
    target = with_experience(2001)
    outcome = find("level-up").apply(target, slot=0)
    assert outcome.ok, outcome.message
    written = dict(outcome.writes)
    base = games.POOL_OF_RADIANCE.slot_area_base
    # fighter 2: THAC0 19 (stored 60 - 19), the per-class entry, the level
    # byte, attack_level, and experience -- which the clamp only ever lowers,
    # so 2001 stays 2001.
    assert written[base + 0x071] == bytes([41])
    assert written[base + 0x0CC] == bytes([2])
    assert written[base + 0x0A0] == bytes([2])
    assert written[base + 0x098] == bytes([2])
    assert written[base + 0x0E8] == (2001).to_bytes(3, "little")
    # a d10 and a +2 constitution bonus at level 2
    rolled = written[base + 0x0ED][0]
    assert 9 + 4 <= rolled <= 9 + 10          # a pure fighter never rolls under 4
    assert written[base + 0x076] == (rolled + 4).to_bytes(2, "little")
    # the roster's cached THAC0 follows, and current hit points are healed to
    # the *new* maximum -- the trainer heals, and healing before the maximum
    # rose would heal to the old number.
    assert 0x8300 + 0x0E in written
    assert written[0x8300 + ROSTER_HP_CURRENT] == bytes([rolled + 4])


def test_no_money_moves():
    """The trainer charges 1000 gold and turns the rest to platinum. This does
    not: that is what a school costs, not what a level costs."""
    outcome = find("level-up").apply(with_experience(2001), slot=0)
    assert outcome.ok
    slot0 = games.POOL_OF_RADIANCE.slot_area_base
    coin = range(slot0 + 0x0BB, slot0 + 0x0C9)
    assert not [a for a, _ in outcome.writes if a in coin]


def test_a_character_at_zero_is_refused_rather_than_healed():
    """Levelling ends in a heal, and zero is dead or dying -- the record does
    not say which. A corpse at full hit points is a state the game never has."""
    save0, save1 = captured()
    save1[ROSTER_HP_CURRENT] = 0
    at = games.POOL_OF_RADIANCE.slot_area_base - 0x4900 + 0x0E8
    save0[at:at + 3] = (2001).to_bytes(3, "little")
    target = MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(save1),
                           0x6E11: bytes([WORLD])})
    outcome = find("level-up").apply(target, slot=0)
    assert not outcome.ok and outcome.writes == ()
    assert "dead or dying" in outcome.message


def multi_class(points: int, **levels_) -> MemoryTarget:
    """The captured party with BRUTUS turned into a multi-class character.

    The record goes back into `SAVEDGAME0` so `read_party` reads it the way it
    would read the game's -- the action takes a target and not a record, and a
    test that shortcut that would not exercise the write.
    """
    save0, save1 = captured()
    at = games.POOL_OF_RADIANCE.slot_area_base - 0x4900
    record = CharacterRecord.from_bytes(
        bytes(save0[at:at + 0x100]).ljust(RECORD_SIZE, b"\x00"))
    bits = {"magic-user": 1, "cleric": 2, "thief": 4, "fighter": 8}
    record.set("class_bits", sum(bits[n] for n in levels_))
    for name, level in levels_.items():
        record.set(levelup.CLASS_LEVEL_FIELD[name], level)
    for name in bits:
        if name not in levels_:
            record.set(levelup.CLASS_LEVEL_FIELD[name], 0)
    record.set("level", max(levels_.values()))
    record.set("experience", points)
    save0[at:at + 0x100] = bytes(record)[:0x100]
    return MemoryTarget({0x4900: bytes(save0), 0x8300: bytes(save1),
                         0x6E11: bytes([WORLD])})


def press_level_up(target, slot: int = 0):
    """One press of the roster card's button, spell dialog and all."""
    record = actions.read_party(target).by_slot(slot).record
    class_name = actions.LevelUp.class_for(record)
    spell = None
    if class_name == "magic-user":
        offered = actions.LevelUp.offers(record)
        spell = offered[0] if offered else None
    return find("level-up").apply(target, slot=slot, spell=spell)


def test_a_multi_class_character_is_not_asked_which_class():
    """The player picks nothing. Among the ready classes the button takes the
    one whose threshold *after* the level is largest, because that is the
    number `GEN $23D4` reads -- so the clamp's ceiling stays as high as it can
    and the other class usually survives."""
    target = multi_class(5002, **{"magic-user": 1, "thief": 1})
    record = actions.read_party(target).by_slot(0).record
    assert levelup.ready_classes(record) == ["magic-user", "thief"]
    assert levelup.best_class(record) == "magic-user"


def test_the_rule_reads_the_threshold_after_the_level_and_not_the_one_held():
    """The two readings disagree, and the post-level one is right. A
    magic-user 4 / thief 5 holds 22,501 against the thief's 20,001, so
    comparing what they need now picks the magic-user; after the level it is
    40,001 against 42,501, so the clamp will read the thief's -- and with
    42,500 points thief-first reaches magic-user 6 / thief 6 where
    magic-user-first stalls at 5 / 6."""
    target = multi_class(42500, **{"magic-user": 4, "thief": 5})
    record = actions.read_party(target).by_slot(0).record
    assert levelup.best_class(record) == "thief"


def test_offers_is_empty_when_a_ready_magic_user_is_not_the_class_chosen():
    """`#415 (automap/window.py picks the level-up spell dialog's class the
    same wrong way plan would have, blocking Curse's trainer)`. The same
    magic-user 4 / thief 5 as the test above: both classes are ready, but
    `best_class` -- what `class_for` answers, and what this press actually
    trains -- picks the thief. `offers` used to answer only "does the
    magic-user have an unlearned spell at its own next level", which said
    yes here even though the magic-user is not the class this press raises,
    and gating the spell dialog on that alone would have asked LADY
    KATHERINE to pick a magic-user spell for a thief's level."""
    target = multi_class(42500, **{"magic-user": 4, "thief": 5})
    record = actions.read_party(target).by_slot(0).record
    assert levelup.best_class(record) == "thief"
    assert levelup.learnable(record, level=5), \
        "the magic-user has an unlearned spell at its own next level"
    assert actions.LevelUp.offers(record) == []


def test_a_tie_breaks_in_class_bit_order():
    """Deterministic, and the order `0x0C9` stores: magic-user, cleric, thief,
    fighter. A magic-user 1 / cleric 1 both reach 3,001 after the level."""
    target = multi_class(2501, **{"magic-user": 1, "cleric": 1})
    record = actions.read_party(target).by_slot(0).record
    assert levelup.ready_classes(record) == ["magic-user", "cleric"]
    assert levelup.best_class(record) == "magic-user"


def test_katherine_takes_three_levels_from_three_presses():
    """The measured result. LADY KATHERINE, magic-user 1 / thief 1 with 5,002
    points, ends magic-user 2 / thief 3 on 5,000 -- three levels -- because the
    magic-user goes first. Thief first would have clamped her to 2,500 and
    stranded both (`docs/135-levelling.md`)."""
    target = multi_class(5002, **{"magic-user": 1, "thief": 1})
    raised = []
    for _ in range(3):
        outcome = press_level_up(target)
        assert outcome.ok, outcome.message
        raised.append(outcome.message)
    record = actions.read_party(target).by_slot(0).record
    assert record.get("level_magic_user") == 2
    assert record.get("level_thief") == 3
    assert record.get("experience") == 5000
    assert levelup.ready_classes(record) == []          # nothing left to take
    assert [m.split(" is now a level ")[1].replace("!", "") for m in raised] == [
        "2 magic-user", "2 thief", "3 thief"]


def test_the_outcome_names_the_class_it_raised():
    """The player no longer chooses, so this line is the only place the choice
    is visible."""
    target = multi_class(5002, **{"magic-user": 1, "thief": 1})
    assert press_level_up(target).message.endswith(" is now a level 2 magic-user!")


def test_a_single_class_character_is_unaffected():
    """One class ready is one class picked, exactly as before."""
    target = with_experience(2001)
    outcome = find("level-up").apply(target, slot=0)
    assert outcome.ok and outcome.message.endswith(" is now a level 2 fighter!")
    record = actions.read_party(target).by_slot(0).record
    assert record.get("level_fighter") == 2


def test_an_explicit_class_still_wins():
    """`plan` and `run` keep taking a class name: the byte-for-byte replay of
    the measured trainings passes one, and so may any caller that wants it."""
    target = multi_class(5002, **{"magic-user": 1, "thief": 1})
    outcome = find("level-up").apply(target, slot=0, class_name="thief")
    assert outcome.ok and outcome.message.endswith(" is now a level 2 thief!")


def test_a_magic_user_is_not_levelled_without_a_spell_chosen():
    """`GEN $215A` stops on a menu and so does this: nothing picks for you."""
    target = with_experience(2501)
    record = actions.read_party(target).by_slot(0).record
    record.set("class_bits", 1)
    record.set("level_magic_user", 1)
    record.set("level_fighter", 0)
    offered = actions.LevelUp.offers(record)
    assert offered, "a level-1 magic-user has spells left to learn"
    with pytest.raises(levelup.CannotLevel, match="picks one new spell"):
        levelup.plan(record, "magic-user")
    plan = levelup.plan(record, "magic-user", learn=offered[0], rolled=3)
    assert plan.learned_spell == offered[0]


def test_the_offer_is_for_the_level_being_reached_not_the_one_held():
    """`GEN $1FDE` writes the new per-class level before the menu is built, so
    a magic-user reaching 3 is offered second-level spells at that training."""
    target = with_experience(5001)
    record = actions.read_party(target).by_slot(0).record
    record.set("class_bits", 1)
    record.set("level_magic_user", 2)
    from goldbox import spells
    offered = actions.LevelUp.offers(record)
    assert any(spells.spell_group(i)[1] == 2 for i in offered)
    assert all(spells.spell_group(i)[0] == "magic-user" for i in offered)


def test_the_ceiling_refuses():
    target = with_experience(10 ** 6)
    record = actions.read_party(target).by_slot(0).record
    record.set("level_fighter", 8)
    with pytest.raises(levelup.CannotLevel, match="stops at 8"):
        levelup.plan(record, "fighter")


def test_a_race_at_its_limit_refuses():
    """A halfling stops at fighter 6 whatever the class ceiling says."""
    target = with_experience(10 ** 6)
    record = actions.read_party(target).by_slot(0).record
    record.set("race", 5)
    record.set("level_fighter", 6)
    with pytest.raises(levelup.CannotLevel, match="stops at 6"):
        levelup.plan(record, "fighter")


# --- quickfight --------------------------------------------------------------


def test_the_flag_is_where_the_experiment_found_it():
    """Roster block +0x0C, bit 7. Selecting QUICK moved exactly this byte for
    exactly the character quickfought."""
    flag = actions.QUICKFIGHT
    assert (flag.address(0), flag.address(4), flag.mask) == (0x830C, 0x838C, 0x80)


def test_quickfight_clears_the_bit_the_combat_menu_set():
    target = machine()
    target.write(0x830C, bytes([0x80]))
    outcome = find("clear-quickfight").apply(target)
    assert outcome.writes == ((0x830C, b"\x00"),)
    assert target.read(0x830C, 1) == b"\x00"


def test_quickfight_leaves_the_rest_of_the_byte_alone():
    """Only bit 7 is the flag; the other seven bits are unread and stay."""
    target = machine()
    target.write(0x830C, bytes([0x83]))
    assert find("clear-quickfight").apply(target).writes == ((0x830C, b"\x03"),)


def test_quickfight_refuses_when_the_flag_is_not_known(monkeypatch):
    """The refusal path stays, because a retracted address must go back to
    refusing rather than to poking whatever `+0x0C` happens to be."""
    monkeypatch.setattr(actions, "QUICKFIGHT", None)
    action = actions.ClearQuickfight()
    verdict = action.legality(machine())
    assert not verdict and "has not been found" in verdict.reason
    assert not action.apply(machine()).ok


def test_quickfight_clears_the_bit_once_the_flag_is_known():
    """Driven through an explicit flag, so a corrected address is one
    `QuickfightFlag(...)` and no new code."""
    flag = actions.QuickfightFlag(base=0x8300 + 0x11, stride=0x20, mask=0x40)
    target = machine()
    target.write(flag.address(0), bytes([0x43]))
    action = actions.ClearQuickfight(flag)
    assert action.legality(target)
    outcome = action.apply(target)
    assert outcome.writes == ((flag.address(0), b"\x03"),)
    assert action.apply(target).writes == ()      # nobody left on quickfight


def test_the_watcher_fires_on_the_edge_out_of_combat_and_not_again():
    flag = actions.QuickfightFlag(base=0x8300 + 0x11, stride=0x20, mask=0x40)
    watcher = actions.QuickfightWatcher(actions.ClearQuickfight(flag),
                                        enabled=True)
    fighting = machine(COMBAT)
    fighting.write(flag.address(0), bytes([0x40]))
    assert watcher.poll(fighting) is None         # still in the fight

    after = machine(WORLD)
    after.write(flag.address(0), bytes([0x40]))
    outcome = watcher.poll(after)
    assert outcome is not None and outcome.writes
    assert watcher.poll(after) is None            # not on every later tick


def test_the_watcher_does_nothing_while_it_is_off():
    flag = actions.QuickfightFlag(base=0x8300 + 0x11, stride=0x20, mask=0x40)
    watcher = actions.QuickfightWatcher(actions.ClearQuickfight(flag))
    watcher.poll(machine(COMBAT))
    assert watcher.poll(machine(WORLD)) is None


# --- the set of them ---------------------------------------------------------


def test_every_action_carries_what_a_button_needs():
    names = set()
    for action in actions.actions():
        assert action.name and action.label and action.description
        assert action.name not in names
        names.add(action.name)
    assert names == {"heal", "identify", "store-spells", "restore-spells",
                     "clear-quickfight"}
    # Levelling is not on the bar: it is about one character, and a bar button
    # cannot say which. The roster card is where it lives.
    assert "level-up" not in names


def test_nothing_writes_a_disk():
    """The whole point of these being memory writes: a target has `read` and
    `write` and no notion of a file, so an action cannot touch a save."""
    target = machine(hp=5)
    find("heal").apply(target)
    assert set(target.memory) <= {0x4900, 0x8300, 0x6E11,
                                  0x8300 + ROSTER_HP_CURRENT}


# --- per title (#29) ---------------------------------------------------------
#
# The write side of the same fix `tests/test_automap.py` pins for the read side.
# `automap/live.py` and `automap/target.py` were threaded through the `Game`
# descriptor first; these five buttons were not, so they carried Pool of
# Radiance's `$4D00`, `$5900` and `$8300` into every title -- and they *write*,
# which is why the matrix graded them `X` where the reader was only `U`.
#
# The bytes below are still Pool of Radiance's captured party. Nothing here
# claims they are a Curse party; what is under test is which addresses an
# action reads and writes, and Curse's payload is Pool of Radiance's with the
# roster page folded on, so the shape is exactly right for that question.

CURSE = games.CURSE_OF_THE_AZURE_BONDS


def curse_machine(mode: int | None = None, hp: int | None = None
                  ) -> MemoryTarget:
    """The captured party laid out the way Curse lays a save out.

    `mode` goes to Curse's own `$7F11` and not to Pool of Radiance's `$6E11`:
    the flag is `LINKER`'s byte, and `LINKER` is a different resident in each
    title even though the dispatch it does is the same (#29).
    """
    save0, roster = captured()
    if hp is not None:
        roster[ROSTER_HP_CURRENT] = hp
    memory = {CURSE.save_load_address: bytes(save0 + roster)}
    if mode is not None:
        memory[CURSE.mode_flag] = bytes([mode])
    return MemoryTarget(memory)


def test_a_curse_party_is_read_at_curses_own_addresses():
    """`read_party` takes the descriptor, so one read at `$4B00` and a roster
    sliced out of the payload's last page -- not two reads at `$4900` and
    `$8300`."""
    target = curse_machine()
    party = actions.read_party(target, CURSE)
    assert party is not None and [m.name for m in party] == ["BRUTUS"]
    assert target.reads == [(0x4B00, 0x1D00)]


def test_every_address_a_curse_action_would_write_is_curses_own():
    """The three bases, per slot. `$4F00`, `$5B00` and `$6700` are Curse's;
    `$4D00`, `$5900` and `$8300` are Pool of Radiance's, and writing those into
    a running Curse is what #29 is about."""
    member = actions.read_party(curse_machine(), CURSE).by_slot(0)
    assert (member.record_base, member.item_base, member.roster_base) == (
        0x4F00, 0x5B00, 0x6700)
    assert member.field_address("spells_memorised") == 0x4F00 + 0x020
    pool = actions.read_party(machine(), games.POOL_OF_RADIANCE).by_slot(0)
    assert (pool.record_base, pool.item_base, pool.roster_base) == (
        0x4D00, 0x5900, 0x8300)


def test_the_quickfight_flag_follows_the_roster_page():
    """Roster `+0x0C` bit 7 in both titles: the offset is the block's and the
    block is the same block. Only where the page lives moves."""
    assert actions.quickfight_flag(CURSE).address(3) == 0x6700 + 3 * 0x20 + 0x0C
    assert actions.quickfight_flag().address(3) == 0x8300 + 3 * 0x20 + 0x0C
    assert actions.quickfight_flag(CURSE).mask == live.QUICKFIGHT_BIT


def test_a_title_with_no_measured_mode_flag_writes_nothing():
    """The gate is the one address that does not follow the save image: it is
    `LINKER`'s own byte, and `LINKER` is a separate resident in every title.
    Three have been read -- `$6E11`, `$7F11`, `$7F11` -- and the Krynn-era
    titles have not, so on those there is no way to tell a fight from the map
    and every action refuses rather than write blind.

    A wounded party is used deliberately: on Pool of Radiance's machine this
    same call heals, so what is asserted is the refusal and not an empty one.
    """
    krynn = games.CHAMPIONS_OF_KRYNN
    assert krynn.mode_flag is None
    save0, roster = captured()
    roster[ROSTER_HP_CURRENT] = 1
    for name in ("heal", "identify", "store-spells", "restore-spells",
                 "clear-quickfight"):
        action = next(a for a in actions.actions(game=krynn) if a.name == name)
        target = MemoryTarget({krynn.save_load_address: bytes(save0 + roster),
                               0x6E11: bytes([WORLD]), 0x7F11: bytes([WORLD])})
        before = dict(target.memory)
        outcome = action.apply(target)
        assert not outcome.ok, name
        assert outcome.writes == () and target.memory == before, name
        assert outcome.message == actions.UNSUPPORTED.format(
            title=krynn.title), name
    # And the same machine on the title whose flag *was* measured does heal,
    # so the refusal is about the title and not about these bytes.
    healed = find("heal").apply(machine(hp=1))
    assert healed.ok and healed.writes


def test_curses_gate_is_read_at_its_own_linker_byte_and_not_pool_of_radiances():
    """`$6E11` is Pool of Radiance's `LINKER`; Curse's is `$7F11`, read out of
    the first instruction of `LINKER` on `CURSE_A.D64` and confirmed live at
    `$2D00` (#29). A wounded Curse party heals, and the read that decided it
    went to `$7F11`.

    The control is the same machine with a `2` at `$7F11` and a `1` at
    Pool of Radiance's address: an action that is illegal in combat has to
    refuse, which it cannot do if it is reading the wrong byte.
    """
    assert CURSE.mode_flag == 0x7F11
    target = curse_machine(mode=WORLD, hp=1)
    target.memory[0x6E11] = bytes([COMBAT])       # PoR's byte says "fight"
    outcome = next(a for a in actions.actions(game=CURSE)
                   if a.name == "heal").apply(target)
    assert outcome.ok and outcome.writes
    assert (0x7F11, 1) in target.reads and not any(
        r[0] == 0x6E11 for r in target.reads)

    fighting = curse_machine(mode=COMBAT, hp=1)
    fighting.memory[0x6E11] = bytes([WORLD])      # PoR's byte says "no fight"
    verdict = next(a for a in actions.actions(game=CURSE)
                   if a.name == "identify").legality(fighting)
    # **The refusal used to name the address** and this asserted on it.
    # `#306 (The Fast Travel button's own disabled tooltip carries a memory
    # address)` took every address out of what a player reads, so the reason
    # is the situation now and the number went to the log.  What this test is
    # about is unchanged and is asserted above: Curse's own mode flag is the
    # one read, and Pool of Radiance's byte saying "no fight" does not stop
    # the refusal.
    assert not verdict
    assert verdict.reason == "Identify is refused during a fight"
    assert "$" not in verdict.reason


# --- the row under the map, and the fast-travel dropdown ---------------------
#
# Qt widgets, offscreen -- `tests/conftest.py` builds the one `QApplication`
# the whole session shares. `make_root` is the same small helper
# `tests/test_automap.py` and `tests/test_debugmode.py` each carry their own
# copy of, kept local here rather than imported so this file does not reach
# into a test module owned by another change.


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


def test_the_heal_button_is_disabled_in_combat_and_not_just_the_gate():
    """`ActionBar.refresh` applies every action's verdict the same way, so
    `HealParty.combat_legal` being False (the default `Action` sets, now that
    `HealParty` no longer overrides it) is meant to be the whole of what
    disables the button -- checked here rather than assumed."""
    from automap.actionbar import ActionBar

    bar = ActionBar(make_root())
    bar.attach(machine(COMBAT))
    assert not bar.buttons["heal"].isEnabled()
    assert "fight" in bar.buttons["heal"].toolTip()
    bar.attach(machine(WORLD))
    assert bar.buttons["heal"].isEnabled()


def test_the_fast_travel_dropdown_is_disabled_in_combat():
    """The button already refuses mid-fight; the dropdown used to stay
    enabled regardless, so a destination could still be picked while the
    button that would act on it was dead."""
    from automap.actionbar import FastTravelBar

    row = FastTravelBar(make_root())
    assert row.rows                     # every fasttravelable area, no settings
    row.attach(MemoryTarget({0x6E11: bytes([COMBAT])}))
    assert not row.combo.isEnabled()
    assert "fight" in row.combo.toolTip()
    row.attach(MemoryTarget({0x6E11: bytes([WORLD])}))
    assert row.combo.isEnabled()


# --- #207: running the exit's own handler instead of NEWECL's tail -----------
#
# `automap.actions.reenter` is `tools/exitreentry.py`'s `reenter()`, ported: it
# rebuilds `DUNGEON`'s own stack from `$03BF` and lands wherever a step would
# have, so the departing script's own dispatch runs the handler. The push
# itself was proven live across three sessions (#207); what is tested here is
# that the port pushes the same bytes in the same order, and that
# `FastTravel.run` reaches for it only where `automap.fasttravel.EXIT_ROUTES`
# names a direct exit.

from automap import fasttravel  # noqa: E402


class ReenterTarget(MemoryTarget):
    """A `MemoryTarget` with the optional `reenter(pc, sp)` capability
    `actions.reenter` looks for -- the same shape `Machine.set_pc` gives
    `jump` in `tests/test_fasttravel.py`, kept local so this file does not
    reach into a test module another change owns."""

    def __init__(self, memory=None):
        super().__init__(memory)
        self.reenters: list[tuple[int, int]] = []
        self.jumps: list[int] = []

    def reenter(self, pc: int, sp: int) -> None:
        self.reenters.append((pc, sp))

    def set_pc(self, address: int) -> None:
        self.jumps.append(address)


def test_reenter_refuses_a_title_with_no_measured_reentry_addresses():
    target = ReenterTarget({fasttravel.CURSE_OF_THE_AZURE_BONDS.saved_sp
                            or 0x03BF: bytes([0xF0])})
    assert not fasttravel.CURSE_OF_THE_AZURE_BONDS.has_exit_reentry
    assert not actions.reenter(target, fasttravel.CURSE_OF_THE_AZURE_BONDS, 1)
    assert target.reenters == []


def test_reenter_pushes_only_the_main_loop_return_for_entry_1():
    """Entry 1 (`after_step`) does its own redraw, so no chain -- the same
    single push `tools/exitreentry.py`'s `phase_square` measured."""
    addr = fasttravel.POOL_OF_RADIANCE
    target = ReenterTarget({addr.saved_sp: bytes([0xF0])})
    assert actions.reenter(target, addr, 1)
    assert target.reenters == [(addr.after_step, 0xF0 - 2)]
    assert target.read(0x0100 + 0xF0, 1) == bytes([addr.main_loop_return >> 8])
    assert target.read(0x0100 + 0xEF, 1) == bytes([addr.main_loop_return & 0xFF])


def test_reenter_chains_the_redraw_in_front_of_the_forward_key_for_entry_0():
    """Entry 0 (`forward_key`) is reached through the redraw, chained the way
    `tools/exitreentry.py`'s `phase_edge` chained it live."""
    addr = fasttravel.POOL_OF_RADIANCE
    target = ReenterTarget({addr.saved_sp: bytes([0xF0])})
    assert actions.reenter(target, addr, 0)
    assert target.reenters == [(addr.redraw, 0xF0 - 4)]
    chain_ret = addr.forward_key - 1
    assert target.read(0x0100 + 0xEE, 1) == bytes([chain_ret >> 8])
    assert target.read(0x0100 + 0xED, 1) == bytes([chain_ret & 0xFF])


def test_reenter_starts_from_the_saved_depth_not_a_guess():
    """The rebuild starts at `$03BF`'s own recorded depth -- proven live in
    `#207`'s `run5` from three different idle states."""
    addr = fasttravel.POOL_OF_RADIANCE
    target = ReenterTarget({addr.saved_sp: bytes([0x42])})
    assert actions.reenter(target, addr, 1)
    assert target.reenters == [(addr.after_step, 0x42 - 2)]


def kobold_caves_machine() -> ReenterTarget:
    """The party in the Kobold Caves (area 13), idle in `DUNGEON`'s key-wait
    loop, ready for a fast travel to area 27 -- `#207`'s own motivating case:
    `ECL0D $9A9D` is what drops Princess Fatima on the way out, and it is
    what this exit's route runs."""
    addr = fasttravel.POOL_OF_RADIANCE
    return ReenterTarget({
        games.MODE_FLAG_POOL: bytes([WORLD]),
        addr.slot: bytes([13]),
        addr.disk: bytes([3]),
        addr.indoors: bytes([1]),
        addr.live_square: bytes([5, 6, 1]),
        addr.saved_sp: bytes([0xF0]),
    })


def test_fasttravel_runs_the_kobold_caves_handler_instead_of_the_tail_jump():
    """The case `#207`'s whole ticket is about: fast-travelling out of the
    Kobold Caves used to enter `NEWECL` at its tail and skip `ECL0D $9A9D`,
    so Princess Fatima stayed in the roster. `(13, 27)` is a direct route in
    `automap.fasttravel.EXIT_ROUTES`, so `run` now stands the party on the
    exit's own square and re-enters `DUNGEON`'s dispatch instead."""
    target = kobold_caves_machine()
    addr = fasttravel.POOL_OF_RADIANCE
    route = fasttravel.EXIT_ROUTES[(13, 27)]
    outcome = actions.FastTravel().run(target, area=actions.area_by_id(27))
    assert outcome.ok, outcome.message
    # The exit square, with the party's own facing carried over -- entry 1
    # does not care which way the party faces.
    assert target.read(addr.live_square, 3) == bytes([*route.square, 1])
    assert target.reenters == [(addr.after_step, 0xF0 - 2)]
    # Nothing `NEWECL` would write is written here: that is the departing
    # script's own job now, made by its own `NEWECL` once it runs.
    assert target.read(addr.slot, 1) == bytes([13])
    assert target.read(addr.disk, 1) == bytes([3])


def test_fasttravel_restores_the_square_when_reentry_fails(monkeypatch):
    """`#493 (A Fast Travel that fails walking the party out leaves them at
    the doorway and says they have not moved)`: `_run_via_exit` writes the
    exit's own square before asking `reenter` to rebuild the stack, and
    `reenter` failing here is Wish failing to reach `DUNGEON`'s dispatch --
    nothing the game did, so nothing to reason about except the one write
    this method made. That write has to come back."""
    target = kobold_caves_machine()
    addr = fasttravel.POOL_OF_RADIANCE
    original = target.read(addr.live_square, 3)
    monkeypatch.setattr(actions, "reenter", lambda *a, **k: False)
    outcome = actions.FastTravel().run(target, area=actions.area_by_id(27))
    assert not outcome.ok
    assert target.read(addr.live_square, 3) == original


def test_fasttravel_exit_failure_message_does_not_claim_the_party_stood_still(
        monkeypatch):
    """The old wording said "the party has not moved" while the write above
    it had just moved them -- untrue the moment it was read, and the message
    itself said which two things disagreed about it. With the square
    restored, nothing here claims the party did not move; it says where it
    ended up instead."""
    target = kobold_caves_machine()
    monkeypatch.setattr(actions, "reenter", lambda *a, **k: False)
    outcome = actions.FastTravel().run(target, area=actions.area_by_id(27))
    assert not outcome.ok
    # The old sentence opened "the party has not moved", which was untrue --
    # `#493 (A Fast Travel that fails walking the party out leaves them at
    # the doorway and says they have not moved)`. The fix puts the party
    # back, so the replacement can say so; Donald worded it on 2026-09-10.
    assert "has not moved" not in outcome.message
    assert outcome.message == (
        "ERROR: Unable to Fast Travel. The party is back where it started.")


def test_fasttravel_falls_back_to_the_tail_jump_off_the_direct_exit_table():
    """A destination with no row in `EXIT_ROUTES` -- New Phlan (0) is not
    reachable by one of area 13's own scripted exits -- still enters `NEWECL`
    at its tail, today's behaviour, unchanged."""
    target = kobold_caves_machine()
    addr = fasttravel.POOL_OF_RADIANCE
    assert (13, 0) not in fasttravel.EXIT_ROUTES
    outcome = actions.FastTravel().run(target, area=actions.area_by_id(0))
    assert outcome.ok, outcome.message
    assert target.reenters == []
    assert target.jumps == [addr.tail]
    assert target.read(addr.slot, 1) == bytes([0x80])  # (0 & 0x7F) | 0x80


def test_fasttravel_falls_back_to_the_tail_jump_when_the_backend_cannot_reenter():
    """A backend that offers `set_pc` but neither `reenter` nor `_mon` -- a
    Commodore 64 Ultimate, whose REST API reads memory but not registers
    (`#375`), or a test double with no more than `jump` already needed --
    still gets a fast travel, the same way `#421`'s optional capabilities
    fall back to what every caller did before them, rather than being told a
    trip failed that was never attempted."""
    addr = fasttravel.POOL_OF_RADIANCE

    class NoReentryTarget(MemoryTarget):
        def __init__(self, memory=None):
            super().__init__(memory)
            self.jumps: list[int] = []

        def set_pc(self, address: int) -> None:
            self.jumps.append(address)

    target = NoReentryTarget({
        games.MODE_FLAG_POOL: bytes([WORLD]),
        addr.slot: bytes([13]),
        addr.disk: bytes([3]),
        addr.indoors: bytes([1]),
        addr.live_square: bytes([5, 6, 1]),
        addr.saved_sp: bytes([0xF0]),
    })
    assert not actions.can_reenter(target)
    assert (13, 27) in fasttravel.EXIT_ROUTES        # a direct route exists
    outcome = actions.FastTravel().run(target, area=actions.area_by_id(27))
    assert outcome.ok, outcome.message
    assert target.jumps == [addr.tail]
    assert target.read(addr.saved_sp, 1) == bytes([0xF0]), (
        "nothing should have been pushed to the stack page: the capability "
        "check happens before any write, not after a failed one")


def test_can_reenter_is_true_for_a_vice_backed_target():
    """The other half of the gate: a target that does offer the capability
    is not skipped past."""
    class FakeMon:
        pass

    class ViceLikeTarget(MemoryTarget):
        def __init__(self):
            super().__init__()
            self._mon = FakeMon()

    assert actions.can_reenter(ViceLikeTarget())


def test_reenter_writes_nothing_to_the_stack_page_when_set_registers_raises():
    """`#494 (reenter() can push return addresses to the stack page and still
    report failure)`: the write loop used to run before the monitor path was
    tried, so a `_mon` present with no `reenter` capability, whose
    `set_registers` raises, still left the return addresses pushed to
    `$0100`-`$01FF` under the old ordering. Compute-then-write means a
    `False` here has written nothing.

    And the monitor still has to be resumed -- the review on this ticket's
    first pass found that a version which only resumed on success left the
    emulator halted at the monitor prompt behind an "Unable to Fast Travel"
    message with no player action able to bring it back, since
    `FastTravel._run_via_exit`'s own cleanup after a `False` only resumes by
    writing to `target` again, which does not happen when the exit square
    could not be read in the first place."""
    addr = fasttravel.POOL_OF_RADIANCE

    class FailingMon:
        def __init__(self):
            self.resumed = False

        def set_registers(self, regs):
            raise RuntimeError("this build refused the register write")

        def resume(self):
            self.resumed = True

    target = MemoryTarget({addr.saved_sp: bytes([0xF0])})
    mon = FailingMon()
    target._mon = mon
    assert not actions.reenter(target, addr, 1)
    assert target.read(0x0100, 0x100) == bytes(0x100), (
        "nothing should have been pushed to the stack page: the capability "
        "check happens before any write, not after a failed one")
    assert mon.resumed, (
        "a refused register write must still resume the monitor -- "
        "otherwise the machine is left halted with nothing to bring it back")


def test_reenter_pushes_the_stack_in_a_single_write_on_the_monitor_path():
    """`#494`'s second review finding: `ViceTarget.write` resumes the
    connection on *every* call (`automap/target.py`), and by the time the
    write loop ran, `set_registers` had already pointed PC at the re-entry
    target and SP at the finished stack -- so two `target.write` calls per
    return address let the machine run `DUNGEON`'s dispatch over a stack
    only half built, between the writes. `reenter` now builds the whole
    chain as one blob and hands it to the raw monitor's own `write` in a
    single call, resuming once at the end.

    This pins that the blob is byte-for-byte what the old per-address loop
    wrote, for chains of one, two and three return addresses -- entry 1 (no
    chain), and two synthetic longer chains, since no title measured here
    chains more than one address behind the main loop's own return."""
    addr = fasttravel.POOL_OF_RADIANCE
    base_sp = 0xF0

    def old_loop_bytes(items: tuple[int, ...]) -> tuple[int, bytes]:
        """`reenter`'s own write loop before this ticket's fix, and
        `tools/exitreentry.py`'s `reenter()` today: high byte then low,
        each pushed return address two bytes shallower than the last."""
        mem: dict[int, int] = {}
        sp = base_sp
        for ret in items:
            mem[0x0100 + sp] = ret >> 8
            mem[0x0100 + sp - 1] = ret & 0xFF
            sp -= 2
        lo, hi = min(mem), max(mem)
        return lo, bytes(mem[a] for a in range(lo, hi + 1))

    for n in (1, 2, 3):
        items = tuple(addr.main_loop_return - 2 * i for i in range(n))
        sp = base_sp - 2 * len(items)
        want_start, want_bytes = old_loop_bytes(items)
        got_start, got_bytes = actions._reentry_stack_bytes(sp, items)
        assert (got_start, got_bytes) == (want_start, want_bytes), n

    class RecordingMon:
        def __init__(self):
            self.writes: list[tuple[int, bytes]] = []
            self.registers: dict[int, int] | None = None
            self.resumes = 0

        def set_registers(self, values):
            self.registers = values

        def write(self, start, data):
            self.writes.append((start, bytes(data)))

        def resume(self):
            self.resumes += 1

    target = MemoryTarget({addr.saved_sp: bytes([base_sp])})
    mon = RecordingMon()
    target._mon = mon
    items = (addr.main_loop_return, addr.forward_key - 1)
    sp = base_sp - 2 * len(items)
    want_start, want_bytes = old_loop_bytes(items)
    assert actions.reenter(target, addr, 0)
    assert mon.writes == [(want_start, want_bytes)], (
        "exactly one write, matching the old per-address loop byte for byte")
    assert mon.registers == {
        actions.sp_register(mon): sp, actions.pc_register(mon): addr.redraw}
    assert mon.resumes == 1

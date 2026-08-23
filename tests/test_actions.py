"""The live actions, driven against a dictionary of bytes.

Nothing here needs an emulator: `MemoryTarget` is a `Target`, so an action that
writes through one is exercised exactly as it would be against VICE or a
Commodore 64 Ultimate -- and the assertions are on the addresses written, which
is the part that has to be right.

The party is the same captured machine `tests/test_automap.py` uses: BRUTUS
alone in New Phlan, `SAVEDGAME0` and the roster page as the live view reads
them.
"""

from __future__ import annotations

import pathlib

import pytest

from automap import actions, live
from automap.target import MemoryTarget
from por import items as por_items
from por import levelup
from por.record import RECORD_SIZE, CharacterRecord
from por.savegame import ROSTER_HP_CURRENT

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


@pytest.mark.parametrize("name", ["identify", "store-spells", "restore-spells",
                                  "level-up"])
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


def test_healing_is_legal_in_combat():
    assert find("heal").legality(machine(COMBAT))


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


# --- healing -----------------------------------------------------------------


def test_healing_writes_the_roster_byte_and_nothing_else():
    target = machine(hp=5)
    outcome = find("heal").apply(target)
    assert outcome.ok
    assert outcome.writes == ((0x8300 + ROSTER_HP_CURRENT, b"\x0b"),)
    assert target.read(0x8300 + ROSTER_HP_CURRENT, 1) == b"\x0b"


def test_healing_a_whole_party_writes_nothing_when_nobody_is_hurt():
    outcome = find("heal").apply(machine())
    assert outcome.ok and outcome.writes == ()


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


# --- memorised spells --------------------------------------------------------


def test_storing_then_restoring_puts_the_memorised_list_back(tmp_path):
    store = actions.SpellStore(tmp_path / "spells.json")
    target = machine()
    # BRUTUS is a fighter and prepares nothing, so give him a list: ids 1
    # BLESS and 3 CURE LIGHT WOUNDS, the two the layout note names.
    target.write(0x4D20, bytes([1, 3]) + bytes(14))
    assert find("store-spells", store).apply(target, disk="PORSAVE11").ok

    prepared = bytes(target.read(0x4D20, 16))
    target.write(0x4D20, bytes(16))              # everything cast

    outcome = find("restore-spells", store).apply(target, disk="PORSAVE11")
    assert outcome.ok and outcome.writes == ((0x4D20, prepared),)
    assert target.read(0x4D20, 16) == prepared


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
    """0x020 + 16 is well inside the $100 a live slot holds. A field past that
    belongs to the next character and must raise rather than corrupt them."""
    party = actions.read_party(machine())
    member = party.by_slot(0)
    assert member.field_address("spells_memorised") == 0x4D20
    with pytest.raises(ValueError):
        member.field_address("hp_current")           # 0x119, export only


# --- items -------------------------------------------------------------------


def unidentified() -> bytes:
    """One item with all three name words hidden and readied set.

    Built from the format, not copied: `por.items.build_item` is the same
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
    assert find("identify").confirm


# --- levelling ---------------------------------------------------------------


def with_experience(points: int) -> MemoryTarget:
    """The captured party with BRUTUS given enough to train. 0x0E8, 24-bit."""
    save0, save1 = captured()
    at = actions.SLOT_AREA_BASE - 0x4900 + 0x0E8
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
    """The mechanism stays -- a field demoted in por/layout.py stops the
    action dead -- but nothing is standing in the way today."""
    assert actions.level_up_blockers() == ()
    assert all(isinstance(b, str) for b in actions.level_up_blockers(None))


# --- one title has been measured and five have not ---------------------------

def test_levelling_a_character_in_another_title_refuses_and_writes_nothing():
    """#16. Curse is the dangerous one: its level tables are in
    `por/levels.py`, so selecting them looks like enough and is not. Every
    derivation around them was read at Pool of Radiance's addresses out of Pool
    of Radiance's `GEN`, so a Curse fighter would be written Pool of Radiance's
    THAC0, saving throws, hit die and thresholds."""
    from por import games

    target = with_experience(2001)
    before = dict(target.memory)
    outcome = actions.LevelUp(games.CURSE_OF_THE_AZURE_BONDS).apply(target,
                                                                    slot=0)
    assert not outcome.ok and outcome.writes == ()
    assert target.memory == before
    assert "Curse of the Azure Bonds" in " ".join(outcome.notes)
    assert "measured" in " ".join(outcome.notes)


@pytest.mark.parametrize("game", ["curse-of-the-azure-bonds",
                                  "secret-of-the-silver-blades",
                                  "champions-of-krynn",
                                  "death-knights-of-krynn",
                                  "gateway-to-the-savage-frontier"])
def test_every_title_but_pool_of_radiance_is_refused_by_name(game):
    """The other four have no tables at all, so `levels.for_game` falls back to
    Pool of Radiance's -- which is exactly the silent wrong answer the blocker
    is here to stop."""
    from por import games

    blockers = actions.level_up_blockers(None, games.by_key(game))
    assert blockers and games.by_key(game).title in blockers[0]
    assert actions.level_up_blockers(None, games.POOL_OF_RADIANCE) == ()


def test_levelling_writes_what_the_trainer_writes():
    target = with_experience(2001)
    outcome = find("level-up").apply(target, slot=0)
    assert outcome.ok, outcome.message
    written = dict(outcome.writes)
    base = actions.SLOT_AREA_BASE
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
    coin = range(actions.SLOT_AREA_BASE + 0x0BB, actions.SLOT_AREA_BASE + 0x0C9)
    assert not [a for a, _ in outcome.writes if a in coin]


def test_a_character_at_zero_is_refused_rather_than_healed():
    """Levelling ends in a heal, and zero is dead or dying -- the record does
    not say which. A corpse at full hit points is a state the game never has."""
    save0, save1 = captured()
    save1[ROSTER_HP_CURRENT] = 0
    at = actions.SLOT_AREA_BASE - 0x4900 + 0x0E8
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
    at = actions.SLOT_AREA_BASE - 0x4900
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
    assert [m.split(" is a ")[1] for m in raised] == [
        "magic-user 2", "thief 2", "thief 3"]


def test_the_outcome_names_the_class_it_raised():
    """The player no longer chooses, so this line is the only place the choice
    is visible."""
    target = multi_class(5002, **{"magic-user": 1, "thief": 1})
    assert press_level_up(target).message.endswith(" is a magic-user 2")


def test_a_single_class_character_is_unaffected():
    """One class ready is one class picked, exactly as before."""
    target = with_experience(2001)
    outcome = find("level-up").apply(target, slot=0)
    assert outcome.ok and outcome.message.endswith(" is a fighter 2")
    record = actions.read_party(target).by_slot(0).record
    assert record.get("level_fighter") == 2


def test_an_explicit_class_still_wins():
    """`plan` and `run` keep taking a class name: the byte-for-byte replay of
    the measured trainings passes one, and so may any caller that wants it."""
    target = multi_class(5002, **{"magic-user": 1, "thief": 1})
    outcome = find("level-up").apply(target, slot=0, class_name="thief")
    assert outcome.ok and outcome.message.endswith(" is a thief 2")


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
    from por import spells
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

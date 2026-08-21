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


def test_levelling_refuses_and_names_every_field_in_the_way():
    outcome = find("level-up").apply(machine(), slot=0)
    assert not outcome.ok and outcome.writes == ()
    blockers = " ".join(outcome.notes)
    for field in ("hp_max", "save_paralysis", "spells_castable", "thief"):
        assert field in blockers


def test_levelling_refuses_before_it_reads_a_slot_that_is_not_there():
    assert not find("level-up").apply(machine(), slot=7).ok


def test_the_blockers_are_data_so_promoting_a_field_is_what_unblocks_them():
    assert actions.level_up_blockers()
    assert all(isinstance(b, str) for b in actions.level_up_blockers())


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
                     "clear-quickfight", "level-up"}


def test_nothing_writes_a_disk():
    """The whole point of these being memory writes: a target has `read` and
    `write` and no notion of a file, so an action cannot touch a save."""
    target = machine(hp=5)
    find("heal").apply(target)
    assert set(target.memory) <= {0x4900, 0x8300, 0x6E11,
                                  0x8300 + ROSTER_HP_CURRENT}

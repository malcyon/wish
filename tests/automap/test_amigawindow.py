"""The automapper window hands an attached Amiga to the Amiga Action buttons.

Everything runs through the real `AutomapBinding` over a target whose Amiga
memory is made up: records carry an invented name and hit points at the real
rows' own offsets, so the real `amigaparty` and `amigaactions` do the reading.
Whether those offsets are the game's is a measurement on a running Amiga; these
tests check what the window does with the answers.
"""

import os
from types import SimpleNamespace

import pytest
from gamedata import synthetic_geo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap import actions as engine
from automap import amiga, amigaactions, amigalevelup, amigaparty, c64, live
from automap.area import NOT_OURS, RESIDENT_GEO
from automap.state import Automapper
from automap.target import MemoryTarget
from goldbox import c64_port
from goldbox.geo import Geo

POOL = "pool-of-radiance"
CURSE = "curse-of-the-azure-bonds"
SILVER = "secret-of-the-silver-blades"
POOLS_OF_DARKNESS = "pools-of-darkness"
TITLES = {
    POOL: "Pool of Radiance",
    CURSE: "Curse of the Azure Bonds",
    SILVER: "Secret of the Silver Blades",
    POOLS_OF_DARKNESS: "Pools of Darkness",
}

SLOW = 0xC00000
BASE = 0xC10000           # the title's data hunk
HEAP = 0xC20000
PEOPLE = [(b"ALDRIC", 12, 20), (b"BRYNNA", 7, 7), (b"COSIMO", 0, 9)]
MEASURED = frozenset({"hp_max", "combat_value"})


def sentence(key):
    return f"ERROR: Action unsupported on {TITLES[key]} (Amiga)."


class FakeAmiga(MemoryTarget):
    """The C64 memory the map reads, plus Amiga slow memory for the party."""

    c64_memory = False

    def __init__(self, memory, key, can_write=True):
        super().__init__(memory)
        self.layout = amiga.MACHINES[key]
        self.data_base = BASE
        self.can_write = can_write
        self.ram = bytearray(0x80000)
        self.writes = []
        self.fail_at = set()
        #: Every read of Amiga memory, `(address, length)`, in order.
        self.ram_reads = []

    def read(self, addr, length):
        if addr in self.fail_at:
            raise amiga.NotConnected("the emulator did not answer")
        if SLOW <= addr and addr + length <= SLOW + len(self.ram):
            self.ram_reads.append((addr, length))
            return bytes(self.ram[addr - SLOW:addr - SLOW + length])
        return super().read(addr, length)

    def read_blocks(self, blocks):
        return [self.read(addr, length) for addr, length in blocks]

    def write(self, addr, data, verify=True):
        self.writes.append((addr, bytes(data)))
        self.ram[addr - SLOW:addr - SLOW + len(data)] = data

    def put(self, addr, data):
        self.ram[addr - SLOW:addr - SLOW + len(data)] = data


def lay_party(target, key, people=PEOPLE, mode=0):
    """Records at HEAP, 0x400 apart, linked in order; returns their addresses."""
    row = amigaparty.ROWS[key]
    addrs = [HEAP + 0x400 * i for i in range(len(people))]
    for i, (address, (name, hp, hp_max)) in enumerate(zip(addrs, people)):
        raw = bytearray(row.record_size)
        raw[row.name:row.name + len(name)] = name
        raw[row.hp.offset] = hp
        raw[row.hp_max.offset] = hp_max
        raw[row.slot] = i
        following = addrs[i + 1] if i + 1 < len(addrs) else 0
        raw[row.next_offset:row.next_offset + 4] = following.to_bytes(4, "big")
        target.put(address, bytes(raw))
    target.put(BASE + row.head, (addrs[0] if addrs else 0).to_bytes(4, "big"))
    target.put(BASE + row.mode, bytes([mode]))
    return addrs


def c64_memory():
    geo = Geo(synthetic_geo())
    return {0xD011: bytes([0x1B]), 0xD018: bytes([0x15]), 0xDD00: bytes([0x17]),
            c64.DEFAULT.live_position: bytes((4, 5, 0)),
            RESIDENT_GEO: geo.to_bytes()}


_app = None


def window_on(target):
    global _app
    from PyQt6.QtWidgets import QApplication, QMainWindow
    # Held: a `QApplication` with no Python reference can be collected.
    _app = QApplication.instance() or QApplication([])

    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return AutomapBinding(root, Automapper(target, {"GEO00": Geo(synthetic_geo())}))


@pytest.fixture(autouse=True)
def notes_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


@pytest.fixture
def measured(monkeypatch):
    """Rows that list `hp_max` and the fight value as measured, as Heal needs."""
    for key, row in list(amigaparty.ROWS.items()):
        monkeypatch.setitem(amigaparty.ROWS, key, SimpleNamespace(
            **{**vars(row), "measured": MEASURED}))


def attached(key, *, can_write=True, mode=0, people=PEOPLE):
    target = FakeAmiga(c64_memory(), key, can_write)
    lay_party(target, key, people, mode)
    window = window_on(target)
    window._refresh_roster()
    return window, target


def button(window, name):
    return window.actions_bar.buttons[name]


def states(window):
    return {name: (b.isEnabled(), b.toolTip())
            for name, b in window.actions_bar.buttons.items()}


def enabled(window):
    return {name for name, (on, _) in states(window).items() if on}


def card_names(window):
    return [c.name.text() for c in window.roster.cards
            if c.frame.isVisibleTo(window.root)]


# -- the gate ------------------------------------------------------------------

def test_a_confirmed_action_is_enabled_when_every_condition_holds(measured):
    window, _ = attached(POOL)
    assert enabled(window) == {"heal", "store-spells", "restore-spells", "identify"}
    for action in window.actions_bar.actions:
        if action.name in enabled(window):
            assert button(window, action.name).toolTip() == action.description


def test_each_failing_condition_greys_the_button_with_its_reason(measured):
    # Every case starts from the enabled one above and breaks one thing.
    healed = ("heal", "restore-spells")

    window, _ = attached(POOL, can_write=False)
    assert enabled(window) == {"store-spells"}              # Save spells only reads
    for name in healed:
        assert states(window)[name] == (False, sentence(POOL))

    window, _ = attached(POOL, mode=amigaparty.ROWS[POOL].combat_value)
    assert enabled(window) == set()
    assert states(window)["heal"] == (False, "Heal party is not available during a fight")

    window, target = attached(POOL)
    target.fail_at.add(BASE + amigaparty.ROWS[POOL].mode)
    window._refresh_roster()
    assert enabled(window) == set()
    assert states(window)["heal"] == (False, "the machine is not readable right now")

    # An action the title's row does not confirm.
    window, _ = attached(POOL)
    assert states(window)["clear-quickfight"] == (False, sentence(POOL))


def test_an_action_marked_combat_legal_stays_enabled_in_a_fight(measured, monkeypatch):
    row = amigaparty.ROWS[POOL]
    monkeypatch.setitem(amigaparty.ROWS, POOL, SimpleNamespace(
        **{**vars(row), "combat_legal": frozenset({"heal"})}))
    window, _ = attached(POOL, mode=row.combat_value)
    assert enabled(window) == {"heal"}


def test_the_gate_follows_the_game_from_one_poll_to_the_next(measured):
    window, target = attached(POOL)
    assert "heal" in enabled(window)
    target.put(BASE + amigaparty.ROWS[POOL].mode,
               bytes([amigaparty.ROWS[POOL].combat_value]))
    window._refresh_roster()
    assert enabled(window) == set()
    target.put(BASE + amigaparty.ROWS[POOL].mode, bytes([0]))
    window._refresh_roster()
    assert "heal" in enabled(window)
    target.can_write = False
    window._refresh_roster()
    assert enabled(window) == {"store-spells"}


def test_with_the_rows_as_committed_heal_needs_a_measured_maximum():
    """Heal needs `hp_max` measured (only Pools of Darkness has it), and
    Curse's fight value is from the code alone, so Curse has none."""
    expected = {
        POOL: {"store-spells", "restore-spells", "identify"},
        CURSE: set(),
        SILVER: {"store-spells", "restore-spells", "identify"},
        POOLS_OF_DARKNESS: {"heal", "store-spells", "restore-spells", "identify"},
    }
    for key, want in expected.items():
        window, _ = attached(key)
        assert enabled(window) == want, key
        for name, (on, tip) in states(window).items():
            assert on or tip == sentence(key), (key, name)


def test_curse_needs_its_fight_value_measured_even_with_hp_max(monkeypatch):
    row = amigaparty.ROWS[CURSE]
    monkeypatch.setitem(amigaparty.ROWS, CURSE, SimpleNamespace(
        **{**vars(row), "measured": frozenset({"hp_max"})}))
    window, _ = attached(CURSE)
    assert enabled(window) == set()
    monkeypatch.setitem(amigaparty.ROWS, CURSE, SimpleNamespace(
        **{**vars(row), "measured": MEASURED}))
    window._refresh_roster()
    assert enabled(window) == {"heal", "store-spells", "restore-spells", "identify"}


def test_a_click_writes_to_the_amiga_party_and_says_so(measured):
    window, target = attached(POOL)
    row = amigaparty.ROWS[POOL]
    button(window, "heal").click()
    assert (HEAP + row.hp.offset, b"\x14") in target.writes        # ALDRIC 12 -> 20
    assert [a for a, _ in target.writes] == [HEAP + row.hp.offset]  # BRYNNA full, COSIMO down
    assert window.actions_bar.last.ok
    assert "Healed ALDRIC" in window.actions_bar.last.message


def test_disabled_buttons_write_nothing_when_forced(measured):
    window, target = attached(POOL, can_write=False)
    out = window.actions_bar.run(window.actions_bar.actions[0])
    assert not out.ok and out.message == sentence(POOL)
    assert target.writes == []


def test_a_machine_that_is_not_running_this_title_gets_no_actions(measured):
    window, target = attached(POOL)
    assert enabled(window)
    window.mapper.title_check = NOT_OURS
    window._refresh_roster()
    assert enabled(window) == set()
    assert all(tip == sentence(POOL) for _, tip in states(window).values())
    assert window.actions_bar.target is None
    window.mapper.title_check = "unknown"
    window._refresh_roster()
    assert enabled(window)
    assert target.writes == []


# -- the cards -----------------------------------------------------------------

def test_the_cards_show_the_amiga_party(measured, monkeypatch):
    monkeypatch.setattr(live, "read_blocks", lambda *a, **k: pytest.fail(
        "the C64's roster was read off a 68000"))
    window, _ = attached(CURSE)
    assert card_names(window) == ["ALDRIC", "BRYNNA", "COSIMO"]
    first = window.roster.cards[0]
    assert first.hp.fraction == pytest.approx(12 / 20)
    assert first.hp.text == "12 / 20 hp"
    assert window.roster.cards[2].hp.fraction == 0.0
    assert window.roster.heading.text() == "Party"


@pytest.mark.parametrize("key", [POOL, CURSE, SILVER, POOLS_OF_DARKNESS])
def test_a_card_shows_the_class_level_and_armour_class_in_the_c64_form(
        measured, key):
    levels, _f, _l, exp, ac, thac0 = {
        POOL: (0x098, 0, 0, 0x0AE, 0x113, 0x112),
        CURSE: (0x10A, 0, 0, 0x128, 0x19F, 0x19E),
        SILVER: (0x0AC, 0, 0, 0x0C8, 0x148, 0x147),
        POOLS_OF_DARKNESS: (0x09D, 0, 0, 0x044, 0x187, 0x186)}[key]
    window, target = attached(key)
    target.put(HEAP + levels + 2, bytes([7]))       # fighter
    target.put(HEAP + levels + 6, bytes([8]))       # thief
    target.put(HEAP + ac, bytes([53]))
    target.put(HEAP + thac0, bytes([47]))
    target.put(HEAP + exp, (10000).to_bytes(4, "big"))
    window._refresh_roster()
    card = window.roster.cards[0]
    assert card.klass.text() == "F/T  L7/L8"
    assert "AC 7   THAC0 13" in card.frame.toolTip()
    who = window.snapshot.characters[0]
    assert who.experience == 10000


def test_the_cards_follow_the_party_and_hold_it_while_the_list_is_unreadable(measured):
    window, target = attached(POOL)
    target.put(HEAP + amigaparty.ROWS[POOL].hp.offset, bytes([5]))
    window._refresh_roster()
    assert window.roster.cards[0].hp.fraction == pytest.approx(5 / 20)

    target.put(BASE + amigaparty.ROWS[POOL].head, bytes(4))      # mid-load
    window._refresh_roster()
    assert window.roster.heading.text() == "Party - not readable right now"
    assert card_names(window) == ["ALDRIC", "BRYNNA", "COSIMO"]
    lay_party(target, POOL)
    window._refresh_roster()
    assert window.roster.heading.text() == "Party"


def test_the_live_tick_draws_the_cards_without_a_call_to_refresh(measured):
    target = FakeAmiga(c64_memory(), POOL)
    lay_party(target, POOL)
    window = window_on(target)
    for _ in range(24):
        window.tick()
    assert card_names(window) == ["ALDRIC", "BRYNNA", "COSIMO"]
    assert "heal" in enabled(window)


def test_a_quickfight_flag_shows_on_the_card(measured):
    window, target = attached(POOL)
    row = amigaparty.ROWS[POOL]
    target.put(HEAP + 0x400 + row.quickfight.offset, bytes([1]))
    window._refresh_roster()
    assert window.roster.cards[1].quickfight.toolTip() == "Quickfight"
    assert window.roster.cards[0].quickfight.toolTip() == ""


# -- Level up stays greyed ---------------------------------------------------

def ready_character():
    classes = tuple(live.ClassProgress(name, 8, 100_000, 0.5, 90_000)
                    for name in ("magic-user", "cleric", "thief"))
    return live.Character(slot=0, name="LADY KATHERINE", classes=classes,
                          level=8, armour_class=-3, thac0=5, hp=41, hp_max=99,
                          experience=100_000)


@pytest.mark.parametrize("key", sorted(TITLES))
def test_level_up_stays_hidden_and_blocked_on_the_amiga(measured, monkeypatch, key):
    window, target = attached(key)
    assert not window.roster.levelling
    card = window.roster.cards[0]
    widget = card.level_up
    assert not widget.isEnabled() and widget.toolTip() == sentence(key)
    # Even a card that would offer it (a C64 record's) cannot show it here.
    card.show_character(ready_character())
    assert not widget.isVisibleTo(window.root) and not widget.isEnabled()
    asked = []
    window.roster.level_up_requested.connect(asked.append)
    widget.click()
    assert asked == []
    monkeypatch.setattr(engine, "read_party", lambda *a, **k: pytest.fail(
        "C64 addresses were read off an Amiga"))
    window._level_up(0)
    assert target.writes == []


# -- switching machines ----------------------------------------------------------

def test_switching_to_a_c64_and_back_clears_and_restores(measured):
    window, amiga_target = attached(POOL)
    window.actions_bar.watcher.enabled = True
    assert all(isinstance(a, amigaactions._AmigaAction)
               for a in window.actions_bar.actions)
    assert isinstance(window.actions_bar.watcher, amigaactions.AmigaQuickfightWatcher)
    assert card_names(window)

    c64_target = MemoryTarget(c64_memory())
    window.mapper.target = c64_target
    window._refresh_roster()
    assert not any(isinstance(a, amigaactions._AmigaAction)
                   for a in window.actions_bar.actions)
    assert type(window.actions_bar.watcher) is engine.QuickfightWatcher
    assert window.actions_bar.watcher.enabled
    assert window.actions_bar.unsupported is None
    assert window.fasttravel_bar.unsupported is None
    assert not window.roster.unsupported and window.roster.levelling
    assert "Amiga" not in " ".join(tip for _, tip in states(window).values())
    assert not any(n in ("ALDRIC", "BRYNNA", "COSIMO") for n in card_names(window))
    assert window.actions_bar.target is c64_target

    window.mapper.target = amiga_target
    window._refresh_roster()
    assert all(isinstance(a, amigaactions._AmigaAction)
               for a in window.actions_bar.actions)
    assert window.actions_bar.watcher.enabled
    assert card_names(window) == ["ALDRIC", "BRYNNA", "COSIMO"]
    assert not window.roster.levelling and window.roster.unsupported


def test_switching_between_two_amiga_titles_drops_the_first_party(measured):
    window, _ = attached(POOL)
    assert card_names(window) == ["ALDRIC", "BRYNNA", "COSIMO"]
    other = FakeAmiga(c64_memory(), CURSE)           # nothing loaded in Curse yet
    window.mapper.target = other
    window._refresh_roster()
    assert card_names(window) == []
    assert window.roster.heading.text() == "Party - not readable right now"
    lay_party(other, CURSE, [(b"EDRIC", 9, 9)])
    window._refresh_roster()
    assert card_names(window) == ["EDRIC"]
    assert enabled(window) == {"heal", "store-spells", "restore-spells", "identify"}
    assert all(a.key == CURSE for a in window.actions_bar.actions)


def test_a_title_change_on_an_amiga_never_installs_c64_actions(measured):
    window, _ = attached(POOLS_OF_DARKNESS)
    before = window.actions_bar.actions
    window.state.title = "Pool of Radiance"
    window._apply_title()                 # a C64 descriptor for the title
    assert window.actions_bar.game is c64_port.DEFAULT
    window.actions_bar.set_game(None)
    assert window.actions_bar.actions == before
    assert isinstance(window.actions_bar.watcher, amigaactions.AmigaQuickfightWatcher)
    assert not window.roster.levelling


def test_a_c64_window_is_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(live, "read_blocks",
                        lambda *a, **k: calls.append(a) or (b"", b""))
    target = MemoryTarget(c64_memory())
    window = window_on(target)
    for _ in range(24):
        window.tick()
    assert calls
    assert window.actions_bar.target is target
    assert type(window.actions_bar.actions[0]) is engine.HealParty
    assert window._amiga_key is None
    assert card_names(window) == []


def test_a_refresh_reads_the_mode_byte_once_however_many_actions_ask(measured):
    window, target = attached(POOL)
    mode_at = BASE + amigaparty.ROWS[POOL].mode
    target.ram_reads.clear()
    window.actions_bar.refresh(target)
    assert [r for r in target.ram_reads if r[0] == mode_at] == [(mode_at, 1)]
    # The control: several of Pool's actions are confirmed and reach the mode.
    assert len(window.actions_bar.actions) == 5
    assert len(amigaparty.ROWS[POOL].confirmed) > 1


# -- Level up on a title whose row confirms it ------------------------------------

POD_NAME, POD_SLOT, POD_NEXT = 0x60, 0xBD, 0x00
POD_LEVELS, POD_EXPERIENCE = 0x9D, 0x44


def pod_xp(name, level):
    from goldbox import levels
    return levels.POOLS_OF_DARKNESS.at_level(name, level).experience


def fighter(level):
    rec = bytearray(amigaparty.ROWS[POOLS_OF_DARKNESS].record_size)
    rec[0x58], rec[0x79] = 5, 18
    rec[POD_LEVELS + 2] = level
    rec[POD_EXPERIENCE:POD_EXPERIENCE + 4] = pod_xp("fighter", level + 1).to_bytes(4, "big")
    rec[0x81], rec[0x191] = 80, 50
    return rec


def magic_user():
    rec = bytearray(amigaparty.ROWS[POOLS_OF_DARKNESS].record_size)
    rec[0x58], rec[0x73], rec[0x79] = 0, 18, 14
    rec[POD_LEVELS + 5] = 1
    rec[POD_EXPERIENCE:POD_EXPERIENCE + 4] = pod_xp("magic-user", 2).to_bytes(4, "big")
    rec[0x81] = rec[0x191] = 6
    return rec


def with_characters(window, target, records):
    """Put each template over the party member at its index, keeping the name,
    party slot and next pointer the list needs."""
    for i, template in enumerate(records):
        at = HEAP + 0x400 * i
        old = bytes(target.ram[at - SLOW:at - SLOW + len(template)])
        new = bytearray(template)
        new[POD_NAME:POD_NAME + 16] = old[POD_NAME:POD_NAME + 16]
        new[POD_SLOT] = old[POD_SLOT]
        new[POD_NEXT:POD_NEXT + 4] = old[POD_NEXT:POD_NEXT + 4]
        target.put(at, bytes(new))
    window._refresh_roster()


def pod_window(records, **kwargs):
    window, target = attached(POOLS_OF_DARKNESS, people=PEOPLE[:len(records)],
                              **kwargs)
    with_characters(window, target, records)
    return window, target


def level_up_shown(window, index):
    button = window.roster.cards[index].level_up
    return not button.isHidden() and button.isEnabled()


def spoken(window, monkeypatch):
    lines = []
    monkeypatch.setattr(window.messages, "say",
                        lambda text, detail="", alarm=False, **k:
                        lines.append((text, alarm)))
    return lines


def test_level_up_is_offered_to_the_member_the_trainer_would_train():
    window, _ = pod_window([fighter(8), fighter(9)[:0x80] + bytes(0x114)])
    assert level_up_shown(window, 0)
    assert not level_up_shown(window, 1)        # the second has no experience
    assert window.roster.cards[0].level_up.toolTip() == "level up as fighter"


@pytest.mark.parametrize("key, offered", [
    (POOL, False), (CURSE, False), (SILVER, True), (POOLS_OF_DARKNESS, True)])
def test_only_a_title_whose_row_confirms_level_up_trains_anyone(
        monkeypatch, key, offered):
    monkeypatch.setattr(amigalevelup, "ready_classes",
                        lambda raw, key: ("fighter",))
    window, _ = attached(key)
    party = amigaparty.read_party(window.mapper.target)
    expected = {m.address for m in party} if offered else set()
    assert window._amiga_trainable(party) == expected


def test_nothing_is_trained_in_a_fight_or_on_a_read_only_machine(monkeypatch):
    monkeypatch.setattr(amigalevelup, "ready_classes",
                        lambda raw, key: ("fighter",))
    row = amigaparty.ROWS[POOLS_OF_DARKNESS]
    window, target = attached(POOLS_OF_DARKNESS, mode=row.combat_value)
    assert window._amiga_trainable(amigaparty.read_party(target)) == set()
    window, target = attached(POOLS_OF_DARKNESS, can_write=False)
    assert window._amiga_trainable(amigaparty.read_party(target)) == set()


def test_pressing_level_up_plans_and_writes_the_member(monkeypatch):
    window, target = pod_window([fighter(8), fighter(8)])
    lines = spoken(window, monkeypatch)
    seen = []
    real_plan, real_write = amigalevelup.plan_member, amigalevelup.write_plan
    monkeypatch.setattr(amigalevelup, "plan_member", lambda m, key, **k: (
        seen.append(("plan", m.name, key)) or real_plan(m, key, **k)))
    monkeypatch.setattr(amigalevelup, "write_plan", lambda t, m, p: (
        seen.append(("write", m.name, t)) or real_write(t, m, p)))
    window.roster.cards[1].level_up.click()
    assert seen == [("plan", "BRYNNA", POOLS_OF_DARKNESS),
                    ("write", "BRYNNA", target)]
    assert target.ram[HEAP + 0x400 + POD_LEVELS + 2 - SLOW] == 9
    assert target.ram[HEAP + POD_LEVELS + 2 - SLOW] == 8        # ALDRIC untouched
    assert all(HEAP + 0x400 <= addr < HEAP + 0x800 for addr, _ in target.writes)
    assert lines == [("level up: BRYNNA is now a level 9 fighter!", False)]


def test_a_trainer_that_will_not_train_writes_nothing(monkeypatch):
    window, target = pod_window([fighter(8)])
    lines = spoken(window, monkeypatch)

    def stop(*_a, **_k):
        raise amigalevelup.CannotLevel("the record changed after it was read")

    monkeypatch.setattr(amigalevelup, "write_plan", stop)
    window._level_up(0)
    assert target.writes == []
    assert lines == [("level up: ALDRIC cannot level: the record changed after "
                      "it was read", True)]


def test_the_real_planner_stops_before_a_write_when_the_record_changed(monkeypatch):
    window, target = pod_window([fighter(8)])
    real = amigalevelup.plan_member

    def plan_then_change(member, key, **k):
        plan = real(member, key, **k)
        target.put(member.address + 0x81, bytes([1]))   # the game moved on
        return plan

    monkeypatch.setattr(amigalevelup, "plan_member", plan_then_change)
    lines = spoken(window, monkeypatch)
    window._level_up(0)
    assert target.writes == [] and lines[0][1] is True


def test_a_magic_user_is_asked_for_the_spell_and_it_is_learned(monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    window, target = pod_window([magic_user()])
    monkeypatch.setattr(window, "_names_for_spells", lambda: {})
    asked = []

    def pick(parent, title, label, items, current, editable):
        asked.append((label, list(items)))
        return "spell 10", True

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(pick))
    window._level_up(0)
    assert asked[0][0] == "ALDRIC learns one new spell:"
    assert asked[0][1] == [f"spell {i}" for i in range(9, 22)]
    book = target.ram[HEAP + 0x159 - SLOW:HEAP + 0x159 - SLOW + 2]
    assert book[(10 - 1) // 8] & 1 << (10 - 1) % 8
    assert target.ram[HEAP + POD_LEVELS + 5 - SLOW] == 2


def test_closing_the_spell_dialog_writes_nothing(monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    window, target = pod_window([magic_user()])
    monkeypatch.setattr(window, "_names_for_spells", lambda: {})
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("", False)))
    window._level_up(0)
    assert target.writes == []


@pytest.mark.parametrize("how", ["fight", "read-only", "other-title"])
def test_a_press_that_the_gate_would_not_offer_writes_nothing(how):
    window, target = pod_window([fighter(8)])
    if how == "fight":
        target.put(BASE + amigaparty.ROWS[POOLS_OF_DARKNESS].mode,
                   bytes([amigaparty.ROWS[POOLS_OF_DARKNESS].combat_value]))
    elif how == "read-only":
        target.can_write = False
    else:
        window.mapper.title_check = NOT_OURS
    window._level_up(0)
    assert target.writes == []


# -- review follow-ups -------------------------------------------------------------

def test_a_pools_of_darkness_dialog_never_shows_a_pool_of_radiance_name(monkeypatch):
    from PyQt6.QtWidgets import QInputDialog

    from goldbox import spells
    window, target = pod_window([magic_user()])
    called = []
    monkeypatch.setattr(spells, "load_spell_names",
                        lambda *a, **k: called.append(a) or {9: "Burning Hands"})
    monkeypatch.setattr("automap.paths.find_disks", lambda *a, **k: called.append(a)
                        or "/nowhere")
    shown = []
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(
        lambda parent, title, label, items, *a: shown.extend(items) or ("", False)))
    window._level_up(0)
    assert shown == [f"spell {i}" for i in range(9, 22)]
    assert called == []


def test_silver_blades_keeps_its_c64_spell_names(monkeypatch):
    from goldbox import spells
    window, _ = attached(SILVER)
    monkeypatch.setattr("automap.live._disk_images", lambda root, game: ["x.d64"])
    monkeypatch.setattr("automap.paths.find_disks", lambda game=None: "root")
    monkeypatch.setattr(spells, "load_spell_names", lambda path, game=None: {9: game.key})
    assert window._names_for_spells() == {9: "secret-of-the-silver-blades"}


def test_a_failure_between_writes_is_logged_and_nothing_escapes(monkeypatch, caplog):
    window, target = pod_window([fighter(8)])
    lines = spoken(window, monkeypatch)

    def half(t, member, plan):
        t.write(member.address, b"\x00")
        raise amiga.GuestError("the emulator stopped answering")

    monkeypatch.setattr(amigalevelup, "write_plan", half)
    with caplog.at_level("ERROR", logger="wish.automap.window"):
        window._level_up(0)
    assert "stopped part-way" in caplog.text and "GuestError" in caplog.text
    assert lines == []                      # no player line claims a result


def test_an_error_after_the_writes_is_logged_and_nothing_escapes(monkeypatch, caplog):
    window, target = pod_window([fighter(8)])
    monkeypatch.setattr(amigalevelup, "summary",
                        lambda *a: (_ for _ in ()).throw(KeyError("odd")))
    with caplog.at_level("ERROR", logger="wish.automap.window"):
        window._level_up(0)
    assert "level up for slot 0 failed" in caplog.text
    assert target.writes                    # the writes were made


def test_the_gate_is_checked_again_after_the_spell_dialog(monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    window, target = pod_window([magic_user()])
    monkeypatch.setattr(window, "_names_for_spells", lambda: {})

    def pick(*_a):
        target.put(BASE + amigaparty.ROWS[POOLS_OF_DARKNESS].mode,
                   bytes([amigaparty.ROWS[POOLS_OF_DARKNESS].combat_value]))
        return "spell 10", True

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(pick))
    window._level_up(0)
    assert target.writes == []


def test_can_write_is_read_through_a_wrapped_target():
    window, target = pod_window([fighter(8)])
    window.mapper.target = SimpleNamespace(target=target)
    assert window._amiga_row() is not None
    target.can_write = False
    assert window._amiga_row() is None

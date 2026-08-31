from __future__ import annotations

"""The combat log, against screens we construct.

No game data here and none needed: the message panel is text on a screen, so a
synthetic screen exercises every rule. What it cannot exercise is the timing --
see the numbered list at the end of `docs/110-combat-log.md`.
"""


import pytest

from automap import combatlog, rolls
from automap.combatlog import CombatLog, message, parse
from automap.screen import SCREEN_COLS, band
from automap.target import MemoryTarget

SCREEN = 0xCC00
LEFT, RIGHT, TOP, BOTTOM = combatlog.COMBAT_WINDOW


def codes(text: str) -> bytes:
    """ASCII to screen codes: the inverse of `screen._SCREEN_TO_ASCII`."""
    out = bytearray()
    for ch in text.upper():
        out.append(ord(ch) - 64 if "A" <= ch <= "Z" else ord(ch))
    return bytes(out)


def painted(rows, top: int = combatlog.MESSAGE_TOP) -> bytes:
    """Rows 10-22 of a screen, with `rows` in the message window's columns."""
    height = BOTTOM - combatlog.MESSAGE_TOP
    grid = [bytearray(b" " * SCREEN_COLS) for _ in range(height)]
    for i, line in enumerate(rows):
        at = top - combatlog.MESSAGE_TOP + i
        if 0 <= at < height:
            grid[at][LEFT:LEFT + len(line)] = codes(line)
    return b"".join(bytes(r) for r in grid)


def machine(rows=(), top: int = combatlog.MESSAGE_TOP, mode: int = 2,
            d011: int = 0x1B) -> MemoryTarget:
    return MemoryTarget({
        0xD011: bytes([d011]),
        0xD018: b"\x34",                       # screen page 3 of the bank...
        0xDD00: b"\x00",                       # ...and bank 3, so $CC00
        combatlog.MODE: bytes([mode]),
        combatlog.WINDOW: bytes([LEFT, RIGHT, top, BOTTOM]),
        combatlog.CURSOR: bytes([LEFT, top]),
        SCREEN + combatlog.MESSAGE_TOP * SCREEN_COLS: painted(rows, top),
    })


def show(target: MemoryTarget, rows, top: int = combatlog.MESSAGE_TOP) -> None:
    """Repaint the message window, as the game would between two polls."""
    target.memory[combatlog.WINDOW] = bytes([LEFT, RIGHT, top, BOTTOM])
    target.memory[SCREEN + combatlog.MESSAGE_TOP * SCREEN_COLS] = painted(
        rows, top)


# --- reading the region -----------------------------------------------------

def test_a_band_is_sliced_out_of_whole_rows():
    """A window is not contiguous in memory, so it is read as whole rows."""
    block = codes("X" * SCREEN_COLS) + codes("Y" * SCREEN_COLS)
    assert band(block, 2, 5) == ["XXX", "YYY"]


def test_the_window_bytes_are_validated_before_they_are_trusted():
    """`$03F2`-`$03F5` are ordinary RAM and hold whatever the last overlay
    left there."""
    assert combatlog.plausible_window(bytes([23, 39, 10, 23])) == (
        23, 39, 10, 23)
    assert combatlog.plausible_window(bytes([39, 23, 10, 23])) is None
    assert combatlog.plausible_window(bytes([0, 0, 0, 0])) is None
    assert combatlog.plausible_window(b"\x17\x27") is None


def test_the_message_region_is_read_at_the_screens_current_address():
    log = CombatLog()
    target = machine(["MAGNUS", "ATTACKS"])
    assert log.poll(target) == []                  # first poll finds the screen
    target.reads.clear()
    log.poll(target)
    wanted = SCREEN + combatlog.MESSAGE_TOP * SCREEN_COLS
    assert any(addr == wanted for addr, _ in target.reads)


def test_a_moved_screen_costs_one_frame_and_no_bad_data():
    """The address is read in the same burst as the region, so a frame read at
    a stale address is thrown away rather than logged."""
    log = CombatLog()
    target = machine(["MAGNUS", "ATTACKS"])
    log.poll(target)
    target.memory[0xD018] = b"\x14"                # screen page 1: $C400
    assert log.poll(target) == []
    assert log._address == 0xC400


def test_a_bitmap_screen_is_skipped():
    log = CombatLog()
    target = machine(["MAGNUS"])
    log.poll(target)
    target.memory[0xD011] = bytes([0x1B | 0x20])
    assert log.poll(target) == []
    assert log._pending == ()


def test_no_fight_means_nothing_is_kept():
    """The mode byte rides in the same burst as the region rather than gating
    it, because a second burst is a second `resume` and the cost of a read is
    the round trip. Reading the screen out of combat is harmless -- it is the
    screen -- and what matters is that none of it is logged. The window does
    not call this outside a fight anyway."""
    log = CombatLog()
    target = machine(["MAGNUS"], mode=1)
    log.poll(target)
    assert log.poll(target) == []
    assert log._pending == () and log.messages == []


# --- the dedup rule ---------------------------------------------------------

def test_the_same_frame_twice_is_one_message():
    log = CombatLog()
    log.observe(["MAGNUS", "MISSES."], top=10)
    assert log.observe(["MAGNUS", "MISSES."], top=10) == []
    assert log.messages == []


def test_two_identical_messages_in_a_row_both_appear():
    """The whole design. The clear between them is a frame that no longer
    extends the last one, so the second is a new block and not a repeat."""
    log = CombatLog()
    log.observe(["MAGNUS", "MISSES."], top=10)
    log.observe([], top=10)                         # the game clears the panel
    log.observe(["MAGNUS", "MISSES."], top=10)
    log.observe([], top=10)
    assert [m.text for m in log.messages] == ["MAGNUS MISSES.", "MAGNUS MISSES."]


def test_a_missed_clear_is_caught_by_the_top_row_going_back_up():
    """`$2983` sets `$03F4` back to 10 for a fresh block. That is the second
    edge, and it is what saves a message when the blank frame falls between
    two polls."""
    log = CombatLog()
    log.observe(["ORC", "ATTACKS"], top=10)
    log.observe(["ORC", "ATTACKS", "AND MISSES..."], top=12)
    log.observe(["ORC", "ATTACKS"], top=10)         # no blank frame seen
    log.flush()
    assert [m.text for m in log.messages] == [
        "ORC ATTACKS", "AND MISSES...", "ORC ATTACKS"]


def test_a_block_that_grows_is_one_message_not_four():
    """A block is built a row at a time, and `$2F29` prints the number onto a
    row that is already there."""
    log = CombatLog()
    for frame in (["MAGNUS"],
                  ["MAGNUS", "ATTACKS"],
                  ["MAGNUS", "ATTACKS", "AND HITS FOR"],
                  ["MAGNUS", "ATTACKS", "AND HITS FOR 5"],
                  ["MAGNUS", "ATTACKS", "AND HITS FOR 5", "POINTS OF DAMAGE"]):
        assert log.observe(frame, top=10) == []
    log.observe([], top=10)
    assert [m.text for m in log.messages] == [
        "MAGNUS ATTACKS AND HITS FOR 5 POINTS OF DAMAGE"]


def test_a_scrolled_window_gains_a_line_rather_than_repeating_one():
    """`$2D28` calls `$2CA5` when a block runs past the bottom row."""
    log = CombatLog()
    height = BOTTOM - combatlog.MESSAGE_TOP
    full = [f"LINE {i}" for i in range(height)]
    log.observe(full, top=10)
    log.observe(full[1:] + ["LINE LAST"], top=10)
    log.flush()
    assert log.messages[0].lines == tuple(full + ["LINE LAST"])


def test_a_replaced_block_commits_the_one_before_it():
    log = CombatLog()
    log.observe(["MAGNUS", "ATTACKS"], top=10)
    done = log.observe(["ORC", "IS KILLED"], top=10)
    assert [m.text for m in done] == ["MAGNUS ATTACKS"]


# --- splitting a block into its speakers ------------------------------------

def test_a_follow_up_under_the_last_message_is_its_own_message():
    """`$29BA` moves `$03F4` to the row below the cursor, so one frame holds
    two speakers. Every value `$03F4` took is where a name was printed."""
    log = CombatLog()
    log.observe(["MAGNUS", "ATTACKS", "AND HITS FOR 5"], top=10)
    log.observe(["MAGNUS", "ATTACKS", "AND HITS FOR 5", "ORC", "IS KILLED"],
                top=13)
    log.flush()
    assert [m.text for m in log.messages] == [
        "MAGNUS ATTACKS AND HITS FOR 5", "ORC IS KILLED"]


def test_with_no_split_seen_the_block_stays_whole():
    """The honest answer when `$03F4` was never sampled: raw lines, in order."""
    log = CombatLog()
    log.observe(["ORC", "IS KILLED"])
    log.flush()
    assert [m.text for m in log.messages] == ["ORC IS KILLED"]


# --- keeping the log --------------------------------------------------------

def test_the_last_message_of_a_fight_survives_the_fight():
    """COMBAT returns to LINKER with the last message still on screen, so
    nothing ever paints over it."""
    log = CombatLog()
    log.observe(["ORC", "IS KILLED"], top=10)
    assert [m.text for m in log.flush()] == ["ORC IS KILLED"]
    assert [m.text for m in log.messages] == ["ORC IS KILLED"]


def test_leaving_combat_flushes_through_the_poll():
    log = CombatLog()
    target = machine(["ORC", "IS KILLED"])
    log.poll(target)
    log.poll(target)
    target.memory[combatlog.MODE] = b"\x01"        # DUNGEON: the fight ended
    assert [m.text for m in log.poll(target)] == ["ORC IS KILLED"]


def test_the_log_is_capped():
    log = CombatLog(limit=3)
    for i in range(6):
        log.observe([f"NAME {i}"], top=10)
        log.observe([], top=10)
    assert [m.text for m in log.messages] == ["NAME 3", "NAME 4", "NAME 5"]


# --- rounds -----------------------------------------------------------------

def test_a_round_is_counted_when_initiative_comes_back():
    """`$A380` reaching all-zero ends a round."""
    log = CombatLog()
    log.note_round([3, 2, 1])
    assert log.round == 1
    log.note_round([1, 0, 0])
    assert log.round == 1
    log.note_round([0, 0, 0])
    log.note_round([4, 4, 4])
    assert log.round == 2


def test_a_message_carries_the_round_it_was_said_in():
    log = CombatLog()
    log.note_round([1, 1])
    log.observe(["ORC", "IS KILLED"], top=10)
    assert log.flush()[0].round == 1


# --- parsing, and refusing to ----------------------------------------------

@pytest.mark.parametrize("text,subject,outcome,damage", [
    ("MAGNUS ATTACKS AND HITS FOR 5 POINTS OF DAMAGE", "MAGNUS", "attack", 5),
    ("MAGNUS ATTACKS AND MISSES...", "MAGNUS", "attack", None),
    ("ORC IS HIT FOR 12 POINTS OF DAMAGE", "ORC", "hit", 12),
    ("ORC IS KILLED", "ORC", "killed", None),
    ("ORC GOES DOWN", "ORC", "down", None),
])
def test_the_games_own_phrases_parse(text, subject, outcome, damage):
    assert parse(text) == (subject, outcome, damage)


def test_a_line_that_will_not_parse_is_kept_verbatim():
    """Never invent structure. A raw line is still far better than nothing."""
    msg = message(["SOMETHING", "UNEXPECTED"])
    assert msg.text == "SOMETHING UNEXPECTED"
    assert (msg.subject, msg.outcome, msg.damage) == (None, None, None)


def test_a_row_that_filled_the_window_was_cut_mid_word():
    """`$2D28` wraps on the character, not on the word."""
    assert message(["ABCDEFGHIJKLMNOP", "QRS"], width=16).text == (
        "ABCDEFGHIJKLMNOPQRS")
    assert message(["ABCDEFGHIJKLMNO", "QRS"], width=16).text == (
        "ABCDEFGHIJKLMNO QRS")


# --- end to end, through a target ------------------------------------------

def test_a_fight_read_frame_by_frame_gives_the_lines_in_order():
    log = CombatLog()
    target = machine()
    log.poll(target)                                # finds the screen
    for frame, top in ((["MAGNUS"], 10),
                       (["MAGNUS", "ATTACKS"], 10),
                       (["MAGNUS", "ATTACKS", "AND MISSES..."], 10),
                       ([], 10),
                       (["MAGNUS"], 10),
                       (["MAGNUS", "ATTACKS"], 10),
                       (["MAGNUS", "ATTACKS", "AND MISSES..."], 10),
                       ([], 10),
                       (["ORC"], 10),
                       (["ORC", "IS KILLED"], 10)):
        show(target, frame, top)
        log.poll(target)
    target.memory[combatlog.MODE] = b"\x01"
    log.poll(target)
    assert [m.text for m in log.messages] == [
        "MAGNUS ATTACKS AND MISSES...",
        "MAGNUS ATTACKS AND MISSES...",
        "ORC IS KILLED"]


# --- the panel --------------------------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def arena_with_screen(rows) -> MemoryTarget:
    from gamedata import synthetic_arena
    memory = dict(synthetic_arena())
    memory.update(machine(rows).memory)
    return MemoryTarget(memory)


def test_the_messages_panel_keeps_both_identical_lines(app, tmp_path,
                                                       monkeypatch):
    """`MessagesPanel.say` drops a line identical to the one before it, which
    is right for the connection's own chatter and wrong for a fight."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from PyQt6.QtWidgets import QMainWindow

    from automap.state import Automapper
    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)

    target = arena_with_screen([])
    window = AutomapBinding(root, Automapper(target, {}), drive=False)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.battle is not None

    for frame in (["MAGNUS", "MISSES."], [], ["MAGNUS", "MISSES."], []):
        show(target, frame)
        window.tick()
    target.memory[combatlog.MODE] = b"\x01"
    window.tick()

    said = [line for line in window.messages.lines() if "MISSES" in line]
    assert len(said) == 2


def test_the_log_survives_the_end_of_the_fight(app, tmp_path, monkeypatch):
    """The entire point: the player wants to read it once the fight is over."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from PyQt6.QtWidgets import QMainWindow

    from automap.state import Automapper
    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)

    target = arena_with_screen([])
    window = AutomapBinding(root, Automapper(target, {}), drive=False)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    show(target, ["ORC", "IS KILLED"])
    window.tick()
    window.tick()
    target.memory[combatlog.MODE] = b"\x01"
    window.tick()
    for _ in range(window.LIVE_EVERY * 2):
        window.tick()

    assert window.battle is None
    assert any("ORC IS KILLED" in line for line in window.messages.lines())


# --- what a live fight showed -----------------------------------------------
#
# One slums fight, 1428 frames captured at ~0.18 s (`docs/50-experiments.md`,
# "The combat log's two defects, found in a slums fight"). Both of these are
# frames from that capture, not constructed cases.

def test_the_command_bar_window_is_not_the_message_window():
    """`$03F2`-`$03F5` held `00 28 18 19` on 29 of 1428 frames.

    Believing it slices whole rows 10-24 -- the combat map in the game's own
    glyphs, the border and the command bar -- into the log.
    """
    assert combatlog.message_window(bytes([0, 40, 24, 25])) == (
        LEFT, RIGHT, None, BOTTOM)
    assert combatlog.message_window(bytes([LEFT, RIGHT, 10, BOTTOM])) == (
        LEFT, RIGHT, 10, BOTTOM)
    # `$0970`'s own top: the whole text window, not a message top.
    assert combatlog.message_window(bytes([LEFT, RIGHT, 1, BOTTOM])) == (
        LEFT, RIGHT, None, BOTTOM)
    # Rows 23 and 24 are never part of a message.
    assert combatlog.message_window(bytes([LEFT, RIGHT, 10, 25]))[3] == BOTTOM


def test_a_command_bar_frame_logs_nothing():
    log = CombatLog()
    target = machine(["SILAS", "ATTACKS"])
    log.poll(target)                     # first poll only locates the screen
    log.poll(target)
    target.memory[combatlog.WINDOW] = bytes([0, 40, 24, 25])
    assert log.poll(target) == []
    assert "&" not in "".join(m.text for m in log.messages)


def test_a_block_that_loses_its_follow_up_is_not_a_new_block():
    """`$29B7` clears the follow-up first, leaving the rows it grew from.

    Every killing blow in the captured fight was logged twice without this.
    """
    log = CombatLog()
    hit = ["MAGNUS", "ATTACKS", "ORC", "AND HITS FOR 10", "POINTS OF DAMAGE"]
    log.observe(hit, top=10)
    log.observe(hit + ["ORC", "GOES DOWN", "AND IS DYING"], top=15)
    assert log.observe(hit, top=15) == []          # the follow-up is cleared
    done = log.observe([], top=15)                 # ...and then the rest
    assert [m.text for m in done] == [
        "MAGNUS ATTACKS ORC AND HITS FOR 10 POINTS OF DAMAGE",
        "ORC GOES DOWN AND IS DYING",
    ]


# --- the dice, beside what the game printed (#139) ---------------------------
#
# `docs/147-combat-rolls.md`. Everything here is constructed: the point is to
# make the attacker's block and the target's block disagree, so a test can tell
# which one was read.

def fighter(thac0: int, ac: int, dice: int, die: int, bonus: int = 0) -> bytes:
    """One 32-byte battle-roster block, as `$8300 + index * 32`."""
    from goldbox.encoding import COMBAT_BIAS
    from goldbox.savegame import (
        ROSTER_ARMOUR_CLASS,
        ROSTER_DAMAGE_BONUS,
        ROSTER_DAMAGE_DICE,
        ROSTER_DAMAGE_DIE,
        ROSTER_STRIDE,
        ROSTER_THAC0,
    )
    block = bytearray(ROSTER_STRIDE)
    block[ROSTER_THAC0] = COMBAT_BIAS - thac0
    block[ROSTER_ARMOUR_CLASS] = COMBAT_BIAS - ac
    block[ROSTER_DAMAGE_DICE] = dice
    block[ROSTER_DAMAGE_DIE] = die
    block[ROSTER_DAMAGE_BONUS] = bonus
    return bytes(block)


#: BRUTUS with a long sword, and the orc of `docs/147`. THAC0 18 against AC 6
#: needs 12; THAC0 19 against AC 2 needs 17. Both can do 7 damage, so a test
#: that reads the wrong block gets a plausible wrong answer rather than none.
BRUTUS = fighter(thac0=18, ac=2, dice=1, die=8, bonus=5)
ORC = fighter(thac0=19, ac=6, dice=2, die=6)


def roster(**blocks: bytes) -> bytes:
    """The whole `$8300`-`$8AFF` table, with the named indices filled."""
    from goldbox.savegame import ROSTER_STRIDE
    out = bytearray(rolls.ROSTER_LEN)
    for index, block in ((int(k[1:]), v) for k, v in blocks.items()):
        out[index * ROSTER_STRIDE:(index + 1) * ROSTER_STRIDE] = block
    return bytes(out)


def attack(actor: int = 0, target: int = 8, hit: bool = True, damage: int = 7,
           attempts: int = 1, landings: int = 1) -> bytes:
    """`$A4F0`-`$A4FB`, as they stand while an attack is on screen."""
    state = bytearray(rolls.ATTACK_LEN)
    state[rolls.ACTOR] = actor
    state[rolls.TARGET] = target
    state[rolls.DAMAGE] = damage
    state[rolls.ATTEMPTS] = attempts
    state[rolls.LANDINGS] = landings
    state[rolls.HIT] = 1 if hit else 0
    return bytes(state)


NAMES = {0: "BRUTUS", 8: "ORC"}
BOTH = roster(x0=BRUTUS, x8=ORC)


def dice_machine(rows=(), raw: int = 19, state: bytes | None = None,
                 table: bytes = BOTH) -> MemoryTarget:
    target = machine(rows)
    target.memory[rolls.D20] = bytes([raw])
    target.memory[rolls.ATTACK] = state if state is not None else attack()
    target.memory[rolls.ROSTER] = table
    return target


def logged(target: MemoryTarget, rows) -> list:
    """Poll a block onto the screen and then paint it over, which commits it."""
    log = CombatLog()
    log.poll(target)                     # the first poll only finds the screen
    show(target, rows)
    log.poll(target)
    show(target, [])
    return log.poll(target)


def line(rows, **kw) -> str | None:
    done = logged(dice_machine(**kw), rows)
    assert len(done) == 1, [m.text for m in done]
    return rolls.roll_line(done[0], NAMES)


HIT = ["BRUTUS", "ATTACKS ORC AND", "HITS FOR 7", "POINTS OF DAMAGE"]
MISS = ["ORC", "ATTACKS BRUTUS", "AND MISSES"]


def test_a_hit_shows_the_roll_the_number_needed_and_the_dice():
    assert line(HIT) == "BRUTUS rolled 19, needed 12, 1d8+5 = 7"


def test_a_miss_shows_the_roll_and_the_number_needed():
    """No damage clause: there was none, and the game printed none."""
    assert line(MISS, raw=4,
                state=attack(actor=8, target=0, hit=False, damage=0)) == \
        "ORC rolled 4, needed 17"


def test_a_natural_20_is_stored_as_100_and_shown_as_20():
    """`$2B10` held 100 for MALCYON's natural 20 in the driven fight."""
    assert line(HIT, raw=rolls.NATURAL_20) == \
        "BRUTUS rolled 20, needed 12, 1d8+5 = 7"


def test_a_natural_1_is_named_and_never_numbered():
    """`$127F CMP #$01 / BEQ $12AF` returns before the store at `$1289`, so
    `$2B10` still holds the previous attack's roll -- 19 here, which would
    have hit. The miss and the number contradict each other, and that is the
    only tell there is."""
    said = line(["BRUTUS", "ATTACKS ORC AND", "MISSES"], raw=19,
                state=attack(hit=False, damage=0))
    assert said == "BRUTUS rolled a natural 1"
    assert "19" not in said


def test_the_dice_come_from_the_attacker_and_not_the_target():
    """`$0CFE` makes the *target* resident, so the resident block's attack
    table and THAC0 are the wrong creature's. Both blocks here could have
    produced 7 damage and both give a plausible number needed -- 12 read the
    right way round, 17 read the wrong way -- so the line says which was
    read."""
    assert line(HIT) == "BRUTUS rolled 19, needed 12, 1d8+5 = 7"
    assert line(MISS, raw=4,
                state=attack(actor=8, target=0, hit=False, damage=0)) == \
        "ORC rolled 4, needed 17"


def test_a_roll_that_names_somebody_else_is_not_shown():
    """The rolls are read in the same poll as the message and are not
    inherently tied to it. A line that confidently names the wrong attacker is
    worse than no line."""
    assert line(HIT, state=attack(actor=8, target=0)) is None


def test_a_roll_whose_damage_disagrees_with_the_message_is_not_shown():
    assert line(HIT, state=attack(damage=3)) is None


def test_a_roll_is_not_shown_against_a_message_that_is_not_an_attack():
    assert line(["ORC", "IS KILLED"]) is None
    assert line(["ORC", "IS HIT FOR 7", "POINTS OF DAMAGE"]) is None


def test_the_hit_flag_must_agree_with_the_message():
    assert line(HIT, state=attack(hit=False)) is None


def test_only_the_first_message_of_a_block_carries_a_roll():
    """`$29BA` puts "ORC GOES DOWN" under the attack that killed it. The
    follow-up is not an attack and has no dice of its own."""
    log = CombatLog()
    log.observe(HIT, top=10, roll=rolls.read(b"\x13", attack(), BOTH))
    log.observe(HIT + ["ORC", "GOES DOWN"], top=14)
    done = log.observe([], top=14)
    assert [m.roll is not None for m in done] == [True, False]


def test_the_dice_clause_is_left_off_when_the_damage_cannot_have_come_off_them():
    """1d8+5 rolls 6 to 13 and nothing else. A damage outside that says the
    block and the damage do not belong together."""
    roll = rolls.read(b"\x13", attack(damage=20), BOTH)
    assert roll.dice is None
    assert roll.needed == 12


def test_rolls_that_resolved_between_two_polls_are_counted():
    """`$A4F9` counts attempts within an action, cleared at `COMBAT $11AC`, so
    a jump of more than one is exactly the rolls polling never saw."""
    watch = rolls.RollWatch()
    for attempts in (1, 2, 4):
        watch.update(rolls.read(b"\x13", attack(attempts=attempts), BOTH))
    assert watch.take() == 1               # attempt 3 was never seen
    watch.update(rolls.read(b"\x13", attack(attempts=3), BOTH))
    assert watch.take() == 2               # a fresh action already at three


def test_the_roll_is_the_one_read_when_the_block_first_appeared():
    """A block is painted over one row at a time and committed later, and
    `$2B10` can have moved on to the next attack by either point."""
    target = dice_machine()
    log = CombatLog()
    log.poll(target)
    show(target, HIT[:2])                          # the block, part printed
    log.poll(target)
    target.memory[rolls.D20] = bytes([3])          # the next attack, already in
    show(target, HIT)                              # ...the rest of the same one
    log.poll(target)
    show(target, [])
    done = log.poll(target)
    assert rolls.roll_line(done[0], NAMES) == \
        "BRUTUS rolled 19, needed 12, 1d8+5 = 7"


def test_two_identical_roll_lines_are_both_kept(app, tmp_path, monkeypatch):
    """The whole path, through the window: two identical misses, two roll
    lines.

    `log_combat` passes `dedup=False` for the roll line as well as for the
    message, because `MessagesPanel.say` drops a line identical to the one
    before it and two identical rolls in a row are two rolls. That flag cannot
    be made to fail on its own -- a roll line is always preceded by its own
    message line, so two of them are never adjacent -- so it is a guard rather
    than something this test proves. What the test proves is that the line
    reaches the panel at all, once per message.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from PyQt6.QtWidgets import QMainWindow

    from automap.state import Automapper
    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)

    memory = dict(arena_with_screen([]).memory)
    memory[rolls.D20] = b"\x04"
    memory[rolls.ATTACK] = attack(actor=8, target=0, hit=False, damage=0)
    target = MemoryTarget(memory)
    window = AutomapBinding(root, Automapper(target, {}), drive=False)
    for _ in range(window.LIVE_EVERY):
        window.tick()
    assert window.battle is not None
    name = next(c.name for c in window.battle.combatants if c.index == 8)

    for frame in ([name, "ATTACKS AND", "MISSES"], [],
                  [name, "ATTACKS AND", "MISSES"], []):
        show(target, frame)
        window.tick()
    target.memory[combatlog.MODE] = b"\x01"
    window.tick()

    assert len([line for line in window.messages.lines()
                if "rolled 4," in line]) == 2

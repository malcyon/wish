from __future__ import annotations

"""The combat log, against screens we construct.

No game data here and none needed: the message panel is text on a screen, so a
synthetic screen exercises every rule. What it cannot exercise is the timing --
see the numbered list at the end of `docs/110-combat-log.md`.
"""


import pytest

from automap import combatlog
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
    from automap.state import Automapper
    from automap.window import AutomapBinding
    from PyQt6.QtWidgets import QMainWindow
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
    from automap.state import Automapper
    from automap.window import AutomapBinding
    from PyQt6.QtWidgets import QMainWindow
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

#!/usr/bin/env python3
"""A driven Pool of Radiance session: boot, copy protection, disk swapping.

The thing that makes any of this possible is the **disk swap**, and it is not
obvious.  `Alt+N`, `F10` and mouse clicks never reach VICE's GTK layer, so the
fliplist is unusable to automation -- but VICE's *text* monitor has an `attach`
command, and both monitor servers can run at once.  Three rules, each learned
by wedging the emulator:

1. The text monitor does **not** break in on connect: no banner, no prompt.  It
   answers only while the machine is already stopped, which is what connecting
   the binary monitor does.  So open binary, then talk text.
2. VICE serves **one** text-monitor connection per run.  Close it and every
   monitor -- binary included -- goes deaf and the emulator freezes.  So the
   socket is opened once and held for the whole session, which is why this is
   one long-lived process with a command port rather than a series of scripts.
3. Never send `x` on the text socket.  Resuming is the binary monitor's job.

Only images under `work/drive/` are ever attached.  The player's own disks are
never in the drive.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import NamedTuple

sys.path.insert(0, "/home/donald/src/wish/tools")
import instance  # noqa: E402
from drive import Keyboard, Monitor, MonitorError, is_bitmap, read_screen  # noqa: E402

TOOLS = "/home/donald/src/wish/tools"
# Disk images and logs live in scratch; the code does not.
HERE = "/home/donald/src/wish/work/drive"
# The human's numbers, and the defaults when no slot is passed.  The pool never
# allocates these: `tools/instance.py` starts at 6520, so anything still on 6502
# is a game a human started from the desktop menu.
MON_PORT = 6502
TEXT_PORT = 6510
CMD_PORT = 6600
DISPLAY = ":7"
MONFLAGS = (
    f"-binarymonitor -binarymonitoraddress 127.0.0.1:{MON_PORT} "
    f"-remotemonitor -remotemonitoraddress 127.0.0.1:{TEXT_PORT}"
)

# The game asks for a disk in three different wordings, on two different rows.
RE_GAME_SIDE = re.compile(r"INSERT\s+(?:YOUR\s+)?(?:SIDE|GAME\s+DISK)\s*#?\s*(\d)")
SAVE_PROMPT = "SAVE GAME DISK"
# The in-game status line: facing, clock, x,y -- `E 16:48 5,2`
RE_STATUS = re.compile(r"([NESW]) +(\d+):(\d+) +(\d+),(\d+)")
FACING = {"N": 0, "E": 1, "S": 2, "W": 3}

# -- combat -----------------------------------------------------------------
# LINKER's dispatch byte, and the two values a driver cares about: `1` DUNGEON,
# `2` COMBAT.  `automap/combat.py` and `docs/101-combat-view.md` are where it
# came from; before this it was a hand-rolled `peek` in three scratch scripts.
MODE = 0x6E11
DUNGEON = 1
COMBAT = 2

BAR_COMMAND = "command"    # MOVE VIEW AIM USE [CAST] QUICK DONE
BAR_MOVE = "move"          # MOVE/ATTACK, MOVE LEFT = 9
BAR_CONTINUE = "continue"  # CONTINUE BATTLE : YES NO
BAR_YESNO = "yesno"        # any other YES NO bar
BAR_EXIT = "exit"          # the treasure and end-of-fight bars
BAR_DONE = "done"          # GUARD DELAY QUIT SPEED EXIT -- what DONE opens
BAR_PRESS = "press"        # PRESS <RETURN> OR BUTTON TO CONTINUE
BAR_MESSAGE = "message"    # GUARDING, YOUR TEAMMATE IS DYING -- and a bar
                           # caught half-redrawn, which reads as `MOVE/AT`
BAR_BLANK = "blank"        # a monster's turn: row 24 is empty
BAR_NONE = "none"          # no readable screen at all

# `MOVE LEFT = 9` is the move sub-bar's own count of remaining squares, and it
# is the one thing that tells that bar apart from the command bar, which also
# begins with MOVE.
RE_MOVE_LEFT = re.compile(r"MOVE\s*LEFT\s*=\s*(\d+)")

# What a fight prints when it is over.  `THE PARTY HAS WON !` was read off two
# fights (`work/p118-step3/runF.log`, `runH.log`); the losing wording has never
# been seen here, so `DEFEATED` is a guess and `fight()` reports `ended` rather
# than `lost` when it does not match.
WON_TEXT = "THE PARTY HAS WON"
LOST_TEXT = "DEFEATED"

# Lines worth keeping out of a fight: they are the evidence that a turn did
# something.  A driver that only records the command bar cannot tell an attack
# from a character standing still.
#
# **The panel is on the screen too, and it lies to a loose pattern.**  Two
# false positives were caught this way and both reported a blow struck in a
# fight where nobody had swung, which is the one thing `acted` exists to tell
# apart:
#
# * `HIT POINTS 4`, on the acting character's panel on every screen of every
#   fight -- so the word is `HITS`, never `HIT` (`work/p126/quick.log`);
# * `THAC0 17  DAMAGE 1D3`, on the VIEW panel -- so it is `POINTS OF DAMAGE`,
#   never `DAMAGE` on its own (`work/p126/run1.log`).
RE_NOTABLE = re.compile(
    r"\b(HITS|MISSES|SLAIN|KILLED|IS DEAD|DYING|UNCONSCIOUS|HAS WON"
    r"|DEFEATED|EXPERIENCE|GUARDING)\b|POINTS OF DAMAGE")

# Of those, the ones only a blow can produce.
RE_STRUCK = re.compile(r"\b(HITS|MISSES|SLAIN)\b|POINTS OF DAMAGE")

WON, LOST, ENDED, BUDGET, NOT_FIGHTING = (
    "won", "lost", "ended", "budget", "not fighting")


class CombatBar(NamedTuple):
    """Row 24 during a fight, classified."""

    kind: str
    text: str
    moves_left: int | None = None


@dataclass
class FightResult:
    """What one driven fight did.

    `bars` is every row-24 bar in the order it appeared, deduplicated against
    the one before it, and `lines` the messages that say a blow landed.  Both
    are kept because the interesting failure is a fight that ends with the
    party having done nothing, and only the messages tell that apart from a
    fight the party won.
    """

    outcome: str
    turns: int
    seconds: float
    bars: list[str]
    lines: list[str]

    @property
    def acted(self) -> bool:
        """Did a blow land, or miss?  The difference between a fight the party
        fought and one it stood through."""
        return any(RE_STRUCK.search(ln.upper()) for ln in self.lines)


# How a character moves in a fight, measured key by key in `work/p126/run1.log`:
# eight candidate key sets were pressed at a `MOVE/ATTACK, MOVE LEFT = 12` bar
# and the square each one spent was read out of the combatant table.
#
# **It is the joystick, not the keyboard.**  XTEST `Up`, `Down`, `Left` and
# `Right` moved nothing at all, and neither did the world's own `I`, `J`, `K`,
# `M`.  The numeric keypad did, because VICE maps it to joystick port 2 -- so
# this table is a property of the emulator's keyset as the pool seeds it, and
# what would move it is a `vicerc` with a different joystick mapping, not a
# different machine.
#
# Seven of the eight were seen to move a character.  `KP_4` is the exception
# and it is graded PROBABLE by symmetry: the square west of the acting
# character was occupied by another party member on the one turn it was tried.
STEP_KEYS = {
    (0, -1): "KP_8",
    (0, 1): "KP_2",
    (-1, 0): "KP_4",       # PROBABLE -- see above
    (1, 0): "KP_6",
    (-1, -1): "KP_7",
    (1, -1): "KP_9",
    (-1, 1): "KP_1",
    (1, 1): "KP_3",
}

# Where the game names whose turn it is: the right-hand panel, which reads
# `BAKSHI / HIT POINTS 4 / AC 3 / TWO-HANDED SWORD` down its own column.
PANEL_LEFT = 22
PANEL_ROWS = range(0, 8)


def chebyshev(a, b) -> int:
    """Squares between two combatants, eight-way."""
    return max(abs(a.x - b.x), abs(a.y - b.y))


def word_column(text: str, label: str) -> int:
    """Where `label` starts on a bar as a **whole word**, or -1.

    `str.find` is not enough here.  `MOVE` is inside `MOVE/ATTACK, MOVE LEFT
    = 9`, so a substring match walks the highlight towards a target that is not
    a command at all -- which is one of the two ways the draft in
    `work/p118-step3/run.py` stalled.
    """
    want = label.upper()
    for m in re.finditer(r"[A-Z0-9<>]+", text.upper()):
        if m.group(0) == want:
            return m.start()
    return -1


def span_in(screen, row: int, colour: int = 1) -> tuple[int, int] | None:
    """The highlighted run on a bar, from a snapshot's **own** colour RAM.

    `Session.highlight_span` reads colour RAM in a second monitor connection,
    which means the text and the highlight come from two different moments.
    Outside a fight that is harmless; in one the bar is redrawn for every
    character in turn, so the two can disagree and the walk goes the wrong way.
    Blank cells are ignored because colour RAM under a space keeps whatever the
    previous screen left there.
    """
    base = row * 40
    idx = [i for i in range(40)
           if screen.colours[base + i] == colour
           and screen.codes[base + i] not in (0x20, 0x00)]
    return (idx[0], idx[-1]) if idx else None


class Session:
    """One driven game.

    With no `slot` this is what it always was: `work/drive/`, ports 6502, 6510
    and 6600, display `:7` -- the human's numbers, kept so `tools/walkrun.py`
    and `tools/porcmd` need no change.  Pass a `tools.instance.Slot` and every
    one of those six becomes that slot's own, which is the whole of what makes
    two sessions able to run at once.
    """

    def __init__(self, disk: str | None = None, display: str | None = None,
                 slot=None, fastloader: str | None = None):
        self.slot = slot
        # `DISABLE FASTLOADER (Y/N)?`.  A parameter, not a constant, because
        # until P69 nobody could A/B it.  Measured, 5 boots a cell: on this
        # machine's JiffyDOS `Y` reaches the main menu in 167.9 s against `N`'s
        # 168.8; on a stock kernal the order reverses, 238.6 against 199.6.
        # So the default stays `y` and a stock VICE wants `n`.
        # `docs/131-fastloader.md`.
        self.fastloader = (
            fastloader or os.environ.get("POR_FASTLOADER") or "y"
        ).strip().lower()[:1]
        assert self.fastloader in ("y", "n"), \
            f"POR_FASTLOADER must be y or n, not {self.fastloader!r}"
        self.here = str(slot.dir) if slot is not None else HERE
        self.mon_port = slot.port if slot is not None else MON_PORT
        self.text_port = slot.text_port if slot is not None else TEXT_PORT
        self.cmd_port = slot.cmd_port if slot is not None else CMD_PORT
        self.monflags = slot.monflags() if slot is not None else MONFLAGS
        self.display = display or (slot.display if slot is not None else DISPLAY)
        self.disk = disk or f"{self.here}/SIDE1.D64"
        self.kbd = Keyboard(self.display)
        self.text: socket.socket | None = None
        self.attached = self.disk
        # which image answers "insert your save game disk"; swappable so a run
        # can read one save and write another
        self.save_disk = f"{self.here}/SIDE0.D64"
        self.side_prompts = 0
        self._last_prompt = 0.0
        # The process group `launch()` started.  Teardown kills this and nothing
        # else -- never a process by name.
        self.pgid: int | None = None

    def mon(self, timeout: float = 5.0) -> Monitor:
        """A monitor connection to *this* instance."""
        return Monitor(port=self.mon_port, timeout=timeout)

    # -- lifecycle --------------------------------------------------------

    def launch(self) -> None:
        """Start Xephyr and VICE in their own process group.

        **It kills nothing first.**  This used to `pkill -x x64sc` and
        `pkill -x Xephyr`, which under the instance pool would kill every other
        agent's emulator and Donald's own game -- the same failure mode as the
        incident behind `CLAUDE.md`'s rule, generalised.
        """
        env = dict(os.environ, MONFLAGS=self.monflags, POR_DISPLAY=self.display)
        if self.slot is not None:
            env.update(self.slot.env())
        os.makedirs(self.here, exist_ok=True)
        proc = subprocess.Popen(
            [f"{TOOLS}/porlaunch.sh", self.disk],
            env=env,
            stdout=open(f"{self.here}/vice.log", "wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.pgid = os.getpgid(proc.pid)
        if self.slot is not None:
            self.slot.record(pgid=self.pgid, launched=time.time())
        for _ in range(60):
            time.sleep(1)
            try:
                with self.mon(3):
                    break
            except (OSError, MonitorError):
                continue
        else:
            raise RuntimeError("VICE never came up")
        self.text = socket.create_connection(("127.0.0.1", self.text_port), timeout=5)
        self.text.settimeout(3)
        self.attached = self.disk
        self.log("VICE up; text monitor connected")

    def close(self, kill: bool = True) -> None:
        try:
            with self.mon(3) as m:
                n = m.checkpoints_clear()
                if n:
                    self.log(f"deleted {n} checkpoints")
        except Exception:
            pass
        if self.text is not None:
            self.text.close()
            self.text = None
        if kill:
            self.terminate()

    def terminate(self, timeout: float = 8.0) -> bool:
        """Kill the process group `launch()` started -- Xephyr and VICE together.

        Nothing else on the machine, and nothing by name.  A session that never
        launched anything tears down to a no-op rather than guessing at what to
        kill, which is the entire difference from the `pkill -x x64sc` this
        replaced.
        """
        if self.pgid is None:
            return False
        killed = instance._killpg(self.pgid, timeout)
        self.pgid = None
        if self.slot is not None:
            self.slot.record(pgid=None)
        return killed

    @staticmethod
    def log(*a) -> None:
        print(*a, flush=True)

    # -- disk -------------------------------------------------------------

    def attach(self, path: str, unit: int = 8) -> None:
        if str(path).isdigit():
            path = f"{self.here}/SIDE{path}.D64"
        path = os.path.abspath(path)
        assert path.startswith(self.here), \
            f"refusing to attach outside {self.here}: {path}"
        with self.mon(5):  # stopping is what makes the text monitor answer
            self.text.sendall(f'attach "{path}" {unit}\n'.encode())
            time.sleep(0.5)
            with contextlib.suppress(TimeoutError, socket.timeout):
                self.text.recv(65536)  # drained; it is only prompt echo
        self.attached = path
        self.log(f"  attached {os.path.basename(path)}")

    # -- screen -----------------------------------------------------------

    def screen(self):
        try:
            with self.mon(3) as m:
                if is_bitmap(m):
                    return None
                return read_screen(m)
        except (OSError, MonitorError):
            return None

    def dump(self, rows=range(25)) -> None:
        s = self.screen()
        if s is None:
            print("(bitmap)")
            return
        print(f"screen ${s.address:04X}")
        for r in rows:
            line = s.row(r)
            if line.strip():
                print(f"{r:2d} {s.row_colour(r):2d} |{line}|")

    def colours(self, row: int) -> bytes:
        with self.mon(5) as m:
            return bytes(c & 0x0F for c in m.read(0xD800 + row * 40, 40))

    def highlight_span(self, row: int) -> tuple[int, int] | None:
        c = self.colours(row)
        idx = [i for i, v in enumerate(c) if v == 1]
        return (idx[0], idx[-1]) if idx else None

    # -- prompts ----------------------------------------------------------

    def handle_prompt(self, s=None) -> bool:
        """Answer whichever `insert a disk` prompt is on screen.

        The message lingers for a second or so after the keypress, so without
        a cooldown every poll re-answers it -- and a redundant `attach` resets
        the drive, which is slow and can lose the load that was in flight.
        """
        if time.time() - self._last_prompt < 2.0:
            return False
        if s is None:
            s = self.screen()
        if s is None:
            return False
        text = s.text()
        want = None
        if SAVE_PROMPT in text:
            want = self.save_disk
        else:
            m = RE_GAME_SIDE.search(text)
            if m:
                want = f"{self.here}/SIDE{m.group(1)}.D64"
        if want is None:
            return False
        self._last_prompt = time.time()
        if os.path.abspath(want) != self.attached:
            self.log(f"  prompt -> {os.path.basename(want)}")
            self.attach(want)
        self.kbd.key("space")
        return True

    def wait_text(self, needle, timeout=180.0, interval=0.35):
        needles = [needle] if isinstance(needle, str) else list(needle)
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.screen()
            if s is not None:
                for n in needles:
                    if s.contains(n):
                        return n, s
                self.handle_prompt(s)
            time.sleep(interval)
        return None, None

    def settle(self, seconds=6.0) -> None:
        """Ride out a load, answering disk prompts as they appear."""
        end = time.time() + seconds
        while time.time() < end:
            self.handle_prompt()
            time.sleep(0.35)

    # -- menus ------------------------------------------------------------

    def select_row(self, label: str, timeout=30.0) -> bool:
        """Vertical menu: walk the white row onto *label*, then Return.

        Driven by where the highlight is, not by counting from an assumed
        start, because a swallowed keypress otherwise puts every later count
        out by one.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(0.3)
                continue
            hit = s.find(label)
            hot = s.highlighted_rows()
            if hit is None or not hot:
                self.handle_prompt(s)   # a disk prompt can sit over any menu
                time.sleep(0.3)
                continue
            # The column headings are white too, so take the highlighted row
            # nearest the target rather than the first one on the screen.
            cur = min(hot, key=lambda r: abs(r - hit[0]))
            if cur == hit[0]:
                self.kbd.key("Return")
                return True
            self.kbd.key("Down" if cur < hit[0] else "Up")
        return False

    def select_bar(self, label: str, row: int = 24, timeout=30.0) -> bool:
        """Horizontal command bar: the highlight is a run of cells, not a row."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(0.3)
                continue
            col = s.row(row).find(label.upper())
            span = self.highlight_span(row)
            if col < 0 or span is None:
                self.handle_prompt(s)   # a disk prompt can sit over any bar
                time.sleep(0.3)
                continue
            if span[0] == col:
                self.kbd.key("Return")
                return True
            self.kbd.key("Right" if span[0] < col else "Left")
        return False

    # -- the game ---------------------------------------------------------

    def pass_protection(self) -> bool:
        """Answer the code wheel.

        `$12D4` compares seven bytes of `$9700` against the expected word;
        `$12D9` is the `BNE` that rejects a mismatch.  Two `NOP`s there let any
        word through, which beats reading the expected index from `$1376` and
        looking the word up.  The overlay is read back and checked first: this
        address holds unrelated live code once another side has loaded.

        Then six letters are typed and **Return is injected into the KERNAL
        keyboard buffer**, because XTEST `Return` never arrives at this prompt
        while XTEST letters do.
        """
        with self.mon(5) as m:
            cur = m.read(0x12D9, 2)
            if cur != bytes([0xD0, 0x04]):
                self.log(f"$12D9 is {cur.hex()}, not D0 04 -- not patching")
                return False
            m.write(0x12D9, bytes([0xEA, 0xEA]))
        self.log("copy protection patched at $12D9")
        self.kbd.text("aaaaaa")
        time.sleep(0.5)
        self.press_kernal(0x0D)
        return True

    def press_kernal(self, code: int) -> None:
        """Deliver one PETSCII code through the KERNAL keyboard buffer.

        The game's key fetcher at `$2E4E` reads `$0277` with the count at
        `$C6`, so this works where XTEST does not.  `$0277` is written first
        so the game can never see a count without a character behind it.
        """
        with self.mon(5) as m:
            m.write(0x0277, bytes([code]))
        with self.mon(5) as m:
            m.write(0xC6, bytes([1]))

    def boot(self) -> bool:
        self.launch()
        if self.wait_text("DISABLE FASTLOADER", 120)[0] is None:
            self.log("no fastloader prompt")
            return False
        self.kbd.key(self.fastloader, 0.15, 0.28)
        self.log(f"fastloader: {self.fastloader.upper()}")
        if self.wait_text("PLAY GAME", 240)[0] is None:
            self.log("no PLAY GAME menu")
            return False
        self.kbd.key("Return")  # left alone, this screen starts the demo
        self.log("PLAY GAME")
        if self.wait_text("INPUT THE CODE WORD", 240)[0] is None:
            self.log("no code word prompt")
            return False
        return self.pass_protection()

    def load_save(self) -> bool:
        if self.wait_text("LOAD SAVED GAME", 240)[0] is None:
            return False
        if not self.select_row("LOAD SAVED GAME"):
            return False
        self.settle(4)
        if self.wait_text("LOAD SAVED GAME: YES", 60)[0] is None:
            return False
        self.kbd.key("Return")  # YES is already white
        hit, _ = self.wait_text("BEGIN ADVENTURING", 240)
        return hit is not None

    def begin_adventuring(self) -> bool:
        if not self.select_row("BEGIN ADVENTURING"):
            return False
        hit, _ = self.wait_text("ENCAMP", 240)
        return hit is not None

    def position(self) -> tuple[int, int, int]:
        """x, y, facing.

        Read off the game's own status line, not out of `$49C0`.  The memory
        copy is real and it does end up on the disk, but it lags a move --
        reading it straight after a step gives the *previous* square, which
        silently turns a good step into a "blocked" one.  The status line
        (`E 16:48 5,2`) is correct the moment the screen settles.
        """
        for _ in range(12):
            s = self.screen()
            if s is not None:
                m = RE_STATUS.search(s.text())
                if m:
                    return int(m.group(4)), int(m.group(5)), FACING[m.group(1)]
            time.sleep(0.3)
        with self.mon(5) as mon:  # fallback: the lagging memory copy
            x, y, f = mon.read(0x49C0, 3)
        return x, y, f

    def walk(self, moves: str, hold=0.15, gap=0.30) -> None:
        """`moves` in the game's own letters: I forward, J left, K right, M about."""
        for ch in moves.upper():
            self.walk_one(ch, hold, gap)

    def walk_one(self, move: str, hold=0.15, gap=0.30, tries: int = 4) -> bool:
        """One move, verified by the status line.

        Nothing here can be taken on trust.  Selecting `MOVE` succeeds against
        a **stale** row 24 -- the game does not always redraw the command bar
        after a room description -- and the first burst after a screen change
        is swallowed.  So the move is re-sent until the status line moves, and
        a move that never moves it is reported as blocked, which for a forward
        step is exactly the map fact worth having.
        """
        before = self.status()
        for _ in range(tries):
            if not self.select_bar("MOVE", timeout=8):
                self.leave_move(2)
                continue
            time.sleep(0.6)
            self.kbd.key(move.lower(), hold, gap)
            time.sleep(1.2)
            if self.status() != before:
                self.leave_move()
                return True
        self.leave_move()
        return False

    def status(self):
        """(facing, minutes, x, y) off the status line, or None."""
        for _ in range(8):
            s = self.screen()
            if s is not None:
                m = RE_STATUS.search(s.text())
                if m:
                    return (
                        FACING[m.group(1)],
                        int(m.group(2)) * 60 + int(m.group(3)),
                        int(m.group(4)),
                        int(m.group(5)),
                    )
                self.handle_prompt(s)
            time.sleep(0.3)
        return None

    def leave_move(self, tries: int = 8) -> bool:
        """Get out of move mode, and *check*.

        A single Return here is not enough: the game swallows input while it
        redraws the view, and the next thing the driver does is hunt for a
        command bar that is still showing `I,J,K,M`.
        """
        for n in range(tries):
            if n % 2:
                # XTEST Return is not dependable here; the KERNAL buffer is.
                self.press_kernal(0x0D)
            else:
                self.kbd.key("Return", 0.20, 0.30)
            time.sleep(0.6)
            s = self.screen()
            if s is not None and not s.contains("I,J,K,M"):
                return True
            self.handle_prompt(s)
        return False

    def save_game(self, to: str | None = None) -> bool:
        if to:
            self.save_disk = os.path.abspath(to)
        if not self.select_bar("ENCAMP"):
            return False
        self.settle(2)
        if not self.select_bar("SAVE"):  # `ENCAMP:SAVE VIEW MAGIC ...`
            return False
        self.settle(6)  # `INSERT YOUR SAVE GAME DISK` -> attach, press a key
        if not self.select_bar("SAVE GAME"):  # `SAVE GAME  EXIT`
            return False
        self.settle(14)  # the write, then `INSERT YOUR GAME DISK #3`
        self.select_bar("EXIT")
        return True

    # -- combat -----------------------------------------------------------

    def mode(self) -> int | None:
        """LINKER's dispatch byte: which overlay is running, or None.

        `1` DUNGEON, `2` COMBAT.  `automap/combat.py` documents the rest.

        **None is "the read failed", not a mode.**  `screen()` and `battle()`
        degrade the same way, and this one has to as well because `fight()`
        calls it once a second for up to `budget` seconds: a single wedged
        monitor -- a stray client on the port, a text monitor left open --
        would otherwise raise out of the whole fight and throw away every
        turn, bar and line gathered up to that point, which is the evidence
        the harness exists to collect.
        """
        try:
            with self.mon(5) as m:
                return m.read(MODE, 1)[0]
        except (OSError, MonitorError):
            return None

    def in_combat(self) -> bool:
        """True only on a read that answered COMBAT.  A failed read is False."""
        return self.mode() == COMBAT

    def battle(self):
        """The fight as `automap.combat` reads it, or None.

        One monitor connection for the whole read rather than one per range:
        a stop/resume pair costs the emulation ~14.3 ms of extra time whatever
        it carries, so the number that matters is how many, not how many bytes.
        """
        from automap.combat import read_battle

        class _Target:
            def __init__(self, m):
                self.m = m

            def read(self, addr, length):
                return self.m.read(addr, length)

        try:
            with self.mon(8) as m:
                return read_battle(_Target(m))
        except (OSError, MonitorError):
            return None

    def combat_state(self, s=None) -> CombatBar:
        """Row 24 during a fight, classified.  Reading a fight is mostly this.

        A bar caught **half redrawn** -- `MOVE/AT`, `MO`, both seen in
        `work/p118-step3/*.log` -- comes back as `BAR_MESSAGE` rather than
        being forced into a kind, so the driver waits and reads again instead
        of pressing Return at a bar that does not exist yet.
        """
        if s is None:
            s = self.screen()
        if s is None:
            return CombatBar(BAR_NONE, "")
        bar = s.row(24).strip()
        up = bar.upper()
        # Whole words, like every other branch here: a substring test would
        # take IMPRESSED for PRESS.  `word_column` tokenises, so a two-word
        # label is two calls rather than one.
        if word_column(up, "CONTINUE") >= 0 and word_column(up, "BATTLE") >= 0:
            return CombatBar(BAR_CONTINUE, bar)
        found = RE_MOVE_LEFT.search(up)
        if found:
            return CombatBar(BAR_MOVE, bar, int(found.group(1)))
        # `DONE` alone, not `MOVE` and `DONE`.  A character who has spent every
        # square gets `VIEW AIM USE QUICK DONE` -- **MOVE is dropped from its
        # own command bar** -- and a driver that wanted both would sit waiting
        # at a bar that was asking it for a command.  Measured in
        # `work/p126/run1.log`, on the press that spent the last square.
        if word_column(up, "DONE") >= 0:
            return CombatBar(BAR_COMMAND, bar)
        if word_column(up, "PRESS") >= 0:
            return CombatBar(BAR_PRESS, bar)
        # `DONE` does not end a turn; it opens this.  `GUARD` on it is what
        # passes the turn, which is where the `GUARDING` in the old logs was
        # coming from.  Told apart from a treasure bar, which also carries
        # EXIT, by DELAY and SPEED being on it -- **not** by GUARD, which drops
        # off the bar for a character that cannot take it and left the driver
        # bouncing off `DELAY QUIT SPEED EXIT` (`work/p126/melee5.log`).
        if word_column(up, "DELAY") >= 0 and word_column(up, "SPEED") >= 0:
            return CombatBar(BAR_DONE, bar)
        if word_column(up, "EXIT") >= 0:
            return CombatBar(BAR_EXIT, bar)
        if word_column(up, "YES") >= 0 and word_column(up, "NO") >= 0:
            return CombatBar(BAR_YESNO, bar)
        return CombatBar(BAR_BLANK if not bar else BAR_MESSAGE, bar)

    #: Which bars `combat_bar` will walk the highlight along.  Not the move
    #: sub-bar: `MOVE LEFT = 9` is a prompt for a direction, not a menu, and
    #: sending Right there steps the character.
    SELECTABLE = (BAR_COMMAND, BAR_CONTINUE, BAR_YESNO, BAR_EXIT,
                  BAR_DONE)

    def combat_bar(self, label: str, timeout: float = 20.0, row: int = 24) -> bool:
        """Put the combat highlight on `label` and press Return.

        `select_bar` with three differences.  It **refuses every bar that is
        not a menu**, which is what keeps a `Right` out of the move sub-bar,
        where it would step the character rather than move a highlight.  The
        highlight comes from the same screen snapshot as the text rather than
        from a second monitor read, so a bar redrawn between the two cannot
        send the walk the wrong way.  And the label is matched as a whole word
        -- which on every bar measured so far gives the same answer as a plain
        `find`, so treat that one as a guard against a vocabulary we have not
        seen rather than as a fix for anything.

        Returns True when the highlight was on `label` and Return was sent.
        It does **not** claim the command did anything -- verify by effect.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(0.3)
                continue
            state = self.combat_state(s)
            if state.kind not in self.SELECTABLE:
                time.sleep(0.3)
                continue
            col = word_column(s.row(row), label)
            span = span_in(s, row)
            if col < 0 or span is None:
                time.sleep(0.3)
                continue
            if span[0] == col:
                self.kbd.key("Return")
                return True
            self.kbd.key("Right" if span[0] < col else "Left")
        return False

    def idle(self, seconds: float) -> None:
        """Wait out somebody else's turn.

        A seam rather than a bare `time.sleep`, so a fight can be driven
        against a scripted screen without an emulator or a wall clock.
        """
        time.sleep(seconds)

    def combat_turn(self) -> str:
        """Pass one character's turn.  Returns what was chosen.

        It takes no bar: it is only ever reached at a command bar, and it
        walks the highlight to `DONE` from wherever it is rather than from
        anything the bar said.  It used to take one and never read it.

        **`DONE` does not end a turn.**  It opens
        `GUARD DELAY QUIT SPEED EXIT`, and `GUARD` on that is what ends it --
        which is where the `GUARDING` on row 24 in the older logs was coming
        from.  A driver that takes DONE and stops leaves the same command bar
        up and is asked again: 210 turns in 420 seconds
        (`work/p126/melee4.log`).
        """
        if not self.combat_bar("DONE", timeout=12):
            return ""
        if self.await_bar((BAR_DONE,), timeout=6) is None:
            return "DONE"
        return self.end_turn()

    def end_turn(self) -> str:
        """Get off the sub-bar `DONE` opens, and end the turn if it can.

        `GUARD` is the one that ends it, and it is **not always offered** --
        some characters get `DELAY QUIT SPEED EXIT` with no GUARD on it at all.
        `DELAY` postpones the character, which also gets the fight moving;
        `EXIT` only backs out, so it is the last resort rather than the answer.
        """
        for choice in ("GUARD", "DELAY", "EXIT"):
            if self.combat_bar(choice, timeout=8):
                return choice
        return ""

    def acting(self, battle, s=None):
        """Whose turn the command bar belongs to, or None.

        The game says so itself: the right-hand panel carries the acting
        character's name, hit points, armour class and readied weapon.  Reading
        it beats inferring from initiative, which several combatants hold at
        once.
        """
        if battle is None:
            return None
        if s is None:
            s = self.screen()
        if s is None:
            return None
        panel = " ".join(s.row(r)[PANEL_LEFT:] for r in PANEL_ROWS)
        # Longest first, so a party holding both SEAN and BROTHER SEAN does not
        # hand every one of BROTHER SEAN's turns to SEAN.
        named = sorted((c for c in battle.party if c.name.strip()),
                       key=lambda c: -len(c.name.strip()))
        for who in named:
            if who.name.strip() in panel:
                return who
        return None

    def await_bar(self, kinds, timeout: float = 6.0,
                  interval: float = 0.4) -> CombatBar | None:
        """Read row 24 until it is one of `kinds`, or give up.

        **The bar lags the keypress.**  Taking MOVE and reading row 24 straight
        afterwards gives the command bar still, so a driver that decides on one
        read concludes the sub-bar never appeared, backs out, and takes MOVE
        again -- 638 times in 420 seconds with `MOVE LEFT = 12` never once
        going down (`work/p126/melee2.log`).  Verify by effect and retry: it is
        the rule the rest of this file already follows.
        """
        deadline = time.time() + timeout
        while True:
            state = self.combat_state()
            if state.kind in kinds:
                return state
            if time.time() >= deadline:
                return None
            time.sleep(interval)

    @staticmethod
    def step_towards(battle, me, target, avoid=()) -> str | None:
        """The key for the step that gets closest, without walking into an ally.

        Aiming straight at the target and pressing that key walks into whoever
        is in the way, and a step into a party member is a blow like any other
        -- the game asks `ATTACK ALLY: YES NO` first, which is how this was
        found (`work/p126/melee.log`).  So the eight squares are ranked by how
        much closer they get, and any square a party member is standing on is
        dropped.  An enemy's square is not dropped: stepping onto it is the
        attack.

        `avoid` is the keys already tried this turn that spent no square --
        a wall, or something else the position table does not show.  Without it
        a character pinned against one burns its whole turn on the same press.
        """
        best = None
        for (dx, dy), key in STEP_KEYS.items():
            if key in avoid:
                continue
            x, y = me.x + dx, me.y + dy
            if not battle.shape.holds(x, y):
                continue
            who = battle.at(x, y)
            if who is not None and who.is_party:
                continue
            reach = max(abs(target.x - x), abs(target.y - y))
            if best is None or reach < best[0]:
                best = (reach, key)
        if best is None or best[0] >= chebyshev(me, target):
            # Every step either blocked or no better than standing still.
            return None
        return best[1]

    def melee_turn(self, state: CombatBar) -> str:
        """Walk the acting character into the nearest enemy, which attacks it.

        `state` is the bar `fight` was looking at.  It is not read -- the
        tactic protocol is `tactic(session, state)` and this is a tactic, so
        it takes one whether it wants one or not; the positions come from
        `battle()`, which is a fresher read than the bar.

        There is no attack key.  `MOVE/ATTACK` is the whole of it: a step into
        an occupied square is a blow, and the game says as much on the sub-bar
        it puts up.  So this takes MOVE, then steps towards the nearest living
        enemy until the sub-bar goes away -- which it does when the character
        attacks, runs out of squares, or dies.

        Distance is Chebyshev because the moves are eight-way.

        **The square it steps into may hold a different enemy than the one it
        aimed at**, because only party members are excluded from the
        candidates.  That still lands a blow and still ends the turn, so it
        does not stall a fight; it means the target this picks is where the
        character is heading rather than what it is guaranteed to hit.  A
        tactic wanting a chosen target would have to exclude the others too.
        """
        b = self.battle()
        me = self.acting(b)
        if b is None or me is None or not me.alive:
            return self.combat_turn()
        if not any(e.alive and e.on_map for e in b.enemies):
            return self.combat_turn()
        # Work out the step **before** taking MOVE.  A character the rest of
        # the party has boxed in has nowhere that gets it closer, and taking
        # MOVE and backing out again does not end its turn: the same command
        # bar comes back and the driver does it again, 638 times in 420
        # seconds (`work/p126/melee3.log`).  A turn that cannot attack has to
        # be **passed**, not merely left.
        index = me.index
        target = min((e for e in b.enemies if e.alive and e.on_map),
                     key=lambda e: chebyshev(me, e))
        if self.step_towards(b, me, target) is None:
            return self.combat_turn()
        if not self.combat_bar("MOVE", timeout=15):
            return self.combat_turn()
        moving = self.await_bar((BAR_MOVE,), timeout=8)
        if moving is None:
            return ""                           # MOVE did not take; press on
        avoid: set[str] = set()
        stepped = False
        for _ in range(24):
            b = self.battle()
            if b is None:
                break
            me = next((c for c in b.combatants if c.index == index), None)
            live = [e for e in b.enemies if e.alive and e.on_map]
            if me is None or not me.on_map or not live:
                break
            target = min(live, key=lambda e: chebyshev(me, e))
            key = self.step_towards(b, me, target, avoid)
            if key is None:                     # nowhere to go that helps
                break
            before = moving.moves_left
            self.kbd.key(key, 0.15, 0.30)
            moving = self.await_bar((BAR_MOVE,), timeout=3)
            if moving is None:
                return "MOVE"                   # attacked, spent, or dead
            if before is not None and moving.moves_left == before:
                # The step cost nothing, so it did not happen.  Try another.
                avoid.add(key)
            else:
                stepped = True
        if self.combat_state().kind == BAR_MOVE:
            self.press_kernal(0x0D)             # back out of move mode
        if not stepped:
            # Still this character's turn, and it has done nothing.  Pass it,
            # or the same bar comes straight back.
            return self.combat_turn()
        return "MOVE"

    def fight(self, budget: float = 300.0, tactic=None,
              poll: float = 1.0) -> FightResult:
        """Drive a fight from `$6E11 == 2` back to `$6E11 == 1`.

        The end of a fight is **not** the mode byte leaving 2: `THE PARTY HAS
        WON !`, the experience share and any treasure run under POST.COM, and
        a driver that stops at the mode byte leaves the party standing at a
        `PRESS <RETURN>` for ever.  So this runs until DUNGEON is back *and*
        the status line is on screen, which is the state the rest of
        `Session` can drive.

        `tactic(session, state)` is called once per command bar and returns
        what it chose; the default passes the turn with `DONE`.

        **`budget` is a floor on when this gives up, not a ceiling on how
        long it runs.**  The deadline is tested once per iteration, and the
        calls inside one iteration carry their own timeouts: this method
        clamps its own to whatever is left, but a tactic's do not, so
        `melee_turn` can spend `combat_bar(..., 15)` plus `await_bar(..., 8)`
        plus `end_turn`'s three tries at 8 past a deadline that had already
        passed -- about 42 seconds in the worst case measured here.  A short
        budget overruns proportionally worse than a long one.  Give it
        seconds to spare rather than the exact number wanted.
        """
        def left() -> float:
            """Seconds to the deadline, never below one -- a timeout of zero
            asks a bar to have already resolved."""
            return max(1.0, end - time.time())

        act = tactic or (lambda sess, state: sess.combat_turn())
        started = time.time()
        end = started + budget
        bars: list[str] = []
        lines: list[str] = []
        seen: set[str] = set()
        turns = 0
        outcome: str | None = None
        if not self.in_combat():
            return FightResult(NOT_FIGHTING, 0, 0.0, bars, lines)
        while time.time() < end:
            mode = self.mode()
            s = self.screen()
            text = s.text() if s is not None else ""
            if outcome is None and WON_TEXT in text:
                outcome = WON
            elif outcome is None and LOST_TEXT in text:
                outcome = LOST
            for row in text.splitlines():
                row = row.strip()
                if row and row not in seen and RE_NOTABLE.search(row.upper()):
                    seen.add(row)
                    lines.append(row)
            if mode == DUNGEON and RE_STATUS.search(text):
                return FightResult(outcome or ENDED, turns,
                                   time.time() - started, bars, lines)
            state = self.combat_state(s)
            if state.text and (not bars or bars[-1] != state.text):
                bars.append(state.text)
            if state.kind == BAR_CONTINUE:
                # The game offering a withdrawal is how a driven fight ends.
                self.combat_bar("NO", timeout=min(12.0, left()))
            elif state.kind == BAR_DONE:
                self.end_turn()      # left open by a turn that did not finish
            elif state.kind == BAR_EXIT:
                self.combat_bar("EXIT", timeout=min(12.0, left()))
            elif state.kind == BAR_PRESS:
                # XTEST Return is not dependable at a prompt; the buffer is.
                self.press_kernal(0x0D)
            elif state.kind == BAR_YESNO:
                # `ATTACK ALLY: YES NO`, which the game puts up when a step
                # would walk into a party member.  `NO` is the conservative
                # answer to a yes/no bar this does not recognise, and this one
                # is the only such bar seen: it stalled a whole fight for its
                # 421-second budget because there was no branch for it at all
                # (`work/p126/melee.log`).
                self.combat_bar("NO", timeout=min(12.0, left()))
            elif state.kind == BAR_MOVE:
                self.press_kernal(0x0D)      # back out of move mode
            elif state.kind == BAR_COMMAND:
                turns += 1
                act(self, state)
            else:
                self.idle(poll)              # a monster's turn, or a redraw
            self.handle_prompt()
        return FightResult(outcome or BUDGET, turns, time.time() - started,
                           bars, lines)


# -- command server ---------------------------------------------------------


def handle(sess: Session, line: str) -> bool:
    parts = line.split()
    if not parts:
        return True
    cmd, args = parts[0], parts[1:]
    if cmd == "quit":
        sess.close()
        return False
    if cmd == "screen":
        sess.dump()
    elif cmd == "key":
        hold = float(args[1]) if len(args) > 1 else 0.10
        gap = float(args[2]) if len(args) > 2 else 0.14
        for _ in range(int(args[3]) if len(args) > 3 else 1):
            sess.kbd.key(args[0], hold, gap)
        time.sleep(0.8)
        sess.dump()
    elif cmd == "text":
        sess.kbd.text(" ".join(args))
        time.sleep(0.8)
        sess.dump()
    elif cmd == "kernal":
        sess.press_kernal(int(args[0], 16))
        time.sleep(0.8)
        sess.dump()
    elif cmd == "attach":
        sess.attach(args[0])
    elif cmd == "savedisk":
        sess.save_disk = os.path.abspath(args[0])
        print(sess.save_disk)
    elif cmd == "peek":
        with sess.mon(5) as m:
            print(m.read(int(args[0], 16), int(args[1]) if len(args) > 1 else 16).hex(" "))
    elif cmd == "poke":
        addr = int(args[0], 16)
        data = bytes.fromhex("".join(args[1:]))
        with sess.mon(5) as m:
            print("was", m.read(addr, len(data)).hex(" "))
            m.write(addr, data)
    elif cmd == "colours":
        print(sess.colours(int(args[0])).hex(" "))
    elif cmd == "settle":
        sess.settle(float(args[0]) if args else 6.0)
        sess.dump()
    elif cmd == "wait":
        hit, _ = sess.wait_text(" ".join(args))
        print("found" if hit else "TIMEOUT")
        sess.dump()
    elif cmd == "row":
        print(sess.select_row(" ".join(args)))
        sess.dump()
    elif cmd == "bar":
        print(sess.select_bar(" ".join(args)))
        sess.dump()
    elif cmd == "pos":
        print(sess.position())
    elif cmd == "walk":
        sess.walk(args[0])
        print(sess.position())
    elif cmd == "save":
        print(sess.save_game(args[0] if args else None))
        print(sess.position())
    elif cmd == "combat":
        print(sess.combat_state())
    elif cmd == "battle":
        b = sess.battle()
        if b is None:
            print("not in a fight")
        else:
            print(f"shape {b.shape.width}x{b.shape.height} camera {b.camera}")
            for c in b.combatants:
                print(f"  {c.index:2d} {c.kind:9s} ({c.x:2d},{c.y:2d}) "
                      f"init {c.initiative:3d} hp {c.hp_text} {c.name}")
    elif cmd == "fight":
        print(sess.fight(float(args[0]) if args else 300.0))
    elif cmd == "shot":
        print("ok" if sess.kbd.screenshot(
            args[0] if args else f"{sess.here}/shot.png") else "failed")
    else:
        print("unknown command", cmd)
    return True


def serve(sess: Session, port: int | None = None) -> None:
    port = sess.cmd_port if port is None else port
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(4)
    print(f"command server on {port}", flush=True)
    running = True
    while running:
        conn, _ = srv.accept()
        conn.settimeout(900)
        try:
            line = conn.makefile("r").readline().strip()
        except Exception:
            conn.close()
            continue
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                running = handle(sess, line)
        except Exception as exc:  # a bad command must not end the session
            buf.write(f"ERROR {type(exc).__name__}: {exc}\n")
        with contextlib.suppress(OSError):
            conn.sendall(buf.getvalue().encode())
            conn.close()
    srv.close()


if __name__ == "__main__":
    # `--pool` claims an instance slot and holds its lease for as long as this
    # process lives; without it the session is the legacy one on 6502/6510/6600
    # and `work/drive/`, which is what `tools/porcmd` still talks to.
    argv = sys.argv[1:]
    slot = None
    if argv and argv[0] == "--pool":
        argv = argv[1:]
        slot = instance.claim(game="por", note=os.environ.get("POR_AGENT", ""))
        slot.seed_vicerc()
        print(f"slot {slot.n}: monitor {slot.port} text {slot.text_port} "
              f"cmd {slot.cmd_port} display {slot.display} dir {slot.dir}",
              flush=True)
    sess = Session(argv[0] if argv else None, slot=slot)
    if len(argv) > 1:
        sess.save_disk = os.path.abspath(argv[1])
    if not sess.boot():
        print("boot failed")
    serve(sess)

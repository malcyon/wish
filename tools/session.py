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
import pathlib
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import NamedTuple

# From this file, not from a path measured on one machine.  These were three
# absolute paths under `/home/donald`, which is where `tools/` happens to sit
# here and nowhere else -- and `tools/` ships, so they were wrong for everybody
# who is not Donald.  `tests/gamedata.py` carries the same lesson: an absolute
# path is invisible on CI, and this one hid until a test imported the module
# and CI answered `ModuleNotFoundError: No module named 'session'`.
TOOLS = str(pathlib.Path(__file__).resolve().parent)
sys.path.insert(0, TOOLS)
import instance  # noqa: E402
from drive import Keyboard, Monitor, MonitorError, is_bitmap, read_screen  # noqa: E402

# Disk images and logs live in scratch; the code does not.
HERE = str(pathlib.Path(TOOLS).parent / "work" / "drive")
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

# The in-game status line, and **it has two shapes**.  Indoors it carries the
# facing letter -- `E 16:48 5,2`.  On the travel grid the word `OUTDOORS`
# stands where that letter goes -- `OUTDOORS 22:02 7,28` -- and there is no
# facing out there at all.
#
# The lookarounds are not decoration.  Without them the final `S` of
# `OUTDOORS` matched, so `status()` answered facing 2, south, for every
# outdoor party on every square, and `tools/savecheck.py` printed `facing=2`
# as though it were a reading (`#189`).
RE_STATUS = re.compile(r"(?<![A-Z])([NESW])(?![A-Z]) +(\d+):(\d+) +(\d+),(\d+)")
RE_OUTDOOR_STATUS = re.compile(r"OUTDOORS +(\d+):(\d+) +(\d+),(\d+)")
FACING = {"N": 0, "E": 1, "S": 2, "W": 3}

# -- the two worlds ---------------------------------------------------------
# `$49E6` is non-zero in a `GEO` area and zero on the travel grid
# (`docs/118-debug-mode.md`, `docs/140-loaded-files-cache.md`).  Nothing in
# this file asked it until `#189`, which is the whole of why the driver could
# not move an outdoor party: it was written against the dungeon and assumed it.
INDOORS_AT = 0x49E6
#: The dungeon's live position triple: x, y, facing.  It freezes outdoors at
#: the square the party left the grid on, so reading it out there answers the
#: pier rather than where the party is standing.
DUNGEON_XY = 0x49C0
#: The live travel-grid square, window-local -- `#47`, `#59`,
#: `docs/141-dos-savegame.md`.  Two bytes, and no facing.
TRAVEL_XY = 0x49C3

#: What row 24 reads while the travel grid is waiting for a direction:
#: `1-8, RETURN OR BUTTON`.  Matched on `1-8` because that is the part no
#: other bar in the game carries.
OUTDOOR_PROMPT = "1-8"

#: The travel grid's directions, **clockwise from north**, and they are not
#: the numpad: measured on 2026-09-02 by writing `$49C3`/`$49C4`, pressing one
#: digit and reading the square back -- `3` took (11,26) to (12,26), east, and
#: `6` took it to (10,27), south-west (`#189`).
COMPASS = {
    "1": (0, -1), "2": (1, -1), "3": (1, 0), "4": (1, 1),
    "5": (0, 1), "6": (-1, 1), "7": (-1, 0), "8": (-1, -1),
}

#: The world screen's party panel, which is a **menu** and not a read-out:
#: one of its names is drawn in the highlight colour, `Up` and `Down` move
#: that highlight, and `VIEW` puts up the sheet of whichever name carries it.
#: That is what reaches characters two to six; there is nothing on the sheet
#: itself that does (`#183`).
#:
#: `PARTY_COLUMN` is where the names start and `PARTY_HEADER` is the heading
#: over the column beside them.  The rows are not constants because a party
#: of six and a party of eight fill different ones -- they are read off the
#: screen, under the header.
#:
#: **These are not `PANEL_LEFT` and `PANEL_ROWS` further down**, which are
#: combat's panel at column 22: slicing the world panel there cuts five
#: letters off every name, and `THRENDER GRONE` arrives as `DER GRONE`.  Two
#: different panels, so two different names -- the first draft of this called
#: them the same thing and the combat pair, defined lower in the file, simply
#: overwrote it.
#:
#: `PARTY_ROWS` stops at 12 and that is not slack: **row 14 is the status
#: line**, `W 21:15 15,4`, which starts in the panel's own name column and
#: would otherwise be read as a seventh character.  Eight names fill rows 4
#: to 11, so twelve is exactly enough for the largest party the game holds.
PARTY_COLUMN = 17
PARTY_HEADER = "AC"
PARTY_ROWS = range(0, 12)

#: The bar the character sheet puts on row 24.  It carries no `NEXT`.
SHEET_BAR = "VIEW:ITEMS"


class Status(NamedTuple):
    """The status line, read: where the party is and what time it is.

    **`facing` is None on the travel grid**, and that is a reading rather than
    a failure -- the game prints no facing out there.  A NamedTuple so the
    four values still index and compare as the plain tuple this used to
    return, which is what `walk_one` and `tools/savecheck.py` do with it; the
    change a caller has to cope with is `facing` being absent, not the shape.
    """

    facing: int | None
    minutes: int
    x: int
    y: int

    @property
    def outdoors(self) -> bool:
        """True when the line said `OUTDOORS` rather than a facing letter."""
        return self.facing is None

    def where(self) -> str:
        """The reading in words, for a line a person reads."""
        way = "outdoors" if self.outdoors else "NESW"[self.facing]
        return (f"{way} {self.minutes // 60}:{self.minutes % 60:02d} "
                f"{self.x},{self.y}")


def parse_status(text: str) -> Status | None:
    """The status line out of a screen's text, whichever of the two it is.

    Indoors first, then the travel grid.  Either shape or None, and None means
    no status line was on the screen -- a menu, a bitmap, camp -- rather than
    an error.
    """
    m = RE_STATUS.search(text)
    if m:
        return Status(FACING[m.group(1)],
                      int(m.group(2)) * 60 + int(m.group(3)),
                      int(m.group(4)), int(m.group(5)))
    m = RE_OUTDOOR_STATUS.search(text)
    if m:
        return Status(None,
                      int(m.group(1)) * 60 + int(m.group(2)),
                      int(m.group(3)), int(m.group(4)))
    return None


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
BAR_LEAVE = "leave"        # GO BACK LEAVE TREASURE -- what EXIT on the
                           # treasure bar opens when treasure is still there
BAR_DONE = "done"          # GUARD DELAY QUIT SPEED EXIT -- what DONE opens
BAR_PRESS = "press"        # PRESS <RETURN> OR BUTTON TO CONTINUE
BAR_MESSAGE = "message"    # GUARDING, YOUR TEAMMATE IS DYING -- and a bar
                           # caught half-redrawn, which reads as `MOVE/AT`
BAR_BLANK = "blank"        # a monster's turn: row 24 is empty
BAR_NONE = "none"          # no readable screen at all

# What row 24 becomes once the move sub-bar has gone and the turn has moved
# on.  Deliberately not `BAR_MESSAGE` or `BAR_NONE`: a half-redrawn bar reads
# as a message, and taking that for the end of a turn is the mistake
# `combat_state` already refuses to make.
AFTER_MOVE = (BAR_COMMAND, BAR_DONE, BAR_PRESS, BAR_CONTINUE, BAR_YESNO,
              BAR_EXIT, BAR_BLANK)

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

# Of those, the ones only a blow can produce -- **by either side**.  This is
# not who swung and cannot be made into it: the game prints the party's blows
# and the monsters' in the same band in the same words, and the party is being
# attacked in every fight it is in.  `FightResult.anybody_swung` is what this
# answers, and `acted` deliberately does not use it (`#163`).
RE_STRUCK = re.compile(r"\b(HITS|MISSES|SLAIN)\b|POINTS OF DAMAGE")

WON, LOST, ENDED, BUDGET, NOT_FIGHTING = (
    "won", "lost", "ended", "budget", "not fighting")

# What a tactic answers when the blow was struck.  `melee_turn` returns it
# only after a step into an enemy's square and the move sub-bar then going
# away, which is the measured signature of a blow that resolved: an attack
# spends no movement and moves nobody, so nothing else on the screen says it
# happened (`#127`, `work/issue127/sweep1.jsonl`, turn 15).
#
# `fight` counts these and `FightResult.acted` is that count.  A tactic that
# strikes without saying so therefore leaves `acted` False, which is the safe
# direction: this is a check that gets believed, and one that under-reports
# costs a re-run where one that over-reports costs a wrong conclusion.
ATTACK = "ATTACK"


class CombatBar(NamedTuple):
    """Row 24 during a fight, classified."""

    kind: str
    text: str
    moves_left: int | None = None


@dataclass
class FightResult:
    """What one driven fight did.

    `bars` is every row-24 bar in the order it appeared, deduplicated against
    the one before it, and `lines` the messages the fight printed.  Both are
    kept because the interesting failure is a fight that ends with the party
    having done nothing, and a log of command bars cannot tell that apart from
    a fight the party won.

    `blows` is the count `acted` rests on: the turns a tactic answered
    `ATTACK`.
    """

    outcome: str
    turns: int
    seconds: float
    bars: list[str]
    lines: list[str]
    #: Turns whose tactic answered `ATTACK`.  Counted by `fight`.
    blows: int = 0
    #: One entry per bar in `bars`: the word the highlight was covering when
    #: that bar was read, or `-` for a bar carrying no highlight at all.
    #:
    #: Beside `bars` rather than folded into it, because they are two facts
    #: read from one snapshot and the interesting failure needs both.  A run
    #: that logged only the bars could say the driver had reached the
    #: treasure screen and not whether it had reached it *with the highlight
    #: on the wrong command* -- which is exactly the question `#171` was left
    #: unable to answer.
    highlights: list[str] = field(default_factory=list)

    @property
    def acted(self) -> bool:
        """Did a **party member** strike?  The difference between a fight the
        party fought and one it stood through.

        This is the driver's own count of turns that ended with the blow
        struck, and **not** a read of the message band.  It used to be the
        latter, and the latter cannot answer the question: `RE_STRUCK` matches
        `HITS`, `MISSES`, `SLAIN` and `POINTS OF DAMAGE` for **either side**,
        and the party is being attacked in every fight it is in.  One Slums
        ambush drove 27 turns, passed 26 of them with the party standing next
        to the orcs, and reported `acted=True` off `AND MISSES...` and `AND
        HITS FOR 7 POINTS OF DAMAGE` -- the orcs (`#163`).

        **What it depends on, said out loud:** the tactic.  `melee_turn`
        answers `ATTACK` when the blow resolved and `fight` counts that, so a
        tactic that strikes without answering `ATTACK` gets `acted` False.
        That is under-reporting, which is the direction a check that gets
        believed should fail in.  `evidence` says the same thing in words for
        a report.

        **And that is not hypothetical: it is `melee_turn` itself, today.**
        Nothing in this project drives `AIM` or `CAST`, and `melee_turn` is
        the only tactic that ever answers `ATTACK` -- which it does for a step
        into an enemy's square and for nothing else.  A character with a
        missile weapon readied cannot strike that way, so its turn is passed
        rather than counted; `test_a_blow_the_game_refuses_passes_the_turn_
        rather_than_pressing_on` pins exactly that.  **So a party that fought
        only with bows or spells reads here as a party that did nothing**, and
        `evidence` cannot tell the two apart.  That is the same fault `#163`
        fixed with the sign flipped, and it is survivable only because it errs
        towards saying nothing was proven.  What removes it is a tactic that
        drives `AIM`, which is unwritten.
        """
        return self.blows > 0

    @property
    def anybody_swung(self) -> bool:
        """Did **anybody** swing, either side?  What `acted` used to mean.

        Kept, and named for what it is, because it is worth knowing that a
        fight lasted a round at all -- and because deleting it would leave the
        trap undocumented for whoever next writes a pattern over `lines`.
        """
        return any(RE_STRUCK.search(ln.upper()) for ln in self.lines)

    @property
    def evidence(self) -> str:
        """What `acted` rests on, in words, for a run's report to print.

        A number nobody states is a number nobody checks, and `acted` is the
        check that decides whether a conversion has been proven in combat.

        **The band is not attributed to either side, and must not be.**  With
        no blow counted it is tempting to say the `HITS` and `MISSES` on it
        are the monsters', and today that would even be right, because
        `melee_turn` is the only tactic that lands one and it always answers
        `ATTACK`.  It would stop being right the day somebody writes an `AIM`
        tactic, and it would stop silently -- a sentence asserting more than
        the evidence carries, which is `#163` itself.  So it says what can be
        checked and no more.
        """
        said = (f"A party member struck on {self.blows} of {self.turns} "
                f"driven turns")
        if not self.blows and self.anybody_swung:
            said += ("; the HITS and MISSES on the message band cannot be "
                     "attributed to either side")
        return said


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
        incident in `docs/160-why-these-rules.md`, "The machine", generalised.
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

    def colours(self, row: int | None = None) -> bytes:
        """Colour RAM, whole screen or one row.

        `row` is not decoration: the command server's `colours 24` has asked
        for one row since it was written and this took no argument at all, so
        the command raised `TypeError` at every caller -- which is why the
        items command bar's highlight colour was never read (`#125`).
        """
        with self.mon(5) as m:
            all_of_it = bytes(c & 0x0F for c in m.read(0xD800, 1000))
        if row is None:
            return all_of_it
        return all_of_it[row * 40 : (row + 1) * 40]

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

    def select_row(self, label: str, timeout=30.0, column: int | None = None) -> bool:
        """Vertical menu: walk the white row onto *label*, then Return.

        Driven by where the highlight is, not by counting from an assumed
        start, because a swallowed keypress otherwise puts every later count
        out by one.

        **`column` is which column the list's names start in**, and on a
        screen with the map view drawn beside the list it is the difference
        between working and sending no keys at all (`#173`).
        `Screen.highlighted_rows()` with no column takes each row's *dominant*
        colour, and the map view to the left of the in-world roster outvotes
        the six white cells of the highlighted name -- so no row answers
        colour 1, every pass takes the `continue`, and the whole timeout goes
        by without a keypress.  From the outside that is indistinguishable
        from a list ignoring the keyboard, which is how it was read for
        several minutes.

        A caller that knows its list passes `column`.  One that does not gets
        it worked out here: when the dominant-colour scan finds nothing, the
        label's own column is tried, since the highlighted row is another
        entry in the same list and so starts where the label starts.  That
        runs **only** when the plain scan came up empty, so no screen this
        already drove is driven differently.

        And when neither finds a highlight, this says so rather than
        returning `False` off a silent timeout that looks exactly like a menu
        that ignored the keys.
        """
        deadline = time.time() + timeout
        seen_label = seen_highlight = False
        fell_back = False
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(0.3)
                continue
            hit = s.find(label)
            hot = s.highlighted_rows(column=column)
            if hit is not None and not hot and column is None:
                hot = s.highlighted_rows(column=hit[1])
                if hot and not fell_back:
                    fell_back = True
                    self.log(f"  No row is mostly white; reading the highlight "
                             f"in column {hit[1]}, where {label.upper()} starts")
            seen_label = seen_label or hit is not None
            seen_highlight = seen_highlight or bool(hot)
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
        if not seen_label:
            self.log(f"  {label.upper()} never appeared on the screen")
        elif not seen_highlight:
            self.log(f"  Found {label.upper()} but no highlighted row, so no "
                     f"key was sent; pass column= the one the names start in")
        else:
            self.log(f"  Could not walk the highlight onto {label.upper()}")
        return False

    def select_bar(self, label: str, row: int = 24, timeout=30.0) -> bool:
        """Horizontal command bar: the highlight is a run of cells, not a row.

        **The text and the highlight come from the same snapshot**, which is
        what `span_in` is for.  `Session.highlight_span` opens a second
        monitor connection and reads `$D800` again, so the two are readings
        from different moments -- and this walked the highlight by one of them
        towards a word found by the other.  Asked for `CAST` on the world's
        `MOVE VIEW CAST AREA ENCAMP SEARCH LOOK` it pressed Return on `VIEW`,
        twice, minutes apart, and returned `True` both times (`#173`).  It is
        the same fault `span_in` and `Session.combat_bar` were written to
        remove inside a fight, and it was believed not to show outside one.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(0.3)
                continue
            col = s.row(row).find(label.upper())
            span = span_in(s, row)
            if col < 0 or span is None:
                self.handle_prompt(s)   # a disk prompt can sit over any bar
                time.sleep(0.3)
                continue
            if span[0] == col:
                self.kbd.key("Return")
                return True
            self.kbd.key("Right" if span[0] < col else "Left")
        return False

    # -- the party panel, which is a menu ---------------------------------

    def party_rows(self, s=None) -> list[int]:
        """The screen rows the world panel lists a character on, in order.

        Read under the panel's own `NAME  AC HP` heading rather than at fixed
        rows, because the number of them is the party size and that is one of
        the things a driven run is checking (`#104`).
        """
        if s is None:
            s = self.screen()
        if s is None:
            return []
        head = None
        for r in PARTY_ROWS:
            if PARTY_HEADER in s.row(r)[PARTY_COLUMN:]:
                head = r
                break
        if head is None:
            return []
        # Everything left of where `AC` starts is the name field; a row with
        # nothing there is the panel's own frame rather than a character.
        width = s.row(head)[PARTY_COLUMN:].index(PARTY_HEADER)
        out = []
        for r in PARTY_ROWS:
            if r <= head:
                continue
            if s.row(r)[PARTY_COLUMN:PARTY_COLUMN + width].strip():
                out.append(r)
            elif out:
                break   # the list is contiguous; what follows it is not a name
        return out

    def party_highlight(self, s=None) -> int | None:
        """Which party slot the panel's highlight is on, or None.

        The heading is drawn in the highlight colour too, which is why this
        looks only at the rows `party_rows` found under it.
        """
        if s is None:
            s = self.screen()
        if s is None:
            return None
        rows = self.party_rows(s)
        for i, r in enumerate(rows):
            if s.colours[r * 40 + PARTY_COLUMN] == 1:
                return i
        return None

    def select_party(self, index: int, timeout: float = 25.0) -> bool:
        """Put the world panel's highlight on party slot *index*, 0 first.

        **This is the whole of how a driven run reaches a character other
        than the first one** (`#183`).  `VIEW` is not a list of names: it puts
        up the sheet of whoever the panel is highlighting, and the sheet's own
        bar is `VIEW:ITEMS EXIT` with nothing on it that changes character.
        So the selection happens before `VIEW`, on the world screen, and it is
        `Up` and `Down` that make it.

        Driven by where the highlight actually is after each press, the same
        way `select_row` is, so a swallowed keypress costs a pass round the
        loop rather than putting every later count out by one.
        """
        deadline = time.time() + timeout
        seen = False
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(0.3)
                continue
            rows = self.party_rows(s)
            at = self.party_highlight(s)
            if at is None:
                self.handle_prompt(s)   # a disk prompt can sit over the panel
                time.sleep(0.3)
                continue
            seen = True
            if not 0 <= index < len(rows):
                self.log(f"  the panel lists {len(rows)} characters, so there "
                         f"is no slot {index}")
                return False
            if at == index:
                return True
            self.kbd.key("Down" if at < index else "Up", 0.15, 0.30)
        if not seen:
            self.log("  no name in the party panel is highlighted, so no key "
                     "was sent; this is not the world screen")
        else:
            self.log(f"  could not walk the panel highlight onto slot {index}")
        return False

    def character_sheet(self, index: int | None = None,
                        timeout: float = 30.0,
                        shot: str | None = None) -> list[str] | None:
        """One character's `VIEW` sheet, verbatim, back at the world bar after.

        `index` is the party slot, 0 first; None reads whoever the panel is
        already highlighting.  `shot` is photographed while the sheet is still
        up, which is the only moment it can be -- this leaves the sheet before
        it returns, so a caller cannot take that picture itself.  Returns the
        sheet's non-blank rows, or None if it never came up.
        """
        if index is not None and not self.select_party(index):
            return None
        if not self.select_bar("VIEW", timeout=20):
            self.log("  VIEW could not be selected on the world bar")
            return None
        deadline = time.time() + timeout
        lines = None
        while time.time() < deadline:
            s = self.screen()
            # The name row fills in after the bar does, so wait for both --
            # a sheet read on the first screen that says `VIEW:ITEMS` comes
            # back half drawn.
            if s is not None and SHEET_BAR in s.row(24) and s.row(1).strip():
                time.sleep(0.6)
                s = self.screen()
                if s is not None:
                    lines = [line.rstrip() for line in s.rows() if line.strip()]
                    if shot:
                        self.kbd.screenshot(shot)
                    break
            time.sleep(0.3)
        if lines is None:
            self.log("  no character sheet came up after VIEW")
        self.leave_sheet()
        return lines

    def leave_sheet(self, tries: int = 3) -> bool:
        """`EXIT` off a character sheet, by name.

        Asked for by name and never by pressing Return at whatever happens to
        be highlighted: the sheet's bar starts on `ITEMS`, and `ITEMS` opens
        the item list that re-arms itself -- choosing its `EXIT` returns to
        the bar and the next `Return` drops straight back in
        (`docs/70-driving-the-game.md`).
        """
        for _ in range(tries):
            if self.select_bar("EXIT", timeout=8):
                time.sleep(1.0)
                return True
            self.leave_move(2)
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
        return self.wait_for_world(240)

    def wait_for_world(self, timeout: float = 240.0, interval: float = 0.35) -> bool:
        """Wait for the world's command bar, answering a continue prompt on
        the way.

        **An arrival can have a scene in front of it.**  Loading a Sokol Keep
        party draws the boat, prints `THE BOAT DISEMBARKS YOU AT SOKAL KEEP.`
        and puts up `PRESS <RETURN> OR BUTTON TO CONTINUE` -- and a wait that
        only watches for `ENCAMP` sits out its whole budget in front of a game
        that is waiting on the driver, not stuck.  New Phlan and the Slums
        hand control straight back with no scene, which is why this went
        unseen until an arrival that was neither of those two was driven
        (#182).

        Same shape as `outdoor_key`: read what row 24 actually says and act on
        it, rather than sitting for the one thing that was expected.
        `combat_state` and `BAR_PRESS` are reused rather than a second copy of
        the same classification, and the prompt is answered the way `fight`'s
        own `BAR_PRESS` branch already does -- `press_kernal`, because XTEST
        Return is not dependable at a prompt and the keyboard buffer is, and
        once per prompt via `await_change` rather than once per reading, since
        the prompt stays up about a second after the keystroke and answering
        it again on the next poll sends the Return on to whatever it gave way
        to.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(interval)
                continue
            if s.contains("ENCAMP"):
                return True
            state = self.combat_state(s)
            if state.kind == BAR_PRESS:
                self.press_kernal(0x0D)
                self.await_change(state.text,
                                  timeout=max(1.0, min(6.0, deadline - time.time())))
                continue
            self.handle_prompt(s)
            time.sleep(interval)
        return False

    # -- which of the two worlds ------------------------------------------

    def indoors(self) -> bool | None:
        """`$49E6`: True in a `GEO` area, False on the travel grid.

        None is "the read failed", not a world -- the same degradation
        `mode()` makes, and for the same reason: a caller that took a failed
        read for the travel grid would press compass digits at a dungeon.
        """
        try:
            with self.mon(5) as m:
                return m.read(INDOORS_AT, 1)[0] != 0
        except (OSError, MonitorError):
            return None

    def square(self) -> tuple[int, int] | None:
        """Where the party stands, out of memory, from whichever pair is live.

        `$49C0` indoors and `$49C3` on the travel grid.  Reading `$49C0`
        outdoors answers the square the party **left the grid on** -- the
        pier, in all three outdoor specimens -- and it never moves however far
        the party walks, so a driver watching it concludes every outdoor step
        was blocked (`#189`, `docs/141-dos-savegame.md`).
        """
        got = self.square_and_world()
        return None if got is None else (got[0], got[1])

    def square_and_world(self) -> tuple[int, int, bool] | None:
        """`square()`, plus the `$49E6` it had to read to choose the pair.

        One monitor block, so the square and the world it was chosen for
        cannot come from either side of a boundary crossing.  `position()`
        used to call `square()` and then `indoors()` separately, which is two
        reads of one fact -- the same shape `select_bar`'s docstring names as
        `#173`, where two `$D800` reads were treated as one snapshot.  Found
        in the code review of #189.
        """
        try:
            with self.mon(5) as m:
                inside = m.read(INDOORS_AT, 1)[0] != 0
                x, y = m.read(DUNGEON_XY if inside else TRAVEL_XY, 2)
        except (OSError, MonitorError):
            return None
        return x, y, inside

    def position(self) -> tuple[int, int, int | None]:
        """x, y, facing -- and **facing is None on the travel grid**.

        Read off the game's own status line, not out of memory.  The memory
        copy is real and it does end up on the disk, but it lags a move --
        reading it straight after a step gives the *previous* square, which
        silently turns a good step into a "blocked" one.  The status line
        (`E 16:48 5,2`) is correct the moment the screen settles.

        **Outdoors the status line lags too**, measured on 2026-09-02: after a
        step from (11,26) to (12,26), `$49C3`/`$49C4` read 12,26 and the line
        still read 11,26.  So out there the memory pair is the better source
        and `walk_outdoors` uses it directly; this stays screen-first because
        that is what every indoor caller wants.
        """
        for _ in range(12):
            s = self.screen()
            if s is not None:
                at = parse_status(s.text())
                if at is not None:
                    return at.x, at.y, at.facing
            time.sleep(0.3)
        here = self.square_and_world()   # fallback: the lagging memory copy
        if here is None:
            return 0, 0, None
        x, y, inside = here
        if not inside:
            return x, y, None
        with self.mon(5) as mon:
            return x, y, mon.read(DUNGEON_XY + 2, 1)[0]

    def walk(self, moves: str, hold=0.15, gap=0.30) -> None:
        """One move per character of `moves`.

        Indoors those are the game's own letters -- I forward, J left, K
        right, M about.  On the travel grid they are the compass digits `1`
        to `8`, because that is what the bar out there asks for; `walk_one`
        reads `$49E6` and works out which world it is in.
        """
        for ch in moves.upper():
            self.walk_one(ch, hold, gap)

    def walk_one(self, move: str, hold=0.15, gap=0.30, tries: int = 4) -> bool:
        """One move, verified -- by the status line indoors, by memory outdoors.

        Nothing here can be taken on trust.  Selecting `MOVE` succeeds against
        a **stale** row 24 -- the game does not always redraw the command bar
        after a room description -- and the first burst after a screen change
        is swallowed.  So the move is re-sent until the status line moves, and
        a move that never moves it is reported as blocked, which for a forward
        step is exactly the map fact worth having.

        **None of that paragraph is true on the travel grid**, which is why
        the world is asked for first.  Out there the bar takes compass digits
        rather than `I J K M`, a turn does not exist so nothing may be re-sent
        on the strength of an unchanged line, and the line itself lags the
        step.  `walk_outdoors` is that world's version of this.
        """
        if self.indoors() is False:
            return self.walk_outdoors(move, hold, gap)
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

    def walk_outdoors(self, move: str, hold=0.15, gap=0.30,
                      patience: float = 25.0) -> bool:
        """One compass step on the travel grid, verified in memory.

        **Pressed once, never re-sent.**  `walk_one` re-sends a move until the
        status line changes, and out here that line carries no facing, so a
        move it does not shift is indistinguishable from a turn -- which is
        how one key became four presses and walked the party in a circle.

        Verified by `$49C3`/`$49C4` rather than by the screen, because the
        status line lags a step out here and the memory pair does not.  Polled
        rather than slept: an overland step is hours of game time and can go
        to the disk, so a fixed wait measures this machine rather than the
        game.
        """
        if move not in COMPASS:
            self.log(f"  {move} is not a compass digit; the travel grid takes "
                     f"1-8, not the dungeon's I J K M")
            return False
        before = self.square()
        if before is None:
            self.log("  Could not read the travel square")
            return False
        if not self.outdoor_key(move, hold, gap):
            return False
        deadline = time.time() + patience
        after = before
        while time.time() < deadline:
            now = self.square()
            if now is not None and now != before:
                after = now
                break
            time.sleep(0.5)
        self.leave_outdoor_move()
        return after != before

    def outdoor_key(self, key: str, hold=0.15, gap=0.30,
                    timeout: float = 20.0) -> bool:
        """Press one compass digit, whichever bar the travel grid is showing.

        **A walked exit on to the grid lands with the movement prompt already
        up**: row 24 reads `1-8, RETURN OR BUTTON` straight away, so asking
        for `MOVE` finds no such word and spins to its timeout -- which from
        the outside looks exactly like an outdoor party that cannot move, and
        is how one run of this was read.  A warped arrival lands on the
        command bar and does need MOVE taking first.  So row 24 is read and
        whichever bar is there is answered.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.screen()
            row = "" if s is None else s.row(24)
            if OUTDOOR_PROMPT in row:
                self.kbd.key(key, hold, gap)
                return True
            if word_column(row, "MOVE") >= 0:
                if self.select_bar("MOVE", timeout=10):
                    time.sleep(0.6)
                    self.kbd.key(key, hold, gap)
                    return True
            self.handle_prompt(s)
            time.sleep(0.5)
        self.log(f"  Neither a 1-8 prompt nor MOVE on row 24 within "
                 f"{timeout:.0f}s")
        return False

    def leave_outdoor_move(self, tries: int = 4) -> bool:
        """Get off the travel grid's direction prompt, and only if it is up.

        Not `leave_move`, which presses Return before it looks: outdoors the
        prompt may already have given way to the command bar, and a Return
        there runs whichever command the highlight is sitting on rather than
        backing out of anything.
        """
        for _ in range(tries):
            s = self.screen()
            if s is not None and OUTDOOR_PROMPT not in s.row(24):
                return True
            self.kbd.key("Return", 0.20, 0.30)
            time.sleep(0.6)
        return False

    def status(self) -> Status | None:
        """The status line as a `Status`, or None if none was on screen.

        `facing` is None on the travel grid.  Callers that print it say
        "outdoors" rather than a number, and callers that compare two readings
        -- `walk_one` -- are comparing whole tuples and need no change.
        """
        for _ in range(8):
            s = self.screen()
            if s is not None:
                at = parse_status(s.text())
                if at is not None:
                    return at
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
        # `THERE IS STILL TREASURE LEFT` prints above this one, and the two
        # commands do what they say -- measured at a live bar on 2026-09-01,
        # pool slot 1, `PORSAVE13.D64`, after the Slums ambush was won:
        # `GO BACK` returns to `VIEW TAKE POOL SHARE EXIT` with the highlight
        # on `EXIT`, so it only loops back into the treasure, and `LEAVE
        # TREASURE` hands the party back to the world -- `$6E11` reads 1
        # within a second and the status line is back about ten seconds
        # later.  Until it was measured this bar matched no branch at all,
        # read as `BAR_MESSAGE`, and `fight()` idled at it for the whole of
        # whatever budget it had been given (`#171`).
        if word_column(up, "LEAVE") >= 0 and word_column(up, "TREASURE") >= 0:
            return CombatBar(BAR_LEAVE, bar)
        if word_column(up, "EXIT") >= 0:
            return CombatBar(BAR_EXIT, bar)
        if word_column(up, "YES") >= 0 and word_column(up, "NO") >= 0:
            return CombatBar(BAR_YESNO, bar)
        return CombatBar(BAR_BLANK if not bar else BAR_MESSAGE, bar)

    #: How long to give a blow to resolve before calling it refused.  Six
    #: seconds because a landed one showed inside 1.6 s on every press
    #: measured (`work/issue127/sweep1.jsonl`) and a refused one had not
    #: moved after ten (`work/issue127/probe1.jsonl`).
    ATTACK_TIMEOUT = 6.0

    #: Which bars `combat_bar` will walk the highlight along.  Not the move
    #: sub-bar: `MOVE LEFT = 9` is a prompt for a direction, not a menu, and
    #: sending Right there steps the character.
    SELECTABLE = (BAR_COMMAND, BAR_CONTINUE, BAR_YESNO, BAR_EXIT,
                  BAR_DONE, BAR_LEAVE)

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

    #: The commands on the sub-bar `DONE` opens that **finish with the
    #: character**, so the game asks somebody else next.  `GUARD` ends the
    #: turn and leaves the character guarding; `QUIT` ends it outright --
    #: Donald, who plays this game, on 2026-09-01: *"In Combat, QUIT ends the
    #: turn immediately."*  That is testimony rather than a screen read, and
    #: it is the whole evidence for QUIT here.
    ENDS_TURN = ("GUARD", "QUIT")

    #: The ones that only get off the bar.  **`DELAY` postpones a character
    #: rather than finishing with it**: it comes straight back to the front of
    #: the queue, and one character that could not strike took 50 of the 54
    #: turns of a fight that way while the other five never acted again
    #: (`#165`, `work/issue127/after1.jsonl`).  `EXIT` backs out to the same
    #: character's command bar, which is no better.  Both are last resorts for
    #: a bar carrying neither of the two above.
    LEAVES_BAR = ("DELAY", "EXIT")

    def end_turn(self) -> str:
        """Get off the sub-bar `DONE` opens, and end the turn if it can.

        **Take a command that finishes with the character before one that only
        gets off the bar.**  `GUARD` is not always offered -- some characters
        get `DELAY QUIT SPEED EXIT` with no GUARD on it at all -- and the
        driver used to fall to `DELAY` there, which postpones the character
        instead of ending its turn.  `QUIT` is on both shapes of the bar and
        ends the turn, so it is what a bar with no GUARD gets.

        **Ask only for a word that is on the bar.**  `combat_bar` has no way of
        saying "that command is not here": it waits for the label to appear and
        spins to its full timeout when it never does.  Trying the choices blind
        cost **441 of one 605-second fight's seconds -- 73% of it**.  GUARD was
        missing on 34 turns at 8 seconds each, and 10 more turns spent 24
        seconds apiece finding none of them, because `fight` also calls this at
        a bar that is not the sub-bar at all (`#127`,
        `work/issue127/diag1.jsonl`).  One read of row 24 first turns every one
        of those into a tenth of a second.
        """
        bar = self.combat_state().text
        for choice in self.ENDS_TURN + self.LEAVES_BAR:
            if word_column(bar, choice) < 0:
                continue
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

    def await_change(self, was: str, timeout: float = 6.0,
                     interval: float = 0.4) -> CombatBar:
        """Read row 24 until its text is no longer `was`, then give up.

        The prompt a keystroke answers stays on screen for about a second
        after the keystroke has been taken, and `fight`'s loop comes back
        round in a fraction of that -- so a branch that acts on every reading
        acts several times, and the extra ones land on whatever the prompt
        gave way to.

        Returns whatever row 24 says at the end, changed or not: a prompt
        that has not moved after `timeout` is one the caller should answer
        again, which is the retry the rest of this file already insists on.
        """
        deadline = time.time() + timeout
        while True:
            state = self.combat_state()
            if state.text != was:
                return state
            if time.time() >= deadline:
                return state
            time.sleep(interval)

    def await_step(self, index, was, before, tries: int = 6,
                   interval: float = 0.4):
        """Wait for one combat step to show.  Returns `(moved, bar)`.

        `bar` is None once the move sub-bar has gone, which is how a turn
        ends.  Two signals, because either is enough and neither is good on
        its own: row 24's count lags the keypress, and the position table is
        the authority on where a character actually stands.

        **Neither is read once.**  A single read 20 milliseconds after the key
        says the game has not caught up yet, not that the step failed -- and
        `melee_turn` concluded the latter on 27 of 27 turns of one fight,
        passing 26 of them (`#127`).
        """
        for _ in range(max(1, tries)):
            bar = self.combat_state()
            if bar.kind in AFTER_MOVE:
                return True, None
            if before is not None and bar.moves_left is not None \
                    and bar.moves_left != before:
                return True, bar
            b = self.battle()
            me = None if b is None else next(
                (c for c in b.combatants if c.index == index), None)
            if me is not None and (me.x, me.y) != was:
                return True, bar
            time.sleep(interval)
        return False, self.combat_state()

    @staticmethod
    def step_towards(battle, me, target, avoid=()) -> str | None:
        """The first step of the shortest walkable path to the target.

        A breadth-first walk outwards from the target over squares that can
        actually be stood on, which is the whole reason this is not the
        obvious "pick the neighbour that gets closest" (`#170`).  Greedy
        picked the closest square without ever asking `battle.square(x, y)`,
        so it aimed a character at rock: from `(19,13)` at an orc on
        `(25,13)`, with the arena's own block at x 20-22, it pressed `KP_6`
        into `(20,13)` and spent the turn on a key that cannot work.
        **Impassable terrain is confirmed in the running game**, not inferred
        from the renderer -- in the `#127` key sweep a press into a code-1
        square moved nobody and spent no movement.

        What counts as blocked:

        * any square whose terrain code is nonzero -- rock;
        * any square a combatant is standing on, **except** the target's own,
          because stepping onto that is the blow.  That includes other
          enemies: walking into one attacks it rather than the character this
          turn is aimed at.

        The character's own square is never blocked, so a path can start.

        `avoid` is the keys already tried this turn that spent no square -- a
        wall, or something else neither the terrain nor the position table
        shows.  Without it a character pinned against one burns its whole turn
        on the same press.

        The second half of `#170` falls out of the same change: greedy passed
        the turn whenever no neighbour got closer, even when a step sideways
        would round the obstruction next turn.  Breadth-first walks round it
        now, and `None` means what it says -- there is no path at all, or
        every first step on one is in `avoid`.
        """
        shape = battle.shape
        start = (me.x, me.y)
        goal = (target.x, target.y)
        if goal == start or not shape.holds(*start):
            return None

        blocked = {(x, y)
                   for y in range(shape.height) for x in range(shape.width)
                   if battle.square(x, y)}
        for c in battle.combatants:
            if not shape.holds(c.x, c.y):
                continue
            if (c.x, c.y) in (start, goal):
                continue
            blocked.add((c.x, c.y))

        # Outwards from the target, so every square learns its distance to it
        # in one sweep and the first step is a lookup rather than a search.
        dist = {goal: 0}
        frontier = [goal]
        while frontier:
            nxt = []
            for at in frontier:
                for dx, dy in STEP_KEYS:
                    sq = (at[0] + dx, at[1] + dy)
                    if sq in dist or not shape.holds(*sq) or sq in blocked:
                        continue
                    dist[sq] = dist[at] + 1
                    nxt.append(sq)
            frontier = nxt

        here = dist.get(start)
        best = None
        for (dx, dy), key in STEP_KEYS.items():
            if key in avoid:
                continue
            sq = (me.x + dx, me.y + dy)
            if not shape.holds(*sq) or sq in blocked:
                continue
            d = dist.get(sq)
            if d is None:
                continue
            # Ties on path length go to the square that is physically nearest,
            # which keeps the open-arena answers the greedy ones.
            score = (d, max(abs(target.x - sq[0]), abs(target.y - sq[1])))
            if best is None or score < best[0]:
                best = (score, key)
        if best is None:
            return None
        if here is not None and best[0][0] >= here:
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
            delta = next(d for d, k in STEP_KEYS.items() if k == key)
            into = b.at(me.x + delta[0], me.y + delta[1])
            before = moving.moves_left
            was = (me.x, me.y)
            self.kbd.key(key, 0.15, 0.30)
            if into is not None and not into.is_party:
                # **The blow, and it is not a step.**  An attack spends no
                # movement and does not move the character, so neither the
                # count on row 24 nor the position table says it happened --
                # measured at a live sub-bar, ROLAND at (29,13) against an orc
                # on (28,14): `MOVE LEFT` 9 before and 9 after, nobody moved,
                # and the orc went from 5 hit points to 1
                # (`work/issue127/sweep1.jsonl`, turn 15).
                #
                # Treating that as "the step cost nothing, so it did not
                # happen" is what put the attack key in `avoid` on every turn
                # of every fight, and passed 26 of 27 turns with the party
                # standing next to the orcs (`#127`).  So: press it, and wait
                # for the turn to move on rather than for a square to be
                # spent.
                if self.await_bar(AFTER_MOVE, self.ATTACK_TIMEOUT) is not None:
                    # The one place in this file that knows a party member
                    # struck.  `fight` counts it and `FightResult.acted` is
                    # that count -- see `ATTACK` at the top of the file.
                    return ATTACK
                # Still on the sub-bar six seconds later, so the blow was
                # refused rather than struck.  Seen for a character with a
                # **missile weapon readied** -- MALCYON with 13 DART, six
                # presses watched for ten seconds apiece, no message, no
                # damage, nothing (`work/issue127/probe1.jsonl`).  Pass the
                # turn; do not stand there pressing it again.
                self.press_kernal(0x0D)
                return self.combat_turn()
            moved, moving = self.await_step(index, was, before)
            if moving is None:
                return "MOVE"                   # spent, or dead
            if not moved:
                # A wall, and the count says so: a step into impassable
                # terrain spends nothing and moves nobody -- LADY KATHERINE
                # at (29,11) north-east into terrain code 1, `MOVE LEFT` 5
                # and 5 (`work/issue127/sweep1.jsonl`, turn 5).  Try another.
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
        highlights: list[str] = []
        lines: list[str] = []
        seen: set[str] = set()
        turns = 0
        blows = 0
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
            # `parse_status`, not `RE_STATUS`: an ambush on the travel grid
            # ends back on `OUTDOORS 22:02 7,28`, which carries no facing
            # letter, so a pattern that wants one never matches and the fight
            # runs to its whole budget after it is over (`#189`).
            if mode == DUNGEON and parse_status(text) is not None:
                return FightResult(outcome or ENDED, turns,
                                   time.time() - started, bars, lines,
                                   blows, highlights)
            state = self.combat_state(s)
            if state.text and (not bars or bars[-1] != state.text):
                bars.append(state.text)
                # The highlight from the **same** snapshot as the text, so a
                # log can say not only which bar the driver was looking at
                # but which command it was looking at on it.
                span = None if s is None else span_in(s, 24)
                highlights.append("-" if span is None
                                  else s.row(24)[span[0]:span[1] + 1].strip())
            if state.kind == BAR_CONTINUE:
                # The game offering a withdrawal is how a driven fight ends.
                self.combat_bar("NO", timeout=min(12.0, left()))
            elif state.kind == BAR_DONE:
                self.end_turn()      # left open by a turn that did not finish
            elif state.kind == BAR_EXIT:
                self.combat_bar("EXIT", timeout=min(12.0, left()))
            elif state.kind == BAR_LEAVE:
                # `GO BACK LEAVE TREASURE`, and `GO BACK` -- which is the
                # command the highlight starts on -- only returns to the
                # treasure bar this came from.  `LEAVE TREASURE` is the way
                # out to the world.
                self.combat_bar("LEAVE", timeout=min(12.0, left()))
            elif state.kind == BAR_PRESS:
                # XTEST Return is not dependable at a prompt; the buffer is.
                self.press_kernal(0x0D)
                # And **once per prompt, not once per reading**.  The prompt
                # stays up for about a second after the keystroke is taken
                # and this loop comes round in a fraction of that, so
                # injecting on every reading sends several Returns and the
                # spare ones land on whatever the prompt gave way to.  After
                # a won fight that is the treasure bar, whose highlight
                # starts on `VIEW`, and `VIEW` opens the item list -- the
                # trap `docs/70-driving-the-game.md` already records as one
                # that re-arms itself (`#171`).
                #
                # A prompt with a second page of message behind it draws the
                # same row 24 again, so this waits out its timeout and the
                # loop answers it on the next pass.  That costs seconds; the
                # spare Return cost a whole budget.
                self.await_change(state.text, timeout=min(6.0, left()))
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
                # The tactic's own answer, which is the only thing in this
                # loop that knows whether the *party* struck.  Every other
                # signal a fight offers -- the message band, the mode byte,
                # row 24 -- says a blow was struck without saying by whom.
                if act(self, state) == ATTACK:
                    blows += 1
            else:
                self.idle(poll)              # a monster's turn, or a redraw
            self.handle_prompt()
        return FightResult(outcome or BUDGET, turns, time.time() - started,
                           bars, lines, blows, highlights)


# -- claiming a slot, and putting the player's disks in it ------------------


def claim_slot(want: int | None = None, note: str = ""):
    """A pool slot, or the specific one a brief named.

    `instance.claim` is first-free and has no way to ask for slot *n*, so
    getting a named slot means holding the ones before it and letting them go
    again.  Nothing is ever killed to make room: a slot whose lease is held
    belongs to somebody.

    This lived in `tools/fightrun.py` and is here because every tool that
    drives a session needs it, and the second copy of it would be the third
    in this directory.
    """
    if want is None:
        return instance.claim(game="por", note=note)
    holds, slot = [], None
    try:
        while True:
            s = instance.claim(game="por", note=note)
            if s.n == want:
                slot = s
                break
            holds.append(s)
            if s.n > want:
                break
    finally:
        # `instance.claim` raises when the pool is full, and it can do so
        # part way through -- so releasing has to happen on the way out
        # rather than after the loop.  Process exit would drop the locks
        # anyway; a slot held until then is a slot another agent is told
        # is busy, for as long as it takes this one to die.
        for h in holds:
            h.release()
    if slot is None:
        raise RuntimeError(f"slot {want} is not free")
    return slot


def stage_disks(slot, disks, save: str = "") -> str:
    """Copy the eight sides and a save into the slot, and say what to boot.

    **The player's disks are read and never written.**  `Session.attach`
    refuses any path outside the slot's own directory, so everything the game
    is ever shown is one of these copies: `SIDE1.D64` to `SIDE8.D64`, and the
    save as `SIDE0.D64`, which is what `Session.save_disk` points at.
    """
    import shutil

    slot.seed_vicerc()
    here = pathlib.Path(slot.dir)
    disks = pathlib.Path(disks)
    for i in range(1, 9):
        src = disks / f"POOL{i}.D64"
        if src.exists():
            shutil.copy(src, here / f"SIDE{i}.D64")
    if save:
        shutil.copy(disks / save, here / "SIDE0.D64")
    return str(here / "SIDE1.D64")


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
    elif cmd == "melee":
        # The same fight, driven to *strike* rather than to pass every turn.
        # `fight`'s default tactic guards with DONE, which wins nothing and
        # cannot answer whether the party can fight at all.
        print(sess.fight(float(args[0]) if args else 300.0,
                         tactic=lambda s, state: s.melee_turn(state)))
    elif cmd == "load":
        print(sess.load_save())
    elif cmd == "begin":
        print(sess.begin_adventuring())
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
    #
    # `--pool N` demands slot *N*, which is what a brief names; `--disks DIR`
    # and `--save NAME` copy the player's disks into the slot first, so the
    # session comes up ready to load a save rather than needing a `work/drive`
    # laid out by hand.
    argv = sys.argv[1:]
    slot = None
    if argv and argv[0] == "--pool":
        argv = argv[1:]
        want = None
        if argv and argv[0].isdigit():
            want, argv = int(argv[0]), argv[1:]
        slot = claim_slot(want, note=os.environ.get("POR_AGENT", ""))
        slot.seed_vicerc()
        print(f"slot {slot.n}: monitor {slot.port} text {slot.text_port} "
              f"cmd {slot.cmd_port} display {slot.display} dir {slot.dir}",
              flush=True)
    disks = save = ""
    while len(argv) > 1 and argv[0] in ("--disks", "--save"):
        if argv[0] == "--disks":
            disks = argv[1]
        else:
            save = argv[1]
        argv = argv[2:]
    if disks:
        assert slot is not None, "--disks needs --pool: nothing stages work/drive"
        argv = [stage_disks(slot, disks, save)] + list(argv)
    sess = Session(argv[0] if argv else None, slot=slot)
    if len(argv) > 1:
        sess.save_disk = os.path.abspath(argv[1])
    if not sess.boot():
        print("boot failed")
    serve(sess)

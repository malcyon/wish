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


class Session:
    """One driven game.

    With no `slot` this is what it always was: `work/drive/`, ports 6502, 6510
    and 6600, display `:7` -- the human's numbers, kept so `tools/walkrun.py`
    and `tools/porcmd` need no change.  Pass a `tools.instance.Slot` and every
    one of those six becomes that slot's own, which is the whole of what makes
    two sessions able to run at once.
    """

    def __init__(self, disk: str | None = None, display: str | None = None,
                 slot=None):
        self.slot = slot
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
        self.kbd.key("y", 0.15, 0.28)
        self.log("fastloader: Y")
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

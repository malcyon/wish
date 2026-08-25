#!/usr/bin/env python3
"""The DOS debugger harness: a DOSBox-X that can be halted, read and written.

`tools/dosbox.py` drives the *game* -- keystrokes in, screen digests and save
files out -- and until now that was the whole of the DOS side.  Every DOS
finding so far was a save-file differential because there was no instrument
that could look inside a running one.  DOSBox-X built `--enable-debug=heavy`
has a debugger, and this module is what makes it usable from a script:

* **in** is a line on a pty, because the debugger is an ncurses program with no
  socket and no command file, and it reads the process's own terminal;
* **out** is `[log] logfile=`, because every message the debugger prints goes
  through `DEBUG_ShowMsg`, which writes to that file unbuffered.  **Nothing
  here is read off the screen**;
* **memory** comes back as `MEMDUMP.BIN` in the working directory.

`docs/142-dosbox-x-debugger.md` is the finding.  Its worked example -- locate a
save's ECL variable array in a memory dump, watch the clock's minute byte, catch
the tick -- is `main()`'s `clock` command, so the document's result and this
module's behaviour cannot drift apart without a run saying so.

**Four traps are encoded here rather than left in the document**, because each
one cost an hour and none of them announces itself:

1. `MEMDUMPBIN` wraps the offset at 64K (`GetAddress` is `seg*16 + (ofs &
   0xFFFF)`), so asking for a megabyte gives you the same 64K sixteen times at
   the full file size.  `read()` splits every request at the wrap.
2. A fresh `BPM` remembers the value `00`, so unless the byte really is zero its
   first hit is spurious and arrives the instant you `RUN`.  `watch()` reads the
   byte first and absorbs the hit only when there will be one.
3. **A code breakpoint firing prints nothing.**  `halted()` probes with `EV IP`,
   which answers only while the emulator is stopped -- input typed while it runs
   is discarded.
4. Commands are truncated at `MAXCMDLEN` = 254 characters with no complaint, so
   a long `SM` would write part of its bytes and report success.  `write()`
   chunks, and `dbg()` refuses to send a line that would be cut.

**The Wayland trap is the one that matters to a human.**  DOSBox-X asks for a
working directory with a `zenity` chooser when it has no configured one, GTK
prefers `WAYLAND_DISPLAY` over `DISPLAY`, and this desktop is Wayland -- so a
correctly set `DISPLAY=:40` was ignored once and the dialog opened over the
user's editor.  `debug_env()` unsets it, and the config sets a working directory
so nothing is ever asked.  Both belts, every launch.

Displays :40-:47 are this pool's; `tools/dosbox.py` has :30-:37 and VICE has
:10-:17, so the three never collide.  Teardown kills the process groups this
instance started and nothing else: **never a process by name.**

Run time it needs: `dosbox-x` *with the debugger* (`dosbox-x --help | grep -c
helpdebug` is 1, not 0), `Xvfb`, `xdotool` and ImageMagick's `import`.
Everything skips cleanly when they are absent.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

try:  # POSIX only; the pure functions below still import on Windows, and CI
    import fcntl  # runs the suite there.
    import pty
    import termios
except ImportError:  # pragma: no cover - Windows
    fcntl = pty = termios = None

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import dosbox  # noqa: E402

#: This pool's instances live beside `tools/dosbox.py`'s, one directory down,
#: so the two lease files can never be the same file.
WORK = dosbox.WORK / "x"
INST = WORK / "inst"

#: :30-:37 are `tools/dosbox.py`'s and :10-:17 are the VICE pool's.
DISPLAY_BASE = 40
SLOTS = 8

DOSBOXX = os.environ.get("DOSBOXX") or shutil.which("dosbox-x") or "/usr/local/bin/dosbox-x"

#: `MAXCMDLEN` in `src/debug/debug.cpp`.  A longer line is silently cut.
MAX_CMD = 254

#: One real-mode segment.  `GetAddress()` masks the offset to 16 bits, which is
#: the whole reason `read()` has to chunk.
SEGMENT = 0x10000

#: What `regs()` asks for when it is not told.  Every name here is one
#: `GetHexValue` recognises.
REGS = ("AX", "BX", "CX", "DX", "SI", "DI", "BP", "SP",
        "CS", "DS", "ES", "SS", "IP", "FLAGS")

# `DEBUG: Memory breakpoint : 39AC:000E - 06 -> 07`.  The empty `%s` before the
# colon is where `(Prot)` goes for a protected-mode watchpoint.
RE_BPM = re.compile(
    r"Memory breakpoint\s*(\(Prot\))?\s*:\s*([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})"
    r"\s*-\s*([0-9A-Fa-f]{2})\s*->\s*([0-9A-Fa-f]{2})"
)
RE_EV = re.compile(r"EV of '([^']*)' is:\n(.*)")


class DebuggerUnavailable(RuntimeError):
    """`dosbox-x` is missing, or is a build with no debugger in it."""


class NotHalted(RuntimeError):
    """The command went nowhere: the debugger reads input only while stopped."""


class BlankCapture(RuntimeError):
    """A capture came back a single colour, so it is showing nothing."""


# --------------------------------------------------------------------------
# What is installed
# --------------------------------------------------------------------------


def missing_tools() -> list[str]:
    """Every run-time tool this harness needs and does not have.

    It includes `tools/dosbox.py`'s list, plain DOSBox 0.74 among them, because
    `XSession` is that module's `Session` with the launch replaced and inherits
    its `require_tools()` check.  This harness never runs 0.74; it is listed so
    a machine that lacks it is told so up front rather than at `boot()`.
    """
    absent = list(dosbox.missing_tools())
    if not Path(DOSBOXX).is_file() and shutil.which(DOSBOXX) is None:
        absent.insert(0, "dosbox-x")
    return absent


@functools.lru_cache(maxsize=4)
def has_debugger(path: str = DOSBOXX) -> bool:
    """Whether that `dosbox-x` was built with the debugger.

    The one-line test from `docs/142`: a debugger build prints a `helpdebug`
    line for `--help` and a packaged build does not.  Ubuntu's and Flathub's
    both do not, so "dosbox-x is installed" is not the question to ask.
    """
    try:
        out = subprocess.run(
            [path, "--help"], capture_output=True, timeout=30,
            env=debug_env(display=None),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return b"helpdebug" in out.stdout + out.stderr


def require_debugger() -> None:
    absent = missing_tools()
    if absent:
        raise DebuggerUnavailable("not installed: " + ", ".join(absent))
    if not has_debugger(DOSBOXX):
        raise DebuggerUnavailable(
            f"{DOSBOXX} has no debugger; it needs --enable-debug=heavy"
        )


def unavailable() -> str | None:
    """A one-line reason this cannot run here, or None.  How tests skip."""
    try:
        require_debugger()
    except DebuggerUnavailable as e:
        return str(e)
    return None


# --------------------------------------------------------------------------
# Addresses
# --------------------------------------------------------------------------


def linear(addr: int | tuple[int, int]) -> int:
    """A linear address from either a linear one or a `(segment, offset)`.

    Real mode, and the offset wraps at 64K exactly as `GetAddress()` does, so
    `(0x1000, 0x1_0004)` is `0x10004` and not `0x20004`.
    """
    if isinstance(addr, tuple):
        seg, ofs = addr
        return (seg << 4) + (ofs & 0xFFFF)
    return addr


def seg_off(lin: int) -> tuple[int, int]:
    """`(segment, offset)` for a linear address, with the offset kept tiny.

    `(L >> 4, L & 0xF)` is the safest split: the offset starts at most 15 bytes
    into the segment, so the largest read that does not wrap is nearly the whole
    64K, and no address under 1 MB needs a segment that does not exist.
    """
    return lin >> 4, lin & 0xF


def chunks(lin: int, n: int) -> list[tuple[int, int, int]]:
    """`(segment, offset, length)` calls that read `n` bytes from `lin`.

    Each one stops at the 64K wrap, which is what `MEMDUMPBIN` will not do for
    itself: ask it for `100000` and it hands back the same 64K sixteen times,
    at the full million bytes, with nothing in the log to say so.
    """
    if n < 0:
        raise ValueError(f"negative length {n}")
    out: list[tuple[int, int, int]] = []
    got = 0
    while got < n:
        seg, ofs = seg_off(lin + got)
        take = min(n - got, SEGMENT - ofs)
        out.append((seg, ofs, take))
        got += take
    return out


# --------------------------------------------------------------------------
# Reading the log
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Break:
    """One `Memory breakpoint` line: where it was, and what changed."""

    seg: int
    ofs: int
    old: int
    new: int
    prot: bool = False

    @property
    def addr(self) -> int:
        return linear((self.seg, self.ofs))


def parse_breaks(text: str) -> list[Break]:
    """Every memory-breakpoint hit in a slice of the log, oldest first."""
    return [
        Break(int(s, 16), int(o, 16), int(a, 16), int(b, 16), prot=bool(p))
        for p, s, o, a, b in RE_BPM.findall(text)
    ]


def parse_ev(text: str) -> dict[str, int]:
    """The values from the last `EV` reply in a slice of the log.

    The reply names its own expressions -- `EV of 'CS IP' is:` then `2f69 462`
    -- so the caller does not have to remember what it asked for.  Values are
    lowercase hex on one line.  Empty when nothing answered, which is what
    "the emulator is running" looks like from here.
    """
    m = None
    for m in RE_EV.finditer(text):
        pass
    if m is None:
        return {}
    names = m.group(1).split()
    values = m.group(2).split()
    if "parse error" in m.group(2):
        raise ValueError(f"the debugger could not parse {m.group(1)!r}")
    return {n: int(v, 16) for n, v in zip(names, values)}


def locate(image: bytes, needle: bytes, window: int = 12, stride: int = 2):
    """Where `needle` sits in `image`, by majority vote of small windows.

    This is how a live address is found with no symbol table: dump memory,
    then match a file the player already holds -- a save's ECL variable array,
    say -- against it.  A single `find` is no good, because a live array is
    never byte-identical to the file that came from it; a vote over many
    windows tolerates the bytes that moved.  Windows that are mostly zeros are
    skipped, since they match everywhere.

    Returns `(base, votes, matching)`: the linear offset into `image`, how many
    windows agreed, and how many of `len(needle)` bytes are equal there.  None
    when nothing voted.
    """
    from collections import Counter

    votes: Counter[int] = Counter()
    for i in range(0, max(0, len(needle) - window), stride):
        w = needle[i:i + window]
        if w.count(0) > window * 2 // 3:
            continue
        j = image.find(w)
        while j >= 0:
            if j - i >= 0:
                votes[j - i] += 1
            j = image.find(w, j + 1)
    if not votes:
        return None
    base, n = votes.most_common(1)[0]
    same = sum(1 for a, b in zip(image[base:base + len(needle)], needle) if a == b)
    return base, n, same


# --------------------------------------------------------------------------
# The instance lease
# --------------------------------------------------------------------------


@dataclass
class Slot(dosbox.Slot):
    """`tools/dosbox.py`'s lease on this pool's own displays and directories."""

    @property
    def display(self) -> str:
        return f":{DISPLAY_BASE + self.n}"


def claim(note: str = "") -> Slot:
    """Lease the first free DOSBox-X slot, or raise `dosbox.PoolFull`.

    The lease is an `fcntl.flock` this process holds; the kernel drops it
    however the process dies, so there is no stale-lock policy to get wrong.
    """
    if fcntl is None:
        raise dosbox.PoolFull("the DOSBox-X harness needs flock, so it is POSIX only")
    INST.mkdir(parents=True, exist_ok=True)
    for n in range(SLOTS):
        d = INST / str(n)
        d.mkdir(exist_ok=True)
        fd = os.open(d / "lease", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            continue
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps(
            {"slot": n, "pid": os.getpid(), "note": note, "at": time.time()}
        ).encode())
        return Slot(n=n, dir=d, _fd=fd)
    raise dosbox.PoolFull(f"all {SLOTS} DOSBox-X slots are leased")


# --------------------------------------------------------------------------
# The launch
# --------------------------------------------------------------------------

#: `tools/dosbox.py`'s config, plus the four sections that make a debugger
#: reachable and keep every dialog off the user's desktop.  `core=normal`
#: because heavy debugging checks every instruction against every memory
#: breakpoint and the dynamic core does not.
CONFIG = """\
[sdl]
fullscreen=false
output=surface
autolock=false
usescancodes=true
waitonerror=false
mapperfile={dir}/mapper.map

[dosbox]
machine=vga
captures={dir}/capture
memsize=16
working directory option=custom
working directory default={dir}
title={title}

[log]
logfile={dir}/dbg.log
debuggerrun=debugger

[render]
frameskip=0
aspect=false
scaler=none

[cpu]
core=normal
cputype=auto
cycles=fixed {cycles}

[mixer]
nosound=true

[sblaster]
sbtype=none

[gus]
gus=false

[speaker]
pcspeaker=false

[joystick]
joysticktype=none

[autoexec]
mount c {dir}/game
c:
cd {stem}
{exe}
"""

#: The window name the config sets, and what `xdotool search` looks for.  Not
#: "DOSBox": that would also find `tools/dosbox.py`'s window on a shared display.
TITLE = "wishdbg"


def debug_env(display: str | None, **extra: str) -> dict[str, str]:
    """The environment every DOSBox-X invocation gets.  Do not build your own.

    `DISPLAY=:40` is not enough on a Wayland desktop.  GTK and Qt children --
    the `zenity` folder chooser above all -- prefer `WAYLAND_DISPLAY`, and one
    of them drew on the user's real screen before this function existed.
    Unsetting it, `XDG_SESSION_TYPE` and `XAUTHORITY` is what actually confines
    the process; `GDK_BACKEND=x11` and `QT_QPA_PLATFORM=offscreen` are belts.

    `TERM` is load-bearing too: ncurses decodes function keys through terminfo,
    so the debugger sees F10 and F11 only if `TERM` names the terminal whose
    sequences `step()` sends.
    """
    env = dict(os.environ)
    for v in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "XAUTHORITY"):
        env.pop(v, None)
    env.update(
        GDK_BACKEND="x11",
        QT_QPA_PLATFORM="offscreen",
        SDL_AUDIODRIVER="dummy",
        TERM="xterm",
    )
    if display:
        env["DISPLAY"] = display
    else:
        env.pop("DISPLAY", None)
    env.update(extra)
    return env


# --------------------------------------------------------------------------
# Which window is ours
# --------------------------------------------------------------------------


def uniform_colour(screen: dosbox.Screen | None) -> tuple[int, int, int] | None:
    """The single colour a capture is made of, or None if it has two.

    A capture of the wrong window is not an error -- `import` takes it happily
    and returns one flat colour -- so nothing downstream notices.  `settle()`
    calls two identical black frames a finished screen, every `wait_for` on it
    times out, and `load_game` reports a save that loaded perfectly as never
    having loaded.  One colour is the signature, and refusing it by name is
    what stops that reading as "the game did nothing".
    """
    if screen is None:
        return None
    px = screen.px
    if len(px) < 6:
        return None
    first = px[:3]
    whole = len(px) - len(px) % 3
    if px[:whole] != first * (whole // 3):
        return None
    return (first[0], first[1], first[2])


def candidate_windows(ids: list[str], pids: dict[str, int | None],
                      pid: int) -> list[str]:
    """The windows in `ids` that process `pid` could plausibly own, best first.

    Two DOSBox-X processes on one display leave two top-level windows with the
    same title, the same 640x400+80+100 geometry and the same `IsViewable` map
    state; nothing about the windows themselves separates them, and only one
    has pixels in it.  `_NET_WM_PID` does separate them, and SDL2 sets it, so a
    window that names another process is dropped outright.  Windows naming no
    process at all are kept as a fallback, for a build whose SDL does not set
    the property -- there the caller still has to choose by content.
    """
    mine = [w for w in ids if pids.get(w) == pid]
    return mine or [w for w in ids if pids.get(w) is None]


def server_on(display: str) -> bool:
    """Whether an X server is listening on that display, by its own socket.

    Not by running `xdotool`: it exits 1 both for "no windows matched" and for
    "Can't open display", so the readiness loop that tested its status was
    satisfied by a display that did not exist.  Connecting to
    `/tmp/.X11-unix/X<n>` cannot be read two ways -- a socket left behind by a
    dead server refuses the connection.

    Asked before `Xvfb` is started as well as after.  A second `Xvfb` on a busy
    display does exit with "Server is already active", but it takes a moment,
    and by then the session has already gone on to launch DOSBox-X against the
    server that was already there.  Two DOSBox-X windows with the same title is
    what that looks like afterwards.
    """
    n = display.lstrip(":").split(".")[0]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(1.0)
        sock.connect(f"/tmp/.X11-unix/X{n}")
        return True
    except OSError:
        return False
    finally:
        sock.close()


def window_pid(wid: str, env: dict[str, str]) -> int | None:
    """`_NET_WM_PID` of a window, or None where it carries none."""
    out = subprocess.run(["xdotool", "getwindowpid", wid],
                         env=env, capture_output=True).stdout.strip()
    return int(out) if out.isdigit() else None


class XSession(dosbox.Session):
    """A booted DOSBox-X with the debugger on a pty.

    Everything `tools/dosbox.py`'s `Session` does still works -- `capture()`,
    `settle()`, the staged game tree, the save files -- and `PoolOfRadiance`
    drives this class unchanged, which is what gets a run to a loaded save
    before the debugger has anything worth looking at.

    Use it as a context manager.  `close()` kills the two process groups this
    instance started and nothing else.
    """

    def __init__(self, slot: Slot, game: Path, exe: str = "START.EXE",
                 cycles: int = 30000, geometry: str = "800x600x24"):
        require_debugger()
        super().__init__(slot, game, exe=exe, cycles=cycles, geometry=geometry)
        self.log = self.dir / "dbg.log"
        self.master = -1
        self._pty: bytearray = bytearray()
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()

    # -- staging ---------------------------------------------------------

    def stage(self, fresh: bool = True) -> None:
        super().stage(fresh=fresh)
        (self.dir / "dosbox.conf").write_text(CONFIG.format(
            dir=self.dir, stem=self.stem, exe=self.exe,
            cycles=self.cycles, title=TITLE,
        ))

    # -- lifecycle -------------------------------------------------------

    def boot(self, timeout: float = 120.0, fresh: bool = True) -> None:
        """Stage the game, start Xvfb, and start DOSBox-X on a pty.

        The pty is the whole trick.  **The debugger only exists if DOSBox-X was
        started from a terminal** -- on Linux it draws in the terminal that
        launched the process, so a session with no controlling tty has no
        debugger at all -- and `pty.openpty()` is a terminal for this purpose
        as long as it is given a size, because ncurses draws nothing in a 0x0.

        The window is chosen by `_NET_WM_PID` and then proved to have pixels
        in it, because a display that another run's DOSBox-X is still holding
        carries two windows with this one's title and only one of them draws.
        """
        self.stage(fresh=fresh)
        env = debug_env(self.display)
        if server_on(self.display):
            raise RuntimeError(
                f"{self.display} already has an X server on it, so this "
                f"session would share it.  A DOSBox-X or Xvfb from an earlier "
                f"run is still holding the display -- two DOSBox-X windows "
                f"with the same title, and `import` returns solid black for "
                f"whichever is underneath.  Kill that run's process group."
            )

        self.xvfb = subprocess.Popen(
            ["Xvfb", self.display, "-screen", "0", self.geometry, "-nolisten", "tcp"],
            stdout=(self.dir / "xvfb.log").open("wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if server_on(self.display):
                break
            if self.xvfb.poll() is not None:
                why = (self.dir / "xvfb.log").read_text(errors="replace").strip()
                self.close()
                raise RuntimeError(
                    f"Xvfb exited without serving {self.display}: "
                    f"{why.splitlines()[-1] if why else 'no output'}"
                )
            time.sleep(0.2)
        else:
            self.close()
            raise TimeoutError(f"Xvfb never came up on {self.display}")

        self.log.unlink(missing_ok=True)
        (self.dir / "MEMDUMP.BIN").unlink(missing_ok=True)
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 160, 0, 0))
        self.master = master
        self.dosbox = subprocess.Popen(
            [DOSBOXX, "-conf", str(self.dir / "dosbox.conf"),
             "-nopromptfolder", "-nomenu", "-fastlaunch"],
            env=env, cwd=str(self.dir),
            stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True,
        )
        os.close(slave)
        self._start_reader()

        pid, seen = self.dosbox.pid, {}
        while time.time() < deadline:
            ids = [w.decode() for w in subprocess.run(
                ["xdotool", "search", "--name", TITLE],
                env=env, capture_output=True).stdout.split()]
            seen = {w: window_pid(w, env) for w in ids}
            for wid in candidate_windows(ids, seen, pid):
                if uniform_colour(self.grab(wid)) is None:
                    self.window = wid
                    break
            else:
                time.sleep(0.3)
                continue
            break
        else:
            self.close()
            if not seen:
                raise TimeoutError("the DOSBox-X window never appeared")
            raise BlankCapture(
                f"no window on {self.display} titled {TITLE!r} both belongs to "
                f"pid {pid} and has anything in it; the windows "
                f"there are " + ", ".join(
                    f"{int(w):#x} (pid {theirs})" for w, theirs in seen.items())
            )
        subprocess.run(["xdotool", "windowfocus", self.window],
                       env=env, capture_output=True)
        self.settle()

    def _start_reader(self) -> None:
        """Drain the pty forever, in a thread.

        Not tidiness: the curses UI writes a great deal, a pty buffer is about
        64K, and a full one blocks the *emulator* on its next redraw.  Nothing
        read here is ever parsed -- the log file is the output channel -- but
        it is kept, so a launch that dies before opening the log can still be
        explained.
        """
        def pump() -> None:
            while not self._stop.is_set():
                try:
                    r, _, _ = select.select([self.master], [], [], 0.2)
                    if r:
                        data = os.read(self.master, 65536)
                        if not data:
                            return
                        self._pty += data[-1 << 20:]
                except (OSError, ValueError):
                    return
        self._stop.clear()
        self._reader = threading.Thread(target=pump, daemon=True)
        self._reader.start()

    def close(self) -> None:
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            self._reader = None
        if self.master >= 0:
            try:
                os.close(self.master)
            except OSError:
                pass
            self.master = -1
        super().close()

    def _env(self) -> dict[str, str]:
        return debug_env(self.display)

    # -- input -----------------------------------------------------------

    def key(self, *keys: str, gap: float = 0.35) -> None:
        """Press keys in the emulator, as X keysyms.

        **XTEST after `windowfocus`, not `xdotool key --window`.**  SDL2 ignores
        the synthetic events SDL1 accepted, so the `--window` form that
        `tools/dosbox.py` uses throughout silently does nothing here -- it
        neither errors nor presses anything.
        """
        env = self._env()
        for k in keys:
            subprocess.run(["xdotool", "windowfocus", self.window],
                           env=env, capture_output=True)
            subprocess.run(["xdotool", "key", "--clearmodifiers", k],
                           env=env, check=True, capture_output=True)
            time.sleep(gap)

    # -- output ----------------------------------------------------------

    def grab(self, window: str | None = None) -> dosbox.Screen | None:
        """One capture of any window, or None if `import` could not take it.

        `capture()` is this with `check=True` on the session's own window.
        This form is for the moment before there is one, when several windows
        carry the title and the choice between them is being made.
        """
        r = subprocess.run(
            ["import", "-window", window or self.window, "-depth", "8", "ppm:-"],
            env=self._env(), capture_output=True)
        if r.returncode != 0 or not r.stdout.startswith(b"P6"):
            return None
        return dosbox.Screen.from_ppm(r.stdout)

    def shot(self, name: str, allow_blank: bool = False) -> Path:
        """Write a PNG of the window, refusing to write one that is blank.

        A screenshot of the wrong window is a file that looks like the game
        drew nothing, which is the most expensive way for this harness to
        fail.  `allow_blank=True` is for the caller that wants the frame
        whatever it holds -- the shot taken on the way out of a failure.
        """
        if not allow_blank:
            colour = uniform_colour(self.grab())
            if colour is not None:
                raise BlankCapture(
                    f"{name}: window {int(str(self.window), 0):#x} on "
                    f"{self.display} "
                    f"is entirely #{colour[0]:02X}{colour[1]:02X}"
                    f"{colour[2]:02X}, so there is nothing to write"
                )
        return super().shot(name)

    # -- the log ---------------------------------------------------------

    def log_text(self) -> str:
        try:
            return self.log.read_text(errors="replace")
        except FileNotFoundError:
            return ""

    def mark(self) -> int:
        """A cursor into the log, so a later read sees only what came after."""
        return len(self.log_text())

    def wait_log(self, pattern: str, mark: int = 0, timeout: float = 30.0):
        """Poll the log after `mark` for `pattern`.  Match, or None."""
        rx = re.compile(pattern)
        deadline = time.time() + timeout
        while True:
            m = rx.search(self.log_text()[mark:])
            if m or time.time() >= deadline:
                return m
            time.sleep(0.15)

    # -- commands --------------------------------------------------------

    def dbg(self, cmd: str, expect: str | None = None,
            timeout: float = 5.0, quiet: float = 0.3) -> str:
        """Type one debugger command; return what it added to the log.

        With `expect`, returns as soon as that pattern appears.  Without one,
        returns once the log has stopped growing for `quiet` seconds -- or
        immediately at `timeout`, because plenty of commands (`RUN`, above all)
        answer with nothing at all, and so does every command sent while the
        emulator is running.
        """
        if len(cmd) > MAX_CMD:
            raise ValueError(
                f"{len(cmd)} characters; the debugger cuts a line at {MAX_CMD} "
                "and says nothing about it"
            )
        at = self.mark()
        os.write(self.master, cmd.encode() + b"\n")
        rx = re.compile(expect) if expect else None
        deadline = time.time() + timeout
        grew = 0.0
        size = at
        while time.time() < deadline:
            text = self.log_text()
            if rx is not None:
                if rx.search(text[at:]):
                    return text[at:]
            elif len(text) > size:
                size, grew = len(text), time.time()
            elif grew and time.time() - grew >= quiet:
                return text[at:]
            time.sleep(0.1)
        return self.log_text()[at:]

    def halted(self, timeout: float = 3.0) -> bool:
        """Whether the emulator is stopped in the debugger.

        The only reliable test there is, and it exists because **a code
        breakpoint firing logs nothing**.  `debug_gui.cpp` flushes pending
        input when the debugger opens, so a command typed while the emulator
        runs is thrown away and answers nothing; one typed while it is halted
        echoes.  Measured: three probes during a run produced no log lines and
        the game visibly moved a square meanwhile.
        """
        return bool(parse_ev(self.dbg("EV IP", expect=r"EV of", timeout=timeout)))

    def attach(self, tries: int = 6, gap: float = 1.0) -> bool:
        """Alt+Pause into the debugger, and check that it answered.

        This is how a *running* game is caught; `-break-start` and `DEBUGBOX`
        break before or at a program's entry instead.
        """
        for _ in range(tries):
            self.key("alt+Pause")
            time.sleep(gap)
            if self.halted():
                return True
        return False

    def run(self) -> None:
        """Resume.  Answers nothing, so there is nothing to wait for."""
        self.dbg("RUN", timeout=0.6)

    def step(self, wait: float = 0.5) -> None:
        """One instruction (F11).  A terminfo sequence, not a command."""
        os.write(self.master, b"\x1b[23~")
        time.sleep(wait)

    def step_over(self, wait: float = 0.5) -> None:
        """One instruction, over a `CALL` (F10)."""
        os.write(self.master, b"\x1b[21~")
        time.sleep(wait)

    def regs(self, *names: str) -> dict[str, int]:
        """Register and flag values, by name.  `EV` is the only way to get one.

        The register window, the disassembly and the data view are drawn in
        curses and never reach the log, so there is no structured output and
        this is it.  Names beat hex: `EV AF` is the auxiliary-carry flag, not
        `0xAF`, and `EV "AF"` in quotes is the number.
        """
        want = names or REGS
        out = parse_ev(self.dbg("EV " + " ".join(want), expect=r"EV of", timeout=6.0))
        if not out:
            raise NotHalted("EV answered nothing; the emulator is running")
        return out

    # -- memory ----------------------------------------------------------

    def read(self, addr: int | tuple[int, int], n: int) -> bytes:
        """`n` bytes from a linear or `(segment, offset)` address.

        **Split at the 64K wrap for you.**  `MEMDUMPBIN` masks its offset to 16
        bits, so a single call for a megabyte returns the same 64K sixteen
        times, at the full size, with nothing in the log to say so -- a caller
        that did its own arithmetic would be handed sixteen copies of segment
        zero and believe them.  A megabyte here is sixteen calls.
        """
        lin = linear(addr)
        out = bytearray()
        dump = self.dir / "MEMDUMP.BIN"
        for seg, ofs, take in chunks(lin, n):
            dump.unlink(missing_ok=True)
            # The success message is printed after `fclose`, so seeing it means
            # the file is complete: there is no size to poll and no race.
            reply = self.dbg(f"MEMDUMPBIN {seg:X} {ofs:X} {take:X}",
                             expect=r"Memory (dump binary|binary dump) ", timeout=30.0)
            if "success" not in reply:
                raise NotHalted(
                    f"MEMDUMPBIN {seg:04X}:{ofs:04X} answered {reply.strip()!r}; "
                    "the emulator is probably running"
                )
            got = dump.read_bytes()
            if len(got) != take:
                raise RuntimeError(f"MEMDUMP.BIN is {len(got)} bytes, wanted {take}")
            out += got
        return bytes(out)

    def write(self, addr: int | tuple[int, int], data: bytes) -> None:
        """Write bytes with `SM`, in lines short enough to survive the parser.

        A command is cut at 254 characters in silence, so a long `SM` would
        write its first sixty-odd bytes and report success for all of them.
        """
        lin = linear(addr)
        per = 64
        for i in range(0, len(data), per):
            seg, ofs = seg_off(lin + i)
            body = " ".join(f"{b:02X}" for b in data[i:i + per])
            reply = self.dbg(f"SM {seg:X}:{ofs:X} {body}",
                             expect=r"Memory changed", timeout=8.0)
            if "Memory changed" not in reply:
                raise NotHalted(f"SM answered {reply.strip()!r}")

    # -- breakpoints -----------------------------------------------------

    def watch(self, addr: int | tuple[int, int], absorb: bool = True,
              timeout: float = 30.0) -> Break | None:
        """A one-byte watchpoint (`BPM`), with the spurious first hit absorbed.

        **A fresh `BPM` remembers the value `00`**, so unless the byte really
        is zero it fires the instant you `RUN` -- reporting `00 -> <whatever
        was already there>`, which reads exactly like a real change.  The byte
        is read first here, so the absorbing `RUN` happens only when there is
        something to absorb and a genuinely-zero byte does not cost a timeout.

        Returns the hit that was absorbed, or None when there was none.  Both
        leave the emulator halted, ready for `until_break()`.

        Watchpoints are one byte and on change: a word takes two, a write of
        the same value is invisible, and there is no read watchpoint.
        """
        lin = linear(addr)
        seg, ofs = seg_off(lin)
        was = self.read(lin, 1)
        self.dbg(f"BPM {seg:X}:{ofs:X}", expect=r"Set memory breakpoint", timeout=8.0)
        if not absorb or was == b"\x00":
            return None
        return self.until_break(timeout=timeout)

    def brk(self, addr: int | tuple[int, int]) -> None:
        """A code breakpoint (`BP`).

        It stops the emulator and **prints nothing when it fires**, so the way
        to notice is `halted()`, or `wait_halt()`.
        """
        seg, ofs = seg_off(linear(addr))
        self.dbg(f"BP {seg:X}:{ofs:X}", expect=r"Set breakpoint", timeout=8.0)

    def breakpoints(self) -> str:
        """`BPLIST`, verbatim.  There is no structured form of it."""
        return self.dbg("BPLIST", expect=r"Breakpoint list", timeout=8.0)

    def clear_breakpoints(self) -> None:
        self.dbg("BPDEL *", expect=r"Breakpoints deleted", timeout=8.0)

    def wait_break(self, mark: int, timeout: float = 60.0) -> Break | None:
        """The next memory-breakpoint hit logged after `mark`, or None."""
        m = self.wait_log(RE_BPM.pattern, mark, timeout)
        if m is None:
            return None
        hits = parse_breaks(self.log_text()[mark:])
        return hits[0] if hits else None

    def until_break(self, timeout: float = 60.0) -> Break | None:
        """`RUN`, then wait for a watchpoint to fire.  None on timeout."""
        at = self.mark()
        self.run()
        return self.wait_break(at, timeout)

    def wait_halt(self, timeout: float = 60.0) -> bool:
        """Poll `halted()` until it is true -- how a code breakpoint is seen."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.halted():
                return True
        return False


# --------------------------------------------------------------------------
# The worked example, re-run through the harness
# --------------------------------------------------------------------------

#: `docs/141-dos-savegame.md`: `SAVGAM?.DAT` offset 1 is the ECL VM variable
#: array, two bytes per ECL address from `$4900`.
VM_OFFSET = 1
VM_SIZE = 5120
VM_BASE_ADDR = 0x4900

#: `$49C6`-`$49CB` is the clock; `$49C7` is the minute units.
CLOCK_MINUTES = 0x49C7


def vm_slot(ecl_addr: int) -> int:
    """The byte offset into the VM array of an ECL address's low byte."""
    return 2 * (ecl_addr - VM_BASE_ADDR)


def clock_demo(letter: str = "J", timeout: float = 240.0) -> dict:
    """`docs/142`'s worked example, end to end, through this module.

    Boot, load the player's save, break in, dump the first megabyte, find the
    save's own variable array in it, watch the clock's minute-units byte, and
    catch it tick.  The base address it prints is **not a finding to reuse** --
    it is where DOS happened to load this build with this config.  The finding
    is the recipe.
    """
    game = dosbox.find_game("POOLRAD")
    save = (game / "SAVE" / f"SAVGAM{letter.upper()}.DAT").read_bytes()
    vm = save[VM_OFFSET:VM_OFFSET + VM_SIZE]
    out: dict = {"slot": letter}

    with claim("dosboxx clock demo") as slot:
        with XSession(slot, game) as s:
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(letter)
            out["attached"] = s.attach()
            if not out["attached"]:
                return out

            image = s.read(0, 0x100000)
            out["dumped"] = len(image)
            found = locate(image, vm)
            if found is None:
                return out
            base, votes, same = found
            out.update(vm_base=base, votes=votes, matching=f"{same}/{len(vm)}")

            addr = base + vm_slot(CLOCK_MINUTES)
            out["clock_addr"] = f"{seg_off(addr)[0]:04X}:{seg_off(addr)[1]:04X}"
            out["live"] = s.read(addr, 1)[0]
            out["in_save"] = vm[vm_slot(CLOCK_MINUTES)]

            out["absorbed"] = str(s.watch(addr))
            at = s.mark()
            s.run()
            s.key("Up")
            hit = s.wait_break(at, timeout=timeout)
            out["tick"] = (
                f"{hit.seg:04X}:{hit.ofs:04X} {hit.old:02X} -> {hit.new:02X}"
                if hit else None
            )
            if hit:
                out["at"] = s.regs("CS", "IP")
                s.write(addr, b"\x09")
                out["after_write"] = s.read(addr, 1)[0]
            s.clear_breakpoints()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("check", "clock"),
                    help="check what is installed, or re-run docs/142's example")
    ap.add_argument("--slot", default="J", help="the save letter to load")
    args = ap.parse_args(argv)

    if args.command == "check":
        why = unavailable()
        print("dosbox-x:", DOSBOXX)
        print("debugger:", "no -- " + why if why else "yes")
        try:
            print("game:", dosbox.find_game())
        except FileNotFoundError as e:
            print("game:", e)
        return 1 if why else 0

    import pprint
    pprint.pprint(clock_demo(args.slot))
    return 0


if __name__ == "__main__":
    sys.exit(main())

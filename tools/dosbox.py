#!/usr/bin/env python3
"""A driven DOS Gold Box session: DOSBox on a private X display, unattended.

The C64 side of this project drives VICE through its binary monitor.  DOS has
no such thing -- DOSBox 0.74-3, which is what is installed here, ships no
debugger and no scripting -- so the three primitives are the ones a headless X
session gives you:

1. **Input** is XTEST through `xdotool`, aimed at a display nobody else owns.
   `xdotool key --window <id>`, not `windowactivate`: there is no window
   manager under a bare `Xvfb`, so activation fails with "your windowmanager
   claims not to support _NET_ACTIVE_WINDOW" and the keystroke is lost.
2. **Output** is a 320x200 window capture.  `output=surface` with `scaler=none`
   makes the DOSBox window exactly the emulated framebuffer, so a capture is
   the VGA image pixel for pixel with no scaling to undo.
3. **Ground truth is the save file.**  DOS writes plain files into the game's
   `SAVE` directory, so "did that keystroke do anything" is answered by reading
   `SAVGAM<slot>.DAT` back off the host filesystem.  Nothing here has to read
   the screen to know what happened, and that is deliberate: an OCR that is
   wrong once is worse than no OCR at all.

Where the screen *is* needed -- "are we in camp or on the map" -- it is used as
an opaque digest of a strip of pixels, never as text.  A digest cannot be
misread, only unequal.

**Determinism.** `settle()` waits for consecutive identical frames rather than
sleeping a guessed interval, and every action that matters is verified by its
effect: `save_game()` waits for the file to change on disk, and each menu step
checks that the screen it wanted arrived before pressing the next key.  The one
thing DOSBox will not give us is a frame counter, so a run is reproducible in
what it produces, not cycle-exact in how long it takes.

**Isolation.** Every instance owns its X display, its game tree, its DOSBox
config and its capture directory, all under `work/dosbox/inst/<n>/`, and the
slot is held by an `fcntl.flock` so a crashed run frees it with no cleanup --
the lease pattern `docs/123-parallel-sessions.md` chose for the VICE pool.  The
player's archives are copied, never opened for writing, and nothing here reads
or writes a user-level DOSBox configuration.  Teardown kills the process groups
this instance started and nothing else: **never a process by name.**

Run time it needs: `dosbox`, `Xvfb`, `xdotool`, and ImageMagick's `import`.
Everything skips cleanly when they are absent.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

try:
    import fcntl  # POSIX only
except ImportError:                 # pragma: no cover - Windows
    # The harness drives DOSBox on Linux and nothing else needs it, but the
    # module still has to *import* everywhere: `tests/test_dosbox.py` asserts
    # findings about a DOS save that hold on any platform, and CI runs the
    # suite on Windows.
    fcntl = None
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = REPO / "work" / "dosbox"
INST = WORK / "inst"

# The pool never takes a display anything else here uses: `tools/porlaunch.sh`
# defaults to :7 and `docs/123-parallel-sessions.md` allocates :10-:17 to VICE.
DISPLAY_BASE = 30
SLOTS = 8

# Where the player's copy of Forgotten Realms: The Archives is unpacked.
# Read only, always: a game tree is copied into `work/` before DOSBox sees it.
ARCHIVES = Path(
    os.environ.get("FR_ARCHIVES", Path.home() / "Downloads" / "fr-archives")
)

TOOLS = ("dosbox", "Xvfb", "xdotool", "import")


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from por import dos as _por_dos  # noqa: E402
from por import dos_savegame as _sav  # noqa: E402


class DosboxUnavailable(RuntimeError):
    """One of dosbox, Xvfb, xdotool or ImageMagick is not installed."""


class PoolFull(RuntimeError):
    """Every instance slot is leased by another process."""


class BlankCapture(RuntimeError):
    """A capture came back a single colour, so it is showing nothing."""


def missing_tools(tools: tuple[str, ...] = TOOLS) -> list[str]:
    return [t for t in tools if shutil.which(t) is None]


def require_tools(tools: tuple[str, ...] = TOOLS) -> None:
    absent = missing_tools(tools)
    if absent:
        raise DosboxUnavailable("not installed: " + ", ".join(absent))


# --------------------------------------------------------------------------
# Finding a game tree in the archives
# --------------------------------------------------------------------------


def find_game(stem: str = "POOLRAD") -> Path:
    """The DOS game directory for `stem`, inside the player's archives.

    Returns the directory holding `START.EXE` -- for Pool of Radiance that is
    `<collection>/games/POOLRAD/GAME/POOLRAD`.  Raises `FileNotFoundError` when
    the archives are not on this machine, which is how the tests skip.
    """
    if not ARCHIVES.is_dir():
        raise FileNotFoundError(f"no archives at {ARCHIVES}")
    for collection in sorted(ARCHIVES.iterdir()):
        games = collection / "games"
        if not games.is_dir():
            continue
        for entry in sorted(games.iterdir()):
            inner = entry / "GAME" / stem
            if (inner / "START.EXE").is_file():
                return inner
    raise FileNotFoundError(f"no DOS {stem} under {ARCHIVES}")


# --------------------------------------------------------------------------
# The instance lease
# --------------------------------------------------------------------------


@dataclass
class Slot:
    """One leased instance: its number, its display, its directory.

    The lease is an `fcntl.flock` held by this process.  The kernel drops it
    when the process dies however it dies, so there is no stale-lock policy to
    get wrong.
    """

    n: int
    dir: Path
    _fd: int

    @property
    def display(self) -> str:
        return f":{DISPLAY_BASE + self.n}"

    def release(self) -> None:
        if self._fd >= 0:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = -1

    def __enter__(self) -> Slot:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def claim(note: str = "") -> Slot:
    """Lease the first free instance slot, or raise `PoolFull`."""
    if fcntl is None:
        raise PoolFull("the DOSBox harness needs flock, so it is POSIX only")
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
        os.write(
            fd,
            json.dumps(
                {"slot": n, "pid": os.getpid(), "note": note, "at": time.time()}
            ).encode(),
        )
        return Slot(n=n, dir=d, _fd=fd)
    raise PoolFull(f"all {SLOTS} DOSBox slots are leased")


# --------------------------------------------------------------------------
# Screens
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Screen:
    """One window capture: a binary PPM decoded to width, height and RGB."""

    width: int
    height: int
    px: bytes

    @classmethod
    def from_ppm(cls, data: bytes) -> Screen:
        if data[:2] != b"P6":
            raise ValueError("not a binary PPM")
        tok: list[bytes] = []
        i = 2
        while len(tok) < 3:
            while data[i : i + 1].isspace():
                i += 1
            if data[i : i + 1] == b"#":
                while data[i : i + 1] != b"\n":
                    i += 1
                continue
            j = i
            while not data[j : j + 1].isspace():
                j += 1
            tok.append(data[i:j])
            i = j
        i += 1
        w, h, maxval = (int(t) for t in tok)
        if maxval != 255:
            raise ValueError(f"expected 8-bit PPM, got maxval {maxval}")
        return cls(w, h, data[i : i + w * h * 3])

    def rows(self, rect: tuple[int, int, int, int] | None = None) -> bytes:
        x, y, w, h = rect or (0, 0, self.width, self.height)
        return b"".join(
            self.px[((y + dy) * self.width + x) * 3 : ((y + dy) * self.width + x + w) * 3]
            for dy in range(h)
        )

    def digest(self, rect: tuple[int, int, int, int] | None = None) -> str:
        """A short hash of a rectangle -- the way this module compares screens.

        Comparing pixels rather than reading them is the point: a digest is
        never *misread*, only unequal, so a wait can be driven by it safely
        where an OCR result could not be.
        """
        return hashlib.sha1(self.rows(rect)).hexdigest()[:16]

    def ink(self, rect: tuple[int, int, int, int] | None = None) -> str:
        """A digest of the same rectangle's *shape*, ignoring colour.

        The game recolours the command bar without changing a glyph -- it is
        white for one frame after the party arrives somewhere and green
        thereafter -- so `digest` says "different screen" about two screens
        that carry the same 169 lit pixels in the same places.  Thresholding to
        ink and paper first is what makes "am I back on the map" answerable.
        """
        px = self.rows(rect)
        bits = bytes(
            1 if px[i] + px[i + 1] + px[i + 2] > 120 else 0 for i in range(0, len(px), 3)
        )
        return hashlib.sha1(bits).hexdigest()[:16]


# --------------------------------------------------------------------------
# Which window is ours, and whether anything is in it
# --------------------------------------------------------------------------
#
# Three faults with one symptom, found on the DOSBox-X side (#83) and the same
# here (#88): every screenshot comes back solid black while the game is
# plainly drawing, `settle()` calls two identical black frames a finished
# screen, and `load_game` reports a save that loaded perfectly as never having
# loaded.  Both harnesses use these, so there is one copy of them.


def has_content(screen: Screen | None) -> bool:
    """True when a capture was taken *and* it is not one flat colour.

    The two failures read the same through `uniform_colour` alone and must
    not: it answers None both for a capture with something in it and for no
    capture at all, because `grab()` returns None when `import` exits nonzero.
    So `uniform_colour(grab(wid)) is None` accepted a window whose capture had
    failed -- a real race, since `xdotool search` lists a window that can close
    or be unmapped before `import` reaches it -- and `settle()` then ran
    `capture(check=True)` against it and raised `CalledProcessError` instead of
    the named refusal this exists to give.
    """
    return screen is not None and uniform_colour(screen) is None


def uniform_colour(screen: Screen | None) -> tuple[int, int, int] | None:
    """The single colour a capture is made of, or None if it has two.

    A capture of the wrong window is not an error -- `import` takes it happily
    and returns one flat colour -- so nothing downstream notices.  One colour
    is the signature, and refusing it by name is what stops that reading as
    "the game did nothing".
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

    Two DOSBox processes on one display leave two top-level windows with the
    same title, the same geometry and the same `IsViewable` map state; nothing
    about the windows themselves separates them, and only one has pixels in
    it.  `_NET_WM_PID` does separate them, so a window that names another
    process is dropped outright.  Windows naming no process at all are kept as
    a fallback, for a build whose SDL does not set the property -- there the
    caller still has to choose by content.

    **Not by content alone.**  The window with pixels in it is whichever
    process drew last, which is the intruder as often as ours: they overlap
    exactly, `Backing Store State` is `NotUseful` and there is no compositor
    under a bare `Xvfb`, so X keeps no contents for a window nobody can see.

    **`_NET_WM_PID` is SDL2's, and DOSBox 0.74 is SDL 1.2** -- the string does
    not appear in `libSDL-1.2.so.0` at all, where `libSDL2-2.0.so.0` carries
    it -- so for this harness every window takes the no-pid fallback and the
    choice is the content one.  What keeps that safe here is `boot()` refusing
    a display something already answers on: on a display this session created,
    the only client that can have a window is the DOSBox it started.  The
    filter is the belt to that brace, and it goes live the day 0.74 is built
    against SDL2.
    """
    mine = [w for w in ids if pids.get(w) == pid]
    return mine or [w for w in ids if pids.get(w) is None]


def server_on(display: str) -> bool:
    """Whether an X server is listening on that display, by its own socket.

    Not by running `xdotool`: it exits 1 both for "no windows matched" and for
    "Can't open display", so the readiness loop that tested its status was
    satisfied by a display that did not exist -- and never waited for anything.
    Connecting to `/tmp/.X11-unix/X<n>` cannot be read two ways; a socket left
    behind by a dead server refuses the connection.

    Asked before `Xvfb` is started as well as after.  A second `Xvfb` on a busy
    display does exit with "Server is already active", but it takes a moment,
    and by then the session has already launched DOSBox against the server that
    was already there.
    """
    n = display.lstrip(":").split(".")[0]
    # `AF_UNIX` is POSIX-only and this module imports on Windows, where the
    # tests run and DOSBox does not.  Nothing here can start a server on a
    # platform with no X socket, so "free" is the honest answer rather than an
    # `AttributeError` from inside a probe.
    if not hasattr(socket, "AF_UNIX"):
        return False
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


# --------------------------------------------------------------------------
# The session
# --------------------------------------------------------------------------

CONFIG = """\
[sdl]
fullscreen=false
output=surface
autolock=false
usescancodes=true
waitonerror=false
mapperfile={dir}/mapper.map
priority=higher,normal

[dosbox]
machine=vga
captures={dir}/capture
memsize=16

[render]
frameskip=0
aspect=false
scaler=none

[cpu]
core=auto
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


class Session:
    """A booted DOSBox with one DOS game in it.

    Use it as a context manager; `close()` kills the processes, and only the
    two groups this instance started.
    """

    #: What has to be on `PATH` before this class can run.  A class attribute
    #: rather than the module constant so a subclass can narrow it: DOSBox-X's
    #: `XSession` is this class with the launch replaced, and demanding DOSBox
    #: 0.74 of a machine carrying only the debugger build refused it a session
    #: over an emulator that harness never starts (#73).
    TOOLS = TOOLS

    #: What `xdotool search --name` looks for.  DOSBox 0.74 titles its window
    #: "DOSBox 0.74-3"; `XSession` sets a title of its own and overrides this.
    TITLE = "DOSBox"

    def __init__(
        self,
        slot: Slot,
        game: Path,
        exe: str = "START.EXE",
        cycles: int = 20000,
        geometry: str = "800x600x24",
    ):
        require_tools(self.TOOLS)
        self.slot = slot
        self.dir = slot.dir
        self.display = slot.display
        self.stem = game.name
        self.game_dir = self.dir / "game" / self.stem
        self.exe = exe
        self.cycles = cycles
        self.geometry = geometry
        self.source = game
        self.xvfb: subprocess.Popen[bytes] | None = None
        self.dosbox: subprocess.Popen[bytes] | None = None
        self.window: str | None = None

    # -- staging ---------------------------------------------------------

    def stage(self, fresh: bool = True) -> None:
        """Copy the game tree into the instance directory.

        The archives are read only.  This is the one place that touches them
        and it only ever reads.
        """
        dest = self.dir / "game"
        assert str(dest.resolve()).startswith(str(WORK)), dest
        if fresh and dest.exists():
            shutil.rmtree(dest)
        if not dest.exists():
            dest.mkdir(parents=True)
            shutil.copytree(self.source, dest / self.stem)
            for p in (dest / self.stem).rglob("*"):
                p.chmod(p.stat().st_mode | 0o200)
        (self.dir / "capture").mkdir(exist_ok=True)
        (self.dir / "shots").mkdir(exist_ok=True)
        (self.dir / "dosbox.conf").write_text(
            CONFIG.format(dir=self.dir, stem=self.stem, exe=self.exe, cycles=self.cycles)
        )

    @property
    def save_dir(self) -> Path:
        return self.game_dir / "SAVE"

    def save_file(self, letter: str) -> Path:
        return self.save_dir / f"SAVGAM{letter.upper()}.DAT"

    # -- lifecycle -------------------------------------------------------

    def boot(self, timeout: float = 60.0, fresh: bool = True) -> None:
        """Stage the game and start Xvfb and DOSBox.

        `fresh=False` keeps the staged tree, and with it the `SAVE` directory,
        which is how a run gets back to the main menu: quitting the game ends
        the autoexec, so restarting the emulator is cheaper and far more
        deterministic than typing at a DOS prompt.

        **The window is chosen by `_NET_WM_PID` and then proved to have pixels
        in it** (#88).  A display an earlier run's DOSBox is still holding
        carries two top-level windows with this title, and whichever is
        underneath captures as solid black -- see `candidate_windows`.  Two
        smaller faults fed it and are fixed here too: the readiness wait now
        asks the X socket rather than `xdotool`'s exit status, which cannot
        distinguish "no windows matched" from "cannot open display"; and a
        display something already answers on is refused rather than shared,
        which is how two DOSBoxes came to be on one display at all.
        """
        self.stage(fresh=fresh)
        env = dict(os.environ, DISPLAY=self.display, SDL_AUDIODRIVER="dummy")
        env.pop("XAUTHORITY", None)
        if server_on(self.display):
            raise RuntimeError(
                f"{self.display} already has an X server on it, so this "
                f"session would share it.  A DOSBox or Xvfb from an earlier "
                f"run is still holding the display -- two DOSBox windows with "
                f"the same title, and `import` returns solid black for "
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

        self.dosbox = subprocess.Popen(
            ["dosbox", "-conf", str(self.dir / "dosbox.conf"), "-noconsole"],
            env=env,
            stdout=(self.dir / "dosbox.log").open("wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        # `_env()`, not the launch environment: it is what `capture()` and
        # `key()` use, so the window is found and read through one view of X.
        look = self._env()
        pid, seen = self.dosbox.pid, {}
        while time.time() < deadline:
            ids = [w.decode() for w in subprocess.run(
                ["xdotool", "search", "--name", self.TITLE],
                env=look, capture_output=True).stdout.split()]
            seen = {w: window_pid(w, look) for w in ids}
            for wid in candidate_windows(ids, seen, pid):
                if has_content(self.grab(wid)):
                    self.window = wid
                    break
            else:
                time.sleep(0.3)
                continue
            break
        else:
            self.close()
            if not seen:
                raise TimeoutError("DOSBox window never appeared")
            raise BlankCapture(
                f"no window on {self.display} titled {self.TITLE!r} both "
                f"belongs to pid {pid} and has anything in it; the windows "
                f"there are " + ", ".join(
                    f"{int(w):#x} (pid {theirs})" for w, theirs in seen.items())
            )
        self.settle()

    def close(self) -> None:
        for p in (self.dosbox, self.xvfb):
            if p is None or p.poll() is not None:
                continue
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except ProcessLookupError:
                continue
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                # Reaped, not merely signalled: `boot()` now refuses a display
                # something still answers on, so `restart()` would race its own
                # `Xvfb` out of existence and be told the slot is somebody's.
                with contextlib.suppress(subprocess.TimeoutExpired):
                    p.wait(timeout=5)
        self.dosbox = self.xvfb = None

    def restart(self) -> None:
        """Stop and start again, keeping the staged game and its saves."""
        self.close()
        self.boot(fresh=False)

    def __enter__(self) -> Session:
        self.boot()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- input and output ------------------------------------------------

    def _env(self) -> dict[str, str]:
        return dict(os.environ, DISPLAY=self.display)

    def key(self, *keys: str, gap: float = 0.35) -> None:
        """Press keys one at a time, as X keysyms (`a`, `Up`, `Escape`)."""
        for k in keys:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "--window", self.window, k],
                env=self._env(),
                check=True,
                capture_output=True,
            )
            time.sleep(gap)

    def capture(self) -> Screen:
        r = subprocess.run(
            ["import", "-window", self.window, "-depth", "8", "ppm:-"],
            env=self._env(),
            check=True,
            capture_output=True,
        )
        return Screen.from_ppm(r.stdout)

    def grab(self, window: str | None = None) -> Screen | None:
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
        return Screen.from_ppm(r.stdout)

    def shot(self, name: str, allow_blank: bool = False) -> Path:
        """Write a PNG of the window, refusing to write one that is blank.

        A screenshot of the wrong window is a file that looks like the game
        drew nothing, which is the most expensive way for this harness to fail
        (#88).  `allow_blank=True` is for the caller that wants the frame
        whatever it holds -- the shot taken on the way out of a failure.

        `capture()` is deliberately not guarded this way: Pool of Radiance
        draws genuinely black frames between screens, and every `settle()` and
        `wait_for()` polls through them.
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
        out = self.dir / "shots" / f"{name}.png"
        subprocess.run(
            ["import", "-window", self.window, "-depth", "8", str(out)],
            env=self._env(),
            check=True,
            capture_output=True,
        )
        return out

    def settle(self, quiet: float = 0.6, timeout: float = 30.0) -> Screen:
        """Wait until consecutive captures stop differing, and return one.

        Cheaper and far more reliable than sleeping: a screen still being drawn
        differs from itself, and a finished one does not.
        """
        deadline = time.time() + timeout
        last = self.capture()
        stable_since = time.time()
        while time.time() < deadline:
            time.sleep(0.15)
            now = self.capture()
            if now.px == last.px:
                if time.time() - stable_since >= quiet:
                    return now
            else:
                last, stable_since = now, time.time()
        return last

    def wait_for(self, pred, timeout: float = 30.0) -> bool:
        """Poll `pred(Screen)` until true.  Returns whether it became true."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pred(self.capture()):
                return True
            time.sleep(0.25)
        return False

    def wait_until_ink(
        self, rect: tuple[int, int, int, int], want: str, timeout: float = 30.0
    ) -> bool:
        return self.wait_for(lambda s: s.ink(rect) == want, timeout)

    def wait_while_ink(
        self, rect: tuple[int, int, int, int], same: str, timeout: float = 30.0
    ) -> bool:
        return self.wait_for(lambda s: s.ink(rect) != same, timeout)


# --------------------------------------------------------------------------
# Pool of Radiance, driven
# --------------------------------------------------------------------------

# Rectangles of the 320x200 frame, measured off captures rather than guessed.
# The command bar is the bottom text row, `AREA CAST VIEW ENCAMP SEARCH LOOK`;
# the status line is the one under the viewport, `5,2 E 10:04`.
#
# Both stop short of the ornate rope border -- rows 190 and 191 below the bar,
# and the frame around the viewport.  The border recolours as the game changes
# state, and near the ink threshold that flips pixels, so a rectangle that
# includes any of it compares unequal to itself.
BAR = (0, 192, 320, 7)
STATUS = (128, 120, 128, 8)

#: **The byte map is `por/dos_savegame.py`'s and only its** (#76).  This
#: harness held a second copy -- and `AREA_ID` had already drifted out of the
#: map's units: it is the *word index* 395, which is `word_offset($49C5)`, so a
#: reader who fixed `$49C5` on one side would never have found 395 on the
#: other.  Re-exported, the way `item_to_c64` is, so the measurements in
#: `tests/test_dosbox.py` keep reading them from where they were written.
POS_X = _sav.POS_X
POS_Y = _sav.POS_Y
POS_FACING = _sav.POS_FACING
AREA_ID = _sav.word_offset(_sav.AREA)
AREA_FILE = _sav.DAX_NUMBER

#: The facing byte as the *file* carries it: the C64's 0-3 doubled.
#: `por.dos_savegame.position` halves it and this harness does not, because
#: what a driven run wants to see is the byte that moved.
FACINGS = {i * _sav.FACING_SCALE: d for i, d in enumerate("NESW")}


def position(save: bytes) -> tuple[int, int, int]:
    """`(x, y, facing)` out of a `SAVGAM<slot>.DAT`, facing doubled.

    `por.dos_savegame.position` returns the same square with the facing in the
    C64's 0-3; this one is the file's own byte, which is what a differential
    between two saves is written in.
    """
    return save[POS_X], save[POS_Y], save[POS_FACING]


def area_id(save: bytes) -> int:
    """The current area, in the numbering `por/areas.py` uses."""
    return _sav.area_id(save)


# --------------------------------------------------------------------------
# The `.DAX` container, and the 63-byte item record inside `.ITM`
# --------------------------------------------------------------------------

#: The container reader is `por/dos_savegame.py`'s (#76): one index, one
#: run-length decode, one set of refusals.  `por/` may not import from
#: `tools/`, so the shared copy lives there and this is the re-export.
DAX_ENTRY = _sav.DAX_ENTRY
DaxError = _sav.DaxError
dax_index = _sav.dax_index
dax_unpack = _sav.dax_unpack
dax_blocks = _sav.dax_blocks
dax_block = _sav.dax_block


# One item, in a `.ITM` file or an `ITEM<n>.DAX` block.  The file is
# `count x ITEM_SIZE` with no header; the count is the character record's
# `0x0C7`.
ITEM_SIZE = 63

# `0x000` is a length byte and `0x001`-`0x029` the **rendered inventory line**
# -- readied column, "* " when a party member has detect magic up, the stack
# count, then the name.  It is a cache the game rewrites whenever it draws the
# list, so it can disagree with the fields below it and does: one specimen
# reads "11 Darts" over a quantity of 8.  Never source a value from it.
ITEM_TEXT = 0x000
ITEM_TEXT_MAX = 41

# `0x02A`-`0x02D` is a far pointer -- `offset:u16le, segment:u16le` -- to the
# next item in the character's list, NULL on the last.  Live heap state: in 61
# of the player's 66 `.ITM` files consecutive items sit exactly `0x40` apart,
# and all 66 terminate.  Nothing to convert.
ITEM_NEXT = 0x02A

# `0x02E` onwards is the C64's own 16-byte item record with its packed bytes
# spread out.  `por.items` documents what each one means; the correspondence
# below is what makes that documentation apply.
ITEM_TYPE = 0x02E        # indexes ITEMS, the 128 x 16 type table -- and the
ITEM_NAME1 = 0x02F       #   DOS ITEMS is byte-identical to the C64's in 126
ITEM_NAME2 = 0x030       #   of its 128 records.  The class restrictions are
ITEM_NAME3 = 0x031       #   in *that* table, not here.
ITEM_PLUS = 0x032        # signed
ITEM_PLUS_SAVE = 0x033   # signed; accumulates into the saving-throw roll
ITEM_READIED = 0x034     # 0 or 1
ITEM_HIDDEN = 0x035      # bit 0 hides name 3, bit 1 name 2, bit 2 name 1
ITEM_CURSED = 0x036      # 0 or 1
ITEM_WEIGHT = 0x037      # u16le, tenths of a pound
ITEM_QUANTITY = 0x039
ITEM_VALUE = 0x03A       # u16le, gold pieces
ITEM_SPECIAL = 0x03C     # three bytes: charges, effect, power -- or, on a
#                          scroll, up to three spell ids

C64_ITEM_SIZE = 16


#: The projection itself now lives in `por/dos.py`, because it is part of the
#: converter rather than part of the harness that drives DOSBox.  Re-exported
#: here so the measurements in `tests/test_dosbox.py` keep reading it from the
#: place they were written against, and so there is one copy of it.
item_to_c64 = _por_dos.item_to_c64


def items(data: bytes):
    """Yield the 63-byte records of a `.ITM` file or an `ITEM<n>.DAX` block."""
    for i in range(len(data) // ITEM_SIZE):
        yield data[i * ITEM_SIZE:(i + 1) * ITEM_SIZE]


class PoolOfRadiance:
    """The keystroke protocol of DOS Pool of Radiance, verified by effect.

    Three things about the menus that are worth writing down:

    * **Saving is a camp command.** `ENCAMP` (`e`) from the map, `SAVE` (`s`)
      in camp, then the slot letter at `SAVE WHICH GAME: A B C ... J`.
    * **The game offers to quit right after it saves.** `QUIT TO DOS YES NO`
      appears with the file already written; `n` declines and leaves you in
      camp, and `Escape` returns to the map.
    * **The camp menu's EXIT is exit to DOS**, not exit to the map.
    """

    def __init__(self, session: Session):
        self.s = session
        self.world_bar: str | None = None

    # -- screen predicates, as digests rather than text ------------------

    def bar(self) -> str:
        """The command bar, by shape.  See `Screen.ink` for why not by colour."""
        return self.s.capture().ink(BAR)

    def status(self) -> str:
        return self.s.capture().ink(STATUS)

    # -- getting into the game -------------------------------------------

    def to_main_menu(self, timeout: float = 120.0) -> None:
        """Press past the title screens until the bottom bar stops changing.

        The title sequence is several full-screen pictures, each dismissed by
        a keypress, ending at `CREATE NEW CHARACTER  ...  LOAD SAVED GAME`.
        Pressing until two consecutive settled screens agree is what tells us
        we have arrived without reading a word of it.
        """
        deadline = time.time() + timeout
        last = None
        stable = 0
        while time.time() < deadline:
            self.s.key("Return")
            d = self.s.settle().digest()
            if d == last:
                stable += 1
                if stable >= 2:
                    return
            else:
                stable = 0
            last = d
        raise TimeoutError("never reached the main menu")

    def load_game(self, letter: str, timeout: float = 90.0) -> None:
        """`LOAD SAVED GAME` -> a slot letter.  Waits for the map to appear.

        The menu lists only the slots that exist -- `LOAD WHICH GAME: A B J` --
        so asking for a letter with no file leaves the menu up and the wait
        times out rather than silently continuing.
        """
        before = self.s.settle().digest()
        self.s.key("l")
        self.s.settle()
        self.s.key(letter.lower())
        if not self.s.wait_for(lambda s: s.digest() != before, timeout=timeout):
            raise TimeoutError(f"slot {letter} never loaded")
        self.s.settle()
        self.world_bar = self.bar()

    # -- the map ----------------------------------------------------------

    def _move(self, key: str, timeout: float = 20.0) -> bool:
        """Press a movement key and wait for the map's command bar to return.

        A step is not over when the frame stops changing.  **The game blanks the
        command bar while the party moves** and redraws it a beat later, and
        the frame is perfectly still in between -- so `settle()` returns on a
        screen with no bar at all, and a `world` reference taken there is a bar
        that will never be seen again.  That is what made the second save of a
        two-save run fail to find its way out of camp.  Waiting for the bar
        recorded at load time is what makes an action *complete*.

        Returns False when it never came back, which is how a prompt the step
        walked into -- "DO YOU WANT TO TAKE A BOAT BACK TO PHLAN?" -- is
        noticed rather than pressed through blindly.
        """
        self.s.key(key)
        self.s.settle()
        if self.world_bar is None:
            self.world_bar = self.bar()
            return True
        return self.s.wait_until_ink(BAR, self.world_bar, timeout)

    def step(self) -> bool:
        return self._move("Up")

    def turn_left(self) -> bool:
        return self._move("Left")

    def turn_right(self) -> bool:
        return self._move("Right")

    # -- saving, which is the whole point ---------------------------------

    def save_game(self, letter: str, timeout: float = 60.0) -> bytes:
        """Encamp, save to `letter`, decline the quit, leave camp; return bytes.

        Verified by effect at both ends: the save is not believed until
        `SAVGAM<letter>.DAT` changes on disk, and camp is not believed to be
        over until the command bar is the one that was there before encamping.
        """
        path = self.s.save_file(letter)
        was = path.read_bytes() if path.is_file() else None

        world = self.world_bar or self.bar()
        self.s.key("e")
        if not self.s.wait_while_ink(BAR, world, timeout):
            raise TimeoutError("ENCAMP did not open the camp menu")
        camp = self.s.settle().ink(BAR)

        self.s.key("s")
        if not self.s.wait_while_ink(BAR, camp, timeout):
            raise TimeoutError("SAVE did not open the slot list")
        self.s.settle()
        self.s.key(letter.lower())

        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.is_file() and path.read_bytes() != was:
                break
            time.sleep(0.3)
        else:
            raise TimeoutError(f"{path.name} never changed")
        data = path.read_bytes()

        self.leave_camp(world)
        return data

    def leave_camp(self, world: str, tries: int = 12) -> None:
        """Get back to the map from wherever in camp we are.

        Two screens can be in the way -- the camp menu, which `Escape` leaves,
        and `QUIT TO DOS YES NO`, which `n` declines -- and telling them apart
        by digest turned out to be brittle, because the camp bar is captured
        while "THE PARTY MAKES CAMP..." is still being drawn.  Alternating the
        two keys needs no such knowledge: `n` is not a command on the map or in
        the camp menu, and `Escape` backs out of the quit prompt as well.
        """
        for _ in range(tries):
            if self.bar() == world:
                return
            was = self.bar()
            self.s.key("Escape")
            self.s.settle()
            if self.bar() == was:
                self.s.key("n")
                self.s.settle()
        self.s.shot("leave_camp_stuck", allow_blank=True)
        raise TimeoutError("could not get back to the map from camp")


# --------------------------------------------------------------------------
# The obstacle-2 experiment
# --------------------------------------------------------------------------


def one_step(
    load: str = "A", before: str = "C", after: str = "D", turns: int = 0
) -> dict:
    """Save, act, save again, and diff -- the whole evidence for obstacle 2.

    `turns` right turns before the step, so the party is aimed somewhere it can
    actually go.  Returns the two squares, the two areas, and the byte offsets
    that moved in the parts of the file where an answer can live.
    """
    with claim("one_step") as slot:
        with Session(slot, find_game()) as s:
            por = PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(load)
            a = por.save_game(before)
            for _ in range(turns):
                por.turn_right()
            por.step()
            b = por.save_game(after)
    changed = [i for i in range(len(a)) if a[i] != b[i]]
    # The dense tail from 5121 on is the loaded area's ECL text and scratch:
    # hundreds of bytes move on any action and none of it is party state.  The
    # word array and the state struct after it are where an answer can live.
    return {
        "before": position(a),
        "after": position(b),
        "area_file": (a[0], b[0]),
        "area_id": (area_id(a), area_id(b)),
        "changed_in_array": [i for i in changed if i < 5121],
        "changed_in_struct": [i for i in changed if i >= 12550],
        "changed_total": len(changed),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "command", choices=("check", "one-step"), help="check tools, or run the diff"
    )
    ap.add_argument("--load", default="A")
    ap.add_argument("--turns", type=int, default=0)
    args = ap.parse_args(argv)
    if args.command == "check":
        absent = missing_tools()
        print("tools missing:", ", ".join(absent) if absent else "none")
        try:
            print("game:", find_game())
        except FileNotFoundError as e:
            print("game:", e)
        return 1 if absent else 0
    import pprint

    pprint.pprint(one_step(load=args.load, turns=args.turns))
    return 0


if __name__ == "__main__":
    sys.exit(main())

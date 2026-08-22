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
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
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


class DosboxUnavailable(RuntimeError):
    """One of dosbox, Xvfb, xdotool or ImageMagick is not installed."""


class PoolFull(RuntimeError):
    """Every instance slot is leased by another process."""


def missing_tools() -> list[str]:
    return [t for t in TOOLS if shutil.which(t) is None]


def require_tools() -> None:
    absent = missing_tools()
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

    def __init__(
        self,
        slot: Slot,
        game: Path,
        exe: str = "START.EXE",
        cycles: int = 20000,
        geometry: str = "800x600x24",
    ):
        require_tools()
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
        """
        self.stage(fresh=fresh)
        env = dict(os.environ, DISPLAY=self.display, SDL_AUDIODRIVER="dummy")
        env.pop("XAUTHORITY", None)
        self.xvfb = subprocess.Popen(
            ["Xvfb", self.display, "-screen", "0", self.geometry, "-nolisten", "tcp"],
            stdout=(self.dir / "xvfb.log").open("wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            probe = subprocess.run(
                ["xdotool", "search", "--name", "."], env=env, capture_output=True
            )
            if probe.returncode in (0, 1):
                break
            time.sleep(0.2)
        self.dosbox = subprocess.Popen(
            ["dosbox", "-conf", str(self.dir / "dosbox.conf"), "-noconsole"],
            env=env,
            stdout=(self.dir / "dosbox.log").open("wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        while time.time() < deadline:
            ids = subprocess.run(
                ["xdotool", "search", "--name", "DOSBox"], env=env, capture_output=True
            ).stdout.split()
            if ids:
                self.window = ids[0].decode()
                break
            time.sleep(0.3)
        else:
            self.close()
            raise TimeoutError("DOSBox window never appeared")
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

    def shot(self, name: str) -> Path:
        """Write a PNG of the window into the instance's `shots/`."""
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

# Where the party's square and its area live in `SAVGAM<slot>.DAT`.
# Established by driving the game; see `docs/117-save-conversion.md`.
POS_X = 12801
POS_Y = 12802
POS_FACING = 12803

# The area id, as a `u16le` in the engine's variable array, at the array entry
# for `$49C5`.  `$49F2` (offset 485) carries the same value.  Byte 0 of the
# file -- the "header byte" -- is only the *file* number of the `GEO`/`ECL`
# `.DAX` pair that holds this area, 1 to 8, and several areas share one.
AREA_ID = 395
AREA_FILE = 0

# The DOS facing byte is the C64's doubled: C64 `$49C2` is 0 N, 1 E, 2 S, 3 W.
FACINGS = {0: "N", 2: "E", 4: "S", 6: "W"}


def position(save: bytes) -> tuple[int, int, int]:
    """`(x, y, facing)` out of a `SAVGAM<slot>.DAT`."""
    return save[POS_X], save[POS_Y], save[POS_FACING]


def area_id(save: bytes) -> int:
    """The current area, in the numbering `por/areas.py` uses."""
    return save[AREA_ID] | save[AREA_ID + 1] << 8


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
        self.s.shot("leave_camp_stuck")
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

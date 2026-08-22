#!/usr/bin/env python3
"""A driven DOS Gold Box session: DOSBox on a private X display, unattended.

The C64 side of this project drives VICE through its binary monitor.  DOS has
no such thing -- stock DOSBox 0.74 exposes no debugger and no scripting -- so
the three primitives here are the ones a headless X session gives you:

1. **Input** is XTEST through `xdotool`, aimed at a display nobody else owns.
2. **Output** is a 320x200 window capture.  `output=surface` with `scaler=none`
   and `windowresolution=original` makes the window exactly the emulated
   framebuffer, so a capture is the VGA image pixel for pixel with no scaling
   to undo.
3. **Ground truth is the save file.**  DOS writes plain files into the game's
   `SAVE` directory, so "did that keystroke do anything" is answered by reading
   `SAVGAM<slot>.DAT` back off the host filesystem.  Nothing here has to read
   the screen to know what happened, and that is deliberate: an OCR that is
   wrong once is worse than no OCR at all.

Where the screen *is* needed -- "are we in camp or in the world" -- it is used
as an opaque digest of a strip of pixels, never as text.  A digest cannot be
misread.

**Determinism.** `settle()` waits for two identical consecutive frames rather
than sleeping a guessed interval, and every action that matters is verified by
its effect: `save_game()` waits for the file to change on disk, `leave_camp()`
waits for the command bar to match the digest it recorded on the way in.  The
one thing DOSBox will not give us is a frame counter, so a run is reproducible
in what it produces, not cycle-exact in how long it takes.

**Isolation.** Every instance owns its X display, its game tree, its DOSBox
config and its capture directory, all under `work/dosbox/inst/<n>/`, and the
slot is held by an `fcntl.flock` so a crashed run frees it with no cleanup.
The player's archives are copied, never opened for writing, and nothing here
reads or writes a user-level DOSBox configuration.  Teardown kills the process
groups this instance started and nothing else -- **never a process by name**.

Run time it needs: `dosbox`, `Xvfb`, `xdotool`, and ImageMagick's `import`.
Everything skips cleanly when they are absent.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
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

# Where Donald's Steam copy of Forgotten Realms: The Archives is unpacked.
# Read only, always: a game tree is copied into `work/` before DOSBox sees it.
ARCHIVES = Path(
    os.environ.get(
        "FR_ARCHIVES",
        Path.home() / "Downloads" / "fr-archives",
    )
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

    Returns the directory that holds `START.EXE` -- for Pool of Radiance that
    is `.../games/POOLRAD/GAME/POOLRAD`.  Raises `FileNotFoundError` when the
    archives are not on this machine, which is how the tests skip.
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
    get wrong -- the same reason `docs/123-parallel-sessions.md` chose flock
    for the VICE pool.
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

    def digest(self, x: int = 0, y: int = 0, w: int = 0, h: int = 0) -> str:
        """A short hash of a rectangle -- the way this module compares screens.

        Comparing pixels rather than reading them is the point: a digest is
        never *misread*, only unequal, so a wait can be driven by it safely
        where an OCR result could not be.
        """
        w = w or self.width
        h = h or self.height
        rows = [
            self.px[((y + dy) * self.width + x) * 3 : ((y + dy) * self.width + x + w) * 3]
            for dy in range(h)
        ]
        return hashlib.sha1(b"".join(rows)).hexdigest()[:16]

    def cells(self, row: int, col0: int = 0, ncols: int = 0) -> list[tuple[int, ...]]:
        """The 8x8 character cells of one text row, as ink bitmaps.

        Gold Box DOS draws 40x25 cells of 8x8 pixels into a 320x200 frame, on
        the pixel grid, so a cell is a slice and not a search.  Ink is any
        pixel that is not near-black; the games recolour text freely and the
        glyph is the same shape in every colour.
        """
        ncols = ncols or (self.width // 8 - col0)
        out = []
        for c in range(col0, col0 + ncols):
            bits = []
            for dy in range(8):
                v = 0
                for dx in range(8):
                    o = ((row * 8 + dy) * self.width + c * 8 + dx) * 3
                    lit = self.px[o] + self.px[o + 1] + self.px[o + 2] > 120
                    v = (v << 1) | int(lit)
                bits.append(v)
            out.append(tuple(bits))
        return out


class Glyphs:
    """A bitmap-to-character table **learned at run time**, never shipped.

    The game's font is the game's art.  It does not enter this repository, so
    the table is built by showing the reader a row whose text is already known
    -- a menu the driver just opened -- and is cached under `work/`, which is
    gitignored.  Generate, do not copy.
    """

    def __init__(self, cache: Path | None = None):
        self.cache = cache
        self.table: dict[tuple[int, ...], str] = {}
        if cache and cache.is_file():
            for k, v in json.loads(cache.read_text()).items():
                self.table[tuple(int(p) for p in k.split(","))] = v

    def learn(self, cells: list[tuple[int, ...]], text: str) -> None:
        for cell, ch in zip(cells, text):
            if any(cell):
                self.table[cell] = ch
        if self.cache:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(
                json.dumps({",".join(str(p) for p in k): v for k, v in self.table.items()})
            )

    def read(self, cells: list[tuple[int, ...]]) -> str:
        out = []
        for cell in cells:
            if not any(cell):
                out.append(" ")
            else:
                out.append(self.table.get(cell, "?"))
        return "".join(out).rstrip()


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
cycleup=10
cycledown=20

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

    Use it as a context manager; `close()` is what kills the processes, and it
    kills only the two groups this instance started.
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
        self.glyphs = Glyphs(WORK / "glyphs.json")

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
            CONFIG.format(
                dir=self.dir, stem=self.stem, exe=self.exe, cycles=self.cycles
            )
        )

    @property
    def save_dir(self) -> Path:
        return self.game_dir / "SAVE"

    # -- lifecycle -------------------------------------------------------

    def boot(self, timeout: float = 30.0) -> None:
        self.stage()
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
            if subprocess.run(
                ["xdotool", "search", "--name", "."],
                env=env,
                capture_output=True,
            ).returncode in (0, 1):
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
            r = subprocess.run(
                ["xdotool", "search", "--name", "DOSBox"], env=env, capture_output=True
            )
            ids = r.stdout.split()
            if ids:
                self.window = ids[0].decode()
                break
            time.sleep(0.3)
        else:
            self.close()
            raise TimeoutError("DOSBox window never appeared")
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", self.window],
            env=env,
            capture_output=True,
        )
        subprocess.run(
            ["xdotool", "windowfocus", self.window], env=env, capture_output=True
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
        self.dosbox = self.xvfb = None

    def __enter__(self) -> Session:
        self.boot()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- input and output ------------------------------------------------

    def _env(self) -> dict[str, str]:
        return dict(os.environ, DISPLAY=self.display)

    def key(self, *keys: str, gap: float = 0.25) -> None:
        """Press keys, one at a time, as X keysyms (`a`, `Up`, `Escape`)."""
        for k in keys:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", k],
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

    def settle(self, quiet: float = 0.6, timeout: float = 20.0) -> Screen:
        """Wait until two consecutive captures are identical, and return one.

        Cheaper and far more reliable than sleeping: a screen that is still
        being drawn differs from itself, and one that is finished does not.
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

    def wait_for(self, pred, timeout: float = 20.0) -> bool:
        """Poll `pred(Screen)` until true.  Returns whether it became true."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pred(self.capture()):
                return True
            time.sleep(0.25)
        return False


# --------------------------------------------------------------------------
# Pool of Radiance, driven
# --------------------------------------------------------------------------

# Rows of the 25-row text grid, fixed by the game's screen layout.
STATUS_ROW = 15  # `4,3 N 10:02` and, in camp, `CAMPING`
BAR_ROW = 24  # `AREA CAST VIEW ENCAMP SEARCH LOOK`, or the camp menu

# Offsets into `SAVGAM<slot>.DAT`.  See `docs/117-save-conversion.md`.
POS_X = 12801
POS_Y = 12802
POS_FACING = 12803


class PoolOfRadiance:
    """The keystroke protocol of DOS Pool of Radiance, verified by effect.

    Two things about the menus that cost an hour to learn and are worth
    writing down:

    * **The camp menu's EXIT is exit to DOS**, not exit to the map.  `Escape`
      is what leaves camp; `EXIT` asks `QUIT TO DOS YES NO` and `N` backs out
      of it.
    * **The first keystroke after a screen change is swallowed**, exactly as
      the C64 side of this project found.  Every step here therefore checks
      that the screen it wanted actually arrived and presses again if not.
    """

    def __init__(self, session: Session):
        self.s = session

    # -- screen predicates, as digests rather than text ------------------

    def bar(self) -> str:
        return self.s.capture().digest(0, BAR_ROW * 8, 320, 8)

    def status_text(self) -> str:
        """The status line, if the glyph table has been taught its letters."""
        scr = self.s.settle()
        return self.s.glyphs.read(scr.cells(STATUS_ROW, 16, 24))

    # -- getting into the game -------------------------------------------

    def to_main_menu(self, timeout: float = 60.0) -> None:
        """Press Return past the title screens until the menu stops changing."""
        deadline = time.time() + timeout
        seen: set[str] = set()
        while time.time() < deadline:
            self.s.key("Return")
            scr = self.s.settle()
            d = scr.digest(0, BAR_ROW * 8, 320, 8)
            if d in seen:
                return
            seen.add(d)
        raise TimeoutError("never reached the main menu")

    def load_game(self, letter: str) -> None:
        """`LOAD SAVED GAME` -> a slot letter.  Waits for the world to appear."""
        before = self.bar()
        self.s.key("l")
        self.s.settle()
        self.s.key(letter.lower())
        if not self.s.wait_for(
            lambda scr: scr.digest(0, BAR_ROW * 8, 320, 8) != before, timeout=40
        ):
            raise TimeoutError(f"slot {letter} never loaded")
        self.s.settle()
        self.world_bar = self.bar()

    # -- the world --------------------------------------------------------

    def step(self) -> None:
        self.s.key("Up")
        self.s.settle()

    def turn_left(self) -> None:
        self.s.key("Left")
        self.s.settle()

    def turn_right(self) -> None:
        self.s.key("Right")
        self.s.settle()

    # -- saving, which is the whole point ---------------------------------

    def save_game(self, letter: str, timeout: float = 40.0) -> bytes:
        """Encamp, save to `letter`, leave camp, and return the file's bytes.

        Verified by effect at both ends: the save is not believed until
        `SAVGAM<letter>.DAT` changes on disk, and camp is not believed to be
        over until the command bar is the one that was there before encamping.
        """
        path = self.s.save_dir / f"SAVGAM{letter.upper()}.DAT"
        was = path.read_bytes() if path.is_file() else None

        world = self.bar()
        self.s.key("e")
        if not self.s.wait_for(
            lambda scr: scr.digest(0, BAR_ROW * 8, 320, 8) != world, timeout=timeout
        ):
            raise TimeoutError("ENCAMP did not open the camp menu")
        camp = self.s.settle().digest(0, BAR_ROW * 8, 320, 8)

        self.s.key("s")
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

        self.leave_camp(world, camp)
        return data

    def leave_camp(self, world: str, camp: str, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            now = self.bar()
            if now == world:
                return
            if now == camp:
                self.s.key("Escape")
            else:
                # Anything else at this point is `QUIT TO DOS YES NO`.
                self.s.key("n")
            self.s.settle()
        raise TimeoutError("could not get back to the map from camp")

    # -- reading the party out of a save ----------------------------------

    @staticmethod
    def position(save: bytes) -> tuple[int, int, int]:
        """`(x, y, facing)` out of a `SAVGAM?.DAT`."""
        return save[POS_X], save[POS_Y], save[POS_FACING]


def one_step(letter_before: str = "C", letter_after: str = "D") -> dict:
    """The obstacle-2 experiment: save, take one step, save, and diff.

    Returns the two positions and the byte offsets that changed, which is the
    whole evidence the DOS position hunt needs.
    """
    with claim("one_step") as slot:
        with Session(slot, find_game()) as s:
            por = PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game("A")
            before = por.save_game(letter_before)
            por.step()
            after = por.save_game(letter_after)
    changed = [i for i in range(len(before)) if before[i] != after[i]]
    return {
        "before": PoolOfRadiance.position(before),
        "after": PoolOfRadiance.position(after),
        "changed": changed,
    }


if __name__ == "__main__":
    import pprint

    pprint.pprint(one_step())

#!/usr/bin/env python3
"""A hand-driven DOS Curse of the Azure Bonds session, one command at a time.

`tools/dosbox.py` drives Pool of Radiance by *digest*: every screen it has to
recognise was measured once and is compared as a hash.  That works for a menu
path somebody has already walked.  It cannot walk a new one, and Curse's camp
menus -- MEMORIZE, REST, the spell lists -- had never been walked at all when
this was written (#113).

So this is the other half of the harness: a session that boots, stays up, and
executes commands out of a text file, writing a screenshot after each one.  The
agent driving it *looks at the picture*, decides the next key, and appends a
line.  Nothing here reads a word off the screen either -- a person does, which
is the one reader that can be trusted with a menu nobody has mapped.

    tools/doscurse.py console --game CURSE --note "issue 113"

writes `work/dosbox/inst/<n>/console.cmd` (the input), `console.log` (what it
did) and `shots/` (what it saw), and holds the slot until `quit` or `--minutes`
runs out.  The lifetime cap is deliberate: an abandoned console would hold a
pool slot and an X display for as long as the machine stayed up.

Commands, one per line, blank lines and `#` comments ignored:

| line | what it does |
|---|---|
| `key Return` | one or more X keysyms, pressed in order |
| `type WORD` | `xdotool type`, for a name or a number |
| `sleep 2` | wait, when the game is drawing something long |
| `settle` | wait for two identical frames, then shoot |
| `shot name` | screenshot to `shots/NNN-name.png` and `-big.png` |
| `bar` | log the bottom bar's `ink`, `glyphs` and whole-frame digests |
| `files` | log the game's `SAVE` directory, with sizes and mtimes |
| `copy label` | copy `SAVE` to `work/curse/<label>/`, the specimen |
| `restart` | stop and start DOSBox, keeping the staged tree and its saves |
| `quit` | close the session and release the slot |

Every command is followed by a capture, so `shots/last.png` and
`shots/last-big.png` are always the frame after the most recent line.  The
`-big.png` is a 3x point-sampled blow-up, because 320x200 text is what the
agent has to read and a nearest-neighbour enlargement is legible where the
original is not.

The player's archives are read only, as everywhere in this harness: the game
tree is copied into the instance directory before DOSBox sees it, and a
specimen is copied *out* of that tree, never out of the archives.

    tools/doscurse.py pane --slot 0 --rect view --last 8

is the reading half, and it is offline: it crops one named region out of the
last few shots and montages them, so eight steps of a walk are one picture
instead of eight.  `--rect text --events` instead *lists* the shots whose
message pane is not blank, which is how a driven walk finds the square that
made the game say something without a person looking at every frame of it.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import dosbox  # noqa: E402
from tools.dosbox import BAR, Screen, Session, claim, find_game  # noqa: E402

#: Where a copied-out specimen lands.  Gitignored, like everything derived
#: from the game's bytes.
SPECIMENS = REPO / "work" / "curse"

#: The named regions of a 320x200 Gold Box frame, as ImageMagick geometry.
#: Measured off Secret of the Silver Blades and shared with Curse of the Azure
#: Bonds, which draws the same furniture in the same places.
PANES = {
    "view": "112x114+8+5",       # the 3D view, or the area map when it is up
    "coord": "130x14+126+114",   # `3,12 S 00:09` -- square, facing, clock
    "text": "320x58+0+130",      # the message pane, blank when nothing is said
    "bar": "320x12+0+188",       # MOVE AREA CAST VIEW ENCAMP SEARCH LOOK
    "top": "320x128+0+0",        # view, roster and coordinate together
    "all": "320x200+0+0",
}


def shot_files(slot: int, last: int, names: list[str]) -> list[Path]:
    """The shots to read: the named ones, or the last `last` in order.

    `last.png` and `last-big.png` are skipped -- they are copies of a shot
    already in the list, and a montage that repeats its own final frame reads
    as one step more than the walk actually took.
    """
    shots = (REPO / "work" / "dosbox" / "inst" / str(slot) / "shots")
    every = sorted((p for p in shots.glob("*.png")
                    if not p.stem.startswith("last")
                    and not p.stem.endswith("-big")),
                   key=lambda p: p.stat().st_mtime)
    if names:
        return [p for p in every if any(n in p.stem for n in names)]
    return every[-last:]


def pane(slot: int, rect: str, last: int, names: list[str], out: Path,
         scale: int, events: bool) -> int:
    """Crop `rect` out of each shot; montage them, or list the ones with ink."""
    files = shot_files(slot, last, names)
    if not files:
        print(f"no shots under work/dosbox/inst/{slot}/shots")
        return 1
    geometry = PANES[rect]
    if events:
        from PIL import Image
        w, h, x, y = (int(v) for v in
                      geometry.replace("x", " ").replace("+", " ").split())
        for path in files:
            box = Image.open(path).convert("L").crop((x, y, x + w, y + h))
            lit = sum(1 for p in box.getdata() if p > 32)
            if lit:
                print(f"{path.name:28s} {lit:5d} lit pixels in {rect}")
        return 0
    tiles = []
    for i, path in enumerate(files):
        tile = out.parent / f".pane-{i:03d}.png"
        subprocess.run(["convert", str(path), "-crop", geometry, "+repage",
                        "-filter", "point", "-resize", f"{scale * 100}%",
                        "-bordercolor", "grey40", "-border", "2", str(tile)],
                       check=True, capture_output=True)
        tiles.append(tile)
    subprocess.run(["montage", *[str(t) for t in tiles], "-tile", "4x",
                    "-geometry", "+2+2", "-background", "black", str(out)],
                   check=True, capture_output=True)
    for tile in tiles:
        tile.unlink()
    print(f"{out}  ({', '.join(p.stem for p in files)})")
    return 0


def enlarge(src: Path, factor: int = 3) -> Path | None:
    """A point-sampled blow-up beside `src`, or None if ImageMagick failed.

    Nearest neighbour, never a smooth filter: the thing being read is 8x8
    bitmap text, and any interpolation turns it to porridge.
    """
    out = src.with_name(src.stem + "-big.png")
    r = subprocess.run(
        ["convert", str(src), "-filter", "point", "-resize", f"{factor * 100}%",
         str(out)], capture_output=True)
    return out if r.returncode == 0 else None


class Console:
    """One booted session, driven line by line out of a file."""

    def __init__(self, session: Session, cmds: Path, log: Path):
        self.s = session
        self.cmds = cmds
        self.log = log
        self.n = 0

    # -- output ---------------------------------------------------------

    def say(self, text: str) -> None:
        with self.log.open("a") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    def shoot(self, name: str = "last") -> None:
        """Write `shots/NNN-name.png` and refresh `shots/last.png`."""
        shots = self.s.dir / "shots"
        shots.mkdir(exist_ok=True)
        out = shots / f"{self.n:03d}-{name}.png"
        subprocess.run(
            ["import", "-window", self.s.window, "-depth", "8", str(out)],
            env=self.s.env(), check=True, capture_output=True)
        enlarge(out)
        for tail in ("", "-big"):
            src = out.with_name(out.stem + tail + ".png")
            if src.is_file():
                shutil.copyfile(src, shots / f"last{tail}.png")
        self.say(f"  shot {out.name}")

    def describe(self) -> None:
        screen: Screen = self.s.capture()
        self.say(f"  frame={screen.digest()} bar.ink={screen.ink(BAR)} "
                 f"bar.glyphs={screen.glyphs(BAR)}")

    # -- commands -------------------------------------------------------

    def do(self, line: str) -> bool:
        """Run one command line.  Returns False when it was `quit`."""
        word, _, rest = line.partition(" ")
        rest = rest.strip()
        self.say(f"[{self.n:03d}] {line}")
        if word == "key":
            self.s.key(*rest.split())
        elif word == "type":
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--window",
                            self.s.window, rest],
                           env=self.s.env(), check=True, capture_output=True)
        elif word == "sleep":
            time.sleep(float(rest or 1))
        elif word == "settle":
            self.s.settle(timeout=float(rest or 30))
        elif word == "shot":
            self.shoot(rest or "shot")
            return True
        elif word == "bar":
            self.describe()
            return True
        elif word == "files":
            for p in sorted(self.s.save_dir.glob("*")):
                st = p.stat()
                self.say(f"  {p.name:16s} {st.st_size:6d} "
                         f"{time.strftime('%H:%M:%S', time.localtime(st.st_mtime))}")
            return True
        elif word == "copy":
            dest = SPECIMENS / (rest or f"snap{self.n:03d}")
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.s.save_dir, dest)
            self.say(f"  copied {self.s.save_dir} -> {dest}")
            return True
        elif word == "restart":
            self.s.restart()
        elif word == "quit":
            self.say("  quitting")
            return False
        else:
            self.say(f"  ? unknown command {word!r}")
            return True
        time.sleep(0.4)
        self.shoot()
        self.describe()
        return True

    def run(self, minutes: float) -> None:
        deadline = time.time() + minutes * 60
        seen = 0
        self.say(f"console up: display={self.s.display} dir={self.s.dir}")
        self.shoot("boot")
        self.describe()
        while time.time() < deadline:
            lines = [ln.strip() for ln in
                     self.cmds.read_text().splitlines()] if self.cmds.is_file() else []
            if len(lines) <= seen:
                time.sleep(0.25)
                continue
            for line in lines[seen:]:
                seen += 1
                if not line or line.startswith("#"):
                    continue
                self.n += 1
                try:
                    if not self.do(line):
                        return
                except Exception as exc:                # keep the session up
                    self.say(f"  ! {type(exc).__name__}: {exc}")
        self.say("lifetime expired")


def console(game: str, note: str, minutes: float, exe: str = "START.EXE") -> int:
    with claim(note or "doscurse") as slot:
        cmds = slot.dir / "console.cmd"
        log = slot.dir / "console.log"
        cmds.write_text("")
        log.write_text("")
        print(f"slot {slot.n} display {slot.display}")
        print(f"commands: {cmds}")
        print(f"log:      {log}")
        print(f"shots:    {slot.dir / 'shots'}")
        with Session(slot, find_game(game), exe=exe) as s:
            Console(s, cmds, log).run(minutes)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("console", "check", "pane"))
    ap.add_argument("--game", default="CURSE", help="game directory stem")
    ap.add_argument("--exe", default="START.EXE")
    ap.add_argument("--note", default="doscurse")
    ap.add_argument("--minutes", type=float, default=120.0,
                    help="lifetime cap, so an abandoned console frees its slot")
    ap.add_argument("--slot", type=int, default=0, help="pane: which instance")
    ap.add_argument("--rect", default="view", choices=sorted(PANES),
                    help="pane: which region of the frame")
    ap.add_argument("--last", type=int, default=8,
                    help="pane: how many of the most recent shots")
    ap.add_argument("--shots", nargs="*", default=[],
                    help="pane: shot name fragments, instead of --last")
    ap.add_argument("--scale", type=int, default=2, help="pane: blow-up factor")
    ap.add_argument("--events", action="store_true",
                    help="pane: list the shots with ink in the region")
    ap.add_argument("--out", default=str(REPO / "work" / "pane.png"))
    args = ap.parse_args(argv)
    if args.command == "pane":
        return pane(args.slot, args.rect, args.last, args.shots,
                    Path(args.out), args.scale, args.events)
    if args.command == "check":
        absent = dosbox.missing_tools()
        print("tools missing:", ", ".join(absent) if absent else "none")
        try:
            print("game:", find_game(args.game))
        except FileNotFoundError as exc:
            print("game:", exc)
            return 1
        return 1 if absent else 0
    return console(args.game, args.note, args.minutes, args.exe)


if __name__ == "__main__":
    sys.exit(main())

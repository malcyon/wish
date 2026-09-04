#!/usr/bin/env python3
"""Drive DOS Pools of Darkness under DOSBox and take differential saves.

The Pool of Radiance driver in `tools/dosbox.py` does not fit this title
unchanged, for three reasons that are all about the game rather than the
harness:

* the launcher is `START.BAT`, not `START.EXE`, and it runs `STARTUP` and
  `CONTROL` before the game proper;
* the container is `SAVGAM<slot>.PTY` and there is a `VAULT<slot>.DAT`
  beside it, so `Session.save_file` names the wrong file;
* the archive's copy asks for a copy-protection answer, which it accepts
  from any keys followed by Return.

Everything else -- the instance pool, the private X display, the settle-on-
identical-frames discipline, the "ground truth is the file on disk" rule --
is `tools/dosbox.py`'s and is used as it stands.

A run is a list of steps given on the command line, pressed in order once the
main menu is up.  A step is one of three things:

* an `xdotool` keysym -- `Return`, `Escape`, `Up`, `c` -- pressed once;
* `@x,y`, a double-click at that pixel of the emulated 320x200 screen;
* `!name`, which presses nothing and copies the game's whole `SAVE` directory
  into the output directory under that prefix.

So a differential pair is one boot and one command line::

    tools/dospod.py --out work/p175/diff1 Escape c '!C' Right Escape c '!D'

Every step is shot and its screen digest printed, so a run that went somewhere
unexpected can be read back afterwards without re-driving it.

Written for `#175 (Decode the first 1024 bytes of the Pools of Darkness saved
game)`, whose difficulty was that both shipped containers are a party that has
never been played: every byte of the 1024 is either zero or one of the six the
new-game initialiser writes, so only a save the engine wrote after a step can
separate one field from another.  Eight engine-written containers came out of
this tool and they are what turned the code reading of the square, the facing
and the clock into a measurement --
`tools/dossavcensus.py --title pools-of-darkness work/p175` reads them back
and `docs/141-dos-savegame.md` has what they said.

**Never point this at the archives.** `Session.stage` copies the game tree
into the instance directory and the archives are opened read only.
"""

from __future__ import annotations

import argparse
import atexit
import pathlib
import signal
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import dosbox  # noqa: E402

#: The game directory inside the player's archives.  `dosbox.find_game` looks
#: for `START.EXE` and this title ships `STARTUP.EXE` and a `START.BAT`, so
#: the search is repeated here rather than the shared one loosened.
STEM = "DARKNESS"


def find_game(stem: str = STEM) -> pathlib.Path:
    """The directory holding `START.BAT` for `stem`, inside the archives."""
    if not dosbox.ARCHIVES.is_dir():
        raise FileNotFoundError(f"no archives at {dosbox.ARCHIVES}")
    for collection in sorted(dosbox.ARCHIVES.iterdir()):
        games = collection / "games"
        if not games.is_dir():
            continue
        for entry in sorted(games.iterdir()):
            inner = entry / "GAME" / stem
            if (inner / "START.BAT").is_file():
                return inner
    raise FileNotFoundError(f"no DOS {stem} under {dosbox.ARCHIVES}")


def to_main_menu(session: dosbox.Session, tries: int = 30) -> str:
    """Press Escape past the title screens until the screen stops changing.

    **Escape rather than Return**, because Return on the menu the title
    sequence ends at selects `CREATE NEW CHARACTER` and walks straight into
    a stat roll -- which is what a `to_main_menu` copied from the Pool of
    Radiance driver does here.  Escape advances a title screen and does
    nothing on the menu, so "the screen stopped changing" and "we have
    arrived" become the same statement.
    """
    seen: list[str] = []
    for _ in range(tries):
        session.key("Escape")
        time.sleep(0.6)
        seen.append(session.settle(quiet=0.5, timeout=8.0).digest())
        if len(seen) >= 3 and seen[-1] == seen[-2] == seen[-3]:
            return seen[-1]
    raise TimeoutError("never reached a screen Escape does not change")


def double_click(session: dosbox.Session, x: int, y: int) -> None:
    """Point at (x, y) in the emulated 320x200 screen and double-click.

    The manual is explicit that a command is given either by "the highlighted
    letter in that command" or by the mouse, and the highlighted letter is not
    always the first one -- so the mouse is the addressing scheme that needs no
    guessing about which letter a menu line answers to.  `output=surface` with
    `scaler=none` makes the window exactly the framebuffer, so a pixel in a
    capture is a pixel here.
    """
    env = session.env()
    # XTEST, not `--window`.  `xdotool key --window` sends a synthetic event
    # and SDL 1.2 takes it; `xdotool click --window` sends a synthetic button
    # event and SDL ignores it, so the pointer has to be moved for real and
    # the button pressed for real.  Under a bare Xvfb there is no window
    # manager, so the window is where DOSBox put it and its origin has to be
    # asked for rather than assumed.
    geo = subprocess.run(["xdotool", "getwindowgeometry", "--shell",
                          session.window], env=env, check=True,
                         capture_output=True, text=True).stdout
    pos = dict(line.split("=", 1) for line in geo.split() if "=" in line)
    ox, oy = int(pos["X"]), int(pos["Y"])
    subprocess.run(["xdotool", "mousemove", "--sync", str(ox + x), str(oy + y)],
                   env=env, check=True, capture_output=True)
    time.sleep(0.3)
    subprocess.run(["xdotool", "click", "--repeat", "2", "--delay", "80", "1"],
                   env=env, check=True, capture_output=True)


def snapshot(session: dosbox.Session, out: pathlib.Path, tag: str) -> None:
    """Copy every file in the game's `SAVE` directory into `out`, prefixed."""
    out.mkdir(parents=True, exist_ok=True)
    for p in sorted(session.save_dir.iterdir()):
        (out / f"{tag}-{p.name}").write_bytes(p.read_bytes())


#: What one step of a run does, as `(kind, argument)`.  Its own function so
#: that the three prefixes can be tested without an emulator: a run is only
#: reproducible if `!C` snapshots rather than pressing the key `!C`, and that
#: is a parse rather than a drive.
def step_kind(step: str) -> "tuple[str, object]":
    """`("snapshot", name)`, `("click", (x, y))` or `("key", keysym)`."""
    if step.startswith("!"):
        return "snapshot", step[1:]
    if step.startswith("@"):
        x, y = (int(v) for v in step[1:].split(","))
        return "click", (x, y)
    return "key", step


def drive(out: pathlib.Path, script: list[str], presses: int = 30,
          gap: float = 1.0) -> int:
    """Boot, reach the main menu, then run `script` with a shot per step.

    One boot per experiment; the harness costs about a minute of it, so a
    differential pair goes in one run rather than two.
    """
    game = find_game()
    slot = dosbox.claim("dospod drive")
    session = dosbox.Session(slot, game, exe="START.BAT")

    def cleanup(*_: object) -> None:
        session.close()
        slot.release()

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    out.mkdir(parents=True, exist_ok=True)
    session.boot()
    print("menu:", to_main_menu(session, presses), flush=True)
    session.shot("menu", allow_blank=True)
    for i, key in enumerate(script):
        kind, argument = step_kind(key)
        if kind == "snapshot":
            snapshot(session, out, argument)
            print(f"{i:02d} snapshot {argument}", flush=True)
            continue
        if kind == "click":
            double_click(session, *argument)
        else:
            session.key(argument)
        time.sleep(gap)
        screen = session.settle(quiet=0.5, timeout=10.0)
        session.shot(f"step{i:02d}-" + key.replace(",", "x"),
                     allow_blank=True)
        print(f"{i:02d} {key:10s} {screen.digest()}", flush=True)
    snapshot(session, out, "final")
    print("shots in", slot.dir / "shots", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "work" / "p175" / "run",
                    help="where the SAVE directory snapshots go")
    ap.add_argument("--presses", type=int, default=30,
                    help="how many Escapes to spend reaching the main menu")
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("keys", nargs="*",
                    help="steps to run once the main menu is up: an xdotool "
                         "keysym, @x,y for a double-click, or !name to "
                         "snapshot the SAVE directory instead of pressing "
                         "anything")
    args = ap.parse_args(argv)
    return drive(args.out, args.keys, args.presses, args.gap)


if __name__ == "__main__":
    raise SystemExit(main())

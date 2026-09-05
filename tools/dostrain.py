#!/usr/bin/env python3
"""Drive DOS Pool of Radiance's TRAIN CHARACTER and keep every record the
trainer writes, so a level-up can be diffed across the 285-byte record.

`#249 (Build a DOS party from creation and level it ourselves, so DOS
measurements rest on records we watched being written)` wants what `#10
(Finish the high-level test party)` got on the C64: twenty-nine level-ups,
each one diffed against the record as it stood a moment before.  This is the
DOS side of that.

**Almost nothing has to be walked to, and the exception is the part that
matters.**  `tools/dostrainprobe.py` measured that Pool of Radiance gates
TRAIN CHARACTER on the same word Curse of the Azure Bonds and Secret of the
Silver Blades do -- file offset `0xD51` of `SAVGAM<slot>.DAT`, the training
hall's maximum level -- and poking it does put the menu item in the party menu
wherever the party stands.  **But pressing `T` at that menu outside a hall
does nothing at all**, so the hall still has to be entered; the gate only
decides whether the line is drawn.  What this tool does instead is put the
party down one square from the hall's door with `--at` and step in.

**Experience and gold are written into the record before the run, and that is
deliberate.**  `.claude/rules/testing.md` draws the line: editing an *input*
and watching the engine compute from it is a valid experiment, because the
engine does not care how a byte got there; reading back a stored value we
wrote and calling it the game's arithmetic is not.  So the experience total
is ours and proves nothing, and **the hit points, THAC0, saving throws, spell
slots and thief skills the trainer writes are the engine's** and are the
measurement.

`--steps` presses a list from the loaded party menu, shooting each screen,
snapshotting `SAVE/` on `!tag`, and `SAVE/` is snapshotted before and after the
whole list whatever the list does -- so a level-up always has a before and an
after.  `--at` puts the party where the steps expect it and `--save-to` makes
the game write a slot at the end.

**The route into the hall, in step form.**  `Up` from `(7,2)` facing west
enters `(6,2)` and loads area 11; then `Right`, `Up`, `Up` reaches `(6,0)` and
`Left`, `Up` is the clerics' school at `(5,0)` (`Right`, `Up` the magic users'
at `(7,0)`).  `y` opens the party menu, `@End` moves the roster highlight, `t`
trains whoever is highlighted and `y` accepts.

    tools/dostrain.py --party $WISH_SPECIMENS/por-dos/WISH-SPEC-por-party-l1-intown \\
        --slot E --at 7,2,W --xp 300000 --gold 20000 --steps \\
        Up '~10' Right '~2' Up '~3' Up '~3' Left '~2' Up '~5' y '~6' \\
        '@End' t '~5' y '~7' s '~2' f '~7'

Output goes under `work/`, never into the repository.  **Copy anything worth
keeping into `$WISH_SPECIMENS` with `tools/specimens.py add` before the slot
goes down.**
"""

from __future__ import annotations

import argparse
import atexit
import pathlib
import shutil
import signal
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos  # noqa: E402
from goldbox import dos_savegame as _sav  # noqa: E402
from tools import dosbox  # noqa: E402
from tools.dosparty import wipe_roster  # noqa: E402
from tools.dostrainprobe import install  # noqa: E402


def snapshot(session: dosbox.Session, out: pathlib.Path, tag: str) -> None:
    """Copy every character record and save in `SAVE/` under a tag."""
    d = out / "snaps" / tag
    d.mkdir(parents=True, exist_ok=True)
    for p in sorted(session.save_dir.iterdir()):
        if p.name.upper() == "EXPLORED.DAT":
            continue
        shutil.copy(p, d / p.name)


def report(folder: pathlib.Path) -> list[str]:
    """One line per character record in a snapshot."""
    lines = []
    for p in sorted(folder.glob("CHRDAT*.SAV")):
        c = dos.read_character(p)
        lines.append(
            f"{p.name} {c.name:8s} lvl={c.get('level'):2d} "
            f"classes={c.class_levels} xp={c.get('experience'):7d} "
            f"hp={c.get('hp_max'):3d} rolled={c.get('hp_rolled'):3d} "
            f"thac0={c.get('thac0_base'):3d} gold={c.get('gold'):6d}")
    return lines


class Runner:
    def __init__(self, session: dosbox.Session, out: pathlib.Path):
        self.s = session
        self.out = out
        self.n = 0

    def step(self, step: str, gap: float = 1.0) -> str:
        """One step: a keysym, `#text`, `~seconds`, `@key` or `!tag`.

        `@key` presses until the screen changes, up to five times.  **The
        first keypress after a screen is redrawn is reliably swallowed here**
        -- `docs/70-driving-the-game.md` says the same of the C64 -- and a
        lost `End` in the party roster puts the trainer on the character one
        line above the one the run meant, which is a measurement of somebody
        else.  Two runs of the experience-clamp test were spent that way.
        """
        if step.startswith("!"):
            snapshot(self.s, self.out, step[1:])
            return "snapshot"
        if step.startswith("@"):
            key = step[1:]
            before = self.s.capture().digest()
            for _ in range(5):
                self.s.key(key)
                time.sleep(gap)
                screen = self.s.settle(quiet=0.5, timeout=20.0)
                if screen.digest() != before:
                    break
            self.s.shot(f"{self.n:03d}-at-{key}", allow_blank=True)
            self.n += 1
            return screen.digest()
        if step.startswith("~"):
            time.sleep(float(step[1:]))
        elif step.startswith("#"):
            for ch in step[1:]:
                self.s.key("space" if ch == " " else ch)
        else:
            self.s.key(step)
        time.sleep(gap)
        screen = self.s.settle(quiet=0.5, timeout=20.0)
        safe = "".join(c if c.isalnum() else "_" for c in step)
        self.s.shot(f"{self.n:03d}-{safe}", allow_blank=True)
        self.n += 1
        return screen.digest()


def move_to(save: pathlib.Path, spec: str) -> None:
    """Poke the party's saved position: `X,Y,FACING`, facing one of NESW.

    `docs/70-driving-the-game.md`: the training hall is area 11, which has no
    map of its own -- it reuses New Phlan's `GEO00` -- and only script ids 10
    at `(6,1)`/`(6,2)` and 17 at `(9,0)` reach it.  So a party put down at
    `(7,2)` facing **west** is one step from the hall: stepping forward enters
    `(6,2)` and fires the script.

    **Not `(6,2)` itself.**  A save dropped there and stepped east arrives at
    `(7,2)` with nothing happening, measured -- `ECL0B` dispatches on the
    *departing* square's attribute byte, so a party that did not walk onto
    `(6,2)` has nothing to dispatch on, exactly as a fasttravel has not.  The
    poke has to land one square short and let the party walk the last one.
    """
    x, y, facing = spec.split(",")
    data = bytearray(save.read_bytes())
    data[_sav.POS_X] = int(x)
    data[_sav.POS_Y] = int(y)
    data[_sav.POS_FACING] = "NESW".index(facing.strip().upper()) \
        * _sav.FACING_SCALE
    save.write_bytes(bytes(data))


def open_loaded(party: pathlib.Path, out: pathlib.Path, letter: str,
                level: int | None, xp: int | None, gold: int | None,
                at: str | None = None
                ) -> tuple[dosbox.Session, dosbox.Slot]:
    """Stage, install the poked party, boot, and LOAD SAVED GAME it."""
    out.mkdir(parents=True, exist_ok=True)
    slot = dosbox.claim("issue249 training")
    session = dosbox.Session(slot, dosbox.find_game())

    def cleanup(*_: object) -> None:
        session.close()
        slot.release()

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    session.stage(fresh=True)
    shutil.rmtree(session.dir / "shots", ignore_errors=True)
    (session.dir / "shots").mkdir(parents=True, exist_ok=True)
    wipe_roster(session.save_dir)
    install(party, session.save_dir, letter, level, xp, gold)
    if at:
        move_to(session.save_dir / f"SAVGAM{letter.upper()}.DAT", at)
    session.boot(fresh=False)
    dosbox.PoolOfRadiance(session).to_main_menu()
    session.key("l")
    time.sleep(1.0)
    session.settle(quiet=0.5, timeout=15.0)
    session.key(letter.lower())
    time.sleep(4.0)
    session.settle(quiet=0.8, timeout=60.0)
    session.shot("000-loaded")
    return session, slot


def collect(session: dosbox.Session, out: pathlib.Path) -> None:
    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    for png in sorted((session.dir / "shots").glob("*.png")):
        shutil.copy(png, shots / png.name)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--party", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "work" / "issue249" / "train")
    ap.add_argument("--slot", default="C")
    ap.add_argument("--level", type=lambda s: int(s, 0), default=None,
                    help="what to write at 0xD51, the hall's maximum level; "
                         "omitted leaves the save byte for byte")
    ap.add_argument("--at", default=None, metavar="X,Y,FACING",
                    help="poke the party's saved position, e.g. 6,2,E -- "
                         "(6,2) facing east is one step from the training hall")
    ap.add_argument("--xp", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--gold", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--steps", nargs="*", default=None,
                    help="steps to press from the loaded party menu")
    ap.add_argument("--save-to", default=None,
                    help="after the steps, ENCAMP > SAVE to this slot letter")
    args = ap.parse_args(argv)

    session, slot = open_loaded(args.party, args.out, args.slot, args.level,
                                args.xp, args.gold, args.at)
    runner = Runner(session, args.out)
    try:
        snapshot(session, args.out, "before")
        for step in args.steps or []:
            digest = runner.step(step, args.gap)
            print(f"{step:14s} {digest}", flush=True)
        if args.save_to:
            game = dosbox.PoolOfRadiance(session)
            data = game.save_game(args.save_to)
            print(f"saved {len(data)} bytes to slot {args.save_to}", flush=True)
            session.shot("999-saved", allow_blank=True)
        snapshot(session, args.out, "after")
        collect(session, args.out)
    finally:
        session.close()
        slot.release()
    for tag in ("before", "after"):
        print(f"-- {tag}")
        for line in report(args.out / "snaps" / tag):
            print(" ", line)
    print("shots in", args.out / "shots", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

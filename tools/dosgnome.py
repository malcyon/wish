#!/usr/bin/env python3
"""Roll a character in DOS Pool of Radiance's own creation screens and read
the `.SPC` records the engine writes for it.

`#84 (Roll a gnome in DOS and read the two innate effect ids nobody has seen)`
is the reason this exists.  `goldbox.dos.INNATE_EFFECTS` holds eight ids, six
of them measured over three races and 32 archive files and two -- **18** and
**48** -- carried by nobody in any save the archives hold, because nobody in
the archives is a gnome.  The only way to stop guessing is to make the engine
write a gnome's records itself, and the engine only does that at character
creation.

**Nothing is loaded from a saved game.**  `to_main_menu()` lands on the party
menu with an empty party, `c` is CREATE NEW CHARACTER there, and `s` is SAVE
CURRENT GAME and works with the party half-built -- so a run needs no saved
game, and the engine's six-character capacity check is never in the way.  The
ground truth is the host filesystem: `CHRDAT<slot><n>.SPC` is nine bytes per
effect record and this reads them off disk, not off the screen.

**Two menu families, and telling them apart is the whole of the driving.**
The creation screens (race, gender, class, alignment) are *vertical list*
menus, and this game's generic list menu ignores the arrow keys: `Home` and
`End` move the highlight within the page, `N`/`P` and `PgDn`/`PgUp` turn the
page, `E` and `Escape` leave, and **any other key picks whatever is
highlighted**.  A run that presses `Down` and then `Return` therefore picks
the first entry and looks exactly like the game refusing the second.  The
command bars (`KEEP`, `EXIT`, `SAVE`) are the other family and answer to the
highlighted letter.  So a list is addressed by `Home` plus n presses of the
key that moves the highlight one line, and every step is screenshotted so a
run that went somewhere nobody can name can be read back afterwards.

Two modes:

* the default, a list of steps pressed from the main menu, shooting each.  A
  step is an `xdotool` keysym, `#TEXT` to type a string a character at a
  time, `~n` to wait n seconds, or `!tag` to copy the whole `SAVE` directory
  into the output under that prefix.  This is how the creation flow was
  mapped, and it is how the next unmapped screen will be.
* `--interactive` boots and then executes step lines appended to a command
  file, so one boot maps many screens instead of one.  `--quit` on a line of
  its own ends it.

    tools/dosgnome.py c '~2' Home Down Down Return
    tools/dosgnome.py --interactive --cmd work/issue84/cmd.txt

Output -- screenshots, `SAVE` snapshots and the record dump -- goes under
`work/issue84/`, never into the repository: a saved game is the game's data.
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

from tools import dosbox  # noqa: E402

#: Where a run's screenshots, `SAVE` snapshots and reports land.
OUT = REPO / "work" / "issue84"

#: One `.SPC` record.  Nine bytes: the effect id, four of payload, and a
#: four-byte far pointer the loader rebuilds (`goldbox.dos.EFFECT_NEXT_NULL`).
EFFECT_SIZE = 9


def records(data: bytes) -> list[bytes]:
    """Split a `.SPC` file into whole nine-byte records.

    A short tail is dropped rather than padded: the record count comes from
    the file's length, so a file that is not a multiple of nine is a fact
    about the run and not something to round away.
    """
    return [data[i:i + EFFECT_SIZE] for i in range(0, len(data), EFFECT_SIZE)
            if len(data[i:i + EFFECT_SIZE]) == EFFECT_SIZE]


def describe(path: pathlib.Path) -> list[str]:
    """One line per `.SPC` record: id, the four payload bytes, the pointer."""
    out = []
    for n, rec in enumerate(records(path.read_bytes()), start=1):
        out.append(f"{path.name} record {n}: id {rec[0]:3d}  "
                   f"payload {rec[1]:02x} {rec[2]:02x} {rec[3]:02x} "
                   f"{rec[4]:02x}  next {rec[5:9].hex()}")
    if not out:
        out.append(f"{path.name}: {path.stat().st_size} bytes, no whole record")
    return out


def snapshot(session: dosbox.Session, out: pathlib.Path, tag: str) -> None:
    """Copy every file in the game's `SAVE` directory into `out`, prefixed."""
    out.mkdir(parents=True, exist_ok=True)
    for p in sorted(session.save_dir.iterdir()):
        (out / f"{tag}-{p.name}").write_bytes(p.read_bytes())


def step_kind(step: str) -> tuple[str, object]:
    """`("snapshot", tag)`, `("type", text)`, `("wait", s)` or `("key", sym)`.

    Its own function so the four prefixes can be tested without an emulator:
    a run is only reproducible if `!C` snapshots rather than pressing a key
    called `!C`, and that is a parse rather than a drive.
    """
    if step.startswith("!"):
        return "snapshot", step[1:]
    if step.startswith("#"):
        return "type", step[1:]
    if step.startswith("~"):
        return "wait", float(step[1:])
    return "key", step


def do_step(session: dosbox.Session, out: pathlib.Path, step: str,
            tag: str, gap: float = 1.0) -> str:
    """Run one step and shoot the screen it left.  Returns the shot's digest."""
    kind, argument = step_kind(step)
    if kind == "snapshot":
        snapshot(session, out, str(argument))
        return "snapshot"
    if kind == "wait":
        time.sleep(float(argument))  # type: ignore[arg-type]
    elif kind == "type":
        for ch in str(argument):
            session.key("space" if ch == " " else ch)
    else:
        session.key(str(argument))
    time.sleep(gap)
    screen = session.settle(quiet=0.5, timeout=10.0)
    safe = "".join(c if c.isalnum() else "_" for c in step)
    session.shot(f"{tag}-{safe}", allow_blank=True)
    return screen.digest()


def open_session(note: str) -> tuple[dosbox.Session, dosbox.Slot]:
    """Claim a slot, stage a fresh copy of the game, boot, reach the menu.

    `stage(fresh=True)` copies the archives' tree into the slot's work
    directory, so the run writes only there and the player's own files are
    opened read only.
    """
    slot = dosbox.claim(note)
    session = dosbox.Session(slot, dosbox.find_game())

    def cleanup(*_: object) -> None:
        session.close()
        slot.release()

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    session.stage(fresh=True)
    # Slot C is this tool's own; the archives use A, B and J, so a CHRDATC
    # file after a run can only be one the engine wrote here.
    for stale in list(session.save_dir.glob("CHRDATC*")) + \
            list(session.save_dir.glob("SAVGAMC*")):
        stale.unlink()
    session.boot(fresh=False)
    dosbox.PoolOfRadiance(session).to_main_menu()
    session.shot("00-main-menu")
    return session, slot


def collect(session: dosbox.Session, out: pathlib.Path) -> list[str]:
    """Copy the shots out of the slot and dump every `.SPC` in `SAVE`."""
    out.mkdir(parents=True, exist_ok=True)
    for png in sorted((session.dir / "shots").glob("*.png")):
        shutil.copy(png, out / png.name)
    lines: list[str] = []
    for spc in sorted(session.save_dir.glob("*.SPC")):
        lines += describe(spc)
    return lines


def script_run(out: pathlib.Path, steps: list[str], gap: float) -> int:
    """One boot, one list of steps, a shot per step, then the `.SPC` dump."""
    out.mkdir(parents=True, exist_ok=True)
    session, slot = open_session("issue84 script")
    try:
        for i, step in enumerate(steps):
            digest = do_step(session, out, step, f"{i:02d}", gap)
            print(f"{i:02d} {step:12s} {digest}", flush=True)
        snapshot(session, out, "final")
        for line in collect(session, out):
            print(line, flush=True)
    finally:
        session.close()
        slot.release()
    print("shots in", out, flush=True)
    return 0


def interactive(out: pathlib.Path, cmd: pathlib.Path, gap: float,
                idle: float = 900.0) -> int:
    """Boot once, then run step lines as they are appended to `cmd`.

    A boot costs about a minute and an unmapped menu costs one step, so a
    mode that maps many screens per boot is the difference between an
    afternoon and a week.  Lines already in the file when this starts are
    executed first, so a run can be scripted and then continued by hand.
    """
    out.mkdir(parents=True, exist_ok=True)
    cmd.parent.mkdir(parents=True, exist_ok=True)
    session, slot = open_session("issue84 interactive")
    if not cmd.exists():
        cmd.write_text("")
    done = 0
    last = time.time()
    try:
        while time.time() - last < idle:
            lines = [ln.strip() for ln in cmd.read_text().splitlines()]
            lines = [ln for ln in lines if ln and not ln.startswith(";")]
            if done >= len(lines):
                time.sleep(1.0)
                continue
            step = lines[done]
            last = time.time()
            if step == "--quit":
                print("quit", flush=True)
                break
            if step == "--collect":
                for line in collect(session, out):
                    print(line, flush=True)
                done += 1
                continue
            digest = do_step(session, out, step, f"{done:02d}", gap)
            print(f"{done:02d} {step:12s} {digest}", flush=True)
            for png in sorted((session.dir / "shots").glob("*.png")):
                shutil.copy(png, out / png.name)
            done += 1
        snapshot(session, out, "final")
        for line in collect(session, out):
            print(line, flush=True)
    finally:
        session.close()
        slot.release()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=OUT / "run",
                    help="where shots, SAVE snapshots and dumps go")
    ap.add_argument("--gap", type=float, default=1.0,
                    help="seconds to wait after each keypress")
    ap.add_argument("--interactive", action="store_true",
                    help="execute step lines appended to --cmd")
    ap.add_argument("--cmd", type=pathlib.Path, default=OUT / "cmd.txt",
                    help="the command file --interactive reads")
    ap.add_argument("--dump", type=pathlib.Path, nargs="*",
                    help="print the records of these .SPC files and exit")
    ap.add_argument("steps", nargs="*", help="steps to press from the menu")
    args = ap.parse_args(argv)

    if args.dump:
        for path in args.dump:
            for line in describe(path):
                print(line)
        return 0
    if args.interactive:
        return interactive(args.out, args.cmd, args.gap)
    if not args.steps:
        ap.error("give steps, --interactive or --dump")
    return script_run(args.out, args.steps, args.gap)


if __name__ == "__main__":
    raise SystemExit(main())

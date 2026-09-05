#!/usr/bin/env python3
"""Step a converted party off the training-hall square and back on, and
photograph every screen the game puts up on the way.

`#257 (A DOS save made in the training hall converts as though the party were
in New Phlan)` is the ticket, and this answers the one thing left open on it:
a converted hall save arrives showing the hall, and nobody had watched the
hall's own `TRAIN CHARACTER` question come back.

`tools/savecheck.py` could not.  Its walk loop is `Session.walk_one`, which
re-sends a move until the **status line** changes and gives up after four
tries; the training hall answers a step with a room description, a
`PRESS <RETURN>`, a load and then two `YES NO` questions
(`docs/70-driving-the-game.md`), and none of those is a status line.  Six
moves in a row came back `moved: false, status: null` at about 118 seconds
each -- which reads exactly like a hang and is not one.

So this presses the key and then **reads whatever is on the screen**, one
screen at a time, saving a `.png` and the twenty-five text rows for each.
Nothing is inferred from a status line and nothing is retried.  The game's
own words go to `--out`, which must be under `work/`: they are the game's and
must not enter the repository.

    tools/hallmenu.py --disk work/issue257/fixed/script.d64 \
        --out work/issue257/menu --walk MKI

`--answer` is what to give a `YES NO`; the default `NO` declines training,
which leaves the party where it stands.  The C64 game disks are `$POR_DISKS`
then `automap.paths.find_disks()`, read and never written, and the emulator
comes from the instance pool.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from tools import session as S  # noqa: E402

#: Where the player keeps the C64 game disks.  Read only.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The resident area, `$6E1B & $7F` -- `docs/118-debug-mode.md`.  The same
#: address `tools/savecheck.py` reads, and the one the engine restores from
#: `$49F2` on load.
AREA_AT = 0x6E1B


def area(sess) -> int | None:
    try:
        with sess.mon(5) as m:
            return m.read(AREA_AT, 1)[0] & 0x7F
    except Exception:
        return None


def rows(sess) -> list[str]:
    """The twenty-five text rows, or an empty list on a bitmap screen."""
    s = sess.screen()
    if s is None:
        return []
    return [s.row(r).rstrip() for r in range(25)]


def kind(row24: str) -> str:
    """What the command bar is asking for, in one word.

    `movebar` is the one that made this look like a hang.  `I,J,K,M, RETURN
    OR BUTTON` is `MOVE` already selected and waiting for a direction, and it
    is what the game goes back to after the training hall's question is
    answered -- so a driver waiting for the *world* bar waits for ever while
    the game sits there perfectly willing to take a key.
    """
    if "MOVE" in row24 and "ENCAMP" in row24:
        return "world"
    if "YES" in row24 and "NO" in row24:
        return "yesno"
    if "I,J,K,M" in row24:
        return "movebar"
    if "PRESS" in row24:
        return "press"
    if row24.strip():
        return "bar"
    return "none"


class Log:
    def __init__(self, out: pathlib.Path):
        self.dir = out
        self.dir.mkdir(parents=True, exist_ok=True)
        self.f = (self.dir / "hallmenu.jsonl").open("a")

    def emit(self, what: str, **kw) -> None:
        self.f.write(json.dumps({"kind": what, "t": time.time(), **kw}) + "\n")
        self.f.flush()

    def say(self, *a) -> None:
        print(*a, flush=True)

    def close(self) -> None:
        self.f.close()


def watch(sess, log: Log, tag: str, answer: str, seconds: float) -> str:
    """Read screen after screen until the world bar is back or time runs out.

    Every distinct screen is photographed and logged verbatim.  That is the
    whole point: the screen a driver waiting on a status line never sees is
    the one this ticket is about.
    """
    end, shot, last = time.time() + seconds, 0, None
    while time.time() < end:
        s = sess.screen()
        if s is None:
            time.sleep(1.0)
            continue
        # `INSERT SIDE # 3` first, and through `Session`, which attaches the
        # side rather than pressing a key at it.  A loop that only answered
        # `PRESS ANY KEY` sat in front of that prompt 104 times.
        if sess.handle_prompt(s):
            time.sleep(0.8)
            continue
        text = [s.row(r).rstrip() for r in range(25)]
        bar = kind(text[24])
        # One shot per *distinct* screen, keyed on the command bar and the
        # body: the game redraws a menu over an empty row 24 between frames,
        # and photographing every frame buries the one screen that matters.
        here = (bar, text[24], text[3:23])
        if here != last:
            last = here
            shot += 1
            png = str(log.dir / f"{tag}-{shot:02d}.png")
            sess.kbd.screenshot(png)
            log.emit("screen", tag=tag, n=shot, bar=bar, rows=text, png=png,
                     area=area(sess))
            log.say(f"  [{tag}.{shot:02d}] {bar:5s} |{text[24].strip()}|")
        if bar == "world":
            return "world"
        if bar in ("press", "movebar"):
            sess.kbd.key("Return")
        elif bar == "yesno":
            log.say(f"      answering {answer}")
            if not sess.select_bar(answer, timeout=8):
                sess.kbd.key("Return")
        time.sleep(1.2)
    return "stuck"


def run(args, log: Log) -> int:
    slot = S.claim_slot(args.slot, f"hallmenu/{pathlib.Path(args.disk).name}")
    log.say(f"slot {slot.n} display {slot.display}")
    sess = None
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        shutil.copy(args.disk, pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        listed = sess.load_save()
        log.emit("picker", listed=listed)
        if not listed:
            raise RuntimeError("the game did not load the save")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        if watch(sess, log, "arrive", args.answer, args.arrive) != "world":
            raise RuntimeError("no world bar after BEGIN ADVENTURING")
        sess.settle(3)
        log.say(f"arrived in area {area(sess)} at {sess.square()}")
        log.emit("arrived", area=area(sess), square=sess.square())

        for n, move in enumerate(args.walk.upper(), 1):
            tag = f"{n:02d}{move}"
            # `select_bar` rather than `walk_one`: one attempt, no retry, and
            # a failure is a fact about the screen rather than a fault.
            picked = sess.select_bar("MOVE", timeout=8)
            log.say(f"move {move}: MOVE selectable = {picked}")
            if picked:
                time.sleep(0.6)
                sess.kbd.key(move.lower(), 0.15, 0.30)
            else:
                sess.kbd.key(move.lower(), 0.15, 0.30)
            out = watch(sess, log, tag, args.answer, args.patience)
            here, sq = area(sess), sess.square()
            log.say(f"move {move}: {out}, area {here}, square {sq}")
            log.emit("move", move=move, outcome=out, area=here, square=sq,
                     move_bar=picked)
        return 0
    finally:
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:
                log.emit("cleanup_failed", step=what, error=repr(exc))
                log.say(f"Cleanup failed at {what}: {exc!r}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, help="the save .d64 to boot")
    p.add_argument("--disks", default=str(DISKS),
                   help="the C64 game disks; read only")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--out", required=True, help="a directory under work/")
    p.add_argument("--walk", default="MKI",
                   help="moves, in the game's own I J K M")
    p.add_argument("--answer", default="NO", help="what to answer a YES NO")
    p.add_argument("--arrive", type=float, default=240.0,
                   help="seconds to wait for the first world bar")
    p.add_argument("--patience", type=float, default=90.0,
                   help="seconds to watch the screen after each move")
    args = p.parse_args(argv)
    log = Log(pathlib.Path(args.out))
    try:
        return run(args, log)
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())

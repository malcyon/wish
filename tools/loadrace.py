#!/usr/bin/env python3
"""Stage the keypress collision at the game's `LOAD SAVED GAME: YES` prompt.

`#380` is a driven run that failed on the party-creation menu with the party
already loaded and the roster drawn correctly.  `Session.load_save` has four
ways to give up and the caller turns all of them into one sentence, so nothing
in the log said which.

The candidate this tool tests is the third one.  `Session.handle_prompt`
answers a disk prompt by pressing **space**, and it re-fires every two seconds
for as long as the prompt's text is on the screen.  The game's confirm bar
comes up within that window -- measured at 0.0 s after `load_save`'s own
`settle(4)` on this machine -- so a space meant for the disk prompt can land on
the confirm bar instead.  If it does, the bar is answered and gone before
`wait_text("LOAD SAVED GAME: YES")` ever sees it: the save loads, and
`load_save` reports that it did not.

So this run does deliberately what the race does by accident: choose LOAD SAVED
GAME, settle, send one space, and then ask exactly what `load_save` asks next.

    tools/loadrace.py --disk work/376/PORSAVEB.D64 --space
    tools/loadrace.py --disk work/376/PORSAVEB.D64 --no-space   # the control

The two runs differ by one keypress and nothing else, which is what makes the
answer a measurement rather than a story.  Nothing is written to the player's
disks: `stage_disks` copies the eight sides into the slot and `Session.attach`
refuses any path outside it.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from tools import savecheck as V  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")


def rows_of(sess) -> tuple[list[str], bool]:
    s = sess.screen()
    if s is None:
        return [], True
    return [line.rstrip() for line in s.rows() if line.strip()], False


def loaded(rows: list[str]) -> bool:
    """Whether the party menu is showing a loaded party.

    The menu drops `LOAD SAVED GAME` from its own list once a game is loaded,
    and the roster above it only holds names once characters have been read
    off a save or created by hand.  Both, together, because either alone is
    the state before the load on some other title.
    """
    text = "\n".join(rows)
    return "BEGIN ADVENTURING" in text and "LOAD SAVED GAME" not in text


def run(args, log: V.Log) -> int:
    V.catch_signals()
    slot = S.claim_slot(args.slot, f"loadrace/{pathlib.Path(args.disk).name}")
    log.say(f"slot {slot.n} display {slot.display}")
    sess = None
    rc = 0
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        S.stage_writable(args.disk, pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if sess.wait_text("LOAD SAVED GAME", 240)[0] is None:
            raise RuntimeError("the party menu never offered LOAD SAVED GAME")
        if not sess.select_row("LOAD SAVED GAME"):
            raise RuntimeError("the highlight would not go onto LOAD SAVED GAME")
        sess.settle(4)

        if args.space:
            # The stray keypress, byte for byte what `handle_prompt` sends.
            log.say("sending the space a lingering disk prompt would have sent")
            sess.kbd.key("space")
        log.emit("staged", space=args.space)

        chose = time.time()
        hit, _ = sess.wait_text("LOAD SAVED GAME: YES", args.confirm)
        waited = round(time.time() - chose, 2)
        rows, bitmap = rows_of(sess)
        log.emit("confirm", seen=hit is not None, waited=waited,
                 rows=rows, bitmap=bitmap)
        log.say(f"the confirm prompt was {'seen' if hit else 'never seen'} "
                f"in {waited}s -- which is what load_save tests, so it would "
                f"have returned {hit is not None}")
        sess.kbd.screenshot(str(log.dir / f"{args.tag}-confirm.png"))
        if hit is not None:
            sess.kbd.key("Return")

        back, _ = sess.wait_text("BEGIN ADVENTURING", args.settle)
        rows, bitmap = rows_of(sess)
        log.emit("after", menu=back is not None, rows=rows, bitmap=bitmap,
                 loaded=loaded(rows))
        sess.kbd.screenshot(str(log.dir / f"{args.tag}-after.png"))
        for line in rows:
            log.say(f"    |{line}|")
        log.say(f"the party menu is back: {back is not None}; "
                f"it is showing a loaded party: {loaded(rows)}")
        # The whole point, in one line: `load_save`'s answer against the
        # game's own state.
        log.emit("verdict", load_save_would_say=hit is not None,
                 party_actually_loaded=loaded(rows))
        log.say(f"VERDICT: load_save would report {hit is not None}, "
                f"the party is loaded {loaded(rows)}")
    except Exception as exc:
        import traceback
        log.emit("failed", error=repr(exc), traceback=traceback.format_exc())
        traceback.print_exc()
        try:
            if sess is not None:
                sess.kbd.screenshot(str(log.dir / f"{args.tag}-failure.png"))
                rows, bitmap = rows_of(sess)
                log.emit("failure_screen", rows=rows, bitmap=bitmap)
        except Exception:
            log.say("could not photograph the failure")
        rc = 1
    finally:
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:
                log.emit("cleanup_failed", step=what, error=repr(exc))
                log.say(f"Cleanup failed at {what}: {exc!r}")
                rc = rc or 1
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, help="the save .d64 to boot")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's game disks are; read, never written")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--tag", default=None, help="prefix for the screenshots")
    p.add_argument("--out", default=None,
                   help="the log (default work/loadrace/<disk>.jsonl)")
    p.add_argument("--space", action=argparse.BooleanOptionalAction, default=True,
                   help="send the stray space at the confirm prompt; "
                        "--no-space is the control")
    p.add_argument("--confirm", type=float, default=60.0,
                   help="seconds to wait for the confirm prompt, which is "
                        "load_save's own budget")
    p.add_argument("--settle", type=float, default=120.0,
                   help="seconds to wait for the party menu afterwards")
    args = p.parse_args(argv)
    stem = pathlib.Path(args.disk).stem
    args.tag = args.tag or f"{stem}-{'space' if args.space else 'control'}"
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "loadrace" / f"{args.tag}.jsonl")
    log = V.Log(out)
    try:
        return run(args, log)
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())

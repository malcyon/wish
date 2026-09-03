#!/usr/bin/env python3
"""Check the world-menu driver against the running game, command by command.

    tools/menucheck.py --slot 1 --save PORSAVE13.D64 --caster ROLAND

`tools/session.py`'s `select_bar` and `select_row` are how every driven run
reaches a command in the game's own menus, and nothing offline can tell
whether they still land on the right one -- the bar is highlighted in colour
RAM on a live screen. This boots a slot, loads a save and walks four checks
through it, printing PASS or FAIL for each and exiting non-zero if any failed.

  MOVE       `walk_one` is `select_bar("MOVE")` plus a direction; the party's
             position has to change.
  CAST       `select_bar("CAST")` has to open CAST and not the command beside
             it. The proof is one keypress **past** the list: CAST's list of
             casters leads to `PICK A SPELL TO CAST`, and VIEW's
             identical-looking list leads to a character sheet. Nothing on the
             list itself tells them apart, which is why the check goes through
             it rather than stopping at it.
  SELECT ROW `select_row` with no `column` has to find the named character by
             working the list's column out for itself.
  SAVE GAME  `save_game()` is ENCAMP then SAVE GAME then the disk prompts --
             the longest chain of bars in the program.

`#173 (The world menu driver takes the command next to the one it was asked
for, and the character list it opens ignores it entirely)` is what this exists
for: `select_bar` matched a word by where it started rather than by which word
the highlight covered, so CAST reached VIEW, and `select_row` ignored its
argument. Both are one-line-of-colour-RAM faults and both were invisible until
somebody drove the game.

`--caster` names a character in the save who can cast; the default suits the
default save. Needs a set of disks: `$POR_DISKS`, or
`automap.paths.find_disks()`. The pool owns the emulator, and the player's
disks are copied into the slot and never written.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import session as S  # noqa: E402

from automap.paths import find_disks  # noqa: E402

#: What CAST's list leads to and VIEW's does not. The one string that tells
#: the two identical-looking character lists apart.
CAST_PROMPT = "PICK A SPELL"


def show(sess, tag: str):
    """Every non-blank row, with its colour RAM, so a failure is readable."""
    s = sess.screen()
    print(f"--- {tag}", flush=True)
    if s is None:
        print("  (no screen)", flush=True)
        return None
    for r in range(25):
        if s.row(r).strip():
            colours = "".join("%x" % c for c in s.colours[r * 40:(r + 1) * 40])
            print(f"  {r:2d} |{s.row(r)}| {colours}", flush=True)
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slot", type=int, default=None,
                    help="pool slot to claim; the first free one by default")
    ap.add_argument("--save", default="PORSAVE13.D64",
                    help="the save disk to load out of the player's folder")
    ap.add_argument("--caster", default="ROLAND",
                    help="a character in that save who can cast a spell")
    ap.add_argument("--shots", default="",
                    help="directory to photograph each check into")
    args = ap.parse_args(argv)

    disks = pathlib.Path(os.environ.get("POR_DISKS") or (find_disks() or ""))
    if not disks.is_dir():
        raise SystemExit("no game disks: set $POR_DISKS")
    shots = pathlib.Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    os.environ["POR_HEADLESS"] = "1"
    os.environ.setdefault("POR_AGENT", "menucheck")

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, said: str = ""):
        results.append((name, bool(ok), said))
        print(f"{'PASS' if ok else 'FAIL'}  {name}"
              + (f"  -- {said}" if said else ""), flush=True)

    slot = S.claim_slot(args.slot, note="menucheck: select_bar and select_row")
    print(f"slot {slot.n} display {slot.display} dir {slot.dir}", flush=True)
    sess = None
    try:
        sess = S.Session(S.stage_disks(slot, disks, args.save), slot=slot)
        t0 = time.time()
        if not sess.boot():
            raise RuntimeError("boot failed")
        print(f"BOOT ok {time.time() - t0:.0f}s", flush=True)
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        print(f"WORLD at {sess.position()}", flush=True)
        print("row24 |%s|" % sess.screen().row(24), flush=True)

        # -- MOVE ----------------------------------------------------------
        before = sess.status()
        moved = sess.walk_one("I")
        sess.settle(2)
        check("MOVE", moved, f"{before} -> {sess.status()}")

        # -- CAST, and the keypress past the list that names it -------------
        opened = sess.select_bar("CAST", timeout=20)
        sess.settle(4)
        s = show(sess, "after CAST")
        print("highlighted_rows() =", None if s is None else s.highlighted_rows(),
              flush=True)
        if shots:
            sess.kbd.screenshot(str(shots / "after-cast.png"))

        # No `column`: `select_row` has to work the list's column out from the
        # character's own name, which is the whole of what #173 left open.
        picked = sess.select_row(args.caster, timeout=25)
        sess.settle(5)
        s = show(sess, f"after picking {args.caster}")
        text = "" if s is None else "\n".join(s.row(r) for r in range(25))
        check("SELECT ROW", picked, f"select_row({args.caster!r})")
        check("CAST", opened and CAST_PROMPT in text,
              f"{CAST_PROMPT!r} on screen: {CAST_PROMPT in text}"
              " -- absent means it opened the command beside CAST")
        if shots:
            sess.kbd.screenshot(str(shots / "cast-roster.png"))

        # -- back out, then ENCAMP -> SAVE GAME ------------------------------
        for _ in range(4):
            sess.press_kernal(0x1B)     # ESC
            time.sleep(0.5)
        sess.settle(3)
        print("row24 after escaping |%s|" % sess.screen().row(24), flush=True)
        saved = sess.save_game()
        sess.settle(4)
        check("SAVE GAME", saved, f"back in the world at {sess.position()}")
        if shots:
            sess.kbd.screenshot(str(shots / "after-save.png"))
    except Exception as exc:                                # noqa: BLE001
        print(f"FAILED {type(exc).__name__}: {exc}", flush=True)
        results.append(("the run itself", False, str(exc)))
        if sess is not None:
            try:
                show(sess, "at the failure")
                if shots:
                    sess.kbd.screenshot(str(shots / "failure.png"))
            except Exception:
                pass
    finally:
        if sess is not None:
            sess.close()
        slot.release()

    bad = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed"
          + (f"; failed: {', '.join(bad)}" if bad else ""), flush=True)
    return 1 if bad or not results else 0


if __name__ == "__main__":
    raise SystemExit(main())

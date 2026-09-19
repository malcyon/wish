#!/usr/bin/env python3
"""Drive a converted Secret of the Silver Blades C64 save in VICE: load the
party, arrive, read one sheet, walk one square and let the engine resave.

Written for `#52 (File ▸ Import and File ▸ Export for every direction the
library supports)`, the `DosToC64` Silver Blades walk, when
`tools/convert/convertrun.py` had no Silver Blades driver. It drives
`tools.secret_of_the_silver_blades.ssbwarp.SSBSession` directly and reuses `tools/c64/savecheck.py`'s screen
readers, the pattern the sibling `AmigaToC64` Silver Blades walk set. The
worked-around bug in `tools/secret_of_the_silver_blades/ssbwarp.py`'s save prompt
(`#539 (tools/secret_of_the_silver_blades/ssbwarp.py's SAVE_PROMPT does not match Silver Blades' actual
save-disk prompt, so ENCAMP > SAVE silently refuses)`) has been fixed since,
so the assignment that patched it is gone. The sheet is still read by
pressing VIEW and reading the raw screen, the workaround for
`#540 (Session.character_sheet() times out on every Silver Blades sheet,
because SSBSession has no sheet_is_up override)`.

`--disks` is a folder of the player's Silver Blades C64 disks, `--produced`
the converted save disk under test; both are copied, not written. Claims one
pool slot. `--out` receives the screenshots, `ssbcheck.jsonl`, `summary.json`
and, when the engine's own save succeeds, `resave-SSBC.D64`.

    .venv/bin/python -m tools.secret_of_the_silver_blades.ssbresavewalk --disks path/to/ssb-disks \\
        --produced path/to/SSBC.D64 --out DIR
"""
import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.c64 import session as S  # noqa: E402
from tools.c64.savecheck import Log, answer_bars, panel, walk_step_routed  # noqa: E402
from tools.secret_of_the_silver_blades import ssbwarp  # noqa: E402


def sheet_workaround(sess, index: int, tag: str, log: Log,
                     out: pathlib.Path) -> list[str] | None:
    """Press VIEW and read the raw screen, not `sheet_is_up`."""
    if not sess.select_party(index):
        log.say(f"  could not select party slot {index}")
        return None
    if not sess.select_bar("VIEW", timeout=20):
        log.say("  VIEW could not be selected on the world bar")
        return None
    time.sleep(2.0)
    s = sess.screen()
    lines = None
    if s is not None:
        lines = [line.rstrip() for line in s.rows() if line.strip()]
        sess.kbd.screenshot(str(out / f"{tag}-sheet-{index}.png"))
    sess.cancel_bar()
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disks", required=True, type=pathlib.Path,
                    help="folder of the player's Silver Blades C64 disks")
    ap.add_argument("--produced", required=True, type=pathlib.Path,
                    help="the converted save disk to load")
    ap.add_argument("--out", required=True, type=pathlib.Path,
                    help="folder for screenshots, the log and the resave")
    args = ap.parse_args(argv)

    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("XDG_SESSION_TYPE", None)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["GDK_BACKEND"] = "x11"
    os.environ.setdefault("POR_HEADLESS", "1")

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    log = Log(out / "ssbcheck.jsonl")
    slot = S.claim_slot(None, "convertrun-ssb-52")
    log.say(f"slot {slot.n} display {slot.display}")
    sess = None
    try:
        boot = ssbwarp.stage(slot, str(args.disks), save=str(args.produced))
        sess = ssbwarp.SSBSession(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed -- never reached the party menu")
        sess.kbd.screenshot(str(out / "00-party-menu.png"))

        if not ssbwarp.load_party(sess):
            raise RuntimeError("load_party failed -- never reached "
                               "BEGIN ADVENTURING")
        log.say("reached BEGIN ADVENTURING")

        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        arrived = answer_bars(sess, log, "NO", seconds=120)
        log.emit("arrival", outcome=arrived)
        if arrived != "world":
            sess.kbd.screenshot(str(out / "stuck.png"))
            raise RuntimeError(f"no world bar reached: {arrived}")
        sess.settle(3)

        where = sess.status()
        rows, named = panel(sess)
        log.emit("arrived", status=str(where), panel=rows, named=named)
        log.say(f"status: {where.where() if where else None}")
        for r in rows:
            log.say(f"    |{r}|")
        sess.kbd.screenshot(str(out / "01-arrived.png"))

        # One character sheet.
        lines = sheet_workaround(sess, 0, "02", log, out)
        log.emit("sheet", lines=lines)
        if lines:
            for line in lines:
                log.say(f"    {line}")
        else:
            log.say("  sheet read failed")

        # Walk one square.
        before = sess.status()
        before_sq = sess.square()
        moved = sess.walk_one("I")
        routed = walk_step_routed(sess, log, "NO")
        after = sess.status()
        after_sq = sess.square()
        log.emit("walk", moved=moved, routed=routed,
                 before=str(before), after=str(after),
                 before_square=before_sq, after_square=after_sq)
        log.say(f"walk I: moved={moved} routed={routed} "
                f"before={before.where() if before else None} "
                f"after={after.where() if after else None}")
        sess.kbd.screenshot(str(out / "03-walked.png"))

        # Engine's own resave.
        ok = sess.save_game()
        log.emit("resave", ok=ok)
        log.say(f"ENCAMP > SAVE wrote the party back: {ok}")
        if ok:
            S.copy_closed_disk(pathlib.Path(sess.save_disk),
                               out / "resave-SSBC.D64")
            log.say(f"resave kept at {out / 'resave-SSBC.D64'}")
        sess.kbd.screenshot(str(out / "04-resaved.png"))

        result = {
            "arrived_status": str(where), "arrived_panel": rows,
            "arrived_named": named, "sheet_lines": lines,
            "walk_moved": moved, "walk_routed": routed,
            "before_status": str(before), "after_status": str(after),
            "before_square": before_sq, "after_square": after_sq,
            "resave_ok": ok,
        }
        (out / "summary.json").write_text(json.dumps(result, indent=2))
        log.say("SUCCESS")
        return 0
    except Exception as exc:
        log.say(f"FAILED: {exc}")
        if sess is not None:
            try:
                sess.kbd.screenshot(str(out / "failure.png"))
            except Exception:
                pass
        raise
    finally:
        if sess is not None:
            sess.close()
        slot.release()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())

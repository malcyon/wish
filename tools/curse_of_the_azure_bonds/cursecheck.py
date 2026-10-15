#!/usr/bin/env python3
"""Boot a Curse of the Azure Bonds save disk in VICE and read the party off
the game's own screens.

`tools/c64/savecheck.py` does this for Pool of Radiance and there was no Curse
equivalent, which is the whole of why
`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)`'s fifth flag condition graded DOS → C64 Curse PROBABLE rather than
confirmed: `tools/curse_of_the_azure_bonds/curseload.py` gets a party in through the game's own
`LOAD SAVED GAME` and then serves, and nothing ever read the roster panel, a
character sheet or a step off it.  The bytes were believed right; nobody had
looked.

    tools/curse_of_the_azure_bonds/cursecheck.py --disk CURSEJ.D64 --walk KIKI \\
                        --resave RESAVE.D64

What it reads, in order, and every one of them is a thing bytes cannot
answer:

* whether the game's own `LOAD SAVED GAME` takes a container Wish built --
  Curse has no save picker at all, so this is the loader and not a file list
  (the work on converting a Curse of the Azure Bonds DOS save into a C64 one);
* the status line: facing, clock and square, which is the DOS save's own;
* the party panel: every name the game lists with its armour class and hit
  points, and **how many** rows it lists, which is what catches a stranger
  left in slot 7;
* each character's `VIEW` sheet, verbatim, all six of them -- the party panel
  is the selector and `Up`/`Down` on it is what reaches characters two to six
  (`#183 (Nothing knows how to reach the other five character sheets in a
  driven session)`);
* a step, so the save is proven to be a game rather than a file that loads;
* the engine's own `ENCAMP ▸ SAVE`, kept, so what the game wrote back can be
  diffed against what the conversion wrote.

Two things about driving this title that are not Pool of Radiance's and are
carried in `tools/curse_of_the_azure_bonds/curserun.py` rather than here: the move handler answers only
the KERNAL buffer, and there is no travel grid, so `Session.indoors()` must
not read `$49E6`
(`#360 (The session driver will not walk a Curse or Silver Blades party in a
dungeon, because it reads Pool of Radiance's indoors flag)`).

Nothing outside the pool slot's own directory is written and the player's
disks are opened read only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import c64 as machines  # noqa: E402
from automap import gamedisks  # noqa: E402
from goldbox import c64_port, world_state  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools.c64 import session as por  # noqa: E402
from tools.curse_of_the_azure_bonds import curseload, curserun  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: The live square triple -- x, y, facing -- which is where Curse keeps the
#: party while it is running.  `tools/curse_of_the_azure_bonds/cursewarp.py` established it for
#: `#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
#: Radiance's alone?)`
#: and `automap.c64` carries it as `C64Machine.live_position`; it is read
#: here as well as the status line because **Curse does not print the square
#: in every area** (area `$03` draws `E 3:44` and no coordinates at all), so
#: a status-line reader alone proves nothing outside the areas that do.
LIVE_XY = machines.machine_for(curserun.CurseSession.game).live_position


def probe_square(sess) -> list[int]:
    """`$C04B`-`$C04D`, as a list, or an empty one if the read failed."""
    try:
        got = sess.steady_triple()
        if got is None:
            sess.log("  square did not settle; reading it as empty")
        return [] if got is None else list(got)
    except Exception:                                     # noqa: BLE001
        return []


def panel(sess) -> list[str]:
    """The world panel's rows that name a character, left-trimmed.

    `Session.stable_party_rows` finds them under the panel's own `NAME  AC HP`
    heading rather than at fixed rows, because how many there are is the
    party size and that is one of the things being checked
    (`#104 (A converted DOS party arrives with the template save's spare
    characters still in it)`) -- and waits for two reads to agree rather than
    trusting the first frame, because a read straight after a sheet can land
    on the panel still being redrawn (`#538`).
    """
    rows = sess.stable_party_rows()
    s = sess.screen()
    if s is None:
        return []
    return [s.row(r)[por.PARTY_COLUMN:].rstrip() for r in rows]


def read_sheets(sess, out: pathlib.Path, log) -> list[list[str]]:
    """Every character's `VIEW` screen, verbatim, in panel order.

    Reads as many as the panel lists rather than a number given here: a
    conversion proven on one sheet of six is proven on one sixth of it, and
    the three faults this project has shipped -- an armour class of 9 shown
    as 51, a dropped combat tail, a garbage weapon line -- were all sheet
    faults.
    """
    listed = len(sess.stable_party_rows())
    if not listed:
        log(event="no-panel", note="the party panel lists nobody")
        return []
    sheets = []
    for n in range(listed):
        lines = sess.character_sheet(n, shot=str(out / f"sheet-{n}.png"))
        if lines is None:
            # Photograph what *is* on the screen.  A run that stops without
            # saying what it was looking at costs the next run: the first
            # try at this file reported `no character sheet came up after
            # VIEW` and left nothing anybody could read.
            s = sess.screen()
            here = "(bitmap)" if s is None else "\n".join(s.row(r)
                                                          for r in range(25))
            (out / f"sheet-{n}-missing.txt").write_text(here + "\n")
            sess.kbd.screenshot(str(out / f"sheet-{n}-missing.png"))
            log(event="sheet-missing", slot=n, row24="" if s is None
                else s.row(24).strip())
            break
        (out / f"sheet-{n}.txt").write_text("\n".join(lines) + "\n")
        log(event="sheet", slot=n, lines=lines)
        sheets.append(lines)
    return sheets


def walk(sess, moves: str, log) -> list[dict]:
    """One reading per move: what was pressed, and where the party ended up.

    Both readings, every step.  The status line is the one a player sees and
    the live triple is the one that exists in every area, and a step that
    moves neither is a wall -- while a step the driver never sent is a driver
    error, which `Session.walk_stopped` says

    **`before` and `after` bracket the whole call**, script screens included,
    so they can come back equal on a step that `moved` says landed: the
    square west of 3,12 in Tilverton is an armourer, and declining him prints
    `'GOOD DAY THEN.' YOU MOVE AWAY.` and puts the party back where it
    started.  `moved` is `walk_one`'s own reading, taken across the keypress
    alone
    (`#360 (The session driver will not walk a Curse or Silver Blades party in
    a dungeon, because it reads Pool of Radiance's indoors flag)`).
    """
    steps = []
    for move in moves.upper():
        before = probe_square(sess)
        moved = sess.walk_one(move)
        after = probe_square(sess)
        at = sess.status()
        row = {"key": move, "moved": moved, "before": before, "after": after,
               "status": None if at is None else at.where()}
        if sess.walk_stopped:
            row["stopped"] = sess.walk_stopped
        log(event="step", **row)
        steps.append(row)
    return steps


#: The game's own progress line while it writes `SAVEAZURE`.
SAVING = "SAVING GAME"


def wait_write_end(sess, timeout: float, *, clock=time.time,
                   sleep=time.sleep) -> dict:
    """Wait for the game to finish writing: `SAVING GAME` gone and the camp
    bar back, seen twice four seconds apart, answering disk prompts between.

    `CurseSession.save_game` returns a fixed twelve seconds after `SAVING
    GAME` comes up, and on a pooled slot the write is still running then: the
    drive has not closed `SAVEAZURE`, and the image still holds the save
    before it.  Reads the screen only; presses nothing but a disk prompt's
    answer.
    """
    began = clock()
    deadline = began + timeout
    seen = False
    row = ""
    while clock() < deadline:
        s = sess.screen()
        if s is None:
            sleep(0.4)
            continue
        row = s.row(24).strip()
        if sess.handle_prompt(s):
            seen = False
            continue
        done = SAVING not in s.text() and por.CAMP_BAR in s.row(24)
        if done and seen:
            return {"ended": True, "seconds": round(clock() - began, 1),
                    "row24": row}
        seen = done
        sleep(4.0 if done else 0.5)
    return {"ended": False, "seconds": round(clock() - began, 1), "row24": row}


def saved_place(path: pathlib.Path) -> dict:
    """The area, square and facing the save file on a disk image holds."""
    image = D64.open(path)
    game = c64_port.detect(image)
    if game is None:
        raise RuntimeError(f"{path} holds no save file")
    _, payload = split_load_address(image.read_file(game.save_file))
    state = world_state.from_c64(bytes(payload), game)
    return {"area": state.area, "x": state.x, "y": state.y,
            "facing": state.facing,
            "payload_sha1": hashlib.sha1(bytes(payload)).hexdigest()}


def keep_resave(sess, save_disk: pathlib.Path, dest: pathlib.Path,
                live: list[int], log, *, before: dict | None = None,
                attempts: int = 30, backoff: float = 1.0) -> dict:
    """Copy the game-written save disk to `dest` once its file is closed,
    and check the save it holds is the one the game just wrote.

    VICE can keep the drive's last track in its buffer until the image is
    attached again, so a copy that finds the file still open is retried once
    after attaching the same image.  A disk still open after that raises,
    and `dest` is not written.  `verified` is whether the saved square and
    facing are where the party stood, `live`, when the save was made.
    """
    try:
        por.copy_closed_disk(save_disk, dest, attempts=attempts, backoff=backoff)
        reattached = False
    except RuntimeError as exc:
        log(event="resave-copy-open", why=str(exc))
        sess.attach(str(save_disk))
        por.copy_closed_disk(save_disk, dest, attempts=attempts, backoff=backoff)
        reattached = True
    place = saved_place(dest)
    square = [place["x"], place["y"], place["facing"]]
    out = {"kept": str(dest), "reattached": reattached, "place": place,
           "live": list(live), "verified": bool(live) and square == list(live)}
    if before is not None:
        out["before"] = before
        out["payload_changed"] = before["payload_sha1"] != place["payload_sha1"]
    return out


def run(args) -> int:
    out = scratch.ensure(args.out)
    logfile = (out / "cursecheck.jsonl").open("a")

    def log(**kw):
        kw["t"] = round(time.time(), 2)
        logfile.write(json.dumps(kw, default=str) + "\n")
        logfile.flush()
        print(json.dumps(kw, default=str), flush=True)

    def shot(tag: str) -> None:
        sess.kbd.screenshot(str(out / f"{tag}.png"))
        s = sess.screen()
        text = "(bitmap)" if s is None else "\n".join(s.row(r)
                                                      for r in range(25))
        (out / f"{tag}.txt").write_text(text + "\n")

    disks = args.disks or str(gamedisks.find("curse-of-the-azure-bonds") or "")
    if not disks:
        raise SystemExit("no Curse sides: pass --disks or set $COAB_DISKS")
    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "i52"))
    log(event="slot", n=slot.n, monitor=slot.port, cmd=slot.cmd_port,
        display=slot.display, dir=str(slot.dir), disk=args.disk)
    first = curserun.stage(slot, disks, args.disk)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    # The specimen tree is read-only and `stage` copied it; the copy is ours
    # to be written by the game's own save.
    os.chmod(save_disk, 0o644)
    before = saved_place(pathlib.Path(save_disk)) if args.resave else None
    sess = curserun.CurseSession(first, slot=slot)
    sess.save_disk = save_disk
    report: dict = {"disk": args.disk, "slot": slot.n}
    try:
        if not sess.boot():
            log(event="boot-failed")
            return 1
        shot("00-party-menu")
        outcome = curseload.load_saved_game(sess, note=log, shot=shot,
                                            wait=args.wait)
        report["load"] = outcome
        log(event="load", outcome=outcome)
        if outcome != "loaded":
            return 1
        sess.patch_disk_prompt()
        addr = curseload.Addresses(sess.game, disks)
        if not curseload.enter_world(sess, addr, timeout=args.wait):
            log(event="never-reached-the-world")
            shot("03-stuck")
            return 1
        report["bar"] = curseload.clear_messages(sess)
        shot("03-world")

        at = sess.status()
        report["status"] = None if at is None else at.where()
        report["live_square"] = probe_square(sess)
        report["panel"] = panel(sess)
        log(event="arrived", status=report["status"],
            live_square=report["live_square"], panel=report["panel"])

        if not args.no_view:
            report["sheets"] = read_sheets(sess, out, log)
        if args.walk:
            report["walk"] = walk(sess, args.walk, log)
            shot("05-walked")
            at = sess.status()
            report["status_after_walk"] = None if at is None else at.where()
        if args.resave:
            # The save disk is out of the drive by now -- a walk pulls in the
            # side the area lives on -- and `CurseSession.handle_prompt` puts
            # it back when `INSERT CURSE SAVE DISK` asks.
            live = probe_square(sess)
            report["resaved"] = sess.save_game()
            shot("06-resaved")
            if not report["resaved"]:
                log(event="resave", ok=False, note="SAVING GAME never came up")
                return 1
            report["write"] = wait_write_end(sess, args.write_wait)
            shot("07-written")
            log(event="write-end", **report["write"])
            if not report["write"]["ended"]:
                return 1
            try:
                report["resave"] = keep_resave(sess, pathlib.Path(save_disk),
                                               pathlib.Path(args.resave), live, log,
                                               before=before)
            except RuntimeError as exc:
                report["resave"] = {"kept": None, "error": str(exc)}
                log(event="resave", ok=False, error=str(exc))
                return 1
            report["resave_kept_at"] = args.resave
            log(event="resave", ok=report["resave"]["verified"], **report["resave"])
            if not report["resave"]["verified"]:
                return 1
        return 0
    finally:
        log(event="done", **{k: v for k, v in report.items()
                             if k not in ("sheets", "panel")})
        (out / "cursecheck.json").write_text(json.dumps(report, indent=2))
        if args.serve:
            # `serve` returns when somebody sends `quit`, and the teardown
            # then runs like any other: a slot whose lease dies with this
            # process while VICE is still up is an instance nobody can tell
            # from a human's.
            por.serve(sess)
        sess.close()
        slot.teardown()
        logfile.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--disk", required=True,
                    help="the Curse save .d64 to boot; copied into the slot "
                         "and never written where it lies")
    ap.add_argument("--disks", default="",
                    help="where the player's six Curse sides are; read, "
                         "never written")
    ap.add_argument("--pool", type=int, default=None)
    ap.add_argument("--walk", default="",
                    help="dungeon keys to send after arriving -- I forward, "
                         "J left, K right, M about")
    ap.add_argument("--resave", default="",
                    help="have the game's own ENCAMP ▸ SAVE write the party "
                         "back, and keep the save disk here")
    ap.add_argument("--write-wait", type=float, default=300.0,
                    help="seconds the game's own write may take before the "
                         "resave is given up")
    ap.add_argument("--no-view", action="store_true",
                    help="skip the VIEW sheets")
    ap.add_argument("--wait", type=float, default=180.0,
                    help="seconds to wait for the load and for the world")
    ap.add_argument("--serve", action="store_true",
                    help="hand the session over on the command port at the "
                         "end instead of tearing it down")
    ap.add_argument("--out", default=str(scratch.scratch_dir("cursecheck")))
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Records every message a C64 Curse or Silver Blades save shows after BEGIN ADVENTURING, and each character's experience before and after.

Loads `--save` on a pool slot, presses BEGIN ADVENTURING and then watches:
each screen that differs from the last is written to `<out>/NN.png` and
`NN.txt` **before** anything is pressed, and only then answered, using only
the words on row 24.  It never sends Escape.  At the world bar it reads the
status line, the live square (`$C04B`-`$C04D`) and the area byte, camps and
saves, and compares each character's experience on `--save` with the resave,
matched by name.

    tools/c64/openingscene.py --title curse --save CURSE_C.D64 --out DIR
    tools/c64/openingscene.py --title ssb --save SSBA.D64 --out DIR

Written to `--out` (default: a new directory under `cache_dir`, because the
flatpak VICE and the disk copies live there too):

| file | holds |
|---|---|
| `run.jsonl` | one line per event: slot, header, each screen (row 24 and the full text), each action, the world reading, the save |
| `NN.png`, `NN.txt` | each new screen, numbered in the order seen |
| `world.png` | the screen at the world bar |
| `resave.D64` | the save disk after ENCAMP > SAVE, copied only once its directory is closed |
| `summary.json` | the title, the save, the header, the screen count, the first screen that is neither the party menu nor a disk prompt, the outcome, the area byte and square at the world bar, whether the save was written, and the experience rows |

Exit status 0 when the world bar was reached and the save written, 1
otherwise; every capture is on disk either way.  The player's disks are only
read: all seven images are copied into the slot's own directory.  Silent and
headless come from the pool and `POR_HEADLESS`.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.curse_of_the_azure_bonds.curseareazero import (  # noqa: E402
    HEADER_BYTES,
    PAYLOAD_AT,
)
from tools.registry import scratch  # noqa: E402

#: How long a screen is left alone after an action before the action is
#: repeated, and how many repeats are made before the run stops as stuck.
REPEAT_AFTER = 10.0
MAX_REPEATS = 3

#: The live party square.
LIVE_SQUARE = 0xC04B


def opening_step(row24: str, text: str, disk_wanted: bool) -> str:
    """What to do about a screen, from its bottom row alone.

    `disk` is tested before `return` because a side prompt also says PRESS ANY
    KEY, and Return at it is the mistake the prompt reader exists to avoid.
    """
    if disk_wanted:
        return "disk"
    if "MOVE" in row24 and "ENCAMP" in row24:
        return "world"
    if "GO BACK" in row24 and "LEAVE TREASURE" in row24:
        return "leave"
    if "TAKE" in row24 and "EXIT" in row24:
        return "exit"
    if row24.strip() == "EXIT":
        return "exit"
    if "YES" in row24 and "NO" in row24:
        return "no"
    if "PRESS" in row24 or "CONTINUE" in row24 or "MORE" in row24:
        return "return"
    return "wait"


def watch(read, save, act, disk_wanted, *, wait: float, max_screens: int = 200,
          clock=time.monotonic, sleep=time.sleep, poll: float = 0.5,
          repeat_after: float = REPEAT_AFTER, max_repeats: int = MAX_REPEATS,
          ) -> str:
    """Poll `read()` and answer what it shows; return why it stopped.

    `read()` gives the 25 rows joined by newlines, or None for a bitmap.
    A text that differs from the last one is passed to `save(n, text)` before
    `act(step, text)` is called for it.  After an action nothing is done again
    until the text changes; unchanged for `repeat_after` seconds, the same
    action is repeated, and after `max_repeats` repeats the run is `stuck`.
    A text that differs only above the row 24 last answered is saved and not
    answered again: the game redraws the screen under a prompt it has already
    taken the key for.
    Returns `world`, `stuck`, `timeout` or `screens` (the screen limit).
    """
    deadline = clock() + wait
    last, n = None, 0
    step, acted_at, repeats = "wait", 0.0, 0
    answered_row24 = None
    while clock() < deadline:
        text = read()
        if text is None:
            sleep(poll)
            continue
        if text != last:
            if n >= max_screens:
                return "screens"
            n += 1
            save(n, text)
            rows = text.split("\n")
            row24 = rows[24] if len(rows) > 24 else ""
            if answered_row24 is not None and row24 == answered_row24:
                last = text
                sleep(poll)
                continue
            answered_row24 = None
            last, repeats, acted_at = text, 0, None
            step = opening_step(row24, text, disk_wanted(text))
            if step == "world":
                return "world"
            if step != "wait":
                act(step, text)
                acted_at = clock()
                answered_row24 = row24
        elif step not in ("wait", "world") and acted_at is not None \
                and clock() - acted_at >= repeat_after:
            if repeats >= max_repeats:
                return "stuck"
            repeats += 1
            act(step, text)
            acted_at = clock()
        sleep(poll)
    return "timeout"


def experience_delta(before: dict[str, int], after: dict[str, int]) -> list[dict]:
    """One row per character name on either side: name, before, after, delta.

    A side that lacks the name gives None for that side and for the delta.
    """
    rows = []
    for name in list(before) + [n for n in after if n not in before]:
        b, a = before.get(name), after.get(name)
        rows.append({"name": name, "before": b, "after": a,
                     "delta": None if b is None or a is None else a - b})
    return rows


def first_opening_text(texts: list[str]) -> str | None:
    """The first screen that is not the party menu, a disk prompt or the loading screen."""
    for t in texts:
        if "ONWARD BOUND" in t:
            continue
        if "BEGIN ADVENTURING" in t or "CREATE NEW CHARACTER" in t:
            continue
        if "INSERT" in t and ("SIDE" in t or "DISK" in t):
            continue
        return t
    return None


def keyed_by_name(pairs) -> dict[str, int]:
    """`{name: experience}` from (name, experience) pairs in slot order.

    A second character with the same name is keyed `NAME (2)`, and so on, so
    that no row is lost and the two sides still match slot for slot.
    """
    out: dict[str, int] = {}
    for name, xp in pairs:
        key, k = name, 1
        while key in out:
            k += 1
            key = f"{name} ({k})"
        out[key] = xp
    return out


def experience_map(path: pathlib.Path) -> dict[str, int]:
    """`{name: experience}` for every character on a C64 save disk."""
    from goldbox import savegame  # noqa: PLC0415
    from goldbox.d64 import D64  # noqa: PLC0415
    sg0 = savegame.load_save(D64.from_bytes(pathlib.Path(path).read_bytes()))[1]
    return keyed_by_name((slot.record.name.strip(), slot.record.experience)
                         for slot in sg0.characters)


def answer_bar(sess, step: str, s, *, sleep=time.sleep) -> None:
    """Select EXIT, NO or LEAVE TREASURE, and press Return if row 24 has not changed.

    `leave` answers Silver Blades' `GO BACK LEAVE TREASURE`, as `ssbwarp`'s
    `enter_world` does: the party forgoes the starting equipment a player
    would take.  The experience comparison is unaffected, since it compares
    experience and not equipment.

    `s` is the screen the bar was read from.  A bitmap (None) on either side
    is waited out rather than compared.
    """
    label = {"exit": "EXIT", "leave": "LEAVE TREASURE"}.get(step, "NO")
    sess.select_bar(label, timeout=10)
    sleep(3)
    again = sess.screen()
    if s is not None and again is not None and again.row(24) == s.row(24):
        sess.press_kernal(0x0D)


def save_at_world(sess, shot, note, *, settle_s: float = 4) -> bool:
    """Let the world bar settle, camp and save, then photograph what the save left.

    The camp key sent the instant the bar is drawn is dropped while the view is
    still redrawing; the screenshot and row 24 say which bar a failed save
    stopped at.
    """
    sess.settle(settle_s)
    saved = bool(sess.save_game())
    shot("after-save")
    s = sess.screen()
    note(event="save", ok=saved, row24=None if s is None else s.row(24))
    return saved


def copy_resave(copy, repair, verify, src, dest, note, *, clock=time.time,
                attempts: int = 120, backoff: float = 0.5,
                raw_copy=shutil.copy):
    """Copy the save disk once its directory is closed, repairing the copy if it stays open.

    The first copy polls for `attempts * backoff` seconds.  If the entry is
    still open, the raw image is copied to `dest`, `repair(dest)` closes the
    entry on that copy and returns the entries it changed, and `verify(dest)`
    must read the party back from it.  The emulator's own disk is never
    detached or written.  A repair that changed nothing, or a copy that does
    not verify, is removed and raises.
    """
    t0 = clock()
    try:
        out = copy(src, dest, attempts=attempts, backoff=backoff)
    except RuntimeError as exc:
        note(event="copy", stage="polled", ok=False, error=str(exc),
             seconds=round(clock() - t0, 1))
        raw_copy(src, dest)
        try:
            changed = repair(dest)
            if not changed:
                raise RuntimeError(
                    f"the copy of {src} has no unclosed entry to repair "
                    f"after: {exc}")
            verify(dest)
        except BaseException:
            pathlib.Path(dest).unlink(missing_ok=True)
            raise
        note(event="copy", stage="repaired", ok=True, entries=changed,
             seconds=round(clock() - t0, 1))
        return str(dest)
    note(event="copy", stage="polled", ok=True, seconds=round(clock() - t0, 1))
    return out


def shut_down(sess, slot, write_summary) -> None:
    """Close the session and slot, then write the summary, whatever raises."""
    try:
        try:
            if sess is not None:
                sess.close()
        finally:
            slot.teardown()
    finally:
        try:
            write_summary()
        finally:
            slot.release()


def run(args) -> int:
    from automap import gamedisks  # noqa: PLC0415
    from goldbox import c64_save  # noqa: PLC0415
    from tools.c64 import savecheck  # noqa: PLC0415
    from tools.c64 import session as por  # noqa: PLC0415
    from tools.curse_of_the_azure_bonds import curseareazero  # noqa: PLC0415

    savecheck.catch_signals()
    os.environ.setdefault("POR_HEADLESS", "1")

    # Only `close_splat` (a file operation) is used from here, for both
    # titles; the module is Curse's by location, not by what these use.
    from tools.curse_of_the_azure_bonds import curseload  # noqa: PLC0415

    curse = args.title == "curse"
    found = args.disks or gamedisks.find(
        "curse-of-the-azure-bonds" if curse else "secret-of-the-silver-blades")
    if not found:
        raise SystemExit(f"no {args.title} disks; pass --disks")
    save = pathlib.Path(args.save).resolve()
    out = scratch.ensure(pathlib.Path(args.out))
    log = None

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    summary: dict = {"title": args.title, "save": str(save), "header": None,
                     "screens": 0, "first_opening_text": None,
                     "outcome": "not started", "area": None, "square": None,
                     "saved": False, "experience": []}
    texts: list[str] = []
    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "i653"))
    log = (out / "run.jsonl").open("a")
    sess = None
    try:
        note(event="slot", n=slot.n, dir=str(slot.dir), out=str(out))
        if curse:
            from tools.curse_of_the_azure_bonds import curserun  # noqa: PLC0415
            first = curserun.stage(slot, str(found), str(save))
            sess = curserun.CurseSession(first, slot=slot)
            container = c64_save.CURSE_OF_THE_AZURE_BONDS
        else:
            from tools.secret_of_the_silver_blades import ssbwarp  # noqa: PLC0415
            first = ssbwarp.stage(slot, str(found), save=str(save))
            sess = ssbwarp.SSBSession(first, slot=slot)
            container = c64_save.SECRET_OF_THE_SILVER_BLADES
        side0 = pathlib.Path(slot.dir) / "SIDE0.D64"
        os.chmod(side0, 0o644)
        sess.save_disk = str(side0)

        def shot(tag: str) -> None:
            sess.kbd.screenshot(str(out / f"{tag}.png"))
            s = sess.screen()
            text = "(bitmap)" if s is None else "\n".join(
                s.row(r) for r in range(25))
            (out / f"{tag}.txt").write_text(text + "\n")

        note(event="booting")
        if not sess.boot():
            note(event="boot-failed")
            summary["outcome"] = "boot failed"
            return 1
        shot("00-party-menu")
        if curse:
            outcome = curseload.load_saved_game(sess, note=note, shot=shot,
                                                wait=args.wait, tag="01-load")
            loaded = outcome == "loaded"
            note(event="load", outcome=outcome)
        else:
            loaded = ssbwarp.load_party(sess)
            note(event="load", outcome=loaded)
        if not loaded:
            summary["outcome"] = "load failed"
            return 1

        with sess.mon(5) as m:
            page = m.read(PAYLOAD_AT, HEADER_BYTES)
        header = curseareazero.fields(page, container)
        note(event="header", **header)
        summary["header"] = header
        hint = header["disk_hint"]
        if 1 <= hint <= 6:
            sess.attach(str(pathlib.Path(slot.dir) / f"SIDE{hint}.D64"))
            note(event="attached-side", side=hint)

        if not sess.select_row("BEGIN ADVENTURING"):
            note(event="begin-miss")
            summary["outcome"] = "begin missed"
            return 1
        time.sleep(3)
        s = sess.screen()
        if s is not None and "BEGIN ADVENTURING" in s.text():
            sess.press_kernal(0x0D)
        note(event="begin-pressed")

        seen_side = []

        current = [None]

        def read():
            s = current[0] = sess.screen()
            return None if s is None else "\n".join(s.row(r) for r in range(25))

        def wanted(text):
            return current[0] is not None and \
                sess.wanted_disk(current[0]) is not None

        def save_screen(n, text):
            tag = f"{n:02d}"
            sess.kbd.screenshot(str(out / f"{tag}.png"))
            (out / f"{tag}.txt").write_text(text + "\n")
            texts.append(text)
            note(event="screen", n=n, row24=text.split("\n")[24], text=text)

        def act(step, text):
            note(event="action", step=step)
            s = current[0]
            if step == "disk":
                if curse and "INSERT SIDE" in text and not seen_side:
                    seen_side.append(1)
                    note(event="wanted", **curseareazero.wanted_file(sess))
                    sess.patch_disk_prompt()
                sess.handle_prompt(s)
            elif step in ("exit", "no", "leave"):
                answer_bar(sess, step, s)
            elif step == "return":
                sess.press_kernal(0x0D)

        result = watch(read, save_screen, act, wanted, wait=args.wait)
        summary["screens"] = len(texts)
        summary["first_opening_text"] = first_opening_text(texts)
        summary["outcome"] = result
        note(event="watch-ended", outcome=result, screens=len(texts))
        if result != "world":
            shot("stuck")
            return 1

        st = sess.status()
        with sess.mon(5) as m:
            square = list(m.read(LIVE_SQUARE, 3))
            area = m.read(PAYLOAD_AT + container.current_script, 1)[0]
        summary["area"], summary["square"] = area, square
        note(event="world", status=str(st), square=square, area=area)
        sess.kbd.screenshot(str(out / "world.png"))

        saved = save_at_world(sess, shot, note)
        if saved:
            copy_resave(por.copy_closed_disk, curseload.close_splat,
                        experience_map, side0, out / "resave.D64", note)
            summary["saved"] = True
            summary["experience"] = experience_delta(
                experience_map(save), experience_map(out / "resave.D64"))
            note(event="experience", rows=summary["experience"])
        return 0 if saved else 1
    except BaseException as exc:
        note(event="failed", error=f"{type(exc).__name__}: {exc}")
        summary["outcome"] = f"failed: {exc}"
        raise
    finally:
        def write_summary():
            summary["first_opening_text"] = summary["first_opening_text"] or \
                first_opening_text(texts)
            (out / "summary.json").write_text(json.dumps(summary, indent=2))
            note(event="done")

        try:
            shut_down(sess, slot, write_summary)
        finally:
            log.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", required=True, choices=("curse", "ssb"))
    ap.add_argument("--save", required=True, help="the save disk to load")
    ap.add_argument("--disks", default="", help="where the six sides are")
    ap.add_argument("--pool", type=int, default=None)
    ap.add_argument("--wait", type=float, default=240.0)
    ap.add_argument("--out", default="",
                    help="default: a new directory under the cache")
    args = ap.parse_args(argv)
    if not args.out:
        args.out = str(scratch.cache_dir(
            "openingscene", f"{args.title}-{time.strftime('%Y%m%d-%H%M%S')}"))
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

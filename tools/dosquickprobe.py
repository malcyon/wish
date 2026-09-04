#!/usr/bin/env python3
"""Does DOS record `0x10F` hand a character to the computer in a fight?

The last open byte of `#235 (Two unattributed DOS byte ranges in the combat
tail are dropped converting to C64, and nobody knows what they hold)`.
`tools/dostailcensus.py` found `0x10F` reading 1 in every character the engine
resaved after a fight and 0 everywhere else, and the third-party DOS format
workbooks call it `IsQuickFight`.  That correlation cannot separate "QUICK was
pressed" from "a fight happened", because **every** fight in the corpus was
driven with `q` -- `tools/dosfightwatch.py` presses it at the combat bar by
design.

So this tests the byte by its **effect** instead of by its cause, which is the
stronger question anyway.  `goldbox-bugs.md` bug 3 has the C64 behaviour
CONFIRMED: QUICK sets a flag, nothing clears it, and `COMBAT` reads it at the
*start* of the next fight, so the character is still under computer control in
a fight the player never asked to quick-fight.  If DOS `0x10F` is that flag,
then a party staged with `0x10F` = 1 walks into its next fight already under
computer control -- and a driver that answers every screen **except** the
combat command bar will see the fight run to its end without one.  With
`0x10F` = 0 the same driver stalls at the first command bar and never gets
past it.

    tools/dosquickprobe.py --value 1 --label quick-on
    tools/dosquickprobe.py --value 0 --label quick-off

Two runs, one variable, and what is counted is how many command bars the
driver saw and whether the world bar ever came back.  The party is Donald's
own slot J, which stands in the Slums, because that is where wandering
encounters happen; New Phlan has none and a run started there walks for ever.

Nothing is written to the archives: `Session.stage` copies the game tree into
the instance's own work directory and that copy is what is tampered with.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_layout as dl  # noqa: E402
from tools import dosbox  # noqa: E402

OUT = REPO / "work" / "p235"

#: The byte under test, and the two neighbours read beside it so a run that
#: changes the wrong thing says so.
FIELD = "field_10c_10f"

#: Every rung the driver is allowed, and **`q` is deliberately not one of
#: them**.  A run that pressed QUICK would be measuring the same thing the
#: corpus already measured.  `c` answers the encounter menu, `Return` a
#: press-any-key prompt, `n` `CONTINUE BATTLE : YES NO`, `e` EXIT on a
#: treasure bar, `Escape` backs out of a sub-bar.
LADDER = ("c", "Return", "n", "e", "Escape")


def stage(save_dir: pathlib.Path, letter: str, value: int) -> list[dict]:
    """Set `0x10F` to `value` in all six of slot `letter`'s records."""
    f = dl.FIELDS_BY_NAME[FIELD]
    out = []
    for n in range(1, 7):
        path = save_dir / f"CHRDAT{letter.upper()}{n}.SAV"
        if not path.is_file():
            continue
        data = bytearray(path.read_bytes())
        before = bytes(data[f.offset:f.offset + f.size])
        data[f.offset + 3] = value
        path.write_bytes(bytes(data))
        out.append({"file": path.name, "before": before.hex(),
                    "staged": bytes(data[f.offset:f.offset + f.size]).hex()})
    return out


def walk_to_encounter(por, presses: int, log: list) -> dict:
    """Press forward until the world bar stops coming back."""
    for i in range(presses):
        before = por.s.capture().digest()
        if not por.step():
            log.append({"step": i, "event": "world bar did not return"})
            return {"stopped_at": i, "why": "world bar did not return"}
        if por.s.capture().digest() == before:
            por.turn_right()
    return {"stopped_at": None, "why": f"no encounter in {presses} presses"}


def drive(por, budget: float, dwell: float, log: list) -> dict:
    """Answer everything but the combat command bar, and count what is seen."""
    seen: dict[str, int] = {}
    deadline = time.time() + budget
    rung = 0
    bar = None
    world_since = None
    while time.time() < deadline:
        screen = por.s.capture()
        kind = por.bar_kind(screen) or "unknown"
        seen[kind] = seen.get(kind, 0) + 1
        glyphs = screen.glyphs(dosbox.BAR)
        if glyphs == por.world_glyphs:
            world_since = world_since or time.time()
            if time.time() - world_since >= 5.0:
                return {"finished": "world bar held 5s", "bars": seen}
            time.sleep(0.25)
            continue
        world_since = None
        if kind == "command":
            # The screen under test.  Nothing is pressed at it: pressing
            # anything here is the measurement destroying itself.
            time.sleep(0.5)
            continue
        if glyphs != bar:
            bar, rung = glyphs, 0
        por.s.key(LADDER[rung % len(LADDER)])
        rung += 1
        por.s.wait_while_glyphs(dosbox.BAR, glyphs, timeout=dwell)
    return {"finished": "budget", "bars": seen}


def run(value: int, source: str, resave: str, label: str, presses: int,
        budget: float) -> dict:
    shots = OUT / label
    shots.mkdir(parents=True, exist_ok=True)
    log: list = []
    result: dict = {"value": value, "source": source, "label": label}

    slot = dosbox.claim(f"issue235 {label}")
    session = dosbox.Session(slot, dosbox.find_game())
    try:
        session.stage(fresh=True)
        for stale in session.save_dir.glob(f"CHRDAT{resave.upper()}*"):
            stale.unlink()
        for stale in session.save_dir.glob(f"SAVGAM{resave.upper()}*"):
            stale.unlink()
        result["staged"] = stage(session.save_dir, source, value)

        session.boot(fresh=False)
        game = dosbox.PoolOfRadiance(session)
        game.to_main_menu()
        game.load_game(source)
        session.shot("00-loaded")
        result["walk"] = walk_to_encounter(game, presses, log)
        session.shot("01-stopped", allow_blank=True)
        result["drive"] = drive(game, budget, 1.5, log)
        session.shot("02-after-drive", allow_blank=True)
        try:
            game.save_game(resave)
            f = dl.FIELDS_BY_NAME[FIELD]
            xp = dl.FIELDS_BY_NAME["experience"]
            result["after"] = [
                {"file": p.name,
                 "value": p.read_bytes()[f.offset:f.offset + f.size].hex(),
                 "hp": p.read_bytes()[
                     dl.FIELDS_BY_NAME["hp_current"].offset],
                 # Experience is the only ground truth for "the party
                 # fought" -- the screen cannot say it and the bar tally
                 # only says what the driver was shown.
                 "xp": int.from_bytes(
                     p.read_bytes()[xp.offset:xp.offset + xp.size], "little")}
                for p in sorted(
                    session.save_dir.glob(f"CHRDAT{resave.upper()}?.SAV"))]
        except Exception as exc:
            result["after_error"] = str(exc)
        # Only this run's own named frames: a slot's `shots/` survives
        # `stage(fresh=True)`, so copying all of it drags in whatever the
        # slot's last occupant took.
        for name in ("00-loaded", "01-stopped", "02-after-drive"):
            png = session.dir / "shots" / f"{name}.png"
            if png.is_file():
                shutil.copy(png, shots / png.name)
    finally:
        session.close()
        slot.release()
    result["log"] = log
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--value", type=int, default=1,
                    help="what to stage into 0x10F (default 1)")
    ap.add_argument("--source", default="J", help="save slot to load (J)")
    ap.add_argument("--resave", default="D", help="slot to write back to (D)")
    ap.add_argument("--label", default="quick", help="output subdirectory")
    ap.add_argument("--presses", type=int, default=60,
                    help="forward presses to spend looking for a fight")
    ap.add_argument("--budget", type=float, default=180.0,
                    help="seconds to drive the fight for")
    args = ap.parse_args(argv)

    result = run(args.value, args.source, args.resave, args.label,
                 args.presses, args.budget)
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / f"{args.label}.json"
    report.write_text(json.dumps(result, indent=1))
    print(json.dumps({k: result[k] for k in ("value", "walk", "drive")
                      if k in result}, indent=1))
    for row in result.get("after", []):
        print(f"  {row['file']} {row['value']} hp={row['hp']}")
    print(f"\n{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

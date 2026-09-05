#!/usr/bin/env python3
"""What happens to a party member whose DOS record says `0x10E` = 1?

`GAME.OVR` reads character-record byte `0x10E` as the combat **side** -- 0
the party's, 1 the enemy's -- for `#235 (Two unattributed DOS byte ranges in
the combat tail are dropped converting to C64, and nobody knows what they
hold)`: the resident code counts the combatants still standing per side
into `ds:0x6814[side]`, the fight ends when a side's count reaches zero,
the target picker walks "the other side", and the party panel draws a
side-1 name yellow.  `tools/dostailprobe.py` showed the yellow name on the
main screen and that the byte survives a load and a resave.  This is the
fight: what the engine does to a party member it counts as an enemy.

    tools/dossideprobe.py                       # party position 1 on side 1
    tools/dossideprobe.py --side-slot 3 --label side-fight-3

One character of Donald's slot J (the Slums, where wandering encounters
happen) gets `0x10E` = 1; **every** character gets `0x10F` = 1 so the fight
runs under computer control and the driver never has to choose a command --
`tools/dosquickprobe.py` proved that with `0x10F` = 1 the combat command
bar never appears.  The driver answers the encounter menu, press-any-key
prompts, `CONTINUE BATTLE`, treasure and sub-bars with the same ladder, and
photographs the screen every few seconds while the fight runs, so what the
engine did to the side-1 character is on film as well as in the resave.

Nothing is written to the archives: `Session.stage` copies the game tree
into the instance's own work directory and that copy is what is tampered
with.  Frames and the report go under `work/issue235/<label>/`.
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
from tools.dosquickprobe import LADDER, walk_to_encounter  # noqa: E402

OUT = REPO / "work" / "issue235"

FIELD = "field_10c_10f"
SIDE = 2        # 0x10E within the four-byte field
QUICK = 3       # 0x10F


def stage(save_dir: pathlib.Path, letter: str, side_slot: int,
          quick: bool) -> list[dict]:
    """Put party position `side_slot` on side 1; quickfight everybody."""
    f = dl.FIELDS_BY_NAME[FIELD]
    out = []
    for n in range(1, 7):
        path = save_dir / f"CHRDAT{letter.upper()}{n}.SAV"
        if not path.is_file():
            continue
        data = bytearray(path.read_bytes())
        before = bytes(data[f.offset:f.offset + f.size])
        if n - 1 == side_slot:
            data[f.offset + SIDE] = 1
        if quick:
            data[f.offset + QUICK] = 1
        path.write_bytes(bytes(data))
        out.append({"file": path.name, "slot": n - 1,
                    "name": data[1:1 + data[0]].decode("latin1"),
                    "before": before.hex(),
                    "staged": bytes(data[f.offset:f.offset + f.size]).hex(),
                    "hp": data[dl.FIELDS_BY_NAME["hp_current"].offset]})
    return out


def drive(por, budget: float, dwell: float, frame_every: float,
          log: list) -> dict:
    """Answer everything but the combat command bar; film as it goes."""
    seen: dict[str, int] = {}
    deadline = time.time() + budget
    rung = 0
    bar = None
    world_since = None
    last_frame = 0.0
    frames = 0
    while time.time() < deadline:
        screen = por.s.capture()
        kind = por.bar_kind(screen) or "unknown"
        seen[kind] = seen.get(kind, 0) + 1
        if time.time() - last_frame >= frame_every:
            por.s.shot(f"fight-{frames:02d}", allow_blank=True)
            log.append({"frame": frames, "kind": kind,
                        "t": round(time.time(), 1)})
            frames += 1
            last_frame = time.time()
        glyphs = screen.glyphs(dosbox.BAR)
        if glyphs == por.world_glyphs:
            world_since = world_since or time.time()
            if time.time() - world_since >= 5.0:
                return {"finished": "world bar held 5s", "bars": seen,
                        "frames": frames}
            time.sleep(0.25)
            continue
        world_since = None
        if kind == "command":
            time.sleep(0.5)
            continue
        if glyphs != bar:
            bar, rung = glyphs, 0
        por.s.key(LADDER[rung % len(LADDER)])
        rung += 1
        por.s.wait_while_glyphs(dosbox.BAR, glyphs, timeout=dwell)
    return {"finished": "budget", "bars": seen, "frames": frames}


def read_back(save_dir: pathlib.Path, letter: str) -> list[dict]:
    f = dl.FIELDS_BY_NAME[FIELD]
    hp = dl.FIELDS_BY_NAME["hp_current"]
    xp = dl.FIELDS_BY_NAME["experience"]
    out = []
    for p in sorted(save_dir.glob(f"CHRDAT{letter.upper()}?.SAV")):
        d = p.read_bytes()
        out.append({"file": p.name, "name": d[1:1 + d[0]].decode("latin1"),
                    "value": d[f.offset:f.offset + f.size].hex(),
                    "hp": d[hp.offset],
                    "xp": int.from_bytes(d[xp.offset:xp.offset + xp.size],
                                         "little")})
    return out


def run(side_slot: int, quick: bool, source: str, resave: str, label: str,
        presses: int, budget: float, frame_every: float) -> dict:
    shots = OUT / label
    shots.mkdir(parents=True, exist_ok=True)
    log: list = []
    result: dict = {"side_slot": side_slot, "quick": quick,
                    "source": source, "label": label}

    slot = dosbox.claim(f"issue235 {label}")
    session = dosbox.Session(slot, dosbox.find_game())
    try:
        session.stage(fresh=True)
        for stale in session.save_dir.glob(f"CHRDAT{resave.upper()}*"):
            stale.unlink()
        for stale in session.save_dir.glob(f"SAVGAM{resave.upper()}*"):
            stale.unlink()
        result["staged"] = stage(session.save_dir, source, side_slot, quick)

        session.boot(fresh=False)
        game = dosbox.PoolOfRadiance(session)
        game.to_main_menu()
        game.load_game(source)
        session.shot("00-loaded")
        result["walk"] = walk_to_encounter(game, presses, log)
        session.shot("01-stopped", allow_blank=True)
        result["drive"] = drive(game, budget, 1.5, frame_every, log)
        session.shot("02-after-drive", allow_blank=True)
        try:
            game.save_game(resave)
            result["after"] = read_back(session.save_dir, resave)
        except Exception as exc:
            result["after_error"] = str(exc)
        # Only this run's own frames, by exact name: a slot's `shots/`
        # survives `stage(fresh=True)`, and a prefix match once dragged a
        # previous occupant's `00-main-menu.png` in beside this run's.
        own = ["00-loaded", "01-stopped", "02-after-drive"] + [
            f"fight-{k:02d}" for k in range(result["drive"]["frames"])]
        for name in own:
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
    ap.add_argument("--side-slot", type=int, default=1,
                    help="0-based party position to put on side 1 (1)")
    ap.add_argument("--no-quick", action="store_true",
                    help="leave 0x10F alone instead of setting it on all six")
    ap.add_argument("--source", default="J", help="save slot to load (J)")
    ap.add_argument("--resave", default="D", help="slot to write back to (D)")
    ap.add_argument("--label", default="side-fight",
                    help="output subdirectory under work/issue235")
    ap.add_argument("--presses", type=int, default=60,
                    help="forward presses to spend looking for a fight")
    ap.add_argument("--budget", type=float, default=300.0,
                    help="seconds to drive the fight for")
    ap.add_argument("--frame-every", type=float, default=6.0,
                    help="seconds between frames while the fight runs")
    args = ap.parse_args(argv)

    result = run(args.side_slot, not args.no_quick, args.source, args.resave,
                 args.label, args.presses, args.budget, args.frame_every)
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / f"{args.label}.json"
    report.write_text(json.dumps(result, indent=1))
    print(json.dumps({k: result[k] for k in ("side_slot", "walk", "drive")
                      if k in result}, indent=1))
    for row in result.get("staged", []):
        print(f"  staged {row['name']:16s} {row['staged']} hp={row['hp']}")
    for row in result.get("after", []):
        print(f"  after  {row['name']:16s} {row['value']} hp={row['hp']} "
              f"xp={row['xp']}")
    if "after_error" in result:
        print(f"  resave failed: {result['after_error']}")
    print(f"\n{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

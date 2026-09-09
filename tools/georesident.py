#!/usr/bin/env python3
"""How far the resident map block drifts from its disk copy, in a driven game.

`automap.area.NEAR_ENOUGH` is the tolerance `ResidentGeo.verdict` allows
between the 1024 bytes at `$0400` and the `GEO` file they were loaded from.
Its stated reason is that *"the running game is allowed to write into the block
it is drawing"*, and nobody had ever measured that: every reading this project
has recorded -- New Phlan, the Slums, Sokol Keep, an Amiga Silver Blades area
-- matched its disk copy exactly, which says the tolerance was never the thing
standing between a session and a wrong answer.

This takes the measurement rather than repeating the claim.  It boots Pool of
Radiance in a pooled instance, loads a save, and then, for every step of a
route:

* asks the shipped `ResidentGeo.verdict` what the block is, against the maps
  `automap.maps.load_maps` reads off the player's own disks -- the same call
  the automapper makes, not a re-implementation of it;
* records the distance to the nearest map and to every other one, so an exact
  match is distinguishable from a near one;
* reads two **counting** VICE checkpoints armed over `$0400`-`$07FF`, one for
  loads and one for stores.

The load counter is the positive control: the engine draws the view from that
block, so a load count of zero would mean the checkpoints are measuring
nothing.  The store counter is the measurement -- every write into the block
while one map stays loaded, whoever makes it.

    tools/georesident.py --save PORSAVE13.D64 --route IIIIII --out work/issue447/run1

Crossing an area boundary is the other half, and `--route` is how it is asked
for: the loader filling the page for the new area is a legitimate store, and
the counter should jump by about a thousand exactly once per crossing while
staying flat in between.

The player's disks are read and never written -- everything the game is shown
is `stage_disks`' copy inside the slot.  Writes `run.jsonl` and one screenshot
per step into `--out`.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))

from automap.area import NEAR_ENOUGH, RESIDENT_GEO, ResidentGeo, _distance  # noqa: E402
from automap.maps import load_maps  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from goldbox.geo import GEO_SIZE  # noqa: E402
from tools import curseload  # noqa: E402
from tools import session as por  # noqa: E402

#: The page the loader leaves a `GEO` file on and never moves it.
BLOCK, BLOCK_END = RESIDENT_GEO, RESIDENT_GEO + GEO_SIZE - 1

#: The loaded-files cache while the game runs -- 25 slots naming what the
#: loader last fetched, `docs/140-loaded-files-cache.md`.  Read at every
#: sample so a page that has stopped being a map can be attributed to the file
#: that landed on it rather than guessed at.
CACHE, CACHE_LEN = 0x6E13, 25


def disks_dir(given: str | None) -> str:
    """`$POR_DISKS`, then `automap.paths.find_disks()` -- never a fourth way."""
    if given:
        return given
    env = os.environ.get("POR_DISKS")
    if env:
        return env
    found = find_disks()
    if found is None:
        raise SystemExit("no Pool of Radiance disks; set $POR_DISKS")
    return str(found)


def reading(mon, maps) -> dict:
    """What the shipped check says about the block this instant.

    `verdict` is called rather than reimplemented, so this tool cannot
    disagree with the code it is measuring.  The distances are taken
    separately because `verdict` reports only its answer, and the whole
    question here is *how far* the block is from the map it names.
    """
    raw = mon.read(BLOCK, GEO_SIZE)
    answer, name = ResidentGeo(mon).verdict(maps)
    distances = sorted((_distance(raw, geo.to_bytes()), n)
                       for n, geo in maps.items())
    nearest, nearest_name = distances[0]
    return {"verdict": answer, "named": name, "nearest": nearest,
            "nearest_name": nearest_name, "exact": nearest == 0,
            "second": distances[1][0] if len(distances) > 1 else None,
            "second_name": distances[1][1] if len(distances) > 1 else None,
            "within_tolerance": nearest <= NEAR_ENOUGH,
            "nonzero_bytes": sum(1 for b in raw if b),
            "head": raw[:16].hex(" "),
            "cache": mon.read(CACHE, CACHE_LEN).hex(" ")}


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    disks = disks_dir(args.disks)
    maps = load_maps(disks)
    if not maps:
        note(event="no-maps", disks=disks)
        return 1
    note(event="maps", disks=disks, count=len(maps), names=sorted(maps))

    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "i447"))
    note(event="slot", n=slot.n, monitor=slot.port, display=slot.display,
         dir=str(slot.dir))
    boot = por.stage_disks(slot, disks, args.save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    os.chmod(save_disk, 0o644)
    sess = por.Session(boot, slot=slot)
    sess.save_disk = save_disk
    cps: dict[str, int] = {}
    drifted = 0
    try:
        if not sess.boot():
            note(event="boot-failed")
            return 1
        if not sess.load_save():
            note(event="load-failed")
            sess.kbd.screenshot(str(out / "load-failed.png"))
            return 1
        if not sess.begin_adventuring():
            note(event="no-world")
            sess.kbd.screenshot(str(out / "no-world.png"))
            return 1
        sess.settle(3)
        note(event="in-the-world", position=list(sess.position()),
             status=str(sess.status()))

        with sess.mon(10) as m:
            note(event="before-arming", **reading(m, maps))
            # Armed only now.  At the title screen and in the menus the C64's
            # own screen is at `$0400`, so a checkpoint armed before the world
            # is drawn counts the KERNAL's character writes and says nothing
            # about the game.
            cps["load"] = m.checkpoint_set(BLOCK, BLOCK_END, load=True,
                                           stop=False)
            cps["store"] = m.checkpoint_set(BLOCK, BLOCK_END, store=True,
                                            stop=False)
            note(event="armed", **cps)

        def sample(tag: str, **extra) -> dict:
            with sess.mon(10) as m:
                got = reading(m, maps)
                got.update(
                    loads=curseload.checkpoint_hits(m, cps["load"]),
                    stores=curseload.checkpoint_hits(m, cps["store"]))
            note(event="sample", at=tag, **got, **extra)
            return got

        got = sample("00-world")
        if args.shots:
            sess.kbd.screenshot(str(out / "00-world.png"))
        drifted += not got["exact"]
        readings, off_map = 1, 0
        for i, move in enumerate(args.route.upper()):
            before = list(sess.position())
            try:
                moved = sess.walk_one(move)
                sess.settle(args.settle)
            except (por.MonitorError, OSError) as exc:
                # A fight, a menu or a picture leaves the driver arguing with
                # a screen it does not know, and the reading is the point
                # here rather than the walk. Record it and stop walking.
                note(event="walk-failed", at=f"{i + 1:02d}-{move}",
                     error=f"{type(exc).__name__}: {exc}")
                break
            got = sample(f"{i + 1:02d}-{move}", move=move, moved=moved,
                         before=before, after=list(sess.position()))
            if args.shots:
                sess.kbd.screenshot(str(out / f"{i + 1:02d}-{move}.png"))
            readings += 1
            drifted += not got["exact"]
            # The page is a map only while one is loaded: in combat it holds
            # `SQRPACI`, and mid-load it holds half of something. Neither is
            # drift, so walking on measures nothing.
            off_map = 0 if got["verdict"] == "ours" else off_map + 1
            if off_map >= args.give_up:
                note(event="no-map", at=f"{i + 1:02d}-{move}",
                     consecutive=off_map)
                break
        for i in range(args.idle):
            time.sleep(args.interval)
            got = sample(f"idle-{i:02d}")
            readings += 1
            drifted += not got["exact"]
        note(event="done", readings=readings, drifted=drifted,
             stores=got.get("stores"), loads=got.get("loads"))
        return 0
    finally:
        try:
            with sess.mon(5) as m:
                for number in cps.values():
                    try:
                        m.checkpoint_delete(number)
                    except Exception:
                        pass
        except Exception:
            pass
        sess.close()
        slot.release()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--save", default="PORSAVE13.D64",
                    help="a save disk in the disks directory, staged as SIDE0")
    ap.add_argument("--disks", default=None)
    ap.add_argument("--route", default="IIII",
                    help="I forward, J left, K right, M about")
    ap.add_argument("--out", default="work/issue447/georesident")
    ap.add_argument("--idle", type=int, default=0,
                    help="extra readings taken standing still")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--settle", type=float, default=2.0)
    ap.add_argument("--shots", action="store_true")
    ap.add_argument("--give-up", type=int, default=2,
                    help="stop walking after this many readings in a row "
                         "where the page is not a map at all")
    ap.add_argument("--pool", type=int, default=None,
                    help="a specific instance-pool slot; otherwise the next free")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

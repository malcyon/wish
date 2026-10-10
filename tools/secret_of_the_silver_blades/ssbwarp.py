#!/usr/bin/env python3
"""Fast-travel a *Secret of the Silver Blades* party, to confirm the area
table against the running machine.

`#20 (Build an area table for Silver Blades)` is the ticket. `tools/areas/newecl.py`
found the addresses off this title's own overlays and `tools/areas/areatable.py`
built the table off its own scripts; both are static readings, so every row of
`goldbox.areas.AREAS_SILVER_BLADES` is PROBABLE. **A party warped into an area
that then draws that area's map is what makes a row CONFIRMED**, and that is
what this measures.

    tools/secret_of_the_silver_blades/ssbwarp.py --pool 3 --probe --out DIR
    tools/secret_of_the_silver_blades/ssbwarp.py --pool 3 --to 0x22,0x50,0x60 --via-actions \
        --spoil-from 2 --walk --out DIR
    tools/secret_of_the_silver_blades/ssbwarp.py --pool 3 --to 0x20 --via-actions --back \
        --save C64_PARTY_IN_0x10.D64 --out DIR

`--probe` boots, loads a party and reports what the machine holds without
warping; it is what to run first, because the current area and the indoors
flag both decide whether a warp is legal.

**`--to` is a chain.** A boot costs about five minutes and a hop about
thirty seconds, so one session confirms as many rows as it has targets. Each
hop leaves from wherever the last one landed.

**`--via-actions` is the trip a player makes.** It hands the row to
`automap.actions.FastTravel`, which has its own address table, its own
legality chain and its own jump; this file's `warp` reproduces the same six
writes its own way and proves nothing about the code that ships.

**The party never has to reach a command bar.** Eight earlier sessions tried
to answer the prologue's starting-treasure bar `VIEW TAKE POOL SHARE EXIT`
and each ended on a character sheet instead. `NEWECL`'s tail rebuilds the
stack pointer from `$03BF` and re-enters `DUNGEON` at `$0809`, so a warp
discards whatever the script VM had in flight whether it left from the
command bar or from a menu -- and a script's one-option menu waits for a key
in the same `LIBRARY` fetcher the command bar does. `enter_world` leaves at
the first moment the machine is demonstrably idle there.

**Six writes, not five.** Silver Blades' `NEWECL` zeroes `$4BFB` as well as the
32 bytes of scratch, which Pool of Radiance's and Curse's do not -- read off
the handler by `#19`. Eighteen of the twenty-two scripts set that byte again in
their own entry 4, so a driver that skipped it would be right by accident most
of the time; `ECL11`, `ECL44`, `ECL61` and `ECL62` never touch it and are where
it would show. The write is made here because the game makes it.

**Do not read the status line to check a step.** `$4BFB` is what suppresses the
coordinates on it -- `DUNGEON $0A0E` is `LDA $4BFB / BNE` over the block that
prints them -- and eleven of the twenty-two areas set it to 1 on arrival. The
live triple `$C04B`-`$C04D` is the only reliable reader, which is what `#19`
found the hard way in Curse.

Nothing is written to the player's disks: the six sides are copied into the
pool slot and every other byte this writes goes to RAM.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.actions import pc_register  # noqa: E402
from goldbox import areas, c64_port  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools.c64 import session as por  # noqa: E402
from tools.registry import scratch  # noqa: E402
from tools.secret_of_the_silver_blades.ssbsession import (  # noqa: E402
    LIVE_X,
    Addresses,
    SSBSession,
    clear_messages,
    enter_world,
    idle_in_key_window,
    load_party,
    snapshot,
    stage,
)

#: How long to give an arrival that comes off a floppy. A ceiling on a poll of
#: the program counter, not a fixed settle -- a fixed settle is a measurement
#: of the harness rather than of the game.
ARRIVAL_TIMEOUT = 240.0

def pc_histogram(sess, addr, samples: int = 60, gap: float = 0.05) -> dict:
    """Where the CPU actually is, when it is not where it should be.

    A `wait_idle` that times out says only "not in a key window", which is
    the form of a hang, a fight and a full-screen picture alike. Sixty
    samples say which: a tight cluster is a loop and a spread is code that is
    getting on with something.
    """
    seen: dict[str, int] = {}
    for _ in range(samples):
        try:
            with sess.mon(5) as m:
                pc = m.registers().get(pc_register(m))
        except Exception:
            break
        if pc is not None:
            seen[f"${pc:04X}"] = seen.get(f"${pc:04X}", 0) + 1
        time.sleep(gap)
    windows = {"key_wait": addr.key_wait, "key_fetch": addr.key_fetch}
    hit = {name: sum(n for k, n in seen.items()
                     if lo <= int(k[1:], 16) < hi)
           for name, (lo, hi) in windows.items()}
    return {"samples": dict(sorted(seen.items(), key=lambda kv: -kv[1])[:12]),
            "in_windows": hit}


def ssb_maps(disks: str) -> dict:
    """Every `GEO` on every side, by name. Read once and reused."""
    from goldbox.geo import load_geo_files
    out: dict = {}
    for path in sorted(pathlib.Path(disks).glob("*.[dD]64")):
        try:
            out.update(load_geo_files(D64.open(str(path))))
        except Exception:
            continue
    return out


def resident_geo(sess, maps: dict) -> dict:
    """Which map is the one drawn at `$0400`, if any.

    `automap/area.py`'s verdict: an exact match against the disk copies
    first, then reciprocity and shared walled edges. A warp that lands has to
    change this, and a warp that only *looks* like it landed will not.
    """
    from automap.area import ResidentGeo

    class _Block:
        def __init__(self, data):
            self.data = data

        def read(self, addr, length):
            return self.data[addr - 0x0400:addr - 0x0400 + length]

    try:
        with sess.mon(8) as m:
            block = m.read(0x0400, 1024)
        verdict, name = ResidentGeo(_Block(block)).verdict(maps)
        return {"verdict": verdict, "name": name}
    except Exception as exc:                                # pragma: no cover
        return {"verdict": "unreadable", "name": None, "error": str(exc)}


def wait_idle(sess, addr: Addresses, timeout: float = ARRIVAL_TIMEOUT):
    """Poll until the PC is back in the key-wait loop or its fetcher."""
    windows = (addr.key_wait, addr.key_fetch)
    deadline = time.time() + timeout
    pc = None
    while time.time() < deadline:
        try:
            with sess.mon(6) as m:
                pc = m.registers().get(pc_register(m))
        except Exception:
            pc = None
        if pc is not None and any(lo <= pc < hi for lo, hi in windows):
            return True, pc
        sess.handle_prompt()
        time.sleep(0.5)
    return False, pc


def warp(sess, addr: Addresses, target: int, disk: int,
         square: tuple[int, int, int] | None) -> dict:
    """`NEWECL`'s own writes, made from outside, then its tail.

    The order is the handler's, with the operand fetch left out because there
    is no script stream to fetch from. **Six writes**: the sixth is
    `addr.extra`, which the handler zeroes and Pool of Radiance's does not.
    """
    made = {}
    with sess.mon(10) as m:
        m.write(addr.disk, bytes([disk]))
        made["disk"] = disk
        if square is not None:
            m.write(LIVE_X, bytes(square))
            made["square"] = list(square)
        here = m.peek(addr.slot) & 0x7F
        m.write(addr.came_from, bytes([here]))
        made["came_from"] = here
        m.write(addr.slot, bytes([target | 0x80]))
        made["slot"] = target | 0x80
        m.write(addr.scratch, bytes(32))
        made["scratch_zeroed"] = 32
        if addr.extra:
            m.write(addr.extra, b"\x00")
            made["extra_zeroed"] = addr.extra
        rid = pc_register(m)
        m.set_registers({rid: addr.tail})
        made["pc"] = addr.tail
        m.resume()
    return made


class SessTarget:
    """`automap.actions`' Target contract over this session's monitor.

    The same four methods `tools/curse_of_the_azure_bonds/cursewarp.py` wraps a Curse session in. It is
    what makes `--via-actions` exercise the code the window ships rather than
    this file's own `warp`: the two write the same bytes, and only one of them
    is what a player clicking Fast Travel runs.
    """

    def __init__(self, sess):
        self.sess = sess

    def read(self, addr: int, length: int) -> bytes:
        with self.sess.mon(5) as m:
            return m.read(addr, length)

    def write(self, addr: int, data) -> None:
        with self.sess.mon(5) as m:
            m.write(addr, bytes(data))

    def pc(self):
        with self.sess.mon(5) as m:
            return m.registers().get(pc_register(m))

    def set_pc(self, address: int) -> None:
        with self.sess.mon(5) as m:
            m.set_registers({pc_register(m): address})


def warp_via_actions(target, game, row, square, ft=None) -> dict:
    """The same trip, made by `automap.actions.FastTravel` itself.

    **A tool that reproduces a result its own way says nothing about the code
    that ships.** `FastTravel.legality` has its own address table
    (`automap/fasttravel.py`), its own guards and its own jump, and a Silver
    Blades row of that table has never been acted on. The row handed in is
    `goldbox.areas.Area` itself rather than a shim, so what gets written is
    the id, side and arrival square the table actually holds.
    """
    from automap import actions

    if ft is None:
        ft = actions.FastTravel(game)
    verdict = ft.legality(target, row)
    out = {"legal": bool(verdict), "reason": verdict.reason,
           "addresses": ft.addresses.title if ft.addresses else None}
    if not verdict:
        return out
    outcome = ft.apply(target, area=row,
                       arrival=tuple(square) if square else None)
    out["ok"] = outcome.ok
    out["message"] = outcome.message
    out["writes"] = [[at, list(data)] for at, data in outcome.writes]
    out["notes"] = list(outcome.notes)
    return out


def geo_in_ram(sess, maps: dict, low: int = 0x0200, high: int = 0x10000,
               chunk: int = 0x1000) -> dict:
    """Where any known map's exact 1024 bytes sit in RAM, by name.

    `resident_geo` reads `$0400` because that is where a `GEO` PRG loads, and
    that is a Pool of Radiance measurement. This asks the question without the
    address: sweep RAM and look for the bytes. It is the backstop for a
    verdict of `unknown`, and an empty answer is itself a reading -- the map
    the table expects is not in memory anywhere.
    """
    blob = bytearray()
    try:
        with sess.mon(30) as m:
            for a in range(low, high, chunk):
                blob += m.read(a, min(chunk, high - a))
    except Exception as exc:                                # pragma: no cover
        return {"error": str(exc)}
    raw = bytes(blob)
    return {name: low + raw.find(geo.to_bytes())
            for name, geo in maps.items() if geo.to_bytes() in raw}


def walk_proof(sess, keys: str = "JIKI") -> dict:
    """Can the party that arrived actually move?

    One key, one reading, and the command bar read before each: a key sent an
    unknown number of times cannot be read off a table, and the session
    leaves MOVE mode after the first key.
    """
    out = {"bar": clear_messages(sess)}
    if "ENCAMP" not in out["bar"]:
        # No world bar, so nothing to walk from: `clear_messages` says why.
        out.update(rejected=out["bar"], moved=False, turned=False)
        return out

    def triple():
        with sess.mon(8) as m:
            return list(m.read(LIVE_X, 3))

    out["triple_before"] = triple()
    steps = []
    for key in keys:
        s = sess.screen()
        bar = s.row(24).strip() if s is not None else ""
        if "I,J,K,M" not in bar:
            sess.select_bar("MOVE", timeout=10)
            time.sleep(0.8)
            s = sess.screen()
            bar = s.row(24).strip() if s is not None else ""
        sess.kbd.key(key.lower(), 0.15, 0.30)
        time.sleep(1.4)
        steps.append({"key": key, "bar": bar, "triple": triple()})
    out["steps"] = steps
    out["triple_after"] = steps[-1]["triple"] if steps else out["triple_before"]
    out["moved"] = out["triple_after"][:2] != out["triple_before"][:2]
    out["turned"] = any(s["triple"][2] != out["triple_before"][2]
                        for s in steps)
    sess.leave_move()
    return out


def return_via_actions(sess, addr, maps, ft, target, row, out: pathlib.Path,
                       tag: str, origin: int,
                       timeout: float = ARRIVAL_TIMEOUT,
                       departure: int | None = None) -> dict:
    """Return to where the last trip started, on the same `FastTravel` object.

    `back` is set by `FastTravel.apply`, so the object that made the hop has to
    be the one that goes back. The landing is recorded as a hop's is: the
    machine's state, with the live `$C04B`-`$C04D` triple, and a screenshot.
    It counts as landed only in `origin`, the area the hop left; a Return that
    ends elsewhere is reported with `reached_target` false.
    """
    # A Return written while the machine is not in a key window is the write
    # the hop loop's guard exists to prevent.
    pc = idle_in_key_window(sess, addr)
    if pc is None:
        why = "the machine is not idle in a key window; Return not made"
        print(why, flush=True)
        return {"skipped": why, "landed": False}
    outcome = ft.apply_back(target)
    made = {"ok": outcome.ok, "message": outcome.message,
            "writes": [[at, list(data)] for at, data in outcome.writes]}
    print("wrote back:", json.dumps(made), flush=True)
    if not outcome.ok:
        return {"back": made, "landed": False}
    idle, _pc = wait_idle(sess, addr, timeout)
    sess.settle(3)
    after = measure(sess, addr, maps, row, out, tag)
    expect_arrival(after, row, departure)
    after["idle"] = idle
    reached = after.get("area") == origin
    after["reached_target"] = reached
    res = {"back": made, "landed": reached, "reached_target": reached,
           "idle": idle, "state": after, "square": after["square"]}
    if row is not None:
        res["verdict"] = verdict_of(after, row, departure=departure)
    if not reached:
        print(f"Return ended in ${after.get('area', 0):02X}, not "
              f"${origin:02X}", flush=True)
    return res


def screen_text(sess, path: pathlib.Path | None = None) -> str:
    """What the screen says now, saved beside the capture if asked."""
    s = sess.screen()
    text = s.text() if s is not None else "(bitmap or unreadable)"
    if path is not None:
        path.write_text(text)
    return text


def targets_of(spec: str) -> list[int]:
    """`--to 0x22,0x50,0x60` -- a chain, driven in one boot.

    A boot costs about five minutes and a warp costs about thirty seconds, so
    the expensive part of confirming a row is getting a party into the world
    at all. Each hop is measured on its own and the next leaves from wherever
    the last one landed.
    """
    return [int(v, 0) for v in spec.replace(" ", "").split(",") if v]


def measure(sess, addr, maps, row, out: pathlib.Path, tag: str) -> dict:
    """Everything a landing has to be judged on, in one place."""
    state = snapshot(sess, addr)
    state["resident"] = resident_geo(sess, maps)
    if state["resident"].get("verdict") != "ours":
        # The `$0400` reading said nothing. Ask the question without the
        # address before concluding no map is loaded.
        state["ram"] = {k: f"${v:04X}" for k, v in
                        geo_in_ram(sess, maps).items()}
    if row is not None:
        state["expected_geo"] = list(row.geos)
        state["expected_arrival"] = (str(row.arrival) if row.arrival
                                     else None)
        state["expected_disk"] = row.disk
    s = sess.screen()
    text = s.text() if s is not None else None
    print(f"{tag}:", json.dumps(state), flush=True)
    (out / f"{tag}.json").write_text(json.dumps(state, indent=1))
    sess.kbd.screenshot(str(out / f"{tag}.png"))
    if text:
        (out / f"{tag}-screen.txt").write_text(text)
    return state


#: A square no row in the table carries, written in front of a hop by
#: `--spoil-from` so that finding the table's square afterwards can only be
#: the arriving script's own doing.
#:
#: **This is what makes an arrival column confirmable at all.** Left to
#: itself, `FastTravel` writes the table's square into `$C04B` before the
#: jump -- proven by the write list, no emulator needed -- and then reading
#: that same square back afterwards would be reading our own write. The
#: table's claim is the other one: that the *arriving* script's entry 4 puts
#: the party there.
SPOIL_SQUARE = (1, 1, 2)


def expect_arrival(state: dict, row, departure: int | None) -> None:
    """Replace the table's square in a measured `state` with the departure's."""
    if row is None:
        return
    want = row.arrival_for(departure)
    state["expected_arrival"] = str(want) if want else None


def verdict_of(state: dict, row, spoiled: bool = False,
               departure: int | None = None) -> dict:
    """Does this landing match the row the table predicted? Field by field.

    Three independent columns, each reported as its own answer rather than
    rolled into one boolean: a run that gets the map right and the square
    wrong is a different finding from one that gets neither. The arrival is
    judged against the square for the `departure` actually taken.
    """
    got_geo = state.get("resident", {}).get("name")
    want = list(row.geos)
    square = state.get("square") or []
    arrival = row.arrival_for(departure)
    out = {
        "area": state.get("area") == row.id,
        "area_seen": f"0x{state.get('area', 0):02X}",
        "disk": state.get("disk") == row.disk,
        "geo": (got_geo in want) if (want and got_geo) else None,
        "geo_seen": got_geo,
    }
    if arrival is not None and len(square) == 3:
        out["arrival"] = (square[0] == arrival.x and square[1] == arrival.y
                          and (arrival.facing is None
                               or square[2] == arrival.facing))
        # Without this the arrival answer is a reading of our own write.
        out["arrival_is_the_scripts"] = spoiled
        out["arrival_seen"] = f"{square[0]},{square[1]} " \
                              f"{areas.FACINGS[square[2] & 3]}"
    return out


def run(args) -> int:
    game = c64_port.SECRET_OF_THE_SILVER_BLADES
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    addr = Addresses(game, args.disks)
    print("addresses:", addr.describe(), flush=True)
    (out / "addresses.json").write_text(json.dumps(addr.as_dict(), indent=1))

    chain = targets_of(args.to)
    rows = []
    for want in chain:
        row = areas.area_in(want, areas.SECRET_OF_THE_SILVER_BLADES)
        if row is None:
            print(f"no area ${want:02X} in the Silver Blades table",
                  flush=True)
            return 2
        rows.append(row)
        print(f"target ${want:02X}: {row.label}, side {args.disk or row.disk},"
              f" maps {row.geos or '--'}, arrival {row.arrival or '--'}",
              flush=True)

    maps = ssb_maps(args.disks)
    print(f"{len(maps)} maps read off the sides", flush=True)

    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "ssb20"))
    print(f"slot {slot.n}: monitor {slot.port} display {slot.display} "
          f"dir {slot.dir}", flush=True)
    sess = None
    report: dict = {"targets": [f"0x{t:02X}" for t in chain], "hops": []}
    try:
        save = args.save
        if save:
            # A slot is reused, so a bare `shutil.copy` here would carry a
            # read-only specimen's mode onto `SAVE_IN.D64` and then raise on
            # the next run's attempt to stage over it (#472) -- the same
            # fault `stage()` below has for `SIDE0.D64`.
            staged = pathlib.Path(slot.dir) / "SAVE_IN.D64"
            por.stage_writable(save, staged)
            save = str(staged)
        # `tools/c64/session.py` carries Pool of Radiance's `$49E6` as a module
        # constant and `walk_one` reads it to choose which keys to press. In a
        # running Silver Blades that address is somebody else's bytes. Point
        # it at this title's own for this process only; the file is another
        # ticket's -- `#29 (The live reader uses Pool of Radiance's addresses
        # on every title)` -- and is not edited.
        por.INDOORS_AT = addr.indoors
        first = stage(slot, args.disks, save)
        sess = SSBSession(first, slot=slot)
        if not sess.boot():
            print("boot incomplete; the screen says:", flush=True)
            print(screen_text(sess, out / "stuck-boot.txt"), flush=True)
            sess.kbd.screenshot(str(out / "stuck-boot.png"))
            return 3
        if not load_party(sess):
            print("could not load a party; the screen says:", flush=True)
            print(screen_text(sess, out / "stuck-load.txt"), flush=True)
            sess.kbd.screenshot(str(out / "stuck-load.png"))
            return 3
        if not enter_world(sess, addr, fix=not args.no_fix_disk,
                           stop_at_idle=not args.command_bar):
            print("never reached the world; the screen says:", flush=True)
            print(screen_text(sess, out / "stuck-world.txt"), flush=True)
            sess.kbd.screenshot(str(out / "stuck-world.png"))
            return 3
        before = measure(sess, addr, maps, None, out, "before")
        report["before"] = before

        if args.probe:
            (out / "report.json").write_text(json.dumps(report, indent=1))
            return 0

        target = SessTarget(sess)
        ft = None
        if args.back:
            from automap import actions
            ft = actions.FastTravel(game)
        landed_any = False
        for n, (want, row) in enumerate(zip(chain, rows), start=1):
            tag = f"hop{n}-{want:02x}"
            here = snapshot(sess, addr)
            if here["mode"] != 1:
                print(f"${addr.mode:04X} is {here['mode']}, not 1: DUNGEON is "
                      f"not resident and the tail is somebody else's code",
                      flush=True)
                break
            if here["area"] == want:
                print(f"the party is already in area ${want:02X}", flush=True)
                break
            if not here["indoors"] and not args.force:
                print(f"${addr.indoors:04X} is 0, so the party is not "
                      f"indoors. Pool of Radiance wedges its loader warping "
                      f"out of the travel grid; pass --force to test that "
                      f"here.", flush=True)
                break
            pc = idle_in_key_window(sess, addr)
            if pc is None:
                print("the machine is not idle in a key window; rejecting",
                      flush=True)
                break
            square = None
            spoiled = bool(args.spoil_from) and n >= args.spoil_from
            if spoiled:
                square = SPOIL_SQUARE
            elif args.square and n == 1:
                square = tuple(int(v, 0) for v in args.square.split(","))
            elif row.arrival is not None and args.place:
                a = row.arrival
                square = (a.x, a.y, a.facing or 0)
            print(f"hop {n} -> ${want:02X} from ${here['area']:02X}, "
                  f"square {square}, PC ${pc:04X}", flush=True)

            if args.via_actions:
                made = warp_via_actions(target, game, row, square, ft)
                if not made.get("ok"):
                    print("FastTravel rejected:",
                          json.dumps(made), flush=True)
                    report["hops"].append({"target": f"0x{want:02X}",
                                           "writes": made, "landed": False})
                    break
            else:
                made = warp(sess, addr, want, args.disk or row.disk, square)
            print("wrote:", json.dumps(made), flush=True)

            idle, pc = wait_idle(sess, addr, args.arrival_timeout)
            sess.settle(3)
            after = measure(sess, addr, maps, row, out, tag)
            expect_arrival(after, row, here["area"])
            after["idle"] = idle
            # **The landing test is the area byte, not the program counter.**
            # `ECL22` arrives on an encounter menu drawn in bitmap mode, whose
            # key wait is neither `DUNGEON`'s loop nor the `LIBRARY` fetcher --
            # so `wait_idle` timed out on a hop that had plainly landed: the
            # cache slot read `$22`, `$0400` held `GEO22` byte for byte and the
            # script's own text was on the screen (`cited/20/land1`).
            # **And "landed" is not "arrived in the area we asked for".**
            # `ECL30` runs its own entry 4 -- it loads `GEO31` and places the
            # party at 3,3 E -- and then issues `NEWECL 51` on the spot, so a
            # trip to `$30` ends in `$33` with `$7F1B` reading `$33`
            # (`issue20/land3`, scratch, deleted). The trip took effect; it simply did not
            # stop where it was aimed. The two are reported apart.
            landed = after.get("area") != here["area"]
            after["reached_target"] = after.get("area") == want
            if landed and not after["reached_target"]:
                print(f"the trip took effect and went on: ${want:02X} handed "
                      f"the party to ${after['area']:02X}", flush=True)
            if not idle:
                after["where"] = pc_histogram(sess, addr)
                print("not idle:", json.dumps(after["where"]), flush=True)
            hop = {"target": f"0x{want:02X}", "writes": made,
                   "landed": landed, "idle": idle, "spoiled": spoiled,
                   "state": after, "verdict": verdict_of(after, row, spoiled,
                                           here["area"])}
            print(f"verdict {tag}:", json.dumps(hop["verdict"]), flush=True)
            report["hops"].append(hop)
            (out / "report.json").write_text(json.dumps(report, indent=1))
            if not landed:
                break
            landed_any = True
            if args.back:
                report["back"] = return_via_actions(
                    sess, addr, maps,
                    ft, target, areas.area_in(here["area"],
                                              areas.SECRET_OF_THE_SILVER_BLADES),
                    out, f"back{n}-{here['area']:02x}", here["area"],
                    args.arrival_timeout, departure=want)
                (out / "report.json").write_text(json.dumps(report, indent=1))
                break
            if args.walk and n == len(chain) and idle:
                hop["walk"] = walk_proof(sess)
                hop["resident_after_walk"] = resident_geo(sess, maps)
                print("walk:", json.dumps(hop["walk"]), flush=True)
            if n != len(chain) and not idle:
                # Try to hand the arriving script back its key and get to a
                # state another hop can leave from. If it will not come back,
                # stop: a warp made from an unread loop is the one thing the
                # PC guard exists to prevent.
                sess.log("  nudging the arriving script")
                back = None
                for key in (0x0D, 0x0D, 0x1B, 0x0D, 0x0D, 0x1B):
                    sess.press_kernal(key)
                    time.sleep(2.0)
                    sess.handle_prompt()
                    back = idle_in_key_window(sess, addr)
                    if back is not None:
                        break
                if back is None:
                    print(f"after {tag} the machine will not come back to a "
                          f"key window, so the chain stops here", flush=True)
                    break
                sess.log(f"  back at ${back:04X}")
        (out / "report.json").write_text(json.dumps(report, indent=1))
        return 0 if landed_any else 5
    finally:
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pool", type=int, default=None,
                    help="which pool slot to claim (default: any free one)")
    ap.add_argument("--disks", default=os.environ.get("POR_DISKS"),
                    help="where the six Silver Blades sides are")
    ap.add_argument("--save", default="",
                    help="a save disk to stage as SIDE0 (default: a copy of "
                         "side 6, which carries the shipped SAVEDBASH party)")
    ap.add_argument("--to", default="0x22",
                    help="the target area id, the ECL number; a comma-"
                         "separated list is a chain driven in one boot")
    ap.add_argument("--disk", type=int, default=0,
                    help="which side carries that ECL (default: the table's)")
    ap.add_argument("--place", action="store_true",
                    help="write the table's arrival square before the warp; "
                         "omitted, the arriving script places the party")
    ap.add_argument("--square", default="",
                    help="write this x,y,facing instead")
    ap.add_argument("--probe", action="store_true",
                    help="boot and report, warp nothing")
    ap.add_argument("--no-fix-disk", action="store_true",
                    help="leave a prompt for a side that does not exist alone,"
                         " rather than writing a legal one and pressing a key")
    ap.add_argument("--force", action="store_true",
                    help="warp even when the indoors flag is clear")
    ap.add_argument("--via-actions", action="store_true",
                    help="make the trip with automap.actions.FastTravel, "
                         "which is the code a player clicking Fast Travel "
                         "runs, rather than this file's own writes")
    ap.add_argument("--back", action="store_true",
                    help="with --via-actions, after the first hop call "
                         "FastTravel.apply_back on the same object and "
                         "record the landing; no second hop is made")
    ap.add_argument("--command-bar", action="store_true",
                    help="wait for ENCAMP before warping, rather than for "
                         "the first moment the machine is idle in a key "
                         "window; eight sessions never reached one")
    ap.add_argument("--spoil-from", type=int, default=0, metavar="N",
                    help="from hop N on, write %s into the live square "
                         "instead of the table's, so that the table's square "
                         "read back afterwards is the arriving script's own "
                         "doing and not ours" % (SPOIL_SQUARE,))
    ap.add_argument("--arrival-timeout", type=float,
                    default=ARRIVAL_TIMEOUT, metavar="S",
                    help="how long to give the program counter to come back "
                         "to a key window after a hop (default: %(default)s)")
    ap.add_argument("--walk", action="store_true",
                    help="after the last hop, walk the party to show the "
                         "arrival is a place and not a picture")
    ap.add_argument("--out", default=str(scratch.scratch_dir("ssbwarp", "run")),
                    help="where captures go (default: %(default)s)")
    args = ap.parse_args(argv[1:])
    if args.back and args.walk:
        ap.error("--back ends the run after the Return, so --walk would "
                 "never run")
    if args.back and not args.via_actions:
        ap.error("--back needs --via-actions: only FastTravel remembers "
                 "where the trip started")
    if not args.disks or not os.path.isdir(args.disks):
        # `automap/gamedisks.py` is the registry; `automap.paths.find_disks`
        # looks for a directory named after the game and nobody names one
        # that -- `#251 (Curse's and Silver Blades' disks are where nothing
        # looks for them, so every per-title test skips)`.
        from automap import gamedisks
        found = gamedisks.find("secret-of-the-silver-blades")
        args.disks = str(found) if found else ""
    if not args.disks or not os.path.isdir(args.disks):
        print("No Silver Blades disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

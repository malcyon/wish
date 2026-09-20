#!/usr/bin/env python3
"""Watch Pool of Radiance age and expire an active effect, in the running game.

    tools/c64/effectdrive.py --save PORSAVE13.D64 --steps 2 --rest 30

Four effect slots are written into a **copy** of a save disk, one per value of
the duration byte's top two bits and all with the same count, plus a fifth slot
carrying a duration byte of zero and a sixth carrying an id whose expiry
handler puts a strength back.  The party walks `--steps` steps, reading the
four duration bytes and the six clock digits together after each one so a
byte's fall can be set against the minute that caused it, and then ENCAMP and
REST pass `--rest` minutes and `--rest-hours` hours, which is where the
engine's own expiry runs.

The instruments are **non-stopping exec checkpoints** on the addresses the
overlays were read to use, counted rather than stopped at, so the game keeps
running while the counts build:

* `DUNGEON $0E0D` the per-minute ageing sweep, `$0E46` its store and `$0E39`
  the branch that floors a run-out count at 1 instead of expiring it;
* `CAMP $131F` the expiry that clears the id, and `$12F8` the dispatch that
  looks the id up in `ECL65 $9AD5`;
* `SPELLE04 $AD0B`, the handler that rebuilds strength from the magnitude.

`$AD0B` executing is the whole of the second measurement: it is reached only
through the dispatch, and nothing else in the machine writes record `0x014`
from the effect record.

Everything lands under `--out`: `effects.jsonl` one line per reading, and
`screen.txt` at the end.  The player's disks are read and never written.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import struct
import subprocess
import sys
import threading
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import tool_disks  # noqa: E402
from goldbox import effects  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools.c64 import savecheck as SC  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.registry import scratch  # noqa: E402

DISKS: pathlib.Path | None = tool_disks()

#: `SAVEDGAME0` loads at `$4900`; the twelve character slots start at `$4D00`.
SAVE0_LOAD = 0x4900
SLOT_BASE = 0x4D00
SLOT_STRIDE = 0x100
CLOCK = 0x49C6

#: The page an overlay copies the working character into, and the two record
#: bytes the strength handler writes: `0x014` STR and `0x01A` STR %.
STAGING_PAGE = 0x6B00
REC_STR = 0x014
REC_STR_PCT = 0x01A
REC_CHA = 0x019

#: What the run watches, address by address.  A DUNGEON address and a CAMP
#: address are both in the `$0800` overlay window and mean different code, so
#: the two sets are never armed at the same time.
WALK_POINTS = {"age": 0x0E0D, "store": 0x0E46, "floor": 0x0E39,
               "tick": 0x0DEC}
CAMP_POINTS = {"expire": 0x131F, "dispatch": 0x12F8, "restore": 0xAD0B,
               "sweep": 0x1299}

#: `CAMP`'s rest-time field: minutes, hours, days, counted down five minutes
#: at a time -- `tools/c64/c64restinterrupt.py`.
REST_TIME = 0x2898

#: `ECL65` at `$9900`: the id list the expiry dispatch searches, and the two
#: halves of its handler address table.
ECL65_IDS = 0x9AD5
ECL65_LO = 0x9AEE
ECL65_HI = 0x9B06
ECL65_N = 24

#: The combat expiry's own dispatch, read by `SQRPACI01 $0791`, indexed by the
#: effect id itself rather than searched.  Under the ROM, so bank `ram`.
COMBAT_LO = 0xDA63
COMBAT_HI = 0xDAEE
COMBAT_N = 0x8B


def _xdo(display: str, *args: str) -> str:
    return subprocess.run(["xdotool", *args],
                          env={"DISPLAY": display, "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True, check=False).stdout


def dismiss_dialogs(display: str, stop: threading.Event) -> None:
    """Answer VICE's own error dialogs so the keyboard reaches the C64.

    A VICE that cannot find a drive ROM or `/dev/input` puts up a modal GTK
    dialog, and a modal GTK dialog **grabs the keyboard**: every XTEST key
    after that goes to the dialog whatever the X input focus says, so the
    fastloader prompt is never answered and the run dies waiting for a menu.
    There is no window manager on the nested display to close it. Pressing
    Return reaches the dialog for the same reason nothing else does.
    """
    while not stop.wait(1.5):
        names = _xdo(display, "search", "--onlyvisible", "--name", ".").split()
        for w in names:
            if "Error" in _xdo(display, "getwindowname", w):
                _xdo(display, "key", "Return")
                time.sleep(0.5)
                break


def record_offset(slot: int) -> int:
    return SLOT_BASE - SAVE0_LOAD + slot * SLOT_STRIDE


def parse_stage(text: str) -> list[tuple[int, int, int, int, int]]:
    """`0=12:2:3:F4` -- effect slot, id, owner, duration, magnitude."""
    out = []
    for item in text.split(","):
        where, _, rest = item.partition("=")
        parts = rest.split(":")
        if len(parts) != 4:
            raise SystemExit("--stage wants slot=id:owner:duration:magnitude")
        out.append((int(where, 0), *(int(p, 16) for p in parts)))
    return out


#: One effect per value of bits 6-7, all with count 32, so a single rest
#: measures all four units against one clock; slot 4 asks whether a duration
#: byte of zero is ever touched, and slot 5 is the strength restore -- id 12
#: on party slot 2, one minute left, magnitude `$80 | 116`.
DEFAULT_STAGE = "0=01:00:20:00,1=01:00:60:00,2=01:00:A0:00," \
                "3=01:00:E0:00,4=01:00:00:00,5=0C:02:01:F4"


def stage_effects(path: pathlib.Path, wanted) -> list[dict]:
    """Write effect slots into a **copy** of a save disk.

    The four arrays are bytes the engine reads and never checks the
    provenance of, which is what makes writing them a measurement: the
    ageing sweep cannot tell a staged duration from one a spell wrote.
    """
    image = D64.open(str(path))
    addr, body = split_load_address(image.read_file("SAVEDGAME0"))
    body = bytearray(body)
    written = []
    for slot, eid, owner, duration, magnitude in wanted:
        was = [body[off + slot] for off in
               (effects.EFFECT_ID_OFFSET, effects.EFFECT_OWNER_OFFSET,
                effects.EFFECT_DURATION_OFFSET,
                effects.EFFECT_MAGNITUDE_OFFSET)]
        body[effects.EFFECT_ID_OFFSET + slot] = eid
        body[effects.EFFECT_OWNER_OFFSET + slot] = owner
        body[effects.EFFECT_DURATION_OFFSET + slot] = duration
        body[effects.EFFECT_MAGNITUDE_OFFSET + slot] = magnitude
        written.append({"slot": slot, "was": was,
                        "now": [eid, owner, duration, magnitude]})
    image.write_file_inplace("SAVEDGAME0",
                             addr.to_bytes(2, "little") + bytes(body))
    image.save(str(path))
    return written


def abilities(path: pathlib.Path) -> dict[int, list[int]]:
    """STR, STR % and CHA of every occupied save slot, off a `.d64`."""
    image = D64.open(str(path))
    _, body = split_load_address(image.read_file("SAVEDGAME0"))
    out = {}
    for slot in range(8):
        at = record_offset(slot)
        record = body[at:at + SLOT_STRIDE]
        if any(record):
            out[slot] = [record[REC_STR], record[REC_STR_PCT],
                         record[REC_CHA]]
    return out


def checkpoint_hits(mon, number: int) -> int:
    """How many times a checkpoint has been hit, machine still running.

    VICE's `CHECKPOINT_RESPONSE` puts the hit count at byte 13.
    """
    body = mon.command(0x11, struct.pack("<I", number))
    return struct.unpack("<I", body[13:17])[0]


class Log(SC.Log):
    def __init__(self, out: pathlib.Path, quiet: bool = False):
        self.quiet = quiet
        super().__init__(out / "effects.jsonl")

    def say(self, *a) -> None:
        if not self.quiet:
            super().say(*a)


def sample(m) -> dict:
    """The four arrays and the clock, read in one pass."""
    head = m.read(SAVE0_LOAD, 0x300)
    mag = m.read(SAVE0_LOAD + effects.EFFECT_MAGNITUDE_OFFSET, 0x40)
    rec = m.read(STAGING_PAGE, 0x40)
    return {
        "id": list(head[0x00:0x10]),
        "owner": list(head[0x40:0x50]),
        "duration": list(head[0x80:0x90]),
        "magnitude": list(mag[0x00:0x10]),
        "clock": list(head[CLOCK - SAVE0_LOAD:CLOCK - SAVE0_LOAD + 6]),
        "staging_str": [rec[REC_STR], rec[REC_STR_PCT], rec[REC_CHA]],
    }


def live_records(m) -> dict[int, list[int]]:
    block = m.read(SLOT_BASE, SLOT_STRIDE * 8)
    out = {}
    for slot in range(8):
        rec = block[slot * SLOT_STRIDE:(slot + 1) * SLOT_STRIDE]
        if any(rec):
            out[slot] = [rec[REC_STR], rec[REC_STR_PCT], rec[REC_CHA]]
    return out


def rest(sess, log, minutes: int, hours: int, cp: dict) -> dict:
    """`REST` for *minutes* minutes and *hours* hours, sampled either side.

    The rest length is written into `CAMP`'s own rest-time field rather than
    driven with `INCREASE`, the way `tools/c64/c64restinterrupt.py` does it:
    the default is whatever the party has left to memorise, and `INCREASE`'s
    step grows while the key is held.  The engine then counts the field down
    five minutes at a time, and each five-minute pass is one call of the
    expiry sweep.
    """
    if not sess.select_bar("REST"):
        log.say("  REST was not on the camp bar")
        return {"failed": "no REST on the camp bar"}
    if sess.wait_text("INCREASE", timeout=30)[0] is None:
        log.say("  the rest-time bar never appeared")
        return {"failed": "no rest-time bar"}
    with sess.mon(10) as m:
        before = sample(m)
        m.write(REST_TIME, bytes((minutes, hours, 0)))
        staged = tuple(m.read(REST_TIME, 3))
        m.resume()
    if staged != (minutes, hours, 0):
        return {"failed": f"rest time read back {staged}"}
    if not sess.select_bar("REST"):
        return {"failed": "no REST on the rest-time bar"}
    # The rest is over when the clock stops moving.  No key is sent while it
    # runs: `CAMP $1E44` reads the keyboard every pass and SPACE ends it.
    deadline, still, last = time.time() + 300, 0, None
    while time.time() < deadline and still < 10:
        time.sleep(1.0)
        with sess.mon(10) as m:
            now = bytes(m.read(CLOCK, 6))
            m.resume()
        still = still + 1 if now == last else 0
        last = now
    with sess.mon(10) as m:
        after = sample(m)
        counts = {k: checkpoint_hits(m, v) for k, v in cp.items()}
        records = live_records(m)
        m.resume()
    log.say(f"  rest {minutes}m {hours}h: clock {before['clock']} -> "
            f"{after['clock']}")
    log.say(f"    durations {before['duration'][:6]} -> "
            f"{after['duration'][:6]}")
    log.say(f"    ids {after['id'][:6]}  counts {counts}")
    return {"before": before, "after": after, "records": records, **counts}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default="PORSAVE13.D64")
    p.add_argument("--stage", default=DEFAULT_STAGE,
                   help="SLOT=ID:OWNER:DURATION:MAGNITUDE, hex, comma separated")
    p.add_argument("--disks", default=DISKS)
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--steps", type=int, default=0)
    p.add_argument("--rest", type=int, default=30,
                   help="minutes to REST for once in camp")
    p.add_argument("--rest-hours", type=int, default=0,
                   help="hours to REST for, alongside --rest")
    p.add_argument("--walk", default="I")
    p.add_argument("--no-camp", action="store_true",
                   help="stop after the walk rather than entering ENCAMP")
    p.add_argument("--out", default=None)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    if args.disks is None:
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    SC.catch_signals()

    disks = pathlib.Path(args.disks)
    out = pathlib.Path(args.out) if args.out else scratch.scratch_dir(
        "effectdrive", "run")
    scratch.ensure(out)
    log = Log(out, args.quiet)

    staging_dir = out / "disks"
    staging_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 9):
        src, link = disks / f"POOL{i}.D64", staging_dir / f"POOL{i}.D64"
        if src.exists() and not link.exists():
            link.symlink_to(src.resolve())
    save = "STAGED.D64"
    S.stage_writable(disks / args.save if not os.path.isabs(args.save)
                     else args.save, staging_dir / save)
    written = stage_effects(staging_dir / save, parse_stage(args.stage))
    log.emit("staged", values=written,
             abilities=abilities(staging_dir / save))
    for w in written:
        log.say(f"effect slot {w['slot']}: {w['was']} -> {w['now']}")

    slot = S.claim_slot(args.slot, "effectdrive")
    log.say(f"pool slot {slot.n} display {slot.display}  out {out}")
    sess, rc = None, 0
    stop = threading.Event()
    watchdog = threading.Thread(target=dismiss_dialogs,
                                args=(str(slot.display), stop), daemon=True)
    watchdog.start()
    try:
        sess = S.Session(S.stage_disks(slot, staging_dir, save), slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        log.say(f"in the world at {sess.position()}")

        with sess.mon(10) as m:
            first = sample(m)
            log.emit("before", **first, records=live_records(m))
            ids = list(m.read(ECL65_IDS, ECL65_N + 1))
            lo = list(m.read(ECL65_LO, ECL65_N))
            hi = list(m.read(ECL65_HI, ECL65_N))
            log.emit("ecl65", ids=ids, lo=lo, hi=hi,
                     handlers=[f"{h:02X}{lw:02X}" for h, lw in zip(hi, lo)])
            m.resume()
        log.say(f"clock {first['clock']}  durations {first['duration'][:8]}")
        log.say("ECL65 ids " + " ".join(f"{i:02X}" for i in ids))
        log.say("handlers  " + " ".join(f"{h:02X}{lw:02X}"
                                        for h, lw in zip(hi, lo)))

        with sess.mon(10) as m:
            cp = {k: m.checkpoint_set(a, exec_=True, stop=False)
                  for k, a in WALK_POINTS.items()}
            m.resume()
        log.emit("armed_walk", checkpoints=cp, points=WALK_POINTS)

        for step in range(1, args.steps + 1):
            sess.walk_one(args.walk)
            sess.handle_prompt()
            if sess.in_combat():
                log.emit("combat", step=step)
                log.say(f"  step {step}: a fight started; stopping the walk")
                break
            with sess.mon(10) as m:
                now = sample(m)
                counts = {k: checkpoint_hits(m, v) for k, v in cp.items()}
                m.resume()
            log.emit("step", step=step, **now, **counts)
            log.say(f"  step {step:2d} clock {now['clock']} "
                    f"dur {now['duration'][:6]} "
                    + " ".join(f"{k}={v}" for k, v in counts.items()))

        with sess.mon(10) as m:
            for v in cp.values():
                m.checkpoint_delete(v)
            after_walk = sample(m)
            log.emit("after_walk", **after_walk, records=live_records(m))
            m.resume()

        if not args.no_camp:
            with sess.mon(10) as m:
                ccp = {k: m.checkpoint_set(a, exec_=True, stop=False)
                       for k, a in CAMP_POINTS.items()}
                m.resume()
            log.emit("armed_camp", checkpoints=ccp, points=CAMP_POINTS)
            entered = sess.select_bar("ENCAMP")
            if entered:
                entered = sess.wait_text("MAGIC", timeout=60)[0] is not None
            sess.settle(3)
            with sess.mon(10) as m:
                camped = sample(m)
                counts = {k: checkpoint_hits(m, v) for k, v in ccp.items()}
                ids = list(m.read(ECL65_IDS, ECL65_N + 1))
                lo = list(m.read(ECL65_LO, ECL65_N))
                hi = list(m.read(ECL65_HI, ECL65_N))
                log.emit("ecl65", when="camp", ids=ids, lo=lo, hi=hi,
                         handlers=[f"{h:02X}{lw:02X}"
                                   for h, lw in zip(hi, lo)])
                banks = {}
                try:
                    from automap.vice import bank_ids
                    banks = bank_ids(m)
                except Exception as exc:          # noqa: BLE001
                    log.emit("banks_failed", error=repr(exc))
                ram = banks.get("ram", 0)
                clo = list(m.read(COMBAT_LO, COMBAT_N, bank=ram))
                chi = list(m.read(COMBAT_HI, COMBAT_N, bank=ram))
                log.emit("combat_table", bank=ram, lo=clo, hi=chi)
                log.emit("camped", entered=bool(entered), **camped,
                         records=live_records(m), **counts)
                m.resume()
            log.say(f"ENCAMP ({entered}): {counts}")
            log.say(f"  clock {camped['clock']} durations "
                    f"{camped['duration'][:6]} ids {camped['id'][:6]} "
                    f"staging {camped['staging_str']}")
            log.say("ECL65 ids " + " ".join(f"{i:02X}" for i in ids))
            log.say("handlers  " + " ".join(f"{h:02X}{lw:02X}"
                                            for h, lw in zip(hi, lo)))

            if entered and (args.rest or args.rest_hours):
                rested = rest(sess, log, args.rest, args.rest_hours,
                              ccp)
                log.emit("rested", asked=[args.rest, args.rest_hours],
                         **rested)
            sess.select_bar("EXIT")
            sess.settle(3)
            with sess.mon(10) as m:
                log.emit("after_camp", **sample(m), records=live_records(m))
                m.resume()

        s = sess.screen()
        if s is not None:
            (out / "screen.txt").write_text(
                "\n".join(s.row(r) for r in range(25)) + "\n")
    except Exception as exc:                        # noqa: BLE001
        log.emit("failed", error=repr(exc))
        log.say(f"failed: {exc!r}")
        rc = 1
    finally:
        stop.set()
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
        log.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

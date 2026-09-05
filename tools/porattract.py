#!/usr/bin/env python3
"""Run Pool of Radiance's attract loop in a pooled VICE and watch for a stall.

The control for `#286 (Pool of Radiance on the C64 Ultimate sometimes hangs on
a disk load)`.  On Donald's C64 Ultimate the game's opening demo -- which loads
from disk continuously and forever, with nobody touching a key -- reached a
state twice in two runs where it stopped: once with the processor sitting in an
interrupts-off wait, once dropped out to a BASIC warm start.  **Whether the
same disk does that under an emulator is what says whether the fault is in the
hardware at all.**

So this is deliberately the same experiment on the other machine: boot
`POOL1.D64`, answer `DISABLE FASTLOADER (Y/N) ?`, then **send nothing else** --
leaving the `PLAY GAME` menu alone is what starts the demo -- and sample the
jiffy clock and the screen until either the window expires or nothing has moved
for long enough to call it a stall.

    tools/porattract.py --minutes 30 --log work/issue286/vice-attract.jsonl

One JSON line per sample, written as it is taken, because a run that ends in a
stall ends by being killed and nothing would be written at the end.  The slot
comes from `tools/instance.py`, the disk is copied into it, and teardown kills
only the process group this slot started.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import gamedisks, instance  # noqa: E402
from tools.session import Session  # noqa: E402

#: The jiffy clock, and the screen.  `$00A0`-`$00A2` stops for the length of
#: every KERNAL serial load, so a stall is only a stall when the screen has
#: stopped as well.
JIFFY = 0x00A0

#: The program counter's id in VICE's `registers()` map, read once and matched
#: rather than assumed -- `available_registers` names them and the ids differ
#: between builds.  Three is PC on every build this project has met.
PC_REGISTER = 3

#: The stack pointer's id, same caveat.
SP_REGISTER = 4


def find_pool1() -> pathlib.Path:
    for base in gamedisks.candidates("pool-of-radiance"):
        for name in ("POOL1.D64", "pool1.d64"):
            path = pathlib.Path(base) / name
            if path.exists():
                return path
    raise SystemExit("POOL1.D64 not found; set $POR_DISKS")


def sample(mon) -> tuple[str, int, int]:
    """The screen, the jiffy clock, and **the program counter**.

    The jiffy clock alone is not enough here: VICE spends whole minutes inside
    a `SEI` load with the screen blank and the clock stopped, which is exactly
    what a hang looks like from outside.  The binary monitor can read the
    processor, which the Ultimate cannot, so a stall here means the *program
    counter* stopped -- a far stronger statement than anything the hardware
    side of this experiment can make.
    """
    from automap import screen as _screen
    at = _screen.screen_address(mon.read)
    raw = mon.read(at, 1000)
    clock = mon.read(JIFFY, 3)
    pc = mon.registers().get(PC_REGISTER, -1)
    return (hashlib.sha256(raw).hexdigest()[:12],
            (clock[0] << 16) | (clock[1] << 8) | clock[2], pc)


def capture(mon, session, out: pathlib.Path, still: float) -> None:
    """Everything the emulator can say and the hardware cannot.

    The processor first: where it is, how deep the stack is, and the bytes
    around the program counter, so the loop can be named rather than guessed
    at.  Then the screen as text, and the two ports that carry the serial bus.
    """
    from automap import screen as _screen
    regs = mon.registers()
    pc = regs.get(PC_REGISTER, -1)
    at = _screen.screen_address(mon.read)
    record = {
        "stopped_for": round(still, 1),
        "registers": {str(k): v for k, v in regs.items()},
        "pc": pc,
        "sp": regs.get(SP_REGISTER, -1),
        "around_pc": mon.read(max(0, pc - 0x20), 0x60).hex(" ") if pc >= 0 else "",
        "stack": mon.read(0x0100, 0x100).hex(" "),
        "dd00": mon.read(0xDD00, 16).hex(" "),
        "dc00": mon.read(0xDC00, 16).hex(" "),
        "d018": mon.read(0xD018, 1)[0],
        "irq_vector": mon.read(0x0314, 2).hex(" "),
        "kernal_serial": mon.read(0xED00, 0x200).hex(" "),
        "screen_address": at,
        "screen": _screen.codes_to_text(mon.read(at, 1000))
        if hasattr(_screen, "codes_to_text") else "",
        "loaded_files_cache": mon.read(0x6E13, 25).hex(" "),
    }
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(f"stall capture -> {out}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=30.0)
    parser.add_argument("--still", type=float, default=45.0,
                        help="seconds with nothing moving that count as a stall")
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--log", required=True)
    parser.add_argument("--fastloader", default="y")
    args = parser.parse_args(argv)

    os.environ.setdefault("POR_HEADLESS", "1")
    log = pathlib.Path(args.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    source = find_pool1()

    with instance.claim("por", note="#286 attract-loop control") as slot:
        disk = instance.copy_disks(slot, [source])[0]
        session = Session(disk=str(disk), slot=slot, fastloader=args.fastloader)
        try:
            session.launch()
            hit, _ = session.wait_text("DISABLE FASTLOADER", 180)
            if hit is None:
                print("no fastloader prompt")
                return 2
            session.kbd.key(args.fastloader, 0.15, 0.28)
            print(f"answered {args.fastloader.upper()}; sending nothing else",
                  flush=True)
            deadline = time.time() + args.minutes * 60
            last, since = None, time.time()
            # **A monitor connection stops the emulator for as long as it is
            # open** (`automap/vice.py`), so one held across the whole loop
            # freezes the machine and then reports it as stalled -- which is
            # exactly the false positive this took on its first run.  One
            # connect/read/close per sample, and the waiting happens outside.
            with log.open("a") as sink:
                while time.time() < deadline:
                    try:
                        with session.mon(10) as mon:
                            state = sample(mon)
                    except Exception as exc:            # noqa: BLE001
                        sink.write(json.dumps(
                            {"t": time.strftime("%H:%M:%S"),
                             "error": repr(exc)}) + "\n")
                        sink.flush()
                        time.sleep(1.0)
                        continue
                    now = time.time()
                    if state != last:
                        last, since = state, now
                    still = now - since
                    sink.write(json.dumps(
                        {"t": time.strftime("%H:%M:%S"), "screen": state[0],
                         "jiffy": state[1], "pc": state[2],
                         "still": round(still, 1)}) + "\n")
                    sink.flush()
                    if still >= args.still:
                        print(f"STALLED for {still:.0f}s at "
                              f"{time.strftime('%T')}", flush=True)
                        with session.mon(10) as mon:
                            capture(mon, session,
                                    log.with_suffix(".stall.json"), still)
                        return 6
                    time.sleep(args.interval)
            print(f"ran {args.minutes:.0f} minutes with no stall", flush=True)
            return 0
        finally:
            session.terminate()


if __name__ == "__main__":
    raise SystemExit(main())

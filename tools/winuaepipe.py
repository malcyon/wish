#!/usr/bin/env python3
"""Talk to a running WinUAE through its own named pipe.

WinUAE creates `\\\\.\\pipe\\WinUAE` at startup, unconditionally, and a message
beginning `DBG ` is handed to the debugger's own command parser with its output
captured into a buffer instead of a console (`uaeipc.cpp`'s `parsemessage`,
`debug.cpp`'s `debug_parser`).  So the two commands `automap/amiga.py` is built
on -- `S <file> <addr> <n>` and `m <addr> <lines>` -- can be issued with no F11,
no console window, no focus change, and without stopping the emulated machine.

This is the command line for that route; `automap.amiga.WinuaePipe` is the
transport the automapper uses.  It reaches the pipe the way this project's test
rig does -- a `winvm ssh` to the Windows VM -- while `WinuaePipe` itself also
speaks to a local pipe, which is what Wish and WinUAE on one Windows machine
would be.  Four commands:

    tools/winuaepipe.py probe
    tools/winuaepipe.py send 'm 0 1' 'm c00000 2'
    tools/winuaepipe.py ticker --reads 5 --gap 1
    tools/winuaepipe.py time --reads 5

`probe` is the one to run first on a machine nobody has tried this on: it opens
the pipe, sends one harmless `m 0 1`, and prints the reply, the Win32 error
number if there was one, and how long each stage took.

**Only reading commands go down this pipe.**  `m`, `S`, `W` and `T` stay inside
`debug_parser`; `g`, `t`, `f`, `w` and the breakpoint commands can reach
`activate_debugger()`, which calls `open_console()` -- a console window in front
of whoever is playing, which is the whole thing this route exists to avoid.
`IPC_QUIT` quits the emulator and is refused here.

The message is sent as 8-bit text with no byte-order mark.  A UTF-16 request
(`0xFF 0xFE`) takes a reply path that `_tcscpy`s into a 16384-**byte** buffer
while bounding the length at 16384 **characters**, so a long reply overruns it;
the 8-bit path goes through `ua_copy` with a size and is bounded.

Nothing here claims or releases the WinUAE lane, exactly as
`tools/amigatarget.py` does not: a claim that ends with the process that took it
cannot be handed between the several runs one experiment needs.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from automap.amiga import GuestError, WinuaePipe  # noqa: E402

#: Exec's own counters, which are the cheapest proof that the emulated machine
#: is still running: `ExecBase` is the longword at 4, and `ThisTask`,
#: `IdleCount` and `DispCount` are the three longwords at `ExecBase + 0x114`
#: (`exec/execbase.i`). `IdleCount` counts passes of the scheduler's idle loop
#: and `DispCount` counts task dispatches, so both move while the machine runs
#: and neither moves while it is stopped.
EXECBASE_PTR = 4
EXEC_THISTASK = 0x114


def exec_counters(pipe: WinuaePipe) -> dict[str, int]:
    """`ThisTask`, `IdleCount` and `DispCount` out of a running Amiga."""
    execbase = int.from_bytes(pipe.memory(EXECBASE_PTR, 4), "big")
    if not execbase:
        raise GuestError("ExecBase is zero: this machine has no Kickstart up")
    raw = pipe.memory(execbase + EXEC_THISTASK, 12)
    return {"execbase": execbase,
            "this_task": int.from_bytes(raw[0:4], "big"),
            "idle": int.from_bytes(raw[4:8], "big"),
            "disp": int.from_bytes(raw[8:12], "big")}


def _print_replies(replies, show_raw: bool) -> None:
    for cmd, reply in replies:
        print(f"--- {cmd}")
        print(reply if show_raw else reply.rstrip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pipe", default="WinUAE",
                    help="pipe name on the guest (default: WinUAE)")
    ap.add_argument("--json", action="store_true",
                    help="print one JSON object instead of text")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="open the pipe and read the first 16 bytes")

    p_send = sub.add_parser("send", help="send debugger commands, in order")
    p_send.add_argument("command", nargs="+")
    p_send.add_argument("--timings", action="store_true",
                        help="also print what each command cost the guest")

    p_tick = sub.add_parser(
        "ticker", help="read Exec's IdleCount and DispCount repeatedly")
    p_tick.add_argument("--reads", type=int, default=4)
    p_tick.add_argument("--gap", type=float, default=1.0,
                        help="seconds between reads")

    p_time = sub.add_parser("time", help="time a poll, on the guest and here")
    p_time.add_argument("--reads", type=int, default=5,
                        help="how many separate round trips to time")
    p_time.add_argument("--repeat", type=int, default=20,
                        help="commands sent over one open handle, which is "
                             "the local cost with no connection in it")
    p_time.add_argument("--command", default="m 0 1",
                        help="the debugger command to time")

    args = ap.parse_args(argv)
    pipe = WinuaePipe(pipe=args.pipe)

    if args.cmd == "probe":
        started = time.monotonic()
        try:
            replies, timings = pipe.send(["m 0 1"], with_timings=True)
        except GuestError as exc:
            print(f"fail {exc}")
            return 1
        took = time.monotonic() - started
        if args.json:
            print(json.dumps({"replies": [r for _c, r in replies],
                              "guest_ms": timings, "round_trip_s": took}))
        else:
            _print_replies(replies, False)
            print(f"guest ms: {timings}")
            print(f"round trip: {took:.2f}s")
        return 0

    if args.cmd == "send":
        try:
            replies, timings = pipe.send(list(args.command),
                                         with_timings=True)
        except GuestError as exc:
            print(f"fail {exc}")
            return 1
        if args.json:
            print(json.dumps({"replies": [{"command": c, "reply": r}
                                          for c, r in replies],
                              "guest_ms": timings}))
        else:
            _print_replies(replies, False)
            if args.timings:
                print(f"guest ms: {timings}")
        return 0

    if args.cmd == "ticker":
        rows = []
        for i in range(args.reads):
            at = time.monotonic()
            counts = exec_counters(pipe)
            rows.append({"read": i, "t": round(at, 3), **counts})
            if args.json:
                print(json.dumps(rows[-1]), flush=True)
            else:
                print(f"{i} idle={counts['idle']:#010x} "
                      f"disp={counts['disp']:#010x} "
                      f"this_task={counts['this_task']:#010x}", flush=True)
            if i + 1 < args.reads:
                time.sleep(args.gap)
        moved = len({r["idle"] for r in rows}) > 1 or \
            len({r["disp"] for r in rows}) > 1
        print(f"machine advancing: {moved}")
        return 0 if moved else 1

    if args.cmd == "time":
        trips, guest = [], []
        for _ in range(args.reads):
            at = time.monotonic()
            _replies, timings = pipe.send([args.command],
                                          repeat=args.repeat,
                                          with_timings=True)
            trips.append(round((time.monotonic() - at) * 1000))
            guest += timings
        ordered = sorted(guest)
        median = ordered[len(ordered) // 2]
        if args.json:
            print(json.dumps({"command": args.command,
                              "round_trip_ms": trips,
                              "guest_ms": guest,
                              "guest_median_ms": median}))
        else:
            print(f"command: {args.command}")
            print(f"round trips, ssh included (ms): {trips}")
            print(f"on the guest, per command (ms): "
                  f"min {ordered[0]}, median {median}, max {ordered[-1]}, "
                  f"n={len(ordered)}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

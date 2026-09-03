#!/usr/bin/env python3
"""Drive the automapper's give-up-and-reconnect chain against a real VICE.

    tools/monitorchain.py [--slot N] [--out FILE]

No game and no disks: the claim under test is about wish's monitor client,
not about Pool of Radiance. It launches an emulator on a pool slot, poisons a
`ViceTarget` the way a stalled machine does -- ask for bytes and give up
before they arrive -- and then asks the five questions that decide whether the
automapper can ever get back in.

  1. What does a second client see while the first is healthy?
  2. Does `ViceTarget.fix` raise `NotConnected` off a read that times out?
  3. Does `close()` actually close the socket, or leave `_open` guarding it?
  4. What does the next attach see, and how long does it take?
  5. Does a read that times out leave the stream out of step for the next one?

**Why this is not a test.** Every one of the five is about a socket against a
live emulator with real timing, so the suite cannot ask any of them; and
`#151 (The automapper loses VICE and cannot get back in)` was exactly a fault
that no offline check could see -- `close()` was guarded on the `_open` flag
that every give-up path cleared first, so wish held its own abandoned socket
and VICE, which serves one binary-monitor connection at a time, went on
serving it. The measurements this makes are in
`docs/96-live-memory-automapper.md`, "Giving up on a connection".

It reaches into `ViceTarget._mon.sock` on purpose. There is no public way to
make a healthy connection behave like a stalled one, and the point of the run
is what the *public* API does afterwards.

The pool owns the emulator -- claim, launch, tear down -- and nothing is ever
killed by name.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from session import Session, claim_slot  # noqa: E402

from automap.target import (  # noqa: E402
    MonitorBusy,
    NotConnected,
    ViceTarget,
    monitor_listening,
)
from automap.vice import MonitorError  # noqa: E402

#: Short enough that the read gives up mid-message, which is the state a
#: stalled emulator leaves the socket in; long enough not to fail on connect.
POISON = 0.0005

#: Somewhere the KERNAL keeps a byte that is always readable, so step 5 can
#: ask for one and know what a healthy answer looks like.
PROBE_ADDR = 0x00A2


def attempt(port: int) -> str:
    """Attach once, and say what came back and how long it took."""
    t0 = time.perf_counter()

    def took() -> str:
        return f"{(time.perf_counter() - t0) * 1000:.0f} ms"

    try:
        target = ViceTarget(port=port)
        target.close()
        return f"ATTACHED in {took()}"
    except MonitorBusy as exc:
        return f"MonitorBusy in {took()}: {exc}"
    except NotConnected as exc:
        return f"NotConnected in {took()}: {exc}"
    except Exception as exc:                                # noqa: BLE001
        return f"{type(exc).__name__} in {took()}: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    ap.add_argument("--slot", type=int, default=None,
                    help="pool slot to claim; the first free one by default")
    ap.add_argument("--out", default="",
                    help="write the results as JSON here as well as printing")
    ap.add_argument("--settle", type=float, default=3.0,
                    help="seconds to let VICE come up before attaching")
    args = ap.parse_args(argv)

    slot = claim_slot(args.slot, note="monitorchain: the disconnect chain")
    out: dict = {"slot": slot.n, "port": slot.port}
    sess = Session(slot=slot)
    try:
        slot.seed_vicerc()
        sess.launch()
        time.sleep(args.settle)

        out["baseline_attach"] = attempt(slot.port)

        # -- 1. one held connection, and a second client while it is well ---
        target = ViceTarget(port=slot.port)
        out["held_attach"] = "ATTACHED"
        out["second_client_while_healthy"] = attempt(slot.port)

        # -- 2. poison the held one and see what `fix` raises ----------------
        # The socket stays open and whatever VICE sends afterwards is left in
        # it unread, which is what a stalled emulator does to wish.
        target._mon.sock.settimeout(POISON)
        try:
            target.fix()
            out["poisoned_fix"] = "returned without raising"
        except NotConnected as exc:
            out["poisoned_fix"] = f"NotConnected: {exc}"
        except MonitorError as exc:
            out["poisoned_fix"] = f"MonitorError (NOT NotConnected): {exc}"
        except Exception as exc:                            # noqa: BLE001
            out["poisoned_fix"] = f"{type(exc).__name__}: {exc}"
        out["open_flag_after_fix"] = target._open

        # -- 3. does `close()` close? ---------------------------------------
        target.close()
        sock = target._mon.sock
        out["socket_after_close"] = (
            "STILL OPEN" if isinstance(sock, socket.socket)
            and sock.fileno() != -1 else "closed")

        # -- 4. the reattach ------------------------------------------------
        out["monitor_listening"] = monitor_listening(port=slot.port)
        out["reattach_1"] = attempt(slot.port)
        out["reattach_2"] = attempt(slot.port)
        if isinstance(sock, socket.socket) and sock.fileno() != -1:
            sock.close()
            time.sleep(1.0)
            out["reattach_after_socket_closed"] = attempt(slot.port)

        # -- 5. does a timed-out read leave the stream out of step? ----------
        # Same connection, no give-up: read again after the timeout and see
        # whether the reply lines up with what was asked for.
        second = ViceTarget(port=slot.port)
        second._mon.sock.settimeout(POISON)
        try:
            second._mon.read(0x0400, 40)
            out["timed_out_read"] = "returned without raising"
        except Exception as exc:                            # noqa: BLE001
            out["timed_out_read"] = f"{type(exc).__name__}: {exc}"
        second._mon.sock.settimeout(5.0)
        for key in ("next_read_after_timeout", "second_read_after_timeout"):
            try:
                out[key] = f"OK: {second._mon.read(PROBE_ADDR, 1).hex()}"
            except Exception as exc:                        # noqa: BLE001
                out[key] = f"{type(exc).__name__}: {exc}"
        try:
            second.close()
        except Exception:
            pass
    finally:
        print(json.dumps(out, indent=2), flush=True)
        if args.out:
            path = pathlib.Path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, indent=2))
        try:
            sess.close()
        except Exception:
            pass
        slot.teardown()
        slot.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

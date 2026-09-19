#!/usr/bin/env python3
"""Measurements for the two automapper complaints, on one pooled slot.

    tools/automappoll.py [--slot N] [--out DIR]

The two complaints are `#152 (The Fast Travel button greys itself out for a
second while the party stands still)` and `#151 (The automapper loses VICE and
cannot get back in, because it never hangs up the connection it gave up on)`.
It claims pool slot N (default 1), boots Pool of Radiance from `PORSAVE11.D64`
in `$POR_DISKS`, and writes `results.json` to DIR (default
`wish/automappoll` under the temp directory).

E1  Sample the CPU's PC while the party stands still in DUNGEON, and count how
    often it lands outside FastTravel's KEY_WAIT/KEY_FETCH windows.  That is
    the Fast Travel button's own gate, so the miss rate *is* the flicker rate.
E2  With one binary-monitor connection held, what does a second attach do and
    how long does it take?  (The state wish is left in after a give-up.)
E3  Round-trip times for an automapper-shaped poll, idle and across a walk.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from automap.actions import KEY_FETCH, KEY_WAIT, pc_register  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from automap.target import NotConnected, ViceTarget, monitor_listening  # noqa: E402
from automap.vice import Monitor, MonitorError  # noqa: E402
from tools import instance, scratch  # noqa: E402
from tools.c64.session import Session  # noqa: E402

DEFAULT_OUT = scratch.scratch_dir("automappoll")


def disks_dir() -> pathlib.Path:
    """The player's Pool of Radiance disk folder: `$POR_DISKS`, then the search."""
    where = os.environ.get("POR_DISKS") or find_disks()
    if not where:
        raise SystemExit("no C64 disks; set POR_DISKS")
    return pathlib.Path(where)


def claim_slot(n: int) -> instance.Slot:
    """Claim until the pool hands back slot *n*, holding the others meanwhile."""
    held = []
    try:
        for _ in range(8):
            s = instance.claim(game="por", note="automap disconnect study")
            if s.n == n:
                return s
            held.append(s)
        raise RuntimeError(f"slot {n} never came free")
    finally:
        for s in held:
            s.release()


def in_window(pc: int) -> bool:
    return any(lo <= pc < hi for lo, hi in (KEY_WAIT, KEY_FETCH))


def sample(mon: Monitor, n: int, gap: float, mode_addr: int = 0x6E11) -> dict:
    """n samples of (PC, $6E11), with a resume between, as wish does."""
    reg = pc_register(mon)
    pcs, modes, trips = [], [], []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            regs = mon.registers()
            m = mon.read(mode_addr, 1)[0]
        except (OSError, MonitorError) as exc:
            trips.append(time.perf_counter() - t0)
            pcs.append(-1)
            modes.append(-1)
            print(f"  READ FAILED after {trips[-1]*1000:.0f} ms: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue
        finally:
            try:
                mon.resume()
            except Exception:
                pass
        trips.append(time.perf_counter() - t0)
        pcs.append(regs.get(reg, -1))
        modes.append(m)
        time.sleep(gap)
    return {"pc": pcs, "mode": modes, "trip_ms": [t * 1000 for t in trips]}


def report(name: str, s: dict) -> dict:
    pcs = s["pc"]
    good = [p for p in pcs if p >= 0]
    outside = [p for p in good if not in_window(p)]
    trips = s["trip_ms"]
    hist: dict[str, int] = {}
    for p in outside:
        hist[f"${p:04X}"] = hist.get(f"${p:04X}", 0) + 1
    summary = {
        "name": name,
        "samples": len(pcs),
        "read_failures": len(pcs) - len(good),
        "outside_key_wait": len(outside),
        "outside_pct": round(100.0 * len(outside) / max(1, len(good)), 2),
        "modes": sorted(set(s["mode"])),
        "trip_ms_median": round(statistics.median(trips), 1) if trips else None,
        "trip_ms_p99": round(sorted(trips)[int(len(trips) * 0.99)], 1) if trips else None,
        "trip_ms_max": round(max(trips), 1) if trips else None,
        "trip_over_250ms": sum(1 for t in trips if t >= 250),
        "top_outside_pcs": sorted(hist.items(), key=lambda kv: -kv[1])[:12],
    }
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slot", type=int, default=1,
                    help="the pool slot to claim (default 1)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="where results.json goes")
    args = ap.parse_args(argv)
    out_dir = pathlib.Path(args.out)
    slot = claim_slot(args.slot)
    results: dict = {"slot": slot.n, "port": slot.port}
    try:
        here = pathlib.Path(slot.dir)
        shutil.copyfile(disks_dir() / "PORSAVE11.D64", here / "SIDE0.D64")
        sess = Session(slot=slot)
        sess.save_disk = str(here / "SIDE0.D64")
        try:
            if not sess.boot():
                raise RuntimeError("boot failed")
            if not sess.load_save():
                raise RuntimeError("load_save failed")
            if not sess.begin_adventuring():
                raise RuntimeError("begin_adventuring failed")
            sess.settle(4)
            print("in the world at", sess.position(), flush=True)

            # --- E1: idle, party standing still at the key prompt -----------
            with Monitor(port=slot.port, timeout=5.0) as mon:
                mon.resume()
                results["E1_idle_200ms"] = report(
                    "idle, 200 ms apart (wish's own interval)",
                    sample(mon, 400, 0.20))
                results["E1_idle_20ms"] = report(
                    "idle, 20 ms apart (same question, 10x the samples)",
                    sample(mon, 2000, 0.02))

            # --- E3: the same while the party walks -------------------------
            import threading
            stop = threading.Event()

            def walker():
                # Keys only -- XTEST, no monitor connection.  `walk_one` reads
                # the status line through a Monitor of its own, and VICE serves
                # exactly one binary-monitor connection, so it cannot be used
                # while this experiment is holding one.
                while not stop.is_set():
                    for move in "ijik":
                        if stop.is_set():
                            return
                        try:
                            sess.kbd.key(move, 0.15, 0.30)
                        except Exception as exc:            # noqa: BLE001
                            print("walk failed:", exc, flush=True)
                            return

            t = threading.Thread(target=walker, daemon=True)
            t.start()
            with Monitor(port=slot.port, timeout=5.0) as mon:
                mon.resume()
                results["E3_walking"] = report(
                    "while the party walks", sample(mon, 600, 0.20))
            stop.set()
            t.join(timeout=30)

            # --- E2: a second attach while one connection is held ------------
            e2: dict = {}
            with Monitor(port=slot.port, timeout=5.0) as held:
                held.ping()
                held.resume()
                t0 = time.perf_counter()
                e2["monitor_listening"] = monitor_listening(port=slot.port)
                e2["listening_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                t0 = time.perf_counter()
                try:
                    second = ViceTarget(port=slot.port)
                    e2["second_attach"] = "SUCCEEDED"
                    second.close()
                except NotConnected as exc:
                    e2["second_attach"] = f"{type(exc).__name__}: {exc}"
                except Exception as exc:                    # noqa: BLE001
                    e2["second_attach"] = f"{type(exc).__name__}: {exc}"
                e2["second_attach_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                # Two more in a row: does the backlog fill?
                for i in range(2):
                    t0 = time.perf_counter()
                    ok = monitor_listening(port=slot.port)
                    e2[f"listening_again_{i}"] = (
                        ok, round((time.perf_counter() - t0) * 1000, 1))
                    t0 = time.perf_counter()
                    try:
                        ViceTarget(port=slot.port).close()
                        e2[f"attach_again_{i}"] = "SUCCEEDED"
                    except Exception as exc:                # noqa: BLE001
                        e2[f"attach_again_{i}"] = f"{type(exc).__name__}: {exc}"
                    e2[f"attach_again_{i}_ms"] = round(
                        (time.perf_counter() - t0) * 1000, 1)
            results["E2_second_client"] = e2
            print(json.dumps(e2, indent=2), flush=True)

            # --- E2b: abandon a connection without EXIT ---------------------
            # A read stops the machine.  wish's give-up path never sends EXIT
            # and never closes; does the game run again when the socket dies?
            e2b: dict = {}
            m = Monitor(port=slot.port, timeout=5.0)
            m.__enter__()
            m.read(0x00A2, 1)                 # the machine is now stopped
            jiffy0 = m.read(0x00A2, 1)[0]
            m.sock.close()                    # abandoned: no EXIT, no __exit__
            m.sock = None
            time.sleep(2.0)
            with Monitor(port=slot.port, timeout=5.0) as m2:
                jiffy1 = m2.read(0x00A2, 1)[0]
                m2.resume()
            e2b["jiffy_before"] = jiffy0
            e2b["jiffy_after_2s"] = jiffy1
            e2b["emulator_kept_running"] = jiffy0 != jiffy1
            results["E2b_abandoned_socket"] = e2b
            print(json.dumps(e2b, indent=2), flush=True)
        finally:
            try:
                sess.close()
            except Exception as exc:                        # noqa: BLE001
                print("teardown:", exc, flush=True)
    finally:
        scratch.ensure(out_dir)
        (out_dir / "results.json").write_text(json.dumps(results, indent=2))
        slot.teardown()
        slot.release()
    print("wrote", out_dir / "results.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""How long does the PC stay outside FastTravel's windows? (`#152`)

Kept from `#152 (The Fast Travel button greys itself out for a second while the
party stands still)`. The button's gate is one sample of the program counter
and about 3% of samples land in the KERNAL's IRQ path with the game idle.
Donald's fix waits after the click instead, so the number that decides the
wait's time limit is not the miss *rate* but how long a miss *lasts*.

M1  Idle: sample the PC at the interval the wait loop will use, and for every
    sample that is outside, count the samples and the wall time until one is
    inside again.
M2  The same while the party walks -- the game genuinely busy.

    tools/fasttravelpcwait.py [--slot 2] [--save PORSAVE11.D64] [--disks DIR] [--out DIR]

It claims a pool slot, stages the Pool of Radiance disks and the save into it,
boots, loads, begins adventuring and samples the monitor; `--save` defaults to
`PORSAVE11.D64` in the disks directory (`automap.paths.find_disks()`). The
results go to `wait.json` under `--out`. It claims a pool slot and boots an
emulator, so it belongs to `.claude/rules/emulator.md`.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import statistics
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from automap.actions import KEY_FETCH, KEY_WAIT, pc_register  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from automap.vice import Monitor, MonitorError  # noqa: E402
from tools import scratch  # noqa: E402
from tools import session as S  # noqa: E402


def in_window(pc: int) -> bool:
    return any(lo <= pc < hi for lo, hi in (KEY_WAIT, KEY_FETCH))


def trace(mon: Monitor, n: int, gap: float) -> list[tuple[float, int]]:
    """(monotonic, PC) n times, resuming between as wish does."""
    reg = pc_register(mon)
    out = []
    for _ in range(n):
        try:
            regs = mon.registers()
        except (OSError, MonitorError) as exc:
            print("  READ FAILED:", type(exc).__name__, exc, flush=True)
            out.append((time.monotonic(), -1))
            continue
        finally:
            try:
                mon.resume()
            except Exception:
                pass
        out.append((time.monotonic(), regs.get(reg, -1)))
        time.sleep(gap)
    return out


def runs(tr: list[tuple[float, int]]) -> dict:
    """Consecutive outside samples, and how long each such run lasted."""
    lengths, waits = [], []
    i = 0
    while i < len(tr):
        if tr[i][1] >= 0 and not in_window(tr[i][1]):
            j = i
            while j < len(tr) and tr[j][1] >= 0 and not in_window(tr[j][1]):
                j += 1
            lengths.append(j - i)
            if j < len(tr):
                # what a wait starting on the first outside sample would cost
                waits.append((tr[j][0] - tr[i][0]) * 1000.0)
            i = j
        else:
            i += 1
    return {"outside_runs": len(lengths),
            "run_lengths": sorted(lengths, reverse=True)[:20],
            "longest_run_samples": max(lengths) if lengths else 0,
            "wait_ms": [round(w, 1) for w in sorted(waits, reverse=True)[:20]],
            "wait_ms_max": round(max(waits), 1) if waits else 0.0,
            "wait_ms_median": round(statistics.median(waits), 1) if waits else 0.0}


def summarise(name: str, tr: list[tuple[float, int]], gap: float) -> dict:
    good = [p for _t, p in tr if p >= 0]
    outside = [p for p in good if not in_window(p)]
    s = {"name": name, "gap_ms": gap * 1000, "samples": len(tr),
         "read_failures": len(tr) - len(good),
         "outside": len(outside),
         "outside_pct": round(100.0 * len(outside) / max(1, len(good)), 2)}
    s.update(runs(tr))
    hist: dict[str, int] = {}
    for p in outside:
        hist[f"${p:04X}"] = hist.get(f"${p:04X}", 0) + 1
    s["top_outside_pcs"] = sorted(hist.items(), key=lambda kv: -kv[1])[:12]
    print(json.dumps(s, indent=2), flush=True)
    return s


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slot", type=int, default=2,
                        help="the pool slot to claim (default 2)")
    parser.add_argument("--save", type=pathlib.Path,
                        help="a Pool of Radiance save disk "
                             "(default PORSAVE11.D64 in the disks directory)")
    parser.add_argument("--disks", type=pathlib.Path,
                        help="the Pool of Radiance disks directory")
    parser.add_argument("--out", type=pathlib.Path,
                        default=None,
                        help="where wait.json goes (default: this tool's "
                             "scratch directory)")
    args = parser.parse_args(argv)
    disks = args.disks or find_disks()
    if disks is None:
        parser.error("no Pool of Radiance disks found; set $POR_DISKS or "
                     "pass --disks")
    base_save = args.save or disks / "PORSAVE11.D64"

    out = args.out or scratch.scratch_dir("fasttravelpcwait")
    scratch.ensure(out)
    slot = S.claim_slot(args.slot, "issue 152 fast travel wait")
    results: dict = {"slot": slot.n, "port": slot.port}
    try:
        here = pathlib.Path(slot.dir)
        # Seed the slot with its own copies of the game's sides. The game
        # writes to the disks it is given, so the player's own images are
        # never in the drive and two slots never share one copy.
        for n in range(1, 9):
            dst = here / f"SIDE{n}.D64"
            if not dst.exists():
                shutil.copyfile(disks / f"POOL{n}.D64", dst)
                dst.chmod(0o644)
        boot = here / "BOOT.D64"
        if not boot.exists():
            shutil.copyfile(disks / "POOLBOOT.D64", boot)
            boot.chmod(0o644)
        shutil.copyfile(base_save, here / "SIDE0.D64")
        sess = S.Session(slot=slot)
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

            with Monitor(port=slot.port, timeout=5.0) as mon:
                mon.resume()
                results["M1_idle_20ms"] = summarise(
                    "idle, 20 ms apart", trace(mon, 2000, 0.02), 0.02)
                results["M1_idle_5ms"] = summarise(
                    "idle, 5 ms apart", trace(mon, 2000, 0.005), 0.005)

            stop = threading.Event()

            def walker():
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
                results["M2_walking_20ms"] = summarise(
                    "while the party walks, 20 ms apart",
                    trace(mon, 1500, 0.02), 0.02)
            stop.set()
            t.join(timeout=30)
        finally:
            sess.terminate()
    finally:
        slot.release()
    (out / "wait.json").write_text(json.dumps(results, indent=2))
    print("written", out / "wait.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

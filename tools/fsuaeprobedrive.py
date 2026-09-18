#!/usr/bin/env python3
"""Drive the patched FS-UAE over its GDB socket while the game runs, and
screenshot the Xvfb screen at the same moments -- a probe for `#464 (Can the
automapper follow a live FS-UAE game on Linux, so Wish and the Amiga game run
on one machine?)`.

    .venv/bin/python tools/fsuaeprobedrive.py [PORT] [--display :77] \\
        [--shots work/issue464/shots]

Continues the machine, then reads `VHPOSR` and a 1 KB block every 1.5 seconds
for 110 seconds, taking screenshots and sending keys (through `xdotool`, to
the window named FS-UAE) at fixed times, so a screenshot proves the machine
advanced between two reads. Finishes by timing reads of 2, 8, 32 and 128 KB.
The emulator has to be running already, in a private `Xvfb` on `--display`:
`tools/fsuaegdb.py launch` starts one, and `tools/fsuaerununpackaged.sh` and
`tools/fsuaeruncustombuild.sh` are the two shell versions. Uses the `Gdb` class
of `tools/fsuaegdbprobe.py`. Needs `import` (ImageMagick) and `xdotool`.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools.fsuaegdbprobe import Gdb  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def shot(shots: pathlib.Path, display: str, name: str) -> None:
    subprocess.run(
        ["import", "-window", "root", f"{shots}/{name}.png"],
        env={"DISPLAY": display, "PATH": "/usr/bin:/bin"},
        check=False,
    )


def key(display: str, *keys: str) -> None:
    env = {"DISPLAY": display, "PATH": "/usr/bin:/bin"}
    win = subprocess.run(
        ["xdotool", "search", "--name", "FS-UAE"],
        env=env, capture_output=True, text=True, check=False,
    ).stdout.split()
    if win:
        subprocess.run(["xdotool", "windowfocus", win[0]], env=env, check=False)
    for k in keys:
        subprocess.run(["xdotool", "key", k], env=env, check=False)
        time.sleep(0.4)


def timed(gdb: Gdb, addr: int, length: int) -> tuple[bytes, float]:
    t0 = time.perf_counter()
    data = gdb.read_mem(addr, length)
    return data, 1000 * (time.perf_counter() - t0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", nargs="?", type=int, default=6525)
    ap.add_argument("--display", default=":77",
                    help="the Xvfb display the emulator is on (default :77)")
    ap.add_argument("--shots", type=pathlib.Path,
                    default=ROOT / "work" / "issue464" / "shots",
                    help="directory for the screenshots")
    args = ap.parse_args(argv)
    args.shots.mkdir(parents=True, exist_ok=True)

    gdb = Gdb(port=args.port)
    gdb.ask("qSupported")
    gdb.send("vCont;c")
    time.sleep(0.3)
    print("continued")

    script = {
        6: ("shot", "run-06-boot"),
        30: ("shot", "run-30-loading"),
        44: ("key", ("Escape",)),
        48: ("key", ("Return",)),
        52: ("shot", "run-52-menu"),
        70: ("key", ("Escape", "Return")),
        76: ("shot", "run-76"),
        95: ("shot", "run-95"),
    }

    start = time.time()
    done: set[int] = set()
    while True:
        elapsed = time.time() - start
        if elapsed > 110:
            break
        for at, (what, arg) in script.items():
            if at not in done and elapsed >= at:
                done.add(at)
                if what == "shot":
                    shot(args.shots, args.display, arg)
                    print(f"[{elapsed:5.1f}s] shot {arg}")
                else:
                    key(args.display, *arg)
                    print(f"[{elapsed:5.1f}s] key {arg}")
        vh, dt_small = timed(gdb, 0xDFF006, 2)   # VHPOSR
        blk, dt_1k = timed(gdb, 0xC00000, 1024)
        print(f"[{elapsed:5.1f}s] vhposr={vh.hex()} {dt_small:5.1f} ms   "
              f"1KB {dt_1k:6.1f} ms  nonzero={sum(1 for b in blk if b):4d}")
        time.sleep(1.5)

    # how big can one read be?
    for size in (2048, 8192, 32768, 131072):
        try:
            data, dt = timed(gdb, 0xC00000, size)
            print(f"read {size:7d} bytes: {dt:8.1f} ms  ({len(data)} back)")
        except Exception as exc:                     # noqa: BLE001
            print(f"read {size:7d} bytes: FAILED {exc}")
            break
    shot(args.shots, args.display, "run-end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

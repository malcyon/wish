#!/usr/bin/env python3
"""Fire a Pool of Radiance Amiga trip off the travel grid with the boat exit's redraw statements, one screenshot per prefix.

The boat exit runs five statement groups before its `NEWECL` that a Fast Travel
trip off the grid does not (`automap.amigatrip.boat_exit_groups`). One boot
answers which of them clears the wilderness picture left around the 3D frame:
the machine is snapshotted once at the world menu, and for each prefix length
0 to 5 it is restored, the trip is written (the prefix, then the trip's own
`SAVE` square and `NEWECL`) at the script buffer's tail with the step entry and
the forward key's message pointed at it. The wait is: poll the area byte until
it changes, then wait 3 s, then take the screenshot. A prefix whose area byte
never changes is reported as not fired and the run goes on with the next one.

    tools/amiga/tripprobe.py --holder wish1-por --area 0 --square 9,14,2 --out DIR

The lane claim is the caller's, as in `amigadrive.py`; this writes only the
running machine's memory and DIR, and discards its snapshot at the end.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from automap import amigatrip  # noqa: E402

#: Seconds the area byte may take to change after the key, and the pause after
#: it before the screenshot.
FIRE_SECONDS = 20.0
SETTLE_SECONDS = 3.0
POLL_SECONDS = 0.25


class ProbeError(RuntimeError):
    """The game was not ready, or the trip did not fire."""


def statements(prefix: int, square, area: int) -> bytes:
    """The first `prefix` boat-exit groups, then the trip's own statements."""
    groups = amigatrip.boat_exit_groups()
    if not 0 <= prefix <= len(groups):
        raise ValueError(f"prefix {prefix} is outside 0 to {len(groups)}")
    return b"".join(groups[:prefix]) + amigatrip.encode("pool-of-radiance", square, area)


def write_trip(target, row, data: bytes) -> int:
    """Write `data` at the buffer's tail, the entry and the key; returns the departing area."""
    base = amigatrip._base(target)
    if base is None or not amigatrip.gate(target, row):
        raise ProbeError("the game is not at its world menu")
    here = amigatrip.area_id(target, row)
    at, message_at = amigatrip.layout(row, len(data))
    buffer = amigatrip._long(target, base + row.buffer_pointer) + row.buffer_bias
    if (buffer + message_at) % 4:
        raise ProbeError(f"the script buffer at {buffer:#x} is not longword-aligned")
    port = amigatrip._port(target, row)
    window = amigatrip._long(target, base + row.window_pointer)
    target.write(buffer + at, data)
    target.write(buffer + message_at, amigatrip.rawkey_message(port, window))
    target.write(base + row.step_entry, (row.ecl_origin + at).to_bytes(2, "big"))
    target.write(port + amigatrip.PORT_LIST, amigatrip.link(buffer + message_at),
                 verify=False)
    return here


def run(target, holder: str, area: int, square, out: pathlib.Path,
        shot: Callable[[str, pathlib.Path], object],
        prefixes=range(6), sleep: Callable[[float], None] | None = None,
        name: str = "tripprobe", pipe=None) -> list[tuple[int, pathlib.Path | None]]:
    """One (prefix, screenshot) per prefix length, each from a restore of one snapshot.

    `target` reads and writes memory; `pipe` (default `target`) holds the
    snapshots. The screenshot is None for a prefix whose trip did not fire.
    """
    row = amigatrip.row_for("pool-of-radiance")
    pipe = target if pipe is None else pipe
    sleep = time.sleep if sleep is None else sleep
    shots = []
    pipe.snapshot(name, holder)
    try:
        for prefix in prefixes:
            pipe.restore(name, holder)
            here = write_trip(target, row, statements(prefix, square, area))
            waited = 0.0
            while amigatrip.area_id(target, row) == here and waited < FIRE_SECONDS:
                sleep(POLL_SECONDS)
                waited += POLL_SECONDS
            if amigatrip.area_id(target, row) == here:
                shots.append((prefix, None))
                continue
            sleep(SETTLE_SECONDS)
            path = out / f"prefix{prefix}.png"
            shot(holder, path)
            shots.append((prefix, path))
    finally:
        pipe.discard_snapshot(name, holder)
    return shots


def main(argv: list[str] | None = None) -> int:
    from automap import amiga  # noqa: PLC0415
    from tools.amiga import amigadrive  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holder", required=True, help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--area", type=int, required=True, help="the destination area id")
    parser.add_argument("--square", required=True, help="x,y,facing in the destination")
    parser.add_argument("--out", required=True, help="directory for prefix0.png to prefix5.png")
    args = parser.parse_args(argv)
    square = tuple(int(n) for n in args.square.split(","))
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pipe = amiga.WinuaePipe(holder=args.holder)
    target = amiga.AmigaTarget(pipe, amiga.MACHINES["pool-of-radiance"])
    try:
        target.locate()
        for prefix, path in run(target, args.holder, args.area, square, out,
                                lambda holder, path: amigadrive.shot(holder, path),
                                pipe=pipe):
            print(path if path else f"prefix {prefix}: the area byte did not change")
    except ProbeError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    sys.exit(main())

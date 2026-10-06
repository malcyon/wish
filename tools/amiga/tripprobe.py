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

`--door` is the door probe for variant D: the party is stood on the exit square
by writing x, y and facing, the wall nibble ahead (`0x1772`) and the square's
attribute byte (`0x1773`) the step entry reads uncached, and the forward key
is sent for the game's own step code to run the exit. `--attribute skip` leaves
`0x1773` alone, so a run can show whether it matters. A key not taken within
`FIRE_SECONDS` puts every byte back. One JSON line per try goes to
DIR/doors.jsonl.

    tools/amiga/tripprobe.py --holder wish1-por --door \\
        --route edge=4,0,0 --route question=6,14,2 --attribute both --out DIR

The lane claim is the caller's, as in `amigadrive.py`; this writes only the
running machine's memory and DIR, and discards its snapshot at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from automap import amiga, amigatrip  # noqa: E402
from goldbox.geo import Geo  # noqa: E402

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


def stand_writes(target, row, stand, geo: Geo, attribute: bool) -> list[tuple[int, bytes, str]]:
    """Variant D's `(address, data, kind)` writes for the party standing at `stand`.

    The square, then the wall nibble ahead and (unless `attribute` is False)
    the square's attribute byte, which the engine caches at the last redraw,
    then the key's message and its link.
    """
    x, y, facing = stand
    base = amigatrip._base(target)
    notes = amiga.MACHINES[row.key].notes
    writes = [(amigatrip._address(target, spot), amigatrip._encode_spot(spot, value),
               "square") for spot, value in zip(row.square_spots, stand)]
    writes.append((base + notes["wall_ahead"], bytes([geo.wall(x, y, facing)]), "wall"))
    if attribute:
        writes.append((base + notes["square_attribute"], bytes([geo.attributes(x, y)]),
                       "attribute"))
    at, message_at = amigatrip.layout(row, 0)
    buffer = amigatrip._long(target, base + row.buffer_pointer) + row.buffer_bias
    if (buffer + message_at) % 4:
        raise ProbeError(f"the script buffer at {buffer:#x} is not longword-aligned")
    port = amigatrip._port(target, row)
    window = amigatrip._long(target, base + row.window_pointer)
    writes.append((buffer + message_at, amigatrip.rawkey_message(port, window), "message"))
    writes.append((port + amigatrip.PORT_LIST, amigatrip.link(buffer + message_at), "trigger"))
    return writes


def _list_is_empty(target, row) -> bool:
    port = amigatrip._port(target, row)
    return target.read(port + amigatrip.PORT_LIST, 12) == amigatrip.empty_list(port)


def key_taken(target, row) -> bool:
    """True once the window's port list is empty again: the game took the message."""
    return _list_is_empty(target, row)


def put_back(target, row, done, stop_if_taken: bool = False) -> bool:
    """Put the key link back first, then every other byte; True when the game had taken the key.

    The rest is put back even when the key's restore fails, and the first
    exception is the one raised. With `stop_if_taken`, a port list that reads
    empty before the key's restore means the game consumed the key, and the other
    bytes stay under the game's own step.
    """
    keys = [w for w in done if w.kind == "trigger"]
    rest = [w for w in done if w.kind != "trigger"]
    try:
        consumed = stop_if_taken and bool(keys) and _list_is_empty(target, row)
        amigatrip._restore(target, keys)
    except BaseException:
        # A read that failed before the key's restore leaves the key to put back first.
        for records in (keys, rest):
            try:
                amigatrip._restore(target, records)
            except Exception:  # noqa: S110 - the first exception is the one to report
                pass
        raise
    if consumed:
        return True
    amigatrip._restore(target, rest)
    return False


def try_door(target, row, stand, attribute: bool,
             sleep: Callable[[float], None]) -> dict:
    """Stand the party at `stand`, send the key and wait for it to be taken.

    Everything written is put back, the key first, when the key is not taken
    within `FIRE_SECONDS`; once it is taken the game's own step stands. The
    result records the key, the area before and after, and the square after.
    """
    if amigatrip._base(target) is None or not amigatrip.gate(target, row):
        raise ProbeError("the game is not at its world menu")
    blob = target.geo()
    if blob is None:
        raise ProbeError("no map is loaded")
    here = amigatrip.area_id(target, row)
    writes = stand_writes(target, row, stand, Geo(blob), attribute)
    originals = target.read_blocks([(a, len(d)) for a, d, _k in writes])
    done = []
    try:
        for (address, data, kind), was in zip(writes, originals):
            done.append(amigatrip.Written(address, was, data, kind))
            target.write(address, data, verify=kind != "trigger")
    except BaseException:
        try:
            put_back(target, row, done)
        except Exception:  # noqa: S110 - the write's own exception is the one to report
            pass
        raise
    try:
        waited = 0.0
        while not key_taken(target, row) and waited < FIRE_SECONDS:
            sleep(POLL_SECONDS)
            waited += POLL_SECONDS
        taken = key_taken(target, row)
    except BaseException:
        try:
            put_back(target, row, done)
        except Exception:  # noqa: S110 - the poll's own exception is the one to report
            pass
        raise
    if not taken:
        # A key taken after the last poll is found out by the put-back.
        taken = put_back(target, row, done, stop_if_taken=True)
    if taken:
        sleep(SETTLE_SECONDS)
    after = amigatrip.area_id(target, row)
    return {"key_taken": taken, "area_before": here, "area_after": after,
            "area_changed": after != here, "square_after": amigatrip.square(target, row),
            "put_back": not taken}


def run_doors(target, holder: str, routes: dict[str, tuple[int, int, int]], attributes,
              out: pathlib.Path, shot: Callable[[str, pathlib.Path], object],
              sleep: Callable[[float], None] | None = None,
              name: str = "doorprobe", pipe=None) -> list[dict]:
    """One result per (route, attribute choice), each from a restore of one snapshot.

    The snapshot is restored once more after the last try, and on any exception,
    so no try leaves bytes in the game.

    Writes one JSON line per try to `out/doors.jsonl` and one screenshot per
    try, `<route>-attribute.png` or `<route>-skip.png`.
    """
    row = amigatrip.row_for("pool-of-radiance")
    pipe = target if pipe is None else pipe
    sleep = time.sleep if sleep is None else sleep
    results = []
    pipe.snapshot(name, holder)
    try:
        with open(out / "doors.jsonl", "w") as lines:
            for route, stand in routes.items():
                for attribute in attributes:
                    pipe.restore(name, holder)
                    result = try_door(target, row, stand, attribute, sleep)
                    path = out / f"{route}-{'attribute' if attribute else 'skip'}.png"
                    shot(holder, path)
                    result.update(route=route, stand=list(stand), attribute=attribute,
                                  screenshot=path.name)
                    lines.write(json.dumps(result) + "\n")
                    results.append(result)
        pipe.restore(name, holder)
    except BaseException:
        try:
            pipe.restore(name, holder)
        except Exception:  # noqa: S110 - the probe's own exception is the one to report
            pass
        raise
    finally:
        pipe.discard_snapshot(name, holder)
    return results


def main(argv: list[str] | None = None) -> int:
    from tools.amiga import amigadrive  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holder", required=True, help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--area", type=int, help="the destination area id")
    parser.add_argument("--square", help="x,y,facing in the destination")
    parser.add_argument("--out", required=True, help="directory for prefix0.png to prefix5.png")
    parser.add_argument("--door", action="store_true",
                        help="probe a door exit (variant D) instead of a trip off the grid")
    parser.add_argument("--route", action="append", default=[], metavar="NAME=X,Y,FACING",
                        help="with --door: the square to stand on and the facing; repeatable")
    parser.add_argument("--attribute", choices=("write", "skip", "both"), default="write",
                        help="with --door: whether to write the square's attribute byte (0x1773)")
    args = parser.parse_args(argv)
    if args.door:
        if not args.route:
            parser.error("--door needs at least one --route")
    elif args.area is None or args.square is None:
        parser.error("without --door, --area and --square are required")
    routes = {}
    for item in args.route:
        label, _, spot = item.partition("=")
        try:
            stand = tuple(int(n) for n in spot.split(","))
        except ValueError:
            stand = ()
        if not spot or len(stand) != 3:
            parser.error(f"--route {item!r} is not NAME=X,Y,FACING")
        if label in routes:
            parser.error(f"--route {label!r} is given twice")
        routes[label] = stand
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pipe = amiga.WinuaePipe(holder=args.holder)
    target = amiga.AmigaTarget(pipe, amiga.MACHINES["pool-of-radiance"])
    try:
        target.locate()
        if args.door:
            choices = {"write": (True,), "skip": (False,), "both": (True, False)}[args.attribute]
            for result in run_doors(target, args.holder, routes, choices, out,
                                    lambda holder, path: amigadrive.shot(holder, path),
                                    pipe=pipe):
                print(json.dumps(result))
            return 0
        square = tuple(int(n) for n in args.square.split(","))
        for prefix, path in run(target, args.holder, args.area, square, out,
                                lambda holder, path: amigadrive.shot(holder, path),
                                pipe=pipe):
            print(path if path else f"prefix {prefix}: the area byte did not change")
    except (ProbeError, amiga.GuestError) as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    sys.exit(main())

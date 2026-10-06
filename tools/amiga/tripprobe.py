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
DIR/doors.jsonl, with the wall nibble and attribute byte read back just before
the key.

    tools/amiga/tripprobe.py --holder wish1-por --door \\
        --route edge=4,0,0 --route question=6,14,2 --attribute both --out DIR

`--answer NAME=KEY` answers the question the key raised on route NAME. A
screenshot is taken before the door key; the answer goes only when the key was
taken, the area byte is unchanged and the screen differs from that one, so a
route with no question is never answered. Then it presses KEY, polls the area
byte for `FIRE_SECONDS` (until it is `--expect-area [NAME=]AREA`, or until it
changes when none is given), settles, takes a second screenshot, then presses
the forward key and takes a third. A route not answered records `answered:
false` and the reason. An `--expect-area` equal to the area before the answer
proves nothing and is recorded as `expect_unproven`. Without NAME an
`--expect-area` applies to every answered route.

    tools/amiga/tripprobe.py --holder wish1-por --door --route valjevo=5,7,1 \\
        --answer y --expect-area 5 --out DIR

`--prefixes 0` (not with `--door`) fires one trip and leaves the game where it lands, so a later
`--door` run in the same boot starts from the area the trip loaded; every
`--door` run still restores its snapshot at the end.

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
from tools.amiga import amigakeys  # noqa: E402

#: Seconds the area byte may take to change after the key, and the pause after
#: it before the screenshot.
FIRE_SECONDS = 20.0
SETTLE_SECONDS = 3.0
POLL_SECONDS = 0.25

#: The key the game's own forward step answers to (Amiga raw key 8).
FORWARD_KEY = "8"

#: The title the probes run against unless `--title` names another.
DEFAULT_TITLE = "pool-of-radiance"


class ProbeError(RuntimeError):
    """The game was not ready, or the trip did not fire."""


def statements(prefix: int, square, area: int, key: str = DEFAULT_TITLE) -> bytes:
    """The first `prefix` boat-exit groups, then the trip's own statements for title `key`."""
    groups = amigatrip.boat_exit_groups()
    if not 0 <= prefix <= len(groups):
        raise ValueError(f"prefix {prefix} is outside 0 to {len(groups)}")
    return b"".join(groups[:prefix]) + amigatrip.encode(key, square, area)


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
        name: str = "tripprobe", pipe=None,
        title: str = DEFAULT_TITLE) -> list[tuple[int, pathlib.Path | None]]:
    """One (prefix, screenshot) per prefix length, each from a restore of one snapshot.

    `target` reads and writes memory; `pipe` (default `target`) holds the
    snapshots. The screenshot is None for a prefix whose trip did not fire.
    `title` is the `amiga.MACHINES` key whose row and statements are used.
    """
    row = amigatrip.row_for(title)
    pipe = target if pipe is None else pipe
    sleep = time.sleep if sleep is None else sleep
    shots = []
    pipe.snapshot(name, holder)
    try:
        for prefix in prefixes:
            pipe.restore(name, holder)
            here = write_trip(target, row, statements(prefix, square, area, title))
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


def _list_is_empty(target, row) -> bool:
    return amigatrip.port_empty(target, row)


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


def _cached_bytes(target, row) -> dict[str, int]:
    """The wall nibble ahead and the square's attribute byte as the game holds them."""
    base = amigatrip._base(target)
    notes = amiga.MACHINES[row.key].notes
    wall, attribute = target.read_blocks([(base + notes["wall_ahead"], 1),
                                          (base + notes["square_attribute"], 1)])
    return {"wall_ahead": wall[0], "square_attribute": attribute[0]}


def _unanswered(result: dict, before: bytes, after: bytes) -> str | None:
    """Why no question can be on screen after the door key, or None when one may be."""
    if not result["key_taken"]:
        return "the door key was not taken"
    if result["area_changed"]:
        return "the area byte changed, so the key did not raise a question"
    if before == after:
        return "the screen did not change after the door key"
    return None


def answer_door(target, row, route: str, key: str, expect: int | None, out: pathlib.Path,
                shot: Callable[[pathlib.Path], object], press: Callable[[str], object],
                sleep: Callable[[float], None]) -> dict:
    """Press `key`, wait for the area byte, then screenshot, step forward and screenshot.

    The area byte is polled for `FIRE_SECONDS` until it equals `expect`, or until
    it differs from its value before the key when `expect` is None.
    """
    before = amigatrip.area_id(target, row)

    # An expected area equal to the starting one is true before the first poll.
    unproven = expect is not None and expect == before

    def arrived() -> bool:
        now = amigatrip.area_id(target, row)
        return now == expect if expect is not None else now != before

    press(key)
    waited = 0.0
    while not unproven and not arrived() and waited < FIRE_SECONDS:
        sleep(POLL_SECONDS)
        waited += POLL_SECONDS
    reached = None if unproven else arrived()
    sleep(SETTLE_SECONDS)
    answered = out / f"{route}-answer.png"
    shot(answered)
    result = {"answered": True, "answer": key, "expect_area": expect,
              "expect_unproven": unproven, "answer_area_before": before,
              "answer_area": amigatrip.area_id(target, row), "area_reached": reached,
              "answer_square": amigatrip.square(target, row),
              "answer_screenshot": answered.name}
    press(FORWARD_KEY)
    sleep(SETTLE_SECONDS)
    forward = out / f"{route}-forward.png"
    shot(forward)
    result.update(forward_square=amigatrip.square(target, row),
                  forward_screenshot=forward.name)
    return result


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
    try:
        writes = amigatrip.stand_writes(target, row, stand, Geo(blob), attribute)
    except amigatrip.ArmError as exc:
        raise ProbeError(str(exc)) from exc
    originals = target.read_blocks([(a, len(d)) for a, d, _k in writes])
    done = []
    cached = {}
    try:
        for (address, data, kind), was in zip(writes, originals):
            if kind == "trigger":
                # Read before the key, which the game may take within a frame.
                cached = _cached_bytes(target, row)
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
            "put_back": not taken, **cached}


def run_doors(target, holder: str, routes: dict[str, tuple[int, int, int]], attributes,
              out: pathlib.Path, shot: Callable[[str, pathlib.Path], object],
              sleep: Callable[[float], None] | None = None,
              name: str = "doorprobe", pipe=None,
              answers: dict[str, tuple[str, int | None]] | None = None,
              press: Callable[[str], object] | None = None,
              title: str = DEFAULT_TITLE) -> list[dict]:
    """One result per (route, attribute choice), each from a restore of one snapshot.

    The snapshot is restored once more after the last try, and on any exception,
    so no try leaves bytes in the game.

    Writes one JSON line per try to `out/doors.jsonl` and one screenshot per
    try, `<route>-attribute.png` or `<route>-skip.png`. A route in `answers`
    (`(key, expected area or None)`) whose key was taken is answered by
    `answer_door` through `press(key)` before the next restore.
    """
    answers = answers or {}
    if answers and press is None:
        raise ValueError("answers need a press callable")
    row = amigatrip.row_for(title)
    pipe = target if pipe is None else pipe
    sleep = time.sleep if sleep is None else sleep
    results = []
    pipe.snapshot(name, holder)
    try:
        with open(out / "doors.jsonl", "w") as lines:
            for route, stand in routes.items():
                for attribute in attributes:
                    pipe.restore(name, holder)
                    stem = f"{route}-{'attribute' if attribute else 'skip'}"
                    path = out / f"{stem}.png"
                    if route in answers:
                        world = out / f"{stem}-before.png"
                        shot(holder, world)
                    result = try_door(target, row, stand, attribute, sleep)
                    shot(holder, path)
                    result.update(route=route, stand=list(stand), attribute=attribute,
                                  screenshot=path.name)
                    if route in answers:
                        why = _unanswered(result, world.read_bytes(), path.read_bytes())
                        if why is None:
                            key, expect = answers[route]
                            result.update(answer_door(
                                target, row, route, key, expect, out,
                                lambda p: shot(holder, p), press, sleep))
                        else:
                            result.update(answered=False, answer_skipped=why)
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


def _answers(parser, routes, answers, expects) -> dict[str, tuple[str, int | None]]:
    """Each route's `(key, expected area)` from `[NAME=]KEY` and `[NAME=]AREA` options."""
    def split(item: str, what: str, named: bool = False) -> tuple[str | None, str]:
        label, eq, value = item.rpartition("=")
        if not value or (eq and label not in routes) or (named and not eq):
            parser.error(f"{what} {item!r} is not {'' if named else '[NAME=]'}NAME=VALUE "
                         "with NAME a --route")
        return (label or None), value

    keys: dict[str | None, str] = {}
    for item in answers:
        label, value = split(item, "--answer", named=True)
        try:
            amigakeys.lookup(value)
        except KeyError:
            parser.error(f"--answer {value!r} is not a key name")
        keys[label] = value
    areas: dict[str | None, int] = {}
    for item in expects:
        label, value = split(item, "--expect-area")
        try:
            areas[label] = int(value)
        except ValueError:
            parser.error(f"--expect-area {value!r} is not a number")
    result = {}
    for route in routes:
        key = keys.get(route, keys.get(None))
        if key is not None:
            result[route] = (key, areas.get(route, areas.get(None)))
    if areas and not set(areas) <= set(keys) | {None} or (None in areas and not keys):
        parser.error("--expect-area needs an --answer for the same route")
    return result


def main(argv: list[str] | None = None) -> int:
    from tools.amiga import amigadrive  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holder", required=True, help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--title", default=DEFAULT_TITLE, choices=sorted(amiga.MACHINES),
                        help="the amiga.MACHINES key of the title in the machine")
    parser.add_argument("--area", type=int, help="the destination area id")
    parser.add_argument("--square", help="x,y,facing in the destination")
    parser.add_argument("--out", required=True, help="directory for prefix0.png to prefix5.png")
    parser.add_argument("--door", action="store_true",
                        help="probe a door exit (variant D) instead of a trip off the grid")
    parser.add_argument("--route", action="append", default=[], metavar="NAME=X,Y,FACING",
                        help="with --door: the square to stand on and the facing; repeatable")
    parser.add_argument("--attribute", choices=("write", "skip", "both"), default="write",
                        help="with --door: whether to write the square's attribute byte (0x1773)")
    parser.add_argument("--answer", action="append", default=[], metavar="NAME=KEY",
                        help="with --door: the key that answers the game's question")
    parser.add_argument("--expect-area", action="append", default=[], metavar="[NAME=]AREA",
                        help="with --door --answer: the area the answer should reach")
    parser.add_argument("--prefixes", default=None,
                        help="the prefix lengths to fire, default 0,1,2,3,4,5; 0 alone leaves "
                             "the game where the trip lands")
    args = parser.parse_args(argv)
    if (args.answer or args.expect_area) and not args.door:
        parser.error("--answer and --expect-area need --door")
    if args.door and args.prefixes is not None:
        parser.error("--prefixes does not apply to --door")
    longest = len(amigatrip.boat_exit_groups())
    try:
        default = "0,1,2,3,4,5" if args.title == DEFAULT_TITLE else "0"
        prefixes = [int(n) for n in (args.prefixes or default).split(",")]
    except ValueError:
        prefixes = []
    if not prefixes or any(not 0 <= n <= longest for n in prefixes):
        parser.error(f"--prefixes {args.prefixes!r} is not a list of lengths 0 to {longest}")
    if args.title != DEFAULT_TITLE and any(n for n in prefixes):
        parser.error("the boat-exit prefixes are Pool of Radiance statements; "
                     f"{args.title} takes --prefixes 0 only")
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
    answers = _answers(parser, routes, args.answer, args.expect_area)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pipe = amiga.WinuaePipe(holder=args.holder)
    target = amiga.AmigaTarget(pipe, amiga.MACHINES[args.title])
    try:
        target.locate()
        if args.door:
            choices = {"write": (True,), "skip": (False,), "both": (True, False)}[args.attribute]
            for result in run_doors(target, args.holder, routes, choices, out,
                                    lambda holder, path: amigadrive.shot(holder, path),
                                    pipe=pipe, answers=answers, title=args.title,
                                    press=lambda key: amigadrive.press(
                                        args.holder, key, SETTLE_SECONDS)):
                print(json.dumps(result))
            return 0
        square = tuple(int(n) for n in args.square.split(","))
        for prefix, path in run(target, args.holder, args.area, square, out,
                                lambda holder, path: amigadrive.shot(holder, path),
                                prefixes=prefixes, pipe=pipe, title=args.title):
            print(path if path else f"prefix {prefix}: the area byte did not change")
    except (ProbeError, amiga.GuestError) as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    sys.exit(main())

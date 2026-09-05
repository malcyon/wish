#!/usr/bin/env python3
"""Drive a game on the C64 Ultimate and capture what it does when it breaks.

Written for `#286 (Pool of Radiance on the C64 Ultimate sometimes hangs on a
disk load)`, where the measurement wanted is not a byte layout but a picture of
the machine at the moment a load goes wrong: the screen as the corruption
spreads, and the memory regions the bad bytes could have landed in.

`tools/c64urest.py` has the transport -- REST for the machine, FTP for a file --
and this module adds only the four things driving a game needs and that one
does not:

* **A key that is waited for.** `keys` writes the KERNAL buffer at `$0277` with
  the count at `$00C6` and then watches the count go back to zero, which is the
  running program draining it.  A count that sits there is the stage reading
  the keyboard *matrix* through CIA 1 instead, where a buffer write is never
  seen -- so `probe` reports which of the two a stage is, rather than guessing.
* **A screen that is polled until it changes.** `wait` blocks until the text
  screen matches a pattern, or until it stops changing, which is what "the load
  finished" and "the load stopped" look like from outside.
* **A capture as fast as the wire allows.** `burst` reads the screen in a loop
  and writes every frame that differs from the one before it, with the jiffy
  clock beside it.  About five frames a second over WiFi: this cannot see a
  single frame of corruption, and says so in its own manifest.
* **A region set.** `regions` dumps the screen, colour RAM, the zero page and
  the stack, the `GDRIVE` loader page, the resident `DUNGEON` overlay, the
  character-record buffer and the save image, so a hung machine can be compared
  against a running one region by region.

Every region below was identified rather than assumed, and the evidence is in
`docs/177-a-load-that-goes-wrong.md`.

    tools/c64uplay.py boot work/x/POOL1.D64 --mode readonly
    tools/c64uplay.py mount work/x/NEWSAVE6.D64 --mode readwrite
    tools/c64uplay.py screen
    tools/c64uplay.py keys Y --wait
    tools/c64uplay.py probe ' '
    tools/c64uplay.py wait --contains "onward bound" --timeout 200
    tools/c64uplay.py burst --seconds 20 --out work/x/burst
    tools/c64uplay.py regions --out work/x/hang --note "after the exit"
    tools/c64uplay.py alive --seconds 10

Nothing here writes to the device's configuration, and the only memory it
writes is `$0277` and `$00C6` -- the KERNAL keyboard buffer, which is how a
person at the machine answers a prompt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools.c64urest import (  # noqa: E402
    DeviceError,
    Rest,
    find_host,
    first_prg,
    screen_text,
)

#: The regions a failed load could have damaged, each with why it is here.
#: `screen` is `None` because the address moves -- `$0400` at boot and `$CC00`
#: with the game up -- and is computed per reading.
REGIONS: list[tuple[str, int | None, int, str]] = [
    ("screen", None, 0x03E8, "the text screen, wherever the VIC is pointed"),
    ("colour-ram", 0xD800, 0x03E8, "colour RAM; mask with $0F before comparing"),
    ("zero-page", 0x0000, 0x0800, "zero page, stack, and the two screen pages "
                                  "below the game's own"),
    ("gdrive", 0xC000, 0x0400, "GDRIVE00, the loader, and the live party "
                               "square at $C04B"),
    ("dungeon", 0x0800, 0x2380, "the DUNGEON overlay; its PRG header says "
                                "$1000 and it runs at $0800"),
    ("record", 0x6B00, 0x0500, "the 580-byte character-record buffer at "
                               "$6B00, then ITEMNAMES at $6F00"),
    ("save-image", 0x4900, 0x1C00, "SAVEDGAME0 as the engine holds it"),
    ("items", 0x7600, 0x0800, "ITEMS at $7600"),
    ("vic", 0xD000, 0x0030, "VIC registers; $D012 and the two collision "
                            "latches move on their own"),
    ("cia", 0xDC00, 0x0100, "both CIAs, the serial bus among them"),
]


def screen_address(rest: Rest) -> int:
    d018 = rest.readmem(0xD018, 1)[0]
    dd00 = rest.readmem(0xDD00, 1)[0]
    return ((~dd00 & 3) * 0x4000) + ((d018 >> 4) & 0xF) * 0x400


def jiffy(rest: Rest) -> int:
    raw = rest.readmem(0x00A0, 3)
    return (raw[0] << 16) | (raw[1] << 8) | raw[2]


def read_screen(rest: Rest, at: int | None = None) -> tuple[int, list[str]]:
    at = screen_address(rest) if at is None else at
    return at, screen_text(rest.readmem(at, 1000))


# -- keys --------------------------------------------------------------------

#: The KERNAL buffer and its count.  Nothing else in this file writes memory.
KEYBUF, KEYCOUNT = 0x0277, 0x00C6


def send_key(rest: Rest, petscii: int) -> None:
    rest.call("/machine:writemem", {"address": f"{KEYBUF:04X}"},
              method="POST", body=bytes([petscii]))
    rest.call("/machine:writemem", {"address": f"{KEYCOUNT:04X}"},
              method="POST", body=bytes([1]))


def drained(rest: Rest, timeout: float = 3.0) -> bool:
    """Did the running program take the key out of the buffer?

    True means the stage reads through the KERNAL, so it can be driven from
    here.  False means it polls CIA 1's keyboard matrix and cannot.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if rest.readmem(KEYCOUNT, 1)[0] == 0:
            return True
        time.sleep(0.15)
    return False


def petscii(text: str) -> list[int]:
    """One PETSCII code per character, with `\\r` for Return."""
    out = []
    for ch in text:
        if ch == "\\":
            continue
        out.append(0x0D if ch in "\r\n" else ord(ch.upper()))
    return out


# -- commands ----------------------------------------------------------------


def cmd_boot(rest: Rest, args) -> None:
    image = pathlib.Path(args.image)
    rest.mount_upload(image.read_bytes(), mode=args.mode, kind="d64")
    where = rest.drive().get("image_file", "")
    name, program = first_prg(image)
    rest.run_prg(program)
    print(f"{image.name} -> {where} ({args.mode}); started {name}")


def cmd_mount(rest: Rest, args) -> None:
    image = pathlib.Path(args.image)
    rest.mount_upload(image.read_bytes(), mode=args.mode, kind="d64")
    print(f"{image.name} -> {rest.drive().get('image_file', '')} ({args.mode})")


def cmd_drives(rest: Rest, args) -> None:
    print(json.dumps(rest.drives(), indent=2))


def cmd_screen(rest: Rest, args) -> None:
    at, rows = read_screen(rest)
    print(f"screen at ${at:04X}, jiffy {jiffy(rest):06X}")
    for row in rows:
        print("|" + row)


def cmd_keys(rest: Rest, args) -> None:
    for code in petscii(args.text):
        send_key(rest, code)
        took = drained(rest, args.timeout) if args.wait else True
        print(f"sent ${code:02X} {chr(code)!r}"
              + ("" if not args.wait else
                 "; taken" if took else "; NOT taken (matrix stage?)"))
        time.sleep(args.gap)


def cmd_probe(rest: Rest, args) -> None:
    """Does this stage read the KERNAL buffer at all?

    A count back at zero means yes and the stage can be driven; a count still
    sitting at one means the program is reading CIA 1 and never will.
    """
    before = rest.readmem(KEYCOUNT, 1)[0]
    send_key(rest, ord(args.key.upper()[0]))
    took = drained(rest, args.timeout)
    print(f"$00C6 before {before}, after {rest.readmem(KEYCOUNT, 1)[0]}: "
          + ("KERNAL -- drivable" if took else "matrix -- not drivable"))


def cmd_wait(rest: Rest, args) -> None:
    """Block until the screen says something, or until it stops changing."""
    deadline = time.time() + args.timeout
    last, since, at = None, time.time(), None
    while time.time() < deadline:
        at, rows = read_screen(rest)
        text = "\n".join(rows).lower()
        if args.contains and args.contains.lower() in text:
            print(f"matched at {time.strftime('%T')}, screen ${at:04X}")
            for row in rows:
                print("|" + row)
            return
        if text != last:
            last, since = text, time.time()
        elif args.still and time.time() - since >= args.still:
            print(f"still for {args.still:.0f}s at {time.strftime('%T')}")
            for row in rows:
                print("|" + row)
            return
        time.sleep(args.interval)
    print(f"timed out after {args.timeout}s; last screen ${at:04X}")
    for row in (read_screen(rest)[1] if at is None else rows):
        print("|" + row)
    raise SystemExit(4)


def cmd_burst(rest: Rest, args) -> None:
    """Capture the screen as fast as the wire allows, keeping every change.

    Over WiFi this is about five frames a second, so a single frame of
    corruption is not visible to it.  What it does catch is corruption that
    persists for a fifth of a second or longer, which is what "artifacts
    appeared, then covered the screen" describes.
    """
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    at = screen_address(rest)
    frames, prev, deadline = [], None, time.time() + args.seconds
    started = time.time()
    while time.time() < deadline:
        try:
            raw = rest.readmem(at, 1000)
            clock = jiffy(rest)
        except DeviceError as exc:
            frames.append({"at": round(time.time() - started, 3),
                           "error": str(exc)})
            time.sleep(0.5)
            continue
        if raw != prev:
            index = len(frames)
            (out / f"frame{index:04d}.bin").write_bytes(raw)
            frames.append({"index": index, "at": round(time.time() - started, 3),
                           "jiffy": clock,
                           "text": screen_text(raw)})
            prev = raw
    (out / "manifest.json").write_text(json.dumps(
        {"screen_address": at, "seconds": args.seconds,
         "frames": frames,
         "note": "one entry per screen that differed from the one before it"},
        indent=2) + "\n")
    print(f"{len(frames)} distinct frames in {args.seconds}s -> {out}")


def cmd_regions(rest: Rest, args) -> None:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    at = screen_address(rest)
    record = {"taken": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "note": args.note, "screen_address": at,
              "drives": rest.drives(), "regions": []}
    for name, start, length, why in REGIONS:
        where = at if start is None else start
        try:
            data = rest.readmem(where, length)
        except DeviceError as exc:
            record["regions"].append({"name": name, "start": where,
                                      "error": str(exc)})
            continue
        (out / f"{name}.bin").write_bytes(data)
        record["regions"].append({"name": name, "start": where,
                                  "length": length, "note": why})
    record["screen_text"] = screen_text(rest.readmem(at, 1000))
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"{len(REGIONS)} regions -> {out}")


def cmd_monitor(rest: Rest, args) -> None:
    """One JSON line per sample, written as it is taken.

    A run that ends in a hang ends by being killed, so nothing may be written
    at the end: the timeline has to exist while it is being made.  Each line
    carries the jiffy clock, `$DD00` -- the serial bus as the C64 sees it --
    and a hash of the screen, which is enough to say afterwards when the
    machine stopped and what the bus looked like when it did.
    """
    out = pathlib.Path(args.log)
    out.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.seconds
    stuck_since, last = None, None
    with out.open("a") as log:
        while time.time() < deadline:
            row = {"t": time.strftime("%H:%M:%S")}
            try:
                at = screen_address(rest)
                raw = rest.readmem(at, 1000)
                row["screen_at"] = at
                row["screen"] = hashlib.sha256(raw).hexdigest()[:12]
                row["jiffy"] = jiffy(rest)
                row["dd00"] = rest.readmem(0xDD00, 1)[0]
                row["d012"] = rest.readmem(0xD012, 1)[0]
            except DeviceError as exc:
                row["error"] = str(exc)
            key = (row.get("screen"), row.get("jiffy"))
            if key == last:
                stuck_since = stuck_since or time.time()
                row["still_for"] = round(time.time() - stuck_since, 1)
            else:
                stuck_since, last = None, key
            log.write(json.dumps(row) + "\n")
            log.flush()
            if args.echo:
                print(json.dumps(row), flush=True)
            if args.stop_after and row.get("still_for", 0) >= args.stop_after:
                print(f"stopped changing for {row['still_for']}s", flush=True)
                return
            time.sleep(args.interval)


def cmd_hangwatch(rest: Rest, args) -> None:
    """Watch until the machine stops, then capture it without being asked.

    The failure this exists for is intermittent and unattended: a run can go
    twenty minutes before it stops, and by the time a person looks the useful
    moment has passed.  So the watch takes the regions itself, the instant the
    jiffy clock and the screen have both stood still long enough to mean it.

    A stalled jiffy clock alone is not a hang -- the KERNAL's serial routines
    run with interrupts off, so it stops for the length of every load.  The
    test is `--still` seconds with *nothing* moving, and the default is set
    well past the longest legitimate quiet stretch measured on this machine.
    """
    log = pathlib.Path(args.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.seconds
    last, since = None, time.time()
    with log.open("a") as sink:
        while time.time() < deadline:
            try:
                at = screen_address(rest)
                state = (hashlib.sha256(rest.readmem(at, 1000)).hexdigest()[:12],
                         jiffy(rest))
                bus = rest.readmem(0xDD00, 1)[0]
            except DeviceError as exc:
                sink.write(json.dumps({"t": time.strftime("%H:%M:%S"),
                                       "error": str(exc)}) + "\n")
                sink.flush()
                time.sleep(1.0)
                continue
            now = time.time()
            if state != last:
                last, since = state, now
            still = now - since
            sink.write(json.dumps({"t": time.strftime("%H:%M:%S"),
                                   "screen": state[0], "jiffy": state[1],
                                   "dd00": bus,
                                   "still": round(still, 1)}) + "\n")
            sink.flush()
            if still >= args.still:
                print(f"stopped for {still:.0f}s at {time.strftime('%T')}",
                      flush=True)
                args.out = args.capture
                args.note = (f"hangwatch: nothing moved for {still:.0f}s; "
                             f"$DD00 ${bus:02X}")
                cmd_regions(rest, args)
                raise SystemExit(6)
            time.sleep(args.interval)
    print("no stall within the window")


def cmd_alive(rest: Rest, args) -> None:
    """Is the jiffy clock advancing?  That is what says interrupts are on."""
    first = jiffy(rest)
    time.sleep(args.seconds)
    second = jiffy(rest)
    moved = second - first
    print(f"jiffy {first:06X} -> {second:06X}, {moved} ticks in "
          f"{args.seconds}s: " + ("running" if moved else "STOPPED"))
    raise SystemExit(0 if moved else 5)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host")
    parser.add_argument("--quiet", action="store_true", default=True)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("boot")
    p.add_argument("image")
    p.add_argument("--mode", default="readonly")
    p.set_defaults(fn=cmd_boot)

    p = sub.add_parser("mount")
    p.add_argument("image")
    p.add_argument("--mode", default="readwrite")
    p.set_defaults(fn=cmd_mount)

    sub.add_parser("drives").set_defaults(fn=cmd_drives)
    sub.add_parser("screen").set_defaults(fn=cmd_screen)

    p = sub.add_parser("keys")
    p.add_argument("text")
    p.add_argument("--wait", action="store_true")
    p.add_argument("--timeout", type=float, default=3.0)
    p.add_argument("--gap", type=float, default=0.3)
    p.set_defaults(fn=cmd_keys)

    p = sub.add_parser("probe")
    p.add_argument("key")
    p.add_argument("--timeout", type=float, default=3.0)
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("wait")
    p.add_argument("--contains")
    p.add_argument("--still", type=float)
    p.add_argument("--timeout", type=float, default=180.0)
    p.add_argument("--interval", type=float, default=2.0)
    p.set_defaults(fn=cmd_wait)

    p = sub.add_parser("burst")
    p.add_argument("--out", required=True)
    p.add_argument("--seconds", type=float, default=20.0)
    p.set_defaults(fn=cmd_burst)

    p = sub.add_parser("regions")
    p.add_argument("--out", required=True)
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_regions)

    p = sub.add_parser("monitor")
    p.add_argument("--log", required=True)
    p.add_argument("--seconds", type=float, default=600.0)
    p.add_argument("--interval", type=float, default=3.0)
    p.add_argument("--stop-after", type=float, default=0.0,
                   help="return once nothing has changed for this many seconds")
    p.add_argument("--echo", action="store_true")
    p.set_defaults(fn=cmd_monitor)

    p = sub.add_parser("hangwatch")
    p.add_argument("--log", required=True)
    p.add_argument("--capture", required=True)
    p.add_argument("--still", type=float, default=45.0)
    p.add_argument("--seconds", type=float, default=1800.0)
    p.add_argument("--interval", type=float, default=3.0)
    p.set_defaults(fn=cmd_hangwatch)

    p = sub.add_parser("alive")
    p.add_argument("--seconds", type=float, default=5.0)
    p.set_defaults(fn=cmd_alive)

    args = parser.parse_args(argv)
    rest = Rest(find_host(args.host), verbose=not args.quiet)
    args.fn(rest, args)


if __name__ == "__main__":
    main()

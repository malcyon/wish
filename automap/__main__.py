"""Open the live map beside a running game.

    python -m automap                      attach to a running emulator
    python -m automap --area GEO00         skip identification
    python -m automap --svg GEO00 out.svg  render one map offline, no emulator

The emulator is not launched from here. Start it with `tools/porlaunch.sh` (or
the usual wrapper with POR_DEBUG=1) so the binary monitor is listening, then run
this. Attaching to something already running is deliberate: VICE serves one
text-monitor connection per run, and a second emulator would fight the first
over the monitor port.
"""

from __future__ import annotations

import argparse
import glob
import os
import pathlib
import sys

from por.geo import load_geo_files

from .paths import find_disks, vice_settings_hint
from .state import Automapper
from .target import NotConnected, ViceTarget, monitor_listening


def default_disks() -> str:
    """Where the game disks are. $POR_DISKS wins; otherwise go looking.

    There is deliberately no absolute default -- this used to hard-code one
    developer's home directory, which is no use to anybody else and does not
    exist on Windows at all.
    """
    found = find_disks()
    return str(found) if found else str(pathlib.Path.cwd())


def load_maps(disks: str | None = None) -> dict:
    """Every GEO file across the game disks, first copy wins."""
    disks = disks or default_disks()
    found: dict = {}
    for pattern in ("POOL*.D64", "POOL*.d64"):
        for path in sorted(glob.glob(os.path.join(disks, pattern))):
            for name, geo in load_geo_files(path).items():
                found.setdefault(name, geo)
    return found


def forget(area: str) -> int:
    """Drop remembered squares, keeping any notes.

    Wanted after a bug put squares on the wrong map: an early version recorded
    the new area's positions against the old one for a second or two after
    crossing a boundary, so slums coordinates ended up drawn on New Phlan.
    """
    import json

    from .state import data_dir

    files = sorted(data_dir().glob("*.json"))
    if area.upper() != "ALL":
        files = [f for f in files if f.stem.upper() == area.upper()]
        if not files:
            print(f"nothing remembered for {area}", file=sys.stderr)
            return 1
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dropped = len(payload.get("seen", []))
        payload["seen"] = []
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        kept = len(payload.get("notes", {}))
        print(f"{path.stem}: forgot {dropped} squares"
              + (f", kept {kept} note(s)" if kept else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", help="force a GEO name instead of identifying it")
    ap.add_argument("--disks", help="where the POOL*.D64 live "
                    "(default: $POR_DISKS, else searched for)")
    ap.add_argument("--interval", type=int,
                    help="poll interval in ms (default: remembered, else 200)")
    ap.add_argument("--forget", metavar="AREA",
                    help="clear remembered squares for one area (or ALL), then "
                         "exit. Notes are kept")
    ap.add_argument("--svg", nargs=2, metavar=("GEO", "OUT"),
                    help="render one map to SVG and exit; no emulator needed")
    args = ap.parse_args(argv)

    disks = args.disks or default_disks()
    maps = load_maps(disks)
    if not maps:
        print(f"no POOL*.D64 game disks under {disks}.\n"
              "Point --disks or $POR_DISKS at the directory holding them.",
              file=sys.stderr)
        return 1

    if args.forget:
        return forget(args.forget)

    if args.svg:
        from .render import to_svg
        name, out = args.svg
        if name.upper() not in maps:
            print(f"no map named {name}", file=sys.stderr)
            return 1
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(to_svg(maps[name.upper()]))
        print(f"{name.upper()} -> {out}")
        return 0

    # The window opens whether or not the game is running. Waiting for VICE,
    # and waiting for a save to be loaded, are ordinary states -- refusing to
    # start because the emulator is not up yet would be the wrong shape for
    # something you leave open beside the game.
    target = None
    if monitor_listening():
        try:
            target = ViceTarget()
        except NotConnected as exc:
            print(f"could not attach: {exc}", file=sys.stderr)
    else:
        print("no emulator yet - the map will open and wait for one.\n"
              f"Enable VICE's binary monitor on 127.0.0.1:6502 in "
              f"{vice_settings_hint()}, or launch VICE with\n"
              "  -binarymonitor -binarymonitoraddress 127.0.0.1:6502",
              file=sys.stderr)

    mapper = Automapper(target, maps, area=args.area)

    from .window import run
    return run(mapper, args.interval, connect=ViceTarget)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Load a prepared slot into an Amiga Pool of Radiance that `acceptance.py boot` started.

`acceptance.py boot` returns with no key pressed, while the AmigaDOS window is
still starting the game. This presses each key of the load only on a screen a
`guards_pool.json` guard recognises: it waits through the start for the code
wheel and the title (`poolremove.load_slot`), loads the manifest's
`loaded_letter`, and checks the party's square and names in memory against the
manifest's `state_a` and `names_a`. The game is left running at its world
screen for `fasttravelrun.py` and `amigadrive.py` under the same holder; the
lane is not halted.

    tools/amiga/poolload.py --manifest PREPARE.json --holder H --out DIR

OUT/load.json records every guarded screen, every key, the square and names
read and the verdict; the exit status is 0 only when the loaded party is the
manifest's.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from collections.abc import Callable
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import poolremove  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest  # noqa: E402

#: Seconds from the start of the run to the loaded world screen: the title wait and the four keys.
BUDGET = 900.0


def _fold(name: str) -> str:
    """A name as compared: the game's save drops the space that the loaded slot keeps."""
    return name.replace(" ", "").casefold()


def guard_file(out: pathlib.Path, extra: pathlib.Path | None) -> pathlib.Path:
    """`guards_pool.json`'s rules, with `extra`'s on top, as the file `PixelGuards` reads."""
    rules = dict(json.loads(poolremove.GUARDS.read_text())["guards"])
    if extra is not None:
        rules.update(json.loads(extra.read_text()))
    path = out / "guards.json"
    path.write_text(json.dumps(rules, indent=1, sort_keys=True))
    return path


def run(args: argparse.Namespace, *, guest: Any = None,
        live_factory: Callable[[str], Any] = poolremove.Live) -> dict:
    """Load the slot on the running machine and check the party; never halts the lane."""
    manifest = json.loads(args.manifest.read_text())
    poolremove.require(manifest.get("title") == "pool", "the manifest is not a Pool of Radiance run")
    expect = poolremove.manifest_place(manifest)
    poolremove.require(not args.out.exists(), f"the output folder {args.out} already exists")
    args.out.mkdir(parents=True)
    guest = guest or WinGuest()
    # The lane is the caller's claim; screenshots need its holder named.
    guest.holder = args.holder
    guards = poolremove.PixelGuards(guard_file(args.out, args.guards))
    screens = poolremove.Screens(guest, args.holder, args.out / "screens", guards,
                                 time.monotonic() + args.budget)
    receipt: dict[str, Any] = {"manifest": str(args.manifest.resolve()), "holder": args.holder,
                               "letter": manifest["loaded_letter"], "expect": list(expect),
                               "success": False}
    try:
        poolremove.load_slot(screens, manifest)
        live = live_factory(args.holder)
        place = live.place()
        names = [name for name, _address, _record in live.members()]
        receipt["loaded"] = {"place": None if place is None else list(place), "names": names}
        poolremove.require(place == expect, f"the party stands at {place}, not at {expect}")
        poolremove.require([_fold(n) for n in names] == [_fold(n) for n in manifest["names_a"]],
                           "the loaded party is not the slot's")
        receipt["success"] = True
    except RouteError as exc:
        receipt["error"] = str(exc)
    finally:
        receipt["screens"] = screens.events
        poolremove.write_json(args.out / "load.json", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=pathlib.Path, required=True,
                        help="the prepare.json the lane was booted from")
    parser.add_argument("--holder", required=True, help="the lane claim `acceptance.py boot` made")
    parser.add_argument("--out", type=pathlib.Path, required=True,
                        help="a new folder for load.json and the guarded screens")
    parser.add_argument("--guards", type=pathlib.Path, default=None,
                        help="further guard rules, added to guards_pool.json's")
    parser.add_argument("--budget", type=float, default=BUDGET,
                        help="seconds from the start to the loaded world screen")
    args = parser.parse_args(argv)
    receipt = run(args)
    print(json.dumps({key: receipt.get(key) for key in ("success", "loaded", "error")}))
    return 0 if receipt["success"] else 1


if __name__ == "__main__":
    sys.exit(main())

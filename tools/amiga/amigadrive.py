#!/usr/bin/env python3
"""Type at an Amiga game running under WinUAE in the Windows VM, from Linux.

`tools/amiga/winuae.ps1 press <hex raw code>` sends one Amiga key down and up
over the emulator's own pipe (`CFG KEY_RAW_DOWN` / `KEY_RAW_UP`), and
`winuae.ps1 shot` takes the emulator's own screenshot (`DBG sc`) over the same
pipe.  Neither raises a window, takes the focus or looks at the Windows
desktop, so another copy of WinUAE on the same desktop is not disturbed.  Every
call is an ssh round trip.  Driving a Gold Box menu is dozens of keystrokes
("LOAD SAVED GAME" is `L`, a path, a RETURN and a slot letter), so the thing
that was going to be retyped every session is the name-to-key table
(`tools/amiga/amigakeys.py`) and the waiting.

    tools/amiga/amigadrive.py --holder wish109-por keys RET L S A V E SLASH RET
    tools/amiga/amigadrive.py --holder wish109-por keys NP8 NP4 NP8   # walk, turn, walk
    tools/amiga/amigadrive.py --holder wish109-por shot picker.png
    tools/amiga/amigadrive.py --holder wish109-por snapshot before-walk
    tools/amiga/amigadrive.py --holder wish109-por restore before-walk
    tools/amiga/amigadrive.py --holder wish109-por discard_snapshot before-walk
    tools/amiga/amigadrive.py --holder wish109-por insert 0 C:/Amiga/Disks/disk2.adf --sha256 HASH

`shot` writes WinUAE's frame unchanged (752x574); `screens.canonical` cuts the
Amiga screen out of it.  The guest verb resets WinUAE's screenshot counter after
each shot, so a long run stays far below the 999 files a process would otherwise
write; if the limit is reached anyway, the shot fails and says so.

`snapshot`, `restore` and `discard_snapshot` save and put back the whole
running machine through WinUAE's own pipe (`automap.amiga.WinuaePipe`), with
no window, key or dialog; the state files stay on the guest under
`C:\\Amiga\\States\\<holder>`.

`insert DRIVE REMOTE --sha256 H` puts a disk already on the guest (the path
`acceptance.py boot` prints) into DF0 or DF1 of the running machine through
`WinuaePipe.insert_floppy`, and prints the receipt as JSON.

`--holder` is the lane claim `winuae.ps1` enforces, and it is required: every
call this makes is blocked without it.  Take the claim yourself before the
first call and release it at the end -- this script does not, deliberately,
because a claim that ends with the process that took it cannot be handed
between the several runs one experiment needs.

Nothing here opens a window on the host.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from automap.amiga import FloppyError, SnapshotError, WinuaePipe  # noqa: E402
from tools.amiga import amigakeys, winvmguest  # noqa: E402

#: The most screenshots one WinUAE process writes unless its counter is reset;
#: `winuae.ps1 shot` resets it after each shot, and this is the backstop.
SHOT_LIMIT = 999
_SHOT_OK = re.compile(r"^ok shot pid=(\d+) counter=(\d+) ms=(\d+)$", re.MULTILINE)

PS = ("powershell -NoProfile -ExecutionPolicy Bypass -File "
      r"C:\Amiga\winuae.ps1")


def _winvm(*args: str, timeout: int = 180) -> str:
    """Run `winvm`, with the options that stop ssh asking a human anything.

    `winvm` sets `BatchMode` and `SSH_ASKPASS_REQUIRE` itself; setting the
    second one here as well costs nothing and means a caller who has exported
    neither still cannot make ssh reach for a dialog.  A prompt an agent
    cannot answer is a credential dialog on somebody's desktop, not a pause.
    """
    env = dict(os.environ, SSH_ASKPASS_REQUIRE="never")
    proc = subprocess.run(
        ["winvm", *args], capture_output=True, text=True, timeout=timeout,
        env=env)
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        raise SystemExit(f"winvm {' '.join(args)} failed:\n{out}")
    return out


def press(holder: str, name: str, settle: float) -> str:
    """One keystroke into the emulator, named rather than in hex."""
    try:
        key = amigakeys.lookup(name)
    except KeyError:
        raise SystemExit(f"'{name.upper()}' is not a key this knows; "
                         f"names are {', '.join(sorted(amigakeys.KEYS))}") from None
    if key.amiga is None:
        raise SystemExit(f"'{key.name}' is an emulator key ({key.host}), not an Amiga key")
    try:
        out = _winvm("ssh", f"{PS} press {key.amiga:02X} -Holder {holder}")
    except subprocess.TimeoutExpired:
        raise SystemExit(f"Key {key.name} was not pressed: winvm timed out") from None
    # Anchored, because `winuae.ps1` anchors its own reply check
    # (`$r -notmatch '^ok'`) and a substring test would read any future
    # failure message containing "ok" -- "unlocked", "broken" -- as a
    # keystroke that landed. This script exists to decide exactly that.
    if not out.startswith("ok"):
        raise SystemExit(f"Key {key.name} was not pressed: {out}")
    time.sleep(settle)
    return out


class ShotError(RuntimeError):
    """WinUAE's screenshot did not come back."""


class ShotTimeout(ShotError):
    """The `winvm ssh` call for the screenshot hit its time limit; the emulator may be fine."""


#: Per holder: the counter WinUAE reported with its last shot.
_last_counter: dict[str, int] = {}


def shot(holder: str, out: pathlib.Path, run: Callable[..., str] | None = None,
         timeout: float = 30.0) -> dict[str, int]:
    """WinUAE's own frame, unchanged, written to `out`; returns `pid`, `counter` and `ms`.

    `run(*winvm_args, timeout=...)` returns the guest's output and defaults to
    `winvm`.  `ShotError` carries the guest's `fail` line, or says the 999-shot
    limit is spent; `ShotTimeout` says the call ran out of time.
    """
    run = run or (lambda *args, timeout: _winvm(*args, timeout=int(timeout) + 1))
    counter = _last_counter.get(holder, 0)
    try:
        text = run("ssh", f"{PS} shot -Holder {holder}", timeout=timeout)
        found = _SHOT_OK.search(text)
        png = winvmguest.decode_shot(text) if found else None
    except (SystemExit, RuntimeError, subprocess.TimeoutExpired) as exc:
        text, found, png = str(exc), None, None
        timed_out = isinstance(exc, subprocess.TimeoutExpired) or isinstance(
            exc.__cause__, subprocess.TimeoutExpired)
    else:
        timed_out = False
    if png is None:
        if timed_out:
            raise ShotTimeout(f"winuae.ps1 shot returned {text[:200]!r}")
        if "999 screenshots" in text or ("wrote no file" in text and counter >= SHOT_LIMIT):
            raise ShotError(f"WinUAE has written its {SHOT_LIMIT} screenshots for this emulator "
                            "process; restart the run")
        failure = re.search(r"\bfail [^\n]*", text)
        raise ShotError(failure.group(0) if failure
                        else f"winuae.ps1 shot returned {text[:200]!r}")
    pid, counter, ms = (int(n) for n in found.groups())
    _last_counter[holder] = counter
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    return {"pid": pid, "counter": counter, "ms": ms}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holder", required=True,
                        help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--settle", type=float, default=1.5,
                        help="seconds to wait after each key (default 1.5)")
    sub = parser.add_subparsers(dest="command", required=True)
    keys = sub.add_parser("keys", help="press keys in order")
    keys.add_argument("names", nargs="+")
    shot_cmd = sub.add_parser("shot", help="save WinUAE's own screenshot")
    shot_cmd.add_argument("path")
    for verb, text in (("snapshot", "save the whole machine under a name"),
                       ("restore", "put the machine back as a snapshot left it"),
                       ("discard_snapshot", "delete a snapshot")):
        sub.add_parser(verb, help=text).add_argument("name")
    insert = sub.add_parser("insert", help="put a staged disk into a drive")
    insert.add_argument("drive", type=int, choices=(0, 1))
    insert.add_argument("remote", help="the guest path `acceptance.py boot` printed")
    insert.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)

    if args.command == "keys":
        for name in args.names:
            print(f"{name}: {press(args.holder, name, args.settle)}")
    elif args.command == "shot":
        try:
            info = shot(args.holder, pathlib.Path(args.path))
        except ShotError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"{args.path} pid={info['pid']} counter={info['counter']}")
    elif args.command == "insert":
        try:
            receipt = WinuaePipe().insert_floppy(
                args.drive, args.remote.replace("/", "\\"), args.holder, args.sha256)
        except (FloppyError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(receipt.as_dict()))
    else:
        pipe = WinuaePipe()
        try:
            receipt = getattr(pipe, args.command)(args.name, args.holder)
        except (SnapshotError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        print(str(receipt))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Type at an Amiga game running under WinUAE in the Windows VM, from Linux.

`tools/winuae.ps1 key <hex VK>` presses exactly one key per call, and every
call is an ssh round trip through a scheduled task -- about two seconds.
Driving a Gold Box menu is dozens of keystrokes ("LOAD SAVED GAME" is `L`, a
path, a RETURN and a slot letter), so the thing that was going to be retyped
every session is the name-to-virtual-key table and the waiting.

    tools/amigadrive.py --holder wish109-por keys RET L S A V E SLASH RET
    tools/amigadrive.py --holder wish109-por shot work/109/picker.png

`--holder` is the lane claim `winuae.ps1` enforces, and it is required: every
call this makes is refused without it.  Take the claim yourself before the
first call and release it at the end -- this script does not, deliberately,
because a claim that ends with the process that took it cannot be handed
between the several runs one experiment needs.

Nothing here opens a window on the host: `winvm shot` grabs the guest's own
screen through libvirt, and every key goes in through the guest's session 1.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

#: The virtual-key codes a Gold Box title needs, by a name that can be typed
#: on a command line.  Letters and digits are their ASCII codes on every
#: Windows layout; the punctuation is the OEM range, which is layout-dependent
#: and correct for the US layout the guest runs.
KEYS: dict[str, int] = {
    "RET": 0x0D, "RETURN": 0x0D, "ENTER": 0x0D,
    "ESC": 0x1B, "SPACE": 0x20, "BACK": 0x08, "TAB": 0x09,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "F11": 0x7A,
    "SLASH": 0xBF, "COLON": 0xBA, "PERIOD": 0xBE, "COMMA": 0xBC,
    "MINUS": 0xBD,
}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    KEYS.setdefault(_c, ord(_c))

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
    code = KEYS.get(name.upper())
    if code is None:
        raise SystemExit(f"'{name}' is not a key this knows; "
                         f"names are {', '.join(sorted(KEYS))}")
    out = _winvm("ssh", f"{PS} key {code:02X} -Holder {holder}")
    # Anchored, because `winuae.ps1` anchors its own reply check
    # (`$r -notmatch '^ok'`) and a substring test would read any future
    # failure message containing "ok" -- "unlocked", "broken" -- as a
    # keystroke that landed. This script exists to decide exactly that.
    if not out.startswith("ok"):
        raise SystemExit(f"Key {name} was not pressed: {out}")
    time.sleep(settle)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holder", required=True,
                        help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--settle", type=float, default=1.5,
                        help="seconds to wait after each key (default 1.5)")
    sub = parser.add_subparsers(dest="command", required=True)
    keys = sub.add_parser("keys", help="press keys in order")
    keys.add_argument("names", nargs="+")
    shot = sub.add_parser("shot", help="save the guest's screen")
    shot.add_argument("path")
    args = parser.parse_args(argv)

    if args.command == "keys":
        for name in args.names:
            print(f"{name}: {press(args.holder, name, args.settle)}")
    elif args.command == "shot":
        print(_winvm("shot", args.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

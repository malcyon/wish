#!/usr/bin/env python3
"""Save from camp repeatedly in Amiga Silver Blades, and stop on the first
rule-book copy-protection screen.

`tools/amiga/amigabladesjournal.py` answers the journal half of Silver Blades'
copy-protection question -- the one `BEGIN ADVENTURING` asks -- but the other
20 of its 50 challenges come from the printed rule book instead, and
`#449 (The journal reader's rule-book half has never been read off a screen,
so 20 of its 50 challenges are untested live)`'s own research says those are
asked only when the party **saves from camp for the thirtieth time**, never
at the adventuring prompt. Nothing rebooted could ever have found one.

    tools/amiga/amigacampsave.py --holder wish449 --adf party.adf --max-saves 5

Screenshots go under `scratch.scratch_dir("amigacampsave", "run")` unless
`--out` says otherwise.

What it does: claims the WinUAE lane, boots the disk, loads the party named by
`--slot` and answers the journal challenge `BEGIN ADVENTURING` asks with
`amigabladesjournal.answer`, then repeats `ENCAMP > SAVE > <slot> > RETURN`
--waiting with `tools/amiga/winvmsettle.py` after every keystroke, because a key
pressed while the disk is writing is swallowed -- up to `--max-saves` times.
After every save it tests the settled screen with
`amigabladesjournal.fit_grid(text_bands(...))`, which is `None` on every
screen but a challenge. On a challenge it keeps the capture, answers it with
`amigabladesjournal.answer`, and reports where the confirming screenshot went
rather than reading its text -- watch it by eye for `Please re-boot your
system.`, which means the interrupted save failed.

**Never opens the player's own disk image.** `--adf` must already be a scratch
copy; `stage()` below makes one and is how `main()` gets there.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from tools.amiga import amigabladesjournal as journal  # noqa: E402
from tools.amiga import amigadrive, winvmsettle  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: `docs/124-amiga-port.md` §1.11a: the whole route from a cold boot to a
#: loaded party, one first-letter menu pick at a time. `B` (BEGIN ADVENTURING)
#: is not here -- it draws the journal challenge, so `journal.answer` handles
#: it separately, after settling.
BOOT_KEYS = ("RET", "RET", "P", "L")

#: `docs/124-amiga-port.md` §1.11 and §1.11a: `E` ENCAMP, `S` SAVE, the slot
#: letter, RETURN. `N` answers the `EXIT GAME  YES  NO` prompt that follows an
#: ordinary save, to stay in the world rather than quitting to Workbench --
#: there is no route from `YES` back to the party menu on this title.
CAMP_SAVE_KEYS = ("E", "S")
STAY_IN_GAME = "N"

#: Where WinUAE finds a disk staged for this run. Never the player's own copy.
GUEST_DISK_DIR = "C:/Amiga/Disks/issue449"

#: The template `winuae.ps1 start` is pointed at, with `floppy0=` rewritten to
#: the staged copy.
CONFIG_TEMPLATE = HERE / "goldbox-a500.uae"


def scratch_copy(source: pathlib.Path) -> pathlib.Path:
    """A private copy of `source`, so this tool never opens the original."""
    out = scratch.ensure(scratch.scratch_dir("amigacampsave")) / source.name
    shutil.copy(source, out)
    return out


def stage(local_adf: pathlib.Path, host: str | None = None) -> str:
    """Copy `local_adf` onto the Windows guest, and return its remote path."""
    argv = ["winvm"] + (["--host", host] if host else []) + \
        ["put", str(local_adf), GUEST_DISK_DIR + "/"]
    subprocess.run(argv, check=True, capture_output=True, text=True)
    return f"{GUEST_DISK_DIR}/{local_adf.name}"


def build_config(remote_floppy0: str) -> pathlib.Path:
    """A local copy of the checked-in template, with `floppy0=` replaced.

    `floppy1=` is left as the template's own value: Silver Blades' second disk
    is not this run's business, and a config `winuae.ps1 start` was never
    asked to load is not this tool's to invent.
    """
    remote_windows = remote_floppy0.replace("/", "\\")
    lines = []
    for line in CONFIG_TEMPLATE.read_text().splitlines():
        if line.startswith("floppy0="):
            line = f"floppy0={remote_windows}"
        lines.append(line)
    out = scratch.ensure(scratch.scratch_dir("amigacampsave")) / "issue449.uae"
    out.write_text("\n".join(lines) + "\n")
    return out


def camp_save_loop(holder: str, adf: pathlib.Path, slot: str, max_saves: int,
                   out_dir: pathlib.Path, key_settle: float = 1.0,
                   settle_fn=None, capture=None, press=None):
    """`ENCAMP > SAVE > slot > RETURN`, up to `max_saves` times.

    Returns `(attempt, path)` of the preserved challenge screen, or
    `(None, None)` when `max_saves` saves passed with no challenge.
    `settle_fn`, `capture` and `press` are `journal.answer`'s own hooks, so
    the loop can be exercised without a live WinUAE -- `settle_fn(path)`
    defaults to `winvmsettle.settle`.
    """
    if press is None:
        def press(key):
            amigadrive.press(holder, key, key_settle)
    if settle_fn is None:
        def settle_fn(path):
            return winvmsettle.settle(path)
    scratch.ensure(out_dir)
    from PIL import Image  # noqa: PLC0415

    for attempt in range(1, max_saves + 1):
        for key in (*CAMP_SAVE_KEYS, slot, "RET"):
            press(key)
        shot = out_dir / f"save{attempt:02d}.png"
        settle_fn(shot)
        image = Image.open(shot).convert("RGB")
        if journal.fit_grid(journal.text_bands(image)) is not None:
            preserved = out_dir / f"save{attempt:02d}-challenge.png"
            shutil.copy(shot, preserved)
            print(f"challenge screen on save {attempt}: {preserved}")
            journal.answer(holder, key_settle, adf, capture=capture, press=press)
            after = out_dir / f"save{attempt:02d}-after-answer.png"
            settle_fn(after)
            print(f"post-answer screen saved to {after} -- check it by eye "
                  f"for 'Please re-boot your system.', which means the "
                  f"interrupted save failed")
            return attempt, preserved
        press(STAY_IN_GAME)
        print(f"save {attempt}: no challenge on screen")
    print(f"no challenge screen in {max_saves} saves")
    return None, None


def boot_and_load(holder: str, adf: pathlib.Path, slot: str,
                  out_dir: pathlib.Path, key_settle: float = 1.0):
    """Credits to a loaded party, answering the journal challenge `B` asks."""
    scratch.ensure(out_dir)
    for key in BOOT_KEYS:
        amigadrive.press(holder, key, key_settle)
    winvmsettle.settle(out_dir / "boot-load-prompt.png")
    amigadrive.press(holder, slot, key_settle)
    amigadrive.press(holder, "B", key_settle)
    winvmsettle.settle(out_dir / "boot-begin-adventuring.png")
    journal.answer(holder, key_settle, adf)
    winvmsettle.settle(out_dir / "boot-party-loaded.png")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--holder", required=True,
                        help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--adf", required=True,
                        help="a scratch copy of Silver Blades side A holding "
                             "the party to load; never the player's own image")
    parser.add_argument("--slot", default="A",
                        help="the SAVE drawer letter the party is loaded from "
                             "and saved back to (default A)")
    parser.add_argument("--max-saves", type=int, default=5,
                        help="stop after this many camp saves with no "
                             "challenge screen (default 5)")
    parser.add_argument("--out", default=None,
                        help="where to keep the screenshots (default "
                             "the scratch directory for this tool)")
    parser.add_argument("--settle", type=float, default=1.0,
                        help="seconds after each keystroke before the next "
                             "(default 1)")
    parser.add_argument("--skip-boot", action="store_true",
                        help="the party is already loaded and standing at "
                             "camp; go straight to the save loop")
    args = parser.parse_args(argv)

    adf = pathlib.Path(args.adf).expanduser()
    if not adf.is_file():
        raise SystemExit(f"{adf} is not a file")
    out_dir = pathlib.Path(args.out) if args.out else \
        scratch.scratch_dir("amigacampsave", "run")

    if not args.skip_boot:
        boot_and_load(args.holder, adf, args.slot, out_dir, args.settle)
    attempt, shot = camp_save_loop(args.holder, adf, args.slot,
                                   args.max_saves, out_dir, args.settle)
    if attempt is None:
        return 1
    print(f"rule-book challenge found after {attempt} save(s): {shot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

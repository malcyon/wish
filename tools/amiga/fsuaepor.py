#!/usr/bin/env python3
"""Drive Amiga Pool of Radiance in the stock FS-UAE inside an instance-pool slot.

WinUAE lives in the Windows guest, which an agent inside the Ubuntu sandbox
has no key for.  The stock `fs-uae` here runs the same `/program`, so a
question about what the game does with a record is answered by it as well:

    fsuaepor.py stage --out DIR --from ADF --slot C --name 1='MARY\\xffSUE'
    tools/registry/instance.py claim --game amiga-por --note NOTE -- \\
        .venv/bin/python tools/amiga/fsuaepor.py serve --run DIR
    fsuaepor.py keys --display :10 l s a v e slash Return c
    fsuaepor.py shot --display :10 DIR/s01.png
    fsuaepor.py names DIR/por1.adf

`stage` copies a disk 1 into DIR, puts disk 2 beside it from the registry, and
overwrites the name field of chosen records in one slot -- nothing else in the
record changes.  `serve` is what the pool slot runs: a private `Xvfb` on the
slot's display and `fs-uae` inside it, silent, with the floppies written back
in place so the engine's saves land in `DIR/por1.adf`; `--floppy` names other
images in DIR, DF0 first, for another title.  It stays in the slot's
process group, so the pool's teardown ends both.  `keys` and `shot` reach that
display with `xdotool` and `import`; `names` prints every slot's names as the
engine left them, to the first NUL and past it.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import signal
import subprocess
import sys
import time
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from automap import gamedisks  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402

#: The 16-byte name field at the start of a 288-byte `CHRDAT<L><n>.sav`.
NAME_BYTES = 16

#: The Kickstart the Gold Box titles boot on, as `goldbox-a500.uae` names it.
KICKSTART = "kickstart-1.3.rom"


def parse_name(text: str) -> bytes:
    """`'MARY\\xffSUE'` as the bytes it names: Python escapes, then Latin-1."""
    return text.encode("latin-1").decode("unicode_escape").encode("latin-1")


def set_name(record: bytes, name: bytes) -> bytes:
    """`record` with its name field holding `name`, a NUL, and zeroes.

    Zeroes behind the terminator are what `goldbox.amiga_por` writes, so the
    one thing that differs from a converted record is the name itself.
    """
    if len(name) >= NAME_BYTES:
        raise ValueError(f"{len(name)} bytes leaves no room for the NUL in a "
                         f"{NAME_BYTES}-byte field")
    field = name + bytes(NAME_BYTES - len(name))
    return field + bytes(record[NAME_BYTES:])


def name_of(record: bytes) -> tuple[bytes, bytes]:
    """The name to its first NUL, and the whole 16-byte field."""
    field = bytes(record[:NAME_BYTES])
    return field.split(b"\0", 1)[0], field


# --- Reading a capture -----------------------------------------------------

#: Where the adventure screen's party panel draws its first three rows, and the
#: character sheet its name, in a grab of `serve`'s 800x600 display: `(top,
#: bottom)` pixel rows and `(left, right)` columns.  Measured on the captures
#: in the `por-amiga-ff-names` specimen; a different window size moves them.
PANEL_ROWS = ((100, 116), (117, 133), (134, 150))
PANEL_COLUMNS = (343, 600)
SHEET_NAME_ROWS = (64, 82)
SHEET_NAME_COLUMNS = (79, 400)


def white_ink(pixel) -> bool:
    """The selected row's text, white on the green bar."""
    return pixel[0] > 150 and pixel[2] > 150


def green_ink(pixel) -> bool:
    """Every other row's text, and the sheet's name."""
    return pixel[1] > 100 and pixel[0] < 100 and pixel[2] < 100


def glyph_runs(image, rows: tuple[int, int], columns: tuple[int, int],
               ink) -> list[tuple[int, int]]:
    """Each horizontal stretch of columns holding ink anywhere in `rows`.

    `image` is anything with `getpixel((x, y))` returning RGB.  A run is
    `(first column, one past the last)`; glyphs that touch make one run.
    """
    top, bottom = rows
    left, right = columns
    runs, start = [], None
    for x in range(left, right + 1):
        on = x < right and any(ink(image.getpixel((x, y)))
                               for y in range(top, bottom))
        if on and start is None:
            start = x
        elif not on and start is not None:
            runs.append((start, x))
            start = None
    return runs


def blank_cells(runs: list[tuple[int, int]], pitch: float) -> list[int]:
    """How many whole character cells of nothing lie between each two runs.

    The gap between two glyphs in one word is a few pixels, well under half
    a cell, so it rounds to 0; a blank cell adds one pitch to the gap.
    """
    return [round((b[0] - a[1]) / pitch) for a, b in zip(runs, runs[1:])]


def _drawer(disk: AmigaDisk) -> str:
    from goldbox import amiga_savegame
    return amiga_savegame.por_save_drawer(disk)


def slot_names(disk: AmigaDisk) -> dict[str, list[tuple[bytes, bytes]]]:
    """Every `CHRDAT<L><n>.sav` on the disk, by slot letter, in file order."""
    drawer = _drawer(disk)
    out: dict[str, list[tuple[bytes, bytes]]] = {}
    for letter in "ABCDEFGHIJ":
        for n in range(1, 7):
            try:
                raw = disk.read_file(f"{drawer}/CHRDAT{letter}{n}.sav".lstrip("/"))
            except Exception:
                break
            out.setdefault(letter, []).append(name_of(raw))
    return out


def drop_slot(disk: AmigaDisk, letter: str) -> list[str]:
    """Remove one slot's files and its letter from the slot list, for room.

    A disk 1 with six slots on it has 18 blocks free, and the engine's save
    needs more: it puts `VOLUME POOLGAME IS FULL` on screen and stops.
    """
    from goldbox import amiga_savegame as sg
    drawer = _drawer(disk).lstrip("/")
    gone = []
    for entry in disk.entries(disk.lookup(drawer).block):
        stem = entry.name.split(".")[0]
        if stem in (f"savgam{letter}", ) or (
                stem.startswith(f"CHRDAT{letter}") and len(stem) == 8):
            disk.remove_file(f"{drawer}/{entry.name}")
            gone.append(entry.name)
    listed = [s for s in sg.read_slot_list(disk, drawer) if s != letter]
    disk.write_file(f"{drawer}/{sg.POR_SLOT_LIST_NAME}", sg.slot_list_bytes(listed))
    return sorted(gone)


def _disk2() -> bytes:
    """Disk 2 (`POOLDATA`) out of the registry's `amiga` entry, read-only."""
    from automap import gamedisks
    for root in gamedisks.candidates("amiga"):
        for z in sorted(root.glob("Pool*Radiance*.zip")):
            with zipfile.ZipFile(z) as zf:
                for member in zf.namelist():
                    data = zf.read(member)
                    try:
                        if AmigaDisk(data).volume_name == "POOLDATA":
                            return data
                    except Exception:
                        continue
    raise SystemExit("no Pool of Radiance disk 2 (POOLDATA) in the registry")


def stage(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    disk = AmigaDisk(pathlib.Path(args.source).read_bytes())
    drawer = _drawer(disk).lstrip("/")
    for letter in args.drop_slot or []:
        print(f"dropped slot {letter}: {', '.join(drop_slot(disk, letter))}")
    for spec in args.name or []:
        index, _, text = spec.partition("=")
        path = f"{drawer}/CHRDAT{args.slot}{int(index)}.sav"
        before = disk.read_file(path)
        after = set_name(before, parse_name(text))
        disk.write_file(path, after)
        print(f"{path}: {before[:NAME_BYTES].hex(' ')} -> "
              f"{after[:NAME_BYTES].hex(' ')}")
    disk.save(out / "por1.adf")
    (out / "por2.adf").write_bytes(_disk2())
    images = ["por1.adf", "por2.adf"]
    if args.poolsave:
        # Create New Character saves to `POOLSAVE:` until a path is typed at
        # LOAD SAVED GAME, and asks for the volume by name.
        AmigaDisk.blank("POOLSAVE").save(out / "poolsave.adf")
        images.append("poolsave.adf")
    for image in images:
        os.chmod(out / image, 0o644)
    print(f"staged {out / 'por1.adf'} and {out / 'por2.adf'}")
    return 0


def kickstart() -> pathlib.Path:
    for root in gamedisks.candidates("kickstarts"):
        if (root / KICKSTART).exists():
            return root / KICKSTART
    raise SystemExit(f"no {KICKSTART}; set $WISH_KICKSTARTS")


def serve(args) -> int:
    """Run Xvfb and fs-uae on the slot's display until either exits."""
    display = args.display or os.environ.get("POR_DISPLAY")
    if not display:
        raise SystemExit("no display: run under `instance.py claim --`")
    run = pathlib.Path(args.run).resolve()
    base = run / "base"
    base.mkdir(parents=True, exist_ok=True)
    xvfb = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "800x600x24", "-nolisten", "tcp"],
        stdout=(run / "xvfb.log").open("wb"), stderr=subprocess.STDOUT)
    time.sleep(2)
    env = dict(os.environ)
    for name in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
        env.pop(name, None)
    env.update(DISPLAY=display, SDL_AUDIODRIVER="dummy", ALSOFT_DRIVERS="null")
    images = ([run / name for name in args.floppy] if args.floppy else
              [run / name for name in ("por1.adf", "por2.adf", "poolsave.adf")
               if (run / name).exists()])
    floppies = [f"--floppy_drive_{i}={image}" for i, image in enumerate(images)]
    argv = ["fs-uae", f"--base_dir={base}", "--amiga_model=A500",
            f"--kickstart_file={kickstart()}",
            *floppies,
            "--writable_floppy_images=1", "--floppy_drive_speed=0",
            "--fullscreen=0", "--window_width=720", "--window_height=568",
            "--automatic_input_grab=0", "--initial_input_grab=0",
            "--volume=0", "--joystick_port_1=none"]
    emulator = subprocess.Popen(argv, env=env, cwd=str(run),
                                stdout=(run / "fs-uae.log").open("wb"),
                                stderr=subprocess.STDOUT)
    print(f"display {display}  xvfb {xvfb.pid}  fs-uae {emulator.pid}", flush=True)
    try:
        while emulator.poll() is None and xvfb.poll() is None:
            time.sleep(1)
    finally:
        for proc in (emulator, xvfb):
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
    return 0


def _xenv(display: str) -> dict[str, str]:
    return {"DISPLAY": display, "PATH": "/usr/bin:/bin"}


def keys(args) -> int:
    """Each key in turn to the FS-UAE window, focused first (SDL needs it)."""
    env = _xenv(args.display)
    found = subprocess.run(["xdotool", "search", "--name", "FS-UAE"], env=env,
                           capture_output=True, text=True, check=False).stdout.split()
    if not found:
        raise SystemExit(f"no FS-UAE window on {args.display}")
    for key in args.key:
        subprocess.run(["xdotool", "windowfocus", found[0]], env=env, check=False)
        subprocess.run(["xdotool", "keydown", key], env=env, check=True)
        time.sleep(args.hold)
        subprocess.run(["xdotool", "keyup", key], env=env, check=True)
        time.sleep(args.settle)
    return 0


def shot(args) -> int:
    subprocess.run(["import", "-display", args.display, "-window", "root",
                    str(args.path)], env=_xenv(args.display), check=True)
    print(args.path)
    return 0


def names(args) -> int:
    disk = AmigaDisk(pathlib.Path(args.adf).read_bytes())
    for letter, rows in slot_names(disk).items():
        for n, (name, field) in enumerate(rows, 1):
            print(f"{letter}{n}  {name.decode('latin-1')!r:20}  {field.hex(' ')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("stage", help="copy disk 1, patch names, add disk 2")
    p.add_argument("--from", dest="source", required=True, help="a disk 1 .adf, read-only")
    p.add_argument("--out", required=True)
    p.add_argument("--slot", default="C")
    p.add_argument("--name", action="append", help="N=NAME, Python escapes allowed")
    p.add_argument("--drop-slot", action="append", help="remove a slot to free blocks")
    p.add_argument("--poolsave", action="store_true",
                   help="also a blank POOLSAVE disk for DF2")
    p.set_defaults(func=stage)
    p = sub.add_parser("serve", help="Xvfb and fs-uae on the slot's display")
    p.add_argument("--run", required=True)
    p.add_argument("--display")
    p.add_argument("--floppy", action="append",
                   help="an image in --run for the next drive, DF0 first; "
                        "default por1.adf, por2.adf and poolsave.adf if staged")
    p.set_defaults(func=serve)
    p = sub.add_parser("keys", help="press xdotool keys, one at a time")
    p.add_argument("--display", required=True)
    p.add_argument("--settle", type=float, default=0.6)
    p.add_argument("--hold", type=float, default=0.12)
    p.add_argument("key", nargs="+")
    p.set_defaults(func=keys)
    p = sub.add_parser("shot", help="grab the slot's display as a PNG")
    p.add_argument("--display", required=True)
    p.add_argument("path")
    p.set_defaults(func=shot)
    p = sub.add_parser("names", help="every slot's names on a disk 1")
    p.add_argument("adf")
    p.set_defaults(func=names)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

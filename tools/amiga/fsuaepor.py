#!/usr/bin/env python3
"""Drive Amiga Pool of Radiance and Curse in the stock FS-UAE inside an instance-pool slot.

FS-UAE is a second emulator the Amiga tools can use alongside WinUAE: it runs
here, in a pool slot, and it runs the same `/program`, so a question about
what the game does with a record can be answered in either:

    fsuaepor.py stage --out DIR --from ADF --slot C --name 1='MARY\\xffSUE'
    tools/registry/instance.py claim --game amiga-por --note NOTE -- \\
        .venv/bin/python tools/amiga/fsuaepor.py serve --run DIR
    fsuaepor.py keys --display :10 l s a v e slash Return c
    fsuaepor.py shot --display :10 DIR/s01.png
    fsuaepor.py names DIR/por1.adf

Pools of Darkness looks for its disks in DF0 and DF1 only, so `serve` puts disk 1
there and disk 3 beside it when the run holds `pod1.adf`, and lists all three
in the swap list with `floppy_image_N`, an option name read from the fs-uae
3.1.66 binary's strings and untested until a boot proves it:

    fsuaepor.py pod-stage --out DIR --pc normal.pc --pc unconscious.pc
    tools/registry/instance.py claim --game amiga-pod --note NOTE -- \\
        .venv/bin/python tools/amiga/fsuaepor.py serve --run DIR
    fsuaepor.py pod-panel --display :10 --adf DIR/pod3.adf --out DIR/shots

`stage` copies a disk 1 into DIR, puts disk 2 beside it from the registry, and
overwrites the name field of chosen records in one slot -- nothing else in the
record changes.  `serve` is what the pool slot runs: a private `Xvfb` on the
slot's display and `fs-uae` inside it, silent, with the floppies written back
in place so the engine's saves land in `DIR/por1.adf`; `--floppy` names other
images in DIR, DF0 first, for another title.  It stays in the slot's
process group, so the pool's teardown ends both.  `keys` and `shot` reach that
display with `xdotool` and `import`; `names` prints every slot's names as the
engine left them, to the first NUL and past it.

Amiga Curse boots the same way from its own two disks, and asks its code
wheel before it will play:

    fsuaepor.py curse-stage --out DIR
    tools/registry/instance.py claim --game amiga-curse --note NOTE -- \\
        .venv/bin/python tools/amiga/fsuaepor.py serve --run DIR \\
        --floppy curse1.adf --floppy curse2.adf
    WHEELVENV/bin/python tools/amiga/fsuaepor.py wheel --display :10

`curse-stage` copies disks A and B out of the registry, writable, as
`curse1.adf` and `curse2.adf`.  `wheel` reads the challenge off the slot's
display with the private code-wheel repository's reader and types the answer,
printing only `answered` or `no challenge on screen`; the reader needs `numpy`,
which this project's environment does not have.  Serve Curse with `--window
704x556`, which draws each Amiga pixel exactly twice.  Even so the reader does
not yet accept a stock FS-UAE capture -- its rune match and prompt fit fall
short of its own thresholds -- so `wheel` prints `no challenge on screen` and
the title stops at the wheel.
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


#: Amiga Curse's game disks, by volume name, in drive order.
CURSE_VOLUMES = ("CurseA", "CurseB")


def curse_disks() -> list[bytes]:
    """Curse disks A and B out of the registry's `amiga` entry, read-only."""
    for root in gamedisks.candidates("amiga"):
        found: dict[str, bytes] = {}
        for adf in sorted(root.rglob("*.adf")):
            data = adf.read_bytes()
            try:
                volume = AmigaDisk(data).volume_name
            except Exception:
                continue
            if volume in CURSE_VOLUMES:
                found.setdefault(volume, data)
        if all(v in found for v in CURSE_VOLUMES):
            return [found[v] for v in CURSE_VOLUMES]
    raise SystemExit("no Amiga Curse disks (CurseA, CurseB) in the registry")


def curse_stage(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for n, data in enumerate(curse_disks(), 1):
        path = out / f"curse{n}.adf"
        path.write_bytes(data)
        os.chmod(path, 0o644)
        print(f"staged {path}")
    return 0


#: Amiga Pools of Darkness' game disks, by volume name, in drive order.
POD_VOLUMES = ("POD 1", "POD 2", "POD 3")

#: Where the picker's character files live on disk 3.
POD_SAVE_DRAWER = "Save"

#: What a `pod-stage` payload holds at these offsets: the name, the two status
#: bytes, and the in-party flag.
POD_NAME_AT = 0x060
POD_STATUS_AT = (0x05E, 0x05F)
POD_ACTIVE_AT = 0x184

#: The payload files `pod-panel` adds when `--payload` names none.
POD_PAYLOADS = ("normal.pc", "unconscious.pc", "outofparty.pc")


def pod_disks() -> list[bytes]:
    """Pools of Darkness disks 1, 2 and 3 out of the registry, read-only.

    The first container, in sorted order, holding all three volumes whose disk 1
    carries the same executable build the offset tools read.
    """
    from tools.amiga import amigasaves, podimportmap
    build = podimportmap.executable(quiet=True)
    containers: dict[str, dict[str, bytes]] = {}
    for label, data in amigasaves.images():
        try:
            volume = AmigaDisk(data).volume_name
        except Exception:
            continue
        if volume in POD_VOLUMES:
            containers.setdefault(label.split("!")[0], {}).setdefault(volume, data)
    for label in sorted(containers):
        found = containers[label]
        if not all(v in found for v in POD_VOLUMES):
            continue
        try:
            first = AmigaDisk(found[POD_VOLUMES[0]]).read_file(podimportmap.EXECUTABLE)
        except Exception:
            continue
        if first == build:
            return [found[v] for v in POD_VOLUMES]
    raise SystemExit("no Amiga Pools of Darkness disks (POD 1, POD 2, POD 3) "
                     "in the registry")


def picker_rows(disk: AmigaDisk) -> list[str]:
    """The `.pc` names in disk 3's `Save` drawer, in the picker's row order."""
    return [e.name for e in disk.entries(disk.lookup(POD_SAVE_DRAWER).block)
            if e.name.lower().endswith(".pc")]


def payload_line(row: int, name: str, record: bytes) -> str:
    """One line describing a staged payload: its row, name and state bytes."""
    inside = record[POD_NAME_AT:POD_NAME_AT + 16].split(b"\0", 1)[0]
    status = " ".join(f"{record[at]:02x}" for at in POD_STATUS_AT)
    return (f"row {row}  {name}  {inside.decode('latin-1')!r}  "
            f"0x5e/0x5f {status}  0x184 {record[POD_ACTIVE_AT]:02x}")


def stage_pod(disks: list[bytes], out: pathlib.Path,
              payloads: list[pathlib.Path]) -> list[str]:
    """Write the three disks into `out`; disk 3 keeps only `payloads` as `.pc`.

    Its `SavGam*` and `Vault*` files stay.  Returns one line per payload.
    """
    out.mkdir(parents=True, exist_ok=True)
    disk3 = AmigaDisk(disks[2])
    for name in picker_rows(disk3):
        disk3.remove_file(f"{POD_SAVE_DRAWER}/{name}")
    for path in payloads:
        disk3.write_file(f"{POD_SAVE_DRAWER}/{path.name}", path.read_bytes())
    disk3.save(out / "pod3.adf")
    (out / "pod1.adf").write_bytes(disks[0])
    (out / "pod2.adf").write_bytes(disks[1])
    for n in (1, 2, 3):
        os.chmod(out / f"pod{n}.adf", 0o644)
    rows = picker_rows(disk3)
    return [payload_line(rows.index(p.name) + 1, p.name, p.read_bytes())
            for p in payloads]


def pod_stage(args) -> int:
    out = pathlib.Path(args.out)
    for line in stage_pod(pod_disks(), out, [pathlib.Path(p) for p in args.pc]):
        print(line)
    print(f"staged {out / 'pod1.adf'}, {out / 'pod2.adf'} and {out / 'pod3.adf'}")
    return 0


def _wait(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.monotonic()


#: Where the title bar's letters are, measured on `serve`'s 800x600 `Xvfb` root
#: with the default `--window 720x568` and the window at the origin (there is
#: no window manager).  A different `--window` moves them.
BAR_ROWS = (415, 460)
#: The bar's letters are 971 cyan pixels in that band and the intro, credits
#: and version screens have none; 200 sits far from both.
BAR_INK_MIN = 200
#: Seconds between screenshots while waiting for the bar.
BAR_POLL = 2


def grab(display: str):
    """The display's root window as a Pillow image, with no file written."""
    import io

    from PIL import Image

    png = subprocess.run(["import", "-display", display, "-window", "root", "png:-"],
                         env=_xenv(display), check=True, capture_output=True).stdout
    return Image.open(io.BytesIO(png)).convert("RGB")


def title_bar_up(image) -> bool:
    """True when the `PLAY DEMO QUIT` bar's cyan letters are in the bar's band."""
    top, bottom = BAR_ROWS
    band = image.crop((0, top, image.width, min(bottom, image.height)))
    raw = band.tobytes()
    ink = sum(1 for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3])
              if r < 120 and g > 180 and b > 180)
    return ink >= BAR_INK_MIN


def panel_script(rows: list[tuple[int, str]], members: int, limit: float
                 ) -> list[tuple]:
    """The fixed Pools of Darkness key script, as `(kind, ...)` steps.

    `("title", limit)` waits for the title bar for at most `limit` seconds,
    `("key", name, settle)`, `("shot", label)` and `("played",)`, which stops
    the run when the screen did not change after the first `p`.
    `rows` are `(picker row, file name)` in ascending order.  The script never
    sends `Up`, never `y`, and never two `e` in a row: `Up` at the top of an
    FS-UAE menu then Return quits the emulator, and `e` on the party menu is
    EXIT FROM GAME.
    """
    steps: list[tuple] = [("title", limit),
                          ("key", "p", 4), ("played",), ("shot", "play"),
                          ("key", "a", 3), ("shot", "add-character"),
                          ("key", "p", 10), ("shot", "picker")]
    current = 1
    for row, name in rows:
        steps += [("key", "Down", 0.6)] * (row - current)
        current = row
        steps += [("shot", f"on-{name}"), ("key", "a", 4),
                  ("shot", f"added-{name}")]
    steps += [("key", "e", 3), ("shot", "panel")]
    for k in range(1, members + 1):
        if k > 1:
            steps.append(("key", "Down", 0.6))
        steps += [("shot", f"panel-{k}"), ("key", "v", 3),
                  ("shot", f"sheet-{k}"), ("key", "e", 3)]
    for home in ("Home", "End"):
        steps += [("key", home, 0.6), ("shot", f"panel-{home.lower()}"),
                  ("key", "v", 3), ("shot", f"sheet-{home.lower()}"),
                  ("key", "e", 3)]
    steps.append(("shot", "last"))
    return steps


def pod_panel(args) -> int:
    """Run the fixed key script on the slot's display, a shot at each checkpoint."""
    disk = AmigaDisk(pathlib.Path(args.adf).read_bytes())
    names = picker_rows(disk)
    wanted = args.payload or [n for n in POD_PAYLOADS if n in names] or names
    missing = [n for n in wanted if n not in names]
    if missing:
        raise SystemExit(f"{', '.join(missing)} not in {args.adf}; the picker's "
                         f"rows are {', '.join(names) or 'none'}")
    rows = sorted((names.index(n) + 1, n) for n in wanted)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    count = 0

    def take(label: str) -> None:
        nonlocal count
        count += 1
        shot(argparse.Namespace(display=args.display,
                                path=out / f"{count:02d}-{label}.png"))

    bar = None
    for step in panel_script(rows, len(rows), args.boot):
        if step[0] == "title":
            bar = _wait_for_bar(args.display, step[1], take)
        elif step[0] == "played":
            if grab(args.display).tobytes() == bar.tobytes():
                take("play-ignored")
                raise SystemExit("the title bar did not take p; no more keys sent")
        elif step[0] == "key":
            keys(argparse.Namespace(display=args.display, key=[step[1]],
                                    hold=0.12, settle=step[2]))
        else:
            take(step[1])
    return 0


def _wait_for_bar(display: str, limit: float, take):
    """Grab until two in a row show the title bar; stop with no key past `limit`."""
    start = _now()
    seen = False
    while True:
        image = grab(display)
        up = title_bar_up(image)
        if up and seen:
            print(f"title bar after {_now() - start:.0f} s")
            take("title")
            return image
        seen = up
        if _now() - start >= limit:
            take("no-title-bar")
            raise SystemExit(f"no title bar in {limit:g} s; no key sent")
        _wait(BAR_POLL)


def wheel(args) -> int:
    """Answer Curse's code wheel on the slot's display; print only the outcome.

    The same reader and arithmetic as `amigacursewheel.py`, which drives
    WinUAE; neither the challenge nor the answer is printed or kept.
    """
    import tempfile

    from tools.amiga import amigacursewheel
    screen, arithmetic = amigacursewheel._wheel_modules()
    assets = pathlib.Path(tempfile.mkdtemp(prefix="cursewheel-"))
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    grab = pathlib.Path(handle.name)
    try:
        # The reader loads the rune tiles and the font from a directory of its
        # own that the disks are unpacked into; point it at a private copy
        # read from the registry's disks rather than write into its tree.
        for disk, (drawer, name) in zip(curse_disks(), (("DISKA", "CURSE.FON"),
                                                        ("DISKB", "TILES.TLB"))):
            (assets / f"{drawer}_{name}").write_bytes(
                AmigaDisk(disk).read_file(f"{drawer}/{name}"))
        screen.EXE = assets
        subprocess.run(["import", "-display", args.display, "-window", "root",
                        str(grab)], env=_xenv(args.display), check=True)
        challenge = screen.read_challenge(
            amigacursewheel._to_reader_scale(grab, screen))
        if challenge is None:
            print("no challenge on screen")
            return 1
        character = arithmetic.answer_from_screen(
            challenge["box"], challenge["pattern"],
            challenge["espruar"], challenge["dethek"])
    finally:
        grab.unlink(missing_ok=True)
        for leftover in assets.iterdir():
            leftover.unlink()
        assets.rmdir()
    keys(argparse.Namespace(display=args.display, key=[character.lower(), "Return"],
                            hold=0.12, settle=args.settle))
    print("answered")
    return 0


def kickstart() -> pathlib.Path:
    for root in gamedisks.candidates("kickstarts"):
        if (root / KICKSTART).exists():
            return root / KICKSTART
    raise SystemExit(f"no {KICKSTART}; set $WISH_KICKSTARTS")


def default_images(run: pathlib.Path, floppy: list[str] | None = None,
                   swap: list[str] | None = None
                   ) -> tuple[list[pathlib.Path], list[pathlib.Path]]:
    """The images for the drives, DF0 first, and those only the swap list holds.

    Named floppies win.  A run holding `pod1.adf` is Pools of Darkness, whose
    engine looks for its disks in DF0 and DF1 and never DF2, so disk 3 takes
    DF1 and disk 2 waits in the swap list.  Otherwise whatever `stage` left in
    `run` is used.
    """
    swaps = [run / name for name in swap or []]
    if floppy:
        return [run / name for name in floppy], swaps
    if (run / "pod1.adf").exists():
        return [run / "pod1.adf", run / "pod3.adf"], swaps or [run / "pod2.adf"]
    return [run / name for name in ("por1.adf", "por2.adf", "poolsave.adf")
            if (run / name).exists()], swaps


def fsuae_argv(run: pathlib.Path, drives: list[pathlib.Path],
               swaps: list[pathlib.Path], window: str,
               kickstart_file: pathlib.Path) -> list[str]:
    """The `fs-uae` command line: no process is started here."""
    width, height = (int(n) for n in window.split("x"))
    floppies = [f"--floppy_drive_{i}={image}" for i, image in enumerate(drives)]
    # A swap list is only written when there is something to swap.  The option
    # name `floppy_image_N` is read from the fs-uae binary's strings and no boot
    # has confirmed it, so a run with no swap images keeps its old command line.
    if swaps:
        floppies += [f"--floppy_image_{i}={image}"
                     for i, image in enumerate([*drives, *swaps])]
    return ["fs-uae", f"--base_dir={run / 'base'}", "--amiga_model=A500",
            f"--kickstart_file={kickstart_file}",
            *floppies,
            "--writable_floppy_images=1", "--floppy_drive_speed=0",
            "--fullscreen=0", f"--window_width={width}", f"--window_height={height}",
            "--automatic_input_grab=0", "--initial_input_grab=0",
            "--volume=0", "--joystick_port_1=none"]


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
    drives, swaps = default_images(run, args.floppy, args.swap)
    argv = fsuae_argv(run, drives, swaps, args.window, kickstart())
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
    p.add_argument("--swap", action="append",
                   help="an image in --run only the swap list holds")
    p.add_argument("--window", default="720x568",
                   help="fs-uae's window, WxH; 704x556 draws each Amiga pixel "
                        "exactly twice, which Curse's code-wheel reader needs")
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
    p = sub.add_parser("curse-stage", help="copy Curse disks A and B into DIR")
    p.add_argument("--out", required=True)
    p.set_defaults(func=curse_stage)
    p = sub.add_parser("pod-stage", help="stage Pools of Darkness with payload .pc files")
    p.add_argument("--out", required=True)
    p.add_argument("--pc", action="append", required=True,
                   help="a .pc file for disk 3's Save drawer, repeatable")
    p.set_defaults(func=pod_stage)
    p = sub.add_parser("pod-panel", help="run the Pools of Darkness key script")
    p.add_argument("--display", required=True)
    p.add_argument("--adf", required=True, help="the staged pod3.adf")
    p.add_argument("--out", required=True, help="directory for the shots")
    p.add_argument("--boot", type=float, default=300,
                   help="longest to wait for the title bar, in seconds")
    p.add_argument("--payload", action="append",
                   help="a .pc name to add; default the three payload names")
    p.set_defaults(func=pod_panel)
    p = sub.add_parser("wheel", help="answer Curse's code wheel on the display")
    p.add_argument("--display", required=True)
    p.add_argument("--settle", type=float, default=1.0)
    p.set_defaults(func=wheel)
    p = sub.add_parser("names", help="every slot's names on a disk 1")
    p.add_argument("adf")
    p.set_defaults(func=names)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Answer Amiga Silver Blades' journal prompt, without recording the answer.

Amiga *Secret of the Silver Blades* asks a copy-protection question the moment
a party begins adventuring, so nothing behind that point could be driven
unattended -- `#331 (Amiga Silver Blades asks a journal word before it will
adventure, so the title cannot be driven past its party menu)`.  The question
names a printed book, but the words are on the disk: the arithmetic that gets
them out is copy-protection research and `CLAUDE.md` keeps it in Donald's
separate private repository, so this reaches into that repository at run time
and **records nothing** here.

    tools/amigabladesjournal.py --holder wish331

What it does: grabs the guest's screen, reads the challenge off it with the
private repository's own screen reader, matches it against the tables that
repository extracts from `Secret` on the player's own side-A disk, types the
word and RETURN through `tools/amigadrive.py`, and deletes the screenshot.
What it prints is `answered` or `no challenge on screen` and nothing else --
neither the challenge nor the word, because a handful of real
challenge-answer pairs is exactly what that rule keeps out of this repository.

**The geometry is the part that had to be worked out on this side.**  That
reader was written against FS-UAE, where the game's 8x8 character cell lands
at 30.64 captured pixels; `winvm shot` grabs WinUAE's 720-wide window through
libvirt, where the same cell is 16 pixels of a 1920x1080 desktop with the
emulator somewhere in it.  So the grid is fitted on the capture, the game's
screen is cut out of the desktop and rescaled to the pitch the reader
declares, and the fitted origin is handed to the reader instead of its own.
Nearest neighbour throughout: every pixel the reader samples is a pixel that
was really on the screen.

**This is Silver Blades' alone.**  Amiga Pool of Radiance's wheel screen takes
a bare RETURN, and Amiga Curse asks a code wheel that
`tools/amigacursewheel.py` answers.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import amigadrive  # noqa: E402

from tools import gamedisks  # noqa: E402

#: Where the private repository is.  `tools/cursewheel.py` settled this name
#: and this default for the DOS side; a second spelling of the same thing is a
#: second thing to get wrong.
ENV = "WISH_CODEWHEEL"

#: The colour the game draws the challenge in, and how far a pixel may be from
#: it and still count.  Both are the private reader's own `GREEN` and its own
#: tolerance; they are repeated here because the grid has to be fitted before
#: that reader can be handed anything, and a mask is not protection research.
GREEN = (85, 238, 85)
TOLERANCE = 120

#: The challenge screen's own layout, measured on the captures
#: `#28 (Decode an Amiga saved game, not just a character file)` left behind:
#: its text lines sit on **alternate** character rows, and every one of them
#: starts at **column 4**.  Neither says anything about what the text is; they
#: are what turns an ink bounding box into the absolute row and column the
#: reader indexes by.
ROWS_APART = 2
LEFT_MARGIN = 4

#: A challenge is at least three lines, so at least three inked bands.  Fewer
#: than two makes the row pitch unmeasurable, and anything that fails the fit
#: is reported as no challenge rather than guessed at.
MIN_BANDS = 3

#: How much of the Amiga screen to cut out of the desktop, in character cells,
#: measured from the fitted origin.  40x25 is the whole 320x200 display and the
#: extra cell each way keeps a glyph that overhangs its own row.
COLUMNS, LINES, MARGIN = 40, 25, 1


def wheel_repo() -> pathlib.Path:
    return pathlib.Path(os.environ.get(ENV)
                        or pathlib.Path.home() / "src/goldbox-codewheel")


def _blades_modules():
    """The private repository's screen reader and its table extractor."""
    analysis = wheel_repo() / "ssb" / "analysis"
    if not analysis.is_dir():
        raise SystemExit(
            f"{analysis} is not a directory; ${ENV} names the separate "
            f"repository holding the copy-protection research, which is not "
            f"in this one")
    sys.path.insert(0, str(analysis))
    import amiga_tables  # noqa: PLC0415
    import screen  # noqa: PLC0415
    return screen, amiga_tables


def fit_grid(bands: list[tuple[int, int, int, int]]):
    """`(x0, y0, pitch)` of the character grid, from inked row bands.

    Each band is `(top, bottom, left, right)` in captured pixels.  The pitch
    comes from the **closest** pair of band tops, because that pair is two
    character rows apart and every other pair is a multiple of it; the origin
    then follows from the first band's top and from the leftmost ink on the
    screen, which is a glyph that fills its cell to the left edge.

    `None` when there are too few bands to measure a pitch, which is every
    screen that is not the challenge.
    """
    if len(bands) < MIN_BANDS:
        return None
    tops = sorted(band[0] for band in bands)
    pitch = min(b - a for a, b in zip(tops, tops[1:])) / ROWS_APART
    if pitch <= 0:
        return None
    x0 = min(band[2] for band in bands) - LEFT_MARGIN * pitch
    return x0, tops[0] - ROWS_APART * pitch, pitch


#: How far apart two inked rows may be and still be one band.  The private
#: reader's own number, and for its own reason: at the scale the game's text
#: is drawn at, a one-pixel hole inside a glyph is narrower than this and a
#: blank text line is wider.
BAND_GAP = 4


def _ink_mask(image):
    """Where `image` is the colour the challenge is drawn in, as `L` bytes.

    PIL rather than numpy on purpose.  The private reader needs numpy and
    brings it itself; nothing in this file should, because this repository's
    virtual environment does not carry it and a test that skips is not a test.
    `ImageChops.add` saturates at 255, which cannot lose a pixel here: a
    channel sum that saturates is already far outside `TOLERANCE`.
    """
    from PIL import Image, ImageChops  # noqa: PLC0415

    rgb = image.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, GREEN))
    red, green, blue = diff.split()
    total = ImageChops.add(ImageChops.add(red, green), blue)
    return total.point(lambda value: 255 if value < TOLERANCE else 0)


def text_bands(image):
    """The inked row bands of `image`, as `fit_grid` wants them."""
    mask = _ink_mask(image)
    width, height = mask.size
    pixels = mask.tobytes()
    inked = []
    for y in range(height):
        row = pixels[y * width:(y + 1) * width]
        first = row.find(b"\xff")
        inked.append(None if first < 0 else (first, row.rfind(b"\xff")))
    out, span = [], None
    for y, extent in enumerate(inked):
        if extent is None:
            continue
        if span is not None and y > span[1] + BAND_GAP:
            out.append(span)
            span = None
        if span is None:
            span = [y, y, extent[0], extent[1]]
        else:
            span[1] = y
            span[2] = min(span[2], extent[0])
            span[3] = max(span[3], extent[1])
    if span is not None:
        out.append(span)
    return [tuple(band) for band in out]


def to_reader_scale(shot: pathlib.Path, out: pathlib.Path,
                    target_pitch: float | None = None):
    """Cut the game's screen out of the desktop at the reader's own pitch.

    Returns the `(X0, Y0, PITCH)` the reader should use on `out`, or `None`
    when no character grid could be fitted.  The rescale is nearest neighbour
    and the origin is kept as a float: rounding it into a paste offset instead
    moved the sampling phase inside a glyph and read a `0` as an `8`.

    `target_pitch` defaults to the pitch the private reader declares, and is
    an argument so that the arithmetic can be exercised without it.
    """
    from PIL import Image  # noqa: PLC0415

    if target_pitch is None:
        target_pitch = _blades_modules()[0].PITCH
    image = Image.open(shot)
    grid = fit_grid(text_bands(image))
    if grid is None:
        return None
    x0, y0, pitch = grid
    left = max(0, int(x0 - MARGIN * pitch))
    top = max(0, int(y0 - MARGIN * pitch))
    crop = image.convert("RGB").crop((
        left, top,
        min(image.width, int(x0 + (COLUMNS + MARGIN) * pitch)),
        min(image.height, int(y0 + (LINES + MARGIN) * pitch))))
    factor = target_pitch / pitch
    crop = crop.resize((round(crop.width * factor),
                        round(crop.height * factor)), Image.NEAREST)
    crop.save(out)
    return (x0 - left) * factor, (y0 - top) * factor, pitch * factor


def find_disk(named: str | None = None) -> pathlib.Path:
    """The Silver Blades side-A image the tables are read out of.

    Not a copy and not a fixture: the words come off the player's own disk
    every run, the way `tests/gamedata.py` reads map files off theirs.
    """
    if named:
        path = pathlib.Path(named).expanduser()
        if not path.is_file():
            raise SystemExit(f"{path} is not a file")
        return path
    roots = gamedisks.candidates("amiga")
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.adf")):
            if _carries_the_executable(path):
                return path
    raise SystemExit(
        "No Amiga Silver Blades disk: pass --adf, or set $AMIGA_DISKS to a "
        "directory holding one (looked in "
        + ", ".join(str(root) for root in roots) + ")")


def _carries_the_executable(path: pathlib.Path) -> bool:
    from goldbox import amiga_adf  # noqa: PLC0415

    try:
        disk = amiga_adf.AmigaDisk.open(path)
        return any(entry.name == "Secret" and not entry.is_dir
                   for entry in disk.entries())
    except Exception:
        return False


def tables(adf: pathlib.Path):
    """The disk's own challenge tables, extracted at run time."""
    from goldbox import amiga_adf  # noqa: PLC0415

    _, amiga_tables = _blades_modules()
    disk = amiga_adf.AmigaDisk.open(adf)
    return amiga_tables.tables(disk.read_file("Secret"))


def answer(holder: str, settle: float, adf: pathlib.Path,
           shot: pathlib.Path | None = None) -> bool:
    """Read the prompt on screen and type its answer.  True when it did."""
    screen, amiga_tables = _blades_modules()
    table = tables(adf)
    tidy = shot is None
    scaled = None
    if shot is None:
        #: `NamedTemporaryFile`, not `mkstemp`: `mkstemp` hands back an open
        #: descriptor as well as a path, and the rescale below reopens the
        #: same file.  Holding the descriptor there is what broke a Windows
        #: CI job with `PermissionError: [WinError 32]` once already --
        #: `tests/test_iconproposal.py` has the note.
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        shot = pathlib.Path(handle.name)
    try:
        subprocess.run(["winvm", "shot", str(shot)], check=True,
                       capture_output=True, text=True,
                       env=dict(os.environ, SSH_ASKPASS_REQUIRE="never"))
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        scaled = pathlib.Path(handle.name)
        geometry = to_reader_scale(shot, scaled)
        if geometry is None:
            print("no challenge on screen")
            return False
        screen.X0, screen.Y0, screen.PITCH = geometry
        try:
            challenge = screen.read_challenge(scaled)
        except ValueError:
            print("no challenge on screen")
            return False
        try:
            word = amiga_tables.answer_for(challenge, table).answer
        except ValueError:
            # Deliberately not the exception's own message: it quotes the
            # challenge, and neither side of the exchange belongs here.
            raise SystemExit(
                "the challenge on screen is not in this disk's tables") \
                from None
    finally:
        if scaled is not None and scaled.exists():
            scaled.unlink()
        if tidy and shot.exists():
            shot.unlink()
    for letter in word:
        amigadrive.press(holder, letter, settle)
    amigadrive.press(holder, "RET", settle)
    print("answered")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse
                                     .RawDescriptionHelpFormatter)
    parser.add_argument("--holder", required=True,
                        help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--adf", default=None,
                        help="the Silver Blades side-A image; found through "
                             "gamedisks.toml when not given")
    parser.add_argument("--settle", type=float, default=1.0,
                        help="seconds to wait after each key (default 1)")
    args = parser.parse_args(argv)
    return 0 if answer(args.holder, args.settle,
                       find_disk(args.adf)) else 1


if __name__ == "__main__":
    sys.exit(main())

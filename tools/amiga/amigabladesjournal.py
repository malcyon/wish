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

    tools/amiga/amigabladesjournal.py --holder wish331

What it does: grabs the guest's screen, reads the challenge off it with the
private repository's own screen reader, matches it against the tables that
repository extracts from `Secret` on the player's own side-A disk, types the
word and RETURN through `tools/amiga/amigadrive.py`, and deletes the screenshot.
What it prints is `answered` or `no challenge on screen` and nothing else --
neither the challenge nor the word, because a handful of real
challenge-answer pairs is exactly what that rule keeps out of this repository.

**The geometry is the part that had to be worked out on this side.**  That
reader was written against FS-UAE, where the game's 8x8 character cell lands
at 30.64 captured pixels; `winvm shot` grabs WinUAE's 720-wide window through
libvirt, where the same cell is 16 pixels of a 1920x1080 desktop with the
emulator somewhere in it.  So the grid is fitted on the capture, each of the
game's own pixels is sampled once at its centre, and those samples are
replicated to a pitch of 32 -- four pixels each way, a whole number, which
`reader_pitch()` explains and `#371` was caused by not being.  The reader is
then told that pitch and that origin instead of its own.  Nearest neighbour
throughout: every pixel the reader samples is a pixel that was really on the
screen.

**This is Silver Blades' alone.**  Amiga Pool of Radiance's wheel screen takes
a bare RETURN, and Amiga Curse asks a code wheel that
`tools/amiga/amigacursewheel.py` answers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from automap import gamedisks  # noqa: E402
from tools.amiga import amigadrive  # noqa: E402
from tools.curse_of_the_azure_bonds import cursewheel  # noqa: E402

#: Where the private repository is.  `tools/curse_of_the_azure_bonds/cursewheel.py` settled this name
#: and the registry lookup for the DOS side; a second spelling of the same
#: thing is a second thing to get wrong.
ENV = "WISH_CODEWHEEL"

#: The colour the game draws the challenge in, and how far a pixel may be from
#: it and still count.  Both are the private reader's own `GREEN` and its own
#: tolerance; they are repeated here because the grid has to be fitted before
#: that reader can be handed anything, and a mask is not protection research.
GREEN = (85, 238, 85)
TOLERANCE = 120

#: The challenge screen's own layout, measured on the captures
#: `#28 (Decode an Amiga saved game, not just a character file)` left behind:
#: text lines sit on alternate character rows, the first at column 4.  Neither
#: says anything about what the text is; they are what turns an ink bounding
#: box into the absolute row and column the reader indexes by.
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

#: The file in a `keep` directory that says what each kept capture read as.
TALLY = "tally.jsonl"


def reader_pitch(target_pitch: float) -> float:
    """The pitch to hand the reader: a **whole** number of pixels per Amiga
    pixel, nearest the one the reader declares.

    `#371 (The Silver Blades journal reader misreads a 6 as an 8, so a boot is
    spent on a question the disk can answer)` is this number and nothing else.
    The reader's own pitch is 30.64, which is 3.83 pixels per Amiga pixel, so
    building its image replicates some of the game's pixels four times and
    others three.  Every glyph in this font is drawn with one-pixel gaps, and
    a gap that comes out three pixels wide beside one that comes out four does
    not survive the reader's normalise-to-8x8 -- the gap on one row of the
    game's `6` closes, and a closed gap there is an `8`.

    A whole number replicates every Amiga pixel identically, so a gap is the
    same width wherever it lands and the glyph reaching the reader is the
    glyph the game drew, scaled.  The nearest whole number is 4, so the reader
    is handed 32 rather than 30.64: its `cell()` trims a fixed three pixels off
    each side of a cell before it normalises, and that trim only means what it
    was measured to mean at a pitch near 30.
    """
    return max(1, round(target_pitch / 8.0)) * 8.0


def wheel_repo() -> pathlib.Path:
    return cursewheel.wheel_repo()


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
    try:
        import screen  # noqa: PLC0415
    except ModuleNotFoundError as error:
        package = error.name or "a private-reader dependency"
        raise SystemExit(
            f"Missing dependency {package} in {sys.executable}; rerun with an "
            "interpreter whose environment has the private screen reader's "
            "dependencies") from None
    return screen, amiga_tables


def aspect_sweep(centre: float = 1.03, spread: float = 0.06,
                 step: float = 0.005) -> tuple[float, ...]:
    """Horizontal-to-vertical pixel ratios to try, nearest `centre` first.

    FS-UAE draws the game about 3 percent wider than tall in the window
    `fsuaegdb.py` gives it, so the grid fitted from the rows alone is too
    narrow.  The ratio of that window depends on its size, so a run tries
    nearby ratios until the reading matches the disk's tables, which is a
    check no wrong ratio passes.
    """
    count = round(spread / step)
    values = sorted((round(centre + i * step, 4)
                     for i in range(-count, count + 1)),
                    key=lambda value: abs(value - centre))
    return tuple(values)


def fit_grid(bands: list[tuple[int, int, int, int]], aspect: float = 1.0):
    """`(x0, y0, pitch)` of the character grid, from inked row bands.

    Each band is `(top, bottom, left, right)` in captured pixels.  The pitch
    comes from the **closest** pair of band tops, because that pair is two
    character rows apart and every other pair is a multiple of it; the origin
    then follows from the first (topmost) band's top and its leftmost ink,
    which is taken to be a glyph that fills its cell to the left edge.  The
    rows give the vertical pitch only; `aspect` is how many times wider a
    cell is than it is tall, which moves that origin left of the first ink.

    `None` when there are too few bands to measure a pitch, which is every
    screen that is not the challenge.
    """
    if len(bands) < MIN_BANDS:
        return None
    tops = sorted(band[0] for band in bands)
    pitch = min(b - a for a, b in zip(tops, tops[1:])) / ROWS_APART
    if pitch <= 0:
        return None
    first = min(bands, key=lambda band: band[0])
    x0 = first[2] - LEFT_MARGIN * pitch * aspect
    return x0, first[0] - ROWS_APART * pitch, pitch


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


def _client_of(image):
    """The emulator's client area cut out of a desktop grab, at a whole-pixel offset.

    Text elsewhere on the desktop must not take part in the grid fit.  An image
    that is no bigger than a client, or in which no client is found, is used as it is.
    """
    from tools.amiga import amigashots  # noqa: PLC0415

    width, height = amigashots.CLIENT
    if image.size[0] <= width and image.size[1] <= height:
        return image
    try:
        left, top = amigashots.find_client(image)
    except LookupError:
        return image
    if (left < 0 or top < 0 or left + width > image.size[0]
            or top + height > image.size[1]):
        # A window partly off screen: `crop` would pad with black, and a fit on
        # padding is a fit on something the screen never showed.
        return image
    return image.crop((left, top, left + width, top + height))


def to_reader_scale(shot: pathlib.Path, out: pathlib.Path,
                    target_pitch: float | None = None, aspect: float = 1.0):
    """Cut the game's screen out of the desktop, at a pitch the reader can use.

    Two steps, and `#371 (The Silver Blades journal reader misreads a 6 as an
    8, so a boot is spent on a question the disk can answer)` is the second.

    The game draws each of the 8 pixels in its character cell as a
    `pitch / 8`-pixel block of the capture -- an exact 2-pixel block at
    `winvm shot`'s pitch of 16 -- so every Amiga pixel has one true centre in
    the capture, and this samples that centre directly out of the untouched
    screenshot, once per Amiga pixel.  Cropping the desktop first and
    rescaling the crop truncated the fitted origin to a whole pixel, which
    put the resize's own duplicate-and-skip pattern out of phase with where
    the Amiga pixel boundaries really fell.

    Those samples are then replicated up to `reader_pitch(target_pitch)`,
    which is a whole number of pixels per Amiga pixel rather than the
    reader's own fractional 30.64.  Replicating by a fraction is what made
    this issue's `6` read as an `8`, measured on the capture that did it:
    `cited/361run/shots/07-chal.png` reads `8` at 30.64 and `6` at 16, 24,
    32, 40, 48, 64, 80, 96 and 128, under this algorithm and under the
    cropping one alike.  The pitch the reader is handed back is the one it
    must use, so `answer()` sets `screen.PITCH` from this return value.

    The desktop is cropped to the emulator's client first, by a whole-pixel
    offset that moves no sampling phase, so that green text outside the window
    cannot enter the grid fit.

    Returns the `(X0, Y0, PITCH)` for `out`, or `None` when no character grid
    could be fitted.  `target_pitch` defaults to the pitch the private reader
    declares, and is an argument so that the arithmetic can be exercised
    without it.

    `aspect` is the width of an Amiga pixel in the capture over its height.
    It is 1 for WinUAE and about 1.03 for FS-UAE's window; the samples are
    taken at the wider horizontal spacing, so the reader still gets square
    pixels.
    """
    from PIL import Image  # noqa: PLC0415

    if target_pitch is None:
        target_pitch = _blades_modules()[0].PITCH
    image = _client_of(Image.open(shot).convert("RGB"))
    grid = fit_grid(text_bands(image), aspect)
    if grid is None:
        return None
    x0, y0, pitch = grid
    amiga_px = pitch / 8.0
    amiga_px_x = amiga_px * aspect
    ox = x0 - MARGIN * pitch * aspect
    oy = y0 - MARGIN * pitch
    columns = (COLUMNS + 2 * MARGIN) * 8
    rows = (LINES + 2 * MARGIN) * 8
    width, height = image.size
    source = image.load()
    canonical = Image.new("RGB", (columns, rows))
    canonical_px = canonical.load()
    for ay in range(rows):
        sy = min(height - 1, max(0, round(oy + (ay + 0.5) * amiga_px)))
        for ax in range(columns):
            sx = min(width - 1, max(0, round(ox + (ax + 0.5) * amiga_px_x)))
            canonical_px[ax, ay] = source[sx, sy]
    out_pitch = reader_pitch(target_pitch)
    factor = int(out_pitch // 8)
    scaled = canonical.resize((columns * factor, rows * factor), Image.NEAREST)
    scaled.save(out)
    return MARGIN * out_pitch, MARGIN * out_pitch, out_pitch


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


def refuse_keep_inside_repository(directory: pathlib.Path) -> None:
    """`SystemExit` when `directory` is inside this repository's tree."""
    root = HERE.parent.parent.resolve()
    if directory.resolve().is_relative_to(root):
        raise SystemExit(f"{directory} is inside the repository; keep captures outside it")


def _next_number(directory: pathlib.Path) -> int:
    """One more than the highest number among the captures already kept."""
    numbers = [int(path.stem.rsplit("-", 1)[1]) for path in directory.glob("challenge-*.png")
               if path.stem.rsplit("-", 1)[1].isdecimal()]
    return max(numbers, default=0) + 1


def _record_of(match, table) -> int | None:
    """Where `match` sits in `table`, or None when it is not one of its entries."""
    return next((i for i, entry in enumerate(table) if entry is match), None)


def _keep(directory: pathlib.Path, shot: pathlib.Path, challenge: dict, match,
          table) -> None:
    """Copy the raw grab into `directory` and append its tally line."""
    directory.mkdir(parents=True, exist_ok=True)
    name = f"challenge-{_next_number(directory):02d}.png"
    shutil.copyfile(shot, directory / name)
    kind = getattr(match, "kind", None) or challenge.get("kind")
    line = {"capture": name,
            "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest(),
            "kind": kind,
            "record": None if match is None else _record_of(match, table)}
    with (directory / TALLY).open("a", encoding="utf-8") as tally:
        tally.write(json.dumps(line, sort_keys=True) + "\n")


def replay(directory: pathlib.Path, adf: pathlib.Path) -> tuple[int, int, list[str]]:
    """Re-read every capture `answer(keep=...)` kept; `(agreeing, total, disagreeing names)`.

    A capture agrees when its file is present with its recorded digest and the
    reader now names the same kind and record as the tally line did.  A missing
    tally is no captures at all, not an error.
    """
    tally = directory / TALLY
    if not tally.is_file():
        return 0, 0, []
    screen, amiga_tables = _blades_modules()
    table = tables(adf)
    lines = [line for line in tally.read_text(encoding="utf-8").splitlines() if line.strip()]
    bad: list[str] = []
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
            name, digest = row["capture"], row["sha256"]
            expected = (row["kind"], row["record"])
        except (ValueError, KeyError, TypeError):
            # A truncated or incomplete line is a disagreement to report, not a crash.
            bad.append(f"{TALLY} line {number}")
            continue
        path = directory / str(name)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            bad.append(str(name))
            continue
        if _reread(path, screen, amiga_tables, table) != expected:
            bad.append(str(name))
    return len(lines) - len(bad), len(lines), bad


def _reread(shot: pathlib.Path, screen, amiga_tables, table):
    """`(kind, record)` the reader gives `shot` now, or None when it reads no challenge."""
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    scaled = pathlib.Path(handle.name)
    try:
        geometry = to_reader_scale(shot, scaled)
        if geometry is None:
            return None
        screen.X0, screen.Y0, screen.PITCH = geometry
        try:
            challenge = screen.read_challenge(scaled)
        except ValueError:
            return None
        try:
            match = amiga_tables.answer_for(challenge, table)
        except ValueError:
            return (challenge.get("kind"), None)
        return (getattr(match, "kind", None) or challenge.get("kind"),
                _record_of(match, table))
    finally:
        scaled.unlink(missing_ok=True)


def answer(holder: str, settle: float, adf: pathlib.Path,
           shot: pathlib.Path | None = None, capture=None, press=None,
           keep: pathlib.Path | None = None,
           aspects: tuple[float, ...] = (1.0,)) -> bool:
    """Read the prompt on screen and type its answer.  True when it did.

    `aspects` are the horizontal-to-vertical pixel ratios tried in order, each
    on the same capture, until one reads a challenge the disk's tables hold.
    WinUAE's capture is square, so the default is one try; `aspect_sweep()` is
    for FS-UAE.

    `keep` is a directory: when a challenge was read, the raw grab is copied to
    `keep/challenge-NN.png` and one line naming it, its digest, its kind and the
    matched record's index in `tables()` is appended to `keep/tally.jsonl`, so a
    later change to the reader can be checked against it by `replay`.  Nothing
    is kept for a screen with no challenge on it.  `keep` must lie outside this
    repository, whose tree must never hold a capture; a directory inside it is
    refused before anything is grabbed.

    `capture` takes a path and puts the emulator's screen in it; `press` takes
    one character and sends it.  Both default to WinUAE's -- `winvm shot` and
    `tools/amiga/amigadrive.py` -- and both are arguments because the same challenge
    is asked by the same game in FS-UAE, where the screen comes off an X
    server and the keys go in through XTEST (`#464 (Can the automapper follow
    a live FS-UAE game on Linux, so Wish and the Amiga game run on one
    machine?)`).  Only the two ends differ; the reading between them is one
    implementation, which is the point of passing them rather than writing a
    second answerer.
    """
    if capture is None:
        def capture(path):
            subprocess.run(["winvm", "shot", str(path)], check=True,
                           capture_output=True, text=True,
                           env=dict(os.environ,
                                    SSH_ASKPASS_REQUIRE="never"))
    if press is None:
        def press(key):
            amigadrive.press(holder, key, settle)

    if keep is not None:
        refuse_keep_inside_repository(keep)
    screen, amiga_tables = _blades_modules()
    table = tables(adf)
    tidy = shot is None
    scaled = None
    if shot is None:
        #: `NamedTemporaryFile`, not `mkstemp`: `mkstemp` hands back an open
        #: descriptor as well as a path, and the rescale below reopens the
        #: same file.  Holding the descriptor there is what broke a Windows
        #: CI job with `PermissionError: [WinError 32]` once already --
        #: `tests/icons/test_iconproposal.py` has the note.
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        shot = pathlib.Path(handle.name)
    try:
        capture(shot)
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        scaled = pathlib.Path(handle.name)
        challenge = match = None
        for aspect in aspects:
            geometry = to_reader_scale(shot, scaled, aspect=aspect)
            if geometry is None:
                break
            screen.X0, screen.Y0, screen.PITCH = geometry
            try:
                read = screen.read_challenge(scaled)
            except ValueError:
                continue
            challenge = read
            try:
                match = amiga_tables.answer_for(challenge, table)
            except ValueError:
                continue
            break
        if challenge is None:
            print("no challenge on screen")
            return False
        if match is None:
            if keep is not None:
                _keep(keep, shot, challenge, None, None)
            # Deliberately not the exception's own message: it quotes the
            # challenge, and neither side of the exchange belongs here.
            raise SystemExit(
                "the challenge on screen is not in this disk's tables")
        if keep is not None:
            _keep(keep, shot, challenge, match, table)
        word = match.answer
    finally:
        if scaled is not None and scaled.exists():
            scaled.unlink()
        if tidy and shot.exists():
            shot.unlink()
    for letter in word:
        press(letter)
    press("RET")
    print("answered")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse
                                     .RawDescriptionHelpFormatter)
    parser.add_argument("--holder", default=None,
                        help="the winuae.ps1 lane claim this run holds "
                             "(required unless --replay)")
    parser.add_argument("--adf", default=None,
                        help="the Silver Blades side-A image; found through "
                             "gamedisks.yaml when not given")
    parser.add_argument("--settle", type=float, default=1.0,
                        help="seconds to wait after each key (default 1)")
    parser.add_argument("--keep", type=pathlib.Path, default=None,
                        help="a directory to keep each challenge capture and "
                             "its tally line in")
    parser.add_argument("--replay", type=pathlib.Path, default=None,
                        help="re-read every capture kept in this directory "
                             "and check it against its tally line")
    args = parser.parse_args(argv)
    if args.replay is None and args.holder is None:
        parser.error("--holder is required unless --replay is given")
    if args.replay is not None:
        agreeing, total, bad = replay(args.replay, find_disk(args.adf))
        print(f"{agreeing} of {total} agree")
        for name in bad:
            print(name)
        return 0 if not bad else 1
    return 0 if answer(args.holder, args.settle, find_disk(args.adf),
                       keep=args.keep) else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Answer Amiga Curse's code-wheel prompt, without recording the answer.

The Curse of the Azure Bonds release on this machine still asks its code-wheel
question, so nothing on that title can be driven unattended until the prompt is
past -- `#108 (Amiga Curse asks its code wheel, so the title cannot be driven
unattended)`.  The arithmetic behind the wheel is copy-protection research and
`CLAUDE.md` keeps it in Donald's separate private repository; this reaches into
that repository at run time and **records nothing** here.

    tools/amigacursewheel.py --holder wish28

What it does: grabs the guest's screen, reads the challenge off it with the
private repository's own screen reader, computes the character with its own
transcription of the game's arithmetic, presses that key and RETURN through
`tools/amigadrive.py`, and deletes the screenshot.  What it prints is
`answered` or `no challenge on screen` and nothing else -- neither the
challenge nor the character, because a handful of real challenge-answer pairs
is exactly what that rule keeps out of this repository.

**This is Curse's alone, and the other two titles need something else.** Amiga
Pool of Radiance's wheel screen takes a bare RETURN.  Amiga Silver Blades asks
for a word out of the printed Adventurer's Journal rather than a wheel, and
nothing here can answer that -- `#331 (Amiga Silver Blades asks a journal word
before it will adventure, so the title cannot be driven past its party menu)`.
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

import amigadrive  # noqa: E402

#: Where the private repository is.  `tools/cursewheel.py` settled this name
#: and this default for the DOS side; a second spelling of the same thing is a
#: second thing to get wrong.
ENV = "WISH_CODEWHEEL"


def wheel_repo() -> pathlib.Path:
    return pathlib.Path(os.environ.get(ENV)
                        or pathlib.Path.home() / "src/goldbox-codewheel")


def _wheel_modules():
    """The private repository's screen reader and wheel arithmetic."""
    analysis = wheel_repo() / "coab" / "analysis"
    if not analysis.is_dir():
        raise SystemExit(
            f"{analysis} is not a directory; ${ENV} names the separate "
            f"repository holding the code-wheel research, which is not in "
            f"this one")
    sys.path.insert(0, str(analysis))
    import amiga_screen  # noqa: PLC0415
    import amiga_wheel  # noqa: PLC0415
    return amiga_screen, amiga_wheel


#: The character pitch the private repository's reader fits over, in captured
#: pixels per Amiga pixel.  It was written against FS-UAE, which draws the
#: 320-pixel screen about four times over; `winvm shot` grabs WinUAE's 720-wide
#: window, where the same screen lands at exactly 2.0, and the fit's search
#: never reaches it.  Scaling the capture up by a whole number with nearest
#: neighbour puts it back in range and invents no pixel: every sample the
#: reader takes is a pixel that was really there.
PITCH_MIN = 3.6


def scale_factor(pitch: float) -> int:
    """The whole number of times to enlarge a capture at this pitch.

    Whole numbers only, and nearest neighbour when it is applied: a fractional
    resize averages neighbouring pixels, and a sample taken from an averaged
    pixel is a colour that was never on the screen.  The reader identifies a
    rune by the partition its colours fall into, so one invented colour is one
    template that no longer explains the block.
    """
    factor = 1
    while pitch * factor < PITCH_MIN:
        factor += 1
    return factor


def _to_reader_scale(path: pathlib.Path, screen=None):
    """The screenshot at a scale the private repository's reader can fit."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    screen = screen or _wheel_modules()[0]
    image = Image.open(path).convert("RGB")
    grids = screen.find_runes(np.array(image).astype(int))
    if not grids:
        return np.array(image).astype(int)
    factor = scale_factor(grids[0][2])
    if factor > 1:
        image = image.resize((image.width * factor, image.height * factor),
                             Image.NEAREST)
    return np.array(image).astype(int)


def answer(holder: str, settle: float, shot: pathlib.Path | None = None
           ) -> bool:
    """Read the prompt on screen and type its answer.  True when it did."""
    screen, wheel = _wheel_modules()
    tidy = shot is None
    if shot is None:
        shot = pathlib.Path(tempfile.mkstemp(suffix=".png")[1])
    try:
        subprocess.run(["winvm", "shot", str(shot)], check=True,
                       capture_output=True, text=True,
                       env=dict(os.environ, SSH_ASKPASS_REQUIRE="never"))
        challenge = screen.read_challenge(_to_reader_scale(shot))
        if challenge is None:
            print("no challenge on screen")
            return False
        character = wheel.answer_from_screen(
            challenge["box"], challenge["pattern"],
            challenge["espruar"], challenge["dethek"])
    finally:
        if tidy and shot.exists():
            shot.unlink()
    amigadrive.press(holder, character, settle)
    amigadrive.press(holder, "RET", settle)
    print("answered")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse
                                     .RawDescriptionHelpFormatter)
    parser.add_argument("--holder", required=True,
                        help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--settle", type=float, default=2.0,
                        help="seconds to wait after each key (default 2)")
    args = parser.parse_args(argv)
    return 0 if answer(args.holder, args.settle) else 1


if __name__ == "__main__":
    sys.exit(main())

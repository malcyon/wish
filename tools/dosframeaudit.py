#!/usr/bin/env python3
"""Count the DOSBox-X frames that are not a clean 2x2 replication (#215).

`tools/dosboxx.halve()` decides a frame was line-doubled from its width and
height being even, and halves it by taking every other pixel of every other
row.  Nothing checks that the 2x2 blocks it is throwing three quarters of away
were ever uniform.  `#215 (Nothing checks that a frame halve() is about to
halve was really line-doubled)` asks the one question that decides whether a
uniformity check is safe to add:

    Capture a few hundred frames through `settle()` during a driven session
    and count how many have a non-uniform 2x2 block, and where.

That is what this does, and the count is the whole result.  A frame is
captured **unhalved** -- `dosbox.Session.capture` rather than
`dosboxx.XSession.capture` -- because the thing being measured is the frame
`halve()` is handed, not what it gives back.

The frames are captured while the game is doing something: the party turns on
the spot between batches, so the viewport is redrawn and the sample is not
three hundred pictures of one still screen.  Nothing is written but the
report; a frame of the running game is the game's own art and stays under
`work/`.

    tools/dosframeaudit.py --save J --frames 300
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosbox, dosboxx  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent

#: Where the report lands.  Under `work/`, which is gitignored.
OUT = REPO / "work" / "issue215"


def blocks_that_differ(screen: dosbox.Screen, limit: int = 8) -> tuple[int, list]:
    """How many 2x2 blocks of this frame are not one colour, and the first few.

    Returns `(count, [(x, y, four_pixels), ...])` with the list truncated to
    `limit`, so a frame with ten thousand ragged blocks costs the same to
    report as one with three.
    """
    w, h, px = screen.width, screen.height, screen.px
    if w % 2 or h % 2:
        return -1, []
    bad = 0
    where: list = []
    for y in range(0, h, 2):
        r0 = y * w * 3
        r1 = (y + 1) * w * 3
        for x in range(0, w, 2):
            a = px[r0 + x * 3:r0 + x * 3 + 3]
            b = px[r0 + x * 3 + 3:r0 + x * 3 + 6]
            c = px[r1 + x * 3:r1 + x * 3 + 3]
            d = px[r1 + x * 3 + 3:r1 + x * 3 + 6]
            if a == b == c == d:
                continue
            bad += 1
            if len(where) < limit:
                where.append({"x": x, "y": y,
                              "px": [a.hex(), b.hex(), c.hex(), d.hex()]})
    return bad, where


def audit(*, save: str, frames: int, out: pathlib.Path,
          batch: int = 20) -> dict:
    """Boot, load, and measure `frames` raw captures."""
    out.mkdir(parents=True, exist_ok=True)
    game = dosbox.find_game()
    report: dict = {"save": save, "frames_asked": frames, "sizes": {},
                    "clean": 0, "ragged": 0, "odd_sized": 0, "examples": []}

    with dosboxx.claim("issue215 frame audit") as claimed:
        s = dosboxx.XSession(claimed, game)
        try:
            s.stage(fresh=True)
            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(save)
            report["loaded"] = True

            taken = 0
            while taken < frames:
                for _ in range(min(batch, frames - taken)):
                    # **Unhalved on purpose**: this is the frame `halve()` is
                    # handed.  `settle()` polls at this rate by design, so a
                    # capture caught mid-redraw is exactly the case #215 is
                    # unsure about and must not be excluded.
                    screen = dosbox.Session.capture(s)
                    taken += 1
                    key = f"{screen.width}x{screen.height}"
                    report["sizes"][key] = report["sizes"].get(key, 0) + 1
                    bad, where = blocks_that_differ(screen)
                    if bad < 0:
                        report["odd_sized"] += 1
                        continue
                    if bad:
                        report["ragged"] += 1
                        if len(report["examples"]) < 10:
                            report["examples"].append(
                                {"frame": taken, "bad_blocks": bad,
                                 "of": (screen.width // 2) * (screen.height // 2),
                                 "first": where})
                    else:
                        report["clean"] += 1
                    time.sleep(0.05)
                # Something has to move, or three hundred captures are three
                # hundred copies of one still picture and prove nothing about
                # a frame caught mid-redraw.
                por.turn_right()
            report["captured"] = taken
        finally:
            (out / "report.json").write_text(json.dumps(report, indent=1,
                                                        default=str))
            s.close()
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", default="J", help="the slot to load")
    ap.add_argument("--frames", type=int, default=300,
                    help="how many raw captures to measure")
    ap.add_argument("--out", default=None, help="where the report goes")
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out or OUT)
    report = audit(save=args.save, frames=args.frames, out=out)
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

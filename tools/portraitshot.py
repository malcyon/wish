#!/usr/bin/env python3
"""Photograph a DOS character's sheet portrait, and say which art it drew.

The running-game half of `#57 (Carry the character portrait across ports)`.
`goldbox/portraits.py` claims that the DOS record's `portrait_head` at
`0x0BB` is a **one-based position** in a fourteen-entry creation menu whose
ids are the C64's own `HEAD<xx>` files -- a claim from three offline
measurements.  Only the game can settle it, so this drives one:

1. a party is staged into an instance's own game tree, either converted from
   a C64 save disk (`--c64`) or the tree's own shipped party, and each
   character's portrait pair is set to a value this run chose (`--heads`,
   `--bodies`);
2. the game is booted, the slot loaded, and each character's sheet opened;
3. the portrait is cut out of the frame and **matched against every head and
   body block of `HEAD<n>.DAX`/`BODY<n>.DAX`**, rendered from the player's
   own files with `render_block` below.

So the answer is an art id, not a screenshot somebody has to squint at: if
`portrait_head = 9` matches block `$2D`, and `$2D` is the ninth entry of the
menu table, the reading is confirmed and the conversion is a lookup.

Nothing here writes to the player's archives -- `tools.dosbox.Session.stage`
copies the tree -- and nothing opens a window on the desktop.  Screenshots go
under `--out`, which should be under `work/`.

    tools/portraitshot.py --out work/p57-portraits/run2 --heads 1,2,3,4,5,6

`--keys` is the escape hatch for a route that has moved: every key is pressed
in turn from the character sheet and a frame captured after each, which is
how the sheet's own `VIEW` was found in the first place.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos  # noqa: E402
from goldbox import dos_savegame as sg  # noqa: E402
from goldbox import portraits as portrait_tables  # noqa: E402
from goldbox.d64 import load_payload  # noqa: E402
from goldbox.games import POOL_OF_RADIANCE  # noqa: E402
from tools import dosbox  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent

#: The block header is four bytes and the pixels start at seventeen: the
#: four-byte header, then thirteen bytes nothing here reads.  Measured rather
#: than documented -- every `HEAD`/`BODY` and `CHEAD`/`CBODY` block in Pool of
#: Radiance is exactly `17 + rows * stride` bytes long, and rendering from
#: byte 4 shifts each row thirteen bytes left of where it belongs.
PIXEL_START = 17

#: Bytes per row: two pixels each, high nibble first (`docs/145-dos-decode-
#: kit.md`).  Byte 2 of the header is the width in fours; byte 0 is the row
#: count.
EGA = ((0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170),
       (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
       (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255),
       (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255))


def render_block(block: bytes) -> tuple[int, int, list[list[int]]]:
    """`(width, height, rows of palette indices)` for one `.DAX` image block.

    Palette indices rather than colours, so a comparison against a captured
    frame is a comparison of *shape* and can be made after mapping the
    frame's own EGA colours back to indices.
    """
    rows = block[0]
    stride = block[2] * 4
    out = []
    for y in range(rows):
        line = []
        for x in range(stride):
            byte = block[PIXEL_START + y * stride + x]
            line.append(byte >> 4)
            line.append(byte & 0x0F)
        out.append(line)
    return stride * 2, rows, out


def art(game: pathlib.Path, stem: str) -> dict[int, tuple[int, int, list]]:
    """Every `HEAD`/`BODY` block in the game directory, rendered, by id."""
    out: dict[int, tuple[int, int, list]] = {}
    for path in sorted(game.glob(f"{stem}[0-9].DAX")):
        data = path.read_bytes()
        for block, raw in sg.dax_blocks(data, path.name):
            out.setdefault(block, render_block(raw))
    return out


def frame_indices(screen) -> list[list[int]]:
    """The captured frame as EGA palette indices, or -1 where it is not EGA."""
    nearest = {c: n for n, c in enumerate(EGA)}
    px = screen.px
    out = []
    for y in range(screen.height):
        base = y * screen.width * 3
        out.append([nearest.get(tuple(px[base + 3 * x:base + 3 * x + 3]), -1)
                    for x in range(screen.width)])
    return out


def find(pixels: list[list[int]], image: tuple[int, int, list],
         ignore: int = 0) -> tuple[int, int] | None:
    """Where an image sits in a frame, ignoring its background colour.

    A portrait is drawn over whatever the panel already held, so the match is
    on the non-background pixels only -- and every one of them has to agree,
    which is what makes a hit a hit rather than a best guess.
    """
    width, height, rows = image
    marks = [(x, y, v) for y, line in enumerate(rows)
             for x, v in enumerate(line) if v != ignore]
    if not marks:
        return None
    for top in range(len(pixels) - height + 1):
        for left in range(len(pixels[0]) - width + 1):
            if all(pixels[top + y][left + x] == v for x, y, v in marks):
                return left, top
    return None


def patch(save_dir: pathlib.Path, slot: str, heads, bodies) -> list[dict]:
    """Set each character's portrait pair, and say what each record now holds."""
    head = dos.FIELDS_BY_NAME["portrait_head"].offset
    body = dos.FIELDS_BY_NAME["portrait_body"].offset
    out = []
    for n in range(1, 7):
        path = save_dir / f"CHRDAT{slot}{n}.SAV"
        if not path.exists():
            continue
        raw = bytearray(path.read_bytes())
        if heads:
            raw[head] = heads[(n - 1) % len(heads)]
        if bodies:
            raw[body] = bodies[(n - 1) % len(bodies)]
        path.write_bytes(bytes(raw))
        out.append({"file": path.name,
                    "name": raw[1:1 + raw[0]].decode("ascii", "replace"),
                    "portrait_head": raw[head], "portrait_body": raw[body]})
    return out


def rewrite(save_dir: pathlib.Path, game: pathlib.Path, slot: str) -> list[str]:
    """Put each of the slot's own records through the writer, in place.

    The differential that isolates the *writer* from everything else: the
    saved game, the party and the area stay the engine's own, and only the
    285 bytes of each record become ours.  Anything that then behaves
    differently is a byte this writer does not carry.
    """
    tables = portrait_tables.tables_from_dos(game)
    done = []
    for n in range(1, 7):
        path = save_dir / f"CHRDAT{slot}{n}.SAV"
        if not path.exists():
            continue
        char = dos.read_character(path)
        rec, itm, spc, _ = dos.write(dos.to_neutral(char, portraits=tables),
                                     portraits=tables)
        path.write_bytes(rec)
        done.append(path.name)
    return done


def numbers(text: str | None) -> list[int]:
    return [int(n) for n in text.split(",")] if text else []


def put_words(save_dir: pathlib.Path, slot: str, words: str) -> dict[str, int]:
    """Set saved-game words by ECL address: `--words 4AFA=0,4AFD=1`.

    The bisect handle.  A behaviour that follows the saved game rather than
    the records is narrowed by putting one region of it back to what the
    engine's own save holds and running again, which is cheaper than reading
    the overlay that consumes it.
    """
    path = save_dir / f"SAVGAM{slot}.DAT"
    data = bytearray(path.read_bytes())
    done = {}
    for pair in (w for w in words.split(",") if w):
        where, _, value = pair.partition("=")
        sg.put_word(data, int(where, 16), int(value))
        done[where.upper()] = int(value)
    path.write_bytes(bytes(data))
    return done


def make(*, c64: pathlib.Path | None, slot: str, heads: list[int],
         bodies: list[int], keys: list[str], out: pathlib.Path,
         rewritten: bool = False, templated: bool = False,
         words: str = "") -> dict:
    """Stage, patch, boot, open each sheet, and identify what it drew."""
    out.mkdir(parents=True, exist_ok=True)
    game = dosbox.find_game()
    report: dict = {"slot": slot, "keys": keys}

    with dosbox.claim("portraitshot") as claimed:
        s = dosbox.Session(claimed, game)
        try:
            s.stage(fresh=True)
            if c64 is not None:
                save0 = load_payload(str(c64), POOL_OF_RADIANCE.save_file)
                try:
                    save1 = load_payload(str(c64),
                                         POOL_OF_RADIANCE.roster_file)
                except Exception:
                    save1 = None
                if templated:
                    # The staged tree's own shipped saved game, kept, and
                    # only the party replaced: the differential that says
                    # whether a behaviour belongs to the records or to the
                    # 13137 bytes `new_dos_save` builds from nothing.
                    keep = s.save_dir.parent / "SAVE-AS-TEMPLATE"
                    shutil.rmtree(keep, ignore_errors=True)
                    shutil.copytree(s.save_dir, keep)
                    dos.write_dos_save(save0, save1, keep, s.save_dir,
                                       slot, game=s.game_dir)
                else:
                    dos.new_dos_save(save0, save1, s.save_dir, slot,
                                     s.game_dir)
                report["c64"] = str(c64)
                report["templated"] = templated
            if rewritten:
                report["rewritten"] = rewrite(s.save_dir, s.game_dir, slot)
            report["records"] = patch(s.save_dir, slot, heads, bodies)
            if words:
                report["words"] = put_words(s.save_dir, slot, words)

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(slot)
            world = por.world_bar or por.bar()
            por.s.key("v")
            por.s.settle()
            shots = [str(shutil.copy(s.shot("sheet"), out / "sheet.png"))]
            for n, key in enumerate(keys, start=1):
                por.s.key(key)
                por.s.settle()
                shots.append(str(shutil.copy(
                    s.shot(f"key{n}-{key}"), out / f"key{n}-{key}.png")))
                report.setdefault("bars", []).append(por.bar())
            report["shots"] = shots

            # What the frame drew, named as art rather than described.
            #
            # The last key is pressed again while nothing matches, because a
            # keystroke sent into a screen the game is still drawing is
            # dropped -- one run in five came back on the stats page with the
            # portrait never shown.  A frame that matches is the only stop
            # condition, so a page that never appears is reported as no hit
            # rather than as a wrong hit.
            tables = portrait_tables.tables_from_dos(s.game_dir)
            report["menu_heads"] = [f"{i:02X}" for i in tables.heads]
            report["menu_bodies"] = [f"{i:02X}" for i in tables.bodies]
            heads_art = art(s.game_dir, "HEAD")
            bodies_art = art(s.game_dir, "BODY")
            drawn: dict[str, list] = {"HEAD": [], "BODY": []}
            for attempt in range(4):
                pixels = frame_indices(por.s.capture())
                for stem, images in (("HEAD", heads_art), ("BODY", bodies_art)):
                    drawn[stem] = [{"id": f"{block:02X}", "at": where}
                                   for block, image in sorted(images.items())
                                   if (where := find(pixels, image))]
                if drawn["HEAD"]:
                    report["attempts"] = attempt + 1
                    break
                if keys:
                    por.s.key(keys[-1])
                    por.s.settle()
            shutil.copy(s.shot("portrait"), out / "portrait.png")
            for stem, hits in drawn.items():
                report[f"{stem.lower()}_drawn"] = hits
            for _ in range(4):
                por.s.key("Escape")
                if por.s.wait_until_ink(dosbox.BAR, world, 5.0):
                    break
        finally:
            s.close()
    report["out"] = str(out)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="Report whether the emulator tooling is installed")
    ap.add_argument("--c64", default=None,
                    help="Convert this C64 save disk first")
    ap.add_argument("--slot", default="A", help="The DOS slot to play")
    ap.add_argument("--heads", default=None,
                    help="portrait_head values, one per character")
    ap.add_argument("--bodies", default=None,
                    help="portrait_body values, one per character")
    ap.add_argument("--words", default="",
                    help="Saved-game words to set first, as ADDR=VALUE in "
                         "hex addresses: 4AFA=0,4AFD=1")
    ap.add_argument("--template", action="store_true",
                    help="Convert on top of the staged tree's own saved "
                         "game instead of building one from nothing")
    ap.add_argument("--rewrite", action="store_true",
                    help="Put the slot's own records through the writer "
                         "first, leaving the saved game alone")
    ap.add_argument("--keys", default="v",
                    help="Keys to press from the character sheet, comma "
                         "separated, with a frame captured after each")
    ap.add_argument("--out", default="work/p57-portraits/shot",
                    help="Where the run's files go")
    args = ap.parse_args(argv)

    if args.check:
        absent = dosbox.missing_tools()
        print("Tools missing:", ", ".join(absent) if absent else "none")
        return 1 if absent else 0

    report = make(c64=pathlib.Path(args.c64) if args.c64 else None,
                  slot=args.slot, heads=numbers(args.heads),
                  bodies=numbers(args.bodies),
                  keys=[k for k in args.keys.split(",") if k],
                  out=pathlib.Path(args.out), rewritten=args.rewrite,
                  templated=args.template, words=args.words)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

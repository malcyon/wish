#!/usr/bin/env python3
"""Open every character's sheet in DOS Pool of Radiance and name the face drawn.

`tools/portraitshot.py` photographs **one** character's sheet and matches the
drawn portrait against every `HEAD<n>.DAX`/`BODY<n>.DAX` block, which is what
settled the one-based reading of `portrait_head` for `#57 (Convert the
character portrait across ports)`.  What that leaves is the acceptance
question: a *party* is converted, and each character has to arrive wearing its
own face rather than its neighbour's.  One sheet cannot answer that -- a
conversion that wrote character 1's pair into all six records would pass it.

So this walks the party.  The route between sheets is the game's own: the
character screen answers `n` with the next character, wrapping at the end.
`--probe` is the escape hatch that found it and re-finds it if it moves --
every candidate key is pressed from a sheet in turn and the frame identified,
so "which key turns the page" is answered by the art that appears rather than
by a guess.

    tools/dosportraitparty.py --c64 work/issue57/PORSAVE12.D64 --out work/x
    tools/dosportraitparty.py --slot A --out work/y          # the shipped party
    tools/dosportraitparty.py --slot A --probe n,Down,Right,plus --out work/z

With `--c64` the party is converted **from nothing** through
`goldbox.dos.new_dos_save`, which is the code `File > Import` runs -- not a
staged copy of what the writer would have produced.  The comparison is then
between the C64 record's own `portrait_head`/`portrait_body` art ids and the
art the DOS game fetched, so a wrong table, a wrong order and a dropped byte
are all visible.

Nothing here writes to the player's archives (`tools.dosbox.Session.stage`
copies the tree) and nothing opens a window on the desktop.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos  # noqa: E402
from goldbox import portraits as portrait_tables  # noqa: E402
from goldbox.d64 import load_payload  # noqa: E402
from goldbox.games import POOL_OF_RADIANCE  # noqa: E402
from tools import dosbox  # noqa: E402
from tools import portraitshot as shot  # noqa: E402

#: The key the character screen answers with the next character in the party.
#: **There is not one.**  Sixteen keys were pressed on a DOS sheet on
#: 2026-09-05 -- `n`, `p`, the four arrows, `Tab`, `2`, space, `Return`,
#: `PgUp`, `PgDn`, numpad `3` and `9`, `+`, `-`, `<`, `>` -- and the art drawn
#: never changed from the first character's.  `docs/117-save-conversion.md`
#: already said `VIEW` is not a list and has no `NEXT`; this settles that the
#: sheet has no route off it either, so `--first` is how the other five are
#: reached.
NEXT = "n"

#: The party, in marching order, inside `SAVGAM<slot>.DAT`: six 41-byte
#: entries from file offset 12809, each a length byte and the record's
#: filename.  The engine loads whoever is named here rather than whatever
#: `CHRDAT<slot><n>.SAV` files exist, which is what makes `--first` a
#: reordering of the party and not a rewrite of anybody's record.
PARTY_AT = 12809
PARTY_STRIDE = 41


def records(save_dir: pathlib.Path, slot: str) -> list[dict]:
    """What each of the slot's records asks for, named as art.

    The record holds a one-based **menu position**; the art id is the entry
    at that position in the fourteen-and-twelve creation menu
    (`goldbox/portraits.py`).  Both are reported, because a conversion that
    wrote the art id straight into the DOS byte would produce a legal-looking
    record that draws the wrong face.
    """
    head = dos.FIELDS_BY_NAME["portrait_head"].offset
    body = dos.FIELDS_BY_NAME["portrait_body"].offset
    out = []
    for n in range(1, 7):
        path = save_dir / f"CHRDAT{slot}{n}.SAV"
        if not path.exists():
            continue
        raw = path.read_bytes()
        out.append({"file": path.name,
                    "name": raw[1:1 + raw[0]].decode("ascii", "replace"),
                    "portrait_head": raw[head], "portrait_body": raw[body]})
    return out


def put_first(save_dir: pathlib.Path, slot: str, index: int) -> list[str]:
    """Move the `index`-th party member to the front of the marching order.

    `VIEW` shows the first character and nothing on the sheet moves off it, so
    this is how the other five are looked at: the party list is swapped in
    `SAVGAM<slot>.DAT` and the save loaded again.  **No record is touched** --
    the six 285-byte files are exactly what the conversion wrote, and the only
    difference between one run and the next is which of them the engine loads
    first.  It is the same reordering a player makes in camp.
    """
    path = save_dir / f"SAVGAM{slot}.DAT"
    data = bytearray(path.read_bytes())

    def entry(n: int) -> slice:
        return slice(PARTY_AT + n * PARTY_STRIDE,
                     PARTY_AT + (n + 1) * PARTY_STRIDE)

    first, other = bytes(data[entry(0)]), bytes(data[entry(index)])
    data[entry(0)], data[entry(index)] = other, first
    path.write_bytes(bytes(data))
    return [bytes(data[entry(n)][1:1 + data[entry(n)][0]]).decode("latin1")
            for n in range(6)]


def expected(rows: list[dict], tables) -> list[dict]:
    """Add the art id each record's menu position names."""
    for row in rows:
        h, b = row["portrait_head"], row["portrait_body"]
        row["head_art"] = (f"{tables.heads[h - 1]:02X}"
                           if 1 <= h <= len(tables.heads) else None)
        row["body_art"] = (f"{tables.bodies[b - 1]:02X}"
                           if 1 <= b <= len(tables.bodies) else None)
    return rows


def identify(por, heads_art, bodies_art) -> dict:
    """Which head and body block the frame on screen is drawing."""
    pixels = shot.frame_indices(por.s.capture())
    out = {}
    for stem, images in (("head", heads_art), ("body", bodies_art)):
        out[stem] = [f"{block:02X}" for block, image in sorted(images.items())
                     if shot.find(pixels, image)]
    return out


def sheets(por, s, out: pathlib.Path, count: int, heads_art, bodies_art,
           key: str) -> list[dict]:
    """`VIEW`, then the next character, `count` times."""
    seen: list[dict] = []
    por.s.key("v")
    por.s.settle()
    for index in range(count):
        # The stats page already carries the portrait -- top right, over the
        # panel -- so no second keystroke is needed to reach it.  A frame is
        # taken twice because a keystroke into a screen the game is still
        # drawing is dropped, and a page that never appeared must read as no
        # hit rather than as the previous character's face.
        drawn = identify(por, heads_art, bodies_art)
        if not drawn["head"]:
            por.s.settle()
            drawn = identify(por, heads_art, bodies_art)
        shutil.copy(s.shot(f"sheet{index}"), out / f"sheet-{index}.png")
        seen.append({"index": index, **drawn})
        print(f"  sheet {index}: head {drawn['head']} body {drawn['body']}")
        if index + 1 < count:
            por.s.key(key)
            por.s.settle()
    return seen


def probe(por, s, out: pathlib.Path, keys: list[str], heads_art,
          bodies_art) -> list[dict]:
    """Press each key from the first sheet and say what the frame then draws.

    The route between characters is the thing being looked for, so the answer
    wanted is "the art changed to somebody else's", not "the screen changed".
    """
    por.s.key("v")
    por.s.settle()
    first = identify(por, heads_art, bodies_art)
    print(f"  sheet: head {first['head']} body {first['body']}")
    rows = [{"key": None, **first}]
    for n, key in enumerate(keys, start=1):
        por.s.key(key)
        por.s.settle()
        drawn = identify(por, heads_art, bodies_art)
        shutil.copy(s.shot(f"probe{n}-{key}"), out / f"probe-{n}-{key}.png")
        print(f"  after {key!r}: head {drawn['head']} body {drawn['body']}")
        rows.append({"key": key, **drawn})
    return rows


def sequence(por, s, out: pathlib.Path, keys: list[str]) -> list[str]:
    """Press keys from the **map** and photograph after each.

    The route-finding half of `--probe`, for a route that does not start on a
    character sheet: nothing is identified, because what is wanted is the
    screen a person would see.
    """
    shots = [str(shutil.copy(s.shot("seq0"), out / "seq-0.png"))]
    for n, key in enumerate(keys, start=1):
        por.s.key(key)
        por.s.settle()
        shots.append(str(shutil.copy(s.shot(f"seq{n}-{key}"),
                                     out / f"seq-{n}-{key}.png")))
        print(f"  pressed {key!r}")
    return shots


def run(*, c64: pathlib.Path | None, slot: str, out: pathlib.Path,
        count: int, keys: list[str], key: str,
        walk: list[str] | None = None, first: int = 0) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    game = dosbox.find_game()
    report: dict = {"slot": slot, "c64": str(c64) if c64 else None}

    with dosbox.claim("dosportraitparty") as claimed:
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
                written = dos.new_dos_save(save0, save1, s.save_dir, slot,
                                           s.game_dir)
                report["unwritten"] = len(written.unwritten)
                report["warnings"] = list(written.warnings)
            tables = portrait_tables.tables_from_dos(s.game_dir)
            report["records"] = expected(records(s.save_dir, slot), tables)
            if first:
                report["order"] = put_first(s.save_dir, slot, first)
                print(f"  marching order: {', '.join(report['order'])}")
            for row in report["records"]:
                print(f"  {row['name']:<16} position "
                      f"{row['portrait_head']}/{row['portrait_body']} "
                      f"-> art {row['head_art']}/{row['body_art']}")

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(slot)
            world = por.world_bar or por.bar()
            heads_art = shot.art(s.game_dir, "HEAD")
            bodies_art = shot.art(s.game_dir, "BODY")
            if walk:
                report["sequence"] = sequence(por, s, out, walk)
            elif keys:
                report["probe"] = probe(por, s, out, keys, heads_art,
                                        bodies_art)
            else:
                report["drawn"] = sheets(por, s, out, count, heads_art,
                                         bodies_art, key)
            for _ in range(6):
                por.s.key("Escape")
                if por.s.wait_until_ink(dosbox.BAR, world, 5.0):
                    break
        finally:
            s.close()
    (out / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--c64", default=None,
                    help="convert this C64 save disk into the slot first, "
                         "from nothing")
    ap.add_argument("--slot", default="A", help="the DOS slot to play")
    ap.add_argument("--count", type=int, default=6,
                    help="how many sheets to open")
    ap.add_argument("--next", default=NEXT, dest="key",
                    help="the key the character screen answers with the "
                         "next character")
    ap.add_argument("--probe", default="",
                    help="press these keys from the first sheet instead, "
                         "comma separated, and name the art after each")
    ap.add_argument("--first", type=int, default=0,
                    help="swap this party member to the front before "
                         "booting, so `VIEW` shows them: 1-5")
    ap.add_argument("--sequence", default="",
                    help="press these keys from the map instead, comma "
                         "separated, photographing after each")
    ap.add_argument("--out", default="work/issue57/dosparty",
                    help="where the run's files go")
    args = ap.parse_args(argv)

    report = run(c64=pathlib.Path(args.c64) if args.c64 else None,
                 slot=args.slot, out=pathlib.Path(args.out),
                 count=args.count,
                 keys=[k for k in args.probe.split(",") if k],
                 key=args.key,
                 walk=[k for k in args.sequence.split(",") if k],
                 first=args.first)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

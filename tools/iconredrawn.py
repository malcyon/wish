#!/usr/bin/env python3
"""The two combat-figure options Silver Blades re-drew, as a page to look at
(`#335`).

`#335 (Two combat-figure rows describe Pool of Radiance's art, and Silver
Blades draws those two options differently)` ends in a judgement, and a
judgement about a picture cannot be made from a table of pixel counts.  This
draws the three figures each of the two rows is about, side by side and
scaled up, into one self-contained HTML file:

* the DOS figure **as Pool of Radiance draws it** -- the drawing every row of
  `tools/iconproposal.yaml` was chosen by looking at;
* the DOS figure **as Secret of the Silver Blades draws it** -- the drawing a
  Silver Blades player actually picked;
* the **C64 figure** the row currently names, composed the way a conversion
  composes it.

Both poses of each, and then a gallery of the C64 options that could be
chosen instead, numbered, so an answer can be a number.

    tools/iconredrawn.py
    tools/iconredrawn.py --out work/issue335/silver-blades-figures.html

The rows come from `tools/iconproposal.yaml` at run time, so the page can
never show a mapping that is no longer the one in the table.  Which two
options diverge is not assumed either: the two `.DAX` files are compared
block for block, the way `tools/dosicontitles.py` compares them, and the page
is drawn from whatever that comparison finds.

The DOS art is read out of the player's own game folders under
`$FR_ARCHIVES`, the C64 art off their own `SILVER-1.D64`; nothing is written
except the page named by `--out`.  **The page is the game's own art and lives
under `work/`, never in the repository.**
"""

from __future__ import annotations

import argparse
import base64
import pathlib
import sys
import tempfile

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import dosicontitles as dit  # noqa: E402
import iconcorrespond as ic  # noqa: E402
import iconproposal as ip  # noqa: E402

from goldbox import icons  # noqa: E402
from goldbox.iconparts import PART_CLASSES, IconParts  # noqa: E402
from tools import gamedisks  # noqa: E402

#: The title whose art every row of the table was chosen by looking at, and
#: the title whose art this page compares against it.
REFERENCE = "pool-of-radiance"
SUBJECT = "secret-of-the-silver-blades"

#: A shape cell holding no part.
SPACE = 0x20

#: What each of the two kinds is called in the file that holds it, and which
#: way round `iconproposal.dos_figure` wants its two indices.
KINDS = {"CHEAD.DAX": "head", "CBODY.DAX": "weapon"}

#: The size byte a race gets, in the words the player would use.
WHO = {"large": "humans, elves and half-elves",
       "small": "dwarves, gnomes and halflings"}


# -- what actually differs ---------------------------------------------------
def redrawn(reference: pathlib.Path, subject: pathlib.Path) -> list[dict]:
    """Every option the subject title draws differently, one row each.

    Both poses of one option collapse into a single row: the option, the
    size, and what each side's blocks draw.  Measured rather than assumed,
    so a page can never describe a divergence that has gone away.
    """
    rows: dict[tuple[str, int, str], dict] = {}
    for name, kind in KINDS.items():
        ref, mine = dit.blocks(reference / name), dit.blocks(subject / name)
        for bid in sorted(set(ref) & set(mine)):
            if ref[bid] == mine[bid]:
                continue
            option, size, _pose = dit.option_of(bid)
            row = rows.setdefault((kind, option, size), {
                "kind": kind, "option": option, "size": size,
                "poses": 0, "changed": 0, "compared": 0,
                "parts_reference": set(), "parts_subject": set()})
            changed, compared = dit.differing_pixels(ref[bid], mine[bid])
            row["poses"] += 1
            row["changed"] += changed or 0
            row["compared"] += compared
            row["parts_reference"] |= set(dit.parts_used(ref[bid]))
            row["parts_subject"] |= set(dit.parts_used(mine[bid]))
        for key, row in rows.items():
            if key[0] == kind:
                row["gained"] = sorted(row["parts_subject"]
                                       - row["parts_reference"])
                row["lost"] = sorted(row["parts_reference"]
                                     - row["parts_subject"])
    return [rows[k] for k in sorted(rows)]


def draws(parts: IconParts, size: str, kind: str, option: int) -> list[str]:
    """Which named part classes one C64 menu option puts on the figure."""
    shape = parts.apply(bytes([SPACE] * 18), parts.size_for(size, kind, option),
                        kind, option)
    return sorted({PART_CLASSES[parts.part_class(g)]
                   for g in shape if g != SPACE})


def candidates(parts: IconParts, size: str, kind: str, wanted: str,
               present: bool) -> list[int]:
    """Every C64 option of this kind that does, or does not, draw `wanted`."""
    return [o for o in range(parts.count(size, kind))
            if (wanted in draws(parts, size, kind, o)) is present]


# -- drawing -----------------------------------------------------------------
def _uri(path: pathlib.Path) -> str:
    return ("data:image/png;base64,"
            + base64.b64encode(path.read_bytes()).decode("ascii"))


class Drawer:
    """One figure per call, as a data URI, through `iconproposal.save_figure`.

    The PNGs go to a temporary directory and are read straight back, because
    the page is one file Donald can move anywhere and a page of loose images
    beside it is not.
    """

    def __init__(self, tmp: pathlib.Path, scale: int) -> None:
        self.tmp, self.scale, self.n = tmp, scale, 0
        #: The gallery is a shortlist to pick from rather than a comparison,
        #: so it is drawn smaller and fits on one line.
        self.small = max(3, scale // 2)

    def _next(self) -> pathlib.Path:
        self.n += 1
        return self.tmp / f"{self.n}.png"

    def dos(self, game: pathlib.Path, size: str, kind: str, option: int,
            colours: bytes) -> str:
        body, head = ((option, 0) if kind == "weapon" else (0, option))
        path = self._next()
        ip.save_figure(ip.dos_figure(game, size, body, head, colours),
                       ic.EGA, path, self.scale)
        return _uri(path)

    def c64(self, parts: IconParts, charset: bytes, size: str, kind: str,
            option: int, colours: bytes, small: bool = False) -> str:
        weapon, head = ((option, ip.HEADS[0]) if kind == "weapon"
                        else (ip.WEAPONS[0], option))
        px = ip.c64_figure(parts, charset, size, weapon, head, colours)
        path = self._next()
        ip.save_figure([px[:24], px[24:48]], tuple(icons.C64_PALETTE), path,
                       self.small if small else self.scale)
        return _uri(path)


# -- the page ----------------------------------------------------------------
STYLE = """
body { background: #1d1f21; color: #e8e8e8; margin: 2em auto; max-width: 72em;
       padding: 0 1.5em; font-family: system-ui, sans-serif; line-height: 1.5; }
h1 { font-size: 1.6em; } h2 { font-size: 1.2em; margin-top: 2.2em; }
figure { margin: 0; text-align: center; padding: 8px; border-radius: 5px;
         background: #303030; border: 1px solid #4a4a4a; }
figure img { image-rendering: pixelated; display: block; }
figcaption { font-size: 0.85em; color: #c8c8c8; margin-top: 0.5em;
             max-width: 19em; }
.row { display: flex; gap: 1.5em; align-items: flex-start; flex-wrap: wrap; }
.mine { border-color: #ffe08a; }
.mine figcaption { color: #ffe08a; }
.gallery { display: flex; gap: 1em; flex-wrap: wrap; margin-top: 0.6em; }
.gallery figcaption { max-width: none; font-size: 1em; }
.says { border-left: 3px solid #ffe08a; padding-left: 1em; margin: 1.2em 0; }
.ask { border: 1px solid #555; padding: 0.4em 1.4em; margin-top: 2.5em;
       background: #26282b; }
"""

INTRO = """
<p>You are converting a character from DOS <em>Secret of the Silver
Blades</em> to the Commodore 64. The character's record says which combat
figure the player chose &mdash; a body and a head, picked from the DOS game's
own menu. Wish looks those two numbers up in your table
(<code>tools/iconproposal.yaml</code>, read as it stands now) and draws the
Commodore 64 figure the table names.</p>

<p>Every row of that table was chosen by looking at <em>Pool of Radiance's</em>
drawing of the option. Silver Blades re-drew two of them, so for those two
rows the Commodore 64 figure was matched to a picture no Silver Blades player
ever saw. Every picture below shows the figure's two poses, the way the combat
screen alternates them, in the colours a newly made character starts with.</p>
"""


def page(subject: pathlib.Path, reference: pathlib.Path, disk: pathlib.Path,
         colours: bytes, scale: int, tmp: pathlib.Path) -> str:
    parts = IconParts.load(str(disk))
    charset = icons.load_icon_charset(str(disk))
    draw = Drawer(tmp, scale)
    out = ["<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
           "<title>Two combat figures Silver Blades draws differently</title>",
           f"<style>{STYLE}</style></head><body>",
           "<h1>Two combat figures Silver Blades draws differently</h1>",
           INTRO]
    rows = redrawn(reference, subject)
    for row in rows:
        kind, option, size = row["kind"], row["option"], row["size"]
        table = ip.WEAPONS if kind == "weapon" else ip.HEADS
        chosen = table[option]
        noun = "head" if kind == "head" else "body"
        out.append(f"<h2>The {noun} numbered {option}, on the smaller figures"
                   if size == "small" else
                   f"<h2>The {noun} numbered {option}, on the larger figures")
        out.append(f" &mdash; {WHO[size]}</h2>")
        out.append("<div class='row'>")
        out.append(_figure(
            draw.dos(reference, size, kind, option, colours),
            "Pool of Radiance draws it like this. This is the picture your "
            "table was matched against."))
        out.append(_figure(
            draw.dos(subject, size, kind, option, colours),
            "Silver Blades draws it like this. This is what the player saw "
            "when they picked it.", mine=True))
        out.append(_figure(
            draw.c64(parts, charset, size, kind, chosen, colours),
            f"Your table sends it to Commodore 64 {kind} {chosen}, and this "
            "is what arrives."))
        out.append("</div>")
        out.append(f"<p class='says'>{_sentence(row, parts, size, kind, chosen)}"
                   "</p>")
        out.append(_gallery(draw, parts, charset, row, size, kind, chosen,
                            colours))
    out.append(ASK)
    out.append("</body></html>")
    return "\n".join(out)


def _figure(uri: str, caption: str, mine: bool = False) -> str:
    klass = " class='mine'" if mine else ""
    return (f"<figure{klass}><img src='{uri}' alt=''>"
            f"<figcaption>{caption}</figcaption></figure>")


def _sentence(row: dict, parts: IconParts, size: str, kind: str,
              chosen: int) -> str:
    """One line saying what a Silver Blades player would see differently."""
    has = draws(parts, size, kind, chosen)
    if "cap" in row["gained"]:
        wears = ("wears one too" if "cap" in has
                 else "is bare-headed, because it draws hair and nothing else")
        return ("Silver Blades puts a hat on this head where Pool of Radiance "
                "leaves it bare, so a character who picked it arrives on the "
                f"Commodore 64 with a figure that {wears}.")
    if "weapon" in row["lost"]:
        holds = ("still carries one" if "weapon" in has
                 else "carries nothing either")
        return ("Silver Blades draws this figure without the weapon Pool of "
                "Radiance puts in its hands, so a character who picked it "
                f"arrives on the Commodore 64 with a figure that {holds}. The "
                "grey stroke still beside the hand is the same grey as the "
                "shadow under the feet: it is what is left of the haft, and "
                "the game no longer paints any of it in the weapon colour.")
    return ("The two titles draw this option differently; the Commodore 64 "
            "figure beside them is the one your table names.")


def _gallery(draw: Drawer, parts: IconParts, charset: bytes, row: dict,
             size: str, kind: str, chosen: int, colours: bytes) -> str:
    """The Commodore 64 options that show what Silver Blades shows."""
    if "cap" in row["gained"]:
        wanted, present = "cap", True
        lead = ("The Commodore 64 heads that wear something, if you would "
                "rather Silver Blades used one of them:")
    elif "weapon" in row["lost"]:
        wanted, present = "weapon", False
        lead = ("The Commodore 64 figures of this size that hold nothing, if "
                "you would rather Silver Blades used one of them:")
    else:
        return ""
    out = [f"<p>{lead}</p><div class='gallery'>"]
    for option in candidates(parts, size, kind, wanted, present):
        tag = f"{option}" + (" (the one now)" if option == chosen else "")
        out.append(_figure(draw.c64(parts, charset, size, kind, option,
                                    colours, small=True), tag))
    out.append("</div>")
    return "".join(out)


#: The question the page ends on.  Nothing in it counts the rows, so it stays
#: true whatever the comparison finds.
ASK = """
<div class='ask'>
<h2>What to decide</h2>
<p>For each figure above, one of:</p>
<ul>
<li><strong>Leave it.</strong> Every converted character keeps the figure the
table gives it today, and a Silver Blades character who picked one of these
arrives on the Commodore 64 as the figure you matched to Pool of Radiance's
drawing rather than to the one he was looking at.</li>
<li><strong>Pick a different Commodore 64 figure, for Silver Blades only.</strong>
Name a number from the gallery. The table has no way to say &ldquo;this row,
but only for this game&rdquo; today, so choosing one is also a decision to give
it one.</li>
</ul>
<p>If a figure should change for one size and not the other, say so: Silver
Blades re-drew each of these at only one of its two sizes, so the same option
now draws two different things depending on the character's race.</p>
</div>
"""


# -- where the art is --------------------------------------------------------
def c64_disk(given: str | None) -> pathlib.Path:
    """`SILVER-1.D64`: `--disk`, then `gamedisks.toml`'s Silver Blades entry."""
    if given:
        return pathlib.Path(given).expanduser()
    found = gamedisks.find(SUBJECT)
    if found is None:
        raise SystemExit("no Secret of the Silver Blades C64 disks; pass "
                         "--disk, or set $SSB_DISKS")
    for name in ("SILVER-1.D64", "SILVER-1.d64"):
        if (found / name).is_file():
            return found / name
    raise SystemExit(f"no SILVER-1.D64 under {found}; pass --disk")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archives", help="the Forgotten Realms archives root")
    ap.add_argument("--disk", help="the C64 Silver Blades disk to read the "
                                   "combat art off")
    ap.add_argument("--colours", default=ip.DEFAULT_COLOURS.hex(),
                    help="the record's six icon_colours bytes, as hex")
    ap.add_argument("--scale", type=int, default=6,
                    help="how many screen pixels one figure pixel becomes")
    ap.add_argument("--out", default="work/issue335/silver-blades-figures.html",
                    help="where to write the page, under work/")
    args = ap.parse_args(argv)
    colours = bytes.fromhex(args.colours)
    if len(colours) != 6:
        raise SystemExit("--colours is six bytes: twelve hex digits")
    folders = dit.find_folders(dit.archives(args.archives),
                               [REFERENCE, SUBJECT])
    missing = [k for k in (REFERENCE, SUBJECT) if k not in folders]
    if missing:
        raise SystemExit(f"no game folder for {', '.join(missing)}")
    out = pathlib.Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        html = page(folders[SUBJECT], folders[REFERENCE],
                    c64_disk(args.disk), colours, args.scale,
                    pathlib.Path(tmp))
    out.write_text(html)
    print(f"{out}  {len(html)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

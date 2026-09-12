#!/usr/bin/env python3
"""Which byte of a DOS ability pair is the score in force, and which is the base.

`#401 (Which byte of a DOS ability pair is the current score, now that the
C64's two arrays are named)`.  From Curse of the Azure Bonds onward a DOS
record keeps every ability **twice, side by side**: strength at `0x010` and
`0x011`, intelligence at `0x012` and `0x013`, and so on to charisma at `0x01A`
and `0x01B`, with the exceptional-strength percentile at `0x01C` and `0x01D`.
Every record this project can reach holds the two bytes of a pair equal, so no
saved game can separate them and the answer has to come out of the engine.

    tools/dosabilitypair.py sites --game CURSE
    tools/dosabilitypair.py census --game SECRET
    tools/dosabilitypair.py read ~/wish-specimens/coab-dos/WISH-SPEC-...
    tools/dosabilitypair.py stage --save in/ --out work/x/ \\
        --set PHILIPPE:str=18/9 --set SHARA:str=9/17

`sites` is the answer: six instruction signatures, each read out of the
shipped `GAME.OVR` rather than out of anybody's notes, and each one saying
which byte of the pair a routine treats as the character's own permanent
score.  `census` is the shape around them -- how many byte accesses in the
overlay name each displacement -- and it is a linear scan of an undifferentiated
byte stream, so read it as a shape and never as a count of instructions
(`tools/dosfieldrefs.py` has the same caveat at length).

`read` prints both bytes of every pair in a save directory or a single
`CHRDAT*.SAV`.  `stage` copies a save and writes the two bytes of one pair
apart, which is what a run in the emulator needs: `--set NAME:ab=first/second`
puts `first` at the lower address and `second` at the higher one.  **Both are
inputs and neither proves anything on its own** (`.claude/rules/testing.md`) --
the measurement is the sheet the game draws afterwards and the bytes the engine
writes back.

The player's archives and the specimen tree are opened read only; `stage`
writes only into `--out`.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from tools import dosbox  # noqa: E402

#: The seven pairs and the lower address of each, in the order the record
#: holds them.  `goldbox/dos_port.py` declares the same offsets for the
#: 422-, 439- and 510-byte shapes; Pool of Radiance keeps one byte apiece and
#: has no pairs at all.
PAIRS: dict[str, int] = {
    "str": 0x010, "int": 0x012, "wis": 0x014, "dex": 0x016,
    "con": 0x018, "cha": 0x01A, "exstr": 0x01C,
}

#: Instruction signatures, with `.` standing for a stack displacement that
#: differs between titles.  Every one was matched in the shipped Curse
#: `GAME.OVR` first and then in the other four DOS engines of the family.
#: The names say what the routine does; what each one *means* is in the table
#: `sites` prints under it.
SIGNATURES: tuple[tuple[str, bytes, str], ...] = (
    ("recompute-seed",
     rb"\xd1\xe0\xc4\x7e.\x03\xf8\x26\x8a\x45\x10",
     "shl ax,1 / les di,[bp+player] / add di,ax / mov al,es:[di+0x10]: "
     "read the *lower* byte of pair `ax/2`"),
    ("recompute-store",
     rb"\x8a\x46.\xc4\x7e.\x26\x88\x45\x11",
     "mov al,[bp+var] / les di,[bp+player] / mov es:[di+0x11],al: "
     "store a computed strength into the *higher* byte"),
    ("creation-copy-abilities",
     rb"\x26\x8a\x55\x11\x8a\x46.\x98\xd1\xe0\xc4\x7e.\x03\xf8\x26\x88\x55\x10",
     "mov dl,es:[di+0x11] ... mov es:[di+0x10],dl: the loop that ends "
     "character creation, copying the higher byte of each pair onto the lower"),
    ("creation-copy-exceptional",
     rb"\x26\x8a\x45\x1c\xc4\x7e.\x26\x88\x45\x1d",
     "mov al,es:[di+0x1C] / mov es:[di+0x1D],al: the same copy for the "
     "exceptional-strength percentile, and it runs the *other way*"),
    ("is-stronger",
     rb"\x26\x3a\x45\x10\x77.\x80\x7e.\x12\x75.\x8a\x46.\xc4\x7e.\x26\x3a\x45\x1d",
     "cmp al,es:[di+0x10] ... cmp al,es:[di+0x1D]: one routine comparing a "
     "candidate 18/xx against the character's own score, and the pair it "
     "reads is (0x10, 0x1D)"),
    ("weaken",
     rb"\x26\x80\x7d\x11\x03",
     "cmp es:[di+0x11],3: the strength drain's floor test, on the higher byte"),
    ("weaken-store",
     rb"\x26\xfe\x4d\x11",
     "dec byte es:[di+0x11]: the drain itself, on the higher byte"),
)

#: The `es:`-prefixed byte accesses through `[di+disp8]` a linear scan can
#: recognise, by their first three bytes.
OPCODES: dict[bytes, str] = {
    b"\x26\x8a\x45": "mov al,es:[di+%02X]",
    b"\x26\x8a\x55": "mov dl,es:[di+%02X]",
    b"\x26\x88\x45": "mov es:[di+%02X],al",
    b"\x26\x88\x55": "mov es:[di+%02X],dl",
    b"\x26\xfe\x45": "inc byte es:[di+%02X]",
    b"\x26\xfe\x4d": "dec byte es:[di+%02X]",
    b"\x26\x80\x7d": "cmp es:[di+%02X],imm",
    b"\x26\x3a\x45": "cmp al,es:[di+%02X]",
}


def overlay(game: str, name: str = "GAME.OVR") -> pathlib.Path:
    """The overlay file of one DOS title, inside the player's archives.

    `tools/dosbox.py`'s finder wants a `START.EXE` beside it, which is right
    for the two titles this project drives and wrong for the three it only
    reads: Pools of Darkness boots `STARTUP.EXE` and both Savage Frontier
    games boot `START1.EXE`.  So the directory is looked for by name when the
    harness cannot find it, and nothing outside the archives is opened.
    """
    try:
        return dosbox.find_game(game) / name
    except FileNotFoundError:
        for collection in sorted(dosbox.ARCHIVES.glob("*/games/*/GAME/*")):
            if collection.name.upper() == game.upper():
                found = collection / name
                if found.is_file():
                    return found
        raise


def _records(where: pathlib.Path) -> list[pathlib.Path]:
    """Every `CHRDAT*.SAV` under `where`, or `where` itself if it is one."""
    if where.is_file():
        return [where]
    return sorted(p for p in where.iterdir()
                  if p.name.upper().startswith("CHRDAT")
                  and p.name.upper().endswith(".SAV"))


def record_name(data: bytes) -> str:
    """The character's name: a count byte at `0x000` and text after it."""
    return data[1:1 + data[0]].decode("latin-1", "replace").strip()


def sites(args) -> int:
    """Every signature, in the shipped overlay of one title."""
    path = overlay(args.game, args.file)
    data = path.read_bytes()
    print(f"=== {args.game} {path.name}, {len(data)} bytes")
    for name, pattern, what in SIGNATURES:
        hits = [m.start() for m in re.finditer(pattern, data, re.S)]
        shown = ", ".join(f"{h:#07x}" for h in hits[:args.limit])
        more = "" if len(hits) <= args.limit else f", +{len(hits) - args.limit}"
        print(f"{name:26} {len(hits):3}  {shown}{more}")
        if args.verbose:
            print(f"{'':26}      {what}")
    return 0


def census(args) -> int:
    """How many byte accesses in the overlay name each pair displacement."""
    path = overlay(args.game, args.file)
    data = path.read_bytes()
    counts: collections.Counter = collections.Counter()
    for prefix in OPCODES:
        for m in re.finditer(re.escape(prefix), data):
            disp = data[m.end()]
            if 0x10 <= disp <= 0x1D:
                counts[(disp, prefix)] += 1
    print(f"=== {args.game} {path.name}, {len(data)} bytes")
    print("A linear scan of a byte stream: an upper bound, not a count of "
          "instructions.")
    lower = sum(n for (d, _), n in counts.items() if d % 2 == 0 and d <= 0x1A)
    upper = sum(n for (d, _), n in counts.items() if d % 2 == 1 and d <= 0x1B)
    for disp in range(0x10, 0x1E):
        total = sum(n for (d, _), n in counts.items() if d == disp)
        detail = "  ".join(f"{OPCODES[p] % disp} {n}"
                           for (d, p), n in sorted(counts.items())
                           if d == disp)
        print(f"0x{disp:02X}  {total:3}  {detail}")
    print(f"six abilities: lower bytes {lower}, higher bytes {upper}")
    return 0


def read(args) -> int:
    """Both bytes of every pair, for every record of a save."""
    where = pathlib.Path(args.save).expanduser()
    for path in _records(where):
        data = path.read_bytes()
        pairs = "  ".join(
            f"{ab}={data[off]}/{data[off + 1]}" for ab, off in PAIRS.items())
        print(f"{path.name:14} {record_name(data):16} {pairs}")
    return 0


def _apply(data: bytearray, spec: str) -> str:
    """`NAME:ability=first/second` written into one record."""
    who, _, rest = spec.partition(":")
    ability, _, values = rest.partition("=")
    first, _, second = values.partition("/")
    if ability not in PAIRS or not second:
        raise SystemExit(f"bad --set {spec!r}: want NAME:ability=first/second")
    off = PAIRS[ability]
    was = (data[off], data[off + 1])
    data[off], data[off + 1] = int(first), int(second)
    return (f"{who} {ability} {was[0]}/{was[1]} -> "
            f"{data[off]}/{data[off + 1]} at {off:#05x}")


def stage(args) -> int:
    """Copy a save and write the two bytes of a pair apart."""
    src = pathlib.Path(args.save).expanduser()
    out = pathlib.Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.iterdir()):
        if path.is_file():
            (out / path.name).write_bytes(path.read_bytes())
    wanted: dict[str, list[str]] = collections.defaultdict(list)
    for spec in args.set:
        wanted[spec.split(":", 1)[0].upper()].append(spec)
    for path in _records(out):
        data = bytearray(path.read_bytes())
        keys = {record_name(data).upper(), path.stem.upper()}
        touched = False
        for key in keys:
            for spec in wanted.pop(key, []):
                print(f"{path.name}: {_apply(data, spec)}")
                touched = True
        if touched:
            path.write_bytes(bytes(data))
    for key, specs in wanted.items():
        print(f"no record named {key} for {', '.join(specs)}", file=sys.stderr)
    return 1 if wanted else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn, helptext in (
            ("sites", sites, "the instruction signatures, in one overlay"),
            ("census", census, "how often each displacement is named")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--game", default="CURSE", help="game directory stem")
        p.add_argument("--file", default="GAME.OVR", help="the overlay file")
        p.add_argument("--limit", type=int, default=6,
                       help="sites: how many offsets to print per signature")
        p.add_argument("--verbose", action="store_true",
                       help="sites: say what each signature is")
        p.set_defaults(fn=fn)

    rd = sub.add_parser("read", help="both bytes of every pair in a save")
    rd.add_argument("save", help="a save directory or one CHRDAT*.SAV")
    rd.set_defaults(fn=read)

    st = sub.add_parser("stage", help="write the two bytes of a pair apart")
    st.add_argument("--save", required=True, help="the save directory to copy")
    st.add_argument("--out", required=True, help="where the copy goes")
    st.add_argument("--set", action="append", default=[], metavar="SPEC",
                    help="NAME:ability=first/second, ability one of "
                         + ", ".join(PAIRS))
    st.set_defaults(fn=stage)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

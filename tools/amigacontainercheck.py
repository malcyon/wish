#!/usr/bin/env python3
"""Check that a built Amiga saved game carries the source save's own place.

    tools/amigacontainercheck.py                       every C64 specimen
    tools/amigacontainercheck.py SAVE.d64 OTHER.d64    two named saves
    tools/amigacontainercheck.py --data-disk pool2.adf --game-disk pool1.adf
    tools/amigacontainercheck.py --out work/issue316/container.md

`goldbox.amiga_por.new_por_savegame` builds all 13,141 bytes of a
`savgam<letter>.dat` from the save being converted, so a converted party
arrives on its own square at its own clock rather than on the one SSI shipped
(`#316 (Write the Amiga Pool of Radiance saved game from the source save, so a
converted party arrives where it was standing)`).  This is the check of that
claim from outside the writer: for every C64 Pool of Radiance save it is
given, it prints where the source save says the party is, where the container
built from it says the party is, and which of those fields differ from the
shipped `savgamA.dat`.  Exit status 0 when every save's container matches its
own source, 1 when one does not, 2 when there was nothing to check.

**The two ends must not share a reader, and that is the whole reason the
result means anything.**  :func:`c64_fields` reads the C64 payload *by hand*
at the ECL addresses the C64 engine uses -- offset = address minus
:data:`ECL_BASE` -- and :func:`container_fields` reads the built file at fixed
numeric offsets, big-endian, rather than through `goldbox.amiga_por.por_word` or
`goldbox.world_state`.  A later editor tidying either of them into a call to
the library being checked would leave a tool that agrees with the writer by
construction and cannot fail: `tests/test_amigacontainercheck.py` asserts the
two readers name no library accessor, so that edit turns a test red instead of
turning this into a transcript.

`goldbox.d64.load_payload` is used to lift `SAVEDGAME0` out of the disk image,
which is a container reader rather than a field reader: it drops a two-byte
PRG load address and knows nothing about squares or clocks.

Where the files come from
-------------------------
* the C64 saves: `$WISH_SPECIMENS` then `~/wish-specimens`, `por-c64/`, the
  same rule `tools/specimens.py` uses -- or any `.d64` named on the command
  line;
* the Amiga disks: `tools/gamedisks.py`'s `amiga` entry, which is `$AMIGA_DISKS`
  then the committed search list, unless `--data-disk` and `--game-disk` name
  images.  `$POR_DISKS` is the C64 game disks and holds no `.adf`, so it is
  not the lookup for this one.

Everything is opened read-only; the only file written is `--out`.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga_por, c64_port  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from goldbox.d64 import load_payload  # noqa: E402

#: The base of the ECL variable space all three ports share.  A C64
#: `SAVEDGAME0` payload is a memory image based here, so a field's offset in
#: it is its ECL address minus this; the Amiga container holds the same space
#: as big-endian words, two bytes per address, from its own byte 0.
ECL_BASE = 0x4900

#: The addresses this check reads, in the C64 engine's own numbering.
#: `docs/141-dos-savegame.md` for what each holds; they are spelled out here
#: rather than imported so that this tool and the writer under test share no
#: constant either.
POSITION = 0x49C0          # x, y, facing -- three bytes, facing 0-3
TRAVEL = 0x49C3            # the travel-grid square, window-local
GEO = 0x49C5               # the resident map file
CLOCK = 0x49C6             # six digits
CLOCK_DIGITS = 6
INDOORS = 0x49E6           # zero when the party is on the travel grid
AREA = 0x49F2              # the script -- which area the party is in

#: The Amiga container's own tail, by fixed offset.  13,141 bytes: 5120 of
#: variable array, 7680 of staged script, a thirteen-byte tail and a
#: 328-byte name table.
CONTAINER_SIZE = 13141
TAIL_X = 12800
TAIL_Y = 12801
TAIL_FACING = 12802        # the C64's facing, doubled
TAIL_VIEW = 12810          # 1 = 3D, 3 = the travel grid
TAIL_MODE = 12811          # 2 = camp
TAIL_COUNT = 12812         # how many characters the slot holds

#: The saved game Pool of Radiance disk 1 ships in slot A, and the container a
#: converted party used to be wrapped in.
SHIPPED = "/save/savgamA.dat"
ECL_DAX = "/ecl.dax"

#: Fields the writer **declines** to write, with the reason it gives.  Each is
#: a measured rule rather than a dropped field, so a difference here is
#: reported as `declared` rather than as a mismatch -- and reported, rather
#: than hidden, because a rule that quietly stops applying is what this tool
#: exists to catch.
DECLARED_OUTDOORS = {
    "geo": "zero outdoors: a travel window loads a SQRDATA rather than a GEO",
    "x": "the indoor square is left stale outdoors; the travel square is live",
    "y": "the indoor square is left stale outdoors; the travel square is live",
}
DECLARED_INDOORS = {
    "travel": "no travel square is written for a party that is not on the "
              "travel grid",
}

#: What a row can say about one field.
MATCHED, DECLARED, MISMATCH = "matched", "declared", "MISMATCH"


# ---------------------------------------------------------------------------
# The two readers, which share nothing
# ---------------------------------------------------------------------------

def c64_fields(payload: bytes) -> dict:
    """Where a C64 `SAVEDGAME0` payload says the party is standing.

    Read by hand at `address - ECL_BASE`, deliberately: nothing here calls
    `goldbox.world_state`, `goldbox.c64_save` or any other field reader, so
    this side of the comparison cannot agree with the writer by construction.
    """
    def byte(address: int) -> int:
        return payload[address - ECL_BASE]

    return {
        "x": byte(POSITION),
        "y": byte(POSITION + 1),
        "facing": byte(POSITION + 2),
        "travel": (byte(TRAVEL), byte(TRAVEL + 1)),
        "geo": byte(GEO),
        "clock": tuple(byte(CLOCK + i) for i in range(CLOCK_DIGITS)),
        "outdoors": not byte(INDOORS),
        "area": byte(AREA),
    }


def container_fields(save: bytes) -> dict:
    """Where a 13,141-byte Amiga saved game says the party is standing.

    Read at fixed offsets, deliberately: the variable array is big-endian
    words at `2 * (address - ECL_BASE)` and the square is three plain bytes at
    the tail.  Nothing here calls `goldbox.amiga_por.por_word`.
    """
    if len(save) != CONTAINER_SIZE:
        raise ValueError(
            f"an Amiga Pool of Radiance saved game is {CONTAINER_SIZE} bytes, "
            f"got {len(save)}")

    def word(address: int) -> int:
        at = 2 * (address - ECL_BASE)
        return int.from_bytes(save[at:at + 2], "big")

    return {
        "x": save[TAIL_X],
        "y": save[TAIL_Y],
        "facing": save[TAIL_FACING],
        "travel": (word(TRAVEL), word(TRAVEL + 1)),
        "geo": word(GEO),
        "clock": tuple(word(CLOCK + i) for i in range(CLOCK_DIGITS)),
        "outdoors": not word(INDOORS),
        "area": word(AREA),
        "view": save[TAIL_VIEW],
        "mode": save[TAIL_MODE],
        "count": save[TAIL_COUNT],
    }


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------

def expected(source: dict) -> dict:
    """What each field of the container should hold, given the source save.

    Facing is doubled, which is what both the DOS and the Amiga container
    store; everything else is the source save's own value except where
    :data:`DECLARED_OUTDOORS` or :data:`DECLARED_INDOORS` says the writer
    declines to write it.
    """
    want = {
        "x": source["x"],
        "y": source["y"],
        "facing": source["facing"] * 2,
        "travel": source["travel"],
        "geo": source["geo"],
        "clock": source["clock"],
        "area": source["area"],
        "outdoors": source["outdoors"],
    }
    return want


def compare(source: dict, built: dict) -> list[tuple]:
    """One row per field: `(field, wanted, got, verdict, why)`.

    A field the writer declares it does not write is `declared` rather than
    `matched` when it differs, and `matched` when it happens to agree -- the
    outdoor specimens' stale indoor square is (0, 0) as often as not.
    """
    want = expected(source)
    declared = DECLARED_OUTDOORS if source["outdoors"] else DECLARED_INDOORS
    rows = []
    for name, wanted in want.items():
        got = built[name]
        if got == wanted:
            rows.append((name, wanted, got, MATCHED, ""))
        elif name in declared:
            rows.append((name, wanted, got, DECLARED, declared[name]))
        else:
            rows.append((name, wanted, got, MISMATCH, ""))
    return rows


def differs_from(built: dict, shipped: dict) -> list[str]:
    """Which of the place-and-clock fields are not the shipped container's.

    An empty list is not a failure on its own -- a party standing where SSI's
    does, at SSI's clock, is a legitimate save -- but across a set of
    specimens it is what says the container is built rather than copied.
    """
    return [name for name in ("x", "y", "facing", "clock", "area", "geo")
            if built[name] != shipped[name]]


# ---------------------------------------------------------------------------
# The files
# ---------------------------------------------------------------------------

def specimen_saves(root: pathlib.Path) -> list[pathlib.Path]:
    """Every C64 Pool of Radiance save in a specimen tree, sorted.

    `por-c64/` holds Curse and Silver Blades specimens too, so the glob is on
    the `por` prefix; a disk that turns out not to carry `SAVEDGAME0` is
    reported by the run rather than filtered out here.
    """
    where = root / "por-c64"
    if not where.is_dir():
        return []
    return sorted(p for p in where.glob("WISH-SPEC-por*")
                  if p.suffix.lower() == ".d64")


def specimen_root(named: str | None = None) -> pathlib.Path:
    from tools import specimens

    return pathlib.Path(named) if named else specimens.tree_root()


def _amiga_file(images, path: str, size: int | None = None) -> bytes | None:
    """The first Amiga image carrying `path`, as that file's bytes.

    `size` guards against another Gold Box title answering: the Curse save
    disk carries a `save/savgamA.dat` of its own and it is 15,221 bytes where
    Pool of Radiance's is 13,141.
    """
    for _label, data in images:
        try:
            got = AmigaDisk(bytearray(data)).read_file(path)
        except Exception:
            continue
        if size is None or len(got) == size:
            return got
    return None


def amiga_files(data_disk: str | None, game_disk: str | None
                ) -> tuple[bytes | None, bytes | None]:
    """`(ecl.dax, the shipped savgamA.dat)`, either of which may be `None`.

    Named images are read first and on their own; without them the search is
    `tools/gamedisks.py`'s `amiga` entry, which is where every other tool here
    looks for an `.adf`.
    """
    named = []
    for path in (data_disk, game_disk):
        if path:
            named.append((path, pathlib.Path(path).read_bytes()))
    if named:
        images = named
    else:
        from tools import amigasaves, gamedisks

        if not gamedisks.candidates("amiga"):
            return None, None
        images = list(amigasaves.images())
    return (_amiga_file(images, ECL_DAX),
            _amiga_file(images, SHIPPED, CONTAINER_SIZE))


def build(payload: bytes, source: str, ecl_dax: bytes, slot: str,
          count: int) -> tuple[bytes, object]:
    """The container `goldbox.amiga_por` builds for this save. The thing under
    test, and the only call into it."""
    state = amiga_por.por_state_from_c64(payload, source)
    return amiga_por.new_por_savegame(state, slot, count, ecl_dax)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _place(fields: dict) -> str:
    """One line of place and clock, with the clock's six digits kept.

    The digits are printed as well as the time they spell, because the digits
    are what the two readers actually compared: the fourth is the hour and the
    third and second are the minutes, which is how the game's own status line
    is built out of them.
    """
    digits = fields["clock"]
    clock = f"{digits[3]:02d}:{digits[2]}{digits[1]}"
    raw = ",".join(str(d) for d in digits)
    where = (f"travel {fields['travel'][0]},{fields['travel'][1]}"
             if fields["outdoors"]
             else f"({fields['x']},{fields['y']}) f{fields['facing']}")
    return (f"{where} clock {clock} [{raw}] area {fields['area']} "
            f"geo {fields['geo']}")


def report(saves, ecl_dax: bytes, shipped: bytes | None, slot: str,
           count: int) -> tuple[list[str], bool]:
    """The whole run, as lines to print and whether every container matched."""
    lines = ["| save | the source save says | the container says | "
             "differs from shipped in | bytes accounted |",
             "|---|---|---|---|---|"]
    notes: list[str] = []
    ok = True
    checked = 0
    ship = container_fields(shipped) if shipped else None
    save_file = c64_port.by_key("pool-of-radiance").save_file
    for path in saves:
        try:
            payload = load_payload(str(path), save_file)
            source = c64_fields(payload)
        except Exception as e:
            notes.append(f"* `{path.name}`: not a C64 Pool of Radiance save "
                         f"({e})")
            continue
        try:
            built_bytes, rep = build(payload, str(path), ecl_dax, slot, count)
        except Exception as e:
            notes.append(f"* `{path.name}`: **refused** -- {e}")
            continue
        built = container_fields(built_bytes)
        rows = compare(source, built)
        bad = [r for r in rows if r[3] == MISMATCH]
        told = [r for r in rows if r[3] == DECLARED]
        checked += 1
        ok = ok and not bad
        lines.append(
            f"| {path.name} | {_place(source)} | {_place(built)} | "
            f"{', '.join(differs_from(built, ship)) if ship else '-'} | "
            f"{len(rep.sources)}, {len(rep.unwritten)} unwritten |")
        for name, wanted, got, _verdict, why in told:
            notes.append(f"* `{path.name}` {name}: {got} against the source's "
                         f"{wanted} -- {why}")
        for name, wanted, got, _verdict, _why in bad:
            notes.append(f"* `{path.name}` {name}: **{got} against the "
                         f"source's {wanted}**")
    lines.append("")
    lines.append(f"{checked} save(s) checked, "
                 f"{'every' if ok else 'not every'} container carries its own "
                 f"source's place and clock.")
    if notes:
        lines.append("")
        lines.extend(notes)
    return lines, ok and checked > 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("saves", nargs="*",
                        help="C64 .d64 saves; the specimen tree by default")
    parser.add_argument("--specimens",
                        help="the specimen tree; $WISH_SPECIMENS by default")
    parser.add_argument("--data-disk",
                        help="Amiga game disk 2, which carries /ecl.dax")
    parser.add_argument("--game-disk",
                        help="Amiga game disk 1, for the shipped savgamA.dat")
    parser.add_argument("--slot", default="B",
                        help="which slot letter to build for (default B)")
    parser.add_argument("--count", type=int, default=6,
                        help="how many characters the slot holds (default 6)")
    parser.add_argument("-o", "--out", help="write the report here")
    args = parser.parse_args(argv)

    saves = [pathlib.Path(p) for p in args.saves]
    if not saves:
        root = specimen_root(args.specimens)
        saves = specimen_saves(root)
        if not saves:
            print(f"no C64 Pool of Radiance saves under {root}/por-c64; name "
                  f"one, or set $WISH_SPECIMENS", file=sys.stderr)
            return 2
    ecl_dax, shipped = amiga_files(args.data_disk, args.game_disk)
    if ecl_dax is None:
        print("no Amiga disk here carries /ecl.dax, and the area's script is "
              "the one thing a container cannot be built without. It is on "
              "Pool of Radiance disk 2, the POOLDATA volume; name it with "
              "--data-disk, or set $AMIGA_DISKS", file=sys.stderr)
        return 2
    lines, ok = report(saves, ecl_dax, shipped, args.slot, args.count)
    text = "\n".join(lines) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

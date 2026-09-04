#!/usr/bin/env python3
"""Census the DOS saved game's variable array across every specimen present.

`#59 (Map the DOS saved game, not just the character record)` grades most of
`docs/141-dos-savegame.md` on counts -- "2401 of 2560 words are zero in all
twelve specimens", "byte 12807 is 2 in all twelve".  Those counts were taken
against a corpus that has since changed: eight of the twelve files lived under
`work/` and are gone, and `tools/dosoutdoor.py` and `#26`'s runs have made
engine-written ones the original pass never had.  A count nobody can re-take
is a count that rots, so this is the thing that re-takes it.

What it does, and it reads only -- it never writes a saved game:

1. **Finds every `SAVGAM*.DAT` on this machine** -- the played party in the
   Steam `SavesDir`, the shipped ones under each title's `Default files/Saves`
   and `GAME/*/SAVE`, and anything named on the command line (`work/p26/run*`,
   `work/p50-outdoor`) -- and **deduplicates on the bytes**, because the
   archives ship most save directories twice.
2. **Classifies each specimen**: its area, whether it stands indoors, its
   square, its clock, its party size, its wallset triple, and whether its ECL
   buffer is a real script or 7680 zeroes.  A save whose buffer is zero and
   whose clock is 00:00 is a **shipped stub**, not a played party, and is
   excluded from the counts by default -- `--include-stubs` keeps it.
3. **Censuses all 2560 `u16le` variables**: how many are zero in every
   specimen, which are not, and what value each takes per specimen.  The
   *partition* -- which specimens agree with which -- is what names a field,
   so it prints that rather than only the values.

`--word $49C5` reports one address across the corpus; `--tail` reports bytes
12801-12808; `--nonzero` lists every live word with its per-specimen values.

Nothing here is a claim about what a variable *means*.  It reports what the
specimens hold, which is the evidence a claim has to rest on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import areas  # noqa: E402
from goldbox import dos_savegame as sg  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent


def _roots() -> list[pathlib.Path]:
    """Where the DOS archives might be, by the project's own search list."""
    from tools import gamedisks
    return [p for p in gamedisks.candidates("dos-archives") if p.is_dir()]


#: A file we assembled rather than one the engine wrote.  Kept out of every
#: count: a seed is a thing we put together and is not evidence about what the
#: engine does with it.  `work/p26/issue191/built/SAVGAMA.DAT` carries no
#: prefix, so the directory name is the second test.
HAND_BUILT_PREFIXES = ("BUILT-", "SEED-")
HAND_BUILT_DIRS = ("built",)


def hand_built(path: pathlib.Path) -> bool:
    return (path.stem.startswith(HAND_BUILT_PREFIXES)
            or path.parent.name in HAND_BUILT_DIRS)


def find_saves(extra: list[pathlib.Path] | None = None,
               shape: "sg.DosSaveShape | None" = None) -> list[pathlib.Path]:
    """Every saved game of one title's size, deduplicated on its bytes.

    **The size is the filter rather than the directory name.** Each title in
    the family writes its own length -- 13137, 13149, 5469, 1364 -- so asking
    for Pool of Radiance drops a Curse container out of the same sweep without
    needing a path rule, and asking for Curse picks its containers up wherever
    they are. Curse and Silver Blades put the variable array at Pool of
    Radiance's offset with the same ECL addresses (`docs/141-dos-savegame.md`),
    so the whole census is meaningful for them; Pools of Darkness has no
    variable array at all and only the specimen table is worth reading.
    """
    shape = shape or sg.SAVE_POOL_OF_RADIANCE
    seen: dict[str, pathlib.Path] = {}
    found: list[pathlib.Path] = []
    where = list(_roots()) + list(extra or [])
    for root in where:
        if not root.exists():
            continue
        # `*SAVGAM*` already covers the `BUILT-`/`SEED-`/`RESAVE-` prefixes,
        # so matching `SAVGAM*` as well would read every unprefixed file twice
        # for the deduplicator to throw the second copy away.  The sort key
        # puts unprefixed names first, so that if a seed ever were byte for
        # byte an engine-written save, the surviving entry is the one whose
        # name does not claim we assembled it.
        paths = ([root] if root.is_file()
                 else sorted(list(root.rglob("*SAVGAM*.DAT"))
                             + list(root.rglob("*SAVGAM*.PTY")),
                             key=lambda p: (hand_built(p), str(p))))
        for path in paths:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if len(data) != shape.size:
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen[digest] = path
            found.append(path)
    return found


def _label(path: pathlib.Path) -> str:
    """A short name a reader can tell apart: the parent dir and the slot.

    The `BUILT-`/`SEED-` prefix is kept rather than stripped: a file we
    assembled is not evidence about what the engine writes, and collapsing the
    two into one name is how a hand-built save gets counted as a specimen.
    """
    stem = path.stem
    kind = ""
    for prefix in ("BUILT-", "SEED-", "RESAVE-"):
        if stem.startswith(prefix):
            kind = prefix[0].lower()
            stem = stem[len(prefix):]
    slot = stem.replace("SAVGAM", "")
    parent = path.parent
    if parent.name in {"English", "SAVE", "Saves"}:
        # `.../SavesDir/<id>/<appid>/English` and `.../GAME/POOLRAD/SAVE`.
        # Pools of Darkness and Treasures of the Savage Frontier write the
        # same 1364 bytes, so the game folder has to be in the name or the
        # two titles' containers appear in one sweep as four files with two
        # names -- `docs/141-dos-savegame.md`, "the size names the shape".
        tag = "steam" if "SavesDir" in str(path) else "shipped"
        for up in path.parents:
            if up.parent.name == "games":
                tag = f"{tag}/{up.name.split()[0].lower()}"
                break
    else:
        tag = parent.name
        if parent.parent.name.startswith("issue"):
            tag = f"{parent.parent.name}/{tag}"
    return f"{tag}:{kind}{slot}"


def _buffer_zero(save: bytes, shape: sg.DosSaveShape) -> bool:
    """Is the staged ECL script all zeroes?  A title without one answers no."""
    span = shape.script_buffer
    if span is None:
        return False
    return not any(save[span[0]:span[1]])


def describe(path: pathlib.Path,
             shape: "sg.DosSaveShape | None" = None) -> dict:
    """What a reader needs in order to tell one specimen from another.

    Every reading that a title does not have comes back `None` rather than
    being computed off Pool of Radiance's offsets -- Pools of Darkness has no
    container byte and no variable array, and a number read there would be a
    plausible-looking lie.
    """
    save = path.read_bytes()
    shape = sg.save_shape_for(shape or len(save))
    x, y, facing = sg.position(save, shape)
    out = {
        "label": _label(path),
        "path": str(path),
        "title": shape.title,
        "sha": hashlib.sha256(save).hexdigest()[:12],
        "square": [x, y, facing],
        "party_size": sg.party_size(save, shape),
        "tail": list(save[shape.square:shape.square + 8]),
        "hand_built": hand_built(path),
        "dax_byte": save[shape.head] if shape.dax_bytes else None,
    }
    if not shape.var_words:
        # Pools of Darkness: no variable array, so no area, clock or flags.
        out.update(area=None, area_name=None, indoors=None, travel=None,
                   clock=None, disk_word=None, wallset=None, wallmap=None,
                   flags=None, stub=None)
        return out
    area = sg.current_area(save)
    where = areas.area(area)
    out.update(
        area=area,
        area_name=where.name if where else "?",
        indoors=sg.outdoors(save) is False,
        travel=list(sg.travel_square(save)),
        clock=list(sg.clock(save)),
        disk_word=sg.word(save, sg.DISK),
        wallset=list(sg.wall_triple(save)),
        wallmap=[sg.word(save, sg.WALLMAP + i) for i in range(3)],
        flags=sum(1 for a in range(sg.FLAGS_FIRST, sg.FLAGS_LAST + 1)
                  if sg.word(save, a)),
        stub=_buffer_zero(save, shape) and not any(sg.clock(save)),
    )
    return out


def words(save: bytes, shape: sg.DosSaveShape) -> list[int]:
    return [sg.word(save, sg.VAR_BASE + i, shape)
            for i in range(shape.var_words)]


def census(specimens: list[dict], saves: list[bytes],
           shape: sg.DosSaveShape) -> dict:
    """Per-word values across the corpus, and the zero-everywhere count.

    A title with no variable array needs no special case: `var_words` is 0,
    so `words` returns nothing and the loop does not run. There was an early
    return here for Pools of Darkness and it was dead -- removing it changed
    no test, which is what said so.
    """
    table = [words(s, shape) for s in saves]
    live: dict[str, list[int]] = {}
    for i in range(shape.var_words):
        column = [t[i] for t in table]
        if any(column):
            live[f"${sg.VAR_BASE + i:04X}"] = column
    return {
        "specimens": [s["label"] for s in specimens],
        "words_total": shape.var_words,
        "zero_everywhere": shape.var_words - len(live),
        "live": live,
    }


def _parse_addr(text: str) -> int:
    return int(text.lstrip("$"), 16) if text.startswith("$") else int(text, 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("extra", nargs="*", type=pathlib.Path,
                    help="Extra files or directories to sweep")
    ap.add_argument("--title", default="pool-of-radiance",
                    help="Which title's containers to sweep: "
                         + ", ".join(s.key for s in sg.SAVE_SHAPES))
    ap.add_argument("--include-stubs", action="store_true",
                    help="Keep shipped stubs in the counts")
    ap.add_argument("--include-built", action="store_true",
                    help="Keep hand-built seeds in the counts (they are not "
                         "evidence about what the engine writes)")
    ap.add_argument("--word", action="append", default=[],
                    help="Report one address, e.g. $49C5")
    ap.add_argument("--nonzero", action="store_true",
                    help="List every live word with its per-specimen values")
    ap.add_argument("--tail", action="store_true",
                    help="Report the eight bytes of the square block")
    ap.add_argument("--json", action="store_true", help="Machine-readable")
    args = ap.parse_args(argv)

    shape = sg.save_shape_for(args.title)
    paths = find_saves(args.extra, shape)
    if not paths:
        print(f"no {shape.title} saved games found", file=sys.stderr)
        return 1
    specimens = [describe(p, shape) for p in paths]

    def counted(s: dict) -> bool:
        if s["hand_built"] and not args.include_built:
            return False
        return bool(args.include_stubs) or not s["stub"]

    kept = [(s, p) for s, p in zip(specimens, paths) if counted(s)]
    saves = [p.read_bytes() for _, p in kept]
    report = census([s for s, _ in kept], saves, shape)
    report["title"] = shape.title
    report["all_specimens"] = specimens

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    outdoor = sum(1 for s, _ in kept if s["indoors"] is False)
    print(f"{shape.title}: {len(paths)} distinct containers, "
          f"{len(kept)} counted ({len(kept) - outdoor} indoors, "
          f"{outdoor} outdoors), "
          f"{len(paths) - len(kept)} excluded as stubs or hand-built")
    print()
    head = f"{'specimen':<22} {'area':>4} {'in':>3} {'square':>12} " \
           f"{'clock':>14} {'sz':>3} {'wallset':>16} {'flags':>5}"
    print(head)
    print("-" * len(head))
    for s in specimens:
        mark = "" if counted(s) else ("  (built)" if s["hand_built"]
                                      else "  (stub)")
        clock = ("%02d:%02d d%d m%d" % tuple(s["clock"])
                 if s["clock"] and len(s["clock"]) == 4 else "-")
        show = "y" if s["indoors"] else ("n" if s["indoors"] is False else "?")
        print(f"{s['label']:<22} {str(s['area'] if s['area'] is not None else '-'):>4} "
              f"{show:>3} "
              f"{str(s['square']):>12} {clock:>14} {s['party_size']:>3} "
              f"{str(s['wallset'] or '-'):>16} "
              f"{str(s['flags'] if s['flags'] is not None else '-'):>5}{mark}")
    print()
    if shape.var_words:
        print(f"variables: {report['zero_everywhere']} of {shape.var_words} "
              f"words are zero in every counted specimen; "
              f"{len(report['live'])} are live somewhere")
    else:
        print(f"{shape.title} has no ECL variable array "
              f"(#175 is the issue that would decode what is there instead)")

    if args.tail:
        print()
        first = shape.square
        print(f"{'specimen':<22} " + " ".join(f"{n:>5}"
                                              for n in range(first, first + 8)))
        for s in specimens:
            print(f"{s['label']:<22} " +
                  " ".join(f"{b:>5}" for b in s["tail"]))

    for text in args.word:
        addr = _parse_addr(text)
        print()
        print(f"${addr:04X}:")
        for (s, _), save in zip(kept, saves):
            print(f"  {s['label']:<22} {sg.word(save, addr, shape):>6}")

    if args.nonzero:
        print()
        print(f"{'addr':<8} " +
              " ".join(f"{s['label'][:10]:>10}" for s, _ in kept))
        for addr, column in report["live"].items():
            print(f"{addr:<8} " + " ".join(f"{v:>10}" for v in column))
    return 0


if __name__ == "__main__":
    sys.exit(main())

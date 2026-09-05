#!/usr/bin/env python3
"""Which C64 Gold Box title draws a sheet portrait, read off the disks (#300).

`#300 (A Curse or Silver Blades party imported to the C64 arrives with no
sheet portrait, because the creation menu is read only off a POOL<n>.D64)`
asked whether Curse of the Azure Bonds and Secret of the Silver Blades have
sheet-portrait art anywhere.  They do not, and the reason is one step earlier
than the art: **their character-sheet routine has no portrait step at all.**

Pool of Radiance's is `LIBRARY $48A4` -- it reads the record's own
`portrait_head` and `portrait_body`, asks the loader for the `HEAD<xx>` and
`BODY<xx>` files they name, and draws them with two of `ANIMATE00`'s seven
jump-table entries.  Curse's and Silver Blades' `LIBRARY` never calls the
loader at all, and no file on any of their twelve sides calls either of those
two `ANIMATE` entries.

This is the census that says so, re-runnable against the player's own disks:

    tools/portraitdraw.py                        all three C64 titles
    tools/portraitdraw.py --title curse          one of them
    tools/portraitdraw.py --verbose              every call site, with its file

Three measurements per title, none of which needs an emulator:

1. **Where each overlay runs.**  A PRG header on these disks is a family
   stamp rather than a load address (`docs/40-memory-map.md`), so the base is
   found by scoring: for each candidate, take every absolute `JSR`/`JMP`
   target that lands inside the file and count how many decode to a legal
   opcode.  Pool of Radiance's `LIBRARY` scores 166 good to 15 bad at
   `$2C46`, which puts its code at `$2C48` -- `docs/40`'s CONFIRMED value --
   and the next best candidate at 146 to 35.
2. **The loader's two entries**, found by their own code rather than by a
   remembered address: the byte after the 25-entry slot-to-stem table is
   `LDA <cache>,X / CMP #$FF`, which is the "reload slot X if it is dirty"
   entry, and three bytes on is "ensure file A of kind X is loaded"
   (`docs/140-loaded-files-cache.md`).  Then count the calls to those two
   from `LIBRARY` itself, with the slot each one asks for.
3. **`ANIMATE00`'s five entries**, at whatever address that title's own
   loader table gives slot 11.  `+0` and `+$C` draw in the view window at
   screen `$CC7B`; `+6` and `+9` draw at `$CC44`, which is the sheet's
   portrait position, and `+3` steps the animation.  Every file on every side
   is searched for a `JSR` or `JMP` to each.

Nothing is written anywhere: the disks are opened read only, and the disk
directory comes from `tools/gamedisks.py` unless `--disks` says otherwise.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64  # noqa: E402
from tools import d6502, gamedisks  # noqa: E402

#: The three C64 titles this project converts, and where their sides are.
TITLES: tuple[tuple[str, str], ...] = (
    ("pool-of-radiance", "Pool of Radiance"),
    ("curse-of-the-azure-bonds", "Curse of the Azure Bonds"),
    ("secret-of-the-silver-blades", "Secret of the Silver Blades"),
)

#: `LIBRARY`'s slot-to-stem table, which is the same 25 bytes in all three
#: binaries: twenty stems, with `WALLSET` and `WALLDEF` taking three slots
#: each and `CHARPIC` two.  Finding it fixes the load-address tables (25
#: bytes of low bytes 75 back, 25 of high bytes 50 back) and the loader's
#: own code, which begins immediately after it.
SLOT_TO_STEM = bytes([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 15, 16,
                      11, 11, 11, 12, 12, 12, 17, 17, 18, 19])

#: Loader slots 13 and 14: the sheet portrait's body and head.
BODY_SLOT, HEAD_SLOT = 13, 14

#: `ANIMATE00`'s jump table, and what each entry draws.  Read out of the
#: routine itself: `+9` sets frame kind 1 -- the five-row portrait of
#: `docs/181-curse-picture-buffer.md` -- points itself at the `HEAD` slot's
#: load address and draws at screen `$CC44`; `+6` is the same position with
#: the `BODY` slot and kind 0.
ANIMATE_ENTRIES: tuple[tuple[int, str], ...] = (
    (0x0, "a picture in the view window ($CC7B)"),
    (0x3, "step the animation"),
    (0x6, "the sheet portrait's body ($CC44)"),
    (0x9, "the sheet portrait's head ($CC44)"),
    (0xC, "a five-row portrait in the view window ($CC7B)"),
)

#: The two that only a sheet portrait uses.
SHEET_ENTRIES = (0x6, 0x9)


def base_of(data: bytes) -> tuple[int, int, int]:
    """Where `data` loads, by scoring its own `JSR`/`JMP` targets.

    Returns `(base, good, bad)`: the address the file's **first byte** takes,
    so the code proper is at `base + 2` when the first two bytes are a PRG
    header.  A target that lands inside the file and decodes to a documented
    opcode is a good one; anything else is bad.
    """
    targets: set[int] = set()
    for i in range(len(data) - 2):
        if data[i] in (0x20, 0x4C):
            targets.add(data[i + 1] | data[i + 2] << 8)

    def score(base: int) -> tuple[int, int]:
        good = bad = 0
        for a in targets:
            if not base <= a < base + len(data):
                continue
            if data[a - base] in d6502.T:
                good += 1
            else:
                bad += 1
        return good, bad

    best, best_score = 0, (-1, 0)
    for candidate in range(0x0400, 0xC000, 2):
        good, bad = score(candidate)
        if good - bad > best_score[0] - best_score[1]:
            best, best_score = candidate, (good, bad)
    return best, best_score[0], best_score[1]


def library_tables(data: bytes, base: int) -> dict:
    """`LIBRARY`'s slot tables and the two loader entries, or `{}`.

    The anchor is `SLOT_TO_STEM`; everything else is at a fixed distance from
    it, which is the same in all three binaries.
    """
    at = data.find(SLOT_TO_STEM)
    if at < 0:
        return {}
    low, high = data[at - 75:at - 50], data[at - 50:at - 25]
    loads = [lo | hi << 8 for lo, hi in zip(low, high)]
    # `LDA <cache>,X / CMP #$FF / BEQ / AND #$7F / CMP #$7F` -- the
    # dirty-reload entry, which reads the slot's own byte as the request; the
    # ensure entry is the `CMP #$FF` itself, with the caller's A already in
    # hand.  Pool of Radiance and Curse put it immediately after the table
    # and Silver Blades does not, so it is searched for rather than assumed.
    code = -1
    for i in range(len(data) - 12):
        if (data[i] == 0xBD and data[i + 3:i + 5] == b"\xC9\xFF"
                and data[i + 5] == 0xF0 and data[i + 7:i + 9] == b"\x29\x7F"
                and data[i + 9:i + 11] == b"\xC9\x7F"):
            code = i
            break
    if code < 0:
        return {}
    return {
        "cache": data[code + 1] | data[code + 2] << 8,
        "reload_entry": base + code,
        "ensure_entry": base + code + 3,
        "loads": loads,
        "slot_table": base + at,
    }


def calls_to(data: bytes, addr: int) -> list[int]:
    """Every offset in `data` holding a `JSR` or `JMP` to `addr`."""
    out = []
    for op in (0x20, 0x4C):
        pat = bytes([op, addr & 0xFF, addr >> 8])
        i = data.find(pat)
        while i >= 0:
            out.append(i)
            i = data.find(pat, i + 1)
    return out


def slot_asked_for(data: bytes, at: int) -> int | None:
    """The last `LDX #imm` in the fourteen bytes before a loader call."""
    for j in range(at - 2, max(0, at - 16) - 1, -1):
        if data[j] == 0xA2:
            return data[j + 1]
    return None


def sides_of(key: str, disks: str | None) -> list[pathlib.Path]:
    where = pathlib.Path(disks) if disks else gamedisks.find(key)
    if where is None:
        return []
    from goldbox import games
    game = games.by_key(key)
    return sorted(where.glob(game.disk_glob))


def read_named(sides, name: bytes) -> tuple[str, bytes] | tuple[None, None]:
    for side in sides:
        try:
            return side.name, D64(side.read_bytes()).read_file(name)
        except Exception:  # noqa: BLE001 - any refusal means "not this side"
            continue
    return None, None


def survey(key: str, label: str, disks: str | None, verbose: bool) -> dict:
    sides = sides_of(key, disks)
    out: dict = {"title": label, "sides": len(sides)}
    if not sides:
        out["why"] = "no sides found"
        return out

    side, library = read_named(sides, b"LIBRARY")
    if library is None:
        out["why"] = "no LIBRARY on any side"
        return out
    base, good, bad = base_of(library)
    out["library"] = f"{side} @${base + 2:04X} ({good} good / {bad} bad)"
    tables = library_tables(library, base)
    if not tables:
        out["why"] = "LIBRARY's slot tables are not where they are in the "\
                     "other two"
        return out
    out["cache"] = tables["cache"]
    out["animate"] = tables["loads"][11]

    # 1. the sheet portrait's own loader calls, from LIBRARY
    asks: list[tuple[int, int]] = []
    for entry in (tables["ensure_entry"], tables["reload_entry"]):
        for at in calls_to(library, entry):
            asks.append((base + at, slot_asked_for(library, at)))
    out["library_loader_calls"] = sorted(asks)
    out["library_asks_for_art"] = sorted(
        a for a in asks if a[1] in (BODY_SLOT, HEAD_SLOT))

    # 2. every file on every side, against ANIMATE's five entries
    per_entry: dict[int, list[str]] = {e: [] for e, _ in ANIMATE_ENTRIES}
    files = 0
    for image_path in sides:
        image = D64(image_path.read_bytes())
        for entry in image.directory():
            name = entry.raw_name.rstrip(b"\xa0").decode("latin1")
            try:
                data = image.read_file(entry)
            except Exception:  # noqa: BLE001 - a file that will not read
                continue
            files += 1
            for offset, _what in ANIMATE_ENTRIES:
                hits = calls_to(data, out["animate"] + offset)
                if hits:
                    per_entry[offset].append(
                        f"{image_path.name}:{name} x{len(hits)}"
                        if verbose else name)
    out["files"] = files
    out["animate_calls"] = {e: sorted(set(v)) for e, v in per_entry.items()}
    return out


def report(rows: list[dict]) -> None:
    for row in rows:
        print(f"== {row['title']}: {row['sides']} sides")
        if "why" in row:
            print(f"   {row['why']}")
            continue
        print(f"   LIBRARY {row['library']}, loaded-files cache "
              f"${row['cache']:04X}, ANIMATE at ${row['animate']:04X}")
        calls = row["library_loader_calls"]
        if calls:
            print("   LIBRARY calls the loader " + ", ".join(
                f"${a:04X} slot {s}" for a, s in calls))
        else:
            print("   LIBRARY never calls the loader")
        art = row["library_asks_for_art"]
        print(f"   ...of which ask for HEAD/BODY: "
              f"{len(art)}" + (" -- " + ", ".join(
                  f"${a:04X} slot {s}" for a, s in art) if art else ""))
        for offset, what in ANIMATE_ENTRIES:
            who = row["animate_calls"][offset]
            mark = "  <-- the sheet" if offset in SHEET_ENTRIES else ""
            print(f"   ANIMATE +${offset:X} {what:<42} "
                  f"{len(who):3d} file(s){mark}")
            if who and offset in SHEET_ENTRIES:
                print(f"        {', '.join(who)}")
        print(f"   {row['files']} files searched")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", action="append",
                    help="a game key, or part of one; may be repeated")
    ap.add_argument("--disks", help="where that one title's sides are")
    ap.add_argument("--verbose", action="store_true",
                    help="name the side each call site is on")
    args = ap.parse_args(argv)

    wanted = TITLES
    if args.title:
        wanted = tuple(t for t in TITLES
                       if any(w.lower() in t[0] for w in args.title))
        if not wanted:
            print("no title matches", args.title)
            return 2
    if args.disks and len(wanted) != 1:
        print("--disks names one title's sides, so pass one --title with it")
        return 2

    rows = [survey(key, label, args.disks, args.verbose)
            for key, label in wanted]
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

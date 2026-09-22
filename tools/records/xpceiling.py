#!/usr/bin/env python3
"""Whether a DOS character's experience can pass the C64's three bytes.

`#597 (Can a DOS Curse or Silver Blades character hold more experience than
the C64's three bytes?)`: the DOS Curse and Silver Blades records keep
experience in four bytes where every C64 record keeps three, and
`goldbox.c64_codec.write` clamps a value that does not fit to the field's
largest one and records a drop line.  Whether anything can reach that value
is a question about the engine, not about the records anybody happens to
have, so this reads it out of each title's own `GAME.OVR`.

Three things, one per command:

* `sites` -- every instruction addressing the experience longword through a
  segment-prefixed far pointer, with the constant it carries.  A field an
  engine caps has a compare against the cap;
* `check` -- the answer, per title: the 32-bit `add`/`adc` accumulate, the
  largest constant any instruction ever compares the high word against, and
  whether that constant bounds the total below the C64's `0xFFFFFF`;
* `convert` -- a real DOS record with its experience replaced, pushed through
  `goldbox.dos_codec.to_neutral` and `goldbox.c64_codec.write`, which says
  what the conversion does with a value the destination cannot hold.

    tools/records/xpceiling.py check
    tools/records/xpceiling.py sites --title curse-of-the-azure-bonds
    tools/records/xpceiling.py convert RECORD.SAV --value 0x1000000

**What this is evidence of.**  It inherits every limit of
`tools/dos/dosfieldrefs.py`: the overlay is scanned as a byte stream, so a
match may land in data, a displacement match does not prove the pointer is a
character record, and an offset reached without a matching displacement is
invisible.  So "no compare above N" is evidence rather than proof -- a cap
built by loading the ceiling into a register and comparing against that would
not show here, and the `cmp r16,m16` sites this prints are exactly that form
and have to be disassembled (`tools/dos/dosovrwindow.py`) before they can be
called anything.  Archives are read only; nothing here writes a game file.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import c64_codec, dos_codec  # noqa: E402
from goldbox import dos_port as dl  # noqa: E402
from tools.dos import dosbox  # noqa: E402
from tools.dos.dosbyteimm import immediates  # noqa: E402
from tools.dos.dosfieldrefs import references  # noqa: E402

#: The directory stem each title's `GAME.OVR` sits under in the archives.
STEMS = {"pool-of-radiance": "POOLRAD",
         "curse-of-the-azure-bonds": "CURSE",
         "secret-of-the-silver-blades": "SECRET",
         "pools-of-darkness": "DARKNESS"}

#: The widest experience a C64 record can hold: `goldbox/layout.py` keeps the
#: field three bytes in every title.
C64_CEILING = 0xFFFFFF


def experience_offset(key: str) -> int:
    """Where `key`'s DOS record keeps experience."""
    return dl.FIELDS_BY_NAME_FOR[key]["experience"].offset


def overlay(key: str) -> pathlib.Path | None:
    """`key`'s `GAME.OVR` in the player's archives, or `None`.

    Found by the directory it sits in rather than by `dosbox.find_game`,
    which looks for a `START.EXE` beside it: Pools of Darkness ships
    `STARTUP.EXE` instead and would be invisible.
    """
    if not dosbox.ARCHIVES.is_dir():
        return None
    stem = STEMS[key]
    for path in sorted(dosbox.ARCHIVES.rglob("GAME.OVR")):
        if f"/{stem}/" in str(path):
            return path
    return None


def accumulates(image: bytes, offset: int) -> list[int]:
    """Where `image` adds a 32-bit value into the longword at `offset`.

    The pair is `add <seg>:[r+off], r16` then `adc <seg>:[r+off+2], r16` --
    opcodes `0x01` and `0x11` -- on the same base register, which is how a
    16-bit compiler emits `+=` on a `long`.  Finding it is what says the
    engine's running total is 32 bits wide rather than a word the record
    merely has room for.
    """
    out = []
    lo, hi = offset & 0xFF, (offset >> 8) & 0xFF
    lo2, hi2 = (offset + 2) & 0xFF, ((offset + 2) >> 8) & 0xFF
    for i in range(len(image) - 10):
        if image[i + 1] != 0x01 or image[i] not in (0x26, 0x2E, 0x36, 0x3E):
            continue
        add = image[i + 2]
        if add >> 6 != 0b10 or image[i + 3] != lo or image[i + 4] != hi:
            continue
        j = i + 5
        if image[j] != image[i] or image[j + 1] != 0x11:
            continue
        adc = image[j + 2]
        if adc >> 6 != 0b10 or (adc & 7) != (add & 7):
            continue
        if image[j + 3] == lo2 and image[j + 4] == hi2:
            out.append(i)
    return out


def word_sites(image: bytes, offset: int) -> list[dict]:
    """Every segment-prefixed instruction touching the word at `offset`.

    `immediates()` covers `ES`, which is the prefix a far pointer to a
    character record gets; the other three are asked for separately so a
    record reached through `DS`, `SS` or `CS` is not invisible.
    """
    hits = {h["linear"]: h for h in immediates(image, offset)}
    for hit in references(image, offset, prefixes=(0x2E, 0x36, 0x3E)):
        hits.setdefault(hit["linear"], dict(hit, imm=None, op=None))
    return [hits[k] for k in sorted(hits)]


def high_word_constants(image: bytes, offset: int) -> set[int]:
    """Every constant an instruction compares the high word against.

    A cap at the C64's ceiling has to test the high word against `0x0100` or
    more, because `experience >= 0x1000000` is exactly `high >= 0x0100`.  The
    constants that do turn up are the low halves of a title's
    character-creation starting totals.
    """
    return {h["imm"] for h in word_sites(image, offset + 2)
            if h["imm"] is not None and h["mnem"].startswith("cmp")}


def capped_below(image: bytes, offset: int, ceiling: int = C64_CEILING) -> bool:
    """Whether any high-word compare could bound the total at or below
    `ceiling`."""
    want = (ceiling + 1) >> 16
    return any(c >= want for c in high_word_constants(image, offset))


def convert(record: bytes, value: int) -> tuple[str, str]:
    """`(what the DOS record reads back, what the C64 writer did)`.

    The record is copied before the experience is replaced, so the caller's
    bytes -- a file on the player's read-only archive -- are untouched.
    """
    shape = dl.deltas_for(len(record))
    at = experience_offset(shape.key)
    buf = bytearray(record)
    struct.pack_into("<I", buf, at, value)
    dos = dos_codec.DosCharacter(bytes(buf), deltas=shape)
    read_back = dos.get("experience")
    neutral = dos_codec.to_neutral(dos)
    try:
        rec, rep = c64_codec.write(neutral)
    except ValueError as exc:
        return f"{read_back}", f"refused: {exc}"
    wrote = rec.get("experience")
    if wrote == value:
        verdict = "kept"
    else:
        lines = [d for d in rep.losses if d.startswith("experience:")]
        verdict = f"clamped from {value}; lost: {' / '.join(lines)}"
    return f"{read_back}", f"wrote {wrote} ({wrote:#x}) -- {verdict}"


def report_check() -> int:
    """One row a title: the accumulate, the compares, and the verdict."""
    missing = 0
    for key, stem in STEMS.items():
        path = overlay(key)
        if path is None:
            print(f"{key}: no {stem}/GAME.OVR on this machine")
            missing += 1
            continue
        image = path.read_bytes()
        at = experience_offset(key)
        adds = accumulates(image, at)
        consts = sorted(high_word_constants(image, at))
        capped = capped_below(image, at)
        print(f"{key}: experience +{at:#05x}")
        print(f"  32-bit add/adc into the longword: {len(adds)} site(s) "
              + ", ".join(f"{a:#08x}" for a in adds))
        print(f"  constants the high word is compared against: {consts}")
        print(f"  a cap at or below the C64's {C64_CEILING:#x}: "
              f"{'yes' if capped else 'no'}")
    return 1 if missing == len(STEMS) else 0


def report_sites(key: str) -> int:
    path = overlay(key)
    if path is None:
        print(f"no {STEMS[key]}/GAME.OVR on this machine")
        return 1
    image = path.read_bytes()
    at = experience_offset(key)
    for label, off in (("low", at), ("high", at + 2)):
        print(f"-- {key} experience {label} word +{off:#05x}")
        for hit in word_sites(image, off):
            imm = "" if hit["imm"] is None else f" imm={hit['imm']}"
            print(f"   {hit['linear']:#08x} {hit['seg']}[{hit['rm']}] "
                  f"{hit['kind']:2s} {hit['mnem']}{imm}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="the answer, per title")
    s = sub.add_parser("sites", help="every instruction touching the field")
    s.add_argument("--title", default="curse-of-the-azure-bonds",
                   choices=sorted(STEMS))
    c = sub.add_parser("convert", help="a record at a chosen experience")
    c.add_argument("record", type=pathlib.Path)
    c.add_argument("--value", type=lambda v: int(v, 0), default=0x1000000)
    args = ap.parse_args(argv)
    if args.cmd == "check":
        return report_check()
    if args.cmd == "sites":
        return report_sites(args.title)
    read_back, did = convert(args.record.read_bytes(), args.value)
    print(f"{args.record.name}: experience {args.value} ({args.value:#x}) "
          f"reads back {read_back}")
    print(f"  goldbox.c64_codec.write {did}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

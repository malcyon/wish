#!/usr/bin/env python3
"""Decode an area script's packed strings, so a screen capture can be matched
to the statement that printed it.

`#334 (The session driver cannot fight in Curse or Silver Blades, and says the
party is not in a fight while it is standing on the combat floor)` is the
ticket that wanted it. A driven run photographed a line of dialogue and the
question was which `ECL` arm produced it -- and that is the difference between
"the square trigger never fired" and "the square trigger fired and the driver
declined the fight". `tools/eclcensus.py` deliberately prints a string operand
as its byte length, so it cannot answer that.

    ecltext.py secret-of-the-silver-blades ECL10           lengths only
    ecltext.py secret-of-the-silver-blades ECL10 --text    the words
    ecltext.py secret-of-the-silver-blades --find "MARCUS" every script

**The output of `--text` and `--find` is the game's own prose.** It may be read
in a terminal and it must not be pasted into `docs/`, a README, a commit
message or an issue -- `AGENTS.md` bans the game's words from this repository
however they arrive. Without `--text` the tool prints offsets and lengths,
which is safe anywhere.

## The packing

Read out of the title's own `DUNGEON`, at the handler the operand fetch jumps
to for operand kind `$80` -- Silver Blades' is at `$1453`:

* a length byte, then that many bytes of payload;
* the payload is a stream of **six-bit groups, most significant bit first**;
* a group of `$01`-`$1F` is OR'd with `$40`, which is how the letters land on
  `A`-`Z`; `$20`-`$3F` is taken as it stands, which covers space, the comma,
  the full stop, the apostrophe and the digits;
* a group of `$00` terminates the run.

So 81 payload bytes carry 108 characters. The one measurement behind the
whole of this is that `ECL10 +$07B4`, unpacked that way, is character for
character the line in `cited/334/ssb8/04-after-watch.txt`.

Nothing is assumed from Pool of Radiance: the opcode tables and the operand
counts come out of the title's own `DUNGEON` through `tools/eclcensus.py`,
which gets them from the VM's self-modifying dispatch.
"""

from __future__ import annotations

import argparse
import glob
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import disk_globs  # noqa: E402
from goldbox import c64_port  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools import eclcensus  # noqa: E402

#: The operand kind byte that introduces a packed string.
STRING_KIND = 0x80

#: Six bits per character, and the value below which a group is a letter.
BITS = 6
LETTER_TOP = 0x20
LETTER_BIT = 0x40


def unpack(payload: bytes) -> str:
    """The characters a packed run holds, up to its terminator."""
    out: list[str] = []
    accumulator = bits = 0
    for byte in payload:
        for shift in range(7, -1, -1):
            accumulator = (accumulator << 1) | ((byte >> shift) & 1)
            bits += 1
            if bits < BITS:
                continue
            value, accumulator, bits = accumulator, 0, 0
            if value == 0:
                return "".join(out)
            if value < LETTER_TOP:
                value |= LETTER_BIT
            out.append(chr(value))
    return "".join(out)


def strings(machine, body: bytes, base: int):
    """`(offset, opcode, operand, length, text)` for every reachable string.

    Only statements the control-flow walk reaches, for the same reason
    `tools/eclcensus.py` walks rather than sweeps: a linear scan reads the
    data tables `GETTABLE` indexes as instructions and invents strings.
    """
    out = []
    found = eclcensus.walk(machine, body, base)
    for at in sorted(found):
        statement = found[at]
        i = at + 1
        for n, (kind, value) in enumerate(statement.operands):
            if kind == STRING_KIND:
                payload = body[i + 2:i + 2 + value]
                out.append((at, statement.op, n, value, unpack(payload)))
                i += 2 + value
            elif kind == 0x00:
                i += 2
            else:
                i += 3
    return out


def game_for(title: str) -> c64_port.C64Container:
    for candidate in c64_port.GAMES:
        if candidate.key == title or candidate.title == title:
            return candidate
    raise SystemExit(f"No such title: {title}")


def disks(root: str, game: c64_port.C64Container) -> list[str]:
    seen: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in glob.glob(os.path.join(root, pattern)):
            seen.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return sorted(seen.values())


def read_file(root: str, game: c64_port.C64Container, name: str) -> bytes | None:
    """A named file's body, without its two-byte load address."""
    for path in disks(root, game):
        try:
            image = D64.open(path)
        except Exception:
            continue
        for entry in image.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == name:
                return image.read_file(name)[2:]
    return None


def scripts(root: str, game: c64_port.C64Container) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path in disks(root, game):
        try:
            image = D64.open(path)
        except Exception:
            continue
        for entry in image.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if not name.startswith("ECL") or len(name) != 5 or name in out:
                continue
            try:
                int(name[3:], 16)
            except ValueError:
                continue
            out[name] = image.read_file(name)[2:]
    return out


def cmd(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title")
    parser.add_argument("script", nargs="?",
                        help="one script, e.g. ECL10; omit for all of them")
    parser.add_argument("--disks", help="the C64 sides")
    parser.add_argument("--text", action="store_true",
                        help="print the words, not just the lengths")
    parser.add_argument("--find", metavar="PHRASE",
                        help="only strings containing this, case folded")
    args = parser.parse_args(argv)

    game = game_for(args.title)
    root = args.disks or eclcensus.registry(game.key)
    if not root or not os.path.isdir(root):
        raise SystemExit(f"No disks for {game.title}; pass --disks.")

    dungeon = read_file(root, game, "DUNGEON")
    if dungeon is None:
        raise SystemExit(f"No DUNGEON on any {game.title} side under {root}.")
    machine = eclcensus.Machine(dungeon, game.key)

    bodies = scripts(root, game)
    walkable = {}
    for name, body in bodies.items():
        opening = eclcensus.decode(machine, body, 0)
        if opening is not None and opening.op == 1:
            walkable[name] = body
    base = eclcensus.script_base(machine, walkable)
    if args.script:
        if args.script not in walkable:
            raise SystemExit(f"No walkable {args.script} on any side.")
        walkable = {args.script: walkable[args.script]}

    needle = args.find.upper() if args.find else None
    print(f"{game.title}: scripts run at ${base:04X}")
    for name in sorted(walkable):
        for at, op, n, length, text in strings(machine, walkable[name], base):
            if needle and needle not in text.upper():
                continue
            head = (f"  {name}+${at:04X} "
                    f"{eclcensus.OPCODE_NAMES.get(op, f'OP${op:02X}')} "
                    f"operand {n}, {length} bytes, {len(text)} characters")
            print(head + (f": {text}" if args.text or needle else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(cmd())

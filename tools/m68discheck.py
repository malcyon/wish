#!/usr/bin/env python3
"""Check `tools/m68dis.py` against capstone over a real Amiga binary.

`m68dis.py` **refuses to guess**: a word it does not recognise prints as
`dc.w`, never as the nearest instruction that fits. The evidence for that
claim is the run this tool does -- 100 385 instructions of the Amiga *Pools of
Darkness* binary with no length disagreements, no operand disagreements and
nothing capstone decoded that `m68dis` refused (`docs/50-experiments.md`, "The
68000 disassembler"). Getting that answer again is the whole reason this is
kept: a claim about a disassembler is only as old as the last time somebody
ran the comparison.

    tools/m68discheck.py /path/to/amiga-binary.bin

**The mode is not cosmetic and both are run.** In `CS_MODE_M68K_020` capstone
decodes instructions the target CPU does not have, so it reads a `dc.w`
`m68dis` correctly refused as a real instruction -- which is why a comparison
that does not say which mode it used says very little. The 000 run is the one
the write-up rests on; the 020 run is printed underneath for contrast, and
every word the two tools disagree about there is accounted for by name rather
than counted.

The binary is not in this repository and never will be: point this at a copy
of the game's own executable wherever it is kept. `--offset`/`--length`
default to the code hunk of the *Pools of Darkness* binary -- `m68dis` reads a
plain binary at file offsets and does not parse AmigaDOS hunks, so a window
outside the code decodes hunk headers as instructions and the comparison says
nothing.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import m68dis  # noqa: E402

#: The code hunk of the Amiga *Pools of Darkness* binary the write-up used.
DEFAULT_OFFSET = 0x28
DEFAULT_LENGTH = 0x4D2E0

#: 68020-only mnemonics: capstone in 020 mode decodes these and the target
#: CPU has none of them, so `m68dis` refusing the word is the right answer.
ONLY_020 = ("chk.l", "bfext", "bfins", "bfset", "bfclr", "bftst", "divsl",
            "divul", "muls.l", "mulu.l", "trapcc", "pack", "unpk", "rtd",
            "moves", "cas", "cmp2", "chk2")


def norm(text: str) -> str:
    """One spelling for two assemblers' idea of the same operand text."""
    s = text.lower().replace(" ", "").replace("$0x", "$")
    s = re.sub(r"\$0+([0-9a-f])", r"$\1", s)
    s = s.replace("dbf", "dbra")
    s = re.sub(r"^(lea|pea|btst|bset|bclr|bchg|link)\.[bwl]", r"\1", s)
    s = re.sub(r"^(move|exg|nbcd|s[a-z]{2})\.[bwl]", r"\1", s)
    s = s.replace("$0(a", "(a")
    s = re.sub(r"(\$[0-9a-f]+)\.l\b", r"\1", s)
    s = re.sub(r"#\$(f[0-9a-f]{3})\b",
               lambda m: "#-$%x" % (0x10000 - int(m.group(1), 16)), s)
    return s


def why_we_refused(data: bytes, pos: int, ours, theirs) -> str:
    """Why `m68dis` said `dc.w` where capstone printed an instruction."""
    mn, ops = theirs.mnemonic, theirs.op_str
    if mn[0] == "b" and mn[:3] not in ("bch", "bcl", "bse", "bts", "bkp"):
        word = ours.words[0]
        low = word & 0xFF
        if low == 0:
            disp = int.from_bytes(data[pos + 2:pos + 4], "big")
            disp -= 0x10000 if disp & 0x8000 else 0
            target = pos + 2 + disp
        else:
            target = pos + 2 + (low - 0x100 if low & 0x80 else low)
        return ("odd branch target" if target & 1
                else "branch, even target")
    if "*" in ops or "([" in ops or "invalid" in ops:
        return "68020 scaled or memory-indirect index"
    if mn.startswith(ONLY_020):
        return f"68020-only instruction ({mn})"
    return f"68020 index format bit set ({mn})"


def run(cs_mode, label: str, data: bytes, start: int, end: int) -> int:
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_M68K,
                     capstone.CS_MODE_BIG_ENDIAN | cs_mode)
    compared = size_bad = op_bad = 0
    refused_by_us: collections.Counter = collections.Counter()
    refused_by_them = 0
    pos = start
    while pos + 2 <= end:
        ours = m68dis.decode(data, pos)
        theirs = next(md.disasm(data[pos:pos + 12], pos), None)
        decoded = theirs is not None and theirs.mnemonic != "dc.w"
        if not ours.known:
            if decoded:
                refused_by_us[why_we_refused(data, pos, ours, theirs)] += 1
        elif decoded:
            compared += 1
            if theirs.size != ours.size:
                size_bad += 1
                print(f"  ${pos:06X}: length {ours.size} against "
                      f"capstone's {theirs.size}")
            if norm(ours.text) != norm(f"{theirs.mnemonic} {theirs.op_str}"):
                op_bad += 1
                print(f"  ${pos:06X}: {ours.text!r} against capstone's "
                      f"{theirs.mnemonic} {theirs.op_str!r}")
        else:
            refused_by_them += 1
        pos += ours.size
    print(f"--- {label}")
    print(f"  Both decoded it              {compared}")
    print(f"  Length disagreements         {size_bad}")
    print(f"  Operand disagreements        {op_bad}")
    print(f"  capstone refused, we did not {refused_by_them}")
    print(f"  We refused, capstone did not {sum(refused_by_us.values())}")
    for reason, count in refused_by_us.most_common():
        print(f"      {count:6d}  {reason}")
    return size_bad + op_bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Compare tools/m68dis.py with capstone over a binary.")
    ap.add_argument("binary", help="a plain 68000 binary, read at file "
                                   "offsets; not in this repository")
    ap.add_argument("--offset", type=lambda s: int(s, 0),
                    default=DEFAULT_OFFSET, metavar="N",
                    help="where the code starts in the file "
                         "(default: %(default)#x)")
    ap.add_argument("--length", type=lambda s: int(s, 0),
                    default=DEFAULT_LENGTH, metavar="N",
                    help="how much of it is code (default: %(default)#x)")
    args = ap.parse_args(argv[1:])

    try:
        import capstone
    except ImportError:
        print("This needs capstone, which wish does not depend on:\n"
              "    .venv/bin/pip install capstone", file=sys.stderr)
        return 2

    data = pathlib.Path(args.binary).read_bytes()
    start = args.offset
    end = min(len(data), args.offset + args.length)
    print(f"capstone {capstone.__version__}, "
          f"{pathlib.Path(args.binary).name} ${start:06X}-${end:06X}")
    bad = run(capstone.CS_MODE_M68K_000,
              "CS_MODE_BIG_ENDIAN | CS_MODE_M68K_000  "
              "(the mode the write-up rests on)", data, start, end)
    run(capstone.CS_MODE_M68K_020,
        "CS_MODE_BIG_ENDIAN | CS_MODE_M68K_020  (for contrast only)",
        data, start, end)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

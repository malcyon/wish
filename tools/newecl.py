#!/usr/bin/env python3
"""Find a title's `NEWECL` handler, and everything a fast travel needs, by
reading its own `DUNGEON`, `LINKER` and `LIBRARY` rather than by assuming an
address.

`#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
Radiance's alone?)` is the ticket.  A fast travel is `NEWECL`'s own writes made
from outside, with the operand fetch skipped by entering the handler at its
tail -- `docs/118-debug-mode.md` §3.  Every address in that recipe was measured
in Pool of Radiance, and none of them could be assumed to transfer: three are
payload-relative, four are the loader's page, and the rest are overlay code
that moves whenever a routine above it changes size.

    tools/newecl.py pool-of-radiance
    tools/newecl.py curse-of-the-azure-bonds --disks DIR
    tools/newecl.py secret-of-the-silver-blades --against pool-of-radiance

**Nothing here is found by name or by header.** The chain is:

1. `DUNGEON` runs at `$0800`, where `LINKER` puts an overlay it calls, and its
   PRG header does not say so -- Pool of Radiance's claims `$1000` and Curse's
   `$3000` (`#17`, and `docs/118-debug-mode.md`).  `--base` is there for a
   title where `$0800` stops holding; the fit is checked and reported.
2. The script VM's dispatch is a **self-modifying `JSR`**: a `JSR abs` whose
   own two operand bytes are the target of `STA abs` elsewhere in the same
   overlay.  Each `DUNGEON` read so far holds exactly two such calls, and the
   VM's is the one whose stores are three bytes apart, loaded `,X` from two
   tables.  That gives the handler tables without knowing where they are.
3. Opcode `$20` is `NEWECL` (`docs/128-guide-and-scripting.md` §12.3.3), so
   entry `$20` of those tables is the handler.
4. The handler's shape is then **checked against Pool of Radiance's**
   instruction by instruction with the relocations worked out from the
   operands, so a title whose handler is *not* the same routine says so rather
   than handing back a plausible address.
5. The key-wait window and the key fetcher are found by their page-3
   signature -- `$03CB` and `$03F0` do not relocate, because page 3 is the
   KERNAL's.

The output is a table of addresses with the Pool of Radiance column beside it.
Nothing is written, and no byte of the game is printed except the handful an
instruction carries: the disks stay the player's.
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
sys.path.insert(0, str(TOOLS))

import d6502  # noqa: E402

from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox import games  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402

#: Where `LINKER` puts every overlay it dispatches to.
LINKER_BASE = 0x0800

#: `NEWECL`, in every Gold Box opcode table anybody has read.
NEWECL_OPCODE = 0x20

#: The key-wait loop's first two tests, in bytes: `LDA $03CB / CMP #$FF` and
#: `LDA $03F0 / CMP #$1F`.  Page 3 is the KERNAL's, so neither address moves
#: with the save image or with the loader's page, which is what makes this a
#: signature rather than a guess.
KEY_WAIT_SIG = bytes.fromhex("ADCB03C9FF")
#: The key fetcher's first instruction: `LDA $DC00`, the CIA keyboard row.
KEY_FETCH_SIG = bytes.fromhex("AD00DC")


def game_disks(root: str, game: games.Game) -> list[str]:
    """Every one of this title's disk images under `root`, each of them once."""
    seen: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in glob.glob(os.path.join(root, pattern)):
            seen.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return sorted(seen.values())


def load(name: str, root: str, game: games.Game) -> tuple[int, bytes]:
    """The named file's declared load address and its bytes, off any side."""
    for path in game_disks(root, game):
        try:
            image = D64.open(path)
        except Exception:
            continue
        for entry in image.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == name:
                try:
                    return split_load_address(image.read_file(name))
                except Exception as exc:
                    print(f"  ({path}: {name}: {exc})", file=sys.stderr)
                    break
    raise SystemExit(f"No file called {name} on any {game.title} disk "
                     f"under {root}")


def self_modifying_calls(body: bytes, base: int) -> list[tuple[int, int, int]]:
    """Every `JSR abs` whose own operand bytes something in here stores into.

    Returns `(call, low store, high store)` run-time addresses.  A `JSR` with
    both operand bytes written from elsewhere is a dispatch through a table:
    there is no other reason to build a call's target at run time inside a
    single overlay.
    """
    stores: dict[int, list[int]] = {}
    for i in range(len(body) - 2):
        if body[i] == 0x8D:                      # STA abs
            stores.setdefault(body[i + 1] | (body[i + 2] << 8), []).append(
                base + i)
    out = []
    for i in range(len(body) - 2):
        if body[i] != 0x20:                      # JSR abs
            continue
        at = base + i
        if at + 1 in stores and at + 2 in stores:
            out.append((at, stores[at + 1][0], stores[at + 2][0]))
    return out


def dispatch_tables(body: bytes, base: int) -> tuple[int, int, int, int]:
    """`(call, low table, high table, opcode store)` for the script VM.

    The two stores that build the call are each preceded by an `LDA abs,X`
    (`$BD`) whose operand is the table, and the index reached them through an
    `STX abs` (`$8E`) a few bytes before -- that byte is the dispatch's
    "current opcode", which `docs/50-experiments.md` names `$6DDC` in Pool of
    Radiance.

    **There is more than one such dispatch, and the script VM is the big one.**
    `DUNGEON` also dispatches the seven square attributes the same way -- Pool
    of Radiance at `$08A4`, Curse at `$089C` -- so the candidates are ranked by
    how many entries their tables hold and the widest wins.  A table that
    cannot reach opcode `$20` is not the one being looked for, and a title
    where none can is a title this tool refuses rather than guesses at.
    """
    best = None
    for call, lo_store, hi_store in self_modifying_calls(body, base):
        lo_at, hi_at = lo_store - base - 3, hi_store - base - 3
        if lo_at < 0 or hi_at < 0:
            continue
        if body[lo_at] != 0xBD or body[hi_at] != 0xBD:
            continue
        lo_table = body[lo_at + 1] | (body[lo_at + 2] << 8)
        hi_table = body[hi_at + 1] | (body[hi_at + 2] << 8)
        count = hi_table - lo_table
        if count <= NEWECL_OPCODE:
            continue
        opcode_store = 0
        for back in range(3, 8):
            if lo_at - back >= 0 and body[lo_at - back] == 0x8E:
                opcode_store = (body[lo_at - back + 1]
                                | (body[lo_at - back + 2] << 8))
                break
        if best is None or count > best[0]:
            best = (count, call, lo_table, hi_table, opcode_store)
    if best is None:
        raise SystemExit(
            "No table-driven dispatch wide enough to hold opcode $20 in "
            "DUNGEON. Either the base is wrong or this title's VM is built "
            "differently; either way, do not trust an address from here.")
    return best[1], best[2], best[3], best[4]


def handler(body: bytes, base: int, lo_table: int, hi_table: int,
            opcode: int) -> int:
    """One opcode's handler address, out of the two byte tables."""
    lo = body[lo_table - base + opcode]
    hi = body[hi_table - base + opcode]
    return lo | (hi << 8)


def opcode_count(lo_table: int, hi_table: int) -> int:
    """How many opcodes the VM has: the gap between the two byte tables.

    The high table follows the low one immediately in both titles read so far,
    and the operand-count table follows the high one by the same stride, which
    is what makes the count readable rather than assumed.
    """
    return hi_table - lo_table


def instructions(body: bytes, base: int, start: int, span: int):
    """`(address, bytes, text)` for each instruction in a range."""
    out = []
    for line in d6502.lines(body, base, start, span):
        at = int(line[1:5], 16)
        if at >= start + span:
            break
        out.append((at, line[7:16].strip(), line[18:].strip()))
    return out


def operands(text: str) -> str:
    """An instruction with its operand address blanked, for comparison.

    `LDA $6E1B` and `LDA $7F1B` are the same instruction relocated; `LDA $6E1B`
    and `AND #$7F` are not.  Blanking the absolute operand is what lets the two
    handlers be compared instruction for instruction without a relocation
    table having to be known in advance.
    """
    out, i = [], 0
    while i < len(text):
        if text[i] == "$":
            j = i + 1
            while j < len(text) and text[j] in "0123456789ABCDEFabcdef":
                j += 1
            out.append("$" + "?" * (j - i - 1))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def newecl_tail(lines) -> int:
    """The handler's tail: where `CMP #$FF` branches when the operand is `$FF`.

    `docs/118-debug-mode.md` §3: entering there rather than at the handler's
    head is what skips the operand fetch, which needs a script stream a fast
    travel is not in.  Read off the branch rather than counted in bytes,
    because the wipe above it is not the same length in every title.
    """
    for i, (at, _, text) in enumerate(lines):
        if text == "CMP #$FF" and i + 1 < len(lines):
            nxt = lines[i + 1][2]
            if nxt.startswith("BEQ $"):
                return int(nxt[5:], 16)
    return 0


def find_window(body: bytes, base: int, sig: bytes, name: str) -> int:
    """The one place a signature appears, or 0 with a line saying why not."""
    hits = []
    at = body.find(sig)
    while at >= 0:
        hits.append(base + at)
        at = body.find(sig, at + 1)
    if len(hits) == 1:
        return hits[0]
    print(f"  {name}: {len(hits)} matches "
          f"({', '.join(f'${h:04X}' for h in hits)}) -- not decided here",
          file=sys.stderr)
    return 0


#: Which flag a conditional branch tests, and which way it goes when the
#: instruction in front of it is an immediate load with a known value. `LDA
#: #$FF` sets N and clears Z, so the `BMI` after it is an unconditional jump
#: written in two bytes -- Curse's key fetcher ends on exactly that, and a
#: reader that takes it for a branch runs on into the next routine.
_DECIDED = {
    "BMI": lambda v: v & 0x80, "BPL": lambda v: not v & 0x80,
    "BEQ": lambda v: v == 0, "BNE": lambda v: v != 0,
}


def decided_branches(body: bytes, base: int, start: int, span: int
                     ) -> dict[int, bool]:
    """Branches whose outcome the immediately preceding load settles."""
    out: dict[int, bool] = {}
    lines = instructions(body, base, start, span)
    for (_, _, before), (at, _, text) in zip(lines, lines[1:]):
        head = text.split(" ", 1)[0]
        if head not in _DECIDED or " $" not in text:
            continue
        if before[:5] in ("LDA #", "LDX #", "LDY #") and before[5:6] == "$":
            out[at] = bool(_DECIDED[head](int(before[6:], 16)))
    return out


def reachable_end(body: bytes, base: int, start: int, limit: int = 0x100
                  ) -> int:
    """One past the last byte reachable from `start` without leaving the routine.

    A window a fast travel may take the PC from is a *routine*, and its extent
    is the set of addresses control can get to from its head: fall through,
    and branch targets, stopping at `RTS`, `RTI` and `JMP`.  Counting bytes
    instead gets it wrong in both directions -- Pool of Radiance's key fetcher
    has two exits and stopping at the first `RTS` cuts the window six bytes
    short, while Curse's ends on a `BMI` after `LDA #$FF`, which is
    unconditional because `#$FF` sets N and so is not an exit at all.

    `JSR` is followed through as a fall-through and never into the callee: a
    routine's call does not make the callee part of it.
    """
    settled = decided_branches(body, base, start, limit)
    seen: set[int] = set()
    todo = [start]
    end = start
    while todo:
        at = todo.pop()
        if at in seen or not (start <= at < start + limit):
            continue
        pair = instructions(body, base, at, 3)
        if not pair:
            continue
        addr, raw, text = pair[0]
        size = max(1, len(raw.split()))
        seen.add(at)
        end = max(end, at + size)
        head = text.split(" ", 1)[0]
        if head in ("RTS", "RTI"):
            continue
        if head == "JMP":
            if text.startswith("JMP $"):
                todo.append(int(text[5:], 16))
            continue
        if head[0] == "B" and head != "BIT" and text[-6:-4] == " $":
            taken = settled.get(at)
            if taken is not False:
                todo.append(int(text[-4:], 16))
            if taken is True:
                continue
        todo.append(at + size)
    return end


def loop_start(body: bytes, base: int, test: int) -> tuple[int, int]:
    """The key-wait loop's first and last address, from the `JMP` that closes it.

    The loop's own back-edge names its head, so the window's start needs no
    counting: find the `JMP` whose target is at or just above the first test.
    """
    head = test
    for i in range(len(body) - 2):
        if body[i] == 0x4C:                      # JMP abs
            to = body[i + 1] | (body[i + 2] << 8)
            if to <= test and test - to <= 8 and base + i > test:
                head = to
                break
    return head, reachable_end(body, base, head)


def one_reference(body: bytes, base: int, opcode: int, addr: int,
                  followed_by: int | None = None) -> int | None:
    """Where this overlay names `addr` with `opcode`, if it does so exactly once.

    Used to find an address that `NEWECL` does not itself write -- the
    wall-slot-pinned array, which is read by the wall unpacker and by nothing
    else. **Exactly once is the whole test.** A second reference would mean
    the pattern had found something other than the routine being looked for,
    and then the address it hands back is a guess wearing a derivation's
    clothes; the caller gets None and refuses instead.
    """
    want = bytes([opcode, addr & 0xFF, addr >> 8])
    hits, at = [], body.find(want)
    while at >= 0:
        if followed_by is None or (at + 3 < len(body)
                                   and body[at + 3] == followed_by):
            hits.append(base + at)
        at = body.find(want, at + 1)
    return hits[0] if len(hits) == 1 else None


def derive(game: games.Game, root: str, base: int = LINKER_BASE) -> dict:
    """Every fast-travel address for a title, out of its own overlays.

    The same chain the report prints, as data rather than as lines, so that
    `automap/fasttravel.py`'s shipped rows can be checked against the game's
    bytes -- `tests/test_newecl.py` -- and a driver can re-derive rather than
    write an address down (`tools/cursewarp.py`).

    Keys are `automap.fasttravel.FastTravelAddresses` field names where there
    is a field, plus `mode` for the loader's dispatch byte.
    **`walls_slot` and `travel_square` are not here**: neither is `NEWECL`'s
    and both are Pool of Radiance measurements from `#156` and `#178`.
    """
    _, body = load("DUNGEON", root, game)
    _, lo_t, hi_t, _ = dispatch_tables(body, base)
    handler_at = handler(body, base, lo_t, hi_t, NEWECL_OPCODE)
    lines = instructions(body, base, handler_at, 0x40)
    tail = newecl_tail(lines)
    text = [t for _, _, t in lines]

    # `LDA <slot> / AND #$7F / STA <came-from>` opens the handler, and the
    # 32-byte wipe is its one indexed store.
    slot = int(text[0][5:], 16)
    came_from = int(text[2][5:], 16)
    scratch = next(int(t[5:9], 16) for t in text
                   if t.startswith("STA $") and t.endswith(",X"))

    # Anything else zeroed in the same breath: Silver Blades stores to `$4BFB`
    # between the `LDA #$00` and the wipe, and the loop's back edge is the
    # indexed store, so it happens once. Taken as the plain `STA abs` between
    # the immediate zero and the tail, which is where such a write can be.
    zero_at = next(i for i, t in enumerate(text) if t == "LDA #$00")
    tail_at = next(i for i, (a, _, _) in enumerate(lines) if a == tail)
    zeroed = tuple(int(t[5:], 16) for t in text[zero_at + 1:tail_at]
                   if t.startswith("STA $") and "," not in t)

    # The indoors flag is what the position flush tests before copying the
    # live triple into the save, and the flush is the tail's own first call.
    flush = int(text[tail_at][5:], 16)
    flush_lines = instructions(body, base, flush, 0x10)
    indoors = int(flush_lines[0][2][5:], 16)
    live_square = int(next(t for _, _, t in flush_lines
                           if t.startswith("LDA $") and t.endswith(",X"))[5:9],
                      16)

    # The wall-slot-pinned array is read by the wall unpacker and by nothing
    # else, and it sits one byte above the indoors flag in every title read.
    # Checked rather than assumed: `LDA <flag+1>,X` followed by a `BNE` has to
    # appear exactly once in the overlay.
    guard = one_reference(body, base, 0xBD, indoors + 1, 0xD0)
    pinned = indoors + 1 if guard is not None else None

    test = find_window(body, base, KEY_WAIT_SIG, "key-wait")
    key_wait = loop_start(body, base, test) if test else (0, 0)
    _, lib = load("LIBRARY", root, game)
    called = next(int(t[5:], 16) for _, _, t
                  in instructions(body, base, key_wait[0], 0x10)
                  if t.startswith("JSR $"))
    off = lib.find(KEY_FETCH_SIG)
    key_fetch = (called, reachable_end(lib, called - off, called))

    _, lk = load("LINKER", root, game)
    loads = [t for _, _, t in instructions(lk, 0, 0, 0x20)
             if t.startswith(("LDA $", "STA $")) and "," not in t]
    mode_flag = int(loads[0][5:], 16)

    return {
        "key": game.key, "title": game.title,
        "handler": handler_at, "tail": tail,
        "slot": slot, "disk": mode_flag + 1, "came_from": came_from,
        "scratch": scratch, "zeroed": zeroed, "indoors": indoors,
        "live_square": live_square, "wall_slot_pinned": pinned,
        "key_wait": tuple(key_wait), "key_fetch": tuple(key_fetch),
        "mode": mode_flag,
    }


def report(game: games.Game, root: str, base: int,
           against: games.Game | None) -> int:
    decl, body = load("DUNGEON", root, game)
    top = base + len(body) - 1
    print(f"{game.title}")
    print(f"  DUNGEON: {len(body)} bytes, header says ${decl:04X}, "
          f"read at ${base:04X}-${top:04X}")

    lk_decl, lk = load("LINKER", root, game)
    print(f"  LINKER:  {len(lk)} bytes, header says ${lk_decl:04X}; DUNGEON "
          f"ends at ${top:04X}, so it is resident somewhere above that")

    call, lo_t, hi_t, opcode_store = dispatch_tables(body, base)
    count = opcode_count(lo_t, hi_t)
    print(f"  VM dispatch: JSR ${call:04X}, handlers low ${lo_t:04X} / "
          f"high ${hi_t:04X}, operand counts ${hi_t + count:04X}, "
          f"opcode byte ${opcode_store:04X}, {count} opcodes")

    ops = body[hi_t + count - base:hi_t + count - base + count]
    print(f"  opcode ${NEWECL_OPCODE:02X} takes "
          f"{ops[NEWECL_OPCODE]} operand(s)")

    at = handler(body, base, lo_t, hi_t, NEWECL_OPCODE)
    lines = instructions(body, base, at, 0x40)
    tail = newecl_tail(lines)
    print(f"  NEWECL handler ${at:04X}, tail ${tail:04X}")

    test = find_window(body, base, KEY_WAIT_SIG, "key-wait test")
    head = end = 0
    if test:
        head, end = loop_start(body, base, test)
        print(f"  key-wait window ${head:04X}-${end:04X}")

    lib_decl, lib = load("LIBRARY", root, game)
    # LIBRARY's base is not its header and not the byte after LINKER. Derive
    # it from the call DUNGEON's key-wait loop makes into it: the first
    # instruction of that routine is the CIA read, so the offset of `LDA $DC00`
    # inside the file and the call's target together fix the base.
    called = 0
    if test:
        for _, _, text in instructions(body, base, head, 0x10):
            if text.startswith("JSR $"):
                called = int(text[5:], 16)
                break
    off = lib.find(KEY_FETCH_SIG)
    if called and off >= 0:
        lib_base = called - off
        print(f"  LIBRARY: {len(lib)} bytes, header says ${lib_decl:04X}, "
              f"base ${lib_base:04X} from DUNGEON's JSR ${called:04X} onto "
              f"LDA $DC00, so ${lib_base:04X}-${lib_base + len(lib) - 1:04X}")
        print(f"  key fetcher ${called:04X}-"
              f"${reachable_end(lib, lib_base, called):04X}")

    # **`LINKER`'s own base is not derived here, and does not need to be.**
    # The bytes it dispatches on are absolute operands, so they read the same
    # wherever the file sits; only the addresses of `LINKER`'s own
    # instructions would move, and nothing below uses one. Pool of Radiance's
    # `LINKER` does sit immediately above `DUNGEON`, at `$2B80`, and Curse's
    # does not -- `#29` measured `$2D00`, eighteen bytes clear of `$2CED`.
    # What pins it from the file alone is only a range: its three `,X` tables
    # have to be inside it.
    tables = sorted({int(t[5:9], 16)
                     for _, _, t in instructions(lk, 0, 0, len(lk))
                     if t.startswith("LDA $") and t.endswith(",X")})
    print("  LINKER dispatches on (absolute operands, base-independent):")
    for _, _, text in instructions(lk, 0, 0, 0x20):
        if text.startswith(("LDA $", "STA $", "LDX $")) and "," not in text:
            print(f"    {text}")
    if tables:
        print(f"    tables at {', '.join(f'${t:04X}' for t in tables)}, so "
              f"LINKER's own base is between ${tables[-1] + 1 - len(lk):04X} "
              f"and ${tables[0]:04X}")

    if against is not None:
        other = find_disks(against)
        if other is None:
            print(f"  (no {against.title} disks to compare against)")
            return 0
        _, obody = load("DUNGEON", str(other), against)
        ocall, olo, ohi, _ = dispatch_tables(obody, base)
        oat = handler(obody, base, olo, ohi, NEWECL_OPCODE)
        olines = instructions(obody, base, oat, 0x40)
        same = 0
        relocs: dict[str, str] = {}
        for (_, _, a), (_, _, b) in zip(olines, lines):
            if operands(a) != operands(b):
                break
            same += 1
            if "$" in a and a != b:
                relocs[a.split("$", 1)[1]] = b.split("$", 1)[1]
            if a.startswith(("JMP ", "RTS")):
                break
        print(f"  against {against.title}: handler ${oat:04X}, "
              f"{same} instructions identical bar their operands")
        for k, v in relocs.items():
            print(f"    ${k} -> ${v}")
    return 0


def main(argv: list[str]) -> int:
    keys = [g.key for g in games.GAMES]
    ap = argparse.ArgumentParser(
        description="Find a title's NEWECL handler and the addresses a fast "
                    "travel needs, from its own overlays.")
    ap.add_argument("game", choices=keys, help="which title")
    ap.add_argument("--disks", default=os.environ.get("POR_DISKS"),
                    metavar="DIR",
                    help="where that title's disks are (default: $POR_DISKS, "
                         "then wherever the program looks)")
    ap.add_argument("--base", default=hex(LINKER_BASE), metavar="ADDR",
                    help="the address DUNGEON runs at (default: %(default)s, "
                         "where LINKER puts an overlay it calls -- the PRG "
                         "header is wrong in every title read so far)")
    ap.add_argument("--against", choices=keys, default=None,
                    help="compare the handler against this title's, "
                         "instruction for instruction")
    args = ap.parse_args(argv[1:])

    game = next(g for g in games.GAMES if g.key == args.game)
    root = args.disks or str(find_disks(game) or "")
    if not root or not os.path.isdir(root):
        print(f"No {game.title} disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2
    against = (next(g for g in games.GAMES if g.key == args.against)
               if args.against else None)
    return report(game, root, int(args.base, 0), against)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

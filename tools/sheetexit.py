#!/usr/bin/env python3
"""How a driven session leaves a Gold Box character sheet (#444).

A driven run that wants two characters' sheets on Curse or Silver Blades used
to boot twice, because pressing `EXIT` on the sheet's own command bar did not
take.  It does not have to press `EXIT` at all.

**Every command bar in all three C64 titles is driven by one key interpreter,
and it reads the back-arrow key -- PETSCII `$5F`, the `<-` at the top left of
a C64 keyboard -- as "leave, whatever the highlight is on".**  The routine is
byte-for-byte the same in Pool of Radiance, Curse and Silver Blades, only
relocated, and `keys` below prints it out of the player's own `LIBRARY`:

    tools/sheetexit.py keys                the interpreter, per title
    tools/sheetexit.py keys --title curse-of-the-azure-bonds
    tools/sheetexit.py run --save DISK --out DIR --who NAME --then NAME

`keys` finds the interpreter by shape and nothing else.  The anchor is the
sheet's own menu string -- `ITEMS SPELLS TRADE DROP CURE HEAL EXIT`, or Pool
of Radiance's five-entry version -- and from there: the `LDX #lo / LDY #hi`
that hands the table to the menu builder, the interpreter's own
`LDX #$04 / STX abs / DEX` prologue, and the `CMP #imm / BEQ` chain that
follows it.  Two of those branches end in tails this file can name from their
code alone: `LDX abs / LDA abs,X / SEC / RTS` returns the highlighted entry's
command id, and `LDA #$FF / SEC / RTS` returns `$FF`.  The sheet's loop closes
with `BPL / RTS`, so `$FF` -- a negative accumulator -- is the sheet
returning to whoever opened it.

`run` is the proof, and it is the one that cannot pass by accident: it boots
the title once, reads one character's sheet off the party-formation menu,
leaves it, and reads a **second** character's sheet in the same boot.  It
photographs both, and before it leaves the first it records what the machine
held -- row 24's colour RAM, the highlight index, the drawn entries' command
ids -- so a later reader can check the reasoning rather than take it.

The player's disks are read and never written: `run` stages copies into the
pool slot, and the game is shown nothing else.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from goldbox import c64_port  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools import portraitdraw  # noqa: E402
from tools.savecheck import Log, catch_signals  # noqa: E402

#: The three C64 titles, and the label each is reported under.
TITLES: tuple[tuple[str, str], ...] = (
    ("pool-of-radiance", "Pool of Radiance"),
    ("curse-of-the-azure-bonds", "Curse of the Azure Bonds"),
    ("secret-of-the-silver-blades", "Secret of the Silver Blades"),
)

#: The sheet's menu table begins with the first command's name.  Every title
#: draws `ITEMS` first, and only Curse and Silver Blades carry `CURE`/`HEAL`,
#: so the shortest anchor that holds for all three is the first entry.
FIRST_ENTRY = b"ITEMS\x00"

#: `LDX #$04 / STX abs / DEX`, the key interpreter's prologue, followed by its
#: first test.  One hit per `LIBRARY` in all three titles.
INTERPRETER = re.compile(rb"\xA2\x04\x8E(..)\xCA\xC9\x3C\xF0", re.S)

#: `LDX abs / LDA abs,X / SEC / RTS` -- the tail that returns the highlighted
#: entry's command id.  The two absolute operands are the highlight index and
#: the drawn-entry id table, which is what `run` reads the live machine at.
SELECT_TAIL = re.compile(rb"\xAE(..)\xBD(..)\x38\x60", re.S)

#: `LDA #$FF / SEC / RTS` -- the tail that returns "leave".  A caller's `BPL`
#: over its own `RTS` is what turns that `$FF` into an exit.
ABORT_TAIL = bytes.fromhex("a9ff3860")

#: Where the interpreter stops testing the keyboard and starts testing the
#: joystick read at `$03F0`: `LDA $03F0`.
JOYSTICK = bytes.fromhex("adf003")

#: What each key does, once the interpreter has been read.  The codes are not
#: assumed -- they are printed from the file -- but a code needs a name, and
#: these are the PETSCII values a C64 keyboard produces.
KEY_NAMES = {
    0x0D: "RETURN",
    0x11: "CRSR down",
    0x1D: "CRSR right",
    0x2C: ",",
    0x2E: ".",
    0x3C: "<",
    0x3E: ">",
    0x5F: "<- (back-arrow)",
    0x91: "CRSR up (shifted)",
    0x9D: "CRSR left (shifted)",
}


# --- reading the code --------------------------------------------------------

def _abs(raw: bytes) -> int:
    return raw[0] | raw[1] << 8


def _head(data: bytes, at: int) -> int:
    """Back up over the `JSR abs` a tail opens with, if there is one."""
    return at - 3 if at >= 3 and data[at - 3] == 0x20 else at


def menu_table(data: bytes, base: int) -> tuple[int, int] | tuple[None, None]:
    """The sheet's menu table, and the `LDX #lo / LDY #hi` that hands it over.

    Returns `(table address, address of the LDX)`.  The table's first byte is
    the entry count and the names follow, so the address wanted is a few bytes
    *before* `ITEMS` -- and rather than guess how many, every address in that
    window is tried against the immediate pair that pushes it.  Pool of
    Radiance's table carries a `VIEW:` label the later two dropped, which is
    exactly the distance this avoids having to know.
    """
    at = data.find(FIRST_ENTRY)
    if at < 0:
        return None, None
    for back in range(0, 12):
        addr = base + at - back
        push = bytes([0xA2, addr & 0xFF, 0xA0, addr >> 8])
        site = data.find(push)
        if site >= 0:
            return addr, base + site
    return None, None


def key_chain(data: bytes, base: int, start: int) -> list[tuple[int, int, int]]:
    """The interpreter's `CMP #imm / BEQ target` chain, in order.

    Stops at `LDA $03F0`, where the routine leaves the keyboard and starts on
    the joystick.  Each entry is `(address, key code, branch target)`.
    """
    out: list[tuple[int, int, int]] = []
    off = start - base
    while off < len(data) - 4:
        if data[off:off + 3] == JOYSTICK:
            break
        if data[off] == 0xC9 and data[off + 2] == 0xF0:
            rel = data[off + 3]
            target = base + off + 4 + (rel - 256 if rel > 127 else rel)
            out.append((base + off, data[off + 1], target))
            off += 4
            continue
        off += 1
    return out


def loop_of(data: bytes, base: int, after: int) -> dict:
    """The sheet's own poll loop, found forward from the menu-table push.

    What is wanted from it is the pair `BPL x / RTS`: it is the proof that a
    negative answer from the interpreter leaves the sheet, and it is two bytes
    long, so it is looked for rather than reasoned about.  Silver Blades wraps
    the poll in one more subroutine than Curse does, which is why this looks
    for the branch and not for the `JSR` in front of it.
    """
    window = data[after - base:after - base + 0x40]
    site = window.find(b"\x10\x01\x60")
    if site < 0:
        return {}
    at = base + after - base + site
    return {"bpl": at, "rts": at + 2, "leaves_on": "a negative accumulator"}


def read_library(data: bytes) -> dict:
    """Everything this file can say about one title's bar-menu reader."""
    file_base, good, bad = portraitdraw.base_of(data)
    base = file_base                     # `data[0]` maps here; code is at +2
    out: dict = {"base": file_base + 2, "score": [good, bad]}
    table, push = menu_table(data, base)
    out["menu_table"], out["table_pushed_at"] = table, push

    hits = list(INTERPRETER.finditer(data))
    out["interpreters"] = len(hits)
    if len(hits) != 1:
        return out
    start = base + hits[0].start()
    out["interpreter"] = start
    out["chain"] = [{"at": a, "key": k, "goes_to": t}
                    for a, k, t in key_chain(data, base, start)]

    # Both tails open with the `JSR abs` that takes the highlight back off the
    # bar, and the chain's branch lands on *that* -- so each tail's address is
    # three bytes before the part this file can recognise.
    sel = SELECT_TAIL.search(data)
    if sel is not None:
        out["select_tail"] = base + _head(data, sel.start())
        out["highlight_index"] = _abs(sel.group(1))
        out["id_table"] = _abs(sel.group(2))
    ab = data.find(ABORT_TAIL)
    if ab >= 0:
        out["abort_tail"] = base + _head(data, ab)
    targets = {e["goes_to"]: e["key"] for e in out["chain"]}
    out["select_key"] = next((k for t, k in targets.items()
                              if t == out.get("select_tail")), None)
    out["cancel_key"] = next((k for t, k in targets.items()
                              if t == out.get("abort_tail")), None)
    if push is not None:
        out["loop"] = loop_of(data, base, push)
        # `LDX #lo / LDY #hi / JSR <build>` is seven bytes, and the byte after
        # it is the `LDA abs` that reads back the index the sheet remembers
        # between visits.  Only `STX <that address>`, on the arm a chosen
        # command takes, ever writes it -- which makes it the cheapest
        # discriminator there is between "nothing was selected" and "something
        # was, and the sheet came back".
        off = push - base + 7
        if data[off] == 0xAD:
            out["remembered_index"] = _abs(data[off + 1:off + 3])
    return out


def survey(key: str, label: str, disks: str | None) -> dict:
    sides = portraitdraw.sides_of(key, disks)
    side, data = portraitdraw.read_named(sides, b"LIBRARY")
    if data is None:
        return {"title": label, "sides": len(sides), "error": "no LIBRARY"}
    out = read_library(data)
    out.update(title=label, key=key, sides=len(sides), side=side)
    return out


def report(rows: list[dict]) -> None:
    for row in rows:
        print(f"\n== {row['title']}  ({row.get('side') or 'no side'})")
        if "error" in row:
            print(f"   {row['error']}")
            continue
        print(f"   LIBRARY runs at ${row['base']:04X} "
              f"(base score {row['score'][0]} good / {row['score'][1]} bad)")
        if row.get("menu_table"):
            print(f"   sheet menu table ${row['menu_table']:04X}, "
                  f"handed over at ${row['table_pushed_at']:04X}")
        if row.get("interpreters") != 1:
            print(f"   {row.get('interpreters')} interpreter prologues; "
                  f"expected exactly one")
            continue
        print(f"   bar-menu key interpreter at ${row['interpreter']:04X}")
        for e in row["chain"]:
            name = KEY_NAMES.get(e["key"], "")
            what = ""
            if e["goes_to"] == row.get("select_tail"):
                what = "  -> select the highlighted entry"
            elif e["goes_to"] == row.get("abort_tail"):
                what = "  -> LEAVE, wherever the highlight is"
            print(f"     ${e['at']:04X}  CMP #${e['key']:02X} "
                  f"{name:<18} BEQ ${e['goes_to']:04X}{what}")
        if row.get("highlight_index"):
            print(f"   highlight index ${row['highlight_index']:04X}, "
                  f"drawn-entry ids ${row['id_table']:04X}")
        loop = row.get("loop") or {}
        if loop:
            print(f"   the sheet's loop leaves at ${loop['bpl']:04X} "
                  f"(BPL over the RTS at ${loop['rts']:04X}) on "
                  f"{loop['leaves_on']}")


# --- the driven run ----------------------------------------------------------

#: What the party-formation menu calls the sheet, and what the list it opens
#: says on row 24.
VIEW_ROW = "VIEW CHARACTER"
PICKER = "WHICH CHARACTER"


def sheet_up(s) -> bool:
    """Is a character sheet in front of the party menu?

    `Session.sheet_is_up` looks for Pool of Radiance's `VIEW:`, which neither
    later title draws.  The mask builder prints only the commands the
    character can use -- Silver Blades draws `EXIT` alone for a character with
    nothing to trade -- so `EXIT` is the one word every version of the bar
    ends with, and the party menu's own rows have no `EXIT` on them.
    """
    row = s.row(24)
    return "EXIT" in row and "ENCAMP" not in row and PICKER not in row.upper()


def at_picker(s) -> bool:
    return PICKER in s.row(24).upper()


def at_menu(s) -> bool:
    return VIEW_ROW in s.text().upper()


def wait_for(sess, test, timeout: float = 30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = sess.screen()
        if s is not None and test(s):
            return s
        if s is not None:
            sess.handle_prompt(s)
        time.sleep(0.4)
    return None


def machine_state(sess, addrs: dict) -> dict:
    """What the running game holds while the sheet is up.

    Read in one monitor connection: the highlight index, the drawn entries'
    command ids, the colour RAM under row 24, and the four bytes the key
    fetcher works from.
    """
    out: dict = {}
    try:
        with sess.mon(5) as m:
            out["highlight_index"] = m.read(addrs["highlight_index"], 1)[0]
            out["entry_ids"] = list(m.read(addrs["id_table"], 8))
            out["irq_vector"] = list(m.read(0x0314, 2))
            out["kernal_count"] = m.read(0xC6, 1)[0]
            out["kernal_buffer"] = m.read(0x0277, 1)[0]
            out["last_key"] = m.read(0x03CB, 1)[0]
            out["joystick"] = m.read(0x03F0, 1)[0]
    except Exception as exc:                      # noqa: BLE001
        out["error"] = repr(exc)
    s = sess.screen()
    if s is not None:
        out["row24"] = s.row(24).rstrip()
        out["row24_colours"] = list(s.colours[24 * 40:24 * 40 + 40])
    return out


def read_sheet(sess, log: Log, name: str, walk, out: pathlib.Path) -> list[str] | None:
    """`name`'s sheet, from wherever the front end is standing."""
    s = sess.screen()
    if s is not None and at_menu(s) and not at_picker(s):
        if not walk(sess, VIEW_ROW):
            log.emit("view", ok=False, who=name)
            return None
        sess.settle(3.0)
    if wait_for(sess, at_picker, 30.0) is None:
        log.emit("picker", ok=False, who=name, why="no picker came up")
        sess.kbd.screenshot(str(out / f"no-picker-{name}.png"))
        return None
    if not walk(sess, name):
        log.emit("picker", ok=False, who=name, why="could not be picked")
        return None
    s = wait_for(sess, sheet_up, 40.0)
    if s is None:
        log.emit("sheet", ok=False, who=name)
        return None
    sess.settle(2.0)
    s = sess.screen()
    if s is None:
        return None
    lines = [line.rstrip() for line in s.rows() if line.strip()]
    (out / f"sheet-{name}.txt").write_text("\n".join(lines) + "\n")
    sess.kbd.screenshot(str(out / f"sheet-{name}.png"))
    log.emit("sheet", ok=True, who=name, row24=s.row(24).rstrip())
    return lines


#: The routes off the sheet this file can test, and what each is.
#:
#: `leave-sheet` is the one that matters -- it is `Session.leave_sheet`, the
#: method every driven run calls, so a pass here is a pass for the shipped
#: code rather than for this file's own copy of the idea.  The rest are
#: controls: `cancel` is the key on its own, and `press-bar` and `exit-bar`
#: are the two routes `#444` was filed about.
ROUTES = ("leave-sheet", "cancel", "press-bar", "exit-bar", "return-kernal",
          "xtest")


def leave(sess, log: Log, how: str, name: str, addrs: dict,
          out: pathlib.Path) -> bool:
    """Off the sheet by whichever route `how` names, and say whether it took."""
    before = sess.screen()
    row = "" if before is None else before.row(24)
    # **Spoil the remembered index before the route runs.**  The sheet writes
    # it only when a command is chosen, so a sentinel that survives says no
    # key was ever read as a selection, and one that has been overwritten says
    # a command was chosen and the sheet redrawn under it.  `$7F` is outside
    # every bar this game builds, so the sheet clamps it to 0 on a redraw and
    # nothing else changes.
    spoil = addrs.get("remembered_index")
    if spoil:
        with sess.mon(5) as m:
            m.write(spoil, bytes([0x7F]))
    said = None
    if how == "leave-sheet":
        said = sess.leave_sheet()
    elif how == "cancel":
        said = sess.cancel_bar()
    elif how == "press-bar":
        from tools.inventorycheck import press_bar
        said = press_bar(sess, "EXIT", timeout=12)
    elif how == "exit-bar":
        said = sess.select_bar("EXIT", timeout=12)
    elif how == "return-kernal":
        sess.press_kernal(0x0D)
    elif how == "xtest":
        sess.kbd.key("End", 0.15, 0.28)
    else:
        raise SystemExit(f"unknown route {how}")
    # **Left means back where the next character can be chosen**, not merely
    # "the sheet has gone".  A route that presses the wrong command leaves a
    # screen that is neither -- `press-bar` put this run on a blank row 24 for
    # thirty seconds and an earlier version called that a success (#444).
    # **Every distinct row 24 seen while waiting.**  A route that leaves the
    # sheet and is then walked straight back into it looks exactly like a
    # route that never left, and the trail is what tells them apart: the
    # picker's own bar appearing in the middle of the wait is the sheet having
    # closed (#444).
    trail: list[str] = []
    deadline = time.time() + 15.0
    while time.time() < deadline:
        s = sess.screen()
        seen = "(no screen)" if s is None else s.row(24).rstrip()
        if not trail or trail[-1] != seen:
            trail.append(seen)
        if s is not None and (at_picker(s) or at_menu(s)):
            log.emit("left", ok=True, how=how, who=name, said=said,
                     now=seen, was=row.rstrip(), trail=trail)
            return True
        if s is not None:
            sess.handle_prompt(s)
        time.sleep(0.5)
    # A route that did not work is the reading to keep, so the machine is read
    # again here rather than only before the first attempt: where the
    # highlight ended up is what says whether the walk or the key was the half
    # that failed, and the picture says what the run is looking at.
    state = machine_state(sess, addrs) if addrs.get("highlight_index") else {}
    if spoil:
        with sess.mon(5) as m:
            state["remembered_index"] = m.read(spoil, 1)[0]
        state["nothing_was_selected"] = state["remembered_index"] == 0x7F
    sess.kbd.screenshot(str(out / f"stuck-after-{how}-{name}.png"))
    s = sess.screen()
    if s is not None:
        (out / f"stuck-after-{how}-{name}.txt").write_text(
            "\n".join(line.rstrip() for line in s.rows()) + "\n")
    log.emit("left", ok=False, how=how, who=name, said=said, was=row.rstrip(),
             trail=trail, **state)
    return False


def curse_boot(slot, log: Log, save: str, where: str, wait: float):
    from tools import curseload, curserun
    first = curserun.stage(slot, where, save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    os.chmod(save_disk, 0o644)
    sess = curserun.CurseSession(first, slot=slot)
    sess.save_disk = save_disk
    log.emit("staged", save=save, side0=save_disk)
    if not sess.boot():
        log.emit("boot", ok=False)
        return sess, False
    log.emit("boot", ok=True)
    outcome = curseload.load_saved_game(sess, wait=wait)
    log.emit("load", outcome=outcome)
    return sess, outcome == "loaded"


def ssb_boot(slot, log: Log, save: str, where: str, wait: float):
    from tools import ssbwarp
    first = ssbwarp.stage(slot, where, save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    os.chmod(save_disk, 0o644)
    sess = ssbwarp.SSBSession(first, slot=slot)
    sess.save_disk = save_disk
    log.emit("staged", save=save, side0=save_disk)
    if not sess.boot():
        log.emit("boot", ok=False)
        return sess, False
    log.emit("boot", ok=True)
    ok = ssbwarp.load_party(sess, timeout=wait)
    log.emit("load", outcome="loaded" if ok else "failed")
    return sess, ok


def curse_walk(sess, label: str) -> bool:
    from tools import dualclassagain
    return dualclassagain.walk_menu(sess, label)


def ssb_walk(sess, label: str) -> bool:
    return sess.select_row(label, timeout=30.0)


DRIVERS = {
    "curse-of-the-azure-bonds": (curse_boot, curse_walk),
    "secret-of-the-silver-blades": (ssb_boot, ssb_walk),
}


def run(save: str, out: str, who: list[str], how: str, pool: int | None,
        disks: str = "", wait: float = 300.0) -> int:
    """Boot once and read every named character's sheet."""
    from tools import gamedisks
    from tools import session as por

    game = c64_port.detect(D64.open(save))
    if game is None or game.key not in DRIVERS:
        raise SystemExit(f"{save}: no Curse or Silver Blades save on this disk "
                         f"({game.title if game else 'nothing detected'})")
    boot, walk = DRIVERS[game.key]
    where = disks or str(gamedisks.find(game.key) or "")
    if not where:
        raise SystemExit(f"no {game.title} sides: pass --disks")
    here = pathlib.Path(out)
    here.mkdir(parents=True, exist_ok=True)
    log = Log(here / "sheetexit.jsonl")
    addrs = survey(game.key, game.title, disks or None)
    log.emit("code", title=game.title,
             interpreter=addrs.get("interpreter"),
             cancel_key=addrs.get("cancel_key"),
             select_key=addrs.get("select_key"),
             highlight_index=addrs.get("highlight_index"),
             id_table=addrs.get("id_table"))
    if addrs.get("cancel_key") is None:
        log.say("the cancel key could not be read out of LIBRARY; "
                "run `tools/sheetexit.py keys` and see what it says")

    slot = por.claim_slot(pool, note=os.environ.get("POR_AGENT", "sheetexit"))
    log.emit("slot", n=slot.n, monitor=slot.port, display=slot.display,
             dir=str(slot.dir), title=game.title)
    sess = None
    read: list[str] = []
    try:
        sess, ok = boot(slot, log, save, where, wait)
        if not ok:
            sess.kbd.screenshot(str(here / "boot-failed.png"))
            return 1
        sess.settle(3.0)
        for n, name in enumerate(who):
            lines = read_sheet(sess, log, name, walk, here)
            if lines is None:
                break
            read.append(name)
            if n == 0 and addrs.get("highlight_index"):
                log.emit("state", who=name, **machine_state(sess, addrs))
            if n < len(who) - 1 and not leave(sess, log, how, name, addrs, here):
                break
            log.say(f"read {name}")
        log.emit("done", read=read, wanted=who, how=how,
                 two_in_one_boot=len(read) > 1)
        log.say(f"read {len(read)} of {len(who)} sheets in one boot: "
                f"{', '.join(read)}")
        return 0 if len(read) == len(who) else 1
    finally:
        if sess is not None:
            sess.terminate()
        slot.teardown()
        log.emit("torn down")
        log.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("keys", help="the bar-menu key interpreter, per title")
    k.add_argument("--title", default="", help="one title's key, not all three")
    k.add_argument("--disks", default="", help="where that title's sides are")
    k.add_argument("--json", default="", help="write the reading here as well")

    d = sub.add_parser("run", help="two sheets in one boot")
    d.add_argument("--save", required=True, help="the save disk to boot")
    d.add_argument("--out", required=True, help="a directory for this run")
    d.add_argument("--who", action="append", default=[],
                   help="a character to view; give it twice for two sheets")
    d.add_argument("--then", default="", help="the second character, if any")
    d.add_argument("--how", default="leave-sheet", choices=ROUTES,
                   help="which route off the sheet to test")
    d.add_argument("--pool", type=int, default=None, help="demand this slot")
    d.add_argument("--disks", default="", help="the six sides")
    d.add_argument("--wait", type=float, default=300.0,
                   help="seconds to wait for the load")

    args = ap.parse_args(argv)
    if args.cmd == "keys":
        wanted = [(k, label) for k, label in TITLES
                  if not args.title or k == args.title]
        if not wanted:
            raise SystemExit(f"no such title: {args.title}")
        rows = [survey(k, label, args.disks or None) for k, label in wanted]
        report(rows)
        if args.json:
            pathlib.Path(args.json).write_text(json.dumps(rows, indent=2) + "\n")
        return 0
    catch_signals()
    names = list(args.who) + ([args.then] if args.then else [])
    if not names:
        raise SystemExit("pass --who at least once")
    return run(args.save, args.out, names, args.how, args.pool,
               args.disks, args.wait)


if __name__ == "__main__":
    sys.exit(main())

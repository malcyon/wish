#!/usr/bin/env python3
"""Run an exit's own handler from outside the game, the way a step would.

`#207 (Run an exit's own handler before Fast Travel warps out)` is the
ticket.  A fast travel enters `NEWECL` at its tail and skips the departing
script's prologue; the Kobold Caves' prologue is what takes Princess Fatima
out of the party, so a party that warps out keeps her (`#180`).  This drives
the alternative: put the party on the exit square and re-enter `DUNGEON` at
one of its own post-step points, so the script's own dispatch runs the
handler with the machine in the state a step leaves it in.

The two re-entry points, both read off `DUNGEON` (`docs/150-departing-prologues.md`):

* `$0957` -- `JSR $0A4C` (redraw, which calls `GDRIVE00 $C018` and so
  refreshes `$C04E`/`$C04F` for the square in `$C04B`-`$C04D`) then
  `JMP $08FC`, which runs **entry 1**, the per-square dispatch.  This is where
  the game goes after a step lands, and it is what a square-keyed exit needs.
* `$0978` -- `JSR $098B`, the forward-key handler: `$10EC` counts whether the
  step would leave the map into `$6DD5`, then **entry 0** runs.  This is what
  an edge exit needs, chained behind `$0A4C` so the square outputs are fresh.

Both run inside the MOVE routine `$08F4`, which `$08A4 JSR` enters from the
main loop at the stack depth `$0809` saved in `$03BF`.  So the stack is
rebuilt rather than trusted: `SP := [$03BF]`, push `$08A6` (the return into
the main loop), push the chain, set the PC.  `EXIT` unwinds to `$2B63`, which
`$1581` records on entry, and `NEWECL`'s tail resets to `$03BF`, so whatever
the party answers the machine comes back to a state the game itself built.

    tools/exitreentry.py --out work/issue207/run1

Boots `npc_party.d64` -- the party inside the Kobold Caves with Fatima in
slot 3 -- and runs the phases in order, each writing a JSON capture and a
screenshot: the idle stack at the command bar and in MOVE mode; the exit
square with the handler answered NO; the same answered YES; a second hop
from the wilderness back indoors with the writes `ECL1A $A0A4` makes; and,
if that lands, an edge exit out of New Phlan.

Nothing is written to the player's disks: `stage_disks` copies the sides
into the slot.  The pool owns the emulator.  Captures go to `work/`.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions as A  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

CAVES, EAST, PHLAN, SLUMS = 13, 27, 0, 20
#: `GEO0D` square-attribute id 28, the caves' exit, sits on (6,15) and (10,15).
EXIT_SQUARE = (6, 15, 2)
#: New Phlan's south edge, facing south: `$10EC` counts y+1 = 16 as off the
#: map.  It has to be a square that is **open** that way.  `$10EC` reads
#: `$C04E`, the wall art in the facing direction, and only counts the step
#: when it is zero or `$1143` calls it a door you can walk through -- so an
#: edge square with a wall on its outward side never sets `$6DD5` and the
#: script's gate never opens.  (15,1) was the first choice and is walled:
#: `Geo.wall(15, 1, EAST)` = 14, and the emulator read `$C04E` = 14 there.
PHLAN_EDGE = (8, 15, 2)

#: `$0809 TSX / STX $03BF`: the main loop's stack depth.
SAVED_SP = 0x03BF
#: `$08A4 JSR $FFFF` is patched to the command's routine; the JSR pushes $08A6.
MAIN_LOOP_RETURN = 0x08A6
#: `$0957 JSR $0A4C / JMP $08FC`: redraw, then entry 1.
AFTER_STEP = 0x0957
#: `$0978 JSR $098B`: the forward key in MOVE mode.
FORWARD_KEY = 0x0978
#: `$0A4C`, the redraw; chained in front of `$0978` so `$C04F` is fresh.
REDRAW = 0x0A4C
#: The `NEWECL` tail, for the record.
NEWECL_TAIL = 0x2034

SLOT_RECORD, SLOT_ROSTER, SLOTS = 0x4D00, 0x8300, 8
#: VICE's register ids, `docs/50-experiments.md` P43.
REG_PC, REG_SP = 3, 4


def indoors(sess) -> bool:
    """`$49E6`: non-zero indoors, zero on the travel grid.

    `DUNGEON`'s key-wait loop is an indoor loop -- `$08F4` branches to
    `$0ABA`, the overland loop, when this reads zero -- so waiting for
    `KEY_WAIT` after an exit that lands in the wilderness waits for
    something that will never happen.
    """
    with sess.mon(5) as m:
        return m.read(0x49E6, 1)[0] != 0


def wait_idle(sess, timeout: float = 300.0, need: int = 6) -> bool:
    deadline = time.time() + timeout
    inloop = 0
    while time.time() < deadline:
        sess.settle(2)
        try:
            with sess.mon(5) as m:
                pc = m.registers().get(A.pc_register(m))
        except Exception:                       # noqa: BLE001
            pc = None
        idle = pc is not None and any(lo <= pc < hi
                                      for lo, hi in (A.KEY_WAIT, A.KEY_FETCH))
        inloop = inloop + 1 if idle else 0
        if inloop >= need:
            return True
    print("  NEVER went idle", flush=True)
    return False


class SessTarget:
    def __init__(self, sess):
        self.sess = sess

    def read(self, addr: int, length: int) -> bytes:
        with self.sess.mon(5) as m:
            return m.read(addr, length)

    def write(self, addr: int, data) -> None:
        with self.sess.mon(5) as m:
            m.write(addr, bytes(data))

    def pc(self):
        with self.sess.mon(5) as m:
            return m.registers().get(A.pc_register(m))

    def set_pc(self, address: int) -> None:
        with self.sess.mon(5) as m:
            m.set_registers({A.pc_register(m): address})


def _name(raw: bytes) -> str:
    if not raw or raw[0] == 0:
        return "<empty>"
    out = raw.split(b"\x00")[0]
    return "".join(chr(c) if 32 <= c < 127 else "." for c in out)


def party(sess) -> list[dict]:
    rows = []
    with sess.mon(8) as m:
        for i in range(SLOTS):
            rec = m.read(SLOT_RECORD + i * 0x100, 0x100)
            ros = m.read(SLOT_ROSTER + i * 0x20, 0x20)
            rows.append({"slot": i, "name": _name(rec[:16]),
                         "flags_0b8": rec[0xB8], "status": ros[0]})
    return rows


def stack(m) -> dict:
    """SP, the saved base, and the return addresses above SP, oldest last."""
    regs = m.registers()
    sp = regs.get(REG_SP)
    base = m.read(SAVED_SP, 1)[0]
    raw = m.read(0x0100 + sp + 1, 0xFF - sp) if sp is not None and sp < 0xFF \
        else b""
    frames = [f"${(raw[i] | (raw[i + 1] << 8)) + 1:04X}"
              for i in range(0, len(raw) - 1, 2)]
    return {"pc": regs.get(REG_PC), "sp": sp, "base_03BF": base,
            "raw": raw.hex(" "), "returns": frames}


def sample_pcs(sess, n: int = 40) -> dict:
    counts: dict[str, int] = {}
    for _ in range(n):
        with sess.mon(5) as m:
            pc = m.registers().get(REG_PC)
        key = f"${pc:04X}"
        counts[key] = counts.get(key, 0) + 1
        time.sleep(0.05)
    return dict(sorted(counts.items()))


def capture(sess, out: pathlib.Path, label: str, note: str = "") -> dict:
    meta = {"label": label, "note": note}
    with sess.mon(8) as m:
        for name, addr, n in (("6E11", 0x6E11, 1), ("6E12", 0x6E12, 1),
                              ("6E1B", 0x6E1B, 1), ("49E6", 0x49E6, 1),
                              ("C04B", 0xC04B, 3), ("C04E", 0xC04E, 2),
                              ("49C0", 0x49C0, 3), ("49C3", 0x49C3, 2),
                              ("6DD5", 0x6DD5, 1), ("6DC9", 0x6DC9, 1),
                              ("6E47", 0x6E47, 2), ("6DDC", 0x6DDC, 1),
                              ("2B63", 0x2B63, 1), ("6E22", 0x6E22, 6)):
            meta[name] = list(m.read(addr, n))
        meta["stack"] = stack(m)
    meta["party"] = party(sess)
    screen = sess.screen()
    if screen is not None:
        meta["text"] = screen.text()
        meta["row24"] = screen.row(24)
    sess.kbd.screenshot(str(out / f"{label}.png"))
    (out / f"{label}.json").write_text(json.dumps(meta, indent=1))
    live = ", ".join(f"{r['slot']}:{r['name']}" for r in meta["party"]
                     if r["name"] != "<empty>")
    print(f"[{label}] area={meta['6E1B'][0] & 0x7F} $49E6={meta['49E6'][0]} "
          f"square={meta['C04B']} C04E/F={meta['C04E']} "
          f"pc={meta['stack']['pc']:#06x} sp={meta['stack']['sp']:#04x} "
          f"base={meta['stack']['base_03BF']:#04x} "
          f"returns={meta['stack']['returns'][:6]}\n"
          f"          party: {live}", flush=True)
    return meta


def reenter(sess, pc: int, chain: tuple[int, ...]) -> dict:
    """Rebuild the stack from `$03BF` and jump.

    `chain` is the return addresses to push after the main loop's own, first
    pushed first: `(0x0977,)` makes `$0A4C`'s RTS land on `$0978`.  Each
    entry is the address *minus one*, the way JSR leaves it.
    """
    with sess.mon(5) as m:
        before = stack(m)
        base = before["base_03BF"]
        sp = base
        for ret in (MAIN_LOOP_RETURN, *chain):
            m.write(0x0100 + sp, bytes([ret >> 8]))
            m.write(0x0100 + sp - 1, bytes([ret & 0xFF]))
            sp -= 2
        m.set_registers({REG_PC: pc, REG_SP: sp})
        after = stack(m)
    print(f"  re-entered at ${pc:04X}: sp {before['sp']:#04x} -> {sp:#04x}, "
          f"was pc={before['pc']:#06x} returns={before['returns'][:5]}",
          flush=True)
    return {"before": before, "after": after}


def wait_row24(sess, words, timeout: float = 40.0) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = sess.screen()
        row = s.row(24) if s is not None else ""
        if all(w in row.split() for w in words):
            return row
        time.sleep(0.4)
    return None


def answer_until_area(sess, target, want: int, out, label,
                      budget: float = 180.0) -> bool:
    deadline, shots, seen = time.time() + budget, 0, []
    while time.time() < deadline:
        if A.FastTravel.current_area(target) == want:
            return True
        s = sess.screen()
        row = s.row(24).strip() if s is not None else ""
        if row and (not seen or seen[-1] != row):
            seen.append(row)
            shots += 1
            sess.kbd.screenshot(str(out / f"{label}-bar-{shots:02d}.png"))
            print(f"  row 24: {row!r}", flush=True)
        if "PRESS" in row or "RETURN" in row or "BUTTON" in row:
            sess.press_kernal(0x0D)
            time.sleep(1.0)
            continue
        sess.handle_prompt(s)
        time.sleep(0.6)
    print(f"  the area never became {want}", flush=True)
    return False


def phase_stack(sess, out) -> None:
    print("phase A: the idle stack", flush=True)
    meta = {"bar": {}, "move": {}}
    meta["bar"]["pcs"] = sample_pcs(sess)
    with sess.mon(5) as m:
        meta["bar"]["stack"] = stack(m)
    print(f"  at the bar: pcs={meta['bar']['pcs']}\n"
          f"  stack={meta['bar']['stack']}", flush=True)
    if not sess.select_bar("MOVE", timeout=20):
        raise RuntimeError("MOVE could not be selected")
    time.sleep(1.0)
    meta["move"]["pcs"] = sample_pcs(sess)
    with sess.mon(5) as m:
        meta["move"]["stack"] = stack(m)
    print(f"  in MOVE: pcs={meta['move']['pcs']}\n"
          f"  stack={meta['move']['stack']}", flush=True)
    (out / "01-idle-stack.json").write_text(json.dumps(meta, indent=1))
    # Back to the bar, so the next phase starts from the state a player
    # leaves the game in most of the time.
    sess.leave_move()
    time.sleep(1.0)


def phase_square(sess, target, out, answer: str) -> dict:
    label = "10-said-no" if answer == "NO" else "20-said-yes"
    print(f"phase {'C' if answer == 'NO' else 'D'}: exit square, answer "
          f"{answer}", flush=True)
    with sess.mon(5) as m:
        m.write(0xC04B, bytes(EXIT_SQUARE))
        stale = list(m.read(0xC04E, 2))
    print(f"  placed at {EXIT_SQUARE}; $C04E/$C04F before redraw = {stale}",
          flush=True)
    info = reenter(sess, AFTER_STEP, ())
    row = wait_row24(sess, ("YES", "NO"))
    with sess.mon(5) as m:
        fresh = list(m.read(0xC04E, 2))
    print(f"  row 24 after re-entry: {row!r}; $C04E/$C04F now = {fresh}",
          flush=True)
    sess.kbd.screenshot(str(out / f"{label}-prompt.png"))
    info.update({"stale": stale, "fresh": fresh, "row24": row})
    if row is None:
        capture(sess, out, label + "-no-prompt", "the handler did not prompt")
        (out / f"{label}.json").write_text(json.dumps(info, indent=1))
        raise RuntimeError("no YES/NO prompt appeared")
    if not sess.select_bar(answer, timeout=20):
        raise RuntimeError(f"{answer} could not be selected")
    time.sleep(1.0)
    if answer == "YES":
        if not answer_until_area(sess, target, EAST, out, label):
            raise RuntimeError("the handler's exit never reached area 27")
    if indoors(sess):
        wait_idle(sess)
    else:
        print("  landed on the travel grid; no indoor key-wait to wait for",
              flush=True)
        sess.settle(6)
    sess.settle(3)
    meta = capture(sess, out, label, f"exit square, answered {answer}")
    info["capture"] = meta["label"]
    (out / f"{label}-reentry.json").write_text(json.dumps(info, indent=1))
    return meta


def phase_second_hop(sess, target, out) -> bool:
    print("phase E: second hop, wilderness to New Phlan", flush=True)
    ft = A.FastTravel()
    area = A.area_by_id(PHLAN)
    verdict = ft.legality(target, area)
    print(f"  legality as shipped: {verdict.ok} "
          f"{'' if verdict.ok else verdict.reason}", flush=True)
    # What `ECL1A $A0A4` writes on the way into any indoor area from the
    # travel grid, minus its `LOADFILES 127, 127, 127`.
    with sess.mon(5) as m:
        m.write(0x49E6, b"\x01")
        m.write(0x6E22, b"\x7f" * 6)
    outcome = ft.run(target, area=area)
    print(f"  run: {outcome.ok} {outcome.message}", flush=True)
    deadline = time.time() + 150
    seen = []
    while time.time() < deadline:
        s = sess.screen()
        row = s.row(24).strip() if s is not None else ""
        if row and (not seen or seen[-1] != row):
            seen.append(row)
            print(f"  row 24: {row!r}", flush=True)
        if A.FastTravel.current_area(target) == PHLAN and indoors(sess):
            break
        sess.handle_prompt(s)
        time.sleep(0.6)
    wait_idle(sess, timeout=60)
    meta = capture(sess, out, "30-second-hop",
                   "warp 27 -> 0 after writing $49E6=1 and $6E22-$6E27=$7F")
    # The first version of this asked for the word ENCAMP on screen and the
    # arrival came up in MOVE mode showing `I,J,K,M, RETURN OR BUTTON`, so a
    # landing that had worked was reported as a failure.  The area byte and
    # `$49E6` are what "landed indoors in New Phlan" means.
    return (meta["6E1B"][0] & 0x7F) == PHLAN and meta["49E6"][0] != 0


def phase_putback(sess, out, where) -> dict:
    """Put the party back on the square it was on, without running a script.

    The `NO` branch of an exit handler leaves the party standing on the exit
    square, because the re-entry teleported it there.  `$0A4C` on its own is
    the redraw and nothing else: re-entered with only the main loop's return
    pushed, its `RTS` lands on `$08A7` and the game carries on at the command
    bar.  Entry 1 never runs, so no square event fires on the way back.
    """
    print(f"phase G: put the party back on {where}", flush=True)
    with sess.mon(5) as m:
        m.write(0xC04B, bytes(where))
    info = reenter(sess, REDRAW, ())
    wait_idle(sess, timeout=90)
    sess.settle(2)
    meta = capture(sess, out, "15-put-back",
                   f"square rewritten to {where} and $0A4C re-entered alone")
    info["capture"] = meta["label"]
    (out / "15-put-back-reentry.json").write_text(json.dumps(info, indent=1))
    return meta


def phase_edge(sess, target, out) -> None:
    print("phase F: edge exit out of New Phlan", flush=True)
    s = sess.screen()
    row = s.row(24) if s is not None else ""
    if "MOVE" in row.split():
        if not sess.select_bar("MOVE", timeout=20):
            raise RuntimeError("MOVE could not be selected")
        time.sleep(1.0)
    else:
        print(f"  already out of the bar; row 24 is {row.strip()!r}",
              flush=True)
    with sess.mon(5) as m:
        m.write(0xC04B, bytes(PHLAN_EDGE))
    print(f"  placed at {PHLAN_EDGE}", flush=True)
    with sess.mon(5) as m:
        print(f"  $C04E/$C04F there = {list(m.read(0xC04E, 2))}", flush=True)
    info = reenter(sess, REDRAW, (FORWARD_KEY - 1,))
    ok = answer_until_area(sess, target, SLUMS, out, "40-edge")
    wait_idle(sess, timeout=120)
    sess.settle(3)
    meta = capture(sess, out, "40-edge-exit",
                   f"re-entered at $0A4C then $0978 at {PHLAN_EDGE}")
    info["capture"] = meta["label"]
    info["reached"] = ok
    (out / "40-edge-reentry.json").write_text(json.dumps(info, indent=1))


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slot = S.claim_slot(args.slot, "issue207 exit re-entry")
    print(f"Slot {slot.n} display {slot.display}", flush=True)
    sess = None
    try:
        boot = S.stage_disks(slot, DISKS)
        shutil.copy(pathlib.Path(args.save).expanduser(),
                    pathlib.Path(slot.dir) / "SIDE0.D64")
        for p in pathlib.Path(slot.dir).glob("*.D64"):
            os.chmod(p, 0o644)
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("Boot failed")
        if not sess.load_save():
            raise RuntimeError("The game did not accept the disk")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        if not sess.wait_for_world(timeout=args.arrive):
            raise RuntimeError("No command bar after BEGIN ADVENTURING")
        sess.settle(4)
        target = SessTarget(sess)
        meta = capture(sess, out, "00-start", "just loaded")
        if (meta["6E1B"][0] & 0x7F) != CAVES:
            raise RuntimeError("the save is not in the Kobold Caves")
        phases = args.phases
        home = tuple(meta["C04B"])
        if "A" in phases:
            phase_stack(sess, out)
        if "C" in phases:
            phase_square(sess, target, out, "NO")
        if "G" in phases:
            phase_putback(sess, out, home)
        if "D" in phases:
            phase_square(sess, target, out, "YES")
        if "E" in phases:
            landed = phase_second_hop(sess, target, out)
            if landed and "F" in phases:
                phase_edge(sess, target, out)
            elif "F" in phases:
                print("  skipping phase F: the second hop did not land",
                      flush=True)
        return 0
    finally:
        for what, fn in (("session", sess.terminate if sess else None),
                         ("slot teardown", slot.teardown),
                         ("slot release", slot.release)):
            if fn is None:
                continue
            try:
                fn()
            except Exception as e:              # noqa: BLE001
                print(f"  {what} failed: {e}", flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default="~/Downloads/npc_party.d64")
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--out", default=str(ROOT / "work" / "issue207" / "run1"))
    p.add_argument("--arrive", type=float, default=240.0)
    p.add_argument("--phases", default="ACGDEF",
                   help="which phases to run, from A C G D E F")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

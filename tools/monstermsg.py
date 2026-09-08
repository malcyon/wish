#!/usr/bin/env python3
"""What the game prints when a **monster** acts, and where it comes from.

`#350 (The Messages window logs the party's attacks and dice but nothing a
monster does)` has two halves. The dice half is explained in `automap/rolls.py`;
this is the tool for the other one -- the words themselves. Four commands, in
increasing order of what they cost:

    tools/monstermsg.py table            # COMBAT's 64 messages, out of SPELLN00
    tools/monstermsg.py sites            # every place COMBAT prints one
    tools/monstermsg.py replay F.jsonl   # a recorded fight, through CombatLog
    tools/monstermsg.py fight --slot 3   # drive one and poll as the window does

**`table` and `sites` are the evidence that cannot be poisoned**, because they
read the shipped overlay rather than any specimen. `SPELLN00` loads at `$AF00`
and is 128 pointers -- lo `$AF00`, hi `$AF80` -- into strings from `$B000`;
entries 1-56 are the spell names, and `COMBAT` indexes the same table as
`X + $39`, so its messages 0-63 are entries 57-120. Nothing in it is
monster-specific: `COMBAT $0D63` prints a melee attack for whoever swung, from
the same table, into the same window, with the same delay.

`sites` finds the printers' callers by looking back from each
`JSR $2983`/`$299A`/`$29BA` for the `LDX #imm` that set the index. That is a
byte scan and not a control-flow analysis: a site whose index is loaded
somewhere else, or stepped with `INX`, is reported as `?` rather than guessed
at, and a hit inside a string table would be a false one. Read it as an
inventory to check by hand, not as a proof.

`replay` takes any JSON-lines capture carrying a whole-screen `scr` and the
four window bytes `win2` -- `work/rolls/run1.jsonl` is the shape -- and runs it
through today's `automap/combatlog.py`, so a reader change can be checked
against a fight nobody has to drive again.

`fight` is the live measurement: it boots a pool slot, loads the player's save,
walks into an ambush and then polls the message panel **at the interval the
Messages window itself uses** (`AutomapBinding`'s 200 ms tick, one burst a
tick) while driving the party's own turns. Every poll goes to the log with the
acting combatant `$A4F4`, so a message can be attributed to the party or to a
monster, and the summary is the count of each.

Nothing here writes to the player's disks: `Session` stages copies into the
slot's own directory. Nothing it prints is committed -- the game's strings go
to a terminal and to `work/`, and the repository keeps only the findings.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import combatlog, rolls  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from automap.screen import band  # noqa: E402
from tools import overlay  # noqa: E402

#: Where `SPELLN00` is loaded, and the shape of its pointer table.
SPELLN_LOAD = 0xAF00
SPELLN_ENTRIES = 128
#: The high bytes sit at `$AF80`, which `COMBAT $29A8 LDY $AF80,X` reads --
#: **not** at half the entry count into the file. The file's own load address
#: says `$2710` and is a lie; it is loaded at `$AF00`, so offset 0 is `$AF00`.
SPELLN_HI = 0x80
#: `COMBAT $29A2 ADC #$39`: the overlay's message 0 is the table's entry 57.
COMBAT_FIRST = 0x39
#: Entries past this are padding -- `$FF00`, `$20FF`, addresses no string
#: could be at. 120 is `SURRENDERS`, the last one with text behind it.
COMBAT_MESSAGES = 64

#: The three printers, all in `COMBAT`. `$2983` clears the panel and starts a
#: block; `$299A` adds a fragment under what is showing; `$29BA` starts a
#: follow-up block by moving `$03F4` to the row below the cursor.
PRINTERS = {0x2983: "block", 0x299A: "fragment", 0x29BA: "follow-up"}
#: How far back from a `JSR` to look for the `LDX #imm` that set the index.
LOOKBACK = 10

#: `automap/combat.py`: 0-7 are the party, 8 upward the monsters.
FIRST_MONSTER = 8


# -- the table ---------------------------------------------------------------

def spelln_strings(root: str) -> list[tuple[int, int, str | None]]:
    """Every entry of `SPELLN00`'s table as (index, address, text).

    `text` is None where the pointer does not land inside the file, which is
    what the padding past the last real string does.
    """
    _declared, data = overlay.load("SPELLN00", root)
    out = []
    for i in range(SPELLN_ENTRIES):
        addr = data[i] | (data[SPELLN_HI + i] << 8)
        at = addr - SPELLN_LOAD
        if not 0 <= at < len(data):
            out.append((i, addr, None))
            continue
        text = bytearray()
        while at < len(data) and data[at] not in (0x00, 0xFF):
            text.append(data[at])
            at += 1
        out.append((i, addr, text.decode("latin-1")))
    return out


def combat_messages(root: str) -> dict[int, str]:
    """COMBAT's message number -> the text, for the ones that have text."""
    table = spelln_strings(root)
    out = {}
    for n in range(COMBAT_MESSAGES):
        _i, _addr, text = table[COMBAT_FIRST + n]
        if text:
            out[n] = text
    return out


# -- where they are printed from ---------------------------------------------

def print_sites(root: str) -> list[tuple[int, int, int | None, str]]:
    """Every `JSR` to a printer in COMBAT: (address, printer, index, how).

    `index` is None where no `LDX #imm` sits within `LOOKBACK` bytes, and
    `how` says which it was so a reader can weigh it.
    """
    _declared, body = overlay.load("COMBAT", root)
    base = overlay.LINKER_BASE
    found = []
    for at in range(len(body) - 2):
        if body[at] != 0x20:
            continue
        target = body[at + 1] | (body[at + 2] << 8)
        if target not in PRINTERS:
            continue
        index, how = None, "not set here"
        for back in range(1, LOOKBACK + 1):
            if at - back < 0:
                break
            if body[at - back] == 0xA2:          # LDX #imm
                index, how = body[at - back + 1], f"LDX #imm, {back} back"
                break
            if body[at - back] == 0xE8:          # INX, as at $0D86
                how = "stepped with INX"
        found.append((base + at, target, index, how))
    return found


# -- replaying a recorded fight ----------------------------------------------

def replay(path: pathlib.Path) -> list:
    """Run a capture's frames through `CombatLog` and return the messages.

    Wants `scr` (1000 screen codes, hex) and `win2` (`$03F2`-`$03F5`, hex) on
    each line; anything else is skipped, so a log with world rows in it works.
    """
    log = combatlog.CombatLog()
    out = []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if "scr" not in row or "win2" not in row:
            continue
        codes = bytes.fromhex(row["scr"])
        left, right, top, bottom = combatlog.message_window(
            bytes.fromhex(row["win2"]))
        rows = band(codes, left, right)[combatlog.MESSAGE_TOP:bottom]
        out += log.observe(rows, top)
    out += log.flush()
    return out


# -- the live measurement ----------------------------------------------------

class _Target:
    """What `CombatLog.poll` wants, over one monitor connection."""

    def __init__(self, m):
        self.m = m

    def read(self, addr, length):
        return self.m.read(addr, length)


def _name_at(raw: bytes) -> str:
    """The resident record's name, as the engine holds it at `$6B00`."""
    return raw.split(b"\x00")[0].decode("latin-1", "replace").strip()


def _combatant_names(m) -> dict[int, str]:
    """Combatant index -> the name `automap/combat.py` reads for it.

    The same dictionary `AutomapBinding.log_combat` builds and hands to
    `combatlog.recase`, so comparing it against the name the engine printed
    on row 10 says whether the two agree without arguing about it.
    """
    from automap.combat import read_battle

    battle = read_battle(_Target(m))
    if battle is None:
        return {}
    return {c.index: c.name.strip() for c in battle.combatants}


def drive(args) -> int:
    """Boot, find a fight, and poll the message panel as the window does."""
    from tools import session as S

    out = pathlib.Path(args.out or ROOT / "work" / "issue350" / "fight.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    disks = pathlib.Path(args.disks)
    slot = S.claim_slot(args.slot, "monstermsg")
    log = combatlog.CombatLog()
    lines = out.open("w")
    sess = None
    said: list[dict] = []
    polls = 0
    gaps: list[float] = []

    def emit(kind, **kw):
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        lines.write(json.dumps(kw, default=str) + "\n")
        lines.flush()

    def keep(messages, actor, target, name, names=None):
        names = names or {}
        for msg in messages:
            who = msg.roll.actor if msg.roll is not None else actor
            row = {"text": msg.text, "rows": list(msg.lines),
                   "subject": msg.subject, "outcome": msg.outcome,
                   "damage": msg.damage, "actor": who, "target": target,
                   "monster": who is not None and who >= FIRST_MONSTER,
                   "resident": name, "backend_name": names.get(who),
                   "target_name": names.get(target),
                   "names": {str(k): v for k, v in names.items()}}
            # The dice the same poll read, which is `#350`'s other half: a
            # monster's roster block is at `$8300 + index * 32` like anybody
            # else's, so `needed` being filled in for an actor of 8 or more is
            # the whole question.
            if msg.roll is not None:
                row["roll"] = {"d20": msg.roll.d20, "raw": msg.roll.raw,
                               "hit": msg.roll.hit, "needed": msg.roll.needed,
                               "dice": msg.roll.dice,
                               "damage": msg.roll.damage}
                row["roll_line"] = rolls.roll_line(msg, names)
            said.append(row)
            emit("message", **row)
            print(f"  [{'monster' if row['monster'] else 'party  '} "
                  f"{who}] {msg.text}", flush=True)

    try:
        sess = S.Session(S.stage_disks(slot, disks, args.save), slot=slot)
        print(f"slot {slot.n} display {slot.display}  log {out}", flush=True)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        emit("world", at=list(sess.position()))
        steps = 0
        while not sess.in_combat():
            if steps > args.steps:
                raise RuntimeError("route exhausted with no fight")
            sess.walk_one(args.walk)
            sess.handle_prompt()
            steps += 1
        emit("fight_start", steps=steps)
        print(f"fight after {steps} steps", flush=True)
        if args.delay is not None:
            # The game's own message delay, `COMBAT $28C3`'s `$49FC`, which a
            # player sets with SPEED. `INIT $09AC` puts it at 2 -- about a
            # second a message -- and at 0 the panel is cleared with no delay
            # at all. Poked here, once COMBAT is resident, so the run measures
            # what a player who has turned the speed up would see.
            with sess.mon(5) as m:
                was = m.read(combatlog.DELAY, 1)[0]
                m.write(combatlog.DELAY, bytes([args.delay]))
                now = m.read(combatlog.DELAY, 1)[0]
            emit("delay", was=was, asked=args.delay, now=now)
            print(f"message delay $49FC: {was} -> {now}", flush=True)

        end = time.time() + args.budget
        last_poll = 0.0
        actor = target = None
        name = ""
        while time.time() < end and sess.mode() == S.COMBAT:
            now = time.time()
            if now - last_poll >= args.every:
                if last_poll:
                    gaps.append(now - last_poll)
                last_poll = now
                try:
                    with sess.mon(8) as m:
                        done = log.poll(_Target(m))
                        state = m.read(0xA4F4, 2)
                        raw = m.read(0x6B00, 16)
                        # Only when there is something to attribute: this is
                        # two more bursts, and `#345`'s question -- is the
                        # name the engine printed the name our backend reads
                        # for that combatant? -- is only asked of a message.
                        names = _combatant_names(m) if done else {}
                    polls += 1
                    actor, target = state[0], state[1]
                    name = _name_at(raw)
                    keep(done, actor, target, name, names)
                except Exception as exc:                 # a wedged read is not
                    emit("poll_failed", error=repr(exc))  # the end of the run
            s = sess.screen()
            text = s.text() if s is not None else ""
            if S.LOST_TEXT in text or S.WON_TEXT in text:
                emit("outcome", text=S.LOST_TEXT if S.LOST_TEXT in text
                     else S.WON_TEXT)
                break
            bar = sess.combat_state(s)
            if bar.kind == S.BAR_COMMAND:
                emit("turn", bar=bar.text)
                sess.melee_turn(bar) if args.attack else sess.combat_turn()
            elif bar.kind == S.BAR_DONE:
                sess.end_turn()
            elif bar.kind in (S.BAR_PRESS,):
                sess.press_kernal(0x0D)
            elif bar.kind == S.BAR_MOVE:
                sess.press_kernal(0x0D)
            elif bar.kind in (S.BAR_YESNO, S.BAR_CONTINUE):
                sess.combat_bar("NO", timeout=8)
            elif bar.kind == S.BAR_DISK:
                sess.handle_prompt(s)
            else:
                sess.idle(args.every / 4)
        keep(log.flush(), actor, target, name)
    except Exception as exc:
        import traceback
        emit("failed", error=repr(exc), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        monsters = [r for r in said if r["monster"]]
        party = [r for r in said if r["actor"] is not None
                 and not r["monster"]]
        emit("summary", polls=polls, messages=len(said),
             monster_messages=len(monsters), party_messages=len(party),
             mean_gap=round(sum(gaps) / len(gaps), 3) if gaps else None,
             worst_gap=round(max(gaps), 3) if gaps else None)
        print(f"\n{polls} polls, {len(said)} messages: "
              f"{len(monsters)} a monster's, {len(party)} the party's", flush=True)
        if gaps:
            print(f"poll gap: mean {sum(gaps) / len(gaps):.2f}s "
                  f"worst {max(gaps):.2f}s", flush=True)
        lines.close()
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:                       # noqa: BLE001
                print(f"{what}: {exc!r}", file=sys.stderr)
    return 0


# -- command line ------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disks", default=os.environ.get("POR_DISKS")
                   or str(find_disks() or ""),
                   help="where the game disks are; read, never written")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("table", help="COMBAT's messages, out of SPELLN00")
    sub.add_parser("sites", help="every place COMBAT prints one")
    rp = sub.add_parser("replay", help="a recorded fight through CombatLog")
    rp.add_argument("file")
    fp = sub.add_parser("fight", help="drive one and poll as the window does")
    fp.add_argument("--save", default="PORSAVE13.D64")
    fp.add_argument("--slot", type=int, default=None)
    fp.add_argument("--budget", type=float, default=420.0)
    fp.add_argument("--every", type=float, default=0.2,
                    help="seconds between polls; the window's own tick")
    fp.add_argument("--walk", default="I")
    fp.add_argument("--steps", type=int, default=400)
    fp.add_argument("--attack", action="store_true",
                    help="fight back rather than guarding every turn")
    fp.add_argument("--delay", type=int, default=None,
                    help="poke the game's own message delay $49FC once the "
                         "fight starts; 0 is what SPEED at its fastest leaves")
    fp.add_argument("--out", default=None)
    args = p.parse_args(argv)

    if args.cmd == "fight":
        return drive(args)

    if not args.disks or not os.path.isdir(args.disks):
        print("No game disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2

    if args.cmd == "table":
        for n, text in sorted(combat_messages(args.disks).items()):
            print(f"COMBAT #{n:<3} table {COMBAT_FIRST + n:<4} {text!r}")
        return 0

    if args.cmd == "sites":
        texts = combat_messages(args.disks)
        for addr, printer, index, how in print_sites(args.disks):
            what = "?" if index is None else texts.get(index, "(no text)")
            shown = "?" if index is None else f"#{index}"
            print(f"${addr:04X}  JSR ${printer:04X} {PRINTERS[printer]:<10}"
                  f" {shown:<5} {what!r:<20} {how}")
        return 0

    if args.cmd == "replay":
        for msg in replay(pathlib.Path(args.file)):
            print(f"{msg.subject!s:<12} {msg.outcome!s:<10} {msg.text}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

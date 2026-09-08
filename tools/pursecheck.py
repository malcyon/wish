#!/usr/bin/env python3
"""Edit a later title's seven purses in Wish, then read them off the game's
own character sheet.

`docs/139-per-title-validation.md` A8 -- *"the seven money fields"* -- has read
`V (gold only)` for Curse of the Azure Bonds and Secret of the Silver Blades
since it was written, with the note *"the other six purses are untested on any
title but Pool of Radiance"*. It is the last unverified cell in that table
anybody on this project can reach. `#33 (One Silver Blades session, for the
whole editor path)` and `#32 (One Curse session, to get a party with items)`
are the two tickets it belongs to.

**The screen is `VIEW`, not `TRADE`, and the reason no capture has ever shown
a second purse is that every character had one.** The sheet's money box draws
all seven, and skips any purse whose sixteen bits are zero -- read out of the
engine, in both later titles:

    LIBRARY $3D3E (Curse) / $31F2 (Silver Blades)
        LDA #$06 / STA $7EBA            seven purses, counted down
        LDA $7EBA / ASL A / TAY
        LDA $7CBB,Y / ORA $7CBC,Y       the purse at record 0x0BB + 2n
        BEQ <next>                      a zero purse draws no line at all
        LDX $3D96,Y                     22 23 24 25 26 27 39, the label ids
        ... print the label, then the number ...
        DEC $7EBA / BPL <top>

`22`-`27` and `39` are `COPPER SILVER ELECTRUM GOLD PLATINUM GEMS` and
`JEWELRY` in each title's own string table -- Curse's inside `LIBRARY`, with
its pointer pair at `$35C4`/`$3608`, and Silver Blades' inside `ITEMNAMES` at
`$9E8C`/`$9F8C`. Silver Blades' `SILVER` is the one entry whose pointer leaves
the run and lands in the item-name text, which is why a raw scan of that file
appears to show a table with no `SILVER` in it.

Two subcommands:

    tools/pursecheck.py stage \\
        --base ~/wish-specimens/coab-c64/WISH-SPEC-curse-party-with-items.D64 \\
        --out work/issue139-a8/curse-edited.D64 --who "MALE ELF MAGE"

        Copy the disk and set the seven purses **through the form's own spin
        boxes**, so `EditorBinding._flush` is what writes them -- the path a
        player's typing takes. Prints the seven before and after and the
        encumbrance the engine ought to compute from them.

    tools/pursecheck.py run --save work/issue139-a8/curse-edited.D64 \\
        --out work/issue139-a8/curse-edited-run --who "MALE ELF MAGE"

        Claim a pooled VICE slot, boot whichever title the save is, load the
        party through the game's own `LOAD SAVED GAME`, and photograph the
        `VIEW CHARACTER` sheet of `--who`. Writes one JSON line per event as
        it goes, so a run that dies half-way still says how far it got.

**Stage the control before the boot, and read it with the engine.** `stage`
with no purse arguments copies the disk and runs it through the same handlers,
which report `no changes`; booting *that* disk is what says the edited run
measured the edit rather than the sheet. A second control is an untouched
character on the edited disk, whose money box has to stay as it was.

**`--also` wants a second character out of the same boot and does not work
yet**, on either title: the sheet's `EXIT` is on the command bar rather than
in a list, and the press does not take -- `#444 (A driven session cannot leave
a Curse or Silver Blades character sheet, so each sheet costs its own boot)`
carries the two readings. Until that closes, run the tool again with `--who`
naming the second character; every reading in `docs/139` A8 was taken that
way, at one boot each.

The party-formation menu is enough for this screen, unlike the item list --
`work/issue33/run1/03-sheet.txt` shows a sheet reached that way drawing
`GOLD 4321` and `ENCUMBRANCE 4321`, and `LIBRARY`'s money box is the tail of
the one sheet routine each title has, entered by `JMP $3D3E` at Curse's
`$37B7` and `JSR $31F2` at Silver Blades' `$3121`. So the world's `VIEW` draws
the same box, and a run whose formation-menu picker will not answer can be
taken there instead -- `tools/inventorycheck.py` has that route working on
both titles, at the cost of `patch_disk_prompt` and a disk load.

Nothing writes where the player's disks are: `--base` is copied before a byte
of it is touched, and each title's own `stage` copies the sides into the pool
slot.
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

from goldbox import c64_save, games  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from goldbox.items import ITEM_SIZE, ITEMS_PER_CHARACTER, Item  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402

#: The seven purses, in the order the record stores them at `0x0BB`-`0x0C8`
#: and in the order the engine's own label table names them.  The sheet draws
#: them the other way up, jewelry first, because its loop counts down.
PURSES = ("copper", "silver", "electrum", "gold", "platinum", "gems",
          "jewelry")

#: What the sheet prints beside each purse, per `goldbox/layout.py`'s field
#: names and the engine's string table.  `GEMS` and `JEWELRY` are counts
#: rather than coins, and the engine weighs them the same as a coin.
LABELS = {"copper": "COPPER", "silver": "SILVER", "electrum": "ELECTRUM",
          "gold": "GOLD", "platinum": "PLATINUM", "gems": "GEMS",
          "jewelry": "JEWELRY"}

#: `ENCUMBRANCE` is not a purse and is not stored on the C64 at all: the
#: engine recomputes it while drawing the sheet.  Reading it is what turns a
#: screenshot of seven labels into a check that the engine read seven
#: *numbers* -- `goldbox/dos.py:expected_encumbrance` is the same identity.
ENCUMBRANCE = "ENCUMBRANCE"


# --- reading the save from outside the editor --------------------------------

def _container(path: str | pathlib.Path):
    disk = D64.open(str(path))
    game = games.detect(disk)
    if game is None:
        raise SystemExit(f"{path}: no Gold Box save on this disk")
    return disk, game, c64_save.CONTAINERS[game.key]


def purses_on_disk(path: str | pathlib.Path, slot: int) -> dict[str, int]:
    """One character's seven purses, read back off the written disk.

    Through `goldbox.savegame` rather than through the widgets that set them,
    because what this has to answer is whether the editor's writer put the
    bytes where the engine reads them.
    """
    _game, sg0, _sg1 = load_save(D64.open(str(path)))
    record = next(s.record for s in sg0.slots
                  if s.record is not None and s.index == slot)
    return {name: record.get(name) for name in PURSES}


def item_weight(path: str | pathlib.Path, slot: int) -> int:
    """`sum(weight x quantity)` over one character's sixteen item records.

    The weight is in tenths of a pound and the engine adds it to a purse of
    coins without scaling either, which is the arithmetic
    `goldbox/dos.py:expected_encumbrance` does and what `MATHEW`'s
    `PLATINUM 288` beside `ENCUMBRANCE 803` says the C64 does too.

    A quantity of zero means one -- the field counts *extra* copies for
    anything that does not stack -- which is the rule
    `goldbox/dos.py:expected_encumbrance` uses and the only one under which
    the identity balances.
    """
    disk, game, container = _container(path)
    _, payload = split_load_address(disk.read_file(game.save_file))
    base = container.items(slot)
    total = 0
    for n in range(ITEMS_PER_CHARACTER):
        raw = bytes(payload[base + n * ITEM_SIZE: base + (n + 1) * ITEM_SIZE])
        if not any(raw):
            continue
        item = Item(raw)
        total += item.weight_tenths * (item.quantity or 1)
    return total


def expected_encumbrance(path: str | pathlib.Path, slot: int) -> int:
    """What the engine should draw beside `ENCUMBRANCE` for this character."""
    return sum(purses_on_disk(path, slot).values()) + item_weight(path, slot)


# --- staging: the edits, through the form's own spin boxes -------------------

def stage(base: str, out: str, who: str, values: dict[str, int]) -> dict:
    """Copy `base` to `out` and set `who`'s purses in Wish.

    The values go into the `field_<purse>` spin boxes and are written by
    `EditorBinding._flush` on save, which is the path a player's typing takes.
    Setting the record directly would skip the widget, the bound range and the
    flush, and those are three of the things this is meant to exercise.

    Qt runs offscreen: `QT_QPA_PLATFORM=offscreen` is set here rather than
    left to the caller, because nothing an agent runs may put a window on the
    machine's screen.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.pop("WAYLAND_DISPLAY", None)
    from PyQt6.QtWidgets import QApplication, QMainWindow, QSpinBox

    dest = pathlib.Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(base, dest)
    dest.chmod(0o644)

    app = QApplication.instance() or QApplication([])
    from editor.window import EditorBinding
    from wish.ui_window import Ui_WishWindow

    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    editor = EditorBinding(root, str(dest))
    party = editor.party
    if party is None:
        raise SystemExit(f"{dest}: nothing opened")

    row = next((i for i, m in enumerate(party.members)
                if m.record.name.upper() == who.upper()), None)
    if row is None:
        raise SystemExit(f"{dest}: no character called {who!r}; the party is "
                         + ", ".join(m.record.name for m in party.members))
    # Selecting the row is what fills the widgets from this record, so it has
    # to happen before anything is typed into one: `_populate` would
    # otherwise overwrite the new values with the ones on the disk.
    editor.roster.selectRow(row)
    slot = party.member(row).index

    before = purses_on_disk(dest, slot)
    steps: list[str] = []
    for name, value in values.items():
        widget = root.findChild(QSpinBox, f"field_{name}")
        if widget is None:
            raise SystemExit(f"the form has no field_{name} spin box")
        if not widget.isEnabled():
            raise SystemExit(f"field_{name} is disabled, so this title does "
                             f"not store {name} in the save slot")
        widget.setValue(value)
        steps.append(f"field_{name} set to {widget.value()}")

    note = editor.save(interactive=False)
    after = purses_on_disk(dest, slot)
    report = {
        "base": str(base), "out": str(dest), "who": who, "slot": slot,
        "row": row, "save_said": note, "steps": steps,
        "before": before, "after": after,
        "item_weight": item_weight(dest, slot),
        "expected_encumbrance": expected_encumbrance(dest, slot),
        "party": [m.record.name for m in party.members],
    }
    app.processEvents()
    return report


# --- reading the sheet -------------------------------------------------------

def money_box(rows: list[str]) -> dict[str, int]:
    """Every purse the sheet drew, and the encumbrance beside it.

    The two titles lay the sheet out differently -- Curse puts `PLATINUM 288`
    on the same row as `STR 18(100)` and Silver Blades gives the money its own
    boxed column -- so this reads labels wherever they fall rather than at a
    column either title happens to use.  A label with no number after it is
    not a purse and is left out, which is how `GEMS` in an item name would
    have to look to be mistaken for one.
    """
    found: dict[str, int] = {}
    for row in rows:
        for field, label in list(LABELS.items()) + [(ENCUMBRANCE,
                                                     ENCUMBRANCE)]:
            at = row.find(label)
            while at >= 0:
                rest = row[at + len(label):]
                # The next run of digits, and nothing else between: a label
                # followed by another word is a different line of the sheet.
                head = rest.lstrip()
                digits = ""
                for ch in head:
                    if ch.isdigit():
                        digits += ch
                    else:
                        break
                if digits and (not rest[:len(rest) - len(head)].strip()):
                    found[field] = int(digits)
                    break
                at = row.find(label, at + 1)
    return found


class Run:
    """One driven session, logging every event as it happens.

    A `timeout` around the whole tool skips any `finally`, so nothing is held
    back to be written at the end: each event is a JSON line flushed when it
    occurs.
    """

    def __init__(self, out: pathlib.Path):
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True)
        self.log_path = self.out / "run.jsonl"
        self.shots = 0

    def log(self, event: str, **fields) -> None:
        line = json.dumps({"t": round(time.time(), 2), "event": event,
                           **fields}, default=str)
        with self.log_path.open("a") as fh:
            fh.write(line + "\n")
        print(line, flush=True)

    def capture(self, sess, tag: str) -> list[str]:
        """The text screen and a photograph of it, both kept."""
        self.shots += 1
        stem = f"{self.shots:02d}-{tag}"
        s = sess.screen()
        rows = [s.row(r).rstrip() for r in range(25)] if s is not None else []
        (self.out / f"{stem}.txt").write_text("\n".join(rows) + "\n")
        sess.kbd.screenshot(str(self.out / f"{stem}.png"))
        self.log("screen", tag=tag, stem=stem,
                 lines=[r for r in rows if r.strip()])
        return rows


def sheet_up(s) -> bool:
    """Is a character sheet the thing on the screen?

    Curse's sheet bar is `ITEMS ... EXIT` and Silver Blades' is
    `TRADE DROP EXIT`; the world's own bar is
    `MOVE VIEW CAST AREA ENCAMP SEARCH LOOK` and the formation menu has no
    bar at all.  So `EXIT` without `ENCAMP` is the pair that says a sheet has
    replaced whichever of the two we came from -- the same reading as
    `tools/inventorycheck.py:sheet_up` and `CurseSession.sheet_is_up`.
    """
    row = s.row(24)
    return "EXIT" in row and "ENCAMP" not in row


def wait_for_sheet(sess, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = sess.screen()
        if s is not None and sheet_up(s) and s.row(1).strip():
            return True
        time.sleep(0.4)
    return False


def at_menu(s) -> bool:
    """The party-formation menu, named by the row only it has."""
    return "BEGIN ADVENTURING" in s.text()


def at_picker(s) -> bool:
    """`VIEW WHICH CHARACTER?`, which is a list of names with `EXIT` on it."""
    return "WHICH CHARACTER" in s.row(24).upper()


def sheet_of(sess, r: Run, name: str, walk) -> list[str] | None:
    """This character's sheet, from wherever the front end is standing.

    `walk` is the title's own way of pressing Return on a **vertical list**:
    Curse reads it from the KERNAL buffer on this front end
    (`tools/dualclassagain.py:walk_menu`) and Silver Blades from XTEST
    (`Session.select_row`), and neither answers the other's.  The sheet's own
    `EXIT` is not a list row and is left to `leave_sheet`.
    """
    s = sess.screen()
    if s is not None and at_menu(s):
        if not walk(sess, "VIEW CHARACTER"):
            r.log("view", ok=False, why="VIEW CHARACTER is not on this menu")
            r.capture(sess, f"no-view-{name}")
            return None
        sess.settle(3.0)
    picker = r.capture(sess, f"picker-{name}")
    if not any(name in line for line in picker):
        r.log("picker", ok=False, who=name, why="not in the list")
        return None
    if not walk(sess, name):
        r.log("picker", ok=False, who=name, why="could not be picked")
        r.capture(sess, f"no-pick-{name}")
        return None
    if not wait_for_sheet(sess):
        r.log("sheet", ok=False, who=name, why="no sheet came up")
        r.capture(sess, f"no-sheet-{name}")
        return None
    sess.settle(2.0)
    return r.capture(sess, f"sheet-{name}")


def leave_sheet(sess, r: Run, walk) -> bool:
    """Off the sheet and back to the picker, for the next character.

    **The sheet's `EXIT` is on the command bar and the picker's is a row in
    its own list**, and the two take different keys.  Asking `select_row` for
    the bar's `EXIT` walked the highlight the wrong way and pressed `TRADE`,
    which is what `work/issue139-a8/ssb-edited-run/04-no-view-MALACHITE.txt`
    caught: the run came back on `TRADE TO ?` with a side prompt behind it and
    the second character never read.  `tools/inventorycheck.py:press_bar` is
    the bar half -- Curse and Silver Blades read Return from the KERNAL buffer
    on some screens and from XTEST on others, and which is which is a
    per-screen fact `CurseSession.press_bar` already measures.
    """
    from tools.inventorycheck import press_bar

    for attempt in range(3):
        s = sess.screen()
        if s is None:
            sess.settle(1.5)
            continue
        if at_picker(s) or at_menu(s):
            return True
        if not sheet_up(s):
            r.log("leave", ok=False, row24=s.row(24).strip())
            return False
        took = press_bar(sess, "EXIT", timeout=12)
        r.log("leave-try", attempt=attempt, bar=s.row(24).strip(),
              press_bar=took)
        sess.settle(2.5)
        # **A bar with one word on it may not be highlighted at all**, and
        # `Session.select_bar` walks a highlight it cannot find, so it presses
        # nothing and times out -- the same shape as Curse's colour-7 item bar
        # in `docs/120-curse-testing.md` §3.3.  A sheet whose character can
        # neither trade nor drop draws `EXIT` alone, so send both Returns
        # rather than leave the run stuck on a screen with one way off it.
        if not took:
            sess.kbd.key("Return")
            sess.settle(1.5)
            sess.press_kernal(0x0D)
            sess.settle(2.0)
    r.log("leave", ok=False, why="still on the sheet after three tries")
    return False


def curse_boot(slot, r: Run, save: str, where: str, wait: float):
    """Boot Curse and load the party as far as the formation menu."""
    from tools import curseload, curserun

    first = curserun.stage(slot, where, save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    # The specimen tree is read only and `stage` copied it; the copy in the
    # slot is ours to write to.
    os.chmod(save_disk, 0o644)
    sess = curserun.CurseSession(first, slot=slot)
    sess.save_disk = save_disk
    r.log("staged", save=save, side0=save_disk)
    if not sess.boot():
        r.log("boot", ok=False)
        r.capture(sess, "boot-failed")
        return sess, False
    r.log("boot", ok=True)
    outcome = curseload.load_saved_game(sess, wait=wait)
    r.log("load", outcome=outcome)
    if outcome != "loaded":
        r.capture(sess, "load-failed")
        return sess, False
    return sess, True


def ssb_boot(slot, r: Run, save: str, where: str, wait: float):
    """Boot Silver Blades and load the party as far as the formation menu."""
    from tools import ssbwarp

    first = ssbwarp.stage(slot, where, save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    os.chmod(save_disk, 0o644)
    sess = ssbwarp.SSBSession(first, slot=slot)
    sess.save_disk = save_disk
    r.log("staged", save=save, side0=save_disk)
    if not sess.boot():
        r.log("boot", ok=False)
        r.capture(sess, "boot-failed")
        return sess, False
    r.log("boot", ok=True)
    if not ssbwarp.load_party(sess, timeout=wait):
        r.log("load", outcome="failed")
        r.capture(sess, "load-failed")
        return sess, False
    r.log("load", outcome="loaded")
    return sess, True


def curse_walk(sess, label: str) -> bool:
    from tools import dualclassagain
    return dualclassagain.walk_menu(sess, label)


def ssb_walk(sess, label: str) -> bool:
    return sess.select_row(label, timeout=30.0)


#: Which driver boots which title, the `tools/gamedisks.py` key its sides are
#: found under, and how a vertical list takes Return there.
DRIVERS = {
    "curse-of-the-azure-bonds": ("curse-of-the-azure-bonds", curse_boot,
                                 curse_walk),
    "secret-of-the-silver-blades": ("secret-of-the-silver-blades", ssb_boot,
                                    ssb_walk),
}


def run(save: str, out: str, who: str, also: list[str], pool: int | None,
        disks: str = "", wait: float = 300.0) -> int:
    """Boot whichever title the save is and read `who`'s money box."""
    from tools import gamedisks
    from tools import session as por

    game = games.detect(D64.open(save))
    if game is None or game.key not in DRIVERS:
        raise SystemExit(f"{save}: no later-title save on this disk "
                         f"({game.title if game else 'nothing detected'})")
    key, boot, walk = DRIVERS[game.key]
    where = disks or str(gamedisks.find(key) or "")
    if not where:
        raise SystemExit(f"no {game.title} sides: pass --disks")
    r = Run(pathlib.Path(out))
    slot = por.claim_slot(pool, note=os.environ.get("POR_AGENT", "a8"))
    r.log("slot", n=slot.n, monitor=slot.port, cmd=slot.cmd_port,
          display=slot.display, dir=str(slot.dir), title=game.title)
    sess = None
    read: dict[str, dict[str, int]] = {}
    try:
        sess, ok = boot(slot, r, save, where, wait)
        if not ok:
            return 1
        sess.settle(3.0)
        r.capture(sess, "party-menu")
        for n, name in enumerate([who] + list(also)):
            rows = sheet_of(sess, r, name, walk)
            if rows is None:
                r.log("sheet", ok=False, who=name)
                break
            box = money_box(rows)
            read[name] = box
            r.log("money", who=name, box=box,
                  drawn=[f for f in PURSES if f in box])
            if n < len(also) and not leave_sheet(sess, r, walk):
                break
        r.log("done", ok=bool(read.get(who)), read=read)
        return 0 if read.get(who) else 1
    finally:
        if sess is not None:
            sess.terminate()
        slot.teardown()
        r.log("torn down")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("stage", help="set the purses through the editor")
    s.add_argument("--base", required=True, help="the save disk to copy")
    s.add_argument("--out", required=True, help="where the edited copy goes")
    s.add_argument("--who", required=True, help="the character to edit")
    for name in PURSES:
        s.add_argument(f"--{name}", type=int, default=None,
                       help=f"set {name} to this")
    s.add_argument("--json", default="", help="write the report here as well")

    d = sub.add_parser("run", help="boot the save and read the money box")
    d.add_argument("--save", required=True, help="the save disk to boot")
    d.add_argument("--out", required=True, help="a directory for this run")
    d.add_argument("--who", required=True, help="the edited character's name")
    d.add_argument("--also", action="append", default=[],
                   help="another character to view, as a control")
    d.add_argument("--pool", type=int, default=None, help="demand this slot")
    d.add_argument("--disks", default="", help="the six sides")
    d.add_argument("--wait", type=float, default=300.0,
                   help="seconds to wait for the load")

    args = ap.parse_args(argv)
    if args.cmd == "stage":
        values = {name: getattr(args, name) for name in PURSES
                  if getattr(args, name) is not None}
        report = stage(args.base, args.out, args.who, values)
        text = json.dumps(report, indent=2)
        print(text)
        if args.json:
            pathlib.Path(args.json).write_text(text + "\n")
        return 0
    return run(args.save, args.out, args.who, args.also, args.pool,
               args.disks, args.wait)


if __name__ == "__main__":
    sys.exit(main())

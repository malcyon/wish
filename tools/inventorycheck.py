#!/usr/bin/env python3
"""Edit a later title's inventory in Wish, then read it off the game's own
item screen.

`docs/139-per-title-validation.md` A13 -- *"inventory edit, add, remove"* --
is `V` for Pool of Radiance and `U` for both later titles, and it is the
thinnest cell in the table: the editor can add, delete and retype an item on
a Curse or Silver Blades save and nobody has ever watched the game draw the
result. `#32 (One Curse session, to get a party with items)` step 4 is the
same sentence -- *"round-trip an item edit and confirm it in the game"*.

`tools/ssbedit.py` is the shape this follows and could not be reused: it
stages `name`, `gold` and `strength`, which are fields of the character
record. Items are not in the record at all -- they live in `SAVEDGAME0` at
the container's own `item_area` -- so nothing about the staging transfers,
and the reading is a screen `ssbedit.py` never opens. What *is* shared is
the rule: **the edits go through the program's own handlers**,
`EditorBinding.add_item`, `EditorBinding.delete_item` and
`InventoryModel.setData`, and never a second writer of this file's own.

Three edits, one per verb in the A13 row, all on one character:

| verb | what `stage` does | what the game should draw |
|---|---|---|
| remove | `delete_item` on the first `--delete` rows | that many fewer rows on the list |
| edit | `setData` on the quantity column | a count in front of the item's name |
| add | `add_item` with a template off the player's own game disks | one more row, with that name on it |

**Something untouched is the control, and the run is not evidence without
one.** On the Curse specimen it is a readied flask, drawn `YES`, which
nothing here goes near; on any save, run the unedited disk through `run`
first and compare the two lists. Three edits showing while a fourth row
moves is a run that measured something other than what it meant to.

Two subcommands:

    tools/inventorycheck.py stage \\
        --base ~/wish-specimens/coab-c64/WISH-SPEC-curse-party-with-items.D64 \\
        --out work/issue139-a13/edited.D64 --who "MALE ELF MAGE" \\
        --delete 4 --quantity 9 --add "TWO-HANDED SWORD"

    tools/inventorycheck.py run --save work/issue139-a13/edited.D64 --pool N \\
        --out work/issue139-a13/run1 --who "MALE ELF MAGE"

`run` reads the title off the save disk and drives it accordingly: Curse
through `tools/curserun.py` and `tools/curseload.py`, Silver Blades through
`tools/ssbwarp.py`. **Both have to reach the world**, because the item list
hangs off the world's `VIEW` and off nothing else -- the party-formation
menu's `VIEW CHARACTER` draws a sheet whose bar is `TRADE DROP EXIT` with no
`ITEMS` on it (`work/issue33/run1/03-sheet.txt`).

`--base` is copied before a byte of it is touched and the sides are staged
into the pool slot by each title's own `stage`, which copies them; nothing
writes where the player's disks lie.
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
from goldbox.items import ITEM_SIZE, ITEMS_PER_CHARACTER  # noqa: E402

#: The item screen's own columns, from a Pool of Radiance capture kept in
#: `work/issue252/probe4/screen.txt` and unchanged in Curse: a `YES`/`NO`
#: readied column at 1, then an optional count, then the name.
ITEM_ROWS = range(4, 23)
ITEM_COLUMN = 1
#: Column 39 is the window's own right-hand border.
ITEM_BORDER = 39


# --- reading the save from outside the editor --------------------------------

def item_block(path: str | pathlib.Path, slot: int) -> list[bytes]:
    """One character's sixteen 16-byte item records, straight off the disk.

    Read out of the save payload rather than through `editor.inventory`,
    because what this has to answer is whether that module's writer put the
    bytes where the game reads them.
    """
    disk = D64.open(str(path))
    game = games.detect(disk)
    if game is None:
        raise SystemExit(f"{path}: no Gold Box save on this disk")
    container = c64_save.CONTAINERS[game.key]
    _, payload = split_load_address(disk.read_file(game.save_file))
    base = container.items(slot)
    return [bytes(payload[base + n * ITEM_SIZE: base + (n + 1) * ITEM_SIZE])
            for n in range(ITEMS_PER_CHARACTER)]


def describe_block(raws: list[bytes], names: dict[int, str] | None) -> list[dict]:
    """The occupied records, as the report prints them."""
    from goldbox.items import READIED, Item
    out = []
    for n, raw in enumerate(raws):
        if not any(raw):
            continue
        out.append({"n": n, "name": Item(raw, names).name if names else None,
                    "quantity": raw[10], "readied": bool(raw[6] & READIED),
                    "raw": raw.hex()})
    return out


# --- staging: the edits, through the editor's own handlers -------------------

def stage(base: str, out: str, who: str, delete: int, quantity: int | None,
          add: str | None, game_disk: str = "",
          delete_rows: list[int] | None = None,
          quantity_row: int | None = None) -> dict:
    """Copy `base` to `out` and edit one character's inventory in Wish.

    Qt runs offscreen: `QT_QPA_PLATFORM=offscreen` is set here rather than
    left to the caller, because nothing an agent runs may put a window on the
    machine's screen.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.pop("WAYLAND_DISPLAY", None)
    if game_disk:
        os.environ["POR_GAME_DISK"] = game_disk
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMainWindow

    dest = pathlib.Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(base, dest)
    dest.chmod(0o644)

    app = QApplication.instance() or QApplication([])
    from editor import inventory as inv_mod
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
    # Selecting the row is what hands this character's inventory to
    # `editor.items`, which is the model every handler below works through.
    editor.roster.selectRow(row)
    slot = party.member(row).index

    before = item_block(dest, slot)
    steps: list[str] = []

    # remove: the editor's own delete.  `--delete-rows` names them and is
    # taken in descending order, because `Inventory.delete` compacts the list
    # and an ascending pass would shift every row after the first out from
    # under the numbers the caller gave.  `--delete N` takes them off the top
    # instead, where compaction makes row 0 a different item each pass.
    for n in sorted(delete_rows or (), reverse=True):
        steps.append(editor.delete_item(n))
    for _ in range(delete):
        steps.append(editor.delete_item(0))

    # edit: the quantity column, through the model a player types into.
    if quantity is not None:
        model = editor.items
        if quantity_row is None:
            for n in range(ITEMS_PER_CHARACTER):
                if model.inventory.is_empty(n):
                    continue
                # The unreadied one, so a readied record stays a control.
                if not model.inventory.item(n).readied:
                    quantity_row = n
                    break
        if quantity_row is None:
            raise SystemExit("no unreadied item to put a quantity on")
        ok = model.setData(model.index(quantity_row, inv_mod.QTY), quantity,
                           Qt.ItemDataRole.EditRole)
        steps.append(f"quantity of item {quantity_row} set to {quantity}: {ok}")

    # add: a record copied off the player's own game disks.
    if add:
        steps.append(editor.add_item(add))

    note = editor.save(interactive=False)
    after = item_block(dest, slot)
    names = editor.item_names or None
    report = {
        "base": str(base), "out": str(dest), "who": who, "slot": slot,
        "row": row, "game_disk": editor.game_disk_found,
        "templates": len(editor.templates), "steps": steps,
        "save_said": note,
        "before": describe_block(before, names),
        "after": describe_block(after, names),
        "quantity_row": quantity_row,
    }
    app.processEvents()
    return report


# --- the run -----------------------------------------------------------------

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


def item_list(rows: list[str]) -> list[str]:
    """The item screen's own rows, frame and blanks dropped.

    Column 39 is the window's right-hand border and is a graphic character
    that changes down the frame, so a row read to the end of the line is
    never blank and every empty slot on the list would come back as an item.
    """
    out = []
    for r in rows[ITEM_ROWS.start:ITEM_ROWS.stop]:
        text = r[ITEM_COLUMN:ITEM_BORDER].rstrip()
        if not text.strip():
            continue
        if text.strip() == "EXIT":
            break
        out.append(text.strip())
    return out


#: Row 24 while the item list is up.  `LIBRARY $4600`'s sheet bar is
#: `ITEMS SPELLS TRADE DROP CURE HEAL EXIT` and the list's own is
#: `READY TRADE DROP EXIT`, so `READY` with no `ITEMS` beside it is the pair
#: that says the list has replaced the sheet rather than that some word
#: happens to be on the row.
ITEM_BAR = "READY"
SHEET_BAR = "ITEMS"


def press_bar(sess, label: str, timeout: float = 25.0) -> bool:
    """Choose a word on a command bar, whichever Return this screen reads.

    `CurseSession.press_bar` is the measurement -- Curse and Silver Blades
    read Return from the KERNAL buffer on some screens and from XTEST on
    others, and which is which is a per-screen fact -- so it is used when the
    session has one and reproduced here when it does not.  `SSBSession` does
    not, and giving it Curse's method is `tools/session.py`'s change to make
    rather than this file's.
    """
    own = getattr(sess, "press_bar", None)
    if own is not None:
        return own(label, timeout=timeout)
    if not sess.select_bar(label, timeout=timeout):
        return False
    s = sess.screen()
    was = "" if s is None else s.row(24)
    deadline = time.time() + 4.0
    while time.time() < deadline:
        s = sess.screen()
        if s is not None and s.row(24) != was:
            return True
        time.sleep(0.5)
    sess.press_kernal(0x0D)
    return True


def as_drawn(name: str) -> str:
    """What the C64 draws for a name that has lower case in it.

    **This character set has no lower case**, and a lower-case letter is
    drawn as the glyph at its code minus `$40`: `Guy de Valois` comes out of
    the party panel as `G59 $% V!,/)3`, measured on
    `WISH-SPEC-ssb-d-engine-resave` in `work/issue139-a13/ssb-run1`.  A save
    converted from DOS keeps DOS's mixed-case name, so a run that looks for
    the name it read out of the record finds nobody at all.
    """
    return "".join(chr(ord(c) - 0x40) if "a" <= c <= "z" else c
                   for c in name)


def sheet_up(s) -> bool:
    """Is a character sheet or its item list in front of the world?

    `Session.sheet_is_up` looks for Pool of Radiance's `VIEW:`, which neither
    later title draws.  Curse's sheet bar is
    `ITEMS SPELLS TRADE DROP CURE HEAL EXIT` and the game prints only the
    commands the character can use, so `EXIT` is the one word every version
    of it ends with -- and the world's own bar,
    `MOVE VIEW CAST AREA ENCAMP SEARCH LOOK`, has no `EXIT` on it.  The pair
    says the sheet has replaced the world rather than that some word happens
    to be on the row (`CurseSession.sheet_is_up`).
    """
    row = s.row(24)
    return "EXIT" in row and "ENCAMP" not in row


def open_items(sess, r: Run, who: str) -> list[str] | None:
    """`VIEW` the character called `who`, then `ITEMS`, and read the list.

    The party panel is in **marching order**, not slot order, so which row
    to highlight is read off the screen rather than taken from the save.

    **The list can already be up by the time `VIEW` returns.**  The sheet's
    highlight starts on `ITEMS`, and the Return `press_bar` sends at the
    world bar can still be in the KERNAL buffer when the sheet draws -- the
    first run of this file (`work/issue139-a13/run1`) came back holding the
    item list under a capture labelled `sheet`.  So which screen is up is
    read off row 24 rather than assumed, and `ITEMS` is pressed only when the
    sheet is the thing in front of it.
    """
    s = sess.screen()
    if s is None:
        r.log("panel", ok=False, why="the screen is a bitmap")
        return None
    from tools import session as por
    wanted = (who.upper(), as_drawn(who).upper())
    at = None
    for i, row in enumerate(sess.party_rows(s)):
        drawn = s.row(row)[por.PARTY_COLUMN:].upper()
        if any(w in drawn for w in wanted):
            at = i
            break
    if at is None:
        r.log("panel", ok=False, why=f"{who} is not on the party panel",
              rows=[s.row(row).rstrip() for row in sess.party_rows(s)])
        return None
    r.log("panel", ok=True, index=at)
    if not sess.select_party(at):
        r.log("select", ok=False)
        return None
    if not press_bar(sess, "VIEW", timeout=25):
        r.log("view", ok=False)
        r.capture(sess, "no-view")
        return None
    deadline = time.time() + 30
    bar = ""
    while time.time() < deadline:
        s = sess.screen()
        if s is not None and sheet_up(s) and s.row(1).strip():
            bar = s.row(24)
            break
        time.sleep(0.4)
    else:
        r.log("sheet", ok=False, why="no character sheet came up after VIEW")
        r.capture(sess, "no-sheet")
        return None
    sess.settle(1.5)
    r.capture(sess, "after-view")
    s = sess.screen()
    bar = s.row(24) if s is not None else bar
    r.log("bar", row24=bar.strip())
    if SHEET_BAR in bar:
        if not press_bar(sess, "ITEMS", timeout=20):
            r.log("items", ok=False, why="ITEMS could not be chosen")
            r.capture(sess, "no-items")
            return None
        sess.settle(2.0)
        s = sess.screen()
        bar = s.row(24) if s is not None else ""
    if ITEM_BAR not in bar or SHEET_BAR in bar:
        r.log("items", ok=False, why=f"the item list is not up: {bar.strip()!r}")
        r.capture(sess, "no-items")
        return None
    rows = r.capture(sess, "items")
    listed = item_list(rows)
    r.log("items", ok=True, listed=listed)
    return listed


def curse_world(slot, r: Run, save: str, where: str, wait: float):
    """Boot Curse, load the party and get it to the world command bar."""
    from tools import curseload, curserun, cursewarp

    first = curserun.stage(slot, where, save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    # The specimen tree is read-only and `stage` copied it; the copy in the
    # slot is ours.
    os.chmod(save_disk, 0o644)
    sess = curserun.CurseSession(first, slot=slot)
    sess.save_disk = save_disk
    r.log("staged", save=save, side0=save_disk)
    if not sess.boot():
        r.log("boot", ok=False)
        r.capture(sess, "boot-failed")
        return sess, False
    r.log("boot", ok=True)
    r.capture(sess, "party-menu")
    outcome = curseload.load_saved_game(sess, wait=wait)
    r.log("load", outcome=outcome)
    if outcome != "loaded":
        r.capture(sess, "load-failed")
        return sess, False
    sess.patch_disk_prompt()
    if not cursewarp.enter_world(sess, timeout=wait):
        r.log("world", ok=False)
        r.capture(sess, "stuck")
        return sess, False
    r.log("world", ok=True, bar=cursewarp.clear_messages(sess))
    return sess, True


def ssb_world(slot, r: Run, save: str, where: str, game, wait: float):
    """Boot Silver Blades, load the party and get it into the world.

    `ssbwarp.enter_world` wants an `Addresses`, which is read out of this
    title's own `DUNGEON` rather than written down -- and it is not optional
    here even though nothing warps: the function uses it to tell an idle
    machine from one half-way through a disk load, which is what gets a run
    past the prologue's four one-option screens.
    """
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
    r.capture(sess, "party-menu")
    if not ssbwarp.load_party(sess, timeout=wait):
        r.log("load", outcome="failed")
        r.capture(sess, "load-failed")
        return sess, False
    r.log("load", outcome="loaded")
    addr = ssbwarp.Addresses(game, where)
    if not ssbwarp.enter_world(sess, addr, timeout=wait):
        r.log("world", ok=False)
        r.capture(sess, "stuck")
        return sess, False
    r.log("world", ok=True, bar=ssbwarp.clear_messages(sess))
    return sess, True


#: Which driver boots which title, and the `tools/gamedisks.py` key its sides
#: are found under.
DRIVERS = {
    "curse-of-the-azure-bonds": ("curse-of-the-azure-bonds", curse_world),
    "secret-of-the-silver-blades": ("secret-of-the-silver-blades", ssb_world),
}


def run(save: str, out: str, who: str, pool: int | None,
        disks: str = "", wait: float = 240.0) -> int:
    """Boot whichever title the save is, and read `who`'s item list."""
    from tools import gamedisks
    from tools import session as por

    game = games.detect(D64.open(save))
    if game is None or game.key not in DRIVERS:
        raise SystemExit(f"{save}: no later-title save on this disk "
                         f"({game.title if game else 'nothing detected'})")
    key, driver = DRIVERS[game.key]
    where = disks or str(gamedisks.find(key) or "")
    if not where:
        raise SystemExit(f"no {game.title} sides: pass --disks")
    r = Run(pathlib.Path(out))
    slot = por.claim_slot(pool, note=os.environ.get("POR_AGENT", "a13"))
    r.log("slot", n=slot.n, monitor=slot.port, cmd=slot.cmd_port,
          display=slot.display, dir=str(slot.dir), title=game.title)
    sess = None
    try:
        if driver is ssb_world:
            sess, ok = driver(slot, r, save, where, game, wait)
        else:
            sess, ok = driver(slot, r, save, where, wait)
        if not ok:
            return 1
        r.capture(sess, "world")
        listed = open_items(r=r, sess=sess, who=who)
        r.log("done", ok=listed is not None, listed=listed)
        return 0 if listed is not None else 1
    finally:
        if sess is not None:
            sess.terminate()
        slot.teardown()
        r.log("torn down")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("stage", help="edit an inventory through the editor")
    s.add_argument("--base", required=True, help="the save disk to copy")
    s.add_argument("--out", required=True, help="where the edited copy goes")
    s.add_argument("--who", required=True, help="the character to edit")
    s.add_argument("--delete", type=int, default=0,
                   help="delete this many items off the top of the list")
    s.add_argument("--delete-rows", default="",
                   help="delete these slot numbers, comma separated")
    s.add_argument("--quantity-row", type=int, default=None,
                   help="which slot --quantity applies to; the first "
                        "unreadied one by default")
    s.add_argument("--quantity", type=int, default=None,
                   help="set the first unreadied item's quantity to this")
    s.add_argument("--add", default="", help="add this item by name")
    s.add_argument("--game-disk", default="",
                   help="a Curse side, for the item names and templates")
    s.add_argument("--json", default="", help="write the report here as well")

    d = sub.add_parser("run", help="boot the edited save and read the screens")
    d.add_argument("--save", required=True, help="the edited save disk")
    d.add_argument("--out", required=True, help="a directory for this run")
    d.add_argument("--who", required=True, help="the edited character's name")
    d.add_argument("--pool", type=int, default=None, help="demand this slot")
    d.add_argument("--disks", default="", help="the six Curse sides")
    d.add_argument("--wait", type=float, default=240.0,
                   help="seconds to wait for the load and for the world")

    args = ap.parse_args(argv)
    if args.cmd == "stage":
        rows = [int(n) for n in args.delete_rows.split(",") if n.strip()]
        report = stage(args.base, args.out, args.who, args.delete,
                       args.quantity, args.add or None, args.game_disk,
                       rows, args.quantity_row)
        text = json.dumps(report, indent=2)
        print(text)
        if args.json:
            pathlib.Path(args.json).write_text(text + "\n")
        return 0
    return run(args.save, args.out, args.who, args.pool, args.disks, args.wait)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Write a trait through the **editor's own buttons**, then boot the disk.

`#417 (Prove the game applies a trait Wish wrote, so WISH_EXPERIMENTAL_TRAITS
can come off)` is measurement M3, and the whole of what it adds to `#252 (Does
a C64 trait slot apply an item-granted effect id, or only the ones its own
READY routine wrote?)` is the **write path**. `#252` staged its bytes with
`tools/traitdrive.py`, which pokes a `.d64` directly; a byte poked into a save
proves the engine reads a slot and says nothing about the editor. So nothing
here writes a byte: it builds the real `WishWindow`, clicks the real
`button_trait_add`, picks the trait in the real `TraitPicker` and triggers the
real `File > Save` action, and the only thing replaced is `TraitPicker.exec`
-- the modal wait for a person, and nothing else.

    tools/traitsave.py write --who ROLAND --trait "Resist Fire"
    tools/traitsave.py boot --disk work/issue417/edited.d64 --who ROLAND

`write` needs no emulator and opens no window: `QT_QPA_PLATFORM=offscreen` is
assigned at the top of the module, before PyQt is imported anywhere, and the
XDG config variables are pointed at the run directory so nothing touches the
player's own settings. It reports the **byte diff of the whole disk image**,
not just the ten slots, because what a save writes back beyond the field under
test is the other half of "is this write path safe".

`boot` claims a pool slot, loads the save, photographs the character's `VIEW`
sheet, reads the ten slots out of the live record at `$4D00 + slot * $100`,
and with `--save-game` has the game write its own save and reads the block
back off the disk the engine wrote. Run it a second time on that disk and the
block that comes back is the answer to "does it survive a reload".

The consequence -- the engine matching the byte and dispatching its handler --
is `tools/traitask.py --save <the disk this wrote> --cast ...`, which needs no
change: `--save` takes an absolute path and stages nothing without `--stage`.

Nothing on the player's disks is written: the save is copied into the run
directory first and every path below is inside it.
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

# Assigned, never `setdefault`: this desktop exports `QT_QPA_PLATFORM=wayland;xcb`
# already, so a default is never reached and Qt goes looking for a display it
# can find. The XDG pair is what `tests/conftest.py` sets for the same reason:
# a run must not write the player's own settings file.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["GDK_BACKEND"] = "x11"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("XDG_SESSION_TYPE", None)

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools import savecheck as SC  # noqa: E402

#: `SAVEDGAME0` loads at `$4900`; the twelve character slots start at `$4D00`.
#: `docs/30-savegame-layout.md`, and `tools/traitdrive.py` has the same three.
SAVE0_LOAD = 0x4900
SLOT_BASE = 0x4D00
SLOT_STRIDE = 0x100

#: The ten trait slots inside a record. `docs/171-c64-trait-slots.md`.
TRAIT_SLOT = 0x0AD
TRAIT_COUNT = 10


def record_offset(slot: int) -> int:
    """Where slot *n*'s record starts inside the `SAVEDGAME0` body."""
    return SLOT_BASE - SAVE0_LOAD + slot * SLOT_STRIDE


def disks_dir(given: str | None = None) -> pathlib.Path:
    """`--disks`, then `$POR_DISKS`, then the search every other tool does."""
    if given:
        return pathlib.Path(given)
    return pathlib.Path(gamedisks.find("pool-of-radiance")
                        or os.environ.get("POR_DISKS")
                        or find_disks() or "")


def trait_blocks(path: pathlib.Path) -> dict[int, list[int]]:
    """The ten trait slots of every occupied save slot, off a `.d64`."""
    image = D64.open(str(path))
    _, body = split_load_address(image.read_file("SAVEDGAME0"))
    out: dict[int, list[int]] = {}
    for slot in range(8):
        at = record_offset(slot)
        record = body[at:at + SLOT_STRIDE]
        if not any(record):
            continue
        out[slot] = list(record[TRAIT_SLOT:TRAIT_SLOT + TRAIT_COUNT])
    return out


def save_body(path: pathlib.Path) -> bytes:
    """`SAVEDGAME0`'s body, without its two-byte load address."""
    return split_load_address(D64.open(str(path)).read_file("SAVEDGAME0"))[1]


def body_diff(before: bytes, after: bytes) -> list[dict]:
    """Every differing byte, said in terms of the record it lands in."""
    out: list[dict] = []
    for i in range(max(len(before), len(after))):
        was = before[i] if i < len(before) else None
        now = after[i] if i < len(after) else None
        if was == now:
            continue
        where: dict = {"offset": i, "was": was, "now": now}
        for slot in range(8):
            base = record_offset(slot)
            if base <= i < base + SLOT_STRIDE:
                where["slot"] = slot
                where["field_offset"] = i - base
                where["in_trait_block"] = (
                    TRAIT_SLOT <= i - base < TRAIT_SLOT + TRAIT_COUNT)
                break
        out.append(where)
    return out


class Log(SC.Log):
    """`SC.Log` -- `tools/savecheck.py`'s -- opened `append`.

    A run killed on its budget never reaches its own summary, so anything
    measured is written at the moment it is measured.  `write` and `boot` are
    two separate invocations that deliberately share one growing
    `traitsave.jsonl` at the same default `--out`, so `append=True` -- rather
    than `SC.Log`'s ordinary keep-the-old-one-and-start-fresh -- is what keeps
    that.  What was still missing was a `say` a dead console cannot take down
    with it (`#442`).
    """

    def __init__(self, out: pathlib.Path, quiet: bool = False):
        self.quiet = quiet
        super().__init__(out / "traitsave.jsonl", append=True)

    def say(self, *a) -> None:
        if not self.quiet:
            super().say(*a)


# ===========================================================================
# The editor's own path
# ===========================================================================

def _pick_in_picker(dialog, trait: str) -> int:
    """Type the name, select the row that matches, press OK -- as a person.

    Returns the dialog's own result code. **Only `TraitPicker.exec` is
    replaced by the caller**, and this is what stands in for it: the modal
    wait is the one thing a driven run cannot do, and everything the picker
    itself does -- the filter, the two sections, `chosen` reading the
    selection, OK enabled only on a row with a code behind it -- is the
    shipped code running.
    """
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QTreeWidgetItemIterator

    dialog.filter_line.setText(trait)
    QApplication.processEvents()
    wanted = trait.strip().lower()
    it = QTreeWidgetItemIterator(dialog.list)
    while it.value():
        item = it.value()
        if not item.isHidden() and item.text(0).strip().lower() == wanted:
            dialog.list.setCurrentItem(item)
            break
        it += 1
    QApplication.processEvents()
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    if ok is not None and ok.isEnabled():
        ok.click()
    QApplication.processEvents()
    return dialog.result()


def write(args) -> int:
    """Add a trait through the buttons and save through the File menu."""
    from tools import session as S

    SC.catch_signals()
    out = pathlib.Path(args.out)
    log = Log(out, args.quiet)
    disks = disks_dir(args.disks)
    src = (pathlib.Path(args.save) if os.path.isabs(args.save)
           else disks / args.save)
    if not src.is_file():
        log.say(f"no such save: {src}")
        return 1

    original = out / "original.d64"
    edited = out / "edited.d64"
    out.mkdir(parents=True, exist_ok=True)
    # `--out` defaults to a fixed path and is reused across invocations, so
    # a bare `shutil.copy` from a read-only `$WISH_SPECIMENS` file leaves
    # `original.d64`/`edited.d64` read-only too, and a second run into the
    # same `--out` dies opening them for writing (#487). `stage_writable`
    # unlinks the destination first and restores the write bit.
    S.stage_writable(src, original)     # the control, and the diff's left side
    S.stage_writable(src, edited)
    log.emit("copied", source=str(src), original=str(original),
             edited=str(edited))

    # The settings file this run may touch is inside the run directory.
    config = out / "config"
    config.mkdir(parents=True, exist_ok=True)
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        os.environ[var] = str(config)

    from PyQt6.QtWidgets import QApplication

    from editor import traitpicker
    from wish.window import WishWindow

    before = save_body(edited)
    app = QApplication.instance() or QApplication([])
    window = WishWindow(str(edited), disks=str(disks))
    binding = window.editor
    if binding.party is None:
        log.say("the editor did not open the save")
        return 1

    row = None
    model = binding.roster.model()
    for r in range(model.rowCount()):
        if str(model.index(r, 0).data()).strip().upper() == args.who.upper():
            row = r
            break
    if row is None:
        log.say(f"no character called {args.who} in {src.name}")
        return 1
    binding.roster.selectRow(row)
    app.processEvents()

    view = binding._widgets["item_effects"]
    was = list(view.codes())
    log.emit("before", who=args.who, roster_row=row, codes=was)
    log.say(f"{args.who} is roster row {row}; slots {was}")

    add = window.findChild(type(binding._child("button_trait_add")),
                           "button_trait_add")
    if add is None or not add.isEnabled():
        log.say("the Add button is not there, or is disabled")
        return 1
    log.emit("button", text=add.text(), enabled=add.isEnabled())

    chosen: dict = {}

    def fake_exec(self):
        code = _pick_in_picker(self, args.trait)
        chosen["code"] = self.chosen
        chosen["result"] = int(code)
        return code

    real_exec = traitpicker.TraitPicker.exec
    try:
        traitpicker.TraitPicker.exec = fake_exec
        add.click()                      # the real button, the real slot
        app.processEvents()
    finally:
        traitpicker.TraitPicker.exec = real_exec

    now = list(view.codes())
    log.emit("added", picked=chosen.get("code"), result=chosen.get("result"),
             codes=now, dirty=sorted(binding.dirty))
    log.say(f"picked {chosen.get('code')} ({args.trait}); slots {now}")
    if now == was:
        log.say("the block did not change -- nothing was added")
        return 1

    action = None
    for act in window.menuBar().actions():
        for inner in (act.menu().actions() if act.menu() else []):
            if inner.text().replace("&", "") == "Save":
                action = inner
    if action is None:
        log.say("no File > Save action on the menu bar")
        return 1
    action.trigger()                     # File > Save, as a person picks it
    app.processEvents()

    after = save_body(edited)
    diff = body_diff(before, after)
    log.emit("saved", differing_bytes=len(diff), diff=diff,
             blocks=trait_blocks(edited))
    log.say(f"File > Save wrote {len(diff)} differing bytes in SAVEDGAME0")
    for d in diff:
        log.say("  " + json.dumps(d))
    log.say(f"trait blocks on the disk now: {trait_blocks(edited)}")
    log.close()
    return 0


# ===========================================================================
# The running game
# ===========================================================================

def live_blocks(sess) -> dict[int, list[int]]:
    """The ten slots of every save slot, read out of the running machine."""
    with sess.mon(8) as m:
        live = m.read(SLOT_BASE, SLOT_STRIDE * 8)
        m.resume()
    return {i: list(live[i * SLOT_STRIDE + TRAIT_SLOT:
                         i * SLOT_STRIDE + TRAIT_SLOT + TRAIT_COUNT])
            for i in range(8)}


def rest_hours(sess, log: Log, hours: int, before: dict) -> dict:
    """`ENCAMP > REST` for *hours*, then read the ten slots again.

    A trait has no duration byte beside it, so nothing in the block can count
    down -- but "never expires" is the half `#252 (Does a C64 trait slot apply
    an item-granted effect id, or only the ones its own READY routine wrote?)`
    did not test, and resting is what expires a spell. The duration goes into
    `CAMP`'s own rest-time field rather than being driven with `INCREASE`,
    exactly as `tools/c64restinterrupt.py` does it, and no key is sent while
    the loop runs: `$1E44` reads the keyboard on every tick and a key there
    ends the rest early.
    """
    from tools.c64restinterrupt import CLOCK, REST_MINS, leave_camp, open_camp

    if not open_camp(sess, log):
        return {"error": "ENCAMP did not open the camp bar"}
    if not sess.select_bar("REST"):
        return {"error": "REST was not on the camp bar"}
    if sess.wait_text("INCREASE", timeout=30)[0] is None:
        return {"error": "the rest-time bar never appeared"}
    with sess.mon(5) as m:
        clock_before = m.read(CLOCK, 6)
        m.write(REST_MINS, bytes((0, hours, 0)))
        staged = tuple(m.read(REST_MINS, 3))
    if staged != (0, hours, 0):
        return {"error": f"the rest time read back {staged}"}
    if not sess.select_bar("REST"):
        return {"error": "REST was not on the rest-time bar"}
    deadline, still, last = time.time() + 420, 0, None
    while time.time() < deadline and still < 10:
        time.sleep(1.0)
        with sess.mon(5) as m:
            now = bytes(m.read(CLOCK, 6))
        still = still + 1 if now == last else 0
        last = now
    with sess.mon(5) as m:
        clock_after = bytes(m.read(CLOCK, 6))
    after = live_blocks(sess)
    log.say(f"rested {hours}h: clock {clock_before.hex(' ')} -> "
            f"{clock_after.hex(' ')}; blocks "
            + "; ".join(f"{i}:{v}" for i, v in after.items() if any(v)))
    leave_camp(sess)
    return {"clock_before": clock_before.hex(" "),
            "clock_after": clock_after.hex(" "),
            "blocks_before": before, "blocks_after": after,
            "unchanged": before == after}


def boot(args) -> int:
    """Load the disk in the emulator and read the slots back."""
    from tools import session as S

    SC.catch_signals()
    out = pathlib.Path(args.out)
    log = Log(out, args.quiet)
    disks = disks_dir(args.disks)
    disk = pathlib.Path(args.disk)
    if not disk.is_file():
        log.say(f"no such disk: {disk}")
        return 1
    log.emit("blocks_on_disk", disk=str(disk), blocks=trait_blocks(disk))
    log.say(f"trait blocks on {disk.name}: {trait_blocks(disk)}")

    staging_dir = out / "disks"
    staging_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 9):
        s, link = disks / f"POOL{i}.D64", staging_dir / f"POOL{i}.D64"
        if s.exists() and not link.exists():
            link.symlink_to(s.resolve())
    save = "STAGED.D64"
    S.stage_writable(disk, staging_dir / save)

    slot = S.claim_slot(args.slot, "traitsave")
    log.say(f"pool slot {slot.n} display {slot.display}  out {out}")
    sess, rc = None, 0
    try:
        sess = S.Session(S.stage_disks(slot, staging_dir, save), slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        log.say(f"in the world at {sess.position()}")

        blocks = live_blocks(sess)
        log.emit("blocks_live", blocks=blocks)
        log.say("live blocks after the load: " + "; ".join(
            f"{i}:{v}" for i, v in blocks.items() if any(v)))

        if args.party is not None:
            rows = sess.character_sheet(args.party,
                                        shot=str(out / "sheet.png"))
            if rows:
                (out / "sheet.txt").write_text("\n".join(rows) + "\n")
                log.emit("sheet", party=args.party, rows=rows)
                log.say(f"sheet rows written to {out / 'sheet.txt'}")
            else:
                log.emit("sheet", party=args.party, rows=None)
                log.say("no sheet came up")

        if args.rest:
            log.emit("rest", hours=args.rest,
                     **rest_hours(sess, log, args.rest, blocks))

        if args.save_game:
            if sess.save_game():
                written = pathlib.Path(sess.save_disk)
                shutil.copy(written, out / "saved.d64")
                log.emit("saved", blocks=trait_blocks(out / "saved.d64"))
                log.say("the game saved; blocks on its disk "
                        + str(trait_blocks(out / "saved.d64")))
            else:
                log.emit("saved", error="ENCAMP > SAVE did not complete")
                log.say("ENCAMP > SAVE did not complete")
    except Exception as exc:
        log.emit("failed", error=repr(exc))
        log.say(f"failed: {exc!r}")
        rc = 1
    finally:
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
        log.close()
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default=str(ROOT / "work" / "issue417"),
                   help="run directory")
    p.add_argument("--disks", default=None,
                   help="where the player's disks are; read, never written")
    p.add_argument("--quiet", action="store_true")
    sub = p.add_subparsers(dest="mode", required=True)

    w = sub.add_parser("write", help="add a trait through the editor's buttons")
    w.add_argument("--save", default="PORSAVE13.D64")
    w.add_argument("--who", default="ROLAND", help="the character's name")
    w.add_argument("--trait", default="Resist Fire",
                   help="the trait's name, as the picker prints it")

    b = sub.add_parser("boot", help="load a disk and read the slots back")
    b.add_argument("--disk", required=True, help="the .d64 to load")
    b.add_argument("--party", type=int, default=None,
                   help="photograph this party member's VIEW sheet")
    b.add_argument("--rest", type=int, default=None, metavar="HOURS",
                   help="ENCAMP > REST this long, then read the slots again")
    b.add_argument("--save-game", action="store_true",
                   help="ENCAMP > SAVE at the end and read the disk back")
    b.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")

    args = p.parse_args(argv)
    return write(args) if args.mode == "write" else boot(args)


if __name__ == "__main__":
    raise SystemExit(main())

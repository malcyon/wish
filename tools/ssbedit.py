#!/usr/bin/env python3
"""Edit a Silver Blades save in Wish, then read the edits off the game's screens.

`#33 (One Silver Blades session, for the whole editor path)` step 5: *"Edit
three fields of different kinds and read each off the game's own screens."*
Steps 2, 3 and 4 of that ticket are file-path checks and live in
`tests/test_ssbeditorpath.py`; this is the half that needs the running game.

Three fields, chosen to be three different kinds of thing and to land in three
different places in the save:

| field | kind | where the game draws it |
|---|---|---|
| `name` | text, and the only field the save stores **twice** | the party-formation panel and the sheet's top row |
| `gold` | a three-byte purse in the money block | the sheet's money line |
| `strength` | an ability score the engine derives combat numbers from | the sheet's `STR` |

**The name is the interesting one.** Curse and Silver Blades keep the party's
names again in a sixteen-bytes-per-entry table at payload `+$C00`
(`goldbox/c64_save.py`, `name_table`), and `editor/window.py:_write_back`
writes only the 256 bytes of each save slot -- so a rename made in Wish leaves
that table holding the old name.  Whether a player *sees* the old name is what
the run answers, and it is why `--name` is one of the three.

Two subcommands:

    tools/ssbedit.py stage --base ~/wish-specimens/por-c64/WISH-SPEC-ssb-d-engine-resave.D64 \\
        --out work/issue33/edited.D64 --who MORGAINE \\
        --name BRIGHID --gold 4321 --strength 12

        Copy the disk and make the edits **through `EditorBinding`**, which is
        the program's own save path -- `_flush`, `_write_back`,
        `editor.files.save_disk` and the backup it takes.  Prints what each
        field held before and after, and what the `+$C00` table entry for that
        character says once the save is written.

    tools/ssbedit.py run --save work/issue33/edited.D64 --pool N \\
        --out work/issue33/run1 --who BRIGHID --was MORGAINE

        Claim a pooled VICE slot, stage the six sides, boot through the
        cracker intro, load the party, photograph the party-formation panel,
        open `VIEW CHARACTER` on the edited character and photograph the
        sheet.  Writes one JSON line per event as it goes, so a run that dies
        halfway still says how far it got.

Nothing writes to the player's disks: `tools/ssbwarp.stage` copies the six
sides into the pool slot and opens them read only, and `--base` is copied
before a byte of it is touched.
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
from goldbox.savegame import load_save  # noqa: E402

#: The three fields, in the order the report prints them.  `strength` is last
#: because it is the one the engine may recompute something from.
FIELDS = ("name", "gold", "strength")


# --- reading the save from outside the editor --------------------------------

def name_table(path: str | pathlib.Path) -> list[bytes]:
    """The `+$C00` table of party names, or `[]` for a title without one.

    Read straight out of the save file's payload rather than through any
    writer, because the question this answers is whether a writer touched it.
    """
    disk = D64.open(str(path))
    game = games.detect(disk)
    if game is None:
        raise SystemExit(f"{path}: no Gold Box save on this disk")
    container = c64_save.CONTAINERS.get(game.key)
    if container is None or container.name_table is None:
        return []
    _, payload = split_load_address(disk.read_file(game.save_file))
    stride = container.name_stride
    return [bytes(payload[container.name(i):container.name(i) + stride])
            for i in range(container.party_slots)]


def table_name(entry: bytes) -> str:
    return entry.rstrip(b"\x00").decode("latin1")


def party_names(path: str | pathlib.Path) -> list[str]:
    """The name in each occupied record, in slot order."""
    _game, sg0, _sg1 = load_save(D64.open(str(path)))
    return [s.record.name for s in sg0.characters]


def table_index(path: str | pathlib.Path, slot: int) -> int | None:
    """Which `+$C00` entry belongs to a slot, through the container's own rule.

    Silver Blades indexes that table in marching order and Curse in slot
    order, so neither may be assumed -- `Container.name_index` is the one
    place that knows which.
    """
    disk = D64.open(str(path))
    game = games.detect(disk)
    container = c64_save.CONTAINERS.get(game.key) if game else None
    if container is None or container.name_table is None:
        return None
    return container.name_index(slot, len(party_names(path)))


# --- staging: the edits, through the editor's own path -----------------------

def stage(base: str, out: str, who: str, new_name: str | None,
          gold: int | None, strength: int | None) -> dict:
    """Copy `base` to `out` and edit one character in `EditorBinding`.

    Returns a report dict.  Qt runs offscreen: `QT_QPA_PLATFORM=offscreen` is
    set here rather than left to the caller, because nothing an agent runs may
    put a window on the machine's screen.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.pop("WAYLAND_DISPLAY", None)
    from PyQt6.QtWidgets import QApplication, QMainWindow

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
        raise SystemExit(f"{dest}: no character called {who}; the party is "
                         + ", ".join(m.record.name for m in party.members))
    # Selecting the row first is not decoration: `save()` flushes the widgets
    # of the *current* row into its record, so an edit made while another row
    # is selected would be written and then overwritten by stale widget text.
    editor.roster.selectRow(row)
    member = party.member(row)
    slot = member.index

    before = {"name": member.record.name,
              "gold": member.record.get("gold"),
              "strength": member.record.get("strength")}
    if new_name is not None:
        # The C64 has no lower case in this charset: a lower-case letter draws
        # as its code minus $40, so a name typed in mixed case comes back as
        # punctuation on the panel.
        member.record.set("name", new_name.upper())
    if gold is not None:
        member.record.set("gold", gold)
    if strength is not None:
        member.record.set("strength", strength)
    editor._populate()          # the widgets, so `_flush` has nothing stale
    note = editor.save(interactive=False)

    after = party_names(dest)
    entry = table_index(dest, slot)
    table = name_table(dest)
    report = {
        "base": str(base), "out": str(dest), "who": who, "slot": slot,
        "row": row, "save_said": note,
        "before": before,
        "after": {"name": member.record.name,
                  "gold": member.record.get("gold"),
                  "strength": member.record.get("strength")},
        "records_on_disk": after,
        "name_table_index": entry,
        "name_table": [table_name(e) for e in table],
        "name_table_entry": table_name(table[entry]) if table and entry is not None else None,
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
                           **fields})
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


def run(save: str, out: str, who: str, was: str, pool: int | None,
        disks: str = "") -> int:
    from tools import gamedisks, ssbwarp
    from tools import session as por

    where = disks or str(gamedisks.find("secret-of-the-silver-blades") or "")
    if not where:
        raise SystemExit("no Silver Blades disks: set $SSB_DISKS or pass "
                         "--disks")
    r = Run(pathlib.Path(out))
    slot = por.claim_slot(pool, note=os.environ.get("POR_AGENT", "ssb33"))
    r.log("slot", n=slot.n, monitor=slot.port, cmd=slot.cmd_port,
          display=slot.display, dir=str(slot.dir))
    sess = None
    try:
        first = ssbwarp.stage(slot, where, save)
        sess = ssbwarp.SSBSession(first, slot=slot)
        sess.save_disk = f"{slot.dir}/SIDE0.D64"
        r.log("staged", save=save, side0=sess.save_disk)
        if not sess.boot():
            r.log("boot", ok=False)
            r.capture(sess, "boot-failed")
            return 1
        r.log("boot", ok=True)
        if not ssbwarp.load_party(sess):
            r.log("load", ok=False)
            r.capture(sess, "load-failed")
            return 1
        sess.settle(3.0)
        r.log("load", ok=True)

        # 1. The party-formation panel. This is where the `+$C00` table would
        #    show, if the panel reads it.
        rows = r.capture(sess, "party-menu")
        panel = [line.strip("% ").rstrip() for line in rows[3:11]
                 if line.strip("% ").strip()]
        r.log("panel", rows=panel,
              shows_new_name=any(who.upper() in line for line in panel),
              shows_old_name=any(was.upper() in line for line in panel))

        # 2. The sheet, for gold and strength -- and for the name the record
        #    holds, which is the other half of the same question.
        if not sess.select_row("VIEW CHARACTER", timeout=25.0):
            r.log("view", ok=False, why="VIEW CHARACTER not selectable")
            r.capture(sess, "no-view")
            return 1
        sess.settle(4.0)
        picker = r.capture(sess, "view-which")
        wanted = who.upper() if any(who.upper() in line for line in picker) \
            else was.upper()
        r.log("picker", asked_for=wanted,
              new_name_listed=any(who.upper() in line for line in picker),
              old_name_listed=any(was.upper() in line for line in picker))
        if not sess.select_row(wanted, timeout=25.0):
            r.log("sheet", ok=False, why=f"{wanted} not selectable")
            r.capture(sess, "no-sheet")
            return 1
        sess.settle(5.0)
        r.capture(sess, "sheet")
        r.log("done", ok=True)
        return 0
    finally:
        if sess is not None:
            sess.terminate()
        slot.teardown()
        r.log("torn down")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("stage", help="edit a save through the editor")
    s.add_argument("--base", required=True, help="the save disk to copy")
    s.add_argument("--out", required=True, help="where the edited copy goes")
    s.add_argument("--who", required=True, help="the character to edit")
    s.add_argument("--name", default=None, help="a new name")
    s.add_argument("--gold", type=int, default=None, help="a new gold total")
    s.add_argument("--strength", type=int, default=None,
                   help="a new strength")
    s.add_argument("--json", default="", help="write the report here as well")

    d = sub.add_parser("run", help="boot the edited save and read the screens")
    d.add_argument("--save", required=True, help="the edited save disk")
    d.add_argument("--out", required=True, help="a directory for this run")
    d.add_argument("--who", required=True, help="the edited character's name")
    d.add_argument("--was", required=True, help="what that character was called")
    d.add_argument("--pool", type=int, default=None, help="demand this slot")
    d.add_argument("--disks", default="", help="the six Silver Blades sides")

    args = ap.parse_args(argv)
    if args.cmd == "stage":
        report = stage(args.base, args.out, args.who, args.name, args.gold,
                       args.strength)
        text = json.dumps(report, indent=2)
        print(text)
        if args.json:
            pathlib.Path(args.json).write_text(text + "\n")
        return 0
    return run(args.save, args.out, args.who, args.was, args.pool, args.disks)


if __name__ == "__main__":
    sys.exit(main())

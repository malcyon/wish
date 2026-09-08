#!/usr/bin/env python3
"""What `ADD CHARACTER TO PARTY` matches on, and whether it deletes the file.

A parked character on a Curse of the Azure Bonds or Secret of the Silver
Blades save disk is a whole 580-byte record in a file of its own, named for
the character. `docs/216-the-c64-name-table.md` established by reading the
overlay that the add list is built from the **directory**, and this drives the
game to see it: stage a disk whose file name and stored name disagree, take
`ADD CHARACTER TO PARTY`, and read what the list offers.

The two questions it exists to answer, from
`#439 (A rename in Wish leaves a parked character's own file on the C64 save
disk under the old name)`:

* **What does the list match on?** ANSWERED on 2026-09-08: the filename. A
  disk whose file is `\x02ARDXYZ` and whose record still says `ARDEN` offers
  `ARDXYZ`.
* **Does completing an add delete the source file?** OPEN. That is what
  decides whether the ticket's smaller fix -- rename the matching file on save
  -- is even well defined, because there is a file to rename only if a party
  member can legitimately share a name with a leftover parked file.

Run it with a save whose file and record disagree; `--save` takes one, and
`tools/c64nametable.py show` prints both sides so you can build one.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import curserun, gamedisks  # noqa: E402
from tools import savecheck as SC  # noqa: E402
from tools import session as por  # noqa: E402
from tools.c64nametable import character_files, from_bar, load_party  # noqa: E402


def dump(sess, out, tag, shots):
    s = sess.screen()
    text = "(bitmap)" if s is None else "\n".join(s.row(r).rstrip() for r in range(25))
    shots[0] += 1
    stem = f"{shots[0]:02d}-{tag}"
    (out / f"{stem}.txt").write_text(text + "\n")
    sess.kbd.screenshot(str(out / f"{stem}.png"))
    print(f"--- {tag} ---", flush=True)
    for ln in text.splitlines():
        if ln.strip():
            print(ln, flush=True)
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", required=True,
                    help="a save disk whose parked file name and stored name "
                         "disagree")
    ap.add_argument("--out", default="work/issue439/add-probe",
                    help="where the screens and the saved disk are written")
    ap.add_argument("--disks", default="",
                    help="the player's own game disks; $POR_DISKS otherwise")
    ap.add_argument("--pick", default="",
                    help="the name to pick off the add list; the file's own "
                         "name by default")
    ap.add_argument("--slot", type=int, default=None,
                    help="an emulator pool slot; one is claimed otherwise")
    args = ap.parse_args(argv)

    # A signal has to unwind through the `finally` below rather than kill the
    # run where it stands, or the slot's emulator outlives it (#442).
    SC.catch_signals()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shots = [0]
    where = args.disks or str(gamedisks.find("curse-of-the-azure-bonds"))
    if not where:
        raise SystemExit("no Curse disks found; pass --disks")
    save = args.save
    pick = args.pick
    slot = por.claim_slot(args.slot, note="c64addprobe/439")
    sess = None
    try:
        print("slot", slot.n, slot.port, slot.display, slot.dir, flush=True)
        first = curserun.stage(slot, where, save)
        sess = curserun.CurseSession(first, slot=slot)
        sess.save_disk = f"{slot.dir}/SIDE0.D64"
        disk = D64.open(sess.save_disk)
        print("staged, character files:", character_files(disk, 0x02), flush=True)
        if not sess.boot():
            dump(sess, out, "boot-failed", shots)
            return 1
        dump(sess, out, "main-menu", shots)
        if not load_party(sess):
            dump(sess, out, "load-failed", shots)
            return 1
        sess.settle(3.0)
        dump(sess, out, "loaded", shots)
        if hasattr(sess, "patch_disk_prompt"):
            print("disk_prompt_patched", sess.patch_disk_prompt(), flush=True)

        sess.select_row("ADD CHARACTER TO PARTY", timeout=25.0)
        sess.settle(6.0)
        text = dump(sess, out, "add-bar", shots)
        word = from_bar(text) or "CURSE"
        print("ADD FROM word:", word, flush=True)
        sess.select_bar(word, timeout=25.0)
        last, same = None, 0
        end = time.time() + 45
        while time.time() < end and same < 3:
            s = sess.screen()
            t = None if s is None else "\n".join(s.row(r) for r in range(25))
            same = same + 1 if t == last else 0
            last = t
            time.sleep(1.0)
        add_list_text = dump(sess, out, "add-list", shots)
        if not pick:
            files = character_files(D64.open(sess.save_disk), 0x02)
            pick = files[0] if files else ""
        print("on the list:", pick, pick in add_list_text, flush=True)

        ok = sess.select_row(pick, timeout=25.0) if pick else False
        print("picked:", pick, ok, flush=True)
        sess.settle(6.0)
        dump(sess, out, "after-pick", shots)
        for _ in range(20):
            s = sess.screen()
            if s is not None and s.contains("YES"):
                if not sess.select_row("YES", timeout=6.0):
                    sess.select_bar("YES", timeout=6.0)
                sess.press_kernal(0x0D)
            sess.handle_prompt(s)
            time.sleep(1.0)
        dump(sess, out, "after-confirm", shots)

        sess.select_row("EXIT", timeout=15.0)
        sess.settle(4.0)
        dump(sess, out, "after-exit", shots)
        sess.wait_text("BEGIN ADVENTURING", 60)

        sess.select_row("SAVE CURRENT GAME", timeout=15.0)
        sess.settle(4.0)
        s = sess.screen()
        if s is not None and s.contains("YES"):
            if not sess.select_row("YES", timeout=6.0):
                sess.select_bar("YES", timeout=6.0)
            sess.press_kernal(0x0D)
        for _ in range(30):
            if sess.handle_prompt():
                sess.press_kernal(0x20)
            time.sleep(1.0)
        dump(sess, out, "after-save", shots)
        sess.wait_text("BEGIN ADVENTURING", 90)

        kept = out / "save-after.D64"
        shutil.copy(sess.save_disk, kept)
        after = D64.open(str(kept))
        print("files after add+save:", [e.name for e in after.iter_directory()],
              flush=True)
        game, sg0, sg1 = load_save(after)
        for slot_ in sg0.slots:
            if slot_.occupied:
                print("slot", slot_.index, slot_.record.name, flush=True)
        return 0
    finally:
        if sess is not None:
            sess.terminate()
        slot.teardown()


if __name__ == "__main__":
    sys.exit(main())

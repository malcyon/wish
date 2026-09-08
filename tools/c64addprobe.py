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
* **Does completing an add delete the source file?** ANSWERED on 2026-09-08:
  no. `REMOVE CHARACTER FROM PARTY` writes `\x02NAME`, `ADD CHARACTER TO
  PARTY` reads it straight back into the party, and the file is still in the
  directory afterwards -- through the pick, through `EXIT`, and through
  `SAVE CURRENT GAME`. So a party member and a parked file share a name for
  ever after an ordinary remove-and-re-add, and the parked one keeps whatever
  the record held at the moment it was parked.

**A full party is why an add can look ignored.** Curse takes six, and the pick
on a full party leaves the list on screen having done nothing, which reads
exactly like a keypress that never arrived. `--remove NAME` takes a member out
first, which is both what frees the slot and what produces the file to add
back -- the player's own route.

Run it with `--remove` for that route, or with a save whose file and record
disagree for the matching question; `tools/c64nametable.py show` prints both
sides so you can build one.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import curseload, curserun, gamedisks  # noqa: E402
from tools import savecheck as SC  # noqa: E402
from tools import session as por  # noqa: E402
from tools.c64nametable import character_files, from_bar, load_party  # noqa: E402

#: Curse's own prefix byte for a parked character's filename, from
#: `tools/c64nametable.py`'s `PREFIX`.
CURSE_PREFIX = 0x02


def dump(sess, out, tag, shots):
    s = sess.screen()
    text = "(bitmap)" if s is None else "\n".join(s.row(r).rstrip() for r in range(25))
    shots[0] += 1
    # A character's name goes into the tag and a Curse party has an `F/T` in
    # it, which as a filename is a directory nobody made.
    stem = f"{shots[0]:02d}-" + "".join(
        c if c.isalnum() or c in "-_" else "-" for c in tag)
    (out / f"{stem}.txt").write_text(text + "\n")
    sess.kbd.screenshot(str(out / f"{stem}.png"))
    print(f"--- {tag} ---", flush=True)
    for ln in text.splitlines():
        if ln.strip():
            print(ln, flush=True)
    return text


def directory(sess, out, tag, keep: bool = False) -> list[str]:
    """The save disk's directory as the emulator has written it so far.

    Read off the image in the slot rather than off a copy taken at the end,
    because the question is *when* a file appears and disappears rather than
    what is left when the run stops. A copy is kept beside it on request, so a
    reading nobody believes can be checked afterwards.
    """
    names = [e.name.decode("latin1").rstrip("\xa0 ")
             for e in D64.open(sess.save_disk).iter_directory()]
    if keep:
        shutil.copy(sess.save_disk, out / f"disk-{tag}.D64")
    print(json.dumps({"event": "directory", "tag": tag, "names": names}), flush=True)
    return names


def parked_record(sess, name: str) -> str:
    """The name **inside** a parked character's own file, which is the half a
    directory listing cannot show."""
    disk = D64.open(sess.save_disk)
    for entry in disk.iter_directory():
        if entry.name.decode("latin1").rstrip("\xa0 ")[1:] != name:
            continue
        try:
            return CharacterRecord.from_prg(disk.read_file(entry)).name
        except Exception as exc:      # a file that will not parse is a finding
            return f"(unreadable: {exc})"
    return "(no such file)"


def answer(sess, word: str, timeout: float = 60.0) -> bool:
    """Answer whatever `YES NO` question row 24 is asking, with *word*.

    `REMOVE CHARACTER FROM PARTY` does not simply write the character out: it
    asks `MAKE SAVE GAME DISK ? YES NO` first, and until that is answered the
    list stays on the screen and every later pick lands on the wrong menu.
    A first run read the unanswered remove list as an add list, found `CLERIC`
    on it because `CLERIC` is also a party row, and reported a pick that never
    happened (`work/issue439/readd1`).

    The Return goes in through the KERNAL buffer, as it does at this title's
    other `YES NO` bars -- an XTEST Return does not move them
    (`tools/cursewarp.py`).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sess.handle_prompt():
            sess.press_kernal(0x20)
        s = sess.screen()
        row = "" if s is None else s.row(24)
        if "YES" in row and "NO" in row:
            ok = sess.select_bar(word, timeout=15.0)
            sess.press_kernal(0x0D)
            print(json.dumps({"event": "answered", "bar": row.strip(),
                              "with": word, "walked": ok}), flush=True)
            return True
        time.sleep(1.0)
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", required=True,
                    help="a Curse save disk to drive")
    ap.add_argument("--out", default="work/issue439/add-probe",
                    help="where the screens and the saved disk are written")
    ap.add_argument("--disks", default="",
                    help="the player's own game disks; $POR_DISKS otherwise")
    ap.add_argument("--remove", default="",
                    help="a party member to take out first, which frees a "
                         "slot and writes their own file to the disk")
    ap.add_argument("--pick", default="",
                    help="the name to pick off the add list; the removed "
                         "character, or the first parked file, by default")
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
    pick = args.pick or args.remove
    slot = por.claim_slot(args.slot, note="c64addprobe/439")
    sess = None
    try:
        print("slot", slot.n, slot.port, slot.display, slot.dir, flush=True)
        first = curserun.stage(slot, where, save)
        sess = curserun.CurseSession(first, slot=slot)
        sess.save_disk = f"{slot.dir}/SIDE0.D64"
        disk = D64.open(sess.save_disk)
        print("staged, character files:", character_files(disk, CURSE_PREFIX),
              flush=True)
        if not sess.boot():
            dump(sess, out, "boot-failed", shots)
            return 1
        dump(sess, out, "main-menu", shots)
        if not load_party(sess):
            dump(sess, out, "load-failed", shots)
            return 1
        sess.settle(3.0)
        dump(sess, out, "loaded", shots)
        directory(sess, out, "loaded", keep=True)
        if hasattr(sess, "patch_disk_prompt"):
            print("disk_prompt_patched", sess.patch_disk_prompt(), flush=True)

        if args.remove:
            # Curse takes six, and a pick on a full party does nothing at all
            # -- the list stays up and no key looks to have arrived. Taking a
            # member out is what makes room, and it is the same act that
            # writes the file the add then reads.
            sess.select_row("REMOVE CHARACTER FROM PARTY", timeout=25.0)
            sess.settle(4.0)
            dump(sess, out, "remove-list", shots)
            print("remove:", args.remove,
                  sess.select_row(args.remove, timeout=25.0), flush=True)
            settle(sess, 20.0)
            dump(sess, out, f"asked-{args.remove}", shots)
            # NO keeps the disk in the drive; YES would format a fresh one and
            # the run would be measuring a disk it made rather than the
            # player's.
            print("make save disk:", answer(sess, "NO"), flush=True)
            settle(sess, 40.0)
            dump(sess, out, f"removed-{args.remove}", shots)
            directory(sess, out, "after-remove", keep=True)
            sess.select_row("EXIT", timeout=15.0)
            sess.settle(4.0)
            dump(sess, out, "after-remove-exit", shots)
            directory(sess, out, "after-remove-exit")

        sess.select_row("ADD CHARACTER TO PARTY", timeout=25.0)
        sess.settle(6.0)
        text = dump(sess, out, "add-bar", shots)
        word = from_bar(text) or "CURSE"
        print("ADD FROM word:", word, flush=True)
        sess.select_bar(word, timeout=25.0)
        settle(sess, 45.0)
        add_list_text = dump(sess, out, "add-list", shots)
        if not pick:
            files = character_files(D64.open(sess.save_disk), CURSE_PREFIX)
            pick = files[0] if files else ""
        # The add list replaces the party panel, heading and all, so `AC HP`
        # still on the screen means this is some other menu and a name found
        # on it is a party row rather than a candidate. That is what made a
        # first run report picking `CLERIC` off a remove list nobody had
        # dismissed (`work/issue439/readd1`).
        is_add_list = "AC HP" not in add_list_text
        print(json.dumps({"event": "add_list", "reached": is_add_list,
                          "pick": pick,
                          "offered": is_add_list and pick in add_list_text}),
              flush=True)
        print("record inside the file:", pick, parked_record(sess, pick),
              flush=True)

        ok = sess.select_row(pick, timeout=25.0) if pick else False
        print("picked:", pick, ok, flush=True)
        settle(sess, 40.0)
        dump(sess, out, "after-pick", shots)
        directory(sess, out, "after-pick", keep=True)
        answer(sess, "NO", timeout=20.0)
        settle(sess, 30.0)
        dump(sess, out, "after-confirm", shots)
        directory(sess, out, "after-confirm")

        sess.select_row("EXIT", timeout=15.0)
        settle(sess, 20.0)
        dump(sess, out, "after-exit", shots)
        sess.wait_text("BEGIN ADVENTURING", 60)
        directory(sess, out, "after-exit", keep=True)

        sess.select_row("SAVE CURRENT GAME", timeout=15.0)
        settle(sess, 20.0)
        # `SAVE GAME ? YES NO` first, and then `MAKE SAVE GAME DISK ? YES NO`
        # if the drive would not take the write -- which is the shape a
        # write-protected image puts the run into, so NO there rather than
        # formatting one.
        print("save game:", answer(sess, "YES", timeout=30.0), flush=True)
        settle(sess, 20.0)
        print("make save disk:", answer(sess, "NO", timeout=20.0), flush=True)
        settle(sess, 40.0)
        dump(sess, out, "after-save", shots)
        sess.wait_text("BEGIN ADVENTURING", 90)

        kept = out / "save-after.D64"
        shutil.copy(sess.save_disk, kept)
        # A copy taken straight after the engine's own `SAVE CURRENT GAME`
        # can catch `SAVEAZURE` before the drive has finished closing it --
        # type `$02`, no block count -- and the game answers such a disk with
        # `UNABLE TO LOAD SAVED GAME.` on the next boot
        # (`docs/179-loading-a-curse-save.md`, `60, WRITE FILE OPEN`).  The
        # payload is all there, so closing the entry in **this copy** is what
        # makes the run's own output loadable; the disk it was staged from is
        # never touched.
        print(json.dumps({"event": "closed_splat",
                          "entries": curseload.close_splat(str(kept))}),
              flush=True)
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


def settle(sess, budget: float, quiet: int = 3) -> None:
    """Wait for the screen to stop changing rather than for a clock.

    A remove and an add each spin the drive for as long as the drive takes,
    and the disk prompt that can sit over either is answered through the
    KERNAL buffer -- an XTEST space is not one of the two ways out of the
    routine that draws it (`tools/c64nametable.py`'s `wait_still`).
    """
    last, same, end = None, 0, time.time() + max(budget, 6.0)
    while time.time() < end and same < quiet:
        if sess.handle_prompt():
            sess.press_kernal(0x20)
        s = sess.screen()
        text = None if s is None else "\n".join(s.row(r) for r in range(25))
        same = same + 1 if text == last else 0
        last = text
        time.sleep(1.0)


if __name__ == "__main__":
    sys.exit(main())

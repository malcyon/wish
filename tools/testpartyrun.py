#!/usr/bin/env python3
"""Boot the generated test party in VICE and read all six sheets off the screen.

`docs/119-test-party.md` §6's third gate, and the only one that is evidence
about the game: `tools/testparty.py` builds a party out of our own tables, and
a test that reads those bytes back through the same tables passes whether or
not the game agrees.  This asks the C64 instead.  The name, class, level, hit
points, armour class and THAC0 come back through the game's own character-sheet
routine and its own charset, which shares nothing with `goldbox/layout.py`.

    tools/testpartyrun.py --disk work/issue10/TESTPARTY.D64

**Nothing is written to the player's disks.**  `--disk` is a copy
`tools/testparty.py` already made; `tools/session.stage_disks` copies the eight
sides and that save into the pool slot's own directory, and `Session.attach`
refuses any path outside it.  `POR_HEADLESS` is the slot's default, so no
window lands on the desktop.

Every event goes to `run.jsonl` as it happens rather than into a summary a
killed run never reaches, and each sheet is photographed while it is up --
which is the only moment it can be, since `Session.character_sheet` leaves the
sheet before it returns.

**Interrupt this with SIGINT and not SIGTERM**, so the `finally` gets to free
the slot.
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

from automap.paths import find_disks  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")


class Log:
    """One JSON line per event, written as it happens."""

    def __init__(self, out: pathlib.Path, quiet: bool = False) -> None:
        out.mkdir(parents=True, exist_ok=True)
        self.dir = out
        self.file = open(out / "run.jsonl", "w")
        self.quiet = quiet

    def emit(self, kind: str, **what) -> None:
        self.file.write(json.dumps({"t": round(time.time(), 3),
                                    "event": kind, **what}) + "\n")
        self.file.flush()

    def say(self, line: str) -> None:
        if not self.quiet:
            print(line, flush=True)

    def close(self) -> None:
        self.file.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, type=pathlib.Path,
                   help="the generated save disk, already a copy")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's game sides are; read, never "
                        "written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--party", type=int, default=6,
                   help="how many sheets to read")
    p.add_argument("--out", default=None, help="run directory")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out = pathlib.Path(args.out) if args.out else ROOT / "work" / "issue10" / "run"
    log = Log(out, args.quiet)
    log.emit("start", disk=str(args.disk), sides=args.disks)

    # The staging directory holds the generated save beside symlinks to the
    # player's own sides, so `stage_disks` copies all nine into the slot and
    # the originals are only ever read -- the shape `tools/turndrive.py` uses.
    staging = out / "disks"
    staging.mkdir(parents=True, exist_ok=True)
    S.stage_writable(args.disk, staging / "STAGED.D64")
    for i in range(1, 9):
        src = pathlib.Path(args.disks) / f"POOL{i}.D64"
        link = staging / f"POOL{i}.D64"
        if src.exists() and not link.exists():
            link.symlink_to(src.resolve())

    slot = S.claim_slot(args.slot, f"testpartyrun/{args.disk.name}")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    sess, rc = None, 0
    try:
        sess = S.Session(S.stage_disks(slot, staging, "STAGED.D64"), slot=slot)
        for step in ("boot", "load_save", "begin_adventuring"):
            log.say(f"{step} ...")
            if not getattr(sess, step)():
                log.emit("failed", step=step)
                raise RuntimeError(f"{step} failed")
            log.emit("done", step=step)
        sess.settle(3)
        log.emit("world", position=list(sess.position()))
        log.say(f"in the world at {sess.position()}")

        for index in range(args.party):
            shot = str(out / f"sheet{index}.png")
            lines = sess.character_sheet(index, shot=shot)
            log.emit("sheet", index=index, lines=lines, shot=shot)
            if lines is None:
                log.say(f"  slot {index}: no sheet")
                rc = 1
                continue
            (out / f"sheet{index}.txt").write_text("\n".join(lines) + "\n")
            log.say(f"  slot {index}: {lines[0][:60] if lines else ''}")
            for line in lines[:6]:
                log.say(f"      {line}")
    except Exception as exc:                       # noqa: BLE001
        log.emit("error", why=repr(exc))
        log.say(f"ERROR {exc!r}")
        rc = 2
    finally:
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
        log.emit("end", rc=rc)
        log.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

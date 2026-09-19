"""The `ssb14` boot with no Escape ever sent, to see whether `ECL10` then loads whole.

Belongs to #334 (The session driver cannot fight in Curse or Silver Blades, and says the party is not in a fight while it is standing on the combat floor).

`ssb14` showed `ECL10` landing at `$8000` and stopping at `$97CD` -- 6094 of
its 7013 body bytes -- with slot 8's recorded KERNAL `LOAD` end address
(`$2D9E`/`$2DB7`) left at 0 while every other slot loaded in that session
recorded its file's exact length. `tools/secret_of_the_silver_blades/ssbwarp.py`'s `enter_world` presses
`Escape` when a screen has sat unchanged for fifteen seconds, and VICE's C64
keymap puts `Escape` on RUN/STOP, which aborts a KERNAL `LOAD` in flight.

This run reproduces `ssb14` exactly except that **no Escape is ever sent**:
the enter-world loop below answers only the prompts `enter_world` answers and
otherwise waits, polling slot 8's end address and `ECL10`'s tail every two
seconds so the load can be watched arriving.

Expected if the Escape is the cause: the `tail` checkpoint over
`$9AC8`-`$9B64` fires 157 times, `$2D9E`/`$2DB7` reads `$65`/`$9B`, and
`$8000`-`$9B64` matches `ECL10`'s body for all 7013 bytes.

Run: `.venv/bin/python tools/secret_of_the_silver_blades/ssbloadnoescape.py`. It takes no arguments,
claims an emulator pool slot and boots Silver Blades with `$WISH_SPECIMENS/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64`
as the save. Writes dumps and `noesc.jsonl` under this tool's scratch directory
(`tools/scratch.py`).
`ssbloadwatch.py` is the same boot with the loader watched from the party
menu, and `ssbloadescape.py` adds one Escape.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port as G  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools import (  # noqa: E402
    gamedisks,
    scratch,
    specimens,
)
from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds.cursethac0 import checkpoint_hits  # noqa: E402
from tools.secret_of_the_silver_blades import (  # noqa: E402
    ssbwarp,
)

OUT = scratch.scratch_dir("ssbloadnoescape")
SAVE = str(specimens.tree_root() / "por-c64"
            / "WISH-SPEC-ssb-d-engine-resave-walked.D64")

REGIONS = [
    ("script", 0x8000, 0x2000),
    ("linker", 0x2D00, 0x0100),
]
CHECKPOINTS = [
    ("tail", 0x9AC8, 0x9B64),
    ("head", 0x8000, 0x800F),
]


def poll(sess, ckpts):
    """Slot 8's end address, the two hit counts and eight tail bytes."""
    with sess.mon(10) as m:
        lo, hi = m.read(0x2D9E, 1)[0], m.read(0x2DB7, 1)[0]
        hits = {n: checkpoint_hits(m, k) for n, k in ckpts.items()}
        tail = m.read(0x9AF9, 8)
        m.resume()
    return {"slot8_end": f"${hi:02X}{lo:02X}", "hits": hits,
            "tail9AF9": tail.hex(" ")}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    out = OUT
    scratch.ensure(out)
    log_file = (out / "noesc.jsonl").open("w")

    def log(kind: str, **kw) -> None:
        kw["kind"], kw["t"] = kind, round(time.time(), 3)
        rec = {k: (v.hex(" ") if isinstance(v, (bytes, bytearray)) else v)
               for k, v in kw.items()}
        log_file.write(json.dumps(rec, default=str) + "\n")
        log_file.flush()
        print(kind, {k: v for k, v in rec.items() if k not in ("kind", "t")},
              flush=True)

    game = G.SECRET_OF_THE_SILVER_BLADES
    disks = str(gamedisks.find(game.key) or "")
    if not disks:
        print("no Silver Blades disks found", file=sys.stderr)
        return 2

    slot = S.claim_slot(None, "reverse-engineering/334-ssb15-noescape")
    log("slot", n=slot.n, display=slot.display, dir=str(slot.dir))
    sess = None
    rc = 1
    try:
        boot = ssbwarp.stage(slot, disks, SAVE)
        sess = ssbwarp.SSBSession(boot, slot=slot)
        sess.save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        if not sess.boot():
            log("boot", reached_menu=False)
            return 1
        log("boot", reached_menu=True)

        ckpts: dict[str, int] = {}
        with sess.mon(15) as m:
            m.checkpoints_clear()
            for name, start, end in CHECKPOINTS:
                ckpts[name] = m.checkpoint_set(start, end, store=True,
                                               stop=False)
            m.resume()
        log("armed", checkpoints=ckpts)

        if not ssbwarp.load_party(sess):
            log("loaded", outcome="no")
            return 1
        log("loaded", outcome="loaded", **poll(sess, ckpts))

        # -- enter_world's loop, with the Escape branch removed -------------
        deadline = time.time() + 300.0
        seen, began, entered, settled_since = "", False, False, None
        while time.time() < deadline:
            s = sess.screen()
            if s is None:
                time.sleep(0.5)
                continue
            text = s.text()
            if sess.handle_prompt(s):
                log("prompt-answered")
                time.sleep(1.5)
                continue
            state = ("BEGIN" if "BEGIN ADVENTURING" in text
                     else "(blank)" if not text.strip("@ \n")
                     else s.row(24).strip())
            if state != seen:
                seen, settled_since = state, time.time()
                log("screen", state=state, **poll(sess, ckpts))
            if "ENCAMP" in text:
                log("world-bar", **poll(sess, ckpts))
                entered = True
                break
            if state == "BEGIN":
                began = True
                sess.select_row("BEGIN ADVENTURING")
                sess.press_kernal(0x0D)
            elif "EXIT" in state and state != "ENCAMP":
                sess.select_bar("EXIT", timeout=10)
                sess.press_kernal(0x0D)
                settled_since = time.time()
            elif any(w in state for w in ("CONTINUE", "MORE", "PRESS")):
                sess.press_kernal(0x0D)
                settled_since = time.time()
            # No Escape branch. Nothing else is ever pressed.
            time.sleep(2.0)
            if began:
                log("waiting", state=state,
                    settled=round(time.time() - settled_since, 1),
                    **poll(sess, ckpts))
        log("entered", entered=entered, began=began)

        s = sess.screen()
        (out / "03-world.txt").write_text(
            "\n".join(s.row(r) for r in range(25)) + "\n"
            if s is not None else "(bitmap)\n")
        sess.kbd.screenshot(str(out / "03-world.png"))

        with sess.mon(20) as m:
            dumps = {n: m.read(a, ln) for n, a, ln in REGIONS}
            hits = {n: checkpoint_hits(m, k) for n, k in ckpts.items()}
            lo, hi = m.read(0x2D9E, 1)[0], m.read(0x2DB7, 1)[0]
            cache = m.read(0x7F13, 26)
            m.resume()
        for n, blob in dumps.items():
            (out / f"03-world-{n}.bin").write_bytes(blob)

        d = D64(pathlib.Path(disks, "SILVER-1.D64").read_bytes())
        body = d.read_file("ECL10")[2:]
        ram = dumps["script"]
        first = next((i for i in range(len(body)) if ram[i] != body[i]), None)
        log("verdict", hits=hits, slot8_end=f"${hi:02X}{lo:02X}",
            ecl10_body=len(body),
            first_divergence=(None if first is None else
                              f"index {first} (${0x8000 + first:04X})"),
            bytes_matching=(len(body) if first is None else first),
            tail_9AF9=ram[0x9AF9 - 0x8000:0x9AF9 - 0x8000 + 8].hex(" "),
            tail_9B20=ram[0x9B20 - 0x8000:0x9B20 - 0x8000 + 8].hex(" "),
            cache=cache.hex(" "))
        rc = 0
        return rc
    finally:
        log("done", rc=rc)
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
        log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())

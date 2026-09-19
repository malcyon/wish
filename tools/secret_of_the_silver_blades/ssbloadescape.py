"""`ECL10` load with a single Escape sent, the causal half of the `ssb14`/`ssb15` pair.

Belongs to #334 (The session driver cannot fight in Curse or Silver Blades, and says the party is not in a fight while it is standing on the combat floor).

`ssb15` (no Escape ever sent) loaded `ECL10` whole: 157 store hits over
`$9AC8`-`$9B64`, slot 8's end address `$9B65`, 7013 of 7013 body bytes.
`ssb14` (`enter_world`'s fifteen-second stuck timer pressed `Escape` once)
loaded 6094 of 7013 and left slot 8's end at 0.

This run is `ssb15` with **one** thing added: the moment the `head`
checkpoint shows `ECL10`'s load has begun writing `$8000`, wait two seconds
and send a single `Escape` -- VICE's C64 keymap puts it on RUN/STOP, and the
KERNAL `LOAD` loop polls RUN/STOP between bytes. If the Escape is the cause,
the tail count stays below 157, slot 8's end address stays 0, and the script
in RAM stops part-way through the file.

Run: `.venv/bin/python tools/secret_of_the_silver_blades/ssbloadescape.py`. It takes no arguments, claims
an emulator pool slot and boots Silver Blades with `$WISH_SPECIMENS/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64`
as the save. Writes dumps and `esc.jsonl` under `<tmp>/wish/ssbloadescape/`.
`ssbloadnoescape.py` is the `ssb15` half.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox import c64_port as G  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds.cursethac0 import checkpoint_hits  # noqa: E402
from tools.registry import (  # noqa: E402
    scratch,
    specimens,
)
from tools.secret_of_the_silver_blades import (  # noqa: E402
    ssbwarp,
)

OUT = scratch.scratch_dir("ssbloadescape")
SAVE = str(specimens.tree_root() / "por-c64"
            / "WISH-SPEC-ssb-d-engine-resave-walked.D64")

CHECKPOINTS = [("tail", 0x9AC8, 0x9B64), ("head", 0x8000, 0x800F)]


def poll(sess, ckpts):
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
    log_file = (out / "esc.jsonl").open("w")

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

    slot = S.claim_slot(None, "reverse-engineering/334-ssb16-escape")
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

        deadline = time.time() + 300.0
        seen, began, entered, pressed = "", False, False, False
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
                seen = state
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
            elif any(w in state for w in ("CONTINUE", "MORE", "PRESS")):
                sess.press_kernal(0x0D)
            time.sleep(1.0)
            if began:
                r = poll(sess, ckpts)
                log("waiting", state=state, pressed=pressed, **r)
                if not pressed and r["hits"]["head"] >= 16 \
                        and r["hits"]["tail"] == 0:
                    time.sleep(2.0)
                    before = poll(sess, ckpts)
                    sess.kbd.key("Escape")
                    pressed = True
                    log("escape-sent", before=before,
                        after=poll(sess, ckpts))
        log("entered", entered=entered, began=began, pressed=pressed)

        s = sess.screen()
        (out / "03-world.txt").write_text(
            "\n".join(s.row(r) for r in range(25)) + "\n"
            if s is not None else "(bitmap)\n")
        sess.kbd.screenshot(str(out / "03-world.png"))

        with sess.mon(20) as m:
            ram = m.read(0x8000, 0x2000)
            hits = {n: checkpoint_hits(m, k) for n, k in ckpts.items()}
            lo, hi = m.read(0x2D9E, 1)[0], m.read(0x2DB7, 1)[0]
            m.resume()
        (out / "03-world-script.bin").write_bytes(ram)

        d = D64(pathlib.Path(disks, "SILVER-1.D64").read_bytes())
        body = d.read_file("ECL10")[2:]
        first = next((i for i in range(len(body)) if ram[i] != body[i]), None)
        log("verdict", hits=hits, slot8_end=f"${hi:02X}{lo:02X}",
            escape_sent=pressed, ecl10_body=len(body),
            first_divergence=(None if first is None else
                              f"index {first} (${0x8000 + first:04X})"),
            bytes_matching=(len(body) if first is None else first),
            tail_9AF9=ram[0x9AF9 - 0x8000:0x9AF9 - 0x8000 + 8].hex(" "))
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

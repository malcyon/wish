#!/usr/bin/env python3
"""Watch DOS Pool of Radiance write the treasure-share byte, by pressing KEEP.

`#304 (field_83_87 is written as a constant that the characters we rolled
ourselves do not hold)` asks why every character this project rolled holds 0 at
record `0x085` and every character in the archives holds 1.  Reading the
shipped `GAME.OVR` answers it -- the only instruction in Pool of Radiance,
Curse or Silver Blades that stores an immediate into that byte stores **1**,
and it is the last statement of MODIFY CHARACTER, reached on `K` for KEEP.
This is that reading put to the running game, which is the standard
`.claude/rules/conversions.md` sets.

**Two arms and a control, in one boot.**  MODIFY CHARACTER's own prompt reads
`Keep Exit`, and only `K` reaches the store: `E` returns from the routine
several statements earlier.  So the run is

    create two characters, add both, SAVE      -- both should read 0
    MODIFY the selected one, EXIT, SAVE        -- both should still read 0
    MODIFY the selected one, KEEP, SAVE        -- one should read 1

and the second character never goes near the screen, so it is the control for
whatever else a save rewrites.  A run that changes both characters, or that
changes the byte on the EXIT arm, refutes the reading rather than confirming
it.

**MODIFY CHARACTER is only offered on a character who has just been made** --
the engine refuses it unless experience is 0, 8333, 12500 or 25000 -- so this
has to roll its own party rather than load one.  It reuses
`tools/dosparty.py`'s creation flow, which is where the menu positions were
mapped.

    tools/dosmodifyprobe.py --out work/issue304/probe

Every screen is shot and every `SAVE` snapshot kept under `--out`, which is
under `work/` and never in the repository: a saved game is the game's data.
The verdict is read from the records the engine wrote, not from a screenshot.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_layout  # noqa: E402
from tools import dosbox, dosparty  # noqa: E402

#: The byte under test: the third of `field_83_87`, which the Curse
#: decompilation calls `npcTreasureShareCount`.
SHARE = dos_layout.FIELDS_BY_NAME["field_83_87"].offset + 2

#: Two characters, both human fighters so nothing about the roll differs
#: between them.  Menu positions, not record codes -- `tools/dosparty.py` has
#: the lists, and `work/issue249/party.json` is the spec they were measured
#: with: human is race 5 and FIGHTER is class 1 in a human's list.
SPECS = [dosparty.Spec(name="PROBEA", race=5, gender=0, cls=1, alignment=0,
                       classes={"fighter": 1}),
         dosparty.Spec(name="PROBEB", race=5, gender=0, cls=1, alignment=0,
                       classes={"fighter": 1})]


def shares(save_dir: pathlib.Path, letter: str) -> dict[str, int]:
    """`CHRDAT<letter><n>.SAV` -> the share byte, for every record present."""
    out = {}
    for path in sorted(save_dir.glob(f"CHRDAT{letter.upper()}?.SAV")):
        data = path.read_bytes()
        if len(data) == dos_layout.RECORD_SIZE:
            out[path.name] = data[SHARE]
    return out


def save(driver: "dosparty.Driver", session: dosbox.Session, letter: str,
         tag: str) -> None:
    """SAVE CURRENT GAME to `letter`, and wait for the files to stop moving."""
    driver.press("s", f"{tag}-save-open")
    driver.press(letter.lower(), f"{tag}-save-{letter}")
    dosbox.settle_files(session.save_dir, timeout=60.0)
    time.sleep(2.0)


def run(out: pathlib.Path, letter: str) -> int:
    session, slot = dosparty.open_session("issue304 modify probe", out)
    d = dosparty.Driver(session, out)
    log: list[dict] = []
    try:
        for spec in SPECS:
            d.create(spec)
            print(f"created {spec.name}", flush=True)
        menu = dosparty.menu_bar(session)
        d.press("a", "add-open")
        for i, spec in enumerate(SPECS):
            if i:
                d.press("End", f"add-{spec.name}-end")
            d.press("Return", f"add-{spec.name}")
        if dosparty.menu_bar(session) != menu:
            d.press("e", "add-exit")

        save(d, session, letter, "01-created")
        dosparty.collect(session, out, "created")
        log.append({"stage": "created", "shares": shares(session.save_dir,
                                                         letter)})
        print("created:", log[-1]["shares"], flush=True)

        # Arm 1: MODIFY, then EXIT.  The store is past this exit, so nothing
        # should move.
        d.press("m", "02-modify-open")
        d.press("e", "02-modify-exit")
        save(d, session, letter, "02-exited")
        dosparty.collect(session, out, "exited")
        log.append({"stage": "exited", "shares": shares(session.save_dir,
                                                        letter)})
        print("after MODIFY/EXIT:", log[-1]["shares"], flush=True)

        # Arm 2: MODIFY, then KEEP.
        d.press("m", "03-modify-open")
        d.press("k", "03-modify-keep")
        save(d, session, letter, "03-kept")
        dosparty.collect(session, out, "kept")
        log.append({"stage": "kept", "shares": shares(session.save_dir,
                                                      letter)})
        print("after MODIFY/KEEP:", log[-1]["shares"], flush=True)
    finally:
        session.close()
        slot.release()

    (out / "shares.json").write_text(json.dumps(log, indent=2) + "\n")
    created, exited, kept = (row["shares"] for row in log)
    verdict = []
    if set(created.values()) != {0}:
        verdict.append(f"a freshly rolled character does not read 0: {created}")
    if exited != created:
        verdict.append(f"MODIFY then EXIT moved the byte: {created} -> {exited}")
    moved = [n for n in kept if kept[n] != exited.get(n)]
    if len(moved) != 1 or kept[moved[0]] != 1:
        verdict.append(f"MODIFY then KEEP did not set exactly one byte to 1: "
                       f"{exited} -> {kept}")
    for line in verdict or ["CONFIRMED: KEEP writes 1 and EXIT writes nothing"]:
        print(line, flush=True)
    return 1 if verdict else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "work" / "issue304" / "probe")
    ap.add_argument("--slot", default="C", help="save-game letter to write")
    args = ap.parse_args(argv)
    return run(args.out, args.slot)


if __name__ == "__main__":
    raise SystemExit(main())

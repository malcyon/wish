#!/usr/bin/env python3
"""Can a Gold Box character change class twice?  Drive it and find out.

`#256 (The neutral record has nowhere to put a dual-classed character's
former levels)` turns on how many former classes a record can hold.  The C64
keeps one slot (`dual_class_slot` `0x0B9`, `dual_class_level` `0x0BA`) and DOS
keeps an eight-entry array, so the question is whether the engines ever put a
second class in either.

Reading the gate is one comparison in each port, and the addresses are in
`docs/176-changing-class-twice.md`.  This is the other half: it takes a
**save whose character is already dual-classed** back to `HUMAN CHANGE CLASS`
and photographs what the game does.

    tools/dualclassagain.py c64 --save ~/wish-specimens/por-c64/WISH-SPEC-curse-dual-classed.D64
    tools/dualclassagain.py c64 --save ... --serve     # boot and hand over

    tools/dualclassagain.py dos --game CURSE --party work/curse/234-curse-dualclassed
    tools/dualclassagain.py dos --game SECRET --party <tree> --from-slot C --slot C \
        --probe 1 --load-keys "Down,Down,Down,Return,c" \
        --press Down --press Down --press Return --press Down --press Return

**The `dos` half works and is what answered the question.** One save whose
character is already dual-classed, loaded with `0xD51` poked so the party menu
carries the training-hall items wherever the party stands, and then either the
roster highlight swept a character at a time (Curse, where the menu item is
per character) or the command actually pressed (Silver Blades, where it is
not).  `--from-slot` matters: **Silver Blades will not load a save installed
under a different letter from the one it was written as** -- copying slot C in
as slot D gives a `LOAD WHICH GAME: D` that offers D and then does nothing,
twice out of two.  Install a slot as itself.

**The `c64` half boots and reaches the party menu and has never got a save
loaded**, so the C64 answer in `docs/176-changing-class-twice.md` is a code
reading with no replay behind it.  What was tried on 2026-09-05, so the next
attempt starts further on:

* `LOAD SAVED GAME` -> `YES` gives `UNABLE TO LOAD SAVED GAME.` and redraws
  the same question, with the save disk attached to unit 8 before the command
  is entered, after it, with the disk-swap `NOP`s of `tools/curserun.py`
  applied and without, and with `$03B4` -- the byte `GEN $182D` compares
  against 2 to decide whether to ask for the save disk -- poked to 1 first.
* **It is not the specimen.**  `WISH-SPEC-curse-dual-classed`,
  `WISH-SPEC-curse-h-engine-resave` and `#18`'s own `work/issue18/train1.D64`,
  which that session did load, all fail identically.
* **The attach itself works**: with the save disk in the drive,
  `ADD CHARACTER TO PARTY` asks for `INSERT SIDE # 1`, which it would not do
  if the game side were still there.
* `GEN $1F42` is the load -- `LDA #$09 / LDX #$00 / LDY #$4B / JSR $3159`,
  nine characters of `SAVEAZURE` at `GEN $1F66` into `$4B00` -- and `$1F4B`
  branches to the message when it comes back non-zero.  Nobody has read
  `$3159`, and what it wants is the open question.

Two things about that front end are settled and are worth keeping either way.
**The menu's highlight is the colour RAM at the label's own column, not the
row's dominant colour**: `Session.select_row` reads the dominant colour, every
border row of this screen answers white as well, and the walk never starts.
And **Return is not read from XTEST here**, only from the KERNAL buffer, which
is the same finding `tools/cursewarp.py` records for the `YES NO` bar.

`--gate-off` writes two `NOP`s over the branch that refuses -- Curse
`GEN $2396`, Silver Blades `GEN $1F8B` -- so that the same drive can be run
with the refusal removed.  That is the differential that would turn "the
message appeared" into "this instruction is what produced it", and it has not
been run.

Nothing outside the slot's own directory is written and the player's disks are
opened read only.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))

from tools import gamedisks  # noqa: E402

#: Where each C64 title's refusal lives, read out of its own `GEN`.
#: `gate` is the `BNE` that jumps to the message when `dual_class_level` is
#: non-zero; `original` is what has to be there before `--gate-off` writes over
#: it, so a patch never lands on whatever else happens to be at the address.
C64_GATES = {
    "curse-of-the-azure-bonds": {
        "gate": 0x2396, "original": b"\xd0\x07",
        "menu": "HUMAN CHANGE CLASS",
        "sides": "CURSE_?.D64",
    },
    "secret-of-the-silver-blades": {
        "gate": 0x1F8B, "original": b"\xd0\x07",
        "menu": "HUMAN CHANGE CLASS",
        "sides": "SILVER*.D64",
    },
}

#: The working character record the front end reads and writes.
WORKING = 0x7C00
DUAL_SLOT, DUAL_LEVEL, LEVEL, RACE = 0x0B9, 0x0BA, 0x0A0, 0x072


def highlighted(sess, column: int) -> list[int]:
    """Rows whose colour RAM reads white at `column`, which is the highlight.

    Measured on 2026-09-05 with the party-formation menu up: the highlighted
    line's text is colour 1 and the other lines' is colour 5, over identical
    screen codes -- there is no inverse video anywhere on this screen, so
    reading bit 7 finds nothing.  The column matters because every border row
    is white too, and `Session.select_row`'s dominant-colour scan therefore
    answers rows that are not menu lines at all.
    """
    return [r for r in range(25) if sess.colours(r)[column] == 1]


def walk_menu(sess, label: str, timeout: float = 40.0) -> bool:
    """Move the menu highlight onto `label` and press Return.

    Return goes through the KERNAL buffer: this front end does not read an
    XTEST Return, which is the same finding `tools/cursewarp.py` records for
    the `LOAD SAVED GAME ? YES NO` bar.  The arrows *are* read from XTEST.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.3)
            continue
        hit = s.find(label)
        if hit is None:
            sess.handle_prompt(s)
            time.sleep(0.3)
            continue
        hot = highlighted(sess, hit[1])
        if not hot:
            time.sleep(0.3)
            continue
        cur = min(hot, key=lambda r: abs(r - hit[0]))
        if cur == hit[0]:
            sess.press_kernal(0x0D)
            return True
        sess.kbd.key("Down" if cur < hit[0] else "Up")
        time.sleep(0.2)
    return False


def answer_bar(sess, word: str) -> bool:
    """Pick `word` on a `YES NO` bar and press Return through the KERNAL."""
    if not sess.select_bar(word):
        return False
    sess.press_kernal(0x0D)
    return True


def load_party(sess, save_disk: str, note) -> bool:
    """Attach the save disk, then `LOAD SAVED GAME`, then `YES`.

    The order is the whole of it.  Entering the command with the game side in
    the drive fails, and the failure redraws the same question rather than
    saying which disk it wanted.
    """
    sess.attach(save_disk)
    sess.save_disk = save_disk
    if not walk_menu(sess, "LOAD SAVED GAME"):
        note(event="menu-miss", want="LOAD SAVED GAME")
        return False
    time.sleep(1.0)
    if not answer_bar(sess, "YES"):
        note(event="bar-miss", want="YES")
        return False
    for _ in range(40):
        time.sleep(2.0)
        s = sess.screen()
        if s is None:
            continue
        if "UNABLE TO LOAD" in s.text():
            note(event="load-failed", row24=s.row(24).strip())
            return False
        if "BEGIN ADVENTURING" in s.text():
            note(event="loaded")
            return True
        sess.handle_prompt(s)
    return False


def record(sess) -> dict:
    """The three bytes of the working record this question turns on."""
    with sess.mon(5) as m:
        raw = m.read(WORKING, 0x100)
    return {
        "race": raw[RACE], "level": raw[LEVEL],
        "dual_class_slot": raw[DUAL_SLOT], "dual_class_level": raw[DUAL_LEVEL],
        "levels": list(raw[0x0C9:0x0D1]), "class_bits": raw[0x0EB],
    }


def drive(args) -> int:
    from tools import curserun  # noqa: PLC0415
    from tools import session as por  # noqa: PLC0415

    gate = C64_GATES[args.title]
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    disks = args.disks or str(gamedisks.find(args.title) or "")
    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "i256"))
    note(event="slot", n=slot.n, monitor=slot.port, cmd=slot.cmd_port,
         display=slot.display, dir=str(slot.dir))
    disk = curserun.stage(slot, disks, args.save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    os.chmod(save_disk, 0o644)   # the specimen tree is read-only; the copy is ours
    sess = curserun.CurseSession(disk, slot=slot)
    note(event="booting")
    if not sess.boot():
        note(event="boot-failed")
        return 1
    note(event="booted")

    if not load_party(sess, save_disk, note):
        note(event="no-party", hint="serve and drive by hand")
        if args.serve:
            por.serve(sess)
        return 1
    note(event="party", row=sess.screen().text()[:200])

    if args.gate_off:
        with sess.mon(5) as m:
            was = m.read(gate["gate"], 2)
            if was != gate["original"]:
                note(event="gate-not-there", was=was.hex())
                return 1
            m.write(gate["gate"], b"\xea\xea")
        note(event="gate-off", at=hex(gate["gate"]))

    if not walk_menu(sess, gate["menu"]):
        note(event="menu-miss", want=gate["menu"])
        if args.serve:
            por.serve(sess)
        return 1
    time.sleep(1.5)
    note(event="who", screen=sess.screen().text()[:400])
    if args.serve:
        por.serve(sess)
    sess.close()
    slot.teardown()
    return 0


#: The training hall's maximum level, at this file offset of
#: `SAVGAM<slot>.DAT` in Pool of Radiance, Curse and Silver Blades alike
#: (`#234`).  Non-zero is what puts `Human Change Classes` in the party menu
#: wherever the party is standing, so a hall does not have to be walked to.
TRAIN_LEVEL = 0xD51


def install(party: pathlib.Path, save_dir: pathlib.Path, letter: str,
            train_level: int | None, source: str = "D") -> None:
    """Copy one slot out of a DOS save tree in as slot `letter`.

    A tree written by a played session holds several slots, and taking all of
    them renames `CHRDATA1` and `CHRDATB1` onto the same destination name --
    so `source` says which slot the party is, and nothing else is copied.
    Only the slot letter in the file names changes, and the one word at
    `TRAIN_LEVEL`.  Nothing in a character record is touched, so the record
    the game reads is the record the game wrote.
    """
    letter, source = letter.upper(), source.upper()
    for src in sorted(party.iterdir()):
        name = src.name.upper()
        if name.startswith("CHRDAT") and len(name) > 7 and name[6] == source:
            (save_dir / f"CHRDAT{letter}{name[7:]}").write_bytes(src.read_bytes())
        elif name == f"SAVGAM{source}.DAT":
            data = bytearray(src.read_bytes())
            if train_level is not None:
                data[TRAIN_LEVEL:TRAIN_LEVEL + 2] = \
                    int(train_level).to_bytes(2, "little")
            (save_dir / f"SAVGAM{letter}.DAT").write_bytes(bytes(data))


def dos(args) -> int:
    """Load a DOS save whose character is already dual-classed and look.

    The party menu is photographed once per character in the roster, because
    the enable flag Curse computes at `GAME.OVR 0x20252` is a property of the
    *selected* character rather than of the party -- so the answer is which
    shots carry the line and which do not, and one shot answers nothing.
    """
    import shutil  # noqa: PLC0415

    from tools import dosbox  # noqa: PLC0415

    party = pathlib.Path(args.party)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    slot = dosbox.claim("issue256 dual class twice")
    session = dosbox.Session(slot, dosbox.find_game(args.game))
    try:
        session.stage(fresh=True)
        shutil.rmtree(session.dir / "shots", ignore_errors=True)
        (session.dir / "shots").mkdir(parents=True, exist_ok=True)
        for old in session.save_dir.glob("*"):
            old.unlink()
        install(party, session.save_dir, args.slot, args.level,
                args.from_slot)
        note(event="staged", party=str(party), slot=args.slot,
             level=args.level, saves=len(list(session.save_dir.iterdir())))
        session.boot(fresh=False)
        if args.probe:
            # Silver Blades' title sequence does not settle the way
            # `PoolOfRadiance.to_main_menu` expects, so this presses and
            # photographs instead of deciding it has arrived.
            for i in range(args.probe):
                session.key("Return")
                session.settle(quiet=0.4, timeout=10.0)
                session.shot(f"boot-{i:02d}", allow_blank=True)
            note(event="probed", presses=args.probe)
        else:
            dosbox.PoolOfRadiance(session).to_main_menu()
        session.shot("0-menu")
        for i, k in enumerate(args.load_keys.split(",")):
            session.key(k.strip())
            session.settle(quiet=0.5, timeout=25.0)
            session.shot(f"1-load-{i}", allow_blank=True)
        session.settle(quiet=0.8, timeout=60.0)
        session.shot("2-party-menu")
        note(event="loaded", digest=session.capture().digest())
        for i in range(args.characters):
            for k in args.advance.split(","):
                session.key(k)
            session.settle(quiet=0.5, timeout=20.0)
            shot = session.shot(f"3-char-{i + 1}")
            note(event="character", n=i + 1, shot=shot.name,
                 digest=session.capture().digest())
        for n, press in enumerate(args.press):
            session.key(press)
            # A refusal here is a message printed and then timed out, so a
            # `settle` alone photographs the screen it went back to and not
            # the sentence.  Burst first, settle after.
            for b in range(args.burst):
                session.shot(f"4-press-{n:02d}-{press}-b{b}", allow_blank=True)
                time.sleep(args.burst_gap)
            session.settle(quiet=0.6, timeout=30.0)
            session.shot(f"4-press-{n:02d}-{press}")
            note(event="pressed", key=press,
                 digest=session.capture().digest())
        shots = out / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        for png in sorted((session.dir / "shots").glob("*.png")):
            shutil.copy(png, shots / png.name)
        note(event="done", shots=str(shots))
    finally:
        session.close()
        slot.release()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("c64", help="drive a C64 session")
    c.add_argument("--title", default="curse-of-the-azure-bonds",
                   choices=sorted(C64_GATES))
    c.add_argument("--save", required=True, help="the save disk to load")
    c.add_argument("--disks", default="")
    c.add_argument("--pool", type=int, default=None)
    c.add_argument("--out", default="work/issue256-dual/c64")
    c.add_argument("--gate-off", action="store_true",
                   help="NOP the refusal branch, to prove it is the refusal")
    c.add_argument("--serve", action="store_true",
                   help="hand the session over on the command port when done")
    c.set_defaults(func=drive)

    d = sub.add_parser("dos", help="drive a DOSBox session")
    d.add_argument("--game", default="CURSE", help="the game directory stem")
    d.add_argument("--party", required=True,
                   help="a save tree holding SAVGAM*.DAT and CHRDAT*")
    d.add_argument("--slot", default="D", help="which letter to install as")
    d.add_argument("--from-slot", default="D",
                   help="which slot of the source tree is the party")
    d.add_argument("--level", type=lambda s: int(s, 0), default=20,
                   help="what to write at 0xD51; 0 leaves the hall shut")
    d.add_argument("--characters", type=int, default=6,
                   help="how many times to advance the roster highlight")
    d.add_argument("--advance", default="End",
                   help="the key(s) that move the highlight, comma separated")
    d.add_argument("--press", action="append", default=[],
                   help="a key to press at the menu, after the sweep")
    d.add_argument("--burst-gap", type=float, default=0.25,
                   help="seconds between burst shots")
    d.add_argument("--burst", type=int, default=0,
                   help="shots to take straight after each press")
    d.add_argument("--load-keys", default="l,D",
                   help="the keys that reach and pick the save slot")
    d.add_argument("--probe", type=int, default=0,
                   help="press Return this many times and shoot each,\n                        instead of waiting for the menu to settle")
    d.add_argument("--out", default="work/issue256-dual/dos")
    d.set_defaults(func=dos)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

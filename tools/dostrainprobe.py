#!/usr/bin/env python3
"""Ask DOS Pool of Radiance whether TRAIN CHARACTER is gated on the same word
Curse of the Azure Bonds and Secret of the Silver Blades gate it on.

`#234 (A dual-classed Curse or Silver Blades character converted to DOS loses
the class he trained out of)` found the gate by reading the loader:
`cmp word es:[di+0x550], 0` against the second of four `farmalloc`'d buffers,
which is **file offset `0xD51` of `SAVGAM<slot>.DAT`** in both those titles --
the training hall's maximum level.  Set it non-zero in a copy of a save, load
it, and TRAIN CHARACTER is in the party menu wherever the party stands.
`docs/117-save-conversion.md` has the arithmetic.

**Whether Pool of Radiance does the same at the same offset was unknown**, and
this measures it rather than arguing about it.  One save, two slots, one word
different, one boot each:

* slot C is the specimen exactly as the engine wrote it -- the control;
* slot D is the same bytes with the word at `0xD51` set to `--level`.

Each is loaded through the game's own LOAD SAVED GAME and the menu it draws is
shot.  A run in which the two shots differ is the gate; a run in which they do
not is a refutation, and a refutation is the point of having the control.

    tools/dostrainprobe.py --party ~/wish-specimens/por-dos/WISH-SPEC-por-party-l1

Nothing is written outside the staged copy and `--out`, both under `work/`.
The specimen is opened read only.
"""

from __future__ import annotations

import argparse
import atexit
import pathlib
import shutil
import signal
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import dosbox  # noqa: E402
from tools.dosparty import wipe_roster  # noqa: E402

#: Where Curse and Silver Blades keep the training hall's maximum level.  A
#: word, little-endian, and zero everywhere a hall is not.
TRAIN_LEVEL = 0xD51


#: `goldbox.dos_layout`'s offsets, quoted here so the poke says what it is.
XP_AT, XP_SIZE = 0x0AC, 3
GOLD_AT = 0x08E
ENCUMBRANCE_AT = 0x102


def install(party: pathlib.Path, save_dir: pathlib.Path, letter: str,
            train_level: int | None, xp: int | None = None,
            gold: int | None = None) -> None:
    """Copy a specimen party into `save_dir` as slot `letter`.

    `train_level=None` copies the save byte for byte; a number pokes the word
    at `TRAIN_LEVEL` and changes nothing else, which is what makes the pair a
    differential rather than two runs.

    `xp` and `gold` write the character records' own fields.  **That makes the
    record an input, not evidence** -- `.claude/rules/testing.md` draws the
    line: editing an input and watching the engine compute from it is a valid
    experiment, because the engine does not care how a byte got there, while
    reading back a stored value we wrote and calling it the game's arithmetic
    is not.  Gold moves encumbrance with it, since one coin weighs one unit
    and the stored sum would otherwise disagree with the purse.
    """
    letter = letter.upper()
    for src in sorted(party.iterdir()):
        name = src.name.upper()
        if name.startswith("CHRDAT") and len(name) > 7:
            data = bytearray(src.read_bytes())
            if name.endswith(".SAV"):
                if xp is not None:
                    data[XP_AT:XP_AT + XP_SIZE] = \
                        int(xp).to_bytes(XP_SIZE, "little")
                if gold is not None:
                    was = int.from_bytes(data[GOLD_AT:GOLD_AT + 2], "little")
                    enc = int.from_bytes(
                        data[ENCUMBRANCE_AT:ENCUMBRANCE_AT + 2], "little")
                    data[GOLD_AT:GOLD_AT + 2] = int(gold).to_bytes(2, "little")
                    data[ENCUMBRANCE_AT:ENCUMBRANCE_AT + 2] = \
                        max(0, enc - was + int(gold)).to_bytes(2, "little")
            (save_dir / f"CHRDAT{letter}{name[7:]}").write_bytes(bytes(data))
        elif name.startswith("SAVGAM"):
            data = bytearray(src.read_bytes())
            if train_level is not None:
                data[TRAIN_LEVEL:TRAIN_LEVEL + 2] = \
                    int(train_level).to_bytes(2, "little")
            (save_dir / f"SAVGAM{letter}.DAT").write_bytes(bytes(data))


def probe(party: pathlib.Path, out: pathlib.Path, level: int | None,
          letter: str, watch: float, xp: int | None, gold: int | None) -> int:
    """One boot, one slot loaded, a shot every two seconds while it loads.

    One boot per invocation rather than `Session.restart()` between the two
    cases: the restart came back `DOSBox window never appeared` on the second
    boot of the same slot, and a probe that dies half way through has measured
    nothing.  The control and the test are two runs of this, with `--level`
    given for one of them and not the other.
    """
    out.mkdir(parents=True, exist_ok=True)
    slot = dosbox.claim("issue249 training gate")
    session = dosbox.Session(slot, dosbox.find_game())

    def cleanup(*_: object) -> None:
        session.close()
        slot.release()

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    session.stage(fresh=True)
    shutil.rmtree(session.dir / "shots", ignore_errors=True)
    (session.dir / "shots").mkdir(parents=True, exist_ok=True)
    wipe_roster(session.save_dir)
    install(party, session.save_dir, letter, level, xp, gold)

    try:
        session.boot(fresh=False)
        dosbox.PoolOfRadiance(session).to_main_menu()
        session.shot("0-menu")
        session.key("l")
        time.sleep(1.0)
        session.settle(quiet=0.5, timeout=15.0)
        session.shot("1-which")
        session.key(letter.lower())
        deadline = time.time() + watch
        n = 0
        while time.time() < deadline:
            time.sleep(2.0)
            session.shot(f"2-load-{n:02d}", allow_blank=True)
            n += 1
        final = session.settle(quiet=0.8, timeout=30.0)
        session.shot("3-final", allow_blank=True)
        print(f"{letter}: final screen {final.digest()}", flush=True)
        shots = out / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        for png in sorted((session.dir / "shots").glob("*.png")):
            shutil.copy(png, shots / png.name)
    finally:
        session.close()
        slot.release()
    print("shots in", out / "shots", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--party", type=pathlib.Path, required=True,
                    help="a specimen directory holding SAVGAM*.DAT and CHRDAT*")
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "work" / "issue249" / "trainprobe")
    ap.add_argument("--slot", default="C", help="which letter to install as")
    ap.add_argument("--level", type=lambda s: int(s, 0), default=None,
                    help="what to write at 0xD51; omit for the control")
    ap.add_argument("--xp", type=lambda s: int(s, 0), default=None,
                    help="experience to write into every character record")
    ap.add_argument("--gold", type=lambda s: int(s, 0), default=None,
                    help="gold to write into every character record")
    ap.add_argument("--watch", type=float, default=30.0,
                    help="seconds to keep shooting after the slot key")
    args = ap.parse_args(argv)
    return probe(args.party, args.out, args.level, args.slot, args.watch,
                 args.xp, args.gold)


if __name__ == "__main__":
    raise SystemExit(main())

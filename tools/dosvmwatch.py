#!/usr/bin/env python3
"""Watch the DOS engine write an ECL VM variable, and say which instruction did it.

The instrument behind `#218 (Three live regions of the DOS saved game are
named but not understood)`.  The disassembly of `GAME.OVR` says the saved
game's variable array is the ECL VM's memory -- three heap blocks for
`$4900`-`$4CFF`, `$6B00`-`$6EFF` and `$9700`-`$98FF` -- and that the words
this issue could not name are written by the area scripts through the VM's
own store routine: `$6DD2`/`$6DD3` (the rest-interruption interval and
chance) by entry 2 on ENCAMP, and `$6E7A`-`$6E7C` by the overland script's
special-square search on every step.  This puts both to the running game:

    tools/dosvmwatch.py --save work/p59-wallset/ycol --slot C

It stages the named engine-written save into a DOSBox-X instance, loads it,
finds the live VM array by matching the file (`tools/dosboxx.py`'s recipe),
arms a `BPM` on a word's low byte, presses a key, and records every change
the debugger reports together with `CS:IP` and the bytes of the instruction
that made it -- so a hit can be matched to a file offset in `GAME.OVR`
rather than taken on trust.  Two experiments run back to back: a step with
`--step-word` armed, then ENCAMP with `--camp-words` armed.

Addresses are given in the file's contiguous naming (`$4900` + word index),
the way `docs/141-dos-savegame.md` names them, and translated to the VM's own
addresses in the report.  Output goes under `--out`, which should be in
`work/`; the archives and the source save are never written.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosbox, dosboxx  # noqa: E402
from tools.dosspcexpiry import boot_retry, claim_free, on_screen  # noqa: E402

#: The VM's address classes (`GAME.OVR:0x7BCE`), as the file's word ranges.
BLOCKS = ((0, 0x4900), (1024, 0x6B00), (2048, 0x9700))


def vm_address(file_addr: int) -> int:
    """The VM's own address for a word named the file's contiguous way."""
    k = file_addr - dosboxx.VM_BASE_ADDR
    for first, base in reversed(BLOCKS):
        if k >= first:
            return base + (k - first)
    raise ValueError(f"{file_addr:#06x} is not a VM word")


def stage_save(s: dosboxx.XSession, source: pathlib.Path, slot: str) -> bytes:
    """Copy one save and its character files into the staged tree."""
    s.stage(fresh=True)
    letter = slot.upper()
    for p in sorted(source.glob(f"CHRDAT{letter}*")):
        shutil.copy(p, s.save_dir / p.name)
    src = source / f"SAVGAM{letter}.DAT"
    shutil.copy(src, s.save_file(letter))
    return src.read_bytes()


def boot_settled(s: dosboxx.XSession, tries: int = 4) -> None:
    """Boot, and boot again when the first capture lands on a half-drawn frame.

    `XSession.boot` ends with a `settle()`, and that capture can land while
    the emulator is still drawing its first frame, which `halve()` refuses as
    not line-doubled.  The game has not gone anywhere; the emulator has, so
    close it and start again on the staged tree.
    """
    for n in range(tries):
        try:
            boot_retry(s, fresh=False)
            return
        except dosboxx.NotLineDoubled as e:
            if n == tries - 1:
                raise
            print(f"half-drawn boot frame ({e}); rebooting")
            s.close()
            time.sleep(3.0)


def code_at(s: dosboxx.XSession, cs: int, ip: int, back: int = 8, fwd: int = 4) -> str:
    """The bytes around `CS:IP`, so a hit can be matched to `GAME.OVR`."""
    lin = dosboxx.linear((cs, ip))
    return s.read(lin - back, back + fwd).hex(" ")


def collect_hits(s: dosboxx.XSession, mark: int, quiet: float) -> list[dict]:
    """Every watchpoint hit from `mark` until none arrives for `quiet` seconds."""
    hits = []
    while True:
        hit = s.wait_break(mark, timeout=quiet)
        if hit is None:
            return hits
        regs = s.regs("CS", "IP")
        cs, ip = regs.get("CS", 0), regs.get("IP", 0)
        hits.append(dict(at=f"{hit.seg:04X}:{hit.ofs:04X}", old=hit.old, new=hit.new,
                         cs_ip=f"{cs:04X}:{ip:04X}", code=code_at(s, cs, ip)))
        print(f"  {hits[-1]['at']} {hit.old:02X} -> {hit.new:02X} at {hits[-1]['cs_ip']}  {hits[-1]['code']}")
        mark = s.mark()
        s.run()


def read_words(s: dosboxx.XSession, base: int, addrs: list[int]) -> dict[str, int]:
    out = {}
    for a in addrs:
        raw = s.read(base + dosboxx.vm_slot(a), 2)
        out[f"${a:04X} (VM ${vm_address(a):04X})"] = int.from_bytes(raw, "little")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--save", required=True, help="directory holding SAVGAM<slot>.DAT and its CHRDAT files")
    ap.add_argument("--slot", default="C")
    ap.add_argument("--step-word", type=lambda v: int(v, 0), default=0x507A,
                    help="file-named word to watch across one step (default $507A = VM $6E7A)")
    ap.add_argument("--step-key", default="Up")
    ap.add_argument("--camp-words", type=lambda v: int(v, 0), nargs="*", default=[0x4FD2, 0x4FD3],
                    help="file-named words to watch across ENCAMP (default $4FD2 $4FD3 = VM $6DD2 $6DD3)")
    ap.add_argument("--quiet", type=float, default=8.0, help="seconds without a hit that end a collection")
    ap.add_argument("--out", default="work/issue218/watch")
    args = ap.parse_args(argv)
    if dosboxx.unavailable():
        print(dosboxx.unavailable())
        return 2

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source = pathlib.Path(args.save)
    game = dosbox.find_game("POOLRAD")
    report: dict = dict(save=str(source), slot=args.slot)
    with claim_free("dosvmwatch") as slot:
        s = dosboxx.XSession(slot, game)
        try:
            save = stage_save(s, source, args.slot)
            boot_settled(s)
            por = dosbox.PoolOfRadiance(s)
            on_screen(por.to_main_menu)
            on_screen(lambda: por.load_game(args.slot))
            s.shot("loaded")
            if not s.attach():
                print("could not attach the debugger")
                return 1
            image = s.read(0, 0x100000)
            found = dosboxx.locate(image, save[dosboxx.VM_OFFSET:dosboxx.VM_OFFSET + dosboxx.VM_SIZE])
            if found is None:
                print("the VM array was not found in memory")
                return 1
            base, votes, same = found
            report["vm_base"] = f"{base:05X}"
            report["vm_votes"] = votes
            report["vm_same"] = same
            print(f"VM array at {base:05X}: {votes} windows voted, {same} of {dosboxx.VM_SIZE} bytes equal")

            # -- one step, with the step word armed ------------------------
            watched = [args.step_word, args.step_word + 1, args.step_word + 2, 0x49C3, 0x49C4]
            report["step_before"] = read_words(s, base, watched)
            print("before the step:", report["step_before"])
            absorbed = s.watch(base + dosboxx.vm_slot(args.step_word))
            report["step_absorbed"] = None if absorbed is None else dict(old=absorbed.old, new=absorbed.new)
            mark = s.mark()
            s.run()
            time.sleep(0.5)
            s.key(args.step_key)
            print(f"step ({args.step_key}), watching ${args.step_word:04X} = VM ${vm_address(args.step_word):04X}:")
            report["step_hits"] = collect_hits(s, mark, args.quiet)
            if not s.attach():
                print("could not re-attach after the step")
                return 1
            report["step_after"] = read_words(s, base, watched)
            print("after the step:", report["step_after"])
            s.shot("stepped")

            # -- ENCAMP, with the camp words armed ---------------------------
            s.clear_breakpoints()
            report["camp_before"] = read_words(s, base, args.camp_words)
            print("before camp:", report["camp_before"])
            for w in args.camp_words:
                s.watch(base + dosboxx.vm_slot(w))
            mark = s.mark()
            s.run()
            time.sleep(0.5)
            s.key("e")
            print("ENCAMP, watching", ", ".join(f"${w:04X} = VM ${vm_address(w):04X}" for w in args.camp_words))
            report["camp_hits"] = collect_hits(s, mark, args.quiet)
            if not s.attach():
                print("could not re-attach in camp")
                return 1
            report["camp_after"] = read_words(s, base, args.camp_words)
            print("in camp:", report["camp_after"])
            s.clear_breakpoints()
            s.run()
            time.sleep(0.5)
            s.shot("camp")
            s.key("Escape")
            time.sleep(1.0)
        finally:
            for png in (s.dir / "shots").glob("*.png"):
                (out / png.name).write_bytes(png.read_bytes())
            (out / "watch.json").write_text(json.dumps(report, indent=1))
            s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

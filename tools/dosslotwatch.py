#!/usr/bin/env python3
"""Watch a DOS Gold Box engine rebuild a character's spell-slot block.

The live half of `#222 (Silver Blades' fourth spell-slot array is zero in
every state anybody can create)`.  `tools/dosspellslots.py` reads the slot
builder out of `GAME.OVR` and says the engine zeroes the whole block and
adds into three of its four arrays; this puts that to the running game.
DOSBox-X's memory breakpoint fires on *change*, so a byte the file already
holds at zero cannot be watched being zeroed -- the record is patched to a
nonzero value first, and the load is what changes it back.

    tools/dosslotwatch.py --game SECRET --save work/curse/SSB-D-paine-memorised \\
        --slot D --patch 2:0x140=5 --minutes 40

is `tools/doscurse.py`'s console over `tools/dosboxx.py`'s DOSBox-X: it
boots with the save staged and patched, then executes lines appended to
`work/dosbox/x/inst/<n>/console.cmd`, shooting the screen after each.  The
console's own commands (`key`, `type`, `sleep`, `settle`, `shot`, `files`,
`quit`) work as there; these are added for the debugger:

| line | what it does |
|---|---|
| `attach` | Alt+Pause into the debugger |
| `find` | dump memory, find every party record by its name, log each one's address and slot block |
| `poke N OFF=VAL ...` | write bytes into party member N's live record |
| `arm N OFF` | a `BPM` on party member N's record at `OFF` |
| `bpclear` | delete every breakpoint |
| `resume` | `RUN` |
| `collect SECS` | run and log every hit -- old, new, `CS:IP`, the code there and the far return address on the stack -- until none arrives for `SECS` |
| `record N` | log party member N's whole slot block, live |
| `armaddr HEX` | a `BPM` on a linear address -- for a record whose address a previous boot found |
| `reboot` | close DOSBox-X and boot again on the same staged tree, so a save can be loaded a second time with a breakpoint already armed |

Nothing here writes to the archives or to the source save: the staged copy
under `work/` is what is patched and loaded.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosbox, dosboxx, doscurse  # noqa: E402
from tools.dosspcexpiry import claim_free, name_key  # noqa: E402
from tools.dosvmwatch import boot_settled, code_at  # noqa: E402


class RawSession(dosboxx.XSession):
    """`XSession` whose captures are not halved.

    `dosboxx.halve` insists on a line-doubled 640x400 frame, which is Pool
    of Radiance's; Silver Blades' title frame is not, and the boot's
    `settle()` would refuse it forever.  Nothing here reads a rectangle off
    the screen, so the raw window is enough.
    """

    def capture(self) -> dosbox.Screen:
        return dosbox.Session.capture(self)


def parse_patch(spec: str) -> tuple[int, dict[int, int]]:
    """`2:0x140=5,0x143=7` -> `(2, {0x140: 5, 0x143: 7})`."""
    who, _, rest = spec.partition(":")
    edits = {}
    for item in rest.split(","):
        off, _, val = item.partition("=")
        edits[int(off, 0)] = int(val, 0)
    return int(who), edits


class Watch(doscurse.Console):
    """The console, plus the debugger."""

    def __init__(self, session: dosboxx.XSession, cmds: pathlib.Path,
                 log: pathlib.Path, slot: str, block: int, width: int):
        super().__init__(session, cmds, log)
        self.slot = slot
        self.block, self.width = block, width
        self.records: dict[int, int] = {}

    def party(self) -> list[tuple[int, bytes]]:
        out = []
        for n in range(1, 7):
            p = self.s.save_dir / f"CHRDAT{self.slot}{n}.SAV"
            if p.is_file():
                out.append((n, p.read_bytes()))
        return out

    def block_text(self, raw: bytes) -> str:
        cells = [raw[i:i + self.width].hex(" ") for i in range(0, 4 * self.width, self.width)]
        return " | ".join(cells)

    def do(self, line: str) -> bool:
        word, _, rest = line.partition(" ")
        rest = rest.strip()
        s: dosboxx.XSession = self.s  # type: ignore[assignment]
        if word == "type":
            self.say(f"[{self.n:03d}] {line}")
            env = s._env()
            subprocess.run(["xdotool", "windowfocus", s.window], env=env, capture_output=True)
            subprocess.run(["xdotool", "type", "--clearmodifiers", rest],
                           env=env, check=True, capture_output=True)
            time.sleep(0.4)
            self.shoot()
            return True
        if word not in ("attach", "find", "poke", "arm", "armaddr", "bpclear",
                        "resume", "collect", "record", "reboot"):
            return super().do(line)
        self.say(f"[{self.n:03d}] {line}")
        if word == "attach":
            self.say(f"  attached={s.attach()}")
        elif word == "find":
            image = s.read(0, 0x100000)
            for n, rec in self.party():
                key = name_key(rec)
                name = key[1:].decode("ascii", "replace")
                hits, at = [], 0
                while (at := image.find(key, at)) >= 0:
                    hits.append(at)
                    at += 1
                for at in hits:
                    live = image[at + self.block:at + self.block + 4 * self.width]
                    self.say(f"  {n} {name:16s} at {at:05X}  {self.block_text(live)}")
                if hits:
                    self.records[n] = hits[-1]
                    self.say(f"  {n}: using {hits[-1]:05X}; file holds "
                             f"{self.block_text(rec[self.block:self.block + 4 * self.width])}")
        elif word == "record":
            n = int(rest)
            at = self.records[n]
            live = s.read(at + self.block, 4 * self.width)
            self.say(f"  {n} at {at:05X}  {self.block_text(live)}")
        elif word == "poke":
            n, edits = parse_patch(rest.replace(" ", ":", 1))
            for off, val in edits.items():
                s.write(self.records[n] + off, bytes((val,)))
                self.say(f"  {n}+{off:#x} <- {val:#04x}")
        elif word == "arm":
            n, off = rest.split()
            at = self.records[int(n)] + int(off, 0)
            absorbed = s.watch(at)
            self.say(f"  BPM at {at:05X} ({dosboxx.seg_off(at)[0]:04X}:{dosboxx.seg_off(at)[1]:04X})"
                     f" absorbed={absorbed}")
        elif word == "armaddr":
            at = int(rest, 16)
            absorbed = s.watch(at)
            self.say(f"  BPM at {at:05X} absorbed={absorbed}")
        elif word == "reboot":
            s.close()
            time.sleep(3.0)
            boot_settled(s)
            self.say(f"  rebooted on {s.display}")
            self.shoot("reboot")
        elif word == "bpclear":
            s.clear_breakpoints()
        elif word == "resume":
            s.run()
        elif word == "collect":
            quiet = float(rest or 8)
            mark = s.mark()
            s.run()
            while True:
                hit = s.wait_break(mark, timeout=quiet)
                if hit is None:
                    break
                regs = s.regs("CS", "IP", "SS", "SP")
                cs, ip = regs.get("CS", 0), regs.get("IP", 0)
                ss, sp = regs.get("SS", 0), regs.get("SP", 0)
                stack = s.read((ss, sp), 8)
                ret = f"{int.from_bytes(stack[2:4], 'little'):04X}:{int.from_bytes(stack[0:2], 'little'):04X}"
                self.say(f"  hit {hit.seg:04X}:{hit.ofs:04X} {hit.old:02X} -> {hit.new:02X} "
                         f"at {cs:04X}:{ip:04X} code {code_at(s, cs, ip)} "
                         f"stack {stack.hex(' ')} (far return {ret})")
                mark = s.mark()
                s.run()
            self.say("  quiet")
        return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--game", default="SECRET")
    ap.add_argument("--exe", default="START.EXE")
    ap.add_argument("--save", required=True, help="directory holding the SAVGAM and CHRDAT files")
    ap.add_argument("--slot", default="D")
    ap.add_argument("--patch", action="append", default=[],
                    help="N:OFF=VAL[,OFF=VAL] into the staged CHRDAT<slot>N.SAV")
    ap.add_argument("--block", type=lambda v: int(v, 0), default=0x132)
    ap.add_argument("--width", type=int, default=7)
    ap.add_argument("--minutes", type=float, default=40.0)
    ap.add_argument("--note", default="dosslotwatch")
    a = ap.parse_args(argv)
    if dosboxx.unavailable():
        print(dosboxx.unavailable())
        return 2
    source = pathlib.Path(a.save)
    letter = a.slot.upper()
    with claim_free(a.note) as slot:
        s = RawSession(slot, dosbox.find_game(a.game), exe=a.exe)
        cmds = slot.dir / "console.cmd"
        log = slot.dir / "console.log"
        cmds.write_text("")
        log.write_text("")
        print(f"slot {slot.n} display {slot.display}\ncommands: {cmds}\nlog: {log}")
        try:
            s.stage(fresh=True)
            for p in sorted(source.glob(f"CHRDAT{letter}*")) + [source / f"SAVGAM{letter}.DAT"]:
                shutil.copy(p, s.save_dir / p.name)
            for spec in a.patch:
                n, edits = parse_patch(spec)
                p = s.save_dir / f"CHRDAT{letter}{n}.SAV"
                raw = bytearray(p.read_bytes())
                for off, val in edits.items():
                    raw[off] = val
                p.write_bytes(bytes(raw))
                print(f"patched {p.name}: {edits}")
            boot_settled(s)
            Watch(s, cmds, log, letter, a.block, a.width).run(a.minutes)
        finally:
            s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Set a watchpoint on a **running** pooled session and say where it fired.

    tools/livewatch.py --port 6523 --load 3583 3585

`tools/porcmd` has no way to stop the machine and look at it: a session
driver reads memory and presses keys, and the question this answers is a
different one -- *what code touched this byte, and who called it?*  It was
written for `#32 (One Curse session, to get a party with items)`, where the
game asks for a disk that is already in the drive and the only way to learn
which file it wanted was to catch the routine that draws the prompt.

It prints the program counter, the stack above the stack pointer as return
addresses, and 32 bytes either side of the program counter, then deletes the
checkpoint and lets the machine run on.  Nothing is left behind.

**The session must be idle.**  VICE serves one binary-monitor connection per
process; `tools/session.py` opens and closes its own for each command, so this
takes the socket between them and must not be run while a command is in
flight.
"""
from __future__ import annotations

import argparse
import pathlib
import socket
import struct
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.vice import (  # noqa: E402
    CMD_CHECKPOINT_DELETE,
    CMD_EXIT,
    CMD_MEM_GET,
    CMD_REGISTERS_GET,
    Monitor,
)

RESP_STOPPED = 0x62
RESP_CHECKPOINT = 0x11


class Watcher(Monitor):
    """A monitor connection that stays open across a stop."""

    def drain(self, timeout: float) -> list[tuple[int, bytes]]:
        """Every response that arrives before `timeout`, as (type, body)."""
        out: list[tuple[int, bytes]] = []
        end = time.time() + timeout
        assert self.sock is not None
        while time.time() < end:
            self.sock.settimeout(max(0.2, end - time.time()))
            try:
                head = self._recv_exactly(12)
            except (TimeoutError, socket.timeout):
                continue
            length, rtype = struct.unpack("<IB", head[2:7])
            body = self._recv_exactly(length) if length else b""
            out.append((rtype, body))
            if rtype == RESP_STOPPED:
                return out
        return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--load", nargs=2, metavar=("START", "END"),
                    help="break when this range is read, hex")
    ap.add_argument("--store", nargs=2, metavar=("START", "END"),
                    help="break when this range is written, hex")
    ap.add_argument("--exec", dest="exec_", nargs=2, metavar=("START", "END"),
                    help="break when this range is executed, hex")
    ap.add_argument("--peek", action="append", default=[], metavar="ADDR:LEN",
                    help="also dump this range when it fires, hex, repeatable")
    ap.add_argument("--follow", action="append", default=[], metavar="ADDR",
                    help="read a little-endian pointer here and dump 24 bytes "
                         "of what it points at, hex, repeatable")
    ap.add_argument("--wait", type=float, default=60.0)
    a = ap.parse_args(argv)
    kind = ("load", a.load) if a.load else \
           ("store", a.store) if a.store else ("exec_", a.exec_)
    if kind[1] is None:
        ap.error("one of --load, --store or --exec is required")
    start, end = (int(x, 16) for x in kind[1])

    with Watcher(port=a.port) as m:
        m.checkpoints_clear()
        num = m.checkpoint_set(start, end, **{kind[0]: True}, stop=True)
        print(f"checkpoint {num} on ${start:04X}-${end:04X} ({kind[0]})")
        m._send(CMD_EXIT, b"")
        events = m.drain(a.wait)
        kinds = [hex(t) for t, _ in events]
        if not any(t == RESP_STOPPED for t, _ in events):
            print(f"never fired in {a.wait}s; saw {kinds}")
            m.command(CMD_CHECKPOINT_DELETE, struct.pack("<I", num))
            return 1
        print(f"fired; responses {kinds}")
        resp = m.command(CMD_REGISTERS_GET, struct.pack("<B", 0))
        count = struct.unpack("<H", resp[:2])[0]
        regs, off = {}, 2
        for _ in range(count):
            size, rid_ = resp[off], resp[off + 1]
            regs[rid_] = struct.unpack("<H", resp[off + 2:off + 4])[0]
            off += size + 1
        pc, sp = regs.get(3, 0), regs.get(4, 0)
        print(f"PC ${pc:04X}  SP ${sp:02X}  A ${regs.get(0, 0):02X} "
              f"X ${regs.get(1, 0):02X} Y ${regs.get(2, 0):02X}")

        def mem(addr, length):
            body = struct.pack("<BHHBH", 0, addr, addr + length - 1, 0, 0)
            rid = m._send(CMD_MEM_GET, body)
            _, _, r = m._read_response(rid)
            n = struct.unpack("<H", r[:2])[0]
            return r[2:2 + n]

        stack = mem(0x0100, 0x100)
        rets = []
        i = sp + 1
        while i < 0xFF:
            rets.append((0x0100 + i, stack[i] | stack[i + 1] << 8))
            i += 2
        print("return addresses above SP (JSR pushes target-1):")
        for where, value in rets[:8]:
            print(f"  ${where:04X} -> ${value + 1:04X}")
        code = mem(max(0, pc - 0x20), 0x40)
        print(f"code ${pc - 0x20:04X}: {code.hex(' ')}")
        for spec in a.peek:
            addr, _, length = spec.partition(":")
            addr, length = int(addr, 16), int(length or "10", 16)
            blob = mem(addr, length)
            text = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in blob)
            print(f"peek ${addr:04X}: {blob.hex(' ')}  |{text}|")
        for spec in a.follow:
            addr = int(spec, 16)
            lo, hi = mem(addr, 1)[0], mem(addr + 2, 1)[0]
            target = lo | hi << 8
            blob = mem(target, 24)
            text = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in blob)
            print(f"follow ${addr:04X} -> ${target:04X}: {blob.hex(' ')}  |{text}|")
        m.command(CMD_CHECKPOINT_DELETE, struct.pack("<I", num))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

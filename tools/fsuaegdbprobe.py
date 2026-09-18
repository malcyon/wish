#!/usr/bin/env python3
"""The first, minimal GDB-remote client for the patched FS-UAE (the fork
`grahambates/fs-uae`, branch `remote_debugger_barto`), and the probe it was
written for: does a memory read return while the emulated machine runs? --
`#464 (Can the automapper follow a live FS-UAE game on Linux, so Wish and the
Amiga game run on one machine?)`.

    .venv/bin/python tools/fsuaegdbprobe.py [PORT]

PORT is the emulator's `remote_debugger_port` (default 6525). Connects, prints
what the server advertises, reads 16 bytes while the machine is halted, then
continues it and polls `VHPOSR` and a 1 KB block twelve times, printing how
long each read took. Set `RAW=1` to print the raw bytes of every reply.

`tools/fsuaegdb.py` is the shipped command line, built on `automap/amiga.py`'s
transport; this is the earlier standalone client. `tools/fsuaeprobedrive.py`
and the `fsuae*.sh` scripts import its `Gdb` class.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import time

RAW = os.environ.get('RAW') == '1'


class Gdb:
    def __init__(self, host: str = "127.0.0.1", port: int = 6525) -> None:
        self.sock = socket.create_connection((host, port), timeout=10)
        self.buf = b""

    def send(self, body: str) -> None:
        cksum = sum(body.encode()) & 0xFF
        packet = f"${body}#{cksum:02x}".encode()
        self.sock.sendall(packet)

    def recv_packet(self, timeout: float = 10.0) -> str:
        self.sock.settimeout(timeout)
        deadline = time.time() + timeout
        while True:
            # strip acks
            while self.buf[:1] in (b"+", b"-"):
                self.buf = self.buf[1:]
            if self.buf.startswith(b"$"):
                end = self.buf.find(b"#")
                if end != -1 and len(self.buf) >= end + 3:
                    body = self.buf[1:end].decode(errors="replace")
                    self.buf = self.buf[end + 3:]
                    return body
            if time.time() > deadline:
                raise TimeoutError(f"no packet; buffer={self.buf!r}")
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            if RAW:
                print(f"  raw<- {chunk[:200]!r}")
            self.buf += chunk

    def ask(self, body: str, timeout: float = 10.0) -> str:
        self.send(body)
        return self.recv_packet(timeout)

    def read_mem(self, addr: int, length: int) -> bytes:
        self.send(f"m{addr:x},{length:x}")
        while True:
            reply = self.recv_packet()
            if reply.startswith("O") and len(reply) > 1:
                continue                      # console output from the guest
            break
        if reply.startswith("E"):
            raise RuntimeError(f"read error {reply} at {addr:#x}")
        try:
            return bytes.fromhex(reply)
        except ValueError:
            raise RuntimeError(f"unexpected reply {reply[:80]!r}") from None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("port", nargs="?", type=int, default=6525)
    args = ap.parse_args(argv)
    gdb = Gdb(port=args.port)
    print("connected")

    print("qSupported ->", gdb.ask("qSupported")[:120])
    print("? ->", gdb.ask("?"))

    # read while halted, so we have a before picture
    t0 = time.perf_counter()
    before = gdb.read_mem(0x0, 16)
    print(f"halted read  {before.hex()}  "
          f"{1000 * (time.perf_counter() - t0):.1f} ms")

    gdb.send("vCont;c")
    time.sleep(0.2)
    print("continued")

    # now the machine is running.  Poll and time it.
    for i in range(12):
        t0 = time.perf_counter()
        vpos = gdb.read_mem(0xDFF004, 4)         # VPOSR/VHPOSR, moves every line
        dt = 1000 * (time.perf_counter() - t0)
        t1 = time.perf_counter()
        gdb.read_mem(0xC00000, 1024)             # a 1 KB block, the GEO size
        dt2 = 1000 * (time.perf_counter() - t1)
        print(f"poll {i:2d}  vhposr={vpos.hex()} {dt:6.1f} ms   "
              f"1KB {dt2:6.1f} ms")
        time.sleep(0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

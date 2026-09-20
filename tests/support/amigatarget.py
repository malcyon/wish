"""Helpers `test_amigatarget` shares with the test files that reuse them."""
from __future__ import annotations

import base64

from automap import amiga

SSB = amiga.MACHINES["secret-of-the-silver-blades"]


#: A believable data hunk base in the A500's slow memory.
BASE = 0xC12340


class Guest:
    """A fake Windows guest, answering exactly the shape the real one does."""

    def __init__(self, memory: dict[int, bytes] | None = None):
        self.memory = dict(memory or {})
        self.calls: list[str] = []
        #: Set to make every `S` write nothing, which is what a debugger that
        #: never opened looks like from here.
        self.silent = False

    def peek(self, addr: int, length: int) -> bytes:
        out = bytearray(length)
        for base, blob in self.memory.items():
            for i in range(length):
                if base <= addr + i < base + len(blob):
                    out[i] = blob[addr + i - base]
        return bytes(out)

    def __call__(self, argv, timeout):
        assert argv[0] == "winvm" and argv[1] == "ssh"
        script = base64.b64decode(argv[2].split()[-1]).decode("utf-16-le")
        self.calls.append(script)
        batch = self._batch(script)
        out = ["<<key>>", "ok", "<<send>>", "ok sent to pid 1234"]
        dumps = {}
        for line in batch.splitlines():
            if line.startswith("S "):
                _s, path, addr, length = line.split()
                dumps[path] = self.peek(int(addr, 16), int(length, 16))
        for name, path in self._fetched(script):
            blob = dumps.get(path)
            out.append(f"<<{name}>>")
            out.append("MISSING" if blob is None or self.silent
                       else base64.b64encode(blob).decode("ascii"))
        out.append("<<end>>")
        return "\r\n".join(out) + "\r\n"

    @staticmethod
    def _batch(script: str) -> str:
        for line in script.splitlines():
            if "wish-batch.txt" in line and "FromBase64String" in line:
                b64 = line.split("FromBase64String('")[1].split("'")[0]
                return base64.b64decode(b64).decode("ascii")
        raise AssertionError("the script wrote no batch file")

    @staticmethod
    def _fetched(script: str) -> list[tuple[str, str]]:
        out = []
        for line in script.splitlines():
            if line.startswith("Write-Output '<<") and "<<end>>" not in line:
                name = line.split("<<")[1].split(">>")[0]
                if name in ("key", "send"):
                    continue
                out.append(name)
        paths = []
        for line in script.splitlines():
            if "Test-Path -LiteralPath '" in line:
                paths.append(line.split("Test-Path -LiteralPath '")[1]
                             .split("'")[0])
        return list(zip(out, paths))


def target(memory=None, layout=SSB, base=BASE, guest=None):
    guest = guest or Guest(memory)
    debugger = amiga.WinuaeDebugger("wish37", runner=guest)
    return amiga.AmigaTarget(debugger, layout, base), guest

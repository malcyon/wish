"""`Monitor.checkpoint_hits`, the one place a checkpoint's hit count is read."""
import ast
import pathlib
import socket
import struct

from automap.vice import CMD_CHECKPOINT_GET, Monitor

ROOT = pathlib.Path(__file__).resolve().parents[2]


class Recorded(Monitor):
    def __init__(self, count):
        self.count = count
        self.sent = []

    def command(self, cmd, body=b""):
        self.sent.append((cmd, body))
        # number, hit flag, start, end, four flag bytes, hit count, ignore
        # count, memspace.
        return (struct.pack("<I", 7) + bytes([1]) + struct.pack("<HH", 0, 0)
                + bytes([1, 1, 1, 0]) + struct.pack("<II", self.count, 0)
                + bytes([0, 0]))


def test_checkpoint_hits_asks_for_the_checkpoint_and_returns_its_count():
    m = Recorded(768)
    assert m.checkpoint_hits(7) == 768
    assert m.sent == [(CMD_CHECKPOINT_GET, struct.pack("<I", 7))]


def test_checkpoint_hits_reads_by_offset_when_the_trailing_bytes_are_absent():
    m = Recorded(5)
    m.command = lambda cmd, body=b"": (
        struct.pack("<I", 7) + bytes(9) + struct.pack("<I", 5))
    assert m.checkpoint_hits(7) == 5


def test_no_module_but_the_monitor_defines_checkpoint_hits():
    found = []
    for base in ("automap", "tools", "wish", "editor", "goldbox"):
        for path in (ROOT / base).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == "checkpoint_hits" for n in ast.walk(tree)):
                found.append(path.relative_to(ROOT).as_posix())
    assert found == ["automap/vice.py"]


def test_hang_up_closes_the_socket_without_sending_exit_and_is_idempotent():
    mine, peer = socket.socketpair()
    peer.settimeout(2)
    mon = Monitor()
    mon.sock = mine
    mon.hang_up()
    assert mon.sock is None
    mon.hang_up()
    assert mon.sock is None
    assert peer.recv(16) == b""     # end of stream, with no EXIT before it
    peer.close()

"""A Curse machine made of a dictionary, and the walk from Tilverton into the sewers."""
from __future__ import annotations

from automap.area import RESIDENT_GEO
from automap.state import Automapper
from automap.target import MemoryTarget
from goldbox import c64_port

CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
LIVE_POSITION = 0xC04B
SCREEN = 0xCC00
STATUS_ROW = 14


def _codes(text: str) -> bytes:
    return bytes(ord(c) - 64 if "A" <= c <= "Z" else ord(c) for c in text)


def curse_target(status: str, triple: tuple[int, int, int],
                 geo=None) -> MemoryTarget:
    """Row 14 reading *status*, `$C04B` holding *triple*, *geo* at `$0400`."""
    screen = bytearray(1000)
    row = _codes(status.ljust(40))[:40]
    screen[STATUS_ROW * 40:STATUS_ROW * 40 + 40] = row
    memory = {0xD011: bytes([0x1B]), 0xD018: bytes([0x30]),
              0xDD00: bytes([0xFC]), SCREEN: bytes(screen),
              0xD800: bytes(1000), LIVE_POSITION: bytes(triple)}
    if geo is not None:
        memory[RESIDENT_GEO] = geo.to_bytes()
    return MemoryTarget(memory)


def walk_into_the_sewers(town, sewers, tmp_path, monkeypatch) -> Automapper:
    """Tilverton at (14,15), then the sewers' map loaded while the status line
    still reads the town's square, then the line without coordinates."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    maps = {"GEO01": town, "GEO03": sewers}
    target = curse_target("S 8:37 14,15", (14, 15, 2), town)
    mapper = Automapper(target, maps, area="GEO01", title=CURSE.title)
    for _ in range(mapper.RESIDENT_EVERY - 1):
        mapper.poll()
    # The periodic check is due on this poll; the game has moved on, the line
    # has not.
    target.memory.update(curse_target("S 8:37 14,15", (0, 0, 2), sewers).memory)
    mapper.poll()
    target.memory.update(curse_target("S 8:37", (0, 0, 2), sewers).memory)
    mapper.poll()
    mapper.poll()
    return mapper

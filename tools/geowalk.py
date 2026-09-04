#!/usr/bin/env python3
"""Walk a driven session to a square, routed on the area's own `GEO` file.

    tools/geowalk.py --port 6563 --geo GEO01 --title curse 6 12 --to 5 5

`tools/session.py`'s `walk` takes one step at a time and verifies each against
the status line, which costs about forty seconds a step: right for measuring a
map, far too slow for crossing one.  This plans the whole route first --
breadth-first over `Geo.is_passable`, so it never asks the game to walk
through a wall -- and then sends the turns and steps as one burst with `MOVE`
selected once, which the game keeps active until Return.

The party's facing decides which of `I J K M` each leg needs, so the route is
turned into keys as it is walked rather than up front.

It reads the `GEO` off the player's own disks through `tools/gamedisks.py` and
writes nothing.
"""
from __future__ import annotations

import argparse
import pathlib
import socket
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.d64 import D64, load_payload  # noqa: E402
from goldbox.geo import Geo  # noqa: E402
from tools import gamedisks  # noqa: E402

#: North, east, south, west -- the order the record, the `GEO` and the status
#: line all use.
STEP = ((0, -1), (1, 0), (0, 1), (-1, 0))


def load_geo(name: str, key: str) -> Geo:
    for base in gamedisks.candidates(key):
        for path in sorted(pathlib.Path(base).glob("*.[dD]64")):
            try:
                disk = D64.open(path)
            except Exception:
                continue
            if any(e.name == name.encode() for e in disk.directory()):
                return Geo(load_payload(disk, name.encode()))
    raise SystemExit(f"no disk under {key} carries {name}")


def route(geo: Geo, start, goal) -> list[tuple[int, int]] | None:
    """The shortest legal walk from `start` to `goal`, or None."""
    seen = {start: None}
    frontier = [start]
    while frontier:
        nxt = []
        for square in frontier:
            if square == goal:
                path, cur = [], square
                while cur is not None:
                    path.append(cur)
                    cur = seen[cur]
                return list(reversed(path))
            x, y = square
            for facing, (dx, dy) in enumerate(STEP):
                if not geo.is_passable(x, y, facing):
                    continue
                step = (x + dx, y + dy)
                if not 0 <= step[0] < 16 or not 0 <= step[1] < 16:
                    continue
                if step in seen:
                    continue
                seen[step] = square
                nxt.append(step)
        frontier = nxt
    return None


def keys_for(path, facing: int) -> list[str]:
    """`I J K M` for a route, given the facing it starts from."""
    out: list[str] = []
    for here, there in zip(path, path[1:]):
        want = STEP.index((there[0] - here[0], there[1] - here[1]))
        turn = (want - facing) % 4
        out += {0: [], 1: ["k"], 2: ["m"], 3: ["j"]}[turn]
        # `M` is about-turn *and step* in this engine, so a reversal is one key.
        if turn != 2:
            out.append("i")
        facing = want
    return out


def send(port: int, line: str, timeout: float = 60.0) -> str:
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    sock.settimeout(timeout)
    sock.sendall((line + "\n").encode())
    out = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        out += chunk
    return out.decode("latin1")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, required=True, help="session command port")
    ap.add_argument("--geo", required=True)
    ap.add_argument("--key", default="curse-of-the-azure-bonds",
                    help="which game's disks, as gamedisks.toml names it")
    ap.add_argument("--facing", type=int, default=None,
                    help="0 north, 1 east, 2 south, 3 west; read from the "
                         "session when left out")
    ap.add_argument("from_x", type=int)
    ap.add_argument("from_y", type=int)
    ap.add_argument("--to", nargs=2, type=int, required=True, metavar=("X", "Y"))
    ap.add_argument("--pause", type=float, default=2.2)
    a = ap.parse_args(argv)

    geo = load_geo(a.geo, a.key)
    start, goal = (a.from_x, a.from_y), tuple(a.to)
    path = route(geo, start, goal)
    if path is None:
        print(f"no walk from {start} to {goal} in {a.geo}")
        return 1
    facing = a.facing
    if facing is None:
        answer = send(a.port, "pos")
        facing = int(answer.strip().strip("()").split(",")[2])
    keys = keys_for(path, facing)
    print(f"{len(path) - 1} steps, {len(keys)} keys: {''.join(keys)}")
    # A square with a script on it interrupts the walk: the game draws its
    # text and `PRESS BUTTON OR RETURN TO CONTINUE.`, which swallows every
    # movement key until it is answered.  So the bar is read after each step
    # and the walk resumes rather than sending the rest into a message box.
    def in_move() -> bool:
        return "I,J,K,M" in send(a.port, "screen")

    def resume() -> None:
        for _ in range(6):
            if in_move():
                return
            send(a.port, "key Return")
            time.sleep(1.2)
            if in_move():
                return
            send(a.port, "bar MOVE")
            time.sleep(1.0)

    resume()
    for key in keys:
        send(a.port, f"key {key}")
        time.sleep(a.pause)
        if not in_move():
            resume()
    print(send(a.port, "pos").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

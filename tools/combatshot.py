#!/usr/bin/env python3
"""Photograph the automapper's combat canvas, and print what it was drawn from.

A picture of a fight and the bytes behind it, side by side, because looking at
either alone has misled this project twice: a canvas that draws nothing and a
machine with no fight running make the same PNG, and an effect table read
without the picture says nothing about what a player is shown.

    tools/combatshot.py --port 6521 work/fight.png     a fight in progress
    tools/combatshot.py --synthetic work/arena.png     no emulator at all

So it prints all four effect arrays raw, the effects that are running, the
indices the reader calls helpless, and every combatant with its position and
hit points -- and then draws the canvas offscreen and prints **every
combatant's tooltip**, which a `grab()` does not paint.

`--synthetic` builds `tests/gamedata`'s arena instead of reading a machine, so
the drawing half can be looked at with nothing booted; `--helpless N` marks a
combatant helpless in that made-up memory, which is the only way to see the
badge at all, since no save this project holds carries one.

This connects, reads and closes, so it runs beside an idle
`tools/session.py` -- but never beside `wish` or anything else holding the
binary monitor open. It writes nothing to the machine, and the PNG goes under
`work/`, which is gitignored: a picture of a fight is the game's own art.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / "tests"))

# Importing this is what forces the process offscreen and gives it a throwaway
# config directory: both run at its import time, and they have to happen
# before Qt is imported at all.
import shotwindow  # noqa: E402,F401  (imported for that alone)
from PyQt6.QtWidgets import QApplication  # noqa: E402

from automap import combat, live  # noqa: E402
from automap.target import MemoryTarget, ViceTarget  # noqa: E402
from automap.window import CombatCanvas  # noqa: E402


def from_machine(port: int, host: str = "127.0.0.1"):
    """The head of save 0 and the battle, from a running emulator."""
    target = ViceTarget(host=host, port=port)
    try:
        head = target.read(combat.SAVE_HEAD, combat.SAVE_HEAD_LEN)
        return head, combat.read_battle(target)
    finally:
        target.close()


def from_arena(helpless: list[int]):
    """The same pair, from the arena `tests/gamedata` builds."""
    from gamedata import synthetic_arena

    target = MemoryTarget(synthetic_arena())
    if helpless:
        ids = bytearray(live.EFFECT_SLOTS)
        owners = bytearray(live.EFFECT_SLOTS)
        for slot, index in enumerate(helpless[:live.EFFECT_SLOTS]):
            ids[slot], owners[slot] = combat.HELPLESS, index
        target.memory[combat.SAVE_HEAD + live.EFFECT_ID_OFFSET] = bytes(ids)
        target.memory[combat.SAVE_HEAD + live.EFFECT_OWNER_OFFSET] = \
            bytes(owners)
    head = target.read(combat.SAVE_HEAD, combat.SAVE_HEAD_LEN)
    return head, combat.read_battle(target)


def say_effects(head: bytes) -> None:
    for label, offset in (("id ", live.EFFECT_ID_OFFSET),
                          ("own", live.EFFECT_OWNER_OFFSET),
                          ("dur", live.EFFECT_DURATION_OFFSET),
                          ("mag", live.EFFECT_MAGNITUDE_OFFSET)):
        block = head[offset:offset + live.EFFECT_SLOTS]
        print(f"    {label} ${combat.SAVE_HEAD + offset:04X}: "
              f"{block.hex(' ')}")
    running = live.active_effects(head)
    for effect in running:
        print(f"    Slot {effect.slot:2d}  id {effect.id:3d}  owner "
              f"{effect.owner:3d}  duration ${effect.duration:02X}  "
              f"magnitude {effect.magnitude}")
    if not running:
        print("    No effect is running at all.")
    print(f"    Helpless: {sorted(combat.helpless_indices(head)) or 'nobody'}")


def draw(app, battle, out: pathlib.Path) -> None:
    canvas = CombatCanvas()
    canvas.show_battle(battle)
    canvas.resize(canvas.sizeHint())
    app.processEvents()
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.grab().save(str(out))
    print(f"Wrote {out}  ({canvas.width()}x{canvas.height()})")
    cell = canvas.drawn_cell
    x0, y0, _, _ = canvas.box
    for who in battle.combatants:
        tip = canvas.tooltip_at(combat.MARGIN + (who.x - x0) * cell + cell / 2,
                                combat.MARGIN + (who.y - y0) * cell + cell / 2)
        print(f"    ({who.x:2d},{who.y:2d}) index {who.index:2d}: "
              + " / ".join((tip or "(no tooltip)").splitlines()))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Draw the combat canvas and print what it was drawn "
                    "from.")
    ap.add_argument("out", nargs="?", default="work/combatshot.png",
                    help="where to write the PNG (default: %(default)s, "
                         "which is gitignored)")
    ap.add_argument("--port", type=int, default=6502, metavar="N",
                    help="the binary monitor to read (default: %(default)s, "
                         "the human's; a pool slot prints its own)")
    ap.add_argument("--synthetic", action="store_true",
                    help="build tests/gamedata's arena instead of reading a "
                         "machine")
    ap.add_argument("--helpless", type=int, action="append", default=[],
                    metavar="INDEX",
                    help="with --synthetic, mark this combatant helpless; "
                         "give it more than once for more of them")
    args = ap.parse_args(argv[1:])

    if args.helpless and not args.synthetic:
        print("--helpless writes an effect table, so it only makes sense "
              "with --synthetic. This tool never writes to a machine.",
              file=sys.stderr)
        return 2

    if args.synthetic:
        head, battle = from_arena(args.helpless)
        print("The arena tests/gamedata builds, with no emulator:")
    else:
        head, battle = from_machine(args.port)
        print(f"The machine on port {args.port}:")
    say_effects(head)

    if battle is None:
        print("Nothing is fighting: the machine is not in combat, or the "
              "combat overlay is not resident.")
        return 1
    print(f"    Battlefield {battle.shape.width}x{battle.shape.height}")
    for who in battle.combatants:
        print(f"    {who.index:2d} {who.kind:12s} ({who.x:2d},{who.y:2d})  "
              f"initiative {who.initiative:3d}  hp {who.hp_text:9s} "
              f"{who.name}")

    app = QApplication.instance() or QApplication(["combatshot"])
    draw(app, battle, pathlib.Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

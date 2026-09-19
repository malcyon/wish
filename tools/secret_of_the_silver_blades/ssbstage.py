#!/usr/bin/env python3
"""Stage a Silver Blades save with `$4C2D` set, for a repeatable wandering fight.

`#334 (The session driver cannot fight in Curse or Silver Blades, and says the
party is not in a fight while it is standing on the combat floor)`. The
issue's own reverse-engineering read of `ECL10`'s wandering-encounter check
found the roll that starts a fight gated on one byte:

    COMPARE [$4C2D], #1
    IF=
    GOTO $861E              -- SETUPMON, a message, one acknowledgement, COMBAT

`$4C2D` is `SAVEDBASH`'s load address `$4B00` plus file offset `$12D`, and it
is 0 on every specimen driven so far -- which is why `#334`'s wandering walks
(598 steps in one run) never met anything. Set to 1, the roll succeeds about
15 times in 100 once the step counter reaches 10, which is roughly one fight
every seventeen steps: repeatable, and a state the game itself sets
(`ECL10` entry 4, `+$00BB`) rather than an invented value.

    tools/secret_of_the_silver_blades/ssbstage.py ~/wish-specimens/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64 \
        STAGED.D64

The output is a plain copy with that one byte changed; nothing else in the
save is touched, and the input is opened read only.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from goldbox.c64_save import SECRET_OF_THE_SILVER_BLADES as GAME  # noqa: E402
from goldbox.d64 import D64, attach_load_address, split_load_address  # noqa: E402

#: `$4C2D` minus `SAVEDBASH`'s load address `$4B00`.
WANDER_GATE_OFFSET = 0x4C2D - GAME.save_load_address


def stage(base: str, out: str, value: int = 1) -> dict:
    image = D64.open(base)
    load, body = split_load_address(image.read_file(GAME.save_file))
    body = bytearray(body)
    before = body[WANDER_GATE_OFFSET]
    body[WANDER_GATE_OFFSET] = value
    image.write_file_inplace(GAME.save_file,
                             attach_load_address(load, bytes(body)))
    dest = pathlib.Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(image.to_bytes())
    dest.chmod(0o644)
    return {"base": base, "out": out, "load": hex(load),
            "offset": hex(WANDER_GATE_OFFSET), "before": before,
            "after": value}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("base", help="the specimen to copy (read only)")
    p.add_argument("out", help="where to write the staged copy")
    p.add_argument("--value", type=int, default=1,
                   help="what to put at $4C2D (default 1, the game's own "
                        "'wandering encounters can fight' state)")
    args = p.parse_args(argv)
    print(stage(args.base, args.out, args.value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Where the C64 Curse and Silver Blades engines keep a paladin's cure-disease uses.

Everything is read from the player's own overlays, each address found by the
instruction pattern that does the work, so the answer is re-derived rather
than remembered:

* the **counter** is character-record byte `0x012` (`$7C12`), and lay on
  hands' is `0x013` (`$7C13`) -- both inside the 20 bytes `goldbox/layout.py`
  calls `name`;
* `GEN` **seeds** them from the paladin level `0x0CF`: `0x013` = 1 and `0x012`
  = 1, 2 or 3 below 6, below 11 and from 11 up, and both 0 for a character with
  no paladin level; four callers, and training is not one of them;
* `LIBRARY`'s sheet-menu mask **hides** CURE while `0x012` is 0 and HEAL while
  `0x013` is 0;
* `ECL65`'s cure **decrements** `0x012` and starts a **timer effect** in the
  save's effect arrays -- Curse id 141 when the uses were full before the
  cure, Silver Blades id 110 when the paladin has none -- with duration `$C7`
  (seven days) and a magnitude with bit 7 set, so the camp's expiry runs its
  handler;
* at expiry the camp's id table sends the timer to a **reset** that writes the
  full count back into `0x012`.

So the whole state is in the save: two record bytes and up to two rows of the
effect arrays. Pool of Radiance has no paladin, and `pool` says so from its
disks.

    tools/c64/curedisease.py                 # both later titles, and Pool
    tools/c64/curedisease.py --title curse-of-the-azure-bonds
    tools/c64/curedisease.py records SAVE.D64 ...   # the two bytes per paladin

Nothing here writes, and nothing it prints is committed.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import c64_port  # noqa: E402
from tools.c64 import coldread  # noqa: E402

#: Where `LINKER` and the camp put each overlay this reads.
BASES = {"GEN": 0x0800, "CAMP": 0x0800, "ECL65": 0x8000, "LIBRARY": 0x2DC8}

#: The character record the later titles stage at `$7C00`.
RECORD = 0x7C00
CURES = 0x012          # cure-disease uses left
LAY_ON_HANDS = 0x013   # lay-on-hands uses left
PALADIN_LEVEL = 0x0CF  # the paladin slot of the per-class level array

#: The later titles' four effect arrays: id, owner, duration, magnitude.
EFFECT_ID, EFFECT_OWNER, EFFECT_DURATION, EFFECT_MAGNITUDE = (
    0x4B00, 0x4B40, 0x4B80, 0x4D80)

LATER = (c64_port.CURSE_OF_THE_AZURE_BONDS,
         c64_port.SECRET_OF_THE_SILVER_BLADES)
TITLES = {game.key: game for game in LATER}

_ = None   # a wildcard in a pattern


def _lo(address: int) -> int:
    return address & 0xFF


def _hi(address: int) -> int:
    return address >> 8


def _all(body: bytes, pattern: tuple) -> list[int]:
    first = pattern[0]
    out, at = [], body.find(bytes([first])) if first is not None else 0
    while 0 <= at <= len(body) - len(pattern):
        if all(want is None or body[at + i] == want
               for i, want in enumerate(pattern)):
            out.append(at)
        at = (body.find(bytes([first]), at + 1) if first is not None
              else at + 1)
    return out


def _one(body: bytes, pattern: tuple, what: str) -> int:
    hits = _all(body, pattern)
    if len(hits) != 1:
        raise ValueError(f"{what}: expected one match, found {len(hits)}")
    return hits[0]


def _word(body: bytes, at: int) -> int:
    return body[at] | body[at + 1] << 8


# --- the patterns -----------------------------------------------------------

#: `GEN`: `LDA $7CCF / BEQ / LDY #1 / STY $7C13 / CMP #t1 / BCC / INY /
#: CMP #t2 / BCC / INY / STY $7C12 / RTS` and, for no paladin level,
#: `STA $7C12 / STA $7C13 / RTS`.
SEED = (0xAD, PALADIN_LEVEL, 0x7C, 0xF0, 0x13, 0xA0, 0x01,
        0x8C, LAY_ON_HANDS, 0x7C, 0xC9, _, 0x90, 0x06, 0xC8, 0xC9, _,
        0x90, 0x01, 0xC8, 0x8C, CURES, 0x7C, 0x60,
        0x8D, CURES, 0x7C, 0x8D, LAY_ON_HANDS, 0x7C, 0x60)

#: `ECL65`: the full count into Y, the same thresholds tested high first.
FULL = (0xAD, PALADIN_LEVEL, 0x7C, 0xA0, 0x01, 0xC9, _, 0x90, 0x01, 0xC8,
        0xC9, _, 0x90, 0x01, 0xC8, 0x60)

#: `LIBRARY`: `LDX $7C12 / BNE / AND #m1 / LDX $7C13 / BNE / AND #m2`.
GATE = (0xAE, CURES, 0x7C, 0xD0, 0x02, 0x29, _,
        0xAE, LAY_ON_HANDS, 0x7C, 0xD0, 0x02, 0x29, _)

#: `ECL65`: `LDA #id / STA idvar / LDA #dur / STA durvar / STA magvar /
#: STA flagvar / JSR add`, the timer a use starts.
TIMER = (0xA9, _, 0x8D, _, _, 0xA9, _, 0x8D, _, _, 0x8D, _, _, 0x8D, _, _,
         0x20, _, _)

#: `CAMP`: the expiry takes the id, clears it, and skips the handler unless
#: the magnitude's bit 7 is set: `LDA $4B00,X / STA / LDA #0 / STA $4B00,X /
#: LDA $4D80,X / BPL`.
EXPIRY = (0xBD, _lo(EFFECT_ID), _hi(EFFECT_ID), 0x8D, _, _, 0xA9, 0x00,
          0x9D, _lo(EFFECT_ID), _hi(EFFECT_ID),
          0xBD, _lo(EFFECT_MAGNITUDE), _hi(EFFECT_MAGNITUDE), 0x10)

#: `CAMP`: the id-table walk that picks the expiry handler:
#: `LDX #0 / LDA ids,X / BEQ / CMP id / BEQ +3 / INX / BNE / LDA lo,X / STA /
#: LDA hi,X`.
DISPATCH = (0xA2, 0x00, 0xBD, _, _, 0xF0, _, 0xCD, _, _, 0xF0, 0x03, 0xE8,
            0xD0, 0xF3, 0xBD, _, _, 0x8D, _, _, 0xBD, _, _)

#: The sheet menu `LIBRARY` masks, in bit order.
MENU_HEAD = b"ITEMS\x00SPELLS\x00"

#: Absolute-mode opcodes that write a byte.
WRITES = {0x8D: "STA", 0x8E: "STX", 0x8C: "STY", 0xCE: "DEC", 0xEE: "INC"}


@dataclasses.dataclass(frozen=True)
class Timer:
    """One use's timer: where it is started and what row it writes."""

    decrement: int          # `DEC $7C12` or `DEC $7C13`
    setup: int              # the `LDA #id` of :data:`TIMER`
    effect_id: int
    duration: int           # the duration byte, count and unit
    magnitude: int          # the byte the add routine stores at `$4D80`
    add: int                # the routine that writes the four arrays
    reset: int              # the camp expiry handler for this id


def _timer(ecl: bytes, base: int, counter: int, what: str) -> Timer:
    dec = _one(ecl, (0xCE, counter, 0x7C), f"{what} decrement")
    window = ecl[max(0, dec - 0x30):dec]
    found = _all(window, TIMER)
    if len(found) != 1:
        raise ValueError(f"{what}: expected one timer set-up before the "
                         f"decrement at ${dec + base:04X}, found {len(found)}")
    at = found[0] + max(0, dec - 0x30)
    effect_id, duration = ecl[at + 1], ecl[at + 6]
    id_var, dur_var, mag_var = (_word(ecl, at + 3), _word(ecl, at + 8),
                                _word(ecl, at + 11))
    add = _word(ecl, at + 17)
    # The add routine must store exactly those variables into the arrays.
    body = ecl[add - base:add - base + 0x30]
    for var, array in ((id_var, EFFECT_ID), (dur_var, EFFECT_DURATION),
                       (mag_var, None)):
        load = bytes([0xAD, _lo(var), _hi(var)])
        if load not in body:
            raise ValueError(f"{what}: the add routine at ${add:04X} never "
                             f"loads ${var:04X}")
        if array is not None and (load + bytes([0x9D, _lo(array), _hi(array)])
                                  not in body):
            raise ValueError(f"{what}: ${var:04X} does not go to "
                             f"${array:04X} in ${add:04X}")
    mag_store = bytes([0xAD, _lo(mag_var), _hi(mag_var), 0xD0, 0x03])
    k = body.find(mag_store)
    if k < 0 or body[k + 8:k + 11] != bytes(
            [0x9D, _lo(EFFECT_MAGNITUDE), _hi(EFFECT_MAGNITUDE)]):
        raise ValueError(f"{what}: ${mag_var:04X} does not reach the "
                         f"magnitude array in ${add:04X}")
    return Timer(dec + base, at + base, effect_id, duration, duration,
                 add, 0)


def _guard(ecl: bytes, base: int, timer: Timer, full: int) -> str:
    """Which condition starts the cure timer.

    Curse compares the uses with the full count (`JSR full / CPY $7C12 /
    BNE past`), so only a cure from full starts it; Silver Blades asks
    whether the paladin already has the timer id and skips when he does.
    """
    window = ecl[timer.setup - base - 0x18:timer.setup - base]
    at_full = bytes([0x20, _lo(full), _hi(full), 0xCC, CURES, 0x7C, 0xD0])
    if at_full in window:
        return "uses were full"
    absent = (0xA9, timer.effect_id, 0x20, _, _, 0xB0)
    if _all(window, absent):
        return "no timer running"
    raise ValueError(f"no recognised guard before ${timer.setup:04X}")


def _dispatch(camp: bytes, ecl: bytes) -> tuple[int, int, dict[int, int]]:
    """`(the CAMP walk, the id table, id -> handler)` for the camp's expiry."""
    at = _one(camp, DISPATCH, "expiry dispatch")
    ids, lo, hi = (_word(camp, at + 3), _word(camp, at + 16),
                   _word(camp, at + 22))
    base = BASES["ECL65"]
    table: dict[int, int] = {}
    i = 0
    while ecl[ids - base + i]:
        table[ecl[ids - base + i]] = (ecl[lo - base + i]
                                      | ecl[hi - base + i] << 8)
        i += 1
    return at + BASES["CAMP"], ids, table


def _menu(library: bytes) -> tuple[str, ...]:
    at = library.find(MENU_HEAD)
    if at < 0:
        return ()
    words = []
    while True:
        end = library.index(b"\x00", at)
        word = library[at:end].decode("latin1")
        words.append(word)
        if word == "EXIT" or len(words) > 10:
            return tuple(words)
        at = end + 1


def _writes(files: dict[str, bytes]) -> tuple[tuple[str, int, str, int], ...]:
    """Every absolute write to `$7C12` or `$7C13` in the four overlays read.

    The byte census over every file on the sides also turns up art files
    (`PIC`, `WALLDEF`, `COMPIC`) whose bytes happen to spell the operand, and
    `GEN`'s trait-seed table, which is data; those are not code, so the census
    that is kept is over the overlays whose routines this reads.
    """
    out = []
    for name in ("GEN", "LIBRARY", "ECL65", "CAMP"):
        body, base = files[name], BASES[name]
        for offset in (CURES, LAY_ON_HANDS):
            for opcode, mnemonic in WRITES.items():
                for at in _all(body, (opcode, offset, 0x7C)):
                    out.append((name, at + base, mnemonic, offset))
    return tuple(sorted(out))


def inspect(files: dict[str, bytes]) -> dict:
    """Every reading, as addresses and values, from one later title's files."""
    gen, library, ecl, camp = (files["GEN"], files["LIBRARY"],
                               files["ECL65"], files["CAMP"])
    b_gen, b_lib, b_ecl = BASES["GEN"], BASES["LIBRARY"], BASES["ECL65"]

    seed = _one(gen, SEED, "GEN seed")
    thresholds = (gen[seed + 11], gen[seed + 16])
    seed_address = seed + b_gen
    callers = tuple(at + b_gen for at in
                    _all(gen, (0x20, _lo(seed_address), _hi(seed_address))))

    full = _one(ecl, FULL, "full count")
    full_address = full + b_ecl
    full_thresholds = (ecl[full + 11], ecl[full + 6])
    if full_thresholds != thresholds:
        raise ValueError(f"the camp's full count tests {full_thresholds}, "
                         f"GEN's seed {thresholds}")

    gate = _one(library, GATE, "sheet-menu gate")
    menu = _menu(library)
    masks = (library[gate + 6], library[gate + 13])
    gated = tuple(menu[(~m & 0xFF).bit_length() - 1] for m in masks)

    cure = _timer(ecl, b_ecl, CURES, "cure disease")
    lay = _timer(ecl, b_ecl, LAY_ON_HANDS, "lay on hands")
    guard = _guard(ecl, b_ecl, cure, full_address)

    cure_reset = _one(ecl, (0x20, _lo(full_address), _hi(full_address),
                            0x8C, CURES, 0x7C), "cure reset") + b_ecl
    lay_reset = _one(ecl, (0xA9, 0x01, 0x8D, LAY_ON_HANDS, 0x7C),
                     "lay-on-hands reset") + b_ecl
    walk, ids, handlers = _dispatch(camp, ecl)
    if handlers.get(cure.effect_id) != cure_reset:
        raise ValueError(f"expiry of {cure.effect_id} goes to "
                         f"{handlers.get(cure.effect_id)}, not the reset")
    if handlers.get(lay.effect_id) != lay_reset:
        raise ValueError(f"expiry of {lay.effect_id} goes to "
                         f"{handlers.get(lay.effect_id)}, not the reset")
    expiry = _one(camp, EXPIRY, "camp expiry") + BASES["CAMP"]

    return {
        "counter": CURES,
        "lay_on_hands": LAY_ON_HANDS,
        "seed": seed_address,
        "thresholds": thresholds,
        "seed_callers": callers,
        "full_count": full_address,
        "gate": gate + b_lib,
        "menu": menu,
        "gated": gated,
        "cure_decrement": cure.decrement,
        "cure_timer": dataclasses.replace(cure, reset=cure_reset),
        "cure_guard": guard,
        "lay_decrement": lay.decrement,
        "lay_timer": dataclasses.replace(lay, reset=lay_reset),
        "expiry_dispatch": walk,
        "expiry_ids": ids,
        "expiry_handlers": handlers,
        "expiry_magnitude_gate": expiry + len(EXPIRY) - 1,
        "writes": _writes(files),
    }


def inspect_title(key: str, root: str | None = None) -> dict:
    """Read one later title's disks, or raise `SystemExit` without them."""
    files = coldread.every_file(TITLES[key], root)
    return inspect(files)


def pool(root: str | None = None) -> dict:
    """What Pool of Radiance's own disks say about paladins: nothing.

    Every file on every side is searched for the class name, and `LIBRARY`'s
    sheet menu is read for a CURE entry.
    """
    files = coldread.every_file(c64_port.POOL_OF_RADIANCE, root)
    return {"files": len(files),
            "naming_paladin": tuple(sorted(n for n, b in files.items()
                                           if b"PALADIN" in b)),
            "menu_has_cure": b"CURE\x00" in files.get("LIBRARY", b"")}


def full_count(level: int, thresholds: tuple[int, int] = (6, 11)) -> int:
    """What `GEN` seeds and the camp's reset restores for a paladin level."""
    if level <= 0:
        return 0
    return 1 + (level >= thresholds[0]) + (level >= thresholds[1])


def records(paths: list[str]) -> list[str]:
    """One line per character with a paladin level, from each save given."""
    from goldbox.d64 import D64
    from goldbox.savegame import load_save
    out = []
    for path in paths:
        try:
            game, sg0, _ = load_save(D64.from_bytes(
                pathlib.Path(path).read_bytes()))
        except Exception as exc:
            out.append(f"{path}: {exc}")
            continue
        payload = sg0.to_bytes()
        for slot in sg0.characters:
            raw = bytes(slot.record.to_bytes())
            level = raw[PALADIN_LEVEL]
            if not level:
                continue
            rows = [(payload[i], payload[EFFECT_DURATION - EFFECT_ID + i])
                    for i in range(0x40)
                    if payload[i] and payload[EFFECT_OWNER - EFFECT_ID + i]
                    == slot.index]
            out.append(f"{pathlib.Path(path).name} slot {slot.index} "
                       f"paladin {level}: cures {raw[CURES]} (full "
                       f"{full_count(level)}), lay on hands "
                       f"{raw[LAY_ON_HANDS]}, effect rows {rows}")
    return out


def _print(key: str, f: dict) -> None:
    print(TITLES[key].title)
    print(f"  Counter     record 0x{f['counter']:03X} (cures), "
          f"0x{f['lay_on_hands']:03X} (lay on hands)")
    t1, t2 = f["thresholds"]
    print(f"  Seed        GEN ${f['seed']:04X}: 1, 2, 3 at paladin level "
          f"<{t1}, <{t2}, >={t2}; 0 with no paladin level; called from "
          + ", ".join(f"${c:04X}" for c in f["seed_callers"]))
    print(f"  Gate        LIBRARY ${f['gate']:04X} hides "
          f"{' and '.join(f['gated'])} in {' '.join(f['menu'])}")
    for label, key_ in (("Cure", "cure_timer"), ("Lay on hands", "lay_timer")):
        t = f[key_]
        print(f"  {label:<11} ECL65 DEC at ${t.decrement:04X}; timer id "
              f"{t.effect_id}, duration ${t.duration:02X}, magnitude "
              f"${t.magnitude:02X}, added by ${t.add:04X}; reset at expiry "
              f"${t.reset:04X}")
    print(f"  Cure timer  started when {f['cure_guard']}")
    print(f"  Expiry      CAMP ${f['expiry_dispatch']:04X} walks the ids at "
          f"${f['expiry_ids']:04X}; handler only when magnitude bit 7 "
          f"(BPL at ${f['expiry_magnitude_gate']:04X})")
    print("  Writes      " + ", ".join(f"{n} ${a:04X} {m} ${RECORD + o:04X}"
                                      for n, a, m, o in f["writes"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", nargs="?", default="engine",
                        choices=("engine", "records"))
    parser.add_argument("paths", nargs="*", help="save disks, for `records`")
    parser.add_argument("--title", choices=sorted(TITLES), action="append")
    parser.add_argument("--disks", help="one title's disk directory")
    args = parser.parse_args(argv)
    if args.mode == "records":
        print("\n".join(records(args.paths)))
        return 0
    keys = args.title or list(TITLES)
    if args.disks and len(keys) != 1:
        parser.error("--disks needs exactly one --title")
    for key in keys:
        try:
            _print(key, inspect_title(key, args.disks))
        except (OSError, SystemExit, ValueError) as exc:
            print(f"{key}: {exc}")
    if not args.title:
        try:
            p = pool()
            print(f"{c64_port.POOL_OF_RADIANCE.title}\n  {p['files']} files, "
                  f"{len(p['naming_paladin'])} naming PALADIN, sheet CURE "
                  f"{'present' if p['menu_has_cure'] else 'absent'}")
        except (OSError, SystemExit) as exc:
            print(f"pool-of-radiance: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

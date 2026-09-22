#!/usr/bin/env python3
"""Read Pools of Darkness' level tables out of its DOS engine.

    tools/dos/dospodlevels.py tables
    tools/dos/dospodlevels.py check

`tables` prints every per-class table `goldbox/levels.py` carries for this
title, each found through the instruction that indexes it rather than by a
committed address: the experience thresholds and the per-level increment
past level 11, the THAC0 rows the recompute reads, the saving-throw rows,
when a fighter, paladin or ranger gains attacks, the hit dice, and the
constitution hit-point bonus.

`check` recomputes THAC0 (record `0xAC`), the five saves (`0x132`) and
`attack_forms` (`0x168`) for every 510-byte `.SAV` under the Pools of
Darkness install by the engine's own rules over those tables, and counts the
records that agree with what they store. Those records were found in the
archives, not watched being written, so agreement checks this reader's
strides, clamps and dual-class rule; the tables' authority is the code.

The game is read through `tools/dos/dospodtables.py`'s `load`, which finds it
in the registry's archives; `--path` takes the game directory instead.
Prints offsets and numbers; the game's bytes stay in the player's directory.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from tools.dos import dospodtables  # noqa: E402

#: The DOS engine's class numbers, the index every table below takes. The
#: loops close on 6 (`cmp byte ptr [bp-1], 6 / je`), so there is no monk.
CLASSES = ("cleric", "druid", "fighter", "paladin", "ranger", "magic-user",
           "thief")

#: The record's seven-byte current and former class-level arrays.
CLASS_LEVELS = 0x151
FORMER_LEVELS = 0x158


def _one(pattern: bytes, blob: bytes, what: str) -> re.Match:
    found = list(re.finditer(pattern, blob, re.S))
    if len(found) != 1:
        raise LookupError(f"{what}: {len(found)} matches, expected one")
    return found[0]


def _u16(raw: bytes) -> int:
    return struct.unpack("<H", raw)[0]


# --- experience --------------------------------------------------------------
# `GAME.OVR:0x039349`, threshold(class, level): 0x7FFFFFFF from level 41,
# the class's own dword below 12, and past that entry 11 plus a per-class
# increment for every level above 11 (`sub ax, 0xb` then the longint multiply).
_XP = (rb"\x80\x7e\x08(.)\x73.\x80\x7e\x08(.)\x73."
       rb".{0,16}?\xba(..)\xf7\xe2\x8b\xf8\x03\xf9\x8b\x85(..)\x8b\x95.."
       rb".{0,20}?\x8b\x8d(..)\x8b\x9d..\x8a\x46\x08\x30\xe4\x2d(.)\x00"
       rb".{0,20}?\xba..\xf7\xe2\x8b\xf8\x8b\x85(..)")


def experience(ovr: bytes, image: bytes, ds: int) -> dict:
    """Every class's thresholds, level 2 up to the last one the routine
    answers, with where each part was read."""
    m = _one(_XP, ovr, "experience routine")
    beyond, table_below = m.group(1)[0], m.group(2)[0]
    stride, table, inc = _u16(m.group(3)), _u16(m.group(4)), _u16(m.group(5))
    past, last_entry = m.group(6)[0], _u16(m.group(7))
    seg = image[ds * 16:]
    rows = {}
    for number, name in enumerate(CLASSES):
        base = table + number * stride
        step = struct.unpack_from("<I", seg, inc + 4 * number)[0]
        top = struct.unpack_from("<I", seg, last_entry + number * stride)[0]
        out = {}
        for level in range(2, beyond):
            if level < table_below:
                out[level] = struct.unpack_from("<I", seg, base + 4 * level)[0]
            else:
                out[level] = top + step * (level - past)
        rows[name] = out
    return {"site": m.start(), "table": table, "stride": stride,
            "increment": inc, "entry_past": past, "direct_below": table_below,
            "unreachable_from": beyond, "rows": rows}


# --- THAC0 and attacks -------------------------------------------------------
# `GAME.OVR:0x03836D`: zero `0xAC`, then for every class slot take the level
# from `0x0392EE`, clamp it at 21, read `[class * 22 + level]` and keep the
# larger byte (the record stores 60 - THAC0). The same loop writes
# `attack_forms` at `0x168` for the fighter, paladin and ranger.
_THAC0 = (rb"\x80\x7e\xfc(.)\x76\x06\xc6\x46\xfd(.).{0,20}?"
          rb"\xba(.)\x00\xf7\xe2\x8b\xf8\x03\xf9\x8a\x85(..)"
          rb"\xc4\x7e\x06\x26\x3a\x85(..)")
_ATTACKS = (rb"\x3c(.)\x74\x04\x3c(.)\x75.\x80\x7e\xfc(.)\x76\x09"
            rb"\xc4\x7e\x06\x26\xc6\x85(..)(.)\x80\x7e\xfc(.)\x76\x09"
            rb"\xc4\x7e\x06\x26\xc6\x85..(.)\xeb.\x3c(.)\x75."
            rb"\x80\x7e\xfc(.)\x76\x09\xc4\x7e\x06\x26\xc6\x85..(.)"
            rb"\x80\x7e\xfc(.)\x76\x09\xc4\x7e\x06\x26\xc6\x85..(.)")


def thac0(ovr: bytes, image: bytes, ds: int) -> dict:
    """The stored byte (60 - THAC0) a class reaches at levels 0 to the clamp."""
    m = _one(_THAC0, ovr, "THAC0 recompute")
    clamp, stride, table = m.group(2)[0], m.group(3)[0], _u16(m.group(4))
    seg = image[ds * 16:]
    rows = {name: tuple(seg[table + n * stride:table + n * stride + clamp + 1])
            for n, name in enumerate(CLASSES)}
    return {"site": m.start(), "table": table, "stride": stride,
            "clamp": clamp, "record": _u16(m.group(5)), "rows": rows}


def attacks(ovr: bytes) -> dict:
    """`{class: ((above level, doubled attacks), ...)}` and the record offset."""
    site = _one(_THAC0, ovr, "THAC0 recompute").start()
    m = re.search(_ATTACKS, ovr[site:site + 0x100], re.S)
    if m is None:
        raise LookupError("attack bands: not found after the THAC0 loop")
    g = [x[0] if len(x) == 1 else _u16(x) for x in m.groups()]
    first = ((g[2], g[4]), (g[5], g[6]))
    ranger = ((g[8], g[9]), (g[10], g[11]))
    return {"record": g[3],
            "bands": {CLASSES[g[0]]: first, CLASSES[g[1]]: first,
                      CLASSES[g[7]]: ranger}}


# --- saving throws -----------------------------------------------------------
# `GAME.OVR:0x0387B0`: every column starts at 20, then for every class with a
# level above zero (the level clamped at 21) the row byte at
# `[class * 105 + level * 5 + column]` replaces it when lower.
_SAVES = (rb"\x26\xc6\x85(..)(.).{0,40}?\x80\x7e\xfd(.)\x76\x06\xc6\x46\xf5(.)"
          rb".{0,20}?\x8b\xf0\xd1\xe0\xd1\xe0\x01\xf0.{0,8}?"
          rb"\xba(.)\x00\xf7\xe2\x8b\xf8\x03\xf9\x03\xfb\x8a\x95(..)")


def saves(ovr: bytes, image: bytes, ds: int) -> dict:
    """Five save targets a class holds at levels 0 to the clamp."""
    m = _one(_SAVES, ovr, "saving-throw recompute")
    start, clamp = m.group(2)[0], m.group(4)[0]
    stride, table = m.group(5)[0], _u16(m.group(6))
    seg = image[ds * 16:]
    rows = {}
    for n, name in enumerate(CLASSES):
        at = table + n * stride
        rows[name] = tuple(tuple(seg[at + 5 * lv:at + 5 * lv + 5])
                           for lv in range(clamp + 1))
    return {"site": m.start(), "table": table, "stride": stride,
            "clamp": clamp, "start": start, "record": _u16(m.group(1)),
            "rows": rows}


# --- hit dice and the constitution bonus ------------------------------------
# `GAME.OVR:0x026F4B`, one class slot at a time: below `[0x6DC9 + class]` the
# class rolls `[0x6DD0 + class]` dice at level 1 and one after, each die of
# `[0x6DD7 + class]` sides, rolled twice and the higher kept; at or past it a
# flat amount set by class number in code.
_DICE = (rb"\x8a\x85(..)\x22\x46\x0a.{0,16}?\x8a\x95(..).{0,60}?"
         rb"\x8a\x85(..)\x88\x46\xfc.{0,12}?\x8a\x85(..)\x50\x9a(....)"
         rb".{0,16}?\x8a\x85(..)\x50\x9a(....)\x88\x46\xfe\x8a\x46\xfe"
         rb"\x3a\x46\xff\x76")
_FLAT = (rb"\x3c(.)\x74\x04\x3c(.)\x75\x06\xc6\x46\xfd(.)\xeb."
         rb"\x3c(.)\x74\x08\x3c(.)\x74\x04\x3c(.)\x75\x06\xc6\x46\xfd(.)\xeb."
         rb"\x3c(.)\x75\x04\xc6\x46\xfd(.)")


def hit_dice(ovr: bytes, image: bytes, ds: int) -> dict:
    """`{class: (first flat level, dice at level 1, sides, flat)}`."""
    m = _one(_DICE, ovr, "hit-die routine")
    flat_level, first, sides = (_u16(m.group(i)) for i in (2, 3, 4))
    if m.group(5) != m.group(7) or m.group(4) != m.group(6):
        raise LookupError("hit-die routine: the two rolls differ")
    f = re.search(_FLAT, ovr[m.end():m.end() + 0x100], re.S)
    if f is None:
        raise LookupError("hit-die routine: flat amounts not found")
    g = [x[0] for x in f.groups()]
    flat = {g[0]: g[2], g[1]: g[2], g[3]: g[6], g[4]: g[6], g[5]: g[6],
            g[7]: g[8]}
    seg = image[ds * 16:]
    rows = {name: (seg[flat_level + n], seg[first + n], seg[sides + n],
                   flat.get(n, 0))
            for n, name in enumerate(CLASSES)}
    return {"site": m.start(), "rolls": 2, "rows": rows,
            "tables": (flat_level, first, sides)}


# `GAME.OVR:0x026ECC`: `[0x719C + constitution]`, signed, then for class
# numbers 2, 3 and 4 a further amount by band, in code.
_CON = (rb"\x26\x8a\x45\x19\x30\xe4\x8b\xf8\x8a\x85(..)\x00\x46\xfe"
        rb"\x80\x7e\x06(.)\x74.\x80\x7e\x06(.)\x74.\x80\x7e\x06(.)\x75."
        rb"\xc4\x7e\x08\x26\x8a\x45\x19"
        rb"\x3c(.)\x75\x05\xfe\x46\xfe\xeb."
        rb"\x3c(.)\x75\x06\x80\x46\xfe(.)\xeb."
        rb"\x3c(.)\x74\x04\x3c(.)\x75\x06\x80\x46\xfe(.)\xeb."
        rb"\x3c(.)\x72.\x3c(.)\x77\x06\x80\x46\xfe(.)\xeb."
        rb"\x3c(.)\x74\x04\x3c(.)\x75\x04\x80\x46\xfe(.)")


def constitution(ovr: bytes, image: bytes, ds: int, top: int = 25) -> dict:
    """Hit points a die from constitution 0 to `top`: `(other, fighter)`.

    The overlay carries two copies of this helper (`0x01848C` and
    `0x026ED9`); both are decoded and must agree, or this raises.
    """
    found = list(re.finditer(_CON, ovr, re.S))
    decoded = [_constitution_one(m, image, ds, top) for m in found]
    if not decoded or any(d["other"] != decoded[0]["other"]
                          or d["fighter"] != decoded[0]["fighter"]
                          or d["extra_for"] != decoded[0]["extra_for"]
                          for d in decoded):
        raise LookupError(f"constitution helper: {len(found)} copies that "
                          "do not agree")
    decoded[0]["copies"] = tuple(d["site"] for d in decoded)
    return decoded[0]


def _constitution_one(m: re.Match, image: bytes, ds: int, top: int) -> dict:
    g = [x[0] if len(x) == 1 else _u16(x) for x in m.groups()]
    table, extra_for = g[0], {CLASSES[g[1]], CLASSES[g[2]], CLASSES[g[3]]}
    extra = {g[4]: 1, g[5]: g[6], g[7]: g[9], g[8]: g[9], g[13]: g[15],
             g[14]: g[15]}
    for score in range(g[10], g[11] + 1):
        extra[score] = g[12]
    seg = image[ds * 16:]
    base = [struct.unpack_from("<b", seg, table + s)[0]
            for s in range(top + 1)]
    return {"site": m.start(), "table": table, "extra_for": extra_for,
            "other": tuple(base),
            "fighter": tuple(b + extra.get(s, 0) for s, b in enumerate(base))}


# --- the stored records ------------------------------------------------------

def records(path: str | None = None) -> list[pathlib.Path]:
    """The 510-byte `.SAV` records under the game's own install."""
    where = dospodtables.find_game(path).parent
    return [p for p in sorted(where.rglob("*.SAV"))
            if p.stat().st_size == dospodtables.RECORD_SIZE]


def effective_levels(record: bytes) -> list[int]:
    """What `0x0392EE` returns per class: the former level at `0x158` where
    that is higher, which it is for every dual-classed record read here."""
    return [max(record[CLASS_LEVELS + n], record[FORMER_LEVELS + n])
            for n in range(len(CLASSES))]


def engine(record: bytes, t: dict, s: dict, a: dict) -> dict:
    """THAC0 byte, five saves and attack forms as the recomputes leave them,
    before the column-0 constitution adjustments (none of these records
    reaches one)."""
    lv = effective_levels(record)
    thac0_byte = max(t["rows"][name][min(lv[n], t["clamp"])]
                     for n, name in enumerate(CLASSES))
    out = [s["start"]] * 5
    for n, name in enumerate(CLASSES):
        if lv[n]:
            row = s["rows"][name][min(lv[n], s["clamp"])]
            out = [min(x, y) for x, y in zip(out, row)]
    forms = record[a["record"]]
    want = 2
    for name, bands in a["bands"].items():
        level = lv[CLASSES.index(name)]
        for above, value in bands:
            if level > above:
                want = max(want, value)
    return {"thac0": thac0_byte, "saves": tuple(out), "attacks": want,
            "stored_attacks": forms}


# --- the commands ------------------------------------------------------------

def cmd_tables(a) -> int:
    ovr, image, ds = dospodtables.load(a.path)
    xp = experience(ovr, image, ds)
    print(f"experience: routine {xp['site']:06X}, DS:{xp['table']:04X} + "
          f"class * {xp['stride']} + level * 4 below {xp['direct_below']}, "
          f"then entry {xp['entry_past']} + DS:{xp['increment']:04X}[class] "
          f"a level; unreachable from {xp['unreachable_from']}")
    for name, row in xp["rows"].items():
        print(f"  {name:10s} " + " ".join(str(row[lv]) for lv in
                                         sorted(row) if lv <= 14) + " ...")
    t = thac0(ovr, image, ds)
    print(f"\nTHAC0 (stored 60 - THAC0): routine {t['site']:06X}, "
          f"DS:{t['table']:04X} + class * {t['stride']} + level, level "
          f"clamped at {t['clamp']}, into record {t['record']:#05x}")
    for name, row in t["rows"].items():
        print(f"  {name:10s} " + " ".join(str(60 - v) for v in row))
    at = attacks(ovr)
    print(f"\nattack forms into record {at['record']:#05x} (doubled):")
    for name, bands in at["bands"].items():
        print(f"  {name:10s} " + ", ".join(f"above {lv} -> {v}"
                                          for lv, v in bands))
    s = saves(ovr, image, ds)
    print(f"\nsaves: routine {s['site']:06X}, DS:{s['table']:04X} + class * "
          f"{s['stride']} + level * 5 + column, level clamped at "
          f"{s['clamp']}, from {s['start']} into record {s['record']:#05x}")
    for name, rows in s["rows"].items():
        print(f"  {name:10s} " + " | ".join(" ".join(map(str, r))
                                           for r in rows[:4]) + " ...")
    h = hit_dice(ovr, image, ds)
    print(f"\nhit dice: routine {h['site']:06X}, tables DS:"
          + ", DS:".join(f"{x:04X}" for x in h["tables"])
          + f", rolled {h['rolls']} times keeping the higher")
    for name, (flat_level, first, sides, flat) in h["rows"].items():
        print(f"  {name:10s} rolls to {flat_level - 1}, {first}d{sides} at "
              f"level 1, then +{flat} a level")
    c = constitution(ovr, image, ds)
    print("\nconstitution: helpers "
          + ", ".join(f"{x:06X}" for x in c["copies"])
          + f", DS:{c['table']:04X} by "
          f"score, more for {sorted(c['extra_for'])}")
    print("  other   " + " ".join(f"{v:2d}" for v in c["other"]))
    print("  fighter " + " ".join(f"{v:2d}" for v in c["fighter"]))
    return 0


def cmd_check(a) -> int:
    ovr, image, ds = dospodtables.load(a.path)
    t, s, at = thac0(ovr, image, ds), saves(ovr, image, ds), attacks(ovr)
    found = records(a.path)
    agree = {"thac0": 0, "saves": 0, "attacks": 0}
    for p in found:
        r = p.read_bytes()
        got = engine(r, t, s, at)
        stored = {"thac0": r[t["record"]],
                  "saves": tuple(r[s["record"]:s["record"] + 5]),
                  "attacks": got["stored_attacks"]}
        marks = []
        for key in agree:
            if got[key] == stored[key]:
                agree[key] += 1
            else:
                marks.append(f"{key} {stored[key]} != {got[key]}")
        print(f"  {p.parent.name}/{p.name:13s} levels "
              f"{effective_levels(r)} " + ("; ".join(marks) or "agrees"))
    print(" ".join(f"{k} {v} of {len(found)}" for k, v in agree.items()))
    return 0 if all(v == len(found) for v in agree.values()) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("tables", "check"))
    ap.add_argument("--path", default=None, help="the game directory")
    a = ap.parse_args(argv)
    return {"tables": cmd_tables, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

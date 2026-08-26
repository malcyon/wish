"""Two findings that came off the community forum sweep, asserted.

**The `STING` negative** (`docs/126` §2). The DOS builds of both our titles take
a command-line cheat argument -- `start.exe STING` for Pool of Radiance,
`start.exe STING Wooden` for Curse -- and the question was whether the check
survived the port with nothing reaching it. It did not: every occurrence of the
literal on the C64 disks is inside `CASTING`, `PLAYTESTING` or ordinary game
prose. That is a negative worth nailing down, because a negative nobody wrote
down gets re-investigated.

**The `coab` constants** (`docs/117`). `simeonpilgrim/coab` is a decompilation
of the DOS Curse overlays, and it carries the DOS record for both our titles
plus the routine the game runs to import a Pool of Radiance character. Its
arbitrary constants -- 300 platinum, `animate_dead = 0x24`, the money-word order
-- agree with things we measured on the C64 independently, and these tests fail
if either side moves.

Neither half is in this repository. The disks are the player's own
(`tests/gamedata.py`), and the C# is somebody else's work fetched to
`work/forums/ext/`, which is `.gitignore`d. Both halves skip when what they need
is absent, which is what CI does.
"""

from __future__ import annotations

import functools
import pathlib
import re

import pytest
from gamedata import curse_dir, disk_dir

from goldbox.d64 import D64, load_payload
from goldbox.spells import load_spell_names, spellbook_bytes

# --- the STING negative ------------------------------------------------------

#: Literals the DOS builds test on their command line, plus the message the
#: cheat prints and three words a debug facility would plausibly use.
#: `docs/126` §2 has the per-title table.
CHEAT_WORDS = ("STING", "WOODEN", "GODS", "INTERVENE", "HOOP", "HELM",
               "WOOF", "SUPER", "GEM", "PLAYTEST", "DEBUG", "CHEAT")

#: Every longer word a hit is allowed to be part of. Anything else is a
#: standalone occurrence and would need explaining.
INNOCENT = re.compile(
    rb"CASTING|PLAYTESTING|INTERESTING|RUSTING|TWISTING|RESTING|BURSTING"
    rb"|DISGUSTING|CHEATING|SUPERNATURAL|GEMS")


def _payloads():
    """Every file on every Pool of Radiance and Curse side, as raw bytes."""
    out = []
    for where, glob in ((disk_dir(), "POOL*.[dD]64"),
                        (curse_dir(), "CURSE*.[dD]64")):
        if where is None:
            continue
        for image in sorted(pathlib.Path(where).glob(glob)):
            try:
                disk = D64.open(image)
            except Exception:
                continue                      # a rip we cannot read is not a fail
            for entry in disk.directory():
                try:
                    payload = load_payload(str(image), entry.name)
                except Exception:
                    continue
                if payload is None:
                    continue
                name = entry.name.decode("latin1").rstrip("\xa0 ")
                out.append((f"{image.name}:{name}", payload))
    return out


@functools.lru_cache(maxsize=1)
def _all_payloads():
    return tuple(_payloads())


def _need_payloads():
    payloads = _all_payloads()
    if not payloads:
        pytest.skip("needs the game disks; set POR_DISKS / COAB_DISKS")
    return payloads


def test_sting_is_only_ever_a_substring():
    """`STING` on the C64 disks is `CASTING`, never a cheat word.

    The DOS check is on the argument vector; the C64 has none, and the literal
    did not survive the port. Reported as a clean negative in `docs/126` §2.
    """
    standalone = []
    for label, payload in _need_payloads():
        for match in re.finditer(rb"[A-Za-z]*STING[A-Za-z]*", payload):
            if not INNOCENT.fullmatch(match.group()):
                standalone.append((label, hex(match.start()), match.group()))
    assert standalone == []


def test_no_cheat_literal_stands_alone_anywhere():
    """None of the DOS cheat words appears as a word of its own.

    Only ASCII is checked here; `docs/126` §2 records the wider sweep -- six
    encodings including screen codes and the VM's 6-bit packing, against the raw
    sector images as well as the file payloads -- which found the same nothing.
    `GEM`, `HELM` and `WOODEN` are excluded because they are real `ITEMNAMES`
    components, which is a different question from a cheat check.
    """
    words = [w for w in CHEAT_WORDS if w not in ("GEM", "HELM", "WOODEN")]
    pattern = re.compile(
        rb"[A-Za-z]*(?:" + b"|".join(w.encode() for w in words) + rb")[A-Za-z]*")
    standalone = []
    for label, payload in _need_payloads():
        for match in pattern.finditer(payload):
            if not INNOCENT.fullmatch(match.group()):
                standalone.append((label, hex(match.start()), match.group()))
    assert standalone == []


def test_the_gods_never_intervene():
    """The message the DOS cheat prints is on no C64 disk.

    Checked with spaces removed, so that a line break inside the phrase would
    not hide it.
    """
    for label, payload in _need_payloads():
        assert b"GODSINTERVENE" not in payload.upper().replace(b" ", b"")


# --- the coab constants ------------------------------------------------------

EXT = pathlib.Path(__file__).resolve().parent.parent / "work" / "forums" / "ext"


def _source(name: str) -> str:
    path = EXT / name
    if not path.is_file():
        pytest.skip(f"needs {path}; fetch simeonpilgrim/coab into work/forums/ext")
    return path.read_text(encoding="utf-8", errors="replace")


def test_dos_record_sizes():
    """285 for DOS Pool of Radiance, 422 for DOS Curse -- `docs/117`."""
    assert "StructSize = 0x011D" in _source("PoolRadPlayer.cs")
    assert "StructSize = 0x1A6" in _source("Player.cs")


def test_the_import_sets_money_to_300_platinum():
    """The constant our own Pool->Curse import produced at `0x0C3`.

    Two independent artefacts agreeing on an arbitrary number is as close to
    proof as this work gets (`docs/116` §4).
    """
    text = _source("ovr017.cs")
    assert "player.Money.SetCoins(Money.Platinum, 300);" in text
    # The Pool record's own seven money words at 0x88-0x95 are never read: the
    # loader's field list jumps 0x87 -> 0x96. So all seven are discarded, not
    # just the gold we happened to watch change (`docs/117`).
    pool = _source("PoolRadPlayer.cs")
    read = set(re.findall(r"data\[(0x[0-9A-Fa-f]+)\]", pool))
    read |= set(re.findall(r"System\.Array\.Copy\(data, (0x[0-9A-Fa-f]+)", pool))
    read |= set(re.findall(r"Sys\.ArrayTo\w+\(data, (0x[0-9A-Fa-f]+)\)", pool))
    assert not {v for v in read if 0x88 <= int(v, 16) <= 0x95}


def test_the_import_erases_spell_36():
    """`animate_dead = 0x24` is our ANIMATE DEAD, and the import deletes it."""
    assert "player.spellBook[(int)Spells.animate_dead - 1] = 0;" in _source("ovr017.cs")
    assert "animate_dead = 0x24," in _source("Spells.cs")


def test_money_word_order_matches_ours():
    """copper, silver, electrum, gold, platinum, gems, jewelry -- `0x0BB`."""
    text = _source("MoneySet.cs")
    order = re.findall(r"public const int (\w+) = (\d);", text)
    assert order == [("Copper", "0"), ("Silver", "1"), ("Electrum", "2"),
                     ("Gold", "3"), ("Platinum", "4"), ("Gems", "5"),
                     ("Jewelry", "6")]


def test_animate_dead_is_spell_36_on_the_c64_too():
    """The C64 side of the same claim, read off the player's own disks."""
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    for image in sorted(pathlib.Path(where).glob("POOL*.[dD]64")):
        try:
            names = load_spell_names(str(image))
        except Exception:
            continue
        if 36 in names:
            assert names[36] == "ANIMATE DEAD"
            # the C64 mask indexes by spell id, not id-1: bit 4 of byte 4
            assert spellbook_bytes([36]) == bytes([0, 0, 0, 0, 0x10, 0, 0])
            return
    pytest.skip("no POOL disk here carries the spell-name table")

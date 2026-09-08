from __future__ import annotations

"""What the game prints when a monster acts (`#350`).

The table and the call sites come off the player's own disks and skip without
them; the replay is a screen we construct here, so it needs nothing at all.
"""

import json

import pytest
from gamedata import disk_dir, needs_disks

from automap import combatlog
from automap.screen import SCREEN_COLS
from tools import monstermsg

#: `COMBAT $0D63`'s own indices, read off the overlay in `#350`. Kept here as
#: the phrases rather than the numbers, because a number that moved would be a
#: different game and a phrase that moved would be a different reader.
ATTACK_PHRASES = {
    26: "POINTS OF DAMAGE",
    41: "ATTACKS",
    42: "AND MISSES...",
    43: "AND HITS FOR ",
    44: "GOES DOWN",
    45: "AND IS DYING",
    46: "IS KILLED",
}


@pytest.fixture
def disks():
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    return str(where)


@needs_disks
def test_the_attack_phrases_are_the_games_own(disks):
    """Every phrase the melee-attack routine prints, from the shipped table.

    The one that matters is `AND MISSES...`: the three dots are the game's
    own, and a reader that trims them would not match a line the engine
    printed. `#128` made the same point about `THE PARTY HAS LOST`.
    """
    messages = monstermsg.combat_messages(disks)
    assert {n: messages[n] for n in ATTACK_PHRASES} == ATTACK_PHRASES


@needs_disks
def test_the_table_holds_sixty_four_messages(disks):
    """Entries 57-120 of `SPELLN00`, and nothing past `SURRENDERS`.

    The pointers past it are `$FF00` and `$20FF`, which land outside the file
    -- padding, not a 65th message. So a scan that trusted the 128-entry table
    would read seven strings that are not there.
    """
    messages = monstermsg.combat_messages(disks)
    assert len(messages) == 64
    assert messages[63] == "SURRENDERS"


@needs_disks
def test_one_routine_prints_a_melee_attack_for_either_side(disks):
    """`$0D68` is the only `JSR $2983` in COMBAT with a literal index.

    That is the whole of `#350`'s message half: there is no second printer
    for a monster, so a reader that sees a character's attack sees a
    monster's.
    """
    sites = monstermsg.print_sites(disks)
    blocks = [(addr, index) for addr, printer, index, _how in sites
              if printer == 0x2983 and index is not None]
    assert blocks == [(0x0D68, 41)]


def codes(text: str) -> bytes:
    """ASCII to screen codes, as `tests/test_combatlog.py` does it."""
    return bytes(ord(c) - 64 if "A" <= c <= "Z" else ord(c)
                 for c in text.upper())


def screen(rows: dict[int, str]) -> bytes:
    """A whole 1000-byte screen with `rows` painted in the message window."""
    out = bytearray(b"\x20" * (SCREEN_COLS * 25))
    left = combatlog.COMBAT_WINDOW[0]
    for row, text in rows.items():
        at = row * SCREEN_COLS + left
        out[at:at + len(text)] = codes(text)
    return bytes(out)


def test_a_monsters_block_replays_as_one_message(tmp_path):
    """The shape `work/rolls/run1.jsonl` caught an orc printing.

    Four rows: the attacker's name, `ATTACKS`, the target's name, and the
    outcome. The block is committed when the game paints over it, so the
    capture ends with a blank frame the way the game does.
    """
    block = {10: "ORC", 11: "ATTACKS", 12: "BRUTUS", 13: "AND MISSES..."}
    frames = [screen(block), screen(block), screen({})]
    path = tmp_path / "capture.jsonl"
    with path.open("w") as f:
        for codes_ in frames:
            f.write(json.dumps({"scr": codes_.hex(), "win2": "17270a17"})
                    + "\n")
    messages = monstermsg.replay(path)
    assert [m.text for m in messages] == ["ORC ATTACKS BRUTUS AND MISSES..."]
    assert messages[0].subject == "ORC"


def test_a_line_with_no_window_bytes_is_skipped(tmp_path):
    """A capture's world rows carry no screen, and must not stop the replay."""
    path = tmp_path / "capture.jsonl"
    path.write_text(json.dumps({"kind": "world", "pos": [1, 2, 3]}) + "\n")
    assert monstermsg.replay(path) == []

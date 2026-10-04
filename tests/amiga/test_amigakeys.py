"""`tools/amiga/amigakeys.py`: every key the Amiga drivers send is in the table, once.

The raw codes are checked against the *Amiga Hardware Reference Manual*, 3rd
ed., chapter 8 ("RAW Keycodes 40-5F hex" and Figure 8-11) and WinUAE's
`include/keyboard.h`, which agree on every value checked here.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import (  # noqa: E402
    amigakeys,
    fsuaegdb,
    fsuaepor,
    route_camp,
)

ROWS = list(amigakeys.KEYS.values())

#: Keysyms `fsuaeprobedrive.py` sends from its own script table, and the keypad
#: walk `fsuaegdb.py --walk` documents.
LITERAL_KEYSYMS = ("Escape", "Return", "KP_Up", "KP_Left", "KP_Right", "KP_Down")


def _fsuaepor_keysyms() -> set[str]:
    steps = (fsuaepor.panel_script([(1, "a"), (2, "b")], 2, 60.0)
             + fsuaepor.ready_script(1, 3, 60.0))
    return {s[1] for s in steps if s[0] == "key"}


def _swap_keysyms() -> set[str]:
    sequence = fsuaegdb.DEFAULT_SWAP_SEQUENCE.format(index=1)
    return {re.sub(r"\*\d+$", "", word) for word in sequence.split()}


def test_every_keysym_the_fsuae_drivers_send_is_in_the_table():
    sent = (_fsuaepor_keysyms() | _swap_keysyms() | set(LITERAL_KEYSYMS)
            | set(fsuaegdb.KEY_ALIASES.values()))
    assert {"Home", "End", "KP_Down", "Down", "F12"} <= sent
    for keysym in sent:
        assert amigakeys.by_keysym(keysym).keysym == keysym


def test_the_camp_member_and_heal_keys_are_in_the_table():
    names = {k for pair in route_camp.MEMBER_KEYS.values() for k in pair}
    names |= set(route_camp.HEAL_KEYS.values())
    for name in names:
        assert amigakeys.lookup(name).amiga is not None, name


@pytest.mark.parametrize("field", ["amiga", "keysym"])
def test_codes_are_unique(field):
    values = [getattr(k, field) for k in ROWS if getattr(k, field) is not None]
    assert len(values) == len(set(values))


def test_raw_codes_are_seven_bit_and_host_rows_have_none():
    for key in ROWS:
        if key.host:
            assert key.amiga is None, key.name
        else:
            assert key.amiga is not None and 0 <= key.amiga < 0x80, key.name


def test_aliases_name_rows_and_shadow_none():
    for alias, name in amigakeys.ALIASES.items():
        assert alias not in amigakeys.KEYS
        assert name in amigakeys.KEYS
    assert amigakeys.lookup("enter").amiga == 0x44
    with pytest.raises(KeyError):
        amigakeys.lookup("NOSUCHKEY")


@pytest.mark.parametrize("name, code", [
    # HRM chapter 8, "RAW Keycodes 40-5F hex".
    ("SPACE", 0x40), ("BACK", 0x41), ("TAB", 0x42), ("NPENTER", 0x43),
    ("RET", 0x44), ("ESC", 0x45), ("DEL", 0x46), ("UP", 0x4C), ("DOWN", 0x4D),
    ("RIGHT", 0x4E), ("LEFT", 0x4F), ("F1", 0x50), ("F10", 0x59),
    ("NPLPAREN", 0x5A), ("HELP", 0x5F),
    # HRM Figure 8-11, and WinUAE AK_NP0 .. AK_NP9.
    ("NP0", 0x0F), ("NP1", 0x1D), ("NP2", 0x1E), ("NP3", 0x1F), ("NP4", 0x2D),
    ("NP5", 0x2E), ("NP6", 0x2F), ("NP7", 0x3D), ("NP8", 0x3E), ("NP9", 0x3F),
    # HRM Figure 8-11 main block, and WinUAE AK_Q, AK_A, AK_Z, AK_M, AK_1, AK_0.
    ("Q", 0x10), ("P", 0x19), ("A", 0x20), ("L", 0x28), ("Z", 0x31), ("M", 0x37),
    ("1", 0x01), ("9", 0x09), ("0", 0x0A), ("MINUS", 0x0B), ("COLON", 0x29),
    ("COMMA", 0x38), ("PERIOD", 0x39), ("SLASH", 0x3A),
])
def test_raw_code_matches_the_reference(name, code):
    assert amigakeys.lookup(name).amiga == code


def test_keypad_keysyms_are_the_num_lock_off_names():
    # xkeyboard-config symbols/keypad, "x11": level one of KP1 .. KP9, KP0.
    assert [amigakeys.lookup(f"NP{n}").keysym for n in range(10)] == [
        "KP_Insert", "KP_End", "KP_Down", "KP_Next", "KP_Left", "KP_Begin",
        "KP_Right", "KP_Home", "KP_Up", "KP_Prior"]


def test_no_keysym_sends_shift():
    for key in ROWS:
        if key.keysym:
            fsuaegdb.check_shift_letter(key.keysym)


def test_key_raw_writes_hex_with_the_prefix_winuae_needs():
    assert amigakeys.key_raw("esc") == "KEY_RAW_DOWN 0x45"
    assert amigakeys.key_raw("NP2", down=False) == "KEY_RAW_UP 0x1E"
    for key in ROWS:
        if key.amiga is not None:
            word, value = amigakeys.key_raw(key.name).split()
            assert word == "KEY_RAW_DOWN"
            # WinUAE parses with base 16 only after `0x`; base 10 otherwise.
            assert value.startswith("0x") and int(value, 16) == key.amiga
    with pytest.raises(ValueError, match="emulator key"):
        amigakeys.key_raw("F11")

"""One table of the keys the Amiga drivers press, for WinUAE and FS-UAE alike.

Each row names a key once and says how each route reaches it: the Amiga raw
key code that WinUAE's pipe takes as `CFG KEY_RAW_DOWN <code>` /
`KEY_RAW_UP <code>` (what `winuae.ps1 press` sends), and the X keysym `xdotool`
sends to FS-UAE.  A host row is a key the emulator acts on itself and the
Amiga never sees, so it has no raw code.

Sources for the raw codes, every one of which the tests check:

* *Amiga Hardware Reference Manual*, 3rd ed. (ISBN 0-201-56776-8), chapter 8,
  "RAW Keycodes 40-5F hex" and "60-67 hex", and Figure 8-11 (the A500/2000/3000
  keyboard) for 00-3F, the keypad included.
* WinUAE `include/keyboard.h` (`AK_*`), `inputevents.def` and
  `od-win32/keyboard_win32.cpp` (`keytrans_amiga`), commit 5d22d336.
* FS-UAE fork grahambates/fs-uae `remote_debugger_barto`,
  `src/fsuae/fsuae-keyboard.c`, commit b70b1180, for the keysyms with no
  same-named Amiga key (Home, End, Delete), and xkeyboard-config
  `symbols/keypad` (`x11`) for the keypad keysyms with Num Lock off.

`KEY_RAW_*` matches its value against WinUAE's keyboard events, so it is the
raw code itself; WinUAE reads it as decimal unless it starts `0x`, and the
command name is compared case-sensitively.  `key_raw` writes it that way.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Key:
    """One key: what the Amiga receives and how each emulator route sends it."""

    name: str
    #: Amiga raw key code (0x00-0x7F); None for a host row.
    amiga: int | None
    #: X keysym for `xdotool` into FS-UAE; None when FS-UAE has no key for it.
    keysym: str | None
    #: For a host row, what the emulator does with the key instead.
    host: str | None = None


def _k(name: str, amiga: int | None, keysym: str | None, host: str | None = None) -> Key:
    return Key(name, amiga, keysym, host)


_ROWS: list[Key] = [
    # HRM "RAW Keycodes 40-5F hex"; WinUAE AK_SPC .. AK_DEL, AK_UP .. AK_RT, AK_HELP.
    _k("RET", 0x44, "Return"),
    _k("NPENTER", 0x43, "KP_Enter"),
    _k("ESC", 0x45, "Escape"),
    _k("SPACE", 0x40, "space"),
    _k("BACK", 0x41, "BackSpace"),
    _k("TAB", 0x42, "Tab"),
    _k("DEL", 0x46, "Delete"),
    _k("HELP", 0x5F, "End"),
    _k("NPLPAREN", 0x5A, "Home"),
    _k("UP", 0x4C, "Up"),
    _k("DOWN", 0x4D, "Down"),
    _k("RIGHT", 0x4E, "Right"),
    _k("LEFT", 0x4F, "Left"),
    # HRM Figure 8-11, main block.  COLON is the unshifted `;` key.
    _k("SLASH", 0x3A, "slash"),
    _k("COLON", 0x29, "semicolon"),
    _k("PERIOD", 0x39, "period"),
    _k("COMMA", 0x38, "comma"),
    _k("MINUS", 0x0B, "minus"),
    # HRM Figure 8-11 numeric keypad; WinUAE AK_NP0 .. AK_NP9.
    _k("NP0", 0x0F, "KP_Insert"),
    _k("NP1", 0x1D, "KP_End"),
    _k("NP2", 0x1E, "KP_Down"),
    _k("NP3", 0x1F, "KP_Next"),
    _k("NP4", 0x2D, "KP_Left"),
    _k("NP5", 0x2E, "KP_Begin"),
    _k("NP6", 0x2F, "KP_Right"),
    _k("NP7", 0x3D, "KP_Home"),
    _k("NP8", 0x3E, "KP_Up"),
    _k("NP9", 0x3F, "KP_Prior"),
    # Emulator keys.  F11 is bound to SPC_ENTERDEBUGGER by goldbox-a500.uae;
    # F12 opens FS-UAE's menu.
    _k("F11", None, None, host="WinUAE debugger (SPC_ENTERDEBUGGER)"),
    _k("F12", None, "F12", host="FS-UAE menu"),
]
# HRM "50-59 Function keys F1-F10"; WinUAE AK_F1 .. AK_F10.
_ROWS += [_k(f"F{n}", 0x4F + n, f"F{n}") for n in range(1, 11)]
# HRM Figure 8-11 positions on a US keyboard; WinUAE AK_A .. AK_Z, AK_0 .. AK_9.
_ROWS += [_k(c, code, c.lower()) for c, code in zip(
    "QWERTYUIOPASDFGHJKLZXCVBNM",
    [*range(0x10, 0x1A), *range(0x20, 0x29), *range(0x31, 0x38)], strict=True)]
_ROWS += [_k(str(d), 0x0A if d == 0 else d, str(d)) for d in range(10)]

#: Every key by its canonical name.
KEYS: dict[str, Key] = {k.name: k for k in _ROWS}

#: Other names the drivers use for a row; ENTER is the main Return key, as
#: `amigadrive.press` sends it, not the keypad Enter.
ALIASES: dict[str, str] = {"RETURN": "RET", "ENTER": "RET"}

_BY_KEYSYM: dict[str, Key] = {k.keysym: k for k in _ROWS if k.keysym}


def lookup(name: str) -> Key:
    """The row for a driver key name, any case, aliases included; KeyError if unknown."""
    upper = name.upper()
    return KEYS[ALIASES.get(upper, upper)]


def by_keysym(keysym: str) -> Key:
    """The row an X keysym presses; KeyError if no row sends it."""
    return _BY_KEYSYM[keysym]


def key_raw(name: str, down: bool = True) -> str:
    """The WinUAE pipe argument that presses or releases `name`, e.g. `KEY_RAW_DOWN 0x45`.

    ValueError for a host row, which no raw code reaches.
    """
    key = lookup(name)
    if key.amiga is None:
        raise ValueError(f"{key.name} is an emulator key ({key.host}), not an Amiga key")
    return f"KEY_RAW_{'DOWN' if down else 'UP'} 0x{key.amiga:02X}"

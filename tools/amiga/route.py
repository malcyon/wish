"""The Amiga title description: what `run_recon` needs to know about one title."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Mapping
from typing import Any

from goldbox import amiga_adf, amiga_por
from tools.amiga import amigakeys
from tools.amiga.winuaesession import HOLDER, RouteError

ISSUE = "679"
TITLE_LIMIT = 180.0


def _has_raw_code(name: Any) -> bool:
    """Whether `name` is a key the pipe can press: an Amiga key, not an emulator key."""
    try:
        return isinstance(name, str) and amigakeys.lookup(name).amiga is not None
    except KeyError:
        return False


_STEP_KINDS = frozenset({"key", "write", "move", "turn", "answer", "insert"})
_LETTER = re.compile(r"[A-Z]")
_OPTION = re.compile(r"[A-Za-z0-9_]+=[A-Za-z0-9_.]*")
_EXPECT = re.compile(r"(?P<name>[^:]+):(?P<id>-?[0-9]+):(?P<minutes>-?[0-9]+):(?P<data>-?[0-9]+)")


def effect_fields(node: bytes) -> tuple[int, int, int, int]:
    """One 10-byte Amiga effect node's `(id, minutes, data, flag)`, through DOS's byte order.

    `goldbox.amiga_por.amiga_por_effect_to_dos` already does the byte-order
    work (the swap from the Amiga's big-endian `u16` at offset 2 to DOS's
    little-endian one at offset 1); this only re-reads the result as integers,
    for a title-agnostic route reader (#661).
    """
    dos = amiga_por.amiga_por_effect_to_dos(node)
    return dos[0], dos[1] | (dos[2] << 8), dos[3], dos[4]


def parse_expect(text: str) -> tuple[str, int, int, int]:
    """Read `NAME:ID:MINUTES:DATA` into its four fields."""
    m = _EXPECT.fullmatch(text)
    if not m:
        raise RouteError(f"--expect {text!r} is not NAME:ID:MINUTES:DATA")
    return m["name"], int(m["id"]), int(m["minutes"]), int(m["data"])


def check_expect(reading: Mapping[str, Any], expect: tuple[str, int, int, int]) -> tuple[bool, str]:
    """Whether a slot's `effects` reading holds `expect`'s node exactly: `(accepted, verdict line)`.

    `reading` is a `read_slot` result: `effects` maps a character's name to its
    `[id, minutes, data, flag]` rows. The minutes field must match exactly, the
    same way DOS's own `tools.dos.acceptance.judge` requires an exact match --
    a tolerance here would mask whether the Amiga engine counts a spell down at
    all (#661). The boolean is the caller's pass/fail signal; the line is only
    for printing, and must never be string-matched to recover it.
    """
    name, eid, minutes, data = expect
    label = f"expect {name} id {eid} at {minutes} minutes"
    effects = reading.get("effects") if reading else None
    if not effects:
        return False, f"{label}: refutes (the slot holds no effects reading)"
    nodes = effects.get(name)
    if nodes is None:
        return False, f"{label}: refutes ({name} is absent from the slot)"
    if any(n[0] == eid and n[2] == data and n[1] == minutes for n in nodes):
        return True, f"{label}: accepts"
    return False, f"{label}: refutes (holds {nodes})"


@dataclasses.dataclass(frozen=True, kw_only=True)
class AmigaTitle:
    """What `run_recon` needs to know about one Amiga title; Silver Blades is the default without one.

    `mounted` lists manifest disk keys in drive order (None: an empty drive) and
    `spares` the keys put on the VM and not mounted. A route step is
    `(key, state, kind)`; an `insert` step's key is `(drive, disk_key, key)`, and
    `write` steps may press only `control_letter` or `after_letter`, and no other step may press
    those. A title that only loads has neither letter and no `write` step. A kept letter is never
    written, so a non-write step may press one only where `plain_keys` names its `(key, state)`:
    the game's own key that happens to be a slot's letter. A simple key is blocked on a screen
    where some step writes and on a state whose name contains `picker`; the run's compare of
    every kept slot after the fetch is what proves none changed. An interstitial row may press a
    save or kept letter only where `interstitial_letters` names its `(key, screen)`: the game's own
    key on a screen the guard recognises, such as FLEE on an encounter bar. Its screen is never a
    route state or a picker. After an interstitial screen in `move_again_after` has been answered
    during a `move` step, that step's key is pressed again.
    Every entry must be a kept letter that some non-write step presses in that state. An `insert`
    may name drive 1, or drive 0 when the step before it is in `disk_prompts` (states where the
    game itself asks for a disk) and `strict`, naming a disk other than the one in DF0; an
    interstitial insert names drive 1, or drive 0 when its screen is a strict disk prompt and the
    disk differs from DF0's. The step before a `write` or `insert` step must be in
    `strict`. `strict` names the states whose guard must match or the run stops; any other
    state falls back to a settled capture and marks the run as measuring. `wait_limits` gives a
    state its own limit in seconds for a guarded wait, where the default is too short for the
    pages the game shows before that state. `edge_exits` maps `(area, walk facing)` to the area
    a step off that area's 16x16 map enters, for an exit that keeps the party's wrapped square and facing.
    """

    issue: str
    mounted: tuple[str | None, ...]
    save_disk: str
    read_slot: Callable[[amiga_adf.AmigaDisk, str], dict[str, Any]]
    slot_letters: Callable[[amiga_adf.AmigaDisk], list[str]]
    slot_files: Callable[[amiga_adf.AmigaDisk, str], dict[str, bytes]]
    route: tuple[tuple[Any, str, str], ...]
    measure_route: tuple[tuple[Any, str, str], ...]
    boot_span: float
    control_letter: str | None = None
    after_letter: str | None = None
    spares: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    strict: frozenset[str] = frozenset()
    disk_prompts: frozenset[str] = frozenset()
    min_waits: Mapping[str, float] = dataclasses.field(default_factory=dict)
    title_limit: float = TITLE_LIMIT
    interstitials: tuple[tuple[str, tuple, Any, int], ...] = ()
    kept_letters: tuple[str, ...] = ()
    turn: str | None = None
    plain_keys: tuple[tuple[str, str], ...] = ()
    interstitial_letters: tuple[tuple[str, str], ...] = ()
    move_again_after: frozenset[str] = frozenset()
    wait_limits: Mapping[str, float] = dataclasses.field(default_factory=dict)
    edge_exits: Mapping[tuple[int, int], int] = dataclasses.field(default_factory=dict)

    @property
    def disk_keys(self) -> tuple[str, ...]:
        return (*(k for k in self.mounted if k is not None), *self.spares)

    def __post_init__(self) -> None:
        def block(why: str) -> None:
            raise RouteError(f"title description: {why}")

        keys = self.disk_keys
        if not re.fullmatch(r"[0-9]+", str(self.issue)):
            block(f"issue {self.issue!r} is not a number")
        if not self.mounted or len(self.mounted) > 4 or self.mounted[0] is None:
            block("DF0 must hold a disk and there are at most four drives")
        if len(set(keys)) != len(keys) or not all(HOLDER.fullmatch(str(k)) for k in keys):
            block(f"disk keys {keys} must be distinct, lane-safe names")
        if self.save_disk not in keys:
            block(f"save disk {self.save_disk!r} is not one of {keys}")
        if not all(_OPTION.fullmatch(o) for o in self.options):
            block(f"options {self.options} must each be name=value")
        if (self.control_letter is None) != (self.after_letter is None):
            block("control and after letters are both given or both None")
        if self.control_letter is None and any(
                step[2] == "write" for route in (self.route, self.measure_route)
                for step in route if isinstance(step, tuple) and len(step) == 3):
            block("a title with no save letters has a write step")
        letters = tuple(c for c in (self.control_letter, self.after_letter, *self.kept_letters)
                        if c is not None)
        if not all(_LETTER.fullmatch(str(c)) for c in letters) or len(set(letters)) != len(letters):
            block(f"save letters {letters} must be distinct capitals")
        if self.turn not in (None, "about"):
            block(f"turn {self.turn!r} is neither None nor 'about'")
        if any(limit <= 0 for limit in self.wait_limits.values()):
            block("every wait limit must be positive")
        if self.title_limit <= 0 or self.boot_span <= 0:
            block("the title limit and the boot span must be positive")
        if any(w < 0 for w in self.min_waits.values()):
            block("a minimum wait is negative")
        simple = self.plain_keys
        if not (isinstance(simple, tuple) and all(
                isinstance(e, tuple) and len(e) == 2 and all(isinstance(x, str) for x in e)
                for e in simple)):
            block(f"simple keys {simple!r} must be (key, state) pairs")
        if len(set(simple)) != len(simple):
            block(f"simple keys {simple!r} repeat an entry")
        for entry in simple:
            if entry[0] not in self.kept_letters:
                block(f"simple key {entry!r} is not a kept letter, so it cannot be pressed as a simple key")
        used: set[tuple[str, str]] = set()
        # A kept letter pressed where a save letter goes out, or on a picker, could write a slot.
        save_screens = {"title" if at == 0 else route[at - 1][1]
                        for route in (self.route, self.measure_route)
                        for at, step in enumerate(route)
                        if isinstance(step, tuple) and len(step) == 3 and step[2] == "write"}
        for name, route in (("route", self.route), ("measure_route", self.measure_route)):
            if not route:
                block(f"{name} is empty")
            for at, step in enumerate(route):
                allowed = self._check_step(name, step, keys, block,
                                           None if at == 0 else route[at - 1][1], at == 0)
                if allowed:
                    used.add(allowed)
                    on = "title" if at == 0 else route[at - 1][1]
                    if on in save_screens or "picker" in on.lower():
                        why = ("a route step presses a save letter there" if on in save_screens
                               else "a picker screen takes a slot letter as a save")
                        block(f"{name} step {step!r} presses kept letter {allowed[0]} as a "
                               f"simple key on {on!r}, where {why}")
                if step[2] in ("write", "insert"):
                    # The key goes out on the screen the step before it reached, so that
                    # screen's guard must stop the run when it does not match.
                    before = "title" if at == 0 else route[at - 1][1]
                    if before != "title" and before not in self.strict:
                        block(f"{name} {step[2]} step {step!r} follows {before!r}, which is "
                               f"not a strict state")
        for entry in simple:
            if entry not in used:
                block(f"simple key {entry!r} is pressed by no step in that state")
        for row in self.interstitials:
            self._check_row(row, keys, block)
        letters_ok = self.interstitial_letters
        if not (isinstance(letters_ok, tuple) and all(
                isinstance(e, tuple) and len(e) == 2 and all(isinstance(x, str) for x in e)
                for e in letters_ok)):
            block(f"interstitial letters {letters_ok!r} must be (key, screen) pairs")
        row_screens = {row[0] for row in self.interstitials}
        route_states = {step[1] for route in (self.route, self.measure_route)
                        for step in route if isinstance(step, tuple) and len(step) == 3}
        for entry in letters_ok:
            if entry[1] not in row_screens:
                block(f"interstitial letter {entry!r} names a screen with no interstitial row")
            if entry[1] in route_states:
                block(f"interstitial letter {entry!r} names a screen that is also a route state")
            if "picker" in entry[1].lower():
                block(f"interstitial letter {entry!r} names a picker screen, which takes a slot "
                      f"letter as a save")
        for screen in self.move_again_after:
            if screen not in row_screens:
                block(f"move-again screen {screen!r} has no interstitial row")

    def _write_letters(self) -> frozenset[str]:
        """The letters that save, or belong to a slot that must not change."""
        return frozenset(c for c in (self.control_letter, self.after_letter, *self.kept_letters)
                         if c is not None)

    def _check_step(self, name, step, keys, block, before=None, first=False
                    ) -> tuple[str, str] | None:
        """Block a bad step; return the `plain_keys` entry that lets it press a kept letter, if any."""
        if not isinstance(step, tuple) or len(step) != 3 or step[2] not in _STEP_KINDS:
            block(f"{name} step {step!r} is not (key, state, kind) with a known kind")
        key, state, kind = step
        if not state or not isinstance(state, str):
            block(f"{name} step {step!r} names no state")
        if kind == "answer":
            if key is not None:
                block(f"{name} answer step {step!r} takes no key")
            return None
        if kind == "insert":
            if not (isinstance(key, tuple) and len(key) == 3 and type(key[0]) is int
                    and key[0] in (0, 1) and key[1] in keys):
                block(f"{name} insert step {step!r} needs (drive, a disk key, a key): "
                       f"only DF1 may change while the game runs, or DF0 after a disk prompt")
            if key[0] == 0:
                if first:
                    block(f"{name} DF0 insert step {step!r} is the first step; only DF1 may "
                           f"change unless a disk prompt precedes it")
                if before not in self.disk_prompts:
                    block(f"{name} DF0 insert step {step!r} comes after {before!r}, which is not "
                           f"a disk prompt; only DF1 may change there")
                if before not in self.strict:
                    block(f"{name} DF0 insert step {step!r} comes after disk prompt {before!r}, "
                           f"which is not a strict state")
                if key[1] == self.mounted[0]:
                    block(f"{name} DF0 insert step {step!r} names the disk already in DF0")
                if key[1] not in self.spares:
                    block(f"{name} DF0 insert step {step!r} names a disk that is not a spare; "
                           f"only a spare may go into DF0")
            key = key[2]
        if not _has_raw_code(key):
            block(f"{name} step {step!r} presses a key with no Amiga raw code")
        if kind == "write" and key.upper() not in (self.control_letter, self.after_letter):
            block(f"{name} write step {step!r} is not the control or after letter")
        if kind != "write" and key.upper() in self._write_letters():
            entry = (key.upper(), state)
            if key.upper() in self.kept_letters and entry in self.plain_keys:
                return entry
            block(f"{name} {kind} step {step!r} presses a save or kept slot letter")
        return None

    def _check_row(self, row, keys, block) -> None:
        if not (isinstance(row, tuple) and len(row) == 4 and isinstance(row[3], int)
                and row[3] >= 1 and isinstance(row[1], tuple) and row[1]):
            block(f"interstitial {row!r} is not (screen, action, waiting_for, limit)")
        action = row[1]
        if action[0] == "keys":
            names = (action[1],) if isinstance(action[1], str) else tuple(action[1])
            if len(action) != 2 or not names or not all(
                    _has_raw_code(k) for k in names):
                block(f"interstitial {row!r} presses a key with no Amiga raw code")
            pressed = names
        elif action[0] == "insert":
            # DF0 is safe to change only on a screen where the game itself asked for a disk, and
            # an interstitial acts only when that screen's guard matches.
            drive_ok = len(action) == 4 and type(action[1]) is int and (
                action[1] == 1 or (action[1] == 0 and row[0] in self.disk_prompts
                                   and row[0] in self.strict and action[2] in self.spares
                                   and action[2] != self.mounted[0]))
            if not (drive_ok and action[2] in keys
                    and _has_raw_code(action[3])):
                block(f"interstitial {row!r} needs (insert, drive, disk key, key): "
                       f"DF1 may change, or DF0 from a spare on a strict disk prompt")
            pressed = (action[3],)
        elif action == ("answer",):
            return
        else:
            block(f"interstitial {row!r} has an unknown action")
        if any(k.upper() in self._write_letters()
               and (k.upper(), row[0]) not in self.interstitial_letters for k in pressed):
            block(f"interstitial {row!r} presses a save or kept slot letter")

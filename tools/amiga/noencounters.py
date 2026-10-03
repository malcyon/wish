"""The Amiga `no_encounters` switch: which script bytes to change, and keeping them changed.

Every Amiga title decides a random encounter in the loaded area script, with a
`RANDOM` statement (opcode `$08`) whose result is compared and branched on.
Changing the opcode to `SAVE` (`$09`) stores the constant instead of a roll, so
the comparison always goes the common way and fixed square fights, which roll
nothing, are untouched.  A script is reloaded on an area change, a crossing and a
saved-game load, so a roll is recognised by a short hash of its statement at the roll
address and changed again whenever a reload brings it back.

The saved game carries the loaded script for Pool, Curse and Pools of Darkness,
so `no_encounters off` comes before any save; it stays off until turned on again.

The class does no I/O of its own: the driver hands it `resolve`, `read` and
`write`, so it runs against a fake, and a `journal` callback that is given
every change still to be put back, before each write and after each restore,
so a driver killed outright leaves a record a later run can repair from.

`WinuaeEncounters` is the same switch under WinUAE, through the debugger pipe,
and `main` is its command line:

    tools/amiga/noencounters.py --holder H --title pool-of-radiance on
    tools/amiga/noencounters.py --holder H keys NP8 NP8 NP2
    tools/amiga/noencounters.py --holder H off
"""

import dataclasses
import hashlib
import json
import os
import pathlib
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import amiga  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: How sure a row is.  CONFIRMED has been run live; PROBABLE was read from the
#: script or the engine and matches a confirmed case; SPECULATIVE is an address
#: nobody has seen hold the value yet.
CONFIRMED, PROBABLE, SPECULATIVE = "CONFIRMED", "PROBABLE", "SPECULATIVE"

GATE, REST = "gate", "rest"


#: The opcode a roll starts with, and what it is changed to: `SAVE` takes the
#: same operands and stores the constant instead of a roll.
RANDOM, SAVE = 0x08, 0x09

#: A roll statement is six bytes: the opcode, its constant and its variable.
STATEMENT = 6


def digest(statement: bytes) -> str:
    """The short hash a row names its roll by, so the table describes the
    statement without holding it."""
    return hashlib.sha256(statement).hexdigest()[:8]


@dataclasses.dataclass(frozen=True)
class Row:
    """One place to change.

    `spec` is a `peek` spec for the first byte.  A gate is recognised as loaded
    when the `STATEMENT` bytes there hash to `digest`; `changes` are `(offset, value)` pairs written
    over the bytes read there, whose originals the switch keeps itself.  A rest
    row has no `changes`: it holds the bytes of `new` where the game writes a
    chance, and puts back what it read.
    """

    title: str
    kind: str
    spec: str
    digest: str
    changes: tuple[tuple[int, int], ...]
    new: bytes
    grade: str
    source: str


_TO_SAVE = ((0, SAVE),)


def _gate(title, spec, digest, grade, source, changes=_TO_SAVE):
    return Row(title, GATE, spec, digest, changes, b"", grade, source)


def _rest(title, spec, new, grade, source):
    return Row(title, REST, spec, "", (), bytes.fromhex(new), grade, source)


#: Pool's buffer is `ecl.dax` at `[data+0xA4] + (A - $9900)`; the other titles'
#: is `[data+pointer] + A`.  The Slums roll (`$9B3A`) has its encounter on the
#: high side, so its constant, two bytes on, is zeroed as well.
ROWS = (
    _gate("pool-of-radiance", "*0xA4+0x7B3", "59ff65e6", PROBABLE,
          "ECL25 wilderness roll at $A0B3, same statement as area 26"),
    _gate("pool-of-radiance", "*0xA4+0x7E7", "59ff65e6", CONFIRMED,
          "area 26 roll at $A0E7, 103 steps in 29.7 minutes live"),
    _gate("pool-of-radiance", "*0xA4+0x5A7", "59ff65e6", PROBABLE,
          "ECL27 wilderness roll at $9EA7, same statement as area 26"),
    _gate("pool-of-radiance", "*0xA4+0x23A", "a57ba371", PROBABLE,
          "Slums roll at $9B3A, ECL14: IF<= 12 EXIT, so the constant is 0",
          changes=((0, SAVE), (2, 0))),
    _gate("curse-of-the-azure-bonds", "*0x5006+0x8739", "9afc9873", PROBABLE,
          "ECL02 roll at $8739: IF> EXIT"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x859D", "dc6e4e48", PROBABLE,
          "ECL10 roll at $859D: IF> EXIT"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x89F6", "dc6e4e48", PROBABLE,
          "The Ruins (area $20, disk 2 ECL block 3) roll at $89F6, reached on an "
          "ordinary square when the [$4C1B] wait is 0: IF> 5 EXIT"),
    _gate("pools-of-darkness", "*0x6EA6+0x82EA", "e43dac29", PROBABLE,
          "GLB block 17 roll at $82EA, reached from the step entry on an "
          "ordinary square: IF> 5 EXIT, else a fight; decoded with Pools of "
          "Darkness' own operand counts"),
    _rest("pool-of-radiance", "*0x9C+0x5A6", "0000", SPECULATIVE,
          "$6DD3 chance word, confirmed on DOS, not run on the Amiga"),
    _rest("curse-of-the-azure-bonds", "*0x3DBE+0xFDA6", "0000", SPECULATIVE,
          "$7ED3 chance word in the $7C00 block"),
    _rest("secret-of-the-silver-blades", "*0x52B4+0xFDA6", "0000", SPECULATIVE,
          "$7ED3 chance word in the $7C00 block"),
    _rest("pools-of-darkness", "*0x57AC+0x2C", "00", SPECULATIVE,
          "variable $2C, the chance byte"),
)


def rows_for(title: str) -> list[Row]:
    return [row for row in ROWS if row.title == title]


class EncounterSwitch:
    """Holds one title's rows changed while the switch is on.

    `resolve(spec)` gives an address or None for a null pointer, `read(address,
    n)` bytes, and `write(address, data)` a dict with an `error` key when the
    write did not stick.  `inside(address, n)` says whether a rest row's
    resolved address may be written.  `speculative` holds the SPECULATIVE rest
    rows too.  The original bytes are read from memory before the first change
    and kept here, so nothing of the script is stored in the repository.

    Every write is read back: bytes that are neither the change nor the
    original are put back to the original and reported.
    """

    def __init__(self, title, resolve, read, write, speculative=False,
                 inside=lambda address, n: True, journal=lambda rows: None):
        self.rows = [r for r in rows_for(title)
                     if speculative or r.grade != SPECULATIVE]
        if not self.rows:
            raise ValueError(f"no encounter rows for {title!r}")
        self.title = title
        self.resolve, self.read, self.write = resolve, read, write
        self.inside = inside
        #: Gates this switch changed: address -> (original bytes, changed bytes).
        self.patched: dict[int, tuple[bytes, bytes]] = {}
        #: Rest values this switch overwrote: address -> what was there.
        self.held: dict[int, bytes] = {}
        #: Gate addresses whose statement did not match, already reported.
        self.refused: set[int] = set()
        #: How many bytes each change covers: address -> span.
        self.spans: dict[int, int] = {}
        #: What each rest row holds: address -> the bytes written.
        self.holding: dict[int, bytes] = {}
        #: The row each changed address belongs to, for the journal.
        self.row_at: dict[int, Row] = {}
        self.journal = journal
        self.active = True

    def outstanding(self) -> list[dict]:
        """Every change still to be put back: `kind`, `spec`, `address`,
        `original` and `changed` bytes in hex, and for a gate the `digest` its
        whole statement had, so a later repair can check it is the same one."""
        rows = [{"kind": GATE, "spec": self.row_at[a].spec, "address": a,
                 "digest": self.row_at[a].digest,
                 "original": o[:self.spans[a]].hex(),
                 "changed": c[:self.spans[a]].hex()}
                for a, (o, c) in self.patched.items()]
        rows += [{"kind": REST, "spec": self.row_at[a].spec, "address": a,
                  "original": o.hex(), "changed": self.holding[a].hex()}
                 for a, o in self.held.items()]
        return rows

    def _record(self) -> None:
        self.journal(self.outstanding())

    def _checked_write(self, address, original, ours) -> dict:
        """Write `ours`, read it back, and put `original` back if it is neither."""
        result = self.write(address, ours)
        got = self.read(address, len(ours))
        if got not in (ours, original[:len(ours)]):
            self.write(address, original[:len(ours)])
            return {**result, "error": f"read back {got.hex()}, neither the "
                                       "change nor the original; original "
                                       "put back"}
        return result

    def apply(self) -> list[dict]:
        """Change every row that is currently loaded; return what was written
        or refused (a refusal is reported once until the bytes match)."""
        done = []
        for row in self.rows:
            address = self.resolve(row.spec)
            if address is None:
                continue
            if row.kind == GATE:
                now = self.read(address, STATEMENT)
                if address in self.patched and now == self.patched[address][1]:
                    continue
                if digest(now) != row.digest:
                    if address not in self.refused:
                        self.refused.add(address)
                        done.append({"row": row.spec, "grade": row.grade,
                                     "refused": f"the {STATEMENT} bytes there "
                                                f"hash to {digest(now)}, not "
                                                f"{row.digest}"})
                    continue
                self.refused.discard(address)
                changed = bytearray(now)
                for offset, value in row.changes:
                    changed[offset] = value
                span = max(offset for offset, _ in row.changes) + 1
                # Recorded first, here and in the journal: a transport error
                # or a kill mid-write leaves the address restorable.
                self.patched[address] = (now, bytes(changed))
                self.spans[address] = span
                self.row_at[address] = row
                self._record()
                result = self._checked_write(address, now, bytes(changed[:span]))
                if "error" in result:
                    del self.patched[address]
                    self._record()
            else:
                if not self.inside(address, len(row.new)):
                    if address not in self.refused:
                        self.refused.add(address)
                        done.append({"row": row.spec, "grade": row.grade,
                                     "refused": f"{address:#x} is outside the "
                                                "expected memory"})
                    continue
                now = self.read(address, len(row.new))
                if now == row.new:
                    continue
                # Whatever the game last wrote is what to put back.
                self.held[address] = now
                self.holding[address] = row.new
                self.row_at[address] = row
                self._record()
                result = self._checked_write(address, now, row.new)
            done.append({"row": row.spec, "grade": row.grade, **result})
        return done

    def release(self) -> list[dict]:
        """Put every changed byte back, without turning the switch off.

        A row that fails to read or write is reported and the rest still go
        back.
        """
        done = []
        for row in self.rows:
            try:
                address = self.resolve(row.spec)
                if address is None:
                    continue
                if row.kind == GATE:
                    if address not in self.patched:
                        continue
                    original, changed = self.patched[address]
                    if self.read(address, len(changed)) != changed:
                        del self.patched[address]
                        self._record()
                        continue        # the script was reloaded already
                    span = max(offset for offset, _ in row.changes) + 1
                    result = self.write(address, original[:span])
                    if "error" not in result:
                        del self.patched[address]
                        self._record()
                else:
                    if (address not in self.held
                            or self.read(address, len(row.new)) != row.new):
                        continue
                    result = self.write(address, self.held[address])
                    if "error" not in result:
                        del self.held[address]
                        self._record()
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            done.append({"row": row.spec, "grade": row.grade, **result})
        return done

    def adopt(self, rows: list[dict]) -> list[dict]:
        """Take over changes an earlier process recorded, where the bytes are
        still that change; give back every row it did not take.

        A row is taken when its spec is one of this switch's rows of the same
        kind and still resolves to its address, and the bytes there read as the
        recorded change (for a gate, with the original put back, as the
        recorded statement).  A row given back is either gone already, put
        back by a reload, or for `restore_row` to judge.
        """
        left = []
        by_spec = {row.spec: row for row in self.rows}
        for entry in rows:
            row = by_spec.get(entry.get("spec"))
            try:
                address = int(entry["address"])
                original = bytes.fromhex(entry["original"])
                changed = bytes.fromhex(entry["changed"])
            except (KeyError, TypeError, ValueError):
                left.append(entry)
                continue
            if (row is None or row.kind != entry.get("kind", GATE)
                    or len(original) != len(changed) or not changed
                    or self.resolve(row.spec) != address):
                left.append(entry)
                continue
            if row.kind == GATE:
                span = max(offset for offset, _ in row.changes) + 1
                now = self.read(address, STATEMENT)
                if (span != len(changed) or now[:span] != changed
                        or entry.get("digest") != row.digest
                        or digest(original + now[span:]) != row.digest):
                    left.append(entry)
                    continue
                self.patched[address] = (original + now[span:], now)
                self.spans[address] = span
            else:
                if changed != row.new or self.read(address, len(changed)) != changed:
                    left.append(entry)
                    continue
                self.held[address] = original
                self.holding[address] = changed
            self.row_at[address] = row
        self._record()
        return left

    @property
    def pending(self) -> bool:
        """Whether a changed byte is still waiting to be put back."""
        return bool(self.patched or self.held)

    def off(self) -> list[dict]:
        """`release`, and the switch stays off.  The `write` it was given must
        read its bytes back, so a row counts as restored only when it is."""
        done = self.release()
        self.active = False
        return done


#: A key line is a save key when it presses the letter that opens the Save
#: picker in the camp and party menus.  **This net is not complete**: a save
#: can start from keys that contain no `s`, and a line of keysyms does not say
#: which menu is up.  The rule is `no_encounters off` before any save, because
#: the saved game carries the loaded script.
SAVE_KEYS = frozenset("sS")


def is_save_key(keys: str) -> bool:
    return any(k in SAVE_KEYS for k in keys.split())


# -- WinUAE ---------------------------------------------------------------
#
# Under WinUAE the switch reads and writes through the debugger pipe
# (`automap.amiga.WinuaePipe`), with `S` dumps and `W` lines inside an
# `AmigaTarget`, and it lives across processes: `amigadrive.py` presses a key a
# call, so `on` leaves the switch on and every later `keys` takes it over from
# the state file until `off`.

#: A row's spec: `*POINTER+OFFSET` reads the big-endian pointer at the
#: data-hunk offset POINTER and adds OFFSET; `+OFFSET` is a data-hunk offset.
SPEC = re.compile(r"^(?:\+(?P<at>\w+)|\*(?P<ptr>\w+)\+(?P<off>\w+))$")

#: What a failed read, write or key press under WinUAE raises.
WINUAE_ERRORS = (ValueError, OSError, TimeoutError, SystemExit, amiga.GuestError)


def parse_spec(spec: str) -> tuple[int | None, int]:
    """`(pointer offset or None, offset)` for a row's spec."""
    found = SPEC.match(spec.strip())
    if found is None:
        raise ValueError(f"{spec!r} is neither +OFFSET nor *POINTER+OFFSET")
    if found["at"] is not None:
        return None, int(found["at"], 0)
    return int(found["ptr"], 0), int(found["off"], 0)


def inside_memory(address: int, n: int) -> bool:
    return any(base <= address and address + n <= base + size
               for base, size in amiga.MEMORY)


def restore_row(read, write, resolve, row: dict) -> dict:
    """Put one recorded change back where it is certainly still there.

    A gate is written only when its bytes read as the recorded change and the
    statement with the original put back hashes to the recorded digest; a rest
    row only when its bytes read as the change and its spec still resolves to
    its address.  Anything else was reloaded or restored since and is left,
    with no write.  A result with an `error` key was not put back.
    """
    address = int(row["address"])
    original = bytes.fromhex(row["original"])
    changed = bytes.fromhex(row["changed"])
    if len(original) != len(changed) or not changed:
        raise ValueError("its original and changed bytes differ in length")
    if row.get("kind", GATE) == GATE:
        statement = read(address, STATEMENT)
        if statement[:len(changed)] != changed:
            return {"address": address, "left": statement.hex()}
        if digest(original + statement[len(original):]) != row.get("digest"):
            return {"address": address, "left": statement.hex(),
                    "why": "another statement is there now"}
    else:
        now = read(address, len(changed))
        if now != changed:
            return {"address": address, "left": now.hex()}
        if resolve(row["spec"]) != address:
            return {"address": address, "left": now.hex(),
                    "why": f"{row['spec']} no longer points here"}
    result = write(address, original)
    if "error" not in result and read(address, len(original)) != original:
        result = {**result, "error": "the original did not read back"}
    return {"address": address, "repaired": "error" not in result, **result}


def winuae_state_path() -> pathlib.Path:
    """Where the WinUAE switch keeps its state: one file, because the guest
    runs one WinUAE and every run against it must find what an earlier one left."""
    return scratch.cache_dir("noencounters", "winuae.json")


class StateError(ValueError):
    """The WinUAE state file exists and cannot be read."""


class WinuaeState:
    """The WinUAE switch's record on disk.

    `on`, the `title` and `speculative` choice it was turned on with, the
    `anchor_base` and `data_base` where that title was last found, and `rows`:
    every change still to be put back, as `EncounterSwitch.outstanding` gives
    it plus its `title`.  Rewritten before every change and after every
    restore, so a process killed outright leaves the originals for the next.
    """

    EMPTY = {"on": False, "title": None, "speculative": False,
             "anchor_base": None, "data_base": None, "rows": []}

    def __init__(self, path: pathlib.Path | None = None):
        self.path = pathlib.Path(path) if path is not None else winuae_state_path()

    def load(self) -> dict:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return dict(self.EMPTY, rows=[])
        except OSError as exc:
            raise StateError(self._unreadable(exc)) from exc
        try:
            state = json.loads(text)
            if not isinstance(state, dict):
                raise ValueError("it is not a record")
            state = {**self.EMPTY, **state}
            rows = state["rows"]
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                raise ValueError("its rows are not a list of records")
            if not isinstance(state["on"], bool):
                raise ValueError("`on` is not true or false")
        except (ValueError, TypeError) as exc:
            raise StateError(self._unreadable(exc)) from exc
        return state

    def _unreadable(self, exc) -> str:
        return (f"the encounter state {self.path} cannot be read ({exc}), so a "
                "change may still be in the game: check the game, then delete "
                "the file")

    def save(self, state: dict) -> None:
        scratch.ensure(self.path.parent)
        temp = self.path.with_suffix(f".{os.getpid()}.tmp")
        temp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temp, self.path)


class PipeMemory:
    """The switch's `resolve`, `read` and `write` over an `AmigaTarget` on
    WinUAE's pipe, with each pass's reads gathered into one round trip.

    `prefetch(rows)` reads, in one batch, every pointer the rows go through and
    each row's bytes at the address that pointer gave last time; a pointer that
    moved costs a second batch.  Reads are served from what was fetched where
    it covers them; a write drops every fetched block it overlaps, so its
    read-back goes to the machine.  `clear()` ends the pass.
    """

    def __init__(self, target):
        self.target = target
        self.blocks: dict[tuple[int, int], bytes] = {}
        #: The value each pointer offset held when last read.
        self.pointers: dict[int, int] = {}
        #: Pointer offsets read in this pass.
        self.fresh: set[int] = set()

    def _row_length(self, row: Row) -> int:
        return STATEMENT if row.kind == GATE else len(row.new)

    def _address(self, row: Row, pointers: dict[int, int]) -> int | None:
        pointer, offset = parse_spec(row.spec)
        if pointer is None:
            return self.target.data_base + offset
        value = pointers.get(pointer)
        return None if not value else value + offset

    def fetch(self, blocks: list[tuple[int, int]]) -> None:
        """Read `blocks` in one round trip and keep them for this pass."""
        blocks = [b for b in dict.fromkeys(blocks) if inside_memory(*b)]
        if blocks:
            self.blocks.update(zip(blocks, self.target.read_blocks(blocks), strict=True))

    def prefetch(self, rows: list[Row]) -> None:
        pointers = sorted({p for p, _ in (parse_spec(r.spec) for r in rows)
                           if p is not None})
        heads = [(self.target.data_base + p, 4) for p in pointers]
        guesses = [(a, self._row_length(r)) for r in rows
                   if (a := self._address(r, self.pointers)) is not None]
        self.fetch(heads + guesses)
        before = dict(self.pointers)
        for p, head in zip(pointers, heads, strict=True):
            if head in self.blocks:
                self.pointers[p] = int.from_bytes(self.blocks[head], "big")
                self.fresh.add(p)
        moved = [r for r in rows if self._address(r, self.pointers)
                 != self._address(r, before)]
        self.fetch([(a, self._row_length(r)) for r in moved
                    if (a := self._address(r, self.pointers)) is not None])

    def clear(self) -> None:
        self.blocks.clear()
        self.fresh.clear()

    def resolve(self, spec: str) -> int | None:
        pointer, offset = parse_spec(spec)
        if pointer is None:
            return self.target.data_base + offset
        if pointer not in self.fresh:
            self.pointers[pointer] = int.from_bytes(
                self.read(self.target.data_base + pointer, 4), "big")
            self.fresh.add(pointer)
        value = self.pointers[pointer]
        return None if value == 0 else value + offset

    def read(self, address: int, n: int) -> bytes:
        for (start, length), blob in self.blocks.items():
            if start <= address and address + n <= start + length:
                return blob[address - start:address - start + n]
        return self.target.read(address, n)

    def write(self, address: int, data: bytes) -> dict:
        end = address + len(data)
        for start, length in list(self.blocks):
            if start < end and address < start + length:
                del self.blocks[(start, length)]
        try:
            self.target.write(address, bytes(data))
        except WINUAE_ERRORS as exc:
            return {"address": address, "error": f"{type(exc).__name__}: {exc}"}
        return {"address": address, "new": bytes(data).hex()}


class WinuaeEncounters:
    """`no_encounters` for a game under WinUAE: `on`, `off`, and `keys`.

    `target` is an `AmigaTarget` over `WinuaePipe` for `title`'s layout, not yet
    located; `lane_check()` proves this run holds the lane and runs once,
    before the first read; `press(name)` presses one `amigadrive` key.
    `state` is the `WinuaeState`.

    `on` puts back whatever an earlier run left, then changes every loaded row
    and records the switch as on.  `keys` presses keys, refusing the whole line
    when one is a save key while the switch is on or a change may be in the
    game, and while the switch is on takes it over and applies it again before
    each key.  `off` puts every recorded change back.  The switch stays on
    across processes until `off`, so an interrupted `keys` leaves it on and
    recorded; an interrupted `on` or `off` leaves every change recorded, and
    the next command takes it over or puts it back.
    """

    def __init__(self, title: str, target, *, state: WinuaeState | None = None,
                 lane_check=lambda: None, press=lambda name: None):
        if not rows_for(title):
            raise ValueError(f"no encounter rows for {title!r}")
        self.title = title
        self.target = target
        self.state = state or WinuaeState()
        self.lane_check = lane_check
        self.press = press
        self.memory = PipeMemory(target)
        self.switch: EncounterSwitch | None = None
        self.checked = False
        #: Rows of another title, kept in the file and left alone.
        self.foreign: list[dict] = []
        #: This title's rows that could not be put back, still recorded.
        self.stuck: list[dict] = []
        self.speculative = False
        #: `(anchor_base, data_base)` as the state file last had them.
        self.bases: tuple[int | None, int | None] = (None, None)

    def _load(self) -> dict:
        saved = self.state.load()
        if saved.get("title") == self.title:
            self.bases = (saved.get("anchor_base"), saved.get("data_base"))
        return saved

    # -- the state file --------------------------------------------------

    def _save(self, on: bool, rows: list[dict]) -> None:
        located = self.target.data_base is not None
        self.state.save({
            "on": on, "title": self.title, "speculative": self.speculative,
            "anchor_base": self.target.anchor_base if located else self.bases[0],
            "data_base": self.target.data_base if located else self.bases[1],
            "rows": self.foreign + [{**r, "title": self.title} for r in rows + self.stuck]})

    def _journal(self, rows: list[dict]) -> None:
        self._save(True, rows)

    # -- reaching the game -----------------------------------------------

    def _ready(self, saved: dict) -> None:
        """Check the lane, and find the game: where `saved` says if its anchor
        is still there, otherwise by a sweep."""
        if not self.checked:
            self.lane_check()
            self.checked = True
        if self.target.data_base is not None:
            return
        layout = self.target.layout
        anchor, data = saved.get("anchor_base"), saved.get("data_base")
        if saved.get("title") == self.title and isinstance(anchor, int) \
                and isinstance(data, int):
            at = anchor + layout.anchor_offset
            blocks = [(at, len(layout.anchor)), (anchor - 8, 4), (anchor - 4, 4),
                      (data - 8, 4)]
            self.memory.fetch(blocks)
            try:
                if (self.memory.read(at, len(layout.anchor)) == layout.anchor
                        and amiga.data_base_for(self.memory.read, layout,
                                                anchor) == data):
                    self.target.anchor_base, self.target.data_base = anchor, data
                    return
            except amiga.PipeError:
                raise
            except amiga.GuestError:
                pass    # moved: a new boot, found again below
            finally:
                self.memory.clear()
        self.target.locate()

    def _split(self, saved: dict) -> list[dict]:
        """This title's recorded rows; the others are kept as `foreign`."""
        self.foreign = [r for r in saved["rows"] if r.get("title") != self.title]
        return [r for r in saved["rows"] if r.get("title") == self.title]

    def _new_switch(self) -> EncounterSwitch:
        return EncounterSwitch(
            self.title, self.memory.resolve, self.memory.read, self.memory.write,
            speculative=self.speculative, inside=inside_memory,
            journal=self._journal)

    def _restore(self, rows: list[dict]) -> list[dict]:
        """`restore_row` for each row; the rows that failed stay in `stuck`."""
        self.memory.fetch([(int(r["address"]),
                            STATEMENT if r.get("kind", GATE) == GATE
                            else len(bytes.fromhex(r["changed"])))
                           for r in rows if isinstance(r.get("address"), int)
                           and isinstance(r.get("changed"), str)])
        done, self.stuck = [], []
        try:
            for row in rows:
                try:
                    result = restore_row(self.memory.read, self.memory.write,
                                         self.memory.resolve, row)
                except (*WINUAE_ERRORS, KeyError, TypeError) as exc:
                    result = {"row": row, "error": f"{type(exc).__name__}: {exc}"}
                if "error" in result:
                    self.stuck.append(row)
                done.append(result)
        finally:
            self.memory.clear()
        return done

    def _take_over(self, saved: dict) -> list[dict]:
        """Build the switch from a state that is on, adopting its rows; the
        rows it cannot adopt are put back."""
        self.speculative = bool(saved.get("speculative"))
        self.switch = self._new_switch()
        self.memory.prefetch(self.switch.rows)
        try:
            left = self.switch.adopt(self._split(saved))
        finally:
            self.memory.clear()
        done = self._restore(left) if left else []
        self._save(True, self.switch.outstanding())
        return done

    def _apply(self) -> list[dict]:
        self.memory.prefetch(self.switch.rows)
        try:
            return self.switch.apply()
        finally:
            self.memory.clear()

    # -- the commands ----------------------------------------------------

    def on(self, speculative: bool = False) -> dict:
        """Put back what an earlier run left, change every loaded row, and
        record the switch as on."""
        saved = self._load()
        if saved.get("title") not in (None, self.title) and saved["on"]:
            raise ValueError(f"no_encounters is on for {saved['title']}; "
                             "`off` first")
        self._ready(saved)
        repaired = self._restore(self._split(saved))
        if self.stuck:
            self._save(False, [])
            raise ValueError("a recorded change is still in the game and was "
                             "not put back; `off` tries again")
        self.speculative = speculative
        self.switch = self._new_switch()
        self._save(True, [])
        try:
            done = self._apply()
        except WINUAE_ERRORS:
            # Whatever did not go back stays recorded, so a save is refused
            # and the next `on` or `off` tries again.
            self.switch.off()
            self._save(False, self.switch.outstanding())
            self.switch = None
            raise
        return {"action": "on", "repaired": repaired, "rows": done,
                "held": [r.spec for r in self.switch.rows]}

    def off(self) -> dict:
        """Put every recorded change back and record the switch as off."""
        saved = self._load()
        if saved.get("title") not in (None, self.title):
            raise ValueError(f"the state is for {saved['title']}, not "
                             f"{self.title}")
        own = self._split(saved)
        if self.switch is not None:
            own = self.switch.outstanding()
            self.switch = None
        if not own:
            self._save(False, [])
            return {"action": "off", "rows": []}
        self._ready(saved)
        done = self._restore(own)
        self._save(False, [])
        result = {"action": "off", "rows": done}
        if self.stuck:
            result["error"] = ("no_encounters off did not restore every row; "
                               "the script is still changed")
        return result

    def keys(self, names: list[str]) -> dict:
        """Press `names` in order, applying the switch again before each while it
        is on; refuse the whole line, pressing nothing, when one is a save key
        while the switch is on or a change may still be in the game."""
        try:
            saved = self._load()
        except StateError as exc:
            if is_save_key(" ".join(names)):
                return {"action": "keys", "refused": str(exc), "pressed": []}
            raise
        own = [r for r in saved["rows"] if r.get("title") == self.title]
        if is_save_key(" ".join(names)) and (saved["on"] or own):
            return {"action": "keys", "pressed": [],
                    "refused": ("no_encounters is on or a change it made is "
                                "still in the game, and a save carries the "
                                "changed script: turn it off first")}
        if saved["on"] and saved.get("title") != self.title:
            raise ValueError(f"no_encounters is on for {saved['title']}, not "
                             f"{self.title}")
        result = {"action": "keys", "pressed": [], "applied": []}
        if saved["on"] and self.switch is None:
            self._ready(saved)
            result["repaired"] = self._take_over(saved)
        for name in names:
            if self.switch is not None:
                done = self._apply()
                if done:
                    result["applied"].append({"before": name, "rows": done})
            self.press(name)
            result["pressed"].append(name)
        return result


def main(argv: list[str] | None = None) -> int:
    """`no_encounters` against WinUAE, from Linux through `winvm`."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="Switch an Amiga Gold Box title's random encounters off and "
                    "on under WinUAE, and press keys while it is off.  Never for "
                    "conversion proof; `off` before any save.")
    parser.add_argument("--holder", help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--title", choices=sorted(amiga.MACHINES),
                        help="the running title (for keys and off, the state's)")
    parser.add_argument("--settle", type=float, default=1.5,
                        help="seconds to wait after each key (default 1.5)")
    sub = parser.add_subparsers(dest="command", required=True)
    on = sub.add_parser("on", help="change every loaded roll, and keep it changed")
    on.add_argument("--speculative", action="store_true",
                    help="hold the SPECULATIVE rest rows too")
    sub.add_parser("off", help="put every changed byte back")
    keys = sub.add_parser("keys", help="press amigadrive keys, applying the switch "
                                       "before each while it is on")
    keys.add_argument("names", nargs="+")
    sub.add_parser("status", help="print the state file")
    args = parser.parse_args(argv)

    state = WinuaeState()
    try:
        saved = state.load()
    except StateError as exc:
        if args.command != "keys":
            print(json.dumps({"action": args.command, "error": str(exc)}))
            return 1
        saved = dict(WinuaeState.EMPTY)
    if args.command == "status":
        print(json.dumps(saved, indent=1))
        return 0
    title = args.title or saved.get("title")
    if title is None:
        parser.error("--title is needed: the state names no title")
    if args.holder is None:
        parser.error("--holder is needed")
    from tools.amiga import amigadrive  # noqa: PLC0415

    pipe = amiga.WinuaePipe()
    enc = WinuaeEncounters(
        title, amiga.AmigaTarget(pipe, amiga.MACHINES[title]), state=state,
        lane_check=lambda: pipe.drives(args.holder),
        press=lambda name: amigadrive.press(args.holder, name, args.settle))
    try:
        if args.command == "on":
            result = enc.on(args.speculative)
        elif args.command == "off":
            result = enc.off()
        else:
            result = enc.keys(args.names)
    except WINUAE_ERRORS as exc:
        print(json.dumps({"action": args.command,
                          "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(result))
    return 1 if "error" in result or "refused" in result else 0


if __name__ == "__main__":
    sys.exit(main())

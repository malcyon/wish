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
`write`, so it runs against a fake.
"""

import dataclasses
import hashlib

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
    _gate("pools-of-darkness", "*0x6EA6+0x82EA", "e43dac29", PROBABLE,
          "GLB block 17 roll at $82EA: IF> EXIT"),
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
                 inside=lambda address, n: True):
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
        self.active = True

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
                # Recorded first: a transport error mid-write leaves the
                # address restorable.
                self.patched[address] = (now, bytes(changed))
                result = self._checked_write(address, now, bytes(changed[:span]))
                if "error" in result:
                    del self.patched[address]
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
                        continue        # the script was reloaded already
                    span = max(offset for offset, _ in row.changes) + 1
                    result = self.write(address, original[:span])
                    if "error" not in result:
                        del self.patched[address]
                else:
                    if (address not in self.held
                            or self.read(address, len(row.new)) != row.new):
                        continue
                    result = self.write(address, self.held[address])
                    if "error" not in result:
                        del self.held[address]
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            done.append({"row": row.spec, "grade": row.grade, **result})
        return done

    @property
    def pending(self) -> bool:
        """Whether a changed byte is still waiting to be put back."""
        return bool(self.patched or self.held)

    def off(self) -> list[dict]:
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

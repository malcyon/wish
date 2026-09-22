#!/usr/bin/env python3
"""Which bytes of a DOS effect node each title's engine reads, per effect id.

    tools/dos/dosaffectreads.py                    # all three titles, summary
    tools/dos/dosaffectreads.py --title curse --ids 5,45,89
    tools/dos/dosaffectreads.py --title pool --items

A DOS Gold Box effect node is nine bytes -- id, duration `u16`, a value byte
(3), a flag byte (4) and the next pointer (`docs/162-spc-permanence.md`).  A
C64 trait slot carries only the id, so a converter that writes one as a DOS
node has to supply bytes 3 and 4.  That is safe for an id exactly when
nothing in the engine reads them for that id, and this reads the engine's
own code to say which ids those are.  Static throughout, from the player's
own `GAME.OVR` and `START.EXE`; prints addresses and verdicts only.

Everything is found by instruction pattern rather than by address, so one run
covers Pool of Radiance, Curse of the Azure Bonds and Secret of the Silver
Blades:

* **the handler table** -- `tools/dos/dosracialseed.py`'s dispatcher, the
  `shl di,1 / shl di,1 / lcall [di + table]` with the most code-filled
  entries, cut at the first unfilled id and at the one far pointer the
  dispatcher calls instead of the table when a global is set (Curse and
  Silver Blades' item-grant hook);
* **`find_affect(var node, id, player)`** -- the far call most often reached
  with `mov al, imm / push ax / lea di, [bp - n] / push ss / push di`;
* **`remove_affect`** -- the routine in the dispatcher's own unit that tests
  `es:[di + 4]` and calls the dispatcher.

`pointer_uses` follows one far-pointer argument through a routine: every
`es:[di + n]` made through it, every copy of it into a local, and every call
it is handed to, recursing into the callee at the matching argument slot.
A handler's node is its `[bp + 8]`; a `find_affect` caller's is the local
whose address it passed.  The walk is a linear sweep from the entry to the
first `retf`, which is how every Turbo Pascal routine in these overlays is
laid out, and it raises rather than under-reports when a call it must follow
cannot be resolved.

`item_powers` reads how a readied magical item (item byte `0x3E` >= `0x80`)
reaches `add_affect`: Pool of Radiance dispatches on byte `0x3E` itself, the
later two route power 0 through the hook and nothing else.

`apply_walk` and `cancels` read what an effect protects against: the apply
routine parks the incoming id in a global, walks check list 9 over the
target, and each handler on it cancels by handing a helper the ids it
blocks (`tools/dos/dosaffectreads.py --title silver-blades --apply`).

`saving_throw`, `spell_effect_routine`, `spell_rows` and `class_gate` read
the rest of what stands between a spell and its target: the saving throw's
record bytes and list 12, the 16-byte spell table row that names the effect
and the save, and a switch on the record's class inside a spell's own routine
(`--spells 29,68`).
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import pathlib
import re
import struct
import sys

import capstone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from tools.dos import dosovrmap, dosracialseed, unexepack  # noqa: E402

TITLES = {"pool": "POOLRAD", "curse": "CURSE", "silver-blades": "SECRET"}

#: `mov al, imm / push ax / lea di, [bp - n] / push ss / push di / lcall`:
#: a constant id and the address of a local, the call `find_affect` gets.
FIND_CALL = re.compile(rb"\xb0.\x50\x8d\x7e.\x16\x57\x9a(....)", re.S)
FAR_CALL = re.compile(rb"\x9a(....)", re.S)
DISP = re.compile(r"es:\[(di|si|bx)(?: \+ (0x[0-9a-f]+|\d+))?\]")
BP = re.compile(r"\[bp ([+-]) (0x[0-9a-f]+|\d+)\]")
WRITES = {"mov", "inc", "dec", "add", "sub", "or", "and", "xor", "shl", "shr",
          "not", "neg", "sar", "rol", "ror", "adc", "sbb"}


def _md() -> capstone.Cs:
    return capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)


def _bp(op: str) -> int | None:
    m = BP.search(op)
    if not m:
        return None
    n = int(m.group(2), 0)
    return n if m.group(1) == "+" else -n


def _slot_text(disp: int) -> str:
    n = abs(disp)
    return f"[bp {'+' if disp >= 0 else '-'} {n if n < 10 else hex(n)}]"


@dataclasses.dataclass
class Engine:
    """One title's two code files and the routines found in them."""

    title: str
    ovr: bytes
    img: bytes
    units: list
    dispatcher: int = 0
    table: int = 0
    hook: int | None = None
    handlers: dict = dataclasses.field(default_factory=dict)
    find_affect: tuple = ()
    find_affect_at: tuple = ()
    remove_affect: tuple = ()
    add_affect: tuple = ()
    chain: int = 0

    @property
    def effect_ids(self) -> list[int]:
        """The table's ids that name an effect rather than an item power.

        Pool of Radiance dispatches a readied item on its power byte, so its
        table's slots from `0x80` are item handlers; the later titles use the
        hook and every slot is an effect.
        """
        return [e for e in self.handlers if self.hook is not None or e < 0x80]

    def code(self, where: str) -> bytes:
        return self.ovr if where == "GAME.OVR" else self.img

    def resolve(self, seg: int, off: int) -> tuple[str, int]:
        where, at = dosovrmap.resolve(self.units, seg, off)
        if at is None:
            raise ValueError(f"{self.title}: {seg:04x}:{off:04x} is no overlay entry")
        return where, at


def load(game: pathlib.Path, title: str = "") -> Engine:
    """Read `GAME.OVR` and `START.EXE` from `game` and find the routines."""
    ovr = (game / "GAME.OVR").read_bytes()
    img, _ = unexepack.unpack((game / "START.EXE").read_bytes())
    eng = Engine(title or game.name, ovr, img, dosovrmap.units(img, len(ovr)))
    _find_dispatch(eng)
    _find_find_affect(eng)
    _find_remove_affect(eng)
    _find_add_affect(eng)
    return eng


def body(code: bytes, at: int, limit: int = 0x1400) -> list:
    """The instructions from `at` to the first `retf`, inclusive."""
    out = []
    for insn in _md().disasm(code[at:at + limit], at):
        out.append(insn)
        if insn.mnemonic == "retf":
            return out
    raise ValueError(f"no retf within 0x{limit:x} of 0x{at:x}")


def _find_dispatch(eng: Engine) -> None:
    base = dosracialseed.dispatch_table(eng.ovr)
    eng.table = base
    for m in re.finditer(re.escape(dosracialseed.DISPATCH), eng.ovr):
        if struct.unpack_from("<H", eng.ovr, m.end())[0] == base:
            eng.dispatcher = eng.ovr.rfind(b"\x55\x89\xe5", 0, m.start())
    # the dispatcher's other far call, `lcall [imm]`, taken when a global is set
    for insn in body(eng.ovr, eng.dispatcher):
        hook = re.fullmatch(r"(?:dword ptr )?\[(0x[0-9a-f]+)\]", insn.op_str)
        if insn.mnemonic == "lcall" and hook:
            eng.hook = int(hook.group(1), 0)
    fills = dosracialseed._fills(eng.ovr, base)
    for eid in range(1, 256):
        if eid not in fills or base + 4 * eid == eng.hook:
            break
        eng.handlers[eid] = eng.resolve(*fills[eid])
    if eng.hook is not None:
        slot = (eng.hook - base) // 4
        eng.hook_handler = eng.resolve(*fills[slot]) if slot in fills else None
    else:
        eng.hook_handler = None


def _find_find_affect(eng: Engine) -> None:
    count = collections.Counter()
    for m in FIND_CALL.finditer(eng.ovr):
        off, seg = struct.unpack("<HH", m.group(1))
        count[(seg, off)] += 1
    for (seg, off), _ in count.most_common(4):
        where, at = eng.resolve(seg, off)
        ins = body(eng.code(where), at)
        text = [f"{i.mnemonic} {i.op_str}" for i in ins]
        # the walk: head from the record, then `cmp al, byte ptr [bp + 0xa]`
        if "cmp al, byte ptr [bp + 0xa]" in text and "retf 0xa" in text:
            eng.find_affect = (seg, off)
            eng.find_affect_at = (where, at)
            head = next(i for i in ins if "es:[di + 0x" in i.op_str)
            eng.chain = int(DISP.search(head.op_str).group(2), 0)
            return
    raise ValueError(f"{eng.title}: no find_affect")


def _find_remove_affect(eng: Engine) -> None:
    unit = dosovrmap.unit_of(eng.units, eng.dispatcher)
    for stub, code in unit["ents"]:
        at = unit["fileoff"] + code
        try:
            ins = body(eng.ovr, at)
        except ValueError:
            continue
        text = [f"{i.mnemonic} {i.op_str}" for i in ins]
        if "cmp byte ptr es:[di + 4], 0" in text and "retf 0xa" in text:
            eng.remove_affect = (unit["seg"], stub)
            eng.remove_affect_at = at
            flag = next(i for i in ins if i.op_str == "byte ptr es:[di + 4], 0")
            eng.remove_flag_test = flag.address
            return
    raise ValueError(f"{eng.title}: no remove_affect")


def _find_add_affect(eng: Engine) -> None:
    """The entry of the dispatcher's unit that allocates nine bytes and links them."""
    unit = dosovrmap.unit_of(eng.units, eng.dispatcher)
    for stub, code in unit["ents"]:
        try:
            ins = body(eng.ovr, unit["fileoff"] + code)
        except ValueError:
            continue
        if any(i.op_str == "ax, 9" for i in ins[:6]) and \
                any(i.op_str.endswith("es:[di + 5], ax") for i in ins):
            eng.add_affect = (unit["seg"], stub)
            eng.add_affect_at = unit["fileoff"] + code
            return
    raise ValueError(f"{eng.title}: no add_affect")


@dataclasses.dataclass
class Uses:
    """What one routine does with a far pointer to an effect node."""

    access: set = dataclasses.field(default_factory=set)   # (byte, "r"/"w", site)
    removes: list = dataclasses.field(default_factory=list)  # remove_affect sites
    dispatches: list = dataclasses.field(default_factory=list)  # (id | None, site)
    compares: set = dataclasses.field(default_factory=set)  # ids tested at byte 0

    def bytes_read(self) -> set:
        return {b for b, _, _ in self.access}

    def merge(self, other: "Uses") -> None:
        self.access |= other.access
        self.removes += other.removes
        self.dispatches += other.dispatches
        self.compares |= other.compares


def _call_target(eng: Engine, where: str, insn, prev) -> tuple[str, int, int] | None:
    """`(where, file offset, first-argument slot)` of a call, or None."""
    direct = re.fullmatch(r"(0x[0-9a-f]+|\d+)(?:, (0x[0-9a-f]+|\d+))?", insn.op_str)
    if direct is None:
        return None                 # through memory or a register
    if insn.mnemonic == "lcall":
        w, at = eng.resolve(int(direct.group(1), 0), int(direct.group(2), 0))
        return w, at, 6
    far = prev is not None and prev.mnemonic == "push" and prev.op_str == "cs"
    return where, int(direct.group(1), 0), 6 if far else 4


def pointer_uses(eng: Engine, where: str, start: int, slot: int | None,
                 depth: int = 0, seen: set | None = None,
                 whole: bool = False) -> Uses:
    """Follow the far pointer stored at `[bp + slot]` from `start` to `retf`.

    `slot=None` starts with the pointer in `ax`, which is how a routine that
    walks the chain holds the head it has just read out of the record.
    `whole=True` reads a whole routine whose only writer of the slot is
    `find_affect`, so passing the slot's address on does not end the walk.

    Tracks the pointer through `les reg, [slot]` (an access is `es:[reg + n]`
    until `reg` or `es` is rewritten or a call intervenes), through copies of
    it into another local via `ax`, and into a callee it is pushed for, at
    the argument slot the pushes after it put it in.  A hand-off to the
    dispatcher or to `remove_affect` is recorded rather than followed.
    """
    seen = set() if seen is None else seen
    key = (where, start, slot)
    out = Uses()
    if key in seen or depth > 6:
        return out
    seen.add(key)
    slots = set() if slot is None else {slot}
    reg = None            # es:reg points at the node
    ax_node = slot is None  # ax holds the node's offset word
    pending = None        # bytes pushed after the node, or None
    consts: list = []     # the value each `push ax` pushed since the last call
    last = None           # what al/ax was last loaded with, if a constant
    prev = None
    for insn in body(eng.code(where), start):
        m, ops = insn.mnemonic, insn.op_str
        d = _bp(ops)
        dest = ops.split(",")[0]
        if m in ("call", "lcall"):
            if pending is not None:
                tgt = _call_target(eng, where, insn, prev)
                if tgt is None:
                    raise ValueError(f"{eng.title}: node handed to an indirect "
                                     f"call at 0x{insn.address:x}")
                w, at, first = tgt
                if (w, at) == ("GAME.OVR", eng.dispatcher):
                    out.dispatches.append((consts[0] if consts else None, insn.address))
                elif (w, at) == ("GAME.OVR", eng.remove_affect_at):
                    out.removes.append(insn.address)
                else:
                    out.merge(pointer_uses(eng, w, at, first + pending,
                                           depth + 1, seen))
            reg, ax_node, pending, consts, last = None, False, None, [], None
            prev = insn
            continue
        hit = DISP.search(ops)
        if reg is not None and hit and hit.group(1) == reg:
            n = int(hit.group(2), 0) if hit.group(2) else 0
            write = m in WRITES and ops.startswith(("byte ptr es:", "word ptr es:"))
            wide = "word ptr es:" in ops or m == "les"
            for b in (n, n + 1) if wide else (n,):
                out.access.add((b, "w" if write else "r", insn.address))
            imm = re.search(r"\], (0x[0-9a-f]+|\d+)$", ops)
            if n == 0 and m == "cmp" and imm:
                out.compares.add(int(imm.group(1), 0))
        # the pointer's own movements
        if m == "lea" and d in slots and not whole:
            slots.discard(d)              # its address goes to a callee that rewrites it
        if m == "push" and ops.startswith("word ptr [bp") and d in slots:
            pending = 0
        elif m == "push" and ops == "di" and reg == "di" and prev is not None \
                and prev.op_str == "es":
            pending = 0
        elif m == "push" and pending is not None and ops != "cs":
            pending += 2
        if m == "push" and ops == "ax":
            consts.append(last)
        if m == "mov" and ops.endswith(", ax") and ax_node and d is not None:
            slots.add(d)
        # what this instruction rewrites
        if m == "les":
            reg = dest if d in slots and dest != "ax" else None
        elif dest == "es" and m in WRITES | {"pop"}:
            reg = None
        elif dest == reg and m in WRITES | {"lea", "pop", "xchg"}:
            reg = None
        if dest in ("ax", "al", "ah") and m in WRITES | {"les", "lea", "pop", "xchg"}:
            ax_node = d in slots and (m == "les" or ops.startswith("ax, word ptr"))
            imm = re.fullmatch(r"a[lx], (0x[0-9a-f]+|\d+)", ops)
            last = 0 if (m == "xor" and ops == "ax, ax") else \
                int(imm.group(1), 0) if (m == "mov" and imm) else None
        elif m in ("cbw", "cwde"):
            ax_node = False
        prev = insn
    return out


def chain_walkers(eng: Engine) -> dict[tuple[str, int], Uses]:
    """Every routine that reads a character's chain head, and what it reads.

    The head is the far pointer at record offset `eng.chain`, read as
    `mov ax, word ptr es:[di + chain]` or `les ax, ptr es:[di + chain]`.
    Keyed by `(file, routine start)`; `Uses.compares` holds the ids the
    routine tests a node's byte 0 against, which is how a reader of byte 3
    here is attributed to an id.
    """
    ch = eng.chain
    disp = bytes((0x45, ch)) if ch < 0x80 else b"\x85" + struct.pack("<H", ch)
    pats = [b"\x26\x8b" + disp, b"\x26\xc4" + disp]
    out: dict = {}
    for where in ("GAME.OVR", "START.img"):
        code = eng.code(where)
        for pat in pats:
            for m in re.finditer(re.escape(pat), code):
                start = code.rfind(b"\x55\x89\xe5", 0, m.start())
                try:
                    ins = body(code, start)
                except ValueError:
                    continue
                if not any(i.address == m.start() for i in ins):
                    continue            # not an instruction boundary from here
                uses = pointer_uses(eng, where, m.start() + len(pat), None)
                out.setdefault((where, start), Uses()).merge(uses)
    return out


def handler_uses(eng: Engine, eid: int) -> Uses:
    """What the handler for `eid` does with its node argument, `[bp + 8]`."""
    where, at = eng.handlers[eid]
    uses = pointer_uses(eng, where, at, 8)
    for sub, _ in list(uses.dispatches):
        if sub is not None and sub in eng.handlers and sub != eid:
            uses.merge(handler_uses(eng, sub))
    return uses


def find_affect_sites(eng: Engine) -> list[tuple[str, int, int | None, int | None]]:
    """Every call to `find_affect`: `(file, site, id or None, local slot or None)`.

    Far calls in both files, plus near calls in find_affect's own file.
    """
    seg, off = eng.find_affect
    fwhere, fat = eng.find_affect_at
    pat = b"\x9a" + struct.pack("<HH", off, seg)
    sites = [("GAME.OVR", m.start()) for m in re.finditer(re.escape(pat), eng.ovr)]
    sites += [("START.img", m.start()) for m in re.finditer(re.escape(pat), eng.img)]
    code = eng.code(fwhere)
    for p in range(len(code) - 3):
        if code[p] == 0xE8 and p + 3 + struct.unpack_from("<h", code, p + 1)[0] == fat:
            sites.append((fwhere, p))
    out = []
    for where, site in sites:
        back = dosovrmap.window(eng.code(where), site, 40)
        text = [f"{i.mnemonic} {i.op_str}" for i in back if i.address < site]
        slot = eid = None
        for k in range(len(text) - 1, -1, -1):
            if text[k].startswith("lea di, [bp"):
                slot = _bp(text[k])
                break
        for k in range(len(text) - 1, 0, -1):
            if text[k] == "push ax":
                if re.fullmatch(r"mov al, (0x[0-9a-f]+|\d+)", text[k - 1]):
                    eid = int(text[k - 1][8:], 0)
                break
        out.append((where, site, eid, slot))
    return sorted(out, key=lambda s: (s[0], s[1]))


def caller_uses(eng: Engine) -> dict:
    """id (None for a computed id) -> Uses merged over every caller."""
    out: dict = collections.defaultdict(Uses)
    sites = [s for s in find_affect_sites(eng) if s[3] is not None]
    ids_in: dict = collections.defaultdict(set)
    for where, site, eid, slot in sites:
        start = eng.code(where).rfind(b"\x55\x89\xe5", 0, site)
        ids_in[(where, start, slot)].add(eid)
    for where, site, eid, slot in sites:
        code = eng.code(where)
        start = code.rfind(b"\x55\x89\xe5", 0, site)
        if len(ids_in[(where, start, slot)]) == 1:
            # one id owns this local in this routine: read the whole routine,
            # so a loop that reads the node above the call is not missed
            out[eid].merge(pointer_uses(eng, where, start, slot, whole=True))
        size = 5 if code[site] == 0x9A else 3
        out[eid].merge(pointer_uses(eng, where, site + size, slot))
    return out


@dataclasses.dataclass
class Verdict:
    """Who reads which bytes of one id's node, apart from the generic readers."""

    handler: int
    handler_reads: set
    caller_reads: set
    walker_reads: set
    removes: bool

    @property
    def value_read(self) -> bool:
        """Does anything id-specific read or write byte 3 or byte 4?"""
        return bool((self.handler_reads | self.caller_reads | self.walker_reads) & {3, 4})


def dispel_routine(eng: Engine, walkers: dict | None = None) -> dict:
    """The chain walker that tests every node's byte 3 against `0xFF`.

    It is Dispel Magic: a node whose byte 3 is `0xFF` is passed over, any
    other has its low nibble taken as the level the dispel roll is made
    against.  Returns its start, the site of the `0xFF` test and the ids it
    also tests byte 0 against.
    """
    walkers = chain_walkers(eng) if walkers is None else walkers
    for (where, start), uses in sorted(walkers.items()):
        for insn in body(eng.code(where), start):
            if insn.mnemonic == "cmp" and insn.op_str == "byte ptr es:[di + 3], 0xff":
                return dict(file=where, routine=start, test=insn.address,
                            compares=sorted(uses.compares))
    raise ValueError(f"{eng.title}: no chain walker tests byte 3 against 0xFF")


def verdicts(eng: Engine) -> dict[int, Verdict]:
    callers = caller_uses(eng)
    walkers = chain_walkers(eng)
    by_id: dict = collections.defaultdict(set)
    for uses in walkers.values():
        read = uses.bytes_read() & {3, 4}
        for eid in uses.compares:
            by_id[eid] |= read
    out = {}
    for eid in eng.effect_ids:
        h = handler_uses(eng, eid)
        c = callers.get(eid, Uses())
        out[eid] = Verdict(eng.handlers[eid][1], h.bytes_read(), c.bytes_read(),
                           by_id.get(eid, set()), bool(h.removes or c.removes))
    return out


def computed_reads(eng: Engine) -> set:
    """Node bytes read after a `find_affect` whose id is not a constant."""
    return caller_uses(eng).get(None, Uses()).bytes_read()


# --------------------------------------------------------------------------
# Readied items
# --------------------------------------------------------------------------


def add_affect_calls(eng: Engine, where: str, at: int) -> list[tuple]:
    """`(id, duration, data, flag)` of each add_affect call in a routine.

    An argument pushed from somewhere other than an immediate is its source
    text, so `"item[0x3d]"` is the item's byte `0x3D`.
    """
    add = eng.add_affect
    calls = []
    args: list = []
    src = None
    for insn in body(eng.code(where), at):
        m, ops = insn.mnemonic, insn.op_str
        if m == "mov" and re.fullmatch(r"al, (0x[0-9a-f]+|\d+)", ops):
            src = int(ops[4:], 0)
        elif m == "mov" and re.fullmatch(r"ax, (0x[0-9a-f]+|\d+)", ops):
            src = int(ops[4:], 0)
        elif m == "xor" and ops == "ax, ax":
            src = 0
        elif m == "mov" and ops == "al, byte ptr es:[di + 0x3d]":
            src = "item[0x3d]"
        elif m == "mov" and ops.startswith("al, byte ptr [bp"):
            src = f"local{_slot_text(_bp(ops))}"
        elif m == "push" and ops == "ax":
            args.append(src)
        elif m == "lcall" and add and ops == f"{add[0]:#x}, {add[1]:#x}":
            calls.append(tuple(args[-4:]))
            args = []
        elif m in ("call", "lcall"):
            args = []
    return calls


def item_powers(eng: Engine) -> dict:
    """Item power byte (`0x3E`) -> the add_affect calls readying it makes.

    Pool of Radiance dispatches on the byte itself, so power `p` runs handler
    `p`.  Curse and Silver Blades route a power whose low seven bits are zero
    through the hook, and handle the others in a switch that calls no
    add_affect; `item_switch` reads that switch.
    """
    if eng.hook_handler is None:
        return {p: add_affect_calls(eng, *eng.handlers[p])
                for p in eng.handlers if p >= 0x80}
    return {0x80: add_affect_calls(eng, *eng.hook_handler)}


def item_switch(eng: Engine, depth: int = 3) -> dict:
    """For the hook titles: the routine that sets the hook's flag on power 0.

    Returns its file offset, the powers it compares against, and the
    add_affect calls reachable from it within `depth` levels of calls, the
    dispatcher excepted (that is the hook, read by `item_powers`).  None is
    the finding: no other power creates a node.
    """
    flag = None
    for insn in body(eng.ovr, eng.dispatcher):
        if insn.mnemonic == "cmp" and insn.op_str.startswith("byte ptr [0x"):
            flag = int(insn.op_str.split("[")[1].split("]")[0], 0)
            break
    set_flag = bytes((0xC6, 0x06)) + struct.pack("<H", flag) + b"\x01"
    for m in re.finditer(re.escape(set_flag), eng.ovr):
        start = eng.ovr.rfind(b"\x55\x89\xe5", 0, m.start())
        text = [f"{i.mnemonic} {i.op_str}" for i in body(eng.ovr, start)]
        if "and al, 0x7f" not in text or "cmp al, 0" not in text:
            continue
        powers = sorted({int(t[8:], 0) for t in text
                         if re.fullmatch(r"cmp al, (0x[0-9a-f]+|\d+)", t)})
        target = f"{eng.add_affect[0]:#x}, {eng.add_affect[1]:#x}"
        seen, frontier, calls = set(), [("GAME.OVR", start)], []
        for _ in range(depth):
            following = []
            for where, at in frontier:
                if (where, at) in seen:
                    continue
                seen.add((where, at))
                try:
                    ins = body(eng.code(where), at)
                except ValueError:
                    continue
                prev = None
                for insn in ins:
                    if insn.mnemonic == "lcall" and insn.op_str == target:
                        calls.append(insn.address)
                    elif insn.mnemonic in ("call", "lcall"):
                        tgt = _call_target(eng, where, insn, prev)
                        if tgt and tgt[:2] != ("GAME.OVR", eng.dispatcher):
                            following.append(tgt[:2])
                    prev = insn
            frontier = following
        return dict(routine=start, flag=flag, flag_set=m.start(), powers=powers,
                    add_affect_calls=calls, routines_walked=len(seen))
    raise ValueError(f"{eng.title}: no item-power switch sets [0x{flag:x}]")


# --------------------------------------------------------------------------
# Pool of Radiance's strength item
# --------------------------------------------------------------------------


def strength_encoding(eng: Engine) -> dict:
    """Read the value byte the strength item stores, from the code.

    Handler 131 (power `0x83`) calls `add_affect(38, 0, local, 1)` where the
    local is filled by the set-strength routine, whose last act is the
    encoder: `score + 100`, or `percentile + 1` when the score is 18.
    Returns the encoder's file offset and the two constants it uses.
    """
    where, at = eng.handlers[0x83]
    ins = body(eng.code(where), at)
    calls = add_affect_calls(eng, where, at)
    setter = next(i for i in ins if i.mnemonic == "lcall"
                  and i.op_str != f"{eng.add_affect[0]:#x}, {eng.add_affect[1]:#x}"
                  and any(j.op_str == "al, 0x64" for j in ins
                          if at <= j.address < i.address and i.address - j.address < 20))
    seg, off = (int(x, 0) for x in setter.op_str.split(", "))
    sw, sat = eng.resolve(seg, off)
    sins = body(eng.code(sw), sat)
    enc = int(next(i for i in sins if i.mnemonic == "call").op_str, 0)
    eins = body(eng.code(sw), enc)
    add = next(int(i.op_str[4:], 0) for i in eins if i.op_str.startswith("ax, 0x"))
    eighteen = next(int(i.op_str.split(", ")[1], 0) for i in eins
                    if i.mnemonic == "cmp" and i.op_str.startswith("byte ptr [bp + 8]"))
    inc = any(i.mnemonic == "inc" and i.op_str == "ax" for i in eins)
    return dict(handler=at, add_affect=calls, setter=sat, encoder=enc,
                offset=add, eighteen=eighteen, percentile_plus_one=inc)


def encode_strength(strength: int, percentile: int) -> int:
    """The engine's one-byte strength, as `strength_encoding` reads it."""
    return percentile + 1 if strength == 18 else strength + 100


# --------------------------------------------------------------------------
# What one handler does, for comparing an id across ports
# --------------------------------------------------------------------------


def constant_calls(eng: Engine, eid: int) -> list[tuple[int, int]]:
    """`(callee, constant)` for each `mov al, imm / push ax / push cs / call`.

    Silver Blades' immunity handlers call one helper per effect they cancel,
    the constant being the effect id, as the C64 handlers call `$14EA`.
    """
    where, at = eng.handlers[eid]
    ins = body(eng.code(where), at)
    out = []
    for k in range(3, len(ins)):
        a, b, c, d = ins[k - 3:k + 1]
        if (a.mnemonic, b.op_str, c.op_str, d.mnemonic) == ("mov", "ax", "cs", "call") \
                and re.fullmatch(r"al, (0x[0-9a-f]+|\d+)", a.op_str):
            out.append((int(d.op_str, 0), int(a.op_str[4:], 0)))
    return out


def score_bands(eng: Engine, eid: int) -> dict:
    """The record byte a handler grades and its `(low, high, bonus)` bands.

    The form of Pool of Radiance's 97 (`docs/189-effect-97-from-the-code.md`):
    one record byte read into `al`, then `cmp al, low / jb / cmp al, high /
    ja / mov byte ptr [bp - 1], bonus` per band, the bonus added to a global.
    """
    where, at = eng.handlers[eid]
    field = None
    bands, low, high = [], None, None
    for insn in body(eng.code(where), at):
        m, ops = insn.mnemonic, insn.op_str
        if m == "mov" and ops.startswith("al, byte ptr es:[di + 0x") and field is None:
            field = int(DISP.search(ops).group(2), 0)
        elif m == "cmp" and re.fullmatch(r"al, (0x[0-9a-f]+|\d+)", ops) and field is not None:
            if low is None:
                low = int(ops[4:], 0)
            else:
                high = int(ops[4:], 0)
        elif m == "mov" and ops.startswith("byte ptr [bp - 1], ") and low is not None:
            bands.append((low, high if high is not None else low, int(ops.split(", ")[1], 0)))
            low = high = None
    return dict(field=field, bands=bands)


# --------------------------------------------------------------------------
# Applying an effect: what the target's own effects cancel
# --------------------------------------------------------------------------
# Every title applies a spell's effect through one routine that parks the id
# in a global, walks check list 9 over the target -- the target's handler for
# each id on the list that it carries -- and adds the node only if the global
# is still set.  A handler cancels by calling one helper with an id: if the
# id is the one parked (or the constant is 0, whatever is parked), the helper
# clears it.  So what an effect protects against is the constants its handler
# hands that helper, and that the id is on list 9.


def cancel_helper(eng: Engine) -> tuple[int, int]:
    """`(file offset, global)` of the helper that cancels the effect being applied.

    The routine most handlers call with a constant whose body is `cmp byte
    ptr [bp + 6], 0 / je / mov al, byte ptr [G] / cmp al, byte ptr [bp + 6]`.
    """
    count = collections.Counter()
    for eid in eng.effect_ids:
        for callee, _ in constant_calls(eng, eid):
            count[(eng.handlers[eid][0], callee)] += 1
    for (where, callee), _ in count.most_common():
        text = [f"{i.mnemonic} {i.op_str}" for i in body(eng.code(where), callee)]
        if len(text) > 5 and text[2] == "cmp byte ptr [bp + 6], 0" \
                and text[3].startswith("je ") \
                and text[4].startswith("mov al, byte ptr [0x") \
                and text[5] == "cmp al, byte ptr [bp + 6]":
            return callee, int(text[4].split("[")[1].rstrip("]"), 0)
    raise ValueError(f"{eng.title}: no cancel helper")


def cancels(eng: Engine) -> dict[int, list[int]]:
    """Handler id -> the ids its handler cancels on application (0: any)."""
    helper, _ = cancel_helper(eng)
    out = {}
    for eid in eng.effect_ids:
        hits = sorted(c for callee, c in constant_calls(eng, eid) if callee == helper)
        if hits:
            out[eid] = hits
    return out


def apply_walk(eng: Engine) -> dict:
    """The apply routine, the check list it walks, and every list's ids.

    Found by its `mov byte ptr [G], al` into the cancel helper's global,
    followed by `mov al, <list>` and a near call to the list walker.  The
    walker is a switch on the list number: `cmp al, n` opens list `n`, and
    each `mov al, id / push ax / push cs / call <ask>` puts `id` on it.
    """
    _, glob = cancel_helper(eng)
    store = b"\xa2" + struct.pack("<H", glob)
    for m in re.finditer(re.escape(store), eng.ovr):
        start = eng.ovr.rfind(b"\x55\x89\xe5", 0, m.start())
        ins = body(eng.ovr, start)
        at = [i.address for i in ins]
        if m.start() not in at:
            continue
        k = at.index(m.start())
        nxt = ins[k + 1]
        call = next(i for i in ins[k + 1:] if i.mnemonic == "call")
        if not re.fullmatch(r"al, (0x[0-9a-f]+|\d+)", nxt.op_str):
            continue
        walker = int(call.op_str, 0)
        return dict(apply=start, glob=glob, list=int(nxt.op_str[4:], 0),
                    walker=walker, lists=walker_lists(eng, walker))
    raise ValueError(f"{eng.title}: no routine stores the applied effect and walks a list")


def walker_lists(eng: Engine, walker: int) -> dict[int, list[int]]:
    ins = body(eng.ovr, walker, 0x3000)
    calls = collections.Counter(i.op_str for i in ins if i.mnemonic == "call")
    ask = calls.most_common(1)[0][0]
    lists: dict[int, list[int]] = {}
    current = None
    for k, insn in enumerate(ins):
        ops = insn.op_str
        if insn.mnemonic == "cmp" and re.fullmatch(r"al, (0x[0-9a-f]+|\d+)", ops):
            current = int(ops[4:], 0)
            lists.setdefault(current, [])
        elif insn.mnemonic == "call" and ops == ask and current is not None:
            back = [f"{i.mnemonic} {i.op_str}" for i in ins[max(0, k - 3):k]]
            if back[-2:] == ["push ax", "push cs"] and \
                    re.fullmatch(r"mov al, (0x[0-9a-f]+|\d+)", back[0]):
                lists[current].append(int(back[0][8:], 0))
    return lists


def data_list(eng: Engine, offset: int, first: int, last: int) -> list[int]:
    """Bytes `first`..`last` of a byte array in the data segment at `offset`."""
    from tools.dos import dosspellslots
    at = dosspellslots.data_segment(eng.img) * 16 + offset
    return list(eng.img[at + first:at + last + 1])


def data_indexed_callers(eng: Engine, offset: int) -> list[dict]:
    """Every `find_affect` call whose id is `byte ptr [di + offset]`.

    Returns each call site, its routine, and whether the same routine hands
    the same indexed id to `remove_affect` -- which is what a cure does.
    """
    ref = f"al, byte ptr [di + {offset:#x}]"
    out = []
    for where, site, eid, _slot in find_affect_sites(eng):
        if eid is not None:
            continue
        code = eng.code(where)
        start = code.rfind(b"\x55\x89\xe5", 0, site)
        ins = body(code, start, 0x3000)
        before = [i for i in ins if i.address < site][-8:]
        if not any(i.op_str == ref for i in before):
            continue
        removes = any(
            i.mnemonic == "lcall" and _far(eng, i.op_str) == ("GAME.OVR", eng.remove_affect_at)
            and any(j.op_str == ref for j in ins[max(0, k - 8):k])
            for k, i in enumerate(ins))
        out.append(dict(file=where, site=site, routine=start, removes=removes))
    return out


# --------------------------------------------------------------------------
# Casting a spell: the saving throw, the spell table and a spell's own gate
# --------------------------------------------------------------------------
# What protects a target from a spell's effect is not only list 9.  The spell
# routine may refuse a target before anything is applied, the saving throw
# adds a record byte and walks list 12, and the spell's row in the 16-byte
# spell table names the effect, whether a save negates it and against which
# column.  These read each of those out of the engine.


def routine_callers(eng: Engine, at: int) -> list[tuple[int, int]]:
    """`(site, routine)` for every near and far call to `GAME.OVR:at`."""
    unit = dosovrmap.unit_of(eng.units, at)
    sites = set()
    for stub, code in unit["ents"]:
        if unit["fileoff"] + code == at:
            far = b"\x9a" + struct.pack("<HH", stub, unit["seg"])
            sites |= {m.start() for m in re.finditer(re.escape(far), eng.ovr)}
    lo, hi = unit["fileoff"], unit["fileoff"] + unit["code"]
    for p in range(lo, hi - 3):
        if eng.ovr[p] == 0xE8 and \
                p + 3 + struct.unpack_from("<h", eng.ovr, p + 1)[0] == at:
            sites.add(p)
    return sorted((s, eng.ovr.rfind(b"\x55\x89\xe5", 0, s)) for s in sites)


def saving_throw(eng: Engine) -> dict:
    """The saving-throw routine and the record bytes it adds and compares.

    It is the one routine that walks check list 12 (`mov al, 0xc` a few
    instructions before the near call to the walker).  It rolls a d20, adds
    the record byte `bonus` and its own argument, parks the save column in a
    global, walks list 12 over the target, and saves when the roll reaches the
    record's `targets + column`.
    """
    walker = apply_walk(eng)["walker"]
    hits = []
    for site, start in routine_callers(eng, walker):
        before = dosovrmap.window(eng.ovr, site, 40)[-7:]
        if any(i.op_str == "al, 0xc" for i in before):
            hits.append((site, start))
    if len(hits) != 1:
        raise ValueError(f"{eng.title}: {len(hits)} routines walk list 12")
    site, start = hits[0]
    ins = body(eng.ovr, start)
    reads_ = [(i.address, int(DISP.search(i.op_str).group(2), 0)) for i in ins
              if i.mnemonic == "mov" and i.op_str.startswith("al, byte ptr es:[di + 0x")]
    bonus = next(off for a, off in reads_ if a < site)
    targets = next(off for a, off in reads_ if a > site)
    return dict(routine=start, walk=site, list=12, bonus=bonus, targets=targets)


def spell_effect_routine(eng: Engine) -> dict:
    """The routine that applies a spell's table effect, and the table's layout.

    Of the apply routine's callers it is the one that also calls the saving
    throw.  Before that call it tests the row's save-action byte, `cmp byte
    ptr [di + A], 0`, and pushes the save column, `mov al, byte ptr [di +
    A + 1]`; the row is 16 bytes (`shl di, cl` with `cl = 4`), so the table
    starts at `A - 8` and the effect id is its byte 10.
    """
    save = saving_throw(eng)["routine"]
    apply = apply_walk(eng)["apply"]
    for _site, start in routine_callers(eng, apply):
        ins = body(eng.ovr, start, 0x3000)
        calls = [k for k, i in enumerate(ins) if i.mnemonic == "lcall"
                 and _far(eng, i.op_str) == ("GAME.OVR", save)]
        if not calls:
            continue
        back = ins[max(0, calls[0] - 6):calls[0]]
        column = next((i for i in reversed(back) if i.mnemonic == "mov"
                       and re.fullmatch(r"al, byte ptr \[di \+ 0x[0-9a-f]+\]", i.op_str)), None)
        if column is None:
            continue
        col = int(column.op_str.split("+ ")[1].rstrip("]"), 0)
        action = f"byte ptr [di + {col - 1:#x}], 0"
        if not any(i.mnemonic == "cmp" and i.op_str == action for i in ins):
            continue
        base = col - 9
        return dict(routine=start, save_call=ins[calls[0]].address, base=base,
                    level=base + 1, action=base + 8, column=base + 9, effect=base + 10)
    raise ValueError(f"{eng.title}: no apply caller calls the saving throw")


def spell_routines(eng: Engine) -> dict[int, tuple[str, int]]:
    """Spell id -> its routine, from the far-pointer table the spell dispatcher
    calls through: the dispatcher-form table other than the effect handlers'
    with the most code-filled entries."""
    best: dict = {}
    for m in re.finditer(re.escape(dosracialseed.DISPATCH), eng.ovr):
        base = struct.unpack_from("<H", eng.ovr, m.end())[0]
        if base == eng.table:
            continue
        fills = dosracialseed._fills(eng.ovr, base)
        if len(fills) > len(best):
            best = fills
    out = {}
    for sid, (seg, off) in sorted(best.items()):
        try:
            out[sid] = eng.resolve(seg, off)
        except ValueError:
            continue
    return out


def spell_rows(eng: Engine) -> dict[int, bytes]:
    """Spell id -> its 16-byte row in the spell table, for every routine's id."""
    from tools.dos import dosspellslots
    at = dosspellslots.data_segment(eng.img) * 16 + spell_effect_routine(eng)["base"]
    return {sid: eng.img[at + 16 * sid:at + 16 * sid + 16] for sid in spell_routines(eng)}


def spells_applying(eng: Engine, eid: int) -> list[int]:
    """The spell ids whose row names `eid` as its effect."""
    return [sid for sid, row in spell_rows(eng).items() if row[10] == eid]


def lists_holding(eng: Engine, eid: int) -> list[int]:
    """The check lists the walker asks `eid` on."""
    return sorted(n for n, ids in apply_walk(eng)["lists"].items() if eid in ids)


_JCC = {"je", "jne", "jb", "jbe", "ja", "jae", "jl", "jle", "jg", "jge", "js", "jns"}


def class_gate(eng: Engine, where: str, at: int) -> dict | None:
    """Which record classes a spell routine lets through, read from its switch.

    The switch is `mov al, byte ptr es:[di + F]` followed by `cmp al, n` /
    `je`/`jne` chains, each arm ending in a jump to a join that tests a local
    flag (`cmp byte ptr [bp - k], 0`), the flag an arm sets with `mov byte ptr
    [bp - k], 1`.  Each class value 0-17 is followed through the chain; a
    comparison that is not against `al` takes both branches.  Returns the
    field and, per class, the set of values the flag holds at the join --
    `None` in the set where a path reaches it without writing the flag.
    Returns None for a routine with no such switch.
    """
    ins = body(eng.code(where), at, 0x3000)
    index = {i.address: k for k, i in enumerate(ins)}
    sets = collections.Counter(i.op_str.split(",")[0] for i in ins if i.mnemonic == "mov"
                               and re.fullmatch(r"byte ptr \[bp - \w+\], 1", i.op_str))
    if not sets:
        return None
    flag = sets.most_common(1)[0][0]
    join = f"{flag}, 0"
    start = next((k for k, i in enumerate(ins[:-1]) if i.mnemonic == "mov"
                  and re.fullmatch(r"al, byte ptr es:\[di \+ 0x[0-9a-f]+\]", i.op_str)
                  and ins[k + 1].mnemonic == "cmp"
                  and re.fullmatch(r"al, (0x[0-9a-f]+|\d+)", ins[k + 1].op_str)
                  and sum(1 for j in ins[k + 1:k + 40] if j.mnemonic == "cmp"
                          and re.fullmatch(r"al, (0x[0-9a-f]+|\d+)", j.op_str)) >= 3), None)
    if start is None:
        return None
    field = int(DISP.search(ins[start].op_str).group(2), 0)
    out = {}
    for cls in range(18):
        seen, result = set(), set()
        stack = [(start + 1, cls, None, None)]
        while stack:
            k, al, cmpd, value = stack.pop()
            if (k, al, cmpd, value) in seen or k >= len(ins):
                continue
            seen.add((k, al, cmpd, value))
            i = ins[k]
            m, ops = i.mnemonic, i.op_str
            if m == "cmp" and ops == join:
                result.add(value)
                continue
            if m == "cmp":
                imm = re.fullmatch(r"al, (0x[0-9a-f]+|\d+)", ops)
                cmpd = (al, int(imm.group(1), 0)) if imm and al is not None else "?"
                stack.append((k + 1, al, cmpd, value))
                continue
            if m == "mov" and ops.startswith("al,"):
                al = None
            if m == "mov" and ops.startswith(f"{flag}, "):
                value = int(ops.split(", ")[1], 0)
            if m == "jmp":
                stack.append((index[int(ops, 0)], al, cmpd, value))
                continue
            if m in _JCC:
                taken = (index[int(ops, 0)], al, cmpd, value)
                fall = (k + 1, al, cmpd, value)
                if isinstance(cmpd, tuple) and m in ("je", "jne"):
                    equal = cmpd[0] == cmpd[1]
                    stack.append(taken if equal == (m == "je") else fall)
                else:
                    stack += [taken, fall]
                continue
            if m in ("ret", "retf"):
                continue
            stack.append((k + 1, al, cmpd, value))
        out[cls] = result
    return dict(field=field, flag=flag, classes=out)


def _far(eng: Engine, op_str: str) -> tuple[str, int] | None:
    direct = re.fullmatch(r"(0x[0-9a-f]+|\d+), (0x[0-9a-f]+|\d+)", op_str)
    if direct is None:
        return None
    try:
        return eng.resolve(int(direct.group(1), 0), int(direct.group(2), 0))
    except ValueError:
        return None


# --------------------------------------------------------------------------


def _game_dir(title: str, arg: str | None) -> pathlib.Path:
    if arg:
        return pathlib.Path(arg)
    from tools.dos import dosbox
    return dosbox.find_game(TITLES[title])


def _fmt(s: set) -> str:
    return ",".join(str(b) for b in sorted(s)) or "-"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", choices=sorted(TITLES), action="append")
    ap.add_argument("--game-dir", help="a directory holding GAME.OVR and START.EXE")
    ap.add_argument("--ids", help="comma-separated ids to print (default: all)")
    ap.add_argument("--items", action="store_true", help="print the item-power reading")
    ap.add_argument("--apply", action="store_true",
                    help="print check list 9 and what each handler cancels on application")
    ap.add_argument("--spells", metavar="IDS",
                    help="comma-separated effect ids: the spells that apply each, their save"
                         " and the class gate in their routine")
    a = ap.parse_args(argv)
    for title in a.title or list(TITLES):
        try:
            eng = load(_game_dir(title, a.game_dir), title)
        except FileNotFoundError as exc:
            print(f"{title}: {exc}")
            continue
        print(f"== {title}: dispatcher GAME.OVR:0x{eng.dispatcher:x}, table ds:0x{eng.table:x}"
              f" ids 1-{max(eng.handlers)}, hook "
              f"{'none' if eng.hook is None else hex(eng.hook)}")
        fw, fa = eng.find_affect_at
        print(f"   find_affect {eng.find_affect[0]:x}:{eng.find_affect[1]:x} at {fw}:0x{fa:x},"
              f" chain at record 0x{eng.chain:x}; remove_affect GAME.OVR:0x"
              f"{eng.remove_affect_at:x} tests byte 4 at 0x{eng.remove_flag_test:x}")
        v = verdicts(eng)
        want = [int(x) for x in a.ids.split(",")] if a.ids else sorted(v)
        clean = [e for e in sorted(v) if not v[e].value_read]
        print(f"   {len(clean)} of {len(v)} ids: nothing reads byte 3 or 4 of the node")
        print(f"   computed-id find_affect callers read bytes {_fmt(computed_reads(eng))}")
        dsp = dispel_routine(eng)
        print(f"   every node: byte 4 at remove_affect, byte 3 at the dispel walk "
              f"{dsp['file']}:0x{dsp['routine']:x} (0xFF test at 0x{dsp['test']:x},"
              f" also tests ids {dsp['compares']})")
        for e in want:
            x = v[e]
            print(f"   {e:3d} handler 0x{x.handler:05x} reads {_fmt(x.handler_reads):8s}"
                  f" callers read {_fmt(x.caller_reads):6s}"
                  f" walkers read {_fmt(x.walker_reads):4s}"
                  f"{' removes it' if x.removes else ''}"
                  f"{'' if x.value_read else '   <- value byte unread'}")
        if a.items:
            for p, calls in sorted(item_powers(eng).items()):
                print(f"   item power 0x{p:02x}: add_affect {calls or 'none'}")
            if eng.hook_handler is not None:
                sw = item_switch(eng)
                print(f"   item switch GAME.OVR:0x{sw['routine']:x}: powers {sw['powers']},"
                      f" add_affect reached from {sw['routines_walked']} routines:"
                      f" {sw['add_affect_calls'] or 'none'}")
            else:
                s = strength_encoding(eng)
                print(f"   strength item: handler 0x{s['handler']:x}, encoder 0x{s['encoder']:x}:"
                      f" score + {s['offset']}, or percentile + 1 at {s['eighteen']}")
        if a.apply:
            w = apply_walk(eng)
            helper, glob = cancel_helper(eng)
            print(f"   apply GAME.OVR:0x{w['apply']:x} parks the id in [0x{glob:x}] and walks"
                  f" list {w['list']} through 0x{w['walker']:x}: {w['lists'][w['list']]}")
            print(f"   cancel helper 0x{helper:x}; each handler cancels (0 = any):")
            for eid, ids in sorted(cancels(eng).items()):
                print(f"   {eid:3d} {ids}")
        if a.spells:
            s = saving_throw(eng)
            print(f"   saving throw GAME.OVR:0x{s['routine']:x}: d20 + record 0x{s['bonus']:x},"
                  f" walks list 12 {apply_walk(eng)['lists'].get(12, [])},"
                  f" saves at record 0x{s['targets']:x} + column")
            sp = spell_effect_routine(eng)
            rows, routines = spell_rows(eng), spell_routines(eng)
            print(f"   spell effect routine GAME.OVR:0x{sp['routine']:x}, spell table"
                  f" ds:0x{sp['base']:x} (16 bytes: level +1, save action +8, column +9,"
                  f" effect +10)")
            for eid in [int(x) for x in a.spells.split(",")]:
                print(f"   effect {eid}: on lists {lists_holding(eng, eid) or 'none'}")
                for sid in spells_applying(eng, eid):
                    row, (where, at) = rows[sid], routines[sid]
                    gate = class_gate(eng, where, at)
                    shown = "no class gate" if gate is None else (
                        f"class byte 0x{gate['field']:x}: " + ", ".join(
                            f"{c}={'/'.join('unset' if v is None else str(v) for v in sorted(vs, key=str))}"
                            for c, vs in gate["classes"].items()))
                    print(f"     spell {sid} {where}:0x{at:x} level {row[1]} save action {row[8]}"
                          f" column {row[9]}; {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

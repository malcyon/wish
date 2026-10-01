#!/usr/bin/env python3
"""Read a running Amiga in a patched FS-UAE, over its GDB-remote port.

`automap/amiga.py` carries the transport -- `FsuaeGdb` -- and `AmigaTarget` on
top of it; this is the command line that drives them, the same way
`tools/amiga/amigatarget.py` drives the two WinUAE routes.  Nothing here re-derives
an address, a position or a map.

    tools/amiga/fsuaegdb.py probe --port 6525
    tools/amiga/fsuaegdb.py locate --port 6525
    tools/amiga/fsuaegdb.py fix --port 6525
    tools/amiga/fsuaegdb.py dump --port 6525 --at 0xC00000 --length 0x400 \\
        --out DIR/block.bin
    tools/amiga/fsuaegdb.py automap --port 6525 --out DIR/run \\
        --polls 8 --walk 'KP_Up KP_Left KP_Up' --display :77
    tools/amiga/fsuaegdb.py session --port 6525 --out DIR/run \\
        --commands DIR/cmds.txt --window --maps DIR/adfs \\
        --peeks '+0x5B12 1' '*0x57AC+0x24 3'

**`probe` is the one to run first.**  It connects, prints what the server
advertises, continues the machine and times a read at four sizes -- and it
samples `VHPOSR` on every poll, because the same raster position poll after
poll is the signature of a reply built in a frame handler rather than by a
halted debugger.

**The emulator this talks to is the fork `grahambates/fs-uae`, branch
`remote_debugger_prb28`**, run with `remote_debugger=<seconds>` and
`remote_debugger_port=<port>`.  Where a person gets that binary is not settled
and is not this file's business: `--fs-uae` takes a path to one that is already
on the machine, and nothing here downloads, installs or unpacks anything.

`launch` is here because every run needs the same four things right and getting
one wrong is expensive: a private `Xvfb` so no window reaches the desktop,
`SDL_AUDIODRIVER=dummy` because **`--volume=0` does not silence this build**, a
`base_dir` of its own so `~/FS-UAE/` is never touched, and its own process
group so the run can be torn down without killing anything by name.  It starts
what it is pointed at and no more.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from automap import amiga  # noqa: E402

#: The small-data base these titles are linked with, printed beside the hunk
#: address.  `tools/amiga/amigatarget.py` has the same constant for the same reason:
#: `automap/` must not import `tools/`, and this is a printout.
A4_BIAS = 0x7FFE

#: What `probe` reads, in the order it reads them.  16 bytes is the floor of
#: the cost -- the wait for the next frame -- and 512K is one whole region of
#: the A500's memory, which is what `AmigaTarget.locate()` sweeps.
PROBE_SIZES = (16, 1024, 65536, 512 * 1024)

#: `VHPOSR`, the raster position, read every poll as the running-or-halted
#: witness.  Two bytes, and they move every raster line.
VHPOSR = 0xDFF006


#: `--title none`: a session with no `MACHINES` row, for measuring a title that
#: has none yet.  It reads raw memory and drives the emulator; anything that
#: needs a layout says so.
NO_TITLE = "none"

#: The session commands that need a layout, and so are refused under it.
TITLED_COMMANDS = ("locate", "fix", "peek", "observe", "poll")

#: One `dump` is at most one region of the A500's memory, the size `probe`'s
#: largest read and `AmigaTarget.locate()`'s sweep already take in one packet.
DUMP_LIMIT = 0x80000


def connect(args, resume: bool = True) -> amiga.FsuaeGdb:
    return amiga.FsuaeGdb(host=args.host, port=args.port,
                          timeout=args.timeout, resume=resume)


def detect_layout(gdb) -> amiga.AmigaMachine:
    """The one title in this machine's memory, found by sweeping every row.

    There is no default title: a wrong one reads as "the anchor is nowhere in
    memory", which looks like a game that has not loaded.  None or several
    matching stops with the names, since the choice is then the caller's.
    """
    machines = {m.title: m for m in amiga.MACHINES.values()}
    found = amiga.locate_machines(gdb.read_memory, machines.values(),
                                   sweep_all=True)
    if len(found) == 1:
        return machines[next(iter(found))]
    tried = ", ".join(sorted(amiga.MACHINES))
    if not found:
        raise SystemExit("no known title is in this Amiga's memory (tried "
                         f"{tried}); it may still be loading, or pass --title")
    raise SystemExit("more than one title matches this Amiga's memory ("
                     f"{', '.join(sorted(found))}); pass --title")


def resolve_layout(args, gdb) -> amiga.AmigaMachine:
    """`--title`'s row, or the title detected on the open connection."""
    return amiga.MACHINES[args.title] if args.title else detect_layout(gdb)


def refuse_no_title(args, command: str) -> None:
    """Stop a command that needs a layout before it connects, under `--title none`."""
    if args.title == NO_TITLE:
        raise SystemExit(f"{command} needs a title's layout; --title {NO_TITLE} "
                         f"is for `session` ({', '.join(sorted(amiga.MACHINES))})")


def target(args) -> amiga.AmigaTarget:
    """A located `AmigaTarget` over the socket, with the base measured.

    The base is measured on every run and never written down: AmigaDOS
    relocates the executable on every `LoadSeg`, so an address from yesterday
    is wrong today.
    """
    refuse_no_title(args, "this command")
    gdb = connect(args)
    try:
        layout = resolve_layout(args, gdb)
    except BaseException:
        gdb.close()
        raise
    tgt = amiga.AmigaTarget(gdb, layout)
    started = time.monotonic()
    base = tgt.locate()
    print(f"Data hunk  {base:#010x}   a4 {base + A4_BIAS:#010x}   "
          f"({time.monotonic() - started:.1f}s)")
    return tgt


# -- probing ------------------------------------------------------------------


def probe(args) -> int:
    """Connect, continue, and time a read at four sizes.

    One line per poll, and the `VHPOSR` column is the finding rather than the
    decoration: a halted debugger answers from wherever the CPU stopped, so its
    raster position wanders.  A frame handler answers at the same point in
    every frame.
    """
    gdb = connect(args, resume=False)
    print(f"Server     {gdb.greeting}")
    print(f"Stop reply {gdb.ask('?')}")
    gdb.resume()
    time.sleep(0.3)
    print("Continued  the machine is running")

    rows = []
    for i in range(args.polls):
        vh = gdb.read_memory(VHPOSR, 2)
        line = [f"poll {i:2d}  vhposr={vh.hex()}"]
        row = {"i": i, "vhposr": vh.hex()}
        for size in PROBE_SIZES:
            if size > args.max_read:
                continue
            started = time.perf_counter()
            blob = gdb.read_memory(args.at, size)
            ms = 1000 * (time.perf_counter() - started)
            row[str(size)] = round(ms, 1)
            row[f"nonzero{size}"] = sum(1 for b in blob if b)
            line.append(f"{size:>7}B {ms:7.1f} ms")
        rows.append(row)
        print("  ".join(line))
        time.sleep(args.interval)

    seen = {r["vhposr"] for r in rows}
    print(f"VHPOSR     {len(seen)} distinct value(s) over {len(rows)} polls: "
          + ", ".join(sorted(seen)))
    for size in PROBE_SIZES:
        got = sorted(r[str(size)] for r in rows if str(size) in r)
        if got:
            print(f"{size:>7} bytes  n={len(got)}  min {got[0]:.1f} ms  "
                  f"median {got[len(got) // 2]:.1f} ms  max {got[-1]:.1f} ms")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(rows, indent=2))
    gdb.close()
    return 0


# -- the shipped automapper ---------------------------------------------------


def refuse_shift_letter(key: str) -> None:
    """ValueError for a single upper-case letter.

    xdotool sends it as Shift plus the letter, and the Amiga games ignore
    modifiers and read Left Shift as the key `7`.
    """
    if len(key) == 1 and key.isalpha() and key.isupper():
        raise ValueError(f"Key {key!r} would send Shift, which the game reads "
                         f"as 7; use {key.lower()!r}.")


def press(display: str, key: str, settle: float) -> None:
    """One keystroke into the emulator, through XTEST on its own display.

    `xdotool key` with no window argument goes to whatever has focus, which on
    a bare `Xvfb` with no window manager is nothing; the focus call is what
    makes SDL see it.  Proven on 2026-09-08, when `alt+q` sent this way shut
    FS-UAE down cleanly.
    """
    from tools.amiga import fsuaepor

    refuse_shift_letter(key)
    env = {"DISPLAY": display, "PATH": "/usr/bin:/bin"}
    found = fsuaepor.find_windows(display)
    if found:
        fsuaepor.focus(display, found[0])
    subprocess.run(["xdotool", "key", key], env=env, check=False)
    time.sleep(settle)


def schedule(text: str) -> list[tuple[float, str]]:
    """`'40:Return;62:p;70:l'` as `[(seconds, key)]`, sorted.

    Seconds from the moment the machine was continued, not from the key
    before, because that is how a boot is actually observed: the credits are
    at 40 seconds whatever the last keystroke was.
    """
    out = []
    for piece in text.replace(",", ";").split(";"):
        piece = piece.strip()
        if not piece:
            continue
        when, _, key = piece.partition(":")
        out.append((float(when), key))
    return sorted(out)


def boot(gdb, args) -> None:
    """Press a schedule of keys while the machine boots, and say what it did.

    **The connection is open the whole time**, which is the constraint that
    shapes this: the emulator gives out one connection per run and shuts the
    listening socket when it goes, so a run cannot boot the game with one
    process and map it with another.

    A read every second while the keys go in, because the reads are what prove
    the machine is running -- and because the first one to find the anchor
    says when the title finished loading.
    """
    keys = schedule(args.boot)
    if not keys and not args.warmup:
        return
    started = time.monotonic()
    done = 0
    while done < len(keys) or time.monotonic() - started < args.warmup:
        now = time.monotonic() - started
        if done < len(keys) and now >= keys[done][0]:
            press(args.display, keys[done][1], 0.4)
            print(f"[{now:6.1f}s] key {keys[done][1]}")
            done += 1
        vh = gdb.read_memory(VHPOSR, 2)
        if int(now) % 10 == 0:
            print(f"[{now:6.1f}s] vhposr={vh.hex()}")
        time.sleep(1.0)


#: A `peek` spec.  `+OFFSET` is a data-hunk offset; `*POINTER+OFFSET` reads the
#: 32-bit big-endian pointer at the data-hunk offset POINTER and then reads at
#: what it holds plus OFFSET, which is how the engine's own records are reached.
PEEK_SPEC = re.compile(r"^(?:\+(?P<at>\w+)|\*(?P<ptr>\w+)\+(?P<off>\w+))$")


def resolve_spec(tgt, spec: str) -> int | None:
    """The address a `+OFFSET` or `*POINTER+OFFSET` spec names, None for a null pointer."""
    found = PEEK_SPEC.match(spec.strip())
    if found is None:
        raise ValueError(f"{spec!r} is neither +OFFSET nor *POINTER+OFFSET")
    if tgt is None or tgt.data_base is None:
        raise amiga.GuestError("a data-hunk offset needs the data hunk's "
                               "address; run `locate` first")
    if found["at"] is not None:
        return tgt.data_base + int(found["at"], 0)
    pointer = int.from_bytes(
        tgt.read(tgt.data_base + int(found["ptr"], 0), 4), "big")
    if pointer == 0:
        return None
    return pointer + int(found["off"], 0)


def read_spec(tgt, spec: str, length: int) -> bytes | None:
    """Memory named by a `peek` spec, or None when its pointer is null.

    Read-only on purpose: a spec that cannot say a write cannot be mistyped
    into one.
    """
    if length < 1:
        raise ValueError("a peek of nothing is not a read")
    if PEEK_SPEC.match(spec.strip()) is None:
        raise ValueError(f"{spec!r} is neither +OFFSET nor *POINTER+OFFSET")
    if tgt.data_base is None:
        raise amiga.GuestError("peek needs the data hunk's address; run "
                               "`locate` first")
    address = resolve_spec(tgt, spec)
    return None if address is None else tgt.read(address, length)


#: The most a `poke` writes: one `M` packet must fit the server's 512-byte
#: receive buffer, and a test-harness edit of a few bytes needs no more.
POKE_LIMIT = 64

#: Seconds to wait for the answer to an `M`; a server with no write handler
#: sends nothing, and the full packet timeout would stall the session.
POKE_TIMEOUT = 3.0


def poke_row(gdb, tgt, rest: str) -> dict:
    """`poke SPEC HEX` as a log row: a write through the session's own GDB client.

    `AmigaTarget.write` refuses a GDB transport because Wish's product path
    only reads, not because the emulator cannot write; this verb sends the `M`
    packet itself, which the installed `fs-uae-gdb` handles. It never trusts the
    reply alone: the bytes are read back, and a write the server ignored is an
    error row.
    """
    spec, _, digits = rest.strip().partition(" ")
    row = {"spec": spec}
    try:
        data = bytes.fromhex(digits.replace(" ", ""))
        if not data:
            raise ValueError("poke wants SPEC HEXBYTES")
        if len(data) > POKE_LIMIT:
            raise ValueError(f"poke of {len(data)} bytes is over the "
                             f"{POKE_LIMIT}-byte limit")
        if re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|\d+)", spec):
            address = int(spec, 0)
        else:
            address = resolve_spec(tgt, spec)
            if address is None:
                return {**row, "error": "the pointer is null"}
        row["address"] = address
        if not any(base <= address and address + len(data) <= base + size
                   for base, size in amiga.MEMORY):
            raise ValueError(f"{address:#x}..{address + len(data):#x} is outside "
                             "the machine's memory regions")
        old = gdb.read_memory(address, len(data))
        row["old"] = old.hex()
        reply = gdb.ask(f"M{address:x},{len(data):x}:{data.hex()}",
                        timeout=POKE_TIMEOUT)
        if reply != "OK":
            raise amiga.GuestError(
                f"the server answered {reply!r} to the write; a build "
                "without an `M` handler answers with nothing")
        new = gdb.read_memory(address, len(data))
        row["new"] = new.hex()
        if new != data:
            raise amiga.GuestError("the server said OK but the bytes read back "
                                   "are not the ones written")
    except (ValueError, amiga.GuestError, amiga.FsuaeError) as exc:
        return {**row, "error": f"{type(exc).__name__}: {exc}"}
    return row


def dump_row(gdb, rest: str, out: pathlib.Path) -> dict:
    """`dump NAME ADDRESS LENGTH` as a log row, the bytes in `out/dumps/NAME.bin`.

    Absolute, read straight off the connection: the point is to capture memory
    of a title that has no layout, and a read the server refuses is a row too
    because the one connection cannot be taken up again.
    """
    parts = rest.split()
    if len(parts) != 3:
        raise ValueError("dump wants NAME ADDRESS LENGTH")
    name, address, length = parts[0], int(parts[1], 0), int(parts[2], 0)
    if not re.fullmatch(r"\w[\w.-]*", name):
        raise ValueError(f"dump name {name!r} must be a plain file name")
    if not 0 < length <= DUMP_LIMIT:
        raise ValueError(f"dump length {length:#x} is outside 1..{DUMP_LIMIT:#x}")
    row = {"name": name, "address": address, "length": length}
    try:
        blob = gdb.read_memory(address, length)
    except (amiga.GuestError, amiga.FsuaeError) as exc:
        return {**row, "error": f"{type(exc).__name__}: {exc}"}
    (out / "dumps").mkdir(exist_ok=True)
    path = out / "dumps" / f"{name}.bin"
    path.write_bytes(blob)
    return {**row, "length": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
            "path": str(path)}


def peek_row(tgt, spec: str, length: int) -> dict:
    """One `read_spec` as a log row; a refusal or a failed read is a row too."""
    row = {"spec": spec, "length": length}
    try:
        got = read_spec(tgt, spec, length)
    except (ValueError, amiga.GuestError, amiga.FsuaeError) as exc:
        return {**row, "hex": None, "error": str(exc)}
    return {**row, "hex": None if got is None else got.hex(),
            "null_pointer": got is None}


def parse_peeks(items: list[str] | None) -> list[tuple[str, int]]:
    """`['+0x5B12 1', '*0x57AC+0x24 3']` as `[(spec, length)]`."""
    out = []
    for item in items or []:
        spec, _, length = item.rpartition(" ")
        if not spec:
            raise SystemExit(f"--peeks wants 'SPEC LENGTH', got {item!r}")
        out.append((spec, int(length, 0)))
    return out


def expand_sequence(text: str, index: int) -> list[str]:
    """`'F12 Down*{index} Return'` as the keys to press for swap list `index`.

    `{index}` is replaced as text first, and `KEY*N` repeats a key, so a menu
    that is walked by counting entries can be written down.
    """
    keys = []
    for token in text.replace("{index}", str(index)).split():
        key, star, count = token.partition("*")
        keys += [key] * (int(count) if star else 1)
    return keys


#: The F12 menu walk that inserted a swap list image in boot M's hand-driven
#: run: open the menu, three Down and Return to reach the disk entries, Down to
#: the media row and Return, then F12 to close it.  `Down*{index}` is right only
#: while the media row's position equals the swap index; which row is the
#: right one depends on which disks are already in the drives, so check the
#: first swap by screenshot and pass `--swap-sequence` when the count differs.
DEFAULT_SWAP_SEQUENCE = "F12 Down*3 Return Down*{index} Return F12"


def insert_floppy(sequence: str | None, index: int, press_key, wait_still) -> list[str]:
    """Put swap list image `index` into the drive, the one place that does it.

    Everything else about a swap -- the screenshots either side, the log lines,
    the command -- is built around this.  The fork binds no key to a disk
    change, so the keys are an F12 menu walk, `DEFAULT_SWAP_SEQUENCE`.
    """
    if not sequence:
        raise NotImplementedError(
            "swap has no key sequence: how the F12 menu inserts a swap list "
            "image with xdotool is still being measured on #804; pass the "
            "measured sequence as --swap-sequence")
    keys = expand_sequence(sequence, index)
    for n, key in enumerate(keys):
        press_key(key)
        wait_still(f"swap{index}-{n}")
    return keys


#: What the emulator writes to `fs-uae.log` when a disk change reaches the core.
SWAP_LOG = re.compile(r"gui_disk_image_change|perform disk_swap")


def swap_log_lines(log_path: pathlib.Path | None, since: int) -> list[str]:
    """The disk-change lines written to the emulator log after byte `since`."""
    if log_path is None or not log_path.exists():
        return []
    text = log_path.read_bytes()[since:].decode("utf-8", "replace")
    return [line for line in text.splitlines() if SWAP_LOG.search(line)]


def block_match(tgt, maps: dict) -> dict:
    """Whether the resident block is byte-identical to one of `maps`, and which."""
    try:
        block = tgt.geo()
    except (amiga.GuestError, amiga.FsuaeError) as exc:
        return {"resident": None, "error": str(exc)}
    if block is None:
        return {"resident": None}
    return {"resident": [name for name, geo in sorted(maps.items())
                         if geo.to_bytes() == block]}


def poller(tgt, maps, layout, out: pathlib.Path, note):
    """An `Automapper` over this target, and a function that polls it once.

    Shared by `automap` and `session` so both run the *same* shipped code and
    write the same log: a proof that differs between two commands in this file
    is a proof of this file.
    """
    from automap import render
    from automap.state import Automapper

    mapper = Automapper(tgt, maps, title=layout.title)
    counter = [0]

    def once():
        i = counter[0]
        counter[0] += 1
        started = time.monotonic()
        changed = mapper.poll()
        st = mapper.state
        row = dict(event="poll", i=i,
                   seconds=round(time.monotonic() - started, 3),
                   changed=changed, area=st.area, x=st.x, y=st.y,
                   facing=st.facing, source=st.source,
                   title=mapper.title_check,
                   candidates=str(st.candidates) if st.candidates else None,
                   seen=len(st.exploration.seen))
        note(**row)
        print(f"poll {i:2d}  {row['seconds']:6.3f}s  {st.area or '-':6} "
              f"{st.x},{st.y} "
              f"{'NESW'[st.facing] if st.facing is not None else '?'}"
              f"  seen {row['seen']:3d}  {row['candidates']}")
        if st.geo is not None:
            seen = set(st.exploration.seen)
            svg = render.to_svg(
                st.geo, visible=(lambda x, y: (x, y) in seen) if seen else None,
                party=(st.x, st.y, st.facing or 0), notes=st.notes or None)
            (out / f"poll{i:02d}.svg").write_text(svg, encoding="utf-8")
        return st

    return mapper, once


def shot(display: str, path: pathlib.Path) -> None:
    """The emulator's own screen, off the X server it is drawing on."""
    subprocess.run(["import", "-window", "root", str(path)],
                   env={"DISPLAY": display, "PATH": "/usr/bin:/bin"},
                   check=False)


def journal(args, adf: str = "") -> bool:
    """Answer Silver Blades' journal prompt, with the game still running.

    The reading is `tools/amiga/amigabladesjournal.py`'s and the tables come off the
    player's own disk at run time; this supplies the two ends that differ on
    this emulator -- a screenshot off the X server the emulator draws on, and
    keys through XTEST.  Nothing about the challenge or its answer is printed
    or written down, which is that tool's rule and not this one's to relax.
    """
    from tools.amiga import amigabladesjournal as journal_tool

    return journal_tool.answer(
        holder="", settle=args.settle,
        adf=journal_tool.find_disk(adf or None),
        capture=lambda path: shot(args.display, pathlib.Path(path)),
        # The answer's case comes from the disk's tables; the game shows
        # upper case whatever is typed.
        press=lambda key: press(args.display,
                                "Return" if key == "RET" else
                                key.lower() if len(key) == 1 else key,
                                args.settle))


def session(args) -> int:
    """Hold the one connection open and take commands from a file.

    **This exists because of the fork's sharpest limit.**  The emulator hands
    out one connection per run and shuts its listening socket when that
    connection goes, so a game cannot be booted by one command and mapped by
    the next: whatever drives the boot has to still be holding the socket when
    the mapping starts.  A file of commands is what lets a person -- or an
    agent watching screenshots -- decide what to do next without dropping it.

    One command a line, appended to `--commands` while this runs:

        key <keysym>...     keystrokes into the emulator, each held `--hold` s
                            (0.12 by default: the game misses a tap)
        shot <name>         a screenshot into the run directory
        still [label]       wait until the screen stops changing
        wait <seconds>      wait
        dump <name> <addr> <n>
                            n bytes (at most 0x80000) from an absolute address
                            into `dumps/<name>.bin`, with a row giving the
                            address, length and sha256.  Needs no `locate`
        locate              measure the data hunk's load address
        fix                 where the party is, from the engine's globals
        peek <spec> <n>     n bytes of memory: `+0x5B12` is a data-hunk
                            offset, `*0x57AC+0x24` dereferences the pointer
                            there first.  Read-only; refused before `locate`
        poke <spec> <hex>   CHANGES THE RUNNING GAME: writes up to 64 bytes
                            with an `M` packet and logs address, old and new
                            bytes.  `<spec>` is a peek spec or an absolute
                            address; a write outside chip and slow memory is
                            an error row.  Needs a server with `M`; read back,
                            so an ignored write is an error row too
        swap <index>        put swap list image <index> in the drive, by the
                            keys of `--swap-sequence` (default: the F12 menu
                            walk, see DEFAULT_SWAP_SEQUENCE)
        observe <name>      one observation: the game's screenshot, a tick of
                            the automapper (the real tab with `--window`),
                            the `--peeks`, and the raw fix
        poll [n]            n shipped-automapper polls, drawing each map
        time [n]            n timed reads at each of `PROBE_SIZES`
        journal [adf]       answer Silver Blades' journal prompt
        quit

    `--title none` starts a session with no layout, for a title that has no
    `MACHINES` row: no detection, no maps, no poller.  `locate`, `fix`, `peek`,
    `observe` and `poll` then log an error row (`no title`); `key`, `shot`,
    `still`, `wait`, `swap`, `time`, `journal` and `dump` work as usual.

    Anything unrecognised, and any command with a bad argument or no
    configuration (`swap` with no key sequence, `wait x`), is logged as a row
    with an `error` and the session carries on: a typo costs a line rather than
    the run.
    """
    from automap import state as mapstate
    from tools.amiga.amigatarget import find_maps

    out = pathlib.Path(args.out)
    # Every argument that can fail is checked before the connection, because
    # the debugger port takes one client per emulator run.
    peeks = check_arguments(args)
    (out / "shots").mkdir(parents=True, exist_ok=True)
    commands = pathlib.Path(args.commands)
    commands.touch()
    untitled = args.title == NO_TITLE
    layout = amiga.MACHINES[args.title] if args.title and not untitled else None
    maps = image = None
    if layout is not None:
        maps, image = find_maps(layout, args.maps)
    swap_log = pathlib.Path(args.fs_uae_log) if args.fs_uae_log else None
    gdb = connect(args)
    print(f"Server     {gdb.greeting}")
    if layout is None and not untitled:
        try:
            layout = detect_layout(gdb)
            maps, image = find_maps(layout, args.maps)
        except BaseException:
            gdb.close()
            raise
        print(f"Title      {layout.title}")
    if untitled:
        maps = {}
        print("Title      none: no layout, so no maps and no poller")
    else:
        print(f"Maps       {len(maps)} from {image}")
    tgt = None if untitled else amiga.AmigaTarget(gdb, layout)
    log = (out / "session.jsonl").open("a", encoding="utf-8")

    def note(**payload) -> None:
        payload["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(payload) + "\n")
        log.flush()

    # Checked once, here, so each `swap` line does not rediscover it.
    swap_error = None if args.swap_sequence else (
        "swap has no key sequence: pass --swap-sequence (see #804)")
    if swap_error:
        print(f"           {swap_error}")
    was = mapstate._data_dir                            # noqa: SLF001
    mapstate._data_dir = lambda: out / "data"           # noqa: SLF001
    started = time.monotonic()
    read = 0
    try:
        once = None if untitled else poller(tgt, maps, layout, out, note)[1]
        window = None
        if args.window:
            window = open_window(tgt, args.maps, out)
        note(event="session", port=args.port, maps=len(maps),
             image=None if image is None else str(image),
             window=bool(args.window))
        while time.monotonic() - started < args.seconds:
            lines = commands.read_text().splitlines()
            while read < len(lines):
                line = lines[read].strip()
                read += 1
                if not line or line.startswith("#"):
                    continue
                word, _, rest = line.partition(" ")
                now = round(time.monotonic() - started, 1)
                print(f"[{now:7.1f}s] {line}")
                if word == "quit":
                    return 0
                # A mistyped or unconfigured command costs its own line, not
                # the run: the one connection cannot be taken up again.
                try:
                    if untitled and word in TITLED_COMMANDS:
                        error = (f"no title: `{word}` needs a layout and this "
                                 f"session was started with --title {NO_TITLE}")
                        print(f"           {error}")
                        note(event=word, at=now, error=error)
                    elif word == "key":
                        names = [resolve_key(args.display, k)
                                 for k in rest.split()]
                        for key in names:
                            held_key(args, key)
                        note(event="key", keys=rest, at=now)
                    elif word == "shot":
                        shot(args.display, out / "shots" / f"{rest or now}.png")
                    elif word == "still":
                        still(args, out, rest or str(now))
                        note(event="still", label=rest, at=now)
                    elif word == "wait":
                        time.sleep(float(rest))
                        note(event="wait", seconds=float(rest), at=now)
                    elif word == "dump":
                        row = dump_row(gdb, rest, out)
                        print(f"           {row}")
                        note(event="dump", at=now, **row)
                    elif word == "peek":
                        spec, _, length = rest.rpartition(" ")
                        row = peek_row(tgt, spec, int(length or 1, 0))
                        print(f"           {row}")
                        note(event="peek", at=now, **row)
                    elif word == "poke":
                        row = poke_row(gdb, tgt, rest)
                        print(f"           {row}")
                        note(event="poke", at=now, **row)
                    elif word == "swap":
                        if swap_error is not None:
                            note(event="swap", at=now, error=swap_error)
                        else:
                            row = do_swap(args, int(rest), out, swap_log)
                            # The default Down count is measured for one
                            # disk set; with no emulator log nothing says
                            # the right disk went in.
                            if (args.swap_sequence == DEFAULT_SWAP_SEQUENCE
                                    and swap_log is None):
                                row.update(default_sequence=True, unchecked=True)
                            note(event="swap", at=now, **row)
                    elif word == "observe":
                        note(event="observe", at=now,
                             **observe(args, rest or str(now), tgt, maps, out,
                                       once, window, peeks))
                    elif word == "locate":
                        try:
                            base = tgt.locate()
                            print(f"           data hunk {base:#010x}   "
                                  f"a4 {base + A4_BIAS:#010x}")
                            note(event="locate", base=base, at=now)
                        except amiga.GuestError as exc:
                            print(f"           {exc}")
                            note(event="locate", base=None, why=str(exc), at=now)
                    elif word == "fix":
                        got = None if tgt.data_base is None else tgt.fix()
                        print(f"           {got}")
                        note(event="fix", fix=None if got is None else
                             [got.x, got.y, got.facing], at=now)
                    elif word == "poll":
                        for _ in range(int(rest or 1)):
                            once()
                    elif word == "time":
                        for size in PROBE_SIZES:
                            got = []
                            for _ in range(int(rest or 10)):
                                begun = time.perf_counter()
                                gdb.read_memory(args.at, size)
                                got.append(1000 * (time.perf_counter() - begun))
                            got.sort()
                            print(f"           {size:>7} bytes  n={len(got)}  "
                                  f"min {got[0]:.1f} ms  "
                                  f"median {got[len(got) // 2]:.1f} ms  "
                                  f"max {got[-1]:.1f} ms")
                            note(event="time", size=size, ms=[round(v, 2)
                                                              for v in got], at=now)
                    elif word == "journal":
                        note(event="journal", answered=journal(args, rest), at=now)
                    else:
                        note(event="unknown", line=line, at=now)
                except (ValueError, NotImplementedError, SystemExit) as exc:
                    # The `fsuaepor` helpers under `key`, `swap` and `still` end
                    # a failed wait or a missing window with SystemExit; here
                    # that would close the emulator's only debugger connection
                    # for good.
                    print(f"           {exc}")
                    note(event=word, at=now,
                         error=f"{type(exc).__name__}: {exc}")
            # The heartbeat is also the proof: a read every second, from a
            # machine nobody has stopped.
            vh = gdb.read_memory(VHPOSR, 2)
            note(event="beat", vhposr=vh.hex(),
                 at=round(time.monotonic() - started, 1))
            time.sleep(args.interval)
    finally:
        mapstate._data_dir = was                        # noqa: SLF001
        log.close()
        gdb.close()
    return 0


def check_arguments(args) -> list[tuple[str, int]]:
    """Everything `session` can reject, rejected before it connects.

    The patched FS-UAE closes its debugger port for good when the first client
    disconnects, so an argument error found after connecting costs a boot.
    Returns the parsed `--peeks`.
    """
    if args.maps and not pathlib.Path(args.maps).exists():
        raise SystemExit(f"--maps {args.maps} does not exist; it takes a disk "
                         "image or the folder holding the game's disk images")
    if (args.maps or args.window) and not args.title:
        # With no title the layout is detected after connecting, and only then
        # can the maps be looked for; a bad `--maps` would spend the one client.
        raise SystemExit("--maps and --window need --title "
                         f"({', '.join(sorted(amiga.MACHINES))}): without one "
                         "the title is detected after the connection is open")
    if (args.maps or args.window) and args.title == NO_TITLE:
        raise SystemExit(f"--maps and --window need a title's layout; "
                         f"--title {NO_TITLE} has none")
    if args.window and not args.maps:
        raise SystemExit("--window needs --maps to be the folder holding the "
                         "game's disk images")
    if args.swap_sequence:
        try:
            expand_sequence(args.swap_sequence, 0)
        except ValueError as exc:
            raise SystemExit(f"--swap-sequence {args.swap_sequence!r}: {exc}"
                             ) from exc
    try:
        return parse_peeks(args.peeks)
    except ValueError as exc:
        raise SystemExit(f"--peeks: {exc}") from exc


#: Spellings people type that xdotool does not know.
KEY_ALIASES = {"ESC": "Escape", "RET": "Return"}


def resolve_key(display: str, key: str) -> str:
    """The xdotool name for `key`, or ValueError when xdotool has no such key.

    xdotool prints "No such key name" and still exits 0, so an unknown name
    would otherwise be a keystroke that silently never happened.  The probe is
    a `keyup`, which releases a key nobody holds.
    """
    key = KEY_ALIASES.get(key, key)
    refuse_shift_letter(key)
    if not key_known(display, key):
        raise ValueError(f"no such key name {key!r}")
    return key


def key_known(display: str, key: str) -> bool:
    try:
        done = subprocess.run(["xdotool", "keyup", key], capture_output=True,
                              text=True, check=False,
                              env={"DISPLAY": display, "PATH": "/usr/bin:/bin"})
    except FileNotFoundError as exc:
        raise ValueError("xdotool is not installed, so key names cannot be "
                         "checked or sent") from exc
    return "No such key name" not in done.stdout + done.stderr


def held_key(args, key: str) -> None:
    """One keystroke held `--hold` seconds, which the game needs to see it.

    Shares `fsuaepor.keys`, the implementation the `amiga-pod` runs used.  A
    hold of 0 is the old unheld `xdotool key`.
    """
    if not args.hold:
        press(args.display, key, args.settle)
        return
    from tools.amiga import fsuaepor

    fsuaepor.keys(argparse.Namespace(display=args.display, key=[key],
                                     hold=args.hold, settle=args.settle))


def still(args, out: pathlib.Path, label: str) -> None:
    """Wait for the emulator's screen to stop changing (`fsuaepor`'s own wait)."""
    from tools.amiga import fsuaepor

    fsuaepor._wait_until_still(                         # noqa: SLF001
        args.display, label,
        lambda name: shot(args.display, out / "shots" / f"{name}.png"))


def do_swap(args, index: int, out: pathlib.Path,
            log_path: pathlib.Path | None) -> dict:
    """`insert_floppy`, between two screenshots, with the log lines it caused."""
    since = (log_path.stat().st_size
             if log_path is not None and log_path.exists() else 0)
    shot(args.display, out / "shots" / f"swap{index}-before.png")
    keys = insert_floppy(args.swap_sequence, index,
                         lambda key: held_key(args, key),
                         lambda label: still(args, out, label))
    shot(args.display, out / "shots" / f"swap{index}-after.png")
    return {"index": index, "keys": keys,
            "log": swap_log_lines(log_path, since)}


def open_window(tgt, disks: str | None, out: pathlib.Path):
    """The real map tab over `tgt`, offscreen, loading its maps from `disks`.

    The maps come from `load_maps_titled(..., amiga_only=True)`, the way a
    player's window loads them, so what is observed is what a player sees.
    """
    if disks and pathlib.Path(disks).is_file():
        disks = str(pathlib.Path(disks).parent)
    if not disks or not pathlib.Path(disks).is_dir():
        raise SystemExit("--window needs --maps to be the folder holding the "
                         "game's disk images")
    from tools.gui import mapmarker

    mapmarker._offscreen()                              # noqa: SLF001
    return mapmarker.build_window(tgt, disks, out, amiga_only=True)


def observe(args, name: str, tgt, maps: dict, out: pathlib.Path, once,
            window, peeks: list[tuple[str, int]]) -> dict:
    """One observation, written as a single row.

    Without a window it ticks the shipped automapper once; with one it ticks
    the real tab `LIVE_EVERY + 1` times, as the tab's own timer would, and
    photographs it.  A tick that raises is recorded rather than ending the run,
    because the row is the evidence.
    """
    from automap import render

    shot(args.display, out / "shots" / f"{name}.png")
    row: dict = {"name": name, "error": None}
    st = None
    try:
        if window is None:
            st = once()
            row["tab"] = {"x": st.x, "y": st.y, "facing": st.facing,
                          "area": st.area, "source": st.source,
                          "candidates": str(st.candidates) if st.candidates
                          else None, "seen_squares": len(st.exploration.seen)}
        else:
            from tools.gui import mapmarker

            app, _root, binding, _maps = window
            for _ in range(binding.LIVE_EVERY + 1):
                binding.tick()
                app.processEvents()
            st = binding.state
            row["tab"] = mapmarker.reading(binding, name)
            mapmarker.shot(app, binding.root, out / f"{name}-window.png")
            mapmarker.shot(app, binding.canvas, out / f"{name}-map.png")
    except Exception as exc:                    # noqa: BLE001 -- the row is the evidence
        row["error"] = f"{type(exc).__name__}: {exc}"
    if st is not None and st.geo is not None:
        seen = set(st.exploration.seen)
        (out / f"{name}.svg").write_text(render.to_svg(
            st.geo, visible=(lambda x, y: (x, y) in seen) if seen else None,
            party=(st.x, st.y, st.facing or 0), notes=st.notes or None),
            encoding="utf-8")
    try:
        got = tgt.fix()
        row["fix"] = None if got is None else dataclasses.asdict(got)
        row["geo_pointer"] = (None if tgt.data_base is None
                              else tgt.resident_geo_address())
    except Exception as exc:                    # noqa: BLE001 -- recorded, not fatal
        row["fix"] = None
        row["fix_error"] = f"{type(exc).__name__}: {exc}"
    row["peeks"] = [peek_row(tgt, spec, length) for spec, length in peeks]
    row["block"] = block_match(tgt, maps)
    return row


def automap(args) -> int:
    """Run the shipped automapper against a running FS-UAE, and draw its map.

    **Nothing here re-derives anything**, which is the whole point of the
    command: `automap.state.Automapper.poll()` moves the marker,
    `automap.area.ResidentGeo` names the area and `automap.render.to_svg`
    paints it -- the same three the window runs on a C64 and the same three
    `tools/amiga/amigatarget.py automap` ran on WinUAE.  This file supplies the
    target, the maps and the keystrokes.

    One JSON line per poll as it happens: a driven run that dies half way must
    still say what it had measured.
    """
    from automap import state as mapstate
    from tools.amiga.amigatarget import find_maps

    refuse_no_title(args, "automap")
    if not args.title:
        # The game may not be loaded yet (`--boot`), so there is nothing to
        # detect before the connection is open, and a wrong guess costs a boot.
        raise SystemExit("automap needs --title: "
                         f"{', '.join(sorted(amiga.MACHINES))}")
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    layout = amiga.MACHINES[args.title]
    maps, image = find_maps(layout, args.maps)
    if not maps:
        raise SystemExit("no Amiga disk image carrying GEO.GLB for "
                         f"{layout.title}; pass --maps")
    print(f"Maps       {len(maps)} from {image}")

    gdb = connect(args)
    if args.boot or args.warmup:
        boot(gdb, args)
    tgt = amiga.AmigaTarget(gdb, layout)
    base = None
    for attempt in range(args.locate_tries):
        try:
            base = tgt.locate()
            break
        except amiga.GuestError as exc:
            # The anchor is only in memory once the title's own executable has
            # been loaded, so "not found" early in a boot is a state to wait
            # out rather than a failure.
            print(f"locate {attempt}: {exc}")
            time.sleep(args.settle)
    if base is None:
        raise SystemExit(f"{layout.title} never appeared in this machine's "
                         "memory; it is not the title that is running")
    print(f"Data hunk  {base:#010x}   a4 {base + A4_BIAS:#010x}")
    log = (out / "automap.jsonl").open("a", encoding="utf-8")

    def note(**payload) -> None:
        payload["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(payload) + "\n")
        log.flush()

    # The player's own notes live in `automap.paths.data_dir()`; a driven run
    # must not write into them.  Rebound in the function and put back on the
    # way out, which is `tools/amiga/amigatarget.py`'s rule and `#428`'s incident.
    was = mapstate._data_dir                            # noqa: SLF001
    mapstate._data_dir = lambda: out / "data"           # noqa: SLF001
    try:
        note(event="start", title=layout.title, data_base=tgt.data_base,
             maps=sorted(maps), image=str(image))
        _mapper, once = poller(tgt, maps, layout, out, note)
        walk = [k for k in (args.walk or "").replace(",", " ").split() if k]
        steps = 0
        for i in range(args.polls):
            once()
            if steps < len(walk):
                press(args.display, walk[steps], args.settle)
                note(event="key", i=i, key=walk[steps])
                print(f"          pressed {walk[steps]}")
                steps += 1
    finally:
        mapstate._data_dir = was                        # noqa: SLF001
        log.close()
    return 0


# -- launching one, silently and offscreen ------------------------------------


def launch(args) -> int:
    """Start an `Xvfb` and the emulator inside it, and wait for the port.

    Four things every run of this needs, and each has cost somebody a session:

    * a private `Xvfb`, with `WAYLAND_DISPLAY` and `XDG_SESSION_TYPE` unset,
      because a GTK or SDL child prefers Wayland over whatever `DISPLAY` says
      and would draw on the desktop of whoever is sitting there;
    * `SDL_AUDIODRIVER=dummy`.  **`--volume=0` does not silence this build** --
      three runs that passed it were heard through the speakers on 2026-09-08;
    * a `base_dir` under the run's own directory, so `~/FS-UAE/` is untouched;
    * `setsid`, so the whole thing is one process group and the teardown kills
      that group rather than a name.

    Prints the two pids and the display.  Kill with `kill -- -<pid>`.
    """
    # Every path here is resolved, and that is not tidiness: the emulator runs
    # with its own directory as the working directory, so a relative
    # `--kickstart_file` fails with `Failed to open ...` and the machine boots
    # the built-in AROS ROM instead -- which looks like a game that will not
    # load rather than like a path that was not found.
    run = pathlib.Path(args.out).resolve()
    (run / "base").mkdir(parents=True, exist_ok=True)
    binary = pathlib.Path(args.fs_uae).resolve()
    if not binary.exists():
        raise SystemExit(f"{binary} is not on this machine; --fs-uae takes a "
                         "path to a patched FS-UAE that is already here")

    foreground = bool(args.foreground)
    # Detached, `launch` returns and `stop` ends the group.  In the foreground
    # both stay in the caller's process group, so whatever holds the lease
    # (the pool slot's `claim --`) ends them by ending itself.
    xvfb = emulator = None
    try:
        xvfb = subprocess.Popen(
            ["Xvfb", args.display, "-screen", "0", "800x600x24", "-nolisten",
             "tcp"],
            stdout=(run / "xvfb.log").open("wb"), stderr=subprocess.STDOUT,
            start_new_session=not foreground)
        time.sleep(2)

        env = dict(os.environ)
        for name in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
            env.pop(name, None)
        env.update(DISPLAY=args.display, GDK_BACKEND="x11",
                   SDL_AUDIODRIVER="dummy", ALSOFT_DRIVERS="null")
        argv = [str(binary), f"--base_dir={run / 'base'}", "--fullscreen=0",
                f"--remote_debugger={args.wait}",
                f"--remote_debugger_port={args.port}"]
        if args.kickstart:
            argv.append(f"--kickstart_file={pathlib.Path(args.kickstart).resolve()}")
        floppies = [pathlib.Path(f).resolve() for f in args.floppy or []]
        swaps = [pathlib.Path(f).resolve() for f in args.swap or []]
        for i, floppy in enumerate(floppies):
            argv.append(f"--floppy_drive_{i}={floppy}")
        # The swap list holds the drives' images first, then the swaps, as
        # `fsuaepor.fsuae_argv` writes it; none given leaves the command line as it was.
        if swaps:
            argv += [f"--floppy_image_{i}={image}"
                     for i, image in enumerate([*floppies, *swaps])]
        if foreground:
            # A driven run sends keys only, so nothing may arrive from port 1.
            argv.append("--joystick_port_1=none")
        argv += list(args.extra or [])
        emulator = subprocess.Popen(
            argv, env=env, cwd=str(binary.parent),
            stdout=(run / "fs-uae.log").open("wb"), stderr=subprocess.STDOUT,
            start_new_session=not foreground)

        print(f"display    {args.display}")
        print(f"xvfb       {xvfb.pid}")
        print(f"fs-uae     {emulator.pid}   (kill -- -{emulator.pid})")
        print(f"port       {args.port}", flush=True)
        if foreground:
            return wait_foreground(emulator, xvfb)
        for _ in range(args.wait * 2):
            listening = subprocess.run(["ss", "-ltn"], capture_output=True,
                                       text=True, check=False).stdout
            if f":{args.port}" in listening:
                print("listening  yes")
                return 0
            time.sleep(0.5)
        print("listening  NO -- see " + str(run / "fs-uae.log"))
        return 1
    except BaseException:
        # Detached, `stop` is given the pids printed after both starts, so a
        # failure before that leaves an Xvfb in its own session nobody can find.
        if not foreground:
            terminate(emulator, xvfb)
        raise
    finally:
        # From the first Popen, so a failing emulator start or an interrupt
        # during the Xvfb's settling sleep does not leave the Xvfb behind.
        if foreground:
            terminate(emulator, xvfb)


def wait_foreground(emulator, xvfb) -> int:
    """Wait for the emulator to exit, then take the `Xvfb` down after it."""
    try:
        return emulator.wait()
    finally:
        terminate(emulator, xvfb)


def terminate(*procs) -> None:
    """SIGTERM each process still running (kill after 10 s); None is skipped."""
    for proc in procs:
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def alive(pid: int) -> bool:
    """Whether `pid` is a live process; a zombie awaiting its parent is not."""
    try:
        state = pathlib.Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2]
    except OSError:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    return state.split()[0] != "Z"


def stop(args) -> int:
    """Kill one process group, by pid, which is the only sanctioned way.

    Reports what happened: gone after the signal, still running after
    `--wait` seconds, not running, or a live pid that leads no group (a
    `launch --foreground` process, which lives in its caller's group and is
    ended by ending the caller) -- which is not signalled.
    """
    status = 0
    for pid in args.pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            if alive(pid):
                print(f"{pid} is running but leads no process group, so "
                      "nothing was signalled; a --foreground launch ends "
                      "with the process that holds its lease")
                status = 1
            else:
                print(f"{pid} is not running")
            continue
        deadline = time.monotonic() + args.wait
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if alive(pid):
            print(f"{pid} is still running {args.wait:g} s after SIGTERM")
            status = 1
        else:
            print(f"{pid} stopped")
    return status


# -- reading one range --------------------------------------------------------


def dump(args) -> int:
    tgt = target(args) if args.relative else None
    gdb = tgt.debugger if tgt is not None else connect(args)
    at = tgt.data_base + args.at if args.relative else args.at
    started = time.perf_counter()
    blob = gdb.read_memory(at, args.length)
    print(f"{len(blob)} bytes from {at:#010x} in "
          f"{1000 * (time.perf_counter() - started):.1f} ms")
    pathlib.Path(args.out).write_bytes(blob)
    print(f"Written to {args.out}")
    return 0


def fix(args) -> int:
    tgt = target(args)
    reading = tgt.fix()
    print("No fix: the party is not standing on a square the engine "
          "recognises (a menu, camp, or a load in flight)" if reading is None
          else f"Party {reading.x},{reading.y} facing {reading.facing} "
               f"({'NESW'[reading.facing]})")
    return 0


def geo(args) -> int:
    tgt = target(args)
    addr = tgt.resident_geo_address()
    if addr is None:
        print("No map is resident: the GEO pointer holds no address")
        return 0
    block = tgt.read(addr, 0x400)
    print(f"Resident map at {addr:#010x}, {len(block)} bytes")
    if args.out:
        pathlib.Path(args.out).write_bytes(block)
        print(f"Written to {args.out}")
    return 0


def locate(args) -> int:
    target(args)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1",
                        help="the server binds 127.0.0.1 and nothing else")
    parser.add_argument("--port", type=int, default=amiga.FSUAE_PORT,
                        help=f"remote_debugger_port (default "
                             f"{amiga.FSUAE_PORT})")
    parser.add_argument("--timeout", type=float, default=None,
                        help="seconds to wait for one packet's reply")
    parser.add_argument("--title", choices=[*sorted(amiga.MACHINES), NO_TITLE],
                        help="which title is running; without it the running "
                             "title is detected from the Amiga's memory "
                             "(`automap` needs it, because it boots the game); "
                             f"`{NO_TITLE}` starts a `session` with no layout "
                             "for a title that has no row, where `dump` reads "
                             "raw memory and the commands that need a layout "
                             "log an error")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe", help="connect, continue, and time reads")
    p.add_argument("--polls", type=int, default=8)
    p.add_argument("--interval", type=float, default=0.3)
    p.add_argument("--at", type=lambda s: int(s, 0), default=0xC00000,
                   help="where the timed reads come from")
    p.add_argument("--max-read", type=lambda s: int(s, 0),
                   default=512 * 1024,
                   help="skip the sizes above this")
    p.add_argument("--json", help="write the timings here as well")

    sub.add_parser("locate", help="measure the data hunk's load address")
    sub.add_parser("fix", help="where the party is standing")

    g = sub.add_parser("geo", help="the resident 1024-byte map")
    g.add_argument("--out", help="write the block here")

    d = sub.add_parser("dump", help="any range of the running machine")
    d.add_argument("--at", required=True, type=lambda s: int(s, 0))
    d.add_argument("--relative", action="store_true",
                   help="--at is a data-hunk offset instead")
    d.add_argument("--length", required=True, type=lambda s: int(s, 0))
    d.add_argument("--out", required=True)

    m = sub.add_parser("automap",
                       help="run the shipped automapper and draw its map")
    m.add_argument("--out", required=True,
                   help="a directory for the SVGs, the log and the notes")
    m.add_argument("--maps", help="an .adf, or a folder of them")
    m.add_argument("--polls", type=int, default=6)
    m.add_argument("--walk", default="",
                   help="xdotool keysyms to press between polls, e.g. "
                        "'KP_Up KP_Left'")
    m.add_argument("--display", default=os.environ.get("DISPLAY", ":0"),
                   help="the X display the emulator is on")
    m.add_argument("--settle", type=float, default=2.0,
                   help="seconds to wait after each key")
    m.add_argument("--boot", default="",
                   help="keys to press while the game boots, as "
                        "'seconds:key' pairs from the moment the machine is "
                        "continued, e.g. '40:Return;62:p;70:l;78:d;86:b'")
    m.add_argument("--warmup", type=float, default=0.0,
                   help="keep reading for this many seconds after the last "
                        "boot key, before the first poll")
    m.add_argument("--locate-tries", type=int, default=1,
                   help="how many times to look for the title in memory")

    launcher = sub.add_parser(
        "launch", help="start an Xvfb and a patched FS-UAE inside it; its "
                       "debugger port accepts one client per emulator run")
    launcher.add_argument("--fs-uae", required=True,
                          help="path to a patched FS-UAE already on this "
                               "machine; nothing is downloaded")
    launcher.add_argument("--out", required=True,
                          help="a directory for base_dir and the logs")
    launcher.add_argument("--display", default=":77")
    launcher.add_argument("--kickstart")
    launcher.add_argument("--floppy", action="append",
                          help="repeatable: DF0, then DF1, and so on")
    launcher.add_argument("--swap", action="append",
                          help="repeatable: an image only the swap list "
                               "holds, after the --floppy ones")
    launcher.add_argument("--foreground", action="store_true",
                          help="stay in this process group and wait for the "
                               "emulator to exit, so a pool slot's lease "
                               "covers the run; also turns joystick port 1 "
                               "off")
    launcher.add_argument("--wait", type=int, default=60,
                          help="seconds the server waits for a client")
    launcher.add_argument("--extra", nargs=argparse.REMAINDER,
                          help="anything else, passed straight to FS-UAE")

    s = sub.add_parser(
        "session", help="hold the one connection and take commands from a "
                        "file; the debugger port accepts one client per "
                        "emulator run, so a second session needs a new launch")
    s.add_argument("--out", required=True,
                   help="a directory for the SVGs, the log and the shots")
    s.add_argument("--commands", required=True,
                   help="a file to append commands to while this runs")
    s.add_argument("--maps", help="an .adf, or a folder of them")
    s.add_argument("--display", default=os.environ.get("DISPLAY", ":0"))
    s.add_argument("--settle", type=float, default=1.0,
                   help="seconds to wait after each key")
    s.add_argument("--interval", type=float, default=1.0,
                   help="seconds between heartbeat reads")
    s.add_argument("--seconds", type=float, default=1800.0,
                   help="how long to stay up before giving the socket back")
    s.add_argument("--at", type=lambda s: int(s, 0), default=0xC00000,
                   help="where `time` reads from")
    s.add_argument("--hold", type=float, default=0.12,
                   help="seconds a `key` is held down (default 0.12 holds "
                        "every key, as the game needs); 0 sends an unheld "
                        "key")
    s.add_argument("--window", action="store_true",
                   help="`observe` ticks the real map tab, loading its maps "
                        "from the --maps folder, and photographs it")
    s.add_argument("--peeks", nargs="+", metavar="'SPEC LENGTH'",
                   help="memory `observe` records every time, e.g. "
                        "'+0x5B12 1' '*0x57AC+0x24 3'")
    s.add_argument("--swap-sequence",
                   help="the xdotool keys `swap` sends "
                        "(`KEY*N` repeats a key, `{index}` is the swap "
                        "index); default: the measured F12 menu walk "
                        f"'{DEFAULT_SWAP_SEQUENCE}', whose Down count "
                        "assumes the media row's position equals the swap "
                        "index, which depends on the disks in the drives",
                   default=DEFAULT_SWAP_SEQUENCE)
    s.add_argument("--fs-uae-log",
                   help="the emulator's log, where `swap` looks for the disk "
                        "change it caused")

    killer = sub.add_parser("stop", help="kill a launch's process group")
    killer.add_argument("pid", nargs="+", type=int)
    killer.add_argument("--wait", type=float, default=5.0,
                        help="seconds to wait for each group to end")

    args = parser.parse_args(argv)
    return {"probe": probe, "locate": locate, "fix": fix, "geo": geo,
            "dump": dump, "automap": automap, "session": session,
            "launch": launch, "stop": stop}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

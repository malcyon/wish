#!/usr/bin/env python3
"""Read a running Amiga in a patched FS-UAE, over its GDB-remote port.

`automap/amiga.py` carries the transport -- `FsuaeGdb` -- and `AmigaTarget` on
top of it; this is the command line that drives them, the same way
`tools/amigatarget.py` drives the two WinUAE routes.  Nothing here re-derives
an address, a position or a map.

    tools/fsuaegdb.py probe --port 6525
    tools/fsuaegdb.py locate --port 6525
    tools/fsuaegdb.py fix --port 6525
    tools/fsuaegdb.py dump --port 6525 --at 0xC00000 --length 0x400 \\
        --out work/issue464/block.bin
    tools/fsuaegdb.py automap --port 6525 --out work/issue464/run \\
        --polls 8 --walk 'KP_Up KP_Left KP_Up' --display :77

**`probe` is the one to run first.**  It connects, prints what the server
advertises, continues the machine and times a read at four sizes -- and it
samples `VHPOSR` on every poll, because the same raster position poll after
poll is the signature of a reply built in a frame handler rather than by a
halted debugger.

**The emulator this talks to is the fork `grahambates/fs-uae`, branch
`remote_debugger_barto`**, run with `remote_debugger=<seconds>` and
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
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from automap import amiga  # noqa: E402

#: The small-data base these titles are linked with, printed beside the hunk
#: address.  `tools/amigatarget.py` has the same constant for the same reason:
#: `automap/` must not import `tools/`, and this is a printout.
A4_BIAS = 0x7FFE

#: What `probe` reads, in the order it reads them.  16 bytes is the floor of
#: the cost -- the wait for the next frame -- and 512K is one whole region of
#: the A500's memory, which is what `AmigaTarget.locate()` sweeps.
PROBE_SIZES = (16, 1024, 65536, 512 * 1024)

#: `VHPOSR`, the raster position, read every poll as the running-or-halted
#: witness.  Two bytes, and they move every raster line.
VHPOSR = 0xDFF006


def connect(args, resume: bool = True) -> amiga.FsuaeGdb:
    return amiga.FsuaeGdb(host=args.host, port=args.port,
                          timeout=args.timeout, resume=resume)


def target(args) -> amiga.AmigaTarget:
    """A located `AmigaTarget` over the socket, with the base measured.

    The base is measured on every run and never written down: AmigaDOS
    relocates the executable on every `LoadSeg`, so an address from yesterday
    is wrong today.
    """
    layout = amiga.LAYOUTS[args.title]
    gdb = connect(args)
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


def press(display: str, key: str, settle: float) -> None:
    """One keystroke into the emulator, through XTEST on its own display.

    `xdotool key` with no window argument goes to whatever has focus, which on
    a bare `Xvfb` with no window manager is nothing; the focus call is what
    makes SDL see it.  Proven on 2026-09-08, when `alt+q` sent this way shut
    FS-UAE down cleanly.
    """
    env = {"DISPLAY": display, "PATH": "/usr/bin:/bin"}
    found = subprocess.run(["xdotool", "search", "--name", "FS-UAE"],
                           env=env, capture_output=True, text=True,
                           check=False).stdout.split()
    if found:
        subprocess.run(["xdotool", "windowfocus", found[0]], env=env,
                       check=False)
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

    The reading is `tools/amigabladesjournal.py`'s and the tables come off the
    player's own disk at run time; this supplies the two ends that differ on
    this emulator -- a screenshot off the X server the emulator draws on, and
    keys through XTEST.  Nothing about the challenge or its answer is printed
    or written down, which is that tool's rule and not this one's to relax.
    """
    from tools import amigabladesjournal as journal_tool

    return journal_tool.answer(
        holder="", settle=args.settle,
        adf=journal_tool.find_disk(adf or None),
        capture=lambda path: shot(args.display, pathlib.Path(path)),
        press=lambda key: press(args.display,
                                "Return" if key == "RET" else key,
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

        key <keysym>        one keystroke into the emulator
        shot <name>         a screenshot into the run directory
        locate              measure the data hunk's load address
        fix                 where the party is, from the engine's globals
        poll [n]            n shipped-automapper polls, drawing each map
        time [n]            n timed reads at each of `PROBE_SIZES`
        journal [adf]       answer Silver Blades' journal prompt
        quit

    Anything unrecognised is logged and ignored, so a typo costs a line rather
    than the run.
    """
    from automap import state as mapstate
    from tools.amigatarget import find_maps

    out = pathlib.Path(args.out)
    (out / "shots").mkdir(parents=True, exist_ok=True)
    commands = pathlib.Path(args.commands)
    commands.touch()
    layout = amiga.LAYOUTS[args.title]
    maps, image = find_maps(layout, args.maps)
    print(f"Maps       {len(maps)} from {image}")

    gdb = connect(args)
    print(f"Server     {gdb.greeting}")
    tgt = amiga.AmigaTarget(gdb, layout)
    log = (out / "session.jsonl").open("a", encoding="utf-8")

    def note(**payload) -> None:
        payload["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(payload) + "\n")
        log.flush()

    was = mapstate._data_dir                            # noqa: SLF001
    mapstate._data_dir = lambda: out / "data"           # noqa: SLF001
    _mapper, once = poller(tgt, maps, layout, out, note)
    note(event="session", port=args.port, maps=len(maps), image=str(image))
    started = time.monotonic()
    read = 0
    try:
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
                if word == "key":
                    for key in rest.split():
                        press(args.display, key, args.settle)
                    note(event="key", keys=rest, at=now)
                elif word == "shot":
                    shot(args.display, out / "shots" / f"{rest or now}.png")
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
            # The heartbeat is also the proof: a read every second, from a
            # machine nobody has stopped.
            vh = gdb.read_memory(VHPOSR, 2)
            note(event="beat", vhposr=vh.hex(),
                 at=round(time.monotonic() - started, 1))
            time.sleep(args.interval)
    finally:
        mapstate._data_dir = was                        # noqa: SLF001
        log.close()
    return 0


def automap(args) -> int:
    """Run the shipped automapper against a running FS-UAE, and draw its map.

    **Nothing here re-derives anything**, which is the whole point of the
    command: `automap.state.Automapper.poll()` moves the marker,
    `automap.area.ResidentGeo` names the area and `automap.render.to_svg`
    paints it -- the same three the window runs on a C64 and the same three
    `tools/amigatarget.py automap` ran on WinUAE.  This file supplies the
    target, the maps and the keystrokes.

    One JSON line per poll as it happens: a driven run that dies half way must
    still say what it had measured.
    """
    from automap import state as mapstate
    from tools.amigatarget import find_maps

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    layout = amiga.LAYOUTS[args.title]
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
    # way out, which is `tools/amigatarget.py`'s rule and `#428`'s incident.
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

    xvfb = subprocess.Popen(
        ["Xvfb", args.display, "-screen", "0", "800x600x24", "-nolisten",
         "tcp"],
        stdout=(run / "xvfb.log").open("wb"), stderr=subprocess.STDOUT,
        start_new_session=True)
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
    for i, floppy in enumerate(args.floppy or []):
        argv.append(f"--floppy_drive_{i}={pathlib.Path(floppy).resolve()}")
    argv += list(args.extra or [])
    emulator = subprocess.Popen(
        argv, env=env, cwd=str(binary.parent),
        stdout=(run / "fs-uae.log").open("wb"), stderr=subprocess.STDOUT,
        start_new_session=True)

    print(f"display    {args.display}")
    print(f"xvfb       {xvfb.pid}")
    print(f"fs-uae     {emulator.pid}   (kill -- -{emulator.pid})")
    print(f"port       {args.port}")
    for _ in range(args.wait * 2):
        listening = subprocess.run(["ss", "-ltn"], capture_output=True,
                                   text=True, check=False).stdout
        if f":{args.port}" in listening:
            print("listening  yes")
            return 0
        time.sleep(0.5)
    print("listening  NO -- see " + str(run / "fs-uae.log"))
    return 1


def stop(args) -> int:
    """Kill one process group, by pid, which is the only sanctioned way."""
    for pid in args.pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            print(f"{pid} is not running")
    return 0


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
    parser.add_argument("--title", default="secret-of-the-silver-blades",
                        choices=sorted(amiga.LAYOUTS),
                        help="which title is running")
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
        "launch", help="start an Xvfb and a patched FS-UAE inside it")
    launcher.add_argument("--fs-uae", required=True,
                          help="path to a patched FS-UAE already on this "
                               "machine; nothing is downloaded")
    launcher.add_argument("--out", required=True,
                          help="a directory for base_dir and the logs")
    launcher.add_argument("--display", default=":77")
    launcher.add_argument("--kickstart")
    launcher.add_argument("--floppy", action="append",
                          help="repeatable: DF0, then DF1, and so on")
    launcher.add_argument("--wait", type=int, default=60,
                          help="seconds the server waits for a client")
    launcher.add_argument("--extra", nargs=argparse.REMAINDER,
                          help="anything else, passed straight to FS-UAE")

    s = sub.add_parser(
        "session", help="hold the one connection and take commands from a file")
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

    killer = sub.add_parser("stop", help="kill a launch's process group")
    killer.add_argument("pid", nargs="+", type=int)

    args = parser.parse_args(argv)
    return {"probe": probe, "locate": locate, "fix": fix, "geo": geo,
            "dump": dump, "automap": automap, "session": session,
            "launch": launch, "stop": stop}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

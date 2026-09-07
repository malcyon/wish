#!/usr/bin/env python3
"""The smallest thing that reproduces the C64 Ultimate load hang, with no game.

For `#375 (Wish has to work around the Ultimate freezing the C64 mid-load,
which hangs the game while the automapper follows along)`, and written so the
reproduction can be sent upstream: a few lines of BASIC that read from disk in
a loop, and a host-side memory read taken while they run.  Nobody upstream can
act on "a 1989 game hangs sometimes"; they can act on this.

**The claim it demonstrates.** A `GET /v1/machine:readmem` halts the 6510 for
the length of the transfer (measured on this machine: ~42 us fixed + ~1.1 us a
byte).  A halt that lands inside the KERNAL's serial byte-in wait -- which has
no timeout and runs with interrupts off -- makes the C64 miss a clock edge; the
drive times out and releases the bus, and the C64 waits for a byte that never
comes.  No Pool of Radiance, no fastloader, no game code at all: the reproducer
uses the KERNAL's own `LOAD` (or `GET#`), which is the routine both hangs on
`#286 (Pool of Radiance on the C64 Ultimate sometimes hangs on a disk load)`
resolved into.

**The reproducer disk** (built by `build`, mounted by `run`): one small BASIC
program and one data file, generated here, containing nothing copyrighted.

* `load` variant -- `10 LOAD"HANGDATA",8,1`.  A `LOAD` inside a running BASIC
  program restarts it, so this reads `HANGDATA` (a 4 KB file that loads to
  `$C000`, harmless RAM) over and over, keeping the serial bus busy at full
  KERNAL speed.  One line of BASIC.
* `get` variant -- `OPEN`/`GET#`/`CLOSE` in a loop, the KERNAL's `ACPTR` byte
  by byte, for a reader who wants the plainest possible serial read.

**What each run establishes**, one report line each:

* whether a bare KERNAL read hangs at all, with no game loader -- `run`;
* the smallest host read that does it -- `sweep`, which raises the read size
  until a run hangs inside the budget;
* the rate -- time-to-hang, logged;
* the stop state anybody can check -- the frozen jiffy at `$00A0`, `$DD00`,
  `$DC0D`, and where the stack's return addresses fall in the KERNAL, resolved
  against a KERNAL ROM with `capstone`'s MOS65xx backend (`--kernal PATH`).

    tools/c64uhang.py build --out work/x/hang.d64
    tools/c64uhang.py run --size 8192 --interval 2 --minutes 10 --log work/x/r.jsonl
    tools/c64uhang.py sweep --sizes 256,1024,4096,8192,16384 --budget 8 \\
        --log-dir work/x/sweep

Speaker off before a boot (`.claude/rules/emulator.md`); `run` refuses unless
the device reports it Disabled.  Writes memory only at `$0277`/`$00C6` for a
keystroke, resets to `READY.` when done, and touches no device configuration.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools.c64uload import Device, Log, endcheck, sample, screen_address  # noqa: E402
from tools.c64urest import find_host  # noqa: E402

DEFAULT_PORT = 80
DATA_ADDR = 0xC000          # where HANGDATA loads: free RAM on a bare C64
DATA_SIZE = 4096

# CBM BASIC v2 keyword tokens, only the ones the reproducer uses.
_TOKENS = {
    "END": 0x80, "FOR": 0x81, "NEXT": 0x82, "GOTO": 0x89, "RUN": 0x8A,
    "IF": 0x8B, "GOSUB": 0x8D, "REM": 0x8F, "LOAD": 0x93, "PRINT": 0x99,
    "OPEN": 0x9F, "CLOSE": 0xA0, "GET": 0xA1, "TO": 0xA4, "THEN": 0xA7,
}
_KEYWORDS = sorted(_TOKENS, key=len, reverse=True)


def tokenize_line(text: str) -> bytes:
    """One BASIC line's body to tokens.  `ST` and variables stay literal."""
    out = bytearray()
    i, in_quote = 0, False
    while i < len(text):
        ch = text[i]
        if in_quote:
            out.append(ord(ch))
            if ch == '"':
                in_quote = False
            i += 1
            continue
        if ch == '"':
            in_quote = True
            out.append(ord(ch))
            i += 1
            continue
        for kw in _KEYWORDS:
            if text.startswith(kw, i):
                out.append(_TOKENS[kw])
                i += len(kw)
                break
        else:
            out.append(ord(ch))
            i += 1
    return bytes(out)


def build_basic(lines: list[tuple[int, str]], start: int = 0x0801) -> bytes:
    """A runnable BASIC PRG: `$01 $08` load address, linked lines, `$00 $00`."""
    body = bytearray()
    records = []
    for num, text in lines:
        rec = bytearray([num & 0xFF, (num >> 8) & 0xFF])
        rec += tokenize_line(text)
        rec.append(0x00)
        records.append(rec)
    addr = start
    for rec in records:
        nxt = addr + len(rec) + 2
        body += bytes([nxt & 0xFF, (nxt >> 8) & 0xFF]) + rec
        addr = nxt
    body += b"\x00\x00"
    return bytes([start & 0xFF, (start >> 8) & 0xFF]) + bytes(body)


def reproducer_disk(variant: str) -> bytes:
    from goldbox.d64 import D64, FILE_TYPE_PRG

    if variant == "load":
        prog = build_basic([(10, 'LOAD"HANGDATA",8,1')])
    elif variant == "get":
        prog = build_basic([
            (10, 'OPEN2,8,2,"HANGDATA,P,R"'),
            (20, "GET#2,A$:IF ST=0 THEN 20"),
            (30, "CLOSE2:GOTO 10"),
        ])
    else:
        raise ValueError(variant)
    data = bytes([DATA_ADDR & 0xFF, (DATA_ADDR >> 8) & 0xFF]) \
        + bytes(DATA_SIZE)
    disk = D64.blank(b"HANGTEST", b"64")
    disk.write_file(b"HANG", prog, FILE_TYPE_PRG)
    disk.write_file(b"HANGDATA", data, FILE_TYPE_PRG)
    return disk.to_bytes()


# -- the KERNAL stack read ---------------------------------------------------


def resolve_stack(zp: bytes, kernal: bytes) -> list[str]:
    """Every stack pair that is a JSR's pushed return address, into the ROM."""
    try:
        import capstone
    except ImportError:
        return ["(capstone not installed; stack not resolved)"]
    md = capstone.Cs(capstone.CS_ARCH_MOS65XX, capstone.CS_MODE_MOS65XX_6502)
    st = zp[0x100:0x200]

    def jsr_at(addr: int) -> str | None:
        if not (0xE000 <= addr < 0xE000 + len(kernal) - 2):
            return None
        for ins in md.disasm(kernal[addr - 0xE000:addr - 0xE000 + 3], addr):
            if ins.mnemonic == "jsr":
                return f"jsr {ins.op_str}"
        return None

    out = []
    for i in range(255):
        pushed = st[i] | (st[i + 1] << 8)
        j = jsr_at(pushed - 2)
        if j:
            out.append(f"${0x100 + i:04X}: return ${pushed:04X} <- ${pushed-2:04X} {j}")
    return out


# -- capture of the stopped machine ------------------------------------------

#: Only what the hang report needs.  `cia2` at $DD00 is the serial-bus
#: register and is the one c64uload's own region set does not reach.
HANG_REGIONS = [
    ("screen", None, 0x03E8), ("colour-ram", 0xD800, 0x03E8),
    ("zero-page", 0x0000, 0x0800), ("data-C000", 0xC000, 0x0400),
    ("vic", 0xD000, 0x0030), ("cia1", 0xDC00, 0x0010),
    ("cia2", 0xDD00, 0x0010),
]


def capture_hang(dev: Device, out: pathlib.Path, kernal: bytes | None,
                 note: str) -> dict:
    import hashlib
    import json
    out.mkdir(parents=True, exist_ok=True)
    d018, dd00 = dev.readmem(0xD018, 1), dev.readmem(0xDD00, 1)
    at = screen_address(d018[0], dd00[0]) if d018 and dd00 else 0x0400
    manifest = {"taken": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "note": note,
                "screen_address": at, "regions": []}
    zp = None
    for name, start, length in HANG_REGIONS:
        where = at if start is None else start
        data = dev.readmem(where, length)
        if data is None:
            manifest["regions"].append({"name": name, "start": where,
                                        "error": "read failed"})
            continue
        (out / f"{name}.bin").write_bytes(data)
        manifest["regions"].append({"name": name, "start": where,
                                    "length": length,
                                    "sha256": hashlib.sha256(data).hexdigest()})
        if name == "zero-page":
            zp = data
    if zp and kernal:
        frames = resolve_stack(zp, kernal)
        (out / "stack.txt").write_text("\n".join(frames) + "\n")
        manifest["stack_frames"] = frames
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


# -- one run -----------------------------------------------------------------


def boot_reproducer(dev: Device, log: Log, image: bytes, answer: str) -> bool:
    from tools.c64urest import first_prg
    mounted = dev.json("/drives/a:mount", method="POST", body=image,
                       params={"type": "d64", "mode": "readonly"})
    if mounted.get("error") or mounted.get("errors"):
        log.write("meta", event="mount failed", answer=mounted)
        return False
    # `first_prg` wants a path; write the image out once so it can read it.
    tmp = pathlib.Path(log.path.parent if log.path else ".") / "_repro.d64"
    tmp.write_bytes(image)
    name, program = first_prg(tmp)
    started = dev.json("/runners:run_prg", method="POST", body=program)
    log.write("meta", event="run_prg", prg=name, answer=started,
              drives=dev.json("/drives"))
    if started.get("error") or started.get("errors"):
        return False
    time.sleep(6)
    if answer:
        dev.writemem(0x0277, answer.encode("ascii"))
        dev.writemem(0x00C6, bytes([len(answer)]))
    return True


#: `$DD00` at an idle BASIC prompt, where the KERNAL holds CLOCK low itself.
#: A machine in a KERNAL load never reads this; it cycles $27/$47/$87/$07...
IDLE_PROMPT_DD00 = 0x97


def loading_check(dev: Device, log: Log, seconds: float = 10.0) -> dict:
    """Is the machine in the load loop?  Five samples: the jiffy must move
    and `$DD00` must take more than one value, none of them the idle prompt's.
    A run whose machine is sitting at `READY.` cannot be hung by a read
    landing inside a read, and must not be scored as "did not hang"."""
    seen, jiffies = set(), []
    for _ in range(5):
        s = sample(dev)
        if s is None:
            return {"loading": False, "why": "no sample"}
        seen.add(s["dd00"])
        jiffies.append(s["jiffy"])
        time.sleep(seconds / 5)
    out = {"dd00_values": sorted(f"{v:02x}" for v in seen),
           "jiffy_moved": jiffies[-1] - jiffies[0]}
    out["loading"] = (jiffies[-1] != jiffies[0] and len(seen) >= 2
                      and IDLE_PROMPT_DD00 not in seen)
    log.write("meta", event="loading check", **out)
    return out


def poll_until_hang(dev: Device, log: Log, size: int, at: int, interval: float,
                    minutes: float, sample_every: float, still: float,
                    blip: float) -> dict:
    from tools.c64uload import blip as blip_wait
    deadline = time.time() + minutes * 60
    next_sample = time.time()
    last_jiffy, last_change = None, time.time()
    started = time.time()
    why = "time"
    while time.time() < deadline:
        now = time.time()
        if now >= next_sample:
            s = sample(dev, with_screen=(int((now - started) / sample_every) % 6 == 0))
            next_sample = now + sample_every
            if s is None:
                if blip_wait(dev, log, blip):
                    continue
                why = "device"
                break
            log.write("sample", **s)
            if s["jiffy"] != last_jiffy:
                last_jiffy, last_change = s["jiffy"], now
            elif now - last_change >= still:
                why = "hang"
                break
        if dev.readmem(at, size) is None:
            if blip_wait(dev, log, blip):
                continue
            why = "device"
            break
        spent = time.time() - now
        if interval > spent:
            time.sleep(min(interval - spent, max(0.0, deadline - time.time())))
    return {"why": why, "seconds": round(time.time() - started, 1),
            "requests": dev.requests, "failed": dev.failed_count,
            "last_jiffy": last_jiffy}


def loading_evidence(log_path) -> dict:
    """From a run's own samples: did the machine read the disk throughout?"""
    import collections
    import json
    dd, js = collections.Counter(), []
    for line in pathlib.Path(log_path).read_text().splitlines():
        r = json.loads(line)
        if r.get("kind") == "sample":
            if r.get("dd00") is not None:
                dd[r["dd00"]] += 1
            js.append(r["jiffy"])
    total = sum(dd.values())
    idle = dd.get(IDLE_PROMPT_DD00, 0)
    return {"samples": total, "distinct_dd00": len(dd),
            "idle_prompt_samples": idle,
            "jiffy_advanced": (js[-1] - js[0]) if len(js) > 1 else 0,
            "was_loading": total >= 3 and len(dd) >= 3 and idle == 0
            and len(js) > 1 and js[-1] != js[0]}


def one_run(args, size: int, log_path: str, capture_dir: str | None) -> dict:
    import subprocess
    log = Log(log_path)
    dev = Device(args.host, args.port, log)
    kernal = pathlib.Path(args.kernal).read_bytes() if args.kernal else None
    out = subprocess.run(
        ["c64u", "--host", args.host, "config", "get", "Speaker Mixer",
         "Speaker Enable"], capture_output=True, text=True, timeout=30)
    if "current:" not in out.stdout or "Disabled" not in \
            out.stdout.split("current:")[1].splitlines()[0]:
        sys.exit("speaker is not Disabled (.claude/rules/emulator.md)")
    log.write("meta", event="run", variant=args.variant, size=size, at=args.at,
              interval=args.interval, minutes=args.minutes)
    if not dev.online() and not dev.wait_online(args.recover):
        return {"verdict": "unreachable", "why": "device"}
    dev.json("/machine:reset", method="PUT")
    time.sleep(5)
    image = reproducer_disk(args.variant)
    if not boot_reproducer(dev, log, image, args.answer):
        dev.json("/machine:reset", method="PUT")
        return {"verdict": "boot-failed"}
    pre = loading_check(dev, log)
    if not pre.get("loading"):
        dev.json("/machine:reset", method="PUT")
        return {"verdict": "not-loading", **pre}
    summary = poll_until_hang(dev, log, size, args.at, args.interval,
                              args.minutes, args.sample, args.still, args.blip)
    if summary["why"] == "device" and not dev.wait_online(args.recover):
        log.write("endcheck", verdict="unreachable")
        return {"verdict": "unreachable", **summary}
    check = endcheck(dev)
    log.write("endcheck", **check)
    summary["regs"] = check["regs"]
    # The end check's "basic" means the KERNAL-default registers, which a
    # running BASIC program shows as much as an idle prompt.  Say which from
    # the run's own $DD00 samples instead.
    seen = loading_evidence(log.path) if log.path else {}
    summary["loading_evidence"] = seen
    if check["verdict"] == "hung":
        summary["verdict"] = "hung"
    elif check["verdict"] == "unreachable":
        summary["verdict"] = "unreachable"
    elif seen.get("was_loading"):
        summary["verdict"] = "survived-loading"
    else:
        summary["verdict"] = "survived-not-loading"
    if check["verdict"] == "hung" and capture_dir:
        m = capture_hang(dev, pathlib.Path(capture_dir), kernal,
                         f"{args.variant} reproducer, {size}-byte reads: hung")
        summary["stack_frames"] = m.get("stack_frames")
    dev.json("/machine:reset", method="PUT")
    log.write("meta", event="reset to READY")
    return summary


# -- commands ----------------------------------------------------------------


def cmd_build(args) -> int:
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(reproducer_disk(args.variant))
    print(f"{args.variant} reproducer -> {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_run(args) -> int:
    summary = one_run(args, args.size, args.log, args.capture)
    import json
    print(json.dumps(summary, indent=2))
    return 5 if summary.get("verdict") == "hung" else 0


def cmd_sweep(args) -> int:
    import json
    sizes = [int(s) for s in args.sizes.split(",")]
    results = []
    log_dir = pathlib.Path(args.log_dir)
    for size in sizes:
        args.minutes = args.budget
        summary = one_run(args, size, str(log_dir / f"size{size}.jsonl"),
                          str(log_dir / f"size{size}-hang"))
        row = {"size": size, "verdict": summary.get("verdict"),
               "seconds": summary.get("seconds"),
               "requests": summary.get("requests")}
        results.append(row)
        print(json.dumps(row), flush=True)
        if summary.get("verdict") == "hung":
            print(json.dumps({"threshold_bytes": size,
                              "stack_frames": summary.get("stack_frames")},
                             indent=2))
            break
    (log_dir / "sweep.json").write_text(json.dumps(results, indent=2) + "\n")
    return 0


def _common() -> argparse.ArgumentParser:
    c = argparse.ArgumentParser(add_help=False)
    c.add_argument("--host")
    c.add_argument("--port", type=int, default=DEFAULT_PORT)
    c.add_argument("--variant", choices=["load", "get"], default="load")
    c.add_argument("--kernal", help="a C64 KERNAL ROM, to resolve the stack")
    c.add_argument("--answer", default="",
                   help="a key to place after boot (blank = none)")
    c.add_argument("--at", type=lambda x: int(x, 16), default=0x4000,
                   help="address the host read targets (default $4000)")
    c.add_argument("--interval", type=float, default=2.0)
    c.add_argument("--sample", type=float, default=5.0)
    c.add_argument("--still", type=float, default=30.0)
    c.add_argument("--recover", type=float, default=15.0)
    c.add_argument("--blip", type=float, default=60.0)
    return c


def main(argv: list[str] | None = None) -> int:
    common = _common()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", parents=[common], help="write the disk")
    b.add_argument("--out", required=True)
    b.set_defaults(fn=cmd_build)

    r = sub.add_parser("run", parents=[common], help="one run at one read size")
    r.add_argument("--size", type=int, required=True)
    r.add_argument("--minutes", type=float, default=10.0)
    r.add_argument("--log")
    r.add_argument("--capture")
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("sweep", parents=[common],
                       help="raise the read size until a run hangs")
    s.add_argument("--sizes", required=True, help="comma-separated byte sizes")
    s.add_argument("--budget", type=float, default=8.0,
                   help="minutes per size before moving on")
    s.add_argument("--log-dir", required=True)
    s.set_defaults(fn=cmd_sweep)

    args = p.parse_args(argv)
    args.host = find_host(args.host)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

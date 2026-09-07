#!/usr/bin/env python3
"""Run one polling experiment against a game on the C64 Ultimate, and say
whether the C64 was hung when it ended.

Written for `#286 (Pool of Radiance on the C64 Ultimate sometimes hangs on a
disk load)`.  The question is whether Wish's memory polls -- each one a DMA
read that halts the 6510 -- are what stops the game at a disk load, and the
measurement is a *trial*: reset the machine, boot `POOL1.D64`, answer `Y` to
`DISABLE FASTLOADER (Y/N) ?`, apply a treatment for a fixed time, and then take
an end check that can tell a hung C64 from a running one.

The treatments (`trial --treatment`):

* `silent` -- send nothing at all until the end check.  This is the control,
  experiment B in the plan on the issue.
* `readmem` -- one `GET /v1/machine:readmem` of `--size` bytes at `--at`,
  every `--interval` seconds.  Experiment E, and the dose arms of F.  With
  `--at 0` and a size of `$200` or more the block is its own liveness
  reading -- the jiffy at `$A0` and a hash of the zero page and stack -- and
  `--sample 0` turns the separate samples off, so the *only* halts are the
  treatment's.  A hang then shows as the first block identical to the one
  before it, and the number of jiffy ticks between those two blocks says
  whether the machine stopped at the request (zero) or somewhere in the gap
  after it.  That is the correlation experiment E needs on this game, whose
  own clock stops during a load, so a fit of jiffy against wall time dates
  the load and not the hang.
* `wish` -- Wish's own tick, as `tests/test_issue286a2.py` measured it: four
  one-byte-to-forty-byte reads every tick and the two save-image blocks every
  fifth, at `--interval`.  Experiment F6.
* `info`, `version`, `drives` -- the same cadence with no DMA at all.
  Experiment C.

**What a verdict rests on.**  Only the jiffy clock at `$00A0`-`$00A2`, read
twice ten seconds apart.  A frozen jiffy is a C64 with interrupts off and
nothing running, which is the state every hang on this issue has shown; a
moving jiffy with `$0314/$0315` back to the KERNAL's `$EA31` and `$D018` at
`$15` is the crash to BASIC; a moving jiffy with the game's `$D018 = $35` (the
text panel at `$CC00`) or `$79` (the demo's dungeon view at `$DC00`, custom
characters at `$E000`) and `$0288 = $CC` is the game running.  `$DD00` is
logged and decides nothing: the 2026-09-06 runs called `$C4` a hang, and `$C4`
is the commonest healthy value.

**Every request is logged**, with wall time at send and at reply, so a freeze
can be lined up against the request nearest it.  On a hang the tool fits the
last minutes of (wall, jiffy) samples by least squares, converts the frozen
jiffy to a wall time, and reports the signed offset to the nearest request's
send time and whether the freeze fell inside that request's window.  That
offset is the number experiment E exists to produce.

**A request that fails does not end the process.**  One lost request over
WiFi is a blip: if `/v1/version` answers within `--blip` seconds the treatment
carries on and the blip is counted.  The device's HTTP service has also failed
outright under sustained traffic (2026-09-06); when it stays silent past that,
the tool polls `/v1/version` every thirty seconds until the device answers
again, and then takes the end check anyway -- because the C64 may well still
be running, and whether it is, is the finding.

The samples read the jiffy and `$DD00` only, and never `$DC0D`: a DMA read of
CIA 1's interrupt register acknowledges whatever was pending, which is a
perturbation of the machine under test.  `$DC0D` is read once, in the end
check, after the jiffy has already been seen to stop.

    tools/c64uload.py trial --treatment silent --minutes 40 --log work/x/b1.jsonl
    tools/c64uload.py trial --treatment readmem --size 7168 --at 4900 \\
        --interval 5 --minutes 60 --log work/x/e1.jsonl --capture work/x/e1
    tools/c64uload.py endcheck
    tools/c64uload.py fit --log work/x/e1.jsonl
    tools/c64uload.py stress --treatment version --interval 0.1 --minutes 20 \\
        --log work/x/http1.jsonl

`stress` applies a treatment to the machine as it stands -- no reset, no boot
-- so the device's HTTP service can be loaded with the C64 sitting at `READY.`
and no game, drive or disk in the picture.  It reports whether the service
failed, how long it took to answer again, and whether the C64 was reset by
it, which the jiffy clock says: a value smaller than before is a machine that
has been through a reset.

The speaker must be off before a boot (`.claude/rules/emulator.md`); `trial`
refuses to boot unless `c64u config get "Speaker Mixer" "Speaker Enable"` says
`Disabled`, and it changes no configuration itself.  It writes memory at
`$0277`/`$00C6` for the `Y` and nowhere else, and it resets the machine to
BASIC `READY.` at the end of every trial, hung or not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools.c64urest import find_host, first_prg, screen_text  # noqa: E402

DEFAULT_PORT = 80

#: Wish's tick against Pool of Radiance with the party in the 3D view, as
#: `tests/test_issue286a2.py` measures it: `(address, length)` per request.
WISH_EVERY_TICK = [(0xD011, 1), (0xD018, 1), (0xDD00, 1), (0x0630, 40)]
WISH_FIFTH_TICK = [(0x6E11, 1), (0x0600, 20), (0x037E, 2), (0x6E11, 1),
                   (0x6E11, 1), (0x6E11, 1), (0x4900, 7168), (0x8300, 256)]

#: The regions `tools/c64uplay.py regions` takes, plus the loaded-files cache.
REGIONS = [
    ("screen", None, 0x03E8), ("colour-ram", 0xD800, 0x03E8),
    ("zero-page", 0x0000, 0x0800), ("gdrive", 0xC000, 0x0400),
    ("dungeon", 0x0800, 0x2380), ("record", 0x6B00, 0x0500),
    ("save-image", 0x4900, 0x1C00), ("items", 0x7600, 0x0800),
    ("vic", 0xD000, 0x0030), ("cia", 0xDC00, 0x0100),
    ("files-cache", 0x6E13, 0x00C8),
]


# -- transport ---------------------------------------------------------------


class Log:
    """One JSON object per line, flushed as it is written."""

    def __init__(self, path: str | None):
        self.path = pathlib.Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sink = self.path.open("a") if self.path else None

    def write(self, kind: str, **fields) -> dict:
        record = {"kind": kind, "t": time.time(), **fields}
        line = json.dumps(record)
        if self.sink:
            self.sink.write(line + "\n")
            self.sink.flush()
        else:
            print(line, flush=True)
        return record


class Device:
    def __init__(self, host: str, port: int, log: Log,
                 timeout: float = 30.0):
        self.host, self.port, self.log, self.timeout = host, port, log, timeout
        self.base = f"http://{host}:{port}/v1"
        self.requests = 0
        self.failed = None   # the first failed request record, if any
        self.failed_count = 0
        self.last_error = None

    def request(self, route: str, params: dict | None = None,
                method: str = "GET", body: bytes | None = None,
                timeout: float | None = None) -> tuple[dict, bytes]:
        url = self.base + route
        if params:
            url += "?" + urllib.parse.urlencode(params)
        record = {"route": route, "method": method,
                  "size": int(params.get("length", 0)) if params else 0,
                  "send": time.time()}
        req = urllib.request.Request(url, data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/octet-stream")
        data = b""
        try:
            with urllib.request.urlopen(
                    req, timeout=timeout or self.timeout) as reply:
                data = reply.read()
                record.update(status=reply.status, error=None)
        except urllib.error.HTTPError as exc:
            record.update(status=exc.code, error=f"HTTP {exc.code}")
        except Exception as exc:  # URLError, socket.timeout, OSError
            record.update(status=None, error=str(exc))
        record["reply"] = time.time()
        record["elapsed_ms"] = round((record["reply"] - record["send"]) * 1000,
                                     1)
        self.requests += 1
        self.log.write("request", **record)
        if record["error"]:
            self.failed_count += 1
            self.last_error = record
            if self.failed is None:
                self.failed = record
        return record, data

    def readmem(self, address: int, length: int) -> bytes | None:
        record, data = self.request(
            "/machine:readmem",
            {"address": f"{address:04X}", "length": str(length)})
        return data if record["error"] is None and len(data) == length else None

    def writemem(self, address: int, data: bytes) -> bool:
        record, _ = self.request("/machine:writemem",
                                 {"address": f"{address:04X}"},
                                 method="POST", body=data)
        return record["error"] is None

    def json(self, route: str, method: str = "GET",
             body: bytes | None = None, params: dict | None = None) -> dict:
        record, data = self.request(route, params, method=method, body=body)
        if record["error"]:
            return {"error": record["error"]}
        try:
            return json.loads(data)
        except ValueError:
            return {"error": f"not JSON: {data[:80]!r}"}

    def online(self, timeout: float = 5.0) -> bool:
        record, _ = self.request("/version", timeout=timeout)
        return record["error"] is None

    def wait_online(self, minutes: float) -> bool:
        """One `/v1/version` every thirty seconds until it answers."""
        deadline = time.time() + minutes * 60
        while time.time() < deadline:
            if self.online():
                return True
            time.sleep(30)
        return False


# -- readings ----------------------------------------------------------------


def jiffy_of(raw: bytes) -> int:
    return (raw[0] << 16) | (raw[1] << 8) | raw[2]


def screen_address(d018: int, dd00: int) -> int:
    return ((~dd00 & 3) * 0x4000) + ((d018 >> 4) & 0xF) * 0x400


def sample(dev: Device, with_screen: bool = False) -> dict | None:
    """The jiffy and the bus; the screen hash only when asked."""
    raw = dev.readmem(0x00A0, 3)
    dd00 = dev.readmem(0xDD00, 1)
    if raw is None or dd00 is None:
        return None
    out = {"jiffy": jiffy_of(raw), "dd00": dd00[0]}
    if with_screen:
        d018 = dev.readmem(0xD018, 1)
        if d018 is not None:
            at = screen_address(d018[0], dd00[0])
            screen = dev.readmem(at, 1000)
            if screen is not None:
                out["screen_at"] = at
                out["screen"] = hashlib.sha256(screen).hexdigest()[:16]
    return out


def endcheck(dev: Device, gap: float = 10.0) -> dict:
    """Is the C64 running?  The jiffy twice, `gap` seconds apart, decides."""
    first = sample(dev, with_screen=True)
    regs = {}
    for name, addr, length in (("0314", 0x0314, 2), ("d018", 0xD018, 1),
                               ("0288", 0x0288, 1), ("dc0d", 0xDC0D, 1),
                               ("d01a", 0xD01A, 1)):
        raw = dev.readmem(addr, length)
        regs[name] = raw.hex() if raw is not None else None
    if first is None:
        return {"verdict": "unreachable", "first": None, "regs": regs}
    time.sleep(gap)
    second = sample(dev, with_screen=True)
    out = {"first": first, "second": second, "regs": regs, "gap": gap}
    if second is None:
        out["verdict"] = "unreachable"
        return out
    moved = second["jiffy"] - first["jiffy"]
    out["jiffy_moved"] = moved
    out["screen_moved"] = first.get("screen") != second.get("screen")
    if moved == 0:
        out["verdict"] = "hung"
    elif regs["0314"] == "31ea" and regs["d018"] == "15":
        out["verdict"] = ("crashed-to-basic" if regs["0288"] == "cc"
                          else "basic")
    elif regs["d018"] in ("35", "79") and regs["0288"] == "cc":
        out["verdict"] = "game-running"
    else:
        out["verdict"] = "running"
    return out


def capture(dev: Device, out: pathlib.Path, note: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    d018, dd00 = dev.readmem(0xD018, 1), dev.readmem(0xDD00, 1)
    at = screen_address(d018[0], dd00[0]) if d018 and dd00 else 0x0400
    manifest = {"taken": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "note": note,
                "screen_address": at, "regions": []}
    for name, start, length in REGIONS:
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
        if name == "screen":
            manifest["screen_text"] = screen_text(data)
    manifest["drives"] = dev.json("/drives")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


# -- the fit -----------------------------------------------------------------


def fit_freeze(samples: list[dict], requests: list[dict],
               frozen: int, window: int = 60) -> dict:
    """Where in wall time did the jiffy stop, and which request was nearest?

    Least squares of jiffy on wall time over the last `window` samples whose
    jiffy was still moving, then the frozen value converted through the fit.
    The residual RMS is the fit's own uncertainty; one jiffy tick (16.7 ms
    NTSC) is the reading's.
    """
    moving = [s for s in samples if s.get("jiffy") is not None
              and s["jiffy"] != frozen]
    moving = moving[-window:]
    if len(moving) < 3:
        return {"error": f"only {len(moving)} moving samples"}
    xs = [s["t"] for s in moving]
    ys = [s["jiffy"] for s in moving]
    x0 = xs[0]
    xs = [x - x0 for x in xs]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    resid = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    rms = (sum(r * r for r in resid) / n) ** 0.5
    freeze_wall = x0 + (frozen - intercept) / slope
    out = {"samples": n, "slope_hz": round(slope, 4),
           "residual_rms_ticks": round(rms, 3),
           "residual_rms_ms": round(rms / slope * 1000, 1),
           "freeze_wall": freeze_wall,
           "freeze_wall_iso": time.strftime("%H:%M:%S",
                                            time.localtime(freeze_wall))
           + f".{int(freeze_wall * 1000) % 1000:03d}",
           "freeze_jiffy": frozen}
    # The last sample that still moved bounds the freeze from below; the
    # first frozen one from above.
    last_moving = moving[-1]["t"]
    first_frozen = next((s["t"] for s in samples
                         if s.get("jiffy") == frozen and s["t"] > last_moving),
                        None)
    out["bounds"] = [last_moving, first_frozen]
    cands = [r for r in requests
             if first_frozen is None or r["send"] <= first_frozen + 1]
    if cands:
        nearest = min(cands, key=lambda r: abs(r["send"] - freeze_wall))
        out["nearest_request"] = {
            "route": nearest["route"], "size": nearest["size"],
            "send": nearest["send"], "reply": nearest["reply"],
            "offset_ms": round((freeze_wall - nearest["send"]) * 1000, 1),
            "inside_window": nearest["send"] <= freeze_wall <= nearest["reply"],
            "within_100ms": abs(freeze_wall - nearest["send"]) <= 0.1,
        }
        gaps = sorted(b["send"] - a["send"]
                      for a, b in zip(cands, cands[1:]))
        if gaps:
            out["median_request_gap_s"] = round(gaps[len(gaps) // 2], 3)
    return out


def load_log(path: str) -> tuple[list[dict], list[dict], list[dict]]:
    samples, requests, others = [], [], []
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        {"sample": samples, "request": requests}.get(rec["kind"],
                                                     others).append(rec)
    return samples, requests, others


# -- the treatment -----------------------------------------------------------


def blip(dev: Device, log: Log, seconds: float) -> bool:
    """A request failed; does the device still answer?  True means carry on."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if dev.online(timeout=5.0):
            log.write("meta", event="blip", failed=dev.failed_count,
                      last_error=dev.last_error)
            return True
        time.sleep(5.0)
    return False


def apply(dev: Device, log: Log, args) -> dict:
    """Run the treatment until time is up, a hang, or the device fails.

    Returns a summary with `why` in {"time", "hang", "device"}.
    """
    deadline = time.time() + args.minutes * 60
    next_sample = time.time()
    tick, samples, frozen_since = 0, 0, None
    last_jiffy, last_change = None, time.time()
    why = "time"
    while time.time() < deadline:
        now = time.time()
        if args.treatment != "silent" and args.sample > 0 and now >= next_sample:
            s = sample(dev, with_screen=(samples % 6 == 0))
            samples += 1
            next_sample = now + args.sample
            if s is None:
                if blip(dev, log, args.blip):
                    continue
                why = "device"
                break
            log.write("sample", **s)
            if s["jiffy"] != last_jiffy:
                last_jiffy, last_change = s["jiffy"], now
                frozen_since = None
            else:
                frozen_since = frozen_since or now
                if now - last_change >= args.still:
                    why = "hang"
                    break
        if args.treatment == "silent":
            time.sleep(min(5.0, max(0.0, deadline - time.time())))
            continue
        if args.treatment == "readmem":
            block = dev.readmem(args.at, args.size)
            if block is None:
                if blip(dev, log, args.blip):
                    continue
                why = "device"
                break
            if args.at == 0 and args.size >= 0x200:
                # The block carries its own liveness reading: the jiffy at
                # $A0-$A2 and the zero page and stack.  So the request is
                # the sample, and a hang shows as the first block identical
                # to the one before it -- with the request that halted the
                # CPU between them.
                s = {"jiffy": jiffy_of(block[0xA0:0xA3]),
                     "dd00": None, "from_block": True,
                     "request": dev.requests,
                     "zp_stack": hashlib.sha256(block[:0x200]).hexdigest()[:16]}
                log.write("sample", **s)
                if s["jiffy"] != last_jiffy:
                    last_jiffy, last_change = s["jiffy"], now
                elif now - last_change >= args.still:
                    why = "hang"
                    break
        elif args.treatment == "wish":
            tick += 1
            reads = WISH_EVERY_TICK + (WISH_FIFTH_TICK if tick % 5 == 0
                                       else [])
            ok = all(dev.readmem(a, n) is not None for a, n in reads)
            if not ok:
                if blip(dev, log, args.blip):
                    continue
                why = "device"
                break
        else:
            record, _ = dev.request(f"/{args.treatment}")
            if record["error"]:
                if blip(dev, log, args.blip):
                    continue
                why = "device"
                break
        spent = time.time() - now
        if args.interval > spent:
            time.sleep(min(args.interval - spent, max(0.0,
                                                      deadline - time.time())))
    return {"why": why, "ticks": tick, "samples": samples,
            "requests": dev.requests, "failed_requests": dev.failed_count,
            "last_jiffy": last_jiffy}


# -- the trial ---------------------------------------------------------------


def speaker_is_off(host: str) -> bool:
    try:
        out = subprocess.run(
            ["c64u", "--host", host, "config", "get", "Speaker Mixer",
             "Speaker Enable"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "current:" in out.stdout and "Disabled" in out.stdout.split(
        "current:")[1].splitlines()[0]


def boot(dev: Device, log: Log, image: pathlib.Path, answer: str) -> bool:
    """Mount the image, run its first PRG, and answer the fastloader prompt."""
    data = image.read_bytes()
    log.write("meta", image=str(image), sha256=hashlib.sha256(data).hexdigest(),
              info=dev.json("/info"))
    mounted = dev.json("/drives/a:mount", method="POST", body=data,
                       params={"type": "d64", "mode": "readonly"})
    if mounted.get("error") or mounted.get("errors"):
        log.write("meta", event="mount failed", answer=mounted)
        return False
    name, program = first_prg(image)
    started = dev.json("/runners:run_prg", method="POST", body=program)
    log.write("meta", event="run_prg", prg=name, drives=dev.json("/drives"),
              answer=started)
    if started.get("error") or started.get("errors"):
        return False
    time.sleep(10)
    # The prompt reads the KERNAL buffer, so a key placed there early waits
    # for it.  Watch the count drain, which is the game taking it.
    dev.writemem(0x0277, answer.encode("ascii"))
    dev.writemem(0x00C6, bytes([1]))
    deadline = time.time() + 90
    taken = False
    while time.time() < deadline:
        c6 = dev.readmem(0x00C6, 1)
        if c6 is not None and c6[0] == 0:
            taken = True
            break
        time.sleep(1.0)
    log.write("meta", event="answered", key=answer, taken=taken,
              at=time.time())
    return taken


def cmd_trial(args) -> int:
    log = Log(args.log)
    dev = Device(args.host, args.port, log)
    if args.treatment in ("readmem",) and (args.size is None
                                           or args.at is None):
        sys.exit("--treatment readmem needs --size and --at")
    if not speaker_is_off(args.host):
        sys.exit("the speaker is not Disabled; "
                 "c64u config set \"Speaker Mixer\" \"Speaker Enable\" "
                 "Disabled first (.claude/rules/emulator.md)")
    log.write("meta", event="trial", treatment=args.treatment,
              interval=args.interval, size=args.size, at=args.at,
              minutes=args.minutes, sample=args.sample, still=args.still,
              host=args.host, argv=sys.argv[1:])
    if not dev.online():
        if not dev.wait_online(args.recover):
            log.write("meta", event="device never answered")
            return 4
    dev.json("/machine:reset", method="PUT")
    time.sleep(5)
    if not boot(dev, log, pathlib.Path(args.image), args.answer):
        log.write("meta", event="boot failed")
        dev.json("/machine:reset", method="PUT")
        return 2
    started = time.time()
    summary = apply(dev, log, args)
    summary["treatment_seconds"] = round(time.time() - started, 1)
    log.write("meta", event="treatment ended", **summary)
    if summary["why"] == "device":
        log.write("meta", event="device failed", first_failure=dev.failed)
        if not dev.wait_online(args.recover):
            log.write("endcheck", verdict="unreachable",
                      waited_minutes=args.recover)
            print(json.dumps({"verdict": "unreachable", **summary}))
            return 4
        log.write("meta", event="device back", at=time.time())
    check = endcheck(dev)
    log.write("endcheck", **check)
    verdict = check["verdict"]
    if verdict == "hung":
        samples, requests, _ = load_log(args.log) if args.log else ([], [], [])
        if samples:
            fit = fit_freeze(samples, requests, check["first"]["jiffy"])
            log.write("fit", **fit)
        if args.capture:
            manifest = capture(dev, pathlib.Path(args.capture),
                               f"{args.treatment} trial: hung")
            log.write("capture", out=args.capture,
                      screen_text=manifest.get("screen_text"))
    dev.json("/machine:reset", method="PUT")
    log.write("meta", event="reset to READY", at=time.time())
    print(json.dumps({"verdict": verdict, **summary,
                      "regs": check.get("regs")}))
    return {"game-running": 0, "running": 0, "hung": 5,
            "crashed-to-basic": 6, "basic": 7}.get(verdict, 1)


def cmd_stress(args) -> int:
    """The treatment against whatever the machine is doing, with no boot."""
    log = Log(args.log)
    dev = Device(args.host, args.port, log)
    if args.treatment == "readmem" and (args.size is None or args.at is None):
        sys.exit("--treatment readmem needs --size and --at")
    if args.treatment == "silent":
        sys.exit("stress with nothing to send is a sleep")
    log.write("meta", event="stress", treatment=args.treatment,
              interval=args.interval, size=args.size, at=args.at,
              minutes=args.minutes, sample=args.sample, host=args.host,
              info=dev.json("/info"), argv=sys.argv[1:])
    before = endcheck(dev, gap=2.0)
    log.write("endcheck", stage="before", **before)
    started = time.time()
    summary = apply(dev, log, args)
    summary["treatment_seconds"] = round(time.time() - started, 1)
    log.write("meta", event="treatment ended", **summary)
    back = None
    if summary["why"] == "device":
        failed_at = dev.failed["send"]
        log.write("meta", event="device failed", first_failure=dev.failed)
        if not dev.wait_online(args.recover):
            log.write("endcheck", stage="after", verdict="unreachable",
                      waited_minutes=args.recover)
            print(json.dumps({"verdict": "unreachable", **summary}))
            return 4
        back = time.time() - failed_at
        log.write("meta", event="device back", at=time.time(),
                  after_seconds=round(back, 1))
    after = endcheck(dev, gap=2.0)
    reset = (after.get("first") and before.get("first")
             and after["first"]["jiffy"] < before["first"]["jiffy"])
    log.write("endcheck", stage="after", c64_reset=bool(reset), **after)
    print(json.dumps({"verdict": after["verdict"], "c64_reset": bool(reset),
                      "back_after_s": None if back is None else round(back, 1),
                      **summary}))
    return 0 if summary["why"] == "time" else 3


def cmd_endcheck(args) -> int:
    log = Log(args.log)
    dev = Device(args.host, args.port, log)
    check = endcheck(dev, gap=args.gap)
    print(json.dumps(check, indent=2))
    return 0 if check["verdict"] in ("game-running", "running") else 5


def cmd_fit(args) -> int:
    samples, requests, others = load_log(args.log)
    frozen = args.jiffy
    if frozen is None:
        checks = [o for o in others if o["kind"] == "endcheck"
                  and o.get("verdict") == "hung"]
        if not checks:
            sys.exit("no hung end check in the log; pass --jiffy")
        frozen = checks[-1]["first"]["jiffy"]
    print(json.dumps(fit_freeze(samples, requests, frozen), indent=2))
    return 0


def cmd_report(args) -> int:
    """What a log says: requests, failures, samples, the bus, the clock."""
    samples, requests, others = load_log(args.log)
    out = {"requests": len(requests),
           "failed": [r for r in requests if r.get("error")][:3],
           "samples": len(samples)}
    ok = [r["elapsed_ms"] for r in requests if not r.get("error")
          and "elapsed_ms" in r]
    if ok:
        ok.sort()
        out["elapsed_ms"] = {"median": ok[len(ok) // 2],
                             "p90": ok[int(len(ok) * 0.9)], "max": ok[-1]}
    if requests:
        out["span_s"] = round(requests[-1]["reply"] - requests[0]["send"], 1)
    if samples:
        js = [s["jiffy"] for s in samples]
        out["jiffy"] = {"first": js[0], "last": js[-1],
                        "backward_steps": sum(1 for a, b in zip(js, js[1:])
                                              if b < a),
                        "unmoved_pairs": sum(1 for a, b in zip(js, js[1:])
                                             if b == a)}
        hist = {}
        for s_ in samples:
            if s_.get("dd00") is None:
                continue
            hist[f"{s_['dd00']:02x}"] = hist.get(f"{s_['dd00']:02x}", 0) + 1
        out["dd00"] = dict(sorted(hist.items(), key=lambda kv: -kv[1]))
        # Idle in this game is $C4: bits 3-5 clear (the C64 drives nothing)
        # and bits 6-7 set (neither line pulled low by anyone).  Anything
        # else is one side or the other on the bus.  At BASIC READY the
        # KERNAL holds CLOCK low itself and idle reads $97 instead.
        busy = sum(1 for s_ in samples if s_.get("dd00") is not None
                   and (s_["dd00"] & 0x38 or (s_["dd00"] & 0xC0) != 0xC0))
        known = sum(1 for s_ in samples if s_.get("dd00") is not None)
        out["bus_busy_fraction"] = round(busy / known, 3) if known else None
    blocks = [s_ for s_ in samples if s_.get("from_block")]
    if blocks:
        tail = blocks[-8:]
        out["last_blocks"] = [
            {"request": b["request"], "t": round(b["t"], 3),
             "jiffy": b["jiffy"],
             "delta": (b["jiffy"] - a["jiffy"]) if a else None,
             "zp_stack": b["zp_stack"]}
            for a, b in zip([None] + tail[:-1], tail)]
    for rec in others:
        if rec["kind"] in ("endcheck", "fit", "capture"):
            out[rec["kind"]] = {k: v for k, v in rec.items()
                                if k not in ("kind", "t", "screen_text")}
        elif rec["kind"] == "meta" and rec.get("event") in (
                "treatment ended", "device failed", "device back"):
            out.setdefault("events", []).append(
                {k: v for k, v in rec.items() if k != "kind"})
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_capture(args) -> int:
    log = Log(args.log)
    dev = Device(args.host, args.port, log)
    manifest = capture(dev, pathlib.Path(args.out), args.note)
    print(json.dumps(manifest.get("screen_text"), indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("trial", help="reset, boot, treat, end check, reset")
    p.add_argument("--treatment", required=True,
                   choices=["silent", "readmem", "wish", "info", "version",
                            "drives"])
    p.add_argument("--image", default="work/issue286/disks/POOL1.D64")
    p.add_argument("--answer", default="Y",
                   help="the fastloader prompt's answer")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--size", type=int)
    p.add_argument("--at", type=lambda x: int(x, 16))
    p.add_argument("--minutes", type=float, required=True)
    p.add_argument("--sample", type=float, default=10.0)
    p.add_argument("--still", type=float, default=30.0,
                   help="seconds of unmoving jiffy that mean a hang")
    p.add_argument("--recover", type=float, default=20.0,
                   help="minutes to wait for the device after it fails")
    p.add_argument("--blip", type=float, default=60.0,
                   help="seconds a failed request may be a blip for")
    p.add_argument("--log")
    p.add_argument("--capture")
    p.set_defaults(fn=cmd_trial)

    p = sub.add_parser("stress", help="the treatment with no reset and no boot")
    p.add_argument("--treatment", required=True,
                   choices=["readmem", "wish", "info", "version", "drives"])
    p.add_argument("--interval", type=float, default=0.1)
    p.add_argument("--size", type=int)
    p.add_argument("--at", type=lambda x: int(x, 16))
    p.add_argument("--minutes", type=float, required=True)
    p.add_argument("--sample", type=float, default=10.0)
    p.add_argument("--still", type=float, default=30.0)
    p.add_argument("--recover", type=float, default=20.0)
    p.add_argument("--blip", type=float, default=60.0)
    p.add_argument("--log")
    p.set_defaults(fn=cmd_stress)

    p = sub.add_parser("endcheck", help="is the C64 running right now?")
    p.add_argument("--gap", type=float, default=10.0)
    p.add_argument("--log")
    p.set_defaults(fn=cmd_endcheck)

    p = sub.add_parser("fit", help="freeze time and nearest request, from a log")
    p.add_argument("--log", required=True)
    p.add_argument("--jiffy", type=int)
    p.set_defaults(fn=cmd_fit)

    p = sub.add_parser("report", help="summarise a log")
    p.add_argument("--log", required=True)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("capture", help="the regions, into a directory")
    p.add_argument("--out", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--log")
    p.set_defaults(fn=cmd_capture)

    args = parser.parse_args(argv)
    args.host = find_host(args.host)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

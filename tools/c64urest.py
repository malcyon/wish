#!/usr/bin/env python3
"""Talk to a C64 Ultimate over REST and FTP directly, with no `c64u` CLI.

The spike behind `#272 (A Commodore 64 Ultimate tab: swap disks, boot, and
grab the save over the REST API)`.  The tab it plans has to work on a machine
where the `c64u` CLI is not installed -- Donald: *"not everyone will have that
cli installed"* -- so everything here is `urllib` and `ftplib` out of the
standard library, and the module deliberately imports nothing from
`tools/c64u.py`.

**REST for the machine, FTP for the file.** Four of the tab's five buttons are
plain HTTP on port 80; the fifth is not reachable that way at all, because the
firmware has no route that returns a file's bytes.  `grab` here is an
anonymous FTP `RETR` on port 21, which is what `c64u fs download` does too.
Anything a person reads should say FTP where it means FTP.

Routes used, and no others:

    GET  /v1/info
    GET  /v1/drives                      -- `image_path` per drive
    GET  /v1/files/<path>:info
    POST /v1/drives/a:mount?type=&mode=  -- image as the body, uploads
    PUT  /v1/drives/a:mount?image=&mode= -- mounts a file already on the device
    POST /v1/runners:run_prg             -- program as the body
    PUT  /v1/machine:reset
    GET  /v1/machine:readmem             -- read-only, `screen` only
    POST /v1/machine:writemem            -- `$0277`/`$00C6` only, `key` only

The last two are outside the tab's own allowlist on purpose.  The tab never
reads or writes memory; this tool reads screen RAM so a boot can be observed
rather than assumed, and writes exactly two addresses -- the KERNAL keyboard
buffer and its count -- so a game's `DISABLE FASTLOADER (Y/N)?` can be
answered.  Nothing here touches the device's configuration or reaches any of
the routes `tools/c64u.py` refuses.

    tools/c64urest.py info                          device identity
    tools/c64urest.py drives                        every drive and its image_path
    tools/c64urest.py fileinfo /Temp/temp0002       size and name, or the error
    tools/c64urest.py mount work/x.d64 [--name X.D64]   POST: upload and mount
    tools/c64urest.py remount /Temp/X.D64           PUT: mount what is there
    tools/c64urest.py run work/marker.prg           POST: DMA-load and start it
    tools/c64urest.py runfirst work/POOL1.D64       the image's first PRG
    tools/c64urest.py grab /Temp/X.D64 work/back.d64    FTP RETR
    tools/c64urest.py ftpcheck                      does ftplib reach it at all
    tools/c64urest.py dir work/back.d64             a local image's directory
    tools/c64urest.py screen                        what is on the C64's screen
    tools/c64urest.py key Y                         one key into the KERNAL buffer
    tools/c64urest.py reset                         PUT /v1/machine:reset
    tools/c64urest.py markprg work/mark.prg --file MARK1
                       build a PRG that writes one sequential file to drive 8
    tools/c64urest.py tempsweep --count 12 --dir work/issue272/sweep
                       upload N blank images, then ask files:info which survive

The host comes from `--host`, then `$POR_ULTIMATE`/`$WISH_ULTIMATE` (the
variables `wish/ultimate.py` reads), then `~/.config/c64u/config.toml` if it
happens to be there.  There is no default: the device is never this machine.
"""

from __future__ import annotations

import argparse
import ftplib
import io
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.d64 import D64  # noqa: E402  (after the path fix-up)

DEFAULT_PORT = 80
FTP_PORT = 21
ENV_HOST = ("POR_ULTIMATE", "WISH_ULTIMATE", "C64U_HOST")

# The C64's screen codes, enough of them to read a title screen back.
SCREEN_CODES = (
    "@abcdefghijklmnopqrstuvwxyz[£]↑←"
    " !\"#$%&'()*+,-./0123456789:;<=>?"
    "-ABCDEFGHIJKLMNOPQRSTUVWXYZ+|+||"
)


class DeviceError(RuntimeError):
    """The device answered, and what it said was a refusal."""


# -- where it is -------------------------------------------------------------


def find_host(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for name in ENV_HOST:
        if os.environ.get(name):
            return os.environ[name]
    config = pathlib.Path.home() / ".config" / "c64u" / "config.toml"
    if config.exists():
        for line in config.read_text().splitlines():
            match = re.match(r'\s*host\s*=\s*"([^"]+)"', line)
            if match:
                return match.group(1)
    raise SystemExit(
        "no Ultimate configured: pass --host, or set $POR_ULTIMATE")


# -- REST --------------------------------------------------------------------


class Rest:
    def __init__(self, host: str, port: int = DEFAULT_PORT,
                 timeout: float = 30.0, verbose: bool = True):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.verbose = verbose
        self.base = f"http://{host}:{port}/v1"

    def call(self, path: str, params: dict[str, str] | None = None,
             method: str = "GET", body: bytes | None = None,
             filename: str | None = None) -> tuple[bytes, str]:
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, data=body, method=method)
        if body is not None:
            request.add_header("Content-Type", "application/octet-stream")
            if filename:
                # The firmware names an uploaded /Temp file after the
                # attachment when the client sends one, and `temp%04x` when it
                # does not (`filemanager.cc create_temp_file`).
                request.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{filename}"')
        if self.verbose:
            size = "" if body is None else f" [{len(body)} bytes]"
            print(f"-> {method} {url}{size}", file=sys.stderr)
        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                data = reply.read()
                kind = reply.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            data, kind = exc.read(), exc.headers.get("Content-Type", "")
            raise DeviceError(f"HTTP {exc.code}: {data[:400]!r}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DeviceError(f"{self.host}: {exc}") from exc
        if self.verbose:
            print(f"<- {len(data)} bytes in {time.time() - started:.2f}s",
                  file=sys.stderr)
        return data, kind

    def json(self, path: str, params: dict[str, str] | None = None,
             method: str = "GET", body: bytes | None = None,
             filename: str | None = None) -> dict:
        data, _ = self.call(path, params, method, body, filename)
        try:
            answer = json.loads(data)
        except ValueError as exc:
            raise DeviceError(f"not JSON: {data[:200]!r}") from exc
        if answer.get("errors"):
            raise DeviceError("; ".join(answer["errors"]))
        return answer

    # -- the seven the tab may use ------------------------------------------

    def info(self) -> dict:
        return self.json("/info")

    def drives(self) -> list[dict]:
        return self.json("/drives").get("drives", [])

    def drive(self, letter: str = "a") -> dict:
        for entry in self.drives():
            if letter in entry:
                return entry[letter]
        raise DeviceError(f"no drive {letter}")

    def file_info(self, path: str) -> dict:
        quoted = urllib.parse.quote(path)
        return self.json(f"/files{quoted}:info")

    def mount_upload(self, image: bytes, drive: str = "a", kind: str = "d64",
                     mode: str = "readwrite",
                     filename: str | None = None) -> dict:
        return self.json(f"/drives/{drive}:mount", {"type": kind, "mode": mode},
                         method="POST", body=image, filename=filename)

    def mount_path(self, path: str, drive: str = "a",
                   mode: str = "readwrite", kind: str | None = None) -> dict:
        # `type` is not optional for a file with no extension: a POST upload
        # with no attachment name lands as `/Temp/temp0000`, and the PUT form
        # answers `Invalid Type ''` unless it is told.
        params = {"image": path, "mode": mode}
        if kind:
            params["type"] = kind
        return self.json(f"/drives/{drive}:mount", params, method="PUT")

    def run_prg(self, program: bytes) -> dict:
        return self.json("/runners:run_prg", method="POST", body=program)

    def reset(self) -> dict:
        return self.json("/machine:reset", method="PUT")

    # -- read-only, and outside the tab's allowlist -------------------------

    def key(self, petscii: int) -> None:
        """Put one key in the KERNAL's buffer, as a person at the prompt would.

        `$0277` is the buffer and `$00C6` the count, which is the path BASIC,
        `INPUT` and `GET` read from -- and the only way to answer a game's
        `DISABLE FASTLOADER (Y/N)?` from here.  A program polling the keyboard
        matrix through CIA 1 never sees it.  Outside the tab's allowlist and
        deliberately narrow: these two addresses and nothing else.
        """
        self.call("/machine:writemem", {"address": "0277"}, method="POST",
                  body=bytes([petscii]))
        self.call("/machine:writemem", {"address": "00C6"}, method="POST",
                  body=bytes([1]))

    def readmem(self, address: int, length: int) -> bytes:
        data, _ = self.call("/machine:readmem",
                            {"address": f"{address:04X}", "length": str(length)})
        return data


# -- FTP ---------------------------------------------------------------------


def ftp_connect(host: str, timeout: float = 10.0) -> ftplib.FTP:
    """Anonymous login, which is what the device's FTP File Service wants."""
    ftp = ftplib.FTP(timeout=timeout)
    ftp.connect(host, FTP_PORT, timeout=timeout)
    ftp.login("anonymous", "anonymous")
    return ftp


def ftp_retr(host: str, path: str, timeout: float = 30.0) -> bytes:
    ftp = ftp_connect(host, timeout)
    try:
        sink = io.BytesIO()
        ftp.retrbinary(f"RETR {path}", sink.write)
        return sink.getvalue()
    finally:
        try:
            ftp.quit()
        except Exception:  # pragma: no cover - a device that will not say bye
            ftp.close()


# -- a PRG that writes one file to drive 8 -----------------------------------


def marker_prg(filename: str = "MARK", payload: bytes = b"WISH272") -> bytes:
    """Assemble a PRG that opens a sequential file on drive 8 and writes it.

    The oracle for two of the spike's questions at once: a marker in the
    device's copy of the image proves both that `runners:run_prg` really ran
    the program and that a `readwrite` mount reaches the file on the device.
    """
    stub = bytes([0x0C, 0x08, 0x00, 0x00, 0x9E]) + b"2061" + bytes([0, 0, 0])
    start = 0x0801 + len(stub)
    name = (filename + ",S,W").encode("ascii")

    def assemble(name_at: int, data_at: int) -> bytes:
        code = bytearray()
        code += bytes([0xA9, len(name)])                    # LDA #namelen
        code += bytes([0xA2, name_at & 0xFF])               # LDX #<name
        code += bytes([0xA0, name_at >> 8])                 # LDY #>name
        code += bytes([0x20, 0xBD, 0xFF])                   # JSR SETNAM
        code += bytes([0xA9, 0x02, 0xA2, 0x08, 0xA0, 0x02])  # file 2, dev 8, sa 2
        code += bytes([0x20, 0xBA, 0xFF])                   # JSR SETLFS
        code += bytes([0x20, 0xC0, 0xFF])                   # JSR OPEN
        code += bytes([0xA2, 0x02, 0x20, 0xC9, 0xFF])       # LDX #2 : JSR CHKOUT
        code += bytes([0xA0, 0x00])                         # LDY #0
        code += bytes([0xB9, data_at & 0xFF, data_at >> 8])  # LDA data,Y
        code += bytes([0xF0, 0x06])                         # BEQ done
        code += bytes([0x20, 0xD2, 0xFF])                   # JSR CHROUT
        code += bytes([0xC8, 0xD0, 0xF5])                   # INY : BNE loop
        code += bytes([0x20, 0xCC, 0xFF])                   # JSR CLRCHN
        code += bytes([0xA9, 0x02, 0x20, 0xC3, 0xFF])       # LDA #2 : JSR CLOSE
        code += bytes([0x60])                               # RTS
        return bytes(code)

    length = len(assemble(0, 0))
    name_at = start + length
    data_at = name_at + len(name)
    code = assemble(name_at, data_at)
    assert len(code) == length
    return (bytes([0x01, 0x08]) + stub + code + name + payload + b"\0")


def first_prg(image: pathlib.Path) -> tuple[str, bytes]:
    """The image's first PRG -- what `LOAD"*",8,1` would load."""
    disk = D64.open(image)
    for entry in disk.directory():
        if entry.is_prg:
            return entry.display_name, disk.read_file(entry)
    raise SystemExit(f"{image}: no PRG in the directory")


def screen_text(data: bytes) -> list[str]:
    rows = []
    for row in range(25):
        line = data[row * 40:row * 40 + 40]
        rows.append("".join(
            SCREEN_CODES[byte & 0x7F] if (byte & 0x7F) < len(SCREEN_CODES)
            else "." for byte in line).rstrip())
    return rows


# -- commands ----------------------------------------------------------------


def cmd_info(rest: Rest, args) -> None:
    print(json.dumps(rest.info(), indent=2))


def cmd_drives(rest: Rest, args) -> None:
    for entry in rest.drives():
        for name, body in entry.items():
            print(f"{name}: image_file={body.get('image_file', '')!r} "
                  f"image_path={body.get('image_path', '')!r} "
                  f"enabled={body.get('enabled')}")


def cmd_fileinfo(rest: Rest, args) -> None:
    try:
        print(json.dumps(rest.file_info(args.path), indent=2))
    except DeviceError as exc:
        print(f"{args.path}: {exc}")
        raise SystemExit(3) from exc


def cmd_mount(rest: Rest, args) -> None:
    image = pathlib.Path(args.image).read_bytes()
    rest.mount_upload(image, mode=args.mode, kind=args.type,
                      filename=args.name)
    drive = rest.drive()
    print(f"mounted {drive.get('image_file')} at {drive.get('image_path')}")


def cmd_remount(rest: Rest, args) -> None:
    rest.mount_path(args.path, mode=args.mode, kind=args.type)
    drive = rest.drive()
    print(f"mounted {drive.get('image_file')} at {drive.get('image_path')}")


def cmd_run(rest: Rest, args) -> None:
    rest.run_prg(pathlib.Path(args.program).read_bytes())
    print(f"started {args.program}")


def cmd_runfirst(rest: Rest, args) -> None:
    name, program = first_prg(pathlib.Path(args.image))
    rest.run_prg(program)
    print(f"started {name} ({len(program)} bytes) from {args.image}")


def cmd_grab(rest: Rest, args) -> None:
    data = ftp_retr(rest.host, args.path, timeout=args.timeout)
    pathlib.Path(args.out).write_bytes(data)
    print(f"{args.path} -> {args.out}, {len(data)} bytes")


def cmd_ftpcheck(rest: Rest, args) -> None:
    ftp = ftp_connect(rest.host)
    try:
        print("welcome:", ftp.getwelcome())
        print("pwd:", ftp.pwd())
        lines: list[str] = []
        ftp.retrlines(f"LIST {args.path}", lines.append)
        for line in lines:
            print(" ", line)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def cmd_dir(rest: Rest, args) -> None:
    disk = D64.open(pathlib.Path(args.image))
    print(f"{disk.disk_name.decode('latin1')} "
          f"{disk.blocks_free} blocks free")
    for entry in disk.directory():
        print(f"  {entry.display_name:18} {entry.type_name}")


def cmd_screen(rest: Rest, args) -> None:
    for line in screen_text(rest.readmem(0x0400, 1000)):
        print(line)


def cmd_key(rest: Rest, args) -> None:
    rest.key(ord(args.key.upper()[0]))
    print(f"sent {args.key.upper()[0]!r}")


def cmd_reset(rest: Rest, args) -> None:
    rest.reset()
    print("reset")


def cmd_markprg(rest: Rest, args) -> None:
    program = marker_prg(args.file, args.payload.encode("ascii"))
    pathlib.Path(args.out).write_bytes(program)
    print(f"{args.out}: {len(program)} bytes, writes {args.file} to drive 8")


def temp_listing(host: str) -> dict[str, int]:
    """Every file in `/Temp`, by name and size, over FTP.

    One call where `files:info` would be one per path, and it sees files this
    session never created.
    """
    ftp = ftp_connect(host)
    try:
        lines: list[str] = []
        ftp.retrlines("LIST /Temp", lines.append)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    found: dict[str, int] = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 9:
            found[parts[-1]] = int(parts[4])
    return found


def cmd_temps(rest: Rest, args) -> None:
    for name, size in temp_listing(rest.host).items():
        print(f"{name:16} {size}")


def cmd_tempsweep(rest: Rest, args) -> None:
    """Upload N images, listing `/Temp` after each, to find the limit.

    The firmware's `enforce_temp_limits` keeps a fixed number of managed
    temporary files and deletes the oldest closed one past that.  This is that
    number, measured on the firmware in the room rather than read out of the
    master branch.
    """
    folder = pathlib.Path(args.dir)
    folder.mkdir(parents=True, exist_ok=True)
    mounted: list[str] = []
    for index in range(args.count):
        label = f"SWEEP{index:02d}"
        local = folder / f"{label}.D64"
        if not local.exists():
            D64.blank(name=label, disk_id=b"27").save(local)
        rest.mount_upload(local.read_bytes(), mode=args.mode)
        where = rest.drive().get("image_file", "")
        mounted.append(where)
        listing = temp_listing(rest.host)
        gone = [p for p in mounted if p.rsplit("/", 1)[-1] not in listing]
        print(f"{label} -> {where}: /Temp holds {len(listing)} "
              f"({' '.join(sorted(listing))})"
              + (f"; gone: {' '.join(gone)}" if gone else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--quiet", action="store_true",
                        help="do not trace each request on stderr")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info").set_defaults(run=cmd_info)
    sub.add_parser("drives").set_defaults(run=cmd_drives)

    one = sub.add_parser("fileinfo")
    one.add_argument("path")
    one.set_defaults(run=cmd_fileinfo)

    one = sub.add_parser("mount")
    one.add_argument("image")
    one.add_argument("--mode", default="readwrite")
    one.add_argument("--type", default="d64")
    one.add_argument("--name", help="filename to send as the attachment's")
    one.set_defaults(run=cmd_mount)

    one = sub.add_parser("remount")
    one.add_argument("path")
    one.add_argument("--mode", default="readwrite")
    one.add_argument("--type", default="d64",
                     help="the PUT form needs this when the file has no "
                          "extension; pass an empty string to leave it out")
    one.set_defaults(run=cmd_remount)

    one = sub.add_parser("run")
    one.add_argument("program")
    one.set_defaults(run=cmd_run)

    one = sub.add_parser("runfirst")
    one.add_argument("image")
    one.set_defaults(run=cmd_runfirst)

    one = sub.add_parser("grab")
    one.add_argument("path")
    one.add_argument("out")
    one.add_argument("--timeout", type=float, default=30.0)
    one.set_defaults(run=cmd_grab)

    one = sub.add_parser("ftpcheck")
    one.add_argument("--path", default="/Temp")
    one.set_defaults(run=cmd_ftpcheck)

    one = sub.add_parser("dir")
    one.add_argument("image")
    one.set_defaults(run=cmd_dir)

    sub.add_parser("screen").set_defaults(run=cmd_screen)

    one = sub.add_parser("key")
    one.add_argument("key", help="one character, into the KERNAL buffer")
    one.set_defaults(run=cmd_key)
    sub.add_parser("reset").set_defaults(run=cmd_reset)

    one = sub.add_parser("markprg")
    one.add_argument("out")
    one.add_argument("--file", default="MARK")
    one.add_argument("--payload", default="WISH272")
    one.set_defaults(run=cmd_markprg)

    sub.add_parser("temps").set_defaults(run=cmd_temps)

    one = sub.add_parser("tempsweep")
    one.add_argument("--count", type=int, default=12)
    one.add_argument("--dir", default="work/issue272/sweep")
    one.add_argument("--mode", default="readwrite")
    one.set_defaults(run=cmd_tempsweep)

    args = parser.parse_args(argv)
    rest = Rest(find_host(args.host), args.port, verbose=not args.quiet)
    try:
        args.run(rest, args)
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except ftplib.all_errors as exc:
        print(f"FTP error: {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

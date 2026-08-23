"""A Commodore 64 Ultimate backend, over its documented HTTP interface.

**UNVERIFIED. Nobody on this project has the hardware.** Every line below is
written from the vendor documentation and has been exercised only against a
stub server that implements what that documentation says. It may be wrong in
ways only a real device can show, and it is labelled so wherever it appears:
`Backend.verified` is False.

The interface is the REST API the Ultimate firmware serves over HTTP from 3.11
onwards (1541u-documentation.readthedocs.io, "REST API Calls"):

    GET  /v1/version                                  -- {"version": "0.1", ...}
    GET  /v1/info                                     -- product, firmware
    GET  /v1/machine:readmem?address=<hex>&length=<n>  -- binary attachment
    POST /v1/machine:writemem?address=<hex>            -- binary body

`readmem` performs a **DMA read on the cartridge bus**, which is why this is a
backend at all: it is the only documented way to read the machine's memory
without a resident stub. Firmware 3.12 and later may require a password, sent
as an `X-Password` header.

Three things follow from the transport and are designed for rather than
discovered late:

* **There is no discovery.** Set `$POR_ULTIMATE` (or `$WISH_ULTIMATE`) to the
  device's host or `host:port`; without it this backend does not probe and is
  never offered, so a machine with no Ultimate on the network sees no delay and
  no error.
* **Latency is a network round trip**, not a loopback socket, hence a slower
  default interval and hence batching -- one read of `$4900`-`$64FF` beats
  sixty small ones. The four reads a fix costs are the budget worth watching.
* **It should not disturb the machine.** VICE's 7%-fast effect comes from
  stopping and resuming the CPU; DMA does not stop it. Nothing here assumes
  that either way, and `Backend.disturbs` says False only as documentation.

Known-unknown, stated rather than buried: `party_fix` reads `$D011`, `$D018`
and `$DD00` to find the screen. Whether a cartridge-bus DMA read returns
sensible values for I/O registers is exactly the kind of thing that needs the
hardware. If it does not, the status line cannot be found and the mapper falls
back to the `$49C0` memory copy, which lags a move but works.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from automap.target import NotConnected

from . import debuglog
from .backends import Backend

DEFAULT_PORT = 80
ENV_HOST = ("POR_ULTIMATE", "WISH_ULTIMATE")
ENV_PASSWORD = ("POR_ULTIMATE_PASSWORD", "WISH_ULTIMATE_PASSWORD")

# The documentation's limits: a read is 1-65536 bytes and "may not pass $FFFF".
MAX_READ = 0x10000


def configured() -> tuple[str, int] | None:
    """The device's address, if somebody has said where it is."""
    for name in ENV_HOST:
        value = os.environ.get(name)
        if value:
            host, _, port = value.partition(":")
            return host, int(port) if port else DEFAULT_PORT
    return None


def _password() -> str | None:
    for name in ENV_PASSWORD:
        if os.environ.get(name):
            return os.environ[name]
    return None


class UltimateTarget:
    """A `Target` over the Ultimate's REST API. Untested against hardware."""

    def __init__(self, host: str | None = None, port: int | None = None,
                 password: str | None = None, timeout: float = 5.0):
        where = configured()
        if host is None:
            if where is None:
                raise NotConnected(
                    "no Ultimate configured; set $POR_ULTIMATE to its host name")
            host, port = where
        self.host = host
        self.port = port or DEFAULT_PORT
        self.password = password if password is not None else _password()
        self.timeout = timeout
        self.base = f"http://{self.host}:{self.port}/v1"

    # -- wire ------------------------------------------------------------

    def _request(self, path: str, data: bytes | None = None,
                 method: str | None = None) -> bytes:
        req = urllib.request.Request(f"{self.base}{path}", data=data,
                                     method=method)
        if self.password:
            req.add_header("X-Password", self.password)
        if data is not None:
            req.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as reply:
                body = reply.read()
                kind = reply.headers.get("Content-Type", "")
        except (urllib.error.URLError, OSError) as exc:
            # Every failure here is "the device is not answering", which is the
            # session's cue to drop to waiting and try again -- not an error to
            # put in front of somebody.
            raise NotConnected(f"{self.host}: {exc}") from exc
        if "json" in kind and data is None and path.startswith("/machine:read"):
            raise NotConnected(f"{self.host}: {_errors(body)}")
        return body

    # -- Target ----------------------------------------------------------

    def read(self, addr: int, length: int) -> bytes:
        if not 0 < length <= MAX_READ or addr + length > MAX_READ:
            raise ValueError(f"cannot read {length} bytes at ${addr:04X}: "
                             f"the read may not pass $FFFF")
        data = self._request(f"/machine:readmem?address={addr:04X}"
                             f"&length={length}")
        if len(data) != length:
            raise NotConnected(f"asked {length} bytes at ${addr:04X}, "
                               f"got {len(data)}")
        return data

    def write(self, addr: int, data: bytes) -> None:
        # POST rather than the PUT-with-hex form: that one caps at 128 bytes.
        self._request(f"/machine:writemem?address={addr:04X}",
                      data=bytes(data), method="POST")

    def close(self) -> None:
        """Nothing to close: each call is its own HTTP request."""

    # -- identity --------------------------------------------------------

    def describe(self) -> str:
        try:
            info = json.loads(self._request("/info"))
        except Exception as exc:
            # A device that will not name itself is still a device to read.
            debuglog.debug("the Ultimate would not describe itself: %s", exc)
            return "Ultimate"
        return (f"{info.get('product', 'Ultimate')} "
                f"firmware {info.get('firmware_version', '?')}").strip()


def _errors(body: bytes) -> str:
    try:
        return "; ".join(json.loads(body).get("errors") or []) or "refused"
    except Exception as exc:
        # The body is the device's, and a firmware that answers with something
        # other than the documented JSON is exactly what this is for.
        debuglog.debug("unreadable error body from the Ultimate: %s", exc)
        return "refused"


def present(timeout: float = 0.5) -> bool:
    """Is a device answering where we were told to look?

    False, quickly and quietly, when nothing is configured -- probing a network
    nobody named would cost a timeout on every tick and find nothing.
    """
    where = configured()
    if where is None:
        return False
    host, port = where
    try:
        req = urllib.request.Request(f"http://{host}:{port}/v1/version")
        password = _password()
        if password:
            req.add_header("X-Password", password)
        with urllib.request.urlopen(req, timeout=timeout) as reply:
            return reply.status == 200
    except Exception as exc:
        # Per tick while nothing is attached, so one line and no traceback.
        debuglog.debug("nothing answered at %s:%s (%s)", host, port, exc)
        return False


ULTIMATE = Backend(
    name="Ultimate",
    probe=present,
    connect=UltimateTarget,
    setup_hint=("set $POR_ULTIMATE to the device's host name (firmware 3.11+ "
                "serves the REST API; 3.12+ may need $POR_ULTIMATE_PASSWORD)"),
    # A network round trip per read, and reading is believed not to disturb the
    # machine, so a slower poll costs freshness and nothing else.
    default_interval_ms=500,
    disturbs=False,
    verified=False,
)

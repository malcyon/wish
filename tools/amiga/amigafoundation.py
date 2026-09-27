#!/usr/bin/env python3
"""Prepare, measure and accept one Amiga title's load, inspect, move, save and read-back run under WinUAE."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import uuid
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga.amigasecretsave import run_recon  # noqa: E402
from tools.amiga.route import (  # noqa: E402
    ISSUE,
    AmigaTitle,
    check_expect,
    parse_expect,
)
from tools.amiga.route_curse import CURSE, _prepare_curse  # noqa: E402
from tools.amiga.route_darkness import (  # noqa: E402
    DARKNESS,
    DARKNESS_RELOAD,
    _prepare_darkness,
    _prepare_darkness_reload,
)
from tools.amiga.route_pool import POOL, _prepare_pool  # noqa: E402
from tools.amiga.screens import PixelGuards  # noqa: E402
from tools.amiga.staging import _verified_disk  # noqa: E402
from tools.amiga.winuaesession import (  # noqa: E402
    HOLDER,
    RouteError,
    WinGuest,
    terminating,
)
from tools.registry import scratch  # noqa: E402

TITLES: dict[str, AmigaTitle] = {"pool": POOL, "curse": CURSE, "darkness": DARKNESS,
                                 "darkness-reload": DARKNESS_RELOAD}

_PREPARE = {"pool": _prepare_pool, "curse": _prepare_curse, "darkness": _prepare_darkness,
            "darkness-reload": _prepare_darkness_reload}


def _name(title: AmigaTitle) -> str:
    for name, known in TITLES.items():
        if known is title:
            return name
    raise RouteError("that is not one of this module's titles")


def prepare(title: AmigaTitle, run_id: str, *, specimen: pathlib.Path | None = None,
            specimen_sha256: str | None = None, accept_summary: pathlib.Path | None = None
            ) -> pathlib.Path:
    """Copy the title's registered images and specimen into a run folder, write `prepare.json`, and return it.

    Refuses when any pinned hash differs, the loaded slot does not decode, or a
    save letter the run writes already exists. Nothing registered is written.
    `darkness-reload` prepares from a game-written disk 3, so it requires `specimen`,
    `specimen_sha256` and `accept_summary`, and the other titles refuse the last two.
    """
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    name = _name(title)
    reload = name == "darkness-reload"
    given = (specimen, specimen_sha256, accept_summary)
    if reload and not all(given):
        raise RouteError("darkness-reload needs the disk 3, its SHA-256 and the accept summary")
    if not reload and (specimen_sha256 or accept_summary):
        raise RouteError(f"{name} takes no disk 3 hash or accept summary")
    run = scratch.cache_dir("acceptance", ISSUE, run_id)
    if run.exists():
        raise RouteError(f"run folder already exists: {run}")
    manifest = (_PREPARE[name](run, specimen, specimen_sha256, accept_summary) if reload
                else _PREPARE[name](run, specimen))
    path = run / "prepare.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def _summary(result: dict[str, Any], manifest: pathlib.Path, attempt: str) -> str:
    return json.dumps({"success": result["success"], "error": result["error"],
                       "unguarded": result["unguarded"],
                       "summary": str(manifest.parent / attempt / "summary.json")},
                      sort_keys=True)


def expect_verdict(title: AmigaTitle, manifest: pathlib.Path, attempt: str,
                   expect: tuple[str, int, int, int], tolerance_minutes: int = 0
                   ) -> tuple[bool, str]:
    """Read the route's later slot off the run's fetched save disk and check `expect` against it.

    Re-opens `<manifest.parent>/<attempt>/fetched-<save_disk>.adf`, which
    `run_recon` writes for every attempt that reached the fetch step, and
    reads `title.after_letter` -- the camp-save slot the accept route writes
    after its walk. Refutes, naming why, when that file is missing or the
    slot holds no matching node. Returns `(accepted, verdict line)`.
    """
    fetched = manifest.parent / attempt / f"fetched-{title.save_disk}.adf"
    if not fetched.is_file():
        name, eid, minutes, _data = expect
        return False, f"expect {name} id {eid} at {minutes} minutes: refutes (no fetched save disk)"
    reading = title.read_slot(_verified_disk(fetched), title.after_letter)
    return check_expect(reading, expect, tolerance_minutes=tolerance_minutes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    choices = sorted(TITLES)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--title", required=True, choices=choices)
        p.add_argument("--manifest", required=True, type=pathlib.Path)
        p.add_argument("--audio-proof", required=True, type=pathlib.Path)
        p.add_argument("--attempt", required=True)
        p.add_argument("--holder", default=None)
        p.add_argument("--deadline", type=float, default=1800)

    p = sub.add_parser("prepare", help="copy the registered images and the specimen into a run folder")
    p.add_argument("--title", required=True, choices=choices)
    p.add_argument("--run-id", required=True)
    p.add_argument("--disk3", type=pathlib.Path, default=None,
                   help="darkness-reload only: the game-written disk 3 an accept run fetched")
    p.add_argument("--disk3-sha256", default=None, help="darkness-reload only: that disk's SHA-256")
    p.add_argument("--accept-summary", type=pathlib.Path, default=None,
                   help="darkness-reload only: that accept run's summary.json")
    m = sub.add_parser("measure", help="boot and press the route up to the first save; writes nothing")
    common(m)
    m.add_argument("--guards", type=pathlib.Path, default=None,
                   help="screen guard JSON; a route state it holds must match, and the boot waits for its title")
    a = sub.add_parser("accept", help="guarded load, sheet, two saves around a walk and the read-back")
    common(a)
    a.add_argument("--guards", required=True, type=pathlib.Path)
    a.add_argument("--identity", required=True, type=pathlib.Path)
    a.add_argument("--expect", default=None,
                   help="NAME:ID:MINUTES:DATA, checked against the route's later slot")
    a.add_argument("--expect-tolerance-minutes", type=int, default=0,
                   help="minutes of slack --expect allows for elapsed game time")
    r = sub.add_parser("reload", help="guarded load of a game-written slot and a check of the place "
                                      "on screen; writes nothing")
    common(r)
    r.add_argument("--guards", required=True, type=pathlib.Path)
    r.add_argument("--identity", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        expect = parse_expect(args.expect) if getattr(args, "expect", None) else None
        with terminating():
            if args.command == "prepare":
                print(prepare(TITLES[args.title], args.run_id, specimen=args.disk3,
                              specimen_sha256=args.disk3_sha256,
                              accept_summary=args.accept_summary))
                return 0
            title = TITLES[args.title]
            holder = args.holder or f"wish{ISSUE}-{uuid.uuid4().hex[:12]}"
            if args.command == "measure":
                result = run_recon(
                    args.manifest, guest=WinGuest(), holder=holder,
                    audio_proof=args.audio_proof, attempt=args.attempt,
                    guard=PixelGuards(args.guards) if args.guards else None,
                    deadline_seconds=args.deadline, measure=True, title=title)
            else:
                result = run_recon(
                    args.manifest, guest=WinGuest(), guard=PixelGuards(args.guards),
                    identity=PixelGuards(args.identity), holder=holder,
                    audio_proof=args.audio_proof, attempt=args.attempt,
                    deadline_seconds=args.deadline, title=title,
                    **{"reload" if args.command == "reload" else "accept": True})
            print(_summary(result, args.manifest, args.attempt))
            for line in result.get("read", {}).get("verdicts", []):
                print(line)
            success = result["success"]
            if args.command == "accept" and expect is not None:
                accepted, line = expect_verdict(title, args.manifest, args.attempt, expect,
                                                args.expect_tolerance_minutes)
                print(line)
                success = success and accepted
            return 0 if success else 1
    except (RouteError, OSError, ValueError) as exc:
        print(f"amigafoundation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

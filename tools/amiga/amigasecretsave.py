#!/usr/bin/env python3
"""Prepare an exact Silver Blades Save As disk and preserve a guarded WinUAE probe."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga.acceptance import run_recon  # noqa: E402
from tools.amiga.route import check_expect, parse_expect  # noqa: E402
from tools.amiga.route_silver_blades import (  # noqa: E402
    ACCEPT_MIN_WAITS,
    CAMP_SAVE_LETTER,
    ROUTE,
    _slot_reading,
    default_min_waits,
    prepare,
)
from tools.amiga.screens import (  # noqa: E402
    PixelGuards,
    _box_digest,
    _box_is_uniform,
    guard_rule,
)
from tools.amiga.staging import _verified_disk  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402


def parse_route(text: str) -> tuple[tuple[str, str], ...]:
    """Read `KEY:state,KEY:state` into a route."""
    steps = []
    for part in text.split(","):
        key, sep, state = part.strip().partition(":")
        if not sep or not key or not state:
            raise RouteError(f"route step {part!r} is not KEY:state")
        steps.append((key.upper(), state))
    return tuple(steps)


def parse_write_keys(text: str) -> tuple[str, ...]:
    """Read `KEY,KEY` into upper-case write keys; an empty entry is an error."""
    keys = tuple(k.strip().upper() for k in text.split(","))
    if not all(keys):
        raise RouteError(f"write keys {text!r} contain an empty entry")
    return keys


def expect_verdict(manifest_path: pathlib.Path, attempt: str,
                   expect: tuple[str, int, int, int]) -> tuple[bool, str]:
    """Read Silver Blades' camp-save slot off the run's fetched boot disk and check `expect` against it.

    Re-opens `<manifest_path.parent>/<attempt>/fetched-df0.adf`, which
    `run_recon` writes for every attempt that reached the fetch step, and
    reads `CAMP_SAVE_LETTER` -- the slot the accept route's camp save writes.
    Returns `(accepted, verdict line)`.
    """
    fetched = manifest_path.parent / attempt / "fetched-df0.adf"
    if not fetched.is_file():
        name, eid, minutes, _data = expect
        return False, f"expect {name} id {eid} at {minutes} minutes: refutes (no fetched boot disk)"
    reading = _slot_reading(_verified_disk(fetched), CAMP_SAVE_LETTER)
    return check_expect(reading, expect)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="publish Wish's slot, stage DF0 holding it and DF1 as disk B")
    p.add_argument("--source", required=True, type=pathlib.Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--staged-from", type=pathlib.Path)
    p.add_argument("--issue", default="672")
    r = sub.add_parser("recon", help="guarded first load and menu-save probe")
    r.add_argument("--manifest", required=True, type=pathlib.Path)
    r.add_argument("--guards", type=pathlib.Path,
                   help="screen guard JSON; required unless --measure, which "
                        "checks the states it names and settles the rest")
    r.add_argument("--measure", action="store_true",
                   help="capture and record; never presses a write key")
    r.add_argument("--route", default=None,
                   help="KEY:state,KEY:state; default is the built-in route")
    r.add_argument("--write-keys", default="B",
                   help="comma-separated keys that write; measure never presses them")
    r.add_argument("--audio-proof", required=True, type=pathlib.Path)
    r.add_argument("--attempt", default="recon1")
    r.add_argument("--holder", default=None)
    g = sub.add_parser("guard", help="add one state's static box from a measured crop "
                                     "to a guard JSON, refusing a box a neighbour shares")
    g.add_argument("--state", required=True)
    g.add_argument("--crop", required=True, type=pathlib.Path,
                   help="a 720x568 crop of the state, as recon saved it")
    g.add_argument("--box", required=True, help="X0,Y0,X1,Y1 inside the crop")
    g.add_argument("--unlike", type=pathlib.Path, action="append", default=[],
                   help="a crop of a neighbouring state the box must not match")
    g.add_argument("--out", required=True, type=pathlib.Path)
    g.add_argument("--replace", action="store_true",
                   help="overwrite the state's existing rule in --out")
    a = sub.add_parser("accept", help="guarded load, menu save, BEGIN, two squares, camp save "
                                      "and the two-save readback")
    a.add_argument("--manifest", required=True, type=pathlib.Path)
    a.add_argument("--guards", required=True, type=pathlib.Path)
    a.add_argument("--identity", required=True, type=pathlib.Path)
    a.add_argument("--journal-python", required=True,
                   help="an interpreter that can import numpy and PIL, for the journal answerer")
    a.add_argument("--audio-proof", required=True, type=pathlib.Path)
    a.add_argument("--attempt", default="accept1")
    a.add_argument("--holder", default=None)
    a.add_argument("--deadline", type=float, default=1800)
    a.add_argument("--expect", default=None,
                   help="NAME:ID:MINUTES:DATA, checked against the camp-save slot")
    sub.add_parser("spindisk-control", help="unavailable until the exact-output failure is measured")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            print(prepare(args.source, args.run_id, staged_from=args.staged_from,
                          issue=args.issue))
            return 0
        if args.command == "guard":
            box = [int(n) for n in args.box.split(",")]
            rule = guard_rule(args.crop, box, args.state)
            for other in args.unlike:
                if _box_digest(other, box, args.state) == rule["sha256"]:
                    raise RouteError(f"{args.state} box {box} also matches {other}")
            if _box_is_uniform(args.crop, box, args.state):
                raise RouteError(f"{args.state} box {box} is one colour and would match "
                                 f"any screen showing it")
            rules = json.loads(args.out.read_text()) if args.out.exists() else {}
            if args.state in rules and not args.replace:
                raise RouteError(f"{args.out} already has a rule for {args.state}; "
                                 f"pass --replace to overwrite it")
            rules[args.state] = rule
            # Rename over the file so an interrupted write never leaves half a map.
            temp = args.out.with_name(args.out.name + ".tmp")
            try:
                temp.write_text(json.dumps(rules, indent=2, sort_keys=True) + "\n")
                os.replace(temp, args.out)
            finally:
                temp.unlink(missing_ok=True)
            print(json.dumps({args.state: rule}, sort_keys=True))
            return 0
        if args.command == "recon":
            if args.guards is None and not args.measure:
                raise RouteError("--guards is required unless --measure")
            guards = PixelGuards(args.guards) if args.guards else None
            route = parse_route(args.route) if args.route else ROUTE
            write_keys = parse_write_keys(args.write_keys)
            holder = args.holder or f"wish672-{uuid.uuid4().hex[:12]}"
            with terminating():
                result = run_recon(args.manifest, guest=WinGuest(), guard=guards,
                                   holder=holder,
                                   audio_proof=args.audio_proof,
                                   attempt=args.attempt, route=route,
                                   write_keys=write_keys, measure=args.measure,
                                   min_waits=default_min_waits(route))
            print(json.dumps({"success": result["success"],
                              "error": result["error"],
                              "summary": str(args.manifest.parent / args.attempt
                                             / "summary.json")}, sort_keys=True))
            return 0 if result["success"] else 1
        if args.command == "accept":
            expect = parse_expect(args.expect) if args.expect else None
            holder = args.holder or f"wish672-{uuid.uuid4().hex[:12]}"
            with terminating():
                result = run_recon(
                    args.manifest, guest=WinGuest(), guard=PixelGuards(args.guards),
                    identity=PixelGuards(args.identity), holder=holder,
                    audio_proof=args.audio_proof, attempt=args.attempt,
                    deadline_seconds=args.deadline, accept=True,
                    journal_python=args.journal_python,
                    min_waits={**default_min_waits(), **ACCEPT_MIN_WAITS})
            print(json.dumps({"success": result["success"], "error": result["error"],
                              "unguarded": result["unguarded"],
                              "summary": str(args.manifest.parent / args.attempt
                                             / "summary.json")}, sort_keys=True))
            for line in result["read"]["verdicts"]:
                print(line)
            success = result["success"]
            if expect is not None:
                accepted, line = expect_verdict(args.manifest, args.attempt, expect)
                print(line)
                success = success and accepted
            return 0 if success else 1
        raise RouteError(f"{args.command} is unavailable until the measured route is reviewed")
    except (RouteError, OSError, ValueError) as exc:
        print(f"amigasecretsave: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

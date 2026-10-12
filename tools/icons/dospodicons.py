#!/usr/bin/env python3
"""Check DOS Pools of Darkness combat figures against the game's ICON screen.

`goldbox/dos_pod_icons.py` composes a Pools of Darkness figure from the
player's `CHEAD.DAX`, `CBODY.DAX` and `COMSPR.DAX`.  This draws each pose over
the ICON screen's box in the screen's palette and compares it, pixel for
pixel, with a frame the game drew, at the four places the screen shows a
figure: OLD and NEW, ready and action.

``--run DIR [DIR ...]``
    Every `icon N` step of a `tools/dos/acceptance.py` run.  Each member's
    figure bytes come from `--save` (default the game folder's `SAVE`), slot
    the run's own, with the bytes the run's `--stage-icon` wrote laid over
    them; they must equal the bytes the run logged.  Prints one line a
    member and exits 1 on any pixel that differs or any bytes that disagree.

``--capture NAME PNG``
    One member's figure against one frame, from `--save` and `--slot`, with
    `--colours HEX` in place of the record's six colour bytes if given.

    tools/icons/dospodicons.py --run ~/.cache/wish/acceptance/WISH-378/dos-icon-darkness
    tools/icons/dospodicons.py --capture PAINE icon.png --colours 98f9f9c0a260

The game folder is `--game`, else the archives' `DARKNESS` (`$FR_ARCHIVES`,
then `gamedisks.yaml`).  Everything is opened read-only and nothing is
written.  The write-up is `docs/168-dos-dax-and-combat-icons.md`, "Pools of
Darkness".
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import dos_codec  # noqa: E402
from goldbox import dos_pod_icons as pod  # noqa: E402
from tools.icons import dosicons  # noqa: E402

TITLE = "pools-of-darkness"
#: The record fields a figure is composed from, as `acceptance.py` logs them.
FIELDS = ("icon_head", "icon_body", "size", "icon_colours")


def game_folder(given: str | None) -> pathlib.Path:
    """`--game`, else the archives' Pools of Darkness folder."""
    return dosicons.game_folder(TITLE, given)


def record_fields(char) -> dict:
    """A record's figure fields, colours as hex, as the driver logs them."""
    return {"icon_head": char.get("icon_head"),
            "icon_body": char.get("icon_body"), "size": char.get("size"),
            "icon_colours": bytes(char.get("icon_colours")).hex()}


def staged(fields: dict, stages: list[dict], file: str) -> tuple[dict, list]:
    """`fields` with every `--stage-icon` write to `file` laid over them.

    Returns the fields and the problems: a stage whose `before` bytes are not
    the save's own did not start from this save.
    """
    out, problems = dict(fields), []
    for stage in stages:
        if stage.get("stage") != "icon" or stage.get("file") != file:
            continue
        for key, before in stage["before"].items():
            mine = (out[key] if key == "icon_colours"
                    else f"{out[key]:02x}")
            if mine != before:
                problems.append(f"{file}: {key} is {mine} in the save, but "
                                f"the run staged it from {before}")
        for key, after in stage["after"].items():
            out[key] = after if key == "icon_colours" else int(after, 16)
    return out, problems


def drawn(game: pod.PodGameArt, fields: dict):
    """`(ready, action)` drawn over the box, as packed RGB rows."""
    palette = pod.icon_palette(game)
    poses = pod.compose(game.heads, game.bodies, fields["icon_head"],
                        fields["icon_body"], fields["size"],
                        bytes.fromhex(fields["icon_colours"]))
    return tuple(tuple(tuple(r << 16 | g << 8 | b
                             for r, g, b in (palette[v] for v in row))
                       for row in pod.on_box(game.box, pose))
                 for pose in poses)


def differences(screen, poses) -> dict[tuple[str, int], int]:
    """Pixels differing at each of :data:`goldbox.dos_pod_icons.PLACES`."""
    out = {}
    for (which, n), (x, y) in pod.PLACES.items():
        out[(which, n)] = sum(int(screen[y + dy, x + dx]) != v
                              for dy, row in enumerate(poses[n])
                              for dx, v in enumerate(row))
    return out


def check_frame(out, name: str, screen, poses) -> int:
    """Report one frame; the number of places that are not pixel for pixel."""
    differ = differences(screen, poses)
    bad = sum(1 for d in differ.values() if d)
    cells = ", ".join(f"{which} {('ready', 'action')[n]} {d}"
                      for (which, n), d in differ.items())
    out(f"{name}: {'pass' if not bad else 'FAIL'} (pixels differing of "
        f"{pod.CELL * pod.CELL}: {cells})")
    return bad


def check_run(out, game_dir: pathlib.Path, save: pathlib.Path | None,
              run: pathlib.Path) -> int:
    """Every `icon N` step of one acceptance run; the number of problems."""
    summary = json.loads((run / "summary.json").read_text())
    if summary.get("title") != "darkness":
        out(f"{run}: a {summary.get('title')} run, not darkness")
        return 1
    game = pod.read_game(game_dir)
    folder = save or game_dir / "SAVE"
    problems = 0
    steps = [r for r in summary["results"] if "icon" in r]
    if not steps:
        out(f"{run}: no icon step")
        return 1
    for result in steps:
        logged = result["record"]
        char = dos_codec.read_character(folder / logged["file"])
        fields, trouble = staged(record_fields(char),
                                 summary.get("staged", []), logged["file"])
        if any(fields[k] != logged[k] for k in FIELDS):
            trouble.append(f"composed from {fields}, but the run logged "
                           f"{ {k: logged[k] for k in FIELDS} }")
        for line in trouble:
            out(f"{result['name']}: DISAGREES: {line}")
        problems += len(trouble)
        screen = dosicons.capture_pixels(run / "shots"
                                         / f"{result['icon']}.png")
        problems += check_frame(
            out, f"{run.name} {result['icon']} {result['name']} "
                 f"({fields['icon_head']}/{fields['icon_body']}/"
                 f"{fields['size']}/{fields['icon_colours']})",
            screen, drawn(game, fields))
    return problems


def check_capture(out, game_dir: pathlib.Path, save: pathlib.Path,
                  slot: str, name: str, png: str,
                  colours: str | None) -> int:
    """One member against one frame; the number of problems."""
    try:
        screen = dosicons.capture_pixels(png)
    except dosicons.CaptureError as exc:
        out(str(exc))
        return 1
    fields = record_fields(dosicons.find_record(save, slot, name))
    if colours:
        fields["icon_colours"] = bytes.fromhex(colours).hex()
    return check_frame(out, name, screen, drawn(pod.read_game(game_dir),
                                                fields))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", help="the Pools of Darkness game folder")
    parser.add_argument("--save", help="the save folder (default GAME/SAVE)")
    parser.add_argument("--slot", default="A", help="the save slot letter")
    parser.add_argument("--run", nargs="+", metavar="DIR",
                        help="acceptance run folders with icon steps")
    parser.add_argument("--capture", nargs=2, metavar=("NAME", "PNG"),
                        help="NAME's composed figure against an ICON frame")
    parser.add_argument("--colours", metavar="HEX",
                        help="--capture: these six colour bytes instead")
    args = parser.parse_args(argv)
    if not (args.run or args.capture):
        parser.error("say which: --run or --capture")
    game = game_folder(args.game)
    save = pathlib.Path(args.save).expanduser() if args.save else None
    problems = 0
    for run in args.run or []:
        problems += check_run(print, game, save,
                              pathlib.Path(run).expanduser())
    if args.capture:
        problems += check_capture(print, game, save or game / "SAVE",
                                  args.slot, *args.capture, args.colours)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

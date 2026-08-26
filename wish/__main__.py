"""The `wish` command: the window, and the two subcommands beside it.

    wish [SAVE.D64]              open the map, loading a save disk if given
    wish --tab editor            open on the character sheet instead
    wish export SAVE.D64 -o party.yaml    the save editor, reading
    wish import party.yaml -o NEW.D64     the save editor, writing

The emulator is never launched from here. Start it with the usual wrapper (with
`POR_DEBUG=1`, so the binary monitor is listening) and this attaches to it; with
nothing running, the map tab waits and the editor does not care at all.

Two things that need no emulator keep their old spellings, because they are
about files and not about a running machine:

    wish --svg GEO00 out.svg     render one map offline
    wish --forget GEO00          clear remembered squares for an area
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from . import __version__, debuglog
from .debugmode import enable_from_argv

#: The subcommands, and the whole of the rule for spotting one: the first
#: argument is a subcommand when it is *exactly* one of these names, and a save
#: disk otherwise. No prefix matching, no guessing -- a save file genuinely
#: called `export` is still openable, as `./export`. `tools/wish.py` is their
#: body; see docs/129-one-binary.md for why there is one binary and not two.
SUBCOMMANDS = ("export", "import")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wish", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save", nargs="?", help="a .D64 save disk to open")
    ap.add_argument("--game-disk", help="a game disk, for item names and icons")
    ap.add_argument("--tab", choices=("editor", "map"),
                    help="which tab to open on")
    ap.add_argument("--area", help="force a GEO name instead of identifying it")
    ap.add_argument("--disks", help="where the game disks live, for this run "
                    "(default: the Game directory in File > Preferences)")
    ap.add_argument("--interval", type=int,
                    help="poll interval in ms (default: the backend's own)")
    ap.add_argument("--svg", nargs=2, metavar=("GEO", "OUT"),
                    help="render one map to SVG and exit; no emulator needed")
    ap.add_argument("--forget", metavar="AREA",
                    help="clear remembered squares for one area (or ALL), then "
                         "exit. Notes are kept")
    ap.add_argument("--version", action="version",
                    version=f"wish {__version__}")
    return ap


def game_of(save: str | None):
    """Which title's save this disk holds, or None if it cannot be told.

    The map tab needs it: with Pool of Radiance and Curse of the Azure Bonds
    disks in one directory, the open save is the only thing that says which
    game's maps to load and whose area names to print. Never fatal -- an
    unreadable disk is the editor's error to report, with its own message,
    not a reason to refuse to open the window.
    """
    if not save:
        return None
    try:
        from goldbox import games
        from goldbox.d64 import D64
        return games.detect(D64.open(save))
    except Exception:
        # The editor opens the same disk and reports its own failure; this one
        # only decides which title's maps to load.
        debuglog.exception("could not tell which game %s belongs to", save)
        return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else argv
    # Before the parser sees them: `--debug` is not an option the window takes,
    # it is a mode the whole process is in, and it has to be set before
    # anything reads it.
    enable_from_argv(argv)
    debuglog.install_excepthook()

    # `tools` sits beside this package in the source tree, and both the
    # subcommands and the Designer loop below live in it.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

    # Imported here rather than at the top: opening the window should not cost
    # PyYAML, the item tables and a D64 parse.
    if argv and argv[0] in SUBCOMMANDS:
        from tools.wish import subcommand
        return subcommand(argv[0], argv[1:])

    args = _parser().parse_args(argv)
    tab = args.tab or "map"

    # The Designer loop: edit character.ui, restart, and the running window is
    # already the new layout. No build step to forget.
    try:
        from tools.genui import ensure_current
    except ImportError:
        pass  # A frozen build has no .ui and no pyuic6; the form is compiled in.
    else:
        if ensure_current():
            print("character.ui changed; recompiled the form")

    from automap.__main__ import forget, load_maps_titled

    if args.forget:
        return forget(args.forget)

    game = game_of(args.save)
    # One precedence, resolved once: `--disks` for this run, else the Game
    # directory setting, else beside the save, else the usual folders. The
    # window resolves the same way from the same three inputs, so the maps it
    # is handed and the folder it reports cannot disagree.
    from automap.paths import resolve_disks
    where, source = resolve_disks(flag=args.disks, beside=args.save, game=game)
    maps, game = load_maps_titled(str(where) if where else None, game)
    if args.svg:
        from automap.render import to_svg
        name, out = args.svg
        if name.upper() not in maps:
            print(f"no map named {name}", file=sys.stderr)
            return 1
        pathlib.Path(out).write_text(to_svg(maps[name.upper()]),
                                     encoding="utf-8")
        print(f"{name.upper()} -> {out}")
        return 0
    if not maps:
        # Not fatal: the editor is the half most people use, and it needs no
        # game disk to open a save.
        # Naming the title matters when the save is one game and the disks in
        # the directory are another: "no game disks found" beside a shelf full
        # of Pool of Radiance disks reads as a bug.
        print(f"no game disks{f' for {game.title}' if game else ''} found"
              f"{f' under {where} ({source})' if where else ''}, "
              "so the map tab will be empty.\n"
              "File > Preferences… in the window says where to look, and "
              "reports what it found there.", file=sys.stderr)

    from .window import EDITOR_TAB, MAP_TAB, run
    return run(args.save, args.game_disk, maps=maps, area=args.area,
               tab=MAP_TAB if tab == "map" else EDITOR_TAB,
               interval_ms=args.interval, disks=args.disks,
               title=game.title if game else None)


if __name__ == "__main__":
    raise SystemExit(main())

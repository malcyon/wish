"""The `wish` command: the character editor and the live map in one window.

    wish [SAVE.D64]              open the map, loading a save disk if given
    wish --tab editor            open on the character sheet instead
    wish-editor / wish-automap   the same window, on the tab that name implies

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

from . import __version__


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wish", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save", nargs="?", help="a .D64 save disk to open")
    ap.add_argument("--game-disk", help="a POOL*.D64, for item names and icons")
    ap.add_argument("--tab", choices=("editor", "map"),
                    help="which tab to open on")
    ap.add_argument("--area", help="force a GEO name instead of identifying it")
    ap.add_argument("--disks", help="where the POOL*.D64 live "
                    "(default: $POR_DISKS, else searched for)")
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


def main(argv: list[str] | None = None, tab: str = "map") -> int:
    args = _parser().parse_args(argv)
    tab = args.tab or tab

    # The Designer loop: edit character.ui, restart, and the running window is
    # already the new layout. No build step to forget.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    try:
        from tools.genui import ensure_current
    except ImportError:
        pass  # A frozen build has no .ui and no pyuic6; the form is compiled in.
    else:
        if ensure_current():
            print("character.ui changed; recompiled the form")

    from automap.__main__ import forget, load_maps

    if args.forget:
        return forget(args.forget)

    maps = load_maps(args.disks)
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
        print("no POOL*.D64 game disks found, so the map tab will be empty.\n"
              "Point --disks or $POR_DISKS at the directory holding them.",
              file=sys.stderr)

    from .window import EDITOR_TAB, MAP_TAB, run
    return run(args.save, args.game_disk, maps=maps, area=args.area,
               tab=MAP_TAB if tab == "map" else EDITOR_TAB,
               interval_ms=args.interval)


def editor_main(argv: list[str] | None = None) -> int:
    """`wish-editor`: the same window, opened on the character sheet."""
    return main(argv, tab="editor")


def automap_main(argv: list[str] | None = None) -> int:
    """`wish-automap`: the same window, opened on the map.

    Kept because that is how the map is actually used -- a single-purpose
    window beside the game -- and because nobody's habit should break.
    """
    return main(argv, tab="map")


if __name__ == "__main__":
    raise SystemExit(main())

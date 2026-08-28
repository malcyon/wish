import glob
import os
import pathlib
import sys
from goldbox.games import Game
from goldbox.geo import load_geo_files
from .paths import disk_globs, resolve_disks, titles_in

def default_disks(game: Game | None = None) -> str:
    where, _source = resolve_disks(game=game)
    return str(where) if where is not None else str(pathlib.Path.cwd())

def load_maps(disks: str | None = None, game: Game | None = None) -> dict:
    return load_maps_titled(disks, game)[0]

def load_maps_titled(disks: str | None = None, game: Game | None = None) -> tuple[dict, Game | None]:
    if disks is None:
        where, _source = resolve_disks(game=game)
        if where is None:
            return {}, game
    else:
        where = pathlib.Path(disks)
    if game is None:
        present = titles_in(where)
        game = present[0] if present else None
    if game is None:
        return {}, None
    paths: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in glob.glob(os.path.join(str(where), pattern)):
            paths.setdefault(os.path.normcase(os.path.abspath(path)), path)
    found: dict = {}
    for path in sorted(paths.values()):
        for name, geo in load_geo_files(path).items():
            found.setdefault(name, geo)
    return found, game

def forget(area: str) -> int:
    import json
    from .state import data_dir, migrate_flat_notes
    migrate_flat_notes()
    files = sorted(data_dir().glob("*/*.json")) + sorted(data_dir().glob("*.json"))
    if area.upper() != "ALL":
        files = [f for f in files if f.stem.upper() == area.upper()]
        if not files:
            print(f"nothing remembered for {area}", file=sys.stderr)
            return 1
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dropped = len(payload.get("seen", []))
        payload["seen"] = []
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        kept = len(payload.get("notes", {}))
        print(f"{path.stem}: forgot {dropped} squares"
              + (f", kept {kept} note(s)" if kept else ""))
    return 0

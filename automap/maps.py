import glob
import os
import pathlib
import sys

from goldbox import c64_port
from goldbox.c64_port import C64Container
from goldbox.geo import GEO_SIZE, Geo, load_geo_files

from .paths import disk_globs, resolve_disks, titles_in


def default_disks(game: C64Container | None = None) -> str:
    where, _source = resolve_disks(game=game)
    return str(where) if where is not None else str(pathlib.Path.cwd())

def load_maps(disks: str | None = None, game: C64Container | None = None) -> dict:
    return load_maps_titled(disks, game)[0]

def load_maps_titled(disks: str | None = None, game: C64Container | None = None) -> tuple[dict, C64Container | None]:
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
        return _amiga_maps_titled(where, None)
    paths: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in glob.glob(os.path.join(str(where), pattern)):
            paths.setdefault(os.path.normcase(os.path.abspath(path)), path)
    found: dict = {}
    for path in sorted(paths.values()):
        for name, geo in load_geo_files(path).items():
            found.setdefault(name, geo)
    if not found:
        return _amiga_maps_titled(where, game)
    return found, game

def _volume_title(volume: str) -> C64Container | None:
    """Which title an Amiga disk belongs to, by its volume name.

    The disks say it nowhere else: the map library sits under `DISKB` or
    `DISK2`, which Pools of Darkness' `Disk3` echoes, and an image's file name
    is the player's to change. A volume none of these matches is not a title
    the automapper has a sheet for -- Pools of Darkness' `POD 3` also carries a
    `GEO.GLB` -- and is skipped, never handed to whichever title was asked for.
    """
    name = volume.lower()
    if name in ("poolgame", "pooldata"):
        return c64_port.POOL_OF_RADIANCE
    if name.startswith("curse"):
        return c64_port.CURSE_OF_THE_AZURE_BONDS
    if name.startswith("secret"):
        return c64_port.SECRET_OF_THE_SILVER_BLADES
    return None


def _dax_maps(disk) -> dict[str, Geo]:
    """The maps of a disk that keeps them in `geo.dax`, keyed `GEO{id:02X}`.

    That is Pool of Radiance's disk 2; the other two titles keep `GEO.GLB`.
    Each block is the C64's own two-byte load address and then the 1024-byte
    map, and the block id is the number the C64 spells into `GEO<n>`.
    """
    from goldbox import amiga_dax
    for path, _entry in disk.walk():
        if path.rsplit("/", 1)[-1].upper() == "GEO.DAX":
            return {f"GEO{ident:02X}": Geo.from_bytes(block)
                    for ident, block in amiga_dax.blocks(disk.read_file(path), path)
                    if len(block) in (GEO_SIZE, GEO_SIZE + 2)}
    return {}


def _amiga_maps_titled(where, game: C64Container | None
                       ) -> tuple[dict, C64Container | None]:
    """The maps off the Amiga disk images in a folder, and whose they are.

    Tried only once the C64 loader has found nothing, and `disk_globs` is not
    taught about `.adf` -- the character editor reads the same glob to decide
    which disks it opens. The Amiga's own files are read rather than the
    C64's, because the two ports' blocks are not all the same bytes.

    With a `game` only that title's disks are read. Without one the first title
    in `GAMES` order that has maps here answers, as the C64 side does. Every
    disk of a title is merged, since Pool of Radiance's set is two disks and
    only the second carries maps.
    """
    from automap import amiga
    from goldbox.amiga_adf import AmigaDisk
    where = pathlib.Path(where)
    try:
        images = sorted(p for p in where.iterdir() if p.suffix.lower() == ".adf")
    except OSError:
        return {}, game
    by_title: dict[str, dict] = {}
    for image in images:
        try:
            disk = AmigaDisk.open(image)
            title = _volume_title(disk.volume_name)
            if title is None or (game is not None and title is not game):
                continue
            maps = amiga.load_maps(image) or _dax_maps(disk)
        except Exception:                       # not a disk, or not readable
            continue
        for name, geo in maps.items():
            by_title.setdefault(title.key, {}).setdefault(name, geo)
    for title in ([game] if game is not None else c64_port.GAMES):
        if by_title.get(title.key):
            return by_title[title.key], title
    return {}, game


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

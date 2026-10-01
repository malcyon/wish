import glob
import os
import pathlib
import sys

from goldbox import c64_port, titles
from goldbox.c64_port import C64Container
from goldbox.geo import GEO_SIZE, Geo, load_geo_files

from .paths import disk_globs, resolve_disks, titles_in


def default_disks(game: C64Container | None = None) -> str:
    where, _source = resolve_disks(game=game)
    return str(where) if where is not None else str(pathlib.Path.cwd())

def load_maps(disks: str | None = None, game: C64Container | None = None) -> dict:
    return load_maps_titled(disks, game)[0]

#: Titles that have Amiga disks and no C64 container.
AMIGA_ONLY_TITLES = (titles.POOLS_OF_DARKNESS,)


def load_maps_titled(disks: str | None = None, game: C64Container | None = None,
                     amiga_only: bool = False) -> tuple[dict, C64Container | titles.Title | None]:
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
        return _amiga_maps_titled(where, None, amiga_only)
    paths: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in glob.glob(os.path.join(str(where), pattern)):
            paths.setdefault(os.path.normcase(os.path.abspath(path)), path)
    found: dict = {}
    for path in sorted(paths.values()):
        for name, geo in load_geo_files(path).items():
            found.setdefault(name, geo)
    if not found:
        return _amiga_maps_titled(where, game, amiga_only)
    return found, game

def load_world(disks: str | None, game: C64Container | None):
    """The three wilderness windows off a title's C64 disks, or None.

    None for a title without a travel grid, a folder with no C64 disks, and a
    set of disks that does not carry all three windows. An image that cannot
    be opened is skipped, so one damaged file does not cost the windows the
    good disks carry.
    """
    from goldbox.d64 import D64, D64Error
    from goldbox.world import World, WorldError
    if game is None or disks is None or not game.travel_grid:
        return None
    paths: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in glob.glob(os.path.join(str(disks), pattern)):
            paths.setdefault(os.path.normcase(os.path.abspath(path)), path)
    images = []
    for path in sorted(paths.values()):
        try:
            image = D64.open(path)
            list(image.iter_directory())
        except (D64Error, OSError):
            continue
        images.append(image)
    if not images:
        return None
    try:
        return World.from_disks(images)
    except (WorldError, D64Error, OSError):
        return None


def _volume_title(volume: str, amiga_only: bool = False
                  ) -> C64Container | titles.Title | None:
    """Which title an Amiga disk belongs to, by its volume name.

    The disks say it nowhere else: the map library sits under `DISKB` or
    `DISK2`, which Pools of Darkness' `Disk3` echoes, and an image's file name
    is the player's to change. A volume none of these matches is not a title
    the automapper has a sheet for -- Pools of Darkness' `POD 3` also carries a
    `GEO.GLB` -- and is skipped, never handed to whichever title was asked for.
    Pools of Darkness is named only when `amiga_only` asks for it.
    """
    name = volume.lower()
    if name in ("poolgame", "pooldata"):
        return c64_port.POOL_OF_RADIANCE
    if name.startswith("curse"):
        return c64_port.CURSE_OF_THE_AZURE_BONDS
    if name.startswith("secret"):
        return c64_port.SECRET_OF_THE_SILVER_BLADES
    if amiga_only and name.startswith(("pod ", "pools of darkness")):
        return titles.POOLS_OF_DARKNESS
    return None


def amiga_images(where, title: titles.Title) -> list[pathlib.Path]:
    """The loose `.adf` images in a folder whose volume name says they are
    `title`'s, which can only be an `AMIGA_ONLY_TITLES` one.

    The same recognition `_amiga_maps_titled` uses, so a folder cannot count a
    disk the loader would skip.
    """
    from goldbox.amiga_adf import AmigaDisk
    try:
        images = sorted(p for p in pathlib.Path(where).iterdir()
                        if p.suffix.lower() == ".adf")
    except OSError:
        return []
    found = []
    for image in images:
        try:
            named = _volume_title(AmigaDisk.open(image).volume_name,
                                  amiga_only=True)
        except Exception:                       # not a disk, or not readable
            continue
        if named is not None and named.key == title.key:
            found.append(image)
    return found


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


def _amiga_maps_titled(where, game: C64Container | titles.Title | None,
                       amiga_only: bool = False
                       ) -> tuple[dict, C64Container | titles.Title | None]:
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
            title = _volume_title(disk.volume_name, amiga_only)
            if title is None or (game is not None and title.key != game.key):
                continue
            maps = amiga.load_maps(image) or _dax_maps(disk)
        except Exception:                       # not a disk, or not readable
            continue
        for name, geo in maps.items():
            by_title.setdefault(title.key, {}).setdefault(name, geo)
    for title in ([game] if game is not None else
                  c64_port.GAMES + (AMIGA_ONLY_TITLES if amiga_only else ())):
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

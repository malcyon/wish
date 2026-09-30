"""Hide the shipped SAVE drawer on a scratch Silver Blades boot disk.

The game searches its own drawer before DF1.  Renaming only that drawer's
header makes a standalone save disk reachable without deleting game data.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import string
import struct
from typing import Any, Callable

from goldbox import amiga_adf, amiga_savegame, dos_savegame
from goldbox import amiga_adf as adf
from tools.amiga import amigalaterslot, amigasaves
from tools.amiga.route import AmigaTitle
from tools.amiga.winuaesession import RouteError
from tools.registry import scratch, specimens

SOURCE_SHA256 = "2f9ae86494561231dd1d70b350ae07b959c9f62642b64e9d4b57ffd23686ace4"
SECRET_SHA256 = "ba6c8b5ed94b9003d61f727968e040d55a37d79ba109d46fb013163a698a158d"
SAVE_DIR_BLOCK = 919
OLD_NAME = "SAVE"
HIDDEN_NAME = "SAVE_OFF_40"


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _entry(path: pathlib.Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256(path)}


def _verified_disk(path: pathlib.Path) -> amiga_adf.AmigaDisk:
    disk = amiga_adf.AmigaDisk.open(path)
    problems = disk.verify()
    if problems:
        raise RouteError(f"{path} fails ADF verification: {problems}")
    return disk



class StageError(ValueError):
    """The image or destination is not the bounded staging case."""


def replace_file_in_place(disk: amiga_adf.AmigaDisk, path: str, data: bytes) -> None:
    """Overwrite a same-length file's data blocks where they lie, leaving every other byte of the image alone.

    `AmigaDisk.write_file` reallocates blocks and stamps the current time on the
    drawer and root, so two runs of it never give the same image; this gives a
    staged image that can be rebuilt byte for byte from the original and checked
    by hash. Only a single-header OFS file the same length as `data` is handled.
    """
    if disk.ffs:
        raise StageError("in-place staging needs an OFS image")
    header = disk.lookup(path).block
    blocks = disk._file_blocks(header)
    data_blocks = blocks[:-1]
    if (blocks[-1] != header or len(disk.read_file(path)) != len(data)
            or len(data_blocks) != max(1, -(-len(data) // amiga_adf.OFS_DATA_SIZE))):
        raise StageError(f"{path} is not a same-length single-header file to overwrite in place")
    disk._write_data_chain(header, data, data_blocks)


def stage_place(data: bytes, container: str, x: int, y: int,
                facing: int) -> tuple[bytes, dict[str, list[int]]]:
    """A later-title Amiga saved game with the party put on `x`,`y` facing `facing` (0 N, 1 E, 2 S, 3 W).

    Writes only the three square bytes that hold the place; the wall byte, the
    area word and the rest are left for the engine to recompute on the first
    step, as the DOS driver's `stage_place` leaves them. Refused, before
    anything is written, for a value out of range, a file that is not a saved
    game of `container`, and a party standing outdoors, where the square is the
    last indoor one and the game does not read it, and a party that has not
    set out, which the game starts at the first square. Returns the new bytes and
    `{"before": [x, y, facing], "after": [x, y, facing]}`.
    """
    if not (0 <= x <= 15 and 0 <= y <= 15 and 0 <= facing <= 3):
        raise StageError(f"place {x},{y},{facing}: x and y are 0 to 15, facing 0 to 3")
    try:
        save = amiga_savegame.parse(data, container)
        # The indoors word is what the game reads; the world state refuses a save whose
        # word and area disagree, which would hide this reason behind a decode error.
        outdoors = save.word(dos_savegame.INDOORS) == 0
        state = None if outdoors else amiga_savegame.state_from_savegame(save)
    except Exception as exc:  # noqa: BLE001 - any reader failure means this is not a saved game to stage
        raise StageError(f"not a readable {container} saved game: "
                         f"{type(exc).__name__}: {exc}") from exc
    if state is None:
        raise StageError("the saved game was made outdoors, where the square is not "
                         "read; a place can be staged in an indoor save only")
    if not state.set_out:
        raise StageError("the party has not set out, so the game starts it at the story's "
                         "first square and never reads the saved one")
    scale = dos_savegame.FACING_SCALE
    staged = amiga_savegame.with_square(save, x=x, y=y, facing=facing * scale)
    return staged, {"before": [save.x, save.y, save.facing // scale],
                    "after": [x, y, facing]}


def _posix_output_supported() -> bool:
    """Whether this host can create inside a directory without following links."""
    supported = getattr(os, "supports_dir_fd", ())
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in supported
        and os.mkdir in supported
    )


_POSIX_OUTPUT_SUPPORTED = _posix_output_supported()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _renamed_path(path: str) -> str:
    if path == f"/{OLD_NAME}" or path.startswith(f"/{OLD_NAME}/"):
        return f"/{HIDDEN_NAME}{path[len(OLD_NAME) + 1:]}"
    return path


def _files(disk: adf.AmigaDisk) -> dict[str, tuple[int, str]]:
    return {
        path: (entry.block, _sha(disk.read_file(path)))
        for path, entry in disk.walk()
    }


def _drawers(disk: adf.AmigaDisk) -> dict[str, int]:
    return {path: entry.block for path, entry in disk.walk_dirs()}


def _in_root_bucket(disk: adf.AmigaDisk, bucket: int, block: int) -> bool:
    """Check the hash chain; ``lookup`` itself searches every bucket."""
    root = disk.block(disk.root)
    current = struct.unpack_from(">I", root, adf._HDR_HASH_TABLE + 4 * bucket)[0]
    seen: set[int] = set()
    while current:
        if current in seen:
            raise StageError(f"root hash bucket {bucket} loops at block {current}")
        seen.add(current)
        if current == block:
            return True
        current = struct.unpack_from(">I", disk.block(current), adf._HDR_NEXT_HASH)[0]
    return False


def _output_location(out: pathlib.Path) -> tuple[pathlib.Path, tuple[str, ...]]:
    """Resolve an output inside the tool's scratch or cache root."""
    requested = out.absolute()
    if ".." in requested.parts:
        raise StageError("output must stay inside Wish scratch or cache")
    # The namespace is a directory name kept so recorded manifests still resolve.
    roots = (
        (scratch.scratch_dir("amigaacceptance").absolute(), 1),
        (scratch.cache_dir("amigaacceptance").absolute(), 2),
    )
    for root, base_depth in roots:
        try:
            relative = requested.relative_to(root)
        except ValueError:
            continue
        if not relative.parts:
            break
        base = root.parents[base_depth].resolve()
        root_parts = root.relative_to(root.parents[base_depth]).parts
        canonical_root = base.joinpath(*root_parts)
        if not requested.resolve().is_relative_to(canonical_root):
            break
        return base, root_parts + relative.parts
    raise StageError("output must stay inside Wish scratch or cache")


def _write_exclusive(
    out: pathlib.Path, base: pathlib.Path, parts: tuple[str, ...], data: bytes,
) -> None:
    """Walk from a trusted base without following symlinks and create once."""
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open("/", directory_flags)
    try:
        for name in base.parts[1:]:
            try:
                child = os.open(name, directory_flags, dir_fd=directory)
            except OSError as exc:
                raise StageError(
                    "output path contains a symlink or non-directory") from exc
            os.close(directory)
            directory = child
        for name in parts[:-1]:
            try:
                os.mkdir(name, dir_fd=directory)
            except FileExistsError:
                pass
            try:
                child = os.open(name, directory_flags, dir_fd=directory)
            except OSError as exc:
                raise StageError(
                    "output path contains a symlink or non-directory") from exc
            os.close(directory)
            directory = child
        try:
            file = os.open(
                parts[-1],
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o644,
                dir_fd=directory,
            )
        except FileExistsError as exc:
            raise StageError(f"output already exists: {out}") from exc
        with os.fdopen(file, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(directory)


def _pinned_source(source, out, expected_source_sha256, expected_secret_sha256):
    """Check the platform, output and source pins shared by both staging routes."""
    if not _POSIX_OUTPUT_SUPPORTED:
        raise StageError("staging requires POSIX no-follow directory operations")
    if source.resolve() == out.resolve():
        raise StageError("source and output resolve to the same file")
    base, parts = _output_location(out)
    if out.exists() or out.is_symlink():
        raise StageError(f"output already exists: {out}")
    original = source.read_bytes()
    source_sha = _sha(original)
    if source_sha != expected_source_sha256:
        raise StageError(
            f"source SHA-256 differs: {source_sha}, expected {expected_source_sha256}")
    try:
        disk = adf.AmigaDisk(original)
        problems = disk.verify()
        if problems:
            raise StageError(f"source ADF verification failed: {problems}")
        if disk.volume_name != "Secret 1":
            raise StageError(f"source volume is {disk.volume_name!r}, not 'Secret 1'")
        secret_sha = _sha(disk.read_file("/Secret"))
    except adf.AmigaDiskError as exc:
        raise StageError(f"source ADF is unreadable: {exc}") from exc
    if secret_sha != expected_secret_sha256:
        raise StageError(
            f"/Secret SHA-256 differs: {secret_sha}, expected "
            f"{expected_secret_sha256}")
    return base, parts, original, disk, source_sha, secret_sha


def stage_boot_disk(
    source: str | pathlib.Path,
    out: str | pathlib.Path,
    *,
    expected_source_sha256: str = SOURCE_SHA256,
    expected_secret_sha256: str = SECRET_SHA256,
) -> dict[str, object]:
    """Write one verified scratch ADF, refusing a changed source or overwrite.

    The default hashes pin registered side A and its executable.  Overrides
    exist for generated, game-data-free tests.
    """
    source = pathlib.Path(source)
    out = pathlib.Path(out)
    base, parts, original, disk, source_sha, secret_sha = _pinned_source(
        source, out, expected_source_sha256, expected_secret_sha256)
    try:
        try:
            save_dir = disk.lookup(f"/{OLD_NAME}")
        except adf.AmigaDiskError as exc:
            raise StageError(f"/{OLD_NAME} is unavailable on the source") from exc
        if not save_dir.is_dir or save_dir.block != SAVE_DIR_BLOCK:
            raise StageError(
                f"/{OLD_NAME} must be a drawer at block {SAVE_DIR_BLOCK}; "
                f"got {save_dir}")
        header = disk.block(SAVE_DIR_BLOCK)
        old_bytes = OLD_NAME.encode("ascii")
        if (header[adf._HDR_NAME] != len(old_bytes)
                or header[adf._HDR_NAME + 1:
                          adf._HDR_NAME + 1 + len(old_bytes)] != old_bytes):
            raise StageError(f"block {SAVE_DIR_BLOCK} does not name /{OLD_NAME}")
        hidden_bytes = HIDDEN_NAME.encode("ascii")
        if len(hidden_bytes) > adf.MAX_NAME:
            raise StageError("hidden drawer name exceeds the AmigaDOS limit")
        old_bucket = adf.hash_name(OLD_NAME)
        if adf.hash_name(HIDDEN_NAME) != old_bucket:
            raise StageError("hidden drawer name changes the root hash bucket")
        if not _in_root_bucket(disk, old_bucket, SAVE_DIR_BLOCK):
            raise StageError(
                f"block {SAVE_DIR_BLOCK} is absent from root hash bucket "
                f"{old_bucket}")
        if any(entry.name.upper() == HIDDEN_NAME.upper()
               for entry in disk.entries()):
            raise StageError(f"/{HIDDEN_NAME} already exists on the source")

        original_files = _files(disk)
        original_drawers = _drawers(disk)
        name_at = SAVE_DIR_BLOCK * adf.BLOCK_SIZE + adf._HDR_NAME
        disk._data[name_at:name_at + 1 + len(hidden_bytes)] = (
            bytes([len(hidden_bytes)]) + hidden_bytes)
        disk._fix(SAVE_DIR_BLOCK, adf._HDR_CHECKSUM)
        staged_bytes = disk.to_bytes()
        changed_blocks = [
            number for number in range(disk.block_count)
            if original[number * adf.BLOCK_SIZE:(number + 1) * adf.BLOCK_SIZE]
            != staged_bytes[number * adf.BLOCK_SIZE:(number + 1) * adf.BLOCK_SIZE]
        ]
        if changed_blocks != [SAVE_DIR_BLOCK]:
            raise StageError(f"changed blocks are {changed_blocks}, not [919]")
        if staged_bytes[:1024] != original[:1024]:
            raise StageError("the first 1024 boot bytes changed")

        staged = adf.AmigaDisk(staged_bytes)
        problems = staged.verify()
        if problems:
            raise StageError(f"staged ADF verification failed: {problems}")
        try:
            staged.lookup(f"/{OLD_NAME}")
        except adf.AmigaDiskError:
            pass
        else:
            raise StageError(f"/{OLD_NAME} remains available on the staged disk")
        renamed = staged.lookup(f"/{HIDDEN_NAME}")
        if not renamed.is_dir or renamed.block != SAVE_DIR_BLOCK:
            raise StageError(f"/{HIDDEN_NAME} is not the drawer at block 919")
        expected_files = {
            _renamed_path(path): value for path, value in original_files.items()
        }
        if _files(staged) != expected_files:
            raise StageError("a staged file changed, vanished or became unreadable")
        expected_drawers = {
            _renamed_path(path): block for path, block in original_drawers.items()
        }
        if _drawers(staged) != expected_drawers:
            raise StageError("a staged drawer changed or vanished")
        if _sha(staged.read_file("/Secret")) != secret_sha:
            raise StageError("/Secret changed on the staged disk")
    except adf.AmigaDiskError as exc:
        raise StageError(f"source or staged ADF is unreadable: {exc}") from exc

    _write_exclusive(out, base, parts, staged_bytes)
    written = out.read_bytes()
    staged_sha = _sha(staged_bytes)
    if _sha(written) != staged_sha:
        raise StageError("written ADF differs from the verified staged bytes")
    return {
        "source": str(source),
        "output": str(out),
        "volume": staged.volume_name,
        "source_sha256": source_sha,
        "staged_sha256": staged_sha,
        "bootblock_sha256": _sha(original[:1024]),
        "secret_sha256": secret_sha,
        "renamed_directory_block": SAVE_DIR_BLOCK,
        "changed_blocks": changed_blocks,
        "files_checked": len(original_files),
        "file_sha256": {
            path: digest for path, (_, digest) in sorted(_files(staged).items())
        },
    }


def stage_embedded_boot_disk(
    source: str | pathlib.Path,
    slot: bytes,
    letter: str,
    out: str | pathlib.Path,
    *,
    expected_source_sha256: str = SOURCE_SHA256,
    expected_secret_sha256: str = SECRET_SHA256,
) -> dict[str, object]:
    """Write a scratch side A holding `slot` as `/SAVE/savgam<letter>.sav`.

    The game searches its own boot volume's SAVE drawer first, so this is a
    save the game reads with its own disks in place.  Every other file and the
    boot block stay byte-identical, and a letter already in use is refused.
    """
    source = pathlib.Path(source)
    out = pathlib.Path(out)
    base, parts, original, disk, source_sha, secret_sha = _pinned_source(
        source, out, expected_source_sha256, expected_secret_sha256)
    name = f"savgam{letter}.sav"
    path = f"/{OLD_NAME}/{name}"
    if len(letter) != 1 or letter not in string.ascii_letters:
        raise StageError(f"slot letter {letter!r} is not one letter")
    try:
        try:
            disk.lookup(path)
        except adf.AmigaDiskError:
            pass
        else:
            raise StageError(f"{path} already exists on the source")
        original_files = _files(disk)
        disk.write_file(path, slot)
        staged_bytes = disk.to_bytes()
        staged = adf.AmigaDisk(staged_bytes)
        problems = staged.verify()
        if problems:
            raise StageError(f"staged ADF verification failed: {problems}")
        if staged.read_file(path) != slot:
            raise StageError("the staged slot differs from the input")
        staged_files = _files(staged)
        if any(staged_files.get(p, (None, None))[1] != value[1]
               for p, value in original_files.items()):
            raise StageError("an existing file changed on the staged disk")
        if set(staged_files) != set(original_files) | {path}:
            raise StageError("the staged disk gained or lost a file besides the slot")
        if staged_bytes[:1024] != original[:1024]:
            raise StageError("the first 1024 boot bytes changed")
    except adf.AmigaDiskError as exc:
        raise StageError(f"source or staged ADF is unreadable: {exc}") from exc

    _write_exclusive(out, base, parts, staged_bytes)
    written = out.read_bytes()
    if _sha(written) != _sha(staged_bytes):
        raise StageError("written ADF differs from the verified staged bytes")
    return {
        "source": str(source),
        "output": str(out),
        "volume": staged.volume_name,
        "source_sha256": source_sha,
        "staged_sha256": _sha(staged_bytes),
        "secret_sha256": secret_sha,
        "slot_path": path,
        "slot_sha256": _sha(slot),
        "files_checked": len(original_files),
    }


def _find_images(wanted: dict[str, str]) -> dict[str, tuple[str, bytes]]:
    """Each wanted key's registered image, found by its SHA-256 inside the zips too: `{key: (label, bytes)}`."""
    found: dict[str, tuple[str, bytes]] = {}
    for label, data in amigasaves.images():
        digest = hashlib.sha256(data).hexdigest()
        for key, pinned in wanted.items():
            if digest == pinned and key not in found:
                found[key] = (label, data)
    missing = [key for key in wanted if key not in found]
    if missing:
        raise RouteError(f"registered image {missing} was not found by its SHA-256")
    return found


@dataclasses.dataclass(frozen=True)
class _Sources:
    """The registered specimen and disks a title's run starts from."""

    name: str
    title: AmigaTitle
    specimen: tuple[str, ...]
    specimen_sha256: str
    volume: str
    loaded: str
    later: str
    images: dict[str, str]
    import_slot: Callable[[adf.AmigaDisk, str, adf.AmigaDisk, str], bytes] | None = (
        amigalaterslot.import_slot)


def _prepare_from(src: _Sources, run: pathlib.Path, specimen: pathlib.Path | None, *,
                  substitute: pathlib.Path | None = None, substitute_letter: str = "A",
                  ) -> dict[str, Any]:
    """Prepare the run folder from the pinned specimen, or from it with one slot swapped.

    `substitute`, when given, is a disk some other tool wrote a party onto --
    typically a Save As Amiga output. Its `substitute_letter` slot replaces
    `src.loaded` on a copy of the pinned specimen, through
    `src.import_slot`; every other file on the copy, and the pin
    checks on the specimen and side disks, are unchanged. `state_a`/`names_a`
    then describe the substituted slot, not the pinned specimen's.
    """
    title = src.title
    specimen = (pathlib.Path(specimen) if specimen
                else specimens.tree_root().joinpath(*src.specimen))
    if not specimen.is_file():
        raise RouteError(f"the specimen {specimen} is missing")
    if sha256(specimen) != src.specimen_sha256:
        raise RouteError(f"the specimen SHA-256 differs: {sha256(specimen)}")
    save = amiga_adf.AmigaDisk.open(specimen)
    if save.verify() or save.volume_name != src.volume:
        raise RouteError(f"{specimen} is not a verified {src.volume} disk")
    present = title.slot_letters(save)
    for taken in (title.control_letter, title.after_letter):
        if taken in present:
            raise RouteError(f"slot {taken} already exists on the specimen")
    loaded, later = title.read_slot(save, src.loaded), title.read_slot(save, src.later)
    for letter, reading in ((src.loaded, loaded), (src.later, later)):
        if "place" not in reading:
            raise RouteError(f"specimen slot {letter} does not decode: {reading}")
    images = _find_images(src.images)
    scratch.ensure(run)
    disks: dict[str, dict[str, str]] = {}
    for key, (_label, data) in images.items():
        path = run / f"{key}.adf"
        path.write_bytes(data)
        disks[key] = {"path": str(path), "sha256": sha256(path)}
    working = run / "save.adf"
    shutil.copyfile(specimen, working)
    disks["save"] = {"path": str(working), "sha256": sha256(working)}
    if any(disks[key]["sha256"] != pinned for key, pinned in src.images.items()):
        raise RouteError("a working copy differs from the pinned disk")
    if disks["save"]["sha256"] != src.specimen_sha256:
        raise RouteError("the working save disk differs from the specimen")
    substituted: dict[str, str] | None = None
    if substitute is not None:
        if src.import_slot is None:
            raise RouteError(f"{src.name} takes no substitute slot")
        substitute = pathlib.Path(substitute)
        if not substitute.is_file():
            raise RouteError(f"the substitute {substitute} is missing")
        source_disk = amiga_adf.AmigaDisk.open(substitute)
        source_problems = source_disk.verify()
        if source_problems:
            raise RouteError(f"{substitute} fails ADF verification: {source_problems}")
        working_disk = adf.AmigaDisk(bytearray(working.read_bytes()))
        try:
            src.import_slot(working_disk, src.loaded, source_disk, substitute_letter)
        except (adf.AmigaDiskError, ValueError, SystemExit) as exc:
            raise RouteError(f"the substitute slot could not be imported: {exc}") from exc
        problems = working_disk.verify()
        if problems:
            raise RouteError(f"the substituted working disk fails verification: {problems}")
        working_disk.save(working)
        disks["save"]["sha256"] = sha256(working)
        save = amiga_adf.AmigaDisk.open(working)
        if save.volume_name != src.volume:
            raise RouteError(f"{working} is not a {src.volume} disk after substitution")
        loaded = title.read_slot(save, src.loaded)
        if "place" not in loaded:
            raise RouteError(f"substituted slot {src.loaded} does not decode: {loaded}")
        substituted = {"path": str(substitute), "sha256": sha256(substitute),
                       "letter": substitute_letter}
    # A registered image inside a zip has no file of its own, so `registered` holds the
    # specimen and `sources` names each image by where it was found.
    manifest = {
        "title": src.name, "disks": disks,
        "registered": {"specimen": {"path": str(specimen), "sha256": sha256(specimen)}},
        "sources": {key: {"label": label, "sha256": src.images[key]}
                    for key, (label, _data) in images.items()},
        "loaded_letter": src.loaded,
        "state_a": loaded["place"], "names_a": loaded["names"],
        # A substituted party never walked the pinned specimen's route, so its
        # "later" checkpoint describes an unrelated party's position.
        "expected_after": None if substitute is not None else later["place"],
    }
    if substituted is not None:
        manifest["substitute"] = substituted
    after = _find_images(src.images)
    if (sha256(specimen) != src.specimen_sha256
            or any(hashlib.sha256(after[key][1]).hexdigest() != pinned
                   for key, pinned in src.images.items())):
        raise RouteError("a registered image changed during preparation")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args()
    try:
        manifest = stage_boot_disk(args.source, args.out)
    except (OSError, StageError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

"""Hide the shipped SAVE drawer on a scratch Silver Blades boot disk.

The game searches its own drawer before DF1.  Renaming only that drawer's
header makes a standalone save disk reachable without deleting game data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import struct

from goldbox import amiga_adf as adf

SOURCE_SHA256 = "2f9ae86494561231dd1d70b350ae07b959c9f62642b64e9d4b57ffd23686ace4"
SECRET_SHA256 = "ba6c8b5ed94b9003d61f727968e040d55a37d79ba109d46fb013163a698a158d"
SAVE_DIR_BLOCK = 919
OLD_NAME = "SAVE"
HIDDEN_NAME = "SAVE_OFF_40"
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class StageError(ValueError):
    """The image or destination is not the bounded staging case."""


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
    if source.resolve() == out.resolve():
        raise StageError("source and output resolve to the same file")
    if out.resolve().is_relative_to(_REPO_ROOT):
        raise StageError("output must be outside the repository")
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
        if secret_sha != expected_secret_sha256:
            raise StageError(
                f"/Secret SHA-256 differs: {secret_sha}, expected "
                f"{expected_secret_sha256}")
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

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() or out.is_symlink():
        raise StageError(f"output already exists: {out}")
    staged.save(out)
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

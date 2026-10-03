"""Validate focused checks against the exact staged Git tree."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from contextlib import nullcontext
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path(sys.executable).absolute()
RUFF = PYTHON.with_name("ruff")
GUARDS = (
    "tests/suite/test_repository_contents.py",
    "tests/suite/test_toolreadmes.py",
    "tests/generate/test_genimports.py",
)
GENERATED = "tests/generate/test_generated.py"


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def staged_tree() -> tuple[str, list[str]]:
    """Pin the index before running any check and name its changed paths."""
    tree = git("write-tree").decode().strip()
    changed = [name.decode() for name in
               git("diff", "--cached", "--name-only", "-z").split(b"\0") if name]
    tracked = git("ls-files", "-z").split(b"\0")
    if any(name.split(b"/", 1)[0] == b".aws" for name in tracked if name):
        raise ValueError("The index contains a private .aws path")
    return tree, changed


def checkout_symlinks(destination: Path, *, configured: bool | None = None) -> bool:
    """Match Git checkout behavior, including hosts without link privileges."""
    if configured is None:
        result = subprocess.run(["git", "config", "--bool", "--get", "core.symlinks"],
                                cwd=ROOT, capture_output=True, text=True)
        if result.returncode not in (0, 1):
            result.check_returncode()
        configured = (result.stdout.strip() == "true" if result.returncode == 0
                      else os.name != "nt")
    if not configured:
        return False
    probe = destination / ".wish-symlink-probe"
    try:
        probe.symlink_to("absent-target")
    except OSError:
        return False
    else:
        probe.unlink()
        return True


def extract_tree(tree: str, destination: Path,
                 *, create_symlinks: bool | None = None) -> None:
    """Read only tracked index bytes, rejecting private or escaping entries."""
    if create_symlinks is None:
        create_symlinks = checkout_symlinks(destination)
    archive = git("-c", "core.autocrlf=false", "-c", "core.eol=lf",
                  "archive", "--format=tar", tree)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] == ".aws":
                continue
            if member.name.startswith("/") or ".." in parts:
                raise ValueError(f"Unsafe Git archive entry: {member.name}")
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                target.chmod(member.mode & 0o777)
            elif member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or not (target.parent / member.linkname).resolve().is_relative_to(destination):
                    raise ValueError(f"Unsafe Git archive symlink: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                if create_symlinks:
                    target.symlink_to(member.linkname)
                else:
                    target.write_bytes(os.fsencode(member.linkname))
            else:
                raise ValueError(f"Unsupported Git archive entry: {member.name}")


def install_git_inventory(tree: str, parent: str, destination: Path,
                          *, create_symlinks: bool | None = None) -> str:
    """Expose the staged tree and parent history through an isolated Git index."""
    original_git = Path(git("rev-parse", "--absolute-git-dir").decode().strip())
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
    if create_symlinks is not None:
        subprocess.run(["git", "config", "core.symlinks",
                        "true" if create_symlinks else "false"],
                       cwd=destination, check=True)
    alternate = destination / ".git/objects/info/alternates"
    alternate.parent.mkdir(parents=True, exist_ok=True)
    alternate.write_bytes(str(original_git / "objects").encode("utf-8") + b"\n")
    commit = subprocess.check_output(["git", "-c", "user.name=Wish validation",
                                      "-c", "user.email=validation@example.invalid",
                                      "commit-tree", tree, "-p", parent,
                                      "-m", "Prospective commit"], cwd=destination).decode().strip()
    subprocess.run(["git", "read-tree", tree], cwd=destination, check=True)
    subprocess.run(["git", "update-ref", "refs/heads/validated", commit],
                   cwd=destination, check=True)
    subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/validated"],
                   cwd=destination, check=True)
    return commit


def checked_paths(changed: list[str], requested: list[str]) -> tuple[list[str], list[str]]:
    """Collect changed test directories and run selected tests with guards."""
    if "tests/conftest.py" in changed and not requested:
        raise ValueError("tests/conftest.py changed: supply affected --test targets")
    changed_tests = [name for name in changed if name.startswith("tests/")
                     and name.endswith(".py") and not name.endswith("/conftest.py")
                     and name != GENERATED]
    tests = sorted(set(requested + changed_tests))
    fixture_dirs = {str(PurePosixPath(name).parent) for name in changed
                    if name.startswith("tests/") and name.endswith("/conftest.py")
                    and name != "tests/conftest.py"}
    directories = sorted({str(PurePosixPath(name.split("::", 1)[0]).parent)
                          for name in tests} | fixture_dirs)
    collect = sorted(set(directories + list(GUARDS)))
    run = sorted(set(tests + list(GUARDS)))
    return collect, run


def run(command: list[str], root: Path, private_inputs: bool) -> None:
    print("Run:", " ".join(command), flush=True)
    env = os.environ.copy()
    if not private_inputs:
        example = (root / "gamedisks.yaml.example").read_text(encoding="utf-8")
        for name in re.findall(r"^\s*env:\s*(\w+)\s*$", example, re.MULTILINE):
            env.pop(name, None)
        env["WISH_SPECIMENS"] = str(root / ".missing-private-specimens")
    subprocess.run(command, cwd=root, env=env, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="append", default=[],
                        help="Focused pytest path or node ID; repeat for each affected target")
    parser.add_argument("--registry", type=Path,
                        help="Link an existing local gamedisks.yaml for private-input tests")
    parser.add_argument("--output", type=Path,
                        help="Keep the isolated snapshot at this new directory")
    args = parser.parse_args(argv)
    try:
        tree, changed = staged_tree()
        parent = git("rev-parse", "HEAD").decode().strip()
        if not changed:
            raise ValueError("No staged changes to validate")
        for name in args.test:
            path = PurePosixPath(name.split("::", 1)[0])
            if (path.is_absolute() or ".." in path.parts or
                    not name.startswith("tests/") or path.name == "conftest.py"):
                raise ValueError(f"Invalid focused test path: {name}")
        if any(name.endswith(".py") and not name.startswith("tests/")
               for name in changed) and not args.test:
            raise ValueError("Stage Python source changes with --test for affected tests")
        collect, tests = checked_paths(changed, args.test)
        print(f"Staged tree: {tree}", flush=True)
        if args.output is None:
            context = tempfile.TemporaryDirectory(prefix="wish-ci-validate-")
        else:
            snapshot_output = args.output.absolute()
            if snapshot_output.exists():
                raise ValueError(f"Snapshot output already exists: {snapshot_output}")
            snapshot_output.mkdir(parents=True)
            context = nullcontext(str(snapshot_output))
        with context as temporary:
            snapshot = Path(temporary)
            create_symlinks = checkout_symlinks(snapshot)
            extract_tree(tree, snapshot, create_symlinks=create_symlinks)
            commit = install_git_inventory(tree, parent, snapshot,
                                           create_symlinks=create_symlinks)
            (snapshot / ".git/validation.json").write_text(json.dumps({
                "staged_tree": tree, "prospective_commit": commit,
                "parent_commit": parent,
                "changed_paths": changed,
            }, indent=2) + "\n", encoding="utf-8")
            print(f"Prospective commit: {commit}", flush=True)
            if args.registry is not None:
                registry = args.registry.absolute()
                if not registry.is_file():
                    raise ValueError(f"Registry file is absent: {registry}")
                (snapshot / "gamedisks.yaml").symlink_to(registry)
            for name in tests:
                if not (snapshot / name.split("::", 1)[0]).is_file():
                    raise ValueError(f"Focused test is absent from staged tree: {name}")
            ignored = ([] if any(name.split("::", 1)[0] == GENERATED for name in tests)
                       else [f"--ignore={GENERATED}"])
            run([str(PYTHON), "-m", "pytest", "-q", "-n0", "--collect-only",
                 *ignored, *collect], snapshot,
                args.registry is not None)
            run([str(PYTHON), "-m", "pytest", "-q", *tests], snapshot,
                args.registry is not None)
            run([str(RUFF), "check", "."], snapshot, args.registry is not None)
            run([str(PYTHON), "tools/generate/genui.py", "--check"], snapshot,
                args.registry is not None)
        if git("write-tree").decode().strip() != tree:
            raise ValueError("The index changed during validation; rerun on the new tree")
        if git("rev-parse", "HEAD").decode().strip() != parent:
            raise ValueError("HEAD changed during validation; rerun on the new parent")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Validation failed: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

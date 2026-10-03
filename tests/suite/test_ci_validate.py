"""The repair checks must use staged bytes and preserve every collected test."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.suite import ci_validate


def test_snapshot_keeps_git_inventory_and_parent_history(tmp_path, monkeypatch):
    tree = ci_validate.git("rev-parse", "HEAD^{tree}").decode().strip()
    parent = ci_validate.git("rev-parse", "HEAD").decode().strip()
    original_git = ci_validate.git

    def windows_checkout_git(*args):
        return original_git("-c", "core.autocrlf=true", *args)

    monkeypatch.setattr(ci_validate, "git", windows_checkout_git)
    ci_validate.extract_tree(tree, tmp_path)
    ci_validate.install_git_inventory(tree, parent, tmp_path)
    alternate = tmp_path / ".git/objects/info/alternates"
    git_dir = ci_validate.git("rev-parse", "--absolute-git-dir").decode().strip()
    assert alternate.read_bytes() == (str(Path(git_dir) / "objects").encode("utf-8")
                                      + b"\n")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"],
                                     cwd=tmp_path).decode().strip()
    assert actual == tree
    expected = ci_validate.git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    actual_files = subprocess.check_output(["git", "ls-files"],
                                           cwd=tmp_path).splitlines()
    assert actual_files == expected
    assert (tmp_path / "pyproject.toml").read_bytes() == ci_validate.git(
        "show", "HEAD:pyproject.toml")


def test_snapshot_materializes_link_blob_without_symlink_privilege(
        tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("Symlinks are unavailable")

    monkeypatch.setattr(Path, "symlink_to", denied)
    assert ci_validate.checkout_symlinks(tmp_path, configured=True) is False
    tree = ci_validate.git("rev-parse", "HEAD^{tree}").decode().strip()
    ci_validate.extract_tree(tree, tmp_path, create_symlinks=False)
    alias = tmp_path / ".agents/rules/art.md"
    assert alias.is_file() and not alias.is_symlink()
    assert alias.read_bytes() == b"../../.claude/rules/art.md"


def test_changed_test_directories_collect_with_repository_guards():
    collect, run = ci_validate.checked_paths(
        ["tests/areas/test_fasttravelrun.py", "tests/records/conftest.py"],
        ["tests/suite/test_ci_validate.py"])
    assert "tests/areas" in collect
    assert "tests/records" in collect
    assert "tests/suite" in collect
    assert set(ci_validate.GUARDS) <= set(collect)
    assert "tests/areas/test_fasttravelrun.py" in run
    assert "tests/records/conftest.py" not in run


def test_root_conftest_change_requires_explicit_affected_tests():
    with pytest.raises(ValueError, match="supply affected --test targets"):
        ci_validate.checked_paths(["tests/conftest.py"], [])
    targets = ["tests/suite/test_ci_validate.py", "tests/records/test_effects.py"]
    collect, run = ci_validate.checked_paths(["tests/conftest.py"], targets)
    assert {"tests/suite", "tests/records", *ci_validate.GUARDS} <= set(collect)
    assert set(targets + list(ci_validate.GUARDS)) == set(run)


def test_prior_failure_order_keeps_stale_ids_and_remaining_items(pytestconfig, tmp_path):
    conftest = next(plugin for plugin in pytestconfig.pluginmanager.get_plugins()
                    if getattr(plugin, "__file__", None) == str(
                        ci_validate.ROOT / "tests/conftest.py"))
    prior = tmp_path / "failures.json"
    prior.write_text(json.dumps(["gone::case", "c::case", "a::case"]))
    items = [SimpleNamespace(nodeid=f"{name}::case",
                             iter_markers=lambda marker: iter(())) for name in "dbca"]
    config = SimpleNamespace(getoption=lambda _: prior)
    conftest.pytest_collection_modifyitems(config, items)
    assert [item.nodeid for item in items] == [
        "c::case", "a::case", "d::case", "b::case"]
    prior.unlink()
    conftest.pytest_collection_modifyitems(config, items)
    assert len(items) == 4

    prior.write_text(json.dumps(["e::case"]))
    grouped = SimpleNamespace(
        nodeid="e::case@shared",
        iter_markers=lambda marker: iter([SimpleNamespace(args=("shared",), kwargs={})]))
    items.append(grouped)
    conftest.pytest_collection_modifyitems(config, items)
    assert items[0] is grouped

    prior.write_text("not JSON")
    conftest.pytest_collection_modifyitems(config, items)
    assert len(items) == 5


def _record_priority_sample(name):
    directory = os.environ.get("WISH_PRIORITY_TEST_DIR")
    if directory:
        with (Path(directory) / "order.txt").open("a", encoding="utf-8") as log:
            log.write(f"{os.environ['PYTEST_XDIST_WORKER']}:{name}\n")


@pytest.mark.xdist_group("ci-priority")
def test_priority_sample_first():
    _record_priority_sample("first")


@pytest.mark.xdist_group("ci-priority")
def test_priority_sample_second():
    _record_priority_sample("second")


@pytest.mark.xdist_group("ci-priority")
def test_priority_sample_previous_failure():
    _record_priority_sample("previous_failure")


def test_prior_failure_list_orders_group_under_xdist_without_dropping_tests(tmp_path):
    prior = tmp_path / "failures.json"
    prior.write_text(json.dumps([
        "tests/suite/test_ci_validate.py::test_priority_sample_previous_failure",
        "tests/not_selected.py::test_stale",
    ]))
    env = os.environ.copy()
    env["WISH_PRIORITY_TEST_DIR"] = str(tmp_path)
    result = subprocess.run(
        [str(ci_validate.PYTHON), "-m", "pytest", "-q", "-n", "2",
         "--dist", "loadgroup", "--wish-prior-failures", str(prior),
         "tests/suite/test_ci_validate.py::test_priority_sample_first",
         "tests/suite/test_ci_validate.py::test_priority_sample_second",
         "tests/suite/test_ci_validate.py::test_priority_sample_previous_failure",
         "tests/suite/test_ci_validate.py::test_changed_test_directories_collect_with_repository_guards"],
        cwd=ci_validate.ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout
    order = (tmp_path / "order.txt").read_text(encoding="utf-8").splitlines()
    assert [line.split(":", 1)[1] for line in order] == [
        "previous_failure", "first", "second"]
    assert len({line.split(":", 1)[0] for line in order}) == 1

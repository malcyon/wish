"""The per-root credential audit script from
`ansible/roles/sandbox-network/tasks/isolation-test-credential-root.yml`,
run directly against a synthetic directory tree.

The task file is the source of truth; this test renders the same Jinja
template text out of it (rather than keeping a second copy) and runs it
locally with `bash`, so a change to the script is exercised here without any
VM, ssh key or the registry's disks.
"""
from __future__ import annotations

import pathlib
import re
import shlex
import shutil
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
TASK_FILE = (ROOT / "ansible" / "roles" / "sandbox-network" / "tasks"
             / "isolation-test-credential-root.yml")
DEFAULTS_FILE = (ROOT / "ansible" / "roles" / "sandbox-network" / "defaults"
                 / "main.yml")

TOKEN = "ghp_" + "x" * 36  # matches sandbox_net_token_pattern


def _audit_script_template() -> str:
    """The Jinja text of `sandbox_net_credential_audit_script`, straight out
    of the task file -- not a copy kept beside it."""
    tasks = yaml.safe_load(TASK_FILE.read_text())
    for task in tasks:
        script = task.get("vars", {}).get("sandbox_net_credential_audit_script")
        if script is not None:
            return script
    raise AssertionError(
        f"{TASK_FILE} no longer defines sandbox_net_credential_audit_script")


def _prune_globs_and_pattern() -> tuple[list[str], str]:
    defaults = yaml.safe_load(DEFAULTS_FILE.read_text())
    return (defaults["sandbox_net_credential_prune_globs"],
            defaults["sandbox_net_token_pattern"])


#: The only Jinja constructs the audit script template actually uses: one
#: `{% for %}` loop over the prune globs, and `{{ name }}` / `{{ name | quote }}`
#: substitutions. Rendered by hand rather than pulling in `jinja2`, which is
#: not one of this project's own dependencies -- it belongs to the system
#: `ansible` this template is written for, not to `pytest`.
_FOR_LOOP = re.compile(
    r"\{%\s*for\s+g\s+in\s+sandbox_net_credential_prune_globs\s*%\}"
    r"(?P<body>.*?)"
    r"\{%\s*endfor\s*%\}", re.DOTALL)
_VAR = re.compile(r"\{\{\s*(?P<name>\w+)(?:\s*\|\s*(?P<filt>\w+))?\s*\}\}")


def _substitute(text: str, values: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        value = values[m.group("name")]
        return shlex.quote(value) if m.group("filt") == "quote" else value
    return _VAR.sub(repl, text)


def _render(root: pathlib.Path, prune_globs: list[str], pattern: str) -> str:
    values = {"root": str(root), "sandbox_net_token_pattern": pattern}
    template = _audit_script_template()

    def expand_loop(m: re.Match) -> str:
        return "".join(_substitute(m.group("body"), {"g": glob})
                       for glob in prune_globs)

    rendered = _FOR_LOOP.sub(expand_loop, template)
    if "{% for" in rendered or "{% endfor" in rendered:
        raise AssertionError(
            "the audit script template grew a Jinja construct this test's "
            "hand-rolled renderer does not know about -- update _render")
    return _substitute(rendered, values)


def _run_audit(root: pathlib.Path, prune_globs: list[str], pattern: str) -> str:
    script = _render(root, prune_globs, pattern)
    result = subprocess.run(["bash", "-s"], input=script, capture_output=True,
                             text=True, timeout=30)
    return result.stdout


def _counts(stdout: str) -> dict[str, int]:
    line = next(row for row in stdout.splitlines() if row.startswith("COUNTS "))
    fields = dict(part.split("=", 1) for part in line.split()[1:])
    return {k: v for k, v in fields.items() if k != "root"}


@pytest.fixture
def home(tmp_path: pathlib.Path) -> pathlib.Path:
    """`<tmp>/home/testuser`, standing in for a real `/home/<user>`."""
    h = tmp_path / "home" / "testuser"
    h.mkdir(parents=True)
    return h


def _synthetic_globs(tmp_path: pathlib.Path) -> list[str]:
    """The shipped `sandbox_net_credential_prune_globs` is anchored to a real
    `/home`, which a test must not scan. Re-anchor the same glob shape at
    `tmp_path` instead of hand-writing a second pattern here, so a change to
    the shipped glob's *shape* -- not just its value -- is exercised."""
    real_globs = _prune_globs_and_pattern()[0]
    return [g.replace("/home/", f"{tmp_path}/home/") for g in real_globs]


pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="no bash to run the audit script with")


def test_a_token_under_flatpak_repo_objects_is_pruned(home, tmp_path):
    """The token that started this: reachable only through the pruned tree."""
    flatpak = home / ".local" / "share" / "flatpak" / "repo" / "objects" / "ab"
    flatpak.mkdir(parents=True)
    (flatpak / "cdef").write_text(TOKEN)
    prune_globs = _synthetic_globs(tmp_path)
    pattern = _prune_globs_and_pattern()[1]

    stdout = _run_audit(tmp_path / "home", prune_globs, pattern)

    assert "AUDIT=CLEAN" in stdout
    assert _counts(stdout)["scanned"] == "0"


def test_a_token_hard_linked_into_the_flatpak_runtime_tree_is_pruned(home, tmp_path):
    """The correction on #644: pruning only `repo/objects` was not enough,
    because Flatpak hard-links the same content into `runtime/` and `app/`."""
    runtime = home / ".local" / "share" / "flatpak" / "runtime" / "org.x" / "files" / "bin"
    runtime.mkdir(parents=True)
    (runtime / "payload").write_text(TOKEN)
    app = home / ".local" / "share" / "flatpak" / "app" / "org.y" / "files"
    app.mkdir(parents=True)
    (app / "payload").write_text(TOKEN)
    prune_globs = _synthetic_globs(tmp_path)
    pattern = _prune_globs_and_pattern()[1]

    stdout = _run_audit(tmp_path / "home", prune_globs, pattern)

    assert "AUDIT=CLEAN" in stdout, (
        "a token reachable only through flatpak/runtime or flatpak/app was "
        "scanned, so the prune is too narrow again")
    assert _counts(stdout)["scanned"] == "0"


def test_a_token_outside_the_flatpak_directory_is_still_found(home, tmp_path):
    """The prune must not reach past `.local/share/flatpak` itself: a
    similarly-named sibling, and Flatpak's own per-app state under
    `.var/app`, both stay in scope."""
    sibling = home / ".local" / "share" / "flatpak-other"
    sibling.mkdir(parents=True)
    (sibling / "secret.txt").write_text(TOKEN)
    var_app = home / ".var" / "app" / "org.z"
    var_app.mkdir(parents=True)
    (var_app / "secret.txt").write_text(TOKEN)
    prune_globs = _synthetic_globs(tmp_path)
    pattern = _prune_globs_and_pattern()[1]

    stdout = _run_audit(tmp_path / "home", prune_globs, pattern)

    assert "AUDIT=FOUND" in stdout
    assert _counts(stdout)["matched"] == "2"
    assert _counts(stdout)["scanned"] == "2"


def test_a_clean_tree_of_ordinary_files_passes_quickly(home, tmp_path):
    for n in range(50):
        (home / f"file{n}.txt").write_text(f"nothing interesting here #{n}")
    prune_globs = _synthetic_globs(tmp_path)
    pattern = _prune_globs_and_pattern()[1]

    stdout = _run_audit(tmp_path / "home", prune_globs, pattern)

    assert "AUDIT=CLEAN" in stdout
    counts = _counts(stdout)
    assert counts["scanned"] == "50"
    assert counts["matched"] == "0"
    assert counts["errors"] == "0"


def test_an_unreadable_file_is_incomplete_not_clean(home, tmp_path):
    """A file the scan cannot open must never read as a pass."""
    blocked = home / "blocked.txt"
    blocked.write_text("hidden")
    blocked.chmod(0o000)
    prune_globs, pattern = _prune_globs_and_pattern()
    try:
        stdout = _run_audit(tmp_path / "home", prune_globs, pattern)
    finally:
        blocked.chmod(0o644)

    assert "AUDIT=INCOMPLETE" in stdout
    assert int(_counts(stdout)["errors"]) >= 1


def test_the_default_prune_glob_covers_the_whole_of_flatpak():
    """Pins the correction on #644: the first prune list named only
    `repo/objects`, which Flatpak also hard-links into `runtime/` and `app/`,
    so it did not shorten the scan. The default must skip the whole of
    `.local/share/flatpak`, not a subdirectory of it."""
    prune_globs, _ = _prune_globs_and_pattern()
    assert prune_globs == ["/home/*/.local/share/flatpak"]

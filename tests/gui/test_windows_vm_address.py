"""The Windows VM is at 10.77.0.11, and no tracked file names its old address.

The VM moved to the sandbox network. A command copied out of a document or a
script comment that still names the old address fails with a timeout that says
nothing about why, so the old address must not appear anywhere in the
repository.
"""

import pathlib
import subprocess

from tools.gui import winwish

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Built from parts so this file does not contain the address it forbids.
OLD = ".".join(["192", "168", "123", "50"])
NEW = "10.77.0.11"


def _tracked_text():
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                            capture_output=True).stdout.split(b"\0")
    for name in filter(None, (n.decode() for n in listed)):
        path = ROOT / name
        try:
            yield name, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def test_no_tracked_file_names_the_old_address():
    found = [name for name, text in _tracked_text() if OLD in text]
    assert not found, f"{OLD} is still cited in: {', '.join(found)}"


def test_the_guest_the_tools_connect_to_is_the_new_address():
    assert winwish.GUEST == f"donald@{NEW}"

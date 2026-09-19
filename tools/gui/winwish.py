#!/usr/bin/env python3
"""Run Wish in the Windows 11 VM on this machine, so a person can look at the
real window at Windows' own font size.

Every measurement of the editor window's width in `#474 (Raising the UI font
grows the window's minimum width with an ordinary party open, which is the
defect #41 removed for the widest one)` and `#504 (The editor window's
smallest width grew about 266 pixels overnight and no test noticed, because
the guard pins the relationship rather than the number)` was taken on Linux
with the offscreen plugin, using a `+6pt` font as a stand-in for Windows. A proxy is not something a person can judge an interface from, and
this is what removes the proxy.

The VM, its lease and its `winvm` control surface are `docs/143-winuae-debugger.md`
and `jellyfin-stack/ansible/README-windows-vm.md`. This tool drives three
scripts inside the guest:

    tools/gui/winwishsetup.ps1     install Python and PyQt6, unpack the repository
    tools/gui/winwishtask.ps1      run things in the guest's session 1
    tools/gui/winwishmeasure.py    the minimum-width measurement
    tools/gui/winwishrun.py        the visible window

Typical run, from the repository root:

    tools/gui/winwish.py setup            # takes the lease, installs, unpacks
    tools/gui/winwish.py measure          # the numbers, on the Windows style
    tools/gui/winwish.py start            # leaves the window up on the guest
    virt-viewer --connect qemu:///system win11    # a person looks at it
    tools/gui/winwish.py stop
    winvm release <tag>

**The lease is not dropped here.** `winvm release` shuts the VM down when the
last lease goes, and the whole point of `start` is that the window is still
there when somebody connects. Say which tag you hold and drop it yourself.

**Nothing here touches the Amiga lane.** `C:\\Amiga`, its configs and its
`winuae-*` scheduled tasks are how this project drives the Amiga game; every
file this tool writes is under `C:\\Wish` and every task it registers is
`wish-*`.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile

WINVM = "/usr/local/bin/winvm"
GUEST = "donald@10.77.0.11"
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: Excluded from the archive sent to the guest: the virtualenv and the build
#: outputs are the wrong platform's, and `.git` is not needed to run from
#: source.
SKIP = {".git", ".venv", "build", "dist", "__pycache__",
        ".pytest_cache", ".ruff_cache"}

#: PowerShell on this guest refuses a script otherwise: every scope of the
#: execution policy is Undefined, which on Windows 11 client means Restricted.
PS = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    # SSH_ASKPASS_REQUIRE: with no tty and DISPLAY set, OpenSSH runs
    # SSH_ASKPASS when authentication falls through, and on this desktop that
    # draws a KDE credential dialog in front of whoever is sitting there.
    env = dict(os.environ, SSH_ASKPASS_REQUIRE="never")
    print("$", " ".join(args), file=sys.stderr)
    return subprocess.run(args, env=env, **kw)


def _ssh(command: str) -> int:
    return _run([WINVM, "ssh", command]).returncode


def _scp(local: pathlib.Path, remote: str) -> int:
    return _run([WINVM, "scp", str(local), f"{GUEST}:{remote}"]).returncode


def _archive(out: pathlib.Path) -> pathlib.Path:
    """The working tree as it stands, uncommitted changes and all -- the point
    is to look at what is here now, not at what is on `main`."""
    def keep(info: tarfile.TarInfo):
        parts = pathlib.PurePosixPath(info.name).parts
        if any(p in SKIP for p in parts) or info.name.endswith(".pyc"):
            return None
        return info

    with tarfile.open(out, "w:gz") as tar:
        tar.add(ROOT, arcname=".", filter=keep)
    print(f"archive: {out} ({out.stat().st_size // 1024} KiB)", file=sys.stderr)
    return out


def setup() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp())
    archive = _archive(tmp / "wish-tree.tar.gz")
    for local, remote in ((archive, "C:/Wish/wish-tree.tar.gz"),
                          (ROOT / "tools/gui/winwishsetup.ps1", "C:/Wish/winwishsetup.ps1"),
                          (ROOT / "tools/gui/winwishtask.ps1", "C:/Wish/winwishtask.ps1"),
                          (ROOT / "tools/gui/winwishmeasure.py", "C:/Wish/winwishmeasure.py"),
                          (ROOT / "tools/gui/winwishrun.py", "C:/Wish/winwishrun.py")):
        # C:\Wish has to exist before the first scp into it.
        if remote.endswith("wish-tree.tar.gz"):
            _ssh("powershell -NoProfile -Command "
                 "\"New-Item -ItemType Directory -Force -Path C:\\Wish | Out-Null\"")
        if _scp(local, remote):
            return 1
    return _ssh(" ".join(PS + [r"C:\Wish\winwishsetup.ps1"]))


def guest_action(action: str) -> int:
    """`winwishtask.ps1`'s four actions, each of which needs the guest's own
    session 1 -- see that file for why session 0 will not do."""
    return _ssh(" ".join(PS + [r"C:\Wish\winwishtask.ps1", "-Action", action]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action",
                        choices=("setup", "measure", "start", "stop", "status"),
                        help="setup installs and unpacks; the rest run in the "
                             "guest's own session 1")
    got = parser.parse_args(argv)
    if got.action == "setup":
        return setup()
    return guest_action(got.action)


if __name__ == "__main__":
    raise SystemExit(main())

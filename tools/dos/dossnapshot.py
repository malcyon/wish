#!/usr/bin/env python3
"""Machine snapshots for a DOS run: DOSBox-X save states, taken and restored by name.

`SnapshotSession` is `dosboxx.XSession` with three methods matching the C64
`Session`'s: `snapshot(name)`, `restore(name)` and `discard_snapshot(name)`.
A DOS run that may meet an encounter while it walks or rests snapshots before
the leg and restores instead of fighting.

**DOSBox-X only.**  DOSBox 0.74-3 has no save-state code at all, so a run on
`dosbox.Session` cannot be rolled back; it boots this class instead.

The mechanism is DOSBox-X's own save state, reached through its keyboard
mapper because there is no socket, command file or debugger command for it:

* **Host+S saves and Host+L loads** the current slot.  On Linux the host key
  is F12, so the keys are `F12+s` and `F12+l`.  The game sees the F12 press
  (it is bound to the guest's F12 as well as to the host modifier) and never
  sees the `s` or `l`.
* The slot is always slot 1, written to `<slot dir>/save/1.sav` -- DOSBox-X
  puts `save/` beside the `captures` directory.  `snapshot` moves that file to
  `<snapshot_dir>/<name>.sav`; `restore` copies it back and presses Host+L.
* `saveremark=false` is required: without it Host+S opens a text-input dialog
  and the emulator waits on it.  `forceloadstate=true` stops a load from
  asking about a different running program name.  `stage()` adds both.
* Completion is read from the debugger log, which DOSBox-X's `LOG_MSG` writes
  to: `Saved. (Slot 1)` and `Loaded. (Slot 1)`.

**The staged `SAVE` folder is not in the state.**  The C: drive is a mounted
host directory, and a save state holds memory, CPU, devices and the DOS
kernel's file tables but not the files.  A game save made between a snapshot
and its restore stays on disk while memory goes back, exactly as the C64 and
WinUAE disk images behave.  `restore` returns the `SAVE` files that changed
since the snapshot, so a run that saved in between can tell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tools.dos import dosbox, dosboxx  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: DOSBox-X's mapper events `savestate` and `loadstate`, as X keysyms.
SAVE_KEY = "F12+s"
LOAD_KEY = "F12+l"

#: The slot DOSBox-X saves to and loads from: the config's `saveslot` default.
STATE_SLOT = 1

#: What `stage()` adds to the `[dosbox]` section.
CONFIG_LINES = ("saveremark=false", "forceloadstate=true")

#: The log lines a save or load ends with, success first.
RE_SAVED = re.compile(r"Saved\. \(Slot (\d+)\)")
RE_LOADED = re.compile(r"Loaded\. \(Slot (\d+)\)")
RE_FAILED = re.compile(
    r"(No saved slot[^\n]*|Aborted\.[^\n]*|Save state corrupted[^\n]*"
    r"|Stopped\.[^\n]*)")

SNAPSHOT_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class SnapshotFailed(RuntimeError):
    """DOSBox-X did not write or did not load the state."""


def add_config(conf: str) -> str:
    """`conf` with `CONFIG_LINES` added to its `[dosbox]` section."""
    head = "[dosbox]\n"
    if head not in conf:
        raise ValueError("the config has no [dosbox] section")
    missing = [line for line in CONFIG_LINES if line not in conf]
    if not missing:
        return conf
    return conf.replace(head, head + "".join(f"{line}\n" for line in missing), 1)


def folder_digests(folder: Path) -> dict[str, str]:
    """Each file in `folder` (not recursive) by name, to its SHA-1."""
    if not folder.is_dir():
        return {}
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest()
            for p in sorted(folder.iterdir()) if p.is_file()}


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """The names added, removed or rewritten between two `folder_digests`."""
    return sorted(n for n in before.keys() | after.keys()
                  if before.get(n) != after.get(n))


class SnapshotSession(dosboxx.XSession):
    """A DOSBox-X session whose whole machine can be saved and put back by name."""

    #: Seconds a save or a load may take before it is called failed.
    STATE_TIMEOUT = 60.0

    def __init__(self, *args, snapshot_dir: Path | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else scratch.cache_dir(
            "dos", "snapshots", f"x{self.slot.n}")

    def stage(self, fresh: bool = True) -> None:
        super().stage(fresh=fresh)
        conf = self.dir / "dosbox.conf"
        conf.write_text(add_config(conf.read_text()))

    @property
    def state_file(self) -> Path:
        """Where DOSBox-X writes and reads slot `STATE_SLOT`."""
        return self.dir / "save" / f"{STATE_SLOT}.sav"

    def snapshot_path(self, name: str) -> Path:
        if not SNAPSHOT_NAME.match(name):
            raise ValueError(f"a snapshot name is letters, digits, - and _: {name!r}")
        return self.snapshot_dir / f"{name}.sav"

    def _saves_record(self, name: str) -> Path:
        """The sidecar holding the `SAVE` folder's digests at the snapshot."""
        return self.snapshot_dir / f"{name}.saves.json"

    def _press_for(self, key: str, done: re.Pattern, what: str) -> None:
        at = self.mark()
        self.key(key)
        deadline = time.time() + self.STATE_TIMEOUT
        while time.time() < deadline:
            text = self.log_text()[at:]
            bad = RE_FAILED.search(text)
            if bad:
                raise SnapshotFailed(f"{what}: {bad.group(1)}")
            good = done.search(text)
            if good and int(good.group(1)) == STATE_SLOT:
                return
            time.sleep(0.15)
        raise SnapshotFailed(f"{what}: no log line within {self.STATE_TIMEOUT:.0f} s")

    def snapshot(self, name: str) -> Path:
        """Save the whole machine under `name` and return the file.

        The machine runs on after the file is written.
        """
        path = self.snapshot_path(name)
        self.state_file.unlink(missing_ok=True)
        self._press_for(SAVE_KEY, RE_SAVED, f"snapshot {name}")
        if not zipfile.is_zipfile(self.state_file):
            raise SnapshotFailed(f"snapshot {name}: {self.state_file} is not a complete state")
        scratch.ensure(self.snapshot_dir)
        shutil.move(str(self.state_file), path)
        self._saves_record(name).write_text(
            json.dumps(folder_digests(self.save_dir), indent=1))
        return path

    def restore(self, name: str) -> list[str]:
        """Put the machine back as `snapshot(name)` left it.

        Returns the `SAVE` files added, removed or rewritten since the
        snapshot; the restore does not put those back.  Raises
        `FileNotFoundError` for a name never saved and `SnapshotFailed` when
        DOSBox-X does not load it.  The machine runs on from the snapshot's
        instant when this returns.
        """
        path = self.snapshot_path(name)
        if not path.is_file():
            raise FileNotFoundError(f"no snapshot {name!r} at {path}")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, self.state_file)
        self._press_for(LOAD_KEY, RE_LOADED, f"restore {name}")
        try:
            before = json.loads(self._saves_record(name).read_text())
        except (OSError, ValueError):
            before = {}
        return changed_files(before, folder_digests(self.save_dir))

    def discard_snapshot(self, name: str) -> None:
        """Delete a snapshot and its record of the `SAVE` folder."""
        for p in (self.snapshot_path(name), self._saves_record(name)):
            p.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# The live control
# --------------------------------------------------------------------------

def _place(save: bytes) -> dict:
    from goldbox import dos_savegame
    return {"area": dosbox.current_area(save),
            "square": list(dosbox.position(save)),
            "clock": list(dos_savegame.clock(save))}


def control(letter: str = "J", out: Path | None = None) -> dict:
    """Snapshot, walk until the place or clock moves, restore, and save again.

    Saves `B` before the snapshot, `C` after the walk and `D` after the
    restore; `D` must match `B`, and `C` must still be on disk.  A second
    leg saves `E`, restores the same snapshot again and saves `F`, which must
    match `B` too.
    """
    out = scratch.ensure(out or scratch.cache_dir("wish264-dos"))
    game = dosbox.find_game("POOLRAD")
    result: dict = {"game": str(game), "loaded": letter}
    with dosboxx.claim("dossnapshot control") as slot:
        with SnapshotSession(slot, game, snapshot_dir=out / "snapshots") as s:
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(letter)
            before = por.save_game("B")
            result["before"] = _place(before)
            shutil.copy(s.shot("before"), out / "before.png")

            t = time.time()
            result["snapshot_file"] = str(s.snapshot("control"))
            result["snapshot_seconds"] = round(time.time() - t, 2)
            result["snapshot_bytes"] = Path(result["snapshot_file"]).stat().st_size

            moves = []
            after = before
            for key in ("Up", "Right", "Up", "Right", "Up"):
                moves.append([key, por.move(key)])
                if key == "Up":
                    after = por.save_game("C")
                    if _place(after) != result["before"]:
                        break
            result["moves"] = moves
            result["after"] = _place(after)
            shutil.copy(s.shot("after"), out / "after.png")

            t = time.time()
            result["changed_since_snapshot"] = s.restore("control")
            result["restore_seconds"] = round(time.time() - t, 2)
            s.settle()
            shutil.copy(s.shot("restored"), out / "restored.png")

            c_file = s.save_file("C")
            result["savgamc_kept"] = c_file.is_file() and c_file.read_bytes() == after
            restored = por.save_game("D")
            result["restored"] = _place(restored)
            result["restored_equals_before"] = result["restored"] == result["before"]
            result["after_differs"] = result["after"] != result["before"]

            # A retry restores the same snapshot again after a second leg.
            result["second_move"] = por.move("Up")
            result["second_after"] = _place(por.save_game("E"))
            result["second_changed"] = s.restore("control")
            s.settle()
            result["second_restored"] = _place(por.save_game("F"))
            result["second_restored_equals_before"] = (
                result["second_restored"] == result["before"])
            s.discard_snapshot("control")
            shutil.copy(s.log, out / "dbg.log")
            for n in "BCDEF":
                shutil.copy(s.save_file(n), out / f"SAVGAM{n}.DAT")
    (out / "control.json").write_text(json.dumps(result, indent=1))
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("control",),
                    help="boot Pool of Radiance and prove a snapshot restores")
    ap.add_argument("--slot", default="J", help="the save letter to load")
    ap.add_argument("--out", type=Path, help="evidence directory "
                    "(default ~/.cache/wish/wish264-dos)")
    args = ap.parse_args(argv)
    result = control(args.slot, args.out)
    print(json.dumps(result, indent=1))
    ok = (result.get("restored_equals_before") and result.get("after_differs")
          and result.get("second_restored_equals_before"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

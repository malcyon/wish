"""#543: the resave has to run after the walk, not before it.

`tools/c64/savecheck.py`'s `run()` used to call `sess.save_game()` before its
`for move in args.walk` loop, so a combined `--walk X --resave Y` invocation
wrote the party back as it stood on arrival -- before any of the walk's own
moves reached the game.  None of this needs an emulator: a fake session
records the order `walk_one`/`save_game` are actually called in, extending
`tests/c64/test_savecheck_log.py`'s `FakeS`/`FakeSession` pattern with a session
that gets past arrival.
"""

import json
import pathlib

from conftest import load_tools_module

savecheck = load_tools_module("savecheck")

#: The real `tools.c64.session.Status`, captured before any test monkeypatches
#: `savecheck.S` to a fake.  It is a plain `NamedTuple` and `run()` calls
#: `.where()` and `.outdoors` on whatever `sess.status()` hands back.
Status = savecheck.S.Status


class FakeKeyboard:
    def screenshot(self, path: str) -> bool:
        return True

    def key(self, name: str) -> None:
        pass


class FakeScreen:
    """Row 24 always reads as the world bar, so `answer_bars` returns
    `"world"` on its very first poll and the run never sleeps."""

    BAR = "   MOVE   VIEW   CAST   AREA   ENCAMP   SEARCH   LOOK   "

    def row(self, n: int) -> str:
        return self.BAR if n == 24 else ""

    def rows(self) -> list[str]:
        return [self.row(n) for n in range(25)]

    def text(self) -> str:
        return "\n".join(self.rows())


class FakeMon:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, addr: int, length: int) -> bytes:
        return b"\0" * length


class FakeSession:
    """Gets `run()` past arrival and records the order it is driven in.

    `combat_after` is the number of `walk_one` calls after which
    `in_combat()` starts reporting True -- `None` means never.
    """

    def __init__(self, disk, slot=None, calls=None, combat_after=None,
                 save_disk=None):
        self.kbd = FakeKeyboard()
        self.outdoor_boat = None
        self.calls = calls if calls is not None else []
        self.combat_after = combat_after
        self.walks = 0
        self.save_disk = str(save_disk) if save_disk else str(disk)

    def boot(self) -> bool:
        return True

    def load_save(self) -> bool:
        return True

    def screen(self):
        return FakeScreen()

    def select_row(self, name: str) -> bool:
        return True

    def handle_prompt(self, s=None) -> bool:
        return False

    def settle(self, seconds: float = 0) -> None:
        pass

    def status(self):
        return Status(3, 0, 0, 4)

    def mon(self, n: int = 5):
        return FakeMon()

    def square(self):
        return (0, 4)

    def in_combat(self) -> bool:
        return self.combat_after is not None and self.walks >= self.combat_after

    def walk_one(self, move: str) -> bool:
        self.walks += 1
        self.calls.append(f"walk {move}")
        return True

    def save_game(self) -> bool:
        self.calls.append("save")
        return True

    def close(self) -> None:
        pass


class FakeSlot:
    def __init__(self, d: pathlib.Path):
        self.n = 9
        self.display = ":99"
        self.dir = str(d)

    def teardown(self) -> None:
        pass

    def release(self) -> None:
        pass


def entries(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def drive(tmp_path, monkeypatch, walk="", resave=True, combat_after=None):
    """Run `savecheck.main` far enough to exercise the resave/walk order.

    Returns `(rc, calls, log_path)`, where `calls` is the shared list of
    `"walk <move>"`/`"save"` strings in the order the fake session was
    actually driven.
    """
    here = tmp_path / "slot"
    here.mkdir()
    slot = FakeSlot(here)
    disk = tmp_path / "PORSAVEE.D64"
    disk.write_bytes(b"\0" * 16)
    out = tmp_path / "run.jsonl"
    resave_path = tmp_path / "RESAVE.D64"
    calls: list[str] = []

    class FakeS:
        Session = staticmethod(
            lambda d, slot=None: FakeSession(
                d, slot, calls=calls, combat_after=combat_after,
                save_disk=here / "SIDE0.D64"))

        @staticmethod
        def claim_slot(want=None, note=""):
            return slot

        @staticmethod
        def stage_disks(slot, disks, save=""):
            return str(here / "SIDE1.D64")

        @staticmethod
        def stage_writable(src, dest):
            return str(dest)

        @staticmethod
        def copy_closed_disk(src, dest):
            pathlib.Path(dest).write_bytes(b"\0" * 16)

    monkeypatch.setattr(savecheck, "S", FakeS)
    argv = ["--disk", str(disk), "--disks", str(tmp_path),
            "--out", str(out), "--walk", walk]
    if resave:
        argv += ["--resave", str(resave_path)]
    rc = savecheck.main(argv)
    return rc, calls, out


def test_the_resave_happens_after_every_walked_move(tmp_path, monkeypatch):
    """The bug: a combined `--walk MI --resave` run used to write the party
    back before either move reached the game.  This is the assertion that
    goes red if the reorder in `tools/c64/savecheck.py` is reverted."""
    rc, calls, out = drive(tmp_path, monkeypatch, walk="MI", resave=True)
    assert rc == 0, calls
    assert calls == ["walk M", "walk I", "save"], calls
    kinds = [e["kind"] for e in entries(out)]
    assert kinds.count("walk") == 2 and kinds.count("resave") == 1
    assert kinds.index("walk") < kinds.index("resave"), kinds


def test_resave_with_no_walk_still_resaves_the_arrival(tmp_path, monkeypatch):
    """The arrival-only use `#185` wanted must keep working unchanged: a
    `--resave` with no `--walk` is not the combined case this ticket is
    about, and its behaviour must not move."""
    rc, calls, out = drive(tmp_path, monkeypatch, walk="", resave=True)
    assert rc == 0, calls
    assert calls == ["save"], calls
    resaves = [e for e in entries(out) if e["kind"] == "resave"]
    assert len(resaves) == 1 and resaves[0]["ok"] is True, resaves


def test_a_walk_that_ends_in_combat_skips_the_resave(tmp_path, monkeypatch):
    """`ENCAMP` is not on the combat bar, so a walk that lands the party in
    a fight must not spend `select_bar`'s timeout hunting for it."""
    rc, calls, out = drive(tmp_path, monkeypatch, walk="MI", resave=True,
                            combat_after=1)
    assert rc == 0, calls
    assert "save" not in calls, calls
    resaves = [e for e in entries(out) if e["kind"] == "resave"]
    assert len(resaves) == 1 and resaves[0]["ok"] is False, resaves
    assert resaves[0]["reason"] == "the walk ended in combat", resaves

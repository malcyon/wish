"""`tools/pool_of_radiance/outdoorwalk.py` reports a world bar that never came.

No emulator: the slot and the session are fakes, and `wait_text` answers the
way `Session.wait_text` does on a timeout, `(None, None)`.
"""

import argparse

import pytest
from conftest import load_tools_module

outdoorwalk = load_tools_module("outdoorwalk")


class FakeSlot:
    n = 1
    display = ":99"
    dir = "."

    def teardown(self):
        pass

    def release(self):
        pass


class FakeSession:
    def __init__(self, *a, **kw):
        pass

    def boot(self):
        return True

    def load_save(self):
        return True

    def select_row(self, label):
        return True

    def wait_text(self, needle, timeout=180.0, interval=0.35):
        return None, None

    def terminate(self):
        pass


def test_a_world_bar_that_never_appears_is_an_error(tmp_path, monkeypatch):
    S = outdoorwalk.S
    monkeypatch.setattr(S, "claim_slot", lambda *a, **kw: FakeSlot())
    monkeypatch.setattr(S, "stage_disks", lambda *a, **kw: "boot")
    monkeypatch.setattr(S, "stage_writable", lambda *a, **kw: None)
    monkeypatch.setattr(S, "Session", FakeSession)
    args = argparse.Namespace(out=str(tmp_path), slot=None, disk="save.d64",
                              disks=str(tmp_path), arrive=0.01, tag="t",
                              moves=[], shots=False, patience=0.0)

    with pytest.raises(RuntimeError, match="No world bar"):
        outdoorwalk.run(args)

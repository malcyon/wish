"""`dualclassagain c64` stages each title's disks with that title's own harness."""

from __future__ import annotations

import argparse
import types

import pytest

from tools.c64 import dualclassagain


@pytest.fixture
def harnesses(monkeypatch, tmp_path):
    """Record which stager and session class `drive` reaches, launching nothing."""
    from tools.c64 import session as por
    from tools.curse_of_the_azure_bonds import curserun
    from tools.secret_of_the_silver_blades import ssbwarp

    slot_dir = tmp_path / "slot"
    slot_dir.mkdir()
    slot = types.SimpleNamespace(n=1, port=0, cmd_port=0, display=0, dir=slot_dir,
                                 teardown=lambda: None)
    reached = []

    def stager(name):
        def stage(slot, disks, save=""):
            reached.append(("stage", name, disks))
            (slot_dir / "SIDE0.D64").write_bytes(b"")
            return "first.d64"
        return stage

    def session(name):
        class Stub:
            def __init__(self, disk, slot=None):
                reached.append(("session", name))

            def boot(self):
                return False
        return Stub

    monkeypatch.setattr(por, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(curserun, "stage", stager("curse"))
    monkeypatch.setattr(ssbwarp, "stage", stager("silver-blades"))
    monkeypatch.setattr(curserun, "CurseSession", session("curse"))
    monkeypatch.setattr(ssbwarp, "SSBSession", session("silver-blades"))
    return reached


@pytest.mark.parametrize("title, harness, names", [
    ("secret-of-the-silver-blades", "silver-blades", "SILVER-{}.D64"),
    ("curse-of-the-azure-bonds", "curse", "CURSE_{}.D64"),
])
def test_drive_stages_the_title_with_its_own_harness(
        harnesses, tmp_path, title, harness, names):
    disks = tmp_path / "disks"
    disks.mkdir()
    for n in range(1, 7):
        (disks / names.format(n)).write_bytes(b"")
    args = argparse.Namespace(
        title=title, disks=str(disks), out=str(tmp_path / "out"), pool=None,
        save="S.D64", gate_off=False, serve=False)

    assert dualclassagain.drive(args) == 1

    assert harnesses == [("stage", harness, str(disks)), ("session", harness)]

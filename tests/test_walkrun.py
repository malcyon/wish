from __future__ import annotations

"""`tools/walkrun.py` claims a pool slot instead of falling back to Donald's
own ports and display (#144, `tools/walkrun.py has no way to use a pool slot,
so it opens a window on Donald's desktop`).

None of this drives VICE. `Session` is replaced with a fake that never
launches anything, and the pool itself is the same isolated, socket-free
fixture `tests/test_instance.py` uses -- a lease is a file and a flock, and a
slot's ports are arithmetic.
"""

import os
import sys
import types
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import instance  # noqa: E402
import walkrun  # noqa: E402

posix = pytest.mark.skipif(instance.fcntl is None, reason="flock is POSIX only")


@pytest.fixture
def ports(monkeypatch):
    """No port ever answers -- see `tests/test_instance.py`'s fixture of the
    same name for why a temporary pool cannot ask the real machine."""
    busy: set[int] = set()
    monkeypatch.setattr(instance, "_listening", lambda port, *a, **kw: port in busy)
    monkeypatch.setattr(instance, "_greets", lambda port, *a, **kw: port in busy)
    return busy


@pytest.fixture
def pool(tmp_path, monkeypatch, ports):
    monkeypatch.setenv("POR_INST", str(tmp_path / "inst"))
    return tmp_path


class FakeSession:
    """Stands in for `session.Session`: records how it was constructed and
    fails the walk at the first step, which is enough to exercise the
    claim/pass-through/release path without an emulator."""

    instances: list["FakeSession"] = []

    def __init__(self, disk=None, display=None, slot=None, fastloader=None):
        self.slot = slot
        self.headless_at_construction = os.environ.get("POR_HEADLESS")
        self.save_disk = None
        self.kbd = types.SimpleNamespace(screenshot=lambda *a, **kw: None)
        self.closed = False
        FakeSession.instances.append(self)

    def log(self, *a, **kw):
        pass

    def boot(self):
        return False  # short-circuits main() into its failure path

    def dump(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def fake_session(monkeypatch):
    FakeSession.instances = []
    monkeypatch.setattr(walkrun, "Session", FakeSession)
    return FakeSession


@pytest.fixture
def args(tmp_path, monkeypatch):
    """A minimal, valid command line: a real (empty) base save and an
    isolated walks directory, so nothing is written under the real
    `work/drive/walks/`."""
    base = tmp_path / "base.d64"
    base.write_bytes(b"\x00")
    monkeypatch.setattr(walkrun, "WALKS", str(tmp_path / "walks"))
    monkeypatch.setattr(
        sys, "argv",
        ["walkrun.py", "--name", "t", "--route", "I", "--base", str(base)],
    )
    return base


# -- the refusal ------------------------------------------------------------


@posix
def test_refuses_when_no_slot_is_available(pool, fake_session, args, monkeypatch):
    """Every slot leased elsewhere: `main()` must refuse, and must never
    construct a `Session` -- that construction is the one place the human's
    ports and display are reachable."""
    held = [instance.claim() for _ in range(instance.SLOTS)]
    try:
        with pytest.raises(instance.PoolFull):
            instance.claim()  # confirms the pool really is exhausted

        rc = walkrun.main()

        assert rc == 1
        assert FakeSession.instances == []
    finally:
        for slot in held:
            slot.release()


@posix
def test_a_bad_slot_request_is_refused_rather_than_substituted(
        pool, fake_session, args, monkeypatch):
    """`instance.claim()` cannot ask for a slot by number -- it always hands
    back the lowest free one.  `--slot 3` while slot 0 is free must refuse
    rather than silently run on slot 0."""
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--slot", "3"])

    rc = walkrun.main()

    assert rc == 1
    assert FakeSession.instances == []
    # refusing released the slot it briefly held, rather than leaking it
    assert instance.status()[0]["state"] == instance.CLEAN


# -- the pass-through ---------------------------------------------------------


@posix
def test_a_claimed_slot_reaches_session_and_sets_por_headless(
        pool, fake_session, args, monkeypatch):
    """A real slot is passed through to `Session`, `POR_HEADLESS` is set
    before it is constructed, and the lease is released once the run ends --
    including a run that fails, which this one does (`FakeSession.boot()`
    returns `False`)."""
    monkeypatch.delenv("POR_HEADLESS", raising=False)

    rc = walkrun.main()

    assert rc == 1  # boot() failed -- this exercises the failure path too
    assert len(FakeSession.instances) == 1
    sess = FakeSession.instances[0]
    assert isinstance(sess.slot, instance.Slot)
    assert sess.headless_at_construction == "1"
    assert sess.closed is True
    assert instance.status()[sess.slot.n]["state"] == instance.CLEAN


@posix
def test_a_free_named_slot_is_honoured(pool, fake_session, args, monkeypatch):
    """`--slot N` succeeds when N really is the lowest free slot."""
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--slot", "0"])

    walkrun.main()

    assert len(FakeSession.instances) == 1
    assert FakeSession.instances[0].slot.n == 0

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

import pytest

from tools import instance, walkrun

posix = pytest.mark.skipif(instance.fcntl is None, reason="flock is POSIX only")

# Shares a group with tests/test_instance.py -- see that file's own note.
pytestmark = pytest.mark.xdist_group(name="emulator-pool")


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
    """An isolated lease directory *and* an off-band `DISPLAY_BASE`.

    Without this, `test_refuses_when_no_slot_is_available` claims every one
    of the real `:10`-`:25` VICE displays to prove the pool can be
    exhausted -- and every agent runs this suite before reporting
    (`#233 (The test suite takes the emulator displays agents need, and
    eight slots is no longer enough)`). 1030 is this file's own band,
    past `tests/test_instance.py`'s 900-945 and the other two harnesses'
    950-1011.
    """
    monkeypatch.setenv("POR_INST", str(tmp_path / "inst"))
    monkeypatch.setattr(instance, "DISPLAY_BASE", 1030)
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
def test_the_named_slot_is_claimed_though_a_lower_one_is_free(
        pool, fake_session, args, monkeypatch):
    """`--slot 3` on an idle pool must reach slot 3 (#174).

    `instance.claim()` is first-free and cannot be asked for a slot by
    number, and walkrun used to claim whatever came back and refuse when it
    was not the one named -- so the ordinary case, a brief that names a slot
    and an empty pool at the start of a night, failed.  It now uses
    `session.claim_slot`, which holds the lower slots until it has the one
    asked for and lets them go again.
    """
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--slot", "3"])

    rc = walkrun.main()

    assert rc == 1                       # FakeSession.boot() fails, as always
    assert len(FakeSession.instances) == 1
    assert FakeSession.instances[0].slot.n == 3
    # The slots held on the way to 3 were let go, not leaked.
    assert [row["state"] for row in instance.status()[:4]] == [instance.CLEAN] * 4


@posix
def test_a_named_slot_somebody_else_holds_is_refused(
        pool, fake_session, args, monkeypatch):
    """Refusing is still right when the named slot is genuinely taken: run
    somewhere else and two agents share one emulator."""
    held = instance.claim()             # slot 0
    mine = instance.claim()             # slot 1
    try:
        monkeypatch.setattr(sys, "argv", [*sys.argv, "--slot", "1"])

        rc = walkrun.main()

        assert rc == 1
        assert FakeSession.instances == []
        # and the slots it held looking for 1 were released again
        assert instance.status()[2]["state"] == instance.CLEAN
    finally:
        mine.release()
        held.release()


# -- the pass-through ---------------------------------------------------------


@posix
def test_a_claimed_slot_reaches_session(
        pool, fake_session, args, monkeypatch):
    """A real slot is passed through to `Session`, and the lease is released
    once the run ends -- including a run that fails, which this one does
    (`FakeSession.boot()` returns `False`).

    `POR_HEADLESS` is no longer walkrun's own responsibility (#147): `Slot.env()`
    defaults it, and walkrun always claims a slot before building a `Session`,
    so `os.environ` is not touched here at all -- see
    `tests/test_instance.py`'s `test_a_claimed_slot_is_headless_by_default` for
    that guarantee.
    """
    monkeypatch.delenv("POR_HEADLESS", raising=False)

    rc = walkrun.main()

    assert rc == 1  # boot() failed -- this exercises the failure path too
    assert len(FakeSession.instances) == 1
    sess = FakeSession.instances[0]
    assert isinstance(sess.slot, instance.Slot)
    assert sess.headless_at_construction is None  # walkrun itself sets nothing
    assert sess.closed is True
    assert instance.status()[sess.slot.n]["state"] == instance.CLEAN


@posix
def test_a_free_named_slot_is_honoured(pool, fake_session, args, monkeypatch):
    """`--slot N` succeeds when N really is the lowest free slot."""
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--slot", "0"])

    walkrun.main()

    assert len(FakeSession.instances) == 1
    assert FakeSession.instances[0].slot.n == 0

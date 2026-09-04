from __future__ import annotations

"""The instance pool: allocation, contention, the reap table, the `vicerc`.

None of it needs VICE.  A lease is a file and a flock, a slot's ports are
arithmetic, and a seeded `vicerc` is a text file -- which is the point of
`docs/123-parallel-sessions.md` §3.5 putting all of that in one module.

`fcntl` is POSIX only, so the tests that take a lock skip on Windows.  The
module still has to *import* there: CI runs the suite on Windows and an
unimportable module fails at collection time.
"""


import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from conftest import load_tools_module

TOOLS = Path(__file__).resolve().parent.parent / "tools"

instance = load_tools_module("instance")

posix = pytest.mark.skipif(instance.fcntl is None, reason="flock is POSIX only")

# Several tests here claim a slot in a fixed, shared display band (`pool`'s
# 900-915) rather than one unique to the test, on the assumption that only
# one test runs at a time. Under `-n auto` that assumption is false unless
# every test in this file lands in the same worker -- so this whole module
# is one `xdist_group`, shared with `tests/test_dosbox.py`,
# `tests/test_dosboxx.py` and `tests/test_walkrun.py`, which claim from the
# same real `/tmp/.wish-x11-<n>.lock` files under their own fixed bands.
pytestmark = pytest.mark.xdist_group(name="emulator-pool")


@pytest.fixture
def ports(monkeypatch):
    """The set of ports the pool should believe are in use. Empty by default.

    `POR_INST` isolates the lease directory, but a slot's ports are arithmetic
    on a global number and cannot be isolated the same way.  So with a human's
    emulator on 6520, `claim()` inside an empty temporary pool declined slot 0
    and handed out slot 1 -- correctly, and every assertion that said `0` went
    red anyway (#45).  A temporary pool has no emulators in it by construction,
    so the probe answers from this set rather than from the machine's sockets,
    and a test that wants a busy port says which.
    """
    busy: set[int] = set()
    monkeypatch.setattr(instance, "_listening", lambda port, *a, **kw: port in busy)
    monkeypatch.setattr(instance, "_greets", lambda port, *a, **kw: port in busy)
    return busy


@pytest.fixture
def pool(tmp_path, monkeypatch, ports):
    """An isolated lease directory *and* an off-band `DISPLAY_BASE`.

    `POR_INST` isolates the leases, but a claim still searches the real
    :10-:25 VICE band for a display unless this moves it -- and every test
    that claims a slot took one of those eight (now sixteen) real displays
    away from whatever agent needed it next (`#233 (The test suite takes the
    emulator displays agents need, and eight slots is no longer enough)`).
    900-915 is this file's own band, reserved for tests that do not
    themselves need a narrower one; a test that does (band exhaustion, a
    subprocess) picks its own base further up and says so, following the
    numbering `#213 (Each display pool walks out of its own band once the
    band is full)`'s own tests started.
    """
    monkeypatch.setenv("POR_INST", str(tmp_path / "inst"))
    monkeypatch.setattr(instance, "DISPLAY_BASE", 900)
    return tmp_path


# -- what a slot is ---------------------------------------------------------


def test_module_imports_without_fcntl():
    """The guard `tools/dosbox.py` was caught by, asserted rather than assumed."""
    assert instance.pool_root().name == "inst"


def test_the_pool_never_allocates_the_human_s_ports():
    """6502 and 6510 are Donald's, and 6600 is `tools/porcmd`'s.

    This is the property that makes "anything on 6502 is a human's game" true,
    and it is worth an assertion because it is one careless base away from
    being false again.
    """
    for n in range(instance.SLOTS):
        ports = {instance.BIN_BASE + n, instance.TEXT_BASE + n, instance.CMD_BASE + n}
        assert not ports & set(instance.RESERVED_PORTS)
        assert f":{instance.DISPLAY_BASE + n}" != instance.RESERVED_DISPLAY


@posix
def test_a_slot_owns_six_things(pool):
    with instance.claim() as slot:
        assert slot.n == 0
        assert (slot.port, slot.text_port, slot.cmd_port) == (6520, 6540, 6560)
        # The display is searched, not computed -- `tools/instance.py`'s
        # `claim` takes the first free `DISPLAY_BASE + i` within the band's
        # own `slots` width, so only its bounds are deterministic (#138).
        # #213 clamped that search to the band it advertises.
        num = int(slot.display.lstrip(":"))
        assert instance.DISPLAY_BASE <= num < instance.DISPLAY_BASE + instance.SLOTS, slot.display
        assert slot.display != instance.RESERVED_DISPLAY, slot.display
        assert slot.dir == Path(os.environ["POR_INST"]) / "0"
        assert slot.vicerc == slot.dir / "vicerc"


@posix
def test_claiming_a_slot_whose_display_is_taken_still_gets_a_usable_one(pool):
    """Pins #138: a display already held by something else must not stop the
    claim, and the display handed back must still be a search result --
    bounded, not `DISPLAY_BASE + n`. The lock is released and closed in
    `finally` so a failing assertion cannot leave `:{DISPLAY_BASE}` wedged for
    whatever else on the machine wants it next.
    """
    import fcntl  # local: unimportable on Windows, and @posix skips there

    held = f":{instance.DISPLAY_BASE}"
    fd = os.open(f"/tmp/.wish-x11-{instance.DISPLAY_BASE}.lock",
                 os.O_RDWR | os.O_CREAT, 0o644)
    ours = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            ours = True
        except BlockingIOError:
            # Somebody already holds it -- a leased slot keeps this exact lock
            # for its whole life. That *is* the condition under test, so run
            # against theirs rather than failing the way #138 itself did.
            pass
        with instance.claim() as slot:
            assert slot.display != held, slot.display
            num = int(slot.display.lstrip(":"))
            assert instance.DISPLAY_BASE <= num < instance.DISPLAY_BASE + instance.SLOTS, slot.display
    finally:
        if ours:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@posix
def test_claim_hands_out_slots_in_order_and_release_frees_them(pool):
    a = instance.claim(game="por")
    b = instance.claim(game="curse")
    assert (a.n, b.n) == (0, 1)
    assert (a.port, b.port) == (6520, 6521)
    assert a.dir != b.dir
    a.release()
    c = instance.claim()
    assert c.n == 0                      # the freed slot, not the next one
    b.release()
    c.release()


@posix
def test_claim_steps_over_a_slot_whose_port_is_in_use(pool, ports):
    """The rule that keeps an agent off a human's emulator, asserted at last.

    It was untested, and its side effect -- every claim moving up a slot -- was
    what made seven tests read as defects whenever the pool was in use (#45).
    """
    ports.add(instance.BIN_BASE)
    with instance.claim() as slot:
        assert slot.n == 1
    assert instance.inspect(0) == instance.ORPHAN


@posix
def test_the_lease_records_who_holds_it(pool):
    with instance.claim(game="curse", note="P46") as slot:
        info = json.loads((slot.dir / "lease").read_text())
        assert info["pid"] == os.getpid()
        assert info["game"] == "curse"
        assert info["note"] == "P46"
        assert info["port"] == slot.port


@posix
def test_the_pool_can_be_full(pool, monkeypatch):
    """Lease exhaustion, not band exhaustion -- `#213 (Each display pool
    walks out of its own band once the band is full)` has the latter, below.
    `DISPLAY_BASE` moves to 920, past this file's own 900-915 default band
    (`pool`'s own docstring), so this never depends on any real display being
    free on a machine other agents are using tonight -- and `SLOTS` narrows
    to 2 to match the two leases actually taken, so the display band this
    claims is exactly as wide as what it needs.
    """
    monkeypatch.setattr(instance, "DISPLAY_BASE", 920)
    monkeypatch.setattr(instance, "SLOTS", 2)
    held = [instance.claim(slots=2) for _ in range(2)]
    try:
        with pytest.raises(instance.PoolFull):
            instance.claim(slots=2)
    finally:
        for slot in held:
            slot.release()


@posix
def test_the_pool_refuses_once_its_display_band_is_full(pool, monkeypatch):
    """#213: the search used to wander past a full band into whatever the next
    pool's numbers happened to be, rather than admitting its own band was
    exhausted -- so a band that is genuinely full must raise `PoolFull`
    naming the band, not hand back a display outside it.

    `DISPLAY_BASE` moves to a base nothing on this machine uses, so filling
    "the whole band" means locking two `/tmp/.wish-x11-<n>.lock` files this
    test owns outright, never a display another agent's pool might want
    tonight. The lease directory has two free slots throughout (`pool`
    isolates it via `POR_INST`), so this is the display search failing, not
    the lease count.

    **`SLOTS` is patched as well as `DISPLAY_BASE`, and that is the point.**
    The band's width is `SLOTS`; `claim`'s own `slots` argument bounds how
    many leases to try and deliberately does not narrow the band, so a caller
    running a smaller worker pool cannot shrink the numbers this module
    advertises.  A two-wide band here needs both.
    """
    import fcntl  # local: unimportable on Windows, and @posix skips there

    monkeypatch.setattr(instance, "DISPLAY_BASE", 925)
    monkeypatch.setattr(instance, "SLOTS", 2)
    held = []
    try:
        for i in range(2):
            fd = os.open(f"/tmp/.wish-x11-{925 + i}.lock", os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(fd)
        with pytest.raises(instance.PoolFull, match=r":925-:926"):
            instance.claim(slots=2)
    finally:
        for fd in held:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


# -- contention between processes ------------------------------------------


#: A fresh process re-imports `instance` and inherits none of `pool`'s
#: monkeypatches, so `DISPLAY_BASE` is set inline here -- 930, past this
#: file's own 900-926 -- or this subprocess would search the real :10-:25
#: VICE band for a display the way every un-patched test used to (#233
#: (The test suite takes the emulator displays agents need, and eight slots
#: is no longer enough)).
HOLDER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {tools!r})
    import instance
    instance._listening = lambda *a, **kw: False   # the `ports` fixture, out here
    instance.DISPLAY_BASE = 930
    slot = instance.claim(note="holder")
    print(slot.n, flush=True)
    time.sleep(120)
""")


def _holder(pool_dir: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER.format(tools=str(TOOLS))],
        env=dict(os.environ, POR_INST=str(pool_dir)),
        stdout=subprocess.PIPE, text=True,
    )
    assert proc.stdout.readline().strip() == "0"
    return proc


@posix
def test_a_second_process_cannot_take_a_held_slot(pool):
    """The claim that the whole pool rests on, from two real processes."""
    proc = _holder(Path(os.environ["POR_INST"]))
    try:
        assert instance.inspect(0) == instance.HELD
        assert instance.reap(0) == instance.HELD     # held is held, however dead
        with instance.claim() as mine:
            assert mine.n == 1                        # stepped over slot 0
    finally:
        proc.kill()
        proc.wait()


@posix
def test_the_kernel_drops_the_lease_when_the_holder_dies(pool):
    """No cleanup script, no timestamp heuristic, no stale-lock policy."""
    proc = _holder(Path(os.environ["POR_INST"]))
    assert instance.inspect(0) == instance.HELD
    proc.kill()
    proc.wait()
    for _ in range(50):                  # the kernel is prompt but not instant
        if instance.inspect(0) == instance.CLEAN:
            break
        time.sleep(0.1)
    assert instance.inspect(0) == instance.CLEAN
    with instance.claim() as slot:
        assert slot.n == 0


# -- the reap table ---------------------------------------------------------


@posix
def test_reap_calls_an_empty_slot_clean(pool):
    assert instance.reap(0) == instance.CLEAN


@posix
def test_reap_kills_the_recorded_pgid_and_nothing_else(pool):
    """Reaping is by pgid out of *that slot's* lease file. Never by name."""
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                              start_new_session=True)
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                 start_new_session=True)
    try:
        assert instance._killpg(os.getpgid(victim.pid), timeout=5)
        assert victim.wait(5) is not None
        assert bystander.poll() is None          # untouched
    finally:
        bystander.kill()
        bystander.wait()
        if victim.poll() is None:
            victim.kill()
            victim.wait()


@posix
def test_killpg_refuses_our_own_group(pool):
    with pytest.raises(ValueError):
        instance._killpg(os.getpgid(0))


@posix
def test_teardown_of_a_slot_that_launched_nothing_is_a_no_op(pool):
    with instance.claim() as slot:
        assert slot.teardown() is False


@posix
def test_status_reports_every_slot(pool):
    with instance.claim() as slot:
        rows = instance.status()
        assert len(rows) == instance.SLOTS
        assert rows[slot.n]["state"] == instance.HELD
        assert rows[slot.n]["pid"] == os.getpid()
        assert rows[slot.n + 1]["state"] == instance.CLEAN


@posix
def test_a_released_slot_names_nobody(pool):
    """#74: `clean` means the slot is nobody's, so the row says nobody.

    The lease JSON is deliberately never cleared -- the flock is the lease --
    so the record on disk is still the last holder's after release.  Reporting
    it is what let an emulator of ours be read as a human's process.
    """
    slot = instance.claim(game="por", note="whoever")
    n = slot.n
    slot.record(pgid=99999)
    slot.release()

    row = instance.status()[n]
    assert row["state"] == instance.CLEAN
    assert (row["pid"], row["pgid"], row["game"], row["note"]) == \
        (None, None, None, None)
    # The record itself is untouched: release does not write to disk.
    assert json.loads((pool / "inst" / str(n) / "lease").read_text())["pid"] \
        == os.getpid()


@posix
def test_an_orphan_keeps_the_pgid_reap_needs_and_drops_the_dead_pid(pool, ports):
    """On `orphan` the group may still be running; the holder is gone."""
    slot = instance.claim(game="por")
    n = slot.n
    slot.record(pgid=99999)
    slot.release()
    ports.add(instance.BIN_BASE + n)          # a healthy VICE nobody owns

    row = instance.status()[n]
    assert row["state"] == instance.ORPHAN
    assert row["pgid"] == 99999
    assert row["game"] == "por"
    assert row["pid"] is None


@posix
def test_the_status_table_prints_a_dash_for_a_slot_nobody_holds(pool):
    """The CLI, not just the dict: a stale number in the pid column is what a
    reader actually sees."""
    instance.claim().release()
    out = _capture_status()
    body = [line for line in out.splitlines()[1:] if line.strip()]
    assert body, out
    for line in body:
        assert " clean " in line
        assert line.split()[-3:] == ["-", "-", "-"], line


def _capture_status(argv: tuple[str, ...] = ("status",)) -> str:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert instance.main(list(argv)) == 0
    return buf.getvalue()


# -- a held slot that is doing nothing --------------------------------------
#
# "held" only ever meant "somebody's".  These pin the further question: is
# that somebody doing anything?  Read-only throughout -- no `_greets`, no
# `_listening`, no lock attempt -- which the last test in this block checks
# directly.


@posix
def test_idle_for_is_none_until_something_besides_the_lease_is_written(pool):
    """A freshly claimed slot holds nothing but its lease file, so there is
    nothing yet to call idle -- `None`, not zero."""
    with instance.claim() as slot:
        assert instance.status()[slot.n]["idle_for"] is None
        (slot.dir / "shot.png").write_bytes(b"x")
        idle = instance.status()[slot.n]["idle_for"]
        assert idle is not None and idle < 2


@posix
def test_idle_for_grows_with_the_newest_file_s_age_and_ignores_the_lease(pool):
    """Backdating the one file besides the lease must move `idle_for`;
    the lease itself must not count, or every `record()` call would reset it
    to zero regardless of whether anything was actually captured."""
    with instance.claim() as slot:
        shot = slot.dir / "shot.png"
        shot.write_bytes(b"x")
        old = time.time() - 900
        os.utime(shot, (old, old))
        slot.record(note="still alive")           # touches the lease file
        idle = instance.status()[slot.n]["idle_for"]
        assert idle is not None and idle >= 899


@posix
def test_held_for_counts_from_the_lease_s_own_claim_time(pool):
    with instance.claim() as slot:
        slot.record(at=time.time() - 500)
        held = instance.status()[slot.n]["held_for"]
        assert held is not None and held >= 499


@posix
def test_idle_for_and_held_for_are_none_off_a_held_row(pool):
    """The state governs which fields mean anything -- same discipline as
    `LEASE_FIELDS` for `pid`/`pgid`/`game`/`note`."""
    instance.claim().release()
    row = instance.status()[0]
    assert row["state"] == instance.CLEAN
    assert row["held_for"] is None
    assert row["idle_for"] is None
    assert row["owner_pgid"] is None
    assert row["shared_pgid"] is False


@posix
def test_two_slots_held_by_one_process_are_flagged_shared(pool):
    """The leak that matters: one process claims twice and releases neither."""
    a = instance.claim()
    b = instance.claim()
    try:
        rows = instance.status()
        assert rows[a.n]["owner_pgid"] is not None
        assert rows[a.n]["owner_pgid"] == rows[b.n]["owner_pgid"]
        assert rows[a.n]["shared_pgid"] is True
        assert rows[b.n]["shared_pgid"] is True
    finally:
        a.release()
        b.release()


@posix
def test_a_slot_held_by_a_different_process_is_not_flagged_shared(pool):
    """A subprocess started with its own session (`start_new_session=True`,
    the same flag `porlaunch.sh` runs under) gets its own process group --
    without it, a plain child shares the parent's, which would make every
    such fork look shared and defeat the point of the check."""
    a = instance.claim()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(f"""
                import sys, time
                sys.path.insert(0, {str(TOOLS)!r})
                import instance
                instance.DISPLAY_BASE = 935
                slot = instance.claim()
                print(slot.n, flush=True)
                time.sleep(60)
            """)],
            env=dict(os.environ, POR_INST=os.environ["POR_INST"]),
            stdout=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        try:
            n = int(proc.stdout.readline().strip())
            rows = instance.status()
            assert rows[a.n]["shared_pgid"] is False
            assert rows[n]["shared_pgid"] is False
        finally:
            proc.kill()
            proc.wait()
    finally:
        a.release()


@posix
def test_status_never_greets_or_listens_on_a_held_slot(pool, monkeypatch):
    """The whole discipline this feature has to respect: no attaching to a
    monitor an agent may be using, no lock taken to see if one is free.

    Patched in only *after* claiming: `claim()` itself legitimately probes
    a port while it is looking for a free slot to hand out, and that is a
    different question from what `status` may do to a slot it is only
    reporting on.
    """
    with instance.claim() as slot:
        (slot.dir / "shot.png").write_bytes(b"x")

        def _refuse(*a, **kw):
            raise AssertionError("status must not probe a held slot's monitor")
        monkeypatch.setattr(instance, "_greets", _refuse)
        monkeypatch.setattr(instance, "_listening", _refuse)
        rows = instance.status()          # must not raise
        assert rows[slot.n]["state"] == instance.HELD


@posix
def test_the_cli_prints_held_and_idle_columns_and_a_shared_pgid_warning(pool):
    a = instance.claim()
    b = instance.claim()
    try:
        import contextlib
        import io
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            assert instance.main(["status"]) == 0
        assert "held" in out.getvalue() and "idle" in out.getvalue()
        assert f"pgid {os.getpgid(0)}" in err.getvalue()
        assert str(a.n) in err.getvalue() and str(b.n) in err.getvalue()
    finally:
        a.release()
        b.release()

# `_lock_holder` and `display_rows` never take a lock to answer -- taking one
# is not a test of it, and the lock lives on the inode rather than the path
# (see `tools/instance.py`'s own section docstring). These tests use plain
# `tmp_path` files rather than the real `/tmp/.wish-x11-<n>.lock` naming
# except where a test needs the CLI's real path, in which case it picks
# numbers -- 1080 upward -- past every other band this suite uses.


@posix
def test_lock_holder_says_nobody_for_a_file_that_does_not_exist(tmp_path):
    assert instance._lock_holder(tmp_path / "nope.lock") is None


@posix
def test_lock_holder_says_nobody_for_a_file_nobody_locked(tmp_path):
    """The leftover the whole feature exists to explain: a file that was
    opened `O_CREAT` and never flocked, which is what a released slot's
    lock file becomes -- and Donald's twenty-seven-of-them-one-in-use
    machine was full of."""
    path = tmp_path / "unlocked.lock"
    path.write_bytes(b"")
    assert instance._lock_holder(path) is None


@posix
def test_lock_holder_matches_the_inode_not_the_path(tmp_path):
    """The property `#233 (The test suite takes the emulator displays
    agents need, and eight slots is no longer enough)` part 3 exists to
    respect: unlinking a path a process still holds locked would leave
    that process holding an orphaned inode while the next claimer's file
    at the same path starts unlocked. A fresh, unlocked file at a path
    whose old inode is still locked must read as free.
    """
    import fcntl

    path = tmp_path / "x.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        old_ino = os.fstat(fd).st_ino
        path.unlink()                        # the path is gone; the lock is not
        path.write_bytes(b"")                # a fresh, unlocked inode at the same path
        assert path.stat().st_ino != old_ino
        assert instance._lock_holder(path) is None
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _needs_proc_locks():
    if not Path("/proc/locks").exists():
        pytest.skip("needs Linux's /proc/locks")


@posix
def test_lock_holder_names_the_pid_that_holds_the_flock_and_takes_none_itself(tmp_path):
    """Read from `/proc/locks`, never by attempting the lock.

    Also the read-only proof: after asking, the file is still locked by the
    subprocess -- a probe that took the lock to test it would have released
    it again by the time this checks, and the answer would look the same
    either way. Only trying to flock it again and watching that fail tells
    the two apart.
    """
    _needs_proc_locks()
    import fcntl

    path = tmp_path / "held.lock"
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl, os, sys, time\n"
         "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)\n"
         "fcntl.flock(fd, fcntl.LOCK_EX)\n"
         "print('locked', flush=True)\n"
         "time.sleep(60)\n",
         str(path)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        assert instance._lock_holder(path) == proc.pid

        fd = os.open(path, os.O_RDWR)
        try:
            with pytest.raises(OSError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
    finally:
        proc.kill()
        proc.wait()


@posix
def test_display_rows_names_all_three_pools(monkeypatch):
    from tools import dosbox, dosboxx

    monkeypatch.setattr(instance, "DISPLAY_BASE", 1080)
    monkeypatch.setattr(instance, "SLOTS", 2)
    monkeypatch.setattr(dosbox, "DISPLAY_BASE", 1085)
    monkeypatch.setattr(dosbox, "SLOTS", 2)
    monkeypatch.setattr(dosboxx, "DISPLAY_BASE", 1090)
    monkeypatch.setattr(dosboxx, "SLOTS", 2)

    rows = instance.display_rows()
    assert [r["display"] for r in rows] == [
        ":1080", ":1081", ":1085", ":1086", ":1090", ":1091",
    ]
    assert [r["pool"] for r in rows] == \
        ["vice", "vice", "dosbox", "dosbox", "dosboxx", "dosboxx"]


@posix
def test_display_rows_tells_a_stale_file_from_a_held_one_and_from_no_file_at_all(
        monkeypatch):
    """The three states a person actually finds in `/tmp`: nothing there,
    a file nobody locked, and a file somebody genuinely holds."""
    _needs_proc_locks()

    from tools import dosbox, dosboxx

    monkeypatch.setattr(instance, "DISPLAY_BASE", 1095)
    monkeypatch.setattr(instance, "SLOTS", 3)
    monkeypatch.setattr(dosbox, "DISPLAY_BASE", 1200)
    monkeypatch.setattr(dosbox, "SLOTS", 1)
    monkeypatch.setattr(dosboxx, "DISPLAY_BASE", 1210)
    monkeypatch.setattr(dosboxx, "SLOTS", 1)

    stale = Path("/tmp/.wish-x11-1096.lock")
    held = Path("/tmp/.wish-x11-1097.lock")
    stale.write_bytes(b"")
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl, os, sys, time\n"
         "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)\n"
         "fcntl.flock(fd, fcntl.LOCK_EX)\n"
         "print('locked', flush=True)\n"
         "time.sleep(60)\n",
         str(held)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        rows = {r["display"]: r for r in instance.display_rows()}

        assert rows[":1095"]["exists"] is False
        assert rows[":1095"]["held"] is False
        assert rows[":1095"]["pid"] is None

        assert rows[":1096"]["exists"] is True
        assert rows[":1096"]["held"] is False
        assert rows[":1096"]["pid"] is None

        assert rows[":1097"]["exists"] is True
        assert rows[":1097"]["held"] is True
        assert rows[":1097"]["pid"] == proc.pid
    finally:
        proc.kill()
        proc.wait()
        stale.unlink(missing_ok=True)
        held.unlink(missing_ok=True)


@posix
def test_status_displays_prints_a_state_and_a_pid_column(monkeypatch):
    """The CLI a person actually reads, not just the dict.

    One real held lock, so both the "somebody has it" row and the "nobody
    has ever touched this number" rows appear in the same table.
    """
    _needs_proc_locks()
    from tools import dosbox, dosboxx

    monkeypatch.setattr(instance, "DISPLAY_BASE", 1220)
    monkeypatch.setattr(instance, "SLOTS", 1)
    monkeypatch.setattr(dosbox, "DISPLAY_BASE", 1225)
    monkeypatch.setattr(dosbox, "SLOTS", 1)
    monkeypatch.setattr(dosboxx, "DISPLAY_BASE", 1230)
    monkeypatch.setattr(dosboxx, "SLOTS", 1)

    held = Path("/tmp/.wish-x11-1220.lock")
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl, os, sys, time\n"
         "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)\n"
         "fcntl.flock(fd, fcntl.LOCK_EX)\n"
         "print('locked', flush=True)\n"
         "time.sleep(60)\n",
         str(held)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        out = _capture_status(("status", "--displays"))
    finally:
        proc.kill()
        proc.wait()
        held.unlink(missing_ok=True)

    body = [line for line in out.splitlines()[1:] if line.strip()]
    assert len(body) == 3
    assert ":1220" in body[0] and "held" in body[0] and str(proc.pid) in body[0]
    assert ":1225" in body[1] and "no file" in body[1] and body[1].rstrip().endswith("-")
    assert ":1230" in body[2] and "no file" in body[2] and body[2].rstrip().endswith("-")


# -- the seeded vicerc ------------------------------------------------------


TEMPLATE = textwrap.dedent("""\
    [Version]
    ConfigVersion=3.10

    [C64SC]
    SaveResourcesOnExit=1
    KernalName="/home/donald/Downloads/jiffydos/JiffyDOS_C64_6.01.bin"
    DosName1541ii="/home/donald/Downloads/jiffydos/JiffyDOS_1541-II_6.00.bin"
    MachineVideoStandard=2
    FliplistName="/mnt/media/roms/c64/Pool of Radiance Disks/Pool of Radiance.vfl"
    MonitorServerAddress="127.0.0.1:6510"
    MonitorServer=1
    BinaryMonitorServerAddress="127.0.0.1:6502"
    BinaryMonitorServer=1
    """)


def _seeded(pool_dir: Path, template_text: str = TEMPLATE, n: int = 3) -> dict[str, str]:
    src = pool_dir / "vicerc.template"
    src.write_text(template_text)
    slot = instance.Slot(n=n, dir=pool_dir / "inst" / str(n), _fd=-1)
    path = instance.seed_vicerc(slot, src)
    out = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("["):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def test_a_seeded_vicerc_keeps_the_jiffydos_paths(pool):
    """`Session.boot()` answers the fastloader prompt `Y` unconditionally.

    Under a stock kernal that answer is wrong and the symptom looks like a
    corrupt disk image, which is why the rc is seeded by *copying* Donald's
    rather than written fresh.  `docs/131-fastloader.md` is measuring whether
    the answer matters at all; until it reports, the copy is what keeps the
    seeded instance identical to the session everything was learned in.
    """
    rc = _seeded(pool)
    assert "JiffyDOS_C64_6.01.bin" in rc["KernalName"]
    assert "JiffyDOS_1541-II_6.00.bin" in rc["DosName1541ii"]
    assert rc["MachineVideoStandard"] == "2"


def test_a_seeded_vicerc_never_writes_settings_back(pool):
    rc = _seeded(pool)
    assert rc["SaveResourcesOnExit"] == "0"


def test_a_seeded_vicerc_points_at_its_own_ports(pool):
    rc = _seeded(pool, n=3)
    assert rc["BinaryMonitorServerAddress"] == '"127.0.0.1:6523"'
    assert rc["MonitorServerAddress"] == '"127.0.0.1:6543"'
    assert rc["BinaryMonitorServer"] == "1"
    assert rc["MonitorServer"] == "1"


def test_a_seeded_vicerc_drops_the_fliplist(pool):
    """The fliplist in the template names the player's own disks, by path."""
    rc = _seeded(pool)
    assert rc["FliplistName"] == '""'
    assert "Pool of Radiance Disks" not in (pool / "inst" / "3" / "vicerc").read_text()


def test_seeding_never_opens_the_template_for_writing(pool):
    src = pool / "vicerc.template"
    _seeded(pool)
    before = src.read_bytes()
    for n in range(3):
        slot = instance.Slot(n=n, dir=pool / "inst" / str(n), _fd=-1)
        instance.seed_vicerc(slot, src)
    assert src.read_bytes() == before


def test_seeding_works_with_no_template_at_all(pool):
    """A machine with no VICE config yet still gets a valid rc."""
    slot = instance.Slot(n=0, dir=pool / "inst" / "0", _fd=-1, _display_num=10)
    path = instance.seed_vicerc(slot, pool / "nothing-here")
    text = path.read_text()
    assert "[C64SC]" in text
    assert "SaveResourcesOnExit=0" in text
    assert 'BinaryMonitorServerAddress="127.0.0.1:6520"' in text


def test_seeding_leaves_other_sections_alone(pool):
    rc = (pool / "vicerc.template")
    _seeded(pool, TEMPLATE + "\n[C128]\nSaveResourcesOnExit=1\n")
    text = (pool / "inst" / "3" / "vicerc").read_text()
    assert "[C128]\nSaveResourcesOnExit=1" in text
    assert rc.read_text().count("SaveResourcesOnExit=1") == 2


# -- disk copies ------------------------------------------------------------


@posix
def test_disks_are_copied_into_the_slot(pool):
    src = pool / "SIDE1.D64"
    src.write_bytes(b"\x00" * 64)
    with instance.claim() as slot:
        copies = instance.copy_disks(slot, [src])
        assert copies == [slot.dir / "SIDE1.D64"]
        copies[0].write_bytes(b"\xff" * 64)      # the game writes to its disks
        assert src.read_bytes() == b"\x00" * 64


# -- the launch environment -------------------------------------------------


@posix
def test_the_slot_env_is_what_porlaunch_reads(pool):
    with instance.claim() as slot:
        env = slot.env()
        assert env["POR_DISPLAY"] == slot.display
        assert env["POR_MONITOR"] == f"127.0.0.1:{slot.port}"
        assert env["POR_VICERC"] == str(slot.vicerc)
        assert f"127.0.0.1:{slot.port}" in env["MONFLAGS"]
        assert f"127.0.0.1:{slot.text_port}" in env["MONFLAGS"]


@posix
def test_a_claimed_slot_is_headless_by_default(pool, monkeypatch):
    """#147: a slot is by definition something an agent claimed, so headless
    is the default -- an agent must not remember to ask for it."""
    monkeypatch.delenv("POR_HEADLESS", raising=False)
    with instance.claim() as slot:
        assert slot.env()["POR_HEADLESS"] == "1"


@posix
def test_a_human_watching_a_run_still_overrides_headless(pool, monkeypatch):
    """A human who exports `POR_HEADLESS=0` to watch a run must still reach
    `porlaunch.sh` with that value: every caller builds the launch environment
    as `dict(os.environ, **slot.env())` (`tools/session.py:281-283`), so
    `slot.env()`'s own value is what wins, and it must not silently overrule
    an explicit `0` sitting in `os.environ`."""
    monkeypatch.setenv("POR_HEADLESS", "0")
    with instance.claim() as slot:
        assert slot.env()["POR_HEADLESS"] == "0"


def _code_lines(path: Path) -> list[str]:
    """Lines the shell will actually run: comments and blanks dropped."""
    return [ln for ln in path.read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def test_porlaunch_disables_sound_in_the_headless_branch_only():
    """#147: Donald can hear a headless emulator through his speakers even
    though it draws no window. `+sound` (VICE's own flag, from `-help`) must
    sit in the `POR_HEADLESS=1` (`Xvfb`) branch, and must not reach the
    `Xephyr` branch a human watching a run still gets sound from."""
    text = (TOOLS / "porlaunch.sh").read_text()
    before_else, _, after_else = text.partition("else\n")
    headless_part = before_else.rpartition("if ")[2]
    visible_part = after_else.partition("\nfi\n")[0]
    assert "+sound" in headless_part
    assert "+sound" not in visible_part


def test_porlaunch_kills_nothing():
    """The single most important change in `docs/123-parallel-sessions.md`.

    The word survives in the comment that explains why the calls are gone;
    what must not survive is a line that runs it.
    """
    assert not [ln for ln in _code_lines(TOOLS / "porlaunch.sh") if "pkill" in ln]
    text = (TOOLS / "porlaunch.sh").read_text()
    assert "--die-with-parent" in text
    assert "-config" in text


def test_session_kills_nothing_by_name():
    """`subprocess.run(["pkill", ...])` -- the four calls §1 item 2 names."""
    assert '"pkill"' not in (TOOLS / "session.py").read_text()


# -- the port override the pool needs ---------------------------------------


def test_por_monitor_moves_the_probe_and_the_connect_together(monkeypatch):
    """`monitor_listening()` used to test 6502 while `Monitor` connected elsewhere.

    Invisible while the two numbers agree, and a real bug the moment a port is
    overridable -- which is now.  Resolved per call rather than at import, so a
    window already running can be pointed at a pooled instance.
    """
    from automap import target
    from automap.vice import Monitor
    monkeypatch.setenv("POR_MONITOR", "10.0.0.9:6523")

    assert (Monitor().host, Monitor().port) == ("10.0.0.9", 6523)
    assert "6523" in target.who_holds_hint()

    seen = {}

    def fake(address, timeout):
        seen["address"] = address
        raise OSError("nothing there")

    monkeypatch.setattr("socket.create_connection", fake)
    assert target.monitor_listening() is False
    assert seen["address"] == ("10.0.0.9", 6523)


def test_por_monitor_defaults_to_the_human_s_port(monkeypatch):
    from automap import vice
    assert vice.monitor_address("") == ("127.0.0.1", 6502)
    assert vice.monitor_address("6523") == ("127.0.0.1", 6523)
    assert vice.monitor_address("host:6523") == ("host", 6523)
    assert vice.monitor_address("nonsense") == ("127.0.0.1", 6502)

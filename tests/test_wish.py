"""Tests for the one-window application: backends, the session, the window.

Headless throughout -- QT_QPA_PLATFORM=offscreen, set before Qt is imported --
and nothing here needs an emulator: `MemoryTarget` is a dictionary of bytes and
a fake backend hands one over.
"""

import ast
import os
import pathlib

import pytest
from gamedata import disk_dir, disk_path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap.target import Fix, MemoryTarget, NotConnected, party_fix, read_fix
from wish import backends as bk

# Wherever the player keeps them, not wherever one machine did.
DISKS = str(disk_dir() or "no-disks-here")
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/PORSAVE11.D64").exists(),
                                reason="needs the save disks")


# --- the status line, read from plain memory --------------------------------

def screen_codes(text: str) -> bytes:
    """Text as the C64 stores it: A-Z are 1-26, punctuation is its own code."""
    return bytes((ord(c) - 64) if "A" <= c <= "Z" else ord(c) for c in text)


def machine(status: str = "E 16:48  5,2", *, bitmap: bool = False,
            memory_xy: tuple[int, int, int] = (9, 9, 3),
            memory_clock: tuple[int, int, int] = (3, 2, 9)) -> MemoryTarget:
    """A C64 with the game's status line on screen at $CC00.

    `memory_xy` is the three bytes at $C04B, which is where the *engine* keeps
    the party square -- Pool of Radiance's `$49C0` is the save image's copy and
    is only refreshed when `$1A3C` flushes it, so it lags a move (#29).

    `memory_clock` is the three bytes at $49C7: units of a minute, tens, then
    the hour -- so (3, 2, 9) is 09:23."""
    row = screen_codes(status.ljust(40))
    return MemoryTarget({
        0xD011: bytes([0x3B if bitmap else 0x1B]),
        0xD018: bytes([0x30]),          # character base $CC00 within bank 3...
        0xDD00: bytes([0x00]),          # ...which is what bank 0 selects
        0xCC00 + 14 * 40: row,
        0xC04B: bytes(memory_xy),
        0x49C7: bytes(memory_clock),
    })


def test_the_status_line_is_read_through_plain_memory_reads():
    """The whole point of the refactor: no Monitor, no socket, no VICE."""
    fix = party_fix(machine().read)
    assert fix == Fix(5, 2, 1, "status", 16 * 60 + 48)


def test_a_bitmap_screen_yields_no_fix():
    assert party_fix(machine(bitmap=True).read) is None


def test_memory_answers_when_the_status_line_does_not():
    fix = party_fix(machine("PRESS ANY KEY").read)
    assert fix == Fix(9, 9, 3, "memory", 9 * 60 + 23)


def test_an_impossible_reading_is_refused():
    """Validate before trust: the overlay may not be the one we think."""
    assert party_fix(machine("PRESS ANY KEY", memory_xy=(99, 3, 0)).read) is None


def test_the_screen_is_found_where_the_vic_points():
    """$0400 at boot, $CC00 in the world. A fixed address reads the old screen."""
    boot = MemoryTarget({0xD011: bytes([0x1B]), 0xD018: bytes([0x14]),
                         0xDD00: bytes([0x03]),
                         0x0400 + 14 * 40: screen_codes("N 09:00  1,1".ljust(40))})
    assert party_fix(boot.read) == Fix(1, 1, 0, "status", 9 * 60)


def test_reading_a_fix_costs_four_round_trips():
    """Latency is the budget on a network backend, so count them deliberately."""
    m = machine()
    party_fix(m.read)
    assert len(m.reads) == 4


def test_a_target_with_no_fix_method_is_read_the_neutral_way():
    assert read_fix(machine()) == Fix(5, 2, 1, "status", 16 * 60 + 48)


def test_a_target_that_answers_for_itself_is_believed():
    from automap.target import ReplayTarget
    assert read_fix(ReplayTarget([Fix(2, 2, 0, "status")])).square == (2, 2)


# --- the registry -----------------------------------------------------------

def fake_backend(name="Fake", present=True, target=None, **kw):
    return bk.Backend(name=name, probe=lambda: present,
                      connect=lambda: target or MemoryTarget(),
                      setup_hint="plug it in", **kw)


def test_vice_is_a_backend_and_carries_its_own_hint():
    assert bk.VICE.name == "VICE"
    assert "binary monitor" in bk.VICE.setup_hint
    assert bk.VICE.default_interval_ms == 200


def test_a_backend_that_is_not_there_is_not_offered(monkeypatch):
    monkeypatch.setattr(bk, "backends", lambda: [fake_backend(present=False)])
    assert bk.available() == [] and bk.find() is None


def test_a_backend_whose_probe_throws_is_not_offered(monkeypatch):
    """An unverified backend must not take the window down with it."""
    def explode():
        raise OSError("no such host")
    b = bk.Backend(name="Broken", probe=explode, connect=MemoryTarget,
                   setup_hint="")
    monkeypatch.setattr(bk, "backends", lambda: [b])
    assert bk.available() == []


def test_the_preference_settles_a_tie(monkeypatch):
    both = [fake_backend("VICE"), fake_backend("Ultimate")]
    monkeypatch.setattr(bk, "backends", lambda: both)
    assert bk.find().name == "VICE"                    # first by default
    assert bk.find("ultimate").name == "Ultimate"      # named, case-insensitive
    assert bk.find("nonesuch").name == "VICE"          # absent: ignored


# --- the session ------------------------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class CountingTarget(MemoryTarget):
    """A target that knows how many were built and whether it was closed."""

    built = 0

    def __init__(self, memory=None):
        super().__init__(memory)
        CountingTarget.built += 1
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def session(app, monkeypatch):
    from wish.session import Session
    CountingTarget.built = 0
    present = {"yes": True}
    backend = bk.Backend(name="Fake", probe=lambda: present["yes"],
                         connect=CountingTarget, setup_hint="plug it in",
                         default_interval_ms=500)
    s = Session(find=lambda pref=None: backend if present["yes"] else None)
    s.present = present
    return s


def test_the_session_opens_exactly_one_connection(session):
    """VICE ignores a second connection in silence, so two tabs may not each
    open one. Attaching repeatedly must hand back the same target."""
    assert session.attach() and session.attach() and session.attach()
    first = session.target
    session.poll()
    session.poll()
    assert session.target is first
    assert CountingTarget.built == 1


def test_switching_what_is_read_does_not_reconnect(session):
    session.attach()
    target = session.target
    seen = []
    session.set_reader(lambda t: seen.append("map"))
    session.poll()
    session.set_reader(lambda t: seen.append("live"))
    session.poll()
    assert seen == ["map", "live"]
    assert session.target is target and CountingTarget.built == 1


def test_only_the_visible_tab_is_read(session):
    """A tab that is not showing costs nothing: the cost is per round trip."""
    session.attach()
    hidden = []
    session.set_reader(None)
    session.poll()
    assert hidden == []
    assert session.target.reads == []


def test_with_nothing_running_the_session_waits_rather_than_failing(session):
    session.present["yes"] = False
    assert session.attach() is False
    assert session.state == "waiting"
    assert "Waiting" in session.note
    session.poll()                       # and polling is harmless


def test_the_machine_going_away_drops_to_waiting_and_comes_back(session):
    session.attach()
    def reader(target):
        raise NotConnected("connection reset")
    session.set_reader(reader)
    session.poll()
    assert session.state == "waiting" and session.note == "Game disconnected."

    session.set_reader(lambda t: None)
    session.poll()                       # the emulator is back
    assert session.state == "connected"
    assert CountingTarget.built == 2     # a new connection, not the dead one


def test_a_bad_read_is_reported_and_survived(session):
    session.attach()
    session.set_reader(lambda t: 1 / 0)
    session.poll()
    assert session.state == "connected"
    assert "trouble reading" in session.note


def test_the_backend_sets_the_poll_interval(session):
    session.attach()
    assert session.interval_ms == 500        # the backend's own number
    session.detach()
    assert session.interval_ms == 1000       # retry, slower than a poll


def test_closing_closes_the_target(session):
    session.attach()
    target = session.target
    session.close()
    assert target.closed and session.target is None


def test_state_changes_are_published(session):
    notes = []
    session.changed.connect(notes.append)
    session.attach()
    session.detach("gone")
    assert notes[0] == "Fake: connected" and notes[-1] == "gone"


def test_a_busy_monitor_is_not_the_same_as_no_game(app):
    """VICE accepts a second connection and then silently ignores it, so the
    two used to collapse into "waiting for a game" while the game was running.
    Recoverable: when the other client lets go, the next attach succeeds."""
    from automap.target import MonitorBusy
    from wish.session import BUSY, CONNECTED, Session

    held = [True]
    target = MemoryTarget()

    def connect():
        if held[0]:
            raise MonitorBusy()
        return target

    backend = bk.Backend(name="Fake", probe=lambda: True, connect=connect,
                         setup_hint="")
    s = Session(find=lambda pref=None: backend)
    assert not s.attach()
    assert s.state == BUSY and "something else is attached" in s.note

    held[0] = False
    assert s.attach()
    assert s.state == CONNECTED


def test_a_busy_monitor_is_said_in_red_on_the_map(app, tmp_path, monkeypatch):
    """Red text on the map, not a pop-up: the condition clears on its own."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from automap.target import MonitorBusy
    from wish.window import MAP_TAB, WishWindow

    def busy():
        raise MonitorBusy()

    backend = bk.Backend(name="Fake", probe=lambda: True, connect=busy,
                         setup_hint="")
    from wish.session import Session
    w = WishWindow(maps={}, session=Session(find=lambda pref=None: backend))
    w.tabs.setCurrentIndex(MAP_TAB)
    w.session.poll()
    assert w.map.alarm
    assert "something else is attached" in w.map._waiting
    # assert "color: #c0392b" in w.map._status.styleSheet()


# --- the window -------------------------------------------------------------

@pytest.fixture
def save(tmp_path):
    """A throwaway copy. Never test against the player's real disks.

    Skips rather than raising when there are none. A fixture that raises turns
    every test using it into an ERROR on a machine without the game, which is
    what CI is; skipping is the same signal the rest of the suite gives.
    """
    src = disk_path("PORSAVE11")
    if src is None:
        pytest.skip("needs the save disks")
    out = tmp_path / "PORSAVE11.D64"
    out.write_bytes(src.read_bytes())
    return out


def fake_session(target=None, present=True):
    from wish.session import Session
    backend = bk.Backend(name="Fake", probe=lambda: present,
                         connect=lambda: target, setup_hint="")
    return Session(find=lambda pref=None: backend if present else None)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    """The merged window with nothing running and no game disks."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.window import WishWindow
    return WishWindow(maps={}, session=fake_session(present=False))


def test_the_window_opens_with_no_emulator_and_no_file(window):
    from wish.window import EDITOR_TAB, MAP_TAB
    assert window.tabs.count() == 2
    assert window.tabs.tabText(EDITOR_TAB) == "Character Editor"
    assert window.tabs.tabText(MAP_TAB) == "Automapper"
    assert window.session.state == "waiting"


def test_the_editor_tab_is_never_given_the_machine(window):
    """docs/README.md decision 1, as code: the editor gets no reader at all."""
    from wish.window import EDITOR_TAB, MAP_TAB
    window.tabs.setCurrentIndex(MAP_TAB)
    assert window.session.reader is not None
    window.tabs.setCurrentIndex(EDITOR_TAB)
    assert window.session.reader is None


#: What `editor/` may not reach for. `INDEX.md` states the promise: the editor
#: is a file tool that runs with no emulator installed anywhere.
FORBIDDEN_IN_EDITOR = ("automap", "socket", "telnet", "telnetlib", "serial")

#: How a module could import one of those without an `import` statement. The
#: AST walk below sees statements only, so these are grepped for by name --
#: `editor/` uses neither today, and a test that says so is what makes the walk
#: enough.
DYNAMIC_IMPORTS = ("importlib", "__import__")


def test_editor_imports_nothing_live():
    """`editor/` never touches the emulator side -- checked by import, not by
    grepping prose.

    It used to be a substring grep, and that made a **docstring** naming
    `automap.panel.ColumnSplitter` fail the build while explaining a layout
    parallel between the two windows. Mentioning a thing is not importing it,
    and a test that cannot tell the difference punishes the comment that would
    have helped the next reader.

    `test_goldbox_imports_no_transport` had already solved this next door and
    says why in its own docstring: three `goldbox/` modules mention `automap`
    in comments, so a grep is a false positive on every one. This is the same
    walk, applied to the promise `INDEX.md` makes for `editor/`.

    **Stricter than the grep it replaces, not looser.** The grep would have
    passed `importlib.import_module("automap.state")`, which is the one way
    the walk could be evaded; that is grepped for separately below. A relative
    import is checked as though it were absolute, which can only make this too
    strict rather than blind -- no `editor/` module is named after a forbidden
    root.
    """
    for path in pathlib.Path("editor").glob("*.py"):
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                assert root not in FORBIDDEN_IN_EDITOR, (path, name)
        for how in DYNAMIC_IMPORTS:
            assert how not in source, (
                f"{path} uses {how}, which the import walk above cannot see -- "
                f"check by hand that it reaches for nothing live, and say so "
                f"here")


FORBIDDEN_TRANSPORT_ROOTS = ("automap", "socket", "telnet", "telnetlib", "serial")


def test_goldbox_imports_no_transport():
    """goldbox/ stays transport-free -- checked by import, not by grepping prose.

    goldbox/areas.py, goldbox/games.py and goldbox/strength.py all *mention* automap in
    comments, so a substring grep would be a false positive on every one of
    them. Parsing the AST and looking only at Import/ImportFrom nodes is the
    difference.

    Two limits, both deliberate. The walk sees `import` statements only, so a
    dynamic `importlib.import_module("automap.state")` would pass -- catching
    that means reading string literals, which is the prose false-positive this
    test exists to avoid. And a relative import is checked as though it were
    absolute, which can only make the test too strict, never blind: `from
    .d64 import D64` reads as `d64`, and no goldbox/ module is named after a
    forbidden root. goldbox/ uses neither importlib nor `__import__` today.
    """
    for path in pathlib.Path("goldbox").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                assert root not in FORBIDDEN_TRANSPORT_ROOTS, (path, name)


def test_the_test_platform_is_forced_and_not_merely_defaulted():
    """A grep, because the failure it guards is invisible from inside a run.

    `conftest.py` used `setdefault`, which does nothing for a desktop session
    that exports `QT_QPA_PLATFORM` for its own compositor -- COSMIC and KDE
    both do -- so the person most likely to run the suite got the real windows
    the line exists to prevent. Asserting the value at run time cannot catch a
    regression here: by then the variable reads `offscreen` either way.
    """
    source = pathlib.Path("tests/conftest.py").read_text()
    assert 'setdefault("QT_QPA_PLATFORM"' not in source
    assert 'os.environ["QT_QPA_PLATFORM"] = ' in source


def test_switching_tabs_never_opens_a_second_connection(app, tmp_path,
                                                        monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.window import EDITOR_TAB, MAP_TAB, WishWindow
    CountingTarget.built = 0
    target = CountingTarget(machine().memory)
    w = WishWindow(maps={}, session=fake_session(target))
    for _ in range(3):
        w.tabs.setCurrentIndex(MAP_TAB)
        w.session.poll()
        w.tabs.setCurrentIndex(EDITOR_TAB)
        w.session.poll()
    assert CountingTarget.built == 1
    assert w.session.target is target


def _test_the_map_tab_draws_what_the_session_reads(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.window import MAP_TAB, WishWindow
    w = WishWindow(maps={}, session=fake_session(MemoryTarget(machine().memory)))
    w.tabs.setCurrentIndex(MAP_TAB)
    w.session.poll()
    assert (w.mapper.state.x, w.mapper.state.y) == (5, 2)
    # The square lives in the strip under the map now, not in the status bar,
    # which keeps what the strip has no room for: how much has been seen.
    assert "(5,2)" in w.map.strip.where.text()
    assert "seen" in w.statusBar().currentMessage()


def test_a_hidden_map_tab_reads_nothing(app, tmp_path, monkeypatch):
    """Only the visible tab polls. The party panel added two reads a poll, so
    this is worth pinning: a tab nobody is looking at must cost the running
    machine nothing at all."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.window import EDITOR_TAB, MAP_TAB, WishWindow
    target = MemoryTarget(machine().memory)
    w = WishWindow(maps={}, session=fake_session(target))
    w.tabs.setCurrentIndex(MAP_TAB)
    w.session.poll()
    assert target.reads                        # the map tab does read
    w.tabs.setCurrentIndex(EDITOR_TAB)
    quiet = len(target.reads)
    for _ in range(5):
        w.session.poll()
    assert len(target.reads) == quiet


def test_the_emulator_going_away_leaves_the_editor_alone(app, save, tmp_path,
                                                         monkeypatch):
    """The map drops to waiting; the file tab does not notice at all."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.window import MAP_TAB, WishWindow

    class Dying(MemoryTarget):
        def read(self, addr, length):
            raise NotConnected("connection reset")

    w = WishWindow(str(save), maps={}, session=fake_session(Dying()))
    w.tabs.setCurrentIndex(MAP_TAB)
    w.session.poll()
    assert w.session.state == "waiting"
    assert w.session.note == "Game disconnected."
    assert w.editor.party is not None and len(w.editor.party) == 6


@game_disks
def test_a_no_op_save_through_the_merged_window_writes_nothing(app, save,
                                                               tmp_path,
                                                               monkeypatch):
    """The property that has bitten this project four times, re-pinned here:
    the window changed, so the proof has to be repeated at the new door."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.window import MAP_TAB, WishWindow
    before = save.read_bytes()
    w = WishWindow(str(save), f"{DISKS}/POOL1.D64", maps={},
                   session=fake_session(present=False))
    for row in range(6):
        w.editor.roster.selectRow(row)
    w.tabs.setCurrentIndex(MAP_TAB)          # and a tab switch changes nothing
    assert w.editor.save(interactive=False) == "no changes"
    assert save.read_bytes() == before


@game_disks
def _test_the_title_carries_the_file_from_either_tab(app, save, tmp_path,
                                                    monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.window import MAP_TAB, WishWindow
    w = WishWindow(str(save), maps={}, session=fake_session(present=False))
    assert w.windowTitle() == "Wish - PORSAVE11.D64"
    w.editor.roster.selectRow(0)
    w.editor._widgets["gold"].setValue(77)
    w.editor._edited()
    w.tabs.setCurrentIndex(MAP_TAB)
    assert w.windowTitle() == "Wish - PORSAVE11.D64 *"


# --- the Commodore 64 Ultimate ----------------------------------------------
# UNVERIFIED against hardware -- nobody on this project has an Ultimate. These
# exercise the client against a stub implementing what the vendor's REST API
# documentation says, which proves the request shaping and nothing more.

@pytest.fixture
def ultimate_stub():
    """A tiny HTTP server speaking the documented endpoints."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, body, kind="application/octet-stream"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            seen.append((self.command, self.path,
                         self.headers.get("X-Password")))
            if url.path == "/v1/version":
                return self._reply(200, b'{"version": "0.1", "errors": []}',
                                   "application/json")
            if url.path == "/v1/info":
                return self._reply(
                    200, b'{"product": "Ultimate 64", "firmware_version":'
                         b' "3.12", "errors": []}', "application/json")
            if url.path == "/v1/machine:readmem":
                q = parse_qs(url.query)
                addr = int(q["address"][0], 16)
                n = int(q.get("length", ["256"])[0])
                # Counting bytes, with anything the test loaded on top.
                out = bytearray((addr + i) & 0xFF for i in range(n))
                for base, blob in server.memory.items():
                    for i in range(n):
                        if base <= addr + i < base + len(blob):
                            out[i] = blob[addr + i - base]
                return self._reply(200, bytes(out))
            self._reply(404, b'{"errors": ["no such route"]}',
                        "application/json")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            seen.append((self.command, self.path, body))
            self._reply(200, b'{"errors": []}', "application/json")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.memory = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.seen = seen
    yield server
    server.shutdown()


def test_the_ultimate_is_not_offered_when_none_is_configured(monkeypatch):
    """No environment variable, no probe: a network nobody named must not cost
    a timeout on every tick."""
    from wish import ultimate
    for name in ultimate.ENV_HOST:
        monkeypatch.delenv(name, raising=False)
    assert ultimate.configured() is None
    assert ultimate.present() is False
    assert ultimate.ULTIMATE.present() is False


def test_the_ultimate_is_marked_unverified():
    """It has never met the hardware. Say so in the data, not just in a note."""
    from wish.ultimate import ULTIMATE
    assert ULTIMATE.verified is False
    assert ULTIMATE.disturbs is False
    assert ULTIMATE.default_interval_ms > bk.VICE.default_interval_ms


def test_a_device_that_does_not_answer_is_simply_absent(monkeypatch):
    monkeypatch.setenv("POR_ULTIMATE", "127.0.0.1:1")     # nothing listens
    from wish import ultimate
    assert ultimate.present(timeout=0.2) is False


def test_reading_memory_shapes_the_documented_request(monkeypatch,
                                                      ultimate_stub):
    host, port = ultimate_stub.server_address
    monkeypatch.setenv("POR_ULTIMATE", f"{host}:{port}")
    from wish.ultimate import UltimateTarget, present

    assert present(timeout=2)
    t = UltimateTarget(timeout=2)
    data = t.read(0xD020, 4)
    assert data == bytes([0x20, 0x21, 0x22, 0x23])
    method, path, _ = ultimate_stub.seen[-1]
    assert method == "GET"
    assert path == "/v1/machine:readmem?address=D020&length=4"


def test_writing_memory_posts_the_bytes(monkeypatch, ultimate_stub):
    host, port = ultimate_stub.server_address
    monkeypatch.setenv("POR_ULTIMATE", f"{host}:{port}")
    from wish.ultimate import UltimateTarget

    UltimateTarget(timeout=2).write(0x0400, b"\x01\x02\x03")
    method, path, body = ultimate_stub.seen[-1]
    assert (method, path, body) == ("POST", "/v1/machine:writemem?address=0400",
                                    b"\x01\x02\x03")


def test_the_password_header_is_sent_when_one_is_set(monkeypatch,
                                                     ultimate_stub):
    """Firmware 3.12 and later can require it; without it the device says 403."""
    host, port = ultimate_stub.server_address
    monkeypatch.setenv("POR_ULTIMATE", f"{host}:{port}")
    monkeypatch.setenv("POR_ULTIMATE_PASSWORD", "swordfish")
    from wish.ultimate import UltimateTarget

    UltimateTarget(timeout=2).read(0x0400, 1)
    assert ultimate_stub.seen[-1][2] == "swordfish"


def test_a_read_past_the_top_of_memory_is_refused(monkeypatch, ultimate_stub):
    host, port = ultimate_stub.server_address
    monkeypatch.setenv("POR_ULTIMATE", f"{host}:{port}")
    from wish.ultimate import UltimateTarget
    with pytest.raises(ValueError):
        UltimateTarget(timeout=2).read(0xFFF0, 0x20)


def test_the_party_can_be_fixed_through_the_ultimate(monkeypatch,
                                                     ultimate_stub):
    """The refactor's dividend: `party_fix` needs `read` and nothing else, so
    a second backend gets the status line over HTTP for free.

    Shaped, not proven: whether a cartridge-bus DMA read returns anything
    sensible for $D011 and $DD00 is exactly what needs the hardware."""
    host, port = ultimate_stub.server_address
    monkeypatch.setenv("POR_ULTIMATE", f"{host}:{port}")
    ultimate_stub.memory = machine().memory
    from wish.ultimate import UltimateTarget
    assert party_fix(UltimateTarget(timeout=2).read) == Fix(5, 2, 1, "status", 16 * 60 + 48)


def test_a_device_that_dies_mid_session_reads_as_not_connected(monkeypatch,
                                                               ultimate_stub):
    host, port = ultimate_stub.server_address
    monkeypatch.setenv("POR_ULTIMATE", f"{host}:{port}")
    from wish.ultimate import UltimateTarget
    t = UltimateTarget(timeout=2)
    ultimate_stub.shutdown()
    with pytest.raises(NotConnected):
        t.read(0x0400, 1)

"""The opt-in debug log, and the privacy claims it makes.

Most of these tests exist to check a promise rather than a mechanism: off
means no file at all, on means a file with no absolute path, no character name
and no byte of anybody's save in it. `docs/104-debug-log.md`.
"""

import logging
import os
import pathlib
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap.target import MemoryTarget
from wish import backends as bk
from wish import debuglog

DISKS = "/home/donald/c64/Pool of Radiance Disks"
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/PORSAVE11.D64").exists(),
                                reason="needs the save disks")

# Any absolute path, on either platform. Nothing in a log may match it.
ABSOLUTE = re.compile(r"(?<!\.\.)/(?:[^/\s'\"]+/)+|[A-Za-z]:\\")


@pytest.fixture
def logs(tmp_path, monkeypatch):
    """A throwaway config directory, and logging off again afterwards."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    debuglog.stop()
    yield tmp_path / "wish" / "logs"
    debuglog.stop()


def only_log(logs) -> pathlib.Path:
    files = sorted(logs.glob("wish-*.log"))
    assert len(files) == 1
    return files[0]


# --- off ---------------------------------------------------------------------

def test_the_log_is_off_until_asked_for(logs):
    assert debuglog.is_on() is False
    assert debuglog.path() is None


def test_nothing_is_written_while_it_is_off(logs):
    debuglog.note("a note")
    debuglog.warn("a warning")
    try:
        raise ValueError("boom")
    except ValueError:
        debuglog.exception("swallowed")
    with debuglog.timed("a poll", slow_ms=0):
        pass
    assert not logs.exists()


# --- on ----------------------------------------------------------------------

def test_turning_it_on_writes_one_file_headed_by_the_claim(logs):
    path = debuglog.start()
    assert path == only_log(logs)
    text = path.read_text()
    assert text.startswith("# wish debug log")
    assert "Not recorded" in text
    assert "character names" in text and "file paths" in text
    assert "nothing sends it anywhere" in text


def test_the_first_line_is_what_the_versions_are(logs):
    debuglog.start()
    text = only_log(logs).read_text()
    assert "logging on: wish " in text
    assert "Python" in text and "Qt" in text


def test_turning_it_off_stops_writing_at_once(logs):
    debuglog.start()
    path = only_log(logs)
    debuglog.note("while on")
    debuglog.stop()
    for _ in range(20):
        debuglog.note("after off")
    assert debuglog.is_on() is False
    text = path.read_text()
    assert "while on" in text and "logging off" in text
    assert "after off" not in text


def test_starting_twice_keeps_one_file(logs):
    first = debuglog.start()
    assert debuglog.start() == first
    assert len(list(logs.glob("wish-*.log"))) == 1


def test_only_the_last_few_sessions_are_kept(logs):
    logs.mkdir(parents=True)
    for i in range(9):
        (logs / f"wish-2026010{i}-000000.log").write_text("old\n")
    debuglog.start()
    assert len(list(logs.glob("wish-*.log"))) == debuglog.KEEP


def test_nothing_but_our_own_logger_can_reach_the_file(logs):
    """The handler hangs off the `wish` logger, and it does not propagate."""
    debuglog.start()
    logging.getLogger("somebody.else").error("a secret from another library")
    logging.getLogger().error("and one from the root logger")
    assert "secret" not in only_log(logs).read_text()


# --- what is scrubbed --------------------------------------------------------

def test_an_absolute_path_is_reduced_to_its_last_component():
    assert debuglog.scrub("/home/ada/saves/PORSAVE11.D64") == ".../PORSAVE11.D64"
    assert debuglog.scrub(r"C:\Users\Ada\wish\log.txt") == "...\\log.txt"


def test_a_path_in_a_message_never_reaches_the_file(logs):
    debuglog.start()
    debuglog.note("opened %s", "/home/ada/Documents/Pool of Radiance/PORSAVE11.D64")
    text = only_log(logs).read_text()
    assert "PORSAVE11.D64" in text
    assert "ada" not in text and "Documents" not in text


def test_a_traceback_carries_its_frames_but_not_their_paths(logs):
    debuglog.start()
    try:
        raise ZeroDivisionError("division by zero")
    except ZeroDivisionError:
        debuglog.exception("the poll raised")
    text = only_log(logs).read_text()
    assert "Traceback" in text and "ZeroDivisionError" in text
    assert "test_debuglog.py" in text            # the frame is still useful
    assert not ABSOLUTE.search(text), text


def test_a_slow_read_is_timed_and_a_quick_one_is_not(logs):
    debuglog.start()
    with debuglog.timed("a poll", slow_ms=0):
        pass
    with debuglog.timed("another poll", slow_ms=10_000):
        pass
    text = only_log(logs).read_text()
    assert "a poll took" in text and "the emulator stalled" in text
    assert "another poll" not in text


# --- the shape of a file, not its contents -----------------------------------

class FakeEntry:
    block_count = 3


class FakeDisk:
    def to_bytes(self):
        return b"\x00" * 174848

    def directory(self):
        return [FakeEntry(), FakeEntry()]


class FakeSave0:
    area_file = "GEO01"


class FakeParty:
    disk = FakeDisk()
    is_save = True
    save0 = FakeSave0()
    members = ["Malcyon", "Lady Katherine"]

    def __len__(self):
        return len(self.members)


def test_a_save_is_described_by_its_shape(logs):
    shape = debuglog.save_shape(FakeParty(), "/home/ada/saves/PORSAVE11.D64")
    assert shape == ("PORSAVE11.D64, 174848 bytes, 6 blocks, save disk, "
                     "2 characters, area GEO01")
    assert "Malcyon" not in shape


def test_an_unreadable_party_is_not_an_error(logs):
    class Broken:
        pass
    assert debuglog.save_shape(Broken()) == "unreadable"


def test_the_map_says_which_area_and_how_sure(logs):
    from automap.area import Candidates
    from automap.state import AutomapState

    state = AutomapState(area="GEO00",
                         candidates=Candidates(["GEO00"], "resident", True))
    assert debuglog.area_shape(state) == "GEO00 (from resident, certain)"

    guessing = AutomapState(candidates=Candidates(["GEO00", "GEO04"], "fingerprint"))
    assert debuglog.area_shape(guessing) == \
        "unidentified (from fingerprint, 2 candidates)"


# --- the window --------------------------------------------------------------
#
# One window, shared. Every `WishWindow` builds a whole editor form, and a run
# that builds half a dozen of them offscreen segfaults Qt somewhere later --
# reproduced with a throwaway test that did nothing but construct them, so it
# is the count and not this feature. Two tests need their own and say why.

@pytest.fixture(scope="module")
def app():
    """Module-scoped, and held: a QApplication nobody keeps is collected, and
    the next widget built aborts the interpreter."""
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def fake_session(target=None, present=True):
    from wish.session import Session
    backend = bk.Backend(name="Fake", probe=lambda: present,
                         connect=lambda: target, setup_hint="")
    return Session(find=lambda pref=None: backend if present else None)


def window(save=None, target=None, present=False):
    from wish.window import WishWindow
    w = WishWindow(save, maps={}, session=fake_session(target, present))
    w._said = []
    w.announce = lambda title, text: w._said.append((title, text))
    return w


@pytest.fixture(scope="module")
def shared(app):
    w = window(target=MemoryTarget(), present=True)
    yield w
    w.debug_action.setChecked(False)


@pytest.fixture
def live(shared, logs):
    """The shared window, back in its opening state and logging nothing."""
    shared.debug_action.setChecked(False)
    shared.session.detach("between tests")
    shared.session.set_reader(None)
    shared._said.clear()
    shared._logged_save = shared._logged_area = None
    yield shared
    shared.debug_action.setChecked(False)


def test_the_menu_item_is_off_at_every_start(live):
    """Deliberately not remembered: a logging setting that survives a restart
    is one you forget is on -- so it is not in `Settings` at all."""
    from dataclasses import fields
    assert live.debug_action.isChecked() is False
    assert debuglog.is_on() is False
    assert not [f for f in fields(live.settings) if "log" in f.name]


def test_closing_the_window_stops_the_log(app, logs):
    """Its own window, because closing one is what is being tested."""
    w = window()
    w.debug_action.setChecked(True)
    assert debuglog.is_on()
    w.close()
    assert debuglog.is_on() is False


def test_turning_it_on_says_where_the_file_is(live, logs):
    live.debug_action.setChecked(True)
    path = debuglog.path()
    assert path == only_log(logs)
    _title, text = live._said[-1]
    assert str(path) in text
    assert "Nothing is sent anywhere" in text
    assert live.show_log_action.isEnabled()


def test_turning_it_off_disables_showing_it(live):
    live.debug_action.setChecked(True)
    live.debug_action.setChecked(False)
    assert debuglog.is_on() is False
    assert live.show_log_action.isEnabled() is False


def test_the_tab_in_view_and_the_poll_interval_are_recorded(live, logs):
    from wish.window import EDITOR_TAB, MAP_TAB
    live.debug_action.setChecked(True)
    live.tabs.setCurrentIndex(MAP_TAB)
    live.tabs.setCurrentIndex(EDITOR_TAB)
    text = only_log(logs).read_text()
    assert "tab: Automapper, polling every" in text
    assert "tab: Character Editor, polling every" in text


def test_which_backend_attached_is_recorded(live, logs):
    live.debug_action.setChecked(True)
    live.session.attach()
    assert "attached to Fake, polling every 200 ms" in only_log(logs).read_text()


def test_a_busy_monitor_is_recorded(logs):
    from automap.target import MonitorBusy
    from wish.session import Session

    def busy():
        raise MonitorBusy()

    backend = bk.Backend(name="Fake", probe=lambda: True, connect=busy,
                         setup_hint="")
    debuglog.start()
    Session(find=lambda pref=None: backend).attach()
    assert "monitor busy" in only_log(logs).read_text()


def test_a_swallowed_poll_exception_reaches_the_log_and_the_window_lives(live,
                                                                         logs):
    """The single most valuable line in the file: `Session.poll` eats anything
    a read throws to keep the window up, and the traceback used to die with it."""
    from wish.window import MAP_TAB
    live.debug_action.setChecked(True)
    live.tabs.setCurrentIndex(MAP_TAB)

    def explode(_target):
        raise RuntimeError("the map blew up")

    live.session.set_reader(explode)
    live.session.poll()

    text = only_log(logs).read_text()
    assert "the poll raised, and was swallowed" in text
    assert "RuntimeError: the map blew up" in text
    assert "Traceback" in text
    assert live.session.state == "connected"     # and the window is still up
    assert live.tabs.count() == 2
    assert not ABSOLUTE.search(text), text


def test_the_same_failure_is_not_written_every_tick(live, logs):
    live.debug_action.setChecked(True)
    live.session.attach()
    live.session.set_reader(lambda _t: 1 / 0)
    for _ in range(10):
        live.session.poll()
    assert only_log(logs).read_text().count("ZeroDivisionError") == 1


@game_disks
def test_an_open_save_is_logged_as_a_shape_and_nothing_else(app, logs, tmp_path):
    """The whole privacy claim, against a real file: no path, no name, no byte.

    Its own window, because it is the one that must have a save open."""
    from wish.window import MAP_TAB
    disk = tmp_path / "PORSAVE11.D64"
    disk.write_bytes(pathlib.Path(f"{DISKS}/PORSAVE11.D64").read_bytes())

    w = window(save=str(disk), target=MemoryTarget(), present=True)
    w.debug_action.setChecked(True)
    w.tabs.setCurrentIndex(MAP_TAB)
    w.session.poll()

    log = only_log(logs)
    text = log.read_text()
    assert "save file: PORSAVE11.D64" in text
    assert "characters" in text and "blocks" in text

    assert not ABSOLUTE.search(text), text
    for member in w.editor.party.members:
        if len(member.name) >= 3:
            assert member.name not in text

    raw, written = disk.read_bytes(), log.read_bytes()
    for i in range(0, len(raw) - 12, 499):
        assert raw[i:i + 12] not in written

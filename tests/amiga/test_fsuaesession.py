"""`tools/amiga/fsuaesession.py`'s lease, launch, keys, screen, disk change and stop, with the pool, the processes and xdotool faked."""

from __future__ import annotations

import argparse
import hashlib
import types

import pytest
from PIL import Image

from tools.amiga import fsuaegdb, fsuaepor, fsuaesession
from tools.amiga.winuaesession import RouteError

SILENT = {"SDL_AUDIODRIVER": "dummy", "ALSOFT_DRIVERS": "null"}


class Clock:
    now = 1000.0

    def __init__(self):
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Slot:
    n, port, display = 3, 6523, ":13"

    def __init__(self, directory):
        self.dir, self.released = directory, False

    def release(self):
        self.released = True


class Proc:
    started: list = []

    def __init__(self, argv, **kw):
        self.argv, self.kw, self.signals, self.done = argv, kw, [], False
        self.pid = 4000 + len(Proc.started)
        Proc.started.append(self)

    def poll(self):
        return 0 if self.done else None

    def wait(self, timeout=None):
        self.done = True
        return 0

    def send_signal(self, sig):
        self.signals.append(sig)
        self.done = True

    def kill(self):
        self.done = True


class Gdb:
    #: How many reads the next transport leaves unanswered, as the server does with a read that
    #: reaches it in the same receive as the `vCont;c`; None leaves every read unanswered.
    unanswered: int | None = 0

    def __init__(self, **kw):
        self.kw, self.reads, self.closed, self.resumed, self.lost = kw, [], False, 0, False
        self._unanswered = Gdb.unanswered

    def resume(self):
        self.resumed += 1

    def read_memory(self, address, length):
        from automap import amiga

        self.reads.append((address, length))
        if self._unanswered is None or self._unanswered > 0:
            if self._unanswered is not None:
                self._unanswered -= 1
            raise amiga.FsuaeError("the emulator sent no reply in 1s")
        return b"\0" * length

    def close(self):
        self.closed = True


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(fsuaesession.time, "monotonic", c.monotonic)
    monkeypatch.setattr(fsuaesession.time, "sleep", c.sleep)
    monkeypatch.setattr(fsuaegdb.time, "sleep", c.sleep)
    return c


@pytest.fixture
def lane(tmp_path, monkeypatch, clock):
    """The faked outside world; `lane.keys` records each key sent and `lane.claimed` each pool claim."""
    slot = Slot(tmp_path / "slot")
    slot.dir.mkdir()
    binary = tmp_path / "fs-uae"
    binary.write_text("")
    kickstart = tmp_path / "kick.rom"
    kickstart.write_text("")
    Proc.started = []
    monkeypatch.setattr(Gdb, "unanswered", 0)
    state = types.SimpleNamespace(slot=slot, keys=[], claimed=[], gdbs=[], shots=[], environ=dict(SILENT),
                                  window=True, binary=binary, key_windows=[])

    def claim(game, note=""):
        state.claimed.append((game, note))
        return slot

    def gdb(**kw):
        state.gdbs.append(Gdb(**kw))
        return state.gdbs[-1]

    from automap import amiga

    monkeypatch.setattr(fsuaesession.instance, "claim", claim)
    monkeypatch.setattr(fsuaesession, "_binary", lambda: binary)
    monkeypatch.setattr(fsuaesession, "_kickstart", lambda: kickstart)
    monkeypatch.setattr(fsuaegdb.subprocess, "Popen", Proc)
    monkeypatch.setattr(amiga, "FsuaeGdb", gdb)
    monkeypatch.setattr(fsuaesession.FsuaeGuest, "_environment", lambda self: dict(state.environ))
    monkeypatch.setattr(fsuaepor, "keys", lambda args: (state.keys.append(args.key[0]),
                                                        state.key_windows.append(args.window)))
    monkeypatch.setattr(fsuaegdb, "window_size", lambda display, window: None)
    monkeypatch.setattr(fsuaepor, "find_windows", lambda display, timeout=None: ["1"] if state.window else [])
    monkeypatch.setattr(fsuaegdb, "press", lambda display, key, settle: state.shots.append(key))
    return state


def _disk(tmp_path, name, content=b"disk"):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _started(tmp_path, lane, *, disks=("one", "two", "three"), mounted=("one", "two"), options=(),
             first_key_after=None):
    guest = fsuaesession.FsuaeGuest(game="amiga-pool", first_key_after=first_key_after)
    guest.claim("wish1-test", 30)
    for key in disks:
        guest.put(_disk(tmp_path, f"{key}.src", key.encode()), guest.remote_path("1", "wish1-test", key), 30)
    guest.start("wish1-test", *(guest.remote_path("1", "wish1-test", k) for k in mounted),
                timeout=30, options=options)
    return guest


def test_claim_leases_a_pool_slot_for_the_title_and_release_frees_it(lane):
    guest = fsuaesession.FsuaeGuest(game="amiga-pool")
    assert guest.claim("wish1-test", 30) == "ok claimed by wish1-test"
    assert lane.claimed == [("amiga-pool", "wish1-test")]
    assert guest.release("wish1-test", 30) == "ok released"
    assert lane.slot.released


def test_a_full_pool_is_a_route_error(lane, monkeypatch):
    def full(game, note=""):
        raise fsuaesession.instance.PoolFull("all 16 instance slots are leased")

    monkeypatch.setattr(fsuaesession.instance, "claim", full)
    with pytest.raises(RouteError, match="no instance slot"):
        fsuaesession.FsuaeGuest().claim("wish1-test", 30)


def test_nothing_is_staged_or_started_before_the_claim(lane, tmp_path):
    guest = fsuaesession.FsuaeGuest()
    with pytest.raises(RouteError, match="put before the slot was claimed"):
        guest.put(_disk(tmp_path, "a.adf"), "a.adf", 30)
    with pytest.raises(RouteError, match="start before the slot was claimed"):
        guest.start("h", timeout=30)


def test_start_mounts_drives_in_order_with_a_third_drive_and_the_spare_in_the_swap_list(lane, tmp_path):
    guest = _started(tmp_path, lane, mounted=("one", "two", "three"), disks=("one", "two", "three", "spare"),
                     options=("nr_floppies=3", "floppy2type=0"))
    emulator = Proc.started[1]
    names = {a.split("=")[0]: a.split("=", 1)[1] for a in emulator.argv if a.startswith("--floppy")}
    assert [names[f"--floppy_drive_{n}"].rsplit("-", 1)[1] for n in range(3)] == ["one.adf", "two.adf", "three.adf"]
    assert names["--floppy_drive_count"] == "3"
    assert [names[f"--floppy_image_{n}"].rsplit("-", 1)[1] for n in range(4)] == [
        "one.adf", "two.adf", "three.adf", "spare.adf"]
    for wanted in ("--floppy_drive_speed=0", "--writable_floppy_images=1", "--joystick_port_1=none",
                   f"--remote_debugger_port={lane.slot.port}"):
        assert wanted in emulator.argv
    # Both processes stay in this process group, so the pool's lease covers them.
    assert emulator.kw["start_new_session"] is False and Proc.started[0].kw["start_new_session"] is False
    assert emulator.kw["env"]["FSEMU_SCREENSHOTS_DIR"] == str(guest.work / "shots")
    assert emulator.kw["env"]["DISPLAY"] == lane.slot.display
    assert lane.gdbs[0].kw == {"port": lane.slot.port, "resume": False}
    assert lane.gdbs[0].resumed == 1
    assert lane.gdbs[0].reads == [(fsuaegdb.VHPOSR, 2)]


def test_start_without_attach_never_connects_the_debugger_and_still_checks_silence(lane, tmp_path):
    guest = fsuaesession.FsuaeGuest(game="amiga-pool")
    guest.claim("wish1-test", 30)
    guest.put(_disk(tmp_path, "one.src"), guest.remote_path("1", "wish1-test", "one"), 30)
    guest.start("wish1-test", guest.remote_path("1", "wish1-test", "one"), timeout=30, attach=False)
    assert lane.gdbs == [] and guest.gdb is None
    guest.stop("wish1-test", 30)
    lane.environ.pop("SDL_AUDIODRIVER")
    other = fsuaesession.FsuaeGuest(game="amiga-pool")
    other.claim("wish1-test", 30)
    other.put(_disk(tmp_path, "one.src"), other.remote_path("1", "wish1-test", "one"), 30)
    with pytest.raises(RouteError):
        other.start("wish1-test", other.remote_path("1", "wish1-test", "one"), timeout=30, attach=False)
    assert lane.gdbs == []


def test_a_key_goes_to_the_largest_of_two_windows(lane, tmp_path, monkeypatch):
    guest = _started(tmp_path, lane)
    monkeypatch.setattr(fsuaepor, "find_windows", lambda display, timeout=None: ["10x10", "main"])
    monkeypatch.setattr(fsuaegdb, "window_size", lambda display, w: (10, 10) if w == "10x10" else (720, 568))
    guest.press("wish1-test", "RET", 60)
    assert lane.key_windows == ["main"]


def test_a_first_read_lost_with_the_continue_is_sent_again_and_the_start_goes_on(lane, tmp_path, monkeypatch):
    monkeypatch.setattr(Gdb, "unanswered", 1)
    guest = _started(tmp_path, lane)
    assert guest.emulator is not None and guest.gdb is lane.gdbs[0]
    assert lane.gdbs[0].resumed == 1
    assert lane.gdbs[0].reads == [(fsuaegdb.VHPOSR, 2)] * 2


def test_a_machine_that_never_answers_after_the_continue_is_taken_down(lane, tmp_path, monkeypatch, clock):
    monkeypatch.setattr(Gdb, "unanswered", None)
    with pytest.raises(RouteError, match="did not answer after it was continued"):
        _started(tmp_path, lane)
    assert lane.gdbs[0].closed and Proc.started[1].done
    assert len(lane.gdbs[0].reads) > 1


def test_an_option_with_no_fs_uae_counterpart_is_a_route_error(lane, tmp_path):
    guest = fsuaesession.FsuaeGuest()
    guest.claim("wish1-test", 30)
    guest.put(_disk(tmp_path, "a"), "a.adf", 30)
    with pytest.raises(RouteError, match="no FS-UAE counterpart"):
        guest.start("wish1-test", "a.adf", timeout=30, options=("gfx_api=directdraw",))
    with pytest.raises(RouteError, match="cannot be left empty"):
        guest.start("wish1-test", None, "a.adf", timeout=30)


def test_an_emulator_that_is_not_silent_is_taken_down_and_blocks_the_start(lane, tmp_path):
    lane.environ.pop("SDL_AUDIODRIVER")
    guest = fsuaesession.FsuaeGuest()
    guest.claim("wish1-test", 30)
    guest.put(_disk(tmp_path, "a"), "a.adf", 30)
    with pytest.raises(RouteError, match="not silent"):
        guest.start("wish1-test", "a.adf", timeout=30)
    assert all(p.signals for p in Proc.started) and lane.gdbs[0].closed


def test_silence_holds_before_a_start_and_reads_the_running_environment_after(lane, tmp_path):
    guest = fsuaesession.FsuaeGuest()
    assert guest.silence() is True
    guest = _started(tmp_path, lane)
    assert guest.silence() is True
    lane.environ["ALSOFT_DRIVERS"] = "pulse"
    assert guest.silence() is False
    assert (guest.work / "environ.txt").read_text() == "SDL_AUDIODRIVER=dummy\nALSOFT_DRIVERS=null\n"


def test_the_first_key_waits_for_the_titles_emulator_age_once(lane, tmp_path, clock):
    guest = _started(tmp_path, lane, first_key_after=48.0)
    clock.now += 10.0
    clock.sleeps.clear()
    assert guest.press("wish1-test", "ret", 60) == "ok RET"
    # The age counts from the launch, so the pause before the first debugger read is part of it.
    waited = [pytest.approx(38.0 - fsuaegdb.CONTINUE_SETTLE)]
    assert clock.sleeps == waited and lane.keys == ["Return"]
    guest.press("wish1-test", "NP8", 60)
    assert clock.sleeps == waited and lane.keys == ["Return", "KP_Up"]


def test_a_first_key_wait_longer_than_the_call_allows_sends_nothing(lane, tmp_path, clock):
    guest = _started(tmp_path, lane, first_key_after=259.0)
    with pytest.raises(RouteError, match="first key needs 259s more"):
        guest.press("wish1-test", "RET", 30)
    assert lane.keys == []


def test_an_unknown_key_is_a_route_error_and_the_key_table_gives_the_keysym(lane, tmp_path):
    guest = _started(tmp_path, lane)
    with pytest.raises(RouteError, match="NOSUCH has no key row"):
        guest.press("wish1-test", "nosuch", 30)
    with pytest.raises(RouteError, match="F11 has no FS-UAE key"):
        guest.press("wish1-test", "F11", 30)
    for key, keysym in (("ESC", "Escape"), ("x", "x"), ("NP2", "KP_Down"), ("SLASH", "slash")):
        guest.press("wish1-test", key, 30)
        assert lane.keys[-1] == keysym


def test_get_waits_for_stop_and_stop_records_each_images_hash_around_the_signal(lane, tmp_path, clock):
    guest = _started(tmp_path, lane)
    one = guest.remote_path("1", "wish1-test", "one")
    with pytest.raises(RouteError, match="still open in a running emulator"):
        guest.get(one, tmp_path / "out.adf", 30)
    # The emulator rewrites a mounted image, as a game save does.
    guest.staged[one].write_bytes(b"saved")
    guest.press("wish1-test", "B", 30)
    clock.sleeps.clear()
    assert guest.stop("wish1-test", 60).endswith(f"changed on disk: {one}")
    assert clock.sleeps[0] == pytest.approx(fsuaesession.SAVE_REACHES_DISK)   # a save needs ten seconds to reach the disk
    emulator, xvfb = Proc.started[1], Proc.started[0]
    assert emulator.signals and xvfb.signals and lane.gdbs[0].closed
    guest.get(one, tmp_path / "out.adf", 30)
    assert (tmp_path / "out.adf").read_bytes() == b"saved"
    record = (guest.work / "adf-sha256.json").read_text()
    assert hashlib.sha256(b"saved").hexdigest() in record and hashlib.sha256(b"one").hexdigest() in record
    with pytest.raises(RouteError, match="was not staged"):
        guest.get("other.adf", tmp_path / "x.adf", 30)


def _log_line(guest, text):
    log = guest.work / "base" / "Cache" / "Logs" / "fs-uae.log.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as handle:
        handle.write(text + "\n")


def test_insert_walks_the_f12_menu_to_the_spare_and_proves_the_change_from_the_log(lane, tmp_path, clock):
    guest = _started(tmp_path, lane, disks=("one", "three", "two"), mounted=("one", "three"))
    two = guest.remote_path("1", "wish1-test", "two")
    real_send = guest._send

    def send(key):
        real_send(key)
        if key == "F12" and lane.keys.count("F12") == 2:
            _log_line(guest, f"gui_disk_image_change drive 0 name {guest.staged[two]}")

    guest._send = send
    receipt = guest.insert("wish1-test", 0, two, 30, hashlib.sha256(b"two").hexdigest())
    # Entry 0 is in DF0, so its row is disabled: Eject, entry 1, entry 2.
    assert lane.keys == ["F12", "Down", "Down", "Down", "Return", "Down", "Down", "Down", "Return", "F12"]
    assert receipt["index"] == 2 and receipt["staged"] == str(guest.staged[two])
    assert receipt["log"] == [f"gui_disk_image_change drive 0 name {guest.staged[two]}"]
    one = guest.remote_path("1", "wish1-test", "one")
    with pytest.raises(RouteError, match="already in DF0"):
        guest.insert("wish1-test", 0, two, 30, hashlib.sha256(b"two").hexdigest())
    lane.keys.clear()

    def send_back(key):
        real_send(key)
        if key == "F12" and lane.keys.count("F12") == 2:
            _log_line(guest, f"gui_disk_image_change drive 0 name {guest.staged[one]}")

    guest._send = send_back
    guest.insert("wish1-test", 0, one, 30, hashlib.sha256(b"one").hexdigest())
    # Entry 2 is in DF0 now and entry 0 sits above it: Eject, entry 0.
    assert lane.keys == ["F12", "Down", "Down", "Down", "Return", "Down", "Down", "Return", "F12"]


@pytest.mark.parametrize(("index", "inserted", "rows"), [(2, 0, 3), (1, 0, 2), (0, 2, 2), (2, 1, 3), (1, 2, 3)])
def test_media_rows_skip_the_inserted_disks_own_entry(index, inserted, rows):
    assert fsuaegdb.media_rows(index, inserted) == rows


def test_insert_with_no_log_line_for_the_image_raises_with_the_receipt(lane, tmp_path, clock):
    guest = _started(tmp_path, lane, disks=("one", "three", "two"), mounted=("one", "three"))
    two = guest.remote_path("1", "wish1-test", "two")
    _log_line(guest, "gui_disk_image_change drive 0 name /somewhere/else.adf")
    with pytest.raises(RouteError, match="shows no change") as caught:
        guest.insert("wish1-test", 0, two, 30, hashlib.sha256(b"two").hexdigest())
    assert caught.value.receipt["index"] == 2


def test_insert_blocks_a_wrong_hash_a_second_drive_and_an_image_that_was_never_staged(lane, tmp_path):
    guest = _started(tmp_path, lane)
    three = guest.remote_path("1", "wish1-test", "three")
    with pytest.raises(RouteError, match="not the manifest's"):
        guest.insert("wish1-test", 0, three, 30, "0" * 64)
    with pytest.raises(RouteError, match="DF0 only"):
        guest.insert("wish1-test", 1, three, 30, hashlib.sha256(b"three").hexdigest())
    with pytest.raises(RouteError, match="was not staged"):
        guest.insert("wish1-test", 0, "nothing.adf", 30, "0" * 64)
    assert lane.keys == []


def _doubled_frame(path, size=(754, 576)):
    """A 377x288 frame doubled, as FS-UAE's own screenshot is."""
    native = Image.new("RGB", (size[0] // 2, size[1] // 2), (17, 34, 51))
    native.putpixel((8, 2), (255, 0, 0))
    native.resize(size, Image.NEAREST).save(path)


def test_grab_asks_for_the_emulators_screenshot_and_cuts_it_to_the_amiga_screen(lane, tmp_path, monkeypatch):
    guest = _started(tmp_path, lane)
    assert guest.last_shot is None

    def alt_s(display, key, settle):
        lane.shots.append(key)
        _doubled_frame(guest.work / "shots" / f"FS-UAE_Full_261004-0000_{len(lane.shots):02d}.png")

    monkeypatch.setattr(fsuaegdb, "press", alt_s)
    raw, cropped = tmp_path / "raw.png", tmp_path / "crop.png"
    assert guest.grab("title", raw, cropped, 10) is True
    assert lane.shots == ["alt+s"]
    assert guest.last_shot == {"source": "fsuae-alt-s", "file": "FS-UAE_Full_261004-0000_01.png"}
    with Image.open(raw) as image:
        assert image.size == (754, 576)
    with Image.open(cropped) as image:
        assert image.size == (720, 568) and image.getpixel((0, 0)) == (255, 0, 0)
        assert image.getpixel((2, 0)) == (17, 34, 51)


def test_grab_is_false_while_there_is_no_window_or_no_frame_yet_and_an_error_after_a_first_frame(
        lane, tmp_path, monkeypatch, clock):
    guest = _started(tmp_path, lane)
    lane.window = False
    assert guest.grab("title", tmp_path / "r.png", tmp_path / "c.png", 10) is False
    assert lane.shots == []
    lane.window = True
    assert guest.grab("title", tmp_path / "r.png", tmp_path / "c.png", 3) is False
    monkeypatch.setattr(fsuaegdb, "press", lambda display, key, settle: _doubled_frame(
        guest.work / "shots" / "FS-UAE_Full_261004-0000_01.png"))
    assert guest.grab("title", tmp_path / "r.png", tmp_path / "c.png", 3) is True
    monkeypatch.setattr(fsuaegdb, "press", lambda display, key, settle: None)
    with pytest.raises(RouteError, match="wrote no screenshot"):
        guest.grab("title", tmp_path / "r.png", tmp_path / "c.png", 3)


def test_grab_after_the_emulator_has_gone_is_an_error_at_once(lane, tmp_path, clock):
    guest = _started(tmp_path, lane)
    guest._take_down()
    with pytest.raises(RouteError, match="no emulator is running to grab failure"):
        guest.capture("failure", tmp_path / "r.png", tmp_path / "c.png", 90)
    assert lane.shots == [] and clock.sleeps.count(fsuaesession.SETTLE_INTERVAL) == 0


def test_shot_copies_the_emulators_own_screenshot_uncut(lane, tmp_path, monkeypatch, clock):
    guest = _started(tmp_path, lane)
    monkeypatch.setattr(fsuaegdb, "press", lambda display, key, settle: _doubled_frame(
        guest.work / "shots" / "FS-UAE_Full_261004-0000_01.png"))
    guest.shot(tmp_path / "leg.png")
    assert guest.last_shot == {"source": "fsuae-alt-s", "file": "FS-UAE_Full_261004-0000_01.png"}
    assert (tmp_path / "leg.png").read_bytes() == (
        guest.work / "shots" / "FS-UAE_Full_261004-0000_01.png").read_bytes()
    monkeypatch.setattr(fsuaegdb, "press", lambda display, key, settle: None)
    with pytest.raises(RouteError, match="wrote no screenshot within 3s"):
        guest.shot(tmp_path / "none.png", 3)
    guest._take_down()
    with pytest.raises(RouteError, match="no emulator is running to shoot"):
        guest.shot(tmp_path / "gone.png")


def test_get_live_waits_for_the_save_then_copies_once_two_reads_agree(lane, tmp_path, monkeypatch, clock):
    guest = _started(tmp_path, lane)
    remote = guest.remote_path("1", "wish1-test", "one")
    staged = guest.staged[remote]
    guest.press("wish1-test", "ret", 30)
    clock.sleeps.clear()
    writes = iter([b"half", b"saved"])
    real_sleep = clock.sleep

    def sleep(seconds):
        real_sleep(seconds)
        staged.write_bytes(next(writes, b"saved"))

    monkeypatch.setattr(fsuaesession.time, "sleep", sleep)
    local = tmp_path / "live.adf"
    assert guest.get_live(remote, local, 60) == f"ok {remote}"
    assert local.read_bytes() == b"saved"
    assert clock.sleeps[0] == pytest.approx(fsuaesession.SAVE_REACHES_DISK)
    assert clock.sleeps[1:] == [fsuaesession.LIVE_COPY_INTERVAL] * 2


def test_get_live_gives_two_reads_after_a_save_wait_that_overruns(lane, tmp_path, monkeypatch, clock):
    guest = _started(tmp_path, lane)
    remote = guest.remote_path("1", "wish1-test", "one")
    guest.press("wish1-test", "ret", 30)
    late = [2.5]
    real_sleep = clock.sleep

    def sleep(seconds):
        real_sleep(seconds + (late.pop() if late else 0.0))

    monkeypatch.setattr(fsuaesession.time, "sleep", sleep)
    assert guest.get_live(remote, tmp_path / "late.adf", 14) == f"ok {remote}"
    assert (tmp_path / "late.adf").read_bytes() == b"one"


def test_a_key_to_a_recognised_screen_skips_the_age_and_a_later_unrecognised_one_still_waits(
        lane, tmp_path, monkeypatch, clock):
    guest = _started(tmp_path, lane, first_key_after=259.0)
    guest.note_recognised()
    clock.sleeps.clear()
    assert guest.press("wish1-test", "esc", 30) == "ok ESC"
    assert clock.sleeps == [] and lane.keys == ["Escape"]
    assert guest.grab("next", tmp_path / "r.png", tmp_path / "c.png", 1) is False
    clock.sleeps.clear()
    with pytest.raises(RouteError, match="first key needs"):
        guest.press("wish1-test", "ret", 30)
    guest.press("wish1-test", "ret", 300)
    assert len(clock.sleeps) == 1 and clock.sleeps[0] > 200 and lane.keys == ["Escape", "Return"]
    guest.grab("after", tmp_path / "r.png", tmp_path / "c.png", 1)
    clock.sleeps.clear()
    guest.press("wish1-test", "ret", 30)
    assert clock.sleeps == []


def test_a_recognised_screen_lets_one_key_out_early_and_the_next_waits_for_the_age(lane, tmp_path, clock):
    guest = _started(tmp_path, lane, first_key_after=259.0)
    guest.note_recognised()
    guest.press("wish1-test", "esc", 30)
    with pytest.raises(RouteError, match="first key needs"):
        guest.press("wish1-test", "ret", 30)
    assert lane.keys == ["Escape"]


def test_a_swap_keeps_the_mark_for_the_key_that_answers_the_recognised_prompt(lane, tmp_path, clock):
    guest = _started(tmp_path, lane, disks=("one", "three", "two"), mounted=("one", "three"),
                     first_key_after=259.0)
    two = guest.remote_path("1", "wish1-test", "two")
    real_send = guest._send

    def send(key):
        real_send(key)
        if key == "F12" and lane.keys.count("F12") == 2:
            _log_line(guest, f"gui_disk_image_change drive 0 name {guest.staged[two]}")

    guest._send = send
    guest.note_recognised()
    guest.insert("wish1-test", 0, two, 30, hashlib.sha256(b"two").hexdigest())
    clock.sleeps.clear()
    assert guest.press("wish1-test", "space", 30) == "ok SPACE"
    assert lane.keys[-1] == "space" and clock.sleeps == []


def test_get_live_stops_when_the_image_keeps_changing_or_the_save_needs_longer(lane, tmp_path, monkeypatch, clock):
    guest = _started(tmp_path, lane)
    remote = guest.remote_path("1", "wish1-test", "one")
    staged = guest.staged[remote]
    real_sleep = clock.sleep

    def sleep(seconds):
        real_sleep(seconds)
        staged.write_bytes(str(clock.now).encode())

    monkeypatch.setattr(fsuaesession.time, "sleep", sleep)
    with pytest.raises(RouteError, match="still changing after 5s"):
        guest.get_live(remote, tmp_path / "torn.adf", 5)
    assert not (tmp_path / "torn.adf").exists()
    guest.press("wish1-test", "ret", 30)
    with pytest.raises(RouteError, match="needs 12s more"):
        guest.get_live(remote, tmp_path / "early.adf", 5)


def test_get_live_after_the_stop_is_a_plain_copy(lane, tmp_path, clock):
    guest = _started(tmp_path, lane)
    remote = guest.remote_path("1", "wish1-test", "one")
    guest.stop("wish1-test", 30)
    clock.sleeps.clear()
    assert guest.get_live(remote, tmp_path / "after.adf", 30) == f"ok {remote}"
    assert (tmp_path / "after.adf").read_bytes() == b"one" and clock.sleeps == []


def test_a_hires_frame_is_not_shown_yet_and_keeps_its_raw_frame_and_no_crop(lane, tmp_path, monkeypatch):
    guest = _started(tmp_path, lane)
    raw, cropped = tmp_path / "raw.png", tmp_path / "crop.png"
    cropped.write_bytes(b"stale")

    def hires(display, key, settle):
        frame = Image.new("RGB", (754, 576), (0, 0, 0))
        for x in range(16, 736, 2):
            frame.putpixel((x, 100), (255, 255, 255))     # a one-pixel stroke breaks the 2x2 blocks
        frame.save(guest.work / "shots" / "FS-UAE_Full_261004-0000_01.png")

    monkeypatch.setattr(fsuaegdb, "press", hires)
    assert guest.grab("journal", raw, cropped, 10) is False
    assert raw.exists() and not cropped.exists()


def test_capture_returns_on_the_second_identical_frame(lane, tmp_path, monkeypatch, clock):
    guest = _started(tmp_path, lane)
    frames = []

    def shoot(display, key, settle):
        frames.append(1)
        native = Image.new("RGB", (377, 288), (0, 0, 0))
        native.putpixel((10, 10), (17 * min(len(frames), 3), 0, 0))
        native.resize((754, 576), Image.NEAREST).save(
            guest.work / "shots" / f"FS-UAE_Full_261004-0000_{len(frames):02d}.png")

    monkeypatch.setattr(fsuaegdb, "press", shoot)
    guest.capture("title", tmp_path / "r.png", tmp_path / "c.png", 60)
    assert len(frames) == 4


def test_a_machine_snapshot_says_it_is_not_available_yet(lane):
    guest = fsuaesession.FsuaeGuest()
    for verb in (guest.snapshot, guest.restore, guest.discard):
        with pytest.raises(RouteError, match="not available on FS-UAE yet"):
            verb("walk", "wish1-test")
    assert guest.can_snapshot is False


def test_stop_without_a_start_is_a_route_error(lane):
    with pytest.raises(RouteError, match="no emulator was started"):
        fsuaesession.FsuaeGuest().stop("h", 30)


def test_the_first_key_ages_are_the_measured_ones():
    assert fsuaesession.FIRST_KEY_AFTER["ssb"] == 48.0 and fsuaesession.FIRST_KEY_AFTER["darkness"] == 259.0
    assert fsuaesession.FIRST_KEY_AFTER["pool"] == 42.0


def test_a_launch_namespace_is_all_start_processes_reads(lane, tmp_path):
    # `start_processes` runs on exactly the fields the launcher's command line gives it.
    args = argparse.Namespace(fs_uae=str(lane.binary), out=str(tmp_path / "r"), display=":9", kickstart=None,
                              floppy=None, swap=None, foreground=True, wait=1, port=6520, extra=None)
    xvfb, emulator = fsuaegdb.start_processes(args, True)
    assert "FSEMU_SCREENSHOTS_DIR" not in emulator.kw["env"]


def test_a_start_that_fails_before_launch_can_still_be_stopped_and_released(lane, tmp_path, monkeypatch):
    def no_binary():
        raise RouteError("the patched FS-UAE is not installed")

    monkeypatch.setattr(fsuaesession, "_binary", no_binary)
    guest = fsuaesession.FsuaeGuest(game="amiga-pool")
    guest.claim("wish1-test", 30)
    guest.put(_disk(tmp_path, "one.src"), guest.remote_path("1", "wish1-test", "one"), 30)
    with pytest.raises(RouteError, match="not installed"):
        guest.start("wish1-test", guest.remote_path("1", "wish1-test", "one"), timeout=30, options=())
    assert guest.stop("wish1-test", 30) == "ok stopped; nothing was running"
    guest.release("wish1-test", 30)
    assert lane.slot.released


def test_a_screenshot_still_being_written_is_retried_on_the_next_poll(lane, tmp_path, monkeypatch, clock):
    guest = _started(tmp_path, lane)
    shots = guest.work / "shots"
    full = tmp_path / "full.png"
    _doubled_frame(full)
    data = full.read_bytes()
    target = shots / "FS-UAE_Full_261004-0000_01.png"
    polls = []

    def alt_s(display, key, settle):
        # An IDAT length that is not written yet makes PIL raise SyntaxError ("broken PNG file"), not OSError.
        target.write_bytes(data[:33] + b"\0\0\0\0" + data[37:])

    real_sleep = clock.sleep

    def sleep(seconds):
        polls.append(seconds)
        if len(polls) == 2:
            target.write_bytes(data)
        real_sleep(seconds)

    monkeypatch.setattr(fsuaegdb, "press", alt_s)
    monkeypatch.setattr(fsuaesession.time, "sleep", sleep)
    assert guest._shoot(10) == target
    assert len(polls) >= 2


def _swapped(tmp_path, lane, line):
    guest = _started(tmp_path, lane, disks=("one", "three", "two"), mounted=("one", "three"))
    two = guest.remote_path("1", "wish1-test", "two")
    if line:
        _log_line(guest, line.format(path=guest.staged[two]))
    return guest, two


def test_insert_needs_the_change_to_be_for_drive_zero(lane, tmp_path, clock):
    guest, two = _swapped(tmp_path, lane, "")
    real_send = guest._send

    def send(key):
        real_send(key)
        if key == "F12" and lane.keys.count("F12") == 2:
            _log_line(guest, f"gui_disk_image_change drive 1 name {guest.staged[two]} write protected 0")

    guest._send = send
    with pytest.raises(RouteError, match="shows no change"):
        guest.insert("wish1-test", 0, two, 30, hashlib.sha256(b"two").hexdigest())


def test_insert_reads_the_real_log_line_and_matches_a_resolved_path(lane, tmp_path, clock):
    guest, two = _swapped(tmp_path, lane, "")
    link = tmp_path / "link"
    link.symlink_to(guest.staged[two].parent)
    real_send = guest._send

    def send(key):
        real_send(key)
        if key == "F12" and lane.keys.count("F12") == 2:
            _log_line(guest, f"gui_disk_image_change drive 0 name {link / guest.staged[two].name} write protected 0")

    guest._send = send
    receipt = guest.insert("wish1-test", 0, two, 30, hashlib.sha256(b"two").hexdigest())
    assert receipt["index"] == 2

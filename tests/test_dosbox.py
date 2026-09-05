from __future__ import annotations

"""The DOSBox harness, and what driving it established about a DOS save.

Two kinds of test live here, and both skip rather than fail on a machine that
has neither the player's archives nor an emulator, which is what CI is.

* The parts of `tools/dosbox.py` that need nothing: the PPM decode, the
  colour-blind screen digest, and the instance lease.
* The **findings** — where the party's square, its facing and its area sit in
  `SAVGAM<slot>.DAT`. These are asserted against the player's own three saves
  and against the game's `GEO*.DAX` indexes, so they are measurements rather
  than a transcription of what the driven run happened to print.

Nothing is copied in. `docs/117-save-conversion.md` carries the reasoning.
"""


import functools
import os
import pathlib
import shutil
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from gamedata import needs_specimens  # noqa: E402

from tools import dosbox  # noqa: E402

# Shares a group with tests/test_instance.py -- see that file's own note.
# Only three tests here claim a pool slot, each at its own fixed display
# base (950, 955, 960), but the whole module travels together so a future
# test claiming one does not have to discover this on its own.
pytestmark = pytest.mark.xdist_group(name="emulator-pool")

SAVGAM_SIZE = 13137


# --------------------------------------------------------------------------
# Finding the player's files
# --------------------------------------------------------------------------


def _candidates():
    """`gamedisks.toml`'s own search list for the DOS archives (#212)."""
    from tools import gamedisks
    return gamedisks.candidates("dos-archives")


@functools.lru_cache(maxsize=1)
def _saves():
    """`{letter: bytes}` for every 13137-byte `SAVGAM?.DAT` of a played party."""
    best: tuple[int, dict[str, bytes]] = (0, {})
    for root in _candidates():
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("SAVGAM?.DAT"):
                found = {
                    p.stem[-1]: p.read_bytes()
                    for p in path.parent.glob("SAVGAM?.DAT")
                    if p.stat().st_size == SAVGAM_SIZE
                }
                if len(found) > best[0]:
                    best = (len(found), found)
        except OSError:
            continue
    return best[1]


@functools.lru_cache(maxsize=1)
def _geo_files():
    """`{area id: GEO file number}` read out of the game's `GEO*.DAX` indexes.

    The container is a `u16le` index size, then entries of `id:u8,
    offset:u32le, compressed:u16le, raw:u16le`.  Only the ids are wanted here.
    """
    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        return {}
    out: dict[int, int] = {}
    for n in range(1, 9):
        path = game / f"GEO{n}.DAX"
        if not path.is_file():
            continue
        data = path.read_bytes()
        size = struct.unpack_from("<H", data, 0)[0]
        for i in range(size // 9):
            out[data[2 + 9 * i]] = n
    return out


@functools.lru_cache(maxsize=1)
def _itm_files():
    """Every `.ITM` in the archives: `{path: bytes}`, saved parties and shipped."""
    out: dict[str, bytes] = {}
    for root in _candidates():
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*.[iI][tT][mM]"):
                out[str(path)] = path.read_bytes()
        except OSError:
            continue
    return out


@functools.lru_cache(maxsize=1)
def _dos_item_templates():
    """Every distinct item record in the game's own `ITEM<n>.DAX` files."""
    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        return ()
    seen: dict[bytes, bytes] = {}
    for n in range(1, 9):
        path = game / f"ITEM{n}.DAX"
        if not path.is_file():
            continue
        for _, block in dosbox.dax_blocks(path.read_bytes()):
            for record in dosbox.items(block):
                seen.setdefault(record[dosbox.ITEM_NEXT:], record)
    return tuple(seen.values())


def _need_items():
    files = _itm_files()
    if not files:
        pytest.skip("needs the DOS item files; set FR_ARCHIVES to the archives")
    return files


def _need_templates():
    templates = _dos_item_templates()
    if not templates:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    return templates


def _need_saves():
    saves = _saves()
    if not saves:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    return saves


#: Saved games this project watched the engine write, and where each party was
#: standing when it did -- from `tools/specimens.py`'s tree, for `#246 (Nothing
#: tells an engine-written DOS record from one edited with Gold Box Companion,
#: and conclusions already rest on edited ones)`.  `_saves()` above sweeps the
#: archives, whose `SAVE` folder was open in Gold Box Companion on 2026-08-17,
#: so a *measurement* comes from here and the archives are left to the round
#: trips.
CLEAN_SAVES = {
    "por-party-l1": "SAVGAMC.DAT",
    "por-party-l1-intown": "SAVGAME.DAT",
    "por-party-trained-c2": "SAVGAMF.DAT",
    "por-train-clamp": "SAVGAMF.DAT",
    "por-item-granted": "SAVGAMD.DAT",
}


def _clean_saves():
    """`{specimen: bytes}` for every saved game in the specimen tree."""
    from gamedata import specimen
    return {name: (specimen(name) / filename).read_bytes()
            for name, filename in CLEAN_SAVES.items()}


# --------------------------------------------------------------------------
# The pure parts of the harness
# --------------------------------------------------------------------------


def _ppm(pixels, width, height):
    return b"P6\n%d %d\n255\n" % (width, height) + bytes(pixels)


def test_a_binary_ppm_decodes_to_its_pixels():
    px = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    s = dosbox.Screen.from_ppm(_ppm(px, 2, 2))
    assert (s.width, s.height) == (2, 2)
    assert s.px == bytes(px)


def test_a_ppm_with_a_comment_decodes():
    body = b"P6\n# written by something\n1 1\n255\n" + bytes([9, 9, 9])
    assert dosbox.Screen.from_ppm(body).px == bytes([9, 9, 9])


def test_something_that_is_not_a_ppm_is_refused():
    with pytest.raises(ValueError):
        dosbox.Screen.from_ppm(b"\x89PNG\r\n")


def test_the_digest_covers_only_the_rectangle_it_was_given():
    a = dosbox.Screen.from_ppm(_ppm([0] * 12, 2, 2))
    b = dosbox.Screen.from_ppm(_ppm([0, 0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0], 2, 2))
    assert a.digest((0, 0, 2, 1)) == b.digest((0, 0, 2, 1))
    assert a.digest() != b.digest()


def test_the_ink_digest_ignores_a_recolour_and_not_a_reshape():
    """The command bar is white for a frame and green after; same glyphs.

    That is the whole reason `ink` exists: `digest` calls those two frames
    different screens, and a wait driven by it never finishes.
    """
    white = dosbox.Screen.from_ppm(_ppm([255, 255, 255, 0, 0, 0], 2, 1))
    green = dosbox.Screen.from_ppm(_ppm([85, 255, 85, 0, 0, 0], 2, 1))
    moved = dosbox.Screen.from_ppm(_ppm([0, 0, 0, 255, 255, 255], 2, 1))
    assert white.digest() != green.digest()
    assert white.ink() == green.ink()
    assert white.ink() != moved.ink()


# --------------------------------------------------------------------------
# A frame from one harness read with the other's geometry (#204)
# --------------------------------------------------------------------------
#
# DOSBox-X line-doubles this game's 320x200 mode into a 640x400 window; DOSBox
# 0.74 does not.  `BAR` -- `(0, 192, 320, 7)` -- is measured in the 320x200
# frame, so reading it against a 640x400 one lands on the picture panel, not
# the command bar.  Reproduced here with no emulator and no game pixels: a
# synthetic bar, doubled the way DOSBox-X draws it, and `tools/dosboxx.py`'s
# `halve()` putting it back.


def _double_frame(screen: dosbox.Screen) -> dosbox.Screen:
    """The way DOSBox-X draws this game's 320x200 mode into a 640x400 window."""
    w, h = screen.width, screen.height
    px = screen.px
    stride = w * 2 * 3
    out = bytearray(stride * h * 2)
    for y in range(h):
        row = bytearray(stride)
        for x in range(w):
            p = px[(y * w + x) * 3:(y * w + x) * 3 + 3]
            row[x * 6:x * 6 + 3] = p
            row[x * 6 + 3:x * 6 + 6] = p
        out[2 * y * stride:(2 * y + 1) * stride] = row
        out[(2 * y + 1) * stride:(2 * y + 2) * stride] = row
    return dosbox.Screen(w * 2, h * 2, bytes(out))


def test_bar_kind_reads_the_picture_panel_when_the_frame_is_not_halved_back(monkeypatch):
    """A real 640x400 DOSBox-X frame read with `BAR`'s 320x200 numbers.

    This is `#204 (The DOSBox-X harness measures the picture panel where it
    means to measure the command bar)`'s own fault, stated as an assertion: a
    320x200 frame with a bar `bar_kind()` names correctly is doubled the way
    DOSBox-X draws it, and the same rectangle on the doubled frame names
    nothing -- the `fight_unknown_bar` symptom, a plausible `None` rather than
    an error.  `tools/dosboxx.py`'s `halve()` is what recovers the answer.
    """
    from tools import dosboxx

    width, height = 320, 200
    px = bytearray(width * height * 3)  # all-black paper
    # A bar: alternating black-and-white columns across BAR's own row band.
    for y in range(dosbox.BAR[1], dosbox.BAR[1] + dosbox.BAR[3]):
        for x in range(0, width, 5):
            i = (y * width + x) * 3
            px[i:i + 3] = b"\xff\xff\xff"
    screen = dosbox.Screen(width, height, bytes(px))

    digest = screen.glyphs(dosbox.BAR)
    monkeypatch.setattr(dosbox.PoolOfRadiance, "COMBAT_BARS",
                        ((dosbox.BAR[2], digest, "test_bar"),))
    por = dosbox.PoolOfRadiance(None)

    assert por.bar_kind(screen) == "test_bar"

    doubled = _double_frame(screen)
    assert por.bar_kind(doubled) is None, (
        f"a {doubled.width}x{doubled.height} frame read with "
        f"{width}x{height} rectangles should not name a bar by luck"
    )

    halved = dosboxx.halve(doubled)
    assert (halved.width, halved.height) == (width, height)
    assert por.bar_kind(halved) == "test_bar"


#: The lease is an `flock`, which Windows has no equivalent of. Everything
#: else in this file -- the PPM decode, the digest, and the findings about a
#: DOS save -- is platform-independent and runs everywhere.
posix_only = pytest.mark.skipif(sys.platform == "win32",
                                reason="the instance lease is an flock")


@posix_only
def test_a_leased_slot_is_not_leased_twice(tmp_path, monkeypatch):
    """`DISPLAY_BASE` moves off the real `:50`-`:51` so a band shrunk to two
    for speed never depends on those two specific displays being free on a
    machine other agents are using tonight -- `#213 (Each display pool walks
    out of its own band once the band is full)` narrowed the search to
    exactly `SLOTS` displays. 950 is this file's own base, moved by `#233
    (The test suite takes the emulator displays agents need, and eight slots
    is no longer enough)` off the old 930-941 once the real bands widened to
    sixteen and needed the room those numbers used to give this file margin.
    """
    monkeypatch.setattr(dosbox, "INST", tmp_path / "inst")
    monkeypatch.setattr(dosbox, "SLOTS", 2)
    monkeypatch.setattr(dosbox, "DISPLAY_BASE", 950)
    first = dosbox.claim("one")
    second = dosbox.claim("two")
    assert {first.n, second.n} == {0, 1}
    assert first.display != second.display
    with pytest.raises(dosbox.PoolFull):
        dosbox.claim("three")
    first.release()
    third = dosbox.claim("again")
    assert third.n == 0
    second.release()
    third.release()


@posix_only
def test_the_pool_refuses_once_its_display_band_is_full(tmp_path, monkeypatch):
    """The band, not the lease count, is what is exhausted here: the lease
    directory has a free slot throughout, and only the two displays are held.

    Before #213 the search walked past a full band into whatever the next
    free number happened to be instead of admitting its own was exhausted --
    proven by reverting the fix and watching this raise nothing.
    """
    import fcntl  # local: unimportable on Windows, and @posix_only skips there

    monkeypatch.setattr(dosbox, "INST", tmp_path / "inst")
    monkeypatch.setattr(dosbox, "SLOTS", 2)
    monkeypatch.setattr(dosbox, "DISPLAY_BASE", 955)
    held = []
    try:
        for i in range(2):
            fd = os.open(f"/tmp/.wish-x11-{955 + i}.lock", os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(fd)
        with pytest.raises(dosbox.PoolFull, match=r":955-:956"):
            dosbox.claim("blocked")
    finally:
        for fd in held:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


@posix_only
def test_a_lease_is_dropped_when_the_process_holding_it_dies(tmp_path, monkeypatch):
    """The reason the lease is an flock and not a lock file with a pid in it."""
    monkeypatch.setattr(dosbox, "INST", tmp_path / "inst")
    monkeypatch.setattr(dosbox, "SLOTS", 1)
    monkeypatch.setattr(dosbox, "DISPLAY_BASE", 960)
    repo = pathlib.Path(__file__).resolve().parent.parent
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from tools import dosbox\n"
        "dosbox.INST = __import__('pathlib').Path(%r)\n"
        "dosbox.SLOTS = 1\n"
        "dosbox.DISPLAY_BASE = 960\n"
        "dosbox.claim('doomed')\n" % (str(repo), str(tmp_path / "inst"))
    )
    subprocess.run([sys.executable, "-c", script], check=True)
    slot = dosbox.claim("survivor")
    assert slot.n == 0
    slot.release()


def test_the_missing_tool_list_names_only_tools_this_module_uses():
    assert set(dosbox.missing_tools()) <= set(dosbox.TOOLS)


def test_a_plain_session_still_asks_for_dosbox(tmp_path, monkeypatch):
    """The other half of #73: narrowing the list per class, not dropping it.

    `Session` launches DOSBox 0.74 and must keep saying so; only `XSession`,
    which launches DOSBox-X instead, is entitled to leave it out.
    """
    monkeypatch.setattr(
        shutil, "which",
        lambda name, *a, **k: None if name == "dosbox" else f"/usr/bin/{name}")
    with pytest.raises(dosbox.DosboxUnavailable) as e:
        dosbox.Session(dosbox.Slot(n=0, dir=tmp_path, _fd=-1, _display_num=30), tmp_path / "POOLRAD")
    assert "not installed: dosbox" in str(e.value)


def test_a_session_refuses_to_stage_outside_work(tmp_path):
    """The assertion that keeps a copy from ever landing on the player's files."""
    slot = dosbox.Slot(n=0, dir=tmp_path, _fd=-1, _display_num=30)
    session = dosbox.Session.__new__(dosbox.Session)
    session.dir = tmp_path
    session.stem = "POOLRAD"
    session.source = tmp_path
    session.exe = "START.EXE"
    session.cycles = 20000
    with pytest.raises(AssertionError):
        session.stage()
    slot.release()


def test_find_game_says_so_when_the_archives_are_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(dosbox, "ARCHIVES", tmp_path / "nowhere")
    with pytest.raises(FileNotFoundError):
        dosbox.find_game()


# --------------------------------------------------------------------------
# Which window, and whether anything is in it
# --------------------------------------------------------------------------
#
# Measured on the DOSBox-X side (#83) and ported here with the code (#88); the
# specimens in the docstrings are that harness's, because that is where two
# processes on one display were reproduced.  Nothing here needs an emulator.


def _screen(width: int, height: int, pixels: bytes):
    """A `Screen` built from nothing, so the refusal is testable with no X."""
    return dosbox.Screen.from_ppm(f"P6\n{width} {height}\n255\n".encode() + pixels)


def test_a_capture_of_one_colour_is_recognised_as_showing_nothing():
    """The signature of a capture of the wrong window: `import` returns flat.

    Black is the one that cost an hour, but the test is one colour, not black:
    an unmapped window under some drivers comes back white or grey and means
    exactly the same thing.
    """
    assert dosbox.uniform_colour(_screen(4, 2, b"\x00\x00\x00" * 8)) == (0, 0, 0)
    assert dosbox.uniform_colour(_screen(4, 2, b"\xFF\xFF\xFF" * 8)) == (255, 255, 255)
    assert dosbox.uniform_colour(_screen(1, 2, b"\x11\x22\x33" * 2)) == (0x11, 0x22, 0x33)


def test_a_window_whose_capture_failed_is_not_taken_for_a_good_one():
    """The two failures read the same through `uniform_colour` alone.

    `grab()` answers None when `import` exits nonzero, and `uniform_colour`
    answers None for that *and* for a capture with something in it -- so
    `uniform_colour(grab(wid)) is None` chose a window whose capture had
    failed.  `xdotool search` can list a window that closes before `import`
    reaches it, and `boot()` then settled on it and raised
    `CalledProcessError` out of `capture(check=True)` rather than the named
    refusal.
    """
    assert dosbox.has_content(None) is False
    assert dosbox.has_content(_screen(4, 2, b"\x00\x00\x00" * 8)) is False
    px = bytearray(b"\x00\x00\x00" * 8)
    px[0] = 0xFF
    assert dosbox.has_content(_screen(4, 2, bytes(px))) is True


def test_a_capture_with_one_pixel_lit_is_not_refused():
    px = bytearray(b"\x00\x00\x00" * 8)
    px[12] = 1
    assert dosbox.uniform_colour(_screen(4, 2, bytes(px))) is None


def test_a_display_with_no_server_on_it_reads_free():
    """`xdotool` could not answer this, which is why the check is a socket.

    It exits 1 both for "no windows matched" and for "Can't open display", so
    the readiness loop that tested its status was satisfied by a display that
    did not exist -- and the guard against sharing an earlier run's display
    would have been satisfied by every display.  :62 is outside every pool.
    """
    assert dosbox.server_on(":62") is False


def test_the_window_belonging_to_this_process_wins():
    """Two DOSBox processes on one display, and only one window has pixels.

    Reproduced on the DOSBox-X side by starting a second `dosbox-x` on a booted
    session's display: `0x20000b` and `0x40000b`, same title, same
    `640x400+80+100`, both `IsViewable`.  `_NET_WM_PID` is the only thing that
    told them apart.
    """
    ids = ["2097163", "4194315"]
    pids = {"2097163": 582983, "4194315": 582890}
    assert dosbox.candidate_windows(ids, pids, 582890) == ["4194315"]
    assert dosbox.candidate_windows(ids, pids, 582983) == ["2097163"]


def test_a_window_that_names_another_process_is_never_ours():
    """Even as the only candidate.  Taking it is how every shot came back black.

    The window with pixels in it is whichever process drew last, so choosing by
    content would take the intruder's as often as ours.
    """
    assert dosbox.candidate_windows(["2097163"], {"2097163": 99}, 7) == []


def test_windows_with_no_pid_property_stay_candidates():
    """A build whose SDL does not set `_NET_WM_PID` still has to be choosable."""
    ids = ["2097163", "4194315"]
    assert dosbox.candidate_windows(ids, dict.fromkeys(ids), 7) == ids


class _BlankWindow:
    """A session whose window captures as solid black, and nothing else."""

    display = ":30"
    window = "4194315"

    def __init__(self, tmp_path):
        self.dir = tmp_path
        self.grabs = 0

    def grab(self, window=None):
        self.grabs += 1
        return _screen(4, 2, b"\x00\x00\x00" * 8)

    def _env(self):
        return {}


def test_a_screenshot_of_a_blank_window_is_refused_by_name(tmp_path):
    """`shot()` writes no file rather than one that looks like a dead game."""
    with pytest.raises(dosbox.BlankCapture) as e:
        dosbox.Session.shot(_BlankWindow(tmp_path), "loaded")
    assert "loaded" in str(e.value)
    assert "0x40000b" in str(e.value) and "#000000" in str(e.value)


def test_the_shot_on_the_way_out_of_a_failure_is_written_anyway(tmp_path,
                                                               monkeypatch):
    """`leave_camp` takes one to explain itself, and a blank frame is the point.

    Refusing that one would replace the `TimeoutError` that says what went
    wrong with a `BlankCapture` that says less.
    """
    ran = []
    monkeypatch.setattr(dosbox.subprocess, "run",
                        lambda argv, **kw: ran.append(argv))
    stub = _BlankWindow(tmp_path)
    (tmp_path / "shots").mkdir()
    out = dosbox.Session.shot(stub, "leave_camp_stuck", allow_blank=True)
    assert out == tmp_path / "shots" / "leave_camp_stuck.png"
    assert stub.grabs == 0
    assert ran and ran[0][:3] == ["import", "-window", stub.window]


# --------------------------------------------------------------------------
# The public seam #226 (Two tools reach into tools/dosbox.py's private
# methods for want of a public seam) opened, and the two tools that reached
# past `_move` and `_env` before it existed.
# --------------------------------------------------------------------------


class _MoveSession:
    """A `Session` stand-in that records only the keys `move()` sends.

    `move()` also calls `settle()` and, once `world_bar` is set,
    `wait_until_ink()` -- both stubbed to behave as though the command bar
    always comes back, since what this test checks is which key reached
    `key()`, not the wait itself.
    """

    def __init__(self):
        self.pressed: list[str] = []

    def key(self, *keys: str, gap: float = 0.0) -> None:
        self.pressed.extend(keys)

    def settle(self, quiet: float = 0.6, timeout: float = 30.0) -> None:
        return None

    def wait_until_ink(self, rect, want, timeout: float = 30.0) -> bool:
        return True


def test_move_is_public_and_step_turn_left_turn_right_still_wrap_it():
    """`_move` became `move` (#226); the three wrappers keep working unchanged.

    `tools/dosoutdoorprobe.py` needs the raw key directly -- outdoors the
    arrows move the party rather than turn it, so no combination of
    `step`/`turn_left`/`turn_right` can walk a four-direction travel-grid
    route.
    """
    assert not hasattr(dosbox.PoolOfRadiance, "_move")
    sess = _MoveSession()
    por = dosbox.PoolOfRadiance(sess)
    por.world_bar = "world"
    assert por.step() is True
    assert por.turn_left() is True
    assert por.turn_right() is True
    assert por.move("Down") is True
    assert sess.pressed == ["Up", "Left", "Right", "Down"]


class _DisplayStub:
    display = ":40"
    _env = dosbox.Session._env


def test_session_env_is_public_and_returns_what_env_builds():
    """`_env()` stays the implementation; `env()` is the seam (#226).

    `tools/doscurse.py` used to write `session._env()` for the same
    dictionary it now gets from `session.env()`.  `_env()` is not renamed
    away, only wrapped: `tools/dosboxx.py`'s `XSession` overrides `_env`, not
    `env`, to swap in its own `debug_env()`, and a plain rename of the name
    every internal call dispatches through would have silently stopped that
    override from firing.
    """
    stub = _DisplayStub()
    built = dosbox.Session._env(stub)
    assert dosbox.Session.env(stub) == built
    assert built["DISPLAY"] == ":40"


def test_dosoutdoorprobe_and_doscurse_no_longer_reach_past_the_seam():
    """The two callers #226 was filed about, read back off their own source.

    A grep is what would have caught either tool regaining a private call:
    neither name is exercised by an emulator in this suite, so nothing else
    here would notice a `._move(` or `._env(` creeping back in.
    """
    import inspect

    from tools import doscurse, dosoutdoorprobe

    assert "._move(" not in inspect.getsource(dosoutdoorprobe)
    assert "._env(" not in inspect.getsource(doscurse)


# --------------------------------------------------------------------------
# The findings, measured off the player's saves
# --------------------------------------------------------------------------


def test_every_save_is_the_size_the_format_says():
    for letter, data in _need_saves().items():
        assert len(data) == SAVGAM_SIZE, letter


@needs_specimens
def test_every_save_we_watched_being_written_is_the_size_the_format_says():
    for name, data in _clean_saves().items():
        assert len(data) == SAVGAM_SIZE, name


@needs_specimens
def test_the_party_square_reads_as_a_legal_square():
    """16x16 maps, so both coordinates are 0..15 and the facing is 0, 2, 4, 6."""
    for name, data in _clean_saves().items():
        x, y, facing = dosbox.position(data)
        assert 0 <= x < 16, (name, x)
        assert 0 <= y < 16, (name, y)
        assert facing in dosbox.FACINGS, (name, facing)


@needs_specimens
def test_the_square_read_back_is_the_square_the_party_was_standing_on():
    """The one reading here that is not the file checked against itself.

    `WISH-SPEC-por-party-l1-intown` was made by loading the `#249` party,
    pressing BEGIN ADVENTURING, playing Rolf's tour of New Phlan to its end
    and saving -- and the tour ends with the party at (0, 4) facing west,
    which is on the screen in the run's own snapshots.  So the three bytes
    `POS_X`, `POS_Y` and `POS_FACING` are pinned against something outside the
    file for once, and an offset that had drifted a byte would show up as a
    square nobody stood on.
    """
    data = _clean_saves()["por-party-l1-intown"]
    assert dosbox.position(data) == (0, 4, 6)


@needs_specimens
def test_the_harness_reads_the_facing_the_file_carries_and_por_halves_it():
    """The one place the two accessors over one byte map differ (#76).

    `tools/dosbox.py` reports the facing byte as the file carries it, doubled,
    because a differential between two driven saves is written in file bytes;
    `goldbox.dos_savegame.position` reports the C64's 0-3 because that is what a
    conversion writes.  Collapsing the harness onto the other accessor -- the
    obvious next tidy -- halves every facing a driven run reports, silently.
    """
    from goldbox import dos_savegame as sg

    for name, data in _clean_saves().items():
        x, y, facing = dosbox.position(data)
        px, py, pf = sg.position(data)
        assert (x, y) == (px, py), name
        assert facing == pf * sg.FACING_SCALE, name
        assert facing in dosbox.FACINGS, (name, facing)


@needs_specimens
def test_the_area_id_is_one_the_c64_area_table_knows():
    """The numbering is the same on both ports, which is the finding."""
    from goldbox.areas import AREAS_BY_ID

    for name, data in _clean_saves().items():
        assert dosbox.area_id(data) in AREAS_BY_ID, name


@needs_specimens
def test_the_second_area_entry_is_the_script_and_parts_company_in_a_hall():
    """`$49C5` and `$49F2` are **not** the same number, and a save made in the
    training hall is where they separate.

    This test used to assert they agreed in every save seen, and every save it
    had seen was the archives'.  Two saves the engine wrote for `#249` refute
    it: standing in the clerics' school of area 11, `$49C5` reads 0 and
    `$49F2` reads 11.  That is what the pair is *for* -- area 11 has no map of
    its own and borrows New Phlan's `GEO00`, so `$49C5` names the GEO block
    that is loaded and `$49F2` names the area the party is actually in.
    Everywhere the two are the same, the area owns its own map.

    `goldbox.dos_savegame.current_area` prefers `$49C5` indoors and so calls
    the training hall New Phlan; `#246` carries the finding and the issue it
    was filed as.
    """
    saves = _clean_saves()
    for name, data in saves.items():
        second = data[485] | data[486] << 8
        in_a_hall = name in ("por-party-trained-c2", "por-train-clamp")
        if in_a_hall:
            assert (dosbox.area_id(data), second) == (0, 11), name
        else:
            assert second == dosbox.area_id(data), name


@needs_specimens
def test_the_header_byte_is_the_dax_file_that_holds_the_area():
    """Byte 0 is not the area: it is which `GEO<n>.DAX` the area lives in.

    Read straight off the containers, so it is the game's own index that says
    so rather than anything this project inferred.
    """
    saves = _clean_saves()
    files = _geo_files()
    if not files:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    for name, data in saves.items():
        area = dosbox.area_id(data)
        assert files[area] == data[dosbox.AREA_FILE], (name, area)


def test_the_header_byte_names_more_than_one_area_so_it_is_not_the_map():
    """The reason obstacle 2 needed the array entry and not just byte 0."""
    files = _geo_files()
    if not files:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    counts: dict[int, int] = {}
    for n in files.values():
        counts[n] = counts.get(n, 0) + 1
    assert max(counts.values()) > 1


def test_the_c64_arrival_square_for_new_phlan_is_where_the_boat_lands():
    """A cross-port check that costs nothing and would catch a wrong offset.

    `goldbox/areas.py` records New Phlan's arrival as (15, 1) facing west, measured
    on the C64.  Driving DOS and taking the boat back to Phlan puts the party
    at DOS (15, 1) facing 6 -- west, doubled.  The saved run is kept under
    `work/dosbox/p47/`, which is gitignored, so this skips without it.
    """
    from goldbox.areas import AREAS_BY_ID

    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "work"
        / "dosbox"
        / "p47"
        / "09_postboat_phlan.dat"
    )
    if not path.is_file():
        pytest.skip("needs the driven capture in work/dosbox/p47")
    data = path.read_bytes()
    arrival = AREAS_BY_ID[dosbox.area_id(data)].arrival
    x, y, facing = dosbox.position(data)
    assert (x, y) == (arrival.x, arrival.y)
    assert facing == arrival.facing * 2


@pytest.mark.skipif(
    os.environ.get("WISH_DOSBOX_DRIVE") != "1",
    reason="set WISH_DOSBOX_DRIVE=1 to boot DOSBox; it takes about a minute",
)
def test_driving_the_game_one_step_moves_the_square_and_nothing_else():
    """The obstacle-2 experiment itself, opt-in because it drives an emulator."""
    if dosbox.missing_tools():
        pytest.skip("needs " + ", ".join(dosbox.missing_tools()))
    out = dosbox.one_step(load="A", before="C", after="D", turns=2)
    bx, by, _ = out["before"]
    ax, ay, af = out["after"]
    assert (ax, ay) != (bx, by) or af != out["before"][2]
    assert out["area_id"][0] == out["area_id"][1]
    assert dosbox.POS_X in out["changed_in_struct"] + out["changed_in_array"] or (
        dosbox.POS_Y in out["changed_in_struct"]
    )


# --------------------------------------------------------------------------
# The 63-byte item record, and its tail
# --------------------------------------------------------------------------


def test_every_item_file_is_a_whole_number_of_records():
    for path, data in _need_items().items():
        assert data and len(data) % dosbox.ITEM_SIZE == 0, path


def test_every_dax_block_of_every_archive_reaches_its_stated_size():
    """The check #65 asked for: not just the item archives, all of them.

    `ECL2.DAX` block 9 was reported as raising `IndexError`; it does not, and
    neither does any other block the player's archives carry.  The claim about
    "all 843 blocks of all 23 `.dax` files" is about the *Amiga* container,
    which is a different format read by a different tool.
    """
    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    archives = sorted(game.glob("*.DAX"))
    assert len(archives) > 100
    blocks = 0
    for path in archives:
        data = path.read_bytes()
        sizes = [(bid, raw) for bid, _, raw, _ in dosbox.dax_index(data)]
        got = list(dosbox.dax_blocks(data, path.name))
        assert [b for b, _ in got] == [b for b, _ in sizes], path.name
        for (bid, raw), (_, block) in zip(sizes, got):
            assert len(block) == raw, (path.name, bid)
        blocks += len(got)
    assert blocks > 1000


def test_a_truncated_dax_block_is_refused_by_name():
    """A decoder must not raise `IndexError` on its own input (#65)."""
    # A repeat opcode as the last byte of the block: the operand is missing.
    with pytest.raises(dosbox.DaxError) as exc:
        dosbox.dax_unpack(b"\x00A\xff", 8, "ECL2.DAX block 9")
    assert "ECL2.DAX block 9" in str(exc.value)
    assert "operand is missing" in str(exc.value)

    # A copy run that claims more bytes than the block holds.
    with pytest.raises(dosbox.DaxError) as exc:
        dosbox.dax_unpack(b"\x07ABC", 8, "ECL2.DAX block 9")
    assert "past the end" in str(exc.value)

    # A block that simply stops short of its stated size.
    with pytest.raises(dosbox.DaxError) as exc:
        dosbox.dax_unpack(b"\x00A", 8, "ECL2.DAX block 9")
    assert "not the 8 the index states" in str(exc.value)


def test_a_file_too_short_for_its_index_is_not_a_dax():
    with pytest.raises(dosbox.DaxError) as exc:
        dosbox.dax_index(struct.pack("<H", 900) + b"\x00" * 4, "T.DAX")
    assert "T.DAX: not a .DAX" in str(exc.value)


def test_a_dax_index_pointing_past_the_file_is_refused():
    """Truncate an archive and the block is named, not sliced short."""
    data = bytearray(struct.pack("<H", 9) + struct.pack("<BIHH", 9, 0, 2, 3))
    data += b"\x01AB"                       # copy two bytes: a whole block
    assert list(dosbox.dax_blocks(bytes(data), "T.DAX")) == [(9, b"AB")]
    with pytest.raises(dosbox.DaxError) as exc:
        list(dosbox.dax_blocks(bytes(data[:-1]), "T.DAX"))
    assert "T.DAX block 9" in str(exc.value)


def test_the_item_dax_blocks_are_whole_items():
    """The check that the container reader and the run-length coder are right:
    every block decodes to exactly its stated size and every size is items."""
    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    blocks = 0
    for n in range(1, 9):
        path = game / f"ITEM{n}.DAX"
        if not path.is_file():
            continue
        data = path.read_bytes()
        sizes = {bid: raw for bid, _, raw, _ in dosbox.dax_index(data)}
        for bid, block in dosbox.dax_blocks(data):
            assert len(block) == sizes[bid], (path.name, bid)
            assert len(block) % dosbox.ITEM_SIZE == 0, (path.name, bid)
            blocks += 1
    assert blocks > 40


def test_the_item_list_is_a_null_terminated_chain():
    """`0x02A`-`0x02D` is a far pointer to the next item, NULL on the last.

    Live heap state and nothing a converter wants, but reading it as one field
    is what keeps it out of the fields that do matter.
    """
    for path, data in _need_items().items():
        records = list(dosbox.items(data))
        for record in records[:-1]:
            assert any(record[dosbox.ITEM_NEXT:dosbox.ITEM_NEXT + 4]), path
        last = records[-1][dosbox.ITEM_NEXT:dosbox.ITEM_NEXT + 4]
        assert not any(last), path


def test_the_rendered_line_never_reaches_the_pointer():
    """The name is a Pascal string of at most 41 bytes, so `0x02A` is free."""
    for path, data in _need_items().items():
        for record in dosbox.items(data):
            assert record[dosbox.ITEM_TEXT] <= dosbox.ITEM_TEXT_MAX, path


def test_the_dos_item_type_table_is_the_c64_one():
    """`ITEMS` is 128 x 16 on both ports and 126 records are identical.

    This is what settles the class restrictions: they are byte +13 of *this*
    table, indexed by the item's `0x02E`, and there is nothing in the item
    record to convert.
    """
    from tests.gamedata import game_file

    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    dos = (game / "ITEMS").read_bytes()[2:]
    c64 = bytes(game_file("ITEMS"))
    assert len(dos) == len(c64) == 128 * 16
    same = sum(
        dos[i * 16:i * 16 + 16] == c64[i * 16:i * 16 + 16] for i in range(128)
    )
    assert same == 126
    differ = [i for i in range(128) if dos[i * 16:i * 16 + 16] != c64[i * 16:i * 16 + 16]]
    assert differ == [8, 9]                       # dagger and dart, in range only
    for i in differ:
        assert dos[i * 16 + 13] == c64[i * 16 + 13]      # the class flags agree


def test_the_dos_item_tail_projects_onto_the_c64_record():
    """157 of the C64's 163 distinct item records, byte for byte, from DOS.

    Every offset in `tools.dosbox.item_to_c64` rests on this: get the plus,
    the saving-throw bonus, the readied bit, the hidden-name mask, the cursed
    bit, the weight, the quantity, the cost or the three special bytes wrong
    and the count collapses.
    """
    from goldbox.items import load_item_templates
    from tests.gamedata import game_disk

    c64 = set(load_item_templates(str(game_disk("POOL1"))).values())
    dos = {dosbox.item_to_c64(r) for r in _need_templates()}
    assert len(c64) == 163
    assert len(c64 & dos) == 157


def test_the_dos_name_words_are_the_c64_itemnames_indices():
    """`0x02F`-`0x031` index the C64's `ITEMNAMES`, so a name is a copy.

    Not a text match against the rendered line: the same three numbers mean
    the same three words on both ports, and every one the game ships resolves.
    """
    from goldbox.items import load_item_names
    from tests.gamedata import game_disk

    names = load_item_names(str(game_disk("POOL1")))
    assert names[48] == "MAIL" and names[162] == "+1"
    used = set()
    for record in _need_templates():
        used.update(record[dosbox.ITEM_NAME1:dosbox.ITEM_NAME3 + 1])
    used.discard(0)
    assert used and used <= set(names)


def test_a_wand_carries_its_charges_in_the_first_special_byte():
    """`0x03C` is charges, and three wands of magic missiles prove the field.

    They are the same item -- type 79, the same three name words, effect 88 --
    differing in `0x03C` and in nothing else that names them.  The game's own
    use-item routine spends `count` first and then this byte, and destroys the
    item when it reaches zero (`work/coab/engine/ovr020.cs`).
    """
    wands = [
        r for r in _need_templates()
        if r[dosbox.ITEM_SPECIAL + 1] == 88 and r[dosbox.ITEM_TYPE] == 79
    ]
    assert len(wands) >= 3
    charges = {r[dosbox.ITEM_SPECIAL] for r in wands}
    assert len(charges) >= 3
    assert all(0 < c < 128 for c in charges)


def test_the_plus_is_signed_and_a_cursed_item_carries_a_negative_one():
    """`0x032` signed, `0x036` the curse -- the pair the C64 keeps at +4 and
    +7 bit 7.  A cursed necklace reads -5 in both `0x032` and `0x033`."""
    cursed = [r for r in _need_templates() if r[dosbox.ITEM_CURSED]]
    assert cursed
    for record in cursed:
        plus = record[dosbox.ITEM_PLUS]
        assert plus > 127, record[dosbox.ITEM_TEXT:]      # every curse is a minus
    necklaces = [
        r for r in cursed
        if r[dosbox.ITEM_PLUS] == 251 and r[dosbox.ITEM_PLUS_SAVE] == 251
    ]
    assert necklaces


def test_the_hidden_name_mask_hides_the_words_the_c64_mask_hides():
    """`0x035` bit 0 hides name 3, bit 1 name 2, bit 2 name 1.

    The invariant that fixes which bit is which: an unidentified item never
    shows its plus.  Read the bits the other way round and 83 of the shipped
    records leak a "+1" the party has not discovered yet; read this way, none
    does.  It is the C64's mask at +6 bits 0-2, same order.
    """
    from goldbox.items import load_item_names
    from tests.gamedata import game_disk

    names = load_item_names(str(game_disk("POOL1")))
    grades = {i for i, text in names.items() if text[:1] in "+-"}
    assert len(grades) > 4

    masks = {r[dosbox.ITEM_HIDDEN] for r in _need_templates()}
    assert masks <= {0, 1, 2, 3, 4, 5, 6, 7}

    masked = 0
    for record in _need_templates():
        mask = record[dosbox.ITEM_HIDDEN]
        if not mask:
            continue
        masked += 1
        words = (record[dosbox.ITEM_NAME3], record[dosbox.ITEM_NAME2],
                 record[dosbox.ITEM_NAME1])
        visible = [w for i, w in enumerate(words) if not mask & 1 << i]
        assert not set(visible) & grades, record[dosbox.ITEM_TEXT:]
    assert masked > 50


@pytest.mark.skip(reason="the only two saves it can run on were edited in Gold "
                        "Box Companion (#246)")
def test_the_quantity_falls_when_the_party_fires_the_arrows():
    """`0x039` observed changing in two saves of one party.

    The stack of arrows +1 in the earlier save holds 18 and in the later one
    11; the rendered line still says 18, which is why the line is not a source
    of anything.

    **Skipped rather than moved.**  The only pair of saves it can find is
    `CHRDATA2`/`CHRDATB2` of the archives' party, which Gold Box Companion had
    open on 2026-08-17, and Donald says the item encumbrance is specifically
    what he changed there.  A quantity byte a player shot down and a quantity
    byte somebody typed are the same symptom, which is why
    `#246 (Nothing tells an engine-written DOS record from one edited with
    Gold Box Companion, and conclusions already rest on edited ones)`
    retracted the reading that rested on the same two records.  What would
    revive it: a driven run that gives the `#249` party a bow, saves, fires
    it, and saves again.
    """
    files = _need_items()
    pairs = {}
    for path, data in files.items():
        name = pathlib.Path(path).name.upper()
        if not name.startswith("CHRDAT") or len(name) != 12:
            continue
        pairs.setdefault(pathlib.Path(path).parent, {})[name[6:8]] = data
    for _, slots in pairs.items():
        a, b = slots.get("A2"), slots.get("B2")
        if not (a and b):
            continue
        ra = list(dosbox.items(a))
        rb = list(dosbox.items(b))
        if len(ra) != len(rb):
            continue
        for x, y in zip(ra, rb):
            if x[dosbox.ITEM_NEXT:] == y[dosbox.ITEM_NEXT:]:
                continue
            moved = [
                i for i in range(dosbox.ITEM_TYPE, dosbox.ITEM_SIZE) if x[i] != y[i]
            ]
            if moved == [dosbox.ITEM_QUANTITY]:
                assert x[dosbox.ITEM_QUANTITY] < y[dosbox.ITEM_QUANTITY]
                return
    pytest.skip("needs the player's own two saves of one party")

from __future__ import annotations

"""The DOS debugger harness: the arithmetic, the parsing, and the 64K wrap.

Everything here runs with no emulator and no game files, because everything
here is what a caller gets wrong *before* it launches anything: the segmented
address arithmetic, the chunking that hides `MEMDUMPBIN`'s 64K wrap, the
breakpoint and register lines the log carries, and the environment that keeps
a GTK dialog off the user's desktop.

The one test that boots DOSBox-X is opt-in behind `WISH_DOSBOXX_DRIVE=1`, like
`tests/test_dosbox.py`'s driven run, and re-runs `docs/142-dosbox-x-debugger.md`'s
worked example.  Everything else skips cleanly on a machine with no debugger
build, which is what CI is.
"""


import os
import pathlib
import shutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosboxx  # noqa: E402

# --------------------------------------------------------------------------
# Addresses
# --------------------------------------------------------------------------


def test_a_segmented_address_wraps_its_offset_at_64k():
    """`GetAddress()` masks the offset to 16 bits.  So does `linear()`."""
    assert dosboxx.linear((0x39AC, 0x000E)) == 0x39ACE
    assert dosboxx.linear(0x39ACE) == 0x39ACE
    assert dosboxx.linear((0x1000, 0x1_0004)) == 0x10004
    assert dosboxx.linear((0x1000, 0xFFFF)) == 0x1FFFF


def test_seg_off_keeps_the_offset_in_the_bottom_nibble():
    for lin in (0, 0x39ACE, 0x7FFFF, 0xFFFFF):
        seg, ofs = dosboxx.seg_off(lin)
        assert ofs < 0x10 and (seg << 4) + ofs == lin


# --------------------------------------------------------------------------
# The 64K wrap, which is the trap this module exists to hide
# --------------------------------------------------------------------------


def test_a_megabyte_is_sixteen_calls_and_not_one():
    calls = dosboxx.chunks(0, 0x100000)
    assert len(calls) == 16
    assert all(length == 0x10000 for _, _, length in calls)
    assert [seg for seg, _, _ in calls] == [n << 12 for n in range(16)]


def test_no_chunk_ever_crosses_the_wrap():
    """A chunk that ran past `ofs = 0xFFFF` would silently read segment start.

    That is the whole failure: `MEMDUMPBIN 0 0 100000` returns a full megabyte
    of file, sixteen copies of the first 64K, and says nothing.
    """
    for start, n in ((0, 0x100000), (0x39ACE, 0x2_0000), (0xFFFF0, 0x10), (7, 3)):
        got = 0
        for seg, ofs, length in dosboxx.chunks(start, n):
            assert 0 < length <= 0x10000
            assert ofs + length <= 0x10000
            assert (seg << 4) + ofs == start + got
            got += length
        assert got == n


def test_chunks_of_nothing_and_of_a_negative_length():
    assert dosboxx.chunks(0x1234, 0) == []
    with pytest.raises(ValueError):
        dosboxx.chunks(0, -1)


def test_read_reassembles_the_megabyte_instead_of_repeating_one_segment(tmp_path):
    """`read()` against a fake debugger that wraps exactly as the real one does.

    The stub writes `MEMDUMP.BIN` the way `SaveMemoryBin` does -- offset masked
    to 16 bits, one byte at a time -- so a `read()` that asked for the whole
    megabyte in one call would get sixteen copies of segment zero and pass its
    own length check.  This is the regression the chunking exists to prevent.
    """
    memory = bytes((i * 7 + (i >> 8)) & 0xFF for i in range(0x100000))

    class Stub:
        dir = tmp_path
        sent: list[str] = []

        def dbg(self, cmd, expect=None, timeout=0.0, quiet=0.0):
            self.sent.append(cmd)
            _, seg, ofs, num = cmd.split()
            seg, ofs, num = int(seg, 16), int(ofs, 16), int(num, 16)
            out = bytes(memory[(seg << 4) + ((ofs + x) & 0xFFFF)] for x in range(num))
            (tmp_path / "MEMDUMP.BIN").write_bytes(out)
            return "DEBUG: Memory dump binary success."

    stub = Stub()
    got = dosboxx.XSession.read(stub, 0, 0x100000)
    assert got == memory
    assert len(stub.sent) == 16

    stub.sent = []
    assert dosboxx.XSession.read(stub, 0x39ACE, 4) == memory[0x39ACE:0x39AD2]
    assert stub.sent == ["MEMDUMPBIN 39AC E 4"]


def test_read_says_the_emulator_is_running_when_the_dump_answers_nothing(tmp_path):
    class Silent:
        dir = tmp_path

        def dbg(self, cmd, expect=None, timeout=0.0, quiet=0.0):
            return ""

    with pytest.raises(dosboxx.NotHalted):
        dosboxx.XSession.read(Silent(), 0, 16)


# --------------------------------------------------------------------------
# Commands the parser will silently cut
# --------------------------------------------------------------------------


def test_a_command_longer_than_the_parser_accepts_is_refused():
    """`MAXCMDLEN` is 254 and the debugger truncates without complaining."""
    with pytest.raises(ValueError):
        dosboxx.XSession.dbg(object(), "EV " + "AX " * 200)


def test_a_long_write_is_split_into_lines_that_fit():
    class Recorder:
        def __init__(self):
            self.sent: list[str] = []

        def dbg(self, cmd, expect=None, timeout=0.0, quiet=0.0):
            assert len(cmd) <= dosboxx.MAX_CMD, len(cmd)
            self.sent.append(cmd)
            return "DEBUG: Memory changed (64 bytes)"

    rec = Recorder()
    dosboxx.XSession.write(rec, 0x39ACE, bytes(range(200)))
    assert len(rec.sent) == 4
    assert rec.sent[0].startswith("SM 39AC:E 00 01 02")
    # Every line addresses where the previous one stopped.
    addrs = [dosboxx.linear((int(s.split()[1].split(":")[0], 16),
                             int(s.split()[1].split(":")[1], 16)))
             for s in rec.sent]
    assert addrs == [0x39ACE + 64 * i for i in range(4)]


# --------------------------------------------------------------------------
# What the log says
# --------------------------------------------------------------------------


def test_a_memory_breakpoint_line_parses_to_where_and_what():
    hits = dosboxx.parse_breaks(
        "DEBUG: Memory breakpoint : 39AC:000E - 00 -> 06\n"
        "DEBUG: Memory breakpoint : 39AC:000E - 06 -> 07\n"
    )
    assert [(h.old, h.new) for h in hits] == [(0x00, 0x06), (0x06, 0x07)]
    assert hits[0].addr == 0x39ACE and not hits[0].prot


def test_a_protected_mode_watchpoint_is_marked_as_one():
    hits = dosboxx.parse_breaks("DEBUG: Memory breakpoint (Prot): 0170:0004 - 01 -> 02")
    assert hits[0].prot and hits[0].seg == 0x0170


def test_ev_names_its_own_expressions_so_the_reply_needs_no_context():
    assert dosboxx.parse_ev("EV of 'CS IP AX BX' is:\n2f69 462 938e 3db2") == {
        "CS": 0x2F69, "IP": 0x462, "AX": 0x938E, "BX": 0x3DB2,
    }


def test_ev_answers_nothing_while_the_emulator_runs():
    """Input typed while it runs is thrown away.  That is how `halted()` works."""
    assert dosboxx.parse_ev("") == {}
    assert dosboxx.parse_ev("DEBUG: Memory dump binary success.\n") == {}


def test_only_the_last_ev_reply_counts():
    text = "EV of 'IP' is:\n100\nEV of 'IP' is:\n462\n"
    assert dosboxx.parse_ev(text) == {"IP": 0x462}


def test_an_expression_the_debugger_could_not_parse_raises():
    with pytest.raises(ValueError):
        dosboxx.parse_ev("EV of 'ZZ' is:\nGetHexValue parse error at ZZ")


# --------------------------------------------------------------------------
# Finding a live address with no symbol table
# --------------------------------------------------------------------------


def test_locate_finds_an_array_that_is_not_byte_identical_to_its_file():
    """The recipe `docs/142` used: dump memory, match a save the player holds.

    A live array is never quite the file it came from, so a single `find` is no
    good and a vote over many windows is.  Two bytes differ here, as two did in
    the real run.
    """
    import random

    rng = random.Random(142)
    image = bytearray(rng.randrange(256) for _ in range(0x8000))
    array = bytes(rng.randrange(1, 256) for _ in range(1024))
    base = 0x2340
    image[base:base + len(array)] = array
    image[base + 100] = (array[100] + 1) & 0xFF
    image[base + 101] = (array[101] + 1) & 0xFF

    found = dosboxx.locate(bytes(image), array)
    assert found is not None
    where, votes, matching = found
    assert where == base
    assert matching == len(array) - 2
    assert votes > 10


def test_locate_says_nothing_rather_than_guessing():
    assert dosboxx.locate(bytes(4096), bytes(512)) is None


def test_the_clock_lives_where_the_save_format_says_it_does():
    """`SAVGAM?.DAT` offset 1 is the VM array, two bytes per ECL address."""
    assert dosboxx.vm_slot(dosboxx.VM_BASE_ADDR) == 0
    assert dosboxx.vm_slot(dosboxx.CLOCK_MINUTES) == 2 * 0xC7
    assert dosboxx.vm_slot(0x4900 + dosboxx.VM_SIZE // 2 - 1) < dosboxx.VM_SIZE


# --------------------------------------------------------------------------
# DOSBox-X's line-doubled window, and `capture()` undoing it (#204)
# --------------------------------------------------------------------------
#
# `#204 (The DOSBox-X harness measures the picture panel where it means to
# measure the command bar)`: DOSBox-X draws this game's 320x200 mode into a
# 640x400 window, and every rectangle `tools/dosbox.py` measures -- `BAR`,
# `STATUS` -- is in DOSBox 0.74's 320x200 coordinates.  `XSession.capture()`
# halves a frame back before anything else sees it, which is the fix `#69 (No
# WRITE_UNSOURCED zero has been tested during combat)` was blocked on.


def _double(screen):
    """The way DOSBox-X draws this game's 320x200 mode into a 640x400 window.

    Each source pixel becomes an identical 2x2 block of itself -- exactly what
    `dosboxx.halve()` undoes.
    """
    from tools import dosbox

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


def test_halve_recovers_the_frame_dosboxx_doubled_it_from():
    """`halve()` undoes DOSBox-X's line-doubling exactly, not approximately."""
    import random

    from tools import dosbox

    rng = random.Random(204)
    w, h = 40, 30
    original = dosbox.Screen(w, h, bytes(rng.randrange(256) for _ in range(w * h * 3)))
    doubled = _double(original)
    assert (doubled.width, doubled.height) == (w * 2, h * 2)

    halved = dosboxx.halve(doubled)
    assert (halved.width, halved.height) == (w, h)
    assert halved.px == original.px


def test_halve_leaves_an_odd_sized_frame_alone():
    """Nothing this harness captures is odd-sized; refusing to guess is safer."""
    from tools import dosbox

    screen = dosbox.Screen(3, 3, bytes(27))
    assert dosboxx.halve(screen) is screen


def test_halve_raises_on_an_even_sized_frame_that_is_not_a_replication():
    """`#215 (Nothing checks that a frame halve() is about to halve was really
    line-doubled)`: an even-sized frame whose 2x2 blocks are not one pixel
    must not be silently reduced to a plausible, wrong picture.
    """
    import random

    from tools import dosbox

    rng = random.Random(215)
    w, h = 8, 6
    screen = dosbox.Screen(w, h, bytes(rng.randrange(256) for _ in range(w * h * 3)))
    with pytest.raises(dosboxx.NotLineDoubled):
        dosboxx.halve(screen)


def test_halve_raises_on_rows_that_repeat_horizontally_but_not_vertically():
    """Each row pair must repeat the row above, not only its own columns.

    A row that is itself a valid 2x2-wide doubling but whose partner row is a
    *different* valid doubling is the case the old code -- which only ever
    read the top row of each pair -- could not have caught: it read a clean,
    doubled-looking row and never looked at the one below.
    """
    from tools import dosbox

    w, h = 4, 2
    row0 = bytes([10, 20, 30] * 2 + [40, 50, 60] * 2)  # itself doubled: p0 p0 p1 p1
    row1 = bytes([11, 21, 31] * 2 + [41, 51, 61] * 2)  # itself doubled, different pixels
    screen = dosbox.Screen(w, h, row0 + row1)
    with pytest.raises(dosboxx.NotLineDoubled):
        dosboxx.halve(screen)


def test_capture_halves_a_line_doubled_frame_to_dosbox_074s_size(monkeypatch):
    """`XSession.capture()` must hand back the same size `Session.capture()` does.

    Without this override, `PoolOfRadiance.bar_kind()` reads `BAR` --
    `(0, 192, 320, 7)` -- against a 640x400 DOSBox-X window and measures the
    left half of the picture panel instead of the command bar, so every fight
    stands at the encounter menu pressing nothing until `patience` runs out.
    `dosbox.Session.capture` is stubbed here rather than launching anything --
    it is the one line this override calls, and the whole point is what
    happens to what it returns.
    """
    from tools import dosbox

    original = dosbox.Screen(4, 4, bytes(range(48)))
    doubled = _double(original)
    monkeypatch.setattr(dosbox.Session, "capture", lambda self: doubled)

    session = dosboxx.XSession.__new__(dosboxx.XSession)
    got = session.capture()
    assert (got.width, got.height) == (original.width, original.height)
    assert got.px == original.px


# --------------------------------------------------------------------------
# Which window, and whether anything is in it
# --------------------------------------------------------------------------


def test_the_window_trap_is_one_mechanism_and_not_two():
    """`tools/dosbox.py` has the same three faults (#88), so it has the fix.

    These names stay here because `docs/142-dosbox-x-debugger.md` "The window
    trap" documents them here and this is where they were measured; what they
    must not become is a second implementation.  The assertions that exercise
    them are in `tests/test_dosbox.py`, beside the code.
    """
    from tools import dosbox

    assert dosboxx.BlankCapture is dosbox.BlankCapture
    assert dosboxx.uniform_colour is dosbox.uniform_colour
    assert dosboxx.has_content is dosbox.has_content
    assert dosboxx.candidate_windows is dosbox.candidate_windows
    assert dosboxx.server_on is dosbox.server_on
    assert dosboxx.window_pid is dosbox.window_pid
    # `XSession` inherits the capture and the refusal rather than repeating
    # them; only the title it searches for is its own.
    assert dosboxx.XSession.shot is dosbox.Session.shot
    assert dosboxx.XSession.grab is dosbox.Session.grab
    assert dosboxx.XSession.TITLE != dosbox.Session.TITLE


# --------------------------------------------------------------------------
# Keeping the emulator off the user's desktop
# --------------------------------------------------------------------------


def test_the_environment_unsets_wayland_display(monkeypatch):
    """`DISPLAY=:40` alone is not enough, and a dialog escaped once because of it.

    GTK and Qt children prefer `WAYLAND_DISPLAY`; the `zenity` folder chooser
    DOSBox-X opens when it has no working directory is one of them.
    """
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XAUTHORITY", "/run/user/1000/.mutter-Xwaylandauth")
    env = dosboxx.debug_env(":40")
    assert "WAYLAND_DISPLAY" not in env
    assert "XDG_SESSION_TYPE" not in env
    assert "XAUTHORITY" not in env
    assert env["DISPLAY"] == ":40"
    assert env["GDK_BACKEND"] == "x11"
    assert env["QT_QPA_PLATFORM"] == "offscreen"


def test_the_environment_names_the_terminal_the_function_keys_are_sent_for():
    """ncurses decodes F10 and F11 through terminfo, so `TERM` is load-bearing."""
    assert dosboxx.debug_env(None)["TERM"] == "xterm"


def test_the_config_asks_for_no_working_directory_and_logs_the_debugger(tmp_path):
    conf = dosboxx.CONFIG.format(dir=tmp_path, stem="POOLRAD", exe="START.EXE",
                                 cycles=30000, title=dosboxx.TITLE)
    assert "working directory option=custom" in conf
    assert f"working directory default={tmp_path}" in conf
    # `logfile` is what makes any of this scriptable: it is where every
    # `DEBUG_ShowMsg` line lands, unbuffered.
    assert f"logfile={tmp_path}/dbg.log" in conf
    assert "debuggerrun=debugger" in conf
    assert "core=normal" in conf


# --------------------------------------------------------------------------
# The pool
# --------------------------------------------------------------------------

posix_only = pytest.mark.skipif(sys.platform == "win32",
                                reason="the instance lease is an flock")


def _band(module) -> range:
    """The displays a pool starts from: `SLOTS` of them, from its own base.

    Each module carries its own `SLOTS`, so read each one's rather than
    sharing a width -- the three are 8 today and nothing ties them together.
    """
    return range(module.DISPLAY_BASE, module.DISPLAY_BASE + module.SLOTS)


@posix_only
def test_this_pools_displays_never_collide_with_the_other_two(tmp_path, monkeypatch):
    """:10-:17 are VICE's, :30-:37 are `tools/dosbox.py`'s, :40-:47 are these.

    Asserting the absolute number an idle machine hands out (`:40`) fails
    whenever anything else already answers on it -- another agent's
    `tools/dosboxx.py` session, running exactly as this harness is meant to be
    used (#206).  What must hold regardless of the machine's state is the
    property the docstring already states: this pool's two claims are distinct
    from each other and land outside the other two pools' bands.

    Landing *inside* its own band is deliberately not asserted, because
    `claim` does not promise it: the search is `DISPLAY_BASE + i` for `i` in
    `range(100)`, so a pool whose eight displays are all answering walks past
    the end of its band by design.  What keeps two pools off one display is
    the `/tmp/.wish-x11-<n>.lock` all three take, not the bands.
    """
    from tools import dosbox, instance

    dosbox_band, vice_band = _band(dosbox), _band(instance)

    monkeypatch.setattr(dosboxx, "INST", tmp_path / "inst")
    monkeypatch.setattr(dosboxx, "SLOTS", 2)
    first = dosboxx.claim("one")
    try:
        n1 = int(first.display.removeprefix(":"))
        assert n1 not in dosbox_band and n1 not in vice_band
        assert first.dir != (dosbox.INST / str(first.n))
        second = dosboxx.claim("two")
        n2 = int(second.display.removeprefix(":"))
        assert n2 not in dosbox_band and n2 not in vice_band
        assert n1 != n2
        with pytest.raises(dosbox.PoolFull):
            dosboxx.claim("three")
        second.release()
    finally:
        first.release()


def test_a_machine_with_only_the_debugger_build_can_open_a_session(tmp_path,
                                                                   monkeypatch):
    """This harness never launches DOSBox 0.74, so it must not require it (#73).

    `XSession.__init__` runs `tools/dosbox.py`'s `require_tools()`, whose list
    names `dosbox`; a machine carrying only the debugger build was refused a
    session with `not installed: dosbox`, about an emulator nothing here starts.
    `require_debugger` is stubbed because the debugger build is what the machine
    under test *has*, and CI has neither.
    """
    monkeypatch.setattr(
        shutil, "which",
        lambda name, *a, **k: None if name == "dosbox" else f"/usr/bin/{name}")
    monkeypatch.setattr(dosboxx, "require_debugger", lambda: None)
    assert "dosbox" not in dosboxx.missing_tools()
    slot = dosboxx.Slot(n=0, dir=tmp_path, _fd=-1, _display_num=40)
    session = dosboxx.XSession(slot, tmp_path / "POOLRAD")
    assert session.display == ":40"


def test_the_debugger_harness_still_needs_the_tools_it_does_run():
    """Narrowing the list is not emptying it: Xvfb, xdotool and import stay."""
    from tools import dosbox

    assert set(dosboxx.XSession.TOOLS) < set(dosbox.Session.TOOLS)
    assert set(dosboxx.XSession.TOOLS) == {"Xvfb", "xdotool", "import"}


def test_a_machine_with_no_debugger_build_says_so_rather_than_failing_later():
    why = dosboxx.unavailable()
    assert why is None or "not installed" in why or "no debugger" in why


# --------------------------------------------------------------------------
# The worked example, opt-in
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("WISH_DOSBOXX_DRIVE") != "1",
    reason="set WISH_DOSBOXX_DRIVE=1 to boot DOSBox-X; it takes about four minutes",
)
def test_the_harness_reproduces_the_clock_tick_docs_142_recorded():
    """Every number here is one `docs/142-dosbox-x-debugger.md` already carries.

    The base address is deliberately not asserted: it is where DOS happened to
    load that build with that config, not a finding.  What is asserted is the
    recipe -- the array is found, the live byte agrees with the save, the
    spurious `00 ->` hit is absorbed, and the real tick is caught.
    """
    if dosboxx.unavailable():
        pytest.skip(dosboxx.unavailable())
    try:
        game = __import__("tools.dosbox", fromlist=["dosbox"]).find_game("POOLRAD")
    except FileNotFoundError as e:
        pytest.skip(str(e))
    if not (game / "SAVE" / "SAVGAMJ.DAT").is_file():
        pytest.skip("needs the player's slot J")

    out = dosboxx.clock_demo("J")
    assert out["attached"]
    assert out["dumped"] == 0x100000
    assert out["votes"] > 50
    assert out["live"] == out["in_save"]
    assert out["absorbed"].startswith("Break(") and "old=0," in out["absorbed"]
    old, new = out["tick"].split()[1], out["tick"].split()[3]
    assert int(new, 16) == int(old, 16) + 1
    assert out["after_write"] == 9

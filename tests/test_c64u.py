"""`tools/c64u.py` without a C64 Ultimate on the network.

Every test here drives the wrapper through its `runner` seam -- a callable
taking `(argv, binary)` -- so what is under test is the arguments it builds and
the rules it enforces, not the device.  Nothing in this file opens a socket.

The one test that wants hardware is opt-in twice over: `$C64U_HARDWARE_TESTS`
must be set *and* a device must answer.  A pytest run must never reach out and
touch a machine somebody is playing on, and CI has no C64 Ultimate at all.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import c64u  # noqa: E402


class Fake:
    """A `c64u` CLI that never runs: records argv, replies from a table."""

    def __init__(self, replies=None, fail_on=None):
        self.calls: list[list[str]] = []
        self.replies = replies or {}
        self.fail_on = fail_on

    def reply_for(self, argv):
        for prefix, value in self.replies.items():
            if argv[-len(prefix):] == list(prefix) or _has(argv, prefix):
                return value
        return None

    def __call__(self, argv, binary):
        self.calls.append(list(argv))
        if self.fail_on and _has(argv, self.fail_on):
            return subprocess.CompletedProcess(argv, 1, b"" if binary else "",
                                               b"nope" if binary else "nope")
        out = self.reply_for(argv)
        if out is None:
            out = b"" if binary else "{}"
        if binary and isinstance(out, str):
            out = out.encode()
        if not binary and isinstance(out, bytes):
            out = out.decode()
        return subprocess.CompletedProcess(argv, 0, out, b"" if binary else "")

    def issued(self, *words):
        return [c for c in self.calls if _has(c, words)]


def _has(argv, words):
    words = list(words)
    return any(argv[i:i + len(words)] == words
               for i in range(len(argv) - len(words) + 1))


def device(**kw):
    fake = kw.pop("fake", None) or Fake(**kw)
    return c64u.Ultimate(host="10.0.0.1", cli="/nonexistent/c64u", runner=fake), fake


# -- the arguments it builds ------------------------------------------------


def test_the_host_goes_in_front_of_the_subcommand():
    """`--host` is a global flag; behind the subcommand cobra rejects it."""
    dev, _ = device()
    assert dev.argv("info") == ["/nonexistent/c64u", "--host", "10.0.0.1", "info"]


def test_with_no_cli_installed_nothing_is_attempted(monkeypatch):
    """A machine with no `c64u` binary skips rather than producing a confusing
    connection error, so `available()` has to answer False rather than raise."""
    monkeypatch.setattr(c64u, "find_cli", lambda: None)
    dev = c64u.Ultimate(runner=Fake())
    with pytest.raises(c64u.NotReachable):
        dev.argv("info")
    assert dev.available() is False


def test_write_mem_sends_the_hex_as_a_single_argument():
    """Spaces split the hex into several argv entries and the CLI refuses with
    `accepts 2 arg(s), received 6`."""
    dev, fake = device()
    dev.write_mem(0xC000, bytes([0x78, 0xA9, 0x35, 0x85, 0x01]))
    call = fake.issued("machine", "write-mem")[0]
    assert call[-2:] == ["c000", "78a9358501"]


def test_more_than_128_bytes_never_reaches_the_wire():
    dev, fake = device()
    with pytest.raises(ValueError, match="128"):
        dev.write_mem(0xC000, bytes(129))
    assert fake.calls == []


# -- the commands it refuses to issue --------------------------------------


@pytest.mark.parametrize("words", sorted(c64u.REFUSED))
def test_the_commands_that_are_not_ours_are_stopped_before_the_wire(words):
    """Six commands, each of which changes the device rather than reading it:
    two persist past power-off, one cannot be undone, one powers the machine
    down, and two put a window on the desktop."""
    dev, fake = device()
    with pytest.raises(c64u.Refused):
        dev.run(*words)
    assert fake.calls == []


def test_an_ordinary_config_read_is_not_refused():
    """The refusal is per command, not a ban on the whole `config` tree."""
    dev, fake = device()
    dev.run("config", "export")
    assert len(fake.calls) == 1


# -- reading ----------------------------------------------------------------


def test_a_read_asks_for_raw_bytes_and_the_length_it_wants():
    dev, fake = device(replies={("read-mem",): b"\x01\x02\x03\x04"})
    assert dev.read_mem(0x4900, 4) == b"\x01\x02\x03\x04"
    call = fake.issued("machine", "read-mem")[0]
    assert call[-4:] == ["4900", "--length", "4", "--raw"]


def test_a_short_read_is_an_error_rather_than_short_bytes():
    """Silently returning fewer bytes than asked for would shift every offset
    after it, and the reader would blame the game."""
    dev, _ = device(replies={("read-mem",): b"\x01\x02"})
    with pytest.raises(c64u.UltimateError, match="asked for 4 bytes, got 2"):
        dev.read_mem(0x4900, 4)


def test_a_vic_colour_register_reads_back_with_its_top_bits_set():
    """$D020 returns FE, not 0E: the register is four bits wide and the unused
    top four float high.  Comparing against VICE without masking is a
    difference that is entirely ours."""
    dev, _ = device(replies={("read-mem",): b"\xfe"})
    raw = dev.read_mem(0xD020, 1)[0]
    assert raw == 0xFE
    assert c64u.mask_vic_colour(raw) == 14


def test_a_poll_reads_exactly_the_blocks_the_automapper_reads():
    """Two blocks for Pool of Radiance: the $4900 payload and the $8300 roster
    page.  A hardware reading is only comparable with a VICE one if it is the
    same ranges."""
    from automap.live import memory_blocks
    want = memory_blocks(None)
    dev, fake = device(replies={("read-mem",): b"\x00" * max(n for _, n in want)})
    dev.read_mem = lambda a, n: b"\x00" * n  # length check is tested above
    blocks = dev.poll()
    assert [len(b) for b in blocks] == [n for _, n in want]
    assert want[0] == (0x4900, 0x1C00)


# -- pausing ----------------------------------------------------------------


def test_the_machine_is_resumed_even_when_the_dump_fails(tmp_path):
    """A failure mid-dump must not leave a paused machine on somebody's desk."""
    dev, fake = device(fake=Fake(fail_on=("read-mem",)))
    with pytest.raises(c64u.UltimateError):
        dev.dump(0x0000, 0xFFFF, tmp_path / "mem.bin")
    assert fake.issued("machine", "pause")
    assert fake.issued("machine", "resume")


def test_a_dump_is_taken_paused_and_in_that_order(tmp_path):
    dev, fake = device()
    (tmp_path / "mem.bin").write_bytes(b"x")
    dev.dump(0x0000, 0x00FF, tmp_path / "mem.bin", banking="default 37")
    order = [c for c in fake.calls if _has(c, ("machine",))]
    assert _has(order[0], ("pause",))
    assert _has(order[1], ("read-mem",))
    assert _has(order[2], ("resume",))


def test_a_dump_records_the_bank_state_it_was_taken_in(tmp_path):
    """DMA follows the CPU's current banking and `$01` reads as the RAM under
    the processor port, so the dump cannot say for itself whether `$A000` was
    BASIC ROM or the RAM beneath it.  The sidecar is the only record there is."""
    dev, _ = device()
    (tmp_path / "mem.bin").write_bytes(b"x")
    dev.dump(0xA000, 0xA0FF, tmp_path / "mem.bin", banking="ROMs out, $01 = $35")
    side = json.loads((tmp_path / "mem.bin.json").read_text())
    assert side["banking"] == "ROMs out, $01 = $35"
    assert side["start"] == 0xA000 and side["end"] == 0xA0FF
    assert "banking" in side["banking_note"]


# -- the keyboard experiment ------------------------------------------------


def test_a_drained_buffer_reads_as_the_kernal_path():
    """`sendkey` writes PETSCII at $0277 and the count at $00C6.  If something
    calls GETIN the count returns to zero, and that stage can be driven."""
    counts = iter([b"\x00", b"\x01", b"\x00"])
    dev, _ = device(fake=Fake())
    dev.read_mem = lambda a, n: next(counts)
    out = dev.probe_key(" ", settle=0)
    assert out["drained"] is True
    assert "sendkey can drive" in out["reading"]


def test_a_buffer_that_stays_full_reads_as_the_matrix():
    """A program polling $DC00/$DC01 never sees the buffer, so the count sits
    there.  This is the negative result the issue is looking for, and it is a
    real answer: the Ultimate could then be read but not driven."""
    counts = iter([b"\x00", b"\x01", b"\x01"])
    dev, _ = device(fake=Fake())
    dev.read_mem = lambda a, n: next(counts)
    out = dev.probe_key(" ", settle=0)
    assert out["drained"] is False
    assert "matrix" in out["reading"]


# -- disks ------------------------------------------------------------------


def test_the_boot_disk_is_found_through_the_environment(tmp_path, monkeypatch):
    for name in ("POOL1.D64", "POOL2.D64", "POOLBOOT.D64"):
        (tmp_path / name).write_bytes(b"")
    monkeypatch.setenv("POR_DISKS", str(tmp_path))
    assert c64u.boot_disk() == str(tmp_path / "POOL1.D64")
    assert c64u.boot_disk(number=2) == str(tmp_path / "POOL2.D64")


def test_a_missing_disk_says_where_it_looked(tmp_path, monkeypatch):
    monkeypatch.setenv("POR_DISKS", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="POR_DISKS"):
        c64u.boot_disk()


def test_no_path_to_the_players_disks_is_written_into_the_source():
    """Every other tool here reads `$POR_DISKS` then `find_disks()`; a fourth
    way, or a path in the source, is useless to everybody but one machine."""
    text = pathlib.Path(c64u.__file__).read_text()
    assert "/home/" not in text
    assert "POR_DISKS" in text and "find_disks" in text


def test_staging_copies_out_of_the_players_directory(tmp_path):
    """The player's disks are read-only to everything in this repository, so a
    mount goes from a copy under `work/` -- the same rule `tools/session.py`
    follows when it stages SIDE1.D64 for VICE."""
    src = tmp_path / "disks"
    src.mkdir()
    (src / "POOL1.D64").write_bytes(b"disk")
    into = tmp_path / "work"
    staged = c64u.stage(src / "POOL1.D64", into)
    assert pathlib.Path(staged).parent == into
    assert pathlib.Path(staged).read_bytes() == b"disk"
    assert sorted(p.name for p in src.iterdir()) == ["POOL1.D64"]


def test_a_mount_is_read_only_unless_asked_otherwise():
    dev, fake = device()
    dev.mount("/tmp/POOL1.D64")
    assert fake.issued("drives", "mount-upload")[0][-2:] == ["--mode", "readonly"]


# -- the command line -------------------------------------------------------


def test_disks_needs_no_device(tmp_path, monkeypatch, capsys):
    (tmp_path / "POOL1.D64").write_bytes(b"")
    monkeypatch.setenv("POR_DISKS", str(tmp_path))
    assert c64u.main(["disks"]) == 0
    assert "POOL1.D64" in capsys.readouterr().out


def test_no_device_exits_three_rather_than_one(monkeypatch, capsys):
    """A script has to tell "no hardware" from "the hardware disagreed"; one
    is a skip and the other is a finding."""
    monkeypatch.setattr(c64u.Ultimate, "available", lambda self: False)
    assert c64u.main(["info"]) == c64u.NO_DEVICE
    assert "no C64 Ultimate answered" in capsys.readouterr().err


# -- the one test that wants hardware ---------------------------------------


def _hardware():
    if os.environ.get("C64U_HARDWARE_TESTS", "").lower() not in ("1", "true",
                                                                "yes", "on"):
        return None
    dev = c64u.Ultimate()
    return dev if dev.available() else None


@pytest.mark.skipif(_hardware() is None,
                    reason="set C64U_HARDWARE_TESTS=1 with a device reachable")
def test_the_raster_counter_moves_between_two_reads():
    """The only claim worth a hardware test here: a DMA read reaches live I/O.
    `README.md:287` in the c64u repo says DMA writes reach only RAM; two reads
    of $D012 coming back different disproves it for reads at least.

    Read-only, and it still does not run unless somebody opts in: the machine
    is on a desk and may have somebody playing on it."""
    dev = _hardware()
    seen = {dev.read_mem(0xD012, 1)[0] for _ in range(8)}
    assert len(seen) > 1, f"$D012 never moved across 8 reads: {seen}"

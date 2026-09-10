"""`automap.amiga.WinuaePipe`: the route that reads WinUAE without stopping it.

Every test here replaces the one thing that touches Windows -- the `runner`
callable -- with a fake that answers the shape the real guest was measured
answering on 2026-09-08 against WinUAE 6.0.3: `<<connect_ms>>`, one `<<reply>>`
a command carrying base64 of the debugger's own text, then the `<<name>>`
markers for any dumped file.

What is deliberately **not** tested here is that the pipe exists, that session 0
can open it, or that a read leaves the machine running. Those are measurements
on a live emulator and no fake can stand in for one; they are on
`#37 (Automap the Amiga version, not just the C64)`.
"""

from __future__ import annotations

import base64
import re

import pytest

from automap import amiga

CURSE = amiga.MACHINES["curse-of-the-azure-bonds"]
BASE = 0xC4E270


class PipeGuest:
    """A fake Windows guest with a pipe on the other side of it."""

    def __init__(self, memory: dict[int, bytes] | None = None):
        self.memory = dict(memory or {})
        self.scripts: list[str] = []
        #: Made True to answer as a guest whose `S` wrote nothing at all.
        self.silent = False

    def peek(self, addr: int, length: int) -> bytes:
        out = bytearray(length)
        for base, blob in self.memory.items():
            for i in range(length):
                if base <= addr + i < base + len(blob):
                    out[i] = blob[addr + i - base]
        return bytes(out)

    # -- reading the script the transport built ---------------------------

    @staticmethod
    def commands(script: str) -> list[str]:
        line = [ln for ln in script.splitlines() if ln.startswith("$cmds=@(")]
        assert line, "the script sent no commands"
        return [base64.b64decode(b).decode("ascii")
                for b in re.findall(r"'([A-Za-z0-9+/=]+)'", line[0])]

    @staticmethod
    def repeat(script: str) -> int:
        return int(re.search(r"\$r -lt (\d+)", script).group(1))

    @staticmethod
    def fetched(script: str) -> list[tuple[str, str]]:
        names = [ln.split("<<")[1].split(">>")[0]
                 for ln in script.splitlines()
                 if ln.startswith("Write-Output '<<")
                 and "<<end>>" not in ln]
        paths = [ln.split("Test-Path -LiteralPath '")[1].split("'")[0]
                 for ln in script.splitlines()
                 if "Test-Path -LiteralPath '" in ln]
        return list(zip(names, paths))

    # -- answering --------------------------------------------------------

    def __call__(self, argv, timeout):
        script = base64.b64decode(argv[-1].split()[-1]).decode("utf-16-le")
        self.scripts.append(script)
        out = ["<<connect_ms>> 5"]
        dumps: dict[str, bytes] = {}
        for _ in range(self.repeat(script)):
            for command in self.commands(script):
                assert command.startswith("DBG "), command
                out.append("<<reply>> 1.5 " + base64.b64encode(
                    self._answer(command[4:], dumps).encode("latin-1")
                ).decode("ascii"))
        for name, path in self.fetched(script):
            blob = dumps.get(path)
            out.append(f"<<{name}>>")
            out.append("MISSING" if blob is None or self.silent
                       else base64.b64encode(blob).decode("ascii"))
        out.append("<<end>>")
        return "\r\n".join(out) + "\r\n"

    def _answer(self, command: str, dumps: dict[str, bytes]) -> str:
        if command.startswith("S "):
            _s, path, addr, length = command.split()
            blob = self.peek(int(addr, 16), int(length, 16))
            dumps[path] = blob
            return (f"Wrote {int(addr, 16):08X} - "
                    f"{int(addr, 16) + len(blob) - 1:08X} "
                    f"({len(blob)} bytes) to '{path}'.\n\x00")
        if command.startswith("m "):
            bits = command.split()
            # Both numbers are hex: `debug.cpp`'s `m` reads each with
            # `readhex`, and a fake that read the count as decimal would let a
            # decimal caller pass.
            addr = int(bits[1], 16)
            lines = int(bits[2], 16) if len(bits) > 2 else 20
            text = ""
            for row in range(lines):
                at = addr + row * 16
                blob = self.peek(at, 16)
                words = " ".join(blob[i:i + 2].hex().upper()
                                 for i in range(0, 16, 2))
                chars = "".join(chr(b) if 32 <= b < 127 else "."
                                for b in blob)
                text += f"{at:08X} {words}  {chars}\n"
            return text + "\x00"
        return "Unknown command\n\x00"


def pipe(memory=None, guest=None, **kwargs):
    guest = guest or PipeGuest(memory)
    return amiga.WinuaePipe(runner=guest, **kwargs), guest


# -- the framing --------------------------------------------------------------


def test_the_command_goes_down_as_8_bit_text_with_no_byte_order_mark():
    """A UTF-16 request takes WinUAE's `_tcscpy` reply path, which bounds a
    16384-byte buffer at 16384 characters -- `uaeipc.cpp`. The 8-bit path is
    the bounded one."""
    p, guest = pipe({0: b"\x00" * 16})
    p.send(["m 0 1"])
    script = guest.scripts[0]
    assert PipeGuest.commands(script) == ["DBG m 0 1"]
    assert "0xFF" not in script and "Unicode" not in script
    # One byte of NUL after the text, and nothing else: `parsemessage` trims
    # and then compares the whole message.
    assert "$msg=New-Object byte[] ($b.Length+1)" in script


def test_a_reply_keeps_its_bytes_and_loses_its_terminator():
    p, _guest = pipe({0: bytes(range(16))})
    (_cmd, reply), = p.send(["m 0 1"])
    assert reply.startswith("00000000 0001 0203")
    assert "\x00" not in reply


def test_the_debugger_says_it_did_not_know_the_command():
    p, _guest = pipe()
    (_cmd, reply), = p.send(["Q"])
    assert amiga.RE_UNKNOWN.search(reply)


# -- what must never be sent --------------------------------------------------


@pytest.mark.parametrize("command", [
    "g", "g c00000", "t", "b 1 c00000", "w 1 c00000 4 W", "f c00000",
    # `debug_line` splits on unquoted `;` and runs every piece in the same
    # message, so a read with a go hidden behind a semicolon used to pass a
    # guard that read only the first word of the string.
    "m 0 1;g", "m 0 1 ; g c00000", "S dump 0 10;t", "m 0 1;;b 1 c00000",
    # `ignore_ws` skips anything `_istspace`, so the separator need not be a
    # space -- and `split(" ")` does not agree with that.
    "g\tc00000", "g\nc00000", "m 0 1;g\tc00000",
])
def test_a_command_that_could_open_a_console_is_refused(command):
    """`activate_debugger()` calls `open_console()`, and that console is a
    window in front of whoever is playing.

    **Tokenised the way `debug.cpp` tokenises.** The first six are the plain
    forms; the rest are the two ways past a guard that read the first word of
    the whole string, found in review on 2026-09-08 and both reachable through
    the public `send()` and through `tools/winuaepipe.py send`.
    """
    p, guest = pipe()
    with pytest.raises(ValueError, match="console"):
        p.send([command])
    assert guest.scripts == [], "nothing may reach the guest"


def test_ipc_quit_is_refused_by_name():
    """`uaeipc.cpp:38`: it quits the emulator, mid-game."""
    p, _guest = pipe()
    with pytest.raises(ValueError, match="quits the emulator"):
        p.send(["IPC_QUIT"])


# -- failures -----------------------------------------------------------------


def test_a_pipe_that_will_not_open_reports_the_win32_number():
    """The number is the whole diagnosis: 2 is no emulator running, 5 is a
    security descriptor keeping this process out, 231 is somebody else's
    client already connected."""
    def refuse(argv, timeout):
        return ("<<error>> System.UnauthorizedAccessException\r\n"
                "<<message>> Access to the path is denied.\r\n"
                "<<hresult>> 0x80070005\r\n"
                "<<win32>> 5\r\n<<end>>\r\n")

    p = amiga.WinuaePipe(runner=refuse)
    with pytest.raises(amiga.PipeError, match="Win32 5"):
        p.send(["m 0 1"])


def test_a_pipe_error_is_a_not_connected_so_the_window_keeps_waiting():
    assert issubclass(amiga.PipeError, amiga.GuestError)
    from automap.target import NotConnected
    assert issubclass(amiga.PipeError, NotConnected)


def test_a_guest_that_replied_to_fewer_commands_than_it_was_sent_is_an_error():
    def half(argv, timeout):
        return "<<connect_ms>> 5\r\n<<end>>\r\n"

    p = amiga.WinuaePipe(runner=half)
    with pytest.raises(amiga.PipeError, match="2 commands and the guest"):
        p.send(["m 0 1", "m 4 1"])


def test_a_script_that_never_reached_its_end_is_an_error():
    p = amiga.WinuaePipe(runner=lambda argv, timeout: "nothing at all")
    with pytest.raises(amiga.PipeError, match="did not finish"):
        p.send(["m 0 1"])


def test_a_reply_that_never_came_is_named_as_that():
    def hang(argv, timeout):
        return "<<connect_ms>> 5\r\n<<timeout>>\r\n<<end>>\r\n"

    p = amiga.WinuaePipe(runner=hang)
    with pytest.raises(amiga.PipeError, match="never replied"):
        p.send(["m 0 1"])


# -- the dump format ----------------------------------------------------------


def test_a_memory_dump_is_read_by_address_rather_than_by_position():
    """The debugger rounds the address it was given down to an even one, so a
    reader that assumed the first line began where it asked would be off by
    one whenever it asked for an odd address."""
    got = amiga.parse_memory_dump(
        "00C00392 0000 D6B0 0010 0010 0000 FFFF 0000 0000  ................\n")
    assert got[0xC00392] == 0x00 and got[0xC00394] == 0xD6
    assert got[0xC00395] == 0xB0
    assert len(got) == 16


def test_the_character_column_is_not_mistaken_for_hex():
    """It holds spaces, so it cannot be separated from the hex by whitespace;
    the reader takes the eight words and stops."""
    got = amiga.parse_memory_dump(
        "00000000 4142 4344 4546 4748 494A 4B4C 4D4E 4F50  ABCDEFGHIJKLMNOP")
    assert bytes(got[a] for a in sorted(got)) == b"ABCDEFGHIJKLMNOP"


def test_an_odd_address_comes_back_from_the_line_it_is_on():
    p, _guest = pipe({0xC00000: bytes(range(32))})
    assert p.memory(0xC00003, 4) == bytes([3, 4, 5, 6])


def test_the_line_count_goes_down_in_hex_like_the_address():
    """`debug.cpp`'s `m` reads it with `readhex`, so a decimal count asks for
    more lines than were wanted and spends more of the budget below."""
    p, guest = pipe({0xC00000: bytes(32) * 16})
    p.memory(0xC00000, 256)                      # 16 lines
    assert PipeGuest.commands(guest.scripts[0]) == ["DBG m c00000 10"]


def test_a_dump_cut_off_by_winuaes_line_counter_says_so():
    """After about 500 dumped lines `m` prints one line and no more, for the
    life of the emulator process: `debug_linecounter` is reset only at the
    interactive prompt, which this route never opens. The message has to name
    that, or it reads as a broken parser."""
    class Saturated(PipeGuest):
        def _answer(self, command, dumps):
            return super()._answer(command, dumps).split("\n")[0] + "\n\x00"

    p, _guest = pipe(guest=Saturated({0xC00000: bytes(range(32))}))
    with pytest.raises(amiga.PipeError, match="line and no more"):
        p.memory(0xC00000, 32)


def test_a_read_too_big_for_one_reply_is_refused_rather_than_truncated():
    """A reply is capped near 16 KB, which is about 3 KB of memory through
    `m`. Past that the caller wants `S` to a file."""
    p, _guest = pipe()
    with pytest.raises(ValueError, match="16 KB reply"):
        p.memory(0xC00000, 4096)


# -- as a transport for AmigaTarget -------------------------------------------


def test_the_pipe_does_not_halt_the_machine_and_says_so():
    assert amiga.WinuaePipe.halts_machine is False
    assert amiga.WinuaeDebugger.halts_machine is True


def test_a_target_over_the_pipe_never_sends_a_resume():
    """There is no halt to resume, and `g` is one of the commands that can put
    a console in front of the player."""
    p, guest = pipe({0xC00000: b"\x01\x02\x03\x04"})
    t = amiga.AmigaTarget(p, CURSE, BASE)
    assert t.halts_on_read is False
    assert t.read(0xC00000, 4) == b"\x01\x02\x03\x04"
    assert len(guest.scripts) == 1, "a read must not cost two round trips"
    sent = PipeGuest.commands(guest.scripts[0])
    assert not any(c == "DBG g" for c in sent), sent
    assert sent[0].startswith("DBG S ")


def test_a_target_over_the_console_still_resumes():
    """The older route halts the machine at its `>` prompt, so a batch that
    did not resume would leave the emulator stopped -- `#95`."""
    from tests.test_amigatarget import Guest, target
    t, guest = target({0xC00000: b"\x01\x02\x03\x04"})
    assert t.halts_on_read is True
    t.read(0xC00000, 4)
    assert Guest._batch(guest.calls[0]).splitlines()[-1] == "g"


def test_several_blocks_are_one_round_trip_over_the_pipe():
    p, guest = pipe({0xC00000: bytes(range(32))})
    t = amiga.AmigaTarget(p, CURSE, BASE)
    first, second = t.read_blocks([(0xC00000, 4), (0xC00010, 4)])
    assert first == bytes(range(4)) and second == bytes(range(16, 20))
    assert len(guest.scripts) == 1


def test_a_dump_the_guest_could_not_write_is_named_rather_than_returned_short():
    p, guest = pipe({0xC00000: b"\x01\x02\x03\x04"})
    guest.silent = True
    t = amiga.AmigaTarget(p, CURSE, BASE)
    with pytest.raises(amiga.GuestError, match="wrote no dump"):
        t.read(0xC00000, 4)


def test_the_data_hunk_is_found_through_the_pipe_like_any_other_read():
    memory = {0xC00000 + CURSE.anchor_offset + 0x1000: CURSE.anchor}
    p, _guest = pipe(memory)
    t = amiga.AmigaTarget(p, CURSE)
    assert t.locate() == 0xC01000


# -- where it runs ------------------------------------------------------------


def test_the_local_route_runs_powershell_and_not_ssh():
    """Wish and WinUAE on one Windows machine is the ordinary case: a local
    pipe, no network and no session boundary."""
    seen = []

    def watch(argv, timeout):
        seen.append(argv)
        return "<<connect_ms>> 1\r\n<<end>>\r\n"

    p = amiga.WinuaePipe(runner=watch, connection="local")
    with pytest.raises(amiga.PipeError):
        p.send(["m 0 1"])
    assert seen[0][0] == "powershell" and "winvm" not in seen[0]


def test_the_ssh_route_is_one_winvm_call():
    p, guest = pipe({0: b"\x00" * 16})
    p.send(["m 0 1"])
    assert len(guest.scripts) == 1


def test_a_connection_that_is_neither_is_refused():
    with pytest.raises(ValueError, match="neither"):
        amiga.WinuaePipe(connection="telnet")


def test_the_pipe_name_is_settable_because_a_second_winuae_gets_another():
    """`createIPC` appends `_1`, `_2` and so on when the name is taken."""
    p, guest = pipe({0: b"\x00" * 16}, pipe="WinUAE_1")
    p.send(["m 0 1"])
    assert "'.','WinUAE_1','InOut'" in guest.scripts[0]


def test_a_semicolon_inside_quotes_is_not_a_second_command():
    """`debug_line` tracks quotes, so a filename with a `;` in it is one
    piece and must not be refused -- a guard that splits blindly would make
    `S` unusable on such a path."""
    p, guest = pipe()
    p.send(['S "dump;1" 0 10'])
    assert guest.scripts, "the command was refused and should not have been"

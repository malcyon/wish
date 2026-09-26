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
    the public `send()` and through `tools/amiga/winuaepipe.py send`.
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
    from support.amigatarget import Guest, target
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


# -- a floppy insert ----------------------------------------------------------

DISK3 = "C:\\Amiga\\Disks\\wish679-h-disk3.adf"


class CfgGuest:
    """Records every message the script sends and answers each with a reply."""

    def __init__(self, reply: str = "ok\n\x00"):
        self.messages: list[str] = []
        self.reply = reply

    def __call__(self, argv, timeout):
        script = base64.b64decode(argv[-1].split()[-1]).decode("utf-16-le")
        found = PipeGuest.commands(script)
        self.messages += found
        out = ["<<connect_ms>> 5"]
        out += ["<<reply>> 1.0 " + base64.b64encode(
            self.reply.encode("latin-1")).decode("ascii") for _ in found]
        out.append("<<end>>")
        return "\r\n".join(out) + "\r\n"


# -- a floppy change, through the lane script's guest verbs -------------------

HOLDER = "wish679-abc123def456"
DISK_A = f"C:\\Amiga\\Disks\\wish679-{HOLDER}-probeA.adf"
DISK_B = f"C:\\Amiga\\Disks\\wish679-{HOLDER}-probeB.adf"
DISK_C = f"C:\\Amiga\\Disks\\wish679-{HOLDER}-probeC.adf"
SHA_B = "b" * 64


def nul(text: str) -> bytes:
    return text.encode("latin-1") + b"\0"


def query(path: str) -> bytes:
    return nul("200 \n" + path) if path else nul("404")


def dump(mode0: str, mode1: str) -> bytes:
    lines = [f"DEBUG: drive {n} motor off cylinder  0 sel no {mode} mfmpos 0/12668"
             for n, mode in ((0, mode0), (1, mode1))]
    return nul("\n".join(["DEBUG: cia dump"] + lines))


def read_lines(seq, ms, path0, path1, mode0, mode1, **raw):
    """The three `<<r>>` lines of one read of both drives."""
    raws = {"q0": query(path0), "q1": query(path1), "dbg": dump(mode0, mode1)}
    raws.update(raw)
    return [f"<<r>> {seq} {label} {ms + i} " + base64.b64encode(blob).decode("ascii")
            for i, (label, blob) in enumerate(raws.items())]


def guest_output(status, reads=(), setter=b"404\0", tags=True):
    lines = [status]
    if tags:
        lines += ["<<connect_ms>> 70", "<<pid>> 4242",
                  "<<started>> 2026-09-26T10:00:00.0000000+00:00",
                  "<<exe>> C:\\Program Files\\WinUAE\\winuae64.exe",
                  "<<server_pid>> 4242"]
    for seq, ms, kwargs in reads:
        lines += read_lines(seq, ms, **kwargs)
        if seq == 0 and setter is not None:
            lines.append(f"<<r>> 0 set {ms + 10} "
                         + base64.b64encode(setter).decode("ascii"))
    lines.append("<<end>>")
    return "\r\n".join(lines) + "\r\n"


def state(path0=DISK_A, path1=DISK_C, mode0="rw", mode1="rw"):
    return {"path0": path0, "path1": path1, "mode0": mode0, "mode1": mode1}


def swap_reads(target=DISK_B, other_before=DISK_C):
    """DF0 swapped from A to B as the source predicts it: named, empty, then loaded twice."""
    steps = [
        (0, 100, state()),
        (1, 400, state(path0=target, mode0="ro")),
        (2, 650, state(path0=target, mode0="ro")),
        (3, 900, state(path0=target, mode0="rw")),
        (4, 1150, state(path0=target, mode0="rw")),
    ]
    return steps


class LaneGuest:
    """Answers a `winuae.ps1` verb with a canned output and records every argv."""

    def __init__(self, output="", error=None):
        self.output = output
        self.error = error
        self.calls: list[list[str]] = []

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        if self.error:
            raise self.error
        return self.output


def insert(guest, drive=0, path=DISK_B, sha=SHA_B, holder=HOLDER, **kw):
    return amiga.WinuaePipe(runner=guest, **kw).insert_floppy(drive, path, holder, sha)


def test_a_floppy_change_runs_the_lane_verb_with_the_holder_drive_path_and_hash():
    guest = LaneGuest(guest_output("ok inserted drive=0 polls=4", swap_reads()))
    insert(guest)
    assert guest.calls == [[
        "winvm", "ssh", "powershell -NoProfile -ExecutionPolicy Bypass -File "
        f"C:\\Amiga\\winuae.ps1 insert -Holder {HOLDER} 0 {DISK_B} {SHA_B}"]]


def test_a_local_floppy_change_runs_powershell_without_ssh():
    guest = LaneGuest(guest_output("ok inserted drive=0 polls=4", swap_reads()))
    insert(guest, connection="local")
    assert guest.calls[0][:6] == ["powershell", "-NoProfile", "-ExecutionPolicy",
                                  "Bypass", "-File", "C:\\Amiga\\winuae.ps1"]
    assert guest.calls[0][6:] == ["insert", "-Holder", HOLDER, "0", DISK_B, SHA_B]


def test_a_claim_token_goes_down_as_its_own_argument():
    guest = LaneGuest(guest_output("ok inserted drive=0 polls=4", swap_reads()))
    amiga.WinuaePipe(runner=guest).insert_floppy(0, DISK_B, HOLDER, SHA_B, token="0123456789ab")
    assert "-Token 0123456789ab" in guest.calls[0][2]


def test_a_swap_is_proved_by_the_poll_and_keeps_every_raw_reply():
    guest = LaneGuest(guest_output("ok inserted drive=0 polls=4", swap_reads()))
    receipt = insert(guest)
    assert receipt.polls == 4 and receipt.applied_ms == 1152 - 110
    assert (receipt.pid, receipt.server_pid) == ("4242", "4242")
    assert receipt.exe.endswith("winuae64.exe")
    body = receipt.as_dict()
    assert len(body["replies"]) == 3 * 5 + 1
    setter = next(r for r in body["replies"] if r["label"] == "set")
    assert base64.b64decode(setter["raw"]) == b"404\0"
    assert body["before"]["paths"] == {"DF0": DISK_A, "DF1": DISK_C}


def test_the_lower_drive_is_changed_with_the_other_drive_left_alone():
    reads = [(0, 100, state(path1=DISK_A)),
             (1, 400, state(path0=DISK_B, mode0="ro", path1=DISK_A)),
             (2, 650, state(path0=DISK_B, mode0="rw", path1=DISK_A)),
             (3, 900, state(path0=DISK_B, mode0="rw", path1=DISK_A))]
    receipt = insert(LaneGuest(guest_output("ok inserted drive=0 polls=3", reads)))
    assert receipt.polls == 3


def test_df1_may_be_changed_too():
    reads = [(0, 100, state()),
             (1, 400, state(path1=DISK_B, mode1="ro")),
             (2, 650, state(path1=DISK_B, mode1="rw")),
             (3, 900, state(path1=DISK_B, mode1="rw"))]
    assert insert(LaneGuest(guest_output("ok inserted drive=1 polls=3", reads)),
                  drive=1).polls == 3


def test_a_setter_reply_of_404_is_expected_and_proves_nothing_alone():
    reads = [(0, 100, state()), (1, 400, state())]
    with pytest.raises(amiga.FloppyError, match="never took"):
        insert(LaneGuest(guest_output("ok inserted drive=0 polls=1", reads)))


@pytest.mark.parametrize("setter", [b"501\0", b"200 \nx\0", b"200\n\0"])
def test_a_setter_reply_other_than_404_is_an_error(setter):
    guest = LaneGuest(guest_output("ok inserted drive=0", swap_reads(), setter=setter))
    with pytest.raises(amiga.FloppyError, match="a setter answers 404"):
        insert(guest)


@pytest.mark.parametrize("blob", [b"404", b"404\0\0", b"40\x004\0", b"40\x004", b"\x00404", b""])
def test_a_reply_that_is_not_one_nul_terminated_string_is_an_error(blob):
    reads = swap_reads()
    reads[2] = (2, 650, {**state(path0=DISK_B, mode0="ro"), "q0": blob})
    with pytest.raises(amiga.FloppyError, match="is not one NUL-terminated string"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


@pytest.mark.parametrize("blob", [nul("200 \nA\nB"), nul("200 A"), nul("201 \nA"), nul("501")])
def test_a_query_that_is_neither_404_nor_one_200_line_is_an_error(blob):
    reads = swap_reads()
    reads[1] = (1, 400, {**state(path0=DISK_B, mode0="ro"), "q1": blob})
    with pytest.raises(amiga.FloppyError, match="neither 404 nor one 200 line"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


@pytest.mark.parametrize("first", ["404", "501"])
def test_a_pipe_that_does_not_answer_queries_stops_before_anything_is_sent(first):
    reads = [(0, 100, {**state(), "q0": nul(first)})]
    with pytest.raises(amiga.FloppyError,
                       match=r"not answering configuration queries \(" + first):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads, setter=None)))


def test_a_dump_without_a_line_for_a_drive_is_an_error():
    reads = swap_reads()
    reads[3] = (3, 900, {**state(path0=DISK_B), "dbg": nul("DEBUG: drive 0 motor off "
                "cylinder  0 sel no rw mfmpos 0/12668")})
    with pytest.raises(amiga.FloppyError, match="no line for DF1"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


def test_a_dump_with_two_lines_for_one_drive_is_an_error():
    line = "DEBUG: drive 0 motor off cylinder  0 sel no rw mfmpos 0/12668"
    reads = swap_reads()
    reads[3] = (3, 900, {**state(path0=DISK_B), "dbg": nul("\n".join([line, line, line.replace("drive 0", "drive 1")]))})
    with pytest.raises(amiga.FloppyError, match="more than one line for DF0"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


def test_the_guests_tags_are_read_by_name_not_by_position():
    lines = guest_output("ok inserted drive=0 polls=4", swap_reads()).split("\r\n")
    tags = [ln for ln in lines if ln.startswith("<<") and not ln.startswith(("<<r>>", "<<end>>"))]
    rest = [ln for ln in lines if ln not in tags]
    shuffled = "\r\n".join([rest[0], *reversed(tags), *rest[1:]])
    receipt = insert(LaneGuest(shuffled))
    assert (receipt.pid, receipt.server_pid, receipt.connect_ms) == ("4242", "4242", 70.0)


def test_a_stale_readback_is_an_error():
    reads = [(0, 100, state())] + [(n, 100 + 250 * n, state(path0=DISK_A)) for n in range(1, 5)]
    with pytest.raises(amiga.FloppyError, match=r"DF0 never took .*probeB.adf in 10 s; it reads .*probeA"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


def test_a_drive_never_seen_empty_may_still_hold_the_old_disk():
    reads = [(0, 100, state())] + [(n, 100 + 250 * n, state(path0=DISK_B, mode0="rw"))
                                   for n in range(1, 5)]
    with pytest.raises(amiga.FloppyError, match="never seen empty, so the old disk may still be in it"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


def test_a_poll_that_never_turns_rw_is_an_error():
    reads = [(0, 100, state())] + [(n, 100 + 250 * n, state(path0=DISK_B, mode0="ro"))
                                   for n in range(1, 41)]
    with pytest.raises(amiga.FloppyError, match="names .*probeB.adf but holds no disk after 10 s"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


def test_one_rw_poll_is_not_enough():
    reads = swap_reads()[:4]
    with pytest.raises(amiga.FloppyError, match="holds no disk after"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


def test_an_rw_run_broken_by_an_ro_poll_starts_again():
    reads = [(0, 100, state()),
             (1, 400, state(path0=DISK_B, mode0="ro")),
             (2, 650, state(path0=DISK_B, mode0="rw")),
             (3, 900, state(path0=DISK_B, mode0="ro")),
             (4, 1150, state(path0=DISK_B, mode0="rw"))]
    with pytest.raises(amiga.FloppyError, match="holds no disk after"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


@pytest.mark.parametrize("bad", [
    {"path1": DISK_B}, {"mode1": "ro"}, {"path1": ""}])
def test_the_other_drive_changing_at_any_poll_is_an_error(bad):
    reads = swap_reads()
    reads[2] = (2, 650, {**state(path0=DISK_B, mode0="ro"), **bad})
    with pytest.raises(amiga.FloppyError, match="DF1 changed from .* while DF0 was being changed"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads)))


def test_a_poll_missing_a_reply_is_an_error():
    output = guest_output("ok inserted drive=0", swap_reads())
    output = "\r\n".join(ln for ln in output.split("\r\n") if not ln.startswith("<<r>> 3 dbg"))
    with pytest.raises(amiga.FloppyError, match="no dbg reply for read 3"):
        insert(LaneGuest(output))


def test_a_malformed_reply_line_is_an_error():
    output = guest_output("ok inserted drive=0", swap_reads()).replace("<<r>> 1 q0 ", "<<r>> one q0 ")
    with pytest.raises(amiga.FloppyError, match="malformed reply line"):
        insert(LaneGuest(output))


def test_a_guest_refusal_is_an_error_that_keeps_what_it_printed():
    output = guest_output("fail DF0 was not seen holding it", swap_reads()[:2])
    with pytest.raises(amiga.FloppyError, match="was not seen holding it") as caught:
        insert(LaneGuest(output))
    assert len(caught.value.receipt["replies"]) == 7


def test_a_guest_that_never_reaches_its_end_marker_is_an_error():
    output = guest_output("ok inserted drive=0", swap_reads()).replace("<<end>>", "")
    with pytest.raises(amiga.FloppyError, match="did not finish"):
        insert(LaneGuest(output))


def test_a_status_that_is_neither_ok_nor_fail_is_an_error():
    with pytest.raises(amiga.FloppyError, match="neither ok nor fail"):
        insert(LaneGuest(guest_output("maybe", swap_reads())))


def test_a_refusal_before_the_pipe_opens_arrives_as_the_guests_own_text():
    error = amiga.GuestError("winvm ssh failed: fail the WinUAE lane is claimed by other "
                             "since 10:00, not by " + HOLDER)
    with pytest.raises(amiga.FloppyError, match="is claimed by other since 10:00"):
        insert(LaneGuest(error=error))


def test_a_timeout_is_an_error_not_a_success():
    error = amiga.GuestError("winvm ssh did not answer in 60s")
    with pytest.raises(amiga.FloppyError, match="did not answer in 60s"):
        insert(LaneGuest(error=error))


def test_a_path_already_in_the_target_drive_sends_nothing_and_is_ok_when_rw():
    reads = [(0, 100, state(path0=DISK_B))]
    receipt = insert(LaneGuest(guest_output("ok already drive=0", reads, setter=None)))
    assert receipt.already is True and receipt.polls == 0
    assert not any(r["label"] == "set" for r in receipt.as_dict()["replies"])


def test_a_path_already_named_by_an_empty_target_drive_is_an_error():
    reads = [(0, 100, state(path0=DISK_B, mode0="ro"))]
    with pytest.raises(amiga.FloppyError, match="names .*probeB.adf but holds no disk"):
        insert(LaneGuest(guest_output("ok already drive=0", reads, setter=None)))


def test_a_setter_sent_for_a_path_already_in_the_drive_is_an_error():
    reads = [(0, 100, state(path0=DISK_B))]
    with pytest.raises(amiga.FloppyError, match="already named"):
        insert(LaneGuest(guest_output("ok already drive=0", reads)))


def test_a_path_already_in_the_other_drive_is_an_error():
    reads = [(0, 100, state(path1=DISK_B))]
    with pytest.raises(amiga.FloppyError, match="probeB.adf is already in DF1"):
        insert(LaneGuest(guest_output("ok inserted drive=0", reads, setter=None)))


def test_the_drives_verb_reads_both_drives_and_changes_nothing():
    guest = LaneGuest(guest_output("ok drives pid=4242", [(0, 100, state())], setter=None))
    receipt = amiga.WinuaePipe(runner=guest).drives(HOLDER)
    assert guest.calls[0][2].endswith(f"winuae.ps1 drives -Holder {HOLDER}")
    assert {r["label"] for r in receipt.as_dict()["replies"]} == {"q0", "q1", "dbg"}
    assert receipt.status == "ok drives pid=4242"


def test_the_drives_verb_refuses_a_pipe_that_answers_no_queries():
    reads = [(0, 100, {**state(), "q0": nul("404")})]
    with pytest.raises(amiga.FloppyError, match="not answering configuration queries"):
        amiga.WinuaePipe(runner=LaneGuest(guest_output("ok drives pid=1", reads, setter=None))).drives(HOLDER)


@pytest.mark.parametrize("drive", [2, 3, 4, -1, True, False, "0", None, 0.0, 1.0])
def test_a_floppy_change_refuses_every_drive_but_df0_and_df1(drive):
    guest = LaneGuest()
    with pytest.raises(ValueError, match="only DF0 and DF1 may be changed"):
        insert(guest, drive=drive)
    assert guest.calls == []


@pytest.mark.parametrize("path,text", [
    (None, "is not a disk this run staged"), (3, "is not a disk this run staged"),
    (b"x", "is not a disk this run staged"),
    (DISK_B + ";q", "is refused"), (DISK_B.replace("probeB", "pr obeB"), "is refused"),
    (DISK_B.replace("probeB", 'pr"obeB'), "is refused"),
    (DISK_B.replace("probeB", "pr'obeB"), "is refused"),
    (DISK_B.replace("probeB", "pr=obeB"), "is refused"),
    (DISK_B.replace("probeB", "pr%obeB"), "is refused"),
    (DISK_B.replace(".adf", ".adf\n"), "is refused"),
    (DISK_B.replace("probeB", "pr\tobeB"), "is refused"),
    (DISK_B.replace("probeB", "pr\u00e9obeB"), "is refused"),
    ("C:\\Amiga\\Disks\\..\\wish679-x.adf", "is refused"),
    (DISK_B.replace("probeB", "pro..beB"), "is refused"),
    ("\\\\server\\share\\wish679-x.adf", "is refused"),
    ("\\\\?\\C:\\Amiga\\Disks\\wish679-x.adf", "is refused"),
    ("C:\\Amiga\\Disks\\wish679-x.zip", "is refused"),
    ("D:\\Amiga\\Disks\\wish679-x.adf", "is refused"),
    ("C:\\Amiga\\Disks\\sub\\wish679-x.adf", "is refused"),
    ("C:\\Amiga\\Disks\\wish679-" + "x" * 200 + ".adf", "longer than 200"),
    (DISK_B.replace(HOLDER, "wish679-other000000"), "belongs to another holder"),
    (f"C:\\Amiga\\Disks\\wish679-{HOLDER}-.adf", "belongs to another holder"),
    (f"C:\\Amiga\\Disks\\wish679-{HOLDER[:-1]}-probeB.adf", "belongs to another holder"),
])
def test_a_floppy_change_refuses_a_bad_path_before_anything_is_sent(path, text):
    guest = LaneGuest()
    with pytest.raises(ValueError, match=text):
        insert(guest, path=path)
    assert guest.calls == []


@pytest.mark.parametrize("sha", [None, "", "b" * 63, "b" * 65, "g" * 64, " " + "b" * 63])
def test_a_floppy_change_refuses_a_hash_that_is_not_a_sha256(sha):
    guest = LaneGuest()
    with pytest.raises(ValueError, match="is not 64 hexadecimal digits"):
        insert(guest, sha=sha)
    assert guest.calls == []


@pytest.mark.parametrize("holder", ["", "a b", "x;y", "a" * 65, None, "a/b"])
def test_a_floppy_change_refuses_a_holder_that_is_not_lane_safe(holder):
    guest = LaneGuest()
    with pytest.raises(ValueError, match="not a lane-safe name"):
        insert(guest, holder=holder)
    assert guest.calls == []


def test_a_floppy_change_refuses_a_token_that_is_not_the_claims():
    guest = LaneGuest()
    with pytest.raises(ValueError, match="twelve hexadecimal digits"):
        amiga.WinuaePipe(runner=guest).insert_floppy(0, DISK_B, HOLDER, SHA_B, token="x; dbg")
    assert guest.calls == []


def test_a_floppy_change_refuses_a_pipe_that_is_not_winuaes_own():
    guest = LaneGuest()
    with pytest.raises(ValueError, match="WinUAE's own pipe only"):
        insert(guest, pipe="WinUAE_1")
    assert guest.calls == []


def test_a_floppy_change_never_goes_through_the_debugger_script(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a floppy change went through script()")

    monkeypatch.setattr(amiga.WinuaePipe, "script", refuse)
    monkeypatch.setattr(amiga.WinuaePipe, "_framed", refuse)
    guest = LaneGuest(guest_output("ok inserted drive=0 polls=4", swap_reads()))
    insert(guest)


@pytest.mark.parametrize("command", ["CFG floppy0 x dbg g", "ipc_quit", "g", "IPC_QUIT"])
def test_the_debugger_route_still_refuses_what_could_open_a_console(command):
    guest = LaneGuest()
    if command.startswith("CFG"):
        # The debugger prefix goes on in front, so a CFG text is a debugger word, not a setter.
        assert amiga.WinuaePipe(runner=guest).script([command]).count("CFG floppy0") == 0
        return
    with pytest.raises(ValueError):
        amiga.WinuaePipe(runner=guest).script([command])
    assert guest.calls == []


def test_a_debugger_command_still_goes_down_with_dbg_and_never_cfg():
    guest = CfgGuest()
    amiga.WinuaePipe(runner=guest).send(["m 0 1"])
    assert guest.messages == ["DBG m 0 1"]


def test_a_verb_the_guest_refuses_after_the_pipe_is_open_still_raises_with_its_text():
    guest = LaneGuest("fail C:\\x.adf does not exist\r\n<<end>>\r\n")
    with pytest.raises(amiga.FloppyError, match="C:.x.adf does not exist"):
        amiga.WinuaePipe(runner=guest).refused_verb("insert", HOLDER, ["0", DISK_B, SHA_B])


def test_a_verb_the_guest_accepts_returns_its_first_line_and_a_refusal_before_the_pipe_raises():
    said = amiga.WinuaePipe(runner=LaneGuest("ok inserted drive=0\r\n<<end>>\r\n")).refused_verb(
        "insert", HOLDER, ["0", DISK_B, SHA_B])
    assert said == "ok inserted drive=0"
    with pytest.raises(amiga.FloppyError, match="claimed by other"):
        amiga.WinuaePipe(runner=LaneGuest(error=amiga.GuestError(
            "winvm ssh failed: fail the WinUAE lane is claimed by other"))).refused_verb(
                "insert", HOLDER, ["0", DISK_B, SHA_B])

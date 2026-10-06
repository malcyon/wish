"""`tools/amiga/tripprobe.py` and the boat-exit encoders, with fakes for the machine."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import amigatrip  # noqa: E402
from tools.amiga import tripprobe  # noqa: E402

ROW = amigatrip.row_for("pool-of-radiance")


def test_encoders_match_the_boat_exit_bytes():
    assert amigatrip.picture(255) == bytes.fromhex("0E 00 FF")
    assert amigatrip.clear_box() == b"\x3d"
    assert amigatrip.loadfiles(127, 127, 127) == bytes.fromhex("21 00 7F 00 7F 00 7F")
    assert amigatrip.save(1, 0x49E6) == bytes.fromhex("09 00 01 01 E6 49")


def test_the_prologue_is_the_five_groups_in_order_and_53_bytes():
    groups = amigatrip.boat_exit_groups()
    assert [len(g) for g in groups] == [3, 1, 6, 36, 7]
    assert groups[3] == b"".join(
        bytes((0x09, 0x00, 0x7F, 0x01, lo, 0x6E)) for lo in range(0x22, 0x28))
    assert len(b"".join(groups)) == 53


def test_statements_put_the_prefix_before_the_trip():
    trip = amigatrip.encode("pool-of-radiance", (9, 14, 2), 0)
    for n in range(6):
        out = tripprobe.statements(n, (9, 14, 2), 0)
        assert out == b"".join(amigatrip.boat_exit_groups()[:n]) + trip
    with pytest.raises(ValueError):
        tripprobe.statements(6, (9, 14, 2), 0)


class Fake:
    """Records calls; the area byte changes after the key link is written."""

    def __init__(self):
        self.calls = []
        self.area = 26

    def snapshot(self, name, holder):
        self.calls.append(("snapshot", name))

    def restore(self, name, holder):
        self.calls.append(("restore", name))
        self.area = 26

    def discard_snapshot(self, name, holder):
        self.calls.append(("discard", name))


def test_each_prefix_restores_the_snapshot_first(monkeypatch, tmp_path):
    fake = Fake()
    monkeypatch.setattr(tripprobe, "write_trip",
                        lambda t, row, data: fake.calls.append(("write", len(data))) or 26)
    monkeypatch.setattr(amigatrip, "area_id",
                        lambda t, row: fake.calls.append(("area",)) or 0)
    shots = tripprobe.run(fake, "h", 0, (9, 14, 2), tmp_path,
                          lambda holder, path: fake.calls.append(("shot", path.name)),
                          sleep=lambda s: None)
    kinds = [c for c in fake.calls if c[0] != "area"]
    assert kinds[0] == ("snapshot", "tripprobe")
    assert kinds[-1] == ("discard", "tripprobe")
    body = kinds[1:-1]
    assert [c[0] for c in body] == ["restore", "write", "shot"] * 6
    trip = len(amigatrip.encode("pool-of-radiance", (9, 14, 2), 0))
    assert [c[1] for c in body if c[0] == "write"] == [
        trip + sum(len(g) for g in amigatrip.boat_exit_groups()[:n]) for n in range(6)]
    assert [(n, p.name) for n, p in shots] == [(n, f"prefix{n}.png") for n in range(6)]


def test_a_prefix_that_never_fires_is_recorded_and_the_run_goes_on(monkeypatch, tmp_path):
    fake = Fake()
    monkeypatch.setattr(tripprobe, "write_trip",
                        lambda t, row, data: fake.calls.append(("write", len(data))) or 26)
    # Prefix 1 leaves the area byte alone; the others change it.
    state = {"writes": 0}
    monkeypatch.setattr(tripprobe, "FIRE_SECONDS", 1.0)

    def area(t, row):
        state["writes"] = sum(1 for c in fake.calls if c[0] == "write")
        return 26 if state["writes"] == 2 else 0

    monkeypatch.setattr(amigatrip, "area_id", area)
    shots = tripprobe.run(fake, "h", 0, (9, 14, 2), tmp_path,
                          lambda holder, path: fake.calls.append(("shot", path.name)),
                          sleep=lambda s: None)
    assert [n for n, p in shots] == list(range(6))
    assert [p is None for n, p in shots] == [False, True, False, False, False, False]
    assert fake.calls[-1] == ("discard", "tripprobe")
    assert [c[0] for c in fake.calls].count("restore") == 6


class FakePipe:
    """The snapshot half only, as `WinuaePipe` is: no read, write or data_base."""

    def __init__(self, holder):
        self.calls = []

    def snapshot(self, name, holder):
        self.calls.append("snapshot")

    def restore(self, name, holder):
        self.calls.append("restore")

    def discard_snapshot(self, name, holder):
        self.calls.append("discard")


class FakeTarget:
    """A located target over a zeroed memory, as `AmigaTarget(pipe, machine)` is."""

    writes = []

    def __init__(self, pipe, machine):
        self.pipe = pipe
        self.data_base = None

    def locate(self):
        self.data_base = 0x1000
        return self.data_base

    def read(self, addr, length):
        return bytes(length)

    def write(self, addr, data, verify=True):
        type(self).writes.append(addr)


def test_main_builds_a_located_target_for_the_trip_writes(monkeypatch, tmp_path):
    from automap import amiga
    from tools.amiga import amigadrive

    FakeTarget.writes = []
    pipes = []
    monkeypatch.setattr(amiga, "WinuaePipe", lambda holder: pipes.append(FakePipe(holder)) or pipes[-1])
    monkeypatch.setattr(amiga, "AmigaTarget", FakeTarget)
    monkeypatch.setattr(amigatrip, "gate", lambda t, row: True)
    # Memory reads as zero until the first write, so the area byte "changes" by
    # the fake reporting a new area once something has been written.
    monkeypatch.setattr(amigatrip, "area_id",
                        lambda t, row: 26 if len(FakeTarget.writes) % 4 == 0 and FakeTarget.writes else 0)
    monkeypatch.setattr(amigatrip, "_port", lambda t, row: 0x2000)
    monkeypatch.setattr(amigatrip, "rawkey_message", lambda port, window: bytes(4))
    monkeypatch.setattr(amigatrip, "link", lambda addr: bytes(4))
    monkeypatch.setattr(amigadrive, "shot", lambda holder, path: None)
    monkeypatch.setattr(tripprobe.time, "sleep", lambda s: None)
    assert tripprobe.main(["--holder", "h", "--area", "0", "--square", "9,14,2",
                           "--out", str(tmp_path)]) == 0
    assert FakeTarget.writes
    assert pipes[0].calls.count("restore") == 6


# -- the door probe (variant D) ----------------------------------------------

from automap import amiga  # noqa: E402
from goldbox import geo as goldgeo  # noqa: E402

BASE, BUFFER, WINDOW, PORT = 0x10000, 0x40000, 0x50000, 0x60000
NOTES = amiga.MACHINES["pool-of-radiance"].notes


def _geo_blob() -> bytes:
    blob = bytearray(goldgeo.GEO_SIZE)
    # Wall art on the north side of (4,0) is 7; its attribute byte is 0x93.
    blob[0x000 + 4] = 0x70
    blob[0x200 + 4] = 0x93
    return bytes(blob)


class DoorFake:
    """A sparse memory with the pointers the probe follows; the port takes the key if asked."""

    def __init__(self, takes=True):
        self.takes = takes
        self.data_base = BASE
        self.mem = {}
        self.writes = []
        self.put(BASE + ROW.buffer_pointer, BUFFER.to_bytes(4, "big"))
        self.put(BASE + ROW.window_pointer, WINDOW.to_bytes(4, "big"))
        self.put(WINDOW + amigatrip.WINDOW_USERPORT, PORT.to_bytes(4, "big"))
        self.put(PORT + amigatrip.PORT_LIST, amigatrip.empty_list(PORT))
        self.put(BASE + ROW.area, bytes([14]))
        for spot, v in zip(ROW.square_spots, (1, 2, 3)):
            self.put(amigatrip._address(self, spot), amigatrip._encode_spot(spot, v))
        self.put(BASE + NOTES["wall_ahead"], b"\x05")
        self.put(BASE + NOTES["square_attribute"], b"\x06")

    def put(self, addr, data):
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    def read(self, addr, length):
        return bytes(self.mem.get(addr + i, 0) for i in range(length))

    def read_blocks(self, blocks):
        return [self.read(a, n) for a, n in blocks]

    def geo(self):
        return _geo_blob()

    def write(self, addr, data, verify=True):
        self.writes.append((addr, bytes(data)))
        if addr == PORT + amigatrip.PORT_LIST and self.takes and data != amigatrip.empty_list(PORT):
            return  # the game takes the message within a frame
        self.put(addr, data)


@pytest.fixture
def door(monkeypatch):
    monkeypatch.setattr(amigatrip, "gate", lambda t, row: True)


def _walk(fake, stand=(4, 0, 0), attribute=True):
    return tripprobe.try_door(fake, ROW, stand, attribute, lambda s: None)


def test_variant_d_writes_the_square_both_cached_bytes_and_the_key(door):
    fake = DoorFake()
    result = _walk(fake)
    writes = dict(fake.writes)
    assert [fake.read(amigatrip._address(fake, s), s.width) for s in ROW.square_spots] == [
        amigatrip._encode_spot(s, v) for s, v in zip(ROW.square_spots, (4, 0, 0))]
    assert writes[BASE + NOTES["wall_ahead"]] == b"\x07"
    assert writes[BASE + NOTES["square_attribute"]] == b"\x93"
    message = (BUFFER + amigatrip.layout(ROW, 0)[1])
    assert writes[message] == amigatrip.rawkey_message(PORT, WINDOW)
    assert writes[PORT + amigatrip.PORT_LIST] == amigatrip.link(message)
    assert fake.writes[-1][0] == PORT + amigatrip.PORT_LIST
    assert result["key_taken"] and not result["put_back"]
    assert result["square_after"] == (4, 0, 0)


def test_skipping_the_attribute_leaves_0x1773_alone(door):
    fake = DoorFake()
    _walk(fake, attribute=False)
    assert BASE + NOTES["square_attribute"] not in dict(fake.writes)
    assert fake.read(BASE + NOTES["square_attribute"], 1) == b"\x06"


def test_a_key_that_is_not_taken_puts_every_byte_back(door, monkeypatch):
    fake = DoorFake(takes=False)
    before = dict(fake.mem)
    monkeypatch.setattr(tripprobe, "FIRE_SECONDS", 1.0)
    result = _walk(fake)
    assert not result["key_taken"] and result["put_back"]
    assert all(fake.mem.get(a, 0) == before.get(a, 0) for a in set(before) | set(fake.mem))


def test_a_game_not_at_its_world_menu_writes_nothing(monkeypatch):
    fake = DoorFake()
    monkeypatch.setattr(amigatrip, "gate", lambda t, row: False)
    with pytest.raises(tripprobe.ProbeError):
        _walk(fake)
    assert fake.writes == []


def test_a_write_that_fails_puts_back_what_landed(door):
    fake = DoorFake()
    before = dict(fake.mem)
    real = fake.write

    def write(addr, data, verify=True):
        if addr == BASE + NOTES["wall_ahead"]:
            raise amiga.GuestError("gone")
        real(addr, data, verify)

    fake.write = write
    with pytest.raises(amiga.GuestError):
        _walk(fake)
    assert fake.mem == before


def test_run_doors_restores_then_records_each_try(door, tmp_path):
    fake = DoorFake()
    calls = []
    fake.snapshot = lambda n, h: calls.append("snapshot")
    fake.restore = lambda n, h: calls.append("restore")
    fake.discard_snapshot = lambda n, h: calls.append("discard")
    results = tripprobe.run_doors(
        fake, "h", {"edge": (4, 0, 0), "other": (4, 0, 0)}, (True, False), tmp_path,
        lambda holder, path: calls.append(path.name), sleep=lambda s: None)
    assert calls == ["snapshot", "restore", "edge-attribute.png", "restore", "edge-skip.png",
                     "restore", "other-attribute.png", "restore", "other-skip.png", "discard"]
    lines = [__import__("json").loads(x) for x in (tmp_path / "doors.jsonl").read_text().splitlines()]
    assert [(r["route"], r["attribute"], r["key_taken"]) for r in lines] == [
        ("edge", True, True), ("edge", False, True), ("other", True, True), ("other", False, True)]
    assert len(results) == 4


def test_main_door_reports_a_guest_error_as_an_exit(monkeypatch, tmp_path):
    from tools.amiga import amigadrive

    class Pipe(FakePipe):
        pass

    class Target(FakeTarget):
        def locate(self):
            raise amiga.GuestError("no machine")

    monkeypatch.setattr(amiga, "WinuaePipe", lambda holder: Pipe(holder))
    monkeypatch.setattr(amiga, "AmigaTarget", Target)
    monkeypatch.setattr(amigadrive, "shot", lambda holder, path: None)
    with pytest.raises(SystemExit, match="no machine"):
        tripprobe.main(["--holder", "h", "--door", "--route", "edge=4,0,0", "--out", str(tmp_path)])

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
    assert [p.name for p in shots] == [f"prefix{n}.png" for n in range(6)]

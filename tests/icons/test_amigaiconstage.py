"""`tools/icons/amigaiconstage.py`: one member's figure bytes on a copy of an
Amiga save disk, and the check of an ICON capture against them, on disks
and crops built here; plus the four planned stagings on the player's disks."""
from __future__ import annotations

import pytest

from goldbox import amiga_pod, amiga_por, amiga_port, amiga_savegame
from goldbox.amiga_adf import AmigaDisk
from tests.support import amigasavegame as synthetic
from tools.amiga import staging
from tools.icons import amigaiconstage as tool
from tools.icons.amigaiconstage import IconStageError

ICON = (7, 30, 2, bytes.fromhex("5a413b7644ef"))


def _pool_record(name: bytes) -> bytes:
    raw = bytearray(amiga_por.AMIGA_POR_RECORD_SIZE)
    raw[:len(name)] = name
    return bytes(raw)


def _pool() -> AmigaDisk:
    disk = AmigaDisk.blank("POOLSAVE")
    for n, name in enumerate((b"BRUTUS", b"MAGNUS"), 1):
        disk.write_file(f"/CHRDATA{n}.sav", _pool_record(name))
    return disk


def _later(title: str) -> AmigaDisk:
    if title == "curse":
        return amiga_savegame.make_save_disk(
            amiga_savegame.CURSE, "A", synthetic.synthetic_curse(("ALPHA", "BETA")))
    return amiga_savegame.make_save_disk(
        amiga_savegame.SILVER_BLADES, "A",
        synthetic.synthetic_silver_blades(("GAMMA", "DELTA")))


def _darkness() -> AmigaDisk:
    data = bytearray(amiga_savegame.POD_SAVEGAME_SIZE)
    data[amiga_savegame.POD_COUNT_AT + 1] = 2
    for n, name in enumerate((b"saint eric", b"goofey")):
        at = (amiga_savegame.POD_PARTY_AT + n * amiga_savegame.POD_RECORD_BYTES
              + amiga_savegame.POD_NAME_AT)
        data[at:at + len(name)] = name
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir("/Save")
    disk.write_file("/Save/SavGamB.pty", bytes(data))
    disk.write_file("/Save/VaultB.DAT", b"v" * 12)
    return disk


#: Each title's disk, slot, and the second member's record start and figure
#: offsets, worked out from the record tables rather than from the tool.
def _cases():
    pool = [amiga_por.amiga_por_offset(o) for o in (0x0BD, 0x0BE, 0x0C0, 0x0C1)]
    out = [("pool", _pool, "A", "/CHRDATA2.sav", 0, pool, "MAGNUS")]
    # The Amiga record offsets the later-title composer read for the eight
    # captured members, written out rather than mapped here.
    for title, deltas, offsets in (
            ("curse", amiga_port.CURSE_DELTAS, [0x145, 0x146, 0x148, 0x149]),
            ("ssb", amiga_port.SILVER_BLADES_DELTAS, [0x0EF, 0x0F0, 0x0F2, 0x0F3])):
        container = amiga_savegame.container_for(deltas)
        out.append((title, lambda t=title: _later(t), "A",
                    amiga_savegame.slot_path(container, "A"),
                    container.party_at + deltas.record_size, offsets,
                    "BETA" if title == "curse" else "DELTA"))
    out.append(("darkness", _darkness, "B", "/Save/SavGamB.pty",
                amiga_savegame.POD_PARTY_AT + amiga_savegame.POD_RECORD_BYTES,
                [amiga_pod.ICON_HEAD, amiga_pod.ICON_BODY, amiga_pod.SIZE,
                 amiga_pod.ICON_COLOURS], "goofey"))
    return out


CASES = _cases()


@pytest.mark.parametrize("title, make, slot, path, at, offsets, name", CASES,
                         ids=[c[0] for c in CASES])
def test_staging_writes_the_members_figure_bytes_and_nothing_else(
        title, make, slot, path, at, offsets, name):
    source = make().to_bytes()
    staged, report = tool.stage(source, title, slot, 2, ICON)
    before, after = AmigaDisk(bytearray(source)), AmigaDisk(bytearray(staged))
    assert report["name"] == name and report["after"]["icon_colours"] == ICON[3].hex()
    head, body, size, colours = (at + o for o in offsets)
    was, now = before.read_file(path), after.read_file(path)
    changed = [i for i, (a, b) in enumerate(zip(was, now)) if a != b]
    assert changed == [head, body, size] + list(range(colours, colours + 6))
    assert (now[head], now[body], now[size]) == ICON[:3]
    assert now[colours:colours + 6] == ICON[3]
    others = [p for p, e in before.walk() if not e.is_dir and p.upper() != path.upper()]
    assert all(before.read_file(p) == after.read_file(p) for p in others)
    assert tool.locate(after, title, slot, 1).fields() == tool.locate(
        before, title, slot, 1).fields()
    assert after.verify() == []


def test_a_byte_outside_the_figure_fields_or_another_file_is_blocked():
    source = _pool().to_bytes()
    staged, _ = tool.stage(source, "pool", "A", 2, ICON)
    disk = AmigaDisk(bytearray(staged))
    raw = bytearray(disk.read_file("/CHRDATA2.sav"))
    raw[0] ^= 1
    staging.replace_file_in_place(disk, "/CHRDATA2.sav", bytes(raw))
    with pytest.raises(IconStageError, match="outside the figure fields"):
        tool.check_staged(source, disk.to_bytes(), "pool", "A", 2, ICON)
    disk = AmigaDisk(bytearray(staged))
    staging.replace_file_in_place(disk, "/CHRDATA1.sav", _pool_record(b"BRUTUZ"))
    with pytest.raises(IconStageError, match="CHRDATA1.sav changed"):
        tool.check_staged(source, disk.to_bytes(), "pool", "A", 2, ICON)
    with pytest.raises(IconStageError, match="does not read back"):
        tool.check_staged(source, staged, "pool", "A", 2, (6,) + ICON[1:])


def test_a_member_the_slot_lacks_is_blocked():
    with pytest.raises(IconStageError, match="members 1 to 2, not 3"):
        tool.stage(_pool().to_bytes(), "pool", "A", 3, ICON)


@pytest.mark.parametrize("text, wanted", [
    ("7:30:2:5a413b7644ef", ICON), ("0:0:1:91A2B3C4E6F7", (0, 0, 1, bytes.fromhex("91a2b3c4e6f7")))])
def test_an_icon_parses(text, wanted):
    assert tool.parse_icon(text) == wanted


@pytest.mark.parametrize("text, why", [
    ("7:30:2", "HEAD:BODY:SIZE:COLOURS"), ("7:30:x:5a413b7644ef", "HEAD:BODY:SIZE:COLOURS"),
    ("7:30:2:5a41", "hex digits"), ("7:30:2:zz413b7644ef", "hex digits"),
    ("14:30:2:5a413b7644ef", "head is 0 to 13"), ("7:32:2:5a413b7644ef", "head is 0 to 13"),
    ("7:30:3:5a413b7644ef", "head is 0 to 13")])
def test_a_malformed_icon_is_blocked(text, why):
    with pytest.raises(IconStageError, match=why):
        tool.parse_icon(text)


def test_the_source_is_read_and_an_existing_out_is_never_overwritten(tmp_path):
    source, out = tmp_path / "save.adf", tmp_path / "staged.adf"
    source.write_bytes(_pool().to_bytes())
    original = source.read_bytes()
    report = tool.stage_file(source, None, out, "pool", "A", 1, ICON)
    assert source.read_bytes() == original
    assert report["staged_sha256"] == tool._sha(out.read_bytes())
    assert report["before"]["icon_head"] == 0 and report["name"] == "BRUTUS"
    staged = out.read_bytes()
    with pytest.raises(FileExistsError):
        tool.stage_file(source, None, out, "pool", "A", 2, ICON)
    assert out.read_bytes() == staged
    with pytest.raises(IconStageError, match="one of --disk and --registered"):
        tool.stage_file(None, None, tmp_path / "other.adf", "pool", "A", 1, ICON)


def test_main_stages_and_reports_a_blocked_member_without_a_trace(tmp_path, capsys):
    source = tmp_path / "save.adf"
    source.write_bytes(_pool().to_bytes())
    assert tool.main(["stage", "--title", "pool", "--disk", str(source), "--out",
                      str(tmp_path / "a.adf"), "--slot", "A", "--member", "1",
                      "--icon", "7:30:2:5a413b7644ef"]) == 0
    assert '"name": "BRUTUS"' in capsys.readouterr().out
    assert tool.main(["stage", "--title", "pool", "--disk", str(source), "--out",
                      str(tmp_path / "b.adf"), "--slot", "A", "--member", "5",
                      "--icon", "7:30:2:5a413b7644ef"]) == 2
    assert "members 1 to 2, not 5" in capsys.readouterr().err
    assert not (tmp_path / "b.adf").exists()


# -- check ------------------------------------------------------------------------
def _pose(colour):
    return tuple(tuple(colour if (x + y) % 3 else (0, 0, 0) for x in range(24))
                 for y in range(24))


def _crop(path, poses_at):
    """A doubled crop holding each `(pose, x, y)`, Amiga pixels, on grey."""
    from PIL import Image
    image = Image.new("RGB", (200, 120), (85, 85, 85))
    for pose, x0, y0 in poses_at:
        for y, row in enumerate(pose):
            for x, rgb in enumerate(row):
                image.putpixel((x0 + x, y0 + y), rgb)
    image.resize((400, 240), Image.NEAREST).save(path)


def test_check_finds_both_poses_and_fails_on_another_figure(tmp_path, monkeypatch):
    disk = AmigaDisk(bytearray(tool.stage(_pool().to_bytes(), "pool", "A", 1, ICON)[0]))
    ready, action = _pose((255, 0, 0)), _pose((0, 0, 255))
    seen = []
    monkeypatch.setattr(tool, "figure", lambda title, fields: seen.append(fields) or (ready, action))
    good = tmp_path / "good.png"
    _crop(good, [(ready, 29, 16), (action, 101, 16)])
    lines = []
    assert tool.check(disk, "pool", "A", 1, good, lines.append) == 0
    assert seen == [ICON]
    assert lines[1] == "BRUTUS ready: matches pixel for pixel at (29, 16)"
    bad = tmp_path / "bad.png"
    _crop(bad, [(ready, 29, 16), (_pose((0, 255, 0)), 101, 16)])
    lines = []
    assert tool.check(disk, "pool", "A", 1, bad, lines.append) == 1
    assert lines[2].startswith("BRUTUS action: no exact match; the closest differs in")


def test_check_says_when_the_art_is_missing(tmp_path, monkeypatch):
    disk = AmigaDisk(bytearray(_pool().to_bytes()))
    monkeypatch.setattr(tool, "figure", lambda title, fields: None)
    lines = []
    assert tool.check(disk, "pool", "A", 1, tmp_path / "unread.png", lines.append) == 1
    assert lines[-1] == "pool: its art is not all on this machine"


# -- the four planned stagings, on the player's registered disks ------------------------
PLANS = [
    ("pool", "6ad445f5715d021d560ddcf003e78153003315af016a19dbc4b56d55d3019d4c", "A", 1,
     "GARWAN", (10, 30, 2, "1c413b7644ef"), "7:30:2:5a413b7644ef"),
    ("curse", "4bfb64d1ebcf53867b941412ce04eb248b43dadebe34769f73ffa1aa609002ed", "A", 1,
     "GALAIN", (0, 0, 2, "81a283e4e697"), "2:0:2:3ca283e4e697"),
    ("ssb", "2f9ae86494561231dd1d70b350ae07b959c9f62642b64e9d4b57ffd23686ace4", "A", 1,
     "Guy de Valois", (5, 24, 2, "91a2b3c4e6f7"), "2:24:2:3ca2b3c4e6f7"),
    ("darkness", "bba0945c39e54fee75e4453e552a54534a584a395f9796ca570c655bf02f2fdd", "B", 1,
     "saint eric", (5, 24, 2, "fbfbfbc0fbff"), "2:24:2:fbfbfbc2fbff"),
]


@pytest.mark.parametrize("title, sha, slot, member, name, before, icon", PLANS,
                         ids=[p[0] for p in PLANS])
def test_each_planned_plume_staging_applies_to_its_registered_disk(
        title, sha, slot, member, name, before, icon):
    try:
        source, _label = tool.registered_image(sha)
    except IconStageError:
        pytest.skip(f"the registered {title} image is not on this machine")
    staged, report = tool.stage(source, title, slot, member, tool.parse_icon(icon))
    assert report["name"] == name
    head, body, size, colours = before
    assert report["before"] == {"icon_head": head, "icon_body": body, "size": size,
                                "icon_colours": colours}
    assert tool._sha(source) == sha

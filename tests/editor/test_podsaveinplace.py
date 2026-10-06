"""Save in place for a Pools of Darkness party, behind
`WISH_EXPERIMENTAL_POD_CONVERT`: an edit goes back into the DOS save folder
or the Amiga disk 3 slot it was opened from, and nothing else moves.

`goldbox.pod_rewrite` does the writing; `editor.saveplan.dos_files` and
`editor.saveplan.write_amiga` call it for this title, and the window's Save
calls those.

**The synthetic tests need no game data**: a one-character DOS folder written
from a blank record (`test_podwindow._synthetic_folder`). **The specimen tests
read the player's own saves** at run time -- every slot `test_podparty.py`
lists -- copied into a temporary folder first, so nothing a test writes lands
on a specimen. They skip without them.
"""
from __future__ import annotations

import pathlib
import shutil

import pytest
from test_podparty import (
    FLAG,
    OFF,
    _amiga_images,
    _dos_sources,
    _flag,
)
from test_podwindow import _no_box, _synthetic_folder, _window

from editor import binding, convert, podsheet, saveplan
from editor.roster import Party
from goldbox import amiga_pod, amiga_savegame, dos_codec, pod_rewrite
from goldbox.amiga_adf import AmigaDisk
from goldbox.rewrite import RewriteError

AGE = podsheet.TABLE["age"].span
AMIGA_AGE = amiga_pod.AGE
ENCUMBRANCE = podsheet.TABLE["encumbrance"].span
SHOWN = [f.name for f in binding.shown_fields(binding.editable_fields())]


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _files(folder: pathlib.Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())
            if p.is_file()}


def _disk_files(image: bytes) -> dict[str, bytes]:
    disk = AmigaDisk(bytearray(image))
    return {path: disk.read_file(path) for path, _entry in disk.walk()}


def _differing(a: bytes, b: bytes) -> list[int]:
    assert len(a) == len(b)
    return [i for i in range(len(a)) if a[i] != b[i]]


def _span(span: slice) -> list[int]:
    return list(range(span.start, span.stop))


def _inside(moved: list[int], span: "slice | list[int]") -> bool:
    """Some bytes moved, and every one of them is inside `span`."""
    allowed = _span(span) if isinstance(span, slice) else span
    return bool(moved) and set(moved) <= set(allowed)


# ---------------------------------------------------------------------------
# The saves we have, copied before anything is written
# ---------------------------------------------------------------------------

def _dos_copies(tmp_path) -> list[tuple[str, convert.Source]]:
    """Every DOS slot, its folder copied whole into `tmp_path`."""
    copies: dict[pathlib.Path, pathlib.Path] = {}
    out = []
    for source in _dos_sources():
        folder = pathlib.Path(source.path)
        if folder not in copies:
            copies[folder] = tmp_path / f"dos{len(copies)}"
            shutil.copytree(folder, copies[folder],
                            copy_function=shutil.copyfile)
            copies[folder].chmod(0o755)
        out.append((f"{folder}:{source.slot}",
                    convert.Source.detect(copies[folder], slot=source.slot)))
    return out


def _amiga_copies(tmp_path) -> list[tuple[str, convert.Source]]:
    """Every Amiga disk 3 slot, each slot on its own copy of its disk."""
    out = []
    for n, (label, data, slots) in enumerate(_amiga_images()):
        for letter in slots:
            path = tmp_path / f"disk3-{n}-{letter}.adf"
            path.write_bytes(data)
            out.append((f"{label}:{letter}",
                        convert.Source.detect(path, slot=letter)))
    if not out:
        pytest.skip("needs an Amiga Pools of Darkness disk 3; set "
                    "$WISH_SPECIMENS or $AMIGA_DISKS")
    return out


def _open(source, backups: pathlib.Path):
    import editor.window as ew
    window = _window()
    window.backups = str(backups)
    window._adopt(ew.Party(source), str(source.path))
    return window


def _edit_age(window, row: int) -> int:
    window._child("roster").selectRow(row)
    box = window._widgets["age"]
    box.setValue(box.value() + 1 if box.value() < box.maximum()
                 else box.value() - 1)
    return box.value()


# ---------------------------------------------------------------------------
# A one-character folder: what CI runs
# ---------------------------------------------------------------------------

def test_an_age_edit_and_a_save_move_only_the_age_bytes(
        app, monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    folder = _synthetic_folder(tmp_path)
    before = _files(folder)
    window = _open(convert.Source.detect(folder, slot="A"), tmp_path / "b")
    assert _edit_age(window, 0) == 31
    assert window.save(interactive=False) != "no changes"
    after = _files(folder)
    assert set(after) == set(before)
    for name in before:
        if name == "CHRDATA1.SAV":
            assert _inside(_differing(before[name], after[name]), AGE)
            assert int.from_bytes(after[name][AGE], "little") == 31
        else:
            assert after[name] == before[name], name


def test_a_save_with_no_edit_writes_nothing(app, monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    folder = _synthetic_folder(tmp_path)
    before = _files(folder)
    window = _open(convert.Source.detect(folder, slot="A"), tmp_path / "b")
    assert window.save(interactive=False) == "no changes"
    assert saveplan.dos_snapshot(window.party) == before
    assert _files(folder) == before
    assert not (tmp_path / "b").exists()


@pytest.mark.parametrize("value", OFF)
def test_without_the_flag_nothing_opens_and_save_writes_nothing(
        app, monkeypatch, tmp_path, value):
    import editor.window as ew
    _flag(monkeypatch, value)
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append(a[1]))
    folder = _synthetic_folder(tmp_path)
    before = _files(folder)
    window = _window()
    window.backups = str(tmp_path / "b")
    window.load(str(folder))
    assert said == ["Cannot open"]
    assert window.party is None
    assert window.save(interactive=False) == "nothing open"
    assert _files(folder) == before


def test_an_item_edit_patches_its_node_and_keeps_the_rest(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    folder = _synthetic_folder(tmp_path)
    party = Party(convert.Source.detect(folder, slot="A"))
    [member] = party.members
    node = (folder / "CHRDATA1.THG").read_bytes()
    member.inventory.set_quantity(0, 3)
    files = saveplan.dos_files(party)
    items = files["CHRDATA1.THG"]
    quantity = dos_codec.ITEM_FIELDS_BY_NAME["quantity"]
    assert _differing(node, items) == _span(quantity.span)
    assert items[quantity.offset] == 3
    # The mace weighs nothing here, so the load does not move.
    assert files["CHRDATA1.SAV"] == (folder / "CHRDATA1.SAV").read_bytes()


def test_deleting_the_only_item_empties_the_file_and_the_count(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    folder = _synthetic_folder(tmp_path)
    party = Party(convert.Source.detect(folder, slot="A"))
    [member] = party.members
    member.inventory.delete(0)
    files = saveplan.dos_files(party)
    assert files["CHRDATA1.THG"] is None
    record = files["CHRDATA1.SAV"]
    was = (folder / "CHRDATA1.SAV").read_bytes()
    count = podsheet.TABLE["item_count"]
    assert _differing(was, record) == _span(count.span)
    assert record[count.offset] == 0


# ---------------------------------------------------------------------------
# The library, every character we have
# ---------------------------------------------------------------------------

def _perturb(record: podsheet.PodSheetRecord, name: str) -> bool:
    """One edit the sheet can make to `name`; False where none applies."""
    value = record.get(name)
    if name == "spells_known":
        ids = record.known_ids()
        record.set_known_ids(ids[1:] if ids else [1])
    elif name == "spells_memorised":
        spells = record.memorised()
        record.set_memorised(spells[1:] if spells else [1])
    elif name == "name":
        record.set(name, value[:-1] + ("X" if not value.endswith("X")
                                       else "Y"))
    elif name == "class_bits":
        return False
    elif isinstance(value, bytes):
        raw = bytearray(record.get_raw(name))
        raw[0] ^= 1
        record.set_raw(name, bytes(raw))
    elif name == "sex":
        record.set(name, 1 - value)
    else:
        field = podsheet.PodSheetRecord.sheet_field(name)
        top = (1 << (8 * field.size)) - 1
        record.set(name, value + 1 if value < min(top, 250) else value - 1)
    return True


def _sheet_names(port: str) -> list[str]:
    unwritable = podsheet.unwritable(port)
    return [n for n in SHOWN if podsheet.PodSheetRecord.maps(n)
            and n not in unwritable]


def test_every_dos_field_edit_lands_on_its_own_bytes(monkeypatch):
    """Each sheet field, edited on every DOS character: the record written
    is the edited record, except that a money edit moves the load by the
    same amount, and the item and effect files are as read."""
    _flag(monkeypatch, "1")
    seen = 0
    for source in _dos_sources():
        label = f"{source.path}:{source.slot}"
        for member in Party(source).members:
            original = member.native
            for name in _sheet_names("dos"):
                after = podsheet.PodSheetRecord(member.record_original)
                if not _perturb(after, name):
                    continue
                result = pod_rewrite.rewrite_dos(
                    original, member.record_original, after.to_bytes())
                want = bytearray(after.to_bytes())
                if name in ("platinum", "gems", "jewelry"):
                    moved = (podsheet.PodSheetRecord(want).get(name)
                             - member.record.get(name))
                    was = int.from_bytes(want[ENCUMBRANCE], "little")
                    want[ENCUMBRANCE] = (was + moved).to_bytes(2, "little")
                assert result.record == bytes(want), f"{label} {name}"
                assert result.items == b"".join(
                    bytes(i) for i in original.items), label
                assert result.effects == b"".join(
                    bytes(e) for e in original.effects), label
            seen += 1
    assert seen >= 60


def test_every_dos_item_delete_drops_one_node_and_its_load(monkeypatch):
    """Deleting the first item of every DOS character who holds one: the
    item file loses exactly that node, every later node keeps its bytes --
    the ones past the sixteenth, which the sheet never shows, among them --
    the count drops by one and the load by that item's weight."""
    _flag(monkeypatch, "1")
    count = podsheet.TABLE["item_count"]
    seen = past_sixteen = 0
    for source in _dos_sources():
        for member in Party(source).members:
            items = [bytes(i) for i in member.native.items]
            if not items:
                continue
            label = f"{source.path}:{source.slot}{member.index}"
            first = member.native.items[0]
            weight = first.get("weight") * (first.get("quantity") or 1)
            member.inventory.delete(0)
            result = pod_rewrite.rewrite_dos(
                member.native, member.record_original,
                member.record.to_bytes(),
                pod_rewrite.item_blocks(member.native.items),
                member.inventory.raws)
            # Two items whose sheet slots read the same are one item to the
            # sheet, so deleting the first may keep either node.
            twin = next((n for n in range(1, min(len(items), 16)) if
                         pod_rewrite.item_blocks(member.native.items)[n]
                         != pod_rewrite.item_blocks(member.native.items)[0]),
                        len(items)) - 1
            assert result.items == b"".join(items[:twin] + items[twin + 1:]), \
                label
            was = member.record_original
            moved = set(_differing(was, result.record))
            assert moved <= set(_span(count.span)) | set(_span(ENCUMBRANCE))
            assert result.record[count.offset] == (
                was[count.offset] - 1) & 0xFF, label
            assert int.from_bytes(result.record[ENCUMBRANCE], "little") == (
                max(0, int.from_bytes(was[ENCUMBRANCE], "little") - weight))
            seen += 1
            past_sixteen += len(items) > pod_rewrite.ITEM_SLOTS
    assert seen >= 60 and past_sixteen >= 1


def test_every_amiga_field_edit_reads_back_as_the_edit(monkeypatch):
    """Each sheet field the Amiga writes, edited on every distinct Amiga
    block: only the 404-byte record moves, and reading the block back gives
    the edited sheet record -- save the load, which the DOS rendering
    recomputes from the money and the Amiga game recomputes on load."""
    _flag(monkeypatch, "1")
    blocks: dict[bytes, int] = {}
    for _label, data, slots in _amiga_images():
        disk = AmigaDisk(bytearray(data))
        for letter in slots:
            save = amiga_savegame.pod_parse(
                amiga_savegame.pod_read_slot(disk, letter))
            for position, block in enumerate(save.blocks):
                blocks.setdefault(block, position)
    if not blocks:
        pytest.skip("needs an Amiga Pools of Darkness disk 3")
    names = _sheet_names("amiga")
    exceptions: set[tuple[str, str]] = set()
    for block, position in blocks.items():
        before = podsheet.amiga_member(block, position).record
        for name in names:
            after = podsheet.PodSheetRecord(before.to_bytes())
            if not _perturb(after, name):
                continue
            written, moved = pod_rewrite.rewrite_amiga_record(
                block, before.to_bytes(), after.to_bytes())
            assert moved, name
            assert written[amiga_pod.RECORD_BYTES:] == block[
                amiga_pod.RECORD_BYTES:], name
            back = bytearray(podsheet.amiga_member(written, position)
                             .record.to_bytes())
            want = bytearray(after.to_bytes())
            if name in ("platinum", "gems", "jewelry"):
                back[ENCUMBRANCE] = want[ENCUMBRANCE]
            if name.startswith("level_"):
                levels = podsheet.TABLE["class_levels"].span
                at = amiga_pod.CLASS_LEVELS
                assert written[at:at + amiga_pod.CLASS_LEVEL_COUNT] == want[
                    levels], name
                if back != want:
                    # A dual-classed human given a level in a class he does
                    # not hold now: the block holds the level as typed, and
                    # the DOS rendering of it derives the class code and the
                    # levels from the class he left.
                    assert before.former_class() is not None, name
                    exceptions.add((before.name, name))
                    continue
            assert bytes(back) == bytes(want), name
    assert len(blocks) >= 100
    # ABAGAIL (former cleric), DONALD DUCK, jimmi hendrixs and PAINE
    # (former rangers) in the disks we have.
    assert len({who for who, _name in exceptions}) <= 4


def test_the_amiga_greys_what_it_cannot_write_back():
    assert podsheet.unwritable("dos") == podsheet.UNWRITABLE
    assert podsheet.unwritable("amiga") - podsheet.UNWRITABLE == {
        "char_class", "turn_class"}
    assert "turn_class" not in pod_rewrite.AMIGA_PLACES
    before = podsheet.PodSheetRecord(bytes(podsheet.SIZE))
    after = podsheet.PodSheetRecord(bytes(podsheet.SIZE))
    after.set("turn_class", 3)
    with pytest.raises(RewriteError, match="turn_class"):
        pod_rewrite.rewrite_amiga_record(
            bytes(amiga_pod.RECORD_LENGTH), before.to_bytes(),
            after.to_bytes())


# ---------------------------------------------------------------------------
# Save in the window, every slot we have
# ---------------------------------------------------------------------------

def test_every_dos_slot_saves_an_age_edit_and_nothing_else(
        app, monkeypatch, tmp_path):
    """Per slot, one character's age (each slot a different position) is
    edited and saved: that character's record moves at the age bytes and
    nowhere else, and every other file in the folder, the vault among them,
    is as it was. Then a Save with no edit writes nothing."""
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    slots = 0
    for n, (label, source) in enumerate(_dos_copies(tmp_path)):
        folder = pathlib.Path(source.path)
        before = _files(folder)
        window = _open(source, tmp_path / f"backups{n}")
        row = n % len(window.party)
        member = window.party.member(row)
        age = _edit_age(window, row)
        assert window.save(interactive=False) != "no changes", label
        after = _files(folder)
        target = f"CHRDAT{source.slot}{member.index}.SAV"
        assert set(after) == set(before), label
        for name in before:
            if name == target:
                assert _inside(_differing(before[name], after[name]),
                               AGE), label
                assert int.from_bytes(after[name][AGE], "little") == age
            else:
                assert after[name] == before[name], f"{label} {name}"
        assert window.save(interactive=False) == "no changes", label
        unedited = Party(source)
        for name, data in saveplan.dos_snapshot(unedited).items():
            assert data == after[name], f"{label} {name}"
        slots += 1
    assert slots >= 14


def test_every_amiga_slot_saves_an_age_edit_and_nothing_else(
        app, monkeypatch, tmp_path):
    """Per slot, one character's age is edited and saved into the disk 3
    image that was opened: the slot's saved game moves at that block's two
    age bytes and nowhere else, and every other file on the disk, the vault
    among them, is as it was. A Save with no edit leaves the image as it
    was, byte for byte."""
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    slots = 0
    for n, (label, source) in enumerate(_amiga_copies(tmp_path)):
        path = pathlib.Path(source.path)
        image = path.read_bytes()
        assert saveplan.amiga_image(Party(source)) == image, label
        before = _disk_files(image)
        window = _open(source, tmp_path / f"backups{n}")
        row = n % len(window.party)
        member = window.party.member(row)
        age = _edit_age(window, row)
        assert window.save(interactive=False) != "no changes", label
        after = _disk_files(path.read_bytes())
        target = amiga_savegame.pod_slot_path(source.slot)
        save = amiga_savegame.pod_parse(amiga_savegame.pod_read_slot(
            AmigaDisk(bytearray(image)), source.slot))
        at = save.characters[member.index - 1].at + AMIGA_AGE
        assert {k.lower() for k in after} == {k.lower() for k in before}
        for name, data in before.items():
            if name.lower() == target.lower():
                assert _inside(_differing(data, after[name]),
                               [at, at + 1]), label
                assert int.from_bytes(after[name][at:at + 2], "big") == age
            else:
                assert after[name] == data, f"{label} {name}"
        assert window.save(interactive=False) == "no changes", label
        slots += 1
    assert slots >= 51


def test_an_amiga_item_edit_stops_the_save_and_writes_nothing(
        monkeypatch, tmp_path):
    _flag(monkeypatch, "1")
    label, source = _amiga_copies(tmp_path)[0]
    party = Party(source)
    member = next(m for m in party.members if m.inventory.holds(0))
    member.inventory.set_quantity(0, member.inventory.item(0).quantity + 1)
    image = pathlib.Path(source.path).read_bytes()
    with pytest.raises(RewriteError, match="item changes"):
        saveplan.amiga_image(party)
    assert pathlib.Path(source.path).read_bytes() == image, label


def test_the_flag_is_the_one_the_open_tests_set():
    assert FLAG == convert.POD_CONVERT_ENV

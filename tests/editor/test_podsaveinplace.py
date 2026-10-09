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


STRENGTH = podsheet.TABLE["strength"].span
WISDOM = podsheet.TABLE["wisdom"].span


def test_an_ability_edit_and_a_save_move_both_bytes_of_the_pair(
        app, monkeypatch, tmp_path):
    """The DOS engine rebuilds the score in force from the permanent one, so
    the save holds the edit in both bytes of each pair."""
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    folder = _synthetic_folder(tmp_path)
    data = bytearray((folder / "CHRDATA1.SAV").read_bytes())
    data[STRENGTH] = bytes([18, 18])
    data[WISDOM] = bytes([12, 12])
    (folder / "CHRDATA1.SAV").write_bytes(bytes(data))
    before = _files(folder)
    window = _open(convert.Source.detect(folder, slot="A"), tmp_path / "b")
    window._child("roster").selectRow(0)
    window._widgets["strength"].setValue(15)
    window._widgets["wisdom"].setValue(14)
    assert window.save(interactive=False) != "no changes"
    after = _files(folder)
    record = after["CHRDATA1.SAV"]
    assert record[STRENGTH] == bytes([15, 15])
    assert record[WISDOM] == bytes([14, 14])
    assert _differing(before["CHRDATA1.SAV"], record) == [
        *_span(STRENGTH), *_span(WISDOM)]
    for name in before:
        if name != "CHRDATA1.SAV":
            assert after[name] == before[name], name


def test_an_amiga_ability_edit_moves_both_bytes_of_the_pair():
    """The Amiga block keeps the same `(permanent, in force)` pairs as DOS,
    and the exceptional-strength pair the other way round."""
    block = bytearray(amiga_pod.RECORD_BYTES)
    block[amiga_pod.ABILITIES:amiga_pod.ABILITIES + 2] = bytes([18, 18])
    block[amiga_pod.ABILITIES + 4:amiga_pod.ABILITIES + 6] = bytes([12, 12])
    at = amiga_pod.EXCEPTIONAL_STRENGTH
    block[at:at + 2] = bytes([67, 67])
    data = bytearray(podsheet.SIZE)
    data[STRENGTH] = bytes([18, 18])
    data[WISDOM] = bytes([12, 12])
    data[podsheet.TABLE["exceptional_strength"].span] = bytes([67, 67])
    before = podsheet.PodSheetRecord(bytes(data))
    after = podsheet.PodSheetRecord(before.to_bytes())
    after.set("strength", 15)
    after.set("wisdom", 14)
    after.set("exceptional_strength", 50)
    written, moved = pod_rewrite.rewrite_amiga_record(
        bytes(block), before.to_bytes(), after.to_bytes())
    assert set(moved) == {"strength", "wisdom", "exceptional_strength"}
    a = amiga_pod.ABILITIES
    assert written[a:a + 2] == bytes([15, 15])
    assert written[a + 4:a + 6] == bytes([14, 14])
    assert written[at:at + 2] == bytes([50, 50])


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
            assert bytes(back) == bytes(want), name
    assert len(blocks) >= 100


def test_the_amiga_greys_what_dos_greys():
    assert podsheet.unwritable("dos") == podsheet.UNWRITABLE
    assert podsheet.unwritable("amiga") == podsheet.UNWRITABLE
    assert pod_rewrite.AMIGA_PLACES["turn_class"].span == (
        amiga_pod.TURN_CLASS, 1)


def test_a_turn_class_edit_lands_on_the_turning_row_and_reads_back(
        monkeypatch):
    _flag(monkeypatch, "1")
    blocks = _amiga_blocks()
    for block, position in blocks.items():
        before = podsheet.amiga_member(block, position).record
        after = podsheet.PodSheetRecord(before.to_bytes())
        after.set("turn_class", 3)
        written, moved = pod_rewrite.rewrite_amiga_record(
            block, before.to_bytes(), after.to_bytes())
        assert moved == ["turn_class"]
        assert _differing(block, written) == [amiga_pod.TURN_CLASS]
        assert written[amiga_pod.TURN_CLASS] == 3
        again = podsheet.amiga_member(written, position).record
        assert again.get("turn_class") == 3


def test_a_class_code_and_a_level_in_an_unheld_class_read_back_as_typed(
        monkeypatch):
    """A class code typed into the box and a level typed into a class a
    dual-classed human left (ABAGAIL, given cleric 1) are the block's own
    bytes, so reopening shows them."""
    _flag(monkeypatch, "1")
    dual = 0
    for block, position in _amiga_blocks().items():
        before = podsheet.amiga_member(block, position).record
        code = podsheet.PodSheetRecord(before.to_bytes())
        code.set("char_class", (before.get("char_class") + 1) & 0xFF)
        written, _moved = pod_rewrite.rewrite_amiga_record(
            block, before.to_bytes(), code.to_bytes())
        assert podsheet.amiga_member(written, position).record.get(
            "char_class") == code.get("char_class")
        if before.former_class() is None:
            continue
        dual += 1
        level = podsheet.PodSheetRecord(before.to_bytes())
        level.set("level_cleric", 1 if not before.get("level_cleric")
                  else before.get("level_cleric") + 1)
        written, _moved = pod_rewrite.rewrite_amiga_record(
            block, before.to_bytes(), level.to_bytes())
        again = podsheet.amiga_member(written, position).record
        assert again.get("level_cleric") == level.get("level_cleric")
        assert again.to_bytes()[podsheet.TABLE["class_levels"].span] == (
            level.to_bytes()[podsheet.TABLE["class_levels"].span])
    assert dual >= 1


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


# ---------------------------------------------------------------------------
# Amiga items
# ---------------------------------------------------------------------------

def _slots() -> list[tuple[str, bytes, amiga_savegame.PodSavegame]]:
    out = []
    for label, data, letters in _amiga_images():
        disk = AmigaDisk(bytearray(data))
        for letter in letters:
            blob = amiga_savegame.pod_read_slot(disk, letter)
            out.append((f"{label}:{letter}", blob,
                        amiga_savegame.pod_parse(blob)))
    if not out:
        pytest.skip("needs an Amiga Pools of Darkness disk 3")
    return out


def _amiga_blocks() -> dict[bytes, int]:
    blocks: dict[bytes, int] = {}
    for _label, _blob, save in _slots():
        for position, block in enumerate(save.blocks):
            blocks.setdefault(block, position)
    return blocks


def _shown(block: bytes, position: int = 0) -> list[bytes]:
    """The sixteen sheet slots the block opens with."""
    return podsheet.item_blocks(podsheet.amiga_member(block, position).dos)


def _first_sixteen(char) -> list[bytes]:
    return podsheet.item_blocks(char)


def _count(block: bytes) -> int:
    return int.from_bytes(block[amiga_pod.ITEM_CHAIN:
                                amiga_pod.ITEM_CHAIN + 4], "big")


def _items_end(block: bytes) -> int:
    heads, chains, tail = pod_rewrite._amiga_nodes(block)
    return len(block) - len(tail)


def _case_blocks() -> dict[bytes, int]:
    return {b: p for b, p in _amiga_blocks().items()
            if any(c is not None for _h, c in
                   pod_rewrite.amiga_item_sources(b))}


def _edit(block: bytes, position: int, change) -> tuple[bytes, list[str]]:
    was = _shown(block, position)
    now = list(was)
    change(now)
    return pod_rewrite.rewrite_amiga_items(block, was, now)


def _head_item_zero(block: bytes) -> bool:
    """Whether sheet slot 0 is a head node of its own, not a case's scroll."""
    sources = pod_rewrite.amiga_item_sources(block)
    return bool(sources) and sources[0][1] is None


def test_an_unedited_amiga_save_round_trips_byte_for_byte(monkeypatch):
    _flag(monkeypatch, "1")
    for label, blob, save in _slots():
        assert pod_rewrite.rebuild_party(blob, save.blocks) == blob, label
    for block, position in _amiga_blocks().items():
        was = _shown(block, position)
        assert pod_rewrite.rewrite_amiga_items(block, was, was) == (
            block, [])


def test_an_amiga_quantity_edit_moves_only_that_nodes_quantity_byte(
        monkeypatch):
    _flag(monkeypatch, "1")
    seen = 0
    for block, position in _amiga_blocks().items():
        if not _head_item_zero(block):
            continue

        def edit(now):
            raw = bytearray(now[0])
            raw[10] = raw[10] + 1 if raw[10] < 255 else raw[10] - 1
            now[0] = bytes(raw)
        out, moved = _edit(block, position, edit)
        assert moved == ["item 0: quantity"]
        assert _differing(block, out) == [
            amiga_pod.RECORD_BYTES + pod_rewrite._QUANTITY_AT]
        seen += 1
    assert seen >= 100


def test_an_amiga_item_delete_drops_one_node_and_every_other_block_stays(
        monkeypatch, tmp_path):
    """Deleting item 0 of a block: it is 20 bytes shorter and its count one
    lower, the file keeps its size and parses, every other block is as it
    was, and reopening shows the slots without that item."""
    _flag(monkeypatch, "1")
    seen = 0
    for label, blob, save in _slots():
        for n, block in enumerate(save.blocks):
            if not _head_item_zero(block):
                continue
            was = _shown(block, n)
            now = was[1:] + [bytes(len(was[0]))]
            out, moved = pod_rewrite.rewrite_amiga_items(block, was, now)
            # Two items whose slots read the same are one item to the
            # sheet, so deleting the first may drop either node.
            assert [m for m in moved if m.endswith("deleted")] == [
                moved[-1]], label
            assert len(out) == len(block) - amiga_pod.ITEM_FILE_SIZE
            assert _count(out) == _count(block) - 1
            blocks = list(save.blocks)
            blocks[n] = out
            written = pod_rewrite.rebuild_party(blob, blocks)
            assert len(written) == amiga_savegame.POD_SAVEGAME_SIZE, label
            again = amiga_savegame.pod_parse(written)
            assert [b for i, b in enumerate(again.blocks) if i != n] == [
                b for i, b in enumerate(save.blocks) if i != n], label
            assert again.blocks[n] == out
            old = podsheet.amiga_member(block, n).dos
            expect = [dos_codec.item_to_c64(i.to_bytes())
                      for i in old.items[1:pod_rewrite.ITEM_SLOTS + 1]]
            expect += [bytes(len(was[0]))] * (pod_rewrite.ITEM_SLOTS
                                              - len(expect))
            assert _shown(out, n) == expect, label
            seen += 1
    assert seen >= 100


def test_an_item_delete_saved_through_the_editor_reaches_the_disk(
        monkeypatch, tmp_path):
    """The whole path, `saveplan.amiga_image` over a party: a deleted item is
    gone from the slot's saved game, the other slots and files are as they
    were, and a party with no edit gives the image back."""
    _flag(monkeypatch, "1")
    label, source = _amiga_copies(tmp_path)[0]
    image = pathlib.Path(source.path).read_bytes()
    party = Party(source)
    member = next(m for m in party.members
                  if m.inventory.holds(0) and _head_item_zero(bytes(m.native)))
    member.inventory.delete(0)
    written = saveplan.amiga_image(party)
    assert written != image
    was = _disk_files(image)
    now = _disk_files(written)
    target = amiga_savegame.pod_slot_path(source.slot)
    for name in was:
        if name.lower() != target.lower():
            assert now[name] == was[name], f"{label} {name}"
    spelled = next(k for k in was if k.lower() == target.lower())
    before = amiga_savegame.pod_parse(was[spelled])
    after = amiga_savegame.pod_parse(now[spelled])
    assert len(now[spelled]) == amiga_savegame.POD_SAVEGAME_SIZE
    index = member.index - 1
    assert _count(after.blocks[index]) == _count(before.blocks[index]) - 1
    assert [b for i, b in enumerate(after.blocks) if i != index] == [
        b for i, b in enumerate(before.blocks) if i != index]


def test_deleting_a_case_scroll_lowers_the_case_and_keeps_the_others(
        monkeypatch):
    _flag(monkeypatch, "1")
    cases = _case_blocks()
    if not cases:
        pytest.skip("needs an Amiga disk 3 whose saved game holds a case")
    for block, position in cases.items():
        sources = pod_rewrite.amiga_item_sources(block)
        slot = next(n for n, (_h, c) in enumerate(sources)
                    if c is not None and n < pod_rewrite.ITEM_SLOTS)
        head, chain = sources[slot]
        heads, chains, _tail = pod_rewrite._amiga_nodes(block)

        def drop(now):
            now[:] = now[:slot] + now[slot + 1:] + [bytes(len(now[0]))]
        out, moved = _edit(block, position, drop)
        assert _count(out) == _count(block)
        assert len(out) == len(block) - amiga_pod.ITEM_FILE_SIZE
        new_heads, new_chains, new_tail = pod_rewrite._amiga_nodes(out)
        assert new_heads[head][pod_rewrite._QUANTITY_AT] == len(chains[head]) - 1
        assert new_chains[head] == chains[head][:chain] + chains[head][
            chain + 1:]
        assert new_tail == _tail
        for h in range(len(heads)):
            if h != head:
                assert new_heads[h] == heads[h]
                assert new_chains[h] == chains[h]


def test_deleting_every_scroll_of_a_case_removes_the_case(monkeypatch):
    _flag(monkeypatch, "1")
    cases = _case_blocks()
    if not cases:
        pytest.skip("needs an Amiga disk 3 whose saved game holds a case")
    for block, position in cases.items():
        sources = pod_rewrite.amiga_item_sources(block)
        heads, chains, _tail = pod_rewrite._amiga_nodes(block)
        head = next(h for h, c in sources if c is not None)
        gone = {n for n, (h, _c) in enumerate(sources) if h == head}
        if max(gone) >= pod_rewrite.ITEM_SLOTS:
            continue

        def drop(now):
            kept = [b for n, b in enumerate(now) if n not in gone]
            now[:] = kept + [bytes(len(now[0]))] * (len(now) - len(kept))
        out, _moved = _edit(block, position, drop)
        assert _count(out) == _count(block) - 1
        assert len(out) == len(block) - amiga_pod.ITEM_FILE_SIZE * (
            1 + len(chains[head]))
        assert pod_rewrite._amiga_nodes(out)[2] == _tail
        assert _items_end(out) + len(_tail) == len(out)


def test_a_readied_edit_on_a_case_scroll_lands_on_the_case_and_shows_on_all(
        monkeypatch):
    """The sheet shows each scroll with its case's `readied`, so the edit
    goes to the case's head node and every scroll of the case shows it on
    reopening."""
    from editor.inventory import READIED
    _flag(monkeypatch, "1")
    cases = _case_blocks()
    if not cases:
        pytest.skip("needs an Amiga disk 3 whose saved game holds a case")
    readied_at = amiga_pod.ITEM_FIELD_AT["readied"]
    for block, position in cases.items():
        sources = pod_rewrite.amiga_item_sources(block)
        slot, (head, _c) = next((n, s) for n, s in enumerate(sources)
                                if s[1] is not None)
        was = _shown(block, position)
        new_value = (was[slot][6] & READIED) ^ READIED

        def flip(now):
            raw = bytearray(now[slot])
            raw[6] = (raw[6] & ~READIED) | new_value
            now[slot] = bytes(raw)
        out, moved = _edit(block, position, flip)
        assert moved == [f"item {slot}: readied"]
        heads, chains, _tail = pod_rewrite._amiga_nodes(block)
        new_heads, new_chains, _t = pod_rewrite._amiga_nodes(out)
        assert new_heads[head][readied_at] != heads[head][readied_at]
        assert new_chains == chains
        reopened = _shown(out, position)
        mine = [n for n, (h, _c2) in enumerate(sources)
                if h == head and n < pod_rewrite.ITEM_SLOTS]
        assert len(mine) > 1
        assert all(reopened[n][6] & READIED == new_value for n in mine)


def test_the_other_scrolls_of_a_case_show_the_new_readied_at_once(
        monkeypatch, tmp_path):
    """The case keeps one `readied`, so the inventory model updates every row
    of the case when one is edited, and a Save writes the same value that a
    reopened party shows on all of them."""
    from editor.inventory import READIED
    _flag(monkeypatch, "1")
    for label, source in _amiga_copies(tmp_path):
        party = Party(source)
        member = next((m for m in party.members if any(
            c is not None for _h, c in
            pod_rewrite.amiga_item_sources(bytes(m.native)))), None)
        if member is None:
            continue
        sources = pod_rewrite.amiga_item_sources(bytes(member.native))
        slot, (head, _c) = next((n, s) for n, s in enumerate(sources)
                                if s[1] is not None)
        mine = [n for n, (h, _c2) in enumerate(sources)
                if h == head and n < pod_rewrite.ITEM_SLOTS]
        assert len(mine) > 1
        old = member.inventory.raws[slot][6] & READIED
        member.inventory.set_readied(slot, not old)
        assert all(bool(member.inventory.raws[n][6] & READIED) == (not old)
                   for n in mine)
        pathlib.Path(source.path).write_bytes(saveplan.amiga_image(party))
        reopened = Party(source).member(member.index - 1)
        assert all(bool(reopened.inventory.raws[n][6] & READIED) == (not old)
                   for n in mine)
        return
    pytest.skip("needs an Amiga disk 3 whose saved game holds a case")


def test_a_case_s_rows_follow_each_other_through_a_delete():
    from editor.inventory import EMPTY, READIED, Inventory
    item = bytearray(len(EMPTY))
    item[0] = 1
    plain = bytes(item)
    inventory = Inventory.from_blocks([plain] * 3 + [EMPTY] * 13)
    inventory.set_cases([None, 7, 7] + [None] * 13)
    inventory.delete(0)
    inventory.set_readied(0, True)
    assert [bool(inventory.raws[n][6] & READIED) for n in range(3)] == [
        True, True, False]


def test_the_item_picker_never_offers_an_item_to_an_amiga_save(
        app, monkeypatch, tmp_path):
    """An Amiga Pools of Darkness window has no item templates, so the add
    button is off and `add_item` copies nothing; a DOS item of type 105, which
    would become an Amiga scroll case with no chained scrolls, cannot be
    added."""
    _flag(monkeypatch, "1")
    window = _open(convert.Source.detect(_synthetic_folder(tmp_path),
                                         slot="A"), tmp_path / "b")
    window.party.port = "amiga"
    window._apply_read_only()
    window._populate()
    assert window.templates == {}
    assert not window._child("button_item_add").isEnabled()
    assert window._child("button_item_add").toolTip() == ""
    before = list(window.items.inventory.raws)
    assert window.add_item("any") == "no game disk, so no items to copy"
    assert window.items.inventory.raws == before


def test_an_added_amiga_item_becomes_a_new_head_node(monkeypatch):
    _flag(monkeypatch, "1")
    seen = 0
    for block, position in _amiga_blocks().items():
        was = _shown(block, position)
        shown = sum(1 for raw in was if any(raw))
        if shown == 0 or shown >= pod_rewrite.ITEM_SLOTS or any(
                c is not None for _h, c in
                pod_rewrite.amiga_item_sources(block)):
            continue
        dos = bytearray(podsheet.amiga_member(block, position)
                        .dos.items[0].to_bytes())
        dos[podsheet.dos_codec.ITEM_FIELDS_BY_NAME["quantity"].offset] = 7
        dos[podsheet.dos_codec.ITEM_FIELDS_BY_NAME["type_index"].offset] = 0x7E
        new = dos_codec.item_to_c64(bytes(dos))
        assert new not in was
        now = list(was)
        now[shown] = new
        out, moved = pod_rewrite.rewrite_amiga_items(block, was, now)
        assert moved == [f"item {shown}: added"]
        assert _count(out) == _count(block) + 1
        at = _items_end(block)
        assert out[at:at + amiga_pod.ITEM_FILE_SIZE] == (
            amiga_pod.PodItem.from_dos_bytes(bytes(dos)).raw)
        assert out[amiga_pod.RECORD_BYTES:at] == block[
            amiga_pod.RECORD_BYTES:at]
        assert _shown(out, position)[shown] == new
        seen += 1
    assert seen >= 50


def test_the_bytes_no_field_owns_survive_an_edit_to_another_field(
        monkeypatch):
    """Item node bytes 1 and 13 and the `hidden` bits above 7 belong to no
    DOS field; an edit to the quantity of the same node keeps them."""
    _flag(monkeypatch, "1")
    seen = 0
    for block, position in _amiga_blocks().items():
        if not _head_item_zero(block):
            continue
        marked = bytearray(block)
        at = amiga_pod.RECORD_BYTES
        marked[at + 1], marked[at + 13] = 0x84, 0xC2
        hidden = at + amiga_pod.ITEM_FIELD_AT["hidden"]
        marked[hidden] |= 0x40
        marked = bytes(marked)

        def edit(now):
            raw = bytearray(now[0])
            raw[10] = raw[10] + 1 if raw[10] < 255 else raw[10] - 1
            now[0] = bytes(raw)
        out, _moved = _edit(marked, position, edit)
        assert out[at + 1] == 0x84 and out[at + 13] == 0xC2
        assert out[hidden] & 0x40
        seen += 1
        if seen == 10:
            break
    assert seen == 10


def test_rebuild_party_stops_when_the_party_no_longer_fits(monkeypatch):
    _flag(monkeypatch, "1")
    label, blob, save = _slots()[0]
    with pytest.raises(RewriteError, match="past the"):
        pod_rewrite.rebuild_party(
            blob, [save.blocks[0] + bytes(amiga_savegame.POD_SAVEGAME_SIZE)]
            + list(save.blocks[1:]))
    with pytest.raises(RewriteError, match="characters"):
        pod_rewrite.rebuild_party(blob, save.blocks[:-1])


def _dual_class_record(tmp_path) -> podsheet.PodSheetRecord:
    folder = _synthetic_folder(tmp_path)
    return podsheet.PodSheetRecord((folder / "CHRDATA1.SAV").read_bytes())


def test_on_dos_a_level_in_a_class_not_held_reads_back_as_typed(tmp_path):
    """The record keeps the byte and the sheet reads it."""
    before = _dual_class_record(tmp_path)
    after = podsheet.PodSheetRecord(before.to_bytes())
    after.set("level_fighter", 3)
    spans, _unplaced = pod_rewrite.rewrite.dos_spans(pod_rewrite.DELTAS)
    written, _moved = pod_rewrite.rewrite.patch(
        before.to_bytes(), before.to_bytes(), after.to_bytes(), spans)
    back = podsheet.PodSheetRecord(written)
    assert back.to_bytes() == after.to_bytes()
    assert back.get("level_fighter") == 3
    assert back.get("level_magic_user") == 9


def test_an_added_item_moves_encumbrance_by_its_weight_on_dos(
        monkeypatch, tmp_path):
    """An item added from a template reaches the DOS save, and the stored
    load is then the DOS writer's sum (`DosCharacter.expected_encumbrance`)
    of the files written."""
    _flag(monkeypatch, "1")
    folder = _synthetic_folder(tmp_path)
    # The synthetic record stores no load; give it the one its money and its
    # one weightless item add up to, as the engine would.
    record = podsheet.PodSheetRecord((folder / "CHRDATA1.SAV").read_bytes())
    record.set("encumbrance", record.get("platinum"))
    (folder / "CHRDATA1.SAV").write_bytes(record.to_bytes())
    party = Party(convert.Source.detect(folder, slot="A"))
    [member] = party.members
    where = member.inventory.add(bytes(member.inventory.raws[0]))
    assert where == 1
    member.inventory.set_weight_tenths(1, 50)
    member.inventory.set_quantity(1, 2)
    files = saveplan.dos_files(party)
    record = files["CHRDATA1.SAV"]
    items = dos_codec.item_nodes(files["CHRDATA1.THG"],
                                 pod_rewrite.DELTAS.item_size)
    assert len(items) == 2
    stored = int.from_bytes(record[ENCUMBRANCE], "little")
    rebuilt = dos_codec.DosCharacter(
        record, items, [], deltas=pod_rewrite.DELTAS)
    assert rebuilt.expected_encumbrance() > 0
    assert stored == rebuilt.expected_encumbrance()
    assert record[podsheet.TABLE["item_count"].offset] == 2


def test_the_flag_is_the_one_the_open_tests_set():
    assert FLAG == convert.POD_CONVERT_ENV


def _block_with_empty_case(monkeypatch, tmp_path) -> bytes:
    """A synthetic Amiga block of three head nodes: a mace, a scroll case
    that holds no scroll, and the mace again with a different bonus."""
    _flag(monkeypatch, "1")
    [member] = Party(convert.Source.detect(
        _synthetic_folder(tmp_path), slot="A")).members
    mace = bytearray(amiga_pod.PodItem.from_dos_bytes(
        member.native.items[0].to_bytes()).raw)
    case = bytearray(mace)
    case[amiga_pod.ITEM_FIELD_AT["type_index"]] = amiga_pod.SCROLL_TYPE_INDEX
    case[pod_rewrite._QUANTITY_AT] = 0
    other = bytearray(mace)
    other[amiga_pod.ITEM_FIELD_AT["plus"]] ^= 1
    block = bytearray(amiga_pod.RECORD_BYTES)
    block[amiga_pod.ITEM_CHAIN:amiga_pod.ITEM_CHAIN + 4] = (3).to_bytes(
        4, "big")
    return bytes(block + mace + case + other)


def test_an_empty_case_survives_an_edit_to_another_item(monkeypatch, tmp_path):
    block = _block_with_empty_case(monkeypatch, tmp_path)
    heads, _chains, _tail = pod_rewrite._amiga_nodes(block)
    assert amiga_pod.PodItem(bytes(heads[1])).is_scroll
    was = _shown(block)
    assert sum(1 for raw in was if any(raw)) == 2
    now = list(was)
    raw = bytearray(now[0])
    raw[4] = (raw[4] + 5) & 0xFF
    now[0] = bytes(raw)
    out, moved = pod_rewrite.rewrite_amiga_items(block, was, now)
    assert len(moved) == 1 and moved[0].startswith("item 0: ")
    assert _count(out) == 3
    new_heads, _c, _t = pod_rewrite._amiga_nodes(out)
    assert new_heads[1] == heads[1]
    assert new_heads[2] == heads[2]


def test_an_empty_case_stays_after_the_head_it_followed_when_one_is_deleted(
        monkeypatch, tmp_path):
    block = _block_with_empty_case(monkeypatch, tmp_path)
    heads, _chains, _tail = pod_rewrite._amiga_nodes(block)
    was = _shown(block)
    now = [was[1]] + [bytes(len(was[0]))] * (len(was) - 1)
    out, _moved = pod_rewrite.rewrite_amiga_items(block, was, now)
    new_heads, _c, _t = pod_rewrite._amiga_nodes(out)
    assert new_heads == [heads[1], heads[2]]
    assert _count(out) == 2


# A Pools of Darkness scroll case: what an edit leaves of it.  The nodes are
# built here field by field; no byte comes from a game file.
_AT = amiga_pod.ITEM_FIELD_AT


def _scroll_node(spells: tuple[int, int, int], readied: int = 0,
                 weight: int = 1) -> bytes:
    """A synthetic chained scroll node: type 39, three spell ids."""
    node = bytearray(amiga_pod.ITEM_FILE_SIZE)
    node[_AT["type_index"]] = 0x27
    node[_AT["name1"]] = 100 + sum(1 for s in spells if s)
    node[_AT["name2"]], node[_AT["name3"]] = 0x27, 0x28
    node[_AT["plus"]] = 1
    node[_AT["readied"]] = readied
    node[_AT["weight"]:_AT["weight"] + 2] = weight.to_bytes(2, "big")
    node[_AT["charges"]], node[_AT["effect"]], node[_AT["power"]] = spells
    return bytes(node)


_SCROLLS = (_scroll_node((11, 22, 33)), _scroll_node((44, 0, 55)),
            _scroll_node((66, 77, 88)))


def _block_with_case(monkeypatch, tmp_path, scrolls=_SCROLLS) -> bytes:
    """A synthetic Amiga block: a mace, a readied case of `scrolls` that
    weighs 4, and a second mace."""
    _flag(monkeypatch, "1")
    [member] = Party(convert.Source.detect(
        _synthetic_folder(tmp_path), slot="A")).members
    mace = bytearray(amiga_pod.PodItem.from_dos_bytes(
        member.native.items[0].to_bytes()).raw)
    case = bytearray(amiga_pod.ITEM_FILE_SIZE)
    case[_AT["type_index"]] = amiga_pod.SCROLL_TYPE_INDEX
    case[_AT["readied"]] = 1
    case[_AT["weight"]:_AT["weight"] + 2] = (4).to_bytes(2, "big")
    case[pod_rewrite._QUANTITY_AT] = len(scrolls)
    other = bytearray(mace)
    other[_AT["plus"]] ^= 1
    block = bytearray(amiga_pod.RECORD_BYTES)
    block[amiga_pod.ITEM_CHAIN:amiga_pod.ITEM_CHAIN + 4] = (3).to_bytes(
        4, "big")
    return bytes(block + mace + case + b"".join(scrolls) + other)


def _keep(was: list[bytes], gone: set[int]) -> list[bytes]:
    kept = [b for n, b in enumerate(was) if n not in gone]
    return kept + [bytes(len(was[0]))] * (len(was) - len(kept))


def test_a_case_left_with_two_scrolls_stays_a_case_of_two(
        monkeypatch, tmp_path):
    block = _block_with_case(monkeypatch, tmp_path)
    heads, _chains, _tail = pod_rewrite._amiga_nodes(block)
    out, _moved = pod_rewrite.rewrite_amiga_items(
        block, _shown(block), _keep(_shown(block), {2}))
    new_heads, new_chains, _t = pod_rewrite._amiga_nodes(out)
    assert _count(out) == 3
    assert new_heads[1][pod_rewrite._QUANTITY_AT] == 2
    assert [bytes(n) for n in new_chains[1]] == [_SCROLLS[0], _SCROLLS[2]]
    assert new_heads[0] == heads[0] and new_heads[2] == heads[2]


def test_a_case_left_with_one_scroll_becomes_that_scroll(monkeypatch,
                                                         tmp_path):
    """The game copies the last scroll's node over the case: the item is
    that scroll, with its own `readied` and weight, and no case is left."""
    block = _block_with_case(monkeypatch, tmp_path)
    heads, _chains, tail = pod_rewrite._amiga_nodes(block)
    out, moved = pod_rewrite.rewrite_amiga_items(
        block, _shown(block), _keep(_shown(block), {1, 2}))
    new_heads, new_chains, new_tail = pod_rewrite._amiga_nodes(out)
    assert _count(out) == 3
    assert [bytes(h) for h in new_heads] == [heads[0], _SCROLLS[2], heads[2]]
    assert new_chains == [[], [], []]
    assert new_tail == tail
    assert len(out) == len(block) - 3 * amiga_pod.ITEM_FILE_SIZE
    assert "item 1: case of one scroll written as that scroll" in moved
    # The sheet shows it as an item of its own, not readied.
    assert pod_rewrite.amiga_item_sources(out)[1] == (1, None)
    from editor.inventory import READIED
    reopened = _shown(out)
    assert not reopened[1][6] & READIED
    assert reopened[1][:4] == _shown(block)[3][:4]


def test_a_lone_scroll_keeps_a_readied_edit_made_on_its_row(monkeypatch,
                                                            tmp_path):
    from editor.inventory import READIED
    block = _block_with_case(monkeypatch, tmp_path)
    was = _shown(block)
    assert was[3][6] & READIED
    now = _keep(was, {1, 2})
    raw = bytearray(now[1])
    raw[6] &= ~READIED
    now[1] = bytes(raw)
    out, _moved = pod_rewrite.rewrite_amiga_items(block, was, now)
    assert pod_rewrite._amiga_nodes(out)[0][1] == bytearray(_SCROLLS[2])
    # A readied edit on an unreadied case's last scroll is kept.
    (tmp_path / "2").mkdir()
    block = _block_with_case(monkeypatch, tmp_path / "2")
    off = bytearray(block)
    off[amiga_pod.RECORD_BYTES + amiga_pod.ITEM_FILE_SIZE + _AT["readied"]] = 0
    was = _shown(bytes(off))
    now = _keep(was, {1, 2})
    raw = bytearray(now[1])
    raw[6] |= READIED
    now[1] = bytes(raw)
    out, _moved = pod_rewrite.rewrite_amiga_items(bytes(off), was, now)
    lone = pod_rewrite._amiga_nodes(out)[0][1]
    assert lone[_AT["readied"]] == 1
    assert bytes(lone[:7]) == _SCROLLS[2][:7]
    assert bytes(lone[8:]) == _SCROLLS[2][8:]


def test_a_case_left_with_no_scroll_is_removed(monkeypatch, tmp_path):
    block = _block_with_case(monkeypatch, tmp_path)
    heads, _chains, tail = pod_rewrite._amiga_nodes(block)
    out, _moved = pod_rewrite.rewrite_amiga_items(
        block, _shown(block), _keep(_shown(block), {1, 2, 3}))
    new_heads, _c, new_tail = pod_rewrite._amiga_nodes(out)
    assert [bytes(h) for h in new_heads] == [heads[0], heads[2]]
    assert _count(out) == 2 and new_tail == tail


def test_a_case_of_one_already_in_the_file_is_written_as_its_scroll(
        monkeypatch, tmp_path):
    """An edit to another item writes a case of one, as an earlier Wish
    left it, as the scroll the game would have made of it."""
    block = _block_with_case(monkeypatch, tmp_path, _SCROLLS[1:2])
    was = _shown(block)
    now = list(was)
    raw = bytearray(now[0])
    raw[4] = (raw[4] + 5) & 0xFF
    now[0] = bytes(raw)
    out, _moved = pod_rewrite.rewrite_amiga_items(block, was, now)
    assert bytes(pod_rewrite._amiga_nodes(out)[0][1]) == _SCROLLS[1]
    assert _count(out) == 3


def test_dos_scrolls_left_two_one_and_none_stay_items_of_their_own(
        monkeypatch, tmp_path):
    """DOS keeps no case: each scroll is an item, and a delete drops only
    its own node, whatever is left."""
    _flag(monkeypatch, "1")
    for kept in (2, 1, 0):
        (tmp_path / str(kept)).mkdir()
        folder = _synthetic_folder(tmp_path / str(kept))
        record = podsheet.PodSheetRecord(
            (folder / "CHRDATA1.SAV").read_bytes())
        record.set("item_count", 4)
        (folder / "CHRDATA1.SAV").write_bytes(record.to_bytes())
        mace = (folder / "CHRDATA1.THG").read_bytes()
        scrolls = [amiga_pod.PodItem.from_bytes(n).to_dos_bytes()
                   for n in _SCROLLS]
        (folder / "CHRDATA1.THG").write_bytes(mace + b"".join(scrolls))
        party = Party(convert.Source.detect(folder, slot="A"))
        [member] = party.members
        for _ in range(3 - kept):
            member.inventory.delete(1)
        files = saveplan.dos_files(party)
        nodes = dos_codec.item_nodes(files["CHRDATA1.THG"],
                                     pod_rewrite.DELTAS.item_size)
        assert [bytes(n) for n in nodes] == [mace] + scrolls[3 - kept:]
        assert files["CHRDATA1.SAV"][
            podsheet.TABLE["item_count"].offset] == 1 + kept


def test_a_short_case_list_leaves_the_remaining_slots_outside_any_case():
    from editor.inventory import EMPTY, Inventory
    inventory = Inventory.from_blocks([EMPTY] * 16)
    inventory.set_cases([3, 3])
    assert inventory._case_mates(0) == [0, 1]
    assert inventory._case_mates(1) == [0, 1]
    assert inventory._case_mates(5) == [5]


def _abagail_like() -> podsheet.PodSheetRecord:
    data = bytearray(podsheet.SIZE)
    data[podsheet.TABLE["class_levels"].offset + podsheet.LEVEL_SLOTS[
        "level_magic_user"]] = 12
    data[podsheet.TABLE["level"].offset] = 12
    return podsheet.PodSheetRecord(bytes(data))


def test_raising_a_class_level_raises_the_level_byte_on_dos():
    before = _abagail_like()
    after = podsheet.PodSheetRecord(before.to_bytes())
    after.set("level_magic_user", 13)
    assert after.get("level") == 13
    spans, _unplaced = pod_rewrite.rewrite.dos_spans(pod_rewrite.DELTAS)
    written, moved = pod_rewrite.rewrite.patch(
        before.to_bytes(), before.to_bytes(), after.to_bytes(), spans)
    assert "level" in moved
    assert podsheet.PodSheetRecord(written).get("level") == 13


def test_raising_a_class_level_raises_the_level_byte_on_the_amiga():
    before = _abagail_like()
    after = podsheet.PodSheetRecord(before.to_bytes())
    after.set("level_magic_user", 13)
    block = bytearray(amiga_pod.RECORD_BYTES)
    block[amiga_pod.LEVEL] = 12
    written, moved = pod_rewrite.rewrite_amiga_record(
        bytes(block), before.to_bytes(), after.to_bytes())
    assert "level" in moved
    assert written[amiga_pod.LEVEL] == 13


def test_lowering_a_class_level_keeps_the_level_byte():
    before = _abagail_like()
    after = podsheet.PodSheetRecord(before.to_bytes())
    after.set("level_magic_user", 9)
    assert after.get("level") == 12


# ---------------------------------------------------------------------------
# A class-level edit on the Amiga runs the game's recompute
# ---------------------------------------------------------------------------

#: The bytes the recompute writes that a level edit has to move with it.
_RECOMPUTED = ([amiga_pod.THAC0_BASE, amiga_pod.ATTACK_FORMS,
                amiga_pod.CLASS_BITS, amiga_pod.LEVEL]
               + list(range(0x083, 0x088)))
_FIGHTER = "level_fighter"


def _fighter_candidates(source):
    """Members holding only the fighter class at level 7-12 that the
    recompute can run on."""
    for member in Party(source).members:
        record = member.record
        levels = list(amiga_pod.PodCharacter.from_bytes(
            bytes(member.native)).class_levels)
        if not 7 <= record.get(_FIGHTER) <= 12 or sum(levels) != levels[2]:
            continue
        yield member


def _recomputed(member, level: int) -> bytearray:
    """What the game's recompute makes of the member's block at `level`."""
    from goldbox import amiga_pod_recompute as pr
    block = bytes(member.native)
    rec = bytearray(block[:amiga_pod.RECORD_BYTES])
    rec[amiga_pod.CLASS_LEVELS + 2] = level
    items = [bytes(amiga_pod.ITEM_NODE_BASE) + item.raw
             for item in amiga_pod.PodCharacter.from_bytes(block).items]
    pr.pod_check(rec)
    pr.pod_recompute(rec, items)
    return rec


def _saved_block(source, written: bytes, member) -> bytes:
    save = amiga_savegame.pod_parse(amiga_savegame.pod_read_slot(
        AmigaDisk(bytearray(written)), source.slot))
    return save.blocks[member.index - 1]


def test_a_level_edit_saves_the_recomputed_thac0_saves_and_attacks(
        monkeypatch, tmp_path):
    """A fighter raised from level 12 to 13 is written with the THAC0, saves
    and attacks the game's recompute gives, and the current THAC0 moves by the
    base's change, because the Amiga load copies one into the other and
    never runs the recompute itself."""
    _flag(monkeypatch, "1")
    from goldbox import amiga_pod_recompute as pr
    for _label, source in _amiga_copies(tmp_path):
        for member in _fighter_candidates(source):
            level = member.record.get(_FIGHTER)
            try:
                want = _recomputed(member, level + 1)
            except pr.RecomputeError:
                continue
            native = bytes(member.native)
            if (want[amiga_pod.THAC0_BASE] == native[amiga_pod.THAC0_BASE]
                    and want[amiga_pod.ATTACK_FORMS]
                    == native[amiga_pod.ATTACK_FORMS]):
                continue
            party = Party(source)
            party.members[member.index - 1].record.set(_FIGHTER, level + 1)
            written = saveplan.amiga_image(party)
            block = _saved_block(source, written, member)
            for at in _RECOMPUTED:
                assert block[at] == want[at], hex(at)
            moved = want[amiga_pod.THAC0_BASE] - native[amiga_pod.THAC0_BASE]
            assert block[amiga_pod.THAC0_CURRENT] == (
                native[amiga_pod.THAC0_CURRENT] + moved) & 0xFF
            return
    pytest.skip("needs an Amiga fighter at level 7-12 whose next level "
                "moves THAC0 or attacks")


def test_an_edit_that_moves_no_class_level_leaves_hand_set_values_alone(
        monkeypatch, tmp_path):
    """An age edit writes no recompute: the THAC0, saves, attacks, class mask
    and spell slots stay as they were read, which keeps a hand-set record's
    values."""
    _flag(monkeypatch, "1")
    from goldbox import amiga_pod_recompute as pr
    for _label, source in _amiga_copies(tmp_path):
        for member in Party(source).members:
            native = bytes(member.native)
            rec = bytearray(native[:amiga_pod.RECORD_BYTES])
            items = [bytes(amiga_pod.ITEM_NODE_BASE) + item.raw for item in
                     amiga_pod.PodCharacter.from_bytes(native).items]
            try:
                pr.pod_check(rec)
                pr.pod_recompute(rec, items)
            except pr.RecomputeError:
                continue
            if rec[:0x18A] != native[:0x18A]:
                break
        else:
            continue
        break
    else:
        pytest.skip("needs an Amiga record the recompute would change")
    party = Party(source)
    member = party.members[member.index - 1]
    member.record.set("age", member.record.get("age") + 1)
    written = saveplan.amiga_image(party)
    block = _saved_block(source, written, member)
    assert block[amiga_pod.THAC0_CURRENT] == native[amiga_pod.THAC0_CURRENT]
    for at in _RECOMPUTED + list(range(0x169, 0x169 + 27)):
        assert block[at] == native[at], hex(at)


def test_a_record_the_recompute_cannot_cover_saves_its_level_edit_alone():
    """A race past the human fails the recompute's check, so the block is
    as the rewrite left it."""
    block = bytes(amiga_pod.RECORD_BYTES)
    bad = bytearray(block)
    bad[amiga_pod.RACE] = 9
    assert saveplan._recomputed_block(bytes(bad)) == bytes(bad)

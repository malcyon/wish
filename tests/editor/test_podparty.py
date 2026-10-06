"""A Pools of Darkness save opened in the editor, behind
`WISH_EXPERIMENTAL_POD_CONVERT`: `editor.podsheet.PodSheetRecord` and the
`editor.roster.Party` path that builds one per character.

**The specimens are the player's own saves**: every Pools of Darkness DOS
slot in the specimen tree and the DOS archive's `Default files/Saves`, and
every Amiga disk 3 slot in the specimen tree and under the registry's `amiga`
entry, all read at run time. A test that needs them skips without them, which
is what CI does; the synthetic folders are zero bytes and nobody's game data.
"""
from __future__ import annotations

import pathlib

import pytest
from support.editorwindow import make_root

from editor import binding, convert, podsheet
from editor.roster import Party
from goldbox import amiga_pod, amiga_savegame, dos_codec, titles, traits
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
from goldbox.encoding import combat_value

POD = titles.POOLS_OF_DARKNESS
FLAG = convert.POD_CONVERT_ENV
OFF = [None, "0", "off", ""]

#: The sheet's bound fields, as `editor.binding` lists them for every title.
SHOWN = [f.name for f in binding.shown_fields(binding.editable_fields())]


def _flag(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, value)


# ---------------------------------------------------------------------------
# The saves we have, read at run time
# ---------------------------------------------------------------------------

def _dos_folders() -> list[pathlib.Path]:
    import gamedata
    from support.dossave import _game_dirs

    folders = []
    root = gamedata.specimen_root()
    if root is not None:
        folders += sorted({p.parent for p in root.glob("*-dos/*/SAVGAM?.PTY")})
    archive = _game_dirs().get("Pools of Darkness")
    if archive is not None:
        folders.append(archive)
    return [f for f in folders
            if convert.Source.detect(f).title.key == POD.key]


def _dos_sources():
    found = [convert.Source.detect(f, slot=letter) for f in _dos_folders()
             for letter in convert.Source.detect(f).available_slots]
    if not found:
        pytest.skip("needs a Pools of Darkness DOS save; set $WISH_SPECIMENS "
                    "or $FR_ARCHIVES")
    return found


def _amiga_images() -> list[tuple[str, bytes, list[str]]]:
    """Every disk image holding a Pools of Darkness saved game, with its
    slot letters: the specimen tree's and the registry's."""
    import gamedata

    from tools.amiga import amigasaves

    images = []
    root = gamedata.specimen_root()
    if root is not None:
        images += [(str(p), p.read_bytes())
                   for p in sorted(root.glob("*-amiga/*/*.adf"))]
    images += list(amigasaves.images())
    found = []
    for label, data in images:
        try:
            slots = amiga_savegame.pod_slots_present(AmigaDisk(data))
        except (AmigaDiskError, ValueError, amiga_savegame.AmigaSaveError):
            continue
        if slots:
            found.append((label, data, slots))
    return found


def _amiga_sources(tmp_path):
    """A `Source` for every slot of every Amiga disk 3, each disk written to
    `tmp_path` because some are members of a zip."""
    found = []
    for n, (label, data, slots) in enumerate(_amiga_images()):
        path = tmp_path / f"disk3-{n}.adf"
        path.write_bytes(data)
        found += [(f"{label}:{letter}", convert.Source.detect(path, slot=letter))
                  for letter in slots]
    if not found:
        pytest.skip("needs an Amiga Pools of Darkness disk 3; set "
                    "$WISH_SPECIMENS or $AMIGA_DISKS")
    return found


def _loose_amiga_slots() -> list[tuple[str, bytes]]:
    """The specimen tree's loose `SavGam<slot>.pty` files, which no `Source`
    opens because they are not on a disk."""
    import gamedata

    root = gamedata.specimen_root()
    if root is None:
        return []
    found = []
    for p in sorted(root.glob("*-amiga/*/SavGam?.pty")):
        try:
            amiga_savegame.pod_parse(p.read_bytes())
        except (amiga_savegame.AmigaSaveError, ValueError):
            continue
        found.append((str(p), p.read_bytes()))
    return found


# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", OFF)
def test_a_pools_of_darkness_save_stays_closed_without_the_flag(
        monkeypatch, tmp_path, value):
    _flag(monkeypatch, value)
    sources = _dos_sources() + [s for _l, s in _amiga_sources(tmp_path)]
    for source in sources:
        with pytest.raises(dos_codec.WrongTitleError) as blocked:
            Party(source)
        assert blocked.value.title == POD.title, source.path


@pytest.mark.parametrize("value", OFF)
def test_a_synthetic_folder_stays_closed_without_the_flag(
        monkeypatch, tmp_path, value):
    _flag(monkeypatch, value)
    (tmp_path / "CHRDATA1.SAV").write_bytes(bytes(podsheet.SIZE))
    (tmp_path / "SAVGAMA.PTY").write_bytes(b"")
    with pytest.raises(dos_codec.WrongTitleError):
        Party(str(tmp_path))


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("value", OFF)
def test_open_shows_the_cannot_open_box_without_the_flag(
        app, monkeypatch, tmp_path, value):
    import editor.window as ew
    _flag(monkeypatch, value)
    (tmp_path / "CHRDATA1.SAV").write_bytes(bytes(podsheet.SIZE))
    (tmp_path / "SAVGAMA.PTY").write_bytes(b"")
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    ew.EditorBinding(make_root()).load(str(tmp_path))
    assert said == [("Cannot open", convert.POOLS_OF_DARKNESS_UNSUPPORTED)]


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_a_pools_of_darkness_save_opens_with_the_flag(monkeypatch, value):
    _flag(monkeypatch, value)
    source = _dos_sources()[0]
    party = Party(source)
    assert party.game is POD
    assert all(isinstance(m.record, podsheet.PodSheetRecord)
               for m in party.members)


# ---------------------------------------------------------------------------
# Every character, both ports
# ---------------------------------------------------------------------------

#: Sheet name -> the neutral field it must equal, for the names read straight
#: off one field.
_NEUTRAL_SAME = {
    name: name for name in (
        "race", "char_class", "age", "hp_max", "hp_current", "hp_rolled",
        "save_paralysis", "save_petrification", "save_wands", "save_breath",
        "save_spell", "movement", "level", "thief_pick_pockets",
        "thief_open_locks", "thief_find_traps", "thief_move_silently",
        "thief_hide_in_shadows", "thief_hear_noise", "thief_climb_walls",
        "thief_read_languages", "platinum", "gems", "jewelry", "sex",
        "alignment", "armour_class_base", "armour_class", "experience",
        "thac0_base", "class_bits", "size_small", "name",
        *podsheet.ABILITIES, "exceptional_strength",
    )
} | {"thac0": "thac0_current", "roster_movement": "movement_current"}


def _mismatches(record: podsheet.PodSheetRecord, neutral) -> list[str]:
    """Every mapped sheet field that does not read the neutral value."""
    out = []
    for sheet, field in _NEUTRAL_SAME.items():
        want = neutral.get(field)
        if want is not None and record.get(sheet) != want:
            out.append(f"{sheet}: {record.get(sheet)!r} != {want!r}")
    second = neutral.get("abilities_second") or {}
    for name, permanent in second.items():
        if record.ability_pair(name)[1] != permanent:
            out.append(f"{name} permanent: {record.ability_pair(name)} "
                       f"!= {permanent}")
    levels = neutral.get("levels") or {}
    for cls, level in levels.items():
        if record.class_levels().get(cls, 0) != level:
            out.append(f"level {cls}: {record.class_levels().get(cls)} "
                       f"!= {level}")
    for name, slot in podsheet.LEVEL_SLOTS.items():
        cls = next(c for s, c, _n in dos_codec.CLASS_LEVEL_SLOTS if s == slot)
        if record.get(name) != levels.get(cls, 0):
            out.append(f"{name}: {record.get(name)} != {levels.get(cls, 0)}")
    if record.memorised() != list(neutral.get("spells_memorised") or []):
        out.append("spells_memorised")
    if record.known_ids() != list(neutral.get("spells_known") or []):
        out.append("spells_known")
    slots = neutral.get("spells_castable") or {}
    for cls, row in record.spell_slots().items():
        if tuple(slots.get(cls, (0,) * 9)) != row:
            out.append(f"slots {cls}")
    return out


def _round_trip(label: str, record: podsheet.PodSheetRecord) -> None:
    """No edit is byte-identical, and an edit to age moves only age's bytes.

    The store a save makes of every box is modelled by setting each mapped
    sheet field to what it already reads: that must move nothing.
    """
    original = record.to_bytes()
    before = podsheet.PodSheetRecord.from_bytes(original)
    stored = podsheet.PodSheetRecord.from_bytes(original)
    for name in SHOWN:
        if stored.maps(name):
            stored.set(name, stored.get(name))
    assert stored.to_bytes() == original, label
    out, moved = podsheet.rewrite_record(original, before, stored)
    assert out == original and moved == [], label

    after = podsheet.PodSheetRecord.from_bytes(original)
    after.set("age", (after.get("age") + 1) & 0xFFFF)
    out, moved = podsheet.rewrite_record(original, before, after)
    age = podsheet.TABLE["age"]
    changed = {i for i in range(len(out)) if out[i] != original[i]}
    assert moved == ["age"], label
    assert changed and changed <= set(range(age.offset, age.end)), label


def _check_member(label: str, member, expected_name: str, ac: int,
                  hp: tuple[int, int]) -> None:
    record = member.record
    assert isinstance(record, podsheet.PodSheetRecord), label
    assert len(record.to_bytes()) == podsheet.SIZE
    assert member.record_original == record.to_bytes(), label
    assert member.name == expected_name, label
    assert (member.armour_class, member.hp_current, member.hp_max) == (
        ac, *hp), label
    assert member.game is POD
    _round_trip(label, record)


def test_every_dos_character_opens_and_round_trips(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    seen = 0
    for source in _dos_sources():
        party = Party(source)
        assert party.unwritable == podsheet.UNWRITABLE
        folder = pathlib.Path(source.path)
        numbers = dos_codec.party_numbers(folder, source.slot)
        assert [m.index for m in party.members] == numbers, folder
        for member in party.members:
            seen += 1
            char = dos_codec.read_character(
                folder / f"CHRDAT{source.slot}{member.index}.SAV")
            label = f"{folder.name}:{source.slot}{member.index}"
            # The sheet record is the DOS record itself, byte for byte.
            assert member.record.to_bytes() == char.to_bytes(), label
            assert member.native.to_bytes() == char.to_bytes(), label
            _check_member(label, member, char.name,
                          combat_value(char.get("armour_class")),
                          (char.get("hp_current"), char.get("hp_max")))
            assert _mismatches(member.record,
                               dos_codec.to_neutral(char)) == [], label
    assert seen >= 60


def test_every_amiga_character_opens_and_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv(FLAG, "1")
    seen = 0
    for label, source in _amiga_sources(tmp_path):
        party = Party(source)
        assert party.unwritable == podsheet.UNWRITABLE
        blob = amiga_savegame.pod_read_slot(source.amiga_disk(), source.slot)
        blocks = amiga_savegame.pod_parse(blob).blocks
        assert len(party.members) == len(blocks), label
        for member, block in zip(party.members, blocks):
            seen += 1
            pc = amiga_pod.PodCharacter.from_bytes(block)
            who = f"{label}:{member.index}"
            assert member.native == bytes(block), who
            # The armour class worn, at 0x187: `PodCharacter.armour_class`
            # reads the unarmoured base at 0x0B3, 10 in every record.
            ac = combat_value(block[amiga_pod.ARMOUR_CLASS_CURRENT])
            _check_member(who, member, pc.name, ac,
                          (pc.hit_points_current, pc.hit_points_max))
            assert _mismatches(member.record,
                               amiga_pod.pod_to_neutral(block)) == [], who
    assert seen >= 300


def test_every_loose_amiga_slot_renders_and_round_trips():
    found = _loose_amiga_slots()
    if not found:
        pytest.skip("no loose Amiga Pools of Darkness slot in the specimen "
                    "tree; set $WISH_SPECIMENS")
    for label, blob in found:
        for n, block in enumerate(amiga_savegame.pod_parse(blob).blocks):
            member = podsheet.amiga_member(block, n)
            assert member.record.get("combat_figure") == n
            assert _mismatches(member.record, member.neutral) == [], label
            _round_trip(f"{label}:{n}", member.record)


# ---------------------------------------------------------------------------
# Named characters and party sizes
# ---------------------------------------------------------------------------

def _opened(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    return [(s, Party(s)) for s in _dos_sources()]


def _member(parties, name: str):
    for source, party in parties:
        for m in party.members:
            if m.name.strip() == name:
                yield source, m


def test_storm_is_driven_by_the_engine(monkeypatch):
    found = list(_member(_opened(monkeypatch), "STORM"))
    if not found:
        pytest.skip("no save holding STORM")
    for _source, storm in found:
        assert storm.record.is_npc
        assert storm.condition == ("okay", True)


def test_saint_eric_keeps_his_lay_on_hands_node(monkeypatch):
    """Effect 109 is the lay-on-hands timer; the sheet never writes the
    `.EFX` file, so the node stays where the engine left it."""
    found = [m for _s, m in _member(_opened(monkeypatch), "saint eric")
             if 109 in m.native.effect_ids]
    if not found:
        pytest.skip("no save holding saint eric's lay-on-hands node")
    for eric in found:
        assert eric.record.class_levels()["paladin"] > 0
        _round_trip("saint eric", eric.record)


def test_abagail_s_capacity_is_her_own_slot_bytes(monkeypatch):
    """Former cleric 11, magic-user 12: the slots she kept from the cleric
    count, 46 in all, where her current levels alone give 21."""
    found = list(_member(_opened(monkeypatch), "ABAGAIL"))
    if not found:
        pytest.skip("no save holding ABAGAIL")
    for _source, abagail in found:
        assert abagail.record.memorised_capacity() == 46
        assert abagail.record.former_class() == ("cleric", 11)
        assert abagail.class_name.endswith("(was cleric 11)")


def test_paine_s_spellbook_byte_of_eight_is_kept(monkeypatch):
    found = list(_member(_opened(monkeypatch), "PAINE"))
    if not found:
        pytest.skip("no save holding PAINE")
    for _source, paine in found:
        record = paine.record
        original = record.to_bytes()
        assert record.get_raw("spells_known")[117] == 8
        record.set_known_ids(record.known_ids())
        assert record.to_bytes() == original


def test_thief_skills_over_127_read_unsigned(monkeypatch):
    found = [(m, n) for _s, p in _opened(monkeypatch) for m in p.members
             for n in podsheet.SAME_NAME if n.startswith("thief_")
             if m.record.get(n) > 127]
    if not found:
        pytest.skip("no thief skill over 127")
    for member, name in found:
        record = member.record
        assert record.get(name) == record.to_bytes()[
            podsheet.TABLE[name].offset]
        record.set(name, 255)
        assert record.get(name) == 255


def test_a_level_edit_keeps_the_druid_paladin_and_ranger_levels(monkeypatch):
    seen = 0
    for _source, party in _opened(monkeypatch):
        for member in party.members:
            original = member.record.to_bytes()
            before = podsheet.PodSheetRecord.from_bytes(original)
            after = podsheet.PodSheetRecord.from_bytes(original)
            after.set("level_cleric", (after.get("level_cleric") + 1) % 41)
            out, moved = podsheet.rewrite_record(original, before, after)
            at = podsheet.TABLE["class_levels"].offset
            assert moved == ["class_levels"]
            assert [i for i in range(len(out)) if out[i] != original[i]] == [at]
            seen += 1
    assert seen


def _assembled(tmp_path, count: int) -> pathlib.Path:
    """A DOS folder holding `count` of the saves' characters, copied at run
    time with their sibling files, and an empty `SAVGAMA.PTY`, which leaves
    the party bounded by the files present."""
    out = tmp_path / f"party{count}"
    out.mkdir()
    taken = 0
    for source in _dos_sources():
        folder = pathlib.Path(source.path)
        for n in dos_codec.party_numbers(folder, source.slot):
            if taken == count:
                break
            taken += 1
            for suffix in (".SAV", ".THG", ".EFX"):
                got = folder / f"CHRDAT{source.slot}{n}{suffix}"
                if got.exists():
                    (out / f"CHRDATA{taken}{suffix}").write_bytes(
                        got.read_bytes())
    if taken < count:
        pytest.skip(f"fewer than {count} Pools of Darkness characters")
    (out / "SAVGAMA.PTY").write_bytes(b"")
    return out


@pytest.mark.parametrize("count", [1, 8])
def test_a_party_of_one_and_of_eight_opens(monkeypatch, tmp_path, count):
    monkeypatch.setenv(FLAG, "1")
    party = Party(str(_assembled(tmp_path, count)))
    assert party.game is POD
    assert [m.index for m in party.members] == list(range(1, count + 1))
    for member in party.members:
        _round_trip(member.name, member.record)


# ---------------------------------------------------------------------------
# The record, without game data
# ---------------------------------------------------------------------------

def _blank() -> podsheet.PodSheetRecord:
    return podsheet.PodSheetRecord(bytes(podsheet.SIZE))


def test_every_bound_field_maps_or_is_greyed():
    """No bound field is quietly unmapped: each reads a byte of this title
    or is in `UNWRITABLE`, and nothing in `UNWRITABLE` reads one."""
    assert podsheet.UNWRITABLE <= set(SHOWN)
    for name in SHOWN:
        assert podsheet.PodSheetRecord.maps(name) != (
            name in podsheet.UNWRITABLE), name


def test_a_greyed_field_reads_as_not_stored():
    from goldbox.record import FieldNotStored

    record = _blank()
    for name in podsheet.UNWRITABLE:
        assert not record.is_stored(name)
        with pytest.raises(FieldNotStored):
            record.get(name)


def test_the_boxes_get_this_title_s_widths():
    assert binding.value_range(
        podsheet.PodSheetRecord.sheet_field("thief_pick_pockets")) == (0, 255)
    assert binding.value_range(
        podsheet.PodSheetRecord.sheet_field("hp_max")) == (0, 255)
    assert binding.value_range(
        podsheet.PodSheetRecord.sheet_field("hp_current")) == (0, 255)
    assert binding.value_range(
        podsheet.PodSheetRecord.sheet_field("experience")) == (0, 2**32 - 1)


def test_hit_points_past_one_byte_are_an_error():
    record = _blank()
    with pytest.raises(ValueError):
        record.set("hp_max", 256)
    record.set("experience", 2**32 - 1)
    assert record.get("experience") == 2**32 - 1


def test_an_ability_edit_moves_the_in_force_byte_only():
    record = _blank()
    at = podsheet.TABLE["strength"].offset
    record.set("strength", 17)
    assert record.to_bytes()[at:at + 2] == bytes([0, 17])
    record.set("exceptional_strength", 50)
    at = podsheet.TABLE["exceptional_strength"].offset
    assert record.to_bytes()[at:at + 2] == bytes([50, 0])


def test_memorised_spells_are_the_dos_run_reversed():
    record = _blank()
    record.set_memorised([70, 67, 58])
    run = podsheet.TABLE["spells_memorised"]
    assert record.to_bytes()[run.end - 3:run.end] == bytes([58, 67, 70])
    assert record.memorised() == [70, 67, 58]


def test_a_name_is_fifteen_characters_with_its_count():
    record = _blank()
    record.set("name", "SAINT ERIC")
    assert record.to_bytes()[:11] == b"\x0aSAINT ERIC"
    with pytest.raises(ValueError):
        record.set("name", "X" * 16)


def test_a_name_length_past_fifteen_is_an_error_when_set_raw():
    record = _blank()
    with pytest.raises(ValueError):
        record.set_raw("name", bytes([16]) + bytes(15))
    assert record.name == ""
    record.set_raw("name", b"\x03ABC" + bytes(12))
    assert record.name == "ABC"


def _synthetic_folder(tmp_path) -> pathlib.Path:
    """A one-character Pools of Darkness DOS folder made of zeros and a name:
    the empty `SAVGAMA.PTY` names the title and the record size picks the
    layout."""
    record = bytearray(podsheet.SIZE)
    record[:4] = b"\x03ABC"
    (tmp_path / "CHRDATA1.SAV").write_bytes(bytes(record))
    (tmp_path / "SAVGAMA.PTY").write_bytes(b"")
    return tmp_path


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_a_synthetic_folder_opens_with_the_flag(monkeypatch, tmp_path, value):
    _flag(monkeypatch, value)
    party = Party(str(_synthetic_folder(tmp_path)))
    assert party.game is POD
    assert party.unwritable == podsheet.UNWRITABLE
    [member] = party.members
    assert isinstance(member.record, podsheet.PodSheetRecord)
    assert member.name == "ABC"
    assert member.record.to_bytes() == (
        tmp_path / "CHRDATA1.SAV").read_bytes()


def test_a_synthetic_folder_rewrites_and_edits_age_only(monkeypatch, tmp_path):
    monkeypatch.setenv(FLAG, "1")
    [member] = Party(str(_synthetic_folder(tmp_path))).members
    _round_trip("synthetic", member.record)
    original = member.record.to_bytes()
    before = podsheet.PodSheetRecord.from_bytes(original)
    after = podsheet.PodSheetRecord.from_bytes(original)
    after.set("age", 40)
    out, moved = podsheet.rewrite_record(original, before, after)
    assert moved == ["age"]
    assert {i for i in range(len(out)) if out[i] != original[i]} <= {
        0x0B0, 0x0B1}
    assert out[0x0B0:0x0B2] == (40).to_bytes(2, "little")


def test_a_synthetic_folder_runs_without_the_specimen_variables(
        monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    for var in ("WISH_SPECIMENS", "FR_ARCHIVES", "AMIGA_DISKS", "POR_DISKS"):
        monkeypatch.setenv(var, str(empty))
    monkeypatch.setenv(FLAG, "1")
    folder = tmp_path / "save"
    folder.mkdir()
    assert Party(str(_synthetic_folder(folder))).game is POD


def test_pools_of_darkness_gets_no_effect_names_of_another_title():
    table = traits.for_game(POD)
    assert table == {}
    assert table is not traits.DEFAULT_NAMES
    assert traits.describe(109, POD) == "trait 109"
    assert traits.for_game(POD.key) is traits.NAMES_POOLS_OF_DARKNESS

"""`tools/specimens.py`, the tree of DOS and C64 records this project watched
being written (#249, #246).

Every test here points `root=` at `tmp_path` rather than the real
`$WISH_SPECIMENS` -- the actual tree lives on Donald's machine, outside the
repository, and nothing here should touch it or depend on it existing.
`test_tree_root_defaults_to_home_wish_specimens` is the one exception, and it
only checks the *default path string*, never reading or writing through it.

`tmp_path`'s own cleanup has to see through the read-only permissions this
tool deliberately leaves behind, hence `_unlock` in the fixture teardown --
that permission being hard to undo by accident is the feature under test.
"""

from __future__ import annotations

import pathlib
import stat
import sys

import pytest

from goldbox.d64 import D64
from tools import specimens


def _unlock(root: pathlib.Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(stat.S_IRWXU)
    if root.is_dir():
        root.chmod(stat.S_IRWXU)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "specimens"
    yield root
    if root.is_dir():
        _unlock(root)


@pytest.fixture
def one_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    spc = src / "GNOMF1.SPC"
    spc.write_bytes(bytes((97, 0, 0, 0xFF, 0, 0, 0, 0, 0)))
    cha = src / "GNOMF1.CHA"
    cha.write_bytes(b"a character record, standing in for one")
    return [spc, cha]


def _add(root, sources, **kw):
    kw.setdefault("title", "Pool of Radiance")
    kw.setdefault("issue", "#84 (Roll a gnome in DOS and read the two "
                            "innate effect ids nobody has seen)")
    kw.setdefault("made_by", "tools/dosgnome.py")
    kw.setdefault("what", "rolled a gnome in the game's own creation screens")
    return specimens.add("dos", "gnomf1", sources, root=root, **kw)


# --- add ---------------------------------------------------------------


def test_add_creates_a_directory_named_for_the_specimen(tree, one_source):
    dest = _add(tree, one_source)
    assert dest == tree / "por-dos" / "WISH-SPEC-gnomf1"
    assert (dest / "GNOMF1.SPC").is_file()
    assert (dest / "GNOMF1.CHA").is_file()
    assert (dest / "provenance.toml").is_file()


def test_add_writes_the_required_fields(tree, one_source):
    dest = _add(tree, one_source, command="tools/dosgnome.py c ...")
    fields = specimens.read_provenance(dest / "provenance.toml")
    for field in specimens.REQUIRED_FIELDS:
        assert field in fields, field
    assert fields["command"] == "tools/dosgnome.py c ..."
    assert fields["edited_afterwards"] is False


def test_add_records_the_hash_of_every_file(tree, one_source):
    dest = _add(tree, one_source)
    fields = specimens.read_provenance(dest / "provenance.toml")
    assert fields["sha256"]["GNOMF1.SPC"] == specimens.sha256_file(dest / "GNOMF1.SPC")
    assert fields["sha256"]["GNOMF1.CHA"] == specimens.sha256_file(dest / "GNOMF1.CHA")


def test_add_leaves_every_specimen_file_read_only(tree, one_source):
    dest = _add(tree, one_source)
    for path in (dest / "GNOMF1.SPC", dest / "GNOMF1.CHA", dest / "provenance.toml"):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert not mode & stat.S_IWUSR, path


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="a directory's write bit is not what Windows enforces, so chmod "
           "cannot stop a file being created here; `check` is the guard that "
           "works on both platforms and it is tested separately",
)
def test_add_leaves_the_specimen_directory_unwritable(tree, one_source):
    """The directory itself loses its write bit too, so a new file cannot be
    dropped in beside the ones that were watched being written."""
    dest = _add(tree, one_source)
    with pytest.raises(PermissionError):
        (dest / "SNEAKED-IN.SAV").write_bytes(b"not part of the specimen")


def test_add_refuses_to_overwrite_an_existing_specimen(tree, one_source):
    _add(tree, one_source)
    with pytest.raises(FileExistsError):
        _add(tree, one_source)


def test_add_never_touches_the_source_files(tree, one_source):
    """This tool copies; it must never move or delete a source."""
    before = [(p, p.read_bytes()) for p in one_source]
    _add(tree, one_source)
    for path, data in before:
        assert path.is_file()
        assert path.read_bytes() == data


def test_add_refuses_a_name_that_is_not_a_plain_slug(tree, one_source):
    with pytest.raises(ValueError):
        specimens.add("dos", "Gnomf 1!", one_source, root=tree,
                      title="x", issue="x", made_by="x", what="x")


def test_add_accepts_amiga_and_builds_the_dos_shape(tree, one_source):
    """`#313 (The specimen tree has no Amiga platform, so an engine-written
    Amiga save disk cannot be kept)`, `#332 (The specimen tree cannot hold an
    Amiga saved game, so the first two engine-written Amiga parties sit
    outside its checks)`, `#343 (The specimen tool cannot add an Amiga
    specimen, so three have been hand-written)`: `add` used to raise
    `SystemExit: 2` from argparse's `choices=` before `amiga` was in
    `PLATFORMS`. The directory is `coab-amiga`, not `por-amiga` -- the slug
    comes from the title, matching what the two hand-written specimens on
    disk already use."""
    dest = specimens.add("amiga", "coab-test", one_source, root=tree,
                         title="Curse of the Azure Bonds",
                         issue="#28 (test)", made_by="x", what="x")
    assert dest == tree / "coab-amiga" / "WISH-SPEC-coab-test"
    assert (dest / "provenance.toml").is_file()
    fields = specimens.read_provenance(dest / "provenance.toml")
    assert fields["platform"] == "amiga"
    assert specimens.check_specimens(tree) == []


def test_add_refuses_a_title_with_no_known_slug(tree, one_source):
    with pytest.raises(ValueError):
        specimens.add("amiga", "x", one_source, root=tree,
                      title="Some Title Nobody Has Added Yet",
                      issue="x", made_by="x", what="x")


def test_a_c64_specimen_is_one_file_beside_its_own_provenance(tree, tmp_path):
    d64 = tmp_path / "party.d64"
    d64.write_bytes(b"not a real disk image, just bytes")
    dest = specimens.add("c64", "p18party", [d64], root=tree,
                         title="Pool of Radiance", issue="#10 (test)",
                         made_by="the training hall", what="levelled up")
    assert dest == tree / "por-c64" / "WISH-SPEC-p18party.d64"
    assert (tree / "por-c64" / "WISH-SPEC-p18party.provenance.toml").is_file()


def _unclosed_curse_disk(tmp_path, name="SIDE0.D64"):
    """A disk with `SAVEAZURE` marked exactly the way a 1541 leaves it when
    the emulator's slot is copied out before the write-back lands -- same
    construction as `test_curseload.py`'s
    `test_a_save_disk_the_drive_never_closed_is_repaired_in_place`."""
    disk = D64.blank(b"CURSE SAVE")
    payload = bytes(range(256)) * 29
    disk.write_file(b"SAVEAZURE", payload)
    entry = disk.entry(b"SAVEAZURE")
    raw = bytearray(disk.to_bytes())
    raw[entry.offset] &= 0x7F                 # what the drive leaves behind
    raw[entry.offset + 28] = raw[entry.offset + 29] = 0
    path = tmp_path / name
    path.write_bytes(bytes(raw))
    return path


def test_add_refuses_a_c64_disk_with_an_unclosed_directory_entry(tree, tmp_path):
    """#298: the specimen tree must not accept a disk the game itself
    refuses to load with `60, WRITE FILE OPEN`."""
    d64 = _unclosed_curse_disk(tmp_path)
    with pytest.raises(ValueError, match=r"never closed.*SAVEAZURE.*\$02"):
        specimens.add("c64", "curse-broken", [d64], root=tree,
                      title="Curse of the Azure Bonds", issue="#298 (test)",
                      made_by="a driven ENCAMP > SAVE", what="saved from the training hall")
    assert not (tree / "coab-c64").exists()


def test_add_accepts_a_c64_disk_the_drive_closed(tree, tmp_path):
    """The check must not refuse a well-formed disk -- proof it is not
    refusing everything."""
    disk = D64.blank(b"CURSE SAVE")
    payload = bytes(range(256)) * 29
    disk.write_file(b"SAVEAZURE", payload)
    d64 = tmp_path / "SIDE0.D64"
    disk.save(d64)
    dest = specimens.add("c64", "curse-good", [d64], root=tree,
                         title="Curse of the Azure Bonds", issue="#298 (test)",
                         made_by="a driven ENCAMP > SAVE", what="saved from the training hall")
    assert dest == tree / "coab-c64" / "WISH-SPEC-curse-good.D64"


# --- check: this is the part that has to actually work ------------------


def test_check_reports_nothing_wrong_with_an_untouched_tree(tree, one_source):
    _add(tree, one_source)
    assert specimens.check_specimens(tree) == []


def test_check_catches_a_specimen_file_edited_after_the_fact(tree, one_source):
    """The whole reason this tree exists: SILAS was edited after the game
    wrote it and nothing said so. Prove the detection actually fires."""
    dest = _add(tree, one_source)
    target = dest / "GNOMF1.SPC"
    target.chmod(stat.S_IRWXU)
    target.write_bytes(b"edited with an outside tool" + b"\x00" * 3)
    problems = specimens.check_specimens(tree)
    assert any("GNOMF1.SPC" in p and "changed" in p for p in problems)


def test_check_catches_a_missing_file(tree, one_source):
    dest = _add(tree, one_source)
    dest.chmod(stat.S_IRWXU)
    # Windows refuses to unlink a read-only file, where a POSIX system only
    # asks that the *directory* be writable.  Clear the file's own bit too, so
    # this reads the same on both.
    victim = dest / "GNOMF1.CHA"
    victim.chmod(stat.S_IRUSR | stat.S_IWUSR)
    victim.unlink()
    problems = specimens.check_specimens(tree)
    assert any("GNOMF1.CHA" in p and "missing" in p for p in problems)


def test_check_flags_a_file_with_no_provenance_record_at_all(tree, one_source):
    """'A file with no provenance record is not a specimen' -- enforced."""
    _add(tree, one_source)
    stray_dir = tree / "por-dos" / "WISH-SPEC-stray"
    stray_dir.mkdir()
    (stray_dir / "FOUND.SAV").write_bytes(b"found on a disk, provenance unknown")
    problems = specimens.check_specimens(tree)
    assert any("stray" in p and "no provenance.toml" in p for p in problems)


def test_check_flags_an_untracked_file_dropped_beside_a_real_specimen(tree, one_source):
    dest = _add(tree, one_source)
    dest.chmod(stat.S_IRWXU)
    (dest / "EXTRA.SAV").write_bytes(b"not recorded anywhere")
    problems = specimens.check_specimens(tree)
    assert any("EXTRA.SAV" in p and "not recorded" in p for p in problems)


def test_check_on_an_empty_tree_finds_nothing_wrong(tree):
    tree.mkdir()
    assert specimens.check_specimens(tree) == []


# --- a platform directory holding both shapes at once (#450) -------------


def _both_shapes(tree, tmp_path):
    """`por-c64` as it actually stands: flat `.d64` specimens beside one
    directory of memory captures, which is what `#286` left there."""
    d64 = tmp_path / "party.d64"
    d64.write_bytes(b"not a real disk image, just bytes")
    specimens.add("c64", "p18party", [d64], root=tree,
                  title="Pool of Radiance", issue="#10 (test)",
                  made_by="the training hall", what="levelled up")
    # `add` only ever makes the flat shape for c64, so this one is built the
    # way the real `WISH-SPEC-por-c64u-onward-bound-hang` was: by hand.
    dumps = tree / "por-c64" / "WISH-SPEC-hang-captures"
    dumps.mkdir()
    zp = dumps / "hung-zp.bin"
    zp.write_bytes(b"the zero page as it froze")
    specimens.write_provenance(
        dumps / specimens.PROVENANCE_NAME,
        {"name": "hang-captures", "platform": "c64",
         "title": "Pool of Radiance", "issue": "#286 (test)",
         "made_by": "Donald, on his own C64 Ultimate",
         "what": "captures of a hung machine", "created": "2026-09-04",
         "added": "2026-09-05", "edited_afterwards": False},
        {"hung-zp.bin": specimens.sha256_file(zp)})
    return dumps


def test_a_directory_specimen_beside_the_flat_ones_is_listed(tree, tmp_path):
    """Both shapes at once. Until `#450` a non-empty flat list meant "stop
    here", and the directory specimen was listed by nothing."""
    _both_shapes(tree, tmp_path)
    names = sorted(e["name"] for e in specimens.list_specimens(tree))
    assert names == ["hang-captures", "p18party"]


def test_check_catches_an_edit_to_a_directory_specimen_beside_flat_ones(
        tree, tmp_path):
    """The silent half: `check` reported the tree clean while a file in that
    specimen could be rewritten by anything."""
    dest = _both_shapes(tree, tmp_path)
    victim = dest / "hung-zp.bin"
    dest.chmod(stat.S_IRWXU)
    victim.chmod(stat.S_IRWXU)
    victim.write_bytes(b"somebody opened this and saved it")
    problems = specimens.check_specimens(tree)
    assert len(problems) == 1
    assert "hang-captures: hung-zp.bin has changed" in problems[0]


def test_check_flags_a_stray_file_in_a_directory_specimen_beside_flat_ones(
        tree, tmp_path):
    dest = _both_shapes(tree, tmp_path)
    dest.chmod(stat.S_IRWXU)
    (dest / "stray.bin").write_bytes(b"dropped here later")
    problems = specimens.check_specimens(tree)
    assert len(problems) == 1
    assert "stray.bin: not recorded by any provenance.toml" in problems[0]


# --- list ----------------------------------------------------------------


def test_list_reports_every_specimen_with_its_provenance(tree, one_source):
    _add(tree, one_source)
    entries = specimens.list_specimens(tree)
    assert len(entries) == 1
    assert entries[0]["name"] == "gnomf1"
    assert entries[0]["platform"] == "dos"


def test_list_on_a_tree_with_no_specimens_is_empty(tree):
    tree.mkdir()
    assert specimens.list_specimens(tree) == []


# --- the tree location ----------------------------------------------------


def test_tree_root_honours_the_environment_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("WISH_SPECIMENS", str(tmp_path / "elsewhere"))
    assert specimens.tree_root() == tmp_path / "elsewhere"


def test_tree_root_defaults_to_home_wish_specimens(monkeypatch):
    monkeypatch.delenv("WISH_SPECIMENS", raising=False)
    assert specimens.tree_root() == pathlib.Path.home() / "wish-specimens"


def test_ensure_tree_writes_a_do_not_edit_file_addressed_to_a_reader(tree):
    specimens.ensure_tree(tree)
    text = (tree / "DO-NOT-EDIT.md").read_text()
    assert "do not edit" in text.lower()
    assert len(text.splitlines()) > 1


# --- how a test reaches the tree ------------------------------------------
# `tests/gamedata.py`'s helpers, which are what the DOS test modules call.
# Each one points `$WISH_SPECIMENS` at `tmp_path`, so none of this reads the
# real tree, and `_specimen_path` is cached per name so its cache is cleared
# between cases.


@pytest.fixture
def fake_tree(tree, one_source, monkeypatch):
    """A one-specimen tree at `tmp_path`, with `$WISH_SPECIMENS` aimed at it."""
    import gamedata

    _add(tree, one_source)
    monkeypatch.setenv("WISH_SPECIMENS", str(tree))
    gamedata._specimen_path.cache_clear()
    yield tree
    gamedata._specimen_path.cache_clear()


def test_have_specimen_says_which_names_are_there(fake_tree):
    import gamedata

    assert gamedata.have_specimen("gnomf1")
    assert not gamedata.have_specimen("nobody-rolled-this")


def test_a_specimen_that_is_not_there_skips_rather_than_failing(fake_tree):
    """CI has no specimen tree, so an absent one must not turn the suite red."""
    import gamedata

    with pytest.raises(pytest.skip.Exception):
        gamedata.specimen("nobody-rolled-this")


def test_the_whole_tree_being_absent_skips_too(tmp_path, monkeypatch):
    import gamedata

    monkeypatch.setenv("WISH_SPECIMENS", str(tmp_path / "no-such-tree"))
    gamedata._specimen_path.cache_clear()
    try:
        assert gamedata.specimen_root() is None
        with pytest.raises(pytest.skip.Exception):
            gamedata.specimen("gnomf1")
    finally:
        gamedata._specimen_path.cache_clear()


def test_a_changed_specimen_fails_rather_than_being_read(fake_tree):
    """The point of the manifest, from a test's side.

    A specimen somebody edited is no longer evidence, and reading it anyway is
    exactly what `#246` is about -- so this fails loudly where an absent one
    skips quietly. Prove it: the same call succeeds before the edit.
    """
    import gamedata

    assert gamedata.specimen("gnomf1").is_dir()

    target = fake_tree / "por-dos" / "WISH-SPEC-gnomf1" / "GNOMF1.SPC"
    target.chmod(stat.S_IRWXU)
    target.write_bytes(b"edited with an outside tool" + b"\x00" * 3)

    with pytest.raises(pytest.fail.Exception) as caught:
        gamedata.specimen("gnomf1")
    assert "GNOMF1.SPC" in str(caught.value)
    assert "changed" in str(caught.value)


def test_specimen_files_keys_by_specimen_so_two_trees_do_not_collide(fake_tree):
    import gamedata

    found = gamedata.specimen_files(["gnomf1"], (".SPC", ".CHA"))
    assert sorted(found) == ["gnomf1/GNOMF1.CHA", "gnomf1/GNOMF1.SPC"]


def test_specimen_files_can_select_by_record_size(fake_tree):
    """How a Pool of Radiance record is told from every other title's."""
    import gamedata

    nine = gamedata.specimen_files(["gnomf1"], (".SPC", ".CHA"), size=9)
    assert sorted(nine) == ["gnomf1/GNOMF1.SPC"]


# --- the tree's own unloadable specimens, #298 --------------------------


def _plant_c64(tree, name, source, title="Curse of the Azure Bonds"):
    """Put a C64 specimen in the tree by hand, hashes and all.

    `add` refuses an unclosed disk, which is the point of it -- so a test
    about specimens already in the tree cannot use `add` to make one. This is
    what the five real ones look like: they were added before the check
    existed.
    """
    pdir = tree / (specimens.TITLE_SLUGS[title] + "-c64")
    pdir.mkdir(parents=True, exist_ok=True)
    dest = pdir / f"WISH-SPEC-{name}.D64"
    dest.write_bytes(pathlib.Path(source).read_bytes())
    prov = pdir / f"WISH-SPEC-{name}.provenance.toml"
    specimens.write_provenance(prov, {
        "name": name, "platform": "c64", "title": title,
        "issue": "#298 (test)", "made_by": "a driven SAVE CURRENT GAME",
        "what": "stands in for a specimen added before the check existed",
        "created": "2026-09-05", "added": "2026-09-05",
        "edited_afterwards": False,
    }, {dest.name: specimens.sha256_file(dest)})
    return dest


def test_the_tree_reports_a_specimen_the_drive_left_open(tree, tmp_path):
    """#298: five specimens in the real tree carry an entry the drive never
    closed, and nothing said so until somebody tried to boot one. `add`'s
    check guards the door; this is the census of what is already inside."""
    _plant_c64(tree, "curse-left-open", _unclosed_curse_disk(tmp_path))
    rows = specimens.unloadable_specimens(tree)
    assert [r["name"] for r in rows] == ["curse-left-open"]
    assert rows[0]["entries"] == [{"file": "SAVEAZURE", "type": 0x02,
                                   "blocks": 0}]


def test_a_specimen_the_drive_closed_is_not_reported(tree, tmp_path):
    """The control, and the reason this cannot be a check that always fires:
    a sound disk in the same tree is not named."""
    disk = D64.blank(b"CURSE SAVE")
    disk.write_file(b"SAVEAZURE", bytes(range(256)) * 29)
    good = tmp_path / "GOOD.D64"
    disk.save(good)
    _plant_c64(tree, "curse-closed", good)
    _plant_c64(tree, "curse-left-open", _unclosed_curse_disk(tmp_path))
    assert [r["name"] for r in specimens.unloadable_specimens(tree)] == \
        ["curse-left-open"]


def test_an_unloadable_specimen_is_reported_without_failing_the_check(
        tree, tmp_path, monkeypatch, capsys):
    """It is a decision, not a defect.

    The disk still hashes to what its provenance recorded and the payload is
    intact, so `check` says so and exits 0. Turning the tree red would push a
    decision that is Donald's -- repair, replace, re-drive or leave -- into
    looking like something to be tidied away.
    """
    _plant_c64(tree, "curse-left-open", _unclosed_curse_disk(tmp_path))
    monkeypatch.setenv("WISH_SPECIMENS", str(tree))
    assert specimens.check_specimens(tree) == []
    assert specimens.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "all match their manifest" in out
    assert "curse-left-open" in out
    assert "SAVEAZURE type $02" in out
    assert "#298 (A save disk copied out" in out


# --- repair: the one thing here that writes to a specimen already in the tree


def test_repair_closes_the_entry_and_changes_exactly_two_bytes(tree, tmp_path):
    """#298, and Donald's decision of 2026-09-08 to repair the five in place.

    The whole claim the repair rests on is that it moves the directory entry
    and nothing else, so the assertion is a byte diff over the whole image
    rather than a re-read of the entry it just wrote.
    """
    dest = _plant_c64(tree, "curse-left-open", _unclosed_curse_disk(tmp_path))
    before = dest.read_bytes()
    report = specimens.repair_unloadable(
        "curse-left-open", note="closed by hand, see #298", root=tree)
    after = dest.read_bytes()

    assert len(after) == len(before)
    moved = [i for i in range(len(before)) if before[i] != after[i]]
    assert len(moved) == 2, moved
    entry = D64.from_bytes(before).entry(b"SAVEAZURE")
    assert moved == [entry.offset, entry.offset + 28]
    assert (before[entry.offset], after[entry.offset]) == (0x02, 0x82)
    assert (before[entry.offset + 28], after[entry.offset + 28]) == (0, 30)
    assert [(r["offset"], r["field"]) for r in report["diff"]] == [
        (entry.offset, "type byte"), (entry.offset + 28, "block count low")]

    # And the payload the game wrote is the same payload.
    assert D64.from_bytes(after).read_file(b"SAVEAZURE") == \
        D64.from_bytes(before).read_file(b"SAVEAZURE")
    assert specimens.unloadable_specimens(tree) == []
    assert specimens.check_specimens(tree) == []


def test_repair_records_the_edit_in_the_provenance(tree, tmp_path):
    """An honest `edited_afterwards`, the new hash, and a note saying where
    the unrepaired bytes still are -- the cost Donald accepted, written down
    where `tools/carryceiling.py` reads it."""
    dest = _plant_c64(tree, "curse-left-open", _unclosed_curse_disk(tmp_path))
    note = "Repaired 2026-09-08; unrepaired bytes in wish-specimens-...tar.gz"
    specimens.repair_unloadable("curse-left-open", note=note, root=tree)

    prov = dest.parent / "WISH-SPEC-curse-left-open.provenance.toml"
    fields = specimens.read_provenance(prov)
    assert fields["edited_afterwards"] is True
    assert fields["issue_note"] == note
    assert fields["sha256"][dest.name] == specimens.sha256_file(dest)
    assert fields["what"]                      # the original fields survive
    # Both files go back to read-only, or the next editor gets in for free.
    assert not dest.stat().st_mode & stat.S_IWUSR
    assert not prov.stat().st_mode & stat.S_IWUSR


def test_repair_refuses_a_specimen_that_no_longer_matches_its_manifest(
        tree, tmp_path):
    """Repairing over drift would hide the drift, which is the one thing this
    tree exists to catch."""
    dest = _plant_c64(tree, "curse-left-open", _unclosed_curse_disk(tmp_path))
    dest.chmod(stat.S_IRUSR | stat.S_IWUSR)
    raw = bytearray(dest.read_bytes())
    raw[0x20000] ^= 0xFF                       # somebody was in here
    dest.write_bytes(bytes(raw))
    with pytest.raises(ValueError, match="no longer matches its manifest"):
        specimens.repair_unloadable("curse-left-open", note="x", root=tree)
    assert dest.read_bytes() == bytes(raw)     # and it wrote nothing


def test_repair_refuses_a_specimen_whose_entries_are_all_closed(tree, tmp_path):
    """The control: a sound disk is not quietly rewritten and re-hashed."""
    disk = D64.blank(b"CURSE SAVE")
    disk.write_file(b"SAVEAZURE", bytes(range(256)) * 29)
    good = tmp_path / "GOOD.D64"
    disk.save(good)
    dest = _plant_c64(tree, "curse-closed", good)
    before = dest.read_bytes()
    with pytest.raises(ValueError, match="already closed"):
        specimens.repair_unloadable("curse-closed", note="x", root=tree)
    assert dest.read_bytes() == before


def test_repair_dry_run_writes_nothing(tree, tmp_path):
    """`--dry-run` proves the repair on a copy, which is how the five real
    ones were measured before the tree was opened for writing."""
    dest = _plant_c64(tree, "curse-left-open", _unclosed_curse_disk(tmp_path))
    before = dest.read_bytes()
    report = specimens.repair_unloadable(
        "curse-left-open", note="x", root=tree, dry_run=True)
    assert len(report["diff"]) == 2
    assert dest.read_bytes() == before
    assert [r["name"] for r in specimens.unloadable_specimens(tree)] == \
        ["curse-left-open"]


def test_repair_refuses_a_change_outside_the_directory_entry(
        tree, tmp_path, monkeypatch):
    """The guard that has no natural way to fire, so it is driven by hand.

    `close_splat()` only ever touches a directory entry, which is why the
    five real repairs came out at two bytes each. The check is here for the
    day somebody changes that: a repair that moves a byte of the payload is
    refused rather than written and re-hashed under a new SHA-256.
    """
    from tools import curseload

    dest = _plant_c64(tree, "curse-left-open", _unclosed_curse_disk(tmp_path))
    before = dest.read_bytes()
    real = curseload.close_splat

    def scribble(path):
        changed = real(path)
        raw = bytearray(pathlib.Path(path).read_bytes())
        raw[0x20000] ^= 0xFF                   # a byte of somebody's payload
        pathlib.Path(path).write_bytes(bytes(raw))
        return changed

    monkeypatch.setattr(curseload, "close_splat", scribble)
    with pytest.raises(ValueError, match="outside every directory entry"):
        specimens.repair_unloadable("curse-left-open", note="x", root=tree)
    assert dest.read_bytes() == before

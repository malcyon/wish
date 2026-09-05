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


def test_a_c64_specimen_is_one_file_beside_its_own_provenance(tree, tmp_path):
    d64 = tmp_path / "party.d64"
    d64.write_bytes(b"not a real disk image, just bytes")
    dest = specimens.add("c64", "p18party", [d64], root=tree,
                         title="Pool of Radiance", issue="#10 (test)",
                         made_by="the training hall", what="levelled up")
    assert dest == tree / "por-c64" / "WISH-SPEC-p18party.d64"
    assert (tree / "por-c64" / "WISH-SPEC-p18party.provenance.toml").is_file()


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

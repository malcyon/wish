"""`tools/specimenbackup.py`, which counts the copies of the specimen tree and
makes one more (#249 step 5, "somewhere durable to keep it").

Every test builds its own tree in `tmp_path` through `tools.specimens.add`, the
way `tests/test_specimens.py` does, and never reads the real `$WISH_SPECIMENS`
-- the tree lives on Donald's machine, outside the repository, and nothing here
should depend on it existing.  The bytes standing in for game records are
invented here; a slice of a real save would be the game's data under a new
name.

The tree `add` leaves behind is read-only on purpose, so the fixture unlocks it
before `tmp_path` cleans up.
"""

from __future__ import annotations

import argparse
import pathlib
import stat
import tarfile

import pytest

from tools import specimenbackup, specimens


def _unlock(root: pathlib.Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(stat.S_IRWXU)
    if root.is_dir():
        root.chmod(stat.S_IRWXU)


@pytest.fixture
def tree(tmp_path):
    """A tree holding two DOS specimens of two files each."""
    root = specimens.ensure_tree(tmp_path / "specimens")
    src = tmp_path / "src"
    src.mkdir()
    for n, (cha, spc) in enumerate(
            [(b"a character record, standing in for one", b"\x61\x00\x00"),
             (b"a second record, different bytes", b"\x5a\x00\x01")]):
        (src / f"WISH{n}.CHA").write_bytes(cha)
        (src / f"WISH{n}.SPC").write_bytes(spc)
        specimens.add("dos", f"party{n}",
                      [src / f"WISH{n}.CHA", src / f"WISH{n}.SPC"],
                      root=root, title="Pool of Radiance",
                      issue="#249 (Build a DOS party from creation and level "
                            "it ourselves, so DOS measurements rest on "
                            "records we watched being written)",
                      made_by="tools/dosparty.py",
                      what="rolled in the game's own creation screens")
    yield root
    if root.is_dir():
        _unlock(root)


# --- what the tree records --------------------------------------------------


def test_recorded_hashes_covers_every_file_of_every_specimen(tree):
    wanted = specimenbackup.recorded_hashes(tree)
    named = [pair for entries in wanted.values() for pair in entries]
    assert sorted(named) == [("party0", "WISH0.CHA"), ("party0", "WISH0.SPC"),
                             ("party1", "WISH1.CHA"), ("party1", "WISH1.SPC")]


def test_two_specimens_sharing_a_file_are_one_thing_to_find(tmp_path, tree):
    """A ladder rung whose `.SPC` never changed is byte-identical to the
    previous rung's, and finding one copy of those bytes covers both."""
    src = tmp_path / "shared"
    src.mkdir()
    (src / "WISH0.CHA").write_bytes(b"a character record, standing in for one")
    specimens.add("dos", "party2", [src / "WISH0.CHA"], root=tree,
                  title="Pool of Radiance", issue="#249 (...)",
                  made_by="tools/dosparty.py", what="the same record again")
    wanted = specimenbackup.recorded_hashes(tree)
    shared = [entries for entries in wanted.values() if len(entries) == 2]
    assert shared and sorted(shared[0]) == [("party0", "WISH0.CHA"),
                                            ("party2", "WISH0.CHA")]


# --- audit ------------------------------------------------------------------


def test_audit_finds_a_second_copy_under_another_name(tmp_path, tree):
    """The point of hashing: a specimen's bytes usually sit in the run
    directory they were copied out of, and the run may have called the file
    something else."""
    elsewhere = tmp_path / "work" / "issue249" / "run1"
    elsewhere.mkdir(parents=True)
    (elsewhere / "CHRDATC1.SAV").write_bytes(
        b"a character record, standing in for one")
    cov = specimenbackup.audit(tree, directories=[tmp_path / "work"])
    assert len(cov.found) == 1
    assert cov.per_specimen()["party0"] == (1, 2)
    assert cov.per_specimen()["party1"] == (0, 2)


def test_audit_does_not_count_a_file_that_only_shares_the_name(tmp_path, tree):
    """A copy edited since is not a copy, and this is what a name match would
    get wrong -- the whole failure `#246` is about."""
    elsewhere = tmp_path / "work"
    elsewhere.mkdir()
    (elsewhere / "WISH0.CHA").write_bytes(
        b"a character record, standing in for one!")
    cov = specimenbackup.audit(tree, directories=[elsewhere])
    assert cov.found == {}
    assert len(cov.missing) == 4


def test_audit_does_not_count_the_tree_as_a_copy_of_itself(tree):
    """Handed the tree itself, every file would match itself and the answer
    would be a reassuring nothing."""
    cov = specimenbackup.audit(tree, directories=[tree])
    assert cov.found == {}
    assert len(cov.missing) == 4


def test_audit_reads_an_archive(tmp_path, tree):
    dest = tmp_path / "out" / "copy.tar.gz"
    specimenbackup.archive(dest, tree)
    cov = specimenbackup.audit(tree, archives=[dest])
    assert len(cov.missing) == 0


# --- archive ----------------------------------------------------------------


def test_archive_holds_every_file_including_the_provenance(tmp_path, tree):
    dest = tmp_path / "out" / "copy.tar.gz"
    result = specimenbackup.archive(dest, tree)
    assert result["specimens"] == 2
    with tarfile.open(dest) as tar:
        names = sorted(tar.getnames())
    assert "por-dos/WISH-SPEC-party0/WISH0.CHA" in names
    assert "por-dos/WISH-SPEC-party0/provenance.toml" in names
    assert "DO-NOT-EDIT.md" in names
    assert result["files"] == len(names)


def test_archive_refuses_to_overwrite(tmp_path, tree):
    dest = tmp_path / "copy.tar.gz"
    specimenbackup.archive(dest, tree)
    with pytest.raises(FileExistsError):
        specimenbackup.archive(dest, tree)


def test_archive_refuses_a_destination_inside_the_repository(tree):
    """`work/` included: the game's data must never be committed, and a copy
    meant to outlive the working tree does not live in it."""
    with pytest.raises(ValueError, match="inside"):
        specimenbackup.archive(
            specimenbackup.REPO / "work" / "copy.tar.gz", tree)
    with pytest.raises(ValueError, match="inside"):
        specimenbackup.archive(specimenbackup.REPO / "copy.tar", tree)


def test_archive_refuses_a_tree_that_no_longer_matches_its_manifests(tree):
    """An archive of a damaged tree preserves the damage, and the damage is
    exactly what the manifests exist to catch."""
    victim = tree / "por-dos" / "WISH-SPEC-party0" / "WISH0.CHA"
    victim.parent.chmod(stat.S_IRWXU)
    victim.chmod(stat.S_IRWXU)
    victim.write_bytes(b"somebody opened this in an editor")
    with pytest.raises(ValueError, match="has changed"):
        specimenbackup.archive(tree.parent / "copy.tar", tree)


def test_archive_says_where_it_wrote_and_how_much(tmp_path, tree, capsys):
    dest = tmp_path / "copy.tar.gz"
    assert specimenbackup.main(["--root", str(tree), "archive", str(dest)]) == 0
    out = capsys.readouterr().out
    assert "2 specimen(s)" in out and str(dest) in out


# --- verify -----------------------------------------------------------------


def test_verify_passes_on_an_archive_just_written(tmp_path, tree):
    dest = tmp_path / "copy.tar.gz"
    specimenbackup.archive(dest, tree)
    assert specimenbackup.verify(dest, tree) == []


def test_verify_catches_an_archive_missing_a_specimen(tmp_path, tree):
    """What a partial copy looks like: tar exits zero and the evidence is
    still gone."""
    dest = tmp_path / "partial.tar"
    with tarfile.open(dest, "w") as tar:
        one = tree / "por-dos" / "WISH-SPEC-party0"
        for path in sorted(one.rglob("*")):
            tar.add(path, arcname=str(path.relative_to(tree)))
    problems = specimenbackup.verify(dest, tree)
    assert len(problems) == 2
    assert all(p.startswith("party1:") for p in problems)
    assert "is not in the archive" in problems[0]


def test_verify_catches_an_archive_holding_the_wrong_bytes(tmp_path, tree):
    dest = tmp_path / "wrong.tar"
    with tarfile.open(dest, "w") as tar:
        for path in sorted(tree.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(tree)))
        edited = tmp_path / "WISH0.CHA"
        edited.write_bytes(b"not what the manifest records")
        tar.add(edited, arcname="por-dos/WISH-SPEC-party0/WISH0.CHA")
    problems = specimenbackup.verify(dest, tree)
    assert len(problems) == 1
    assert "is not the recorded bytes" in problems[0]


def test_verify_exits_non_zero_when_the_archive_would_not_restore(tmp_path,
                                                                  tree,
                                                                  capsys):
    dest = tmp_path / "empty.tar"
    with tarfile.open(dest, "w"):
        pass
    assert specimenbackup.main(["--root", str(tree), "verify", str(dest)]) == 1
    assert "4 problem(s)" in capsys.readouterr().out


def test_verify_names_the_count_when_it_passes(tmp_path, tree, capsys):
    dest = tmp_path / "copy.tar"
    specimenbackup.archive(dest, tree)
    assert specimenbackup.main(["--root", str(tree), "verify", str(dest)]) == 0
    assert "all 2 specimen(s)" in capsys.readouterr().out


# --- the audit command ------------------------------------------------------


def test_audit_command_reports_the_counts(tmp_path, tree, capsys):
    elsewhere = tmp_path / "work"
    elsewhere.mkdir()
    (elsewhere / "anything.bin").write_bytes(
        b"a character record, standing in for one")
    assert specimenbackup.main(["--root", str(tree), "audit",
                                "--in", str(elsewhere)]) == 0
    out = capsys.readouterr().out
    assert "4 distinct file contents recorded" in out
    assert "1 of them have a second copy" in out
    assert "3 exist nowhere but the tree itself" in out
    assert "party1" in out and "0 of   2 files" in out


def test_archive_refuses_a_zstd_name_it_cannot_write(tmp_path, tree):
    """A `.tar.zst` that is a plain tar is worse than no archive at all.

    Nothing here writes zstd -- `_stream_tar` only reads it -- so a
    destination ending `.zst` used to fall through to an uncompressed tar,
    report success, and then fail `verify` with `unsupported format`.  The
    name has to mean what it says, because the operator's next move is the
    `verify` line this tool prints for them.
    """
    dest = tmp_path / "copy.tar.zst"
    with pytest.raises(ValueError, match="zstd"):
        specimenbackup.archive(dest, tree)
    assert not dest.exists()


def test_a_failed_archive_leaves_nothing_at_the_name_it_was_given(
        tmp_path, tree, monkeypatch):
    """A write that dies partway must not block every retry.

    `archive` never overwrites, so a truncated tar left at `dest` would stand
    in the way of the next attempt with nothing saying it was a wreck.  It is
    written beside the destination and renamed only on success.
    """
    real_add = tarfile.TarFile.add
    seen = {"n": 0}

    def flaky(self, path, *a, **kw):
        seen["n"] += 1
        if seen["n"] == 2:
            raise OSError(28, "No space left on device")
        return real_add(self, path, *a, **kw)

    monkeypatch.setattr(tarfile.TarFile, "add", flaky)
    dest = tmp_path / "copy.tar.gz"
    with pytest.raises(OSError):
        specimenbackup.archive(dest, tree)
    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_a_missing_archive_is_a_message_rather_than_a_traceback(
        tmp_path, tree, capsys):
    """`verify` and `audit` answer an operator's mistake the way `archive`
    does: one line on stderr and a non-zero exit."""
    args = argparse.Namespace(archive=str(tmp_path / "nothing.tar.gz"),
                              root=str(tree))
    assert specimenbackup.cmd_verify(args) == 1
    assert "nothing.tar.gz" in capsys.readouterr().err

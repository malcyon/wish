"""`tools/curse_of_the_azure_bonds/cursepaladin.py`'s offline half, for `#409`.

The driven half needs an emulator and is not tested here; what is tested is
everything a wrong answer would quietly poison the run with -- which record
offsets the class fields are read at, that an ability is staged into **both**
of the record's two arrays, and that `stage` writes nothing it was not asked
for.

No game data is read: the save disk each test uses is built here out of
zeroes, which is what `SAVEAZURE` is before a party is written into it.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds import cursepaladin as cp  # noqa: E402
from tools.registry import specimens  # noqa: E402

#: `SAVEAZURE`'s payload length, from `goldbox/c64_save.py` by way of
#: `tools/curse_of_the_azure_bonds/cursetrain.py`'s geometry: eight 256-byte slots at `$400` and the
#: name table at `$C00`.
PAYLOAD = 7424
LOAD = 0x4B00


def _blank_save(tmp_path: pathlib.Path, names: dict[int, str]) -> pathlib.Path:
    """A save disk with a zeroed `SAVEAZURE` and the named slots occupied."""
    body = bytearray(PAYLOAD)
    for slot, name in names.items():
        off = cp.SLOT0 + slot * cp.SLOT_SIZE
        body[off + 0x072] = 7                      # race: human
        body[off + 0x0A0] = 6                      # level
        body[off + 0x0CF] = 6                      # level_paladin
        body[off + 0x0EB] = 0x40                   # class_bits: paladin
        for i, ability in enumerate((15, 15, 16, 15, 15, 17)):
            body[off + cp.ABILITY_NOW + i] = ability
            body[off + cp.ABILITY_COPY + i] = ability
        blob = name.encode("ascii").ljust(16, b"\0")
        body[0xC00 + slot * 16:0xC00 + (slot + 1) * 16] = blob
        body[off:off + 16] = blob
    disk = D64.blank(b"CURSE SAVE")
    disk.write_file(b"SAVEAZURE", LOAD.to_bytes(2, "little") + bytes(body))
    path = tmp_path / "save.d64"
    disk.save(path)
    return path


def test_slots_are_named_from_their_records_not_the_table(tmp_path):
    """A table holding one NPC name must not hide the party."""
    path = _blank_save(tmp_path, {0: "ALPHA", 1: "BETA"})
    image = bytearray(path.read_bytes())
    load, body = cp.payload_of(bytes(image))
    body = bytearray(body)
    body[0xC00:0xC00 + 16] = b"BAR PATRON".ljust(16, b"\0")
    body[0xC10:0xC20] = bytes(16)
    assert cp.slot_names(bytes(body))[:3] == ["ALPHA", "BETA", ""]


_SPECIMEN = (specimens.tree_root() / "coab-c64" /
             "WISH-SPEC-curse-671-invisibility-absent-before-attack.D64")


@pytest.mark.skipif(not _SPECIMEN.is_file(),
                    reason="needs WISH-SPEC-curse-671-invisibility-absent-before-attack")
def test_the_curse_671_disk_names_its_whole_party():
    _, body = cp.payload_of(_SPECIMEN.read_bytes())
    assert cp.slot_names(body)[:6] == [
        "PHILIPPE", "SHARA", "LEDERA", "TRAVIS", "MARK", "MATHEW"]


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_the_class_fields_are_read_at_the_records_own_offsets(tmp_path):
    """`class_bits` at `0x0EB` and the paladin's level at `0x0CF`."""
    path = _blank_save(tmp_path, {5: "MATHEW"})
    _, payload = cp.payload_of(path.read_bytes())
    base = cp.SLOT0 + 5 * cp.SLOT_SIZE
    fields = cp.describe(payload[base:base + cp.SLOT_SIZE])
    assert fields["class_bits"] == 0x40
    assert fields["level_paladin"] == 6
    assert fields["race"] == 7
    assert fields["cha"] == 17


def test_an_ability_is_staged_into_both_of_the_records_arrays(tmp_path):
    """`GEN $1E9C` copies `0x065` down to `0x014`, so a stage that wrote one
    of them would leave a character no roll could make."""
    path = _blank_save(tmp_path, {4: "MARK"})
    out = tmp_path / "staged.d64"
    cp.stage(_Args(base=str(path), out=str(out), give=["MARK:wis=18"]))
    _, payload = cp.payload_of(out.read_bytes())
    base = cp.SLOT0 + 4 * cp.SLOT_SIZE
    assert payload[base + cp.ABILITY_NOW + 2] == 18
    assert payload[base + cp.ABILITY_COPY + 2] == 18


def test_stage_writes_nothing_it_was_not_asked_for(tmp_path):
    """One field named, one byte pair changed, and the rest byte for byte."""
    path = _blank_save(tmp_path, {4: "MARK", 5: "MATHEW"})
    out = tmp_path / "staged.d64"
    cp.stage(_Args(base=str(path), out=str(out), give=["MARK:wis=18"]))
    _, before = cp.payload_of(path.read_bytes())
    _, after = cp.payload_of(out.read_bytes())
    moved = {i for i in range(len(before)) if before[i] != after[i]}
    base = cp.SLOT0 + 4 * cp.SLOT_SIZE
    assert moved == {base + cp.ABILITY_NOW + 2, base + cp.ABILITY_COPY + 2}


def test_a_name_the_disk_does_not_carry_is_refused(tmp_path):
    path = _blank_save(tmp_path, {5: "MATHEW"})
    with pytest.raises(SystemExit):
        cp.stage(_Args(base=str(path), out=str(tmp_path / "x.d64"),
                       give=["NOBODY:wis=18"]))
    with pytest.raises(SystemExit):
        cp.find_slot(str(path), "NOBODY")
    assert cp.find_slot(str(path), "mathew") == 5


def test_the_live_class_is_the_one_non_zero_level_slot():
    """What `run` reads to know which slot to stage the regain into."""
    assert cp.live_class({"level_cleric": 1}) == "cleric"
    assert cp.live_class({"level_fighter": 1, "level_paladin": 6}) is None
    assert cp.live_class({}) is None


#: The party menu as the game leaves it drawn for the whole of a save
#: (`#712`'s screens `06-save-answered` to `08-saved`): every item, `SAVE
#: CURRENT GAME` included, with only row 24 changing.
_MENU = "CREATE NEW CHARACTER\nVIEW CHARACTER\nSAVE CURRENT GAME\nBEGIN ADVENTURING\n"


class _Screen:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text

    def contains(self, needle):
        return needle in self._text


class _FakeSess:
    """Enough of a `CurseSession` for `save_current_game`.

    `screens` is what successive `screen()` reads return, the last one
    repeating; `wait_text` reads through them the way the real one polls.
    Every call that matters to the order is recorded.
    """

    save_disk = "/slot/SIDE0.D64"

    def __init__(self, screens):
        self.screens = list(screens)
        self.calls: list[tuple] = []
        self.kbd = self

    def select_row(self, label):
        self.calls.append(("select_row", label))
        return True

    def screen(self):
        text = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        self.calls.append(("screen", text))
        return _Screen(text)

    def screenshot(self, path):
        return True

    def handle_prompt(self, s=None):
        return False

    def wait_text(self, needle, timeout=180.0):
        self.calls.append(("wait_text", needle))
        for _ in range(len(self.screens) + 1):
            s = self.screen()
            if s.contains(needle):
                return needle, s
        return None, None

    def settle(self, seconds=6.0):
        self.calls.append(("settle", seconds))

    def attach(self, path, unit=8, settle=None):
        self.calls.append(("attach", path))


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(
        "tools.curse_of_the_azure_bonds.curseload.answer_yes",
        lambda sess, word: True)
    monkeypatch.setattr(cp.time, "sleep", lambda s: None)
    # The default: the drive closed the entry on the first read, so a test
    # that only cares about the menu-waiting half never has to know about
    # the copy step underneath it.
    monkeypatch.setattr(S, "copy_closed_disk",
                        lambda src, dest: str(dest))


def test_save_current_game_waits_for_saving_game_to_clear_then_flushes_the_disk(
        tmp_path, quick):
    """`#712`: the party menu stays drawn under `SAVING GAME`, so waiting for
    `SAVE CURRENT GAME` returned at once and the copy found `SAVEAZURE`
    open.  The wait has to outlast `SAVING GAME` on the screen, and then the
    save disk goes into the drive again, which is what makes VICE write the
    closed directory entry out to the image file."""
    saving = _MENU + "SAVING GAME"
    run = cp.Run(tmp_path / "out")
    run.sess = _FakeSess([_MENU, saving, saving, saving, saving, _MENU])

    assert cp.save_current_game(run, tmp_path / "SAVED.D64") is True

    calls = run.sess.calls
    assert calls.count(("attach", _FakeSess.save_disk)) == 1, calls
    at = calls.index(("attach", _FakeSess.save_disk))
    reads = [c[1] for c in calls[:at] if c[0] == "screen"]
    assert reads.count(saving) == 4, reads
    assert reads[-1] == _MENU


def test_save_current_game_fails_if_saving_game_never_appears(tmp_path, quick):
    """A save that never starts must not fall through to the copy step."""
    run = cp.Run(tmp_path / "out")
    run.sess = _FakeSess([_MENU])

    assert cp.save_current_game(run, tmp_path / "SAVED.D64") is False
    assert not [c for c in run.sess.calls if c[0] == "attach"]


def test_save_current_game_fails_if_saving_game_never_clears(
        tmp_path, quick, monkeypatch):
    """A write still showing `SAVING GAME` at the deadline is not finished,
    and the disk is not re-attached under it."""
    monkeypatch.setattr(cp, "SAVE_WRITE_WAIT", 0.05)
    run = cp.Run(tmp_path / "out")
    run.sess = _FakeSess([_MENU + "SAVING GAME"])

    assert cp.save_current_game(run, tmp_path / "SAVED.D64") is False
    assert not [c for c in run.sess.calls if c[0] == "attach"]


def test_save_current_game_retries_the_settle_and_attach_until_the_drive_closes_it(
        tmp_path, quick, monkeypatch):
    """`wait_text_gone` only proves the menu text left -- not that the 1541
    has actually closed `SAVEAZURE`.  A `copy_closed_disk` that still finds
    it open on the first tries must not fail the save outright; it must
    settle and re-attach again, the way `copy_closed_disk` itself retries a
    read that finds a directory entry still open."""
    saving = _MENU + "SAVING GAME"
    run = cp.Run(tmp_path / "out")
    run.sess = _FakeSess([_MENU, saving, saving, _MENU])
    dest = tmp_path / "SAVED.D64"
    attempts = []

    def flaky(src, d):
        attempts.append((src, d))
        if len(attempts) < 3:
            raise RuntimeError("open directory entry 'SAVEDGAME0'")
        return str(d)

    monkeypatch.setattr(S, "copy_closed_disk", flaky)
    slept = []
    monkeypatch.setattr(cp.time, "sleep", slept.append)

    assert cp.save_current_game(run, dest) is True

    assert len(attempts) == 3
    assert all(src == pathlib.Path(run.sess.save_disk) and d == dest
               for src, d in attempts)
    assert run.sess.calls.count(("attach", run.sess.save_disk)) == 3
    assert run.sess.calls.count(("settle", 4)) == 3
    # `wait_text_gone`'s own polling sleeps land in the same list; only the
    # two retry backoffs, at the end, are this loop's.
    assert slept[-2:] == [2.0, 2.0]


def test_save_current_game_gives_up_with_the_original_error_after_the_retry_budget(
        tmp_path, quick, monkeypatch):
    """A drive that never closes the entry must not be retried forever, and
    the failure raised must be `copy_closed_disk`'s own, not a swallowed
    generic one."""
    saving = _MENU + "SAVING GAME"
    run = cp.Run(tmp_path / "out")
    run.sess = _FakeSess([_MENU, saving, saving, _MENU])
    dest = tmp_path / "SAVED.D64"
    attempts = []

    def never_closes(src, d):
        attempts.append((src, d))
        raise RuntimeError("open directory entry 'SAVEDGAME0'")

    monkeypatch.setattr(S, "copy_closed_disk", never_closes)
    monkeypatch.setattr(cp.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="SAVEDGAME0"):
        cp.save_current_game(run, dest, attempts=3, backoff=0.01)

    assert len(attempts) == 3
    assert run.sess.calls.count(("attach", run.sess.save_disk)) == 3


def test_save_current_game_refuses_an_attempts_count_below_one(tmp_path, quick):
    """`copy_closed_disk` guards the same way; without this guard
    `attempts=0` leaves `last_exc` `None` and `raise last_exc` fails with a
    confusing `TypeError` instead of a clear complaint."""
    run = cp.Run(tmp_path / "out")
    run.sess = _FakeSess([_MENU])

    with pytest.raises(ValueError, match="attempts must be at least one"):
        cp.save_current_game(run, tmp_path / "SAVED.D64", attempts=0)


def test_an_unreadable_screen_never_counts_as_the_text_having_gone(quick):
    """`screen()` returns None when the monitor read fails; two of those in a
    row must not pass for `SAVING GAME` having left."""
    sess = _FakeSess([_MENU + "SAVING GAME"])
    reads = iter([None, None, None, _Screen(_MENU), _Screen(_MENU)])
    sess.screen = lambda: next(reads)

    assert cp.wait_text_gone(sess, "SAVING GAME", 5) is True
    # Only the two real reads counted: the iterator is exhausted.
    assert next(reads, "done") == "done"


def test_the_class_slots_match_the_bit_the_engine_ors_back():
    """`GEN $20A3` reads `$0B82,X` -- `01 02 04 08 10 20 40 80` -- with the
    same index it writes `class_levels[X]` with, so a paladin's slot 6 is the
    `$40` this ticket is about."""
    from goldbox import classcode

    for name, slot in cp.CLASS_SLOT.items():
        assert classcode.CLASS_BIT_FOR_NAME[name] == 1 << slot

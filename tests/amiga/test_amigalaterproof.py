"""`tools/amiga/amigalaterproof.py`: the run harness that put `write_later` in front
of the two later Amiga games.

The run itself is in `docs/203-a-converted-later-amiga-party-in-the-running-game.md`
and cannot be a test -- it needs a Windows VM, WinUAE and the player's own
disks.  What can be tested is the two things the harness decides on its own,
because both of them would spoil a run silently:

* **the ordering**, which is why this tool exists rather than
  `tools/amiga/amigalaterwrite.py --into`.  The writer's riskiest choice is a
  boolean chain head where `write_por` writes NULL, and a wrong head does not
  spoil one character -- the loader's file position desynchronises and every
  character *after* it is read out of the wrong bytes.  So the character
  carrying the items has to be put in front of the others, and the C64 saves
  this converts from keep theirs last;
* **the mask**, which has to be the lists the writers *declare* and never
  whatever happened to differ (`.claude/rules/conversions.md`).  A mask that
  quietly widened would turn a real regression into a clean run.
"""

from __future__ import annotations

import pytest
from gamedata import specimen_root

from goldbox import amiga_later, amiga_port, dos_port
from tools.amiga import amigalaterproof as proof

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class _Stub:
    """Only `.name` is read by `reorder`, so only `.name` is here."""

    def __init__(self, name: str) -> None:
        self.name = name


def _party(*names: str) -> list:
    return [(None, _Stub(n), None) for n in names]


def _names(built: list) -> list[str]:
    return [c.name for _a, c, _b in built]


# ---------------------------------------------------------------------------
# The ordering
# ---------------------------------------------------------------------------

def test_the_named_character_goes_to_the_front_and_the_rest_keep_their_order():
    built = _party("MORGAINE", "DOMINIC", "MALACHITE", "Guy de Valois ")
    moved = proof.reorder(built, "Guy de Valois")
    assert _names(moved) == ["Guy de Valois ", "MORGAINE", "DOMINIC",
                             "MALACHITE"]


def test_the_name_is_matched_without_case_or_the_amiga_trailing_space():
    """An Amiga record's own copy of a name can carry a trailing space the
    C64's does not (`#308`), and a command line is typed in whatever case
    the person felt like."""
    built = _party("MORGAINE", "Guy de Valois ")
    assert _names(proof.reorder(built, "  guy DE valois  "))[0] \
        == "Guy de Valois "


def test_a_party_with_no_first_named_is_left_exactly_as_it_came():
    built = _party("MORGAINE", "DOMINIC")
    assert proof.reorder(built, None) is built


def test_a_name_nobody_in_the_party_has_is_refused_rather_than_ignored():
    """Silently converting the party in its original order would produce a
    disk that looks right and tests nothing: the character with the items
    would still be last, with nobody behind him to be corrupted."""
    built = _party("MORGAINE", "DOMINIC")
    with pytest.raises(SystemExit) as bad:
        proof.reorder(built, "GUY DE VALOIS")
    assert "MORGAINE" in str(bad.value)      # it names who is actually there


# ---------------------------------------------------------------------------
# The mask
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shape", amiga_port.AMIGA_DELTAS, ids=lambda s: s.key)
def test_every_unsourced_byte_the_writer_declares_is_in_the_mask(shape):
    """`LATER_WRITE_UNSOURCED` is the list of Amiga offsets no DOS field
    reaches, so a resave is entitled to differ there and the diff must not
    report one."""
    mask = proof.declared_record_mask(shape)
    for at, size, _why in amiga_later.LATER_WRITE_UNSOURCED[shape.key]:
        assert set(range(at, at + size)) <= mask, hex(at)


@pytest.mark.parametrize("shape", amiga_port.AMIGA_DELTAS, ids=lambda s: s.key)
def test_the_mask_is_the_declared_lists_and_not_everything(shape):
    """The half that matters: a field the writer claims to convert has to be
    outside the mask, or the diff proves nothing.  Hit points, armour class
    and the seven abilities are what a player reads off the sheet."""
    mask = proof.declared_record_mask(shape)
    table = dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]
    for name in ("hp_max", "armour_class", "strength", "intelligence",
                 "wisdom", "dexterity", "constitution", "charisma",
                 "race", "char_class", "class_levels"):
        field = table[name]
        at = shape.offset(field.offset)
        assert not (set(range(at, at + field.size)) & mask), name


@pytest.mark.parametrize("shape", amiga_port.AMIGA_DELTAS, ids=lambda s: s.key)
def test_the_live_heap_pointers_the_engine_fills_in_are_masked(shape):
    """`effect_chain` and `item_chain` come back as real Amiga addresses in
    the engine's own resave -- measured on both titles, 2026-09-07 -- and
    `goldbox.dos_codec.WRITE_UNSOURCED` is where the writer says so."""
    mask = proof.declared_record_mask(shape)
    table = dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]
    for name in ("effect_chain", "item_chain"):
        field = table[name]
        at = shape.offset(field.offset)
        assert set(range(at, at + field.size)) <= mask, name


def test_the_derived_bytes_the_engine_recomputes_are_masked():
    """`#402 (Amiga Curse recomputes thac0_current and a roster_tail byte on
    load, and no declared list says so)`: the two Curse offsets in
    `LATER_WRITE_DERIVED` are exactly `thac0_current` and the sixth byte of
    `roster_tail`, computed from the shift map rather than typed twice."""
    shape = amiga_port.CURSE_DELTAS
    table = dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]
    want = {shape.offset(table["thac0_current"].offset),
            shape.offset(table["roster_tail"].offset) + 5}
    mask = proof.declared_record_mask(shape)
    assert want <= mask
    got = {at for at, _size, _why in amiga_later.LATER_WRITE_DERIVED[shape.key]}
    assert got == want


@pytest.mark.parametrize("shape", amiga_port.AMIGA_DELTAS, ids=lambda s: s.key)
def test_the_control_and_share_bytes_are_not_masked(shape):
    """`field_83_87` is on `WRITE_CONSTANTS` for the control byte the writer
    patches over it, but the control and share bytes it now carries exactly
    (#529) must reach a live diff -- masking the whole field would swallow
    both silently."""
    table = dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]
    f83 = table["field_83_87"]
    at = shape.offset(f83.offset)
    control_index = 1 if f83.size == 5 else 0
    mask = proof.declared_record_mask(shape)
    assert at + control_index not in mask
    assert at + control_index + 1 not in mask


class _CharStub:
    """Only `.deltas`, `.items` and `.effects` are read by `declared_block_mask`."""

    def __init__(self, deltas) -> None:
        self.deltas = deltas
        self.items: list = []
        self.effects: list = []


@pytest.mark.parametrize("shape", amiga_port.AMIGA_DELTAS, ids=lambda s: s.key)
def test_a_control_or_share_difference_is_caught_by_the_unmasked_diff(shape):
    """Two records differing only in the control and share bytes: before this
    fix, `declared_record_mask` covered the whole `field_83_87` run and a
    live diff would have reported zero unexplained differences here."""
    table = dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]
    f83 = table["field_83_87"]
    at = shape.offset(f83.offset)
    control_index = 1 if f83.size == 5 else 0
    a = bytearray(shape.record_size)
    b = bytearray(shape.record_size)
    b[at + control_index] = 0x80
    b[at + control_index + 1] = 3
    mask = proof.declared_block_mask(_CharStub(shape))
    loose = [i for i in range(len(a)) if a[i] != b[i] and i not in mask]
    assert loose == [at + control_index, at + control_index + 1]


def test_silver_blades_has_no_derived_bytes_declared():
    """UNMEASURED, not confirmed absent (`#402`): Silver Blades' converted
    party happened to agree with the engine's resave, which proves nothing,
    so nothing is masked there yet."""
    assert amiga_later.LATER_WRITE_DERIVED[amiga_port.SILVER_BLADES_DELTAS.key] == ()


def test_the_curse_resave_diff_is_the_known_gap_and_old_thac0_base():
    """The live-game evidence `#402` rests on: Amiga Curse loaded a party
    `write_later` converted and wrote it back through `ENCAMP > SAVE`, and
    before the derived-field fix `thac0_current`, one `roster_tail` byte and
    `combat_figure` were the only bytes outside the declared lists.
    `combat_figure` is the writer's own known gap; the other two are now on
    `LATER_WRITE_DERIVED`.

    The reference specimen is `WISH-SPEC-coab-amiga-converted-resave-
    postspellfix`, captured 2026-09-14 at commit `64eb99a` -- after `#547
    (A C64-to-DOS Curse resave writes a thief's base skills and a mage's/
    cleric's spell slots wrong, silently repaired by the engine's own next
    load)`'s fix landed, which makes `write_later` compute real spell-slot
    values instead of zeros for a Curse party.  The original specimen,
    `WISH-SPEC-coab-amiga-converted-resave` (`#384`, captured 2026-09-07,
    before the fix), still held the pre-fix zeros, so comparing today's
    fixed "ours" against it reported the fix landing as a regression --
    `#549 (The Amiga two-hop spell-slot proof's reference specimen predates
    #547's fix, so it now reports the fix landing as a regression)`.  This
    fresh specimen proves the round trip still holds with the corrected
    values: PHILIPPE's `spells_castable_magic_user` (`4 2 1 0 0`), SHARA's
    `spells_castable_cleric` (`5 5 2 0 0`) and LEDERA's
    `spells_castable_magic_user` (`3 2 0 0 0`) all survive the Amiga
    engine's own load-camp-save cycle unchanged -- the engine does not
    recompute this field on load, which is why the pre-fix zeros were
    permanent and why the fix matters more for Amiga than for DOS.

    That 2026-09-14 conversion also predates the Amiga THAC0 floor proof.
    `write_later` then supplied 39 for the pure low-level mages MATHEW and
    PHILIPPE, and the ordinary engine resave preserved 39 without running a
    base-THAC0 rebuild.  Current conversion intentionally supplies 40, matching
    the target engine's unguarded import/training rebuild.  Their one-byte
    `thac0_base` differences therefore belong in this exact diff; masking them
    would hide the evidence that ordinary resave and import use different
    paths.

    `docs/203-a-converted-later-amiga-party-in-the-running-game.md`.
    """
    root = specimen_root()
    if root is None:
        pytest.skip("no $WISH_SPECIMENS; see tools/registry/specimens.py")
    source = (root / "coab-c64" /
              "WISH-SPEC-curse-52-dialog-converted-resave.D64")
    theirs_path = (root / "coab-amiga" /
                   "WISH-SPEC-coab-amiga-converted-resave-postspellfix" /
                   "savgamC.dat")
    if not source.is_file() or not theirs_path.is_file():
        pytest.skip("the #384/#402/#549 specimens are not on this machine")

    amigalaterwrite = proof.amigalaterwrite
    built = amigalaterwrite.convert(amigalaterwrite.party_from(source))
    ours_by_name = {c.name.strip().upper(): c for _n, c, _r in built}

    theirs_data = theirs_path.read_bytes()
    theirs_by_name = {c.name.strip().upper(): c
                      for c in proof.party_of(theirs_data, str(theirs_path))}

    assert {"MATHEW", "PHILIPPE"} <= ours_by_name.keys()
    thac0_differences = {
        name: (mine.get("thac0_base"), theirs_by_name[name].get("thac0_base"))
        for name, mine in ours_by_name.items()
        if (name in theirs_by_name
            and mine.get("thac0_base")
            != theirs_by_name[name].get("thac0_base"))
    }
    assert thac0_differences == {
        "MATHEW": (40, 39),
        "PHILIPPE": (40, 39),
    }
    loose: set[str] = set()
    for name, mine in ours_by_name.items():
        twin = theirs_by_name.get(name)
        if twin is None:
            continue
        a, b = mine.block_bytes(), twin.block_bytes()
        mask = proof.declared_block_mask(mine)
        for at in range(min(len(a), len(b))):
            if a[at] != b[at] and at not in mask:
                loose.add(proof.field_at(mine.deltas, at))
    assert loose == {"combat_figure+0", "thac0_base+0"}


# ---------------------------------------------------------------------------
# Naming an offset, which is what makes a diff line readable
# ---------------------------------------------------------------------------

def test_an_offset_in_the_record_is_named_by_its_field():
    shape = amiga_port.SILVER_BLADES_DELTAS
    at = shape.offset(dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]["hp_max"]
                      .offset)
    assert proof.field_at(shape, at) == "hp_max+0"


def test_silver_blades_names_its_re_encoded_spellbook():
    """The one region with no DOS field behind it: 117 flag bytes packed into
    15 of mask, which `AmigaDeltas.offset` cannot map."""
    shape = amiga_port.SILVER_BLADES_DELTAS
    assert proof.field_at(shape, amiga_later.AMIGA_SSB_SPELLBOOK_AT + 3) \
        == "spellbook+3"


# ---------------------------------------------------------------------------
# Effects that time ran out on
# ---------------------------------------------------------------------------

def _effect(effect_id: int, minutes: int, value: int = 0x0b, flag: int = 0
            ) -> bytes:
    """One ten-byte node: id, pad, duration u16 big-endian, value, flag, next."""
    return (bytes((effect_id, 0)) + minutes.to_bytes(2, "big")
            + bytes((value, flag)) + bytes(4))


def _slot(tmp_path, name: str, effects: list[bytes], clock_minutes: int):
    """A synthetic Curse saved game, one member, on a given clock."""
    from goldbox import amiga_savegame, dos_savegame
    container = amiga_savegame.CURSE
    record = bytearray(container.deltas.record_size)
    record[:5] = b"ALPHA"
    for i in range(6):
        record[0x10 + 2 * i] = record[0x11 + 2 * i] = 12
    base = amiga_savegame.parse(_synthetic_save(container), container)
    char = amiga_later.AmigaCharacter.from_bytes(
        bytes(record), container.deltas, effects=effects)
    data = bytearray(amiga_savegame.rebuild(base, [char]))
    digits = (0, clock_minutes % 10, clock_minutes // 10 % 6,
              clock_minutes // 60 % 24, clock_minutes // 1440 % 30,
              clock_minutes // 43200 % 12)
    for i, digit in enumerate(digits):
        at = container.vm_offset(dos_savegame.CLOCK + i)
        data[at:at + 2] = digit.to_bytes(2, "big")
    path = tmp_path / name
    path.write_bytes(bytes(data))
    return path


def _synthetic_save(container) -> bytes:
    from tests.amiga.test_amiga_savegame import _synthetic
    return _synthetic(container, ("ALPHA",))


def _diff(tmp_path, capsys, before: list[bytes], after: list[bytes],
          elapsed: int, start: int = 10) -> tuple[int, str]:
    a = _slot(tmp_path, "ours.dat", before, start)
    b = _slot(tmp_path, "theirs.dat", after, start + elapsed)
    code = proof.main(["diff", "--ours", str(a), "--theirs", str(b)])
    return code, capsys.readouterr().out


def test_a_two_minute_shield_that_ran_out_is_named_and_not_undeclared(
        tmp_path, capsys):
    code, out = _diff(tmp_path, capsys,
                      [_effect(75, 0), _effect(17, 2), _effect(134, 0)],
                      [_effect(75, 0), _effect(134, 0)], 2)
    assert code == 0
    assert "ALPHA: effect id 17, 2 minutes left, expired" in out
    assert "0 differences outside the declared lists" in out


def test_a_long_effect_ages_by_exactly_the_minutes_that_passed(
        tmp_path, capsys):
    code, out = _diff(tmp_path, capsys, [_effect(45, 47)], [_effect(45, 45)], 2)
    assert code == 0
    assert "0 differences outside the declared lists" in out


@pytest.mark.parametrize("after", [
    [],                                          # gone with time left
    [_effect(45, 46)],                           # aged by 1, not 2
    [_effect(45, 47)],                           # did not age
    [_effect(46, 45)],                           # id changed
    [_effect(45, 45, value=0x0c)],               # value changed
    [_effect(45, 45), _effect(9, 5)],            # one the party never had
], ids=["vanished", "wrong-age", "no-age", "id", "value", "extra"])
def test_anything_else_in_the_effect_list_is_undeclared(
        tmp_path, capsys, after):
    code, out = _diff(tmp_path, capsys, [_effect(45, 47)], after, 2)
    assert code == 1
    assert "0 differences outside the declared lists" not in out


def test_a_removed_effect_with_no_time_elapsed_is_undeclared(
        tmp_path, capsys):
    code, out = _diff(tmp_path, capsys, [_effect(17, 2)], [], 0)
    assert code == 1
    assert "expired" not in out


def test_a_duration_zero_effect_that_is_gone_is_undeclared(tmp_path, capsys):
    code, _out = _diff(tmp_path, capsys, [_effect(75, 0)], [], 5)
    assert code == 1


def test_a_clock_that_rolls_over_midnight_still_expires_the_effect(
        tmp_path, capsys):
    code, out = _diff(tmp_path, capsys, [_effect(17, 2)], [], 2,
                      start=23 * 60 + 59)
    assert code == 0
    assert "effect id 17, 2 minutes left, expired" in out


def test_a_clock_that_ran_backwards_is_undeclared_and_does_not_crash(
        tmp_path, capsys):
    code, out = _diff(tmp_path, capsys, [_effect(45, 47)],
                      [_effect(45, 49)], -2)
    assert code == 1
    assert "-2 minutes" in out


def test_a_large_elapsed_time_expires_every_timed_effect(tmp_path, capsys):
    code, out = _diff(tmp_path, capsys,
                      [_effect(75, 0), _effect(45, 47), _effect(17, 2)],
                      [_effect(75, 0)], 500)
    assert code == 0
    assert out.count("expired") >= 2


def test_an_effect_the_engine_kept_past_its_time_is_named_and_the_next_still_lines_up(
        tmp_path, capsys):
    code, out = _diff(tmp_path, capsys,
                      [_effect(17, 2), _effect(134, 0)],
                      [_effect(17, 2), _effect(134, 0)], 2)
    assert code == 1
    assert "kept by the engine" in out
    assert "\n1 differences outside the declared lists" in out
    assert "effect 1" not in out            # the follower was not misaligned


# ---------------------------------------------------------------------------
# The opening scene's award
# ---------------------------------------------------------------------------

_SB = amiga_port.SILVER_BLADES_DELTAS
_XP = _SB.offset(dos_port.FIELDS_BY_NAME_FOR[_SB.dos.key]["experience"].offset)


class _Member:
    """What `do_diff` and `opening_award` read of an `AmigaCharacter`."""

    def __init__(self, name, char_class, scores, xp) -> None:
        self.name = name
        self.deltas = _SB
        self.items: tuple = ()
        self.effects: tuple = ()
        self.abilities = list(scores)
        self._class = char_class
        raw = bytearray(_SB.record_size)
        raw[_XP:_XP + 4] = xp.to_bytes(4, "big")
        self.raw = bytes(raw)

    def get(self, field):
        assert field == "char_class"
        return self._class

    def block_bytes(self):
        return self.raw


class _Save:
    def __init__(self, members) -> None:
        self.characters = members


# class codes: 3 paladin, 2 fighter, 4 ranger, 0 cleric, 5 magic-user,
# 14 fighter/thief (goldbox.classcode.CLASS_CODE_TABLE)
_PARTY = (("GUY", 3, (18, 10, 18, 10, 10, 10)),
          ("EPONA", 2, (18, 10, 10, 10, 10, 10)),
          ("PAINE", 4, (18, 17, 16, 10, 10, 10)),
          ("DOMINIC", 0, (10, 10, 18, 10, 10, 10)),
          ("MALACHITE", 14, (18, 10, 10, 18, 10, 10)),
          ("MORGAINE", 5, (10, 18, 10, 10, 10, 10)))


def _award_diff(monkeypatch, capsys, rises, flag):
    ours = [_Member(n, c, s, 200000) for n, c, s in _PARTY]
    theirs = [_Member(n, c, s, 200000 + r)
              for (n, c, s), r in zip(_PARTY, rises)]
    monkeypatch.setattr(proof, "slot_bytes", lambda p, s: (b"", str(p)))
    monkeypatch.setattr(proof, "save_of",
                        lambda data, where: _Save(
                            ours if "ours" in where else theirs))
    monkeypatch.setattr(proof, "clock_minutes", lambda save: 0)
    args = type("A", (), {"ours": "ours", "ours_slot": None,
                          "theirs": "theirs", "theirs_slot": None,
                          "opening_award": flag})()
    code = proof.do_diff(args)
    return code, capsys.readouterr().out


_AWARDS = [2750, 2750, 2750, 2750, 1250, 2750]


def test_each_members_own_award_is_accepted_with_the_flag(monkeypatch, capsys):
    code, out = _award_diff(monkeypatch, capsys, _AWARDS, "ssb")
    assert code == 0, out
    assert "0 differences outside the declared lists" in out


def test_the_same_rise_is_undeclared_without_the_flag(monkeypatch, capsys):
    code, out = _award_diff(monkeypatch, capsys, _AWARDS, None)
    assert code == 1
    assert "experience" in out


def test_a_rise_one_off_the_award_stays_undeclared(monkeypatch, capsys):
    rises = list(_AWARDS)
    rises[2] += 1
    code, out = _award_diff(monkeypatch, capsys, rises, "ssb")
    assert code == 1
    assert "PAINE" in out and "experience" in out


def test_a_single_class_member_short_of_the_prime_bonus_gets_the_base_share():
    weak = _Member("X", 2, (15, 10, 10, 10, 10, 10), 0)
    assert proof.opening_award(weak, 6) == 2500

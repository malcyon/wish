"""Where C64 Curse and Silver Blades keep a paladin's cure-disease uses.

Read off the player's own overlays at run time by `tools/c64/curedisease.py`;
each title skips cleanly without its disks. No game bytes are fixtures here.
"""

from __future__ import annotations

import pytest

from goldbox import effects
from tools.c64 import curedisease

#: What the instruction read settles, one row a title.
EXPECTED = {
    "curse-of-the-azure-bonds": {
        "seed": 0x2550,
        "seed_callers": (0x0C1A, 0x1C5F, 0x20BF, 0x23DE),
        "full_count": 0x87EF,
        "gate": 0x46AB,
        "cure_decrement": 0x870F,
        "cure_guard": "uses were full",
        "lay_decrement": 0x873D,
        "expiry_dispatch": 0x14A9,
        "expiry_ids": 0x9953,
        "expiry_magnitude_gate": 0x14DB,
        # (effect id, duration, magnitude, add routine, reset at expiry)
        "cure": (141, 0xC7, 0xC7, 0x8156, 0x85BA),
        "lay": (140, 0xC1, 0xC1, 0x8156, 0x85B3),
        "writes": (("ECL65", 0x85B5, "STA", 0x13),
                   ("ECL65", 0x85BD, "STY", 0x12),
                   ("ECL65", 0x870F, "DEC", 0x12),
                   ("ECL65", 0x873D, "DEC", 0x13),
                   ("GEN", 0x2557, "STY", 0x13),
                   ("GEN", 0x2564, "STY", 0x12),
                   ("GEN", 0x2568, "STA", 0x12),
                   ("GEN", 0x256B, "STA", 0x13)),
    },
    "secret-of-the-silver-blades": {
        "seed": 0x0C69,
        "seed_callers": (0x0BEE, 0x156B, 0x1FC6, 0x212A),
        "full_count": 0x884E,
        "gate": 0x4383,
        "cure_decrement": 0x874B,
        "cure_guard": "no timer running",
        "lay_decrement": 0x8779,
        "expiry_dispatch": 0x12E2,
        "expiry_ids": 0x9496,
        "expiry_magnitude_gate": 0x1314,
        "cure": (110, 0xC7, 0xC7, 0x8156, 0x8657),
        "lay": (109, 0xC1, 0xC1, 0x8156, 0x8650),
        "writes": (("ECL65", 0x8652, "STA", 0x13),
                   ("ECL65", 0x865A, "STY", 0x12),
                   ("ECL65", 0x874B, "DEC", 0x12),
                   ("ECL65", 0x8779, "DEC", 0x13),
                   ("GEN", 0x0C70, "STY", 0x13),
                   ("GEN", 0x0C7D, "STY", 0x12),
                   ("GEN", 0x0C81, "STA", 0x12),
                   ("GEN", 0x0C84, "STA", 0x13)),
    },
}


def _finding(key: str) -> dict:
    try:
        return curedisease.inspect_title(key)
    except SystemExit as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_uses_live_in_record_bytes_0x012_and_0x013(key):
    """Every write to either byte is the seed, a use, or the expiry reset.

    No other routine in `GEN`, `LIBRARY`, `ECL65` or `CAMP` stores to them,
    so nothing else can put a use back.
    """
    finding = _finding(key)
    want = EXPECTED[key]
    assert (finding["counter"], finding["lay_on_hands"]) == (0x012, 0x013)
    assert finding["writes"] == want["writes"]
    for name in ("seed", "seed_callers", "full_count", "cure_decrement",
                 "lay_decrement"):
        assert finding[name] == want[name], name


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_seed_and_the_reset_count_one_two_or_three_by_level(key):
    """1 below paladin level 6, 2 below 11, 3 from 11 up; 0 for no paladin."""
    finding = _finding(key)
    assert finding["thresholds"] == (6, 11)
    assert [curedisease.full_count(level, finding["thresholds"])
            for level in (0, 1, 5, 6, 10, 11, 15)] == [0, 1, 1, 2, 2, 3, 3]


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_sheet_hides_cure_at_zero_and_heal_at_zero(key):
    finding = _finding(key)
    assert finding["gate"] == EXPECTED[key]["gate"]
    assert finding["menu"] == ("ITEMS", "SPELLS", "TRADE", "DROP", "CURE",
                               "HEAL", "EXIT")
    assert finding["gated"] == ("CURE", "HEAL")


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_a_use_starts_a_timer_row_whose_expiry_resets_the_count(key):
    """The spent state is an effect-array row, not memory the save drops."""
    finding = _finding(key)
    want = EXPECTED[key]
    for label, timer in (("cure", finding["cure_timer"]),
                         ("lay", finding["lay_timer"])):
        assert (timer.effect_id, timer.duration, timer.magnitude, timer.add,
                timer.reset) == want[label], label
        # Bit 7 of the magnitude is what lets the camp run the handler.
        assert timer.magnitude & 0x80
        assert finding["expiry_handlers"][timer.effect_id] == timer.reset
    assert finding["cure_guard"] == want["cure_guard"]
    for name in ("expiry_dispatch", "expiry_ids", "expiry_magnitude_gate"):
        assert finding[name] == want[name], name


def test_pool_of_radiance_has_no_paladin_to_keep_uses_for():
    try:
        finding = curedisease.pool()
    except SystemExit as exc:
        pytest.skip(str(exc))
    assert finding["files"] > 0
    assert finding["naming_paladin"] == ()
    assert finding["menu_has_cure"] is False


# --- the DOS side the conversion reads from -------------------------------

#: Every instruction in each DOS `GAME.OVR` that names the uses byte, read by
#: `curedisease.dos_inspect`: the refresh, the seeds of 1, the gate's
#: compare, and the cure's guarded decrement.  Nothing in the loader image.
DOS_EXPECTED = {
    "curse": {
        "counter": 0x191, "effect_id": 141, "handler": 0x127D6,
        "uses": ((0x12810, "mov"), (0x20DE5, "mov"), (0x2A6F1, "cmp"),
                 (0x2A959, "cmp"), (0x2A964, "dec")),
    },
    "silver-blades": {
        "counter": 0x6D, "effect_id": 110, "handler": 0x1444F,
        "uses": ((0x14496, "mov"), (0x1E38C, "mov"), (0x256E9, "mov"),
                 (0x25810, "mov"), (0x2AEDF, "cmp"), (0x2B160, "cmp"),
                 (0x2B16A, "dec")),
    },
}


def _dos_finding(title: str) -> dict:
    try:
        return curedisease.dos_inspect(title)
    except (FileNotFoundError, SystemExit) as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("title", sorted(DOS_EXPECTED))
def test_dos_spends_a_use_and_starts_a_node_only_when_he_has_none(title):
    """A DOS cure takes one use (never below 0) and adds the seven-day node
    only when he carries none; the node's removal writes the full count.

    So a DOS paladin's uses are only ever the creation seed of 1, one less
    after each cure, or the full count at a node's end -- training never
    touches them.
    """
    finding = _dos_finding(title)
    want = DOS_EXPECTED[title]
    assert finding["counter"] == want["counter"]
    assert (finding["effect_id"], finding["minutes"], finding["value"],
            finding["flag"]) == (want["effect_id"], 10080, 0, 1)
    assert finding["decrement_guarded"]
    assert finding["node_only_if_absent"]
    assert finding["handler"] == ("GAME.OVR", want["handler"])
    assert finding["handler_refreshes"]
    assert tuple((at, text.split()[0]) for where, at, text
                 in finding["uses"]) == want["uses"]
    assert all(where == "GAME.OVR" for where, _, _ in finding["uses"])


def test_dos_and_the_c64_refill_to_the_same_count_through_level_15():
    assert [curedisease.dos_full_count(level) for level in range(1, 16)] == \
        [curedisease.full_count(level) for level in range(1, 16)]
    assert curedisease.dos_full_count(16) == 4
    assert curedisease.full_count(16) == 3


# --- what the C64 writer must write ---------------------------------------

CURSE = "curse-of-the-azure-bonds"
SILVER = "secret-of-the-silver-blades"

#: The camp clock the staged saves held, 03:42, and the byte a DOS node
#: with 4000 minutes left becomes there: `$C3` has 4098 minutes left.
CLOCK = 222
NODE = 4000

#: (title, paladin level, DOS uses, DOS node minutes) -> record `0x012` and
#: the rows `(id, duration, magnitude)` a writer must produce.  Each Curse
#: row is a state driven in the running game, `tools/c64/curedrive.py`;
#: `docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md` has what the
#: game did with it, including Donald's decision on the one state (1 left,
#: no node) no C64 Curse state reproduces exactly.
WRITER_CASES = {
    (CURSE, 11, 3, None): (3, ()),
    (CURSE, 6, 2, None): (2, ()),
    (CURSE, 11, 3, NODE): (3, ((141, 0xC3, 0xC7),)),
    (CURSE, 11, 1, NODE): (1, ((141, 0xC3, 0xC7),)),
    (CURSE, 6, 1, NODE): (1, ((141, 0xC3, 0xC7),)),
    (CURSE, 11, 0, NODE): (0, ((141, 0xC3, 0xC7),)),
    (CURSE, 6, 0, NODE): (0, ((141, 0xC3, 0xC7),)),
    (CURSE, 11, 0, None): (0, ()),
    (CURSE, 6, 0, None): (0, ()),
    # Donald's decision (#600): rather than refuse this state,
    # `c64_cure_write` writes an adjustment row -- id 141, duration and
    # magnitude both the byte the cure itself writes -- rather than the
    # state's own recovery time, which no C64 Curse state holds exactly
    # (`test_no_c64_curse_state_gives_one_use_of_three_its_dos_recovery`).
    (CURSE, 11, 1, None): (1, ((141, 0xC7, 0xC7),)),
    (CURSE, 11, 2, None): (2, ((141, 0xC7, 0xC7),)),
    (CURSE, 6, 1, None): (1, ((141, 0xC7, 0xC7),)),
    (CURSE, 5, 1, None): (1, ()),
    (CURSE, 0, 0, None): (0, ()),
    (SILVER, 11, 1, None): (1, ()),
    (SILVER, 6, 1, None): (1, ()),
    (SILVER, 11, 1, NODE): (1, ((110, 0xC3, 0xC7),)),
    (SILVER, 11, 0, NODE): (0, ((110, 0xC3, 0xC7),)),
    (SILVER, 11, 3, None): (3, ()),
}


def _case_id(case) -> str:
    title, level, cures, minutes = case
    return (f"{'curse' if title == CURSE else 'silver'}-level{level}-"
            f"{cures}uses-{'node' if minutes else 'nonode'}")


@pytest.mark.parametrize("case", sorted(WRITER_CASES, key=str), ids=_case_id)
def test_the_uses_byte_is_the_dos_uses_and_a_node_is_a_row(case):
    """Never a refill: `0x012` is what DOS holds, and a DOS node is a row."""
    title, level, cures, minutes = case
    want = WRITER_CASES[case]
    if want is None:
        with pytest.raises(curedisease.Unrepresentable):
            curedisease.c64_cure_write(title, level, cures, minutes, CLOCK)
        return
    got = curedisease.c64_cure_write(title, level, cures, minutes, CLOCK)
    assert (got.cures, got.rows) == want
    if minutes is not None:
        (_, byte, magnitude), = got.rows
        # Bit 7 is what makes the camp run the reset at expiry.
        assert magnitude & 0x80
        assert effects.remaining_minutes(byte, CLOCK) == 4098


def _curse_c64(cures: int, rows: list[int], level: int, cure_at: int,
               clock: int = CLOCK) -> tuple[int, int | None]:
    """C64 Curse after one cure at `cure_at`: uses left, and the minute the
    full count comes back (None for never).

    `rows` are the minutes left on his cure rows.  A cure from the full
    count adds a row that runs out at the seventh midnight (`$C7`); the
    first row to run out writes the full count (`ECL65 $85BA`).
    """
    rows = list(rows)
    if cures:
        if cures == curedisease.full_count(level):
            rows.append(cure_at + effects.remaining_minutes(
                0xC7, (clock + cure_at) % 1440))
        cures -= 1
    return cures, min(rows) if rows else None


def _dos(cures: int, node: int | None, cure_at: int) -> tuple[int, int | None]:
    """DOS after one cure at `cure_at`: uses left and the minute the node
    ends.  The node is added only when he has none (`GAME.OVR:0x2A97E`)."""
    if cures:
        cures -= 1
        if node is None:
            node = cure_at + 10080
    return cures, node


def _silver_c64(cures: int, rows: list[int], cure_at: int,
                clock: int = CLOCK) -> tuple[int, int | None]:
    """C64 Silver Blades after one cure: a row is added when he has none
    (`ECL65 $872E`-`$8733`), whatever his count -- DOS's own rule."""
    rows = list(rows)
    if cures:
        if not rows:
            rows.append(cure_at + effects.remaining_minutes(
                0xC7, (clock + cure_at) % 1440))
        cures -= 1
    return cures, min(rows) if rows else None


def test_c64_silver_blades_plays_back_one_use_of_three_as_written():
    """Silver Blades starts the timer on the absence of a row, as DOS does,
    so `0x012` = 1 and no row gives him DOS's one cure and DOS's recovery:
    seven days after he cures, to the C64's midnight."""
    write = curedisease.c64_cure_write(SILVER, 11, 1, None, CLOCK)
    assert (write.cures, write.rows) == (1, ())
    for cure_at in (0, 5 * 1440):
        cures, back = _silver_c64(write.cures, [], cure_at)
        dos_cures, dos_back = _dos(1, None, cure_at)
        assert cures == dos_cures == 0
        assert 0 <= dos_back - back < 1440


def test_no_c64_curse_state_gives_one_use_of_three_its_dos_recovery():
    """DOS paladin 11 with 1 use and no node: whenever he cures, his three
    come back seven days later.  C64 Curse cannot hold that.

    With no row his cure starts no timer, since he was not at 3; with a row
    the three come back when the row runs out, whenever he cured.  So for
    every row there is a cure time whose recovery is days away from DOS's.
    """
    for cure_at in (0, 5 * 1440):
        assert _dos(1, None, cure_at) == (0, cure_at + 10080)
        assert _curse_c64(1, [], 11, cure_at) == (0, None)
    for left in range(1, 64 * 1440):
        worst = max(abs(_curse_c64(1, [left], 11, cure_at)[1]
                        - _dos(1, None, cure_at)[1])
                    for cure_at in (0, 5 * 1440))
        assert worst >= 2 * 1440


def test_the_written_c64_state_plays_back_a_dos_node():
    """DOS 1 use and a node with 4000 minutes left, against the written
    `0x012` = 1 and a `$C3` row: the cure leaves 0, and the three come back
    when the row runs out -- at 4098 minutes, the nearest the C64's day unit
    gets to 4000 -- whenever he cured."""
    write = curedisease.c64_cure_write(CURSE, 11, 1, NODE, CLOCK)
    (_, byte, _), = write.rows
    left = effects.remaining_minutes(byte, CLOCK)
    for cure_at in (0, 1000, 3000):
        assert _curse_c64(write.cures, [left], 11, cure_at) == (0, 4098)
        assert _dos(1, NODE, cure_at) == (0, NODE)


def test_a_full_c64_curse_paladin_recovers_seven_midnights_after_a_cure():
    """From the full count with no timer, both engines start one at the
    cure: DOS for exactly 10080 minutes, C64 Curse until the seventh
    midnight, which is what the game did in the driven run (cure at 03:43,
    three back at 00:00 seven days on)."""
    assert _curse_c64(3, [], 11, 0, clock=223) == (2, 10080 - 223)
    assert _dos(3, None, 0) == (2, 10080)


def test_the_game_writes_the_cure_row_the_writer_is_asked_for():
    """The one save the C64 game wrote after a cure: PALADIN, level 6, in
    save slot 0, cured once from 2 at 03:43.  His `0x012` is 1 and his row is
    id 141, owner 0 -- the save slot, not his place on the panel (sixth) --
    duration and magnitude `$C7`: the row `WRITER_CASES` asks a writer for,
    in the game's own hand."""
    import gamedata

    from goldbox.d64 import D64
    from goldbox.savegame import load_save
    root = gamedata.specimen_root()
    path = None if root is None else (
        root / "coab-c64" / "WISH-SPEC-curse-600-paladin6-cured.D64")
    if path is None or not path.is_file():
        pytest.skip("needs the specimen WISH-SPEC-curse-600-paladin6-cured")
    _, save, _ = load_save(D64.from_bytes(path.read_bytes()))
    payload = save.to_bytes()
    paladin = next(slot for slot in save.characters
                   if slot.record.name == "PALADIN")
    assert paladin.index == 0
    assert (paladin.record.level_paladin, paladin.record.paladin_cures) == (6, 1)
    rows = [(payload[i], payload[0x040 + i], payload[0x080 + i],
             payload[0x280 + i]) for i in range(0x40) if payload[i]]
    assert rows == [(141, 0, 0xC7, 0xC7)]
    assert list(payload[0xC6:0xCA]) == [0, 3, 4, 3]


# --- the converter itself, once its C64 writer writes these bytes ----------

def _dos_paladin_party(tmp_path, level: int, cures: int,
                       minutes: int | None, heal_minutes: int | None = None):
    """A copy of the DOS Curse party `curse-551` with its paladin staged.

    Inputs only, into the copy: paladin level `0x10C`, uses `0x191`, a cure
    node (141, `minutes`, value 0, flag 1) appended to his `.FX`, and, when
    `heal_minutes` is given, a lay-on-hands node (140, `heal_minutes`, value
    0, flag 1) beside it.
    """
    import shutil

    import gamedata

    from goldbox import dos_codec
    root = gamedata.specimen_root()
    where = None if root is None else (
        root / "coab-dos" / "WISH-SPEC-curse-551-party-as-converted")
    if where is None or not where.is_dir():
        pytest.skip("needs the specimen WISH-SPEC-curse-551-party-as-converted")
    party = tmp_path / "party"
    shutil.copytree(where, party)
    for f in party.iterdir():
        f.chmod(0o644)
    sav = party / "CHRDATA6.SAV"
    raw = bytearray(sav.read_bytes())
    assert raw[1:8] == b"PALADIN"
    raw[0x10C], raw[0x191] = level, cures
    sav.write_bytes(bytes(raw))
    if minutes is not None:
        fx = party / "CHRDATA6.FX"
        fx.write_bytes(fx.read_bytes() + bytes(
            (141, minutes & 0xFF, minutes >> 8, 0, 1))
            + dos_codec.EFFECT_NEXT_NULL)
    if heal_minutes is not None:
        fx = party / "CHRDATA6.FX"
        fx.write_bytes(fx.read_bytes() + bytes(
            (140, heal_minutes & 0xFF, heal_minutes >> 8, 0, 1))
            + dos_codec.EFFECT_NEXT_NULL)
    return party


@pytest.mark.parametrize("case", [
    pytest.param(c, id=_case_id(c))
    for c in sorted((c for c in WRITER_CASES if c[0] == CURSE and c[1] > 0),
                    key=str)])
def test_a_converted_dos_curse_paladin_gets_the_cure_state_above(
        tmp_path, case):
    """DOS Curse -> C64 Curse through `dos_codec.convert_save`: record
    `0x012` and the paladin's rows are exactly `WRITER_CASES`, and the row's
    owner is his own save slot (the driven cure wrote owner 0 for PALADIN
    in slot 0, sixth on the panel)."""
    from goldbox import c64_port, c64_save, dos_codec
    _, level, cures, minutes = case
    want = WRITER_CASES[case]
    container = c64_save.CURSE_OF_THE_AZURE_BONDS
    save0 = bytearray(container.payload_size)
    dos_codec.convert_save(_dos_paladin_party(tmp_path, level, cures, minutes),
                           "A", save0, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    slot = next(i for i in range(8)
                if save0[container.slot(i):container.slot(i) + 8]
                == b"PALADIN\0")
    rows = tuple((save0[i], save0[0x080 + i], save0[0x280 + i])
                 for i in range(0x40)
                 if save0[i] in (140, 141) and save0[0x040 + i] == slot)
    assert list(save0[0xC6:0xCA]) == [0, 2, 4, 3]     # 03:42, as CLOCK says
    assert (save0[container.slot(slot) + 0x012], rows) == want


#: The duration byte `closest_duration(1000, 222)` gives at the party's own
#: camp clock, 03:42 -- computed once and written as a literal.
_HEAL_1000_DURATION = 0x91


@pytest.mark.parametrize("heal_minutes", [None, 1000], ids=["nonode", "node"])
def test_a_converted_dos_curse_paladin_gets_the_lay_on_hands_state_above(
        tmp_path, heal_minutes):
    """DOS Curse -> C64 Curse through `dos_codec.convert_save`: no lay-on-
    hands node gives `0x013` = 1 and no row; a node gives `0x013` = 0 and a
    row owned by his own save slot."""
    from goldbox import c64_port, c64_save, dos_codec
    container = c64_save.CURSE_OF_THE_AZURE_BONDS
    save0 = bytearray(container.payload_size)
    dos_codec.convert_save(
        _dos_paladin_party(tmp_path, 11, 3, None, heal_minutes),
        "A", save0, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    slot = next(i for i in range(8)
                if save0[container.slot(i):container.slot(i) + 8]
                == b"PALADIN\0")
    rows = tuple((save0[i], save0[0x040 + i], save0[0x080 + i],
                 save0[0x280 + i]) for i in range(0x40) if save0[i] == 140)
    heal_byte = save0[container.slot(slot) + 0x013]
    if heal_minutes is None:
        assert (heal_byte, rows) == (1, ())
    else:
        assert (heal_byte, rows) == (0, ((140, slot, _HEAL_1000_DURATION,
                                         0xC1),))

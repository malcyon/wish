"""`tools/records/traitnames.py`'s own headline numbers, re-derived off Curse of the
Azure Bonds' disks.

`#561 (A Curse of the Azure Bonds character's traits are named from Pool of
Radiance's table, which disagrees with Curse's own data about eight codes)`
is the ticket the tool's commit answered, and nothing imported the tool
before this file. Modeled on `tests/secret_of_the_silver_blades/test_ssbtraitnames.py`'s pattern: re-run
the tool's own grouping and counting logic against the player's real disks,
so a base offset that slips or a grouped/ungrouped classification that breaks
turns a test red rather than only a printed number nobody checks.

Everything here skips cleanly with no Curse of the Azure Bonds disks on the
machine.
"""

from __future__ import annotations

import pytest

from automap import gamedisks
from goldbox import c64_port
from tools.records import traitnames

CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS


def _root():
    root = gamedisks.find(CURSE.key)
    if root is None:
        pytest.skip("no Curse of the Azure Bonds disks on this machine")
    return str(root)


# --- the spell audit ---------------------------------------------------------


def test_the_spell_effect_table_is_where_this_title_keeps_it():
    """`COMBAT2 +2732`, nine bytes a record, one per spell id 1-100 -- the
    base `tools/c64/traitquery.py`'s `SPELL_EFFECTS` names for this title."""
    from tools.c64 import traitquery
    table = traitquery.spell_effects(_root(), CURSE)
    assert len(table) == 100
    name, effect, message = table[1]
    assert name == "BLESS"
    assert effect == 1
    assert message == "IS BLESSED"


def test_the_spell_audit_reports_47_codes_43_grouped():
    """The tool's own headline count off `spell_rows`: 47 codes are written
    by at least one of Curse's own spells, 43 of them by a row that sits in
    a spell group and 4 only by a row that is in none."""
    rows = traitnames.spell_rows(_root(), CURSE)
    assert len(rows) == 47
    grouped = sum(1 for here in rows.values() if any(g for *_x, g, _m in here))
    assert grouped == 43
    assert len(rows) - grouped == 4


def test_two_codes_the_spell_audit_names_from_this_titles_own_spells():
    """68 is FEEBLEMIND and 63 is Minor Globe of Invulnerability -- two of
    the codes `goldbox/traits.py`'s `NAMES_CURSE` replaced Pool of
    Radiance's wrong name for, pinned against the spell that actually writes
    them rather than trusted from the table."""
    rows = traitnames.spell_rows(_root(), CURSE)
    assert {name for _s, name, _g, _m in rows[68]} == {"FEEBLEMIND"}
    assert {name for _s, name, _g, _m in rows[63]} == {
        "MINOR GLOBE OF INVULNERABLITY"}


# --- the monster census ------------------------------------------------------


def test_the_monster_census_reports_70_templates_52_codes():
    """The tool's own headline count off `monster_blocks`: 70 `MON*`
    templates ship on Curse's sides and carry 52 distinct codes between
    them."""
    blocks = traitnames.monster_blocks(CURSE.key, _root())
    assert len(blocks) == 70
    carriers = traitnames.carriers_of(CURSE.key, _root())
    assert len(carriers) == 52


def test_a_curse_only_code_the_monster_census_carries():
    """128 is above Pool of Radiance's namespace and unnamed in `NAMES`; the
    census still reports a creature carrying it, which is what let
    `NAMES_CURSE` leave it out rather than mis-naming it."""
    carriers = traitnames.carriers_of(CURSE.key, _root())
    assert 128 in carriers
    assert carriers[128]


# --- a bad disk is reported, not silently skipped ---------------------------


def test_monster_blocks_reports_a_disk_it_cannot_read(tmp_path, capsys):
    """`monster_blocks` used to swallow a bad `.d64` or a bad directory
    entry with a bare `except Exception: continue` -- a census tool whose
    whole point is a complete count over every `MON*` template must say what
    it skipped, matching `tools/c64/traitcross.py`'s pattern."""
    bad = tmp_path / "BAD.D64"
    bad.write_bytes(b"not a disk image")
    traitnames.monster_blocks(CURSE.key, str(tmp_path))
    out = capsys.readouterr().out
    assert "skipped" in out
    assert "BAD.D64" in out

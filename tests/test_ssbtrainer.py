from __future__ import annotations

"""Secret of the Silver Blades' training hall, watched in the running game.

`#89 (Silver Blades' trainer grants spells from a table, and
goldbox/levelup.py offers them from a menu)`. Every table this title's
trainer reads was already in `goldbox/levels.py` and `goldbox/spells.py`,
read out of `GEN` and `ECL65` by `tools/ssbtrainerinputs.py` and
`tools/c64/trainerspells.py`. What had never happened was the other half:
putting a party in front of the hall, pressing `TRAIN CHARACTER`, and asking
whether `goldbox.levelup.plan` writes what the engine wrote.

**Fourteen presses over two boots, 2026-09-16**, on SSI's own shipped party
off `SILVER-6.D64`, covering all four classes this title's trainer has a
spell step for -- the cleric at both sides of its Wisdom gate, the magic-user
at four intelligences over four levels, the paladin at two levels and the
ranger at three. All fourteen reproduced: **196 of 196 derived fields, 70 of
70 saving-throw columns and 224 of 224 spellbook bytes**
(`tools/ssbtrain.py diff`). The two specimens below are four of those
presses made again in one sitting so the pair could be registered and
replayed here.

* `WISH-SPEC-ssb-89-train-input` -- the shipped party with four characters
  one press short of a level, written by the game's own `SAVE CURRENT GAME`.
* `WISH-SPEC-ssb-89-trained-party` -- the same disk after one press each on
  DOMINIC (cleric), MORGAINE (magic-user, picking id 13), GUY DE VALOIS
  (paladin) and PAINE (ranger).

**The spellbook is the point of this file.** `Plan.spellbook` is a separate
attribute from `Plan.fields`, so every replay this project had written --
`tests/test_cursetrainer.py` included -- compared the fields and never the
sixteen bytes at `0x078`. That is the half `#89` is about, and it is checked
here in both directions: the mask the engine wrote, and the menu it built to
let a player write part of it.

Every test skips when the specimens are absent, and none of the game's bytes
is committed: `AGENTS.md` forbids that, test fixture or not.
"""

import dataclasses

import pytest

from goldbox import levels, levelup, spells
from goldbox.savegame import load_save
from tests import gamedata

SSB = levels.SECRET_OF_THE_SILVER_BLADES


def _specimen_disk(name: str):
    """One C64 `.D64` specimen, checked against its own recorded hash.

    `tests/gamedata.specimen` looks for a *directory* under `por-<platform>`,
    which is the DOS layout; a C64 specimen is one file and this title's live
    under `ssb-c64`, so the search is a glob the way `tools/ssbtrainerinputs.
    specimen_party` does it.
    """
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted(root.rglob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs specimen WISH-SPEC-{name}")
    path = found[0]
    recorded = specimens.read_provenance(
        path.with_suffix(".provenance.toml")).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail(f"WISH-SPEC-{name}: {path.name} has changed since it was "
                    f"recorded; run tools/specimens.py check")
    return path


def _party(name: str) -> dict:
    """Every named record on one specimen, keyed by name."""
    from goldbox.d64 import D64

    disk = D64.open(str(_specimen_disk(name)))
    _game, saved, _roster = load_save(disk)
    out = {}
    for slot in saved.slots:
        if slot.record is None:
            continue
        who = str(slot.record.name).strip().upper()
        if who:
            out[who] = slot.record
    return out


def _slot(name: str, character: str):
    party = _party(name)
    if character not in party:
        pytest.skip(f"{character} is not on WISH-SPEC-{name}")
    return party[character]


#: Every field one press writes that is not the hit-die roll or anything it
#: feeds. `hp_rolled` and `hp_max` are excluded for the reason
#: `tests/test_cursetrainer.py` excludes them -- a roll leaves no trace in a
#: record -- and are checked separately below by handing the roll in.
_ORDER_INDEPENDENT_FIELDS = (
    "thac0_base", "save_paralysis", "save_petrification", "save_wands",
    "save_breath", "save_spell", "level", "attack_level", "attack_forms",
    "turn_power", "experience",
    "level_magic_user", "level_cleric", "level_thief", "level_fighter",
    "level_paladin", "level_ranger")

#: Who was pressed, which class the press raised, and the spell id the
#: magic-user picked off the menu -- `$2ACE` read it back as 13 both times.
_PRESSES = (
    ("DOMINIC", "cleric", 10, 11, None),
    ("MORGAINE", "magic-user", 13, 14, 13),
    ("GUY DE VALOIS", "paladin", 11, 12, None),
    ("PAINE", "ranger", 12, 13, None),
)


@pytest.fixture
def measured(monkeypatch):
    """Reach past `TRAINER_MEASURED` for one test.

    Kept even though this title is now in the set, because these tests are
    what earns the entry: with the key removed they must still be the
    measurement and not become a tautology. Remove the monkeypatch and they
    pass unchanged; remove the key from `goldbox/levels.py` and they still
    pass, which is the point.
    """
    monkeypatch.setattr(levels, "TRAINER_MEASURED",
                        frozenset(set(levels.TRAINER_MEASURED) | {SSB.key}))


@pytest.mark.parametrize("character,class_name,from_level,to_level,learn",
                         _PRESSES)
def test_one_press_reproduces_through_plan(character, class_name, from_level,
                                           to_level, learn, measured):
    """The engine's own before and after, one class at a time.

    The die is handed in -- it is the one field nothing derives -- and every
    other field the press wrote comes back out of `plan`, **including the
    sixteen-byte spellbook**, which is what this ticket is about: the cleric's
    granted row behind its Wisdom gate, the paladin's borrowed cleric rows,
    the ranger's druid and magic-user rows, and the one bit the magic-user's
    player picked.
    """
    before = _slot("ssb-89-train-input", character)
    after = _slot("ssb-89-trained-party", character)
    assert levelup.ready_classes(before, SSB) == [class_name]
    assert levelup.class_level(before, class_name) == from_level
    assert levelup.class_level(after, class_name) == to_level

    rolled = (after.get("hp_rolled") or 0) - (before.get("hp_rolled") or 0)
    plan = levelup.plan(before, class_name, game=SSB, learn=learn,
                        rolled=rolled)
    trained = levelup.apply_to(before, plan)

    mismatches = {name: (trained.get(name), after.get(name))
                  for name in _ORDER_INDEPENDENT_FIELDS
                  if trained.get(name) != after.get(name)}
    assert not mismatches
    assert trained.get("hp_max") == after.get("hp_max")
    assert spells.spellbook_raw(trained)[:16] == \
        spells.spellbook_raw(after)[:16]


@pytest.mark.parametrize("character,class_name,from_level,to_level,learn",
                         _PRESSES)
def test_one_press_reproduces_through_plan_all(character, class_name,
                                               from_level, to_level, learn,
                                               measured):
    """The same four presses through `plan_all`, which is the walk
    `automap.actions.LevelUp.run` makes for a title with
    `trains_all_ready_classes` -- and this title has it set (`GEN $156F`
    walks class slots 7 down to 0).

    `plan_all` takes no roll, so it rolls its own die and `hp_rolled` and
    `hp_max` are left out. Everything else, spellbook included, is the same
    answer as `plan`'s.
    """
    del from_level, to_level
    before = _slot("ssb-89-train-input", character)
    after = _slot("ssb-89-trained-party", character)
    steps = levelup.plan_all(before, game=SSB, learn=learn)
    assert [p.class_name for p in steps] == [class_name]
    trained = before
    for step in steps:
        trained = levelup.apply_to(trained, step)
    mismatches = {name: (trained.get(name), after.get(name))
                  for name in _ORDER_INDEPENDENT_FIELDS
                  if trained.get(name) != after.get(name)}
    assert not mismatches
    assert spells.spellbook_raw(trained)[:16] == \
        spells.spellbook_raw(after)[:16]


def test_the_cleric_grant_is_the_only_thing_the_wisdom_gate_moves(measured):
    """`GEN $0F35 CPX #$0B / BCC / LDA $7C67 / CMP #$11 / BCS / LDX #$0A`.

    DOMINIC's press was cleric 10 to 11 at a permanent Wisdom of 18 and ids
    36 and 56 arrived. The same press was driven again with the permanent
    Wisdom poked to 16 and they did not -- thirteen bytes of the record moved
    instead of fifteen, and the two missing ones were `0x07C` and `0x07F`,
    the bytes those two ids live in. Everything else was identical, which is
    what makes this a gate on the grant and not on the raise.

    Here that differential is re-derived from the specimen by contradicting
    the table rather than the record: with `cleric_grant_wisdom` emptied the
    model stops distinguishing the two, and the ids arrive at any Wisdom.
    """
    before = _slot("ssb-89-train-input", "DOMINIC")
    assert levelup._permanent(before, 2, "wisdom") == 18
    at_18 = set(levelup._cleric_spell_ids(11, SSB, 18))
    at_16 = set(levelup._cleric_spell_ids(11, SSB, 16))
    assert at_18 - at_16 == {36, 56}

    table = spells.for_game(SSB)
    ungated = dataclasses.replace(table, cleric_grant_wisdom=())
    assert set(levelup._cleric_spell_ids(11, ungated, 16)) == at_18


#: What `$18EB STA $7A00,X` held when the menu was on screen, with `$18DA
#: STY $1C10` counting it -- read out of the running game at four magic-user
#: presses on 2026-09-16, and the answer this project has never had before.
#: The engine's own list, in the engine's own order.
_MENUS = {
    # (magic-user level trained to, permanent intelligence): the ids offered
    (11, 18): [13, 17, 20, 33, 46, 49, 53, 83, 84, 86, 87, 89, 91, 92, 93],
    (12, 18): [13, 17, 20, 33, 46, 49, 53, 83, 84, 86, 87, 89, 91, 92, 93,
               110, 111, 112, 113, 114],
    (12, 11): [13, 17, 20, 33, 46, 49, 53, 83, 84, 86, 87, 89, 91, 92, 93],
    (13, 18): [13, 17, 20, 33, 46, 49, 53, 83, 84, 86, 87, 89, 91, 92, 93,
               110, 111, 112, 113, 114],
    (14, 18): [13, 17, 20, 33, 46, 49, 53, 83, 84, 86, 87, 89, 91, 92, 93,
               110, 111, 112, 113, 114, 115, 116, 117],
    (14, 13): [13, 17, 20, 33, 46, 49, 53, 83, 84, 86, 87, 89, 91, 92, 93,
               110, 111, 112, 113, 114],
}


def _morgaine_at(intelligence: int):
    """MORGAINE's specimen record with a permanent intelligence written in.

    The trainer reads `0x066`, the **permanent** score (`$18AA LDA $7C66`),
    and not the one in force at `0x015`; both are written here so the sheet
    would agree with what the menu did, which is what the driven presses
    poked as well.
    """
    from goldbox.record import CharacterRecord

    record = _slot("ssb-89-train-input", "MORGAINE")
    body = bytearray(bytes(record))
    body[0x015] = body[0x066] = intelligence
    return CharacterRecord.from_bytes(bytes(body))


@pytest.mark.parametrize("to_level,intelligence", sorted(_MENUS))
def test_the_menu_silver_blades_built_is_the_one_learnable_lists(
        to_level, intelligence):
    """`levelup.learnable` against the ids the engine put at `$7A00`.

    Six presses, six lists, and the three things they settle:

    * **`menu_spell_level` is a table, not `(level + 1) // 2`.** The two
      agree at magic-user 12 and 14, which is why the first four presses
      could not tell them apart and two more were driven: at 11 the
      arithmetic gives 6 and the engine offered no sixth-level spell, and at
      13 the arithmetic gives 7 and the engine offered no seventh-level one.
      `test_the_arithmetic_disagrees_with_the_engine_at_eleven_and_thirteen`
      is that differential.
    * **`menu_intelligence` gates it**, on the permanent score. At 12 with an
      intelligence of 11 the sixth-level ids are gone; at 14 with 13 the
      seventh-level ones are.
    * **Id 109 is never offered.** `not_granted=(109,)`: 109 and 110 are both
      `DEATH SPELL`, and the sixth-level row's masks are ids 110-114, so a
      Silver Blades magic-user reaching 12 is offered five sixth-level spells
      and not six. It is absent from all four of these lists and 110-114 are
      in two of them.
    """
    record = _morgaine_at(intelligence)
    assert levelup.learnable(record, SSB, level=to_level) \
        == _MENUS[(to_level, intelligence)]
    assert 109 not in _MENUS[(to_level, intelligence)]


def test_the_arithmetic_disagrees_with_the_engine_at_eleven_and_thirteen():
    """The control for `menu_spell_level`, and the reason two more presses
    were driven after the first four.

    Pool of Radiance's `$2163` and Curse's `$2207` are the same two
    instructions, `LSR A / ADC #$00` -- `(level + 1) // 2`. Silver Blades
    reads a table at `$1926` instead, and the two agree at magic-user 12 and
    14 and disagree at 11, 13 and 15. So the four presses at 12 and 14 could
    not tell the rules apart, however clean they came out.

    With `menu_spell_level` emptied, `learnable` falls back to the
    arithmetic, and at 11 and 13 it then offers spell levels the engine did
    not: five ids at 11 and three more at 13. Both lists are the engine's own
    `$7A00`.
    """
    table = spells.for_game(SSB)
    arithmetic = dataclasses.replace(table, menu_spell_level=())
    at_11 = levelup.learnable(_morgaine_at(18), arithmetic, level=11)
    at_13 = levelup.learnable(_morgaine_at(18), arithmetic, level=13)
    assert set(at_11) - set(_MENUS[(11, 18)]) == {110, 111, 112, 113, 114}
    assert set(at_13) - set(_MENUS[(13, 18)]) == {115, 116, 117}


def test_emptying_menu_intelligence_stops_the_two_level_twelve_menus_differing():
    """The control for the test above, and the one that would have caught a
    gate that never fires.

    The two level-12 presses differ only in the permanent intelligence, so
    with `menu_intelligence` emptied they must stop differing -- and they do:
    both become the intelligence-18 list. A table that made no difference
    would pass the test above by accident.
    """
    table = spells.for_game(SSB)
    ungated = dataclasses.replace(table, menu_intelligence=())
    assert _MENUS[(12, 18)] != _MENUS[(12, 11)]
    at_18 = levelup.learnable(_morgaine_at(18), ungated, level=12)
    at_11 = levelup.learnable(_morgaine_at(11), ungated, level=12)
    assert at_18 == at_11 == _MENUS[(12, 18)]


def test_the_ranger_and_the_paladin_get_their_rows_at_the_press(measured):
    """Two classes Pool of Radiance does not have and nothing had watched.

    PAINE was ranger 12 and came out ranger 13 holding ids 9-21, 29-35 and
    {90, 96, 98} on top of the 77-80 he ships with. GUY DE VALOIS was
    paladin 11 and came out paladin 12 holding cleric ids 1-8 and 22-28 --
    `$1BEB`'s row index of `paladin level - 8` climbing a cleric level a
    level, where Curse's `$22F4` fixes it at 1 forever.
    """
    paine_before = _slot("ssb-89-train-input", "PAINE")
    paine_after = _slot("ssb-89-trained-party", "PAINE")
    gained = (set(spells.spells_known(bytes(paine_after), SSB))
              - set(spells.spells_known(bytes(paine_before), SSB)))
    assert gained == set(range(9, 22)) | set(range(29, 36)) | {90, 96, 98}
    assert set(spells.spells_known(bytes(paine_before), SSB)) == {77, 78, 79,
                                                                  80}

    guy_before = _slot("ssb-89-train-input", "GUY DE VALOIS")
    guy_after = _slot("ssb-89-trained-party", "GUY DE VALOIS")
    assert spells.spells_known(bytes(guy_before), SSB) == []
    assert set(spells.spells_known(bytes(guy_after), SSB)) \
        == set(range(1, 9)) | set(range(22, 29))


def test_offers_is_empty_when_the_ready_classes_have_no_magic_user(measured):
    """`automap.actions.LevelUp.offers`. GUY DE VALOIS is a paladin with the
    experience for another level, and a press that raises him has no spell
    menu to build -- the grant is a table and nothing is picked."""
    from automap import actions

    guy = _slot("ssb-89-train-input", "GUY DE VALOIS")
    assert levelup.ready_classes(guy, SSB) == ["paladin"]
    assert actions.LevelUp.offers(guy, SSB) == []


def test_offers_lists_spells_when_the_magic_user_is_ready(measured):
    """MORGAINE, and the list is the engine's own menu.

    `offers` branches on `LevelTables.trains_all_ready_classes`, which this
    title has set, so it asks `ready_classes` rather than `best_class` -- the
    `#415 (automap/window.py picks the level-up spell dialog's class the same
    wrong way plan would have, blocking Curse's trainer)` branch, taken here
    by construction rather than by a second fix.
    """
    from automap import actions

    morgaine = _slot("ssb-89-train-input", "MORGAINE")
    assert levelup.ready_classes(morgaine, SSB) == ["magic-user"]
    assert actions.LevelUp.offers(morgaine, SSB) == _MENUS[(14, 18)]


def test_level_up_blockers_is_empty_for_silver_blades():
    """What actually un-darkens the button. It refuses a title outside
    `levels.TRAINER_MEASURED` whatever tables it has, which is why this
    ticket needed a driven session rather than another table."""
    from automap import actions

    morgaine = _slot("ssb-89-train-input", "MORGAINE")
    assert actions.level_up_blockers(morgaine, SSB) == ()


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _heal_the_party(sg0, game) -> None:
    """Put every character's current hit points back to its own maximum.

    **`WISH-SPEC-ssb-89-train-input` needs this and its trained twin does
    not**, and the reason is how the input was staged rather than anything
    the game did. The twelve presses came first; the four characters were
    then restaged for the specimen by writing their **record** slots back,
    and the roster page -- which is where the game caches current hit points
    -- was left as those presses had made it. So MORGAINE's block says 40
    over a record whose maximum is 35, DOMINIC's 82 over 78, PAINE's 80 over
    74 and GUY DE VALOIS' 102 over 95, which are exactly the maxima the
    presses had given them. `automap.live.roster_page_plausible` refuses a
    page whose hit points exceed the record's maximum, by design (`#82`), so
    `read_party` answers None and this test never reaches the code it is
    about.

    Healing is an input we write and it is the only one; nothing below reads
    a hit point. The record slots, which are what every other test here
    compares, are untouched by it.
    """
    from automap import live
    from goldbox.savegame import SaveGame1

    page = sg0.to_bytes()[game.roster_offset:
                          game.roster_offset + game.roster_size]
    save1 = SaveGame1(bytes(page), game)
    for slot in sg0.characters:
        block = save1.roster(slot.index)
        if block.occupied:
            block.hit_points = slot.record.get("hp_max")
    healed = b"".join(b.raw for b in save1.roster_blocks)
    sg0.set_roster_page(healed.ljust(game.roster_size, b"\0"))
    assert live.roster_page_plausible(sg0, save1)


def test_the_level_up_button_asks_for_a_spell_through_the_window(app):
    """Driven through `automap.window.AutomapBinding._level_up`, not through
    `plan_all` or `LevelUp.offers` directly -- that is the layer `#89`'s own
    2026-09-08 comment said had never been re-verified for this title.

    MORGAINE is a single-class magic-user, so `class_for` names her class
    correctly and `#415`'s Curse failure cannot reproduce here; what this
    test proves is the simpler thing nobody had checked, that the button
    opens the menu at all and that the write goes through when a spell comes
    back from it.
    """
    from PyQt6.QtWidgets import QMainWindow

    from automap import actions, c64
    from automap.target import MemoryTarget
    from automap.window import AutomapBinding
    from goldbox.d64 import D64
    from wish.ui_window import Ui_WishWindow

    disk = D64.open(str(_specimen_disk("ssb-89-train-input")))
    game, sg0, _roster = load_save(disk)
    _heal_the_party(sg0, game)
    slot_index = None
    for slot in sg0.slots:
        if slot.record is not None \
                and str(slot.record.name).strip().upper() == "MORGAINE":
            slot_index = slot.index
            break
    if slot_index is None:
        pytest.skip("MORGAINE is not on WISH-SPEC-ssb-89-train-input")

    target = MemoryTarget({
        game.save_load_address: sg0.to_bytes(),
        c64.machine_for(game).mode_flag: bytes([1])})   # 1: not COMBAT

    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    window = AutomapBinding.__new__(AutomapBinding)
    window.state = type("S", (), {"title": game.title})()
    window.mapper = type("M", (), {"target": target})()
    seen = {}

    class Messages:
        def say(self, text, detail="", alarm=False):
            seen["said"] = text

    window.messages = Messages()
    window.ask = lambda question: True
    window._refresh_roster = lambda: seen.update(refreshed=True)
    picked = {}

    def fake_chosen_spell(record, name, game=None):
        offers = actions.LevelUp.offers(record, game)
        picked["offers"] = offers
        return offers[0] if offers else 0

    window._chosen_spell = fake_chosen_spell

    AutomapBinding._level_up(window, slot_index)
    assert picked["offers"] == _MENUS[(14, 18)]
    assert "picks one new spell" not in seen.get("said", "")
    assert "magic-user" in seen.get("said", "")


def test_silver_blades_is_now_in_trainer_measured():
    """The entry this file earns.

    Fourteen presses on 2026-09-16 -- the cleric at both sides of its Wisdom
    gate, the magic-user at four intelligences across four levels, the
    paladin at 8 and 11, the ranger at 8, 11 and 12 -- reproduced 196 of 196
    derived fields, 70 of 70 saving-throw columns and 224 of 224 spellbook
    bytes through `goldbox.levelup.plan`, and the four presses saved as
    `WISH-SPEC-ssb-89-train-input`/`WISH-SPEC-ssb-89-trained-party` are
    replayed above through `plan` and `plan_all` both. The `#415` gate needed
    no second fix: `offers` branches on `trains_all_ready_classes`, which
    this title has set.
    """
    assert SSB.key in levels.TRAINER_MEASURED
    assert levels.trainer_measured(SSB)

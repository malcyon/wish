"""Check the darkness maps hold identity rules for the A4 party's camp screens: ABAGAIL on line 5 and BINKY's items."""

import json
import pathlib

import pytest

from tools.amiga import screens
from tools.registry import scratch

MAP = pathlib.Path(__file__).resolve().parents[2] / 'tools' / 'amiga' / 'guards_darkness.json'
ROOT = scratch.cache_dir('acceptance')

# The boot that loaded the game-written slot G of the edited A4 party (BINKY's head item deleted,
# ABAGAIL given a cleric level) and drove camp steps view 5 and items 1, with these four identity
# states left out of its map; the reload of that slot G showed BINKY's sheet from the loaded menu.
CAPTURE = 'WISH-2/r9-l4-gcamp/b1/shots/'
# The passing accept run of the same route with the four rules in the map.
PROOF = 'WISH-2/r9-l4-gcamp/b2/shots/'
RELOAD = 'WISH-2/r9-l4-reload/b1/shots/'
ABAGAIL = f'{CAPTURE}17-camp_sheet_5.png'
NAME_LINE = [74, 46, 330, 62]
# Each entry: map, state, the rule's box, its example, the other kept crops of the A4 party's
# screen, and the same screen of other parties, which the new rule must not match.
RULES = {
    'abagail-sheet': ('identity', 'camp_sheet_5', NAME_LINE, ABAGAIL, (f'{PROOF}17-camp_sheet_5.png',),
                      ('WISH-2/wish2-a2-capture/sheets2/shots/36-camp_sheet_5.png',
                       'amiga-grab-crops/wish9-b1__31-camp_sheet_items_5.png')),
    'abagail-items-sheet': ('identity', 'camp_sheet_items_5', NAME_LINE, ABAGAIL,
                            (f'{PROOF}17-camp_sheet_5.png',),
                            ('amiga-grab-crops/wish9-b1__31-camp_sheet_items_5.png',
                             'WISH-354/w354-live3/live3/shots/17-camp_sheet_items_5.png')),
    'binky-items-sheet': ('identity', 'camp_sheet_items', NAME_LINE,
                          f'{CAPTURE}21-camp_sheet_items.png',
                          (f'{CAPTURE}23-camp_sheet_items.png', f'{RELOAD}06-sheet.png',
                           f'{PROOF}21-camp_sheet_items.png', f'{PROOF}23-camp_sheet_items.png'),
                          ('amiga-grab-crops/wish9-b1__12-camp_sheet_items.png',)),
    'binky-items': ('identity', 'camp_items', [150, 104, 676, 400], f'{CAPTURE}22-camp_items.png',
                    (f'{PROOF}22-camp_items.png',),
                    ('amiga-grab-crops/wish9-b1__13-camp_items.png',)),
}


def _spec():
    return json.loads(MAP.read_text())


def _own(name):
    kind, state, _box, example, _same, _other = RULES[name]
    return [rule for rule in screens.rules_of(_spec()[kind][state]) if rule['example'] == example]


def _matches(rule, crop):
    return screens.box_digests(crop, [tuple(rule['box'])], 'guard')[tuple(rule['box'])] == rule['sha256']


def _present(names):
    found = [ROOT / name for name in names if (ROOT / name).is_file()]
    if not found:
        pytest.skip('no kept crops of this screen')
    return found


@pytest.mark.parametrize('name', sorted(RULES))
def test_the_a4_party_has_one_alternative_beside_the_first_rule(name):
    kind, state, box, _example, _same, _other = RULES[name]
    own = _own(name)
    assert len(own) == 1
    assert own[0]['box'] == box
    assert len(screens.rules_of(_spec()[kind][state])) > 1


@pytest.mark.parametrize('name', sorted(RULES))
def test_the_example_is_labelled_with_its_state(name):
    _kind, state, _box, example, _same, _other = RULES[name]
    # The capture run did not pass, because it checked no identity on those screens, so its crops
    # carry labels rather than names a passing run would give them.
    assert state in _spec()['labels'].get(example, ()), example


@pytest.mark.parametrize('name', sorted(RULES))
def test_the_rule_matches_every_kept_crop_of_the_a4_partys_screen(name):
    _kind, _state, _box, example, same, _other = RULES[name]
    rule = _own(name)[0]
    for crop in _present((example, *same)):
        assert _matches(rule, crop), crop


@pytest.mark.parametrize('name', sorted(RULES))
def test_the_rule_matches_no_other_partys_screen(name):
    rule = _own(name)[0]
    for crop in _present(RULES[name][5]):
        assert not _matches(rule, crop), crop

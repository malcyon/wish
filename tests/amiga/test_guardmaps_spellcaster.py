"""Check the darkness maps hold rules for HILDE, a magic-user on party line 5, through the camp USE route."""

import json
import pathlib

import pytest

from tools.amiga import screens
from tools.registry import scratch

MAP = pathlib.Path(__file__).resolve().parents[2] / 'tools' / 'amiga' / 'guards_darkness.json'
ROOT = scratch.cache_dir('acceptance')

# The completed runs that used every spell in HILDE's case of 4 on the played disk (W4D) and her
# lone scroll on Wish's disk (LONE); list rows 1 and 2 stay as they were while row 3 changes and goes.
W4D = 'WISH-2/w4c/w4d/shots/'
LONE = 'WISH-354/w354-live3/live4c/shots/'
RUNS = (W4D, LONE)
RUN_SHEETS = (*(f'{W4D}{n}-camp_sheet_items_5.png' for n in (17, 40, 76, 151)),
              *(f'{LONE}{n}-camp_sheet_items_5.png' for n in (17, 50, 71)))
RUN_LISTS = (*(f'{W4D}{n}-camp_items_5.png' for n in (18, 49, 59, 77, 118, 152)),
             *(f'{LONE}{n}-camp_items_5.png' for n in (18, 41, 51, 72)))
# HILDE's sheet bar reads ITEMS SPELLS TRADE DROP EXIT, so the items-sheet guard cut from a
# member with no SPELLS button misses it; her name and her item list need identity rules too.
# Each entry: map, state, the rule's box, its example, the other kept crops of HILDE's screen,
# and the same screen of the member the first rule was cut from, which the new rule must not match.
RULES = {
    'guard-sheet': ('guards', 'camp_sheet_items_5', [58, 402, 160, 430],
                    'WISH-354/w354-live3/live3/shots/17-camp_sheet_items_5.png',
                    ('amiga-grab-crops/wish2-hilde__camp_sheet_items_5.png', *RUN_SHEETS),
                    ('amiga-grab-crops/wish9-b1__31-camp_sheet_items_5.png',)),
    'identity-sheet': ('identity', 'camp_sheet_items_5', [74, 46, 330, 62],
                       'WISH-354/w354-live3/live3/shots/17-camp_sheet_items_5.png',
                       ('amiga-grab-crops/wish2-hilde__camp_sheet_items_5.png', *RUN_SHEETS),
                       ('amiga-grab-crops/wish9-b1__31-camp_sheet_items_5.png',)),
    'identity-items': ('identity', 'camp_items_5', [150, 104, 676, 142],
                       'amiga-grab-crops/wish2-hilde__camp_items_5.png', RUN_LISTS,
                       ('amiga-grab-crops/wish9-b1__32-camp_items_5.png',)),
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
def test_hilde_has_one_alternative_beside_the_first_rule(name):
    kind, state, box, _example, _same, _other = RULES[name]
    own = _own(name)
    assert len(own) == 1
    assert own[0]['box'] == box
    assert len(screens.rules_of(_spec()[kind][state])) > 1


@pytest.mark.parametrize('name', sorted(RULES))
def test_every_kept_crop_of_hildes_screen_is_labelled_with_its_state(name):
    _kind, state, _box, example, same, _other = RULES[name]
    labels = _spec()['labels']
    # A completed run's crops are named after their state; the kept grabs and a stopped run's are labelled.
    for crop in (example, *same):
        if not crop.startswith(RUNS):
            assert state in labels.get(crop, ()), crop


@pytest.mark.parametrize('name', sorted(RULES))
def test_the_rule_matches_every_kept_crop_of_hildes_screen(name):
    _kind, _state, _box, example, same, _other = RULES[name]
    rule = _own(name)[0]
    for crop in _present((example, *same)):
        assert _matches(rule, crop), crop


@pytest.mark.parametrize('name', sorted(RULES))
def test_the_rule_matches_no_other_members_screen(name):
    rule = _own(name)[0]
    for crop in _present(RULES[name][5]):
        assert not _matches(rule, crop), crop

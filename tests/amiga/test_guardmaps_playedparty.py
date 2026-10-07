"""Check the darkness identity map holds rules for the TROND party as the played Amiga disk 3 shows it."""

import json
import pathlib

import pytest

from tools.amiga import screens
from tools.registry import scratch

MAP = pathlib.Path(__file__).resolve().parents[2] / 'tools' / 'amiga' / 'guards_darkness.json'
ROOT = scratch.cache_dir('acceptance')

# The played disk (Pools of Darkness3.adf, 6af0d0ac) draws five of its seven names in another
# colour than the party converted from DOS, so its loaded menu and first sheet need their own
# rules. Each rule's example, then the other kept crops of the same screen of this party.
PARTY = {
    'loaded_menu': ('WISH-2/l4-r6-control/control/shots/05-loaded_menu.png',
                    'WISH-2/l4g-b1/b1/shots/05-loaded_menu.png',
                    'WISH-2/l4g-b2/b2/shots/05-loaded_menu.png',
                    'WISH-2/l4g-b2/b2/shots/07-loaded_menu.png'),
    'sheet': ('WISH-2/l4g-b1/b1/shots/06-sheet.png',
              'WISH-2/l4g-b2/b2/shots/06-sheet.png'),
}
# The same screens of the party converted from DOS (A2), which must not match these rules.
OTHER = {
    'loaded_menu': ('WISH-2/wish2-a2/measure1/shots/05-loaded_menu.png',
                    '679/0fecb2ffdc-amiga-darkness-accept-A/acceptA/shots/05-loaded_menu.png',
                    'amiga-grab-crops/wish9-b1__05-loaded_menu.png'),
    'sheet': ('WISH-2/wish2-a2/measure2/shots/06-sheet.png',
              '679/0fecb2ffdc-amiga-darkness-accept-A/acceptA/shots/06-sheet.png',
              'amiga-grab-crops/wish9-b1__06-sheet.png'),
}
BOX = {'loaded_menu': [74, 94, 690, 192], 'sheet': [74, 46, 330, 62]}


def _spec():
    return json.loads(MAP.read_text())


def _own(state):
    example = PARTY[state][0]
    return [rule for rule in screens.rules_of(_spec()['identity'][state]) if rule['example'] == example]


def _matches(rule, crop):
    return screens.box_digests(crop, [tuple(rule['box'])], 'identity')[tuple(rule['box'])] == rule['sha256']


def _present(names):
    found = [ROOT / name for name in names if (ROOT / name).is_file()]
    if not found:
        pytest.skip('no kept crops of this party')
    return found


@pytest.mark.parametrize('state', sorted(PARTY))
def test_the_played_party_has_one_identity_alternative_with_the_states_box(state):
    own = _own(state)
    assert len(own) == 1
    assert own[0]['box'] == BOX[state]
    assert len(screens.rules_of(_spec()['identity'][state])) > 1


@pytest.mark.parametrize('state', sorted(PARTY))
def test_every_kept_crop_of_the_played_party_is_labelled_with_its_screen(state):
    labels = _spec()['labels']
    for name in PARTY[state]:
        assert labels.get(name) == [state], name


@pytest.mark.parametrize('state', sorted(PARTY))
def test_the_rule_matches_every_kept_crop_of_the_played_party(state):
    rule = _own(state)[0]
    for crop in _present(PARTY[state]):
        assert _matches(rule, crop), crop


@pytest.mark.parametrize('state', sorted(PARTY))
def test_the_rule_matches_no_other_partys_screen(state):
    rule = _own(state)[0]
    for crop in _present(OTHER[state]):
        assert not _matches(rule, crop), crop

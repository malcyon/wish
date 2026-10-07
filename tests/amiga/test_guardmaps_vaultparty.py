"""Check the darkness identity map holds the rules the vault accept route's party needs, against its kept crops."""

import json
import pathlib

import pytest

from tools.amiga import screens
from tools.registry import scratch

MAP = pathlib.Path(__file__).resolve().parents[2] / 'tools' / 'amiga' / 'guards_darkness.json'
ROOT = scratch.cache_dir('acceptance')

# The vault route checks an identity rule at two states, `sheet` and `loaded_menu`; the party's
# crops of each come from its measure and accept runs.
PARTY = {
    'sheet': ('WISH-6/wish6-accept2/wish6-accept2/shots/06-sheet.png',
              'WISH-6/wish6-l1/measure1/shots/06-sheet.png',
              'WISH-6/wish6-l1/measure2/shots/06-sheet.png',
              'WISH-317/wish317-vault/m1/shots/06-sheet.png'),
    'loaded_menu': ('WISH-6/wish6-accept2/wish6-accept2/shots/05-loaded_menu.png',
                    'WISH-6/wish6-l1/measure1/shots/05-loaded_menu.png',
                    'WISH-6/wish6-l1/measure1/shots/07-loaded_menu.png',
                    'WISH-317/wish317-vault/m1/shots/05-loaded_menu.png',
                    'WISH-317/wish317-vault/m1/shots/07-loaded_menu.png'),
}
# Sheets and menus of other parties kept in the same cache.
OTHER = {
    'sheet': ('WISH-2/wish2-a2/measure2/shots/06-sheet.png',
              'WISH-2/wish2-a3/measure-a3-8/shots/06-sheet.png',
              'WISH-2/wish2-a4/measure-a4-33/shots/06-sheet.png',
              '679/0fecb2ffdc-amiga-darkness-accept-A/acceptA/shots/06-sheet.png',
              'amiga-grab-crops/wish9-b1__06-sheet.png'),
    'loaded_menu': ('WISH-2/wish2-a2/measure1/shots/05-loaded_menu.png',
                    '679/0fecb2ffdc-amiga-darkness-accept-A/acceptA/shots/05-loaded_menu.png',
                    'amiga-grab-crops/wish9-b1__05-loaded_menu.png'),
}


def _rules(state):
    return screens.rules_of(json.loads(MAP.read_text())['identity'][state])


def _matches(rule, crop):
    return screens._box_digest(crop, rule['box'], 'identity') == rule['sha256']


def _present(names):
    found = [ROOT / name for name in names if (ROOT / name).is_file()]
    if not found:
        pytest.skip('no kept crops of this party')
    return found


@pytest.mark.parametrize('state', sorted(PARTY))
def test_a_rule_matches_every_crop_of_the_party(state):
    for crop in _present(PARTY[state]):
        assert any(_matches(rule, crop) for rule in _rules(state)), crop


def test_the_party_sheet_rule_matches_no_other_party():
    others = _present(OTHER['sheet'])
    party = _present(PARTY['sheet'])
    # The rules that match the party's sheet are its own; no other party's sheet may match one.
    own = [rule for rule in _rules('sheet') if any(_matches(rule, crop) for crop in party)]
    assert own
    for crop in others:
        assert not any(_matches(rule, crop) for rule in own), crop


def test_the_party_loaded_menu_rule_matches_no_other_party():
    others = _present(OTHER['loaded_menu'])
    party = _present(PARTY['loaded_menu'])
    own = [rule for rule in _rules('loaded_menu') if any(_matches(rule, crop) for crop in party)]
    assert own
    for crop in others:
        assert not any(_matches(rule, crop) for rule in own), crop

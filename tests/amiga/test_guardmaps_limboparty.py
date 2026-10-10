"""Check the exported darkness identity map recognises the Limbo party's HILDE on the sheet and item list of the camp item walk."""

import json
import pathlib

import pytest

from tools.amiga import guardmaps, screens
from tools.registry import scratch

MAP = pathlib.Path(__file__).resolve().parents[2] / 'tools' / 'amiga' / 'guards_darkness.json'
ROOT = scratch.cache_dir('acceptance')

MEASURE = 'WISH-2/guards-measure3/1/shots/'
SHEETS = (f'{MEASURE}41-camp_sheet_items_5.png', f'{MEASURE}49-camp_sheet_items_5.png',
          'WISH-2/guards-accept1/1/shots/43-camp_sheet_items_5.png')
LIST = f'{MEASURE}42-camp_items_5.png'
# The earlier HILDE (same name, lower level) and wish9-b1's member 5 are the screens the new rules must not match.
OTHERS = {
    'camp_sheet_items_5': ('amiga-grab-crops/wish2-hilde__camp_sheet_items_5.png',
                           'amiga-grab-crops/wish9-b1__31-camp_sheet_items_5.png'),
    'camp_items_5': ('amiga-grab-crops/wish2-hilde__camp_items_5.png',
                     'amiga-grab-crops/wish9-b1__32-camp_items_5.png'),
}
EXAMPLES = {'camp_sheet_items_5': SHEETS[0], 'camp_items_5': LIST}


def _present(*names):
    paths = [ROOT / name for name in names]
    if not all(path.is_file() for path in paths):
        pytest.skip('the kept crops of this party are not on this machine')
    return paths


def test_the_exported_identity_map_recognises_the_limbo_party_item_walk(tmp_path):
    sheets = _present(*SHEETS)
    (listing,) = _present(LIST)
    assert guardmaps.main(['export', '--title', 'darkness', '--out', str(tmp_path)]) == 0
    identity = screens.PixelGuards(tmp_path / 'identity.json')
    for crop in sheets:
        assert identity('camp_sheet_items_5', crop), crop
    assert identity('camp_items_5', listing)


@pytest.mark.parametrize('state', sorted(EXAMPLES))
def test_the_limbo_rules_match_no_other_party(state):
    others = _present(*OTHERS[state])
    rules = [rule for rule in screens.rules_of(json.loads(MAP.read_text())['identity'][state])
             if rule['example'] == EXAMPLES[state]]
    assert len(rules) == 1
    for crop in others:
        digest = screens.box_digests(crop, [tuple(rules[0]['box'])], 'guard')[tuple(rules[0]['box'])]
        assert digest != rules[0]['sha256'], crop

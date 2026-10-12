"""Check that the Pool guard and identity maps recognise the C64 party converted with its zombie companion, and no other party."""

import json
import pathlib

import pytest

from tools.amiga import guardmaps, screens
from tools.registry import scratch

MAP = pathlib.Path(__file__).resolve().parents[2] / 'tools' / 'amiga' / 'guards_pool.json'
ROOT = scratch.cache_dir('acceptance')

CAPTURE = 'WISH-303/s7-cap/cap1/shots/'
#: The world, the first member's sheet, and line 7's camp sheet and item list of the capture boot.
EXAMPLES = {
    ('identity', 'world'): f'{CAPTURE}045-world.png',
    ('identity', 'sheet'): f'{CAPTURE}046-sheet.png',
    ('identity', 'camp_sheet_items_7'): f'{CAPTURE}052-camp_sheet_items_7.png',
    ('identity', 'camp_items_7'): f'{CAPTURE}053-camp_items.png',
    ('guards', 'camp_sheet_items_7'): f'{CAPTURE}052-camp_sheet_items_7.png',
    ('guards', 'camp_items_7'): f'{CAPTURE}053-camp_items.png',
}
#: Other grabs of the same screens: the failed accept boot's world and the sheet after ITEMS.
AGAIN = {
    ('identity', 'world'): ('WISH-303/s7-a/1/shots/04-world.png', f'{CAPTURE}047-world.png'),
    ('identity', 'camp_sheet_items_7'): (f'{CAPTURE}055-camp_sheet_items_7_back.png',),
    ('guards', 'camp_sheet_items_7'): (f'{CAPTURE}055-camp_sheet_items_7_back.png',),
}
#: The parties whose rules were there before: their world, sheet and line-1 item screens.
OTHERS = {
    'world': ('679/5fcbfccc65-amiga-pool-accept2b/accept2b/shots/04-world.png',
              'amiga-grab-crops/wish16-a__04-world.png', '300/wish300-amiga-npc/accept1/shots/04-world.png',
              '301/wish301-amiga/accept2/shots/04-world.png', 'WISH-1/f3accept/accept1/shots/04-world.png'),
    'sheet': ('679/5fcbfccc65-amiga-pool-accept2b/accept2b/shots/05-sheet.png',
              'amiga-grab-crops/wish16-a__05-sheet.png', '300/wish300-amiga-npc2/accept1/shots/05-sheet.png',
              'amiga-grab-crops/wish303-a1__06-sheet_dead.png'),
    'camp_sheet_items_7': ('amiga-grab-crops/wish16-a__08-camp_sheet_items.png',),
    'camp_items_7': ('amiga-grab-crops/wish16-a__09-camp_items.png',),
}


def _present(*names):
    paths = [ROOT / name for name in names]
    if not all(path.is_file() for path in paths):
        pytest.skip('the kept crops of this party are not on this machine')
    return paths


@pytest.mark.parametrize('kind,state', sorted(EXAMPLES))
def test_the_exported_maps_recognise_the_converted_party(tmp_path, kind, state):
    crops = _present(EXAMPLES[kind, state], *AGAIN.get((kind, state), ()))
    assert guardmaps.main(['export', '--title', 'pool', '--out', str(tmp_path)]) == 0
    rules = screens.PixelGuards(tmp_path / f'{kind}.json')
    for crop in crops:
        assert rules(state, crop), crop


@pytest.mark.parametrize('state', sorted(OTHERS))
def test_the_converted_partys_identity_rules_match_no_other_party(state):
    others = _present(*OTHERS[state])
    example = EXAMPLES['identity', state]
    held = json.loads(MAP.read_text())['identity'].get(state)
    rules = [rule for rule in screens.rules_of(held or []) if rule['example'] == example]
    assert len(rules) == 1, state
    box = tuple(rules[0]['box'])
    for crop in others:
        assert screens.box_digests(crop, [box], 'guard')[box] != rules[0]['sha256'], crop


def test_the_pool_map_guards_every_strict_state_of_an_items_7_run():
    """A seven-member Pool run with `items 7` keys every strict state on a recognised screen; needs no crops."""
    from tools.amiga import route_camp
    from tools.amiga.route_pool import POOL_FORWARD

    spec = guardmaps._load(MAP.parent, 'pool')
    route = route_camp.camp_title(POOL_FORWARD, ('items 7',), 7, name='pool')
    assert {'camp_sheet_items_7', 'camp_items_7'} <= route.strict
    assert route.strict <= spec['guards'].keys()
    assert {'camp_sheet_items_7', 'camp_items_7'} <= spec['identity'].keys()

"""Place guards for the Pools of Darkness reload boots, against crops kept from live runs."""

import pathlib

import pytest

from tools.amiga import guardmaps, screens
from tools.registry import scratch

_PLACES = {
    'place_x4_y10_f1': 'WISH-2/wish2-a2-capture/strict1/shots/12-world.png',
    'place_x5_y10_f1': 'WISH-2/wish2-a2-capture/strict1/shots/13-world.png',
    'place_x11_y3_f2': 'WISH-2/wish2-a4/accept2/shots/12-world.png',
    'place_x11_y4_f2': 'WISH-2/wish2-a4/accept2/shots/13-world.png',
    'place_x4_y7_f1_w22_5': 'WISH-2/wish2-a3/accept3c/shots/12-world.png',
    'place_x4_y7_f0_w22_4': 'WISH-2/wish2-a3/accept3c/shots/13-world.png',
}
# A place the map already guarded, so a new rule is also tried against an old neighbour.
_OLD_NEIGHBOUR = 'WISH-2/wish2-s5/accept2/shots/13-world.png'


def _spec():
    return guardmaps._load(pathlib.Path(guardmaps.__file__).parent, 'darkness')


def _crops():
    root = scratch.cache_dir('acceptance')
    names = (*_PLACES.values(), _OLD_NEIGHBOUR)
    if not all((root / name).is_file() for name in names):
        pytest.skip('the kept Pools of Darkness reload crops are not on this machine')
    return root, names


def test_every_reload_place_has_a_guard_and_a_label_on_its_crop():
    spec = _spec()
    for state, crop in _PLACES.items():
        assert state in spec['guards'], state
        assert state in spec['labels'][crop], crop


@pytest.mark.parametrize('state', sorted(_PLACES))
def test_a_reload_place_guard_matches_its_crop_and_no_neighbouring_place(state):
    root, names = _crops()
    rule = _spec()['guards'][state]
    box = tuple(rule['box'])
    for name in names:
        digest = screens.box_digests(root / name, {box})[box]
        assert (digest == rule['sha256']) is (name == _PLACES[state]), (state, name)

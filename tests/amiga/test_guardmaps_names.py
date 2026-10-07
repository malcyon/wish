"""Checks how guardmaps reads a crop's name into the screen it shows."""

import json

import pytest

from tools.amiga import guardmaps


@pytest.mark.parametrize('stem, expected', [
    ('05-camp-after-1', ('camp',)),
    ('07-camp-after-12', ('camp',)),
    ('03-camp', ('camp',)),
    ('04-camp-again-2', ('camp',)),
    ('02-journal-1', ()),
    ('06-camp-after-restore', ('camp',)),
    ('08-camp-resumed', ('camp',)),
    ('09-post_write', ('loaded_menu',)),
])
def test_crop_name_maps_to_screen(tmp_path, stem, expected):
    (tmp_path / 'summary.json').write_text(json.dumps({'success': True}))
    shots = tmp_path / 'shots'
    shots.mkdir()
    assert guardmaps._states(shots / f'{stem}.png') == expected

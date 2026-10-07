"""A guard rule can require several boxes, so a screen drawn in stages matches only once it is whole."""

import json
import pathlib

import pytest
from PIL import Image

from tools.amiga import guardmaps, screens

TOP = [10, 10, 30, 20]
BAR = [10, 40, 30, 50]


def _screen(path, *, bar):
    """A crop whose top region is drawn first and whose bar region is drawn last."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (720, 568), 'black')
    for x in range(10, 30):
        for y in range(10, 20):
            image.putpixel((x, y), (255, 0, 0) if x % 2 else (0, 0, 255))
    if bar:
        for x in range(10, 30):
            for y in range(40, 50):
                image.putpixel((x, y), (0, 255, 0) if y % 2 else (255, 255, 0))
    image.save(path)
    return path


def _guards(tmp_path, partial, whole):
    rule = {**screens.guard_rule(partial, TOP), 'and': [screens.guard_rule(whole, BAR)]}
    path = tmp_path / 'guards.json'
    path.write_text(json.dumps({'sheet': rule}))
    return screens.PixelGuards(path)


def test_a_rule_with_and_matches_only_when_every_box_does(tmp_path):
    partial = _screen(tmp_path / 'partial.png', bar=False)
    whole = _screen(tmp_path / 'whole.png', bar=True)
    guards = _guards(tmp_path, partial, whole)
    assert guards('sheet', whole)
    assert not guards('sheet', partial)


def test_a_malformed_and_is_rejected(tmp_path):
    path = tmp_path / 'guards.json'
    rule = {**screens.guard_rule(_screen(tmp_path / 'a.png', bar=True), TOP), 'and': [{'box': BAR}]}
    path.write_text(json.dumps({'sheet': rule}))
    with pytest.raises(screens.RouteError):
        screens.PixelGuards(path)


def test_add_and_box_extends_a_rule_and_check_requires_both(tmp_path, capsys):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    run = root / '1' / 'run'
    run.mkdir(parents=True)
    (run / 'prepare.json').write_text(json.dumps({'title': 'pool'}))
    (run / 'accept').mkdir()
    (run / 'accept' / 'summary.json').write_text(json.dumps({'success': True, 'measure': False}))
    partial = _screen(run / 'accept' / 'shots' / '01-sheet.png', bar=False)
    whole = _screen(run / 'accept' / 'shots' / '02-sheet.png', bar=True)
    argv = ['--root', str(root), '--maps', str(maps)]
    assert guardmaps.main([*argv, 'add', '--title', 'pool', '--map', 'guards', '--state', 'sheet',
                           '--crop', str(whole), '--box', '10,10,30,20']) == 0
    assert guardmaps.main([*argv, 'add', '--title', 'pool', '--map', 'guards', '--state', 'sheet',
                           '--crop', str(whole), '--box', '10,40,30,50', '--and-box']) == 0
    held = json.loads((maps / 'guards_pool.json').read_text())['guards']['sheet']
    assert [part['box'] for part in held['and']] == [BAR]
    capsys.readouterr()
    # The half-drawn crop shows the top region but not the bar, so it is not the sheet.
    assert guardmaps.main([*argv, 'check', '--title', 'pool']) == 0
    out = capsys.readouterr().out
    assert 'guards/sheet [10, 10, 30, 20] hits 1 misses 1' in out
    assert partial.exists()
    # Without the bar, the same crop would have matched.
    held.pop('and')
    spec = json.loads((maps / 'guards_pool.json').read_text())
    spec['guards']['sheet'] = held
    (maps / 'guards_pool.json').write_text(json.dumps(spec))
    guardmaps.main([*argv, 'check', '--title', 'pool'])
    assert 'guards/sheet [10, 10, 30, 20] hits 2 misses 0' in capsys.readouterr().out


def test_the_committed_pool_sheet_waits_for_the_view_bar():
    spec = guardmaps._load(pathlib.Path(guardmaps.__file__).parent, 'pool')
    rule = spec['guards']['sheet']
    assert rule['box'] == [70, 146, 124, 240]
    assert [part['box'] for part in rule['and']] == [[60, 418, 128, 432]]

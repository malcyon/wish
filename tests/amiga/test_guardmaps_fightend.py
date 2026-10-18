"""Check the Pool end-of-fight guards and the Pools of Darkness fight guards against the quickfight captures they were cut from."""

import pathlib

import pytest

from tools.amiga import guardmaps, screens
from tools.registry import scratch

ROOT = scratch.cache_dir('acceptance')
MAPS = pathlib.Path(guardmaps.__file__).parent

#: The Pools of Darkness frames showing a member's command bar, with or without GUARD.
DARKNESS_BARS = frozenset(
    'f1b f1q f1p1 f1p2 f1p3 f1p4 f1p5 f1p6 f1e1 f1x1 f1x2 f1x5 f1x6 f1x8 f1x9 f1x10 '
    'f1x11 f1x12 f1y1 f1y2 f1y3 f1y4 a_f2turn b_f2turn'.split())

#: Each title's WinUAE capture of a whole fight, and for each new guard the frames that show its screen.
SHOWN = {
    'pool': ('WISH-359/m1-qf-pool', {
        'continue_battle': frozenset({'f1-h4', 'B-p3', 'B-p4', 'B-p5', 'B-p6'}),
        'party_won': frozenset({'f1-end', 'B-end'}),
        'treasure': frozenset({'f1-grid'}),
        'treasure_left': frozenset({'f1-x'}),
    }),
    'darkness': ('WISH-359/m1-qf-pod', {
        'combat_bar': DARKNESS_BARS,
        'continue_battle': frozenset({'f1z1'}),
        'party_won': frozenset({'f1end'}),
        'treasure': frozenset({'f1r1'}),
        'treasure_left': frozenset({'f1r2'}),
    }),
}


@pytest.mark.parametrize('title', sorted(SHOWN))
def test_the_committed_map_guards_every_fight_screen(title):
    """Each screen a fight shows has a rule; no crops are needed, so CI sees a missing one."""
    spec = guardmaps._load(MAPS, title)
    for state in SHOWN[title][1]:
        assert state in spec['guards'], state


def _frames(capture: str, out: pathlib.Path) -> dict[str, pathlib.Path]:
    """Every WinUAE screenshot of the capture, cut to the window the guards are measured on."""
    source = ROOT / capture
    shots = sorted(source.glob('*.png'))
    if not shots:
        pytest.skip(f'the {capture} capture is not on this machine')
    out.mkdir()
    frames = {}
    for shot in shots:
        frames[shot.stem] = out / shot.name
        screens.canonical_file(shot, frames[shot.stem])
    return frames


@pytest.mark.parametrize('title', sorted(SHOWN))
def test_each_fight_guard_matches_its_screens_and_no_other_frame(title, tmp_path):
    """The rule matches every frame of its screen, and no frame before it or after it, in either capture."""
    assert guardmaps.main(['export', '--title', title, '--out', str(tmp_path / 'map')]) == 0
    guards = screens.PixelGuards(tmp_path / 'map' / 'guards.json')
    frames = {capture: _frames(capture, tmp_path / capture.replace('/', '-'))
              for capture, _ in SHOWN.values()}
    own, shown = SHOWN[title]
    for state, expected in shown.items():
        for capture, captured in frames.items():
            matched = {name for name, frame in captured.items() if guards(state, frame)}
            assert matched == (expected if capture == own else set()), (state, capture)


#: Frames of the Pools of Darkness encounter bar, with the four-button and two-button forms.
ENCOUNTER_FRAMES = {
    'four buttons': 'WISH-2/wish2-a3/accept2/shots/13-world.png',
    'undead, two buttons': 'WISH-359/qf-off1/w14.png',
    'undead, two buttons, walk': 'WISH-359/fight/darkness/watch2/fight/010-walk.png',
}


@pytest.mark.parametrize('name', sorted(ENCOUNTER_FRAMES))
def test_darkness_encounter_guard_matches_both_command_bars(name, tmp_path):
    """The ATTACK FLEE TALK WAIT bar and the undead ATTACK FLEE bar are both an encounter, and neither is the world or a member's bar."""
    source = ROOT / ENCOUNTER_FRAMES[name]
    if not source.exists():
        pytest.skip(f'{source.name} is not on this machine')
    assert guardmaps.main(['export', '--title', 'darkness', '--out', str(tmp_path / 'map')]) == 0
    guards = screens.PixelGuards(tmp_path / 'map' / 'guards.json')
    frame = tmp_path / 'frame.png'
    screens.canonical_file(source, frame)
    assert guards('encounter', frame)
    if name != 'four buttons':
        assert not guards('world', frame)
        assert not guards('combat_bar', frame)

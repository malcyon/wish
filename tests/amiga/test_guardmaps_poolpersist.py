"""Check that the Pool guards recognise the scrolled CLI and a caster's camp sheet bar, and not the screens beside them."""

import pytest

from tools.amiga import guardmaps, screens
from tools.registry import scratch

KEPT = scratch.cache_dir('acceptance') / 'WISH-359' / 'persist2'


def _frame(run, number):
    path = KEPT / run / f'game-{number:03d}.png'
    if not path.is_file():
        pytest.skip('the kept frames of this run are not on this machine')
    return path


@pytest.fixture(scope='module')
def guards(tmp_path_factory):
    out = tmp_path_factory.mktemp('pool-guards')
    assert guardmaps.main(['export', '--title', 'pool', '--out', str(out)]) == 0
    return screens.PixelGuards(out / 'guards.json')


@pytest.mark.parametrize('number', (129, 137, 182, 213))
def test_cli_matches_the_first_and_the_scrolled_second_quit(guards, number):
    assert guards('cli', _frame('pool-heal', number))


@pytest.mark.parametrize('number', (128, 181))
def test_cli_does_not_match_the_quit_prompt(guards, number):
    assert not guards('cli', _frame('pool-heal', number))


@pytest.mark.parametrize('run,number', (('pool-spells', 114), ('pool-heal', 106)))
def test_camp_sheet_items_matches_a_caster_and_a_fighter(guards, run, number):
    assert guards('camp_sheet_items', _frame(run, number))


@pytest.mark.parametrize('run,number', (('pool-heal', 0), ('pool-heal', 128), ('pool-heal', 129),
                                        ('pool-heal', 181), ('pool-spells', 0)))
def test_camp_sheet_items_does_not_match_other_screens(guards, run, number):
    assert not guards('camp_sheet_items', _frame(run, number))


def test_cli_does_not_match_the_camp_sheets(guards):
    assert not guards('cli', _frame('pool-spells', 114))
    assert not guards('cli', _frame('pool-heal', 106))

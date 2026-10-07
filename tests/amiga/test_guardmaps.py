"""Check guard-map ownership, export, and cross-title collisions on synthetic crops."""

import json
import os

import pytest
from PIL import Image

from tools.amiga import guardmaps


def _crop(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (720, 568), 'black')
    for x in range(10, 20):
        for y in range(10, 20):
            image.putpixel((x, y), (255, 0, 0) if x % 2 else (0, 0, 255))
    image.save(path)


def _run(root, issue, name, title, state, *, manifest=True):
    run = root / issue / name
    run.mkdir(parents=True, exist_ok=True)
    if manifest:
        (run / 'prepare.json').write_text(json.dumps({'title': title}))
    shot = run / 'accept' / 'shots' / f'01-{state}.png'
    _crop(shot)
    (run / 'accept' / 'summary.json').write_text(json.dumps({'success': True, 'measure': False}))
    return shot


def test_manifest_ownership_and_cross_title_collision(tmp_path, capsys):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    pool = _run(root, '1', 'unusual-folder', 'pool', 'title')
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'add', '--title', 'pool',
                           '--map', 'guards', '--state', 'title', '--crop', str(pool),
                           '--box', '10,10,20,20']) == 0
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'check', '--title', 'pool']) == 0
    _run(root, '2', 'another-folder', 'curse', 'title')
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'check', '--title', 'pool']) == 1
    assert 'another-folder' in capsys.readouterr().out


def test_missing_unreadable_manifest_and_aliases(tmp_path):
    root = tmp_path / 'root'
    missing = _run(root, '1', 'missing', 'curse', 'title', manifest=False)
    broken = _run(root, '1', 'broken', 'curse', 'title')
    (broken.parents[2] / 'prepare.json').write_text('{')
    reload = _run(root, '1', 'reload', 'darkness-reload', 'title')
    legacy = _run(root, '1', 'legacy', 'ssb', 'title')
    (legacy.parents[2] / 'prepare.json').write_text(json.dumps({'published_df1': {}}))
    crops = guardmaps.scan_crops(root)
    owners = {crop.relative: crop.title for crop in crops}
    assert owners[missing.relative_to(root).as_posix()] is None
    assert owners[broken.relative_to(root).as_posix()] is None
    assert owners[reload.relative_to(root).as_posix()] == 'darkness'
    assert owners[legacy.relative_to(root).as_posix()] == 'ssb'


@pytest.mark.parametrize('title', ['pool', 'ssb'])
def test_export_loads_as_pixel_guards(tmp_path, title):
    from tools.amiga.screens import PixelGuards, rules_of

    out = tmp_path / 'export'
    assert guardmaps.main(['export', '--title', title, '--out', str(out)]) == 0
    for kind in ('guards', 'identity'):
        exported = json.loads((out / f'{kind}.json').read_text())
        assert exported
        assert all(set(rule) - {'and'} == {'box', 'sha256'}
                   for value in exported.values() for rule in rules_of(value))
        assert PixelGuards(out / f'{kind}.json').rules == exported
    assert guardmaps.main(['export', '--title', title, '--out', str(out)]) == 2


def test_also_admits_a_trusted_state(tmp_path, capsys):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    crop = _run(root, '1', 'run', 'pool', 'journal')
    spec = {'labels': {}, 'guards': {
        'journal': {**guardmaps.screens.guard_rule(crop, [10, 10, 20, 20], 'journal'),
                    'example': crop.relative_to(root).as_posix(), 'also': []}}, 'identity': {}}
    (maps / 'guards_pool.json').write_text(json.dumps(spec))
    _run(root, '1', 'run2', 'pool', 'journal_answer')
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'check', '--title', 'pool']) == 1
    assert 'journal_answer' in capsys.readouterr().out
    spec['guards']['journal']['also'] = ['journal_answer']
    (maps / 'guards_pool.json').write_text(json.dumps(spec))
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'check', '--title', 'pool']) == 0


def test_stale_example_fails_check(tmp_path, capsys):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    crop = _run(root, '1', 'run', 'pool', 'title')
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'add', '--title', 'pool',
                           '--map', 'guards', '--state', 'title', '--crop', str(crop),
                           '--box', '10,10,20,20']) == 0
    Image.new('RGB', (720, 568), 'green').save(crop)
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'check', '--title', 'pool']) == 1
    assert 'stale' in capsys.readouterr().out


def test_untrusted_run_needs_a_label(tmp_path):
    root = tmp_path / 'root'
    shot = _run(root, '1', 'measure', 'pool', 'title')
    summary = shot.parent.parent / 'summary.json'
    summary.write_text(json.dumps({'success': True, 'measure': True}))
    assert guardmaps.scan_crops(root)[0].states == ()
    summary.write_text(json.dumps({'success': False, 'measure': False}))
    assert guardmaps.scan_crops(root)[0].states == ()


def test_a_diagnose_runs_grab_names_are_not_screen_names(tmp_path, capsys):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    pool = _run(root, '1', 'real', 'pool', 'title')
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'add', '--title', 'pool',
                           '--map', 'guards', '--state', 'title', '--crop', str(pool),
                           '--box', '10,10,20,20']) == 0
    shot = _run(root, '2', 'diagnose', 'pool', 'x')
    boot = shot.with_name('00-boot-01.png')
    shot.rename(boot)
    summary = shot.parent.parent / 'summary.json'
    summary.write_text(json.dumps({'success': True, 'measure': False, 'argv': ['diagnose', '--x']}))
    assert guardmaps.scan_crops(root)[1].states == ()
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'check', '--title', 'pool']) == 0
    assert 'collision' not in capsys.readouterr().out


def test_committed_maps_cover_guarded_routes():
    from tools.amiga import route_silver_blades
    from tools.amiga.route_curse import CURSE
    from tools.amiga.route_darkness import DARKNESS, DARKNESS_RELOAD
    from tools.amiga.route_pool import POOL

    for title, routes in {'pool': (POOL,), 'curse': (CURSE,),
                          'darkness': (DARKNESS, DARKNESS_RELOAD)}.items():
        spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, title)
        required = {'title'}
        for route in routes:
            required.update(route.strict)
            required.update(step[1] for step in route.route)
        assert required <= spec['guards'].keys()
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    required = {'title'} | {step[1] for route in (route_silver_blades.ROUTE,
                                                  route_silver_blades.ACCEPT_ROUTE)
                            for step in route}
    assert required <= spec['guards'].keys()


def test_committed_darkness_map_guards_every_vault_route_state():
    """Both vault forms and Elminster's menu each have a rule; no crops are needed, so CI sees a missing one."""
    from tools.amiga import route_darkness

    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'darkness')
    required = {route_darkness.VAULT_MENU, 'elminster_menu'}
    for coins in (True, False):
        required.update(state for _, state, _ in route_darkness.vault_steps(3, coins))
    assert {'vault_take', 'vault_items', 'vault_row', 'vault_bar'} <= required
    for state in sorted(required):
        assert state in spec['guards'], state
        assert spec['guards'][state] and _rules(spec['guards'][state]), state


def test_pool_map_guards_line_one_items_and_holds_its_list_identity():
    """A Pool substitute run with `items 1` keys every strict state on a recognised screen."""
    from tools.amiga import route_camp
    from tools.amiga.route_pool import POOL

    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'pool')
    route = route_camp.camp_title(POOL, ('items 1',), 6, name='pool')
    assert {'camp_sheet_items', 'camp_items'} <= route.strict
    assert route.strict <= spec['guards'].keys()
    assert {'camp_items', 'camp_sheet_items'} <= spec['identity'].keys()
    # The camp sheet is the world sheet's picture, so each guard admits the other.
    assert 'sheet' in spec['guards']['camp_sheet_items']['also']
    assert 'camp_sheet_items' in spec['guards']['sheet']['also']
    # The pinned party keeps its sheet and roster rules beside the substituted party's.
    for state in ('sheet', 'world'):
        assert len(_rules(spec['identity'][state])) >= 2, state


def test_darkness_map_guards_ready_steps_and_every_lines_item_list():
    """A Pools of Darkness `ready 1 7` run, and `items N` on any line, keys every strict state on a recognised screen."""
    from tools.amiga import route_camp
    from tools.amiga.route_darkness import DARKNESS

    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'darkness')
    route = route_camp.camp_title(DARKNESS, ('ready 1 7', 'ready 1 7'), 6, name='darkness')
    rows = {f'camp_items_row{n}' for n in range(2, 8)}
    assert {'camp_sheet_items', 'camp_items'} | rows <= route.strict
    assert route.strict <= spec['guards'].keys()
    tokens = tuple(f'items {n}' for n in range(1, 7))
    states = {state for _, state, _ in route_camp.steps_for(tokens, 'darkness', 6)}
    assert {'camp_sheet_items_6', 'camp_items_6'} <= states
    assert states <= spec['guards'].keys()
    # Each line's sheet and list say whose they are; a row state's READY column differs by boot.
    owned = {s for s in states if s.startswith(('camp_items', 'camp_sheet_items'))}
    assert owned <= spec['identity'].keys()
    assert not rows & spec['identity'].keys()
    # READY flips the YES/NO column, and `ready 1 7` twice opens the list again with row 7 at NO,
    # so a list's identity rule reads only the item names to the right of that column.
    for state in owned:
        if state.startswith('camp_items'):
            assert all(rule['box'][0] >= 150 for rule in _rules(spec['identity'][state])), state
    # Line 1 of the substituted party is not the pinned party's first member, so its world
    # sheet and roster need a second rule beside the pinned ones.
    for kind, state in (('guards', 'sheet'), ('identity', 'sheet'), ('identity', 'loaded_menu')):
        assert len(_rules(spec[kind][state])) >= 2, (kind, state)
    # Every list shows the same READY ITEM heading, so each list guard admits the others.
    lists = {s for s in states | route.strict if route_camp.is_items(s)}
    for state in lists:
        assert lists - {state} <= set(spec['guards'][state]['also']), state


def test_silver_blades_map_guards_line_one_items_and_join_steps_and_their_messages():
    from tools.amiga import route_camp, route_silver_blades

    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    steps = route_camp.steps_for(('items 1', 'join 1 2', 'join 1 1'), 'ssb')
    states = {state for _, state, _ in steps}
    states |= {route_camp.joined_after(state) for state in states if route_camp.is_join(state)}
    assert {'camp_sheet_items', 'camp_items', 'camp_items_row2', 'camp_join',
            'camp_joined'} <= states
    assert states <= spec['guards'].keys()
    assert {*route_camp.JOIN_MESSAGES, route_silver_blades.LOAD_MESSAGE} <= spec['guards'].keys()
    # The list states share the list header with the party menu's list, so each lists the others.
    lists = {'items', 'camp_items', 'camp_items_row2', 'camp_join', 'camp_joined'}
    for state in lists:
        assert lists - {state} <= set(spec['guards'][state]['also'])


def _rules(value):
    return value if isinstance(value, list) else [value]


#: Camp steps over every row the U and C Save As parties' lists reach on lines 1 to 3.
_UC_STEPS = ('items 1', 'items 2', 'items 3', 'join 1 3', 'join 2 15', 'join 3 2')


def _step_states(tokens):
    from tools.amiga import route_camp

    states = {state for _, state, _ in route_camp.steps_for(tokens, 'ssb')}
    return states | {route_camp.joined_after(s) for s in states if route_camp.is_join(s)}


def test_silver_blades_map_guards_every_row_of_the_u_and_c_lists():
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    states = _step_states(_UC_STEPS)
    assert {'camp_items_row3', 'camp_items_2_row15', 'camp_sheet_items_3', 'camp_joined_3'} <= states
    assert states <= spec['guards'].keys()
    # Every list state shows the same header, so each guard lists every other.
    from tools.amiga import route_camp
    lists = {s for s in states if route_camp.is_items(s) or route_camp.is_join(s)
             or route_camp.is_joined(s)} | {'items'}
    for state in lists:
        for rule in _rules(spec['guards'][state]):
            assert lists - {state} <= set(rule['also']), state


def test_silver_blades_identity_covers_the_lists_and_sheets_but_not_the_join_grab():
    from tools.amiga import route_camp

    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    states = _step_states(('items 1', 'join 1 2', 'join 1 1')) | _step_states(_UC_STEPS)
    checked = {s for s in states if route_camp.is_items(s) or route_camp.is_joined(s)
               or s.startswith('camp_sheet_items')}
    assert {'camp_sheet_items', 'camp_items', 'camp_items_row2', 'camp_joined',
            'camp_sheet_items_2', 'camp_items_2_row15', 'camp_joined_3'} <= checked
    assert checked <= spec['identity'].keys()
    # The first grab after J can catch the list half redrawn (wish4-b1__a_join1-00), so a rows
    # rule there would stop a correct run on timing; the redrawn list is checked instead.
    assert not {s for s in states if route_camp.is_join(s)} & spec['identity'].keys()
    # The U and C Save As parties share these lists, and a cut alternative leaves the other
    # disk's run stopped on a screen its guard does not know: each disk needs its own crop
    # matched. C's lists have 13 rows, so rows 14 and 15 and PAINE's and EPONA's single-rule
    # states are U only.
    first = _step_states(('items 1', 'join 1 2', 'join 1 1'))
    uc = {s for s in checked - first if not s.startswith('camp_sheet_items')} | {'camp_items'}
    u_only = {'camp_items_2_row14', 'camp_items_2_row15', 'camp_items_3', 'camp_items_3_row2',
              'camp_items_row3'}
    assert u_only <= uc and 'camp_joined_3' in uc and 'camp_items_2_row7' in uc
    for state in uc:
        examples = [rule['example'] for rule in _rules(spec['identity'][state])]
        disks = ('wish4-uc__u_',) if state in u_only else ('wish4-uc__u_', 'wish4-uc__c_')
        for disk in disks:
            assert any(disk in example for example in examples), (state, disk)
        # Removing the other disk's alternative must fail even where the first disk's remains.
        assert len(examples) >= len(disks), state
    # The first-line lists also carry the first run's own alternatives.
    assert len(_rules(spec['identity']['camp_items'])) >= 5
    assert len(_rules(spec['identity']['camp_items_row2'])) >= 4
    assert len(_rules(spec['identity']['camp_joined'])) >= 4


def test_silver_blades_sheet_family_and_camp_sheet_items_list_each_other():
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    family = {'camp_sheet', 'camp_sheet_2', 'camp_sheet_heal', 'camp_sheet_spent', 'sheet'}
    guards = spec['guards']
    # The ITEMS button is on every sheet of a member who carries something.
    assert family <= set(guards['camp_sheet_items']['also'])
    for state in family:
        for rule in _rules(guards[state]):
            assert 'camp_sheet_items' in rule['also'], state
    # Identity is the name line: every rule with the same picture lists the other.
    identity = spec['identity']
    items = identity['camp_sheet_items']
    same = {state for state in family
            if any((r['box'], r['sha256']) == (items['box'], items['sha256'])
                   for r in _rules(identity[state]))}
    assert same == family - {'camp_sheet_2'}
    assert same <= set(items['also'])
    for state in same:
        for rule in _rules(identity[state]):
            assert 'camp_sheet_items' in rule['also'], state
    # Lines 2 and 3 show the same ITEMS button, so their guards are the line 1 picture, and the
    # sheet frame every member shows lists them all. Of the bars, only Guy's spent bar from
    # the first camp run is also PAINE's and EPONA's (no HEAL on either).
    lines = {'camp_sheet_items', 'camp_sheet_items_2', 'camp_sheet_items_3'}
    for state in lines:
        rule = guards[state]
        assert (rule['box'], rule['sha256']) == (guards['camp_sheet_items']['box'],
                                                 guards['camp_sheet_items']['sha256'])
        assert (family | lines) - {state} <= set(rule['also'])
    for state in ('camp_sheet', 'camp_sheet_2', 'sheet'):
        assert lines <= set(guards[state]['also']), state
    assert lines <= set(_rules(guards['camp_sheet_spent'])[0]['also'])
    # PAINE's name line is camp_sheet_2's picture, so the two identity rules list each other.
    assert identity['camp_sheet_items_2']['sha256'] == identity['camp_sheet_2']['sha256']
    assert 'camp_sheet_2' in identity['camp_sheet_items_2']['also']
    assert 'camp_sheet_items_2' in identity['camp_sheet_2']['also']


def _interstitial_screens(title):
    from tools.amiga import route_silver_blades
    from tools.amiga.route_curse import CURSE
    from tools.amiga.route_darkness import DARKNESS, DARKNESS_RELOAD
    from tools.amiga.route_pool import POOL

    tables = {'pool': (POOL.interstitials,), 'curse': (CURSE.interstitials,),
              'darkness': (DARKNESS.interstitials, DARKNESS_RELOAD.interstitials),
              'ssb': (route_silver_blades.SILVER_BLADES_INTERSTITIALS,
                      route_silver_blades.PUBLISHED_INTERSTITIALS)}[title]
    return {row[0] for table in tables for row in table}


@pytest.mark.parametrize('title', ['pool', 'curse', 'ssb', 'darkness'])
def test_committed_maps_guard_every_interstitial_screen(title):
    """A row whose screen has no guard never fires, so the run waits out the screen it names."""
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, title)
    assert _interstitial_screens(title) <= spec['guards'].keys()


def test_add_rejections_leave_map_unchanged(tmp_path, capsys):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    crop = _run(root, '1', 'pool-run', 'pool', 'title')
    argv = ['--root', str(root), '--maps', str(maps), 'add', '--title', 'pool',
            '--map', 'guards', '--state', 'title', '--crop', str(crop), '--box', '10,10,20,20']
    assert guardmaps.main(argv) == 0
    path = maps / 'guards_pool.json'
    original = path.read_bytes()
    assert guardmaps.main(argv) == 2
    assert path.read_bytes() == original
    outside = tmp_path / 'outside.png'
    _crop(outside)
    assert guardmaps.main(argv[:argv.index('--crop') + 1] + [str(outside)] + argv[argv.index('--box'):]) == 2
    assert path.read_bytes() == original
    other = _run(root, '2', 'curse-run', 'curse', 'title')
    assert guardmaps.main(argv + ['--replace']) == 2
    assert 'also matches' in capsys.readouterr().err
    assert path.read_bytes() == original
    with Image.open(other) as image:
        image.paste('green', (0, 0, 10, 10))
        image.save(other)
    assert guardmaps.main(argv + ['--replace', '--box', '0,0,10,10']) == 2
    assert 'one colour' in capsys.readouterr().err
    assert path.read_bytes() == original


def test_failed_replace_keeps_map_and_removes_temp_file(tmp_path, monkeypatch):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    crop = _run(root, '1', 'pool-run', 'pool', 'title')
    argv = ['--root', str(root), '--maps', str(maps), 'add', '--title', 'pool',
            '--map', 'guards', '--state', 'title', '--crop', str(crop),
            '--box', '10,10,20,20']
    assert guardmaps.main(argv) == 0
    path = maps / 'guards_pool.json'
    original = path.read_bytes()

    def fail_replace(source, target):
        raise OSError('disk gone')

    monkeypatch.setattr(guardmaps.os, 'replace', fail_replace)
    assert guardmaps.main([*argv, '--replace']) == 2
    assert path.read_bytes() == original
    assert not path.with_name(path.name + '.tmp').exists()


def test_screens_digest_boxes_and_checked_rule(tmp_path):
    import pytest

    from tools.amiga import screens
    from tools.amiga.winuaesession import RouteError

    crop = tmp_path / 'crop.png'
    other = tmp_path / 'other.png'
    _crop(crop)
    _crop(other)
    box = [10, 10, 20, 20]
    assert screens.box_digests(crop, [box])[tuple(box)] == screens._box_digest(crop, box, 'title')
    with pytest.raises(RouteError, match='invalid crop box'):
        screens.box_digests(crop, [[0, 0, 721, 568]])
    with pytest.raises(RouteError, match='also matches'):
        screens.checked_rule(crop, box, 'title', [other])
    with pytest.raises(RouteError, match='one colour'):
        screens.checked_rule(crop, [0, 0, 10, 10], 'title', [])


def test_grabs_copy_crop_and_diff(tmp_path, capsys):
    from tests.amiga.test_amigashots import _desktop

    source = tmp_path / 'source'
    (source / 'nested').mkdir(parents=True)
    _crop(source / 'nested' / 'small.png')
    _desktop((0, 0, 34)).save(source / 'desktop.png')
    Image.new('RGB', (900, 700), 'black').save(source / 'no-band.png')
    root = tmp_path / 'root'
    assert guardmaps.main(['--root', str(root), 'grabs', str(source)]) == 0
    assert 'copied 1 cropped 1 failed 1 kept 0' in capsys.readouterr().out
    out = root / 'amiga-grab-crops'
    assert (out / 'nested__small.png').exists()
    assert Image.open(out / 'desktop.png').size == (720, 568)
    assert guardmaps.main(['diff', str(out / 'desktop.png'), str(out / 'desktop.png')]) == 0
    assert 'identical' in capsys.readouterr().out


def test_add_blocks_a_crop_owned_by_another_title(tmp_path, capsys):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    curse = _run(root, '1', 'misleading-pool-name', 'curse', 'title')
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'add',
                           '--title', 'pool', '--map', 'guards', '--state', 'title',
                           '--crop', str(curse), '--box', '10,10,20,20']) == 2
    assert 'guardmaps:' in capsys.readouterr().err
    assert not (maps / 'guards_pool.json').exists()


def test_diff_rejects_rows_outside_image_without_traceback(tmp_path):
    import subprocess
    import sys

    crop = tmp_path / 'crop.png'
    _crop(crop)
    result = subprocess.run([sys.executable, guardmaps.__file__, 'diff',
                             str(crop), str(crop), '--rows', '0,569'],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert result.stderr.startswith('guardmaps: ')
    assert 'Traceback' not in result.stderr


def test_non_string_manifest_titles_leave_crops_unowned(tmp_path):
    root = tmp_path / 'root'
    for name, value in (('list', []), ('map', {})):
        shot = _run(root, '1', name, 'pool', 'title')
        (shot.parents[2] / 'prepare.json').write_text(json.dumps({'title': value}))
    assert {crop.title for crop in guardmaps.scan_crops(root)} == {None}


def test_the_silver_blades_treasure_bar_and_world_guards_match_their_kept_crops():
    """Reads crops kept from the live run, so it skips on a machine without them."""
    from tools.amiga import screens
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    kept = {'treasure_bar': ('640/ssb2/accept1/shots/11-world.png',
                             '640/ssb2/accept2/shots/11-world.png'),
            'world': ('640/ssb2/accept2/shots/12-camp.png',)}
    if not all((root / crop).is_file() for crops in kept.values() for crop in crops):
        pytest.skip('the kept 640 Silver Blades crops are not on this machine')
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    everything = [c for crops in kept.values() for c in crops]
    for state, crops in kept.items():
        rule = spec['guards'][state]
        box = tuple(rule['box'])
        for crop in everything:
            digest = screens.box_digests(root / crop, {box})[box]
            assert (digest == rule['sha256']) is (crop in crops), (state, crop)


def test_the_silver_blades_camp_save_picker_guard_matches_only_the_camp_picker_crops():
    """Reads crops kept from live runs, so it skips on a machine without them."""
    from tools.amiga import screens
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    pickers = ('640/ssb3/accept3/shots/15-camp_save_picker.png',
               '672/f6f1f461a8-amiga-accept2/accept2/shots/15-camp_save_picker.png',
               '672/400d2381cd-amiga-accept2/accept2/shots/15-camp_save_picker.png',
               '449/rb449-4/accept1/shots/15-camp_save_picker.png')
    # The menu's own picker shares the bar row with this one, and the last
    # three are the rule-book question screen, which no picker rule may match.
    not_pickers = ('449/rb449-4/accept1/shots/08-save_picker.png',
                   '449/rb449-2/accept1/shots/15-camp_save_picker.png',
                   '449/rb449-3/accept1/shots/15-camp_save_picker.png',
                   '449/rb449-3/accept1/shots/16-exit_game.png')
    if not all((root / crop).is_file() for crop in (*pickers, *not_pickers)):
        pytest.skip('the kept Silver Blades camp picker crops are not on this machine')
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    rule = spec['guards']['camp_save_picker']
    box = tuple(rule['box'])
    for crop in guardmaps.scan_crops(root):
        owned = crop.title == 'ssb' or crop.relative in spec['labels']
        if not owned or not crop.path.is_file():
            continue
        named = crop.relative in pickers or crop.relative in not_pickers
        if not (named or crop.relative in spec['labels'] or crop.states):
            continue
        digest = screens.box_digests(crop.path, {box})[box]
        shown = 'camp_save_picker' in spec['labels'].get(crop.relative, crop.states)
        if crop.relative in pickers or shown:
            assert digest == rule['sha256'], crop.relative
        elif crop.relative in not_pickers:
            assert digest != rule['sha256'], crop.relative
        elif crop.states:
            assert digest != rule['sha256'], crop.relative


def test_the_camp_picker_guard_test_decodes_only_the_crops_an_assertion_reads(monkeypatch):
    """Reads crops kept from live runs, so it skips on a machine without them."""
    from tools.amiga import screens
    from tools.registry import scratch

    decoded = []
    real = screens.box_digests

    def counting(path, boxes):
        decoded.append(path)
        return real(path, boxes)

    monkeypatch.setattr(screens, 'box_digests', counting)
    test_the_silver_blades_camp_save_picker_guard_matches_only_the_camp_picker_crops()
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    unread = [crop for crop in guardmaps.scan_crops(scratch.cache_dir('acceptance'))
              if crop.path in decoded and crop.relative not in spec['labels'] and not crop.states
              and not crop.relative.endswith(('15-camp_save_picker.png', '08-save_picker.png',
                                              '16-exit_game.png'))]
    assert decoded
    assert not unread, unread[0].relative


def _second_crop(path):
    _crop(path)
    image = Image.open(path).copy()
    for x in range(10, 20):
        image.putpixel((x, 12), (0, 255, 0))
    image.save(path)


def test_alternative_rule_matches_either_crop_and_single_rule_json_loads(tmp_path):
    from tools.amiga.screens import PixelGuards

    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    first = _run(root, '1', 'pool-run', 'pool', 'sheet')
    second = root / '2' / 'pool-run' / 'accept' / 'shots' / '01-sheet.png'
    _second_crop(second)
    (second.parents[1] / 'summary.json').write_text(json.dumps({'success': True, 'measure': False}))
    (second.parents[2] / 'prepare.json').write_text(json.dumps({'title': 'pool'}))
    base = ['--root', str(root), '--maps', str(maps), 'add', '--title', 'pool', '--map', 'guards',
            '--state', 'sheet', '--box', '10,10,20,20']
    assert guardmaps.main([*base, '--crop', str(first)]) == 0
    single = json.loads((maps / 'guards_pool.json').read_text())['guards']['sheet']
    assert isinstance(single, dict)
    assert guardmaps.main([*base, '--crop', str(second)]) == 2
    assert guardmaps.main([*base, '--crop', str(second), '--alternative', '--replace']) == 2
    assert guardmaps.main([*base, '--crop', str(first), '--alternative']) == 2
    assert guardmaps.main([*base, '--crop', str(second), '--alternative']) == 0
    assert guardmaps.main([*base, '--crop', str(second), '--alternative']) == 2
    stored = json.loads((maps / 'guards_pool.json').read_text())['guards']['sheet']
    assert isinstance(stored, list) and stored[0] == single and len(stored) == 2
    assert guardmaps._load(maps, 'pool')
    out = tmp_path / 'out'
    assert guardmaps.main(['--maps', str(maps), 'export', '--title', 'pool', '--out', str(out)]) == 0
    guard = PixelGuards(out / 'guards.json')
    assert guard('sheet', first) and guard('sheet', second)
    other = tmp_path / 'other.png'
    Image.new('RGB', (720, 568), 'black').save(other)
    assert not guard('sheet', other)
    (tmp_path / 'one.json').write_text(json.dumps({'sheet': single}))
    lone = PixelGuards(tmp_path / 'one.json')
    assert lone('sheet', first) and not lone('sheet', second)


def test_alternative_needs_an_existing_state(tmp_path):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    crop = _run(root, '1', 'pool-run', 'pool', 'sheet')
    assert guardmaps.main(['--root', str(root), '--maps', str(maps), 'add', '--title', 'pool',
                           '--map', 'guards', '--state', 'sheet', '--crop', str(crop),
                           '--box', '10,10,20,20', '--alternative']) == 2


def test_committed_silver_blades_camp_sheets_match_itemless_crops(tmp_path):
    """The camp sheet without an item row puts HEAL/CURE and EXIT at other x positions."""
    from tools.amiga.screens import PixelGuards
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance') / '628'
    shots = {'camp_sheet_heal': 'accept1/shots/27-camp_sheet_heal.png',
             'camp_sheet_spent': 'accept1/shots/29-camp_sheet_spent.png'}
    crops = {(run, state): root / run / name for run in ('628-S3b', '628-S5b')
             for state, name in shots.items()}
    crops[('628-S5b', 'camp_sheet_heal')] = root / '628-S5b/accept1/shots/26-camp_sheet_heal.png'
    crops[('628-S5b', 'camp_sheet_spent')] = root / '628-S5b/accept1/shots/28-camp_sheet_spent.png'
    if not all(path.exists() for path in crops.values()):
        pytest.skip('the #628 itemless camp sheet crops are not on this machine')
    assert guardmaps.main(['export', '--title', 'ssb', '--out', str(tmp_path)]) == 0
    guard = PixelGuards(tmp_path / 'guards.json')
    for (_, state), path in crops.items():
        assert guard(state, path)


def test_silver_blades_sheets_of_lines_3_to_6_share_the_sheet_frame_and_line_3_has_its_name_line():
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    guards, identity = spec['guards'], spec['identity']
    new = {f'camp_sheet_{n}' for n in range(3, 7)}
    frame = guards['camp_sheet']
    # The ARMOR CLASS / THAC0 / DAMAGE labels are one picture on every member's sheet, so lines
    # 3 to 6 take line 1's rule and each sheet state lists every other.
    for state in new:
        rule = guards[state]
        assert (rule['box'], rule['sha256']) == (frame['box'], frame['sha256']), state
        assert (new | {'sheet', 'camp_sheet', 'camp_sheet_2', 'camp_sheet_heal',
                       'camp_sheet_spent', 'camp_sheet_items', 'camp_sheet_items_2',
                       'camp_sheet_items_3'}) - {state} <= set(rule['also']), state
    for state in ('sheet', 'camp_sheet', 'camp_sheet_2', 'camp_sheet_items', 'camp_sheet_items_2',
                  'camp_sheet_items_3'):
        assert new <= set(guards[state]['also']), state
    for state in ('camp_sheet_heal', 'camp_sheet_spent'):
        assert all(new <= set(rule['also']) for rule in _rules(guards[state])), state
    # Only line 3 has a cut name line, EPONA's, listed with her items-list state; lines 4 to 6
    # wait for their own grabs.
    assert identity['camp_sheet_3']['sha256'] == identity['camp_sheet_items_3']['sha256']
    assert 'camp_sheet_items_3' in identity['camp_sheet_3']['also']
    assert 'camp_sheet_3' in identity['camp_sheet_items_3']['also']
    assert not new - {'camp_sheet_3'} & identity.keys()


def test_the_darkness_sheet_guard_matches_a_paladin_sheet_with_lay_on_hands_spent(tmp_path):
    """Reads crops kept from live runs, so it skips on a machine without them.

    The registered party's sheet bar offers LAY; a paladin who has laid on hands
    today shows a bar without it, which only the class- and state-independent
    alternative (the ITEMS button alone) matches.
    """
    from tools.amiga import screens
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    sheets = ('679/0fecb2ffdc-amiga-darkness-accept-A/acceptA/shots/06-sheet.png',
              'WISH-2/wish2-s5/accept1/shots/06-sheet.png')
    not_sheets = ('WISH-2/wish2-s5/accept1/shots/05-loaded_menu.png',
                  'WISH-2/wish2-s5/accept1/shots/04-disk2_prompt.png')
    if not all((root / crop).is_file() for crop in (*sheets, *not_sheets)):
        pytest.skip('the kept Pools of Darkness sheet crops are not on this machine')
    maps = guardmaps.pathlib.Path(guardmaps.__file__).parent
    out = tmp_path / 'darkness'
    assert guardmaps.main(['--maps', str(maps), 'export', '--title', 'darkness', '--out', str(out)]) == 0
    guard = screens.PixelGuards(out / 'guards.json')
    for crop in sheets:
        assert guard('sheet', root / crop), crop
    for crop in not_sheets:
        assert not guard('sheet', root / crop), crop
    bar = [r for r in screens.rules_of(guardmaps._load(maps, 'darkness')['guards']['sheet'])
           if r['box'] == [58, 402, 160, 430]]
    assert len(bar) == 1
    box = tuple(bar[0]['box'])
    for crop in sheets:
        assert screens.box_digests(root / crop, {box})[box] == bar[0]['sha256'], crop


def test_the_silver_blades_identity_map_matches_the_sixteen_row_item_list(tmp_path):
    """Reads a crop kept from a live run, so it skips on a machine without it."""
    from tools.amiga import screens
    from tools.registry import scratch

    crop = scratch.cache_dir('acceptance') / '4/ssb-accept-c/accept5/shots/29-camp_items_2.png'
    if not crop.is_file():
        pytest.skip('the kept Silver Blades item-list crop is not on this machine')
    maps = guardmaps.pathlib.Path(guardmaps.__file__).parent
    rules = screens.rules_of(guardmaps._load(maps, 'ssb')['identity']['camp_items_2'])
    mine = [r for r in rules if r['sha256'].startswith('299fc40d')]
    assert len(mine) == 1
    assert mine[0]['box'] == [88, 104, 680, 372] and mine[0]['also'] == []
    box = tuple(mine[0]['box'])
    assert screens.box_digests(crop, {box})[box] == mine[0]['sha256']
    out = tmp_path / 'ssb'
    assert guardmaps.main(['--maps', str(maps), 'export', '--title', 'ssb', '--out', str(out)]) == 0
    assert screens.PixelGuards(out / 'identity.json')('camp_items_2', crop)


def test_a_second_add_decodes_no_unchanged_crop_and_decodes_a_changed_one(tmp_path, monkeypatch):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    first = _run(root, '1', 'pool-run', 'pool', 'title')
    other = _run(root, '2', 'curse-run', 'curse', 'title')
    _second_crop(other)
    decoded = []
    real = guardmaps._decode_digests
    monkeypatch.setattr(guardmaps, '_decode_digests',
                        lambda path, boxes, state: decoded.append(path) or real(path, boxes, state))
    argv = ['--root', str(root), '--maps', str(maps), 'add', '--title', 'pool',
            '--map', 'guards', '--state', 'title', '--crop', str(first), '--box', '10,10,20,20']
    assert guardmaps.main(argv) == 0
    assert set(decoded) == {first, other}
    decoded.clear()
    assert guardmaps.main([*argv, '--replace']) == 0
    assert decoded == []
    with Image.open(other) as image:
        image.paste('green', (15, 15, 17, 17))
        image.save(other)
    assert guardmaps.main([*argv, '--replace']) == 0
    assert decoded == [other]


def _cache_entries(root):
    return json.loads((root / guardmaps.CACHE_NAME).read_text())


def _add_argv(root, maps, crop, *extra, state='title', box='10,10,20,20'):
    return ['--root', str(root), '--maps', str(maps), 'add', '--title', 'pool',
            '--map', 'guards', '--state', state, '--crop', str(crop), '--box', box, *extra]


def test_cache_drops_entries_for_deleted_crops(tmp_path):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    first = _run(root, '1', 'pool-run', 'pool', 'title')
    gone = _run(root, '2', 'curse-run', 'curse', 'title')
    _second_crop(gone)
    argv = _add_argv(root, maps, first)
    assert guardmaps.main(argv) == 0
    relative = gone.relative_to(root).as_posix()
    assert relative in _cache_entries(root)
    gone.unlink()
    assert guardmaps.main([*argv, '--replace']) == 0
    assert relative not in _cache_entries(root)


def test_changed_inode_with_same_size_and_mtime_is_decoded_again(tmp_path, monkeypatch):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    first = _run(root, '1', 'pool-run', 'pool', 'title')
    other = _run(root, '2', 'curse-run', 'curse', 'title')
    _second_crop(other)
    decoded = []
    real = guardmaps._decode_digests
    monkeypatch.setattr(guardmaps, '_decode_digests',
                        lambda path, boxes, state: decoded.append(path) or real(path, boxes, state))
    argv = _add_argv(root, maps, first)
    assert guardmaps.main(argv) == 0
    stat = other.stat()
    copy = other.with_name('copy.png')
    copy.write_bytes(other.read_bytes())
    os.utime(copy, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    other.unlink()
    copy.rename(other)
    assert other.stat().st_ino != stat.st_ino
    assert (other.stat().st_size, other.stat().st_mtime_ns) == (stat.st_size, stat.st_mtime_ns)
    decoded.clear()
    assert guardmaps.main([*argv, '--replace']) == 0
    assert decoded == [other]


def test_bad_box_error_names_the_state(tmp_path, capsys):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    first = _run(root, '1', 'pool-run', 'pool', 'title')
    _run(root, '2', 'curse-run', 'curse', 'title')
    assert guardmaps.main(_add_argv(root, maps, first, state='title', box='10,10,9000,20')) == 2
    assert 'invalid crop box for title' in capsys.readouterr().err


def test_a_crop_deleted_after_the_scan_is_skipped(tmp_path):
    root = tmp_path / 'root'
    kept = _run(root, '1', 'pool-run', 'pool', 'title')
    gone = _run(root, '2', 'curse-run', 'curse', 'title')
    crops = guardmaps.scan_crops(root)
    gone.unlink()
    digests = guardmaps.cached_digests(root, crops, [(10, 10, 20, 20)])
    assert set(digests) == {kept.relative_to(root).as_posix()}


def test_a_warm_cache_opens_no_png_on_a_second_scan(tmp_path, monkeypatch):
    root, maps = tmp_path / 'root', tmp_path / 'maps'
    maps.mkdir()
    first = _run(root, '1', 'pool-run', 'pool', 'title')
    other = _run(root, '2', 'curse-run', 'curse', 'title')
    _second_crop(other)
    argv = _add_argv(root, maps, first)
    assert guardmaps.main(argv) == 0
    opened = []
    real = guardmaps.Image.open
    monkeypatch.setattr(guardmaps.Image, 'open', lambda path, *a, **k: opened.append(path) or real(path, *a, **k))
    assert guardmaps.main([*argv, '--replace']) == 0
    opened.clear()
    assert len(guardmaps.scan_crops(root)) == 2
    assert opened == []
    # Only the crop named by --crop is opened by the command itself, never by the scan.
    assert [path for path in opened if path != first] == []
    opened.clear()
    with real(other) as image:
        image.paste('green', (15, 15, 17, 17))
        image.save(other)
    assert [crop.path for crop in guardmaps.scan_crops(root)] == [first, other]
    assert opened == [other]


def test_silver_blades_identity_holds_guys_one_row_item_list():
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    rules = _rules(spec['identity']['camp_items'])
    # Guy's list is a one-row page, a different picture from the U and C lists.
    assert any(rule['sha256'] == 'e2d2719448986eeddb8c5cb7bdd938384856026333e52a193f8c318ce1707cd5'
               and rule['box'] == [88, 104, 680, 372] and rule['also'] == ['items']
               for rule in rules)


def _darkness_matching(crop, *, places=True):
    """Guards matching `crop`; `places=False` leaves out the place readout guards, which any screen drawn at that place shows."""
    from tools.amiga import screens

    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'darkness')
    matching = set()
    for state, value in spec['guards'].items():
        if not places and state.startswith('place_'):
            continue
        for rule in screens.rules_of(value):
            box = tuple(rule['box'])
            if screens.box_digests(crop, {box})[box] == rule['sha256']:
                matching.add(state)
    return matching


def test_the_darkness_save_picker_guards_recognise_the_seven_member_party_picker_on_the_camp_and_the_party_menu():
    """Reads crops kept from live runs, so each skips on a machine without it."""
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    crops = ('WISH-2/wish2-a2/measure8/shots/13-camp_save_picker.png',
             'WISH-2/wish2-a2-capture/sheets1/shots/08-save_picker.png')
    seen = 0
    for name in crops:
        crop = root / name
        if not crop.is_file():
            continue
        seen += 1
        assert _darkness_matching(crop, places=False) == {'camp_save_picker', 'save_picker'}, name
    if not seen:
        pytest.skip('the kept Darkness picker crops are not on this machine')


def test_the_darkness_exit_game_guard_recognises_a_quit_question_drawn_with_the_seven_member_border(tmp_path):
    """Reads crops kept from live runs, so it skips on a machine without them."""
    from PIL import Image

    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    quit_ = next(root.glob('679/*-amiga-darkness-accept-A/acceptA/shots/16-camp.png'), None)
    picker = root / 'WISH-2/wish2-a2-capture/sheets1/shots/08-save_picker.png'
    if quit_ is None or not picker.is_file():
        pytest.skip('the kept Darkness quit question or picker crop is not on this machine')
    image = Image.open(quit_).convert('RGB')
    other = Image.open(picker).convert('RGB')
    for rows in ((402, 406), (428, 432)):
        image.paste(other.crop((58, rows[0], 698, rows[1])), (58, rows[0]))
    image.paste(other.crop((322, 406, 360, 416)), (322, 406))
    drawn = tmp_path / 'quit.png'
    image.save(drawn)
    assert 'exit_game' in _darkness_matching(drawn)
    for name in ('628/darkness-P1a/accept2/shots/31-exit_game.png',
                 'WISH-2/wish2-a3/accept3b/shots/16-exit_game.png'):
        crop = root / name
        if crop.is_file():
            assert 'exit_game' in _darkness_matching(crop), name
    assert 'exit_game' in _darkness_matching(quit_)
    for name in ('WISH-2/wish2-a2/measure8/shots/13-camp_save_picker.png',
                 'WISH-2/wish2-a2-capture/sheets1/shots/08-save_picker.png',
                 'WISH-2/wish2-a2/measure7/shots/12-camp.png'):
        crop = root / name
        if crop.is_file():
            assert 'exit_game' not in _darkness_matching(crop), name


def test_the_darkness_exit_game_guard_recognises_the_seven_member_quit_question():
    """Reads crops kept from live runs, so it skips on a machine without them."""
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    crop = root / 'WISH-2/wish2-a2-capture/sheets2/shots/54-exit_game.png'
    if not crop.is_file():
        pytest.skip('the kept Darkness seven-member quit question is not on this machine')
    assert _darkness_matching(crop, places=False) == {'exit_game'}
    for name in ('628/darkness-P1a/accept2/shots/31-exit_game.png',
                 'WISH-2/wish2-a3/accept3b/shots/16-exit_game.png'):
        other = root / name
        if other.is_file():
            assert 'exit_game' in _darkness_matching(other), name


def test_the_darkness_camp_sheet_identities_match_their_seven_member_line_and_not_the_others():
    """Reads crops kept from live runs, so it skips on a machine without them."""
    from tools.amiga import screens
    from tools.registry import scratch

    shots = scratch.cache_dir('acceptance') / 'WISH-2/wish2-a2-capture/sheets2/shots'
    sheets = {'camp_sheet': '51-camp_sheet.png', 'camp_sheet_2': '16-camp_sheet_2.png',
              'camp_sheet_3': '21-camp_sheet_3.png', 'camp_sheet_4': '28-camp_sheet_4.png',
              'camp_sheet_5': '36-camp_sheet_5.png', 'camp_sheet_6': '43-camp_sheet_6.png',
              'camp_sheet_7': '48-camp_sheet_7.png'}
    if not all((shots / name).is_file() for name in sheets.values()):
        pytest.skip('the kept Darkness seven-member sheet crops are not on this machine')
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'darkness')

    def matching(crop):
        found = set()
        for state in sheets:
            for rule in screens.rules_of(spec['identity'][state]):
                box = tuple(rule['box'])
                if screens.box_digests(crop, {box})[box] == rule['sha256']:
                    found.add(state)
        return found

    for state, name in sheets.items():
        assert matching(shots / name) == {state}, state


def test_the_darkness_vault_guards_match_their_screens_and_not_the_neighbours(tmp_path):
    """Reads crops kept from the vault measure boot, so it skips on a machine without them.

    The bar guard matches the bar with and without the TAKE word; the row guard
    matches the list's bar at every highlight position the route presses.
    """
    from tools.amiga import screens
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    shots = 'WISH-6/wish6-l1/measure2/shots/'
    empty_bar = 'WISH-6/wish6-a5/a5m1/shots/11-vault_bar.png'
    seen = {
        'vault_bar': [shots + '11-vault_bar.png', shots + '54-vault_bar.png', empty_bar],
        'vault_take': [shots + '12-vault_take.png', shots + '53-vault_take.png'],
        'vault_items': [shots + '13-vault_items.png'],
        'vault_row': [shots + f'{n}-vault_row.png' for n in range(14, 53)],
    }
    others = [shots + '10-elminster_menu.png', shots + '55-elminster_menu.png', shots + '56-camp.png']
    if not all((root / crop).is_file() for crops in (*seen.values(), others) for crop in crops):
        pytest.skip('the kept vault measure crops are not on this machine')
    maps = guardmaps.pathlib.Path(guardmaps.__file__).parent
    out = tmp_path / 'darkness'
    assert guardmaps.main(['--maps', str(maps), 'export', '--title', 'darkness', '--out', str(out)]) == 0
    guard = screens.PixelGuards(out / 'guards.json')
    for state, crops in seen.items():
        for crop in crops:
            assert guard(state, root / crop), (state, crop)
        # vault_row shares its bar with the first list screen, which vault_items also names.
        ignore = {'vault_row': {'vault_items'}, 'vault_items': set()}.get(state, set())
        for other, other_crops in seen.items():
            if other == state or other in ignore:
                continue
            for crop in other_crops:
                assert not guard(state, root / crop), (state, crop)
        for crop in others:
            assert not guard(state, root / crop), (state, crop)


_DARKNESS_WORLD_LABELS = {
    '9/wish9-control/accept1/shots/12-world.png': 'place_x1_y2_f1',
    '9/wish9-test/accept3/shots/12-world.png': 'place_x1_y2_f1',
    '9/wish9-control/accept1/shots/13-world.png': 'place_x2_y2_f1',
    '9/wish9-test/accept3/shots/13-world.png': 'place_x2_y2_f1',
    'WISH-2/wish2-a1a/accept1/shots/12-world.png': 'place_x2_y2_f1',
    'WISH-2/wish2-a1b/accept1/shots/12-world.png': 'place_x2_y2_f1',
    'WISH-2/wish2-s5/accept2/shots/12-world.png': 'place_x2_y2_f1',
    'WISH-2/wish2-a1a/accept1/shots/13-world.png': 'place_x3_y2_f1',
    'WISH-2/wish2-a1b/accept1/shots/13-world.png': 'place_x3_y2_f1',
    'WISH-2/wish2-s5-reload/reload1/shots/10-world.png': 'place_x3_y2_f1',
    'WISH-2/wish2-s5-reload/reload1/shots/11-place.png': 'place_x3_y2_f1',
}
_DARKNESS_SHEET_CROPS = (
    'WISH-2/wish2-a1a/accept1/shots/06-sheet.png',
    'WISH-2/wish2-a1b/accept1/shots/06-sheet.png',
    'WISH-2/wish2-s5/accept2/shots/06-sheet.png',
    'WISH-2/wish2-s5-reload/reload1/shots/06-sheet.png',
)


def test_the_darkness_map_declares_the_spent_sheet_and_the_walked_world_crops():
    """The party-menu sheet is the spent-sheet bar, and each walked world crop names its place guard."""
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'darkness')
    assert 'sheet' in spec['guards']['camp_sheet_spent']['also']
    for path, guard in _DARKNESS_WORLD_LABELS.items():
        assert spec['labels'].get(path) == [guard], path


def test_the_darkness_guard_map_checks_clean_over_the_kept_crops():
    """Every kept Pools of Darkness crop that a guard matches is a state that guard declares."""
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    wanted = [*_DARKNESS_WORLD_LABELS, *_DARKNESS_SHEET_CROPS]
    if not all((root / path).is_file() for path in wanted):
        pytest.skip('the kept Pools of Darkness acceptance crops are not on this machine')
    assert guardmaps.main(['check', '--title', 'darkness']) == 0


def test_kept_interstitial_restore_and_again_crops_are_named_for_the_screen_they_show(tmp_path):
    """A crop's name gives the screen it shows, not the awaited state, for the copies an accept run keeps."""
    root = tmp_path / 'root'
    shot = _run(root, '1', 'run', 'ssb', 'title')
    names = {
        '15-camp_save_picker-journal-1.png': ('journal',),
        'title-credits-1.png': ('credits',),
        '21-camp-after-restore.png': ('camp',),
        '05-camp-again-1.png': ('camp',),
        '07-world-resumed.png': ('world',),
        '09-camp-again-1-journal-2.png': ('journal',),
        'journal-0.png': (),
        '03-post_write.png': ('loaded_menu',),
    }
    for name in names:
        _crop(shot.parent / name)
    states = {crop.relative.rsplit('/', 1)[1]: crop.states for crop in guardmaps.scan_crops(root)}
    assert {name: states[name] for name in names} == names


def test_silver_blades_line_one_item_list_identity_declares_the_party_menu_items():
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'ssb')
    rules = [rule for rule in spec['identity']['camp_items']
             if 'uc__u_l1_items' in rule['example'] or 'uc__c_l1_items' in rule['example']]
    assert len(rules) >= 2
    for rule in rules:
        assert 'items' in rule['also'], rule['example']


def _checks_clean_over(title, wanted):
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    if not all((root / path).is_file() for path in wanted):
        pytest.skip(f'the kept {title} acceptance crops are not on this machine')
    assert guardmaps.main(['check', '--title', title]) == 0


def test_the_curse_guard_map_checks_clean_over_the_kept_crops():
    _checks_clean_over('curse', ['628/263-amiga-live/accept1/shots/21-camp-after-restore.png'])


def test_the_silver_blades_guard_map_checks_clean_over_the_kept_crops():
    runs = [f'449/rb449-{run}/accept1/shots' for run in ('s3-3', 's3-4', 's4-1')]
    wanted = [f'{run}/{name}' for run in runs
              for name in ('title-credits-1.png', '15-camp_save_picker-journal-1.png')]
    wanted += [f'{run}/accept1/shots/05-items.png' for run in
               ('282/live3', '4/ssb-stage4-u', '4/ssb-stage4-c', '4/ssb-substitute-camp')]
    _checks_clean_over('ssb', wanted)


def test_the_darkness_loaded_menu_identity_matches_the_vault_party_and_not_the_other_parties():
    """Reads crops kept from live runs, so it skips on a machine without them."""
    from tools.amiga import screens
    from tools.registry import scratch

    root = scratch.cache_dir('acceptance')
    vault = root / 'WISH-6/wish6-accept1/wish6-accept1/shots/05-loaded_menu.png'
    others = [root / name for name in (
        'WISH-2/wish2-a2/measure1/shots/05-loaded_menu.png',
        'WISH-2/wish2-a3/accept1/shots/05-loaded_menu.png',
        'WISH-2/wish2-a4/measure-a4-33/shots/05-loaded_menu.png',
        'amiga-grab-crops/wish9-b1__05-loaded_menu.png')]
    if not vault.is_file() or not all(path.is_file() for path in others):
        pytest.skip('the kept Darkness loaded-menu crops are not on this machine')
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'darkness')
    rules = screens.rules_of(spec['identity']['loaded_menu'])

    def matching(crop):
        return {rule['example'] for rule in rules
                if screens.box_digests(crop, {tuple(rule['box'])})[tuple(rule['box'])] == rule['sha256']}

    assert matching(vault) == {'WISH-6/wish6-accept1/wish6-accept1/shots/05-loaded_menu.png'}
    for path in others:
        assert path.relative_to(root).as_posix() in matching(path)
        assert 'WISH-6/wish6-accept1/wish6-accept1/shots/05-loaded_menu.png' not in matching(path)


def _reload_run(root, name, *, shown=True, completed=True):
    run = root / '2' / name
    run.mkdir(parents=True, exist_ok=True)
    place = {'area': 5, 'facing': 1, 'x': 5, 'y': 10}
    (run / 'prepare.json').write_text(json.dumps({'title': 'darkness-reload', 'state_a': place}))
    shots = run / 'reload' / 'shots'
    for stem in ('10-world', '11-place'):
        _crop(shots / f'{stem}.png')
    # The summary records the crop at the path the run wrote, which need not be this machine's.
    (run / 'reload' / 'summary.json').write_text(json.dumps({
        'success': True, 'measure': False, 'completed': completed, 'argv': ['reload'],
        'reload': {'shown': shown, 'place': place, 'crop': '/elsewhere/shots/11-place.png'}}))
    return shots


def test_a_reload_runs_world_and_place_crops_are_named_for_the_square_it_proved(tmp_path):
    """A completed reload run's place crop, and a world crop with the same pixels, show the loaded square."""
    root = tmp_path / 'root'
    shots = _reload_run(root, 'proved')
    image = Image.open(shots / '10-world.png')
    image.putpixel((0, 0), (1, 1, 1))
    image.save(shots / '12-world.png')
    _reload_run(root, 'unshown', shown=False)
    _reload_run(root, 'unfinished', completed=False)
    states = {crop.relative: crop.states for crop in guardmaps.scan_crops(root)}
    assert states['2/proved/reload/shots/10-world.png'] == ('world', 'place_x5_y10_f1')
    assert states['2/proved/reload/shots/11-place.png'] == ('place', 'place_x5_y10_f1')
    assert states['2/proved/reload/shots/12-world.png'] == ('world',)
    for name in ('unshown', 'unfinished'):
        assert states[f'2/{name}/reload/shots/10-world.png'] == ('world',)
        assert states[f'2/{name}/reload/shots/11-place.png'] == ('place',)


def test_darkness_use_route_states_for_line_5_all_have_a_guard():
    """The `use 5 3 SYY` route keys line 5's row 2 and row 3, which need guards of their own."""
    from tools.amiga import route_camp, route_darkness

    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, 'darkness')
    route = route_camp.camp_title(route_darkness.DARKNESS, ('use 5 3 SYY',), 7, name='darkness')
    assert {'camp_items_5_row2', 'camp_items_5_row3'} <= route.strict
    assert route.strict <= spec['guards'].keys()

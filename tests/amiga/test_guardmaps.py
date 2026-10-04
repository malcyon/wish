"""Check guard-map ownership, export, and cross-title collisions on synthetic crops."""

import json

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
        assert all(set(rule) == {'box', 'sha256'}
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


def test_add_refuses_a_crop_owned_by_another_title(tmp_path, capsys):
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
        digest = screens.box_digests(crop.path, {box})[box]
        shown = 'camp_save_picker' in spec['labels'].get(crop.relative, crop.states)
        if crop.relative in pickers or shown:
            assert digest == rule['sha256'], crop.relative
        elif crop.relative in not_pickers:
            assert digest != rule['sha256'], crop.relative
        elif crop.states:
            assert digest != rule['sha256'], crop.relative


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

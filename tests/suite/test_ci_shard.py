"""Keep split CI coverage complete without importing files assigned elsewhere."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.suite.ci_shard import (
    inventory,
    literal_groups,
    make_plan,
    validate_plan,
    write_plan,
)

ROOT = Path(__file__).resolve().parents[2]


def suite(tmp_path, sources):
    for name, source in sources.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding='utf-8')
    return tuple(sources)


def test_transitive_groups_are_kept_together_and_plan_is_deterministic(tmp_path):
    files = suite(tmp_path, {
        'test_a.py': 'pytestmark = pytest.mark.xdist_group("one")',
        'test_b.py': 'pytestmark = [pytest.mark.xdist_group("one"), '
                     'pytest.mark.xdist_group(name="two")]',
        'test_c.py': 'pytestmark = pytest.mark.xdist_group("two")',
        'test_d.py': '',
        'test_new.py': '',
    })
    weights = {'test_a.py': 8, 'test_d.py': 4}
    plan = make_plan(tmp_path, files, weights)
    assert plan == make_plan(tmp_path, tuple(reversed(files)), weights)
    assert any({'test_a.py', 'test_b.py', 'test_c.py'} <= set(s)
               for s in plan['shards'])
    assert sum(plan['seconds']) == 30  # Three unseen files each receive six seconds.


@pytest.mark.parametrize('source', [
    'pytest.mark.xdist_group(group)', 'pytest.mark.xdist_group(**options)',
    'group = pytest.mark.xdist_group',
])
def test_dynamic_marks_fail_before_collection(source):
    with pytest.raises(ValueError, match='xdist_group'):
        literal_groups(source, 'test_dynamic.py')


@pytest.mark.parametrize('weight', [-1, float('inf'), float('nan'), True, '1'])
def test_invalid_weights_stop_planning(tmp_path, weight):
    files = suite(tmp_path, {'test_a.py': '', 'test_b.py': ''})
    with pytest.raises(ValueError, match='Invalid test weight'):
        make_plan(tmp_path, files, {'test_a.py': weight})


def test_zero_weights_still_produce_two_nonempty_shards(tmp_path):
    files = suite(tmp_path, {'test_a.py': '', 'test_b.py': ''})
    assert all(make_plan(tmp_path, files, dict.fromkeys(files, 0))['shards'])


def test_four_shards_cover_files_and_keep_transitive_groups(tmp_path):
    files = suite(tmp_path, {
        'test_a.py': 'pytest.mark.xdist_group("one")',
        'test_b.py': 'pytest.mark.xdist_group("one"); pytest.mark.xdist_group("two")',
        'test_c.py': 'pytest.mark.xdist_group("two")',
        'test_d.py': '', 'test_e.py': '', 'test_f.py': '',
    })
    plan = make_plan(tmp_path, files, {}, 4)
    assert len(plan['shards']) == 4
    assert all(plan['shards'])
    assert {name for shard in plan['shards'] for name in shard} == set(files)
    assert any({'test_a.py', 'test_b.py', 'test_c.py'} <= set(shard)
               for shard in plan['shards'])
    assert plan == make_plan(tmp_path, tuple(reversed(files)), {}, 4)


@pytest.mark.parametrize('count', [0, -1, True, 3])
def test_invalid_or_unfillable_shard_count_fails(tmp_path, count):
    files = suite(tmp_path, {'test_a.py': '', 'test_b.py': ''})
    with pytest.raises(ValueError):
        make_plan(tmp_path, files, {}, count)


def test_one_connected_unit_cannot_be_split(tmp_path):
    files = suite(tmp_path, {'test_a.py': 'pytest.mark.xdist_group("same")',
                             'test_b.py': 'pytest.mark.xdist_group("same")'})
    with pytest.raises(ValueError, match='independent test units'):
        make_plan(tmp_path, files, {})


@pytest.mark.parametrize('shards', [
    [['test_a.py'], ['test_a.py', 'test_b.py']],
    [['test_a.py'], ['test_c.py']], [[], ['test_a.py', 'test_b.py']],
])
def test_serialized_plan_rejects_missing_or_repeated_files(shards):
    with pytest.raises(ValueError):
        validate_plan({'version': 1, 'files': ['test_a.py', 'test_b.py'],
                       'shards': shards})


def test_serialized_plan_accepts_one_and_four_shards():
    files = [f'test_{index}.py' for index in range(4)]
    for shards in ([files], [[name] for name in files]):
        validate_plan({'version': 1, 'files': files, 'shards': shards})


def test_inventory_uses_tracked_files_patterns_and_directory_exclusions(tmp_path):
    suite(tmp_path, {
        'tests/test_a.py': '', 'tests/a_test.py': '', 'tests/helper.py': '',
        'tests/livetests/test_hidden.py': '', 'elsewhere/test_outside.py': '',
        'tests/test_untracked.py': '',
        'pyproject.toml': '[tool.pytest.ini_options]\ntestpaths=["tests"]\n'
                          'norecursedirs=["livetests"]\n',
    })
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    subprocess.run(['git', 'add', '.', ':!tests/test_untracked.py'],
                   cwd=tmp_path, check=True)
    assert inventory(tmp_path) == ('tests/a_test.py', 'tests/test_a.py')


def run_pytest(root, *args):
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    return subprocess.run(
        [sys.executable, '-m', 'pytest', '-p', 'xdist.plugin',
         '-p', 'tools.suite.ci_shard', '-q', *args],
        cwd=root, env=env, capture_output=True, text=True, timeout=60,
    )


def test_shards_cover_nodeids_and_do_not_import_other_files(tmp_path):
    files = suite(tmp_path, {
        'test_a.py': 'import pytest\n@pytest.mark.parametrize("x", [1,2])\n'
                     'def test_parameter(x): pass\n',
        'test_b.py': 'import pytest\n@pytest.mark.skip(reason="Synthetic skip")\n'
                     'def test_skipped(): pass\n',
        'test_new.py': 'def test_new(): pass\n',
        'test_ignored.py': 'raise RuntimeError("Existing ignore hook must win")\n',
        'conftest.py': 'collect_ignore = ["test_ignored.py"]\n',
    })
    files = tuple(name for name in files if name.startswith('test_'))
    plan = make_plan(tmp_path, files, {})
    plan_path = tmp_path / 'plan.json'
    write_plan(plan_path, plan)
    baseline = run_pytest(tmp_path, '--collect-only')
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    baseline_ids = {line for line in baseline.stdout.splitlines() if '::' in line}
    collected = []
    for index in range(2):
        result = run_pytest(tmp_path, '--collect-only', '--ci-shard-plan',
                            str(plan_path), '--ci-shard-index', str(index))
        assert result.returncode == 0, result.stdout + result.stderr
        collected.append({line for line in result.stdout.splitlines() if '::' in line})
    assert collected[0].isdisjoint(collected[1])
    assert collected[0] | collected[1] == baseline_ids
    excluded = next(name for name in plan['shards'][1] if name != 'test_ignored.py')
    (tmp_path / excluded).write_text('raise RuntimeError("Must not import")\n')
    result = run_pytest(tmp_path, '--ci-shard-plan', str(plan_path),
                        '--ci-shard-index', '0')
    assert result.returncode == 0, result.stdout + result.stderr


def test_unexpected_collected_files_fail(tmp_path):
    files = suite(tmp_path, {'test_a.py': 'def test_a(): pass',
                             'test_b.py': 'def test_b(): pass'})
    write_plan(tmp_path / 'plan.json', make_plan(tmp_path, files, {}))
    (tmp_path / 'test_new.py').write_text('def test_new(): pass')
    result = run_pytest(tmp_path, '--ci-shard-plan', 'plan.json',
                        '--ci-shard-index', '0')
    assert result.returncode != 0
    assert 'Collected files outside shard plan' in result.stderr


@pytest.mark.parametrize('index', ['-1', '4'])
def test_out_of_range_shard_index_fails_before_collection(tmp_path, index):
    files = suite(tmp_path, {f'test_{i}.py': f'def test_{i}(): pass'
                             for i in range(4)})
    write_plan(tmp_path / 'plan.json', make_plan(tmp_path, files, {}, 4))
    result = run_pytest(tmp_path, '--collect-only', '--ci-shard-plan', 'plan.json',
                        '--ci-shard-index', index)
    assert result.returncode != 0
    assert 'Shard index' in result.stderr


def test_loadgroup_keeps_shared_group_in_one_worker(tmp_path):
    body = ('import os, pathlib, pytest\n'
            'pytestmark = pytest.mark.xdist_group("shared")\n'
            'def test_worker():\n'
            ' pathlib.Path(__file__).with_suffix(".worker").write_text('
            'os.environ["PYTEST_XDIST_WORKER"])\n')
    files = suite(tmp_path, {'test_a.py': body, 'test_b.py': body,
                             'test_c.py': 'def test_other(): pass'})
    plan = make_plan(tmp_path, files, {})
    write_plan(tmp_path / 'plan.json', plan)
    index = next(i for i, shard in enumerate(plan['shards']) if 'test_a.py' in shard)
    result = run_pytest(tmp_path, '-n', '2', '--dist', 'loadgroup',
                        '--ci-shard-plan', 'plan.json', '--ci-shard-index', str(index))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / 'test_a.worker').read_text() == (
        tmp_path / 'test_b.worker').read_text()
    assert json.loads((tmp_path / 'plan.json').read_text()) == plan


def test_runtime_group_not_in_static_plan_fails(tmp_path):
    files = suite(tmp_path, {
        'test_a.py': 'def test_a(): pass', 'test_b.py': 'def test_b(): pass',
        'conftest.py': 'import pytest\n'
                       'def pytest_collection_modifyitems(items):\n'
                       ' for item in items:\n'
                       '  item.add_marker(pytest.mark.xdist_group("runtime"))\n',
    })
    write_plan(tmp_path / 'plan.json', make_plan(
        tmp_path, tuple(p for p in files if p.startswith('test_')), {}))
    result = run_pytest(tmp_path, '--ci-shard-plan', 'plan.json',
                        '--ci-shard-index', '0')
    assert result.returncode != 0
    assert 'Unplanned xdist_group' in result.stderr


def measured_profile():
    return {'schema_version': 1, 'worker': 'main', 'exit_code': 0,
            'files': {'tests/test_a.py': {'setup_seconds': 1.0, 'call_seconds': 2.5,
                                         'teardown_seconds': 0.25, 'reports': 3}}}


def test_weights_cli_sums_main_phases_and_preserves_other_platforms(tmp_path):
    from tools.suite.ci_shard import main

    profile = tmp_path / 'pytest-main.json'
    profile.write_text(json.dumps(measured_profile()))
    (tmp_path / 'resources.json').write_text(json.dumps({
        'schema_version': 1, 'exit_code': 0, 'cleanup_complete': True,
    }))
    # A worker file alongside the input must never be included in the sum.
    (tmp_path / 'pytest-gw0.json').write_text(json.dumps(measured_profile()))
    output = tmp_path / 'weights.json'
    arguments = ['--profile', str(profile), '--source-sha', 'a' * 40,
                 '--run-id', '123', '--output', str(output)]
    assert main([*arguments, '--weight-key', 'linux']) == 0
    linux = json.loads(output.read_text())['platforms']['linux']
    assert linux == {'weights': {'tests/test_a.py': 3.75},
                     'source_sha': 'a' * 40, 'run_id': '123'}
    assert main([*arguments, '--weight-key', 'windows']) == 0
    assert json.loads(output.read_text())['platforms'] == {
        'linux': linux, 'windows': linux,
    }


@pytest.mark.parametrize('change', [
    {'worker': 'gw0'}, {'exit_code': 1}, {'exit_code': False},
    {'schema_version': 2}, {'files': {}},
])
def test_profile_rejects_worker_failed_or_invalid_input(change):
    from tools.suite.ci_shard import profile_weights

    with pytest.raises(ValueError):
        profile_weights(measured_profile() | change)


@pytest.mark.parametrize('value', [None, -1, float('nan'), float('inf'), True, '3'])
def test_profile_rejects_invalid_phase_durations(value):
    from tools.suite.ci_shard import profile_weights

    profile = measured_profile()
    profile['files']['tests/test_a.py']['call_seconds'] = value
    with pytest.raises(ValueError):
        profile_weights(profile)


@pytest.mark.parametrize('change', [
    {'source_sha': 'unverified'}, {'run_id': 0}, {'run_id': True},
    {'weights': {'../test_a.py': 1}}, {'weights': {'test_a.py': float('inf')}},
])
def test_invalid_existing_weights_are_not_overwritten(tmp_path, change):
    from tools.suite.ci_shard import main

    profile = tmp_path / 'pytest-main.json'
    profile.write_text(json.dumps(measured_profile()))
    (tmp_path / 'resources.json').write_text(json.dumps({
        'schema_version': 1, 'exit_code': 0, 'cleanup_complete': True,
    }))
    output = tmp_path / 'weights.json'
    data = {'version': 1, 'platforms': {'existing': {
        'weights': {'tests/test_a.py': 1}, 'source_sha': 'a' * 40, 'run_id': 123,
    } | change}}
    original = json.dumps(data)
    output.write_text(original)
    with pytest.raises(SystemExit) as error:
        main(['--profile', str(profile), '--source-sha', 'a' * 40,
              '--run-id', '123', '--output', str(output), '--weight-key', 'new'])
    assert error.value.code == 2
    assert output.read_text() == original


def test_cli_rejects_worker_filename_even_with_main_content(tmp_path):
    from tools.suite.ci_shard import main

    profile = tmp_path / 'pytest-gw0.json'
    profile.write_text(json.dumps(measured_profile()))
    (tmp_path / 'resources.json').write_text(json.dumps({
        'schema_version': 1, 'exit_code': 0, 'cleanup_complete': True,
    }))
    output = tmp_path / 'weights.json'
    with pytest.raises(SystemExit):
        main(['--profile', str(profile), '--source-sha', 'a' * 40,
              '--run-id', '123', '--output', str(output), '--weight-key', 'new'])
    assert not output.exists()


@pytest.mark.parametrize('change', [
    {'exit_code': 1}, {'cleanup_complete': False}, {'schema_version': 2},
])
def test_weights_cli_rejects_incomplete_resource_report(tmp_path, change):
    from tools.suite.ci_shard import main

    profile = tmp_path / 'pytest-main.json'
    profile.write_text(json.dumps(measured_profile()))
    (tmp_path / 'resources.json').write_text(json.dumps({
        'schema_version': 1, 'exit_code': 0, 'cleanup_complete': True,
    } | change))
    output = tmp_path / 'weights.json'
    with pytest.raises(SystemExit):
        main(['--profile', str(profile), '--source-sha', 'a' * 40,
              '--run-id', '123', '--output', str(output), '--weight-key', 'new'])
    assert not output.exists()


def profile_bundle(tmp_path, index, *, files=None, run_attempt='1', shard_count=2):
    source = tmp_path / f'shard-{index}'
    source.mkdir()
    names = files or (f'tests/test_{index}.py',)
    profile = measured_profile()
    profile['collected_tests'] = 1
    profile['files'] = {name: {
        'setup_seconds': 1.0, 'call_seconds': 2.0,
        'teardown_seconds': 0.5, 'reports': 3,
    } for name in names}
    (source / 'pytest-main.json').write_text(json.dumps(profile))
    (source / 'junit.xml').write_text('<testsuites><testsuite><testcase/></testsuite></testsuites>')
    (source / 'resources.json').write_text(json.dumps({
        'schema_version': 1, 'exit_code': 0, 'cleanup_complete': True,
        'run_sha': 'a' * 40, 'run_id': '123', 'run_attempt': run_attempt,
        'full_shard_run': True,
        'shard': {'index': index, 'weight_key': 'linux',
                  'selected_files': [f'tests/test_{index}.py'],
                  'source_sha': 'b' * 40, 'run_id': '99'},
    }))
    (source / 'shard-plan.json').write_text(json.dumps({
        'version': 1,
        'files': [f'tests/test_{i}.py' for i in range(shard_count)],
        'shards': [[f'tests/test_{i}.py'] for i in range(shard_count)],
        'seconds': [1] * shard_count, 'groups': {},
    }))
    return source / 'pytest-main.json'


def test_multi_profile_import_combines_disjoint_main_reports(tmp_path):
    from tools.suite.ci_shard import combined_profile_weights

    paths = [profile_bundle(tmp_path, index) for index in range(2)]
    assert combined_profile_weights(paths, 'a' * 40, '123', 'linux') == {
        'tests/test_0.py': 3.5, 'tests/test_1.py': 3.5,
    }


def test_single_new_profile_rejects_incomplete_run(tmp_path):
    from tools.suite.ci_shard import combined_profile_weights

    path = profile_bundle(tmp_path, 0)
    resources = path.with_name('resources.json')
    data = json.loads(resources.read_text())
    data['full_shard_run'] = False
    resources.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='complete CI shard run'):
        combined_profile_weights([path], 'a' * 40, '123', 'linux')


def test_one_report_from_four_shard_run_is_incomplete(tmp_path):
    from tools.suite.ci_shard import combined_profile_weights

    path = profile_bundle(tmp_path, 2, shard_count=4)
    with pytest.raises(ValueError, match='Incomplete or inconsistent shard profile set'):
        combined_profile_weights([path], 'a' * 40, '123', 'linux')


def test_complete_one_shard_modern_run_is_accepted(tmp_path):
    from tools.suite.ci_shard import combined_profile_weights

    path = profile_bundle(tmp_path, 0, shard_count=1)
    assert combined_profile_weights([path], 'a' * 40, '123', 'linux') == {
        'tests/test_0.py': 3.5,
    }


@pytest.mark.parametrize('mutation', [
    'duplicate_file', 'missing_shard', 'wrong_sha', 'wrong_attempt',
    'wrong_selected', 'unsafe_path', 'failed_resource',
])
def test_multi_profile_import_rejects_inconsistent_reports(tmp_path, mutation):
    from tools.suite.ci_shard import combined_profile_weights

    paths = [profile_bundle(tmp_path, index) for index in range(2)]
    if mutation == 'missing_shard':
        paths.pop()
    else:
        target = paths[1]
        if mutation in ('duplicate_file', 'unsafe_path'):
            data = json.loads(target.read_text())
            name = 'tests/test_0.py' if mutation == 'duplicate_file' else '../escape.py'
            data['files'] = {name: next(iter(data['files'].values()))}
            target.write_text(json.dumps(data))
        elif mutation == 'wrong_selected':
            path = target.with_name('resources.json')
            data = json.loads(path.read_text())
            data['shard']['selected_files'] = ['tests/test_0.py']
            path.write_text(json.dumps(data))
        else:
            path = target.with_name('resources.json')
            data = json.loads(path.read_text())
            field, value = {
                'wrong_sha': ('run_sha', 'b' * 40),
                'wrong_attempt': ('run_attempt', '2'),
                'failed_resource': ('exit_code', 1),
            }[mutation]
            data[field] = value
            path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        combined_profile_weights(paths, 'a' * 40, '123', 'linux')


def test_the_committed_weights_do_not_name_the_deleted_winvmsettle_test():
    path = Path(__file__).resolve().parents[2] / 'tools' / 'suite' / 'ci_weights.json'
    data = json.loads(path.read_text())
    for platform in data['platforms'].values():
        assert 'tests/amiga/test_winvmsettle.py' not in platform['weights']

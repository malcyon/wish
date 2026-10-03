"""Plan deterministic pytest shards and filter files before their import."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import math
import re
import statistics
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

import pytest

_DEFAULT_EXCLUDES = (
    '*.egg', '.*', '_darcs', 'build', 'CVS', 'dist', 'node_modules',
    'venv', '{arch}',
)


def inventory(root: Path) -> tuple[str, ...]:
    """Read tracked pytest filenames using the repository's collection settings."""
    config_path = root / 'pyproject.toml'
    config = tomllib.loads(config_path.read_text()).get('tool', {}).get(
        'pytest', {}).get('ini_options', {}) if config_path.exists() else {}
    patterns = config.get('python_files', ['test_*.py', '*_test.py'])
    excluded = config.get('norecursedirs', _DEFAULT_EXCLUDES)
    testpaths = config.get('testpaths', ['tests'])
    tracked = subprocess.run(
        ['git', 'ls-files', '-z'], cwd=root, check=True, capture_output=True,
    ).stdout.decode().split('\0')
    result = []
    for name in tracked:
        path = PurePosixPath(name)
        if not any(path == PurePosixPath(base) or PurePosixPath(base) in path.parents
                   for base in testpaths):
            continue
        if any(fnmatch.fnmatchcase(part, pattern)
               for part in path.parts[:-1] for pattern in excluded):
            continue
        if any(fnmatch.fnmatchcase(path.name, pattern) for pattern in patterns):
            result.append(name)
    return tuple(sorted(result))


def literal_groups(source: str, filename: str) -> frozenset[str]:
    """Find literal group marks without importing test modules."""
    tree = ast.parse(source, filename=filename)
    groups = set()
    calls = {id(node.func): node for node in ast.walk(tree)
             if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == 'xdist_group'):
            continue
        call = calls.get(id(node))
        if call is None:
            raise ValueError(f'Dynamic xdist_group marker in {filename}')
        args = call.args
        keywords = call.keywords
        if len(args) == 1 and not keywords:
            value = args[0]
        elif not args and len(keywords) == 1 and keywords[0].arg == 'name':
            value = keywords[0].value
        else:
            raise ValueError(f'Unsupported xdist_group marker in {filename}')
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            raise ValueError(f'Dynamic xdist_group marker in {filename}')
        groups.add(value.value)
    return frozenset(groups)


def _relative_file(name: str) -> bool:
    path = PurePosixPath(name)
    return (bool(name) and not path.is_absolute() and '..' not in path.parts
            and '\\' not in name and path.as_posix() == name)


def make_plan(root: Path, files: tuple[str, ...], weights: dict[str, float],
              shard_count: int = 2) -> dict:
    """Keep connected groups together and assign longest units to the lighter shard."""
    if len(files) != len(set(files)) or any(not _relative_file(p) for p in files):
        raise ValueError('Inventory must contain unique repository-relative paths')
    if type(shard_count) is not int or shard_count < 1:
        raise ValueError('Shard count must be a positive integer')
    for name, value in weights.items():
        if (not _relative_file(name) or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise ValueError(f'Invalid test weight: {name!r} = {value!r}')
    positive = [value for value in weights.values() if value > 0]
    fallback = statistics.median(positive) if positive else 1.0
    parents = {name: name for name in files}

    def leader(name):
        while parents[name] != name:
            parents[name] = parents[parents[name]]
            name = parents[name]
        return name

    groups = {}
    memberships = {}
    for name in sorted(files):
        memberships[name] = sorted(literal_groups(
            (root / name).read_text(encoding="utf-8"), name))
        for group in memberships[name]:
            if group in groups:
                parents[leader(name)] = leader(groups[group])
            else:
                groups[group] = name
    units = {}
    for name in sorted(files):
        units.setdefault(leader(name), []).append(name)
    ordered = sorted(units.values(), key=lambda names: (
        -sum(weights.get(name, fallback) for name in names), tuple(names)))
    if len(ordered) < shard_count:
        raise ValueError('Not enough independent test units for nonempty shards')
    shards = [[] for _ in range(shard_count)]
    totals = [0.0] * shard_count
    for names in ordered:
        # Give each shard a unit even when every measured weight is zero.
        index = min(range(shard_count), key=lambda i: (bool(shards[i]), totals[i], i))
        shards[index].extend(names)
        totals[index] += sum(weights.get(name, fallback) for name in names)
    plan = {'version': 1, 'files': sorted(files),
            'shards': [sorted(shard) for shard in shards], 'seconds': totals,
            'groups': memberships}
    validate_plan(plan)
    return plan


def validate_plan(plan: dict) -> None:
    """Reject incomplete, overlapping, empty, or unsafe serialized plans."""
    if plan.get('version') != 1:
        raise ValueError('Unsupported shard plan version')
    files, shards = plan.get('files'), plan.get('shards')
    if (not isinstance(files, list) or not all(isinstance(p, str) for p in files)
            or len(files) != len(set(files))
            or not all(_relative_file(p) for p in files)
            or not isinstance(shards, list) or not shards
            or not all(isinstance(s, list) and s for s in shards)
            or not all(isinstance(p, str) for s in shards for p in s)):
        raise ValueError('Invalid shard inventory')
    joined = [name for shard in shards for name in shard]
    if len(joined) != len(set(joined)) or set(joined) != set(files):
        raise ValueError('Shard files must be disjoint and cover the inventory exactly')
    groups = plan.get('groups', {})
    if not isinstance(groups, dict) or any(
            name not in files or not isinstance(values, list)
            or not all(isinstance(value, str) for value in values)
            for name, values in groups.items()):
        raise ValueError('Invalid group membership')
    owners = {}
    for index, shard in enumerate(shards):
        for name in shard:
            for group in groups.get(name, []):
                if group in owners and owners[group] != index:
                    raise ValueError(f'Group {group!r} crosses shards')
                owners[group] = index


def write_plan(path: Path, plan: dict) -> None:
    """Serialize a checked plan for cheap reading in each pytest worker."""
    validate_plan(plan)
    path.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')


def pytest_addoption(parser):
    group = parser.getgroup('ci-shard')
    group.addoption('--ci-shard-plan', help='Precomputed shard JSON plan')
    group.addoption('--ci-shard-index', type=int)


def pytest_configure(config):
    path = config.getoption('--ci-shard-plan')
    index = config.getoption('--ci-shard-index')
    if path is None and index is None:
        return
    if path is None or index is None:
        raise pytest.UsageError('Both --ci-shard-plan and --ci-shard-index are required')
    try:
        plan = json.loads(Path(path).read_text(encoding='utf-8'))
        validate_plan(plan)
        if index < 0 or index >= len(plan['shards']):
            raise ValueError(f'Shard index {index} is outside 0..{len(plan["shards"]) - 1}')
    except (OSError, ValueError, TypeError, AttributeError) as error:
        raise pytest.UsageError(f'Invalid shard plan: {error}') from error
    config.pluginmanager.register(_Selection(config.rootpath, plan, index))


class _Selection:
    def __init__(self, root, plan, index):
        self.root = root
        self.files = set(plan['files'])
        self.selected = set(plan['shards'][index])
        self.groups = plan.get('groups', {})

    def relative(self, path):
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return None

    def pytest_ignore_collect(self, collection_path):
        name = self.relative(collection_path)
        if name in self.files and name not in self.selected:
            return True
        return None

    @pytest.hookimpl(wrapper=True)
    def pytest_collection_modifyitems(self, items):
        result = yield
        for item in items:
            name = self.relative(item.path)
            for marker in item.iter_markers('xdist_group'):
                group = marker.args[0] if marker.args else marker.kwargs.get('name')
                if group not in self.groups.get(name, []):
                    raise pytest.UsageError(
                        f'Unplanned xdist_group {group!r} in {name}')
        unexpected = sorted({str(item.path) for item in items
                             if self.relative(item.path) not in self.selected})
        if unexpected:
            raise pytest.UsageError('Collected files outside shard plan: '
                                    + ', '.join(unexpected))
        return result


def _seconds(value) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0)


def validate_weights(data: dict) -> None:
    """Check platform weights and the provenance required to reproduce them."""
    if (not isinstance(data, dict) or type(data.get('version')) is not int
            or data['version'] != 1 or not isinstance(data.get('platforms'), dict)):
        raise ValueError('Invalid weights schema')
    for key, platform in data['platforms'].items():
        if not isinstance(key, str) or not key.strip() or not isinstance(platform, dict):
            raise ValueError('Invalid weights platform')
        sha = platform.get('source_sha')
        run_id = platform.get('run_id')
        if (not isinstance(sha, str) or re.fullmatch(r'[0-9a-f]{40}', sha) is None
                or isinstance(run_id, bool) or not isinstance(run_id, (int, str))
                or re.fullmatch(r'[1-9][0-9]*', str(run_id)) is None):
            raise ValueError(f'Invalid weights provenance for {key}')
        weights = platform.get('weights')
        if (not isinstance(weights, dict) or not weights
                or any(not isinstance(name, str) or not _relative_file(name)
                       or not _seconds(value) for name, value in weights.items())):
            raise ValueError(f'Invalid weights for {key}')


def profile_weights(profile: dict) -> dict[str, float]:
    """Use only successful main-process reports, which already include workers."""
    if (not isinstance(profile, dict) or type(profile.get('schema_version')) is not int
            or profile['schema_version'] != 1 or profile.get('worker') != 'main'
            or type(profile.get('exit_code')) is not int or profile['exit_code'] != 0
            or not isinstance(profile.get('files'), dict) or not profile['files']):
        raise ValueError('Expected a successful version 1 pytest-main.json profile')
    weights = {}
    for name, row in profile['files'].items():
        if not isinstance(name, str) or not _relative_file(name) or not isinstance(row, dict):
            raise ValueError('Invalid profile file entry')
        values = [row.get(phase + '_seconds') for phase in ('setup', 'call', 'teardown')]
        if (not all(_seconds(value) for value in values)
                or type(row.get('reports')) is not int or row['reports'] <= 0):
            raise ValueError(f'Invalid profile durations for {name}')
        total = sum(values)
        if not _seconds(total):
            raise ValueError(f'Invalid profile duration total for {name}')
        weights[name] = total
    return dict(sorted(weights.items()))


def combined_profile_weights(paths: list[Path], source_sha: str, run_id: str,
                             weight_key: str) -> dict[str, float]:
    """Combine one successful main report from every shard in a CI run."""
    if not paths:
        raise ValueError('At least one main profile is required')
    plans = []
    indexes = set()
    weights = {}
    provenance = set()
    attempts = set()
    for path in paths:
        if path.name != 'pytest-main.json':
            raise ValueError('Profile must be pytest-main.json; worker reports duplicate its costs')
        resources = json.loads(path.with_name('resources.json').read_text(encoding='utf-8'))
        if (not isinstance(resources, dict)
                or type(resources.get('schema_version')) is not int
                or resources['schema_version'] != 1
                or type(resources.get('exit_code')) is not int
                or resources['exit_code'] != 0
                or resources.get('cleanup_complete') is not True):
            raise ValueError('Expected successful resources.json with complete cleanup')
        profile = json.loads(path.read_text(encoding='utf-8'))
        report = profile_weights(profile)
        modern = any(key in resources for key in ('run_sha', 'run_id', 'full_shard_run'))
        if modern:
            if resources.get('run_sha') != source_sha or str(resources.get('run_id')) != run_id:
                raise ValueError('Profile run/SHA provenance does not match requested weights')
        if len(paths) > 1 or modern:
            if type(profile.get('collected_tests')) is not int or profile['collected_tests'] < 1:
                raise ValueError('Incomplete main profile collection')
            if (re.fullmatch(r'[1-9][0-9]*', str(resources.get('run_attempt'))) is None
                    or resources.get('full_shard_run') is not True):
                raise ValueError('Profile is not a complete CI shard run')
            junit = ET.parse(path.with_name('junit.xml')).getroot()
            if len(junit.findall('.//testcase')) != profile['collected_tests']:
                raise ValueError('JUnit cases disagree with collected test count')
            shard = resources.get('shard')
            if (not isinstance(shard, dict) or shard.get('weight_key') != weight_key
                    or type(shard.get('index')) is not int):
                raise ValueError('Missing or inconsistent shard provenance')
            plan = json.loads(path.with_name('shard-plan.json').read_text(encoding='utf-8'))
            validate_plan(plan)
            index = shard['index']
            if shard.get('count', len(plan['shards'])) != len(plan['shards']):
                raise ValueError('Profile shard count disagrees with plan')
            if index < 0 or index >= len(plan['shards']) or index in indexes:
                raise ValueError('Duplicate or invalid profile shard index')
            selected = shard.get('selected_files')
            if (not isinstance(selected, list) or not all(isinstance(name, str) for name in selected)
                    or len(selected) != len(set(selected))
                    or set(selected) != set(plan['shards'][index])):
                raise ValueError('Profile selected files disagree with shard plan')
            if set(report) != set(plan['shards'][index]):
                raise ValueError('Profile files do not cover the selected shard')
            indexes.add(index)
            plans.append(plan)
            provenance.add((shard.get('source_sha'), str(shard.get('run_id'))))
            attempts.add(resources.get('run_attempt'))
        overlap = weights.keys() & report.keys()
        if overlap:
            raise ValueError(f'Duplicate profile file: {sorted(overlap)[0]}')
        weights.update(report)
    if plans:
        if (indexes != set(range(len(plans[0]['shards'])))
                or any(plan != plans[0] for plan in plans[1:])
                or len(provenance) != 1 or len(attempts) != 1):
            raise ValueError('Incomplete or inconsistent shard profile set')
    return dict(sorted(weights.items()))


def main(argv=None):
    """Merge measured main-process durations into a platform weights document."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path, action='append')
    parser.add_argument('--weight-key', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        weights = combined_profile_weights(args.profile, args.source_sha, args.run_id,
                                           args.weight_key)
        data = {'version': 1, 'platforms': {}}
        if args.output.exists():
            data = json.loads(args.output.read_text(encoding='utf-8'))
            validate_weights(data)
        data['platforms'][args.weight_key] = {
            'weights': weights, 'source_sha': args.source_sha, 'run_id': args.run_id,
        }
        validate_weights(data)
        args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n',
                               encoding='utf-8')
    except (OSError, ValueError, TypeError, ET.ParseError) as error:
        parser.error(str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

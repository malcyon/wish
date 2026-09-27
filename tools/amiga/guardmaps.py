#!/usr/bin/env python3
"""Build and check Amiga screen guards against saved WinUAE crops."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from PIL import Image  # noqa: E402

from tools.amiga import amigashots, screens  # noqa: E402
from tools.registry import scratch  # noqa: E402

FILES = {'pool': 'pool', 'curse': 'curse', 'darkness': 'darkness',
         'ssb': 'silver_blades'}


@dataclass(frozen=True)
class Crop:
    path: pathlib.Path
    relative: str
    title: str | None
    states: tuple[str, ...]


def _title(run: pathlib.Path) -> str | None:
    try:
        manifest = json.loads((run / 'prepare.json').read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    title = manifest.get('title')
    if title == 'darkness-reload':
        title = 'darkness'
    if title is None and 'published_df1' in manifest:
        title = 'ssb'
    return title if title in FILES else None


def _states(path: pathlib.Path) -> tuple[str, ...]:
    try:
        summary = json.loads((path.parent.parent / 'summary.json').read_text())
    except (OSError, ValueError):
        return ()
    if not isinstance(summary, dict) or not summary.get('success') or summary.get('measure'):
        return ()
    state = re.sub(r'^\d+-', '', path.stem)
    if state in ('post_write', 'post-write'):
        state = 'loaded_menu'
    return (state,)


def scan_crops(root: pathlib.Path) -> list[Crop]:
    """Read eligible saved crops and their manifest ownership."""
    paths = sorted((*root.glob('*/*/*/shots/*.png'), *root.glob('amiga-grab-crops/*.png')))
    runs: dict[pathlib.Path, str | None] = {}
    crops = []
    for path in paths:
        if path.name.endswith('.raw.png'):
            continue
        try:
            with Image.open(path) as image:
                if image.size != amigashots.CLIENT:
                    continue
        except OSError:
            continue
        parts = path.relative_to(root).parts
        run = root / parts[0] / parts[1] if len(parts) >= 5 else None
        if run is not None and run not in runs:
            runs[run] = _title(run)
        title = runs.get(run) if run else None
        crops.append(Crop(path, path.relative_to(root).as_posix(), title,
                          _states(path) if title else ()))
    return crops


def _path(maps: pathlib.Path, title: str) -> pathlib.Path:
    return maps / f'guards_{FILES[title]}.json'


def _load(maps: pathlib.Path, title: str) -> dict:
    path = _path(maps, title)
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {'labels', 'guards', 'identity'}:
        raise ValueError(f'{path}: expected labels, guards and identity')
    if not isinstance(data['labels'], dict):
        raise ValueError(f'{path}: labels must be a map')
    for name, states in data['labels'].items():
        if not isinstance(name, str) or not isinstance(states, list) or not states or not all(isinstance(s, str) for s in states):
            raise ValueError(f'{path}: invalid label {name!r}')
    for kind in ('guards', 'identity'):
        if not isinstance(data[kind], dict):
            raise ValueError(f'{path}: {kind} must be a map')
        for state, rule in data[kind].items():
            if (not isinstance(state, str) or not isinstance(rule, dict)
                    or set(rule) != {'box', 'sha256', 'example', 'also'}
                    or not isinstance(rule['box'], list) or len(rule['box']) != 4
                    or not all(type(n) is int for n in rule['box'])
                    or not isinstance(rule['sha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', rule['sha256'])
                    or rule['example'] is not None and not isinstance(rule['example'], str)
                    or not isinstance(rule['also'], list)
                    or not all(isinstance(s, str) for s in rule['also'])):
                raise ValueError(f'{path}: invalid {kind}/{state}')
    return data


def _save(path: pathlib.Path, data: dict) -> None:
    temp = path.with_name(path.name + '.tmp')
    try:
        temp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _shown(crop: Crop, title: str, spec: dict) -> set[str]:
    labels = set(spec['labels'].get(crop.relative, ()))
    return labels | (set(crop.states) if crop.title == title else set())


def _owned(crop: Crop, title: str, spec: dict) -> bool:
    return crop.title == title or crop.relative in spec['labels']


def _check(args, crops: list[Crop]) -> int:
    print(f'{len(crops)} crops')
    failed = False
    specs = {title: _load(args.maps, title) for title in args.title or FILES}
    boxes = {tuple(rule['box']) for spec in specs.values() for kind in ('guards', 'identity')
             for rule in spec[kind].values()}
    digests = {crop.relative: screens.box_digests(crop.path, boxes) for crop in crops}
    for title in args.title or FILES:
        spec = specs[title]
        problems = 0
        for kind in ('guards', 'identity'):
            for state, rule in spec[kind].items():
                hits = misses = 0
                for crop in crops:
                    shown = _shown(crop, title, spec)
                    match = digests[crop.relative][tuple(rule['box'])] == rule['sha256']
                    if match:
                        hits += 1
                        if not _owned(crop, title, spec) or shown and state not in shown and not shown.intersection(rule['also']):
                            print(f'{title} {kind}/{state} collision {crop.relative}')
                            problems += 1
                    elif _owned(crop, title, spec) and state in shown:
                        misses += 1
                example = rule['example']
                if example and (example not in digests or digests[example][tuple(rule['box'])] != rule['sha256']):
                    print(f'{title} {kind}/{state} stale {example}')
                    problems += 1
                print(f"{title} {kind}/{state} {rule['box']} hits {hits} misses {misses}")
        print(f'{title}: {problems} problems' if problems else f'{title}: clean')
        failed |= problems != 0
    return int(failed)


def _add(args, crops: list[Crop]) -> int:
    spec = _load(args.maps, args.title) if _path(args.maps, args.title).exists() else {'labels': {}, 'guards': {}, 'identity': {}}
    crop = args.crop.resolve()
    selected = next((c for c in crops if c.path.resolve() == crop), None)
    if selected is None:
        raise ValueError(f'{crop} is outside the scanned crops')
    box = [int(n) for n in args.box.split(',')]
    if args.state in spec[args.map] and not args.replace:
        raise ValueError(f'{args.state} already exists; pass --replace')
    negatives = [c.path for c in crops if c.path != crop and
                 (not _owned(c, args.title, spec) or
                  _shown(c, args.title, spec) and args.state not in _shown(c, args.title, spec)
                  and not _shown(c, args.title, spec).intersection(args.also))]
    rule = screens.checked_rule(crop, box, args.state, negatives)
    spec[args.map][args.state] = {**rule, 'example': selected.relative, 'also': sorted(args.also)}
    _save(_path(args.maps, args.title), spec)
    print(json.dumps({args.state: spec[args.map][args.state]}, sort_keys=True))
    return 0


def _export(args) -> int:
    spec = _load(args.maps, args.title)
    args.out.mkdir(parents=True, exist_ok=True)
    for kind in ('guards', 'identity'):
        if (args.out / f'{kind}.json').exists():
            raise ValueError(f'{args.out / (kind + ".json")} exists')
    for kind in ('guards', 'identity'):
        rules = {state: {'box': rule['box'], 'sha256': rule['sha256']}
                 for state, rule in spec[kind].items()}
        (args.out / f'{kind}.json').write_text(json.dumps(rules, indent=2, sort_keys=True) + '\n')
    return 0


def _grabs(args) -> int:
    out = args.root / 'amiga-grab-crops'
    copied = cropped = failed = kept = 0
    for source in sorted(args.source.rglob('*.png')):
        target = out / ('__'.join(source.relative_to(args.source).parts))
        if target.exists():
            kept += 1
            continue
        try:
            with Image.open(source) as image:
                size = image.size
                if size == amigashots.CLIENT:
                    out.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
                    copied += 1
                elif size[0] > 720 and size[1] > 568:
                    amigashots.crop(source, target)
                    cropped += 1
                else:
                    failed += 1
        except (LookupError, OSError):
            failed += 1
    print(f'copied {copied} cropped {cropped} failed {failed} kept {kept}')
    return 0


def _diff(args) -> int:
    with Image.open(args.a) as a, Image.open(args.b) as b:
        if a.size != b.size:
            raise ValueError('images differ in size')
        if args.rows:
            y0, y1 = (int(n) for n in args.rows.split(','))
        else:
            y0, y1 = 0, a.height
        pa, pb = a.convert('RGB').load(), b.convert('RGB').load()
        points = [(x, y) for y in range(y0, y1) for x in range(a.width) if pa[x, y] != pb[x, y]]
        if points:
            print(f'{min(x for x, _ in points)},{min(y for _, y in points)},{max(x for x, _ in points) + 1},{max(y for _, y in points) + 1}')
        else:
            print('identical')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, default=scratch.cache_dir('acceptance'))
    parser.add_argument('--maps', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check')
    check.add_argument('--title', choices=FILES, action='append')
    add = sub.add_parser('add')
    add.add_argument('--title', choices=FILES, required=True)
    add.add_argument('--map', choices=('guards', 'identity'), required=True)
    add.add_argument('--state', required=True)
    add.add_argument('--crop', required=True, type=pathlib.Path)
    add.add_argument('--box', required=True)
    add.add_argument('--also', action='append', default=[])
    add.add_argument('--replace', action='store_true')
    export = sub.add_parser('export')
    export.add_argument('--title', choices=FILES, required=True)
    export.add_argument('--out', required=True, type=pathlib.Path)
    grabs = sub.add_parser('grabs')
    grabs.add_argument('source', type=pathlib.Path)
    diff = sub.add_parser('diff')
    diff.add_argument('a', type=pathlib.Path)
    diff.add_argument('b', type=pathlib.Path)
    diff.add_argument('--rows')
    args = parser.parse_args(argv)
    try:
        if args.command == 'grabs':
            return _grabs(args)
        if args.command == 'diff':
            return _diff(args)
        if args.command == 'export':
            return _export(args)
        crops = scan_crops(args.root)
        return _check(args, crops) if args.command == 'check' else _add(args, crops)
    except (OSError, ValueError, screens.RouteError) as error:
        print(f'guardmaps: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

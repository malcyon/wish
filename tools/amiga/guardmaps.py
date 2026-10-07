#!/usr/bin/env python3
"""Build and check Amiga screen guards against saved WinUAE crops."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import tempfile
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
    return title if isinstance(title, str) and title in FILES else None


def _states(path: pathlib.Path) -> tuple[str, ...]:
    """Give the screen a crop's name says it shows, including kept copies of interstitials and re-grabs."""
    try:
        summary = json.loads((path.parent.parent / 'summary.json').read_text())
    except (OSError, ValueError):
        return ()
    if not isinstance(summary, dict) or not summary.get('success') or summary.get('measure'):
        return ()
    # A diagnose run names its crops after the grab count (00-boot-NN), not after a screen.
    argv = summary.get('argv')
    if isinstance(argv, list) and argv and argv[0] == 'diagnose':
        return ()
    state = re.sub(r'^\d+-', '', path.stem)
    for pattern in (r'([a-z0-9_]+)-again-\d+',
                    r'([a-z0-9_-]+)-after-\d+', r'.+-([a-z][a-z0-9_]*)-\d+',
                    r'([a-z0-9_]+)-(?:after-restore|resumed)'):
        found = re.fullmatch(pattern, state)
        if found:
            state = found.group(1)
            break
    else:
        if re.fullmatch(r'journal-\d+', state):
            return ()
    if state in ('post_write', 'post-write'):
        state = 'loaded_menu'
    return (state,)


def scan_crops(root: pathlib.Path) -> list[Crop]:
    """Read eligible saved crops and their manifest ownership."""
    paths = sorted((*root.glob('*/*/*/shots/*.png'), *root.glob('amiga-grab-crops/*.png')))
    runs: dict[pathlib.Path, str | None] = {}
    crops = []
    # Opening every PNG to read its size dominates a scan of the acceptance
    # cache, so a file whose stat stamp matches its digest-cache entry reuses
    # the size recorded there.
    old = _read_cache(root)
    cache = dict(old)
    for path in paths:
        if path.name.endswith('.raw.png'):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            stat = path.stat()
        except OSError:
            continue
        stamp = [stat.st_size, stat.st_mtime_ns, stat.st_ino]
        entry = old.get(relative)
        if isinstance(entry, dict) and entry.get('stamp') == stamp and isinstance(entry.get('size'), list):
            size = tuple(entry['size'])
        else:
            try:
                with Image.open(path) as image:
                    size = image.size
            except OSError:
                continue
            kept = entry.get('boxes') if isinstance(entry, dict) and entry.get('stamp') == stamp else None
            cache[relative] = {'stamp': stamp, 'size': list(size), 'boxes': kept if isinstance(kept, dict) else {}}
        if size != amigashots.CLIENT:
            continue
        parts = path.relative_to(root).parts
        run = root / parts[0] / parts[1] if len(parts) >= 5 else None
        if run is not None and run not in runs:
            runs[run] = _title(run)
        title = runs.get(run) if run else None
        crops.append(Crop(path, path.relative_to(root).as_posix(), title,
                          _states(path) if title else ()))
    if cache != old:
        _write_cache(root, cache)
    return crops


CACHE_NAME = 'guardmaps-digests.json'


def _decode_digests(path: pathlib.Path, boxes, state: str) -> dict[tuple, str]:
    return screens.box_digests(path, boxes, state)


def _read_cache(root: pathlib.Path) -> dict:
    try:
        data = json.loads((root / CACHE_NAME).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(root: pathlib.Path, data: dict) -> None:
    """Replace the cache atomically so two runners writing at once leave one whole file."""
    try:
        fd, name = tempfile.mkstemp(dir=root, prefix=CACHE_NAME + '.', suffix='.tmp')
    except OSError:
        return
    temp = pathlib.Path(name)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(data, handle)
        os.replace(temp, root / CACHE_NAME)
    except OSError:
        pass
    finally:
        temp.unlink(missing_ok=True)


def cached_digests(root: pathlib.Path, crops: list[Crop], boxes, state: str = 'guard') -> dict[str, dict[tuple, str]]:
    """Box digests per crop, decoding a crop only when its path, size, mtime or inode is new.

    A crop deleted since the scan is skipped. Entries for crops gone from
    disk are dropped from the cache. `state` names the rule in a bad-box error.

    Reading a crop from disk dominates a scan of the acceptance cache, so each
    entry remembers the digests it has computed for the boxes asked so far.
    """
    old = _read_cache(root)
    cache = {name: entry for name, entry in old.items() if (root / name).exists()}
    result: dict[str, dict[tuple, str]] = {}
    dirty = False
    for crop in crops:
        try:
            stat = crop.path.stat()
        except FileNotFoundError:
            continue
        stamp = [stat.st_size, stat.st_mtime_ns, stat.st_ino]
        entry = old.get(crop.relative)
        if not isinstance(entry, dict) or entry.get('stamp') != stamp or not isinstance(entry.get('boxes'), dict):
            entry = {'stamp': stamp, 'boxes': {}}
        known = entry['boxes']
        missing = [tuple(box) for box in boxes if ','.join(map(str, box)) not in known]
        if missing:
            for box, digest in _decode_digests(crop.path, missing, state).items():
                known[','.join(map(str, box))] = digest
            dirty = True
        cache[crop.relative] = entry
        result[crop.relative] = {tuple(box): known[','.join(map(str, box))] for box in boxes}
    if dirty or cache.keys() != old.keys():
        _write_cache(root, cache)
    return result


def _path(maps: pathlib.Path, title: str) -> pathlib.Path:
    return maps / f'guards_{FILES[title]}.json'


def _valid_part(part, keys: set[str]) -> bool:
    return (isinstance(part, dict) and set(part) == keys
            and isinstance(part['box'], list) and len(part['box']) == 4
            and all(type(n) is int for n in part['box'])
            and isinstance(part['sha256'], str)
            and re.fullmatch('[0-9a-f]{64}', part['sha256']) is not None)


def _parts(rule: dict) -> list[dict]:
    """The rule's own box and the further boxes it requires, all of which must match."""
    return [rule, *rule.get('and', ())]


def _valid_rule(rule) -> bool:
    base = {'box', 'sha256', 'example', 'also'}
    return (isinstance(rule, dict) and set(rule) - {'and'} == base
            and _valid_part({k: rule[k] for k in ('box', 'sha256')}, {'box', 'sha256'})
            and isinstance(rule.get('and', []), list)
            and all(_valid_part(part, {'box', 'sha256'}) for part in rule.get('and', []))
            and (rule['example'] is None or isinstance(rule['example'], str))
            and isinstance(rule['also'], list)
            and all(isinstance(s, str) for s in rule['also']))


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
        for state, value in data[kind].items():
            alternatives = screens.rules_of(value)
            if (not isinstance(state, str) or not alternatives
                    or isinstance(value, list) and len(alternatives) < 2
                    or not all(_valid_rule(rule) for rule in alternatives)):
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
    boxes = {tuple(part['box']) for spec in specs.values() for kind in ('guards', 'identity')
             for value in spec[kind].values() for rule in screens.rules_of(value) for part in _parts(rule)}
    digests = cached_digests(args.root, crops, boxes)
    crops = [c for c in crops if c.relative in digests]
    for title in args.title or FILES:
        spec = specs[title]
        problems = 0
        for kind in ('guards', 'identity'):
            for state, value in spec[kind].items():
                alternatives = screens.rules_of(value)
                hits = [0] * len(alternatives)
                misses = 0
                for crop in crops:
                    shown = _shown(crop, title, spec)
                    matched = False
                    for index, rule in enumerate(alternatives):
                        name = state if len(alternatives) == 1 else f'{state}[{index}]'
                        if any(digests[crop.relative][tuple(part['box'])] != part['sha256']
                               for part in _parts(rule)):
                            continue
                        matched = True
                        hits[index] += 1
                        if not _owned(crop, title, spec) or shown and state not in shown and not shown.intersection(rule['also']):
                            print(f'{title} {kind}/{name} collision {crop.relative}')
                            problems += 1
                    if not matched and _owned(crop, title, spec) and state in shown:
                        misses += 1
                for index, rule in enumerate(alternatives):
                    name = state if len(alternatives) == 1 else f'{state}[{index}]'
                    example = rule['example']
                    if example and (example not in digests or any(
                            digests[example][tuple(part['box'])] != part['sha256'] for part in _parts(rule))):
                        print(f'{title} {kind}/{name} stale {example}')
                        problems += 1
                    suffix = f' misses {misses}' if index == len(alternatives) - 1 else ''
                    print(f"{title} {kind}/{name} {rule['box']} hits {hits[index]}{suffix}")
        print(f'{title}: {problems} problems' if problems else f'{title}: clean')
        failed |= problems != 0
    return int(failed)


def _add(args, crops: list[Crop]) -> int:
    spec = _load(args.maps, args.title) if _path(args.maps, args.title).exists() else {'labels': {}, 'guards': {}, 'identity': {}}
    crop = args.crop.resolve()
    selected = next((c for c in crops if c.path.resolve() == crop), None)
    if selected is None:
        raise ValueError(f'{crop} is outside the scanned crops')
    if not _owned(selected, args.title, spec):
        raise ValueError(f'{crop} does not belong to {args.title}')
    box = [int(n) for n in args.box.split(',')]
    if args.and_box and (args.alternative or args.replace):
        raise ValueError('--and-box adds to the existing rule; it takes neither --alternative nor --replace')
    if args.and_box and (args.state not in spec[args.map] or len(screens.rules_of(spec[args.map][args.state])) != 1):
        raise ValueError(f'--and-box needs {args.state} to hold exactly one rule')
    if args.alternative and args.replace:
        raise ValueError('--alternative and --replace are exclusive')
    if args.state in spec[args.map] and not (args.replace or args.alternative or args.and_box):
        raise ValueError(f'{args.state} already exists; pass --replace or --alternative')
    if args.alternative and args.state not in spec[args.map]:
        raise ValueError(f'{args.state} does not exist; --alternative adds to an existing state')
    negatives = [c.path for c in crops if c.path != crop and
                 (not _owned(c, args.title, spec) or
                  _shown(c, args.title, spec) and args.state not in _shown(c, args.title, spec)
                  and not _shown(c, args.title, spec).intersection(args.also))]
    against = set(negatives)
    candidates = [c for c in crops if c.path in against]
    same = cached_digests(args.root, [selected, *candidates], [box], args.state)
    if selected.relative not in same:
        raise ValueError(f'{crop} was deleted')
    wanted = same[selected.relative][tuple(box)]
    negatives = [c.path for c in candidates if c.relative in same and same[c.relative][tuple(box)] == wanted]
    rule = screens.checked_rule(crop, box, args.state, negatives)
    rule = {**rule, 'example': selected.relative, 'also': sorted(args.also)}
    if args.and_box:
        held = spec[args.map][args.state]
        if any(part['box'] == rule['box'] for part in _parts(held)):
            raise ValueError(f'{args.state} already requires box {rule["box"]}')
        held['and'] = [*held.get('and', []), {'box': rule['box'], 'sha256': rule['sha256']}]
    elif args.alternative:
        if any((r['box'], r['sha256']) == (rule['box'], rule['sha256'])
               for r in screens.rules_of(spec[args.map][args.state])):
            raise ValueError(f'{args.state} already has this box and picture')
        spec[args.map][args.state] = [*screens.rules_of(spec[args.map][args.state]), rule]
    else:
        spec[args.map][args.state] = rule
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
        rules = {}
        for state, value in spec[kind].items():
            exported = [{key: rule[key] for key in ('box', 'sha256', 'and') if key in rule}
                        for rule in screens.rules_of(value)]
            rules[state] = exported[0] if len(exported) == 1 else exported
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
        if not 0 <= y0 <= y1 <= a.height:
            raise ValueError(f'rows must be inside 0,{a.height}')
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
    add.add_argument('--and-box', action='store_true',
                     help='require this box too, on top of the existing rule; all of its boxes must match')
    add.add_argument('--alternative', action='store_true',
                     help='append a second rule to an existing state; either one matches')
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

#!/usr/bin/env python3
"""Register the Wish policy adapter without replacing unrelated client settings."""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import tempfile
import tomllib
from pathlib import Path


def register(home: Path, launcher: str, codex: str) -> bool:
    """Validate both files before changing either; let Codex own its TOML syntax."""
    claude_path = home / '.claude.json'
    codex_path = home / '.codex/config.toml'
    claude = json.loads(claude_path.read_text()) if claude_path.exists() else {}
    original_codex = codex_path.read_bytes() if codex_path.exists() else None
    original_mode = stat.S_IMODE(codex_path.stat().st_mode) if original_codex is not None else None
    config = tomllib.loads(original_codex.decode('utf-8')) if original_codex is not None else {}
    servers = claude.setdefault('mcpServers', {})
    if not isinstance(servers, dict):
        raise ValueError('Claude MCP configuration must be an object')
    desired = {'command': launcher, 'args': []}
    current = config.get('mcp_servers', {}).get('wish-plane', {})
    changed = False
    if {**current, 'args': current.get('args', [])} != desired:
        try:
            subprocess.run([codex, 'mcp', 'add', 'wish-plane', '--', launcher],
                           env={**os.environ, 'CODEX_HOME': str(codex_path.parent)},
                           check=True, capture_output=True, timeout=30)
            updated = tomllib.loads(codex_path.read_text())
            actual = updated.get('mcp_servers', {}).pop('wish-plane', None)
            config.get('mcp_servers', {}).pop('wish-plane', None)
            if not config.get('mcp_servers'):
                config.pop('mcp_servers', None)
            if not updated.get('mcp_servers'):
                updated.pop('mcp_servers', None)
            if actual is not None:
                actual.setdefault('args', [])
            if actual != desired or updated != config:
                raise ValueError('Codex MCP registration did not preserve unrelated settings')
        except BaseException:
            if original_codex is None:
                codex_path.unlink(missing_ok=True)
            else:
                fd, temporary = tempfile.mkstemp(prefix='.codex-plane-', dir=codex_path.parent)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(original_codex)
                        os.fchmod(stream.fileno(), original_mode)
                    os.replace(temporary, codex_path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            raise
        changed = True
    desired_claude = {'type': 'stdio', **desired}
    if servers.get('wish-plane') != desired_claude:
        servers['wish-plane'] = desired_claude
        fd, temporary = tempfile.mkstemp(prefix='.claude-plane-', dir=home)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(claude, stream, indent=2)
                stream.write('\n')
            os.replace(temporary, claude_path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        changed = True
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--launcher', required=True)
    parser.add_argument('--codex', required=True)
    args = parser.parse_args()
    try:
        changed = register(args.home, args.launcher, args.codex)
    except (OSError, ValueError, subprocess.SubprocessError):
        parser.exit(1, 'Plane client registration failed; inspect private client configuration.\n')
    print('Plane clients changed' if changed else 'Plane clients unchanged')


if __name__ == '__main__':
    main()

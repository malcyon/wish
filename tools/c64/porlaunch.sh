#!/usr/bin/env bash
# Entry point of the old name for `launch.sh`; remove it when the current docs and `.claude/rules/emulator.md` name `launch.sh`.
exec "$(dirname -- "${BASH_SOURCE[0]}")/launch.sh" "$@"

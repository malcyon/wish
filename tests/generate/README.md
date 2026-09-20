# generate

Tests for the generators under `tools/generate/`, chiefly that each generated file is still what its generator writes today.

| file | purpose |
|---|---|
| `test_classdiagram.py` | Checks the parts of `tools/generate/classdiagram.py` that need no real `pyreverse` run: Mermaid parsing, the missing-tool message and the temporary worktree's lifetime. |
| `test_classedges.py` | Checks that `tools/generate/classedges.py` counts an annotated field as a class-diagram edge and an ordinary parameter as none. |
| `test_gencodex.py` | Checks that every `.codex/agents/*.toml` is what `tools/generate/gencodex.py` writes from its `.claude/agents/*.md` and that neither side has an unpaired file. |
| `test_generated.py` | Checks that the compiled `ui_*.py` files and the generated pages under `docs/` are current with their generators. |
| `test_genexits.py` | Checks that `tools/generate/genexits.py` agrees with the checked-in exit-route table and that its pure helpers pick the right squares and facings. |
| `test_geniconset.py` | Checks that `assets/wish.icns` holds PNGs of the sizes its type codes promise and is what `packaging/geniconset.py` writes today. |
| `test_genimports.py` | Checks that `tools/generate/genimports.py` sees an import however it is spelled and that the block it prints is the one in `docs/117-save-conversion.md`. |

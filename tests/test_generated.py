from __future__ import annotations

import pathlib
import subprocess
import sys

def test_generated_ui_is_current():
    """Fail if UI files were changed but tools/genui.py wasn't run."""
    result = subprocess.run([sys.executable, "tools/genui.py", "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, f"Generated UI files are out of date: {result.stdout}\nRun tools/genui.py to update them."

def test_generated_docs_are_current():
    """Fail if docs or memory map were changed but tools/gendocs.py or genmemory.py weren't run."""
    subprocess.run([sys.executable, "tools/gendocs.py"], check=True)
    subprocess.run([sys.executable, "tools/genmemory.py"], check=True)
    
    result = subprocess.run(["git", "diff", "--exit-code", "--", "docs/"],
                            capture_output=True, text=True)
    assert result.returncode == 0, f"Generated documentation is out of date: {result.stdout}\nRun tools/gendocs.py and tools/genmemory.py to update it."

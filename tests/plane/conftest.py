"""Run Linux Plane storage integration checks only where POSIX permissions exist."""
import os

import pytest

_PRIVATE_STORAGE_TESTS = {
    "test_scope_cannot_be_reused_for_another_project",
    "test_export_has_all_comments_and_events_without_printing",
    "test_private_directory_and_ledger_permissions",
    "test_cli_dry_run_prints_counts_only",
    "test_production_writer_requires_separate_explicit_configuration",
    "test_production_dry_run_does_not_write_without_allow_import",
}


@pytest.fixture(autouse=True)
def require_private_storage_permissions(request):
    """Migration storage enforces POSIX ownership and private file modes."""
    if os.name == "posix" or request.node.path.name != "test_migrate.py":
        return
    if "ledger" in request.fixturenames or request.node.originalname in _PRIVATE_STORAGE_TESTS:
        pytest.skip("Migration storage requires POSIX ownership and private file modes")

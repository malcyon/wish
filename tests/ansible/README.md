# Ansible tests

Tests for sandbox provisioning and access controls.

| File | Purpose |
|---|---|
| `test_agent_vm_wish_mount.py` | Checks that the host mounts only the guest's home and temporary directories with restricted access. |
| `test_plane_clients.py` | Checks private Plane client configuration and preservation of unrelated client settings. |
| `test_sandbox_isolation_credential_audit.py` | Checks credential-audit coverage and ordering after guest network checks. |
| `test_sandbox_service_exceptions.py` | Checks scoped service access, guest identity bindings and negative isolation probes. |
| `test_windows_vm_harness.py` | Checks that Windows harness replacement passes a null backup path to .NET. |

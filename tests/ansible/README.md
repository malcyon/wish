# Ansible tests

Tests for sandbox provisioning and access controls.

| File | Purpose |
|---|---|
| `test_agent_vm_wish_mount.py` | Checks that guest checkout mounts preserve the host repository and required access. |
| `test_plane_clients.py` | Checks private Plane client configuration and preservation of unrelated client settings. |
| `test_sandbox_isolation_credential_audit.py` | Checks credential-audit coverage and ordering after guest network checks. |
| `test_sandbox_service_exceptions.py` | Checks scoped service access, guest identity bindings and negative isolation probes. |

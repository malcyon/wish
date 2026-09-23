"""The sshfs unit the `agent-vm` role installs on the desktop, rendered with the
role's defaults: a writable view of the guest's whole filesystem that only the
mounting user can reach."""
from __future__ import annotations

import pathlib
import re

import yaml

ROLE = pathlib.Path(__file__).resolve().parents[2] / "ansible" / "roles" / "agent-vm"


def _exec_start() -> str:
    variables = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    variables.update(agent_vm_operator="op", agent_vm_wish_mount="/home/op/agent-wish",
                     sandbox_net_name="sandbox", sandbox_net_leases={})
    variables["agent_vm_network_name"] = variables["agent_vm_ip"] = variables["agent_vm_mac"] = ""
    # Rendered by hand: the template only substitutes `{{ name }}`, and jinja2
    # is not a dependency of the suite.
    def render(text: str) -> str:
        return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(variables[m.group(1)]), text)

    for _ in range(4):
        for k, v in list(variables.items()):
            if isinstance(v, str):
                variables[k] = render(v)
    text = render((ROLE / "templates" / "agent-vm-wish-mount.service.j2").read_text())
    m = re.search(r"^ExecStart=(.*?)(?=^\S)", text, re.S | re.M)
    assert m
    return m.group(1).replace("\\\n", " ")


def test_mount_is_writable_whole_filesystem_of_the_mounting_user_only():
    line = _exec_start()
    opts = line.split("-o ")[1].split()[0].split(",")
    assert "ro" not in opts
    assert "agent-vm:/ /home/op/agent-wish" in line
    for kept in ("reconnect", "BatchMode=yes", "ConnectTimeout=3",
                 "ServerAliveInterval=2", "ServerAliveCountMax=2"):
        assert kept in opts
    assert "follow_symlinks" in opts and "noexec" in opts
    assert "allow_other" not in line and "allow_root" not in line

"""The two sshfs units rooted at the guest home and temporary directories."""
from __future__ import annotations

import pathlib
import re

import yaml

ROLE = pathlib.Path(__file__).resolve().parents[2] / "ansible" / "roles" / "agent-vm"


def _exec_starts() -> dict[str, str]:
    variables = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    variables.update(agent_vm_operator="op", agent_vm_user="agent",
                     sandbox_net_name="sandbox", sandbox_net_leases={})
    variables["agent_vm_network_name"] = variables["agent_vm_ip"] = variables["agent_vm_mac"] = ""
    # Rendered by hand: the template only substitutes variable and item fields.
    def render(text: str, item: dict | None = None) -> str:
        def replace(match: re.Match) -> str:
            name = match.group(1)
            return str(item[name[5:]] if name.startswith("item.") else variables[name])

        return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", replace, text)

    for _ in range(4):
        for k, v in list(variables.items()):
            if isinstance(v, str):
                variables[k] = render(v)
    template = (ROLE / "templates" / "agent-vm-wish-mount.service.j2").read_text()
    starts = {}
    for raw in variables["agent_vm_wish_mounts"]:
        item = {key: render(value) for key, value in raw.items()}
        text = render(template, item)
        match = re.search(r"^ExecStart=(.*?)(?=^\S)", text, re.S | re.M)
        assert match
        starts[item["unit"]] = match.group(1).replace("\\\n", " ")
    return starts


def test_mount_roots_are_home_and_tmp_for_the_mounting_user():
    starts = _exec_starts()
    assert set(starts) == {"agent-wish-home.service", "agent-wish-tmp.service"}
    assert "agent-vm:/home/agent /home/op/agent-home" in starts["agent-wish-home.service"]
    assert "agent-vm:/tmp /home/op/agent-tmp" in starts["agent-wish-tmp.service"]
    for line in starts.values():
        opts = line.split("-o ")[1].split()[0].split(",")
        assert "ro" not in opts
        for kept in ("reconnect", "BatchMode=yes", "ConnectTimeout=3",
                     "ServerAliveInterval=2", "ServerAliveCountMax=2"):
            assert kept in opts
        assert "follow_symlinks" in opts and "noexec" in opts
        assert "allow_other" not in line and "allow_root" not in line


def test_retired_root_mount_stops_before_scoped_mounts_start():
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    names = [task["name"] for task in tasks]
    assert names.index("Stop and disable the retired root mount") < names.index(
        "Create the home and temporary mount points")
    assert names.index("Check that the retired root mount is gone") < names.index(
        "Enable the home and temporary mounts at login, and start them")
    check = tasks[names.index("Check that the retired root mount is gone")]
    assert check["failed_when"] == "agent_vm_wish_retired_mounted.rc not in [1, 32]"
    for task in tasks[names.index("Check for the retired root mount unit"):]:
        assert "agent_vm_mount" in task["tags"]


def test_teardown_checks_detachment_before_removing_units():
    tasks = yaml.safe_load((ROLE / "tasks" / "teardown.yml").read_text())
    names = [task["name"] for task in tasks]
    assert names.index("Stop and disable the guest file mounts") < names.index(
        "Check that the guest file mounts detached") < names.index(
            "Remove the guest file mount units")
    check = tasks[names.index("Check that the guest file mounts detached")]
    assert "agent-wish" in check["loop"]
    assert "agent_vm_wish_mounts" in check["loop"]
    assert check["failed_when"] == "agent_vm_td_mounts.rc not in [1, 32]"


def _tasks(items):
    for t in items:
        yield t
        for key in ("block", "always", "rescue"):
            yield from _tasks(t.get(key, []))


def test_verify_block_can_run_alone():
    tasks = list(_tasks(yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())))
    lookup = next(t for t in tasks if "ansible.builtin.getent" in t)
    tags = lookup.get("tags", [])
    assert "verify" in ([tags] if isinstance(tags, str) else tags)
    ssh = next(t for t in tasks if isinstance(t.get("ansible.builtin.command"), dict)
               and "ssh" in t["ansible.builtin.command"].get("argv", []))
    argv = ssh["ansible.builtin.command"]["argv"]
    assert any(a.startswith("ConnectTimeout=") for a in argv)

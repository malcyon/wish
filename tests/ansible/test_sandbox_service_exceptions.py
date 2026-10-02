"""Invalid service permissions stop provisioning before network changes."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / 'ansible/roles/sandbox-network'
SERVICE = {
    'source': '10.77.0.10', 'destination': '192.0.2.20', 'protocol': 'tcp',
    'port': 80, 'scheme': 'http', 'hostname': 'plane.example.test', 'denied_tcp_ports': [22, 81, 3000],
}


def _validate(service, pinholes=()):
    tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
    command = tasks[0]['ansible.builtin.command']['argv']
    data = {'services': [service], 'pinholes': pinholes,
            'leases': {'agent-vm': {'ip': '10.77.0.10'}}}
    return subprocess.run([sys.executable, *command[1:]], input=json.dumps(data),
                          capture_output=True, text=True, timeout=5)


def test_scoped_http_permission_is_accepted():
    assert _validate(SERVICE).returncode == 0


@pytest.mark.parametrize(('field', 'value'), [
    ('source', '10.77.0.99'), ('destination', '999.1.1.1'),
    ('destination', '192.0.2.0/24'), ('protocol', 'udp'), ('port', 22),
    ('hostname', "plane.test'; true"), ('denied_tcp_ports', [22]),
    ('denied_tcp_ports', [22, 81, 3000, 80]), ('scheme', 'file'), ('port', 443),
])
def test_unsafe_service_permission_is_rejected(field, value):
    service = copy.deepcopy(SERVICE)
    service[field] = value
    assert _validate(service).returncode != 0


def test_all_port_pinhole_cannot_override_denied_service_ports():
    assert _validate(SERVICE, [SERVICE['destination']]).returncode != 0


def test_both_guests_disable_source_learning_and_pin_their_own_address():
    for role, prefix, filename in [('agent-vm', 'agent_vm', 'agent-vm'),
                                   ('windows-vm', 'winvm', 'winvm')]:
        template = (ROOT / f'ansible/roles/{role}/templates/{filename}-domain.xml.j2').read_text()
        assert "<parameter name='IP' value='{{ " + prefix + "_ip }}'/>" in template
        assert "<parameter name='CTRL_IP_LEARNING' value='none'/>" in template


@pytest.mark.parametrize('broken', ['', 'live-ip', 'inactive-ip', 'learning', 'mac'])
def test_permission_cannot_open_until_live_and_saved_guest_identity_is_fixed(tmp_path, broken):
    import os

    tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
    task = next(t for t in tasks if t['name'].startswith('Verify fixed interface'))
    command = task['ansible.builtin.command']['argv']
    domain = """<domain><devices><interface>
      <mac address='52:54:00:00:00:11'/><source network='sandbox'/>
      <filterref filter='no-lan'><parameter name='IP' value='10.77.0.11'/>
        <parameter name='CTRL_IP_LEARNING' value='none'/></filterref>
    </interface></devices></domain>"""
    saved = live = domain
    if broken == 'live-ip':
        live = live.replace('10.77.0.11', '10.77.0.10')
    elif broken == 'inactive-ip':
        saved = saved.replace('10.77.0.11', '10.77.0.10')
    elif broken == 'learning':
        live = live.replace("value='none'", "value='any'")
    elif broken == 'mac':
        live = live.replace('52:54:00:00:00:11', '52:54:00:00:00:10')
    fake = tmp_path / 'virsh'
    fake.write_text(f'#!{sys.executable}\nimport sys\n'
                    f'print("win11" if "list" in sys.argv else '
                    f'{saved!r} if "--inactive" in sys.argv else {live!r})\n')
    fake.chmod(0o755)
    data = {'leases': {'win11': {'ip': '10.77.0.11', 'mac': '52:54:00:00:00:11'}},
            'network': 'sandbox', 'filter': 'no-lan'}
    result = subprocess.run([sys.executable, *command[1:]], input=json.dumps(data),
                            capture_output=True, text=True, timeout=5,
                            env={**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH']})
    assert (result.returncode == 0) == (broken == ''), result.stderr


def test_existing_domain_bindings_preserve_devices_and_need_no_second_update(tmp_path):
    import os
    import xml.etree.ElementTree as ET

    tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
    task = next(t for t in tasks if t['name'].startswith('Prepare fixed identities'))
    command = task['ansible.builtin.command']['argv']
    domain = """<domain><devices><interface type='network'>
      <mac address='52:54:00:00:00:11'/><source network='sandbox'/>
      <model type='e1000e'/><target dev='vnet7'/>
      <filterref filter='no-lan'/>
    </interface><disk type='file'/></devices></domain>"""
    domain_file = tmp_path / 'domain.xml'
    domain_file.write_text(domain)
    fake = tmp_path / 'virsh'
    fake.write_text(f'#!{sys.executable}\nimport sys\nfrom pathlib import Path\n'
                    f'print("win11" if "list" in sys.argv else '
                    f'Path({str(domain_file)!r}).read_text())\n')
    fake.chmod(0o755)
    data = {'leases': {'win11': {'ip': '10.77.0.11', 'mac': '52:54:00:00:00:11'}},
            'network': 'sandbox', 'filter': 'no-lan'}

    def prepare():
        result = subprocess.run([sys.executable, *command[1:]], input=json.dumps(data),
                                capture_output=True, text=True, timeout=5,
                                env={**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH']})
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    changes = prepare()
    assert {entry['mode'] for entry in changes} == {'config', 'live'}
    for entry in changes:
        iface = ET.fromstring(entry['xml'])
        assert iface.find('model').get('type') == 'e1000e'
        assert iface.find('target').get('dev') == 'vnet7'
        assert iface.find('disk') is None
        assert {p.get('name'): p.get('value') for p in iface.findall('filterref/parameter')} == {
            'IP': '10.77.0.11', 'CTRL_IP_LEARNING': 'none',
        }
    domain_file.write_text('<domain><devices>' + changes[0]['xml'] + '</devices></domain>')
    assert prepare() == []

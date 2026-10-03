"""Invalid service permissions stop provisioning before network changes."""
from __future__ import annotations

import copy
import io
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
            'service_guest': 'agent-vm',
            'leases': {'agent-vm': {'ip': '10.77.0.10'}, 'win11': {'ip': '10.77.0.11'}}}
    return subprocess.run([sys.executable, *command[1:]], input=json.dumps(data),
                          capture_output=True, text=True, timeout=5)


def test_scoped_http_permission_is_accepted():
    assert _validate(SERVICE).returncode == 0


@pytest.mark.parametrize(('field', 'value'), [
    ('source', '10.77.0.11'), ('source', '10.77.0.99'), ('destination', '999.1.1.1'),
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
def test_permission_cannot_open_until_live_and_saved_guest_identity_is_fixed(monkeypatch, broken):
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
    calls = []

    def virsh(argv, *, text, timeout):
        assert argv[:3] == ['virsh', '-c', 'qemu:///system']
        assert text is True and timeout == 10
        args = argv[3:]
        calls.append(args)
        if args == ['list', '--name']:
            return 'win11\n'
        if args == ['dumpxml', 'win11', '--inactive']:
            return saved
        if args == ['dumpxml', 'win11']:
            return live
        pytest.fail(f'Unexpected libvirt read: {args}')

    monkeypatch.setattr(subprocess, 'check_output', virsh)
    data = {'leases': {'win11': {'ip': '10.77.0.11', 'mac': '52:54:00:00:00:11'}},
            'network': 'sandbox', 'filter': 'no-lan'}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(data)))
    if broken:
        message = {'live-ip': '^Pin IP first: win11$', 'inactive-ip': '^Pin IP first: win11$',
                   'learning': '^Disable IP learning first: win11$', 'mac': '^win11$'}[broken]
        with pytest.raises(AssertionError, match=message):
            exec(command[2], {})
    else:
        exec(command[2], {})
    expected = [['list', '--name'], ['dumpxml', 'win11', '--inactive']]
    if broken != 'inactive-ip':
        expected.append(['dumpxml', 'win11'])
    assert calls == expected


def test_unavailable_libvirt_is_not_an_identity_rejection(monkeypatch):
    tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
    task = next(t for t in tasks if t['name'].startswith('Verify fixed interface'))

    def unavailable(*args, **kwargs):
        raise OSError('Cannot start virsh')

    monkeypatch.setattr(subprocess, 'check_output', unavailable)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({'leases': {}})))
    with pytest.raises(OSError, match='Cannot start virsh'):
        exec(task['ansible.builtin.command']['argv'][2], {})


def test_existing_domain_bindings_preserve_devices_and_need_no_second_update(monkeypatch, capsys):
    import xml.etree.ElementTree as ET

    tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
    task = next(t for t in tasks if t['name'].startswith('Prepare fixed identities'))
    command = task['ansible.builtin.command']['argv']
    domain = """<domain><devices><interface type='network'>
      <mac address='52:54:00:00:00:11'/><source network='sandbox'/>
      <model type='e1000e'/><target dev='vnet7'/>
      <filterref filter='no-lan'/>
    </interface><disk type='file'/></devices></domain>"""

    def virsh(argv, *, text, timeout):
        assert argv[:3] == ['virsh', '-c', 'qemu:///system']
        assert text is True and timeout == 10
        args = argv[3:]
        if args in (['list', '--name'], ['list', '--all', '--name']):
            return 'win11\n'
        if args in (['dumpxml', 'win11'], ['dumpxml', 'win11', '--inactive']):
            return domain
        pytest.fail(f'Unexpected libvirt read: {args}')

    monkeypatch.setattr(subprocess, 'check_output', virsh)
    data = {'leases': {'win11': {'ip': '10.77.0.11', 'mac': '52:54:00:00:00:11'}},
            'network': 'sandbox', 'filter': 'no-lan'}

    def prepare():
        monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(data)))
        exec(command[2], {})
        return json.loads(capsys.readouterr().out)

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
    domain = '<domain><devices>' + changes[0]['xml'] + '</devices></domain>'
    assert prepare() == []


@pytest.fixture
def spoof_tool():
    import runpy

    return runpy.run_path(str(ROLE / 'files/service-spoof-test.py'))


def _syn(source='10.77.0.10', source_port=45000, sequence=1234, mac='52:54:00:00:00:11'):
    return {'source': source, 'destination': '192.0.2.20', 'source_port': source_port,
            'destination_port': 80, 'sequence': sequence, 'mac': mac}


def _assess(spoof_tool, tap, uplink):
    return spoof_tool['assess'](tap, uplink, '10.77.0.10', '52:54:00:00:00:11',
                                '192.0.2.20', 80, 45000, 45001)


def test_spoof_gate_requires_emission_and_a_positive_uplink_control(spoof_tool):
    control = _syn(source='192.0.2.1', source_port=45001, sequence=9000)
    assert _assess(spoof_tool, [_syn()], [control]) == {
        'uplink_control_syns': 1, 'windows_forged_syns': 1, 'escaped_syns': 0,
    }
    with pytest.raises(RuntimeError, match='No forged Windows SYN'):
        _assess(spoof_tool, [], [control])
    with pytest.raises(RuntimeError, match='positive SYN control'):
        _assess(spoof_tool, [_syn()], [])


def test_spoof_gate_detects_escape_even_when_nat_rewrites_source_and_port(spoof_tool):
    control = _syn(source='192.0.2.1', source_port=45001, sequence=9000)
    escaped = _syn(source='192.0.2.1', source_port=59000)
    with pytest.raises(RuntimeError, match='ISOLATION BROKEN'):
        _assess(spoof_tool, [_syn()], [control, escaped])


def test_spoof_gate_does_not_count_another_guests_packet_as_windows_emission(spoof_tool):
    control = _syn(source='192.0.2.1', source_port=45001, sequence=9000)
    with pytest.raises(RuntimeError, match='No forged Windows SYN'):
        _assess(spoof_tool, [_syn(mac='52:54:00:00:00:10')], [control])


def test_spoof_capture_reads_generated_packets_and_rejects_truncation(spoof_tool, tmp_path):
    import ipaddress
    import struct

    ethernet = bytes.fromhex('5254000000015254000000110800')
    ip = bytearray(20)
    ip[0], ip[9] = 0x45, 6
    ip[12:16] = ipaddress.IPv4Address('10.77.0.10').packed
    ip[16:20] = ipaddress.IPv4Address('192.0.2.20').packed
    tcp = struct.pack('!HHIIBBHHH', 45000, 80, 1234, 0, 0x50, 2, 65535, 0, 0)
    packet = ethernet + ip + tcp
    header = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 128, 1)
    record = struct.pack('<IIII', 0, 0, len(packet), len(packet)) + packet
    path = tmp_path / 'packets.pcap'
    path.write_bytes(header + record)
    assert spoof_tool['read_syns'](path) == [_syn()]
    path.write_bytes(header + record[:-1])
    with pytest.raises(RuntimeError, match='Truncated capture packet'):
        spoof_tool['read_syns'](path)

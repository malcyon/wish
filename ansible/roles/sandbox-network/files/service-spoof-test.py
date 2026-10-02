#!/usr/bin/env python3
"""Measure a Windows forged-source SYN at its tap and at the host uplink."""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import signal
import socket
import struct
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


def run(argv, timeout=10):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=True).stdout


def read_syns(path):
    """Read IPv4 TCP SYN identifiers from Ethernet or Linux cooked pcap."""
    raw = Path(path).read_bytes()
    if len(raw) < 24:
        raise RuntimeError('Capture has no pcap header')
    orders = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>',
              b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}
    order = orders.get(raw[:4])
    if order is None:
        raise RuntimeError('Unsupported capture format')
    link = struct.unpack_from(order + 'I', raw, 20)[0]
    if link not in (1, 113, 276):
        raise RuntimeError(f'Unsupported capture link type: {link}')
    packets = []
    offset = 24
    while offset < len(raw):
        if len(raw) - offset < 16:
            raise RuntimeError('Truncated capture record')
        size = struct.unpack_from(order + 'I', raw, offset + 8)[0]
        offset += 16
        frame = raw[offset:offset + size]
        if len(frame) != size:
            raise RuntimeError('Truncated capture packet')
        offset += size
        head, protocol_at = {1: (14, 12), 113: (16, 14), 276: (20, 0)}[link]
        if len(frame) < head + 20:
            continue
        if frame[protocol_at:protocol_at + 2] != b'\x08\x00':
            continue
        packet = frame[head:]
        ihl = (packet[0] & 15) * 4
        if packet[0] >> 4 != 4 or ihl < 20 or len(packet) < ihl + 20 or packet[9] != 6:
            continue
        if struct.unpack_from('!H', packet, 6)[0] & 0x1fff:
            continue
        tcp = packet[ihl:]
        if tcp[13] & 0x12 != 0x02:
            continue
        source_port, destination_port, sequence = struct.unpack_from('!HHI', tcp)
        packets.append({'source': str(ipaddress.IPv4Address(packet[12:16])),
                        'destination': str(ipaddress.IPv4Address(packet[16:20])),
                        'source_port': source_port, 'destination_port': destination_port,
                        'sequence': sequence,
                        'mac': ':'.join(f'{n:02x}' for n in frame[6:12]) if link == 1 else None})
    return packets


def assess(tap, uplink, source, mac, destination, port, spoof_port, control_port):
    """Require emitted forged traffic and a working uplink capture control."""
    def target(packet):
        return packet['destination'] == destination and packet['destination_port'] == port
    control = [p for p in uplink if target(p) and p['source_port'] == control_port]
    forged = [p for p in tap if target(p) and p['source'] == source and p['mac'] == mac
              and p['source_port'] == spoof_port]
    if not control:
        raise RuntimeError('The host positive SYN control was not captured on the uplink')
    if not forged:
        raise RuntimeError('No forged Windows SYN was captured on its tap; isolation is untested')
    sequences = {p['sequence'] for p in forged}
    escaped = [p for p in uplink if target(p) and p['sequence'] in sequences]
    if escaped:
        raise RuntimeError(f'ISOLATION BROKEN: {len(escaped)} forged SYNs reached the uplink')
    return {'uplink_control_syns': len(control), 'windows_forged_syns': len(forged),
            'escaped_syns': 0}


class Capture:
    def __init__(self, interface, path, destination, port):
        self.log = Path(str(path) + '.log')
        self.handle = self.log.open('w+')
        self.process = subprocess.Popen(
            ['tcpdump', '-U', '-n', '-s', '128', '-i', interface, '-w', str(path),
             f'ip and dst host {destination} and tcp dst port {port} and tcp[tcpflags] & tcp-syn != 0'],
            stdout=subprocess.DEVNULL, stderr=self.handle)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if 'listening on' in self.log.read_text():
                return
            if self.process.poll() is not None:
                break
            time.sleep(0.05)
        self.stop(check=False)
        raise RuntimeError('Packet capture could not start: ' + self.log.read_text())

    def stop(self, check=True):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
                raise RuntimeError('Packet capture did not stop cleanly') from None
        self.handle.close()
        text = self.log.read_text()
        if check and (self.process.returncode != 0 or '\n0 packets dropped by kernel\n' not in text):
            raise RuntimeError('Packet capture failed or lost packets: ' + text)


def powershell_script(args, token, spoof_port):
    """Register independent rollback before temporarily adding the source alias."""
    return r'''
$ErrorActionPreference = 'Stop'
$Source = '__SOURCE__'
$WindowsIP = '__WINDOWS__'
$TaskName = 'WishServiceSpoof-__TOKEN__'
$Directory = Join-Path $env:ProgramData $TaskName
$Rollback = Join-Path $Directory 'rollback.ps1'
if (Get-NetIPAddress -IPAddress $Source -ErrorAction SilentlyContinue) { throw 'Source alias already exists; nothing changed' }
$Address = @(Get-NetIPAddress -IPAddress $WindowsIP -AddressFamily IPv4 -ErrorAction Stop)
if ($Address.Count -ne 1) { throw 'Expected exactly one Windows interface' }
$Index = $Address[0].InterfaceIndex
$Interface = Get-NetIPInterface -InterfaceIndex $Index -AddressFamily IPv4 -PolicyStore ActiveStore
if ($Interface.Dhcp -ne 'Disabled') { throw 'DHCP interface cannot be changed by this test' }
$Dad = [int]$Interface.DadTransmits
New-Item -ItemType Directory -Path $Directory -ErrorAction Stop | Out-Null
$State = @{ InterfaceIndex=$Index; DadTransmits=$Dad; Source=$Source; Directory=$Directory; TaskName=$TaskName }
$State | ConvertTo-Json | Set-Content (Join-Path $Directory 'state.json')
@'
$ErrorActionPreference = 'Stop'
$Directory = Split-Path -Parent $MyInvocation.MyCommand.Path
$State = Get-Content (Join-Path $Directory 'state.json') | ConvertFrom-Json
try {
    if (Test-Path (Join-Path $Directory 'alias-owned')) {
        Get-NetIPAddress -InterfaceIndex $State.InterfaceIndex -IPAddress $State.Source -ErrorAction SilentlyContinue |
            Remove-NetIPAddress -Confirm:$false -ErrorAction Stop
    }
} finally {
    Set-NetIPInterface -InterfaceIndex $State.InterfaceIndex -AddressFamily IPv4 -PolicyStore ActiveStore -DadTransmits $State.DadTransmits -ErrorAction Stop
}
if (Get-NetIPAddress -InterfaceIndex $State.InterfaceIndex -IPAddress $State.Source -ErrorAction SilentlyContinue) { throw 'Source alias was not removed' }
$Current = Get-NetIPInterface -InterfaceIndex $State.InterfaceIndex -AddressFamily IPv4 -PolicyStore ActiveStore
if ([int]$Current.DadTransmits -ne [int]$State.DadTransmits) { throw 'DAD was not restored' }
Unregister-ScheduledTask -TaskName $State.TaskName -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Directory -Recurse -Force
'@ | Set-Content $Rollback
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $Rollback + '"')
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(45)
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 30) -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -User 'SYSTEM' -RunLevel Highest | Out-Null
try {
    Set-NetIPInterface -InterfaceIndex $Index -AddressFamily IPv4 -PolicyStore ActiveStore -DadTransmits 0
    New-Item -ItemType File -Path (Join-Path $Directory 'alias-owned') | Out-Null
    New-NetIPAddress -InterfaceIndex $Index -IPAddress $Source -PrefixLength 32 -SkipAsSource $true -PolicyStore ActiveStore | Out-Null
    $Client = New-Object Net.Sockets.TcpClient([Net.Sockets.AddressFamily]::InterNetwork)
    try {
        $Client.Client.Bind((New-Object Net.IPEndPoint([Net.IPAddress]::Parse($Source), __SPORT__)))
        try { $null = $Client.ConnectAsync('__DESTINATION__', __PORT__).Wait(3000) } catch { }
    } finally { $Client.Dispose() }
} finally {
    & $Rollback
}
'Cleanup verified'
'''.replace('__SOURCE__', args.source).replace('__WINDOWS__', args.windows_ip).replace(
        '__TOKEN__', token).replace('__SPORT__', str(spoof_port)).replace(
        '__DESTINATION__', args.destination).replace('__PORT__', str(args.port))


def ssh_command(args, script):
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    command = ['runuser', '-u', args.controller_user, '--', 'ssh', '-F', '/dev/null',
               '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
               '-o', 'UserKnownHostsFile=/dev/null', '-o', 'LogLevel=ERROR']
    if args.key:
        command += ['-i', args.key, '-o', 'IdentitiesOnly=yes']
    return command + [args.windows_user + '@' + args.windows_ip,
                      'powershell.exe -NoProfile -EncodedCommand ' + encoded]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'destination', 'windows-ip'):
        parser.add_argument('--' + name, required=True, type=lambda s: str(ipaddress.IPv4Address(s)))
    for name in ('windows-user', 'controller-user', 'windows-mac', 'network', 'filter-name'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--port', type=int, choices=(80, 443), required=True)
    parser.add_argument('--key', default='')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Run on the libvirt host as root for packet capture')
    if args.source == args.windows_ip:
        raise RuntimeError('Forged source must differ from the Windows reservation')
    if 'win11' not in run(['virsh', '-c', 'qemu:///system', 'list', '--name']).splitlines():
        raise RuntimeError('Windows must be running for the source-spoof experiment')
    root = ET.fromstring(run(['virsh', '-c', 'qemu:///system', 'dumpxml', 'win11']))
    interfaces = [i for i in root.findall('./devices/interface')
                  if i.find('source') is not None and i.find('source').get('network') == args.network]
    if len(interfaces) != 1:
        raise RuntimeError('Expected one running Windows sandbox interface')
    iface = interfaces[0]
    if iface.find('mac').get('address').lower() != args.windows_mac.lower():
        raise RuntimeError('Windows interface MAC does not match the reservation')
    ref = iface.find('filterref')
    if ref is None or ref.get('filter') != args.filter_name:
        raise RuntimeError('Windows interface filter is missing')
    params = [(p.get('name'), p.get('value')) for p in ref.findall('parameter')]
    if [v for k, v in params if k == 'IP'] != [args.windows_ip] or ('CTRL_IP_LEARNING', 'none') not in params:
        raise RuntimeError('Fixed Windows identity must be applied before the spoof test')
    definition = ET.fromstring(run(['virsh', '-c', 'qemu:///system', 'nwfilter-dumpxml', args.filter_name]))
    refs = {ref.get('filter') for ref in definition.findall('filterref')}
    if not {'no-ip-spoofing', 'no-mac-spoofing', 'no-arp-spoofing'} <= refs:
        raise RuntimeError('Source binding filters must stay enabled during the spoof test')
    tap = iface.find('target').get('dev')
    routes = json.loads(run(['ip', '-j', 'route', 'get', args.destination]))
    uplink = routes[0]['dev']
    if tap == uplink or uplink == 'lo':
        raise RuntimeError('Expected a distinct physical uplink')
    token = uuid.uuid4().hex
    with socket.socket() as spare:
        spare.bind(('', 0))
        spoof_port = spare.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='wish-service-spoof-') as directory:
        tap_path, uplink_path = Path(directory) / 'tap.pcap', Path(directory) / 'uplink.pcap'
        captures = []
        try:
            captures.append(Capture(tap, tap_path, args.destination, args.port))
            captures.append(Capture(uplink, uplink_path, args.destination, args.port))
            with socket.create_connection((args.destination, args.port), timeout=5) as control:
                control_port = control.getsockname()[1]
            try:
                output = run(ssh_command(args, powershell_script(args, token, spoof_port)), timeout=30)
                if 'Cleanup verified' not in output:
                    raise RuntimeError('Windows cleanup did not report success')
            except Exception:
                recovery = r"$p=Join-Path $env:ProgramData 'WishServiceSpoof-__TOKEN__\rollback.ps1'; if (Test-Path $p) { & $p }"
                try:
                    run(ssh_command(args, recovery.replace('__TOKEN__', token).replace('__SOURCE__', args.source)), timeout=15)
                except subprocess.SubprocessError as error:
                    raise RuntimeError('Immediate rollback could not be verified; inspect the Windows rollback task and source alias before continuing') from error
                raise
        finally:
            errors = []
            for capture in captures:
                try:
                    capture.stop()
                except RuntimeError as error:
                    errors.append(str(error))
            if errors:
                raise RuntimeError('; '.join(errors))
        result = assess(read_syns(tap_path), read_syns(uplink_path), args.source,
                        args.windows_mac.lower(), args.destination, args.port, spoof_port, control_port)
        result['windows_cleanup'] = 'Verified'
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()

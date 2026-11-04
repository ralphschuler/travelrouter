"""Discover USB network devices and restrict activation to those devices."""
import re
from pathlib import Path

from .network import command
from .policy import interface


def discover_usb_networks(networks=Path('/sys/class/net')):
    found = []
    for device in networks.iterdir():
        if (device / 'phy80211').exists():
            continue
        try:
            name = interface(device.name)
            resolved = device.resolve(strict=True)
            usb = next((parent for parent in resolved.parents if (parent / 'idVendor').is_file()), None)
            if usb is None:
                continue
            vendor = (usb / 'idVendor').read_text().strip().lower()
            state = (device / 'operstate').read_text().strip()
            if state not in {'up', 'down', 'unknown', 'dormant', 'lowerlayerdown', 'notpresent', 'testing'}:
                state = 'unknown'
            found.append({'interface': name, 'kind': 'iPhone' if vendor == '05ac' else 'USB network',
                          'state': state})
        except (OSError, ValueError):
            continue
    return sorted(found, key=lambda item: item['interface'])


def perform_usb_action(manager, action, name):
    if action not in {'connect', 'disconnect'}:
        raise ValueError('Choose connect or disconnect')
    interface(name)
    if name not in {item['interface'] for item in discover_usb_networks()}:
        raise ValueError('USB network interface is no longer available')
    manager.nm('device', action, name, timeout=40)
    if action == 'connect':
        # Prefer the selected USB network over ordinary Wi-Fi for this session.
        manager.nm('device', 'modify', name, 'ipv4.route-metric', '50', timeout=20)


def pair_iphone():
    devices = command(['/usr/bin/idevice_id', '-l'], timeout=15).splitlines()
    if len(devices) != 1 or not re.fullmatch(r'[A-Fa-f0-9-]{8,64}', devices[0]):
        raise ValueError('Connect exactly one unlocked iPhone and retry pairing')
    command(['/usr/bin/idevicepair', '-u', devices[0], 'pair'], timeout=30)

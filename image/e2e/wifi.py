"""Wait for real WPA completion and carrier before requesting a DHCP lease."""

import json
import os
import socket
import subprocess
import time
from pathlib import Path

DIRECTORY = Path('/root/ci-image-test')


def supplicant_status():
    # STATUS uses the documented wpa_supplicant UNIX datagram protocol. We do
    # not ATTACH, so replies cannot be confused with unsolicited event messages.
    local = DIRECTORY / f'wpa-status-{os.getpid()}'
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.settimeout(1)
            client.bind(str(local))
            client.connect(str(DIRECTORY / 'wpa-control/wlan2'))
            client.send(b'STATUS')
            response = client.recv(16384).decode()
        return dict(line.split('=', 1) for line in response.splitlines() if '=' in line)
    finally:
        local.unlink(missing_ok=True)


def associated(status, link, expected_ssid):
    return (status.get('wpa_state') == 'COMPLETED' and status.get('ssid') == expected_ssid
            and link.get('ifname') == 'wlan2' and link.get('operstate') == 'UP'
            and {'UP', 'LOWER_UP'} <= set(link.get('flags', [])))


def main():
    expected = (DIRECTORY / 'expected-ssid').read_text()
    deadline = time.monotonic() + 45
    progress_at = 0
    snapshot = {}
    while time.monotonic() < deadline:
        try:
            status = supplicant_status()
            result = subprocess.run(['/sbin/ip', '-j', 'link', 'show', 'dev', 'wlan2'],  # nosec B603
                                    check=True, capture_output=True, text=True, timeout=3)
            link = json.loads(result.stdout)[0]
            snapshot = {'supplicant': status, 'link': link}
            (DIRECTORY / 'wifi-status.json').write_text(json.dumps(snapshot, indent=2) + '\n')
            if associated(status, link, expected):
                print('Real WPA association completed; client interface and carrier are UP', flush=True)
                return
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as error:
            snapshot = {'error': str(error)}
            (DIRECTORY / 'wifi-status.json').write_text(json.dumps(snapshot, indent=2) + '\n')
        if time.monotonic() >= progress_at:
            state = snapshot.get('supplicant', {}).get('wpa_state', 'control socket unavailable')
            print(f'Waiting for actual client association: {state}', flush=True)
            progress_at = time.monotonic() + 5
        time.sleep(0.5)
    raise RuntimeError('Client did not complete WPA association with an active link within 45 seconds; see Wi-Fi diagnostics')


if __name__ == '__main__':
    main()

"""Verify that real network-service restarts preserve the original panel process."""

import http.client
import json
import sys
import time
from pathlib import Path

DIRECTORY = Path('/root/ci-image-test')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def identity(pid):
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    require(fields[0] != 'Z', f'Process {pid} became a zombie')
    return [int(pid), int(fields[19])]


def service_identity(service):
    matches = []
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            executable = path.read_bytes().split(b'\0', 1)[0].decode()
            if Path(executable).name == service:
                matches.append(identity(path.parent.name))
        except (OSError, UnicodeDecodeError):
            continue
    require(len(matches) == 1, f'Expected one live {service} process, found {len(matches)}')
    return matches[0]


def controller_identity():
    pid = int(Path('/run/travelrouter/daemon.pid').read_text().strip())
    return identity(pid)


def assert_controller():
    expected = json.loads((DIRECTORY / 'controller.json').read_text())
    require(controller_identity() == expected, 'Network restart replaced or stopped the original panel process')
    return expected


def panel_http():
    connection = http.client.HTTPConnection('10.42.0.1', 80, timeout=5)
    try:
        connection.request('GET', '/api/status')
        response = connection.getresponse()
        payload = response.read()
        require(response.status == 200 and bool(json.loads(payload)), 'Panel stopped responding during network restart')
    finally:
        connection.close()


def wait_restart(service, previous=None, after_start=None, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert_controller()
        panel_http()
        try:
            current = service_identity(service)
        except AssertionError:
            current = None  # An intentional restart briefly has no service process.
        if current is not None and ((previous is not None and current != previous)
                                    or (after_start is not None and current[1] > after_start)):
            print(f'{service} restarted while the original panel process and HTTP remained available', flush=True)
            return
        time.sleep(0.5)
    raise AssertionError(f'{service} did not complete the expected real restart')


def first_policy():
    original = assert_controller()
    # Boot starts dnsmasq before the controller; a newer dnsmasq process proves
    # that the controller's first real policy application completed its restart.
    wait_restart('dnsmasq', after_start=original[1])


def assert_ap_ssid(config, expected):
    encoded = [line.partition('=')[2] for line in config.splitlines() if line.startswith('ssid2=')]
    require(len(encoded) == 1, 'Expected one hex-encoded SSID in the real hostapd configuration')
    try:
        actual = bytes.fromhex(encoded[0])
    except ValueError as error:
        raise AssertionError('The real hostapd SSID is not valid hexadecimal') from error
    require(actual == expected.encode(), 'Setup did not apply the new SSID to the real access point')


def main():
    if sys.argv[1] == 'capture':
        (DIRECTORY / 'controller.json').write_text(json.dumps(controller_identity()))
    elif sys.argv[1] == 'after-setup':
        previous = json.loads((DIRECTORY / 'before-setup.json').read_text())
        wait_restart('hostapd', previous=previous)
        assert_ap_ssid(Path('/etc/hostapd/hostapd.conf').read_text(), 'TravelRouter-CI')
    else:
        raise ValueError('Unknown lifecycle test phase')


if __name__ == '__main__':
    main()

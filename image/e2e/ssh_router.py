"""Exercise panel-controlled SSH from simulated trusted and untrusted networks."""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, '/root/ci-image-test')
from client import NEW_ADMIN, Client


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def ssh(namespace, identity):
    # Both namespaces and key paths are fixed, generated in this disposable VM.
    return subprocess.run(  # nosec B603
        ['/sbin/ip', 'netns', 'exec', namespace, '/usr/bin/ssh', '-i', identity,
         '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=no',
         '-o', 'UserKnownHostsFile=/dev/null', '-o', 'ConnectTimeout=4',
         'root@10.42.0.1', 'id -u'], text=True, capture_output=True, timeout=8)


def main():
    key = '/root/ci-image-test/devkey'
    wrong = '/root/ci-image-test/wrongkey'
    for path in (key, wrong):
        subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', path], check=True)  # nosec B603
    client = Client()
    client.login(NEW_ADMIN, False)
    client.expect(200, '/api/developer', {'enabled': True, 'public_key': Path(key + '.pub').read_text().strip()})
    status = json.loads(client.expect(200, '/api/status')[0])
    require(status['developer_enabled'] and status['developer_host_fingerprint'].startswith('SHA256:'),
            'Panel did not report SSH and its host fingerprint')
    result = ssh('tr-client', key)
    require(result.returncode == 0 and result.stdout.strip() == '0', 'Hotspot SSH login failed')
    require(ssh('tr-client', wrong).returncode != 0, 'Wrong key was accepted')
    require(ssh('tr-untrusted', key).returncode != 0, 'SSH was reachable from untrusted ingress')
    print('Panel enabled key-only SSH; hotspot succeeds and foreign ingress is denied', flush=True)
    client.expect(200, '/api/developer', {'enabled': False, 'public_key': ''})
    require(not json.loads(client.expect(200, '/api/status')[0])['developer_enabled'], 'Panel did not disable SSH')
    time.sleep(1)
    require(ssh('tr-client', key).returncode != 0, 'Key still works after disabling SSH')
    print('Panel disabled SSH; previous key no longer connects', flush=True)


if __name__ == '__main__':
    main()

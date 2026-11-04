"""Exercise signed update trials using keys generated only inside a disposable VM."""
import base64
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, '/opt/travelrouter')
from client import NEW_ADMIN, Client
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from travelrouter import __version__
from travelrouter.updates import package_update

KEY = Path('/etc/travelrouter/ci-update-private.pem')
PACKAGE = Path('/opt/travelrouter/travelrouter')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def client_login():
    client = Client()
    client.login(NEW_ADMIN, False)
    return client


def update_status(client):
    payload, _ = client.expect(200, '/api/status')
    return json.loads(payload)['updates']


def await_message(client, prefix):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = update_status(client)
        if not status['busy'] and status['message'].startswith(prefix):
            return status
        if not status['busy'] and status['message'].startswith('Update failed') and prefix != 'Update failed':
            raise AssertionError(status['message'])
        time.sleep(0.5)
    raise AssertionError('Timed out waiting for update worker: ' + prefix)


def next_version(version):
    major, minor, patch = map(int, version.split('.'))
    return f'{major}.{minor}.{patch + 1}'


def medium():
    matches = [path.parent for path in Path('/media').glob('*/.travelrouter')]
    require(len(matches) == 1, 'Could not identify the boot medium')
    return matches[0]


def candidate(version, broken=False):
    allowed = {'.py', '.js', '.html', '.css', '.woff2', '.txt'}
    files = {'travelrouter/' + str(path.relative_to(PACKAGE)): path.read_bytes()
             for path in PACKAGE.rglob('*') if path.is_file() and path.suffix in allowed}
    marker = ("'" + __version__ + "'").encode()
    require(files['travelrouter/__init__.py'].count(marker) == 1, 'Expected version marker missing')
    files['travelrouter/__init__.py'] = files['travelrouter/__init__.py'].replace(marker, ("'" + version + "'").encode())
    if broken:
        files['travelrouter/__main__.py'] = b'raise RuntimeError("CI-only intentional startup failure")\n'
    return files


def create_test_key():
    key = Ed25519PrivateKey.generate()
    KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    KEY.chmod(0o600)
    Path('/etc/travelrouter/update-public.pem').write_bytes(
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return key


def stage_good():
    version = next_version(__version__)
    key = create_test_key()
    update = package_update(candidate(version), version, key)
    invalid = copy.deepcopy(update)
    signature = bytearray(base64.b64decode(invalid['signature']))
    signature[0] ^= 1
    invalid['signature'] = base64.b64encode(signature).decode()
    client = client_login()
    client.expect(202, '/api/updates/install', {'update': invalid})
    await_message(client, 'Update failed')
    client.expect(202, '/api/updates/install', {'update': update})
    status = await_message(client, 'Application ' + version + ' staged')
    require(status['reboot_required'], 'Update did not request a reboot')
    require(' application ready ' in (medium() / '.travelrouter-update').read_text(), 'Update not committed')
    print('Tampered update rejected; valid signed update staged for a trial', flush=True)


def wait_confirmed():
    marker = medium() / '.travelrouter-update'
    deadline = time.monotonic() + 90
    while marker.exists() and time.monotonic() < deadline:
        time.sleep(1)
    require(not marker.exists(), 'Healthy update was not confirmed')
    require('confirmed' in (medium() / '.travelrouter-recovery/result').read_text(), 'Confirmation result missing')
    require(update_status(client_login())['application_version'] == __version__, 'Panel version mismatch')
    print('CI_CONFIRMED_VERSION:' + __version__, flush=True)
    print('Healthy signed update and saved credentials survived reboot', flush=True)


def stage_broken():
    key = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    version = next_version(__version__)
    client = client_login()
    client.expect(202, '/api/updates/install', {'update': package_update(candidate(version, True), version, key)})
    await_message(client, 'Application ' + version + ' staged')
    require(' application ready ' in (medium() / '.travelrouter-update').read_text(), 'Broken update not staged')
    print('Intentionally broken signed update staged for recovery test', flush=True)


def verify_rollback():
    require(len(sys.argv) == 3 and __version__ == sys.argv[2], 'Previous application version was not restored')
    require('rolled back' in (medium() / '.travelrouter-recovery/result').read_text(), 'Rollback result missing')
    require(not (medium() / '.travelrouter-update').exists(), 'Failed trial marker remains')
    require(update_status(client_login())['application_version'] == __version__, 'Restored panel version mismatch')
    print('Failed update rolled back; prior panel and credentials work', flush=True)


if __name__ == '__main__':
    {'stage-good': stage_good, 'verify-good': wait_confirmed,
     'stage-broken': stage_broken, 'verify-rollback': verify_rollback}[sys.argv[1]]()

"""Signed application updates and staged, signature-checked Alpine packages."""

import base64
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import __version__
from .network import command

CONTEXT = b'TravelRouter application update v1\x00'
MIRROR = 'https://dl-cdn.alpinelinux.org/alpine/v3.24'


def package_architecture():
    architecture = command(['/sbin/apk', '--print-arch']).strip()
    if architecture not in {'aarch64', 'x86_64'}:
        raise ValueError('Package updates are unavailable for this architecture')
    return architecture


def repository_location(url, architecture):
    if architecture not in {'aarch64', 'x86_64'}:
        raise ValueError('Unsupported package architecture')
    for repository in ('main', 'community'):
        prefix = f'{MIRROR}/{repository}/{architecture}/'
        if url.startswith(prefix):
            name = url[len(prefix):]
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.~-]*\.apk', name):
                return repository, name
    raise ValueError('Unexpected package source or architecture')


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value):
        raise ValueError('A semantic release version is required')
    return tuple(int(part) for part in value.split('.'))


def _signed_bytes(manifest):
    return CONTEXT + json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()


def package_update(files, version, key):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, data in sorted(files.items()):
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
            archive.addfile(entry, io.BytesIO(data))
    payload = buffer.getvalue()
    manifest = {'version': version, 'alpine_branch': 'v3.24', 'sha256': hashlib.sha256(payload).hexdigest()}
    return {'format': 'travelrouter-update-v1', 'manifest': manifest,
            'signature': base64.b64encode(key.sign(_signed_bytes(manifest))).decode(),
            'payload': base64.b64encode(payload).decode()}


def verify_update(envelope, key, current_version):
    try:
        if not isinstance(envelope, dict) or envelope.get('format') != 'travelrouter-update-v1':
            raise ValueError('Unsupported update format')
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError('An Ed25519 release key is required')
        manifest = envelope['manifest']
        key.verify(base64.b64decode(envelope['signature'], validate=True), _signed_bytes(manifest))
        if manifest.get('alpine_branch') != 'v3.24':
            raise ValueError('This update needs a different Alpine image')
        if version_tuple(manifest['version']) <= version_tuple(current_version):
            raise ValueError('Update must be newer than the installed application')
        payload = base64.b64decode(envelope['payload'], validate=True)
        if len(payload) > 2 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != manifest['sha256']:
            raise ValueError('Update payload checksum or size is invalid')
        files, total = {}, 0
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
            for entry in archive:
                path = PurePosixPath(entry.name)
                if (not entry.isfile() or path.is_absolute() or '..' in path.parts
                        or not path.parts or path.parts[0] != 'travelrouter'
                        or path.suffix not in {'.py', '.js', '.html', '.css', '.woff2', '.txt'}
                        or entry.size > 1024 * 1024 or len(files) >= 500):
                    raise ValueError('Update contains unsupported files')
                total += entry.size
                if total > 8 * 1024 * 1024:
                    raise ValueError('Expanded update is too large')
                if str(path) in files:
                    raise ValueError('Duplicate update path')
                files[str(path)] = archive.extractfile(entry).read()
        if 'travelrouter/__init__.py' not in files or 'travelrouter/__main__.py' not in files:
            raise ValueError('Application update is incomplete')
        return manifest, files
    except (InvalidSignature, KeyError, TypeError, tarfile.TarError, OSError) as error:
        raise ValueError('Update signature or content is invalid') from error


class Updates:
    def __init__(self, backend):
        self.backend = backend
        self.worker_lock = threading.Lock()
        self.last_check = 0
        self.status = {'busy': False, 'message': 'No updates staged', 'reboot_required': False,
                       'application_version': __version__}

    def start(self, operation, data=None):
        if not self.worker_lock.acquire(blocking=False):
            raise ValueError('An update operation is already running')
        self.status.update(busy=True, message='Checking update')

        def worker():
            try:
                if operation == 'packages':
                    self.stage_packages()
                elif operation == 'application':
                    self.install_application(data)
                elif operation == 'check':
                    self.check_release()
                else:
                    raise ValueError('Unknown update operation')
            except Exception:
                # No command arguments, credentials, or uploaded content in logs.
                self.status['message'] = 'Update failed validation or could not be staged. Current installation remains available.'
            finally:
                self.last_check = time.monotonic()
                self.status['busy'] = False
                self.worker_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def check_release(self):
        url = 'https://api.github.com/repos/ralphschuler/travelrouter/releases?per_page=10'
        with urllib.request.urlopen(url, timeout=15) as response:  # nosec B310
            releases = json.loads(response.read(1024 * 1024))
        releases = [release for release in releases if not release['draft']]
        latest = releases[0] if releases else None
        self.status['release_url'] = latest['html_url'] if latest else None
        self.status['message'] = 'Latest release: ' + latest['tag_name'] if latest else 'No release is published yet'

    def install_application(self, envelope):
        key = serialization.load_pem_public_key(Path('/etc/travelrouter/update-public.pem').read_bytes())
        manifest, files = verify_update(envelope, key, self.status.get('staged_version', __version__))
        with self.backend.lock:
            staging = Path(tempfile.mkdtemp(prefix='.travelrouter-update-', dir='/opt'))
            try:
                for name, content in files.items():
                    path = staging / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    path.chmod(0o644)
                target, previous = Path('/opt/travelrouter'), Path('/opt/.travelrouter-previous')
                if previous.exists():
                    shutil.rmtree(previous)
                os.replace(target, previous)
                os.replace(staging, target)
                try:
                    self.backend.persist()
                except Exception:
                    shutil.rmtree(target)
                    os.replace(previous, target)
                    raise
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        self.status.update(message='Application ' + manifest['version'] + ' staged. Reboot when convenient.',
                           reboot_required=True, staged_version=manifest['version'])

    def stage_packages(self):
        # The live RAM root stays unchanged. Signed packages activate on reboot.
        from .system import boot_medium
        with self.backend.lock:
            architecture = package_architecture()
            available = command(['/sbin/apk', '--no-cache', '--repositories-file', '/dev/null',
                                 '--repository', MIRROR + '/main', '--repository', MIRROR + '/community',
                                 'list', '--upgradable'], timeout=60).strip()
            if not available:
                self.status['message'] = 'Alpine stable packages are current'
                return
            medium = boot_medium()
            if shutil.disk_usage(medium).free < 1024 * 1024 * 1024:
                raise ValueError('At least 1 GiB free boot space is required for package staging')
            command(['/bin/mount', '-o', 'remount,rw', str(medium)])
            staging = None
            try:
                staging = Path(tempfile.mkdtemp(prefix='.packages-', dir=medium))
                cache = staging / 'downloads'
                cache.mkdir()
                packages = Path('/etc/apk/world').read_text().split()
                args = ['/sbin/apk', '--repositories-file', '/dev/null', '--repository', MIRROR + '/main',
                        '--repository', MIRROR + '/community']
                self.status['message'] = 'Downloading signed Alpine stable packages'
                command([*args, 'fetch', '--recursive', '--output', str(cache), *packages], timeout=1200)
                urls = command([*args, 'fetch', '--recursive', '--url', *packages], timeout=60).splitlines()
                repositories = staging / 'repositories'
                for repository in ('main', 'community'):
                    directory = repositories / repository / architecture
                    directory.mkdir(parents=True)
                    url = f'{MIRROR}/{repository}/{architecture}/APKINDEX.tar.gz'
                    with urllib.request.urlopen(url, timeout=20) as response:  # nosec B310
                        data = response.read(8 * 1024 * 1024 + 1)
                    if len(data) > 8 * 1024 * 1024:
                        raise ValueError('Package index is too large')
                    (directory / 'APKINDEX.tar.gz').write_bytes(data)
                for url in urls:
                    repository, name = repository_location(url, architecture)
                    os.replace(cache / name, repositories / repository / architecture / name)
                downloaded = [str(path) for path in repositories.glob(f'*/{architecture}/*.apk')]
                if not downloaded:
                    raise ValueError('No packages were downloaded')
                command(['/sbin/apk', 'verify', *downloaded], timeout=120)
                check = staging / 'check'
                (check / 'etc/apk/keys').mkdir(parents=True)
                shutil.copytree('/etc/apk/keys', check / 'etc/apk/keys', dirs_exist_ok=True)
                command(['/sbin/apk', '--root', str(check), '--initdb', '--no-network',
                         '--repositories-file', '/dev/null', '--repository', str(repositories / 'main'),
                         '--repository', str(repositories / 'community'), 'add', '--simulate', *packages], timeout=120)
                # Publish repository markers only after the whole staged set validates.
                for repository in ('main', 'community'):
                    (repositories / repository / '.boot_repository').touch()
                previous = medium / '.repositories.previous'
                if previous.exists():
                    if previous.is_symlink() or previous.resolve().parent != medium.resolve():
                        raise ValueError('Invalid previous repository location')
                    shutil.rmtree(previous)
                os.replace(medium / 'repositories', previous)
                os.replace(repositories, medium / 'repositories')
                # Persistence remounts the boot medium read-only, including on failure.
                # Finish all temporary filesystem cleanup before crossing that boundary.
                shutil.rmtree(staging)
                staging = None
                self.backend.persist()
                self.status.update(message='Verified Alpine packages staged for next boot. Kernel updates use a full release image.',
                                   reboot_required=True)
            finally:
                try:
                    if staging is not None and staging.exists():
                        shutil.rmtree(staging)
                finally:
                    command(['/bin/mount', '-o', 'remount,ro', str(medium)])

"""Durably prepare a recoverable boot-media update transaction."""
import gzip
import hashlib
import os
import re
import shutil
from pathlib import Path


class RecoveryUnavailable(ValueError):
    """Staging is unsafe because early recovery or a usable watchdog is absent."""


def ensure_ready(medium):
    if not (Path(medium) / '.travelrouter-recovery-v1').is_file() or not all(
            Path(path).is_file() for path in ('/etc/init.d/travelrouter-recovery',
                                               '/etc/travelrouter/recovery.sh')):
        raise RecoveryUnavailable('Update recovery is unavailable; install a recovery-enabled image first.')
    watchdog = Path('/dev/watchdog')
    info = Path('/sys/class/watchdog/watchdog0')
    try:
        usable = (watchdog.is_char_device() and os.access(watchdog, os.W_OK)
                  and (info / 'nowayout').read_text().strip() == '0'
                  and (info / 'state').read_text().strip() == 'inactive')
    except OSError:
        usable = False
    if not usable:
        raise RecoveryUnavailable('A free, stoppable watchdog is required before staging an update.')


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def file_digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


class Transaction:
    def __init__(self, medium):
        self.medium = Path(medium)
        self.marker = self.medium / '.travelrouter-update'
        self.backup = self.medium / '.travelrouter-recovery'

    def _prepare_directory(self):
        if self.marker.exists() or self.marker.is_symlink():
            raise ValueError('A previous update must be confirmed or rolled back before staging another')
        if self.backup.is_symlink():
            raise ValueError('Invalid recovery directory')
        if self.backup.exists():
            shutil.rmtree(self.backup)
        self.backup.mkdir(mode=0o700)
        sync_directory(self.medium)

    def _marker(self, value):
        temporary = self.medium / '.travelrouter-update.new'
        if temporary.is_symlink():
            raise ValueError('Invalid recovery marker')
        with temporary.open('w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.marker)
        sync_directory(self.medium)

    def prepare_application(self, version):
        if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
            raise ValueError('Invalid update version')
        self._prepare_directory()
        source = self.medium / 'travelrouter.apkovl.tar.gz'
        if source.is_symlink() or not source.is_file():
            raise ValueError('Current boot overlay is unavailable')
        # Read to the end so gzip verifies its CRC before accepting the backup.
        with gzip.open(source, 'rb') as compressed:
            while compressed.read(1024 * 1024):
                pass
        backup = self.backup / 'overlay.gz'
        with source.open('rb') as incoming, backup.open('wb') as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        digest = file_digest(source)
        if file_digest(backup) != digest:
            raise ValueError('Recovery overlay verification failed')
        sync_directory(self.backup)
        self._marker(f'v1 application prepared {version} {digest}\n')

    def prepare_packages(self):
        self._prepare_directory()
        source = self.medium / 'repositories'
        if source.is_symlink() or not source.is_dir():
            raise ValueError('Current package repository is unavailable')
        self._marker('v1 packages prepared - -\n')

    def back_up_repositories(self):
        if self.marker.read_text() != 'v1 packages prepared - -\n':
            raise ValueError('Package update recovery marker is missing')
        os.replace(self.medium / 'repositories', self.backup / 'repositories')
        sync_directory(self.backup)
        sync_directory(self.medium)

    def mark_ready(self):
        state = self.marker.read_text()
        if not re.fullmatch(r'v1 (?:application prepared [0-9]+\.[0-9]+\.[0-9]+ [0-9a-f]{64}|packages prepared - -)\n', state):
            raise ValueError('A prepared recovery transaction is required')
        self._marker(state.replace(' prepared ', ' ready ', 1))

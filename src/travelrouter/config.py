"""Private configuration with crash-resistant replacement."""

import copy
import json
import os
import tempfile
from pathlib import Path

from .security import DEFAULT_ADMIN_PASSWORD, DEFAULT_AP_PASSWORD, hash_password


def atomic_write(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ConfigStore:
    def __init__(self, path='/etc/travelrouter/config.json'):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            data = {'schema': 1, 'setup_complete': False, 'ssid': 'TravelRouter',
                    'ap_password': DEFAULT_AP_PASSWORD, 'country': '00',
                    'admin_hash': hash_password(DEFAULT_ADMIN_PASSWORD)}
            self.save(data)
            return data
        try:
            data = json.loads(self.path.read_text())
            required = {'schema', 'setup_complete', 'ssid', 'ap_password', 'country', 'admin_hash'}
            if not isinstance(data, dict) or not required <= data.keys() or data['schema'] != 1:
                raise ValueError('Unsupported or incomplete configuration')
            if type(data['setup_complete']) is not bool:
                raise ValueError('Invalid setup state')
            return copy.deepcopy(data)
        except (json.JSONDecodeError, OSError) as error:
            raise ValueError('Cannot read router configuration; use console recovery') from error

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        atomic_write(self.path, json.dumps(data, indent=2) + '\n')

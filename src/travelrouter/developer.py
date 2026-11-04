"""Validation for explicitly enabled, key-only local developer access."""
import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .config import atomic_write


def host_fingerprint(path):
    try:
        private = serialization.load_ssh_private_key(path.read_bytes(), password=None)
        if not isinstance(private, Ed25519PrivateKey):
            return None
        encoded = private.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                                    serialization.PublicFormat.OpenSSH).split()[1]
        return 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(encoded)).digest()).decode().rstrip('=')
    except (OSError, ValueError, TypeError):
        return None


def render_sshd_config():
    return ('Port 22\nListenAddress 10.42.0.1\n'
            'HostKey /etc/travelrouter/ssh_host_ed25519_key\n'
            'PidFile /run/travelrouter-sshd.pid\n'
            'AuthorizedKeysFile /etc/travelrouter/ssh_authorized_keys\n'
            'PermitRootLogin prohibit-password\nAllowUsers root\n'
            'PasswordAuthentication no\nKbdInteractiveAuthentication no\n'
            'PermitEmptyPasswords no\nDisableForwarding yes\n'
            'X11Forwarding no\nPermitTunnel no\nStrictModes yes\n')


def root_shadow(content, enabled):
    lines = content.splitlines(keepends=True)
    matching = [index for index, line in enumerate(lines) if line.startswith('root:')]
    if len(matching) != 1:
        raise ValueError('Cannot identify the root account')
    index = matching[0]
    fields = lines[index].split(':')
    if len(fields) != 9 or fields[1] not in {'!', 'NP'}:
        raise ValueError('Unexpected root account state')
    # NP is not a password hash. It permits SSH key authentication without
    # creating a usable local password; ! locks the account when disabled.
    fields[1] = 'NP' if enabled else '!'
    lines[index] = ':'.join(fields)
    return ''.join(lines)


def configure_files(etc, enabled, public_key):
    if type(enabled) is not bool:
        raise ValueError('Developer mode must be enabled or disabled')
    key = validate_public_key(public_key) if enabled else ''
    directory = etc / 'travelrouter'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    marker = directory / 'developer-enabled'
    shadow = etc / 'shadow'
    shadow_content = root_shadow(shadow.read_text(), enabled)
    if not enabled:
        marker.unlink(missing_ok=True)
        atomic_write(shadow, shadow_content)
        (directory / 'ssh_authorized_keys').unlink(missing_ok=True)
        return
    host_key = directory / 'ssh_host_ed25519_key'
    if host_key.is_symlink():
        raise ValueError('Invalid SSH host key location')
    if not host_key.exists():
        private = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption()).decode('ascii')
        atomic_write(host_key, private)
    atomic_write(directory / 'ssh_authorized_keys', key + '\n')
    atomic_write(directory / 'sshd_config', render_sshd_config())
    atomic_write(shadow, shadow_content)
    atomic_write(marker, 'enabled\n')


def validate_public_key(value):
    if not isinstance(value, str) or len(value) > 1024 or '\n' in value or '\r' in value:
        raise ValueError('Provide one Ed25519 public key')
    parts = value.split()
    if len(parts) < 2 or parts[0] != 'ssh-ed25519':
        raise ValueError('Provide one Ed25519 public key')
    try:
        key = serialization.load_ssh_public_key(' '.join(parts[:2]).encode('ascii'))
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError('Invalid Ed25519 public key') from error
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError('Provide one Ed25519 public key')
    return key.public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode('ascii')

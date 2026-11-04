"""Developer access accepts only explicit, well-formed public keys."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from travelrouter.config import ConfigStore
from travelrouter.developer import configure_files, render_sshd_config, root_shadow, validate_public_key
from travelrouter.system import System


class DeveloperTests(unittest.TestCase):
    def test_valid_ed25519_key_is_canonicalized(self):
        key = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        self.assertEqual(validate_public_key(key + ' laptop'), key)

    def test_multiple_keys_and_authorized_key_options_are_rejected(self):
        key = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        for value in (key + '\n' + key, 'command="id" ' + key, '', key + '\r\n'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_public_key(value)

    def test_ssh_configuration_is_local_and_key_only(self):
        config = render_sshd_config()
        for option in ('ListenAddress 10.42.0.1', 'PasswordAuthentication no',
                       'KbdInteractiveAuthentication no', 'AllowUsers root',
                       'DisableForwarding yes', 'PermitRootLogin prohibit-password'):
            self.assertIn(option + '\n', config)

    def test_root_auth_never_installs_a_usable_password(self):
        initial = 'root:!:19000:0:99999:7:::\nother:!:19000:0:99999:7:::\n'
        enabled = root_shadow(initial, True)
        self.assertIn('root:NP:', enabled)
        self.assertEqual(root_shadow(enabled, False), initial)
        with self.assertRaises(ValueError):
            root_shadow('root:$6$existing:19000:0:99999:7:::\n', True)

    def test_enable_and_disable_material_without_changing_host_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            etc = Path(temporary)
            (etc / 'shadow').write_text('root:!:19000:0:99999:7:::\n')
            key = Ed25519PrivateKey.generate().public_key().public_bytes(
                serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
            configure_files(etc, True, key)
            directory = etc / 'travelrouter'
            self.assertTrue((directory / 'developer-enabled').is_file())
            self.assertEqual((directory / 'ssh_authorized_keys').read_text(), key + '\n')
            host = (directory / 'ssh_host_ed25519_key').read_bytes()
            self.assertEqual((directory / 'ssh_host_ed25519_key').stat().st_mode & 0o777, 0o600)
            configure_files(etc, False, '')
            self.assertFalse((directory / 'developer-enabled').exists())
            self.assertIn('root:!:', (etc / 'shadow').read_text())
            configure_files(etc, True, key)
            self.assertEqual((directory / 'ssh_host_ed25519_key').read_bytes(), host)

    def test_failed_service_start_restores_config_and_key_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            etc = Path(temporary)
            (etc / 'shadow').write_text('root:!:19000:0:99999:7:::\n')
            store = ConfigStore(etc / 'config.json')
            old = store.load()
            router = System.__new__(System)
            router.store, router.state, router.wan = store, 'offline', None
            router.persist = Mock()
            router.ensure_no_pending_update = Mock()
            router.apply = Mock()
            key = Ed25519PrivateKey.generate().public_key().public_bytes(
                serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()

            def scoped_path(value):
                return etc / str(value).removeprefix('/etc/') if str(value).startswith('/etc/') else etc

            def run(args, **_kwargs):
                if args[-1] == 'start':
                    raise RuntimeError('service failed')
                return ''

            with patch('travelrouter.system.Path', side_effect=scoped_path), patch('travelrouter.system.command', side_effect=run):
                with self.assertRaises(RuntimeError):
                    router.save_developer({'enabled': True, 'public_key': key})
            self.assertEqual(store.load(), old)
            self.assertIn('root:!:', (etc / 'shadow').read_text())
            self.assertFalse((etc / 'travelrouter/developer-enabled').exists())
            self.assertFalse((etc / 'travelrouter/ssh_authorized_keys').exists())

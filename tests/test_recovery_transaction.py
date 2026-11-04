"""Update transaction setup preserves the last good boot generation."""
import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from travelrouter.recovery import RecoveryUnavailable, Transaction, ensure_ready
from travelrouter.system import System


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.medium = Path(self.temporary.name)
        self.overlay = self.medium / 'travelrouter.apkovl.tar.gz'
        self.old = gzip.compress(b'known-good user settings and application')
        self.overlay.write_bytes(self.old)
        (self.medium / 'repositories').mkdir()
        (self.medium / 'repositories/old').write_text('known good')

    def test_application_backup_is_verified_and_pending_update_cannot_be_replaced(self):
        transaction = Transaction(self.medium)
        transaction.prepare_application('0.2.1')
        backup = self.medium / '.travelrouter-recovery/overlay.gz'
        self.assertEqual(backup.read_bytes(), self.old)
        expected = hashlib.sha256(self.old).hexdigest()
        self.assertEqual((self.medium / '.travelrouter-update').read_text(),
                         f'v1 application prepared 0.2.1 {expected}\n')
        with self.assertRaises(ValueError):
            Transaction(self.medium).prepare_application('0.2.2')
        self.assertEqual(backup.read_bytes(), self.old)

    def test_invalid_overlay_never_arms_an_update(self):
        self.overlay.write_bytes(b'not gzip')
        with self.assertRaises((ValueError, OSError)):
            Transaction(self.medium).prepare_application('0.2.1')
        self.assertFalse((self.medium / '.travelrouter-update').exists())

    def test_old_image_without_early_recovery_refuses_to_stage(self):
        with self.assertRaises(RecoveryUnavailable):
            ensure_ready(self.medium)

    def test_commit_only_accepts_a_prepared_transaction(self):
        transaction = Transaction(self.medium)
        transaction.prepare_application('0.2.1')
        backup = (transaction.backup / 'overlay.gz').read_bytes()
        transaction.mark_ready()
        self.assertIn(' application ready ', transaction.marker.read_text())
        self.assertEqual((transaction.backup / 'overlay.gz').read_bytes(), backup)
        with self.assertRaises(ValueError):
            transaction.mark_ready()
        transaction.marker.write_text('invalid\n')
        with self.assertRaises(ValueError):
            transaction.mark_ready()

    def test_package_marker_is_durable_before_the_active_repository_moves(self):
        transaction = Transaction(self.medium)
        transaction.prepare_packages()
        self.assertEqual((self.medium / '.travelrouter-update').read_text(), 'v1 packages prepared - -\n')
        self.assertEqual((self.medium / 'repositories/old').read_text(), 'known good')
        transaction.back_up_repositories()
        self.assertFalse((self.medium / 'repositories').exists())
        self.assertEqual((self.medium / '.travelrouter-recovery/repositories/old').read_text(), 'known good')

    def test_settings_cannot_overwrite_a_pending_recovery_generation(self):
        router = System.__new__(System)
        transaction = Transaction(self.medium)
        with patch('travelrouter.system.boot_medium', return_value=self.medium), \
             patch('travelrouter.system.persist_overlay') as persist:
            transaction.prepare_application('0.2.1')
            with self.assertRaisesRegex(ValueError, 'pending update'):
                router.persist()
            router.persist_for_update()
            persist.assert_called_once()
            transaction.mark_ready()
            with self.assertRaises(ValueError):
                router.persist_for_update()


if __name__ == '__main__':
    unittest.main()

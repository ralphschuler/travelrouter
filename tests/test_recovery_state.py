"""Exercise real on-disk update recovery through interrupted transaction states."""
import gzip
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'rootfs/etc/travelrouter/recovery.sh'


class RecoveryStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.medium = Path(self.temporary.name)
        self.backup = self.medium / '.travelrouter-recovery'
        self.backup.mkdir()
        self.marker = self.medium / '.travelrouter-update'

    def transition(self, success=True):
        result = subprocess.run(['/bin/sh', str(SCRIPT), 'transition', str(self.medium)],
                                capture_output=True, text=True, check=False)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result.stdout.strip()

    def application_state(self, phase='ready'):
        old = gzip.compress(b'known-good overlay')
        (self.backup / 'overlay.gz').write_bytes(old)
        digest = hashlib.sha256(old).hexdigest()
        self.marker.write_text(f'v1 application {phase} 0.2.1 {digest}\n')
        (self.medium / 'travelrouter.apkovl.tar.gz').write_bytes(gzip.compress(b'candidate overlay'))
        return old

    def test_application_trial_then_failed_boot_restores_exact_previous_overlay(self):
        old = self.application_state()
        self.assertEqual(self.transition(), 'trial')
        self.assertIn(' application trial ', self.marker.read_text())
        self.assertEqual(self.transition(), 'rolled-back')
        self.assertEqual((self.medium / 'travelrouter.apkovl.tar.gz').read_bytes(), old)
        self.assertFalse(self.marker.exists())

    def test_corrupt_backup_never_overwrites_the_current_overlay(self):
        self.application_state('trial')
        (self.backup / 'overlay.gz').write_bytes(b'corrupt')
        current = (self.medium / 'travelrouter.apkovl.tar.gz').read_bytes()
        self.transition(success=False)
        self.assertEqual((self.medium / 'travelrouter.apkovl.tar.gz').read_bytes(), current)
        self.assertTrue(self.marker.exists())

    def test_application_interrupted_before_commit_never_trials_candidate(self):
        old = self.application_state('prepared')
        self.assertEqual(self.transition(), 'rolled-back')
        self.assertEqual((self.medium / 'travelrouter.apkovl.tar.gz').read_bytes(), old)

    def test_package_interruption_before_and_between_renames_restores_old_repository(self):
        self.marker.write_text('v1 packages prepared - -\n')
        active = self.medium / 'repositories'
        active.mkdir()
        (active / 'old').write_text('known good')
        self.assertEqual(self.transition(), 'rolled-back')
        self.assertEqual((active / 'old').read_text(), 'known good')
        self.marker.write_text('v1 packages prepared - -\n')
        active.rename(self.backup / 'repositories')
        self.assertEqual(self.transition(), 'rolled-back')
        self.assertEqual((active / 'old').read_text(), 'known good')
        self.assertFalse(self.marker.exists())

    def test_package_failed_trial_and_interrupted_rollback_keep_previous_generation(self):
        self.marker.write_text('v1 packages ready - -\n')
        old = self.backup / 'repositories'
        old.mkdir()
        (old / 'old').write_text('known good')
        active = self.medium / 'repositories'
        active.mkdir()
        (active / 'new').write_text('candidate')
        self.assertEqual(self.transition(), 'trial')
        self.assertEqual(self.transition(), 'rolled-back')
        self.assertEqual((active / 'old').read_text(), 'known good')
        self.assertEqual((self.backup / 'failed' / 'new').read_text(), 'candidate')
        self.marker.write_text('v1 packages trial - -\n')
        self.assertEqual(self.transition(), 'rolled-back')
        self.assertEqual((active / 'old').read_text(), 'known good')

    def test_uncommitted_package_candidate_rolls_back_without_a_trial(self):
        self.marker.write_text('v1 packages prepared - -\n')
        old = self.backup / 'repositories'
        old.mkdir()
        (old / 'old').write_text('known good')
        active = self.medium / 'repositories'
        active.mkdir()
        (active / 'new').write_text('candidate')
        self.assertEqual(self.transition(), 'rolled-back')
        self.assertEqual((active / 'old').read_text(), 'known good')

    def test_malformed_transaction_is_rejected_without_modification(self):
        self.marker.write_text('v1 application trial ../../bad wrong\n')
        self.transition(success=False)
        self.assertTrue(self.marker.exists())


if __name__ == '__main__':
    unittest.main()

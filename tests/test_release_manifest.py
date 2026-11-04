"""Publishing requires all architectures and excludes unintended files."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from image.release_manifest import expected_files, generate


class ReleaseManifestTests(unittest.TestCase):
    def test_missing_arm_installer_prevents_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in expected_files() - {'travelrouter-installer-aarch64.iso'}:
                (directory / name).write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError, 'travelrouter-installer-aarch64.iso'):
                generate(directory)
            self.assertFalse((directory / 'SHA256SUMS').exists())

    def test_unexpected_file_is_not_silently_included_in_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in expected_files() | {'unexpected.pem'}:
                (directory / name).write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError, 'unexpected.pem'):
                generate(directory)

    def test_complete_release_has_checksums_for_both_iso_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in expected_files():
                (directory / name).write_bytes(name.encode())
            (directory / 'SHA256SUMS').write_text('old manifest')
            generate(directory)
            checksums = dict(line.split('  ', 1)[::-1] for line in (directory / 'SHA256SUMS').read_text().splitlines())
            for architecture in ('aarch64', 'x86_64'):
                name = f'travelrouter-installer-{architecture}.iso'
                self.assertEqual(checksums[name], hashlib.sha256(name.encode()).hexdigest())
            self.assertNotIn('SHA256SUMS', checksums)


if __name__ == '__main__':
    unittest.main()

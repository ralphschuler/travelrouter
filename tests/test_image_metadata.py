"""Build provenance must identify the actual target and package architecture."""

import json
import tempfile
import unittest
from pathlib import Path

from image.sbom import generate


class ImageMetadataTests(unittest.TestCase):
    def test_generic_amd64_inventory_does_not_claim_arm_packages_or_cm5(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root, out = directory / 'check', directory / 'dist'
            database = root / 'lib/apk/db'
            database.mkdir(parents=True)
            out.mkdir()
            (database / 'installed').write_text(
                'P:python3\nV:3.14.10-r1\nA:x86_64\n\n'
                'P:dns-root-hints\nV:2024021501-r0\nA:noarch\n')
            generate(root, out, 'a' * 64, 'x86_64', 'generic-x86_64')
            metadata = json.loads((out / 'build-metadata.json').read_text())
            self.assertEqual(metadata['architecture'], 'x86_64')
            self.assertEqual(metadata['target'], 'generic-x86_64')
            self.assertNotIn('CM5', metadata['qualification'])
            packages = {item['name']: item['purl'] for item in
                        json.loads((out / 'sbom.cdx.json').read_text())['components']}
            self.assertIn('arch=x86_64', packages['python3'])
            self.assertIn('arch=noarch', packages['dns-root-hints'])

    def test_incompatible_target_architecture_is_rejected(self):
        with self.assertRaises(ValueError):
            generate('/unused', '/unused', 'a' * 64, 'x86_64', 'cm5')


if __name__ == '__main__':
    unittest.main()

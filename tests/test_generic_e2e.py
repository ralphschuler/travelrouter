"""Test boot-config instrumentation without touching release media."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'image/e2e'
RUN_SPEC = importlib.util.spec_from_file_location('image_boot_helpers', E2E / 'run.py')
RUN = importlib.util.module_from_spec(RUN_SPEC)
RUN_SPEC.loader.exec_module(RUN)
SPEC = importlib.util.spec_from_file_location('generic_image_e2e', E2E / 'generic.py')
GENERIC = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {'run': RUN}):
    SPEC.loader.exec_module(GENERIC)


class GenericBootConfigTests(unittest.TestCase):
    def test_preserves_shipped_kernel_initramfs_and_menu_paths(self):
        source = ("set timeout=3\nterminal_output gfxterm\nmenuentry 'TravelRouter (UEFI)' {\n"
                  " linux /boot/vmlinuz-lts modules=loop,squashfs quiet console=tty0\n"
                  " initrd /boot/initramfs-lts\n}\n")
        for architecture, console in [('x86_64', 'ttyS0'), ('aarch64', 'ttyAMA0')]:
            with self.subTest(architecture=architecture):
                result = GENERIC.instrument_grub(source, architecture)
                self.assertIn("menuentry 'TravelRouter (UEFI)'", result)
                self.assertIn('linux /boot/vmlinuz-lts modules=loop,squashfs', result)
                self.assertIn('initrd /boot/initramfs-lts', result)
                self.assertIn(f'console={console},115200 init=/bin/sh init_args=+i', result)
                self.assertNotIn('console=tty0', result)
                self.assertNotIn('quiet', result)
                self.assertNotIn('gfxterm', result)
                self.assertEqual(result.count('set timeout='), 1)

    def test_refuses_unknown_boot_configuration(self):
        with self.assertRaisesRegex(RuntimeError, 'No Linux boot entry'):
            GENERIC.instrument_grub('search --label UNKNOWN\n', 'x86_64')


if __name__ == '__main__':
    unittest.main()

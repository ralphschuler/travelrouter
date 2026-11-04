"""Production boot arguments must give every target the same RAM-root policy."""

import unittest

from image.boot_config import configure_cmdline, configure_grub


class RootFilesystemBootTests(unittest.TestCase):
    def test_adds_scaling_limit_without_replacing_other_kernel_arguments(self):
        original = 'modules=loop,squashfs,sd-mod,usb-storage quiet console=tty1\n'
        configured = configure_cmdline(original)
        self.assertEqual(configured, original.strip() + ' rootflags=size=75%\n')
        self.assertEqual(configure_cmdline(configured), configured)

    def test_replaces_duplicate_and_deprecated_sizes_but_retains_mount_options(self):
        configured = configure_cmdline(
            'rootflags=size=256M,noatime modules=loop root_size=512M '
            'rootflags=mode=0755,size=1G,noatime quiet\n')
        self.assertEqual(configured,
                         'modules=loop quiet rootflags=noatime,mode=0755,size=75%\n')
        self.assertEqual(configured.count('rootflags='), 1)
        self.assertNotIn('root_size=', configured)
        self.assertEqual(configure_cmdline(configured), configured)

    def test_configures_every_grub_kernel_entry_and_preserves_boot_paths(self):
        original = ("set timeout=3\nmenuentry 'TravelRouter (UEFI)' {\n"
                    '    linux /boot/vmlinuz-lts modules=loop quiet\n'
                    '    initrd /boot/initramfs-lts\n}\n'
                    "menuentry 'Recovery' {\n"
                    '    linuxefi /boot/vmlinuz-lts rootflags=size=256M,noatime\n'
                    '    initrdefi /boot/initramfs-lts\n}\n')
        configured = configure_grub(original)
        self.assertIn('linux /boot/vmlinuz-lts modules=loop quiet rootflags=size=75%\n', configured)
        self.assertIn('linuxefi /boot/vmlinuz-lts rootflags=noatime,size=75%\n', configured)
        self.assertIn('    initrd /boot/initramfs-lts\n', configured)
        self.assertIn('    initrdefi /boot/initramfs-lts\n', configured)
        self.assertEqual(configured.count('rootflags='), 2)
        self.assertEqual(configure_grub(configured), configured)

    def test_rejects_missing_kernel_command_lines(self):
        with self.assertRaises(ValueError):
            configure_cmdline(' \n')
        with self.assertRaises(ValueError):
            configure_grub('set timeout=3\n')


if __name__ == '__main__':
    unittest.main()

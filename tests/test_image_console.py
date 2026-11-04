"""Regression coverage for progress text seen during actual image boots."""

import importlib.util
import re
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'image_e2e_run', Path(__file__).resolve().parents[1] / 'image/e2e/run.py')
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


class ImageConsoleTests(unittest.TestCase):
    def test_apk_progress_and_recovery_prompt_are_not_root_readiness(self):
        # Real progress/prompt bytes from CI runs 41830155833 and 41830943569.
        for text in (b'\x1b7  2% # \x1b8\x1b[0K( 83/262) Installing linux-firmware-wfx\r\n',
                     b'\r\n~ # \x1b[6n', b'OK: 916.8 MiB in 262 packages\r\n'):
            with self.subTest(text=text):
                self.assertIsNone(re.search(HARNESS.BOOT_READY, text, re.MULTILINE))
        complete = b'[  241.546769] Installing packages to root filesystem: ok.\r\n'
        self.assertIsNotNone(re.search(HARNESS.BOOT_READY, complete, re.MULTILINE))

    def test_switch_root_failure_cannot_be_accepted_as_success(self):
        console = HARNESS.Console.__new__(HARNESS.Console)
        console.buffer = (b"switch_root: can't open '/dev/ttyAMA1': No such file or directory\r\n"
                          b"/bin/sh: can't access tty; job control turned off\r\n~ # \x1b[6n")
        with self.assertRaisesRegex(RuntimeError, 'Guest boot failed'):
            console.expect(HARNESS.BOOT_READY, 1, error_patterns=HARNESS.BOOT_ERRORS)

    def test_final_image_boot_options_and_root_sizing_are_preserved(self):
        source = ('modules=loop,squashfs,sd-mod,usb-storage quiet console=tty1 '
                  'rootflags=size=75% apkovl=travelrouter.apkovl.tar.gz\n')
        result = HARNESS.instrument_cmdline(source)
        self.assertIn('modules=loop,squashfs,sd-mod,usb-storage', result)
        self.assertIn('rootflags=size=75%', result)
        self.assertIn('apkovl=travelrouter.apkovl.tar.gz', result)
        self.assertIn('console=ttyAMA1,115200', result)
        self.assertIn('init=/bin/sh init_args=/proc/self/fd/0', result)
        self.assertNotIn('quiet', result)
        self.assertNotIn('console=tty1', result)

    def test_unknown_or_multiline_release_cmdline_fails_closed(self):
        for source in ('root=/dev/example', 'modules=loop\nrootflags=size=1G\n'):
            with self.subTest(source=source), self.assertRaises(RuntimeError):
                HARNESS.instrument_cmdline(source)


if __name__ == '__main__':
    unittest.main()

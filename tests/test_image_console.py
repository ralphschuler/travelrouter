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


if __name__ == '__main__':
    unittest.main()

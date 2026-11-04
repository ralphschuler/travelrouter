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
    def test_apk_progress_is_not_an_interactive_root_prompt(self):
        # Captured from the published image in CI run 41830155833.
        progress = (b'\x1b7  2% #                                           '
                    b'\x1b8\x1b[0K( 83/262) Installing linux-firmware-wfx (20260519-r0)\r\n')
        self.assertIsNone(re.search(HARNESS.SHELL_PROMPT, progress, re.MULTILINE))
        self.assertIsNone(re.search(HARNESS.SHELL_PROMPT, b'\r\n2% # ', re.MULTILINE))

    def test_prompt_is_exact_and_available_without_a_final_newline(self):
        for prompt in (b'/ # ', b'~ # '):
            with self.subTest(prompt=prompt):
                text = b'Package installation finished\r\n' + prompt
                self.assertIsNotNone(re.search(HARNESS.SHELL_PROMPT, text, re.MULTILINE))
        self.assertIsNone(re.search(HARNESS.SHELL_PROMPT, b'not a shell / # ', re.MULTILINE))

    def test_switch_root_recovery_prompt_is_not_successful_boot(self):
        # Captured from CI run 41830943569: a recovery shell printed a prompt
        # after the serial device failed to open, but could not accept input.
        console = HARNESS.Console.__new__(HARNESS.Console)
        console.buffer = (b"switch_root: can't open '/dev/ttyAMA1': No such file or directory\r\n"
                          b"/bin/sh: can't access tty; job control turned off\r\n~ # \x1b[6n")
        with self.assertRaisesRegex(RuntimeError, 'Guest boot failed'):
            console.expect(HARNESS.SHELL_PROMPT, 1, error_patterns=HARNESS.BOOT_ERRORS)

    def test_ash_cursor_query_is_answered_before_accepting_prompt(self):
        console = HARNESS.Console.__new__(HARNESS.Console)
        console.buffer = b'\r\n/ # \x1b[6n'
        replies = []
        console.send = replies.append
        output, _ = console.expect(HARNESS.SHELL_PROMPT, 1, error_patterns=HARNESS.BOOT_ERRORS)
        self.assertEqual(replies, ['\x1b[1;5R'])
        self.assertEqual(output, b'\r\n/ # ')


if __name__ == '__main__':
    unittest.main()

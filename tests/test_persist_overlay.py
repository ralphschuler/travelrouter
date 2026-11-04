"""A failed overlay save must not leave the boot medium writable."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from travelrouter.system import persist_overlay


class PersistOverlayTests(unittest.TestCase):
    def test_temporary_file_failure_always_remounts_boot_medium_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            medium = Path(temporary)
            calls = []
            with patch('travelrouter.system.boot_medium', return_value=medium), \
                    patch('travelrouter.system.command', side_effect=lambda args, **_: calls.append(args)), \
                    patch('travelrouter.system.tempfile.mkstemp', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    persist_overlay()
        self.assertEqual([call[2] for call in calls], ['remount,rw', 'remount,ro'])


if __name__ == '__main__':
    unittest.main()

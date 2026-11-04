"""The image gate must reject a panel replaced or lost during daemon restarts."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'image_e2e_lifecycle', Path(__file__).resolve().parents[1] / 'image/e2e/lifecycle.py')
LIFECYCLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIFECYCLE)


class LifecycleTests(unittest.TestCase):
    def test_restart_cannot_hide_a_replaced_controller_or_reused_pid(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'controller.json').write_text(json.dumps([123, 1000]))
            for replacement in ([124, 1001], [123, 1001]):
                with (self.subTest(replacement=replacement), patch.object(LIFECYCLE, 'DIRECTORY', directory),
                      patch.object(LIFECYCLE, 'controller_identity', return_value=replacement),
                      patch.object(LIFECYCLE, 'panel_http') as http):
                    with self.assertRaisesRegex(AssertionError, 'original panel process'):
                        LIFECYCLE.wait_restart('dnsmasq', previous=[200, 900])
                    http.assert_not_called()

    def test_changed_service_pid_does_not_mask_failed_http(self):
        with (patch.object(LIFECYCLE, 'assert_controller', return_value=[123, 1000]),
              patch.object(LIFECYCLE, 'service_identity', return_value=[201, 1001]),
              patch.object(LIFECYCLE, 'panel_http', side_effect=ConnectionRefusedError)):
            with self.assertRaises(ConnectionRefusedError):
                LIFECYCLE.wait_restart('unbound', previous=[200, 900])


if __name__ == '__main__':
    unittest.main()

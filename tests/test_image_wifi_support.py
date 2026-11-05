"""Release images must contain the signed wireless regulatory database."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'image_validate', Path(__file__).resolve().parents[1] / 'image/validate.py')
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class WirelessSupportTests(unittest.TestCase):
    def test_release_package_set_includes_wireless_regdb(self):
        packages = (Path(__file__).resolve().parents[1] / 'image/packages.txt').read_text().splitlines()
        self.assertIn('wireless-regdb', packages)

    def test_missing_regulatory_database_is_rejected(self):
        check = getattr(VALIDATOR, 'validate_wireless_regulatory_database', None)
        self.assertTrue(callable(check), 'image validator must check signed regulatory data')

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, 'wireless-regdb'):
                check(Path(temporary))

    def test_regulatory_database_requires_kernel_trusted_signature(self):
        check = getattr(VALIDATOR, 'validate_wireless_regulatory_database', None)
        self.assertTrue(callable(check), 'image validator must check signed regulatory data')

        with tempfile.TemporaryDirectory() as temporary:
            firmware = Path(temporary) / 'lib/firmware'
            firmware.mkdir(parents=True)
            (firmware / 'regulatory.db').write_bytes(b'database')
            with self.assertRaisesRegex(RuntimeError, 'signature'):
                check(Path(temporary))
            (firmware / 'regulatory.db.p7s').write_bytes(b'signature')
            check(Path(temporary))

    def test_cm5_kernel_audit_requires_maintained_usb_wifi_drivers(self):
        module_path = Path(__file__).resolve().parents[1] / 'image/wifi_support.py'
        self.assertTrue(module_path.is_file(), 'CM5 build must audit its kernel Wi-Fi module set')
        spec = importlib.util.spec_from_file_location('image_wifi_support', module_path)
        support = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(support)

        config = '\n'.join(f'{option}=m' for option in support.REQUIRED_USB_WIFI_MODULES)
        config += '\nCONFIG_BRCMFMAC=m\nCONFIG_BRCMFMAC_USB=y\n'
        modloop = '\n'.join(f'./lib/modules/kernel/{module}.ko.xz'
                            for module in support.REQUIRED_USB_WIFI_MODULES.values())
        modloop += '\n./lib/modules/kernel/brcmfmac.ko.xz\n'
        support.validate_kernel_wifi_support(config, modloop)

        with self.assertRaisesRegex(RuntimeError, 'rtw88_usb'):
            support.validate_kernel_wifi_support(config, modloop.replace('rtw88_usb.ko.xz', ''))


if __name__ == '__main__':
    unittest.main()

"""Fail CM5 builds if Alpine drops the supported USB Wi-Fi module set."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_USB_WIFI_MODULES = {
    'CONFIG_AT76C50X_USB': 'at76c50x_usb',
    'CONFIG_ATH6KL_USB': 'ath6kl_usb',
    'CONFIG_ATH9K_HTC': 'ath9k_htc',
    'CONFIG_AR5523': 'ar5523',
    'CONFIG_CARL9170': 'carl9170',
    'CONFIG_LIBERTAS_USB': 'libertas_usb',
    'CONFIG_LIBERTAS_THINFIRM_USB': 'libertas_tf_usb',
    'CONFIG_MT7601U': 'mt7601u',
    'CONFIG_MT76x0U': 'mt76x0u',
    'CONFIG_MT76x2U': 'mt76x2u',
    'CONFIG_MT7921U': 'mt7921u',
    'CONFIG_MT7925U': 'mt7925u',
    'CONFIG_P54_USB': 'p54usb',
    'CONFIG_RT2500USB': 'rt2500usb',
    'CONFIG_RT73USB': 'rt73usb',
    'CONFIG_RT2800USB': 'rt2800usb',
    'CONFIG_RTL8187': 'rtl8187',
    'CONFIG_RTL8192CU': 'rtl8192cu',
    'CONFIG_RTL8XXXU': 'rtl8xxxu',
    'CONFIG_RTW88_USB': 'rtw88_usb',
    'CONFIG_RTW89_USB': 'rtw89_usb',
    'CONFIG_ZD1211RW': 'zd1211rw',
}


def _kernel_options(text):
    options = {}
    for line in text.splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            name, value = line.split('=', 1)
            options[name] = value
        elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
            name = line[2:].split(' ', 1)[0]
            options[name] = 'n'
    return options


def _module_names(listing):
    names = set()
    for line in listing.splitlines():
        filename = Path(line.split()[-1]).name if line.split() else ''
        match = re.fullmatch(r'(.+)\.ko(?:\.(?:gz|xz|zst))?', filename)
        if match:
            names.add(match.group(1))
    return names


def validate_kernel_wifi_support(config_text, modloop_listing):
    options = _kernel_options(config_text)
    required_options = dict(REQUIRED_USB_WIFI_MODULES)
    required_options.update({'CONFIG_BRCMFMAC': 'brcmfmac'})
    missing_config = sorted(name for name in required_options if options.get(name) != 'm')
    if options.get('CONFIG_BRCMFMAC_USB') != 'y':
        missing_config.append('CONFIG_BRCMFMAC_USB=y')

    modules = _module_names(modloop_listing)
    missing_modules = sorted(module for module in required_options.values() if module not in modules)
    if missing_config or missing_modules:
        problems = []
        if missing_config:
            problems.append('kernel config missing: ' + ', '.join(missing_config))
        if missing_modules:
            problems.append('modloop missing: ' + ', '.join(missing_modules))
        raise RuntimeError('USB Wi-Fi support audit failed (' + '; '.join(problems) + ')')


def main(config_path, modloop_path):
    unsquashfs = shutil.which('unsquashfs', path='/usr/bin:/bin')
    if not unsquashfs:
        raise RuntimeError('Missing build utility: unsquashfs (squashfs-tools)')
    listing = subprocess.run([unsquashfs, '-ll', str(modloop_path)], check=True,
                             capture_output=True, text=True).stdout  # nosec B603
    validate_kernel_wifi_support(Path(config_path).read_text(), listing)
    print(f'Kernel Wi-Fi audit passed: {len(REQUIRED_USB_WIFI_MODULES) + 1} USB drivers', flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('usage: wifi_support.py KERNEL_CONFIG MODLOOP')
    main(sys.argv[1], sys.argv[2])

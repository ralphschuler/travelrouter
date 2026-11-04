"""Generate a root-owned APK overlay; never import host settings or keys."""

import os
import shutil
import sys
import tarfile
from pathlib import Path


def build(source, target):
    source, target = Path(source), Path(target)
    overlay = target / 'overlay'
    shutil.copytree(source / 'rootfs', overlay, dirs_exist_ok=True)
    shutil.copytree(source / 'src' / 'travelrouter', overlay / 'opt/travelrouter/travelrouter',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), dirs_exist_ok=True)
    packages = (source / 'image/packages.txt').read_text()
    (overlay / 'etc/apk').mkdir(parents=True, exist_ok=True)
    (overlay / 'etc/apk/world').write_text(packages)
    (overlay / 'etc/NetworkManager/system-connections').mkdir(parents=True, mode=0o700, exist_ok=True)
    (overlay / 'etc/NetworkManager/conf.d').mkdir(parents=True, exist_ok=True)
    (overlay / 'etc/hostapd').mkdir(parents=True, exist_ok=True)
    # A locked root account prevents the stock installer's passwordless login.
    (overlay / 'etc/shadow').write_text('root:!:19000:0:99999:7:::\n')
    (overlay / 'etc/shadow').chmod(0o600)
    services = {
        'sysinit': ['devfs', 'dmesg', 'udev', 'udev-trigger', 'hwdrivers', 'modloop'],
        'boot': ['modules', 'sysctl', 'hostname', 'bootmisc', 'syslog', 'localmount'],
        'default': ['dbus', 'networkmanager', 'hostapd', 'dnsmasq', 'unbound', 'chronyd',
                    'travelrouter-bootstrap', 'travelrouter'],
        'shutdown': ['mount-ro', 'killprocs', 'savecache'],
    }
    for level, names in services.items():
        directory = overlay / 'etc/runlevels' / level
        directory.mkdir(parents=True, exist_ok=True)
        for name in names:
            (directory / name).symlink_to('/etc/init.d/' + name)
    for path in (overlay / 'etc/init.d').iterdir():
        path.chmod(0o755)
    with tarfile.open(target / 'media/travelrouter.apkovl.tar.gz', 'w:gz') as archive:
        for directory in ('etc', 'opt'):
            archive.add(overlay / directory, arcname=directory, filter=root_owner)


def root_owner(info):
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    info.mtime = int(os.environ.get('SOURCE_DATE_EPOCH', '1793750400'))
    return info


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])

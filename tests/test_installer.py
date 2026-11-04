"""Exercise installer validation without running its entry point or opening devices."""

import ast
import gzip
import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

INSTALLER = Path(__file__).resolve().parents[1] / 'image/targets/install.sh'


def load_installer_functions():
    source = INSTALLER.read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY\n', 1)[0]
    tree = ast.parse(source, filename=str(INSTALLER))
    declarations = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            if isinstance(node, ast.FunctionDef):
                if node.decorator_list or node.args.defaults or node.args.kw_defaults:
                    raise AssertionError('Installer declarations gained executable defaults/decorators')
            declarations.append(node)
        elif isinstance(node, ast.Assign):
            # Constants may be loaded; calls or other executable expressions may not.
            allowed = (ast.Constant, ast.BinOp, ast.Mult)
            if (not all(isinstance(target, ast.Name) for target in node.targets)
                    or not all(isinstance(value, allowed) for value in ast.walk(node.value))):
                raise AssertionError('Installer constant contains executable expressions')
            declarations.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            declarations.append(node)
        elif not isinstance(node, ast.Try):
            raise AssertionError('Unexpected executable installer declaration')
    namespace = {'__name__': 'installer_validation_fixture'}
    exec(compile(ast.Module(body=declarations, type_ignores=[]), str(INSTALLER), 'exec'), namespace)
    return namespace


class InstallerValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='travelrouter-installer-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.installer = load_installer_functions()
        self.installer['platform'] = SimpleNamespace(machine=lambda: 'x86_64')

    def manifest(self):
        return {'format': 'travelrouter-install-v1', 'architecture': 'x86_64',
                'image_filename': 'travelrouter-generic-x86_64.img.gz',
                'compressed_sha256': 'a' * 64, 'compressed_bytes': 100,
                'image_sha256': 'b' * 64, 'image_bytes': 4096}

    def read_manifest(self, data):
        path = self.root / 'install-manifest.json'
        path.write_text(json.dumps(data))
        return self.installer['read_manifest'](path)

    def test_valid_manifest_is_accepted_for_matching_architecture(self):
        self.assertEqual(self.read_manifest(self.manifest()), self.manifest())

    def test_manifest_rejects_wrong_architecture_paths_hashes_and_sizes(self):
        changes = [
            ('format', 'another-format'), ('architecture', 'aarch64'), ('architecture', 'amd64'),
            ('image_filename', '../travelrouter-generic-x86_64.img.gz'),
            ('image_filename', '/dev/sda'), ('image_filename', 'different.img.gz'),
            ('compressed_sha256', 'A' * 64), ('compressed_sha256', 'g' * 64),
            ('compressed_sha256', 'a' * 63), ('image_sha256', None),
            ('image_sha256', 123), ('compressed_bytes', True), ('image_bytes', False),
            ('image_bytes', '4096'), ('image_bytes', 4096.0), ('image_bytes', 0),
            ('compressed_bytes', -1), ('compressed_bytes', 64 * 1024 ** 3 + 1),
            ('image_bytes', 64 * 1024 ** 3 + 512), ('image_bytes', 4097),
        ]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                data = self.manifest()
                data[field] = value
                with self.assertRaises(RuntimeError):
                    self.read_manifest(data)
        for field in self.manifest():
            with self.subTest(missing=field):
                data = self.manifest()
                del data[field]
                with self.assertRaises(RuntimeError):
                    self.read_manifest(data)
        for data in ([], None, 'not an object'):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                self.read_manifest(data)

    def payload(self, data=None):
        data = data if data is not None else b'installer validation sector'.ljust(512, b'\0') * 8
        path = self.root / 'payload.img.gz'
        path.write_bytes(gzip.compress(data, mtime=0))
        manifest = self.manifest()
        manifest.update(compressed_bytes=path.stat().st_size,
                        compressed_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        image_bytes=len(data), image_sha256=hashlib.sha256(data).hexdigest())
        return path, manifest

    def verify_payload(self, path, manifest):
        with path.open('rb') as stream:
            self.installer['verify_payload'](stream, manifest)
            self.assertEqual(stream.tell(), 0)

    def test_full_payload_validation_accepts_valid_gzip_and_hashes(self):
        self.verify_payload(*self.payload())

    def test_payload_rejects_modified_bytes_and_incorrect_size_or_hash(self):
        path, manifest = self.payload()
        for field, value in [('compressed_bytes', manifest['compressed_bytes'] + 1),
                             ('compressed_sha256', '0' * 64), ('image_sha256', '0' * 64),
                             ('image_bytes', manifest['image_bytes'] + 512)]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.verify_payload(path, {**manifest, field: value})
        changed = bytearray(path.read_bytes())
        changed[len(changed) // 2] ^= 1
        path.write_bytes(changed)
        with self.assertRaisesRegex(RuntimeError, 'Compressed image SHA256 mismatch'):
            self.verify_payload(path, manifest)

    def test_gzip_crc_is_checked_even_when_compressed_hash_matches(self):
        path, manifest = self.payload()
        data = bytearray(path.read_bytes())
        data[-8] ^= 1  # Damage the gzip CRC, then give the compressed bytes their correct hash.
        path.write_bytes(data)
        manifest['compressed_sha256'] = hashlib.sha256(data).hexdigest()
        with self.assertRaises(gzip.BadGzipFile):
            self.verify_payload(path, manifest)

    def test_compressed_expansion_cannot_exceed_declared_image_size(self):
        path, manifest = self.payload(bytes(2 * 1024 * 1024))
        manifest['image_bytes'] = 512
        with self.assertRaisesRegex(RuntimeError, 'Expanded image exceeds'):
            self.verify_payload(path, manifest)


class InstallerDiskSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='travelrouter-device-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.installer = load_installer_functions()
        (self.root / 'sys/dev/block').mkdir(parents=True)
        (self.root / 'proc/self').mkdir(parents=True)
        (self.root / 'proc/self/mountinfo').write_text('')
        (self.root / 'proc/swaps').write_text('Filename Type Size Used Priority\n')
        self.stats = {}
        self.fd_stats = {}
        self.disks = {}
        self.sda = self.device('sda', '8:0')
        self.sda1 = self.device('sda1', '8:1', self.sda)
        self.sdb = self.device('sdb', '8:16')
        for name, number in [('sda', '8:0'), ('sdb', '8:16')]:
            self.disks['/dev/' + name] = {'path': '/dev/' + name, 'number': number,
                                         'size': 8 * 1024 ** 3, 'readonly': False,
                                         'model': 'Fixture disk', 'serial': name, 'wwn': ''}
        self.installer['Path'] = self.fixture_path
        self.installer['os'] = SimpleNamespace(major=os.major, minor=os.minor,
                                               stat=self.fixture_stat, fstat=lambda fd: self.fd_stats[fd])
        self.installer['disk_snapshot'] = lambda: {key: dict(value) for key, value in self.disks.items()}

    def fixture_path(self, value):
        if str(value).startswith(('/proc/', '/sys/')):
            return self.root / str(value).lstrip('/')
        return Path(value)

    def fixture_stat(self, path):
        try:
            return self.stats[str(path)]
        except KeyError as error:
            raise FileNotFoundError(f'No fixture path: {path}') from error

    @staticmethod
    def file_stat(number, block=False):
        major, minor = map(int, number.split(':'))
        device = os.makedev(major, minor)
        return SimpleNamespace(st_mode=stat.S_IFBLK if block else stat.S_IFREG,
                               st_rdev=device if block else 0, st_dev=0 if block else device)

    def device(self, name, number, parent=None):
        node = (parent if parent is not None else self.root / 'sys/devices/block') / name
        node.mkdir(parents=True)
        (node / 'dev').write_text(number)
        (node / 'diskseq').write_text('42')
        if parent is not None:
            (node / 'partition').write_text('1')
        (self.root / 'sys/dev/block' / number).symlink_to(node)
        self.stats['/dev/' + name] = self.file_stat(number, block=True)
        return node

    def mount(self, number):
        (self.root / 'proc/self/mountinfo').write_text(f'42 1 {number} / /media/installer ro - auto /dev/fixture ro\n')

    def reject_sda_but_allow_spare(self, sources=()):
        with self.assertRaisesRegex(RuntimeError, 'mounted, used for swap'):
            self.installer['inspect_target']('/dev/sda', 4096, sources)
        accepted = self.installer['inspect_target']('/dev/sdb', 4096, sources)
        self.assertEqual(accepted['number'], '8:16')

    def test_mounted_partition_protects_whole_disk_but_not_unrelated_spare(self):
        self.mount('8:1')
        self.reject_sda_but_allow_spare()

    def test_payload_source_files_protect_their_underlying_disk(self):
        self.fd_stats[123] = self.file_stat('8:1')
        source = SimpleNamespace(fileno=lambda: 123)
        self.reject_sda_but_allow_spare([source])

    def test_swap_partition_and_escaped_swapfile_paths_protect_ancestors(self):
        for filename, kind in [('/dev/sda1', 'partition'), ('/swap\\040file', 'file')]:
            with self.subTest(kind=kind):
                self.stats['/swap file'] = self.file_stat('8:1')
                (self.root / 'proc/swaps').write_text('Filename Type Size Used Priority\n'
                                                     f'{filename} {kind} 4096 0 -2\n')
                self.reject_sda_but_allow_spare()

    def test_mounted_mapper_protects_slave_partition_and_physical_parent(self):
        mapper = self.device('dm-0', '253:0')
        (mapper / 'slaves').mkdir()
        (mapper / 'slaves/sda1').symlink_to(self.sda1)
        self.mount('253:0')
        self.reject_sda_but_allow_spare()

    def test_loop_image_on_mapper_protects_backing_disk_ancestry(self):
        mapper = self.device('dm-0', '253:0')
        (mapper / 'slaves').mkdir()
        (mapper / 'slaves/sda1').symlink_to(self.sda1)
        loop = self.device('loop0', '7:0')
        (loop / 'loop').mkdir()
        (loop / 'loop/backing_file').write_text('/images/installer.iso')
        self.stats['/images/installer.iso'] = self.file_stat('253:0')
        self.mount('7:0')
        self.reject_sda_but_allow_spare()

    def test_unknown_mounted_device_ancestry_fails_closed(self):
        self.mount('8:99')
        with self.assertRaisesRegex(RuntimeError, 'Cannot establish ancestry'):
            self.installer['inspect_target']('/dev/sda', 4096, [])

    def test_partition_regular_file_readonly_and_undersized_targets_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'whole disk'):
            self.installer['inspect_target']('/dev/sda1', 4096, [])
        self.stats['/dev/sda'] = self.file_stat('8:0')
        with self.assertRaisesRegex(RuntimeError, 'not a block device'):
            self.installer['inspect_target']('/dev/sda', 4096, [])
        self.stats['/dev/sda'] = self.file_stat('8:0', block=True)
        self.disks['/dev/sda']['readonly'] = True
        with self.assertRaisesRegex(RuntimeError, 'read-only'):
            self.installer['inspect_target']('/dev/sda', 4096, [])
        self.disks['/dev/sda']['readonly'] = False
        with self.assertRaisesRegex(RuntimeError, 'smaller'):
            self.installer['inspect_target']('/dev/sda', 9 * 1024 ** 3, [])

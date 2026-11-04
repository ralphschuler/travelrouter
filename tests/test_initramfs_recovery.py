"""The early recovery hook must run before Alpine loads state or packages."""
import gzip
import unittest

from image.initramfs_recovery import archive, entries, patch


class InitramfsRecoveryTests(unittest.TestCase):
    def test_injects_recovery_before_overlay_and_handles_install_failures(self):
        init = (b'#!/bin/sh\n'
                b'\t$repoopts -a "$ROOT"/tmp/apkovls\neend $?\n'
                b'\tunpack_apkovl "$ovl" "$sysroot"\n\teend $? "$errstr" || ovlfiles=\n'
                b'\t\techo "WARNING: apkovl packages install completed with errors..." > "$ROOT"/dev/kmsg\n'
                b'\t\techo "WARNING: apkovl packages install completed with errors..." > "$ROOT"/dev/kmsg\n')
        original = gzip.compress(archive([('init', 0o100755, init)]), mtime=0)
        patched = patch(original, b'#!/bin/sh\nexit 0\n')
        files = dict((name, data) for name, _mode, data in entries(gzip.decompress(patched)))
        result = files['init']
        self.assertLess(result.index(b'travelrouter-recovery early'), result.index(b'unpack_apkovl'))
        self.assertEqual(result.count(b'travelrouter-recovery failure'), 3)
        self.assertEqual(files['sbin/travelrouter-recovery'], b'#!/bin/sh\nexit 0\n')
        with self.assertRaises(ValueError):
            patch(patched, b'#!/bin/sh\nexit 0\n')

    def test_unknown_upstream_init_fails_closed(self):
        original = gzip.compress(archive([('init', 0o100755, b'#!/bin/sh\necho unknown\n')]), mtime=0)
        with self.assertRaises(ValueError):
            patch(original, b'#!/bin/sh\nexit 0\n')


if __name__ == '__main__':
    unittest.main()

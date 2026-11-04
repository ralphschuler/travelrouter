"""Boot the built image with its shipped RPi kernel and exercise real services.

The CI-only init override starts an interactive shell after Alpine has restored
the image's apkovl and installed its packages. It injects simulated radio hardware
before starting the unchanged OpenRC runlevels. Production code is never patched.
"""

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
import secrets
import select
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE = '/root/ci-image-test'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def host_command(arguments):
    # All executable names are fixed by this harness; image paths are absolute.
    return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout  # nosec B603


def executable(name):
    path = shutil.which(name)
    require(path is not None, f'Missing host test dependency: {name}')
    return path


def expand_image(source, target):
    compressed_hash = hashlib.sha256()
    with source.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            compressed_hash.update(chunk)
    digest = hashlib.sha256()
    zeroes = bytes(1024 * 1024)
    with gzip.open(source, 'rb') as compressed, target.open('wb') as output:
        for chunk in iter(lambda: compressed.read(1024 * 1024), b''):
            digest.update(chunk)
            if chunk == zeroes[:len(chunk)]:
                output.seek(len(chunk), os.SEEK_CUR)
            else:
                output.write(chunk)
        output.truncate()
    return compressed_hash.hexdigest(), digest.hexdigest()


class Console:
    def __init__(self, command, logfile):
        self.log = logfile.open('wb')
        # QEMU is isolated software emulation, with no host network or device access.
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,  # nosec B603
                                        stderr=subprocess.STDOUT, bufsize=0)
        self.buffer = b''
        self.ready = False

    def send(self, text):
        require(self.process.poll() is None, 'QEMU exited before the command could run')
        self.process.stdin.write(text.encode())
        self.process.stdin.flush()

    def expect(self, pattern, timeout):
        started = time.monotonic()
        deadline = started + timeout
        progress_at = started + 30
        received = 0
        compiled = re.compile(pattern, re.MULTILINE)
        while time.monotonic() < deadline:
            if time.monotonic() >= progress_at:
                print(f'Guest wait: {int(time.monotonic() - started)}s elapsed; '
                      f'{received} serial bytes received', flush=True)
                progress_at = time.monotonic() + 30
            if b'Kernel panic - not syncing' in self.buffer:
                raise RuntimeError('Guest kernel panic; see console.log for the complete boot trace')
            match = compiled.search(self.buffer)
            if match:
                output = self.buffer[:match.end()]
                self.buffer = self.buffer[match.end():]
                return output, match
            if self.process.poll() is not None:
                remaining = self.process.stdout.read()
                if remaining:
                    self.log.write(remaining)
                    self.log.flush()
                raise RuntimeError(f'QEMU exited unexpectedly ({self.process.returncode})')
            readable, _, _ = select.select([self.process.stdout], [], [], 0.5)
            if readable:
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if chunk:
                    received += len(chunk)
                    self.log.write(chunk)
                    self.log.flush()
                    self.buffer += chunk
                    require(len(self.buffer) < 32 * 1024 * 1024, 'Guest output exceeded the bounded log window')
        raise TimeoutError(f'Guest did not reach expected state within {timeout} seconds')

    def boot(self):
        self.expect(rb'(?:^|\r?\n)[^\r\n]*# ', 900)
        self.ready = True
        self.command('stty -echo', timeout=10)
        self.command(f'mkdir -p {REMOTE}; chmod 700 {REMOTE}', timeout=10)
        self.command('test -f /opt/travelrouter/travelrouter/web.py', timeout=10)

    def command(self, command, timeout=120, check=True):
        marker = 'CI_DONE_' + secrets.token_hex(8)
        self.buffer = b''
        self.send(f"( {command}\n); result=$?; printf '\\n{marker}:%s\\n' \"$result\"\n")
        output, match = self.expect((r'^' + marker + r':([0-9]+)\r?$').encode(), timeout)
        status = int(match.group(1))
        if check and status:
            raise RuntimeError(f'Guest command failed ({status}): {command[:140]}\n'
                               + output.decode(errors='replace')[-3000:])
        return output.decode(errors='replace')

    def upload(self, path):
        content = base64.b64encode(path.read_bytes()).decode()
        lines = '\n'.join(content[position:position + 512] for position in range(0, len(content), 512))
        delimiter = 'CI_FILE_' + secrets.token_hex(8)
        self.command(f"base64 -d > {REMOTE}/{path.name} <<'{delimiter}'\n{lines}\n{delimiter}", timeout=30)

    def diagnostics(self, output):
        if not self.ready or self.process.poll() is not None:
            return
        commands = {
            'services.txt': 'rc-status -a',
            'interfaces.txt': 'ip -details address; ip route; iw dev',
            'listeners.txt': 'ss -lntup',
            'firewall.txt': 'nft list ruleset',
            'system.log': 'logread 2>/dev/null || tail -n 250 /var/log/messages',
            'application.log': 'tail -n 250 /var/log/travelrouter.log',
            'client-wifi.log': f'tail -n 150 {REMOTE}/client-wpa.log',
            'kernel.log': 'dmesg | tail -n 100',
        }
        for name, command in commands.items():
            try:
                result = self.command(command, timeout=10, check=False)
                (output / name).write_text(result)
            except (OSError, RuntimeError, TimeoutError):
                break

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log.close()


def run(args, report):
    source = args.image.resolve()
    require(source.is_file() and source.name.endswith('.img.gz'), 'Expected a built regular .img.gz file')
    args.output.mkdir(parents=True, exist_ok=True)
    args.scratch.mkdir(parents=True, exist_ok=True)
    qemu, qemu_img, mcopy = (executable(name) for name in ('qemu-system-aarch64', 'qemu-img', 'mcopy'))
    report['qemu'] = host_command([qemu, '--version']).splitlines()[0]
    require('raspi4b' in host_command([qemu, '-machine', 'help']), 'QEMU must support raspi4b')
    raw = args.scratch / 'release.img'
    report['archive_sha256'], report['image_sha256'] = expand_image(source, raw)
    report['image_bytes'] = raw.stat().st_size
    with raw.open('rb') as stream:
        mbr = stream.read(512)
    require(mbr[510:512] == b'\x55\xaa', 'Built image has no MBR signature')
    offset = struct.unpack_from('<I', mbr, 446 + 8)[0] * 512
    require(offset == 1024 * 1024, 'Unexpected release boot partition offset')
    for source_path, destination in [('boot/vmlinuz-rpi', 'kernel'), ('boot/initramfs-rpi', 'initramfs'),
                                     ('bcm2711-rpi-4-b.dtb', 'board.dtb')]:
        host_command([mcopy, '-o', '-i', f'{raw}@@{offset}', f'::/{source_path}',
                      str(args.scratch / destination)])
    kernel = args.scratch / 'kernel'
    if kernel.read_bytes()[:2] == b'\x1f\x8b':
        kernel.write_bytes(gzip.decompress(kernel.read_bytes()))
    overlay = args.scratch / 'runtime.qcow2'
    require(not overlay.exists(), 'Use a fresh image E2E scratch directory')
    capacity = 1 << (raw.stat().st_size - 1).bit_length()
    host_command([qemu_img, 'create', '-f', 'qcow2', '-F', 'raw', '-b', str(raw), str(overlay), str(capacity)])
    # The shipped Pi4 DTB aliases PL011 as serial1; Raspberry Pi firmware normally
    # applies console fixups, which QEMU's direct kernel boot deliberately skips.
    # The kernel's PL011 driver uses that alias index, so this is ttyAMA1 here.
    command = [qemu, '-machine', 'raspi4b', '-accel', 'tcg,thread=multi', '-m', '2G', '-smp', '4',
               '-display', 'none', '-monitor', 'none', '-serial', 'stdio', '-nic', 'none', '-no-reboot',
               '-kernel', str(kernel), '-initrd', str(args.scratch / 'initramfs'),
               '-dtb', str(args.scratch / 'board.dtb'), '-drive', f'file={overlay},if=sd,format=qcow2',
               '-append', 'earlycon=pl011,mmio32,0xfe201000 console=ttyAMA1,115200 '
                          'modules=loop,squashfs,sd-mod,usb-storage '
                          'init=/bin/sh init_args=-i rootflags=size=1536M']
    report['boundary'] = ('Shipped RPi kernel/initramfs and image packages/apkovl on QEMU raspi4b; '
                          'CI init shell and mac80211_hwsim radios. No CM5 firmware, RP1 or physical radio qualification.')
    for phase in ('initial', 'restored'):
        report['stage'] = phase + ': boot'
        print('Booting real image:', phase, flush=True)
        output = args.output / phase
        output.mkdir(exist_ok=True)
        console = Console(command, output / 'console.log')
        try:
            console.boot()
            console.upload(HERE / 'prepare.sh')
            console.upload(HERE / 'client.py')
            report['stage'] = phase + ': OpenRC, WPA2 and DHCP'
            console.command(f'sh {REMOTE}/prepare.sh {phase}', timeout=240)
            # Verify the synthetic external server is really alive before testing denial.
            console.command("ip netns exec tr-untrusted python3 -c \"import socket; "
                            "socket.create_connection(('198.18.0.2',8080),3).close()\"")
            console.command(f'ip netns exec tr-untrusted python3 {REMOTE}/client.py untrusted', timeout=30)
            report['stage'] = phase + ': client HTTP, DNS and credentials'
            result = console.command(f'ip netns exec tr-client python3 {REMOTE}/client.py {phase}', timeout=120)
            (output / 'client-results.txt').write_text(result)
            report.setdefault('passed', []).append(phase)
            console.command('sync', timeout=30)
            # QEMU termination is a cold restart. The application must have fsynced
            # its overlay; no source image mutation or special reboot fixture is used.
        finally:
            console.diagnostics(output)
            console.close()
    report.update(result='passed', stage='complete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    args.image, args.output, args.scratch = (path.resolve() for path in (args.image, args.output, args.scratch))
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'result': 'failed', 'stage': 'host preparation'}
    started = time.monotonic()
    try:
        run(args, report)
    except (OSError, RuntimeError, ValueError, TimeoutError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
        print('IMAGE E2E FAILED:', error, file=sys.stderr, flush=True)
    finally:
        report['duration_seconds'] = round(time.monotonic() - started, 1)
        (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    if report['result'] != 'passed':
        return 1
    print('IMAGE E2E PASSED: real OpenRC startup, WPA2, DHCP, DNS, HTTP, setup and cold reboot', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

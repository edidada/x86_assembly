#!/usr/bin/env python3
"""Boot a raw disk image in QEMU and verify VGA text output via QMP.

Starts qemu-system-i386 headless with a QMP socket, waits for the guest to
run, reads physical memory at 0xB8000 (the VGA text-mode framebuffer) with
the HMP `xp` command, and checks that the expected string was written.

Usage:
    python3 scripts/verify_boot.py --image disk.img --expect "1+2+3=5050" \
        [--screenshot screen.ppm] [--timeout 20]
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time

VGA_TEXT_ADDR = 0xB8000
QMP_SOCKET = "qmp.sock"


class QMP:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.buf = b""
        self._greeting()

    def _readline(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("QMP socket closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)

    def _greeting(self):
        g = self._readline()
        if "QMP" not in g:
            raise RuntimeError(f"unexpected greeting: {g}")

    def cmd(self, execute, arguments=None, timeout=15):
        msg = {"execute": execute}
        if arguments is not None:
            msg["arguments"] = arguments
        self.sock.sendall((json.dumps(msg) + "\n").encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self._readline()
            if "return" in resp or "error" in resp:
                return resp
        raise TimeoutError(f"no response for {execute}")

    def hmp(self, command, timeout=15):
        resp = self.cmd("human-monitor-command",
                        {"command-line": command}, timeout=timeout)
        if "error" in resp:
            raise RuntimeError(f"HMP error: {resp['error']}")
        return resp["return"]


def wait_for_socket(path, proc, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return
        if proc.poll() is not None:
            raise RuntimeError(f"qemu exited early with code {proc.returncode}")
        time.sleep(0.1)
    raise TimeoutError("QMP socket did not appear")


def read_vga_text(qmp, nbytes=1024):
    """Read nbytes from 0xB8000 via HMP xp (hex bytes), decode text.

    VGA text-mode framebuffer stores a character byte followed by an
    attribute byte for each cell. Reading as hex avoids mis-parsing
    quoted control bytes in HMP's char format.
    """
    raw = qmp.hmp(f"xp/{nbytes}xb {VGA_TEXT_ADDR:#x}")
    data = []
    for line in raw.splitlines():
        if ":" not in line:
            continue
        payload = line.split(":", 1)[1].strip()
        for tok in payload.split():
            try:
                data.append(int(tok, 16))
            except ValueError:
                pass
    # Character byte is at even offsets; attribute byte at odd offsets.
    chars = "".join(chr(b) if 0x20 <= b <= 0x7E else " " for b in data[0::2])
    return chars, raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="raw disk image to boot")
    ap.add_argument("--expect", required=True,
                    help="substring that must appear in VGA text")
    ap.add_argument("--screenshot", default=None, help="HMP screendump path")
    ap.add_argument("--timeout", type=int, default=25,
                    help="seconds to wait for expected text")
    args = ap.parse_args()

    if os.path.exists(QMP_SOCKET):
        os.remove(QMP_SOCKET)

    qemu = subprocess.Popen([
        "qemu-system-i386",
        "-drive", f"file={args.image},format=raw,index=0,media=disk",
        "-boot", "order=c",
        "-display", "none",
        "-qmp", f"unix:{QMP_SOCKET},server,nowait",
        "-no-reboot",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    qmp = None
    text = ""
    raw = ""
    try:
        wait_for_socket(QMP_SOCKET, qemu)
        qmp = QMP(QMP_SOCKET)
        qmp.cmd("qmp_capabilities")

        deadline = time.time() + args.timeout
        while time.time() < deadline:
            text, raw = read_vga_text(qmp)
            if args.expect in text:
                break
            time.sleep(0.5)

        print("===== VGA text buffer @ 0xB8000 =====")
        print(text[:512])
        print("======================================")

        if args.screenshot:
            try:
                qmp.hmp(f"screendump {args.screenshot}")
                print(f"screenshot saved: {args.screenshot}")
            except Exception as e:  # screendump is best-effort
                print(f"screendump skipped: {e}")

        if args.expect not in text:
            print(f"::error::expected text {args.expect!r} not found in VGA output")
            print("----- raw xp dump -----")
            print(raw[:4000])
            return 1

        print(f"OK: found {args.expect!r} in guest VGA output")
        return 0
    finally:
        if qmp:
            try:
                qmp.cmd("quit")
            except Exception:
                pass
        if qemu.poll() is None:
            qemu.terminate()
            try:
                qemu.wait(timeout=10)
            except subprocess.TimeoutExpired:
                qemu.kill()
        if os.path.exists(QMP_SOCKET):
            os.remove(QMP_SOCKET)


if __name__ == "__main__":
    sys.exit(main())

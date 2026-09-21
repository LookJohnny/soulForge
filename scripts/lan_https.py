"""Serve a page on the LAN over whichever protocol the browser picks.

Two problems solved in one place, both of which look like "the server is down":

  * A browser decides on its own whether a bare ``host:port`` means http or
    https, and a plaintext port answers a TLS handshake with nothing.
  * ``getUserMedia`` only exists in a secure context, so a page served as
    http:// over a LAN address has no microphone and no camera at all —
    indistinguishable from a machine with no devices.

Answering https with a self-signed certificate fixes both: the browser warns
once, the user clicks through, and from then on the origin is secure.
"""

from __future__ import annotations

import socket
import ssl
import subprocess
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

# ── one port, either protocol ────────────────────────────────

LAN_CERT = Path.home() / ".cache" / "soulforge" / "lan-cert.pem"
LAN_KEY = Path.home() / ".cache" / "soulforge" / "lan-key.pem"


def local_ips() -> list[str]:
    """Every IPv4 this machine answers on.

    A Mac with both ethernet and wifi sits on two subnets, and the one the
    phone can reach is not always the one `ipconfig getifaddr en0` prints.
    """
    ips = {"127.0.0.1"}
    for iface in ("en0", "en1", "en2", "en3"):
        try:
            out = subprocess.run(
                ["ipconfig", "getifaddr", iface],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        addr = out.stdout.strip()
        if addr:
            ips.add(addr)
    return sorted(ips)


def lan_tls_context(bind_ips: list[str]) -> ssl.SSLContext | None:
    """A self-signed context for this machine's addresses, or None."""
    if not (LAN_CERT.exists() and LAN_KEY.exists()):
        sans = ",".join(f"IP:{ip}" for ip in bind_ips)
        LAN_CERT.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-days", "825", "-subj", "/CN=soulforge-lan",
                    "-addext", f"subjectAltName={sans},DNS:localhost",
                    "-keyout", str(LAN_KEY), "-out", str(LAN_CERT),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ctx.load_cert_chain(str(LAN_CERT), str(LAN_KEY))
    except (OSError, ssl.SSLError):
        return None
    return ctx


class DualProtocolServer(ThreadingHTTPServer):
    """Answer http and https on the same port.

    Browsers decide on their own whether a bare `host:port` means http or
    https, and a phone or laptop that picks https gets nothing back from a
    plaintext port — no error the user can act on, just a page that will not
    load. Peeking at the first byte costs nothing and removes the guess: 0x16
    is a TLS handshake, anything else is a request line.
    """

    tls: ssl.SSLContext | None = None

    def get_request(self):
        sock, addr = super().get_request()
        if self.tls is None:
            return sock, addr
        try:
            sock.settimeout(10)
            first = sock.recv(1, socket.MSG_PEEK)
        except OSError:
            return sock, addr
        finally:
            sock.settimeout(None)
        if first == b"\x16":
            print(f"[http] {addr[0]} 用 https 进来，已用自签证书接住", flush=True)
            return self.tls.wrap_socket(sock, server_side=True), addr
        return sock, addr

    def handle_error(self, request, client_address):
        # A refused certificate is the user clicking "go back", not a crash.
        exc = sys.exception()
        if isinstance(exc, ssl.SSLError):
            print(f"[http] {client_address[0]} TLS 握手未完成：{exc.reason}", flush=True)
            return
        super().handle_error(request, client_address)


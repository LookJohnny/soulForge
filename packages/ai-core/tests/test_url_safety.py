"""Tests for the SSRF protection boundary. No network access — DNS is
exercised through the injectable resolver hook."""

import pytest

from ai_core.services.url_safety import (
    _is_safe_ip,
    _resolve_and_validate,
    _rewrite_to_ip,
    assert_public_http_url,
)


class TestIsSafeIp:
    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",  # loopback
            "10.0.0.1",  # private
            "172.16.0.1",  # private
            "192.168.1.1",  # private
            "169.254.169.254",  # link-local (cloud metadata!)
            "100.64.0.1",  # CGNAT shared space
            "224.0.0.1",  # multicast
            "240.0.0.1",  # reserved
            "0.0.0.0",  # unspecified
            "::1",  # v6 loopback
            "fe80::1",  # v6 link-local
            "fd00::1",  # v6 ULA (private)
            "::ffff:127.0.0.1",  # IPv4-mapped loopback
            "::ffff:192.168.1.1",  # IPv4-mapped private
            "not-an-ip",  # garbage
            "",
        ],
    )
    def test_unsafe_addresses_rejected(self, ip):
        assert not _is_safe_ip(ip)

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "104.16.0.1",
            "2001:4860:4860::8888",  # public v6
            "::ffff:8.8.8.8",  # IPv4-mapped public
        ],
    )
    def test_public_addresses_accepted(self, ip):
        assert _is_safe_ip(ip)


class TestResolveAndValidate:
    async def test_rejects_non_http_scheme(self):
        with pytest.raises(RuntimeError, match="http"):
            await _resolve_and_validate("ftp://example.com/file")

    async def test_rejects_missing_hostname(self):
        with pytest.raises(RuntimeError):
            await _resolve_and_validate("http:///path")

    async def test_rejects_credentialed_url(self):
        with pytest.raises(RuntimeError, match="credential"):
            await _resolve_and_validate("https://user:pass@example.com/")

    async def test_rejects_literal_private_ip(self):
        with pytest.raises(RuntimeError, match="non-public"):
            await _resolve_and_validate("http://192.168.1.172:8080/")

    async def test_rejects_literal_loopback(self):
        with pytest.raises(RuntimeError, match="non-public"):
            await _resolve_and_validate("http://127.0.0.1/")

    async def test_accepts_literal_public_ip(self):
        host, port, ips = await _resolve_and_validate("http://8.8.8.8/x")
        assert host == "8.8.8.8"
        assert port == 80
        assert ips == ["8.8.8.8"]

    async def test_default_https_port(self):
        _, port, _ = await _resolve_and_validate("https://1.1.1.1/")
        assert port == 443

    async def test_hostname_resolving_to_public_ip_ok(self):
        async def resolver(host, port):
            return ["93.184.216.34"]

        host, port, ips = await _resolve_and_validate("https://example.com/a", resolver=resolver)
        assert host == "example.com"
        assert ips == ["93.184.216.34"]

    async def test_hostname_resolving_to_private_ip_rejected(self):
        """DNS 指向内网 = 经典 SSRF，必须拦截。"""

        async def resolver(host, port):
            return ["10.0.0.5"]

        with pytest.raises(RuntimeError, match="non-public"):
            await _resolve_and_validate("https://evil.example/a", resolver=resolver)

    async def test_mixed_resolution_rejected(self):
        """哪怕只有一个解析结果是内网 IP 也要整体拒绝（防轮询绕过）。"""

        async def resolver(host, port):
            return ["93.184.216.34", "192.168.0.10"]

        with pytest.raises(RuntimeError, match="non-public"):
            await _resolve_and_validate("https://evil.example/a", resolver=resolver)

    async def test_empty_resolution_rejected(self):
        async def resolver(host, port):
            return []

        with pytest.raises(RuntimeError, match="did not resolve"):
            await _resolve_and_validate("https://ghost.example/", resolver=resolver)

    async def test_resolver_oserror_wrapped(self):
        async def resolver(host, port):
            raise OSError("dns down")

        with pytest.raises(RuntimeError, match="unable to resolve"):
            await _resolve_and_validate("https://example.com/", resolver=resolver)


class TestRewriteToIp:
    def test_ipv4_with_port(self):
        assert (
            _rewrite_to_ip("https://example.com:8443/a?b=1", "1.2.3.4")
            == "https://1.2.3.4:8443/a?b=1"
        )

    def test_ipv6_gets_brackets(self):
        out = _rewrite_to_ip("https://example.com/a", "2001:db8::1")
        assert out.startswith("https://[2001:db8::1]/")

    def test_empty_path_becomes_slash(self):
        assert _rewrite_to_ip("http://example.com", "1.2.3.4") == "http://1.2.3.4/"


class TestAssertPublicHttpUrl:
    async def test_blocks_loopback_literal(self):
        with pytest.raises(RuntimeError):
            await assert_public_http_url("http://127.0.0.1:8100/internal")

    async def test_blocks_metadata_endpoint(self):
        """云厂商 metadata 169.254.169.254 是 SSRF 的头号目标。"""
        with pytest.raises(RuntimeError):
            await assert_public_http_url("http://169.254.169.254/latest/meta-data/")

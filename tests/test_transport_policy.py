"""Tests for punt_lux.transport_policy -- luxd WebSocket loopback trust policy."""

from __future__ import annotations

from punt_lux.transport_policy import LoopbackTransportPolicy


class TestRejectsOrigin:
    def test_absent_origin_is_allowed(self):
        """mcp-proxy and other non-browser clients send no Origin."""
        assert LoopbackTransportPolicy().rejects_origin(None) is False

    def test_loopback_origins_are_allowed(self):
        policy = LoopbackTransportPolicy()
        assert policy.rejects_origin("http://localhost:5173") is False
        assert policy.rejects_origin("http://127.0.0.1:8430") is False
        assert policy.rejects_origin("https://localhost") is False

    def test_foreign_origin_is_rejected(self):
        assert LoopbackTransportPolicy().rejects_origin("http://evil.com") is True

    def test_custom_hostnames_replace_the_default_allowlist(self):
        policy = LoopbackTransportPolicy(hostnames=("example.test",))
        assert policy.rejects_origin("http://example.test") is False
        assert policy.rejects_origin("http://localhost") is True


class TestSecuritySettings:
    def test_dns_rebinding_protection_enabled(self):
        settings = LoopbackTransportPolicy().security_settings()
        assert settings.enable_dns_rebinding_protection

    def test_allowed_hosts_are_loopback_with_wildcard_port(self):
        hosts = LoopbackTransportPolicy().security_settings().allowed_hosts
        assert hosts == ["127.0.0.1:*", "localhost:*"]

    def test_allowed_origins_mirror_the_allowlist_across_schemes_and_ports(self):
        origins = LoopbackTransportPolicy().security_settings().allowed_origins
        assert "http://localhost" in origins
        assert "http://localhost:*" in origins
        assert "https://127.0.0.1:*" in origins
        # A foreign host is never present.
        assert not any("evil" in origin for origin in origins)

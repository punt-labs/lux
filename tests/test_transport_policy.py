"""Tests for punt_lux.transport_policy -- luxd loopback trust policy."""

from __future__ import annotations

from punt_lux.transport_policy import LoopbackTransportPolicy


class TestAllowsBindHost:
    def test_loopback_hosts_are_allowed(self):
        policy = LoopbackTransportPolicy()
        assert policy.allows_bind_host("127.0.0.1") is True
        assert policy.allows_bind_host("localhost") is True

    def test_wildcard_bind_is_refused(self):
        """0.0.0.0 binds every interface -- the off-loopback case luxd refuses."""
        assert LoopbackTransportPolicy().allows_bind_host("0.0.0.0") is False

    def test_foreign_host_is_refused(self):
        assert LoopbackTransportPolicy().allows_bind_host("192.168.1.10") is False

    def test_custom_hostnames_replace_the_default_allowlist(self):
        policy = LoopbackTransportPolicy(hostnames=("example.test",))
        assert policy.allows_bind_host("example.test") is True
        assert policy.allows_bind_host("127.0.0.1") is False


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

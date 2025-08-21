"""TTL management utilities for cache configuration."""

from typing import Optional


class TTLManager:
    """Manages TTL resolution for cache entries based on domain configuration."""

    def __init__(self, config: dict):
        """Initialize TTL manager with configuration.

        Args:
            config: Full proxy configuration dictionary
        """
        self.config = config
        self.default_ttl = config.get("cache", {}).get("default_ttl_seconds", 86400)
        self.domain_mappings = config.get("domain_mappings", {})

    def get_ttl_for_domain(self, domain_key: str) -> int:
        """Get TTL value for a specific domain.

        Args:
            domain_key: The domain key from domain_mappings

        Returns:
            TTL in seconds - domain-specific if configured, otherwise default
        """
        if domain_key in self.domain_mappings:
            domain_config = self.domain_mappings[domain_key]
            if isinstance(domain_config, dict):
                return domain_config.get("ttl_seconds", self.default_ttl)

        return self.default_ttl

    def get_default_ttl(self) -> int:
        """Get the system default TTL value.

        Returns:
            Default TTL in seconds
        """
        return self.default_ttl

"""Command-line interface for Reference API Buddy."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from reference_api_buddy.core.proxy import CachingProxy
from reference_api_buddy.utils.logger import configure_logging


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load configuration from JSON file."""
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Configuration file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in configuration file: {e}")
        sys.exit(1)


def create_default_config() -> Dict[str, Any]:
    """Create a default configuration."""
    return {
        "server": {"host": "127.0.0.1", "port": 8080},
        "security": {"require_secure_key": True},
        "cache": {"database_path": "api_buddy_cache.db", "default_ttl_days": 7},
        "throttling": {"default_requests_per_hour": 1000},
        "domain_mappings": {"example": {"upstream": "https://api.example.com"}},
    }


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Reference API Buddy - HTTP Caching Proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  api-buddy --config config.json                    # Start with config file
  api-buddy --port 9090 --host 0.0.0.0             # Custom host/port
  api-buddy --generate-config                       # Generate default config
  api-buddy --security-key-only                     # Just print security key
        """,
    )

    parser.add_argument("--config", "-c", type=Path, help="Path to configuration JSON file")

    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")

    parser.add_argument("--port", "-p", type=int, default=8080, help="Port to bind to (default: 8080)")

    parser.add_argument("--generate-config", action="store_true", help="Generate a default configuration file and exit")

    parser.add_argument(
        "--security-key-only", action="store_true", help="Generate and print security key only, then exit"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )

    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    args = parser.parse_args()

    # Handle special modes
    if args.generate_config:
        config = create_default_config()
        config_file = Path("api_buddy_config.json")
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Generated default configuration: {config_file}")
        return

    if args.security_key_only:
        from reference_api_buddy.security.manager import SecurityManager

        manager = SecurityManager({})
        key = manager.generate_secure_key()
        print(f"Generated security key: {key}")
        return

    # Load configuration
    if args.config:
        config = load_config(args.config)
    else:
        config = create_default_config()
        print("Using default configuration. Use --generate-config to " "create a config file.")

    # Override with CLI arguments
    if args.host != "127.0.0.1":
        config.setdefault("server", {})["host"] = args.host
    if args.port != 8080:
        config.setdefault("server", {})["port"] = args.port

    # Configure logging
    config.setdefault("logging", {})["level"] = args.log_level
    configure_logging(config["logging"])

    # Start proxy
    try:
        proxy = CachingProxy(config)

        # Print startup information
        host = config.get("server", {}).get("host", "127.0.0.1")
        port = config.get("server", {}).get("port", 8080)

        print(f"Starting Reference API Buddy on {host}:{port}")

        if config.get("security", {}).get("require_secure_key", False):
            key = proxy.get_secure_key()  # type: ignore
            if key:
                print(f"Security key: {key}")
                print("Include this key in your requests:")
                print(f"  Path prefix: /{key}/domain/path")
                print(f"  Query param: ?key={key}")
                print(f"  Header: X-API-Buddy-Key: {key}")

        print("\nPress Ctrl+C to stop")
        proxy.start(blocking=True)

    except KeyboardInterrupt:
        print("\nShutting down...")
        if "proxy" in locals():
            proxy.stop()
    except Exception as e:
        print(f"Error starting proxy: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

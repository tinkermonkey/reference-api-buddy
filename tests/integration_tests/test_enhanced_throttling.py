#!/usr/bin/env python3
"""Test script to demonstrate enhanced throttling statistics."""

import time

from reference_api_buddy.cache.engine import CacheEngine
from reference_api_buddy.database.manager import DatabaseManager
from reference_api_buddy.monitoring.manager import MonitoringManager
from reference_api_buddy.throttling.manager import ThrottleManager


def test_enhanced_throttling_stats():
    """Test enhanced throttling statistics with realistic scenarios."""
    print("🚀 Testing Enhanced Throttling Statistics\n")

    # Create components with interesting throttling config
    throttle_config = {
        "default_requests_per_hour": 1000,
        "progressive_max_delay": 300,
        "domain_limits": {"api.openai.com": 50, "api.anthropic.com": 100, "high-volume.api.com": 5000},
    }

    db = DatabaseManager(":memory:")
    cache = CacheEngine(db)
    throttle = ThrottleManager(throttle_config)
    monitor = MonitoringManager(cache, db, db, throttle)

    # Simulate realistic request patterns
    print("📊 Simulating request patterns...")

    # Normal usage for OpenAI API
    for i in range(15):
        throttle.record_request("api.openai.com")

    # Heavy usage for Anthropic API
    for i in range(35):
        throttle.record_request("api.anthropic.com")

    # Light usage for high-volume API
    for i in range(100):
        throttle.record_request("high-volume.api.com")

    # Some usage for unknown domain (uses default limit)
    for i in range(25):
        throttle.record_request("unknown.api.com")

    # Simulate a throttled domain by forcing violations
    print("⚠️  Simulating throttling scenario...")

    # Force OpenAI API to exceed its limit and trigger throttling
    for i in range(40):  # This will exceed the 50/hour limit
        throttle.record_request("api.openai.com")

    # Check if it should be throttled now
    if throttle.should_throttle("api.openai.com"):
        print("✅ OpenAI API is now being throttled as expected")

    # Get enhanced throttling stats
    stats = monitor.get_throttling_stats()

    print("\n" + "=" * 60)
    print("📈 ENHANCED THROTTLING STATISTICS")
    print("=" * 60)

    # Configuration info
    print(f"🔧 Configuration:")
    print(f"   Default Requests/Hour: {stats['default_requests_per_hour']}")
    print(f"   Progressive Max Delay: {stats['progressive_max_delay']}s")
    print(f"   Progressive Enabled: {stats['progressive_enabled']}")

    # Domain limits
    print(f"\n🎯 Domain Limits:")
    for domain, limit in stats["domain_limits"].items():
        print(f"   {domain}: {limit} requests/hour")

    # Request patterns
    print(f"\n📊 Current Request Activity:")
    for domain, domain_stats in stats["requests_per_domain"].items():
        print(f"   📍 {domain}:")
        print(f"      Current Hour: {domain_stats['current_hour_requests']} requests")
        print(f"      Total Ever: {domain_stats['total_requests']} requests")
        print(f"      Violations: {domain_stats['violations']}")
        print(f"      Delay: {domain_stats['current_delay_seconds']}s")

    # Throttling status
    print(f"\n🚨 Throttling Status:")
    for domain, state in stats["throttle_state"].items():
        status = "🔴 THROTTLED" if state["is_throttled"] else "🟢 Normal"
        print(f"   📍 {domain}: {status}")
        if state["is_throttled"]:
            print(f"      Violations: {state['violations']}")
            print(f"      Delay: {state['delay_seconds']}s")
            print(
                f"      Last Violation: {time.ctime(state['last_violation']) if state['last_violation'] else 'Never'}"
            )

    print("\n" + "=" * 60)
    print("✅ Enhanced throttling statistics test completed!")
    print("=" * 60)


if __name__ == "__main__":
    test_enhanced_throttling_stats()

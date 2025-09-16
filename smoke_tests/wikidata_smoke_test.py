#!/usr/bin/env python3
"""
Smoke test script for debugging Wikidata SPARQL query endpoint issues.

This test script validates:
- Basic SPARQL query functionality
- GET and POST request methods
- Query parameter handling
- Response parsing and caching
- Concurrent request handling
- Various SPARQL query types (SELECT, ASK, DESCRIBE)
"""

import concurrent.futures
import json
import os
import sys
import time
import urllib.parse

# Add the parent directory to sys.path to use local source code
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from reference_api_buddy.core.proxy import CachingProxy

# Configure logging to DEBUG and save to logs/wikidata_smoke_test.log
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "wikidata_smoke_test.log")
os.makedirs(LOG_DIR, exist_ok=True)

# Test configuration based on provided config
config = {
    "logging": {
        "level": "DEBUG",
        "enable_console": True,
        "enable_file": True,
        "file_path": LOG_FILE,
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "date_format": "%Y-%m-%d %H:%M:%S",
        "max_file_size": 10485760
    },
    "server": {
        "host": "127.0.0.1",
        "port": 18081
    },
    "cache": {
        "database_path": "./test_data/wikidata_smoke_cache.db",
        "max_cache_response_size": 10485760,
        "max_cache_entries": 10000
    },
    "domain_mappings": {
        "wikidata": {
            "upstream": "https://query.wikidata.org"
        }
    },
    "throttling": {
        "default_requests_per_hour": 1000,
        "progressive_max_delay": 300,
        "domain_limits": {
            "wikidata": 1000
        }
    },
    "security": {
        "require_secure_key": False,
        "log_security_events": False
    },
    "callbacks": {}
}

logger = CachingProxy.get_logger("wikidata_smoke_test")

# Test SPARQL queries
TEST_QUERIES = {
    "simple_select": """
        SELECT ?item ?itemLabel WHERE {
            ?item wdt:P31 wd:Q146.
            SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
        }
        LIMIT 5
    """,

    "ask_query": """
        ASK {
            wd:Q42 wdt:P31 wd:Q5.
        }
    """,

    "describe_query": """
        DESCRIBE wd:Q42
    """,

    "complex_select": """
        SELECT ?person ?personLabel ?birthDate ?birthPlace ?birthPlaceLabel WHERE {
            ?person wdt:P31 wd:Q5;
                   wdt:P569 ?birthDate;
                   wdt:P19 ?birthPlace.
            FILTER(YEAR(?birthDate) = 1952)
            SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
        }
        LIMIT 10
    """,

    "count_query": """
        SELECT (COUNT(?item) AS ?count) WHERE {
            ?item wdt:P31 wd:Q5;
                  wdt:P27 wd:Q30.
        }
    """
}


def make_sparql_request(query, method="GET", timeout=60, request_id="unknown"):
    """Make a SPARQL request via the proxy."""
    base_url = "http://127.0.0.1:18081/wikidata/sparql"

    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": "reference-api-buddy-smoke-test/1.0"
    }

    try:
        start_time = time.time()

        if method.upper() == "GET":
            # Encode query as URL parameter
            params = {"query": query}
            response = requests.get(base_url, params=params, headers=headers, timeout=30)
        else:  # POST
            # Send query in request body
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = {"query": query}
            response = requests.post(base_url, data=data, headers=headers, timeout=30)

        duration = time.time() - start_time

        # Try to parse JSON response
        try:
            json_data = response.json()
            json_valid = True
            result_count = 0

            # Count results based on query type
            if "results" in json_data and "bindings" in json_data["results"]:
                result_count = len(json_data["results"]["bindings"])
            elif "boolean" in json_data:
                result_count = 1 if json_data["boolean"] else 0

        except (ValueError, TypeError) as e:
            json_valid = False
            json_data = None
            result_count = 0
            logger.warning(f"Request {request_id}: JSON parse error - {e}")

        logger.info(
            f"Request {request_id}: {method} Status {response.status_code}, "
            f"Duration: {duration:.3f}s, Size: {len(response.text)} bytes, "
            f"JSON Valid: {json_valid}, Results: {result_count}"
        )

        return {
            "status_code": response.status_code,
            "duration": duration,
            "size": len(response.text),
            "json_valid": json_valid,
            "result_count": result_count,
            "error": None,
            "response_data": json_data
        }

    except Exception as e:
        duration = time.time() - start_time if 'start_time' in locals() else 0
        logger.error(f"Request {request_id}: ERROR - {e}")
        return {
            "status_code": None,
            "duration": duration,
            "size": 0,
            "json_valid": False,
            "result_count": 0,
            "error": str(e),
            "response_data": None
        }


def test_basic_queries():
    """Test basic SPARQL queries with both GET and POST methods."""
    logger.info("\n=== Testing Basic SPARQL Queries ===")

    results = []

    for query_name, query in TEST_QUERIES.items():
        logger.info(f"\nTesting {query_name}...")

        # Test with GET method
        result_get = make_sparql_request(query, "GET", request_id=f"{query_name}_GET")
        results.append(("GET", query_name, result_get))

        # Test with POST method
        result_post = make_sparql_request(query, "POST", request_id=f"{query_name}_POST")
        results.append(("POST", query_name, result_post))

        # Brief pause between queries
        time.sleep(0.5)

    return results


def test_cache_behavior():
    """Test caching behavior with repeated queries."""
    logger.info("\n=== Testing Cache Behavior ===")

    query = TEST_QUERIES["simple_select"]

    # First request (cache miss)
    logger.info("Making first request (cache miss expected)...")
    result1 = make_sparql_request(query, "GET", request_id="CACHE_MISS")

    # Second request (cache hit)
    logger.info("Making second request (cache hit expected)...")
    result2 = make_sparql_request(query, "GET", request_id="CACHE_HIT_1")

    # Third request (cache hit)
    logger.info("Making third request (cache hit expected)...")
    result3 = make_sparql_request(query, "GET", request_id="CACHE_HIT_2")

    logger.info("\nCache test timing summary:")
    logger.info(f"  First request:  {result1['duration']:.3f}s (cache miss)" if result1['duration'] else "  First request: Failed")
    logger.info(f"  Second request: {result2['duration']:.3f}s (cache hit)" if result2['duration'] else "  Second request: Failed")
    logger.info(f"  Third request:  {result3['duration']:.3f}s (cache hit)" if result3['duration'] else "  Third request: Failed")

    return [result1, result2, result3]


def test_concurrent_requests():
    """Test concurrent SPARQL requests to identify threading issues."""
    logger.info("\n=== Testing Concurrent Requests ===")

    # Use a mix of different queries for concurrent testing
    concurrent_queries = [
        ("simple_1", TEST_QUERIES["simple_select"]),
        ("ask_1", TEST_QUERIES["ask_query"]),
        ("simple_2", TEST_QUERIES["simple_select"]),  # Duplicate for cache testing
        ("count_1", TEST_QUERIES["count_query"]),
        ("ask_2", TEST_QUERIES["ask_query"]),  # Duplicate for cache testing
    ]

    logger.info(f"Running {len(concurrent_queries)} concurrent requests...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for i, (name, query) in enumerate(concurrent_queries):
            future = executor.submit(make_sparql_request, query, "GET", f"CONC_{name}")
            futures.append((name, future))

        results = []
        errors = 0
        json_errors = 0

        for name, future in futures:
            result = future.result()
            results.append((name, result))

            if result["error"]:
                errors += 1
            if not result["json_valid"]:
                json_errors += 1

    logger.info(f"Concurrent test completed: {len(results)} requests, {errors} errors, {json_errors} JSON errors")
    return results


def test_malformed_queries():
    """Test handling of malformed SPARQL queries."""
    logger.info("\n=== Testing Malformed Queries ===")

    malformed_queries = [
        ("syntax_error", "SELECT ?item WHERE { ?item wdt:P31 wd:Q146 MISSING_DOT }"),
        ("empty_query", ""),
        ("invalid_sparql", "This is not SPARQL at all"),
        ("incomplete_query", "SELECT ?item WHERE {"),
    ]

    results = []
    for name, query in malformed_queries:
        logger.info(f"Testing {name}...")
        result = make_sparql_request(query, "GET", request_id=f"MALFORMED_{name}")
        results.append((name, result))

    return results


def test_large_result_queries():
    """Test queries that might return large result sets."""
    logger.info("\n=== Testing Large Result Queries ===")

    large_queries = {
        "medium_result": """
            SELECT ?item ?itemLabel WHERE {
                ?item wdt:P31 wd:Q5;
                      wdt:P27 wd:Q30.
                SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
            }
            LIMIT 100
        """,

        "large_result": """
            SELECT ?item ?itemLabel WHERE {
                ?item wdt:P31 wd:Q5.
                SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
            }
            LIMIT 1000
        """
    }

    results = []
    for name, query in large_queries.items():
        logger.info(f"Testing {name}...")
        result = make_sparql_request(query, "GET", request_id=f"LARGE_{name}")
        results.append((name, result))

        # Longer pause for large queries
        time.sleep(2)

    return results


def print_test_summary(all_results):
    """Print a comprehensive test summary."""
    logger.info("\n" + "="*60)
    logger.info("WIKIDATA SMOKE TEST SUMMARY")
    logger.info("="*60)

    total_requests = 0
    successful_requests = 0
    json_errors = 0
    network_errors = 0
    total_duration = 0

    for test_name, test_results in all_results.items():
        logger.info(f"\n{test_name}:")

        for result in test_results:
            total_requests += 1

            if isinstance(result, tuple):
                # Handle tuple results (method, name, result) or (name, result)
                if len(result) == 3:
                    method, name, res = result
                    identifier = f"{method}_{name}"
                else:
                    name, res = result
                    identifier = name
            else:
                # Handle direct result objects
                res = result
                identifier = "direct"

            if res["error"]:
                network_errors += 1
                logger.info(f"  {identifier}: ERROR - {res['error']}")
            else:
                if res["status_code"] == 200:
                    successful_requests += 1
                if not res["json_valid"]:
                    json_errors += 1
                if res["duration"] is not None:
                    total_duration += res["duration"]

                duration_str = f"{res['duration']:.3f}s" if res["duration"] is not None else "Failed"
                logger.info(
                    f"  {identifier}: Status {res['status_code']}, "
                    f"Duration {duration_str}, "
                    f"Results {res['result_count']}, "
                    f"JSON Valid: {res['json_valid']}"
                )

    logger.info(f"\nOVERALL STATISTICS:")
    logger.info(f"  Total Requests: {total_requests}")
    logger.info(f"  Successful (200): {successful_requests}")
    logger.info(f"  Network Errors: {network_errors}")
    logger.info(f"  JSON Parse Errors: {json_errors}")
    successful_duration_count = total_requests - network_errors
    logger.info(f"  Average Duration: {total_duration/max(successful_duration_count, 1):.3f}s" if successful_duration_count > 0 else "  Average Duration: N/A")

    # Determine overall test result
    if network_errors > 0 or json_errors > 0:
        logger.error("❌ SMOKE TEST FAILED - Issues detected!")

        # Add detailed issue summary
        logger.error("\nISSUES DETECTED:")
        if json_errors > 0:
            logger.error(f"  - {json_errors} JSON parsing errors (likely Content-Length header issues with gzip compression)")
        if network_errors > 0:
            logger.error(f"  - {network_errors} network/connection errors (timeouts, connection failures)")

        logger.error("\nRECOMMENDATIONS:")
        if json_errors > 0:
            logger.error("  - Check proxy's gzip decompression handling and Content-Length header management")
        if network_errors > 0:
            logger.error("  - Increase timeout values for complex SPARQL queries")
            logger.error("  - Verify network connectivity to query.wikidata.org")

        return False
    else:
        logger.info("✅ SMOKE TEST PASSED - All requests successful!")
        return True


def main():
    """Main test execution function."""
    logger.info("Starting Wikidata SPARQL Smoke Test...")

    # Ensure test data directory exists
    os.makedirs("test_data", exist_ok=True)

    # Start the proxy
    proxy = CachingProxy(config)
    proxy.start(blocking=False)

    # Give the server time to start
    logger.info("Waiting for proxy to start...")
    time.sleep(2)

    try:
        # Clear cache for fresh testing
        try:
            proxy.cache_engine.clear()
            logger.info("Cache cleared for fresh testing")
        except Exception as e:
            logger.warning(f"Could not clear cache: {e}")

        # Run all test suites
        all_results = {}

        all_results["Basic Queries"] = test_basic_queries()
        all_results["Cache Behavior"] = test_cache_behavior()
        all_results["Concurrent Requests"] = test_concurrent_requests()
        all_results["Malformed Queries"] = test_malformed_queries()
        all_results["Large Result Queries"] = test_large_result_queries()

        # Print monitoring stats if available
        try:
            monitor = proxy.get_monitoring_manager()
            logger.info("\n--- Monitoring Stats ---")
            logger.info(f"Cache Stats: {monitor.get_cache_stats()}")
            logger.info(f"Upstream Stats: {monitor.get_upstream_stats()}")
            logger.info(f"Database Stats: {monitor.get_database_stats()}")
            logger.info(f"Proxy Health: {monitor.get_proxy_health()}")
            logger.info(f"Throttling Stats: {monitor.get_throttling_stats()}")
        except Exception as e:
            logger.warning(f"Could not retrieve monitoring stats: {e}")

        # Print comprehensive summary
        test_passed = print_test_summary(all_results)

        return test_passed

    finally:
        # Stop the proxy
        proxy.stop()
        logger.info(f"\nWikidata smoke test complete. Logs saved to {LOG_FILE}")


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

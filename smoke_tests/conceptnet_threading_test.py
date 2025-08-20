#!/usr/bin/env python3
"""Test script to reproduce the threading issue with concurrent requests."""

import concurrent.futures
import os
import sys
import threading
import time

# Add the parent directory to sys.path to use local source code
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from reference_api_buddy.core.proxy import CachingProxy

# Configure logging to DEBUG and save to logs/threading_test.log
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "threading_test.log")
os.makedirs(LOG_DIR, exist_ok=True)

config = {
    "logging": {
        "level": "DEBUG",
        "enable_console": True,
        "enable_file": True,
        "file_path": LOG_FILE,
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "date_format": "%Y-%m-%d %H:%M:%S",
    },
    "server": {
        "host": "127.0.0.1",
        "port": 18080,
    },
    "domain_mappings": {"concepcy": {"upstream": "https://api.conceptnet.io"}},
    "cache": {"database_path": "smoke_tests/cache.db", "max_cache_response_size": 10485760},
    "security": {},
    "throttling": {},
    "callbacks": {},
}

logger = CachingProxy.get_logger("threading_test")


def make_request(url, request_id):
    """Make a single request and return the result."""
    try:
        logger.debug(f"Request {request_id}: Starting...")
        response = requests.get(url, timeout=10)

        # Try to parse the response as JSON to replicate the original issue
        try:
            response_json = response.json()
            json_valid = True
            json_keys = list(response_json.keys()) if isinstance(response_json, dict) else "not_dict"
        except (ValueError, TypeError) as json_error:
            json_valid = False
            json_keys = f"JSON_PARSE_ERROR: {json_error}"
            logger.warning(f"Request {request_id}: JSON parse error - {json_error}")

        logger.debug(
            f"Request {request_id}: Status {response.status_code}, Length: {len(response.text)}, JSON Valid: {json_valid}, Keys: {json_keys}"
        )
        return response.status_code, len(response.text), json_valid, json_keys, None
    except Exception as e:
        logger.error(f"Request {request_id}: ERROR - {e}")
        return None, None, False, None, str(e)


def test_concurrent_requests():
    """Test concurrent requests to reproduce the threading issue."""
    # Start the proxy in a background thread
    proxy = CachingProxy(config)
    proxy.start(blocking=False)

    # Give the server a moment to start
    logger.info("Waiting for proxy to start...")
    time.sleep(2)

    try:
        # Create URLs similar to the ones that were causing issues
        base_url = "http://127.0.0.1:18080"
        urls = [
            f"{base_url}/concepcy/query?node=/c/en/email&other=/c/en",
            f"{base_url}/concepcy/query?node=/c/en/communicate&other=/c/en",
            f"{base_url}/concepcy/query?node=/c/en/great&other=/c/en",
            f"{base_url}/concepcy/query?node=/c/en/work&other=/c/en",
            f"{base_url}/concepcy/query?node=/c/en/computer&other=/c/en",
        ]

        logger.info(f"Testing with {len(urls)} concurrent requests...")

        # Test 1: Sequential requests (baseline)
        logger.info("\n=== Sequential Requests ===")
        for i, url in enumerate(urls):
            make_request(url, f"SEQ-{i+1}")

        # Test 2: Concurrent requests (where the issue likely occurs)
        logger.info("\n=== Concurrent Requests ===")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i, url in enumerate(urls):
                future = executor.submit(make_request, url, f"CONC-{i+1}")
                futures.append(future)

            # Wait for all requests to complete
            results = []
            json_errors = 0
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                if len(result) >= 3 and not result[2]:  # Check if JSON parsing failed
                    json_errors += 1

        logger.info(f"\nCompleted {len(results)} concurrent requests, {json_errors} JSON parsing errors")

        # Test 3: Rapid-fire requests to the same endpoint
        logger.info("\n=== Rapid-fire Requests to Same Endpoint ===")
        same_url = urls[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(20):  # Increase to 20 for more stress
                future = executor.submit(make_request, same_url, f"RAPID-{i+1}")
                futures.append(future)

            results = []
            json_errors = 0
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                if len(result) >= 3 and not result[2]:  # Check if JSON parsing failed
                    json_errors += 1

        logger.info(f"Completed {len(results)} rapid-fire requests, {json_errors} JSON parsing errors")

    finally:
        # Stop the proxy
        proxy.stop()
        logger.info(f"\nTesting complete. Logs saved to {LOG_FILE}")


if __name__ == "__main__":
    test_concurrent_requests()

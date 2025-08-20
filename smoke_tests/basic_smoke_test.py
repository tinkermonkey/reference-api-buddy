import os
import sys
import time

# Add the parent directory to sys.path to use local source code
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from reference_api_buddy.core.proxy import CachingProxy

# Configure logging to DEBUG and save to logs/smoke_test.log
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "smoke_test.log")
os.makedirs(LOG_DIR, exist_ok=True)

config = {
    "logging": {
        "level": "DEBUG",
        # "enable_console": True,
        # "enable_file": True,
        # "file_path": LOG_FILE,
        # "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        # "date_format": "%Y-%m-%d %H:%M:%S",
    },
    "server": {
        "host": "127.0.0.1",
        "port": 18080,
    },
    "domain_mappings": {
        # Intercept requests to /jsonplaceholder and map to jsonplaceholder.typicode.com
        "jsonplaceholder": {"upstream": "https://jsonplaceholder.typicode.com"}
    },
    "cache": {"database_path": "smoke_tests/cache.db", "max_cache_response_size": 10485760},
    "security": {},
    "throttling": {},
    "callbacks": {},
}

# Start the proxy in a background thread
proxy = CachingProxy(config)
proxy.start(blocking=False)

# Give the server a moment to start
print("Waiting for proxy to start...")
time.sleep(1)

# Target endpoint: /jsonplaceholder/todos/1 (maps to https://jsonplaceholder.typicode.com/todos/1)
proxy_url = "http://127.0.0.1:18080/jsonplaceholder/todos/1"

print("Making first request (should be a cache miss)...")
start1 = time.time()
resp1 = requests.get(proxy_url)
duration1 = time.time() - start1
print(f"First request status: {resp1.status_code}, duration: {duration1:.3f}s, body: {resp1.text[:60]}...")

print("Making second request (should be a cache hit)...")
start2 = time.time()
resp2 = requests.get(proxy_url)
duration2 = time.time() - start2
print(f"Second request status: {resp2.status_code}, duration: {duration2:.3f}s, body: {resp2.text[:60]}...")

# Make a third request to further verify cache
print("Making third request (should be a cache hit)...")
start3 = time.time()
resp3 = requests.get(proxy_url)
duration3 = time.time() - start3
print(f"Third request status: {resp3.status_code}, duration: {duration3:.3f}s, body: {resp3.text[:60]}...")

# Print timing summary
print("\nTiming summary:")
print(f"  First request:  {duration1:.3f}s (expected: slow, cache miss)")
print(f"  Second request: {duration2:.3f}s (expected: fast, cache hit)")
print(f"  Third request:  {duration3:.3f}s (expected: fast, cache hit)")

# Stop the proxy
proxy.stop()
print(f"Smoke test complete. Logs saved to {LOG_FILE}")

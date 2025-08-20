"""Performance tests for Reference API Buddy proxy."""

import concurrent.futures
import os
import platform
import statistics
import time
from typing import Dict, List, Tuple

import pytest
import requests

from reference_api_buddy.core.proxy import CachingProxy


@pytest.mark.skipif(
    platform.system() == 'Windows' and os.environ.get('CI') == 'true',
    reason="Skipping performance tests on Windows CI due to file locking issues"
)
class PerformanceTestSuite:
    """Performance test suite for the caching proxy."""

    @pytest.fixture(autouse=True)
    def setup_proxy(self, tmp_path):
        """Set up a test proxy instance."""
        # Create a unique cache database for each test
        self.cache_db_path = tmp_path / "perf_test_cache.db"

        self.config = {
            "logging": {
                "level": "INFO",  # Reduce logging verbosity for performance tests
                "enable_console": False,
                "enable_file": False,
            },
            "server": {
                "host": "127.0.0.1",
                "port": 18081,  # Different port to avoid conflicts
            },
            "domain_mappings": {
                "jsonplaceholder": {"upstream": "https://jsonplaceholder.typicode.com"},
                "httpbin": {"upstream": "https://httpbin.org"},
            },
            "cache": {"database_path": str(self.cache_db_path), "max_cache_response_size": 10485760},
            "security": {},
            "throttling": {},
            "callbacks": {},
        }

        self.proxy = CachingProxy(self.config)
        self.proxy.start(blocking=False)

        # Wait for server to start
        time.sleep(0.5)

        yield

        # Cleanup - ensure proper shutdown sequence for Windows compatibility
        try:
            self.proxy.stop()
            # Give Windows time to release file locks
            import platform
            if platform.system() == 'Windows':
                time.sleep(0.2)
            
            # Attempt to clean up database file
            if self.cache_db_path.exists():
                try:
                    self.cache_db_path.unlink()
                except (PermissionError, OSError) as e:
                    # On Windows, file might still be locked - log but don't fail the test
                    print(f"Warning: Could not delete cache file {self.cache_db_path}: {e}")
        except Exception as e:
            print(f"Warning: Error during cleanup: {e}")

    def make_request(self, url: str, timeout: int = 10) -> Tuple[bool, float, int, str]:
        """
        Make a request and return success, duration, status_code, and error.

        Returns:
            Tuple of (success, duration_seconds, status_code, error_message)
        """
        start_time = time.time()
        try:
            response = requests.get(url, timeout=timeout)
            duration = time.time() - start_time
            return True, duration, response.status_code, ""
        except Exception as e:
            duration = time.time() - start_time
            return False, duration, 0, str(e)

    def analyze_response_times(self, durations: List[float]) -> Dict[str, float]:
        """Analyze response time statistics."""
        if not durations:
            return {}

        return {
            "min": min(durations),
            "max": max(durations),
            "mean": statistics.mean(durations),
            "median": statistics.median(durations),
            "p95": statistics.quantiles(durations, n=20)[18] if len(durations) >= 20 else max(durations),
            "p99": statistics.quantiles(durations, n=100)[98] if len(durations) >= 100 else max(durations),
        }


class TestBasicPerformance(PerformanceTestSuite):
    """Basic performance tests."""

    def test_sequential_requests_performance(self):
        """Test sequential request performance with cache hits and misses."""
        base_url = "http://127.0.0.1:18081"

        # Test different endpoints
        urls = [
            f"{base_url}/jsonplaceholder/posts/1",
            f"{base_url}/jsonplaceholder/posts/2",
            f"{base_url}/jsonplaceholder/posts/3",
            f"{base_url}/jsonplaceholder/users/1",
            f"{base_url}/jsonplaceholder/users/2",
        ]

        # First pass - cache misses
        cache_miss_times = []
        for url in urls:
            success, duration, status_code, error = self.make_request(url)
            assert success, f"Request failed: {error}"
            assert status_code == 200, f"Unexpected status code: {status_code}"
            cache_miss_times.append(duration)

        # Second pass - cache hits
        cache_hit_times = []
        for url in urls:
            success, duration, status_code, error = self.make_request(url)
            assert success, f"Request failed: {error}"
            assert status_code == 200, f"Unexpected status code: {status_code}"
            cache_hit_times.append(duration)

        # Analyze performance
        miss_stats = self.analyze_response_times(cache_miss_times)
        hit_stats = self.analyze_response_times(cache_hit_times)

        # Cache hits should be significantly faster
        assert hit_stats["mean"] < miss_stats["mean"], "Cache hits should be faster than cache misses"
        assert hit_stats["max"] < miss_stats["min"], "Even slowest cache hit should be faster than fastest cache miss"

        # Performance assertions
        assert hit_stats["mean"] < 0.025, f"Cache hit average response time too slow: {hit_stats['mean']:.3f}s"
        assert miss_stats["mean"] < 5.0, f"Cache miss average response time too slow: {miss_stats['mean']:.3f}s"

    def test_repeated_requests_performance(self):
        """Test performance of repeated requests to the same endpoint."""
        url = "http://127.0.0.1:18081/jsonplaceholder/posts/1"
        num_requests = 50

        durations = []
        for i in range(num_requests):
            success, duration, status_code, error = self.make_request(url)
            assert success, f"Request {i+1} failed: {error}"
            assert status_code == 200, f"Request {i+1} unexpected status: {status_code}"
            durations.append(duration)

        stats = self.analyze_response_times(durations)

        # Performance assertions
        assert stats["mean"] < 0.025, f"Average response time too slow: {stats['mean']:.3f}s"
        assert stats["p95"] < 0.05, f"95th percentile too slow: {stats['p95']:.3f}s"
        assert stats["max"] < 1.0, f"Maximum response time too slow: {stats['max']:.3f}s"


class TestConcurrentPerformance(PerformanceTestSuite):
    """Concurrent performance tests."""

    def test_concurrent_requests_same_endpoint(self):
        """Test concurrent requests to the same endpoint."""
        url = "http://127.0.0.1:18081/jsonplaceholder/posts/1"
        num_workers = 10
        num_requests = 50

        def make_concurrent_request(request_id: int) -> Tuple[int, bool, float, int, str]:
            success, duration, status_code, error = self.make_request(url)
            return request_id, success, duration, status_code, error

        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(make_concurrent_request, i) for i in range(num_requests)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        total_time = time.time() - start_time

        # Analyze results
        successful_requests = [r for r in results if r[1]]  # r[1] is success flag
        failed_requests = [r for r in results if not r[1]]

        assert (
            len(successful_requests) == num_requests
        ), f"Expected {num_requests} successful requests, got {len(successful_requests)}"
        assert len(failed_requests) == 0, f"Had {len(failed_requests)} failed requests"

        durations = [r[2] for r in successful_requests]  # r[2] is duration
        stats = self.analyze_response_times(durations)

        # Performance assertions
        throughput = num_requests / total_time
        assert throughput > 20, f"Throughput too low: {throughput:.1f} req/s"
        assert stats["mean"] < 0.5, f"Average response time too slow: {stats['mean']:.3f}s"
        assert stats["p95"] < 1.0, f"95th percentile too slow: {stats['p95']:.3f}s"

    def test_concurrent_requests_different_endpoints(self):
        """Test concurrent requests to different endpoints."""
        base_url = "http://127.0.0.1:18081"
        urls = [f"{base_url}/jsonplaceholder/posts/{i}" for i in range(1, 21)] + [
            f"{base_url}/jsonplaceholder/users/{i}" for i in range(1, 11)
        ]

        num_workers = 15

        def make_concurrent_request(url: str) -> Tuple[str, bool, float, int, str]:
            success, duration, status_code, error = self.make_request(url)
            return url, success, duration, status_code, error

        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(make_concurrent_request, url) for url in urls]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        total_time = time.time() - start_time

        # Analyze results
        successful_requests = [r for r in results if r[1]]
        failed_requests = [r for r in results if not r[1]]

        assert len(successful_requests) == len(
            urls
        ), f"Expected {len(urls)} successful requests, got {len(successful_requests)}"
        assert len(failed_requests) == 0, f"Had {len(failed_requests)} failed requests"

        durations = [r[2] for r in successful_requests]
        stats = self.analyze_response_times(durations)

        # Performance assertions
        throughput = len(urls) / total_time
        assert throughput > 5, f"Throughput too low: {throughput:.1f} req/s"
        assert stats["mean"] < 2.0, f"Average response time too slow: {stats['mean']:.3f}s"


class TestLoadPerformance(PerformanceTestSuite):
    """Load testing for high-stress scenarios."""

    def test_high_volume_sequential_load(self):
        """Test high volume of sequential requests."""
        url = "http://127.0.0.1:18081/jsonplaceholder/posts/1"
        num_requests = 100

        durations = []
        errors = []

        for i in range(num_requests):
            success, duration, status_code, error = self.make_request(url)
            durations.append(duration)

            if not success or status_code != 200:
                errors.append(f"Request {i+1}: success={success}, status={status_code}, error={error}")

        # Allow some tolerance for errors under load
        error_rate = len(errors) / num_requests
        assert error_rate < 0.05, f"Error rate too high: {error_rate:.2%}. Errors: {errors[:5]}"

        successful_durations = durations[: len(durations) - len(errors)]
        if successful_durations:
            stats = self.analyze_response_times(successful_durations)
            assert stats["mean"] < 0.2, f"Average response time too slow: {stats['mean']:.3f}s"

    def test_sustained_concurrent_load(self):
        """Test sustained concurrent load over time."""
        base_url = "http://127.0.0.1:18081"
        urls = [f"{base_url}/jsonplaceholder/posts/{i}" for i in range(1, 11)]

        num_workers = 20
        requests_per_worker = 10
        total_requests = num_workers * requests_per_worker

        def worker_requests(worker_id: int) -> List[Tuple[int, bool, float, int, str]]:
            """Each worker makes multiple requests."""
            results = []
            for request_num in range(requests_per_worker):
                url = urls[request_num % len(urls)]  # Cycle through URLs
                success, duration, status_code, error = self.make_request(url)
                results.append((worker_id, success, duration, status_code, error))
            return results

        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_requests, i) for i in range(num_workers)]
            all_results = []
            for future in concurrent.futures.as_completed(futures):
                all_results.extend(future.result())
        total_time = time.time() - start_time

        # Analyze results
        successful_requests = [r for r in all_results if r[1]]  # r[1] is success flag
        failed_requests = [r for r in all_results if not r[1]]

        success_rate = len(successful_requests) / total_requests
        assert success_rate > 0.90, f"Success rate too low: {success_rate:.2%}"

        if successful_requests:
            durations = [r[2] for r in successful_requests]  # r[2] is duration
            stats = self.analyze_response_times(durations)

            # Performance assertions for sustained load
            throughput = len(successful_requests) / total_time
            assert throughput > 15, f"Sustained throughput too low: {throughput:.1f} req/s"
            assert stats["mean"] < 1.0, f"Average response time under load too slow: {stats['mean']:.3f}s"
            assert stats["p95"] < 2.0, f"95th percentile under load too slow: {stats['p95']:.3f}s"


class TestCachePerformance(PerformanceTestSuite):
    """Cache-specific performance tests."""

    def test_cache_hit_vs_miss_performance(self):
        """Test and compare cache hit vs miss performance."""
        base_url = "http://127.0.0.1:18081"

        # URLs for cache misses (first time requests)
        miss_urls = [f"{base_url}/jsonplaceholder/posts/{i}" for i in range(1, 11)]

        # Measure cache miss performance
        miss_times = []
        for url in miss_urls:
            success, duration, status_code, error = self.make_request(url)
            assert success and status_code == 200
            miss_times.append(duration)

        # Measure cache hit performance (same URLs again)
        hit_times = []
        for url in miss_urls:
            success, duration, status_code, error = self.make_request(url)
            assert success and status_code == 200
            hit_times.append(duration)

        miss_stats = self.analyze_response_times(miss_times)
        hit_stats = self.analyze_response_times(hit_times)

        # Cache performance assertions
        speedup_factor = miss_stats["mean"] / hit_stats["mean"]
        assert speedup_factor > 3, f"Cache speedup insufficient: {speedup_factor:.1f}x"
        assert hit_stats["mean"] < 0.025, f"Cache hits too slow: {hit_stats['mean']:.3f}s"
        assert hit_stats["p95"] < 0.05, f"Cache hit p95 too slow: {hit_stats['p95']:.3f}s"

    def test_mixed_cache_hit_miss_performance(self):
        """Test performance with mixed cache hits and misses."""
        base_url = "http://127.0.0.1:18081"

        # Create a pattern of URLs with some repeats (cache hits) and some new (cache misses)
        urls = []
        for i in range(1, 6):  # First set - will be cache misses
            urls.append(f"{base_url}/jsonplaceholder/posts/{i}")
        for i in range(1, 6):  # Repeat - will be cache hits
            urls.append(f"{base_url}/jsonplaceholder/posts/{i}")
        for i in range(6, 11):  # New set - will be cache misses
            urls.append(f"{base_url}/jsonplaceholder/posts/{i}")

        durations = []
        for url in urls:
            success, duration, status_code, error = self.make_request(url)
            assert success and status_code == 200
            durations.append(duration)

        stats = self.analyze_response_times(durations)

        # Mixed workload should still perform well
        assert stats["mean"] < 0.5, f"Mixed workload average too slow: {stats['mean']:.3f}s"
        assert stats["p95"] < 1.0, f"Mixed workload p95 too slow: {stats['p95']:.3f}s"

# Performance Test Suite Documentation

## Overview

The performance test suite validates that the Reference API Buddy proxy maintains acceptable performance characteristics under various load conditions. The tests are organized into four main categories, each testing different aspects of proxy performance.

## Test Categories

### 1. TestBasicPerformance
Basic performance validation for sequential requests and cache behavior.

**Tests:**
- `test_sequential_requests_performance`: Validates cache hit vs miss performance
- `test_repeated_requests_performance`: Tests repeated requests to the same endpoint

**Key Assertions:**
- Cache hits must be significantly faster than cache misses
- Cache hit average response time < 100ms
- Cache miss average response time < 5 seconds
- 95th percentile response time < 200ms

### 2. TestConcurrentPerformance
Tests concurrent request handling capabilities.

**Tests:**
- `test_concurrent_requests_same_endpoint`: 50 concurrent requests to the same endpoint
- `test_concurrent_requests_different_endpoints`: Concurrent requests to 30 different endpoints

**Key Assertions:**
- Throughput > 20 requests/second for same endpoint
- Throughput > 5 requests/second for different endpoints
- Average response time < 500ms under concurrent load
- 95th percentile < 1 second

### 3. TestLoadPerformance
High-stress load testing scenarios.

**Tests:**
- `test_high_volume_sequential_load`: 100 sequential requests
- `test_sustained_concurrent_load`: 20 workers × 10 requests each (200 total)

**Key Assertions:**
- Error rate < 5% under high load
- Success rate > 90% under sustained load
- Sustained throughput > 15 requests/second
- Average response time < 1 second under load

### 4. TestCachePerformance
Cache-specific performance validation.

**Tests:**
- `test_cache_hit_vs_miss_performance`: Direct comparison of cache performance
- `test_mixed_cache_hit_miss_performance`: Mixed workload performance

**Key Assertions:**
- Cache speedup factor > 3x
- Cache hits < 100ms average
- Mixed workload average < 500ms

## Performance Metrics

The test suite analyzes the following metrics for each test:

- **Response Times:** min, max, mean, median, 95th percentile, 99th percentile
- **Throughput:** requests per second
- **Success Rate:** percentage of successful requests
- **Error Rate:** percentage of failed requests

## Configuration

Tests use a separate configuration to avoid interference:

- **Port:** 18081 (different from smoke tests)
- **Cache Database:** Temporary file per test
- **Logging:** Reduced verbosity for performance
- **Endpoints:** jsonplaceholder.typicode.com and httpbin.org

## Running the Tests

```bash
# Run all performance tests
pytest tests/performance_tests/ -v

# Run specific test category
pytest tests/performance_tests/test_placeholder.py::TestBasicPerformance -v

# Run with timing output
pytest tests/performance_tests/ -v --durations=10
```

## Performance Baselines

The test suite establishes the following performance baselines:

| Metric | Cache Hit | Cache Miss | Concurrent | Load |
|--------|-----------|------------|------------|------|
| Average Response Time | < 100ms | < 5s | < 500ms | < 1s |
| 95th Percentile | < 200ms | N/A | < 1s | < 2s |
| Throughput | N/A | N/A | > 20 req/s | > 15 req/s |
| Error Rate | < 1% | < 1% | < 5% | < 10% |

## Test Architecture

The test suite uses a base class `PerformanceTestSuite` that provides:

1. **Proxy Setup/Teardown**: Automatic proxy lifecycle management
2. **Request Helper**: Standardized request method with timing
3. **Statistics Analysis**: Response time analysis utilities
4. **Cleanup**: Automatic database cleanup after tests

Each test class inherits from this base and focuses on specific performance aspects while maintaining consistent measurement methodology.

## Future Enhancements

Potential additions to the performance test suite:

1. **Memory Usage Tests**: Monitor memory consumption under load
2. **Long-running Tests**: Extended duration tests for stability
3. **Regression Testing**: Compare performance against baseline metrics
4. **Stress Testing**: Push system to failure points
5. **Different Payload Sizes**: Test performance with varying response sizes

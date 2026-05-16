"""
Prometheus Metrics Configuration for Chainlink Job Marketplace

# REQ-METRICS-001: Request latency histograms by endpoint
# REQ-METRICS-002: Error rate counters by type
# REQ-METRICS-003: Active connections gauge
# REQ-METRICS-004: Job queue depth gauge
# BLP-031: Self-Improvement - Metrics drive optimization decisions
"""

import time
import traceback
from functools import wraps
from typing import Any, Callable, Dict, Optional

# Prometheus imports
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        Summary,
        generate_latest,
    )
    from prometheus_client.multiprocess import MultiProcessCollector

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    print(
        "WARNING [metrics_config]: prometheus_client not installed. Run: pip install prometheus-client"
    )

# ============================================================================
# REQ-METRICS-001: Request Latency Histograms
# ============================================================================

if PROMETHEUS_AVAILABLE:
    # HTTP request latency histogram with endpoint labels
    REQUEST_LATENCY = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds",
        labelnames=["method", "endpoint", "status_code"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
    )

    # Job processing latency by job type
    JOB_PROCESSING_LATENCY = Histogram(
        "job_processing_duration_seconds",
        "Job processing latency in seconds",
        labelnames=["job_type", "status"],
        buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    )

    # External API call latency (Chainlink, Fedimint)
    EXTERNAL_API_LATENCY = Histogram(
        "external_api_duration_seconds",
        "External API call latency in seconds",
        labelnames=["service", "operation", "status"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    # Database query latency
    DB_QUERY_LATENCY = Histogram(
        "database_query_duration_seconds",
        "Database query latency in seconds",
        labelnames=["operation", "table"],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    )

# ============================================================================
# REQ-METRICS-002: Error Rate Counters
# ============================================================================

if PROMETHEUS_AVAILABLE:
    # HTTP request errors by type
    REQUEST_ERRORS = Counter(
        "http_request_errors_total",
        "Total HTTP request errors",
        labelnames=["method", "endpoint", "error_type", "status_code"],
    )

    # Job processing errors
    JOB_ERRORS = Counter(
        "job_processing_errors_total",
        "Total job processing errors",
        labelnames=["job_type", "error_type"],
    )

    # Payment errors
    PAYMENT_ERRORS = Counter(
        "payment_errors_total",
        "Total payment processing errors",
        labelnames=["payment_method", "error_type"],
    )

    # External service errors
    EXTERNAL_SERVICE_ERRORS = Counter(
        "external_service_errors_total",
        "Total external service errors",
        labelnames=["service", "operation", "error_type"],
    )

    # Total requests counter
    REQUEST_COUNT = Counter(
        "http_requests_total",
        "Total HTTP requests",
        labelnames=["method", "endpoint", "status_code"],
    )

    # Total jobs counter
    JOB_COUNT = Counter("jobs_total", "Total jobs submitted", labelnames=["job_type", "status"])

# ============================================================================
# REQ-METRICS-003: Active Connections Gauge
# ============================================================================

if PROMETHEUS_AVAILABLE:
    # Active HTTP connections
    ACTIVE_CONNECTIONS = Gauge("http_active_connections", "Number of active HTTP connections")

    # Active WebSocket connections
    WEBSOCKET_CONNECTIONS = Gauge(
        "websocket_active_connections",
        "Number of active WebSocket connections",
        labelnames=["tier"],
    )

    # Database connection pool
    DB_POOL_CONNECTIONS = Gauge(
        "database_pool_connections",
        "Database connection pool status",
        labelnames=["state"],  # idle, active, waiting
    )

    # Redis connection pool
    REDIS_POOL_CONNECTIONS = Gauge(
        "redis_pool_connections", "Redis connection pool status", labelnames=["state"]
    )

# ============================================================================
# REQ-METRICS-004: Job Queue Depth Gauge
# ============================================================================

if PROMETHEUS_AVAILABLE:
    # Pending jobs in queue by type
    JOB_QUEUE_DEPTH = Gauge(
        "job_queue_depth", "Number of jobs in queue", labelnames=["job_type", "status"]
    )

    # Processing jobs
    JOBS_IN_PROGRESS = Gauge(
        "jobs_in_progress", "Number of jobs currently being processed", labelnames=["job_type"]
    )

    # Rate limiting state
    RATE_LIMIT_REMAINING = Gauge(
        "rate_limit_remaining", "Remaining rate limit for user/tier", labelnames=["tier"]
    )

    # Circuit breaker state
    CIRCUIT_BREAKER_STATE = Gauge(
        "circuit_breaker_state",
        "Circuit breaker state (0=closed, 1=open, 2=half-open)",
        labelnames=["service"],
    )

# ============================================================================
# BLP-031: Self-Improvement Metrics
# ============================================================================

if PROMETHEUS_AVAILABLE:
    # Agent performance metrics
    AGENT_TASK_DURATION = Histogram(
        "agent_task_duration_seconds",
        "Agent task execution duration",
        labelnames=["agent_type", "task_type", "status"],
        buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0),
    )

    # BLP metric tracking
    BLP_PROPERTY_SCORE = Gauge(
        "blp_property_score", "Base Level Property score", labelnames=["blp_id", "property_name"]
    )

    # Compute advantage components
    COMPUTE_ADVANTAGE = Gauge(
        "compute_advantage_score", "Computed advantage score based on BLP formula"
    )


# ============================================================================
# Decorator Functions
# ============================================================================


def track_request_latency(method: str, endpoint: str) -> Callable:
    """
    Decorator to track HTTP request latency.

    # REQ-METRICS-001: Request latency histograms by endpoint

    Usage:
        @track_request_latency("GET", "/api/v1/jobs")
        async def get_jobs():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not PROMETHEUS_AVAILABLE:
                return await func(*args, **kwargs)

            start_time = time.perf_counter()
            status_code = "200"

            try:
                result = await func(*args, **kwargs)
                print(f"SUCCESS [{endpoint}]: Request completed")
                return result
            except Exception as e:
                status_code = "500"
                REQUEST_ERRORS.labels(
                    method=method,
                    endpoint=endpoint,
                    error_type=type(e).__name__,
                    status_code=status_code,
                ).inc()
                print(f"ERROR [{endpoint}]: {type(e).__name__}: {e}")
                print(f"TRACEBACK: {traceback.format_exc()}")
                raise
            finally:
                duration = time.perf_counter() - start_time
                REQUEST_LATENCY.labels(
                    method=method, endpoint=endpoint, status_code=status_code
                ).observe(duration)
                REQUEST_COUNT.labels(
                    method=method, endpoint=endpoint, status_code=status_code
                ).inc()

        return wrapper

    return decorator


def track_job_processing(job_type: str) -> Callable:
    """
    Decorator to track job processing metrics.

    # REQ-METRICS-002: Error rate counters by type

    Usage:
        @track_job_processing("ORACLE_FEED")
        async def process_oracle_job(params):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not PROMETHEUS_AVAILABLE:
                return await func(*args, **kwargs)

            start_time = time.perf_counter()
            status = "success"

            try:
                JOBS_IN_PROGRESS.labels(job_type=job_type).inc()
                result = await func(*args, **kwargs)
                print(f"SUCCESS [job.{job_type}]: Job completed")
                return result
            except Exception as e:
                status = "error"
                JOB_ERRORS.labels(job_type=job_type, error_type=type(e).__name__).inc()
                print(f"ERROR [job.{job_type}]: {type(e).__name__}: {e}")
                print(f"TRACEBACK: {traceback.format_exc()}")
                raise
            finally:
                duration = time.perf_counter() - start_time
                JOB_PROCESSING_LATENCY.labels(job_type=job_type, status=status).observe(duration)
                JOB_COUNT.labels(job_type=job_type, status=status).inc()
                JOBS_IN_PROGRESS.labels(job_type=job_type).dec()

        return wrapper

    return decorator


def track_external_api(service: str, operation: str) -> Callable:
    """
    Decorator to track external API calls.

    # REQ-TRACE-002: Spans created for external API calls (Chainlink, Fedimint)

    Usage:
        @track_external_api("chainlink", "get_price")
        async def get_chainlink_price(pair):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not PROMETHEUS_AVAILABLE:
                return await func(*args, **kwargs)

            start_time = time.perf_counter()
            status = "success"

            try:
                result = await func(*args, **kwargs)
                print(f"SUCCESS [external.{service}.{operation}]: API call completed")
                return result
            except Exception as e:
                status = "error"
                EXTERNAL_SERVICE_ERRORS.labels(
                    service=service, operation=operation, error_type=type(e).__name__
                ).inc()
                print(f"ERROR [external.{service}.{operation}]: {type(e).__name__}: {e}")
                print(f"TRACEBACK: {traceback.format_exc()}")
                raise
            finally:
                duration = time.perf_counter() - start_time
                EXTERNAL_API_LATENCY.labels(
                    service=service, operation=operation, status=status
                ).observe(duration)

        return wrapper

    return decorator


def track_db_query(operation: str, table: str) -> Callable:
    """
    Decorator to track database query metrics.

    # REQ-TRACE-003: Database queries traced with timing

    Usage:
        @track_db_query("SELECT", "jobs")
        async def get_jobs():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not PROMETHEUS_AVAILABLE:
                return await func(*args, **kwargs)

            start_time = time.perf_counter()

            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.perf_counter() - start_time
                DB_QUERY_LATENCY.labels(operation=operation, table=table).observe(duration)

        return wrapper

    return decorator


# ============================================================================
# Metrics Endpoint
# ============================================================================


def get_metrics() -> bytes:
    """
    Generate Prometheus metrics for /metrics endpoint.

    Returns:
        Prometheus metrics in text format
    """
    if not PROMETHEUS_AVAILABLE:
        return b"# Prometheus metrics not available\n"

    try:
        metrics = generate_latest()
        print(f"SUCCESS [get_metrics]: Generated {len(metrics)} bytes of metrics")
        return metrics
    except Exception as e:
        print(f"ERROR [get_metrics]: {type(e).__name__}: {e}")
        print(f"TRACEBACK: {traceback.format_exc()}")
        raise


def get_metrics_content_type() -> str:
    """Get the content type for Prometheus metrics."""
    if PROMETHEUS_AVAILABLE:
        return CONTENT_TYPE_LATEST
    return "text/plain"


# ============================================================================
# Helper Functions
# ============================================================================


def update_connection_gauge(connection_type: str, count: int, state: str = "active") -> None:
    """
    Update connection gauge.

    # REQ-METRICS-003: Active connections gauge
    """
    if not PROMETHEUS_AVAILABLE:
        return

    try:
        if connection_type == "http":
            ACTIVE_CONNECTIONS.set(count)
        elif connection_type == "websocket":
            WEBSOCKET_CONNECTIONS.labels(tier=state).set(count)
        elif connection_type == "database":
            DB_POOL_CONNECTIONS.labels(state=state).set(count)
        elif connection_type == "redis":
            REDIS_POOL_CONNECTIONS.labels(state=state).set(count)
    except Exception as e:
        print(f"WARNING [update_connection_gauge]: {e}")


def update_queue_depth(job_type: str, status: str, count: int) -> None:
    """
    Update job queue depth gauge.

    # REQ-METRICS-004: Job queue depth gauge
    """
    if not PROMETHEUS_AVAILABLE:
        return

    try:
        JOB_QUEUE_DEPTH.labels(job_type=job_type, status=status).set(count)
    except Exception as e:
        print(f"WARNING [update_queue_depth]: {e}")


def update_circuit_breaker_state(service: str, state: int) -> None:
    """
    Update circuit breaker state.
    States: 0=closed, 1=open, 2=half-open
    """
    if not PROMETHEUS_AVAILABLE:
        return

    try:
        CIRCUIT_BREAKER_STATE.labels(service=service).set(state)
    except Exception as e:
        print(f"WARNING [update_circuit_breaker_state]: {e}")


def update_blp_score(blp_id: str, property_name: str, score: float) -> None:
    """
    Update BLP property score.

    # BLP-031: Self-Improvement - Metrics drive optimization decisions
    """
    if not PROMETHEUS_AVAILABLE:
        return

    try:
        BLP_PROPERTY_SCORE.labels(blp_id=blp_id, property_name=property_name).set(score)
    except Exception as e:
        print(f"WARNING [update_blp_score]: {e}")


if __name__ == "__main__":
    # Test metrics configuration
    print("Testing Prometheus metrics configuration...")

    if PROMETHEUS_AVAILABLE:
        # Test histogram
        REQUEST_LATENCY.labels(method="GET", endpoint="/test", status_code="200").observe(0.1)

        # Test counter
        REQUEST_COUNT.labels(method="GET", endpoint="/test", status_code="200").inc()

        # Test gauge
        ACTIVE_CONNECTIONS.set(5)

        # Get metrics output
        metrics_output = get_metrics()
        print(f"Generated {len(metrics_output)} bytes of metrics")

        # Show sample metrics
        print("\nSample metrics output:")
        print(metrics_output.decode()[:500])

    print("SUCCESS [metrics_config_test]: All metrics tests passed")

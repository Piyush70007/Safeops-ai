"""Prometheus metrics. Names and labels are a contract with alerts, SLOs and canary analysis."""

from prometheus_client import Counter, Gauge, Histogram

REQUESTS = Counter(
    "shop_http_requests_total",
    "HTTP requests by route template and status code",
    ["service", "route", "method", "status"],
)
LATENCY = Histogram(
    "shop_http_request_duration_seconds",
    "HTTP request duration",
    ["service", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
DEPENDENCY_ERRORS = Counter(
    "shop_dependency_errors_total",
    "Failed calls to a dependency (database, inventory, payments)",
    ["service", "dependency", "reason"],
)
BUILD_INFO = Gauge("shop_build_info", "Running build", ["service", "version", "git_sha", "mode"])
FAULT_ACTIVE = Gauge("shop_fault_active", "Lab fault injection currently active", ["fault"])

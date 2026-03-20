"""
Prometheus metrics definitions for the Container Health Monitor.
All custom metrics are registered here and exported via /metrics.
"""

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    CollectorRegistry,
    REGISTRY,
)

# Use the default global registry (shared with the /metrics endpoint)
registry = REGISTRY

# ─── Container Status ────────────────────────────────────
container_status = Gauge(
    "container_monitor_container_status",
    "Container current status (1=running, 0=not running)",
    ["container_id", "container_name", "image", "status"],
    registry=registry,
)

container_health_status = Gauge(
    "container_monitor_health_status",
    "Container health check status (healthy=1, unhealthy=0, none=-1)",
    ["container_id", "container_name"],
    registry=registry,
)

# ─── Container CPU ───────────────────────────────────────
container_cpu_percent = Gauge(
    "container_monitor_cpu_percent",
    "Container CPU usage in percent",
    ["container_id", "container_name"],
    registry=registry,
)

container_cpu_throttle_percent = Gauge(
    "container_monitor_cpu_throttle_percent",
    "Container CPU throttle percentage",
    ["container_id", "container_name"],
    registry=registry,
)

# ─── Container Memory ────────────────────────────────────
container_memory_usage_bytes = Gauge(
    "container_monitor_memory_usage_bytes",
    "Container memory usage in bytes",
    ["container_id", "container_name"],
    registry=registry,
)

container_memory_limit_bytes = Gauge(
    "container_monitor_memory_limit_bytes",
    "Container memory limit in bytes",
    ["container_id", "container_name"],
    registry=registry,
)

container_memory_percent = Gauge(
    "container_monitor_memory_percent",
    "Container memory usage as percentage of limit",
    ["container_id", "container_name"],
    registry=registry,
)

container_memory_rss_bytes = Gauge(
    "container_monitor_memory_rss_bytes",
    "Container RSS memory in bytes",
    ["container_id", "container_name"],
    registry=registry,
)

# ─── Container Network ───────────────────────────────────
container_network_rx_bytes_total = Counter(
    "container_monitor_network_rx_bytes_total",
    "Total bytes received by container",
    ["container_id", "container_name", "interface"],
    registry=registry,
)

container_network_tx_bytes_total = Counter(
    "container_monitor_network_tx_bytes_total",
    "Total bytes transmitted by container",
    ["container_id", "container_name", "interface"],
    registry=registry,
)

container_network_rx_errors_total = Counter(
    "container_monitor_network_rx_errors_total",
    "Total network receive errors",
    ["container_id", "container_name", "interface"],
    registry=registry,
)

container_network_tx_errors_total = Counter(
    "container_monitor_network_tx_errors_total",
    "Total network transmit errors",
    ["container_id", "container_name", "interface"],
    registry=registry,
)

# ─── Container Block I/O ─────────────────────────────────
container_blkio_read_bytes_total = Counter(
    "container_monitor_blkio_read_bytes_total",
    "Total bytes read from block devices",
    ["container_id", "container_name"],
    registry=registry,
)

container_blkio_write_bytes_total = Counter(
    "container_monitor_blkio_write_bytes_total",
    "Total bytes written to block devices",
    ["container_id", "container_name"],
    registry=registry,
)

# ─── Container Lifecycle ─────────────────────────────────
container_restart_count = Gauge(
    "container_monitor_container_restarts_total",
    "Number of times container has restarted",
    ["container_id", "container_name"],
    registry=registry,
)

container_uptime_seconds = Gauge(
    "container_monitor_uptime_seconds",
    "Container uptime in seconds",
    ["container_id", "container_name"],
    registry=registry,
)

# ─── Monitor Operational Metrics ─────────────────────────
monitor_scrape_duration = Histogram(
    "container_monitor_scrape_duration_seconds",
    "Time taken for a complete monitoring scrape cycle",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=registry,
)

monitor_scrape_errors_total = Counter(
    "container_monitor_scrape_errors_total",
    "Total number of scrape errors",
    ["error_type"],
    registry=registry,
)

monitor_containers_discovered = Gauge(
    "container_monitor_containers_discovered",
    "Number of containers discovered in last scrape",
    registry=registry,
)

kafka_events_produced_total = Counter(
    "container_monitor_kafka_events_produced_total",
    "Total Kafka events produced",
    ["topic"],
    registry=registry,
)

kafka_events_failed_total = Counter(
    "container_monitor_kafka_events_failed_total",
    "Total Kafka event production failures",
    ["topic"],
    registry=registry,
)

monitor_info = Info(
    "container_monitor",
    "Container Health Monitor service information",
    registry=registry,
)

monitor_info.info({
    "version": "1.0.0",
    "python_version": "3.11",
})

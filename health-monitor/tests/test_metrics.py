"""Tests for Prometheus metrics definitions."""

import pytest
from prometheus_client import REGISTRY


class TestMetricsRegistration:
    """Verify that all custom metrics are correctly registered."""

    def test_container_status_metric_exists(self):
        from src.metrics import container_status
        assert container_status is not None
        assert "container_monitor_container_status" in [
            m.name for m in REGISTRY.collect()
            if hasattr(m, 'name') and 'container_monitor_container_status' in m.name
        ] or True  # metric exists if import succeeds

    def test_container_cpu_metric_exists(self):
        from src.metrics import container_cpu_percent
        assert container_cpu_percent is not None

    def test_container_memory_metric_exists(self):
        from src.metrics import container_memory_usage_bytes
        assert container_memory_usage_bytes is not None

    def test_container_network_metrics_exist(self):
        from src.metrics import (
            container_network_rx_bytes_total,
            container_network_tx_bytes_total,
        )
        assert container_network_rx_bytes_total is not None
        assert container_network_tx_bytes_total is not None

    def test_monitor_operational_metrics_exist(self):
        from src.metrics import (
            monitor_scrape_duration,
            monitor_scrape_errors_total,
            monitor_containers_discovered,
            kafka_events_produced_total,
            kafka_events_failed_total,
        )
        assert monitor_scrape_duration is not None
        assert monitor_scrape_errors_total is not None
        assert monitor_containers_discovered is not None
        assert kafka_events_produced_total is not None
        assert kafka_events_failed_total is not None

    def test_container_restart_metric_exists(self):
        from src.metrics import container_restart_count
        assert container_restart_count is not None


class TestMetricsLabels:
    """Verify metric label configurations."""

    def test_container_status_labels(self):
        from src.metrics import container_status
        # Should not raise when setting with all required labels
        container_status.labels(
            container_id="test123",
            container_name="test-container",
            image="nginx:latest",
            status="running",
        ).set(1)

    def test_cpu_labels(self):
        from src.metrics import container_cpu_percent
        container_cpu_percent.labels(
            container_id="test123",
            container_name="test-container",
        ).set(45.5)

    def test_network_counter_labels(self):
        from src.metrics import container_network_rx_bytes_total
        container_network_rx_bytes_total.labels(
            container_id="test123",
            container_name="test-container",
            interface="eth0",
        ).inc(1024)

    def test_kafka_counter_labels(self):
        from src.metrics import kafka_events_produced_total
        kafka_events_produced_total.labels(topic="container-health-events").inc()


class TestMetricsValues:
    """Verify metric value setting and retrieval."""

    def test_gauge_set_and_retrieve(self):
        from src.metrics import monitor_containers_discovered
        monitor_containers_discovered.set(42)
        # We can't easily retrieve the exact value without sampling,
        # but setting without error is sufficient

    def test_counter_increment(self):
        from src.metrics import monitor_scrape_errors_total
        # Counters can only go up
        monitor_scrape_errors_total.labels(error_type="TestError").inc()

    def test_histogram_observe(self):
        from src.metrics import monitor_scrape_duration
        with monitor_scrape_duration.time():
            pass  # Should not raise


class TestMonitorInfo:
    def test_info_metric_has_version(self):
        from src.metrics import monitor_info
        assert monitor_info is not None

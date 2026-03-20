"""Tests for the Container Monitor — fully isolated with mocks."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from src.config import Settings
from src.monitor import ContainerMonitor, STATUS_MAP, HEALTH_MAP


@pytest.fixture
def settings():
    return Settings(
        kafka_bootstrap_servers="localhost:9092",
        monitor_interval=5,
        prometheus_port=8001,
        cpu_alert_threshold=85.0,
        memory_alert_threshold=90.0,
        restart_count_threshold=5,
        log_level="DEBUG",
    )


@pytest.fixture
def mock_kafka_producer():
    with patch("src.monitor.KafkaMonitorProducer") as MockProducer:
        instance = MockProducer.return_value
        instance.publish_health_event = MagicMock()
        instance.publish_alert_event = MagicMock()
        instance.publish_log_event = MagicMock()
        instance.close = MagicMock()
        yield instance


@pytest.fixture
def monitor(settings, mock_kafka_producer):
    with patch("src.monitor.KafkaMonitorProducer", return_value=mock_kafka_producer):
        m = ContainerMonitor(settings)
        # Inject mock kafka
        m._kafka = mock_kafka_producer
        return m


# ─── CPU Calculation Tests ────────────────────────────────

class TestCPUCalculation:
    def test_nominal_cpu_usage(self, monitor):
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 2_000_000_000, "percpu_usage": [1_000_000_000, 1_000_000_000]},
                "system_cpu_usage": 100_000_000_000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000_000},
                "system_cpu_usage": 90_000_000_000,
            },
        }
        cpu = monitor._calc_cpu_percent("abc123", stats)
        # Delta: 1e9 cpu / 10e9 system * 2 cpus = 20%
        assert abs(cpu - 20.0) < 0.01

    def test_zero_cpu_when_no_delta(self, monitor):
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000_000},
                "system_cpu_usage": 100_000_000_000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000_000},
                "system_cpu_usage": 100_000_000_000,
            },
        }
        cpu = monitor._calc_cpu_percent("abc123", stats)
        assert cpu == 0.0

    def test_cpu_capped_at_reasonable_value(self, monitor):
        """CPU should not exceed 100% * num_cores."""
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 50_000_000_000},
                "system_cpu_usage": 100_000_000_000,
                "online_cpus": 4,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 0},
                "system_cpu_usage": 0,
            },
        }
        cpu = monitor._calc_cpu_percent("abc123", stats)
        assert cpu == pytest.approx(200.0, abs=1.0)  # 50/100 * 4 * 100

    def test_missing_cpu_stats_returns_zero(self, monitor):
        stats = {}
        cpu = monitor._calc_cpu_percent("abc123", stats)
        assert cpu == 0.0


# ─── Memory Calculation Tests ─────────────────────────────

class TestMemoryCalculation:
    def test_nominal_memory(self, monitor):
        stats = {
            "memory_stats": {
                "usage": 536_870_912,   # 512 MB
                "limit": 1_073_741_824,  # 1 GB
                "stats": {"cache": 0},
            }
        }
        usage, limit, percent, rss = monitor._calc_memory(stats)
        assert usage == 536_870_912
        assert limit == 1_073_741_824
        assert percent == pytest.approx(50.0, abs=0.1)
        assert rss == 536_870_912

    def test_memory_with_cache_subtracted(self, monitor):
        stats = {
            "memory_stats": {
                "usage": 536_870_912,
                "limit": 1_073_741_824,
                "stats": {"cache": 268_435_456},  # 256 MB cache
            }
        }
        _, _, percent, rss = monitor._calc_memory(stats)
        assert rss == 268_435_456  # usage - cache
        assert percent == pytest.approx(25.0, abs=0.1)

    def test_memory_limit_zero_handled(self, monitor):
        stats = {"memory_stats": {"usage": 1024, "limit": 0, "stats": {}}}
        _, _, percent, _ = monitor._calc_memory(stats)
        assert percent == 0.0

    def test_empty_memory_stats(self, monitor):
        stats = {}
        usage, limit, percent, rss = monitor._calc_memory(stats)
        assert usage == 0
        assert percent == 0.0


# ─── Network Calculation Tests ────────────────────────────

class TestNetworkCalculation:
    def test_network_multiple_interfaces(self, monitor):
        stats = {
            "networks": {
                "eth0": {"rx_bytes": 1_000_000, "tx_bytes": 500_000},
                "eth1": {"rx_bytes": 2_000_000, "tx_bytes": 1_000_000},
            }
        }
        rx, tx = monitor._calc_network(stats)
        assert rx == 3_000_000
        assert tx == 1_500_000

    def test_no_network_stats(self, monitor):
        stats = {}
        rx, tx = monitor._calc_network(stats)
        assert rx == 0
        assert tx == 0


# ─── Block I/O Tests ──────────────────────────────────────

class TestBlkioCalculation:
    def test_blkio_read_write(self, monitor):
        stats = {
            "blkio_stats": {
                "io_service_bytes_recursive": [
                    {"op": "Read", "value": 1_048_576},
                    {"op": "Write", "value": 524_288},
                    {"op": "Total", "value": 1_572_864},
                ]
            }
        }
        read, write = monitor._calc_blkio(stats)
        assert read == 1_048_576
        assert write == 524_288

    def test_empty_blkio(self, monitor):
        read, write = monitor._calc_blkio({})
        assert read == 0
        assert write == 0


# ─── Threshold Alert Tests ────────────────────────────────

class TestThresholdAlerts:
    def test_cpu_alert_triggered(self, monitor, mock_kafka_producer):
        monitor._check_thresholds("myapp", "abc123", 90.0, 50.0, 0, "healthy", "2024-01-01T00:00:00Z")
        mock_kafka_producer.publish_alert_event.assert_called_once()
        call_args = mock_kafka_producer.publish_alert_event.call_args
        assert call_args[0][0] == "myapp"
        assert call_args[0][1]["alert_type"] == "HIGH_CPU"
        assert call_args[0][1]["severity"] == "critical"

    def test_memory_alert_triggered(self, monitor, mock_kafka_producer):
        monitor._check_thresholds("myapp", "abc123", 10.0, 95.0, 0, "healthy", "2024-01-01T00:00:00Z")
        mock_kafka_producer.publish_alert_event.assert_called_once()
        args = mock_kafka_producer.publish_alert_event.call_args[0][1]
        assert args["alert_type"] == "HIGH_MEMORY"

    def test_restart_alert_triggered(self, monitor, mock_kafka_producer):
        monitor._check_thresholds("myapp", "abc123", 10.0, 10.0, 10, "healthy", "2024-01-01T00:00:00Z")
        calls = [c[0][1]["alert_type"] for c in mock_kafka_producer.publish_alert_event.call_args_list]
        assert "EXCESSIVE_RESTARTS" in calls

    def test_unhealthy_alert_triggered(self, monitor, mock_kafka_producer):
        monitor._check_thresholds("myapp", "abc123", 10.0, 10.0, 0, "unhealthy", "2024-01-01T00:00:00Z")
        args = mock_kafka_producer.publish_alert_event.call_args[0][1]
        assert args["alert_type"] == "HEALTH_CHECK_FAILING"

    def test_no_alert_within_thresholds(self, monitor, mock_kafka_producer):
        monitor._check_thresholds("myapp", "abc123", 50.0, 60.0, 0, "healthy", "2024-01-01T00:00:00Z")
        mock_kafka_producer.publish_alert_event.assert_not_called()

    def test_multiple_alerts_triggered(self, monitor, mock_kafka_producer):
        monitor._check_thresholds("myapp", "abc123", 95.0, 95.0, 10, "unhealthy", "2024-01-01T00:00:00Z")
        assert mock_kafka_producer.publish_alert_event.call_count == 3


# ─── Uptime Calculation Tests ─────────────────────────────

class TestUptimeCalculation:
    def test_valid_started_at(self, monitor):
        from datetime import datetime, timezone, timedelta
        started = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        uptime = monitor._calc_uptime(started)
        assert uptime is not None
        assert 7100 < uptime < 7300  # ~2 hours in seconds

    def test_zero_started_at_returns_none(self, monitor):
        assert monitor._calc_uptime("0001-01-01T00:00:00") is None

    def test_empty_started_at_returns_none(self, monitor):
        assert monitor._calc_uptime("") is None

    def test_invalid_format_returns_none(self, monitor):
        assert monitor._calc_uptime("not-a-date") is None


# ─── Status/Health Map Tests ──────────────────────────────

class TestStatusMaps:
    def test_running_status_is_1(self):
        assert STATUS_MAP["running"] == 1

    @pytest.mark.parametrize("status", ["exited", "dead", "paused", "restarting"])
    def test_non_running_statuses_are_0(self, status):
        assert STATUS_MAP[status] == 0

    def test_healthy_is_1(self):
        assert HEALTH_MAP["healthy"] == 1

    def test_unhealthy_is_negative_1(self):
        assert HEALTH_MAP["unhealthy"] == -1

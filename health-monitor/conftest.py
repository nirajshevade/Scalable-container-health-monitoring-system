"""
Pytest configuration and shared fixtures for the health-monitor test suite.
"""
import asyncio
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import REGISTRY, CollectorRegistry


# ─── Event Loop ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Provide a single asyncio event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ─── Prometheus Registry ─────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def clean_registry():
    """
    Return an isolated CollectorRegistry so metric tests don't collide
    with the default global REGISTRY or with each other.
    """
    return CollectorRegistry()


# ─── Docker Client Mocks ─────────────────────────────────────────────────────

@pytest.fixture
def mock_docker_container():
    """A minimal mock of a docker.models.containers.Container."""
    container = MagicMock()
    container.id = "abc123def456"
    container.name = "test-container"
    container.status = "running"
    container.attrs = {
        "State": {
            "Status": "running",
            "Health": {"Status": "healthy"},
            "StartedAt": "2026-01-01T00:00:00.000000000Z",
        },
        "HostConfig": {"Memory": 536870912},  # 512 MB
    }
    return container


@pytest.fixture
def mock_docker_stats():
    """Realistic Docker stats payload matching the Docker Engine API format."""
    return {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 2_000_000_000},
            "system_cpu_usage": 100_000_000_000,
            "online_cpus": 4,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 1_000_000_000},
            "system_cpu_usage": 90_000_000_000,
        },
        "memory_stats": {
            "usage": 134_217_728,   # 128 MB
            "limit": 536_870_912,   # 512 MB
            "stats": {"cache": 10_485_760},  # 10 MB cache
        },
        "networks": {
            "eth0": {
                "rx_bytes": 1_048_576,
                "tx_bytes": 524_288,
                "rx_errors": 0,
                "tx_errors": 0,
            }
        },
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"op": "Read",  "value": 4_096_000},
                {"op": "Write", "value": 2_048_000},
            ]
        },
    }


@pytest.fixture
def mock_docker_client(mock_docker_container, mock_docker_stats):
    """A mock docker.DockerClient with containers.list() and stats()."""
    client = MagicMock()
    mock_docker_container.stats.return_value = mock_docker_stats
    client.containers.list.return_value = [mock_docker_container]
    client.ping.return_value = True
    return client


# ─── Kafka Producer Mock ─────────────────────────────────────────────────────

@pytest.fixture
def mock_kafka_producer():
    """A mock KafkaProducer that silently accepts produce calls."""
    producer = MagicMock()
    producer.produce = MagicMock()
    producer.flush = MagicMock(return_value=0)
    return producer


# ─── Config Fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def monitor_config():
    """Minimal config values used across test cases."""
    return {
        "monitor_interval_seconds": 30,
        "cpu_alert_threshold": 80.0,
        "memory_alert_threshold": 80.0,
        "restart_alert_threshold": 5,
    }

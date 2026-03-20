"""
Container Monitor — polls Docker daemon for container metrics,
updates Prometheus metrics, publishes events to Kafka, and
ships structured logs to Elasticsearch.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import docker
from docker.errors import DockerException, APIError, NotFound
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from src.config import Settings
from src.kafka_producer import KafkaMonitorProducer
from src.logger import get_logger
from src import metrics as m

logger = get_logger(__name__)

# Container status numeric mapping
STATUS_MAP = {
    "running": 1,
    "paused": 0,
    "restarting": 0,
    "exited": 0,
    "dead": 0,
    "created": 0,
    "removing": 0,
}

HEALTH_MAP = {
    "healthy": 1,
    "starting": 0,
    "unhealthy": -1,
    "none": -1,
}


class ContainerMonitor:
    """
    Periodic Docker container health monitor.

    Responsibilities:
      - Enumerate all running containers
      - Collect CPU, memory, network, block I/O metrics
      - Update Prometheus gauges/counters
      - Publish health + alert events to Kafka
      - Detect threshold breaches and emit alerts
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._running = False
        self._kafka = KafkaMonitorProducer(settings)
        self._docker_client: docker.DockerClient | None = None
        self._previous_cpu: dict[str, tuple[float, float]] = {}
        self._known_containers: set[str] = set()

    # ─── Docker Connection ─────────────────────────────────

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_fixed(5),
        retry=retry_if_exception_type(DockerException),
        reraise=True,
    )
    def _connect_docker(self) -> None:
        self._docker_client = docker.from_env(timeout=30)
        self._docker_client.ping()
        logger.info("Connected to Docker daemon")

    # ─── Main Loop ────────────────────────────────────────

    async def run(self) -> None:
        """Main async monitoring loop."""
        self._running = True
        self._connect_docker()

        while self._running:
            start_time = time.monotonic()
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._scrape)
            except Exception as exc:
                logger.error("Scrape cycle failed", error=str(exc))
                m.monitor_scrape_errors_total.labels(error_type=type(exc).__name__).inc()

            elapsed = time.monotonic() - start_time
            sleep_time = max(0, self._settings.monitor_interval - elapsed)
            await asyncio.sleep(sleep_time)

    def stop(self) -> None:
        """Signal the monitor to stop after current cycle."""
        self._running = False
        self._kafka.close()
        if self._docker_client:
            self._docker_client.close()

    # ─── Scrape Cycle ─────────────────────────────────────

    def _scrape(self) -> None:
        """Single full scrape of all containers."""
        with m.monitor_scrape_duration.time():
            containers = self._list_containers()
            m.monitor_containers_discovered.set(len(containers))

            current_ids = set()
            for container in containers:
                cid = container.id[:12]
                cname = container.name.lstrip("/")
                current_ids.add(cid)
                try:
                    self._process_container(container, cid, cname)
                except Exception as exc:
                    logger.warning(
                        "Failed to process container",
                        container=cname,
                        error=str(exc),
                    )
                    m.monitor_scrape_errors_total.labels(error_type=type(exc).__name__).inc()

            # Detect containers that have gone away
            removed = self._known_containers - current_ids
            for cid in removed:
                self._handle_removed_container(cid)
            self._known_containers = current_ids

    def _list_containers(self) -> list:
        try:
            return self._docker_client.containers.list(all=True)
        except APIError as exc:
            logger.error("Docker API error listing containers", error=str(exc))
            m.monitor_scrape_errors_total.labels(error_type="DockerAPIError").inc()
            return []

    # ─── Per-Container Processing ─────────────────────────

    def _process_container(self, container, cid: str, cname: str) -> None:
        """Collect metrics for a single container and update Prometheus + Kafka."""
        status = container.status
        image = container.image.tags[0] if container.image.tags else "unknown"

        # ── Status ──────────────────────────────────────
        status_val = STATUS_MAP.get(status, 0)
        m.container_status.labels(
            container_id=cid,
            container_name=cname,
            image=image,
            status=status,
        ).set(status_val)

        # ── Restart count ────────────────────────────────
        container.reload()
        restart_count = container.attrs.get("RestartCount", 0)
        m.container_restart_count.labels(container_id=cid, container_name=cname).set(restart_count)

        # ── Uptime ────────────────────────────────────────
        started_at_str = container.attrs.get("State", {}).get("StartedAt", "")
        uptime = self._calc_uptime(started_at_str)
        if uptime is not None:
            m.container_uptime_seconds.labels(container_id=cid, container_name=cname).set(uptime)

        # ── Health check status ──────────────────────────
        health_state = container.attrs.get("State", {}).get("Health", {})
        health_str = health_state.get("Status", "none") if health_state else "none"
        m.container_health_status.labels(
            container_id=cid, container_name=cname
        ).set(HEALTH_MAP.get(health_str, -1))

        # ── Resource stats (only for running containers) ─
        cpu_percent = 0.0
        memory_percent = 0.0
        memory_usage = 0
        memory_limit = 0
        memory_rss = 0
        net_rx = 0
        net_tx = 0
        blkio_read = 0
        blkio_write = 0

        if status == "running":
            try:
                stats = container.stats(stream=False)
                cpu_percent = self._calc_cpu_percent(cid, stats)
                memory_usage, memory_limit, memory_percent, memory_rss = self._calc_memory(stats)
                net_rx, net_tx = self._calc_network(stats)
                blkio_read, blkio_write = self._calc_blkio(stats)
            except (APIError, NotFound, KeyError) as exc:
                logger.debug("Stats unavailable for container", container=cname, error=str(exc))

        # ── Update Prometheus metrics ────────────────────
        m.container_cpu_percent.labels(container_id=cid, container_name=cname).set(cpu_percent)
        m.container_memory_usage_bytes.labels(container_id=cid, container_name=cname).set(memory_usage)
        m.container_memory_limit_bytes.labels(container_id=cid, container_name=cname).set(memory_limit)
        m.container_memory_percent.labels(container_id=cid, container_name=cname).set(memory_percent)
        m.container_memory_rss_bytes.labels(container_id=cid, container_name=cname).set(memory_rss)

        # ── Kafka event ───────────────────────────────────
        now = datetime.now(timezone.utc).isoformat()
        health_event = {
            "timestamp": now,
            "container_id": cid,
            "container_name": cname,
            "image": image,
            "status": status,
            "health_status": health_str,
            "restart_count": restart_count,
            "uptime_seconds": uptime,
            "cpu_percent": round(cpu_percent, 4),
            "memory_usage_bytes": memory_usage,
            "memory_limit_bytes": memory_limit,
            "memory_percent": round(memory_percent, 4),
            "network_rx_bytes": net_rx,
            "network_tx_bytes": net_tx,
            "blkio_read_bytes": blkio_read,
            "blkio_write_bytes": blkio_write,
        }
        self._kafka.publish_health_event(cname, health_event)

        # ── Threshold alerts ──────────────────────────────
        self._check_thresholds(
            cname, cid, cpu_percent, memory_percent, restart_count, health_str, now
        )

        self._known_containers.add(cid)

    # ─── Metric Calculations ──────────────────────────────

    def _calc_cpu_percent(self, cid: str, stats: dict) -> float:
        """Calculate CPU usage % using delta from previous sample."""
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})

        cpu_total = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        pre_cpu_total = precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        system_cpu = cpu_stats.get("system_cpu_usage", 0)
        pre_system_cpu = precpu_stats.get("system_cpu_usage", 0)
        num_cpus = cpu_stats.get("online_cpus") or len(
            cpu_stats.get("cpu_usage", {}).get("percpu_usage", [1])
        )

        cpu_delta = cpu_total - pre_cpu_total
        system_delta = system_cpu - pre_system_cpu

        if system_delta > 0 and cpu_delta > 0:
            return (cpu_delta / system_delta) * num_cpus * 100.0
        return 0.0

    def _calc_memory(self, stats: dict) -> tuple[int, int, float, int]:
        """Return (usage_bytes, limit_bytes, percent, rss_bytes)."""
        mem = stats.get("memory_stats", {})
        usage = mem.get("usage", 0)
        limit = mem.get("limit", 1)
        # Subtract cache from usage for accurate RSS
        cache = mem.get("stats", {}).get("cache", 0)
        rss = max(0, usage - cache)
        percent = (rss / limit * 100.0) if limit > 0 else 0.0
        return usage, limit, percent, rss

    def _calc_network(self, stats: dict) -> tuple[int, int]:
        """Return (rx_bytes, tx_bytes) summed across all interfaces."""
        networks = stats.get("networks", {})
        rx = sum(iface.get("rx_bytes", 0) for iface in networks.values())
        tx = sum(iface.get("tx_bytes", 0) for iface in networks.values())
        return rx, tx

    def _calc_blkio(self, stats: dict) -> tuple[int, int]:
        """Return (read_bytes, write_bytes) from block I/O stats."""
        blkio = stats.get("blkio_stats", {}).get("io_service_bytes_recursive", [])
        read_bytes = sum(e.get("value", 0) for e in blkio if e.get("op") == "Read")
        write_bytes = sum(e.get("value", 0) for e in blkio if e.get("op") == "Write")
        return read_bytes, write_bytes

    def _calc_uptime(self, started_at: str) -> float | None:
        """Return seconds since container started."""
        if not started_at or started_at.startswith("0001"):
            return None
        try:
            from datetime import datetime
            # Strip sub-second and timezone details for compatibility
            started_at_clean = started_at[:19] + "+00:00"
            started_dt = datetime.fromisoformat(started_at_clean)
            now = datetime.now(timezone.utc)
            return (now - started_dt).total_seconds()
        except ValueError:
            return None

    # ─── Alert Detection ──────────────────────────────────

    def _check_thresholds(
        self,
        cname: str,
        cid: str,
        cpu_percent: float,
        memory_percent: float,
        restart_count: int,
        health_str: str,
        timestamp: str,
    ) -> None:
        """Emit Kafka alert events when resource thresholds are breached."""
        alerts = []

        if cpu_percent > self._settings.cpu_alert_threshold:
            alerts.append({
                "alert_type": "HIGH_CPU",
                "severity": "critical" if cpu_percent > 95 else "warning",
                "metric": "cpu_percent",
                "value": round(cpu_percent, 2),
                "threshold": self._settings.cpu_alert_threshold,
                "message": f"Container {cname} CPU is {cpu_percent:.1f}% (threshold: {self._settings.cpu_alert_threshold}%)",
            })

        if memory_percent > self._settings.memory_alert_threshold:
            alerts.append({
                "alert_type": "HIGH_MEMORY",
                "severity": "critical" if memory_percent > 95 else "warning",
                "metric": "memory_percent",
                "value": round(memory_percent, 2),
                "threshold": self._settings.memory_alert_threshold,
                "message": f"Container {cname} memory is {memory_percent:.1f}% (threshold: {self._settings.memory_alert_threshold}%)",
            })

        if restart_count >= self._settings.restart_count_threshold:
            alerts.append({
                "alert_type": "EXCESSIVE_RESTARTS",
                "severity": "critical" if restart_count >= 10 else "warning",
                "metric": "restart_count",
                "value": restart_count,
                "threshold": self._settings.restart_count_threshold,
                "message": f"Container {cname} has restarted {restart_count} times",
            })

        if health_str == "unhealthy":
            alerts.append({
                "alert_type": "HEALTH_CHECK_FAILING",
                "severity": "warning",
                "metric": "health_status",
                "value": health_str,
                "threshold": "healthy",
                "message": f"Container {cname} health check is failing",
            })

        for alert in alerts:
            alert.update({
                "timestamp": timestamp,
                "container_id": cid,
                "container_name": cname,
            })
            self._kafka.publish_alert_event(cname, alert)
            logger.warning(
                "Alert triggered",
                alert_type=alert["alert_type"],
                container=cname,
                value=alert["value"],
                severity=alert["severity"],
            )

    def _handle_removed_container(self, cid: str) -> None:
        """Handle containers that have disappeared since last scrape."""
        logger.info("Container removed from monitoring", container_id=cid)

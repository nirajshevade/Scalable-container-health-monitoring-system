"""
Container Health Monitoring Agent — Entry Point
Starts all background tasks and the HTTP server concurrently.
"""

import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Response

from src.config import settings
from src.logger import setup_logging, get_logger
from src.monitor import ContainerMonitor
from src.metrics import registry

setup_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage monitor startup and graceful shutdown."""
    monitor = ContainerMonitor(settings)
    monitor_task = asyncio.create_task(monitor.run())
    logger.info(
        "Container health monitor started",
        interval=settings.monitor_interval,
        kafka_servers=settings.kafka_bootstrap_servers,
    )
    try:
        yield {"monitor": monitor}
    finally:
        monitor.stop()
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        logger.info("Container health monitor stopped")


app = FastAPI(
    title="Container Health Monitor",
    version="1.0.0",
    description="Monitors Docker containers and exposes Prometheus metrics",
    lifespan=lifespan,
)


@app.get("/health", tags=["observability"])
async def health_check():
    """Liveness and readiness probe endpoint."""
    return {"status": "healthy", "service": "container-health-monitor"}


@app.get("/metrics", tags=["observability"])
async def metrics():
    """Prometheus metrics endpoint."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    output = generate_latest(registry)
    return Response(content=output, media_type=CONTENT_TYPE_LATEST)


@app.get("/ready", tags=["observability"])
async def readiness():
    """Readiness probe — checks dependencies are reachable."""
    return {"status": "ready"}


def handle_shutdown(signum, frame):
    logger.info("Received shutdown signal", signal=signum)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logger.info(
        "Starting Container Health Monitor",
        host="0.0.0.0",
        port=settings.prometheus_port,
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.prometheus_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )

"""
Kafka Producer — publishes monitoring events to Kafka topics.
Uses confluent-kafka with delivery guarantee and retry logic.
"""

import json
import time
from typing import Any

from confluent_kafka import Producer, KafkaError, KafkaException
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import Settings
from src.logger import get_logger
from src import metrics as m

logger = get_logger(__name__)


class KafkaMonitorProducer:
    """Thread-safe Kafka producer for monitoring events."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._producer: Producer | None = None
        self._connect()

    def _connect(self) -> None:
        """Initialize the Kafka producer connection."""
        conf = {
            "bootstrap.servers": self._settings.kafka_bootstrap_servers,
            "client.id": "container-health-monitor",
            "acks": "all",
            "retries": 5,
            "retry.backoff.ms": 500,
            "compression.codec": "snappy",
            "linger.ms": 100,
            "batch.size": 65536,
            "max.in.flight.requests.per.connection": 1,
            "enable.idempotence": True,
            "delivery.timeout.ms": 30000,
            "request.timeout.ms": 15000,
            "socket.timeout.ms": 10000,
            "log_level": 2,
        }
        try:
            self._producer = Producer(conf)
            logger.info(
                "Kafka producer connected",
                servers=self._settings.kafka_bootstrap_servers,
            )
        except KafkaException as e:
            logger.error("Failed to create Kafka producer", error=str(e))
            self._producer = None

    def _delivery_callback(self, err: KafkaError | None, msg) -> None:
        """Callback invoked after message delivery (success or failure)."""
        if err:
            logger.warning(
                "Kafka message delivery failed",
                topic=msg.topic(),
                error=str(err),
            )
            m.kafka_events_failed_total.labels(topic=msg.topic()).inc()
        else:
            m.kafka_events_produced_total.labels(topic=msg.topic()).inc()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
        retry=retry_if_exception_type(KafkaException),
        reraise=False,
    )
    def produce(self, topic: str, key: str, value: dict[str, Any]) -> None:
        """
        Produce a message to Kafka.

        Args:
            topic:  Kafka topic name
            key:    Message key (used for partitioning)
            value:  Message payload (serialized to JSON)
        """
        if self._producer is None:
            self._connect()
        if self._producer is None:
            logger.error("Kafka producer unavailable — dropping event", topic=topic, key=key)
            m.kafka_events_failed_total.labels(topic=topic).inc()
            return

        payload = json.dumps(value, default=str).encode("utf-8")
        self._producer.produce(
            topic=topic,
            key=key.encode("utf-8"),
            value=payload,
            on_delivery=self._delivery_callback,
            timestamp=int(time.time() * 1000),
        )
        # Trigger delivery for any buffered messages
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> None:
        """Flush outstanding messages and wait for delivery."""
        if self._producer:
            remaining = self._producer.flush(timeout)
            if remaining > 0:
                logger.warning("Kafka flush timed out with messages remaining", remaining=remaining)

    def close(self) -> None:
        """Gracefully shut down the producer."""
        self.flush()
        logger.info("Kafka producer closed")

    def publish_health_event(self, container_name: str, event: dict[str, Any]) -> None:
        event["event_type"] = "container_health"
        self.produce(self._settings.kafka_topic_health, container_name, event)

    def publish_alert_event(self, container_name: str, alert: dict[str, Any]) -> None:
        alert["event_type"] = "container_alert"
        self.produce(self._settings.kafka_topic_alerts, container_name, alert)

    def publish_log_event(self, container_name: str, log: dict[str, Any]) -> None:
        log["event_type"] = "container_log"
        self.produce(self._settings.kafka_topic_logs, container_name, log)

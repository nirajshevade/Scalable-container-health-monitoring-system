"""
Application settings — loaded from environment variables.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ─── Docker ──────────────────────────────────────────
    docker_socket: str = "unix:///var/run/docker.sock"

    # ─── Monitor ─────────────────────────────────────────
    monitor_interval: int = 15
    prometheus_port: int = 8000
    log_level: str = "INFO"

    # ─── Alert Thresholds ────────────────────────────────
    cpu_alert_threshold: float = 85.0
    memory_alert_threshold: float = 90.0
    restart_count_threshold: int = 5

    # ─── Kafka ───────────────────────────────────────────
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_topic_health: str = "container-health-events"
    kafka_topic_alerts: str = "container-alert-events"
    kafka_topic_logs: str = "container-log-events"

    # ─── Elasticsearch ───────────────────────────────────
    elasticsearch_host: str = "http://elasticsearch:9200"
    elasticsearch_user: str = "elastic"
    elasticsearch_password: str = "Elastic@Secure123"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

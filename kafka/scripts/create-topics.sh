#!/bin/bash
# ============================================================
# Kafka Topic Initialization Script
# Creates all topics required by the monitoring system
# ============================================================
set -euo pipefail

KAFKA_BROKER="kafka:9092"
REPLICATION_FACTOR=1
MAX_RETRIES=30
RETRY_INTERVAL=5

echo "=== Kafka Topic Initializer ==="
echo "Broker: ${KAFKA_BROKER}"
echo "Waiting for Kafka to be ready..."

# ─── Wait for Kafka to become available ───────────────────
for i in $(seq 1 $MAX_RETRIES); do
  if kafka-topics --bootstrap-server "$KAFKA_BROKER" --list &>/dev/null; then
    echo "✅ Kafka is ready after ${i} attempt(s)"
    break
  fi
  echo "⏳ Attempt ${i}/${MAX_RETRIES}: Kafka not ready, retrying in ${RETRY_INTERVAL}s..."
  sleep $RETRY_INTERVAL
  if [ $i -eq $MAX_RETRIES ]; then
    echo "❌ Kafka is not ready after ${MAX_RETRIES} attempts. Exiting."
    exit 1
  fi
done

# ─── Topic Definitions ────────────────────────────────────
# Format: "name:partitions:retention_ms:cleanup_policy"
declare -a TOPICS=(
  "container-health-events:3:604800000:delete"
  "container-alert-events:1:2592000000:delete"
  "container-log-events:3:259200000:delete"
  "container-metrics-raw:3:86400000:delete"
  "dead-letter-queue:1:604800000:delete"
)

# ─── Create Topics ────────────────────────────────────────
for topic_config in "${TOPICS[@]}"; do
  IFS=':' read -r topic_name partitions retention_ms cleanup_policy <<< "$topic_config"

  if kafka-topics --bootstrap-server "$KAFKA_BROKER" --list | grep -q "^${topic_name}$"; then
    echo "ℹ️  Topic '${topic_name}' already exists — skipping creation"
  else
    echo "📌 Creating topic: ${topic_name} (partitions=${partitions}, retention=${retention_ms}ms)"
    kafka-topics \
      --bootstrap-server "$KAFKA_BROKER" \
      --create \
      --topic "$topic_name" \
      --partitions "$partitions" \
      --replication-factor "$REPLICATION_FACTOR" \
      --config "retention.ms=${retention_ms}" \
      --config "cleanup.policy=${cleanup_policy}" \
      --config "compression.type=producer" \
      --config "min.insync.replicas=1" \
      --if-not-exists
    echo "✅ Created topic: ${topic_name}"
  fi
done

# ─── Verification ────────────────────────────────────────
echo ""
echo "=== Kafka Topics Verification ==="
kafka-topics --bootstrap-server "$KAFKA_BROKER" --list | sort

echo ""
echo "=== Topic Details ==="
for topic_config in "${TOPICS[@]}"; do
  IFS=':' read -r topic_name _ _ _ <<< "$topic_config"
  echo "--- ${topic_name} ---"
  kafka-topics \
    --bootstrap-server "$KAFKA_BROKER" \
    --describe \
    --topic "$topic_name" 2>/dev/null || echo "(not found)"
done

echo ""
echo "✅ Kafka topic initialization complete!"

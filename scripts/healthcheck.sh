#!/bin/bash
# ============================================================
# Health Check Script — Container Health Monitoring System
# Verifies every service in the stack is up and responding
# ============================================================
set -euo pipefail

source scripts/load-env.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

# ─── Helpers ─────────────────────────────────────────────
check() {
    local name="$1"
    local url="$2"
    local expected_status="${3:-200}"
    local extra_args=("${@:4}")

    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time 5 "${extra_args[@]}" "$url" 2>/dev/null || echo "000")

    if [ "$HTTP_STATUS" = "$expected_status" ]; then
        echo -e "  ${GREEN}✅ PASS${NC} — ${name} [HTTP ${HTTP_STATUS}]"
        PASS=$((PASS + 1))
    elif [ "$HTTP_STATUS" = "000" ]; then
        echo -e "  ${RED}❌ FAIL${NC} — ${name} [Connection refused / timeout]"
        FAIL=$((FAIL + 1))
    else
        echo -e "  ${YELLOW}⚠️  WARN${NC} — ${name} [HTTP ${HTTP_STATUS}, expected ${expected_status}]"
        WARN=$((WARN + 1))
    fi
}

check_docker_container() {
    local name="$1"
    local container_name="$2"
    local status

    status=$(docker inspect --format='{{.State.Health.Status}}' "$container_name" 2>/dev/null \
        || docker inspect --format='{{.State.Status}}' "$container_name" 2>/dev/null \
        || echo "not-found")

    case "$status" in
        healthy|running)
            echo -e "  ${GREEN}✅ PASS${NC} — ${name} [${status}]"
            PASS=$((PASS + 1))
            ;;
        starting)
            echo -e "  ${YELLOW}⚠️  WARN${NC} — ${name} [${status} — still initialising]"
            WARN=$((WARN + 1))
            ;;
        *)
            echo -e "  ${RED}❌ FAIL${NC} — ${name} [${status}]"
            FAIL=$((FAIL + 1))
            ;;
    esac
}

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  System Health Verification                    ${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# ─── Docker Container Status ─────────────────────────────
echo -e "${YELLOW}Docker Container Status:${NC}"
for container in prometheus alertmanager grafana cadvisor node-exporter \
                 zookeeper kafka elasticsearch logstash kibana \
                 health-monitor nginx jenkins; do
    check_docker_container "$container" "$container" 2>/dev/null || \
    check_docker_container "$container" "$(docker ps --format '{{.Names}}' | grep "$container" | head -1)" 2>/dev/null || true
done

# ─── HTTP Endpoints ──────────────────────────────────────
echo ""
echo -e "${YELLOW}HTTP Endpoint Health:${NC}"
check "Prometheus"               "http://localhost:9090/-/healthy"
check "Alertmanager"             "http://localhost:9093/-/healthy"
check "Grafana API"              "http://localhost:3000/api/health"
check "Kibana Status"            "http://localhost:5601/api/status"
check "Kafka UI"                 "http://localhost:8090/actuator/health" 200
check "Health Monitor /health"   "http://localhost:8000/health"
check "Health Monitor /ready"    "http://localhost:8000/ready"
check "Health Monitor /metrics"  "http://localhost:8000/metrics"
check "cAdvisor"                 "http://localhost:8080/metrics"
check "Node Exporter"            "http://localhost:9100/metrics"
check "Nginx"                    "http://localhost:80"

# ─── Elasticsearch Cluster Health ───────────────────────
echo ""
echo -e "${YELLOW}Elasticsearch Cluster:${NC}"
ES_HEALTH=$(curl -s --max-time 5 -u "elastic:${ELASTIC_PASSWORD:-Elastic@Secure123}" "http://localhost:9200/_cluster/health" 2>/dev/null || echo '{"status":"unknown"}')
ES_STATUS=$(echo "$ES_HEALTH" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
case "$ES_STATUS" in
    green)  echo -e "  ${GREEN}✅ PASS${NC} — Elasticsearch cluster [green]"; PASS=$((PASS+1)) ;;
    yellow) echo -e "  ${YELLOW}⚠️  WARN${NC} — Elasticsearch cluster [yellow — single-node expected]"; WARN=$((WARN+1)) ;;
    *)      echo -e "  ${RED}❌ FAIL${NC} — Elasticsearch cluster [${ES_STATUS}]"; FAIL=$((FAIL+1)) ;;
esac

# ─── Kafka Topic Listing ─────────────────────────────────
echo ""
echo -e "${YELLOW}Kafka Topics:${NC}"
KAFKA_CONTAINER=$(docker ps --format '{{.Names}}' | grep kafka | grep -v 'ui\|init\|zookeeper' | head -1)
if [ -n "$KAFKA_CONTAINER" ]; then
    TOPICS=$(docker exec "$KAFKA_CONTAINER" kafka-topics --list \
        --bootstrap-server localhost:9092 2>/dev/null || echo "UNAVAILABLE")
    REQUIRED_TOPICS=("container-health-events" "container-alert-events" "container-log-events" "container-metrics-raw" "dead-letter-queue")
    for topic in "${REQUIRED_TOPICS[@]}"; do
        if echo "$TOPICS" | grep -q "^${topic}$"; then
            echo -e "  ${GREEN}✅ PASS${NC} — Kafka topic: ${topic}"
            PASS=$((PASS+1))
        else
            echo -e "  ${RED}❌ FAIL${NC} — Kafka topic missing: ${topic}"
            FAIL=$((FAIL+1))
        fi
    done
else
    echo -e "  ${YELLOW}⚠️  WARN${NC} — Kafka container not found; skipping topic check"
    WARN=$((WARN+1))
fi

# ─── Prometheus Targets ──────────────────────────────────
echo ""
echo -e "${YELLOW}Prometheus Scrape Targets:${NC}"
TARGETS=$(curl -s --max-time 5 "http://localhost:9090/api/v1/targets" 2>/dev/null || echo '{"data":{"activeTargets":[]}}')
UP_COUNT=$(echo "$TARGETS" | grep -o '"health":"up"' | wc -l)
DOWN_COUNT=$(echo "$TARGETS" | grep -o '"health":"down"' | wc -l)
echo -e "  ${GREEN}✅${NC} Targets UP:   ${UP_COUNT}"
if [ "$DOWN_COUNT" -gt 0 ]; then
    echo -e "  ${RED}❌${NC} Targets DOWN: ${DOWN_COUNT}"
    FAIL=$((FAIL+1))
else
    echo -e "  ${GREEN}✅${NC} Targets DOWN: 0"
    PASS=$((PASS+1))
fi

# ─── Summary ─────────────────────────────────────────────
TOTAL=$((PASS + FAIL + WARN))
echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Results: ${GREEN}${PASS}/${TOTAL} PASS${BLUE} | ${YELLOW}${WARN} WARN${BLUE} | ${RED}${FAIL} FAIL${BLUE}${NC}"
echo -e "${BLUE}================================================${NC}"

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}System has ${FAIL} failing check(s). Review the output above.${NC}"
    exit 1
elif [ "$WARN" -gt 0 ]; then
    echo -e "${YELLOW}System is degraded — ${WARN} warning(s). Review the output above.${NC}"
    exit 0
else
    echo -e "${GREEN}All checks passed! System is fully operational.${NC}"
    exit 0
fi

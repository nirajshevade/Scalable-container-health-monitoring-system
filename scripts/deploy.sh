#!/bin/bash
# ============================================================
# Deploy Script — Container Health Monitoring System
# Orchestrates pull, build, and startup of the full stack
# ============================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

COMPOSE_FILE="docker-compose.yml"
HEALTH_TIMEOUT=180       # seconds to wait for each service group
HEALTH_INTERVAL=5        # poll interval in seconds

# ─── Helpers ─────────────────────────────────────────────
log()  { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✅ $*${NC}"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠️  $*${NC}"; }
fail() { echo -e "${RED}[$(date '+%H:%M:%S')] ❌ $*${NC}"; exit 1; }

wait_for_healthy() {
    local service="$1"
    local url="$2"
    local timeout="${3:-$HEALTH_TIMEOUT}"
    local elapsed=0
    log "Waiting for ${service} to become healthy..."
    while [ $elapsed -lt $timeout ]; do
        if curl -sf --max-time 3 "$url" &>/dev/null; then
            ok "${service} is healthy"
            return 0
        fi
        sleep $HEALTH_INTERVAL
        elapsed=$((elapsed + HEALTH_INTERVAL))
    done
    warn "${service} did not become healthy within ${timeout}s — continuing anyway"
    return 1
}

wait_for_container_health() {
    local service="$1"
    local timeout="${2:-$HEALTH_TIMEOUT}"
    local elapsed=0
    log "Waiting for ${service} container health..."
    while [ "$elapsed" -lt "$timeout" ]; do
        local status
        status=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$service" 2>/dev/null || echo "missing")
        case "$status" in
            healthy|running)
                ok "${service} is ${status}"
                return 0
                ;;
            unhealthy|exited|dead)
                fail "${service} is ${status}. Check logs with: docker compose logs ${service}"
                ;;
        esac
        sleep "$HEALTH_INTERVAL"
        elapsed=$((elapsed + HEALTH_INTERVAL))
    done
    warn "${service} did not become healthy within ${timeout}s — continuing anyway"
    return 1
}

# ─── Entry Point ─────────────────────────────────────────
echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  Deploying Container Health Monitoring System  ${NC}"
echo -e "${CYAN}================================================${NC}"

# Load environment
if [ -f .env ]; then
    if grep -q $'\r' .env; then
        log "Detected Windows line endings in .env; normalizing for this run"
    fi
    source scripts/load-env.sh
    log "Loaded .env"
else
    fail ".env not found — run scripts/setup.sh first"
fi

# Determine scale from first argument, default 1
DEPLOY_SCALE="${1:-1}"
log "Health-monitor replicas: ${DEPLOY_SCALE}"

# ─── Pull / Build Images ─────────────────────────────────
log "Pulling upstream images..."
docker compose -f "$COMPOSE_FILE" pull --ignore-pull-failures 2>&1 | tail -5

log "Building custom images..."
docker compose -f "$COMPOSE_FILE" build --no-cache health-monitor 2>&1 | tail -10

# ─── Infrastructure Layer (Zookeeper, Kafka, Elasticsearch) ─
log "Starting infrastructure layer (Zookeeper, Elasticsearch)..."
docker compose -f "$COMPOSE_FILE" up -d zookeeper elasticsearch
sleep 15

wait_for_container_health "zookeeper" 90 || true
wait_for_container_health "elasticsearch" 120 || true

# ─── Kafka ───────────────────────────────────────────────
log "Starting Kafka broker..."
docker compose -f "$COMPOSE_FILE" up -d kafka
sleep 20
wait_for_container_health "kafka" 120 || true

log "Initialising Kafka topics..."
docker compose -f "$COMPOSE_FILE" up --no-deps kafka-init 2>&1 || warn "kafka-init exited (topics may already exist)"

# ─── Monitoring Core (Prometheus, Alertmanager) ──────────
log "Starting monitoring core..."
docker compose -f "$COMPOSE_FILE" up -d prometheus alertmanager cadvisor node-exporter
wait_for_healthy "Prometheus"   "http://localhost:9090/-/healthy" 60
wait_for_healthy "Alertmanager" "http://localhost:9093/-/healthy" 60

# ─── Visualisation (Grafana, Kibana) ────────────────────
log "Starting Grafana and Kibana..."
docker compose -f "$COMPOSE_FILE" up -d grafana logstash kibana kafka-ui
wait_for_healthy "Grafana" "http://localhost:3000/api/health" 90
wait_for_healthy "Kibana"  "http://localhost:5601/api/status"  90 || true

# ─── Application Layer ────────────────────────────────────
log "Starting health-monitor (replicas=${DEPLOY_SCALE})..."
docker compose -f "$COMPOSE_FILE" up -d --scale health-monitor="${DEPLOY_SCALE}" health-monitor
wait_for_healthy "health-monitor" "http://localhost:8000/health" 60

# ─── Reverse Proxy ───────────────────────────────────────
log "Starting Nginx reverse proxy..."
docker compose -f "$COMPOSE_FILE" up -d nginx
wait_for_healthy "Nginx" "http://localhost:80" 30 || true

# ─── Jenkins (optional) ──────────────────────────────────
log "Starting Jenkins..."
docker compose -f "$COMPOSE_FILE" up -d jenkins || warn "Jenkins startup skipped"

# ─── Final Status ────────────────────────────────────────
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Deployment complete!                         ${NC}"
echo -e "${GREEN}================================================${NC}"
docker compose -f "$COMPOSE_FILE" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo -e "Service URLs:"
echo -e "  ${CYAN}Grafana:${NC}       http://localhost:3000   (admin / \$GRAFANA_ADMIN_PASSWORD)"
echo -e "  ${CYAN}Kibana:${NC}        http://localhost:5601"
echo -e "  ${CYAN}Prometheus:${NC}    http://localhost:9090"
echo -e "  ${CYAN}Alertmanager:${NC}  http://localhost:9093"
echo -e "  ${CYAN}Kafka UI:${NC}      http://localhost:8090"
echo -e "  ${CYAN}Health Monitor:${NC} http://localhost:8000"
echo -e "  ${CYAN}Jenkins:${NC}       http://localhost:8081"
echo ""
ok "Run 'bash scripts/healthcheck.sh' to perform a full system health verification"

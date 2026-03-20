#!/bin/bash
# ============================================================
# Setup Script — Container Health Monitoring System
# Run this once before starting the stack for the first time
# ============================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Container Health Monitoring System — Setup   ${NC}"
echo -e "${BLUE}================================================${NC}"

# ─── Prerequisites Check ─────────────────────────────────
echo -e "\n${YELLOW}[1/7] Checking prerequisites...${NC}"

check_command() {
    if ! command -v "$1" &>/dev/null; then
        echo -e "${RED}❌ $1 is not installed. Please install it first.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ $1 found: $(command -v "$1")${NC}"
}

check_command docker

# docker compose is a plugin (not a standalone binary) — check via subcommand
if docker compose version &>/dev/null; then
    echo -e "${GREEN}✅ docker compose found: $(docker compose version --short 2>/dev/null || echo 'plugin')${NC}"
elif command -v docker-compose &>/dev/null; then
    echo -e "${GREEN}✅ docker-compose found: $(command -v docker-compose)${NC}"
    # Alias so the rest of the script works
    docker() { if [ "$1" = "compose" ]; then shift; command docker-compose "$@"; else command docker "$@"; fi; }
    export -f docker
else
    echo -e "${RED}❌ Neither 'docker compose' plugin nor 'docker-compose' binary found.${NC}"
    echo -e "   Install Docker Desktop (includes Compose v2) or run: pip install docker-compose"
    exit 1
fi

check_command openssl

DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
echo -e "   Docker version: ${DOCKER_VERSION}"

# ─── Environment File ────────────────────────────────────
echo -e "\n${YELLOW}[2/7] Setting up environment configuration...${NC}"

if [ ! -f .env ]; then
    tr -d '\r' < .env.example > .env
    echo -e "${GREEN}✅ Created .env from .env.example${NC}"
    echo -e "${YELLOW}⚠️  Please review and update .env with your settings before deploying!${NC}"
else
    if grep -q $'\r' .env; then
        tmp_env=$(mktemp)
        tr -d '\r' < .env > "$tmp_env"
        mv "$tmp_env" .env
        echo -e "${GREEN}✅ Normalized .env line endings for Bash compatibility${NC}"
    fi
    echo -e "${GREEN}✅ .env already exists${NC}"
fi

# ─── Directory Structure ─────────────────────────────────
echo -e "\n${YELLOW}[3/7] Creating required directories...${NC}"

DIRS=(
    "nginx/conf.d"
    "nginx/certs"
    "nginx/htpasswd"
    "jenkins/init.groovy.d"
    "jenkins/jobs"
    "logs"
)

for dir in "${DIRS[@]}"; do
    mkdir -p "$dir"
    echo -e "   📁 Created: ${dir}"
done

# ─── System Parameter Tuning for Elasticsearch ───────────
echo -e "\n${YELLOW}[4/7] Configuring system parameters...${NC}"

if [ "$(uname)" == "Linux" ]; then
    CURRENT_VM_MAX=$(cat /proc/sys/vm/max_map_count 2>/dev/null || echo 0)
    if [ "$CURRENT_VM_MAX" -lt 262144 ]; then
        echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
        sudo sysctl -w vm.max_map_count=262144
        echo -e "${GREEN}✅ Set vm.max_map_count=262144 (required for Elasticsearch)${NC}"
    else
        echo -e "${GREEN}✅ vm.max_map_count already sufficient: ${CURRENT_VM_MAX}${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Non-Linux system: vm.max_map_count must be set manually for Elasticsearch${NC}"
fi

# ─── Nginx htpasswd ──────────────────────────────────────
echo -e "\n${YELLOW}[5/7] Setting up Nginx basic auth...${NC}"

if [ ! -f nginx/htpasswd/.htpasswd ]; then
    # Generate htpasswd for prometheus and alertmanager (internal UIs)
    if command -v htpasswd &>/dev/null; then
        htpasswd -cb nginx/htpasswd/.htpasswd admin "$(grep GRAFANA_ADMIN_PASSWORD .env | cut -d= -f2)"
    else
        # Fallback: create manually with openssl
        HASHED=$(openssl passwd -apr1 "Admin@Secure123")
        echo "admin:${HASHED}" > nginx/htpasswd/.htpasswd
    fi
    echo -e "${GREEN}✅ Created nginx/.htpasswd${NC}"
else
    echo -e "${GREEN}✅ nginx/.htpasswd already exists${NC}"
fi

# ─── Self-Signed TLS Certificate ────────────────────────
echo -e "\n${YELLOW}[6/7] Generating self-signed TLS certificate...${NC}"

if [ ! -f nginx/certs/server.crt ]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout nginx/certs/server.key \
        -out nginx/certs/server.crt \
        -subj "/C=US/ST=State/L=City/O=Monitoring/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        2>/dev/null
    chmod 600 nginx/certs/server.key
    echo -e "${GREEN}✅ Generated self-signed TLS certificate in nginx/certs/${NC}"
else
    echo -e "${GREEN}✅ TLS certificates already exist${NC}"
fi

# ─── Docker Network Check ────────────────────────────────
echo -e "\n${YELLOW}[7/7] Verifying Docker daemon access...${NC}"

if docker info &>/dev/null; then
    echo -e "${GREEN}✅ Docker daemon is accessible${NC}"
    docker info --format 'Containers: {{.Containers}} | Running: {{.ContainersRunning}} | Paused: {{.ContainersPaused}}'
else
    echo -e "${RED}❌ Cannot connect to Docker daemon. Is Docker running?${NC}"
    exit 1
fi

# ─── Summary ─────────────────────────────────────────────
echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}  Setup complete!                               ${NC}"
echo -e "${GREEN}================================================${NC}"
echo -e ""
echo -e "Next steps:"
echo -e "  1. ${YELLOW}Review and update .env with your configuration${NC}"
echo -e "  2. ${YELLOW}Run: ${GREEN}bash scripts/deploy.sh${NC}"
echo -e "  3. ${YELLOW}Access services:${NC}"
echo -e "     • Grafana:      http://localhost:3000  (admin / Admin@Secure123)"
echo -e "     • Kibana:       http://localhost:5601"
echo -e "     • Prometheus:   http://localhost:9090"
echo -e "     • Alertmanager: http://localhost:9093"
echo -e "     • Kafka UI:     http://localhost:8090"
echo -e "     • Jenkins:      http://localhost:8081"
echo -e ""

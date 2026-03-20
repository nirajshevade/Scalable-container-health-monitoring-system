# ============================================================
# Makefile — Container Health Monitoring System
# Usage: make <target>
# ============================================================

.PHONY: help setup deploy down restart logs ps healthcheck \
        test test-unit test-coverage lint format \
        build push clean topics

COMPOSE      := docker compose
SERVICE      := health-monitor
SHELL        := /bin/bash

# Default target
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Setup & Deploy ──────────────────────────────────────────

setup: ## Run first-time setup wizard
	@bash scripts/setup.sh

deploy: ## Deploy the full stack (optionally: make deploy REPLICAS=3)
	@bash scripts/deploy.sh $(REPLICAS)

down: ## Stop and remove all containers
	$(COMPOSE) down

restart: ## Restart the full stack
	$(COMPOSE) restart

restart-monitor: ## Restart only the health-monitor service
	$(COMPOSE) restart $(SERVICE)

# ─── Observability ───────────────────────────────────────────

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Tail logs for all services (Ctrl+C to stop)
	$(COMPOSE) logs -f

logs-monitor: ## Tail health-monitor logs
	$(COMPOSE) logs -f $(SERVICE)

logs-prometheus: ## Tail Prometheus logs
	$(COMPOSE) logs -f prometheus

logs-kafka: ## Tail Kafka logs
	$(COMPOSE) logs -f kafka

healthcheck: ## Run full system health verification
	@bash scripts/healthcheck.sh

# ─── Build & Push ────────────────────────────────────────────

build: ## Build the health-monitor Docker image
	$(COMPOSE) build --no-cache $(SERVICE)

build-fast: ## Build with cache
	$(COMPOSE) build $(SERVICE)

push: ## Push health-monitor image to registry
	$(COMPOSE) push $(SERVICE)

# ─── Kafka ───────────────────────────────────────────────────

topics: ## Create Kafka topics (run after Kafka is up)
	$(COMPOSE) up --no-deps kafka-init

topics-list: ## List all Kafka topics
	$(COMPOSE) exec kafka kafka-topics \
	  --list --bootstrap-server localhost:9092

topics-describe: ## Describe all Kafka topics
	$(COMPOSE) exec kafka kafka-topics \
	  --describe --bootstrap-server localhost:9092

# ─── Testing ─────────────────────────────────────────────────

test: ## Run all unit tests
	cd health-monitor && python -m pytest tests/ -v

test-unit: ## Run tests marked as unit only
	cd health-monitor && python -m pytest tests/ -v -m unit

test-coverage: ## Run tests with coverage report
	cd health-monitor && python -m pytest tests/ \
	  --cov=src --cov-report=term-missing --cov-report=html:htmlcov

test-watch: ## Re-run tests on file changes (requires pytest-watch)
	cd health-monitor && ptw tests/ src/

# ─── Code Quality ────────────────────────────────────────────

lint: ## Run flake8 linter
	cd health-monitor && python -m flake8 src/ tests/

format: ## Auto-format with black
	cd health-monitor && python -m black src/ tests/

format-check: ## Check formatting without applying changes
	cd health-monitor && python -m black --check src/ tests/

typecheck: ## Run mypy type checker
	cd health-monitor && python -m mypy src/

security-scan: ## Run bandit security scan
	cd health-monitor && python -m bandit -r src/ -ll

# ─── Cleanup ─────────────────────────────────────────────────

clean: ## Remove containers, orphans, and dangling images
	$(COMPOSE) down --remove-orphans
	docker image prune -f

clean-volumes: ## Remove all data volumes (DESTRUCTIVE)
	@echo "WARNING: This will erase all Prometheus, Grafana, Elasticsearch and Kafka data."
	@read -r -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	$(COMPOSE) down -v --remove-orphans
	docker volume prune -f

clean-all: clean clean-volumes ## Full clean including volumes (DESTRUCTIVE)

# ─── Elasticsearch ───────────────────────────────────────────

es-health: ## Show Elasticsearch cluster health
	@curl -s http://localhost:9200/_cluster/health | python3 -m json.tool

es-indices: ## List Elasticsearch indices
	@curl -s http://localhost:9200/_cat/indices?v

# ─── Scale ───────────────────────────────────────────────────

scale: ## Scale health-monitor replicas (make scale N=3)
	$(COMPOSE) up -d --scale $(SERVICE)=$(N) $(SERVICE)

# Subscription LLM Gateway - development and deployment tasks.
#
# OpenWebUI is optional. It lives in the Compose "webui" profile, so the plain
# Docker targets deploy the gateway alone. Ask for the UI in one of three ways:
#
#   make up-webui          start the gateway together with OpenWebUI
#   make up WEBUI=1        the same choice spelled as a variable
#   COMPOSE_PROFILES=webui in .env, to make the choice permanent
#
# Targets that tear down or inspect the stack (down, ps, logs, purge) always
# include the profile, so they still find OpenWebUI containers when the current
# command did not ask for the UI.

SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV ?= .venv
COMPOSE ?= docker compose
CONFIG ?= config.yaml
PORT ?= 11435
BASE_URL ?= http://127.0.0.1:$(PORT)
API_KEY ?= $(or $(GATEWAY_API_KEY),local)

# Host UID for the container user, so mounted client state stays writable.
GATEWAY_UID ?= $(shell id -u)
export GATEWAY_UID

# Prefer uv with the checked-in lock file, fall back to the local virtualenv.
UV := $(shell command -v uv 2>/dev/null)
ifeq ($(UV),)
RUN :=
BIN := $(VENV)/bin/
else
RUN := uv run
BIN :=
endif

# Use ./config.yaml automatically once it exists, locally and in the container.
CONFIG_ARG := $(if $(wildcard $(CONFIG)),--config $(CONFIG),)
GATEWAY_CONFIG_FILE ?= $(if $(wildcard $(CONFIG)),./$(CONFIG),./config.example.yaml)
export GATEWAY_CONFIG_FILE

WEBUI ?= 0
ifeq ($(filter 1 true yes on,$(WEBUI)),)
PROFILE :=
else
PROFILE := --profile webui
endif
ALL_PROFILES := --profile webui

.PHONY: help install dev lock precommit test lint format fix typecheck check coverage \
        serve status doctor config env dist clean docker-build up up-webui down restart \
        logs ps shell docker-status docker-doctor smoke purge

##@ General

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make <target> [WEBUI=1]\n"} \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } \
		/^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }' \
		$(MAKEFILE_LIST)
	@echo

##@ Setup

install: ## Install the gateway for normal use
ifeq ($(UV),)
	python3 -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/python -m pip install -e .
else
	uv sync
endif

dev: ## Install the gateway with development extras
ifeq ($(UV),)
	python3 -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/python -m pip install -e '.[dev]'
else
	uv sync --all-extras
endif

lock: ## Refresh uv.lock
	uv lock

precommit: ## Install the pre-commit hooks
	$(RUN) $(BIN)pre-commit install || \
		echo "pre-commit is not installed; run: pipx install pre-commit"

config: ## Create config.yaml from the example
	@if [ -e $(CONFIG) ]; then echo "$(CONFIG) already exists; leaving it alone."; \
	else cp config.example.yaml $(CONFIG) && echo "Created $(CONFIG)."; fi

env: ## Create .env for Docker from the example
	@if [ -e .env ]; then echo ".env already exists; leaving it alone."; \
	else cp .env.docker.example .env && echo "Created .env."; fi

##@ Checks

test: ## Run the test suite
	$(RUN) $(BIN)pytest

lint: ## Check style and formatting with ruff
	$(RUN) $(BIN)ruff check .
	$(RUN) $(BIN)ruff format --check .

format: ## Format the code with ruff
	$(RUN) $(BIN)ruff format .

fix: ## Apply ruff autofixes and formatting
	$(RUN) $(BIN)ruff check --fix .
	$(RUN) $(BIN)ruff format .

typecheck: ## Type-check with mypy
	$(RUN) $(BIN)mypy

coverage: ## Run the test suite with a coverage report
	$(RUN) $(BIN)pytest --cov

check: lint typecheck test ## Run lint, typecheck, and tests

##@ Local gateway

serve: ## Run the gateway on this machine
	$(RUN) $(BIN)subscription-gateway serve $(CONFIG_ARG)

status: ## Show provider and model status
	$(RUN) $(BIN)subscription-gateway status $(CONFIG_ARG)

doctor: ## Diagnose the local setup
	$(RUN) $(BIN)subscription-gateway doctor $(CONFIG_ARG)

smoke: ## Curl /health and /v1/models on a running gateway
	curl --fail --silent --show-error $(BASE_URL)/health; echo
	curl --fail --silent --show-error \
		-H 'Authorization: Bearer $(API_KEY)' $(BASE_URL)/v1/models; echo

##@ Docker

docker-build: ## Build the gateway image
	$(COMPOSE) $(PROFILE) build

up: ## Start the gateway (add WEBUI=1 for OpenWebUI)
	$(COMPOSE) $(PROFILE) up --detach --build
	@echo "Gateway API: $(BASE_URL)/v1"
	@if [ -n "$(PROFILE)" ]; then \
		echo "OpenWebUI:   http://$$($(COMPOSE) $(PROFILE) port open-webui 8080)"; \
	fi

up-webui: ## Start the gateway together with OpenWebUI
	@$(MAKE) up WEBUI=1

down: ## Stop the stack, keeping all data volumes
	$(COMPOSE) $(ALL_PROFILES) down

restart: ## Restart the running containers
	$(COMPOSE) $(PROFILE) restart

logs: ## Follow container logs
	$(COMPOSE) $(ALL_PROFILES) logs --follow

ps: ## Show container status
	$(COMPOSE) $(ALL_PROFILES) ps

shell: ## Open a shell in the gateway container
	$(COMPOSE) exec gateway bash

docker-status: ## Run `subscription-gateway status` in the container
	$(COMPOSE) exec gateway subscription-gateway status

docker-doctor: ## Run `subscription-gateway doctor` in the container
	$(COMPOSE) exec gateway subscription-gateway doctor

##@ Cleanup

clean: ## Remove build artifacts and tool caches
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

purge: ## Remove containers AND their data volumes (destructive)
	@if [ "$(CONFIRM)" != "1" ]; then \
		echo "This deletes the gateway session database and all OpenWebUI accounts and chats."; \
		echo "Re-run as: make purge CONFIRM=1"; \
		exit 1; \
	fi
	$(COMPOSE) $(ALL_PROFILES) down --volumes

##@ Packaging

dist: ## Build the wheel and sdist
ifeq ($(UV),)
	$(VENV)/bin/python -m pip install --upgrade build
	$(VENV)/bin/python -m build
else
	uv build
endif

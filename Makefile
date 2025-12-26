# PocketDRS root Makefile
#
# Usage:
#   make dev      # start backend + Flutter app
#   make setup    # install backend + app deps
#
# Notes:
# - Backend must be started from server/ to avoid import collisions with the Flutter app/ folder.
# - Put your local config in .env (ignored by git).

SHELL := /bin/sh

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
APP_DIR := $(ROOT_DIR)/app/pocket_drs
SERVER_DIR := $(ROOT_DIR)/server
VENV_DIR := $(SERVER_DIR)/.venv
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip

# Load environment variables from .env if present.
# The .env format is intentionally Make-compatible: KEY=VALUE with optional # comments.
ifneq (,$(wildcard $(ROOT_DIR)/.env))
include $(ROOT_DIR)/.env
export
endif

# Optional Flutter device id, e.g. "emulator-5554" or "chrome".
FLUTTER_DEVICE ?=

# Flutter Web settings (used when FLUTTER_DEVICE is a web device, e.g. chrome)
FLUTTER_WEB_PORT ?= 5173
FLUTTER_WEB_HOSTNAME ?= localhost

.PHONY: help dev setup setup-app setup-server dev-app dev-server dev-app-only dev-server-only \
	server-test app-test clean

help:
	@printf "%s\n" "Targets:" \
		"  make dev          Start backend + Flutter app" \
		"  make setup        Install dependencies (backend venv + flutter pub get)" \
		"  make dev-server    Start backend only" \
		"  make dev-app       Start Flutter app only" \
		"  make server-test   Run backend tests" \
		"  make clean         Remove generated dev artifacts"

# ----- Setup -----

$(PYTHON):
	@printf "%s\n" "Creating backend virtualenv at $(VENV_DIR)"
	@python3 -m venv "$(VENV_DIR)"
	@"$(PIP)" install -U pip setuptools wheel

setup-server: $(PYTHON)
	@printf "%s\n" "Installing backend dependencies"
	@cd "$(SERVER_DIR)" && "$(PIP)" install -r requirements.txt

setup-app:
	@printf "%s\n" "Installing Flutter dependencies"
	@cd "$(APP_DIR)" && flutter pub get

setup: setup-server setup-app

# ----- Dev runners -----

dev-server: setup-server
	@cd "$(SERVER_DIR)" && "$(PYTHON)" run.py

dev-app: setup-app
	@cd "$(APP_DIR)" && \
		flutter run $(if $(FLUTTER_DEVICE),-d $(FLUTTER_DEVICE),) \
		$(if $(filter chrome edge web-server,$(FLUTTER_DEVICE)),--web-port $(FLUTTER_WEB_PORT) --web-hostname $(FLUTTER_WEB_HOSTNAME),)

# No-setup variants for parallel start.

dev-server-only:
	@PORT=$${POCKET_DRS_PORT:-8000}; \
	if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:$$PORT -sTCP:LISTEN >/dev/null 2>&1; then \
		printf "%s\n" "Backend already listening on port $$PORT; skipping dev server start."; \
		exit 0; \
	fi; \
	cd "$(SERVER_DIR)" && "$(PYTHON)" run.py

dev-app-only:
	@cd "$(APP_DIR)" && \
		flutter run $(if $(FLUTTER_DEVICE),-d $(FLUTTER_DEVICE),) \
		$(if $(filter chrome edge web-server,$(FLUTTER_DEVICE)),--web-port $(FLUTTER_WEB_PORT) --web-hostname $(FLUTTER_WEB_HOSTNAME),)

# Convenience: start backend + Flutter Web on chrome.
.PHONY: dev-web
dev-web:
	@$(MAKE) dev FLUTTER_DEVICE=chrome

# Start both in parallel.
# Ctrl+C should stop both (Make will forward SIGINT to its jobs).

dev: setup
	@printf "%s\n" "Starting PocketDRS dev (backend + Flutter)" \
		"- Backend: http://$${POCKET_DRS_HOST:-0.0.0.0}:$${POCKET_DRS_PORT:-8000}" \
		"- Flutter: interactive device selection unless FLUTTER_DEVICE is set"
	@$(MAKE) -j2 dev-server-only dev-app-only

# ----- Tests / cleanup -----

server-test: setup-server
	@cd "$(SERVER_DIR)" && "$(PYTHON)" -m pytest -q

app-test: setup-app
	@cd "$(APP_DIR)" && flutter test

clean:
	@rm -rf "$(SERVER_DIR)/.venv" \
		"$(ROOT_DIR)/data/jobs" \
		"$(APP_DIR)/build" \
		"$(APP_DIR)/.dart_tool"
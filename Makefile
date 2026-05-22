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
POCKET_DRS_PORT ?= 8000
DETECT_HOST_IP_SCRIPT := $(ROOT_DIR)/scripts/detect_host_ip.py
DEV_HOST_IP := $(strip $(shell python3 "$(DETECT_HOST_IP_SCRIPT)" 2>/dev/null || python "$(DETECT_HOST_IP_SCRIPT)" 2>/dev/null || echo localhost))

POCKET_DRS_FLUTTER_HOST ?= $(DEV_HOST_IP)
FLUTTER_SERVER_URL := http://$(POCKET_DRS_FLUTTER_HOST):$(POCKET_DRS_PORT)
FLUTTER_DART_DEFINES := \
	--dart-define=POCKET_DRS_SERVER_URL=$(FLUTTER_SERVER_URL) \
	--dart-define=POCKET_DRS_LOG_DIR=$(ROOT_DIR)/logs/flutter

# Load environment variables from .env if present.
# The .env format is intentionally Make-compatible: KEY=VALUE with optional # comments.
ifneq (,$(wildcard $(ROOT_DIR)/.env))
include $(ROOT_DIR)/.env
export
endif

# Optional Flutter device id, e.g. "emulator-5554" or "chrome".
# Leave empty to auto-detect the first connected phone over adb.
FLUTTER_DEVICE ?=

# adb binary + optional wireless address (host:port from "Wireless debugging").
# If ADB_ADDR is set (here or in .env), "make dev" reconnects to it first so a
# wirelessly-paired phone is picked up without a USB cable.
ADB ?= adb
ADB_ADDR ?=

# Flutter Web settings (used when FLUTTER_DEVICE is a web device, e.g. chrome)
FLUTTER_WEB_PORT ?= 5173
FLUTTER_WEB_HOSTNAME ?= localhost

.PHONY: help dev setup setup-app setup-server dev-app dev-server dev-app-only dev-server-only \
	free-port dev-server-fresh phone-connect dev-app-phone \
	server-test app-test clean

help:
	@printf "%s\n" "Targets:" \
		"  make dev          Free port, start backend, build+install+launch app on phone" \
		"  make setup        Install dependencies (backend venv + flutter pub get)" \
		"  make dev-server    Start backend only" \
		"  make dev-app       Start Flutter app only" \
		"  make free-port     Kill whatever listens on POCKET_DRS_PORT" \
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
	@mkdir -p "$(ROOT_DIR)/logs/flutter"
	@cd "$(APP_DIR)" && \
		flutter run $(if $(FLUTTER_DEVICE),-d $(FLUTTER_DEVICE),) \
		$(if $(filter chrome edge web-server,$(FLUTTER_DEVICE)),--web-port $(FLUTTER_WEB_PORT) --web-hostname $(FLUTTER_WEB_HOSTNAME),) \
		$(FLUTTER_DART_DEFINES)

# No-setup variants for parallel start.

dev-server-only:
	@PORT=$${POCKET_DRS_PORT:-8000}; \
	if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:$$PORT -sTCP:LISTEN >/dev/null 2>&1; then \
		printf "%s\n" "Backend already listening on port $$PORT; skipping dev server start."; \
		exit 0; \
	fi; \
	cd "$(SERVER_DIR)" && "$(PYTHON)" run.py

dev-app-only:
	@mkdir -p "$(ROOT_DIR)/logs/flutter"
	@cd "$(APP_DIR)" && \
		flutter run $(if $(FLUTTER_DEVICE),-d $(FLUTTER_DEVICE),) \
		$(if $(filter chrome edge web-server,$(FLUTTER_DEVICE)),--web-port $(FLUTTER_WEB_PORT) --web-hostname $(FLUTTER_WEB_HOSTNAME),) \
		$(FLUTTER_DART_DEFINES)

# Free the backend port by killing whatever currently listens on it.
# Makes "make dev" deterministic even if a stale server (or another app) squats
# the port.
free-port:
	@PORT=$${POCKET_DRS_PORT:-8000}; \
	if command -v lsof >/dev/null 2>&1; then \
		PIDS=$$(lsof -nP -tiTCP:$$PORT -sTCP:LISTEN 2>/dev/null); \
		if [ -n "$$PIDS" ]; then \
			printf "%s\n" "Freeing port $$PORT (killing: $$PIDS)"; \
			kill $$PIDS 2>/dev/null || true; \
			sleep 1; \
			PIDS=$$(lsof -nP -tiTCP:$$PORT -sTCP:LISTEN 2>/dev/null); \
			if [ -n "$$PIDS" ]; then kill -9 $$PIDS 2>/dev/null || true; fi; \
		fi; \
	fi

# Start the backend after guaranteeing the port is free.
dev-server-fresh: free-port
	@cd "$(SERVER_DIR)" && "$(PYTHON)" run.py

# Reconnect a wirelessly-paired phone if ADB_ADDR is set (no-op otherwise).
phone-connect:
	@if [ -n "$(ADB_ADDR)" ]; then \
		printf "%s\n" "adb connect $(ADB_ADDR)"; \
		$(ADB) connect "$(ADB_ADDR)" >/dev/null 2>&1 || true; \
	fi

# Build + install + launch the latest app on the connected phone.
# Auto-detects the first authorized adb device unless FLUTTER_DEVICE is set.
dev-app-phone: phone-connect
	@mkdir -p "$(ROOT_DIR)/logs/flutter"
	@SERIAL="$(FLUTTER_DEVICE)"; \
	if [ -z "$$SERIAL" ]; then \
		SERIAL=$$($(ADB) devices | awk 'NR>1 && $$2=="device"{print $$1; exit}'); \
	fi; \
	if [ -z "$$SERIAL" ]; then \
		printf "%s\n" "No phone detected over adb." \
			"  - USB: plug in + enable USB debugging, then re-run." \
			"  - Wireless: set ADB_ADDR=<ip:port> in .env (from Wireless debugging)." >&2; \
		exit 1; \
	fi; \
	printf "%s\n" "Installing latest app on $$SERIAL -> $(FLUTTER_SERVER_URL)"; \
	cd "$(APP_DIR)" && \
		flutter run -d "$$SERIAL" \
		$(if $(filter chrome edge web-server,$(FLUTTER_DEVICE)),--web-port $(FLUTTER_WEB_PORT) --web-hostname $(FLUTTER_WEB_HOSTNAME),) \
		$(FLUTTER_DART_DEFINES)

# Convenience: start backend + Flutter Web on chrome.
.PHONY: dev-web
dev-web:
	@$(MAKE) dev FLUTTER_DEVICE=chrome

# Start both in parallel.
# Ctrl+C should stop both (Make will forward SIGINT to its jobs).

dev: setup
	@printf "%s\n" "Starting PocketDRS dev (backend + phone app)" \
		"- Backend:  http://$${POCKET_DRS_HOST:-0.0.0.0}:$${POCKET_DRS_PORT:-8000}" \
		"- App URL:  $(FLUTTER_SERVER_URL) (baked into the build)" \
		"- Phone:    auto-detected via adb (set FLUTTER_DEVICE/ADB_ADDR to override)"
	@$(MAKE) -j2 dev-server-fresh dev-app-phone

# ----- Tests / cleanup -----

server-test: setup-server
	@cd "$(SERVER_DIR)" && "$(PYTHON)" -m pytest -q

app-test: setup-app
	@mkdir -p "$(ROOT_DIR)/logs/flutter"
	@cd "$(APP_DIR)" && \
		POCKET_DRS_FLUTTER_TEST_LOG_PATH="$(ROOT_DIR)/logs/flutter/flutter_test.log" \
		flutter test $(FLUTTER_DART_DEFINES)

clean:
	@rm -rf "$(SERVER_DIR)/.venv" \
		"$(ROOT_DIR)/data/jobs" \
		"$(APP_DIR)/build" \
		"$(APP_DIR)/.dart_tool"
# PocketDRS
#   make setup    server venv + flutter pub get
#   make dev      run the app on a connected phone, against the public server
#   make server   run the server locally on :8000
#   make apk      build the release apks
#   make aab      build the app bundle for Google Play
#   make deploy   copy server/ to the Azure VM, rebuild the container, let running reviews finish,
#                 restart it, wait until it answers,
#                 then publish the website to https://pocket-drs-app.web.app
#   make logs     follow the live server's log
#   make clean    remove the venv and build output

SHELL := /bin/sh
ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
APP_DIR := $(ROOT_DIR)/app/pocket_drs
SERVER_DIR := $(ROOT_DIR)/server
VENV_DIR := $(SERVER_DIR)/.venv
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip

# local overrides, e.g. FLUTTER_DEVICE or SERVER_URL
ifneq (,$(wildcard $(ROOT_DIR)/.env))
include $(ROOT_DIR)/.env
export
endif


DEPLOY_HOST ?= azureuser@20.193.228.228
DEPLOY_KEY ?= $(HOME)/.ssh/pocketdrs_azure
DEPLOY_URL ?= https://pocketdrs-saarathi.centralindia.cloudapp.azure.com
# how long a deploy waits for queued and running reviews to finish before it restarts the server anyway
DRAIN_WAIT_S ?= 600

.PHONY: setup dev server apk aab deploy logs clean

# keyed on pip, not python, so a venv left half made by an interrupted setup is made again
$(PIP):
	python3 -m venv --clear "$(VENV_DIR)"
	"$(PIP)" install -U pip

# the same opencv swap as the Dockerfile, so a local run uses the opencv the server ships with
setup: $(PIP)
	cd "$(SERVER_DIR)" && "$(PIP)" install -r requirements.txt && "$(PIP)" uninstall -y opencv-python \
		&& "$(PIP)" install --no-deps --force-reinstall "$$(grep -i '^opencv-python-headless' requirements.txt)"
	cd "$(APP_DIR)" && flutter pub get

dev:
	cd "$(APP_DIR)" && flutter run $(if $(FLUTTER_DEVICE),-d $(FLUTTER_DEVICE)) \
		$(if $(SERVER_URL),--dart-define=POCKET_DRS_SERVER_URL=$(SERVER_URL))

server: $(PIP)
	cd "$(SERVER_DIR)" && .venv/bin/uvicorn app.main:app --port 8000

# one apk per chip keeps each download under 20 MB; symbols decode crash stack traces
apk:
	cd "$(APP_DIR)" && flutter build apk --release --split-per-abi \
		--target-platform android-arm,android-arm64 --split-debug-info=build/symbols

aab:
	cd "$(APP_DIR)" && flutter build appbundle --release --split-debug-info=build/symbols

# the server is a docker container on an Azure VM; Caddy in front of it does HTTPS.
# docker keeps 3 log files of 10 MB; the server copies its database to /data/backups every night
deploy:
	@rsync -az --delete --exclude __pycache__ --exclude /.venv --exclude /data --exclude /logs --exclude /.env \
		-e "ssh -i $(DEPLOY_KEY)" "$(SERVER_DIR)/" "$(DEPLOY_HOST):/opt/pocket-drs/server/"
	@ssh -i "$(DEPLOY_KEY)" "$(DEPLOY_HOST)" 'sudo docker build -t pocket-drs /opt/pocket-drs/server || exit 1; \
		END=$$(( $$(date +%s) + $(DRAIN_WAIT_S) )); \
		while n=$$(sudo find /opt/pocket-drs-data/jobs -maxdepth 2 -name status.json \
				-exec grep -lE "\"status\": \"(queued|running)\"" {} + 2>/dev/null | wc -l); \
			[ "$$n" -gt 0 ] && [ $$(date +%s) -lt $$END ]; do \
			echo "Waiting for $$n review(s) to finish before restarting"; sleep 5; \
		done; \
		[ "$$n" -gt 0 ] && echo "Restarting with $$n review(s) still going; the app sends those clips again"; \
		{ sudo docker rm -f pocket-drs || true; } && \
		sudo docker run -d --name pocket-drs --restart unless-stopped -p 127.0.0.1:7860:7860 \
			--log-opt max-size=10m --log-opt max-file=3 \
			-v /opt/pocket-drs-data:/data -e ADMIN_EMAILS=kafleniraj@gmail.com pocket-drs'
	@printf "%s\n" "Waiting for $(DEPLOY_URL)/healthz"
	@END=$$(( $$(date +%s) + 120 )); \
	while [ $$(date +%s) -lt $$END ]; do \
		[ "$$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$(DEPLOY_URL)/healthz")" = 200 ] && { echo "Deployed, the server is up"; exit 0; }; \
		sleep 2; \
	done; \
	echo "The server did not answer on /healthz within 2 minutes. Check make logs"; exit 1
	cd "$(ROOT_DIR)" && firebase deploy --only hosting --project pocket-drs-app

logs:
	ssh -i "$(DEPLOY_KEY)" "$(DEPLOY_HOST)" 'sudo docker logs -f --tail 200 pocket-drs'

clean:
	rm -rf "$(VENV_DIR)" "$(ROOT_DIR)/data/jobs" "$(APP_DIR)/build" "$(APP_DIR)/.dart_tool"

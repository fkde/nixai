SHELL := /bin/bash

PYTHON ?= python3
PIP ?= pip
HOST ?= 127.0.0.1
PORT ?= 8765

.PHONY: help install install-desktop install-editable install-editable-desktop serve desktop desktop-check check check-python check-js diff-check build build-cli build-linux-binary build-macos-app build-windows-binary verify-macos-app install-macos-app clean

help:
	@printf "NixAI build commands\n\n"
	@printf "  make install                  Install base Python dependencies\n"
	@printf "  make install-desktop          Install desktop dependencies\n"
	@printf "  make install-editable         Install package editable\n"
	@printf "  make install-editable-desktop Install package editable with desktop extras\n"
	@printf "  make serve                    Start web UI on HOST/PORT (default 127.0.0.1:8765)\n"
	@printf "  make desktop                  Start native desktop mode\n"
	@printf "  make desktop-check            Check desktop dependencies\n"
	@printf "  make check                    Run Python, JS, and diff checks\n"
	@printf "  make build                    Build CLI binary and macOS app bundle\n"
	@printf "  make build-cli                Build dist/nixai with PyInstaller\n"
	@printf "  make build-linux-binary       Build dist/nixai on Linux\n"
	@printf "  make build-macos-app          Build dist/NixAI.app\n"
	@printf "  make build-windows-binary     Build dist/nixai.exe on Windows PowerShell\n"
	@printf "  make verify-macos-app         Verify dist/NixAI.app code signature\n"
	@printf "  make install-macos-app        Copy dist/NixAI.app to /Applications\n"
	@printf "  make clean                    Remove build artifacts\n"

install:
	$(PIP) install -r requirements.txt

install-desktop:
	$(PIP) install -r requirements-desktop.txt

install-editable:
	$(PIP) install -e .

install-editable-desktop:
	$(PIP) install -e ".[desktop]"

serve:
	$(PYTHON) -m app.cli serve --host $(HOST) --port $(PORT)

desktop:
	$(PYTHON) -m app.cli desktop

desktop-check:
	$(PYTHON) -m app.cli desktop --check

check: check-python check-js diff-check

check-python:
	PYTHONPYCACHEPREFIX=/private/tmp/nixai-pycache $(PYTHON) -m compileall app

check-js:
	node --check app/static/app.js

diff-check:
	git diff --check

build: build-cli build-macos-app verify-macos-app

build-cli:
	$(PYTHON) -m PyInstaller --clean -y nixai.spec

build-linux-binary:
	./scripts/build_linux_binary.sh

build-macos-app:
	./scripts/build_macos_app.sh

build-windows-binary:
	powershell -ExecutionPolicy Bypass -NoProfile -File scripts/build_windows_binary.ps1

verify-macos-app:
	codesign --verify --deep --strict dist/NixAI.app

install-macos-app:
	./scripts/install_macos_app.sh

clean:
	rm -rf build dist

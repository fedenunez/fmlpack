# Updated Makefile with virtual environment support

VENV_DIR := .venv
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip
ACTIVATE := . $(VENV_DIR)/bin/activate

.PHONY: init build upload install test test-all testpackage


init:
	python3 -m venv $(VENV_DIR)
	$(ACTIVATE) && $(PIP) install --upgrade pip

build: init
	$(ACTIVATE) && $(PIP) install build
	$(PYTHON) -m build

test: test-all

test-all: init
	$(ACTIVATE) && pytest -v -s ./tests/*.py


testpackage: build
	$(ACTIVATE) && $(PYTHON) -m pip install dist/*-*.tar.gz

upload: testpackage
	$(ACTIVATE) && $(PIP) install twine
	$(ACTIVATE) && python3 -m twine upload dist/*-*
	rm -rf dist

install: init
	$(ACTIVATE) && $(PIP) install --force-reinstall dist/*-*.tar.gz

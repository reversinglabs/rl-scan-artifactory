# Makefile tab=tab,ts=4
# ==========================================

SHELL := /bin/bash
export SHELL

# the lowest installed python3.NN that is at least 3.11 (requires-python); tested on 3.11-3.14
MIN_PYTHON_VERSION := $(shell basename $$( ls /usr/bin/python3.[0-9][0-9] | sort -V | awk -F. '$$NF >= 11 {print $$0; exit}' ) )
export MIN_PYTHON_VERSION

VENV := vtmp
export VENV

COMMON_VENV := rm -rf $(VENV); \
	$(MIN_PYTHON_VERSION) -m venv $(VENV); \
	source ./$(VENV)/bin/activate;

PIP_INSTALL := pip3 -q \
	--require-virtualenv \
	--disable-pip-version-check \
	--no-color install --no-cache-dir

VENV_PIP_INSTALL := $(COMMON_VENV) $(PIP_INSTALL)

# ==========================================
# Code formatting and checks
PY_FILES := *.py \
		rl_scan_artifactory/*.py \
		rl_scan_artifactory/*/*.py \
		tools/*.py \
		tests/*.py \
		livetest/*.py

MYPY_INSTALL := -r requirements.txt \
	types-requests

# What is not ours to correct: the virtualenv, the drawing, the captured output of
# past runs, and patch files. The captured output holds the messages as they were
# spelled at the time and the names of whatever was scanned; a patch file holds
# the old spelling on its '-' lines, so correcting it would break the patch.
CODESPELL_SKIP := --skip="./$(VENV),./.git,./keep,*.log,*.1,*.2,*.patch,*.diff,./.mypy_cache,./.ruff_cache,./doc/*.svg,./livetest/work"

.PHONEY: all clean prep test cleanupVenv dead-code spell

# ==========================================

all: clean prep unit-test dead-code spell build # test

clean: cleanupVenv
	rm -f *.1 *.2 *.log *.tmp  1 2
	rm -rf tmp $(DOWNLOAD_PATH)
	rm -rf download_temp tmp2
	rm -rf .mypy_cache .pytest_cache dist .ruff_cache .mypy_cache
	-@find . -type d -name __pycache__ | xargs rm -fr

# cleanup the virtual env
cleanupVenv:
	rm -rf $(VENV)
	rm -rf venv-artifactory2rlportal

# ======================================
# prep the code with format, lint typing

prep: mypy format verify
	mkdir -p tmp $(DOWNLOAD_PATH)

format:
	$(COMMON_VENV) \
		ruff format $(PY_FILES)

verify:
	$(COMMON_VENV) \
		ruff check --fix $(PY_FILES)

mypy:
	$(VENV_PIP_INSTALL) mypy pytest $(MYPY_INSTALL); \
		mypy \
			--strict \
			--no-incremental \
			$(PY_FILES)

# ======================================

dead-code:
	$(COMMON_VENV) \
		python3 nocheck/find_dead_code.py --strict

# A misspelling in a log line or a --help text is what a user actually reads
spell:
	$(VENV_PIP_INSTALL) codespell; \
		codespell $(CODESPELL_SKIP)

unit-test:
	$(VENV_PIP_INSTALL) pytest $(MYPY_INSTALL); \
		python3 -m pytest

test:
	make -f Makefile.test test

build:
	make -f Makefile.testpypi build

# ======================================
testpypi:
	make -f Makefile.testpypi

clean_both:
	make -f Makefile.clean_both clean_both

full_test: clean_both all testpypi

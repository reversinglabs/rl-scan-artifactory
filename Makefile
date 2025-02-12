# Makefile tab=tab,ts=4
# ==========================================

SHELL := /bin/bash
export SHELL

VENV := ./vtmp/
export VENV

# tested on 3.10-3.14
MIN_PYTHON_VERSION := $(shell basename $$( ls /usr/bin/python3.[0-9][0-9] | awk '{print $0; exit}' ) )
export MIN_PYTHON_VERSION

PIP_INSTALL := pip3 -q \
	--require-virtualenv \
	--disable-pip-version-check \
	--no-color install --no-cache-dir

# ==========================================
# Code formatting and checks
PY_FILES := \
		*.py \
		rl_scan_artifactory/*.py \
		rl_scan_artifactory/*/*.py

LINE_LENGTH := 120
PL_LINTERS := eradicate,mccabe,pycodestyle,pyflakes,pylint

# C0114 Missing module docstring [pylint]
# C0115 Missing class docstring [pylint]
# C0116 Missing function or method docstring [pylint]
# E203 whitespace before ':' [pycodestyle]
#
# W0105 String statement has no effect
# C901 : is to complex

PL_IGNORE := C0114,C0115,C0116,E203

MYPY_INSTALL := \
	types-requests \
	types-python-dateutil \
	spectra-assure-sdk

COMMON_VENV := rm -rf $(VENV); \
	$(MIN_PYTHON_VERSION) -m venv $(VENV); \
	source ./$(VENV)/bin/activate;

.PHONEY: clean prep

# ==========================================

all: clean prep test

clean: cleanupVenv
	rm -f *.1 *.2 *.log *.tmp  1 2
	rm -rf tmp $(DOWNLOAD_PATH)
	rm -rf download_temp tmp2
	rm -rf .mypy_cache

# cleanup the virtual env
cleanupVenv:
	rm -rf $(VENV)
	rm -rf venv-artifactory2rlportal

# ======================================
# prep the code with format, lint typing

prep: black pylama mypy verify_vertical_def
	mkdir -p tmp $(DOWNLOAD_PATH)
	ls -l

black:
	$(COMMON_VENV) \
	$(PIP_INSTALL) black; \
	black \
		--line-length $(LINE_LENGTH) \
		$(PY_FILES)

pylama:
	$(COMMON_VENV) \
	$(PIP_INSTALL) setuptools pylama; \
	pylama \
		--max-line-length $(LINE_LENGTH) \
		--linters "${PL_LINTERS}" \
		--ignore "${PL_IGNORE}" \
		$(PY_FILES)

mypy:
	$(COMMON_VENV) \
	$(PIP_INSTALL) mypy $(MYPY_INSTALL); \
	mypy \
		--strict \
		--no-incremental \
		$(PY_FILES)

# verify we use vertical defs def xxx(self,) -> ...:
# that get formatted vertical by black
verify_vertical_def:
	grep '(self)' $(PY_FILES) || exit 0
	grep '(self,' $(PY_FILES) || exit 0

full_test: clean_both all testpypi

test:
	make -f Makefile.test test

build:
	make -f Makefile.testpypi build

testpypi:
	make -f Makefile.testpypi

clean_both:
	make -f Makefile.clean_both clean_both

# Development Makefile for gen_dsp Python package

.PHONY: all install install-dev test test-cov clean dist help venv \
       example-pd example-max example-chuck example-au examples

VENV := .venv
UV := uv
PYTEST := $(UV) run pytest
GEN_DSP := $(UV) run gen-dsp

# Example project settings (override with: make example-chuck FIXTURE=RamplePlayer BUFFERS="--buffers sample")
FIXTURE ?= gigaverb
NAME ?= $(FIXTURE)
BUFFERS ?=
EXAMPLES_DIR := build/examples

# Default target
all: install-dev test

# Create virtual environment with uv
venv:
	$(UV) venv

# Install package in development mode
install:
	$(UV) pip install -e .

# Install with development dependencies
install-dev:
	$(UV) pip install -e ".[dev]"

# Run tests
test:
	$(PYTEST) tests/ -v

# Run a single test file: make test-file F=tests/test_chuck.py
test-file:
	$(PYTEST) $(F) -v

# Run tests with coverage
test-cov:
	$(PYTEST) tests/ -v --cov=src/gen_dsp --cov-report=term-missing --cov-report=html

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf src/*.egg-info/
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Generate and build a PureData external from a test fixture
example-pd:
	rm -rf $(EXAMPLES_DIR)/$(NAME)_pd
	$(GEN_DSP) init tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p pd -o $(EXAMPLES_DIR)/$(NAME)_pd $(BUFFERS)
	$(MAKE) -C $(EXAMPLES_DIR)/$(NAME)_pd all

# Generate and build a Max/MSP external from a test fixture
example-max:
	rm -rf $(EXAMPLES_DIR)/$(NAME)_max
	$(GEN_DSP) init tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p max -o $(EXAMPLES_DIR)/$(NAME)_max $(BUFFERS)
	$(GEN_DSP) build $(EXAMPLES_DIR)/$(NAME)_max -p max

# Generate and build a ChucK chugin from a test fixture
example-chuck:
	rm -rf $(EXAMPLES_DIR)/$(NAME)_chuck
	$(GEN_DSP) init tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p chuck -o $(EXAMPLES_DIR)/$(NAME)_chuck $(BUFFERS)
	$(MAKE) -C $(EXAMPLES_DIR)/$(NAME)_chuck mac

# Generate and build an AudioUnit plugin from a test fixture (macOS only)
example-au:
	rm -rf $(EXAMPLES_DIR)/$(NAME)_au
	$(GEN_DSP) init tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p au -o $(EXAMPLES_DIR)/$(NAME)_au $(BUFFERS)
	cd $(EXAMPLES_DIR)/$(NAME)_au/build && cmake .. && cmake --build .

# Build all example plugins
examples: example-pd example-max example-chuck example-au

# Build distribution
dist: clean
	$(UV) pip install build
	$(UV) run python -m build

# Help
help:
	@echo "Available targets:"
	@echo "  all           - Install dev dependencies and run tests (default)"
	@echo "  venv          - Create virtual environment with uv"
	@echo "  install       - Install package in development mode"
	@echo "  install-dev   - Install with development dependencies"
	@echo "  test          - Run tests with pytest"
	@echo "  test-file     - Run a single test file (F=tests/test_foo.py)"
	@echo "  test-cov      - Run tests with coverage report"
	@echo "  example-pd    - Generate and build a PureData external"
	@echo "  example-max   - Generate and build a Max/MSP external"
	@echo "  example-chuck - Generate and build a ChucK chugin"
	@echo "  example-au    - Generate and build an AudioUnit plugin (macOS only)"
	@echo "  examples      - Build all example plugins"
	@echo "  clean         - Remove build artifacts"
	@echo "  dist          - Build distribution packages"
	@echo "  help          - Show this help message"
	@echo ""
	@echo "Example targets accept: FIXTURE=<name> NAME=<name> BUFFERS='--buffers buf1 buf2'"
	@echo "  Fixtures: gigaverb (default), RamplePlayer, spectraldelayfb"
	@echo "  e.g.: make example-chuck FIXTURE=RamplePlayer BUFFERS='--buffers sample'"

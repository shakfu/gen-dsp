# Development Makefile for gen_dsp Python package

.PHONY: all install install-dev test test-cov clean dist publish-test publish \
       help venv example-pd example-max example-chuck example-au example-clap \
       example-vst3 example-lv2 example-sc examples lint format typecheck qa

VENV := .venv
UV := uv
PYTEST := $(UV) run pytest
GEN_DSP := $(UV) run gen-dsp

# Example project settings (override with: make example-chuck FIXTURE=RamplePlayer BUFFERS="--buffers sample")
FIXTURE ?= gigaverb
NAME ?= $(FIXTURE)
BUFFERS ?=
EXAMPLES_DIR := build/examples
export GEN_DSP_CACHE_DIR := $(CURDIR)/build/.fetchcontent_cache

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

lint:
	$(UV) run ruff check --fix src/ tests/

format:
	$(UV) run ruff format src/ tests/

typecheck:
	$(UV) run mypy --strict src/

qa: test lint typecheck format 

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

# Generate and build a CLAP plugin from a test fixture
example-clap:
	rm -rf $(EXAMPLES_DIR)/$(NAME)_clap
	$(GEN_DSP) init tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p clap -o $(EXAMPLES_DIR)/$(NAME)_clap $(BUFFERS)
	cd $(EXAMPLES_DIR)/$(NAME)_clap/build && cmake .. && cmake --build .

# Generate and build a VST3 plugin from a test fixture
example-vst3:
	rm -rf $(EXAMPLES_DIR)/$(NAME)_vst3
	$(GEN_DSP) init tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p vst3 -o $(EXAMPLES_DIR)/$(NAME)_vst3 $(BUFFERS)
	cd $(EXAMPLES_DIR)/$(NAME)_vst3/build && cmake .. && cmake --build .

# Generate and build an LV2 plugin from a test fixture
example-lv2:
	rm -rf $(EXAMPLES_DIR)/$(NAME)_lv2
	$(GEN_DSP) init tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p lv2 -o $(EXAMPLES_DIR)/$(NAME)_lv2 $(BUFFERS)
	cd $(EXAMPLES_DIR)/$(NAME)_lv2/build && cmake .. && cmake --build .

# Generate and build a SuperCollider UGen from a test fixture
example-sc:
	rm -rf $(EXAMPLES_DIR)/$(NAME)_sc
	$(GEN_DSP) init tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p sc -o $(EXAMPLES_DIR)/$(NAME)_sc $(BUFFERS)
	cd $(EXAMPLES_DIR)/$(NAME)_sc/build && cmake .. && cmake --build .

# Build all example plugins
examples: example-pd example-max example-chuck example-au example-clap example-vst3 example-lv2 example-sc

# Build distribution
dist: clean
	$(UV) build
	$(UV) run twine check dist/*

# Upload to TestPyPI
publish-test: dist
	$(UV) run twine upload --repository testpypi dist/*

# Upload to PyPI
publish: dist
	$(UV) run twine upload dist/*

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
	@echo "  example-clap  - Generate and build a CLAP plugin"
	@echo "  example-vst3  - Generate and build a VST3 plugin"
	@echo "  example-lv2   - Generate and build an LV2 plugin"
	@echo "  example-sc    - Generate and build a SuperCollider UGen"
	@echo "  examples      - Build all example plugins"
	@echo "  clean         - Remove build artifacts"
	@echo "  dist          - Build distribution packages"
	@echo "  publish-test  - Upload to TestPyPI"
	@echo "  publish       - Upload to PyPI"
	@echo "  help          - Show this help message"
	@echo ""
	@echo "Example targets accept: FIXTURE=<name> NAME=<name> BUFFERS='--buffers buf1 buf2'"
	@echo "  Fixtures: gigaverb (default), RamplePlayer, spectraldelayfb"
	@echo "  e.g.: make example-chuck FIXTURE=RamplePlayer BUFFERS='--buffers sample'"

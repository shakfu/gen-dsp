# Development Makefile for gen_dsp Python package

.PHONY: all install install-dev test test-cov clean dist publish-test publish \
       help venv example-pd example-max example-chuck example-au example-clap \
       example-vst3 example-lv2 example-sc example-vcvrack example-daisy example-circle examples lint format typecheck qa

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

# Shared: clean + init for any platform (usage: $(call example_init,PLATFORM_KEY))
define example_init
	rm -rf $(EXAMPLES_DIR)/$(NAME)_$(1)
	$(GEN_DSP) init tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p $(1) -o $(EXAMPLES_DIR)/$(NAME)_$(1) $(BUFFERS)
endef

# CMake-based examples: au, clap, vst3, lv2, sc
CMAKE_EXAMPLES := example-au example-clap example-vst3 example-lv2 example-sc
$(CMAKE_EXAMPLES): example-%:
	$(call example_init,$*)
	cmake -B $(EXAMPLES_DIR)/$(NAME)_$*/build -S $(EXAMPLES_DIR)/$(NAME)_$* && cmake --build $(EXAMPLES_DIR)/$(NAME)_$*/build

# gen-dsp build examples: max, vcvrack, daisy, circle
GENDSP_EXAMPLES := example-max example-vcvrack example-daisy example-circle
$(GENDSP_EXAMPLES): example-%:
	$(call example_init,$*)
	$(GEN_DSP) build $(EXAMPLES_DIR)/$(NAME)_$* -p $*

# PureData: uses make target 'all'
example-pd:
	$(call example_init,pd)
	$(MAKE) -C $(EXAMPLES_DIR)/$(NAME)_pd all

# ChucK: uses platform-specific make target
CHUCK_TARGET := $(if $(filter Darwin,$(shell uname -s)),mac,linux)
example-chuck:
	$(call example_init,chuck)
	$(MAKE) -C $(EXAMPLES_DIR)/$(NAME)_chuck $(CHUCK_TARGET)

# Platform-portable examples (work on any OS with a C/C++ compiler)
PORTABLE_EXAMPLES := example-pd example-max example-chuck example-clap example-vst3 example-lv2 example-sc example-vcvrack example-daisy example-circle

# macOS-only examples
MACOS_EXAMPLES := example-au

# Build all example plugins appropriate for this platform
ifeq ($(shell uname -s),Darwin)
examples: $(PORTABLE_EXAMPLES) $(MACOS_EXAMPLES)
else
examples: $(PORTABLE_EXAMPLES)
endif

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
	@echo "  example-vcvrack - Generate and build a VCV Rack module (requires RACK_DIR)"
	@echo "  example-daisy - Generate and build a Daisy firmware (requires arm-none-eabi-gcc)"
	@echo "  example-circle - Generate and build a Circle kernel image (requires aarch64-none-elf-gcc)"
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

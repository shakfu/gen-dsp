# Development Makefile for gen_dsp Python package

.PHONY: all install install-dev test test-cov clean dist publish-test publish \
       help venv examples graph-examples lint format typecheck qa

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

# Graph source (override with: make graph-example-clap GRAPH=examples/dsl/fm_synth.gdsp)
GRAPH ?= examples/dsl/stereo_gain.gdsp
GRAPH_NAME = $(basename $(notdir $(GRAPH)))

# ---------------------------------------------------------------------------
# gen~ export examples (generate + build in one step)
# ---------------------------------------------------------------------------

EXAMPLE_PLATFORMS := pd max chuck au clap vst3 lv2 sc vcvrack daisy circle
$(addprefix example-,$(EXAMPLE_PLATFORMS)): example-%:
	rm -rf $(EXAMPLES_DIR)/$(NAME)_$*
	$(GEN_DSP) tests/fixtures/$(FIXTURE)/gen -n $(NAME) -p $* -o $(EXAMPLES_DIR)/$(NAME)_$* $(BUFFERS)

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

# ---------------------------------------------------------------------------
# Graph examples (.gdsp / .json -> platform, generate + build in one step)
# Override source: make graph-example-clap GRAPH=examples/json/fm_synth.json
# ---------------------------------------------------------------------------

GRAPH_PLATFORMS := pd chuck au clap vst3 lv2 sc
$(addprefix graph-example-,$(GRAPH_PLATFORMS)): graph-example-%:
	rm -rf $(EXAMPLES_DIR)/$(GRAPH_NAME)_$*
	$(GEN_DSP) $(GRAPH) -p $* -o $(EXAMPLES_DIR)/$(GRAPH_NAME)_$*

# Web Audio example (standalone generator, uses fm_synth by default)
WEBAUDIO_GRAPH ?= examples/dsl/fm_synth.gdsp
WEBAUDIO_GRAPH_NAME = $(basename $(notdir $(WEBAUDIO_GRAPH)))
graph-example-webaudio:
	rm -rf $(EXAMPLES_DIR)/$(WEBAUDIO_GRAPH_NAME)_webaudio
	$(GEN_DSP) $(WEBAUDIO_GRAPH) -p webaudio -o $(EXAMPLES_DIR)/$(WEBAUDIO_GRAPH_NAME)_webaudio

# Build all graph examples appropriate for this platform
GRAPH_PORTABLE := $(addprefix graph-example-,pd chuck clap vst3 lv2 sc webaudio)
GRAPH_MACOS := graph-example-au
ifeq ($(shell uname -s),Darwin)
graph-examples: $(GRAPH_PORTABLE) $(GRAPH_MACOS)
else
graph-examples: $(GRAPH_PORTABLE)
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
	@echo "  all              - Install dev dependencies and run tests (default)"
	@echo "  venv             - Create virtual environment with uv"
	@echo "  install          - Install package in development mode"
	@echo "  install-dev      - Install with development dependencies"
	@echo "  test             - Run tests with pytest"
	@echo "  test-file        - Run a single test file (F=tests/test_foo.py)"
	@echo "  test-cov         - Run tests with coverage report"
	@echo ""
	@echo "gen~ export examples (FIXTURE=gigaverb|RamplePlayer|spectraldelayfb):"
	@echo "  example-pd       - PureData external"
	@echo "  example-max      - Max/MSP external"
	@echo "  example-chuck    - ChucK chugin"
	@echo "  example-au       - AudioUnit plugin (macOS)"
	@echo "  example-clap     - CLAP plugin"
	@echo "  example-vst3     - VST3 plugin"
	@echo "  example-lv2      - LV2 plugin"
	@echo "  example-sc       - SuperCollider UGen"
	@echo "  example-vcvrack  - VCV Rack module"
	@echo "  example-daisy    - Daisy firmware"
	@echo "  example-circle   - Circle kernel image"
	@echo "  examples         - Build all of the above"
	@echo ""
	@echo "Graph examples (GRAPH=examples/dsl/stereo_gain.gdsp):"
	@echo "  graph-example-pd    - PureData from .gdsp/.json"
	@echo "  graph-example-chuck - ChucK from .gdsp/.json"
	@echo "  graph-example-au    - AudioUnit from .gdsp/.json (macOS)"
	@echo "  graph-example-clap  - CLAP from .gdsp/.json"
	@echo "  graph-example-vst3  - VST3 from .gdsp/.json"
	@echo "  graph-example-lv2   - LV2 from .gdsp/.json"
	@echo "  graph-example-sc    - SuperCollider from .gdsp/.json"
	@echo "  graph-example-webaudio - Web Audio WASM + demo page (default: fm_synth)"
	@echo "  graph-examples      - Build all graph examples"
	@echo ""
	@echo "  clean            - Remove build artifacts"
	@echo "  dist             - Build distribution packages"
	@echo "  publish-test     - Upload to TestPyPI"
	@echo "  publish          - Upload to PyPI"
	@echo "  help             - Show this help message"
	@echo ""
	@echo "Override variables:"
	@echo "  FIXTURE=<name>   - gen~ export fixture (default: gigaverb)"
	@echo "  BUFFERS='--buffers buf1'  - buffer names for export examples"
	@echo "  GRAPH=<path>     - .gdsp or .json file (default: examples/dsl/stereo_gain.gdsp)"
	@echo ""
	@echo "Examples:"
	@echo "  make example-chuck FIXTURE=RamplePlayer BUFFERS='--buffers sample'"
	@echo "  make graph-example-clap GRAPH=examples/json/fm_synth.json"
	@echo "  make graph-example-vst3 GRAPH=examples/dsl/wavetable.gdsp"

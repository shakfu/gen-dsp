# Development Makefile for gen_ext Python package

.PHONY: all install install-dev test test-cov lint clean help venv

# Default target
all: install-dev test

# Create virtual environment with uv
venv:
	uv venv

# Install package in development mode
install:
	uv pip install -e .

# Install with development dependencies
install-dev:
	uv pip install -e ".[dev]"

# Run tests
test:
	pytest tests/ -v

# Run tests with coverage
test-cov:
	pytest tests/ -v --cov=src/gen_ext --cov-report=term-missing --cov-report=html

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

# Build distribution
dist: clean
	uv pip install build
	python -m build

# Help
help:
	@echo "Available targets:"
	@echo "  all         - Install dev dependencies and run tests (default)"
	@echo "  venv        - Create virtual environment with uv"
	@echo "  install     - Install package in development mode"
	@echo "  install-dev - Install with development dependencies"
	@echo "  test        - Run tests with pytest"
	@echo "  test-cov    - Run tests with coverage report"
	@echo "  clean       - Remove build artifacts"
	@echo "  dist        - Build distribution packages"
	@echo "  help        - Show this help message"
